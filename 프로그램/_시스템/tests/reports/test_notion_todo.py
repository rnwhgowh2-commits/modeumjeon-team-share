# -*- coding: utf-8 -*-
"""노션 투두 일일 보고 — 대조·요일 선택·메시지·발송 게이트."""
from __future__ import annotations

import json
from datetime import date

import pytest

from lemouton.reports import notion_todo as nt


# ──────────────────────────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _isolated_snapshot(tmp_path, monkeypatch):
    """상태 파일 전부를 테스트별 임시 경로로 — 라이브 저장분을 절대 건드리지 않는다.

    스냅샷만 격리하면 시각표·이력·캡처가 실제 폴더에 써진다(테스트가 사장님
    발송 기록을 오염시킨다).
    """
    from lemouton.reports import report_history, report_schedule, shot_store

    monkeypatch.setattr(nt, "_SNAPSHOT_PATH", str(tmp_path / "snap.json"))
    monkeypatch.setattr(report_schedule, "_PATH", str(tmp_path / "sched.json"))
    monkeypatch.setattr(report_history, "_PATH", str(tmp_path / "hist.jsonl"))
    monkeypatch.setattr(shot_store, "_PATH", str(tmp_path / "shots"))
    yield


def _todo(tid, text, checked=False, weekday=None, seq=0, order=0,
          last_edited=None):
    return {"id": tid, "text": text, "checked": checked, "weekday": weekday,
            "weekday_seq": seq, "order": order, "last_edited": last_edited}


# ──────────────────────────────────────────────────────────────
# ③ 대조
# ──────────────────────────────────────────────────────────────
def test_diff_분류_5종():
    prev = [
        _todo("a", "택배비 점검"),
        _todo("b", "넥슨캐시 현금화", checked=False),
        _todo("c", "이미 끝난 일", checked=True),
        _todo("d", "지워질 일"),
    ]
    curr = [
        _todo("a", "택배비 점검 (수정됨)"),      # 문구만 바뀜
        _todo("b", "넥슨캐시 현금화", checked=True),  # 완료
        _todo("c", "이미 끝난 일", checked=False),    # 체크 해제
        _todo("e", "새로 생긴 일"),                    # 신규
    ]
    d = nt.diff_todos(prev, curr)

    assert [t["id"] for t in d["added"]] == ["e"]
    assert [t["id"] for t in d["completed"]] == ["b"]
    assert [t["id"] for t in d["reopened"]] == ["c"]
    assert [t["id"] for t in d["removed"]] == ["d"]
    assert d["edited"] == [
        {"id": "a", "before": "택배비 점검", "after": "택배비 점검 (수정됨)",
         "last_edited": None,          # 노션이 준 실제 수정 시각(여기선 가짜라 없음)
         "weekday": None, "weekday_seq": 0}   # 요일 칸으로 걸러내기 위해 같이 싣는다
    ]


def test_diff_문구수정은_삭제_신규로_잡히지_않는다():
    """블록 ID 로 신원을 잡기 때문에 오타 수정이 「삭제1+신규1」이 되면 안 된다."""
    prev = [_todo("x", "택베비 점검")]
    curr = [_todo("x", "택배비 점검")]
    d = nt.diff_todos(prev, curr)
    assert d["added"] == [] and d["removed"] == []
    assert len(d["edited"]) == 1


def test_diff_변화없으면_전부_빈리스트():
    same = [_todo("a", "그대로", checked=True)]
    d = nt.diff_todos(same, list(same))
    assert all(not v for v in d.values())


# ──────────────────────────────────────────────────────────────
# ② 요일 선택
# ──────────────────────────────────────────────────────────────
def test_오늘요일_첫번째_블록만_고른다():
    """같은 요일이 여러 주 쌓여 있어도 최신(seq=0) 것만."""
    todos = [
        _todo("m0", "이번주 월요일 일", weekday="월요일", seq=0),
        _todo("m1", "지난주 월요일 일", weekday="월요일", seq=1),
        _todo("m2", "지지난주 월요일 일", weekday="월요일", seq=2),
        _todo("t0", "화요일 일", weekday="화요일", seq=0),
    ]
    got = nt.todays_todos(todos, when=date(2026, 7, 27))  # 월요일
    assert [t["id"] for t in got] == ["m0"]


def test_요일라벨_매핑():
    assert nt.weekday_label(date(2026, 7, 27)) == "월요일"
    assert nt.weekday_label(date(2026, 7, 30)) == "목요일"
    assert nt.weekday_label(date(2026, 7, 31)) == "금요일"
    assert nt.weekday_label(date(2026, 8, 2)) == "일요일"


# ──────────────────────────────────────────────────────────────
# ① 노션 파싱 — 요일 문맥 전파
# ──────────────────────────────────────────────────────────────
def _blk(bid, btype, text="", checked=None, has_children=False):
    body = {"rich_text": [{"plain_text": text}]} if text else {"rich_text": []}
    if btype == "to_do":
        body["checked"] = bool(checked)
    return {"id": bid, "type": btype, btype: body, "has_children": has_children}


def test_요일라벨_이후_형제와_자손이_그_요일에_속한다(monkeypatch):
    """라벨은 콜아웃의 첫 자식이고 할 일은 뒤따르는 형제 — 문맥이 옆으로 흘러야 한다."""
    tree = {
        "PAGE": [_blk("callout1", "callout", has_children=True),
                 _blk("callout2", "callout", has_children=True)],
        "callout1": [_blk("l1", "paragraph", "월요일"),
                     _blk("t1", "to_do", "월요일 할일", checked=False),
                     _blk("sub", "toggle", "묶음", has_children=True)],
        "sub": [_blk("t2", "to_do", "월요일 하위 할일", checked=True)],
        "callout2": [_blk("l2", "paragraph", "화요일"),
                     _blk("t3", "to_do", "화요일 할일", checked=False)],
    }
    monkeypatch.setattr(nt, "_fetch_children", lambda bid, s: tree.get(bid, []))
    monkeypatch.setattr(nt, "page_id", lambda: "PAGE")
    monkeypatch.setenv("NOTION_TOKEN", "fake")

    todos = nt.fetch_todos()
    by_id = {t["id"]: t for t in todos}
    assert by_id["t1"]["weekday"] == "월요일"
    assert by_id["t2"]["weekday"] == "월요일"   # 자손으로 전파
    assert by_id["t3"]["weekday"] == "화요일"   # 다음 라벨에서 갈아탐
    assert by_id["t2"]["checked"] is True


def test_같은_요일_두번_나오면_순번이_증가한다(monkeypatch):
    tree = {
        "PAGE": [_blk("c1", "callout", has_children=True),
                 _blk("c2", "callout", has_children=True)],
        "c1": [_blk("l1", "paragraph", "월요일"),
               _blk("t1", "to_do", "이번주")],
        "c2": [_blk("l2", "paragraph", "월요일"),
               _blk("t2", "to_do", "지난주")],
    }
    monkeypatch.setattr(nt, "_fetch_children", lambda bid, s: tree.get(bid, []))
    monkeypatch.setattr(nt, "page_id", lambda: "PAGE")
    monkeypatch.setenv("NOTION_TOKEN", "fake")

    by_id = {t["id"]: t for t in nt.fetch_todos()}
    assert by_id["t1"]["weekday_seq"] == 0
    assert by_id["t2"]["weekday_seq"] == 1


def test_토큰_없으면_명확한_에러(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="NOTION_TOKEN"):
        nt.fetch_todos()


# ──────────────────────────────────────────────────────────────
# ④ 메시지
# ──────────────────────────────────────────────────────────────
def _changes(**kw):
    base = {"added": [], "completed": [], "reopened": [], "removed": [], "edited": []}
    base.update(kw)
    return base


def test_사진통은_짧고_남은_일을_말한다():
    today = [_todo("a", "x"), _todo("b", "y", checked=True), _todo("c", "z")]
    msg = nt.build_photo_message(today, when=date(2026, 8, 2), slot="14:00",
                                 changed=3)
    assert msg.splitlines()[0] == "영빈 투두 8/2(일) 14:00"   # 첫 줄 = 카톡 제목
    assert "오늘(일) 남은 일 2건" in msg
    assert "바뀐 것 없음" not in msg


def test_사진통_요일블록_못찾으면_0건이라_하지_않는다():
    """0건이라 하면 「다 끝냈다」로 읽힌다 — 못 찾은 것과 구별해야 한다."""
    msg = nt.build_photo_message([], when=date(2026, 8, 2), changed=0)
    assert "못 찾았습니다" in msg
    assert "남은 일 0건" not in msg


def test_사진통_변경없으면_그렇게_말한다():
    msg = nt.build_photo_message([_todo("a", "x")], when=date(2026, 8, 2),
                                 changed=0)
    assert "바뀐 것 없음" in msg


def test_변경통_표식_4종이_붙는다():
    """사장님 확정(시안 1) — 완료✅ 추가🆕 수정✏️ 삭제🗑."""
    ch = _changes(
        completed=[_todo("c", "쿠팡 가품 소명", last_edited="2026-08-02T02:20:00.000Z")],
        added=[_todo("a", "옥션 재설정", last_edited="2026-08-02T04:47:00.000Z")],
        removed=[_todo("r", "무퀴즈 적립금")],
        edited=[{"before": "대량등록 XX개", "after": "대량등록 120개",
                 "last_edited": "2026-08-02T04:58:00.000Z"}],
    )
    msg = nt.build_change_message(ch, when=date(2026, 8, 2), slot="14:00")
    assert msg.splitlines()[0] == "8/2(일) 14:00 · 변경 4건"
    assert "11:20 ✅ 쿠팡 가품 소명" in msg      # 노션 UTC → 서울 시각
    assert "13:47 🆕 옥션 재설정" in msg
    assert "✏️ 대량등록 XX개 → 대량등록 120개" in msg   # 문구 수정은 전→후 보존
    assert "🗑 무퀴즈 적립금" in msg


def test_변경통_200자_넘지_않고_잘린_건수를_밝힌다():
    """말없이 잘라내면 몇 건이 빠졌는지 알 길이 없다."""
    ch = _changes(added=[_todo(f"a{i}", "아주 긴 할 일 제목 " * 4) for i in range(30)])
    msg = nt.build_change_message(ch, when=date(2026, 8, 2), slot="14:00")
    assert len(msg) <= 200
    assert "변경 30건" in msg          # 총 건수는 제목에 그대로
    assert "외 " in msg and "건" in msg  # 못 담은 건수를 밝힌다


def test_변경통_빈_체크박스는_안_넣는다():
    """노션에 글자 없는 체크박스가 있다 — 표식만 덩그러니 나가면 안 된다."""
    ch = _changes(added=[_todo("a", ""), _todo("b", "   "), _todo("c", "진짜 할일")])
    msg = nt.build_change_message(ch, when=date(2026, 8, 2))
    assert "진짜 할일" in msg
    assert "변경 3건" in msg            # 집계는 있는 그대로
    assert msg.count("🆕") == 1         # 표시는 내용 있는 것만


# ──────────────────────────────────────────────────────────────
# ⑤ 발송 게이트
# ──────────────────────────────────────────────────────────────
def _stub_report(monkeypatch, todos, sent_ok=True, calls=None):
    monkeypatch.setattr(nt, "fetch_todos", lambda **kw: todos)
    import shared.notifier as sn

    def _fake_send(text, **kw):
        if calls is not None:
            calls.append(text)
        return {"ok": sent_ok, "status": 200 if sent_ok else 400,
                "error": None if sent_ok else "boom"}

    monkeypatch.setattr(sn, "send_kakao_memo_detailed", _fake_send)


def test_첫실행은_기준선만_저장하고_발송안함(monkeypatch):
    """어제가 없으면 전 항목이 신규 — 700건을 카톡에 쏟아붓지 않는다."""
    calls: list[str] = []
    _stub_report(monkeypatch, [_todo("a", "할일"), _todo("b", "할일2")], calls=calls)

    res = nt.run_slot_report("09:30", when=date(2026, 7, 31))
    assert res["skipped"] == "baseline_saved"
    assert calls == []
    assert len(nt.load_snapshot()["todos"]) == 2


def test_이미_보낸_회차는_건너뛴다(monkeypatch):
    """배포 재기동으로 틱이 한 번 더 돌아도 카톡이 두 번 가면 안 된다."""
    from lemouton.reports import report_schedule

    calls: list[str] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-07-31")
    report_schedule.mark_sent("09:30", "2026-07-31")
    _stub_report(monkeypatch, [_todo("a", "할일", checked=True)], calls=calls)

    res = nt.run_slot_report("09:30", when=date(2026, 7, 31))
    assert res["skipped"] == "already_sent"
    assert calls == []


def test_둘째날부터_변경분만_두_통으로_발송(monkeypatch):
    calls: list[str] = []
    # 2026-07-31 = 금요일 — 사진 통이 「남은 일」을 세려면 그 요일 칸에 속해야 한다.
    prev = [_todo("a", "할일", weekday="금요일"), _todo("b", "할일2", weekday="금요일")]
    nt.save_snapshot(prev, sent_date="2026-07-30")
    _stub_report(monkeypatch,
                 [_todo("a", "할일", checked=True, weekday="금요일"),
                  _todo("b", "할일2", weekday="금요일")], calls=calls)

    res = nt.run_slot_report("09:30", when=date(2026, 7, 31))
    assert res["sent"] is True
    assert len(calls) == 2                 # 사진 통 + 변경 통
    assert "남은 일" in calls[0]           # ① 사진 통
    assert "변경 1건" in calls[1]          # ② 변경 통
    assert "✅ 할일" in calls[1]           # 완료 표식
    assert nt.load_snapshot()["sent_date"] == "2026-07-31"


def test_변경이_없으면_변경통은_안_보낸다(monkeypatch):
    """읽을 게 없는 통을 보내면 알림만 늘어난다."""
    calls: list[str] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-07-30")
    _stub_report(monkeypatch, [_todo("a", "할일")], calls=calls)   # 변화 없음

    res = nt.run_slot_report("09:30", when=date(2026, 7, 31))
    assert res["sent"] is True
    assert len(calls) == 1                 # 사진 통만
    assert "바뀐 것 없음" in calls[0]


def test_발송실패하면_발송일을_찍지_않는다(monkeypatch):
    """찍어버리면 그 회차는 영영 재시도가 막힌다."""
    from lemouton.reports import report_schedule

    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-07-30")
    _stub_report(monkeypatch, [_todo("a", "할일", checked=True)], sent_ok=False)

    res = nt.run_slot_report("09:30", when=date(2026, 7, 31))
    assert res["sent"] is False
    assert nt.load_snapshot()["sent_date"] == "2026-07-30"           # 그대로
    assert report_schedule.already_sent("09:30", "2026-07-31") is False


def test_dry_run_은_발송도_저장도_안한다(monkeypatch):
    calls: list[str] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-07-30")
    _stub_report(monkeypatch, [_todo("a", "할일", checked=True)], calls=calls)

    res = nt.run_slot_report("09:30", dry_run=True, when=date(2026, 7, 31))
    assert res["dry_run"] is True
    assert calls == []
    assert nt.load_snapshot()["sent_date"] == "2026-07-30"


def test_노션_읽기_실패는_조용히_넘어가지_않는다(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("노션 블록 조회 실패 404: page not found")

    monkeypatch.setattr(nt, "fetch_todos", _boom)
    res = nt.run_slot_report("09:30", when=date(2026, 7, 31))
    assert res["ok"] is False
    assert "404" in res["error"]


def test_손상된_스냅샷이_보고를_영구차단하지_않는다(monkeypatch):
    with open(nt._SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        f.write("{깨진 JSON")
    snap = nt.load_snapshot()
    assert snap["todos"] == []


# ──────────────────────────────────────────────────────────────
# 화면용 캐시 — 요청 안에서 노션을 읽으면 Cloudflare 100초에 걸려 죽는다
# ──────────────────────────────────────────────────────────────
def test_수집전에는_마지막결과가_없다():
    assert nt.load_last_report() is None


def test_마지막결과는_700건을_싣지_않는다():
    """todos 를 그대로 저장하면 파일이 비대해지고 화면 응답도 무거워진다."""
    nt._save_last_report({"ok": True, "photo_message": "m",
                          "todos": [{"id": "a"}] * 700})
    saved = nt.load_last_report()
    assert saved["ok"] is True
    assert "todos" not in saved
    assert saved["collected_at"]


def test_수집은_요청을_막지_않는다(monkeypatch):
    """start_refresh 는 즉시 돌아오고, 결과는 나중에 파일로 떨어진다."""
    import threading as _t

    done = _t.Event()

    def _slow_build():
        done.wait(2)
        return {"ok": True, "photo_message": "늦게 끝난 수집",
                "change_message": "", "changes": {}, "picked": {}}

    monkeypatch.setattr(nt, "build_report", lambda **kw: _slow_build())

    assert nt.start_refresh() is True
    assert nt.is_refreshing() is True          # 요청은 이미 반환된 상태
    assert nt.start_refresh() is False         # 중복 실행 금지
    done.set()
    for _ in range(50):
        if not nt.is_refreshing():
            break
        _t.Event().wait(0.1)
    assert nt.load_last_report()["photo_message"] == "늦게 끝난 수집"




def test_옛_형식_저장본은_안_쓴다(tmp_path, monkeypatch):
    """문구 형식을 바꾸면 바꾸기 전 저장본이 남는다.

    그대로 쓰면 **옛 형식 그대로 카톡이 나간다**(2026-08-02 실측 — 새 두 통 대신
    옛 한 통이 왔다). 없는 셈 치고 다시 읽게 유도하는 편이 정직하다.
    """
    import json as _json

    path = tmp_path / "last.json"
    monkeypatch.setattr(nt, "_SNAPSHOT_PATH", str(tmp_path / "snap.json"))
    path.write_text(_json.dumps(
        {"ok": True, "message": "[영빈 투두 8/2(일)] 신규 719",   # 옛 칸 이름
         "changes": {}, "picked": {}, "collected_at": "2026-08-02T14:58:48"}),
        encoding="utf-8")
    monkeypatch.setattr(nt, "_last_report_path", lambda: str(path))

    assert nt.load_last_report() is None


def test_새_형식_저장본은_그대로_쓴다(tmp_path, monkeypatch):
    import json as _json

    path = tmp_path / "last.json"
    path.write_text(_json.dumps(
        {"ok": True, "photo_message": "영빈 투두 8/2(일)\n남은 일 35건",
         "change_message": "", "changes": {}, "picked": {},
         "format": nt.REPORT_FORMAT_VERSION}), encoding="utf-8")
    monkeypatch.setattr(nt, "_last_report_path", lambda: str(path))

    got = nt.load_last_report()
    assert got and got["photo_message"].startswith("영빈 투두")


def test_오늘_아닌_수정은_날짜로_보인다():
    """시:분만 찍으면 며칠 전 고친 게 오늘 그 시각처럼 읽힌다.

    2026-08-02 실측: 오후 6시인데 20:31·22:13 이 찍혀 미래처럼 보였다.
    """
    ch = _changes(
        completed=[_todo("t", "오늘 한 것", last_edited="2026-08-02T02:20:00.000Z"),
                   _todo("y", "어제 한 것", last_edited="2026-08-01T11:31:00.000Z")])
    msg = nt.build_change_message(ch, when=date(2026, 8, 2))
    assert "11:20 ✅ 오늘 한 것" in msg      # 오늘 → 시:분
    assert "8/1 ✅ 어제 한 것" in msg        # 다른 날 → 날짜


# ──────────────────────────────────────────────────────────────
# 보고 범위 — 사진과 같은 기준(오늘 요일 칸)
# ──────────────────────────────────────────────────────────────
def test_다른_요일_변경은_보고에_안_섞인다():
    """사진은 오늘 칸인데 변경만 페이지 전체를 보면 어긋난다.

    2026-08-02 실측: 오늘 칸은 37건인데 변경이 719건으로 잡혔다.
    """
    ch = _changes(
        completed=[_todo("a", "오늘 칸 완료", weekday="일요일", seq=0),
                   _todo("b", "목요일 칸 완료", weekday="목요일", seq=0),
                   _todo("c", "지난주 일요일", weekday="일요일", seq=1)],
        added=[_todo("d", "요일 없는 것", weekday=None)])
    got = nt.filter_changes_to_weekday(ch, "일요일")

    assert [t["id"] for t in got["completed"]] == ["a"]
    assert got["added"] == []          # 요일 칸 밖은 제외


def test_보고는_오늘_칸만_세고_전체_건수도_알려준다(monkeypatch):
    todos = ([_todo(f"s{i}", f"일요일 {i}", weekday="일요일", seq=0) for i in range(3)]
             + [_todo(f"t{i}", f"목요일 {i}", weekday="목요일", seq=0) for i in range(9)])
    nt.save_snapshot([], sent_date="2026-08-01")
    monkeypatch.setattr(nt, "fetch_todos", lambda **kw: todos)

    r = nt.build_report(when=date(2026, 8, 2))      # 일요일
    assert r["changed_all"] == 12                   # 페이지 전체
    assert sum(len(v) for v in r["changes"].values()) == 3   # 오늘 칸만


def test_판번호가_다르면_다시_읽게_한다(tmp_path, monkeypatch):
    """문구 형식을 바꿔도 옛 저장본이 남아 옛 문구가 그대로 나가던 문제.

    2026-08-02 반복 발생 — 배포는 됐는데 화면·카톡은 옛 것. 사람이 매번
    「다시 읽기」를 기억해야 했다. 판 번호로 코드가 스스로 알아채게 한다.
    """
    import json as _json

    path = tmp_path / "last.json"
    monkeypatch.setattr(nt, "_last_report_path", lambda: str(path))

    # 새 칸 이름은 있지만 판 번호가 옛것
    path.write_text(_json.dumps({"ok": True, "photo_message": "x",
                                 "format": nt.REPORT_FORMAT_VERSION - 1}),
                    encoding="utf-8")
    assert nt.load_last_report() is None

    # 판 번호가 맞으면 그대로 쓴다
    path.write_text(_json.dumps({"ok": True, "photo_message": "x",
                                 "format": nt.REPORT_FORMAT_VERSION}),
                    encoding="utf-8")
    assert nt.load_last_report() is not None


def test_저장하면_판번호가_찍힌다(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "_last_report_path", lambda: str(tmp_path / "l.json"))
    nt._save_last_report({"ok": True, "photo_message": "x"})
    assert nt.load_last_report()["format"] == nt.REPORT_FORMAT_VERSION

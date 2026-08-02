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
    """스냅샷 파일을 테스트별 임시 경로로 — 라이브 data/ 를 절대 건드리지 않는다."""
    monkeypatch.setattr(nt, "_SNAPSHOT_PATH", str(tmp_path / "snap.json"))
    yield


def _todo(tid, text, checked=False, weekday=None, seq=0, order=0):
    return {"id": tid, "text": text, "checked": checked,
            "weekday": weekday, "weekday_seq": seq, "order": order}


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
        {"id": "a", "before": "택배비 점검", "after": "택배비 점검 (수정됨)"}
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
def test_메시지_200자_넘지_않는다():
    changes = {
        "added": [_todo(f"a{i}", "아주 긴 할 일 제목 " * 5) for i in range(20)],
        "completed": [_todo(f"c{i}", "완료된 긴 제목 " * 5) for i in range(20)],
        "reopened": [], "removed": [], "edited": [],
    }
    today = [_todo("t", "남은 일")]
    msg = nt.build_message(changes, today, when=date(2026, 7, 31))
    assert len(msg) <= 200


def test_메시지_집계와_꼬리말은_항상_남는다():
    """항목이 잘려도 숫자와 남은 건수는 살아 있어야 신호가 된다."""
    changes = {
        "added": [_todo(f"a{i}", "x" * 100) for i in range(30)],
        "completed": [], "reopened": [], "removed": [], "edited": [],
    }
    today = [_todo("t1", "a"), _todo("t2", "b", checked=True)]
    msg = nt.build_message(changes, today, when=date(2026, 7, 31))   # 금요일
    assert "[영빈 투두 7/31(금)]" in msg
    assert "신규 30" in msg
    assert "오늘(금) 남은 일 1건" in msg
    assert len(msg) <= 200


def test_메시지_변경없음_표기():
    empty = {"added": [], "completed": [], "reopened": [], "removed": [], "edited": []}
    msg = nt.build_message(empty, [_todo("t", "할일")], when=date(2026, 7, 31))
    assert "변경 없음" in msg


def test_메시지_요일블록_못찾으면_숨기지_않는다():
    """오늘 블록이 비면 조용히 0건이 아니라 못 찾았다고 말해야 한다."""
    empty = {"added": [], "completed": [], "reopened": [], "removed": [], "edited": []}
    msg = nt.build_message(empty, [], when=date(2026, 7, 31))
    assert "오늘 요일 블록 못 찾음" in msg


# ──────────────────────────────────────────────────────────────
# ⑤ 발송 게이트
# ──────────────────────────────────────────────────────────────
def _stub_report(monkeypatch, todos, sent_ok=True, calls=None):
    monkeypatch.setattr(nt, "fetch_todos", lambda **kw: todos)
    import shared.notifier as sn

    def _fake_send(text, **kw):
        if calls is not None:
            calls.append(text)
        return sent_ok

    monkeypatch.setattr(sn, "send_kakao_memo", _fake_send)


def test_첫실행은_기준선만_저장하고_발송안함(monkeypatch):
    """어제가 없으면 전 항목이 신규 — 700건을 카톡에 쏟아붓지 않는다."""
    calls: list[str] = []
    _stub_report(monkeypatch, [_todo("a", "할일"), _todo("b", "할일2")], calls=calls)

    res = nt.run_daily_report(when=date(2026, 7, 31))
    assert res["skipped"] == "baseline_saved"
    assert calls == []
    assert len(nt.load_snapshot()["todos"]) == 2


def test_이미_보낸_날은_건너뛴다(monkeypatch):
    """배포 재기동으로 잡이 한 번 더 뛰어도 카톡이 두 번 가면 안 된다."""
    calls: list[str] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-07-31")
    _stub_report(monkeypatch, [_todo("a", "할일", checked=True)], calls=calls)

    res = nt.run_daily_report(when=date(2026, 7, 31))
    assert res["skipped"] == "already_sent"
    assert calls == []


def test_둘째날부터_변경분만_발송(monkeypatch):
    calls: list[str] = []
    nt.save_snapshot([_todo("a", "할일"), _todo("b", "할일2")], sent_date="2026-07-30")
    _stub_report(monkeypatch,
                 [_todo("a", "할일", checked=True), _todo("b", "할일2")], calls=calls)

    res = nt.run_daily_report(when=date(2026, 7, 31))
    assert res["sent"] is True
    assert len(calls) == 1
    assert "완료 1" in calls[0]
    assert nt.load_snapshot()["sent_date"] == "2026-07-31"


def test_발송실패하면_발송일을_찍지_않는다(monkeypatch):
    """찍어버리면 그날은 영영 재시도가 막힌다."""
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-07-30")
    _stub_report(monkeypatch, [_todo("a", "할일", checked=True)], sent_ok=False)

    res = nt.run_daily_report(when=date(2026, 7, 31))
    assert res["sent"] is False
    assert nt.load_snapshot()["sent_date"] == "2026-07-30"   # 그대로


def test_dry_run_은_발송도_저장도_안한다(monkeypatch):
    calls: list[str] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-07-30")
    _stub_report(monkeypatch, [_todo("a", "할일", checked=True)], calls=calls)

    res = nt.run_daily_report(dry_run=True, when=date(2026, 7, 31))
    assert res["dry_run"] is True
    assert calls == []
    assert nt.load_snapshot()["sent_date"] == "2026-07-30"


def test_노션_읽기_실패는_조용히_넘어가지_않는다(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("노션 블록 조회 실패 404: page not found")

    monkeypatch.setattr(nt, "fetch_todos", _boom)
    res = nt.run_daily_report(when=date(2026, 7, 31))
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
    nt._save_last_report({"ok": True, "message": "m", "todos": [{"id": "a"}] * 700})
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
        return {"ok": True, "message": "늦게 끝난 수집", "changes": {}, "picked": {}}

    monkeypatch.setattr(nt, "build_report", lambda **kw: _slow_build())

    assert nt.start_refresh() is True
    assert nt.is_refreshing() is True          # 요청은 이미 반환된 상태
    assert nt.start_refresh() is False         # 중복 실행 금지
    done.set()
    for _ in range(50):
        if not nt.is_refreshing():
            break
        _t.Event().wait(0.1)
    assert nt.load_last_report()["message"] == "늦게 끝난 수집"

# -*- coding: utf-8 -*-
"""발송 시각표 · 변경 이력 · 노션 캡처."""
from __future__ import annotations

import json
from datetime import date

import pytest

from lemouton.reports import report_history as H
from lemouton.reports import report_schedule as S
from lemouton.reports import shot_store as SH
from lemouton.reports import notion_todo as nt


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_PATH", str(tmp_path / "sched.json"))
    monkeypatch.setattr(H, "_PATH", str(tmp_path / "hist.jsonl"))
    monkeypatch.setattr(SH, "_PATH", str(tmp_path / "shots"))
    monkeypatch.setattr(nt, "_SNAPSHOT_PATH", str(tmp_path / "snap.json"))
    yield


def _todo(tid, text, checked=False, weekday="일요일", seq=0, edited=None):
    return {"id": tid, "text": text, "checked": checked, "weekday": weekday,
            "weekday_seq": seq, "order": 0, "last_edited": edited}


_PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


# ──────────────────────────────────────────────────────────────
# 시각표
# ──────────────────────────────────────────────────────────────
def test_시각_정규화와_잘못된값_반환():
    good, bad = S.set_times(["9:30", "14:00", "25:99", "", "아무말"])
    assert good == ["09:30", "14:00"]
    assert bad == ["25:99", "아무말"]      # 조용히 버리지 않는다


def test_시각별로_발송기록이_따로다():
    """하나의 발송일만 쓰면 그날 첫 회차 뒤 나머지가 전부 막힌다."""
    S.set_times(["09:30", "14:00"])
    S.mark_sent("09:30", "2026-08-02")

    assert S.already_sent("09:30", "2026-08-02") is True
    assert S.already_sent("14:00", "2026-08-02") is False   # ★막히면 안 됨
    assert S.already_sent("09:30", "2026-08-03") is False   # 다음 날은 다시


def test_없어진_시각의_발송기록은_같이_지운다():
    S.set_times(["09:30", "14:00"])
    S.mark_sent("14:00", "2026-08-02")
    S.set_times(["09:30"])
    assert "14:00" not in S.status()["sent"]


# ──────────────────────────────────────────────────────────────
# 변경 이력
# ──────────────────────────────────────────────────────────────
def test_이력에_언제_무엇이_어떻게가_남는다():
    changes = {
        "added": [_todo("a", "새 할일")],
        "completed": [_todo("b", "끝낸 일", checked=True,
                            edited="2026-08-02T05:03:00.000Z")],
        "reopened": [], "removed": [],
        "edited": [{"id": "c", "before": "옛 문구", "after": "새 문구",
                    "last_edited": "2026-08-02T06:10:00.000Z"}],
    }
    assert H.append(slot="09:30", changes=changes) == 3

    rows = H.load()
    kinds = {e["kind"] for e in rows[0]["entries"]}
    assert kinds == {"added", "completed", "edited"}

    ed = next(e for e in rows[0]["entries"] if e["kind"] == "edited")
    assert ed["before"] == "옛 문구" and ed["after"] == "새 문구"   # 전→후 보존

    done = next(e for e in rows[0]["entries"] if e["kind"] == "completed")
    assert done["edited_at"] == "08/02 14:03"   # 노션 UTC → 서울 시각


def test_변경이_없으면_이력을_쌓지_않는다():
    empty = {"added": [], "completed": [], "reopened": [], "removed": [], "edited": []}
    assert H.append(slot="09:30", changes=empty) == 0
    assert H.load() == []


def test_이력은_날짜별로_묶인다():
    H.append(slot="09:30", changes={"added": [_todo("a", "x")], "completed": [],
                                    "reopened": [], "removed": [], "edited": []})
    H.append(slot="14:00", changes={"added": [_todo("b", "y")], "completed": [],
                                    "reopened": [], "removed": [], "edited": []})
    grouped = H.by_day()
    assert len(grouped) == 1                    # 같은 날
    assert len(grouped[0][1]) == 2              # 회차 2개


# ──────────────────────────────────────────────────────────────
# 캡처
# ──────────────────────────────────────────────────────────────
def test_PNG가_아니면_거부():
    with pytest.raises(ValueError, match="PNG"):
        SH.save(b"NOT A PNG")


def test_너무_크면_거부():
    with pytest.raises(ValueError, match="너무 큼"):
        SH.save(b"\x89PNG\r\n\x1a\n" + b"\x00" * (SH.MAX_BYTES + 1))


def test_저장하면_신선하고_주소가_생긴다(monkeypatch):
    monkeypatch.setenv("MOUM_PUBLIC_BASE", "https://mou-m.com")
    SH.save(_PNG, weekday="일요일")
    assert SH.is_fresh() is True
    url = SH.public_url()
    assert url.startswith("https://mou-m.com/reports/notion-todo/shot/shot_")


def test_오래된_캡처는_안_붙인다(monkeypatch):
    SH.save(_PNG)
    monkeypatch.setattr(SH, "age_minutes", lambda: SH.STALE_MINUTES + 1)
    assert SH.is_fresh() is False
    assert SH.public_url() is None      # 어제 사진을 오늘 보고에 붙이면 거짓말


def test_최신_한장만_남긴다():
    import time as _t

    SH.save(_PNG)
    _t.sleep(1.05)          # 파일명이 초 단위라 겹치지 않게
    SH.save(_PNG)
    import os
    shots = [f for f in os.listdir(SH._dir()) if f.startswith("shot_")]
    assert len(shots) == 1


def test_경로_탈출은_막는다():
    assert SH.path_of("../../etc/passwd") is None
    assert SH.path_of("meta.json") is None


# ──────────────────────────────────────────────────────────────
# 회차 발송
# ──────────────────────────────────────────────────────────────
def _stub(monkeypatch, todos, ok=True, calls=None):
    monkeypatch.setattr(nt, "fetch_todos", lambda **kw: todos)
    import shared.notifier as sn

    def _send(text, **kw):
        if calls is not None:
            calls.append(kw)
        return {"ok": ok, "status": 200 if ok else 400, "error": None if ok else "boom"}

    monkeypatch.setattr(sn, "send_kakao_memo_detailed", _send)


def test_회차마다_따로_나간다(monkeypatch):
    """09:30 이 나갔다고 14:00 이 막히면 안 된다."""
    calls: list[dict] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-08-01")
    _stub(monkeypatch, [_todo("a", "할일", checked=True)], calls=calls)

    r1 = nt.run_slot_report("09:30", when=date(2026, 8, 2))
    r2 = nt.run_slot_report("14:00", when=date(2026, 8, 2))
    r3 = nt.run_slot_report("09:30", when=date(2026, 8, 2))   # 같은 회차 재실행

    assert r1["sent"] is True
    assert r2.get("sent") is True or r2.get("skipped") is None
    assert r3["skipped"] == "already_sent"


def test_캡처가_있으면_사진을_붙인다(monkeypatch):
    monkeypatch.setenv("MOUM_PUBLIC_BASE", "https://mou-m.com")
    SH.save(_PNG, weekday="일요일")
    calls: list[dict] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-08-01")
    _stub(monkeypatch, [_todo("a", "할일", checked=True)], calls=calls)

    res = nt.run_slot_report("09:30", when=date(2026, 8, 2))
    assert res["had_image"] is True
    assert calls[0]["image_url"].endswith(".png")


def test_캡처가_없어도_보고는_나간다(monkeypatch):
    """PC 가 꺼져 있다고 보고 자체가 빠지면 안 된다."""
    calls: list[dict] = []
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-08-01")
    _stub(monkeypatch, [_todo("a", "할일", checked=True)], calls=calls)

    res = nt.run_slot_report("09:30", when=date(2026, 8, 2))
    assert res["sent"] is True
    assert res["had_image"] is False
    assert calls[0]["image_url"] == ""


def test_발송_실패해도_이력은_남는다(monkeypatch):
    """보낸 것만 기록하면 실패한 날의 변경분이 영영 사라진다."""
    nt.save_snapshot([_todo("a", "할일")], sent_date="2026-08-01")
    _stub(monkeypatch, [_todo("a", "할일", checked=True)], ok=False)

    res = nt.run_slot_report("09:30", when=date(2026, 8, 2))
    assert res["sent"] is False
    assert len(H.load()) == 1                       # 이력은 남았다
    assert S.already_sent("09:30", "2026-08-02") is False   # 재시도는 열려 있다


# ──────────────────────────────────────────────────────────────
# 「지금 찍어줘」 — 테스트 발송용
# ──────────────────────────────────────────────────────────────
def test_요청하면_표시가_남고_찍으면_사라진다():
    assert SH.is_requested() is False
    SH.request_capture()
    assert SH.is_requested() is True

    SH.save(_PNG, weekday="일요일")
    assert SH.is_requested() is False    # 같은 요청으로 두 번 찍지 않는다


def test_오래된_요청은_스스로_만료된다(monkeypatch):
    """요청이 남아 엉뚱한 때 노션 탭이 열리면 안 된다."""
    import json as _json
    from datetime import timedelta as _td

    SH.request_capture()
    old = (SH._seoul_now() - _td(minutes=SH.REQUEST_TTL_MINUTES + 1)).isoformat()
    with open(SH._req_path(), "w", encoding="utf-8") as f:
        _json.dump({"at": old}, f)

    assert SH.is_requested() is False
    import os
    assert not os.path.exists(SH._req_path())   # 만료분은 치운다


def test_요청이_있으면_신선해도_다시_찍는다():
    """테스트는 「방금 화면」을 보려는 것 — 어제 찍은 게 있어도 새로 찍어야 한다."""
    SH.save(_PNG)
    assert SH.is_fresh() is True
    SH.request_capture()
    assert SH.is_requested() is True     # 라우트가 needed=True 로 판정하는 근거


# ──────────────────────────────────────────────────────────────
# 화면 — 발송 결과가 500 으로 죽지 않아야 한다
# ──────────────────────────────────────────────────────────────
def test_발송_결과화면이_죽지_않는다(monkeypatch):
    """카톡은 나갔는데 결과 화면이 터지면 「실패했나」 싶어진다.

    2026-08-02 실측: 없어진 칸 이름(message)을 부르다 500. 발송은 이미 끝난 뒤라
    카톡은 갔는데 화면만 죽었다 — 성공을 실패로 오인하게 만든다.
    """
    import app as A
    from lemouton.reports import notion_todo as _nt
    import shared.notifier as sn

    monkeypatch.setenv("MOUM_NO_AUTOCONFIRM_SCHED", "1")
    monkeypatch.setenv("MOUM_ORDER_INGEST_HOURS", "0")
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    monkeypatch.setattr(sn, "send_kakao_memo_detailed",
                        lambda *a, **k: {"ok": True, "status": 200, "error": None})
    monkeypatch.setattr(_nt, "load_last_report", lambda: {
        "ok": True,
        "photo_message": "영빈 투두 8/2(일)\n남은 일 35건",
        "change_message": "8/2(일) · 변경 2건\n11:20 ✅ 끝낸 일",
        "changes": {}, "picked": {},
    })

    client = A.create_app().test_client()
    r = client.post("/reports/notion-todo/test/send")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "발송 완료" in body
    assert "남은 일 35건" in body          # 두 통 다 보여줘야 한다
    assert "변경 2건" in body

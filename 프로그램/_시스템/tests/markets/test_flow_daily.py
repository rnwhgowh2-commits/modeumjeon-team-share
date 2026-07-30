# -*- coding: utf-8 -*-
"""배송흐름 최근 7일 요약 — 「지켜본 결과」를 날짜별로.

사장님 요청(2026-07-30): "멈춘 주문 없음에 감시된 내용 요약을 설명해줘 —
최근 1~7일별 X건 송장번호 입력 / X건 배송중 / X건 배송완료."
"""
import datetime as _dt

from lemouton.markets import flow_daily as fd
from lemouton.markets.flow_stall import KST

NOW = _dt.datetime(2026, 7, 30, 12, 0, tzinfo=KST)


def _row(dispatch, status="배송준비중", inv="505045353994", market="스마트스토어"):
    return {"송장입력": inv, "주문상태": status, "발송처리일": dispatch,
            "판매처": market, "상품명": "테스트 상품"}


def _patch(monkeypatch, rows):
    from lemouton.markets import order_store
    monkeypatch.setattr(order_store, "load", lambda **k: rows)


def test_날짜별로_세_갈래를_센다(monkeypatch):
    _patch(monkeypatch, [
        _row("2026-07-30 09:00", "배송준비중"),   # 오늘 · 송장 입력
        _row("2026-07-30 10:00", "배송중"),       # 오늘 · 배송 중
        _row("2026-07-30 11:00", "배송완료"),     # 오늘 · 배송 완료
        _row("2026-07-29 09:00", "배송중"),       # 어제 · 배송 중
    ])
    got = fd.summarize(days=7, now=NOW)
    today, yday = got["rows"][0], got["rows"][1]
    assert (today["label"], today["inp"], today["ing"], today["fin"]) == ("오늘", 1, 1, 1)
    assert (yday["label"], yday["ing"]) == ("어제", 1)


def test_일곱_칸이_빠짐없이_나온다(monkeypatch):
    """주문이 없는 날도 0 으로 자리를 지켜야 표가 안 흔들린다."""
    _patch(monkeypatch, [])
    got = fd.summarize(days=7, now=NOW)
    assert len(got["rows"]) == 7
    assert [r["label"] for r in got["rows"]][:3] == ["오늘", "어제", "2일 전"]
    assert all(r["total"] == 0 for r in got["rows"])


def test_최신_날짜가_맨_위다(monkeypatch):
    _patch(monkeypatch, [])
    dates = [r["date"] for r in fd.summarize(days=7, now=NOW)["rows"]]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-07-30"


def test_송장이_없으면_안_센다(monkeypatch):
    """아직 안 보낸 주문은 지켜볼 대상이 아니다."""
    _patch(monkeypatch, [_row("2026-07-30 09:00", inv="송장미입력"),
                         _row("2026-07-30 09:00", inv=""),
                         _row("2026-07-30 09:00", inv="확인 불가")])
    got = fd.summarize(days=7, now=NOW)
    assert got["rows"][0]["total"] == 0 and got["unknown"] == 0


def test_날짜를_모르는_건수를_숨기지_않는다(monkeypatch):
    """쿠팡·옥션·G마켓은 발송처리일을 안 준다 — 조용히 빠지면 안 보인다."""
    _patch(monkeypatch, [_row("2026-07-30 09:00"),
                         _row("", market="쿠팡"), _row("", market="옥션")])
    got = fd.summarize(days=7, now=NOW)
    assert got["rows"][0]["total"] == 1
    assert got["unknown"] == 2


def test_기간_밖은_안_센다(monkeypatch):
    _patch(monkeypatch, [_row("2026-06-01 09:00"), _row("2026-07-30 09:00")])
    got = fd.summarize(days=7, now=NOW)
    assert sum(r["total"] for r in got["rows"]) == 1


def test_구매확정도_배송완료로_센다(monkeypatch):
    """구매확정은 배송이 끝난 뒤 단계다 — 완료 칸에 들어가야 숫자가 안 샌다."""
    _patch(monkeypatch, [_row("2026-07-30 09:00", "구매확정"),
                         _row("2026-07-30 10:00", "수취완료")])
    assert fd.summarize(days=7, now=NOW)["rows"][0]["fin"] == 2


def test_날짜를_누르면_그날_그갈래만_준다(monkeypatch):
    _patch(monkeypatch, [
        _row("2026-07-30 09:00", "배송중"),
        _row("2026-07-30 10:00", "배송완료"),
        _row("2026-07-29 09:00", "배송중"),
    ])
    got = fd.detail(date="2026-07-30", kind="ing", now=NOW)
    assert got["count"] == 1
    assert got["rows"][0]["_dispatch_at"] == "2026-07-30 09:00"


def test_상세는_늦은_시각부터_보여준다(monkeypatch):
    _patch(monkeypatch, [_row("2026-07-30 09:00", "배송중"),
                         _row("2026-07-30 18:00", "배송중")])
    got = fd.detail(date="2026-07-30", kind="ing", now=NOW)
    times = [r["_dispatch_at"] for r in got["rows"]]
    assert times == sorted(times, reverse=True)


def test_요약과_상세의_숫자가_맞는다(monkeypatch):
    """다른 기준으로 세면 「3건」이라 해놓고 눌렀을 때 2건이 나온다."""
    rows = [_row("2026-07-30 09:00", "배송중"), _row("2026-07-30 10:00", "배송중"),
            _row("2026-07-30 11:00", "배송완료"), _row("2026-07-30 12:00", "배송준비중")]
    _patch(monkeypatch, rows)
    s = fd.summarize(days=7, now=NOW)["rows"][0]
    for kind in ("inp", "ing", "fin"):
        assert fd.detail(date="2026-07-30", kind=kind, now=NOW)["count"] == s[kind]


class TestRoute:
    """화면이 부르는 창구 — 요약과 상세가 한 경로에서 갈린다."""

    def _client(self):
        from flask import Flask
        from webapp.routes import orders as om
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(om.bp)
        return app.test_client()

    def test_요약을_돌려준다(self, monkeypatch):
        from lemouton.markets import order_store
        monkeypatch.setattr(order_store, "load", lambda **k: [])
        j = self._client().get("/orders/flow-daily.json?days=7").get_json()
        assert j["ok"] is True and len(j["rows"]) == 7

    def test_날짜를_주면_상세로_간다(self, monkeypatch):
        from lemouton.markets import order_store
        monkeypatch.setattr(order_store, "load", lambda **k: [])
        j = self._client().get("/orders/flow-daily.json?date=2026-07-30&kind=ing").get_json()
        assert j["ok"] is True and j["kind"] == "ing"

    def test_엉뚱한_갈래는_막는다(self):
        r = self._client().get("/orders/flow-daily.json?date=2026-07-30&kind=xxx")
        assert r.status_code == 400

    def test_기간_상한을_지킨다(self, monkeypatch):
        """너무 넓게 부르면 적재분을 통째로 읽어 화면이 멈춘다."""
        from lemouton.markets import order_store
        monkeypatch.setattr(order_store, "load", lambda **k: [])
        j = self._client().get("/orders/flow-daily.json?days=999").get_json()
        assert j["days"] == 31

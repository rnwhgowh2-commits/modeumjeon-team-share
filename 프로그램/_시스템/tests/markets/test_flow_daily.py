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
    assert (today["label"], today["prep"], today["ing"], today["fin"]) == ("오늘", 1, 1, 1)
    assert (yday["label"], yday["ing"]) == ("어제", 1)


def test_일곱_칸이_빠짐없이_나온다(monkeypatch):
    """주문이 없는 날도 0 으로 자리를 지켜야 표가 안 흔들린다."""
    _patch(monkeypatch, [])
    got = fd.summarize(days=7, now=NOW)
    assert len(got["rows"]) == 7
    assert [r["label"] for r in got["rows"]][:3] == ["오늘", "어제", "2일 전"]
    assert all(r["sent"] == 0 for r in got["rows"])


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
    assert got["rows"][0]["sent"] == 0 and got["unknown"] == 0


def test_날짜를_모르는_건수를_숨기지_않는다(monkeypatch):
    """쿠팡·옥션·G마켓은 발송처리일을 안 준다 — 조용히 빠지면 안 보인다."""
    _patch(monkeypatch, [_row("2026-07-30 09:00"),
                         _row("", market="쿠팡"), _row("", market="옥션")])
    got = fd.summarize(days=7, now=NOW)
    assert got["rows"][0]["sent"] == 1
    assert got["unknown"] == 2


def test_기간_밖은_안_센다(monkeypatch):
    _patch(monkeypatch, [_row("2026-06-01 09:00"), _row("2026-07-30 09:00")])
    got = fd.summarize(days=7, now=NOW)
    assert sum(r["sent"] for r in got["rows"]) == 1


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
    for kind in ("prep", "ing", "fin", "clm"):
        assert fd.detail(date="2026-07-30", kind=kind, now=NOW)["count"] == s[kind]


def test_세_갈래를_한_번에_준다(monkeypatch):
    """갈래마다 따로 부르면 같은 적재분을 세 번 읽어 탭마다 수십 초를 기다린다."""
    _patch(monkeypatch, [
        _row("2026-07-30 09:00", "배송준비중"), _row("2026-07-30 10:00", "배송중"),
        _row("2026-07-30 11:00", "배송완료"), _row("2026-07-30 12:00", "배송완료"),
    ])
    got = fd.detail(date="2026-07-30", kind="all", now=NOW)
    assert got["counts"] == {"prep": 1, "ing": 1, "fin": 2, "clm": 0}
    assert set(got["rows"]) == {"prep", "ing", "fin", "clm"}
    assert len(got["rows"]["fin"]) == 2


def test_한번에_받은_숫자가_요약과_같다(monkeypatch):
    rows = [_row("2026-07-30 09:00", "배송중"), _row("2026-07-30 10:00", "배송중"),
            _row("2026-07-30 11:00", "배송완료"), _row("2026-07-30 12:00", "배송준비중")]
    _patch(monkeypatch, rows)
    s = fd.summarize(days=7, now=NOW)["rows"][0]
    a = fd.detail(date="2026-07-30", kind="all", now=NOW)["counts"]
    assert a == {k: s[k] for k in ("prep", "ing", "fin", "clm")}


def test_상세는_그_날짜_앞뒤만_읽는다(monkeypatch):
    """적재분을 통째로 읽으면 라이브에서 28초 걸린다 — 창을 좁혀야 한다."""
    seen = {}

    def _load(**kw):
        seen.update(kw)
        return []

    from lemouton.markets import order_store
    monkeypatch.setattr(order_store, "load", _load)
    fd.detail(date="2026-07-10", kind="all", now=NOW)
    assert seen["until"] == "2026-07-10"
    assert seen["since"] == "2026-06-10"        # 30일 앞
    assert seen["include_claims"] is False      # 클레임은 배송흐름과 무관


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

    def test_all_로_세_갈래를_한_번에_받는다(self, monkeypatch):
        from lemouton.markets import order_store
        monkeypatch.setattr(order_store, "load", lambda **k: [])
        j = self._client().get("/orders/flow-daily.json?date=2026-07-30&kind=all").get_json()
        assert j["ok"] is True and j["kind"] == "all"
        assert j["counts"] == {"prep": 0, "ing": 0, "fin": 0, "clm": 0}

    def test_기간_상한을_지킨다(self, monkeypatch):
        """너무 넓게 부르면 적재분을 통째로 읽어 화면이 멈춘다."""
        from lemouton.markets import order_store
        monkeypatch.setattr(order_store, "load", lambda **k: [])
        j = self._client().get("/orders/flow-daily.json?days=999").get_json()
        assert j["days"] == 31


# ── 2026-07-30 사장님 확정: X = Y + Z + K + Q ──────────────────────────

def test_송장넣음이_나머지_넷의_합이다(monkeypatch):
    """X 를 「나머지 통」으로 두면 총계가 아니어서 사장님이 더해 봐야 한다."""
    _patch(monkeypatch, [
        _row("2026-07-30 09:00", "배송준비중"), _row("2026-07-30 10:00", "배송중"),
        _row("2026-07-30 11:00", "구매확정"), _row("2026-07-30 12:00", "반품완료"),
    ])
    r = fd.summarize(days=7, now=NOW)["rows"][0]
    assert (r["prep"], r["ing"], r["fin"], r["clm"]) == (1, 1, 1, 1)
    assert r["sent"] == r["prep"] + r["ing"] + r["fin"] + r["clm"] == 4


def test_클레임은_배송준비중에_안_섞인다(monkeypatch):
    """반품·취소를 「준비중」에 넣으면 멈춘 주문이 있는 것처럼 보인다(거짓 경보)."""
    _patch(monkeypatch, [_row("2026-07-30 09:00", s)
                         for s in ("반품완료", "취소완료", "교환요청", "회수지시", "철회")])
    r = fd.summarize(days=7, now=NOW)["rows"][0]
    assert r["clm"] == 5 and r["prep"] == 0


def test_지난_날짜의_배송준비중은_멈춘_것이다(monkeypatch):
    """송장을 넣고 그날이 지났는데 흐름이 안 잡혔으면 정상이 아니다."""
    _patch(monkeypatch, [_row("2026-07-28 09:00", "배송준비중"),   # 2일 전 → 멈춤
                         _row("2026-07-27 09:00", "배송준비중")])  # 3일 전 → 멈춤
    got = fd.summarize(days=7, now=NOW)
    assert got["stuck"] == 2
    assert [r["stuck"] for r in got["rows"]] == [0, 0, 1, 1, 0, 0, 0]


def test_오늘_어제는_아직_멈춘_게_아니다(monkeypatch):
    """넣자마자 흐름이 안 잡히는 건 정상이다 — 빨갛게 칠하면 늑대소년이 된다."""
    _patch(monkeypatch, [_row("2026-07-30 09:00", "배송준비중"),
                         _row("2026-07-29 09:00", "배송준비중")])
    got = fd.summarize(days=7, now=NOW)
    assert got["stuck"] == 0
    assert (got["rows"][0]["prep"], got["rows"][1]["prep"]) == (1, 1)


# ── 2026-07-30 라이브 사고: 「발송완료」가 배송준비중으로 빨갛게 떴다 ──────

def test_발송된_상태를_하나도_안_빠뜨린다():
    """`_SHIPPED_STATES` 에 새 상태가 늘면 여기서 **바로 걸려야** 한다.

    실제로 「발송완료」가 빠져 롯데온 1건이 「지난 날짜인데 배송준비중」으로
    빨갛게 떴다 — 마켓은 정상이었고 우리 분류만 틀렸다.
    """
    from lemouton.markets.order_export import _SHIPPED_STATES
    covered = set(fd._ING) | set(fd._FIN)
    assert _SHIPPED_STATES - covered == set(), \
        f"발송된 상태인데 어느 칸에도 안 들어감: {_SHIPPED_STATES - covered}"


def test_발송완료는_배송중으로_센다(monkeypatch):
    _patch(monkeypatch, [_row("2026-07-25 09:00", "발송완료")])
    r = fd.summarize(days=7, now=NOW)["rows"][5]
    assert (r["ing"], r["prep"], r["stuck"]) == (1, 0, 0)


def test_처음_보는_상태는_멈춘_걸로_안_몬다(monkeypatch):
    """모르는 상태를 멈춘 것으로 몰면 **없는 문제**를 만든다."""
    _patch(monkeypatch, [_row("2026-07-25 09:00", "듣도보도못한상태"),
                         _row("2026-07-25 10:00", "배송준비중")])
    got = fd.summarize(days=7, now=NOW)
    r = got["rows"][5]
    assert r["prep"] == 2          # 칸에는 둘 다 들어가되
    assert r["stuck"] == 1         # 멈춘 것으로는 아는 것만 센다
    assert got["unseen"] == {"듣도보도못한상태": 1}   # 이름째 드러난다


def test_아는_준비중_상태는_멈춘_걸로_센다(monkeypatch):
    _patch(monkeypatch, [_row("2026-07-25 09:00", s) for s in fd._PREP])
    got = fd.summarize(days=7, now=NOW)
    assert got["stuck"] == len(fd._PREP) and got["unseen"] == {}


# ── 2026-07-30 사장님 요청: 두 시각을 구분한다 ─────────────────────────

def test_두_시각을_따로_보여준다(monkeypatch):
    """① 송장 전송 시각(마켓이 준 값) ② 상태 바뀐 걸 우리가 본 때(관측값)."""
    r = _row("2026-07-30 09:00", "배송중")
    r["_status_at"] = "2026-07-30 05:30:00+00:00"      # UTC → KST 14:30
    _patch(monkeypatch, [r])
    got = fd.detail(date="2026-07-30", kind="ing", now=NOW)["rows"][0]
    assert got["_dispatch_at"] == "2026-07-30 09:00"
    assert got["_status_seen"] == "07-30 14:30"


def test_기록_전_주문은_빈칸이다(monkeypatch):
    """2026-07-30 이전 주문엔 기록이 없다 — 없는 시각을 지어내지 않는다."""
    _patch(monkeypatch, [_row("2026-07-30 09:00", "배송중")])
    got = fd.detail(date="2026-07-30", kind="ing", now=NOW)["rows"][0]
    assert got["_status_seen"] == ""


class TestStatusStamp:
    """상태가 **실제로 바뀔 때만** 시각을 찍는다.

    🔴 [2026-08-13] `_stamp_status` → `_apply_status` 로 이름이 바뀌었다. 계약은 그대로이고
      **되돌아가는 값은 안 쓴다**는 막이가 하나 붙었다(롯데온 510줄 31,790,892원이 뒤로
      가 있었다). 되돌아가는 쪽 시험은 `tests/markets/test_status_no_regress.py` 에 있다.
    """

    class _Obj:
        status = "배송준비중"
        status_prev = ""
        status_at = None

    def test_같은_상태면_안_찍는다(self):
        from lemouton.markets.order_store import _apply_status
        o = self._Obj()
        assert _apply_status(o, "배송준비중") is False
        assert o.status_at is None

    def test_바뀌면_직전_상태와_함께_찍는다(self):
        from lemouton.markets.order_store import _apply_status
        o = self._Obj()
        assert _apply_status(o, "배송중") is True
        assert o.status_prev == "배송준비중" and o.status_at is not None
        assert o.status == "배송중", "이제 값을 쓰는 것까지 이 함수가 한다"

    def test_빈_상태로는_안_덮는다(self):
        """마켓이 상태를 덜 준 조회가 '바뀐 것'으로 둔갑하면 시각이 거짓이 된다."""
        from lemouton.markets.order_store import _apply_status
        o = self._Obj()
        assert _apply_status(o, "") is False
        assert o.status_at is None

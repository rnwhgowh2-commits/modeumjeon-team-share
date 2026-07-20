"""업로드 속도한도 프로브 라우트 — 게이트·입력검증 테스트.

★ 실제 마켓에 접속하지 않는다. 게이트가 닫혀 있으면 어떤 마켓 호출도 없어야 한다.
"""
import pytest

from webapp.routes.upload_rate_probe import bp


@pytest.fixture
def client(monkeypatch):
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


# ── 게이트 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/upload-rate-probe/targets?market=coupang",
    "/api/upload-rate-probe/baseline?market=coupang&product_id=1&option_id=2",
    "/api/upload-rate-probe/noop-check?market=coupang&product_id=1&option_id=2",
    "/api/upload-rate-probe/burst?market=coupang&product_id=1&option_id=2",
    "/api/upload-rate-probe/ramp?market=coupang&product_id=1&option_id=2",
])
def test_게이트가_꺼져있으면_전부_404(client, monkeypatch, path):
    monkeypatch.delenv("UPLOAD_RATE_PROBE", raising=False)
    r = client.get(path)
    assert r.status_code == 404
    assert "UPLOAD_RATE_PROBE" in r.get_json()["error"]


def test_게이트가_꺼져있으면_마켓을_건드리지_않는다(client, monkeypatch):
    """게이트가 클라이언트 생성보다 먼저 막아야 한다."""
    monkeypatch.delenv("UPLOAD_RATE_PROBE", raising=False)
    called = []
    import webapp.routes.upload_rate_probe as R
    monkeypatch.setattr(R, "_client", lambda *a, **k: called.append(1))

    client.get("/api/upload-rate-probe/burst?market=coupang&product_id=1&option_id=2")
    assert called == [], "게이트가 닫혔는데 클라이언트를 만들었다"


# ── 입력 검증 ───────────────────────────────────────────────────

def test_모르는_마켓은_400(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    r = client.get("/api/upload-rate-probe/baseline?market=11street_typo"
                   "&product_id=1&option_id=2")
    assert r.status_code == 400


def test_키_미등록이면_400이고_쓰지_않는다(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    from lemouton.markets import upload_rate_probe as P

    wrote = []
    monkeypatch.setattr(R, "_client", lambda *a, **k: None)   # 키 미등록
    monkeypatch.setattr(P, "write_stock", lambda *a, **k: wrote.append(1))

    r = client.get("/api/upload-rate-probe/burst?market=coupang"
                   "&product_id=1&option_id=2")
    assert r.status_code == 400
    assert wrote == []


def test_재고를_못읽으면_시작하지_않는다(client, monkeypatch):
    """원래 값을 모르면 원복을 보장할 수 없다 — 쓰기 자체를 안 한다."""
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    from lemouton.markets import upload_rate_probe as P

    wrote = []
    monkeypatch.setattr(R, "_client", lambda *a, **k: object())
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: None)
    monkeypatch.setattr(P, "write_stock", lambda *a, **k: wrote.append(1))

    r = client.get("/api/upload-rate-probe/burst?market=coupang"
                   "&product_id=1&option_id=2")
    assert r.status_code == 400
    assert wrote == [], "현재 재고를 모르는데 썼다"


# ── 무변화·원복 표면화 ──────────────────────────────────────────

def test_버스트는_읽은_값만_되쓴다(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    from lemouton.markets import upload_rate_probe as P

    sent = []
    monkeypatch.setattr(R, "_client", lambda *a, **k: object())
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 5)

    class _Resp:
        status_code = 200
        headers = {}
        text = "{}"

    def w(market, *, client, product_id, option_id, stock):
        sent.append(stock)
        if len(sent) >= 4:
            raise _RateErr()
        return _Resp()

    class _RateErr(Exception):
        status_code = 429

    monkeypatch.setattr(P, "write_stock", w)

    r = client.get("/api/upload-rate-probe/burst?market=coupang"
                   "&product_id=1&option_id=2&max_calls=10")
    d = r.get_json()
    assert set(sent) == {5}, f"읽은 값(5) 외의 값을 보냈다: {set(sent)}"
    assert d["capacity"] == 3 and d["hit_429"] is True
    assert d["restored"] is True


def test_재고가_안_돌아오면_경고를_띄운다(client, monkeypatch):
    """조용히 넘어가면 오염을 못 잡는다."""
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    from lemouton.markets import upload_rate_probe as P

    # 측정 루프는 known_stock 을 써서 조회를 건너뛴다 →
    # read_stock 은 ①기준선 ②끝난 뒤 확인, 딱 2번만 불린다.
    reads = iter([5, 99])         # 기준선=5, 끝나고 확인=99 (안 돌아옴)
    monkeypatch.setattr(R, "_client", lambda *a, **k: object())
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: next(reads, 99))

    class _Resp:
        status_code = 200
        headers = {}
        text = "{}"
    monkeypatch.setattr(P, "write_stock", lambda *a, **k: _Resp())

    r = client.get("/api/upload-rate-probe/noop-check?market=coupang"
                   "&product_id=1&option_id=2&n=1")
    d = r.get_json()
    assert d["restored"] is False
    assert "수기 확인" in d["warning"]


def test_호출수_상한을_넘지_않는다(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    from lemouton.markets import upload_rate_probe as P

    n = {"c": 0}
    monkeypatch.setattr(R, "_client", lambda *a, **k: object())
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 5)

    class _Resp:
        status_code = 200
        headers = {}
        text = "{}"

    def w(*a, **k):
        n["c"] += 1
        return _Resp()
    monkeypatch.setattr(P, "write_stock", w)

    client.get("/api/upload-rate-probe/burst?market=coupang"
               "&product_id=1&option_id=2&max_calls=99999")
    assert n["c"] <= R._MAX_CALLS_CAP


# ── 동시 부하(load) ─────────────────────────────────────────────

def test_load도_게이트가_막는다(client, monkeypatch):
    monkeypatch.delenv("UPLOAD_RATE_PROBE", raising=False)
    r = client.get("/api/upload-rate-probe/load?market=coupang"
                   "&product_id=1&option_id=2")
    assert r.status_code == 404


def test_load는_읽은_값만_되쓰고_429를_센다(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    from lemouton.markets import upload_rate_probe as P
    import threading

    monkeypatch.setattr(R, "_client", lambda *a, **k: object())
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 5)

    lock = threading.Lock()
    sent, n = [], {"c": 0}

    class _Resp:
        status_code = 200
        headers = {}
        text = "{}"

    class _RateErr(Exception):
        status_code = 429

    def w(market, *, client, product_id, option_id, stock):
        with lock:
            sent.append(stock)
            n["c"] += 1
            over = n["c"] > 5
        if over:
            raise _RateErr()
        return _Resp()

    monkeypatch.setattr(P, "write_stock", w)

    r = client.get("/api/upload-rate-probe/load?market=coupang"
                   "&product_id=1&option_id=2&concurrency=4&duration=1")
    d = r.get_json()
    assert set(sent) == {5}, f"읽은 값(5) 외를 보냈다: {set(sent)}"
    assert d["hit_429"] is True and d["rate_limited_429"] > 0
    assert d["concurrency"] == 4
    assert d["restored"] is True


def test_load_동시성과_지속시간에_상한이_있다(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    from lemouton.markets import upload_rate_probe as P

    monkeypatch.setattr(R, "_client", lambda *a, **k: object())
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 5)

    class _Resp:
        status_code = 200
        headers = {}
        text = "{}"
    monkeypatch.setattr(P, "write_stock", lambda *a, **k: _Resp())

    r = client.get("/api/upload-rate-probe/load?market=coupang"
                   "&product_id=1&option_id=2&concurrency=9999&duration=9999")
    d = r.get_json()
    assert d["concurrency"] <= R._MAX_CONCURRENCY
    assert d["sent"] <= R._MAX_CALLS_CAP


# ── discover 지연 import 심볼 실재 ──────────────────────────────

def test_discover가_쓰는_심볼이_전부_실재한다():
    """함수 안 import 는 테스트가 안 잡는다 — 서버에서만 터진다.

    실제로 11번가를 `fetch_orders` 로 적었다가(진짜 이름은 iter_orders)
    여기서 잡았다.
    """
    import importlib
    required = {
        "shared.platforms.lotteon.products": ["get_product_detail", "extract_items"],
        "shared.platforms.esm.inventory": ["get_recommended_options", "_option_id_of"],
        "shared.platforms.eleven11.orders": ["iter_orders"],
        "shared.platforms.eleven11.stocks_query": ["get_stocks"],
    }
    missing = []
    for mod, names in required.items():
        m = importlib.import_module(mod)
        missing += [f"{mod}.{n}" for n in names if not hasattr(m, n)]
    assert not missing, f"없는 심볼: {missing}"


def test_discover도_게이트가_막는다(client, monkeypatch):
    monkeypatch.delenv("UPLOAD_RATE_PROBE", raising=False)
    assert client.get("/api/upload-rate-probe/discover?market=lotteon").status_code == 404


def test_discover는_연동이력_있는_마켓을_되돌려보낸다(client, monkeypatch):
    """쿠팡·스스는 /targets 가 정본 — discover 로 중복 경로를 만들지 않는다."""
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R
    monkeypatch.setattr(R, "_client", lambda *a, **k: object())
    r = client.get("/api/upload-rate-probe/discover?market=coupang")
    assert r.status_code == 400
    assert "/targets" in r.get_json()["error"]


def test_discover_실패는_빈목록으로_위장하지_않는다(client, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_PROBE", "1")
    import webapp.routes.upload_rate_probe as R

    class _Cli:
        _cfg = {}
        def request(self, **k):
            raise RuntimeError("boom")
    monkeypatch.setattr(R, "_client", lambda *a, **k: _Cli())
    r = client.get("/api/upload-rate-probe/discover?market=lotteon")
    assert r.status_code == 500
    assert "boom" in r.get_json()["error"]

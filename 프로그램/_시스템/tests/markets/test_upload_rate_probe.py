"""업로드 속도 한도 실측 프로브 — 안전선 테스트.

★ 실제 마켓에 접속하지 않는다. 전부 모의.
★ 여기서 고정하는 선:
   ① 가격 필드는 절대 전송에 섞이지 않는다 (가격 오류 = 즉시 금전 손실)
   ② 현재 재고를 못 읽으면 쓰지 않는다 (무변화를 보장할 수 없으므로)
   ③ 429 를 다른 오류와 섞지 않는다 (403 을 429 로 읽으면 없는 한도를 날조한다)
   ④ 원래 값을 기억하고 원복할 수 있다
"""
import pytest

from lemouton.markets import upload_rate_probe as P


class _Resp:
    def __init__(self, status=200, headers=None, text="{}"):
        self.status_code = status
        self.headers = headers or {}
        self.text = text


class _Err(Exception):
    def __init__(self, status_code, message="", body=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


# ── ③ 429 판정 ──────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    (429, True), (200, False), (403, False), (401, False), (500, False),
])
def test_429만_한도초과로_센다(status, expected):
    assert P.is_rate_limited(status) is expected


def test_상태코드는_예외에서_뽑는다():
    assert P.status_of_exception(_Err(429)) == 429
    assert P.status_of_exception(_Err(403)) == 403


def test_상태코드_없는_예외는_None():
    """네트워크 오류 등 — 한도로 오해하면 안 된다."""
    assert P.status_of_exception(RuntimeError("boom")) is None


def test_스마트스토어_전용_429예외도_인식한다():
    class SmartStoreRateLimitError(Exception):
        pass
    e = SmartStoreRateLimitError("429 quota")
    assert P.status_of_exception(e) == 429


# ── ② 무변화 보장 ───────────────────────────────────────────────

def test_현재값을_못읽으면_쓰지_않는다(monkeypatch):
    wrote = []
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: None)
    monkeypatch.setattr(P, "write_stock", lambda *a, **k: wrote.append(1))

    r = P.noop_write("coupang", client=object(),
                     product_id="P", option_id="O")
    assert wrote == [], "현재값을 모르는데 썼다 — 무변화 보장 불가"
    assert r.status is None
    assert "현재" in (r.error or "")


def test_읽은_값_그대로_쓴다(monkeypatch):
    sent = []
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 7)
    monkeypatch.setattr(P, "write_stock",
                        lambda market, *, client, product_id, option_id, stock:
                        sent.append(stock) or _Resp(200))

    r = P.noop_write("coupang", client=object(), product_id="P", option_id="O")
    assert sent == [7], f"읽은 값(7)과 다른 값을 보냈다: {sent}"
    assert r.status == 200
    assert r.is_rate_limited is False


def test_무변화_쓰기가_429면_한도초과로_기록한다(monkeypatch):
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 3)

    def boom(*a, **k):
        raise _Err(429, "too many")
    monkeypatch.setattr(P, "write_stock", boom)

    r = P.noop_write("lotteon", client=object(), product_id="P", option_id="O")
    assert r.status == 429 and r.is_rate_limited is True


def test_403은_한도초과가_아니다(monkeypatch):
    """IP 미등록을 한도로 읽으면 없는 상한을 날조한다."""
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 3)

    def boom(*a, **k):
        raise _Err(403, "ip not allowed")
    monkeypatch.setattr(P, "write_stock", boom)

    r = P.noop_write("lotteon", client=object(), product_id="P", option_id="O")
    assert r.status == 403 and r.is_rate_limited is False


# ── ① 가격 미포함 ───────────────────────────────────────────────

def test_쓰기_인자에_가격이_없다(monkeypatch):
    captured = {}
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 5)

    def cap(market, *, client, product_id, option_id, stock):
        captured.update(market=market, product_id=product_id,
                        option_id=option_id, stock=stock)
        return _Resp(200)
    monkeypatch.setattr(P, "write_stock", cap)

    P.noop_write("smartstore", client=object(), product_id="P", option_id="O")
    assert not (set(captured) & {"price", "sale_price", "salePrice", "new_price"})


def test_스마트스토어_본문에_판매가를_넣지_않는다():
    """edit_options 는 sale_price=None 이면 현재값 유지 — 반드시 None 이어야 한다."""
    import inspect
    src = inspect.getsource(P.write_stock)
    assert "sale_price" not in src or "sale_price=None" in src, \
        "판매가를 명시 전달하는 코드가 있다 — 현재값 유지(None)여야 한다"


# ── ④ 기억·원복 ─────────────────────────────────────────────────

def test_기준선은_원래값을_기억한다(monkeypatch):
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 12)
    b = P.Baseline.capture("coupang", client=object(),
                           product_id="P", option_id="O")
    assert b.original_stock == 12
    assert b.market == "coupang"


def test_기준선을_못_잡으면_예외(monkeypatch):
    """원래 값을 모르면 원복이 불가능하므로 시작 자체를 막는다."""
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: None)
    with pytest.raises(P.ProbeUnsafe):
        P.Baseline.capture("coupang", client=object(),
                           product_id="P", option_id="O")


def test_원복은_원래값을_다시_쓴다(monkeypatch):
    sent = []
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 9)
    monkeypatch.setattr(P, "write_stock",
                        lambda market, *, client, product_id, option_id, stock:
                        sent.append(stock) or _Resp(200))
    b = P.Baseline.capture("coupang", client=object(),
                           product_id="P", option_id="O")
    b.restore(client=object())
    assert sent == [9]


def test_원복_검증은_실제로_다시_읽어_확인한다(monkeypatch):
    """썼다고 믿지 않고 조회로 확인한다 (거짓 성공 금지)."""
    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 9)
    monkeypatch.setattr(P, "write_stock", lambda *a, **k: _Resp(200))
    b = P.Baseline.capture("coupang", client=object(),
                           product_id="P", option_id="O")

    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 4)   # 안 돌아옴
    assert b.verify_restored(client=object()) is False

    monkeypatch.setattr(P, "read_stock", lambda *a, **k: 9)
    assert b.verify_restored(client=object()) is True


# ── 토글 ────────────────────────────────────────────────────────

def test_토글은_짝수회에_원래값으로_돌아온다(monkeypatch):
    sent = []
    monkeypatch.setattr(P, "write_stock",
                        lambda market, *, client, product_id, option_id, stock:
                        sent.append(stock) or _Resp(200))
    t = P.Toggler("coupang", client=object(), product_id="P", option_id="O",
                  base_stock=7)
    for _ in range(4):
        t.step()
    assert sent == [8, 7, 8, 7]
    assert t.at_original is True


def test_토글_홀수회는_원복_안됨으로_표시(monkeypatch):
    monkeypatch.setattr(P, "write_stock", lambda *a, **k: _Resp(200))
    t = P.Toggler("coupang", client=object(), product_id="P", option_id="O",
                  base_stock=7)
    t.step()
    assert t.at_original is False


# ── 측정 ────────────────────────────────────────────────────────

def test_버스트는_첫_429직전까지_센다():
    seq = iter([200] * 5 + [429])
    r = P.measure_burst(lambda: P.WriteOutcome(next(seq), None, 0.0),
                        max_calls=50)
    assert r["capacity"] == 5 and r["hit_429"] is True


def test_버스트가_429를_못보면_상한미도달로_보고한다():
    r = P.measure_burst(lambda: P.WriteOutcome(200, None, 0.0), max_calls=6)
    assert r["hit_429"] is False and r["capacity"] == 6
    assert "미도달" in r["note"]


def test_버스트는_429아닌_오류에서_중단하고_판별불가로_남긴다():
    """403·500 을 상한으로 읽으면 안 된다."""
    seq = iter([200, 200, 403])
    r = P.measure_burst(lambda: P.WriteOutcome(next(seq), None, 0.0),
                        max_calls=50)
    assert r["hit_429"] is False
    assert "403" in r["note"]


def test_램프업은_첫_실패_직전_계단을_안전상한으로_잡는다():
    r = P.ramp_up(lambda rate: rate <= 4.0, steps=(0.5, 1, 2, 3, 5, 8))
    assert r["last_ok"] == 3 and r["first_fail"] == 5


def test_램프업이_전부_통과하면_상한미도달():
    r = P.ramp_up(lambda rate: True, steps=(0.5, 1, 2))
    assert r["last_ok"] == 2 and r["first_fail"] is None


def test_권고치는_안전마진을_곱한다():
    assert P.recommended_rate(4.0, margin=0.7) == pytest.approx(2.8)


# ── 지연 import 심볼 실재 확인 ──────────────────────────────────

def test_지연_import_심볼이_전부_실재한다():
    """함수 안에서 import 하는 이름은 테스트가 안 잡는다 — 서버에서만 터진다.

    실제로 `fetch_stocks`·`_site_qty_of` 를 없는 이름으로 적었다가 여기서 잡았다.
    """
    import importlib

    required = {
        "shared.platforms.coupang.inventory": ["get_quantity"],
        "shared.platforms.smartstore.get_options": ["fetch_product_options"],
        "shared.platforms.smartstore.edit_product": ["edit_options"],
        "shared.platforms.lotteon.products": ["get_product_detail", "extract_items"],
        "shared.platforms.eleven11.stocks_query": ["get_stocks"],
        "shared.platforms.eleven11.inventory": ["_PATH_STOCKQTY", "_xml_escape"],
        "shared.platforms.esm.inventory": [
            "get_recommended_options", "_option_id_of", "_set_site_qty"],
        "shared.platforms.esm.products": ["site_field", "_ci_get"],
    }
    missing = []
    for mod, names in required.items():
        m = importlib.import_module(mod)
        missing += [f"{mod}.{n}" for n in names if not hasattr(m, n)]
    assert not missing, f"없는 심볼: {missing}"


def test_마켓별_설정_경로키가_실재한다():
    """paths 키 오타도 서버에서만 터진다."""
    from shared.platforms import COUPANG, LOTTEON
    assert "update_quantity" in COUPANG["paths"]
    assert "get_inventory" in COUPANG["paths"]
    assert LOTTEON["paths"].get("stock_change")

"""「순차 필수」를 코드가 실제로 강제한다 (화면 배지 말고).

2026-07-20 발견: 판매처 지도에 11번가는 「계정 순차 조회 필수 — 병렬 시 429
전체 다운」이라고 적혀 있는데, 실제 주문조회는 **계정 2개를 동시에** 때리고
있었다. 지도를 읽는 판정 함수(`must_be_sequential`)는 이미 있었지만
**화면 배지에만** 쓰였고, 호출부는 별도 하드코딩 표(`_ACCOUNT_WORKERS`)만 봤다.

★ 이 파일이 지키는 선: 표와 지도가 어긋나면 **엄격한 쪽**이 이긴다.
"""
from lemouton.markets.order_export import _ACCOUNT_WORKERS, account_workers
from lemouton.uploader.market_concurrency import must_be_sequential


# ── 🔴 지도가 「순차」라 한 마켓 ────────────────────────────────

def test_11번가는_계정_동시호출_금지():
    """이게 깨져 있었다 — 표에 2 로 적혀 병렬로 나갔다."""
    assert account_workers("eleven11") == 1


def test_스마트스토어도_순차():
    assert account_workers("smartstore") == 1


def test_표를_올려도_지도가_이긴다():
    """누가 나중에 표만 고쳐도 병렬로 새지 않아야 한다."""
    assert _ACCOUNT_WORKERS["eleven11"] >= 1        # 표에는 값이 남아 있어도
    assert account_workers("eleven11") == 1         # 실제로는 1


def test_지도가_순차라_한_마켓은_전부_1():
    for m in ("smartstore", "coupang", "lotteon", "eleven11", "auction", "gmarket"):
        if must_be_sequential(m):
            assert account_workers(m) == 1, f"{m} 이 병렬로 나간다"


# ── 병렬이 허용된 마켓은 그대로 ─────────────────────────────────

def test_쿠팡은_병렬_유지():
    """5 req/s 토큰버킷 = 속도 제한이지 동시 금지가 아니다."""
    assert account_workers("coupang") == 2


def test_옥션_G마켓은_계정별_버킷이라_병렬_유지():
    """2026-07-20 라이브 실측 — ESM 5초/1회는 판매자 계정별로 따로 센다."""
    assert account_workers("auction") == 3
    assert account_workers("gmarket") == 3


def test_롯데온은_병렬_유지():
    """IP 등록은 동시성과 무관하다 — 섞어 읽으면 멀쩡한 마켓이 느려진다."""
    assert account_workers("lotteon") == 3


# ── 가장자리 ────────────────────────────────────────────────────

def test_모르는_마켓은_1():
    """표에도 지도에도 없으면 가장 안전한 쪽으로."""
    assert account_workers("없는마켓") == 1


def test_지도를_못_읽어도_죽지_않는다(monkeypatch):
    """지도 파일이 깨져도 조회는 돌아야 한다 — 상한표로 폴백."""
    import lemouton.uploader.market_concurrency as mc
    monkeypatch.setattr(mc, "must_be_sequential",
                        lambda m: (_ for _ in ()).throw(RuntimeError("지도 손상")))
    assert account_workers("coupang") == 2


def test_0이나_음수로_내려가지_않는다():
    assert account_workers("smartstore") >= 1

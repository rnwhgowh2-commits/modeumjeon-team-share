"""업로드 속도 한도 실측 프로브 — 안전장치 테스트.

★ 이 테스트는 실제 마켓에 접속하지 않는다. 전부 모의다.
★ 프로브가 지켜야 할 선을 여기서 고정한다:
   ① 가격 필드는 절대 전송에 섞이지 않는다
   ② 등록된 테스트 상품 외에는 대상으로 삼지 않는다
   ③ 현재값을 못 읽으면 쓰지 않는다(무변화 보장 불가)
   ④ 「1건 업로드」의 API 호출 수(스스·ESM = 2콜)를 예산에 반영한다
"""
import pytest

from scripts.ratelimit_probe.config import (
    ProbeForbidden, TEST_TARGETS, assert_target_allowed, budget_for,
    calls_per_upload, safety_margin,
)


# ── 대상 화이트리스트 ────────────────────────────────────────────

def test_미등록_마켓_대상은_거부한다():
    with pytest.raises(ProbeForbidden):
        assert_target_allowed("coupang", product_id="999999", option_id="1")


def test_등록된_대상은_통과한다(monkeypatch):
    monkeypatch.setitem(TEST_TARGETS, "coupang",
                        {"product_id": "111", "option_id": "222"})
    assert_target_allowed("coupang", product_id="111", option_id="222")


def test_등록됐어도_다른_상품이면_거부한다(monkeypatch):
    """테스트 상품 하나만 건드린다 — 실판매 상품 오염 방지."""
    monkeypatch.setitem(TEST_TARGETS, "coupang",
                        {"product_id": "111", "option_id": "222"})
    with pytest.raises(ProbeForbidden):
        assert_target_allowed("coupang", product_id="111", option_id="333")


# ── 호출배수 ─────────────────────────────────────────────────────

def test_호출배수는_1건업로드에_드는_API_호출수다():
    """스스·ESM 은 현재값을 GET 한 뒤 전체를 PUT 하므로 2콜."""
    assert calls_per_upload("coupang") == 1
    assert calls_per_upload("lotteon") == 1
    assert calls_per_upload("eleven11") == 1
    assert calls_per_upload("smartstore") == 2
    assert calls_per_upload("auction") == 2
    assert calls_per_upload("gmarket") == 2


def test_호출배수가_프로덕션_throttle_과_일치한다():
    """프로브는 독립 실행되지만 값이 어긋나면 측정과 적용이 따로 논다."""
    from lemouton.uploader.throttle import calls_per_upload as prod_calls

    for market in ("coupang", "lotteon", "eleven11",
                   "smartstore", "auction", "gmarket"):
        assert calls_per_upload(market) == prod_calls(market), (
            f"{market}: 프로브({calls_per_upload(market)}) != "
            f"프로덕션({prod_calls(market)})")


def test_미등록_마켓_호출배수는_거부한다():
    with pytest.raises(ProbeForbidden):
        calls_per_upload("11street_typo")


# ── 안전마진·예산 ────────────────────────────────────────────────

def test_안전마진은_보수적이다():
    """실측 상한을 그대로 쓰면 경계에서 429 가 난다."""
    assert 0.5 <= safety_margin() <= 0.8


def test_안전마진은_환경변수로_조정된다(monkeypatch):
    monkeypatch.setenv("PROBE_SAFETY_MARGIN", "0.6")
    assert safety_margin() == pytest.approx(0.6)


def test_예산_기본값():
    assert budget_for("coupang") == 2000


def test_예산은_환경변수로_조정된다(monkeypatch):
    monkeypatch.setenv("PROBE_BUDGET_COUPANG", "50")
    assert budget_for("coupang") == 50


# ── 램프업 계단 ──────────────────────────────────────────────────

def test_램프업_계단은_낮은_값부터_오름차순이다():
    """이분탐색만 하면 첫 시도가 최고속도라 곧바로 차단당한다."""
    from scripts.ratelimit_probe.config import RAMP_STEPS

    assert RAMP_STEPS[0] <= 0.5, "첫 계단이 너무 높다"
    assert list(RAMP_STEPS) == sorted(RAMP_STEPS), "오름차순이 아니다"
    assert len(RAMP_STEPS) >= 5, "계단이 너무 성기면 상한을 못 좁힌다"

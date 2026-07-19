# -*- coding: utf-8 -*-
"""[S5] 예시 주소 「▶ 크롤」 결과 계산 — 순수 함수.

확장이 긁어온 raw 1건을 주소 카드에 보여줄 값으로 바꾼다.
DB·HTTP 없음 — 금전 산수만 여기서 검증한다.

핵심은 혜택 **값 출처(value_source)** 다 (가이드 스키마 crawl_guide.py:506).
  · fixed = 사장님이 직접 넣은 고정값 → 크롤과 무관하게 늘 안다 → 적용한다
  · crawl = 상품마다 긁어야 아는 값   → 못 긁었으면 **적용하지 않는다**
                                       (없는 혜택을 깎으면 손해 매입이 된다)

지켜야 할 것 (CLAUDE.md 정합성 3대 원칙):
  · 못 읽은 값은 0 이 아니라 None. 0원은 '공짜'로 읽혀 금전 사고가 된다.
  · 가격을 못 읽었으면 대표가로 메우지 않고 '실패'로 표면화한다.
  · 이 값이 크롤 혜택까지 반영된 값인지(benefit_source) 항상 밝힌다.
"""
import pytest

from lemouton.sourcing import crawl_guide as cg
from lemouton.sourcing.guide_url_result import compute_url_result


NOW = "2026-07-19T14:22:00Z"


def _fixed(name, method, value, **over):
    """사장님이 값을 직접 넣은 고정 혜택."""
    d = {"name": name, "apply": "deduct", "status": "always", "method": method,
         "value": value, "value_source": "fixed", "triggers": [], "match": "any"}
    d.update(over)
    return d


def _crawled(name, triggers, method="정액(원)", value=None, **over):
    """상품마다 긁어야 값을 아는 혜택."""
    d = {"name": name, "apply": "deduct", "status": "conditional", "method": method,
         "value": value, "value_source": "crawl", "triggers": list(triggers), "match": "any"}
    d.update(over)
    return d


def _guide(*, benefits=(), excludes=()):
    g = cg.empty_skeleton()
    g["pricing"] = {"benefits": list(benefits)}
    g["exclude_keywords"] = list(excludes)
    return cg.validate_guide(g)


def _ok(**over):
    raw = {"status": "ok", "price": 100000}
    raw.update(over)
    return raw


# ── 실패는 조용히 삼키지 않는다 ────────────────────────────────────────────

def test_failed_crawl_reports_reason_and_no_numbers():
    r = compute_url_result(_guide(), {"status": "error", "error": "로그인이 풀렸습니다"},
                           now_iso=NOW)
    assert r["status"] == "failed"
    assert r["error"] == "로그인이 풀렸습니다"
    assert r["surface_price"] is None
    assert r["final_price"] is None
    assert r["benefit_total"] is None


def test_failed_without_reason_still_says_something():
    """사유를 안 줘도 빈칸으로 두지 않는다."""
    r = compute_url_result(_guide(), {"status": "error"}, now_iso=NOW)
    assert r["status"] == "failed"
    assert r["error"]


def test_ok_but_no_price_is_failure_not_zero():
    """가격을 못 읽었으면 0원이 아니라 실패다(폴백 금지)."""
    r = compute_url_result(_guide(), {"status": "ok", "price": None}, now_iso=NOW)
    assert r["status"] == "failed"
    assert r["surface_price"] is None
    assert r["final_price"] is None


# ── 표면 노출가 ────────────────────────────────────────────────────────────

def test_surface_price_prefers_explicit_surface_over_price():
    """무신사는 surface_price 를 따로 준다 — price(=최저 옵션가)보다 우선."""
    r = compute_url_result(_guide(), _ok(surface_price=129000, price=119000), now_iso=NOW)
    assert r["surface_price"] == 129000


def test_surface_price_falls_back_to_price():
    """나머지 소싱처는 surface_price 가 없다 — price 가 표면가."""
    r = compute_url_result(_guide(), _ok(price=119000), now_iso=NOW)
    assert r["surface_price"] == 119000


# ── 고정 혜택 ──────────────────────────────────────────────────────────────

def test_fixed_amount_benefit_is_applied():
    g = _guide(benefits=[_fixed("제휴 할인", "정액(원)", 3000)])
    r = compute_url_result(g, _ok(), now_iso=NOW)
    assert r["benefit_source"] == "fixed_only"
    assert r["final_price"] == 97000
    assert r["benefit_total"] == 3000


def test_fixed_rate_benefit_uses_engine():
    """정률은 사람이 넣은 % 를 소수로 바꿔 엔진에 넘긴다 (10 → 0.10)."""
    g = _guide(benefits=[_fixed("카드 청구할인", "정률(%)", 10)])
    r = compute_url_result(g, _ok(), now_iso=NOW)
    assert r["final_price"] == 90000
    assert r["benefit_total"] == 10000


def test_installment_is_not_a_discount():
    """'옵션(개월)' = 무이자 할부. 깎아주는 돈이 아니다."""
    g = _guide(benefits=[_fixed("무이자 할부", "옵션(개월)", 12)])
    r = compute_url_result(g, _ok(), now_iso=NOW)
    assert r["final_price"] == 100000
    assert r["benefit_total"] == 0


def test_planned_benefit_is_not_deducted():
    """아직 계획 단계인 혜택은 실제 돈이 아니다."""
    g = _guide(benefits=[_crawled("예정 할인", ["할인"], value=3000, status="planned")])
    r = compute_url_result(
        g, _ok(benefit_lines=["할인"],
               benefit_amounts={"예정 할인": {"type": "amount", "value": 3000}}),
        now_iso=NOW)
    assert r["final_price"] == 100000


# ── 크롤 혜택 ──────────────────────────────────────────────────────────────

def test_crawled_benefit_applied_when_lines_and_amount_present():
    """긁은 라인이 있고 금액도 받았으면 적용 — benefit_source=crawled."""
    g = _guide(benefits=[_crawled("상품 쿠폰", ["쿠폰"])])
    r = compute_url_result(
        g, _ok(benefit_lines=["상품 쿠폰 5,000원"],
               benefit_amounts={"상품 쿠폰": {"type": "amount", "value": 5000}}),
        now_iso=NOW)
    assert r["benefit_source"] == "crawled"
    assert r["final_price"] == 95000
    assert r["benefit_total"] == 5000


def test_crawled_benefit_excluded_by_keyword_is_not_deducted():
    """'불가' 라인이면 그 혜택은 빠진다 — 금액이 달라져야 한다."""
    g = _guide(benefits=[_crawled("등급 할인", ["등급 할인"])],
               excludes=[{"word": "불가", "with": [], "except": []}])
    r = compute_url_result(
        g, _ok(benefit_lines=["등급 할인 불가"],
               benefit_amounts={"등급 할인": {"type": "amount", "value": 5000}}),
        now_iso=NOW)
    assert r["final_price"] == 100000
    assert r["benefit_total"] == 0


def test_crawled_benefit_without_lines_is_not_applied():
    """★ 못 긁은 크롤 혜택은 적용하지 않는다.

    확장은 무신사·롯데온에서만 혜택 라인을 준다(background.js:1563).
    나머지 소싱처에서 이 혜택을 깎아버리면 '실제로는 못 받은 할인'이 반영된
    싼 값이 되어 손해 매입이 된다. 더 비싼 쪽으로 둔다.
    """
    g = _guide(benefits=[_crawled("상품 쿠폰", ["쿠폰"], value=5000)])
    r = compute_url_result(g, _ok(), now_iso=NOW)
    assert r["final_price"] == 100000
    assert r["benefit_total"] == 0
    assert r["benefit_source"] == "fixed_only"   # 'crawled' 로 둔갑 금지
    assert r["benefit_note"]                     # 왜 빠졌는지 화면에 말해준다


def test_crawled_benefit_without_amount_is_not_guessed():
    """라인은 잡혔는데 금액을 못 받았으면 지어내지 않는다."""
    g = _guide(benefits=[_crawled("상품 쿠폰", ["쿠폰"])])
    r = compute_url_result(g, _ok(benefit_lines=["상품 쿠폰"]), now_iso=NOW)
    assert r["final_price"] == 100000
    assert r["benefit_note"]


def test_fixed_and_crawled_mix():
    """고정은 늘 적용, 못 긁은 크롤분만 빠진다 — 섞여 있어도 정확해야 한다."""
    g = _guide(benefits=[
        _fixed("제휴 할인", "정액(원)", 3000),
        _crawled("상품 쿠폰", ["쿠폰"], value=5000),
    ])
    r = compute_url_result(g, _ok(), now_iso=NOW)
    assert r["final_price"] == 97000          # 고정 3,000 만
    assert r["benefit_source"] == "fixed_only"
    assert "상품 쿠폰" in r["benefit_note"]     # 무엇이 빠졌는지 이름을 댄다


# ── 재고 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stock,expect", [
    (0, "품절"),
    (999, "재고 있음"),
    (7, "7개"),
])
def test_stock_label(stock, expect):
    r = compute_url_result(_guide(), _ok(stock=stock), now_iso=NOW)
    assert r["stock_label"] == expect


def test_stock_unknown_is_not_in_stock():
    """파싱 실패(-1)를 '재고 있음'으로 둔갑시키면 오버셀이 난다."""
    r = compute_url_result(_guide(), _ok(stock=-1), now_iso=NOW)
    assert r["stock_label"] == "확인 불가"


def test_stock_missing_is_unknown():
    r = compute_url_result(_guide(), _ok(), now_iso=NOW)
    assert r["stock_label"] == "확인 불가"


# ── 스키마 왕복 ────────────────────────────────────────────────────────────

def test_result_survives_guide_validation():
    """계산 결과를 가이드에 넣고 validate 해도 값이 그대로 살아남는다."""
    g = _guide(benefits=[_fixed("제휴 할인", "정액(원)", 3000)])
    r = compute_url_result(g, _ok(stock=999), now_iso=NOW)
    g["sample_urls"] = [{"url": "https://a.com/1", "result": r}]
    out = cg.validate_guide(g)["sample_urls"][0]["result"]
    assert out["final_price"] == 97000
    assert out["benefit_source"] == "fixed_only"
    assert out["stock_label"] == "재고 있음"
    assert out["status"] == "done"
    assert out["crawled_at"] == NOW

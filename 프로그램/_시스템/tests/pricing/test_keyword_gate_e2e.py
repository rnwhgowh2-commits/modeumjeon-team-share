# -*- coding: utf-8 -*-
"""키워드 게이트 E2E 검증 — 예상(수동) vs 실제(게이트+final_price), 키워드→매입가 변화.

르무통 메이트 (musinsa 4046672) 실제 혜택 라인 + 크롤 금액으로:
  · 게이트가 어떤 혜택을 켜는지 판정
  · 적용 혜택을 final_price 엔진으로 최종 매입가 계산
  · 키워드 설정(A/B)을 바꾸면 매입가가 의도대로 달라지는지
  · 예상값(투명 수동 검산) == 실제값(엔진) 인지

`pytest tests/pricing/test_keyword_gate_e2e.py -s` 로 사람이 읽는 표 출력.
"""
from lemouton.pricing.benefit_gate import gate_benefits
from lemouton.pricing.final_price import compute_final_price


# ── 실데이터 ────────────────────────────────────────────────────────────────
BENEFIT_LINES = [
    "등급 할인 불가", "상품 쿠폰", "적립금 사용", "구매 적립 / 선할인",
    "최대 적립", "10% 추가 적립", "결제혜택", "무신사 회원은 전 품목 무료배송",
]
BASE_PRICE = 126_900   # 회원가(표면 노출가) — 라이브 확인값
CRAWLED = {            # 혜택명 → (type, value)  실제 크롤 시 dynamic_benefits_json 주입
    "등급 할인": ("amount", 0),       # '등급 할인 불가' → 0
    "상품 쿠폰": ("amount", 5_000),
    "구매적립":  ("rate",   0.10),    # '10% 추가 적립'
    "후기적립":  ("rate",   0.01),
    "결제적립":  ("rate",   0.0),
}
EXCLUDES = [{"word": "불가", "with": [], "except": []}]


class Item:
    def __init__(self, name, btype, value, enabled):
        self.id = -1; self.benefit_name = name; self.benefit_type = btype
        self.value = value; self.enabled = enabled
        self.category = None; self.sort_order = 999; self.template_id = None


def _engine_price(benefits, excludes):
    """게이트 → 적용 혜택만 final_price 입력으로 → 최종 매입가 (실제값)."""
    gated = gate_benefits(benefits, BENEFIT_LINES, excludes)
    items = []
    for g in gated:
        bt, v = CRAWLED.get(g["name"], ("amount", 0))
        items.append(("dyn", Item(g["name"], bt, v, enabled=g["applied"])))
    res = compute_final_price(BASE_PRICE, items, base_override=None)
    return gated, res["final_price"]


def _manual_price(gated):
    """예상값 — 투명 수동 검산: 정액 먼저, 그다음 정률 순차곱(직전 잔액 기준)."""
    applied = [(g["name"], *CRAWLED.get(g["name"], ("amount", 0)))
               for g in gated if g["applied"]]
    bal = float(BASE_PRICE)
    for nm, bt, v in sorted(applied, key=lambda x: 0 if x[1] == "amount" else 1):
        bal = max(bal - (v if bt == "amount" else int(bal * v)), 0)
    # [2026-07-02] 엔진과 동일하게 최종 백원 단위 버림
    return (int(bal) // 100) * 100


def _report(title, gated, price):
    print(f"\n── {title}")
    for g in gated:
        bt, v = CRAWLED.get(g["name"], ("amount", 0))
        vs = f"{v*100:g}%" if bt == "rate" else f"{v:,}원"
        print(f"   {g['name']:<7} [{vs:>8}] {'[O]적용' if g['applied'] else '[X]미적용'} - {g['reason']}")
    print(f"   => 최종 매입가: {price:,}원")


# 시나리오 정의
SCEN_A = [
    {"name": "등급 할인", "triggers": ["등급 할인"], "match": "any"},
    {"name": "상품 쿠폰", "triggers": ["쿠폰"], "match": "any"},
    {"name": "구매적립", "triggers": ["적립"], "match": "any"},
    {"name": "후기적립", "triggers": ["후기"], "match": "any"},
    {"name": "결제적립", "triggers": ["결제"], "match": "any"},
]
SCEN_B = [dict(b) for b in SCEN_A]
for _b in SCEN_B:
    if _b["name"] == "구매적립":
        _b["triggers"] = ["적립", "캐시백"]; _b["match"] = "all"   # 캐시백 라인 없음 → 미적용


# ── 테스트 ──────────────────────────────────────────────────────────────────
def test_scenario_A_predicted_equals_actual():
    gated, price = _engine_price(SCEN_A, EXCLUDES)
    _report("시나리오 A · 포함 any + 제외 '불가'", gated, price)
    assert price == _manual_price(gated)                 # 예상 == 실제


def test_scenario_B_predicted_equals_actual():
    gated, price = _engine_price(SCEN_B, EXCLUDES)
    _report("시나리오 B · 구매적립 all[적립+캐시백] 미충족", gated, price)
    assert price == _manual_price(gated)


def test_grade_discount_vetoed_in_both():
    """'등급 할인 불가' → 제외 '불가' veto → 두 시나리오 모두 미적용."""
    for scen in (SCEN_A, SCEN_B):
        gated, _ = _engine_price(scen, EXCLUDES)
        gd = next(g for g in gated if g["name"] == "등급 할인")
        assert gd["applied"] is False


def test_keyword_change_changes_price():
    """핵심: 키워드 설정만 바꿔도 최종 매입가가 달라진다 (게이트가 가격에 영향)."""
    _, pa = _engine_price(SCEN_A, EXCLUDES)
    _, pb = _engine_price(SCEN_B, EXCLUDES)
    print(f"\n   A={pa:,}원  vs  B={pb:,}원   diff={pb-pa:+,}원")
    assert pa != pb
    assert pb > pa     # 구매적립 10% 빠지면 매입가 상승


# ── 혜택별 per-benefit exclude 테스트 (Task 1b-1) ────────────────────────────

def test_line_excluded_by_benefit():
    from lemouton.pricing.benefit_gate import line_excluded_by_benefit as f
    assert f("후기 적립 불가", ["불가"], "any") is True
    assert f("후기 적립", ["불가"], "any") is False
    assert f("A B", ["A", "B"], "all") is True
    assert f("A only", ["A", "B"], "all") is False
    assert f("anything", [], "any") is False        # 빈 excludes → 제외 안 함
    assert f("anything", ["x"], "weird") is False   # 'all' 아니면 any


def test_gate_benefit_per_benefit_exclude():
    from lemouton.pricing.benefit_gate import gate_benefit
    b = {"name": "후기적립", "triggers": ["후기"], "match": "any",
         "excludes": ["불가"], "exclude_match": "any"}
    # "후기" 매칭되지만 "불가"로 혜택별 제외 → applied False
    r = gate_benefit(b, ["후기 적립 불가"], [])
    assert r["applied"] is False
    # 제외 키워드 없는 라인 → applied True
    r2 = gate_benefit(b, ["후기 적립"], [])
    assert r2["applied"] is True

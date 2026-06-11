# -*- coding: utf-8 -*-
"""키워드 게이트 검증 하버스 — 예상값(수동) vs 실제값(프로그램: 게이트 + final_price) 비교.

목적(사용자 2026-06-11):
  르무통 무신사 상품의 실제 혜택 라인에 포함/제외 키워드를 적용 →
  어떤 혜택이 켜지는지(게이트) → 크롤 금액으로 최종 매입가 계산(final_price) →
  키워드 설정을 바꾸면 매입가가 의도대로 달라지는지, 예상==실제 인지 확인.

값 출처(사용자 확정 Q1a): 혜택 금액은 '크롤값' 재사용. 본 하버스는 CRAWLED 딕셔너리로 주입.
실제 라이브 연결(compute_breakdown 수정)은 blast radius 커서 별도 회귀 단계.

실행:  python scripts/verify_keyword_gate.py
"""
from __future__ import annotations
import sys, io, os

# 콘솔 UTF-8 (Windows)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lemouton.pricing.benefit_gate import gate_benefits
from lemouton.pricing.final_price import compute_final_price


# ════════════════════════════════════════════════════════════════════════════
#  실데이터 — 르무통 메이트 (musinsa.com/products/4046672)
# ════════════════════════════════════════════════════════════════════════════

# ① 크롤된 혜택 라인 (2026-06-11 라이브 추출, 게이트 매칭 입력)
BENEFIT_LINES = [
    "등급 할인 불가",
    "상품 쿠폰",
    "적립금 사용",
    "구매 적립 / 선할인",
    "최대 적립",
    "10% 추가 적립",
    "결제혜택",
    "무신사 회원은 전 품목 무료배송",
]

# ② 크롤된 금액 (회원가 base + 혜택별 값). 실제 크롤 시 dynamic_benefits_json 에서 주입.
#    혜택명 → (benefit_type, value).  rate=비율(0.10), amount=원.
BASE_PRICE = 126_900   # 회원가(표면 노출가) — 라이브 확인값
CRAWLED = {
    "등급 할인":  ("amount", 0),       # 이 상품 '등급 할인 불가' → 크롤값 0
    "상품 쿠폰":  ("amount", 5_000),   # 상품쿠폰 정액 (크롤 입력)
    "구매적립":   ("rate",   0.10),    # '10% 추가 적립' → 10%
    "후기적립":   ("rate",   0.01),    # 후기 적립 1% (크롤 입력)
    "결제적립":   ("rate",   0.0),     # 이 상품 결제적립 없음
}


# ════════════════════════════════════════════════════════════════════════════
#  최소 혜택 아이템 (final_price 가 받는 형태)
# ════════════════════════════════════════════════════════════════════════════
class Item:
    def __init__(self, name, btype, value, enabled):
        self.id = -1
        self.benefit_name = name
        self.benefit_type = btype          # 'rate' | 'amount'
        self.value = value
        self.enabled = enabled
        self.category = None
        self.sort_order = 999
        self.template_id = None


def run_scenario(title, benefits, excludes):
    """게이트 → 적용 혜택만 final_price 입력으로 조립 → 최종 매입가."""
    gated = gate_benefits(benefits, BENEFIT_LINES, excludes)

    items = []
    for g in gated:
        nm = g["name"]
        btype, value = CRAWLED.get(nm, ("amount", 0))
        items.append(("dyn", Item(nm, btype, value, enabled=g["applied"])))

    res = compute_final_price(BASE_PRICE, [it for it in items], base_override=None)

    # ── 예상값 수동 계산 (투명 검산): 정액 먼저, 그다음 정률 순차곱 ──
    applied = [(g["name"], *CRAWLED.get(g["name"], ("amount", 0)))
               for g in gated if g["applied"]]
    exp = float(BASE_PRICE)
    for nm, bt, v in sorted(applied, key=lambda x: 0 if x[1] == "amount" else 1):
        exp = max(exp - (v if bt == "amount" else int(exp * v)), 0)
    expected = int(exp)

    print(f"\n── {title} " + "─" * (60 - len(title)))
    for g in gated:
        bt, v = CRAWLED.get(g["name"], ("amount", 0))
        vs = f"{v*100:g}%" if bt == "rate" else f"{v:,}원"
        mark = "✅ 적용" if g["applied"] else "⛔ 미적용"
        print(f"   {g['name']:<8} [{vs:>8}] {mark:<8} — {g['reason']}")
    print(f"   {'─'*54}")
    print(f"   BASE(회원가)      : {BASE_PRICE:,}원")
    print(f"   예상 최종매입가    : {expected:,}원   (수동 검산)")
    print(f"   실제 최종매입가    : {res['final_price']:,}원   (final_price 엔진)")
    ok = expected == res["final_price"]
    print(f"   일치 여부          : {'✅ 일치' if ok else '❌ 불일치'}")
    return res["final_price"], ok


def main():
    print("=" * 64)
    print(" 키워드 게이트 검증 — 르무통 메이트 (musinsa 4046672)")
    print(" 실제 혜택 라인:", " · ".join(BENEFIT_LINES))
    print("=" * 64)

    # 공통 제외: '불가' 단독 제외 (등급 할인 불가 → veto)
    EXCLUDES = [{"word": "불가", "with": [], "except": []}]

    # 시나리오 A — 포함 키워드 느슨(any), 제외 '불가' 적용
    A = [
        {"name": "등급 할인", "triggers": ["등급 할인"], "match": "any"},
        {"name": "상품 쿠폰", "triggers": ["쿠폰"],      "match": "any"},
        {"name": "구매적립",  "triggers": ["적립"],      "match": "any"},
        {"name": "후기적립",  "triggers": ["후기"],      "match": "any"},
        {"name": "결제적립",  "triggers": ["결제"],      "match": "any"},
    ]
    price_A, okA = run_scenario("시나리오 A · 포함 any + 제외 '불가'", A, EXCLUDES)

    # 시나리오 B — 구매적립을 'all'(적립+캐시백 모두) 로 좁힘 → 미적용으로 전환
    B = [dict(b) for b in A]
    for b in B:
        if b["name"] == "구매적립":
            b["triggers"] = ["적립", "캐시백"]
            b["match"] = "all"          # 캐시백 라인 없음 → 미적용 → 매입가 ↑
    price_B, okB = run_scenario("시나리오 B · 구매적립 all[적립+캐시백] (미충족)", B, EXCLUDES)

    # 시나리오 C — 제외 키워드 제거 → 등급 할인 veto 풀림 (단 크롤 금액 0이라 가격 영향 X, 적용 플래그만 변화)
    price_C, okC = run_scenario("시나리오 C · 제외 키워드 없음 (등급할인 veto 해제)", A, [])

    print("\n" + "=" * 64)
    print(" 결과 요약")
    print("=" * 64)
    print(f"   A (구매적립 적용)         : {price_A:,}원")
    print(f"   B (구매적립 all 미충족)    : {price_B:,}원   Δ {price_B-price_A:+,}원")
    print(f"   C (제외 해제)             : {price_C:,}원")
    print(f"   예상==실제 일치           : A={okA} · B={okB} · C={okC}")
    diverged = price_A != price_B
    print(f"   키워드 설정→매입가 변화    : {'✅ 변함(게이트 작동)' if diverged else '❌ 동일'}")
    allok = okA and okB and okC and diverged
    print(f"\n   ▶ 로직 정상 작동 판단: {'✅ PASS' if allok else '❌ FAIL'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())

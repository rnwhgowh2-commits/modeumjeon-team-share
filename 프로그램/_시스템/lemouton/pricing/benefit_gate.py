"""소싱처 크롤링 가이드 ③ — 포함/제외 키워드 게이트 (순수 함수, DB·요청 의존 없음).

가이드 ③ 의 혜택 규칙(benefits[].triggers + match)과 공통 제외 키워드(exclude_keywords)를
**크롤된 혜택 라인 리스트**에 적용해, "이 상품에서 어떤 혜택이 실제로 적용되는가"를 판정한다.

설계 근거:
  - lemouton/sourcing/crawl_guide.py
      · benefits[].triggers (포함 키워드, list[str])
      · benefits[].match   ('any'=1개 이상 포함 / 'all'=모두 포함)
      · exclude_keywords   [{word, with[], except[]}]  (공통)
          with   = 함께 — word 와 같이 있으면 제외
          except = 예외 — 같이 있으면 제외 취소(포함)

핵심 모델 — **라인 기반**:
  크롤된 혜택 텍스트는 라인 리스트다. 예) ["등급 할인 불가", "상품 쿠폰", "구매 적립 / 선할인", ...]
  각 가이드 혜택의 포함 키워드를 라인별로 매칭하고, 제외 규칙이 그 라인을 veto 한다.
  → "등급 할인 불가" 라인은 포함('등급 할인')엔 맞지만 제외('불가')에 걸려 적용 안 됨.

값(%·원)은 본 모듈이 다루지 않는다. 게이트는 **적용 여부(on/off)만** 결정하고,
금액은 크롤된 dynamic_benefits 를 재사용한다(사용자 확정 2026-06-07 Q1a / 2026-06-11 빌드 결정).
"""
from __future__ import annotations

from typing import Optional


# ────────────────────────────────────────────────────────────────────────────
# 포함 (any / all)
# ────────────────────────────────────────────────────────────────────────────

def line_matches_triggers(line: str, triggers: list[str], match: str) -> bool:
    """한 혜택 라인이 포함 키워드 규칙을 통과하는가.

    - triggers 가 비면: 게이트 없음 → 항상 통과(True). (포함 키워드 미설정 = 전부 후보)
    - match == 'all': 모든 trigger 가 라인에 있어야 통과.
    - 그 외('any'): trigger 중 1개 이상이 라인에 있으면 통과.
    """
    line = line or ""
    kws = [t for t in (triggers or []) if t]
    if not kws:
        return True
    if match == "all":
        return all(k in line for k in kws)
    return any(k in line for k in kws)


# ────────────────────────────────────────────────────────────────────────────
# 제외 (word + with / except)
# ────────────────────────────────────────────────────────────────────────────

def line_excluded(line: str, exclude_rules: list[dict]) -> Optional[dict]:
    """한 라인이 공통 제외 규칙에 걸리는가. 걸리면 발동한 규칙 dict, 아니면 None.

    규칙 {word, with[], except[]} 발동 조건:
      1) word 가 라인에 있고
      2) with 가 비었거나(단독 제외) with 키워드 중 1개 이상이 라인에 있고
      3) except 키워드가 라인에 하나도 없을 때  (있으면 제외 취소 → None)
    """
    line = line or ""
    for rule in (exclude_rules or []):
        word = (rule.get("word") or "").strip()
        if not word or word not in line:
            continue
        withs = [w for w in (rule.get("with") or []) if w]
        if withs and not any(w in line for w in withs):
            continue  # with 조건 미충족 → 이 규칙은 발동 안 함
        excepts = [e for e in (rule.get("except") or []) if e]
        if excepts and any(e in line for e in excepts):
            continue  # 예외 키워드 존재 → 제외 취소
        return rule
    return None


# ────────────────────────────────────────────────────────────────────────────
# 혜택별 제외 (per-benefit excludes / exclude_match)
# ────────────────────────────────────────────────────────────────────────────

def line_excluded_by_benefit(line: str, excludes: list[str], exclude_match: str) -> bool:
    """한 라인이 혜택 자체의 excludes 키워드 목록에 걸리는가.

    - excludes 가 비면: 제외 안 함 → False.
    - exclude_match == 'all': 모든 키워드가 라인에 있어야 제외.
    - 그 외('any' 또는 기타): 키워드 중 1개 이상이 라인에 있으면 제외.
    """
    line = line or ""
    kws = [k for k in (excludes or []) if k]
    if not kws:
        return False
    if exclude_match == "all":
        return all(k in line for k in kws)
    return any(k in line for k in kws)


# ────────────────────────────────────────────────────────────────────────────
# 게이트 — 혜택별 적용 판정
# ────────────────────────────────────────────────────────────────────────────

def gate_benefit(benefit: dict, benefit_lines: list[str],
                 exclude_rules: list[dict]) -> dict:
    """한 가이드 혜택을 크롤 라인들에 게이트.

    Returns {
      name, applied(bool), matched_lines[], excluded[{line, rule_word}], reason
    }
    """
    name = benefit.get("name", "")
    triggers = benefit.get("triggers") or []
    match = benefit.get("match") or "any"
    b_excludes = benefit.get("excludes") or []
    b_exmatch = benefit.get("exclude_match") or "any"

    matched, excluded = [], []
    for line in (benefit_lines or []):
        if not line_matches_triggers(line, triggers, match):
            continue
        hit = line_excluded(line, exclude_rules)
        if hit is not None:
            excluded.append({"line": line, "rule_word": hit.get("word")})
        elif line_excluded_by_benefit(line, b_excludes, b_exmatch):
            excluded.append({"line": line, "rule_word": f"[benefit] {b_excludes}"})
        else:
            matched.append(line)

    applied = len(matched) > 0
    if applied:
        reason = f"포함 매칭 라인 {len(matched)}개"
    elif excluded:
        reason = f"포함됐으나 제외 키워드로 veto ({len(excluded)}개 라인)"
    else:
        mode = "모두 포함(all)" if match == "all" else "1개 이상(any)"
        reason = f"포함 키워드 미매칭 [{mode}]"
    return {
        "name": name,
        "applied": applied,
        "matched_lines": matched,
        "excluded": excluded,
        "reason": reason,
    }


def gate_benefits(benefits: list[dict], benefit_lines: list[str],
                  exclude_keywords: list[dict]) -> list[dict]:
    """가이드 혜택 목록 전체를 크롤 라인들에 게이트. 혜택별 판정 리스트 반환."""
    return [gate_benefit(b, benefit_lines, exclude_keywords) for b in (benefits or [])]


def gated_off_names(
    guide_benefits: list[dict],
    benefit_lines: list[str],
    exclude_keywords: list[dict],
) -> set[str]:
    """status=='conditional' 가이드 혜택 중 키워드 매칭에 실패한 항목 이름 집합 반환.

    ★ SAFETY INVARIANT: status != 'conditional' 인 혜택(always / optional / planned)은
    절대 반환 집합에 포함되지 않는다 — 먼저 conditional 만 걸러낸 후 게이트를 돈다.

    Args:
        guide_benefits:  SourceRegistry.crawl_guide['pricing']['benefits'] 목록
        benefit_lines:   크롤된 혜택 텍스트 라인 리스트 (dynamic_benefits['_benefit_lines'])
        exclude_keywords: crawl_guide['exclude_keywords'] 공통 제외 규칙

    Returns:
        set[str] — 비활성화해야 할 혜택 이름 집합.
                   benefit_lines 가 비거나 conditional 혜택이 없으면 빈 집합(no-op).
    """
    if not guide_benefits or not benefit_lines:
        return set()

    # ① conditional 만 필터 — 이 검사가 invariant #1 보장
    conditionals = [b for b in guide_benefits if (b.get('status') or '') == 'conditional']
    if not conditionals:
        return set()

    # ② 게이트 수행
    results = gate_benefits(conditionals, benefit_lines, exclude_keywords or [])

    # ③ 미적용(applied=False)된 항목 이름만 반환 → compute_breakdown 에서 enabled=False
    return {r['name'] for r in results if not r.get('applied')}


# ────────────────────────────────────────────────────────────────────────────
# 상품쿠폰 선택 — 크롤된 쿠폰 목록 중 키워드 살아남은 최고 금액 1개
# ────────────────────────────────────────────────────────────────────────────

def pick_best_coupon(coupons, benefit, exclude_rules=None):
    """상품쿠폰 목록에서 포함/제외 키워드에 살아남은 '최고 금액' 쿠폰 1개.

    coupons: [{'name': str, 'amount': int|float}, ...]  (크롤 원본 전량 = 이미 전부 '상품쿠폰')
    benefit: 가이드의 상품쿠폰 혜택 dict (excludes / exclude_match 사용).
      ★ 적용 키워드(triggers)는 '혜택 라인 식별용'(가격라인 "상품 쿠폰 X원" 찾기)이지
        쿠폰 이름 필터가 아니므로 쿠폰 선택에는 적용하지 않는다. (기본 트리거 '상품 쿠폰'이
        실제 쿠폰명 "…정기 쿠폰 블랙다이아몬드 등급"과 안 맞아 전 쿠폰을 오탈락시키던 버그
        수정 2026-07-05 — 쿠폰 필터는 '제외 키워드'만으로.)
    exclude_rules: 소싱처 공통 제외 규칙(crawl_guide['exclude_keywords']), 선택.
    반환: {'name','amount','candidates':[...],'excluded':[{'name','amount','reason'}]}
          또는 후보 없음 시 None.
    """
    b_excludes = benefit.get('excludes') or []
    b_exmatch = benefit.get('exclude_match') or 'any'
    exclude_rules = exclude_rules or []

    survivors, excluded = [], []
    for c in (coupons or []):
        name = (c.get('name') or '')
        amount = float(c.get('amount') or 0)
        if amount <= 0:
            continue
        hit = line_excluded(name, exclude_rules)
        if hit is not None:
            excluded.append({'name': name, 'amount': amount,
                             'reason': f"공통제외 '{hit.get('word')}'"})
            continue
        if line_excluded_by_benefit(name, b_excludes, b_exmatch):
            excluded.append({'name': name, 'amount': amount, 'reason': '제외 키워드'})
            continue
        survivors.append({'name': name, 'amount': amount})

    if not survivors:
        return None
    best = max(survivors, key=lambda x: x['amount'])
    return {'name': best['name'], 'amount': best['amount'],
            'candidates': survivors, 'excluded': excluded}

"""소싱처 매입가 순차 누적 차감 — 순수 계산(DB 의존 없음).

compute_breakdown(api_benefits.py)의 계산 꼬리를 추출. 동작 100% 동일.
effective: [(kind, item)] where item has .benefit_name/.benefit_type('rate'|'amount')/.value/.enabled

M2b 확장:
- preapplied skip (선반영 항목은 차감 안 하고 items_used 에만 기록)
- tagged-mode: pay_method/channel 태그가 하나라도 있으면 경로 열거 최저가 선택
- 태그 없으면 legacy 경로 (7개 기존 테스트 byte-identical)
"""
from __future__ import annotations
from itertools import product as _product


# ────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ────────────────────────────────────────────────────────────────────────────

def _benefit_priority(it):
    if (it.benefit_type or 'rate') == 'amount':
        return 0
    if '적립' in (it.benefit_name or ''):
        return 1
    return 2


# 이름에 나타나는 **결제수단 표기**. 이게 이름에 있으면 "그 수단으로 결제해야
# 받는 혜택" 이라는 뜻이라, 캐시백처럼 보여도 결제 택1 그룹에 남아야 한다.
# ('캐시백' 은 여기 없다 — 그 자체는 수단이 아니라 유입경로 축이다.)
_PAYMENT_MEANS_TOKENS = ('카드', '페이', '무신사머니', '청구할인')


def _is_payment(nm):
    # ⚠️ 동작 불변: 토큰 집합은 예전 그대로 (수단 4종 + '캐시백').
    #    '네이버' 제외도 의도된 설계다 — 네이버페이는 카드와 **동시 적용**이라
    #    택1 그룹에 넣으면 안 된다. 고치지 말 것.
    nm = nm or ''
    if '네이버' in nm:
        return False
    return any(t in nm for t in _PAYMENT_MEANS_TOKENS + ('캐시백',))


def _is_cashback(it) -> bool:
    """캐시백(유입경로 축) 항목인가 — 결제카드 축과 **별개**.

    ■ 이 함수가 이 모듈에 있는 이유 (단일 정의)
      legacy 경로(`_compute_legacy` 의 결제 택1)와 tagged 조립부
      (`card_candidates.apply_card_candidates`), 그리고 수기입력 조립부
      (`webapp.routes.bulk.margin`)가 **같은 기준**으로 판정해야 한다. 판정이 두
      벌로 갈라지면 같은 소싱처가 경로에 따라 다른 매입가를 낸다 —
      실제로 그렇게 어긋나 있었고(legacy 만 캐시백을 택1로 잡아먹음), 그래서
      정의를 계산 엔진 한 곳으로 모았다. 다른 모듈은 여기서 import 만 한다.

    ■ 왜 필요한가
      ``_is_payment`` 는 이름에 '캐시백' 이 있으면 True 를 준다. 그 판정을 그대로
      결제 택1 후보에 쓰면 캐시백이 **카드와 상호배타**가 되어, 카드를 고른 경로에서
      캐시백이 통째로 꺼진다(= 매입가 과대).
      확정 계산 모델에서 유입경로(N쇼핑경유 ↔ OK캐시백)와 결제카드는 다른 축이고
      둘 다 적용된다. 설계 문서(2026-06-07-최종매입가-계산엔진-design.md §4)의 세트
      제약도 ①결제 택1 ②naver_via ⟹ 캐시백 off 둘뿐 — 캐시백⟷카드 택1은 없다.

      ⚠ ``_is_payment`` 자체는 고치지 않는다. 시그니처(이름 문자열을 받는다)와
      동작을 유지해야 하는 호출처가 따로 있다. 택1 **후보를 고르는 지점**에서만
      캐시백을 걸러낸다.

    ■ 판정 순서 (근거가 강한 것부터)
      1. ``apply_mode == 'cashback'`` — 명시 태그. 1순위 근거.
      2. apply_mode 가 **다른 값**으로 이미 태깅됨 → 캐시백 아님(태그를 신뢰).
      3. ``category == '캐시백'`` — 태그 없는 legacy 행. 이름 추측이 아니라
         데이터다. scripts/backfill_benefit_apply_mode.py 가 category='캐시백'
         → apply_mode='cashback' 으로 백필하므로 **1번과 같은 진실 원천**이다.
      4. 이름에 '캐시백' — 위 근거가 하나도 없을 때의 최후 수단.

    ■ 경계: '현대카드 캐시백' · '무신사머니 캐시백' 처럼 **결제수단 표기**가 붙은 항목
      이름에 ``_PAYMENT_MEANS_TOKENS`` 가 있으면 캐시백으로 치지 않고 결제 택1에
      남긴다. '현대카드 캐시백' 은 **현대카드로 결제해야** 받고 '무신사머니 캐시백'
      은 **무신사머니로 결제해야** 받는다. 이걸 캐시백 축으로 빼면 삼성카드 경로
      에서도 같이 적용돼 물리적으로 불가능한 조합이 되고, 매입가를 실제보다
      **낮게** 잡는다 → 마진 과대 → 판매가 오설정 → 금전 손실.
      매입가는 낮게 잡는 쪽이 위험하므로, 애매하면 안 깎는(택1 유지) 쪽을 고른다.
      단 1~3번 근거가 있으면 이름과 무관하게 캐시백이다(명시 태그 > 이름 추측).
    """
    mode = getattr(it, 'apply_mode', None)
    if mode == 'cashback':
        return True
    if mode is not None:
        return False
    if (getattr(it, 'category', None) or '').strip() == '캐시백':
        return True
    nm = getattr(it, 'benefit_name', '') or ''
    return '캐시백' in nm and not any(t in nm for t in _PAYMENT_MEANS_TOKENS)


def _is_tagged(effective):
    """pay_method 태그가 하나라도 있거나 naver_via 채널이면 tagged-mode.

    [2026-07-18 M1-4] 기존엔 pay_method 를 ('affiliate_card','naver_pay') **두 값만**
    태그로 인정했다. 결제카드 다중 후보는 pay_method 에 PurchaseCard.key
    (예: 'samsung_select')를 쓰므로 그대로면 legacy 로 떨어져 승자를 잘못 고른다.
    → 'None 이 아니면 태그' 로 넓힌다.

    안전한 이유: 이 컬럼에 값을 **쓰는** 코드·UI 가 코드베이스에 한 곳도 없다
    (전수 grep — 템플릿→override 복사 경로만 존재). 즉 태그를 붙인 적 없는 기존
    소싱처는 여전히 pay_method=None 이라 legacy 로 남고, 이 확장은 M1-4 가 카드
    태그를 붙인 소싱처만 tagged 로 보낸다. 회귀 스냅샷 36케이스가 그 증거다.
    """
    return any(
        getattr(it, 'pay_method', None) is not None
        or getattr(it, 'channel', None) == 'naver_via'
        for _k, it in effective
    )


# ────────────────────────────────────────────────────────────────────────────
# 단일 경로 실행기 (tagged-mode 전용; shared item 객체 불변)
# ────────────────────────────────────────────────────────────────────────────

def _run(sale_price, ordered, active, *, card_enabled, card_issuer, base_override):
    """ordered[(kind,it)] 와 active(kind,it)->bool 을 받아 한 경로의 결과를 반환.

    shared item 객체를 일절 변경하지 않는다 (active callable 로 활성화 판정).
    """
    base = float(base_override if base_override is not None else sale_price)
    steps = []
    items_used = []
    for kind, it in ordered:
        apply_mode = getattr(it, 'apply_mode', None)
        is_preapplied = (apply_mode == 'preapplied')

        _by_card_off = ((not card_enabled) and card_issuer
                        and (card_issuer in (it.benefit_name or '')))
        # 활성화 = base enabled AND active(path 조건) AND not card-off
        # preapplied 는 items_used 기록만, 차감 없음
        if is_preapplied:
            is_effective_enabled = bool(it.enabled) and not _by_card_off
            items_used.append({
                'kind': kind, 'id': it.id, 'name': it.benefit_name,
                'type': it.benefit_type, 'value': float(it.value or 0),
                'category': getattr(it, 'category', None),
                'enabled': is_effective_enabled, 'disabled_by_card_off': _by_card_off,
                'preapplied': True,
            })
            continue  # 차감 없음 — 선반영 항목

        is_effective_enabled = (
            bool(it.enabled) and not _by_card_off and active(kind, it)
        )
        items_used.append({
            'kind': kind, 'id': it.id, 'name': it.benefit_name,
            'type': it.benefit_type, 'value': float(it.value or 0),
            'category': getattr(it, 'category', None),
            'enabled': is_effective_enabled, 'disabled_by_card_off': _by_card_off,
        })
        if not is_effective_enabled:
            continue
        if it.benefit_type == 'rate':
            deduct = int(base * (it.value or 0))
        else:
            deduct = int(it.value or 0)
        deduct = min(deduct, int(base))
        base = max(base - deduct, 0)
        steps.append({
            'name': it.benefit_name, 'type': it.benefit_type,
            'value': float(it.value or 0), 'deduct': deduct, 'base_after': int(base),
        })
    return {
        'sale_price': float(base_override if base_override is not None else sale_price),
        'final_price': int(base),
        'steps': steps,
        'items_used': items_used,
    }


# ────────────────────────────────────────────────────────────────────────────
# Legacy 경로 (태그 없음 — 기존 동작 완전 보존)
# ────────────────────────────────────────────────────────────────────────────

def _compute_legacy(sale_price, effective, *, card_enabled, card_issuer, base_override):
    """기존 compute_final_price 동작 (tagged 필드 없는 항목 집합). 7개 기존 테스트 전용."""
    # 카테고리 정렬 (stable): 정액 → %적립 → %할인
    effective = sorted(effective, key=lambda x: _benefit_priority(x[1]))

    # 결제 수단 택1 (네이버 제외, 차감액 가장 큰 1개만 남김)
    # shared item 객체를 일절 변경하지 않는다 (_run() 과 동일한 원칙).
    # 택1에서 진 항목은 로컬 집합(_pay_losers)으로만 판정한다 — 예전엔 여기서
    # it.enabled = False 로 호출자의 ORM 객체를 영구 변형해, 공유 캐시로 여러 SKU 를
    # 순회하는 bulk_breakdowns 에서 뒤 SKU 의 차감이 통째로 누락됐다.
    #
    # [2026-07-19] 캐시백은 택1 후보에서 제외한다.
    #   _is_payment 는 이름에 '캐시백' 이 있으면 True 를 준다. 그래서 OK캐시백(1.1%)이
    #   현대카드 청구할인(2.73%)과 택1로 경합해 **져서 통째로 안 깎였다** = 매입가 과대.
    #   확정 설계 §4 의 세트 제약은 ①결제 택1 ②naver_via ⟹ 캐시백 off 둘뿐이고,
    #   유입경로(캐시백)와 결제카드는 별개 축이라 **둘 다 누적 차감**되어야 한다.
    #   판정은 tagged 조립부와 **같은 함수**(_is_cashback)를 쓴다 — 두 벌로 갈라지면
    #   같은 소싱처가 태그 유무에 따라 다른 매입가를 낸다.
    #   ※ 제약②는 여기서 처리하지 않아도 된다: channel='naver_via' 항목이 하나라도
    #     있으면 _is_tagged 가 True 라 이 legacy 함수에 애초에 도달하지 않는다.
    _pay = [(k, it) for (k, it) in effective
            if it.enabled and _is_payment(it.benefit_name) and not _is_cashback(it)]
    _pay_losers = set()  # id(it) 집합 — effective 가 살아있는 동안 id 는 안정·고유
    if len(_pay) > 1:
        def _approx_deduct(it):
            v = float(it.value or 0)
            return v if (it.benefit_type or 'rate') == 'amount' else float(sale_price) * v
        _best_it = max((it for _k, it in _pay), key=_approx_deduct)
        _pay_losers = {id(it) for _k, it in _pay if it is not _best_it}

    def _pay_active(it):
        """택1에서 지지 않았는가 (기존 it.enabled=False 변형과 동치)."""
        return id(it) not in _pay_losers

    base = float(base_override if base_override is not None else sale_price)
    steps = []
    items_used = []
    for kind, it in effective:
        apply_mode = getattr(it, 'apply_mode', None)
        is_preapplied = (apply_mode == 'preapplied')

        _by_card_off = ((not card_enabled) and card_issuer
                        and (card_issuer in (it.benefit_name or '')))
        if is_preapplied:
            is_effective_enabled = (
                bool(it.enabled) and not _by_card_off and _pay_active(it)
            )
            items_used.append({
                'kind': kind, 'id': it.id, 'name': it.benefit_name,
                'type': it.benefit_type, 'value': float(it.value or 0),
                'category': getattr(it, 'category', None),
                'enabled': is_effective_enabled, 'disabled_by_card_off': _by_card_off,
                'preapplied': True,
            })
            continue

        is_effective_enabled = (
            bool(it.enabled) and not _by_card_off and _pay_active(it)
        )
        items_used.append({
            'kind': kind, 'id': it.id, 'name': it.benefit_name,
            'type': it.benefit_type, 'value': float(it.value or 0),
            'category': getattr(it, 'category', None),
            'enabled': is_effective_enabled, 'disabled_by_card_off': _by_card_off,
        })
        if not is_effective_enabled:
            continue
        if it.benefit_type == 'rate':
            deduct = int(base * (it.value or 0))
        else:
            deduct = int(it.value or 0)
        deduct = min(deduct, int(base))
        base = max(base - deduct, 0)
        steps.append({
            'name': it.benefit_name, 'type': it.benefit_type,
            'value': float(it.value or 0), 'deduct': deduct, 'base_after': int(base),
        })
    result = {
        'sale_price': float(base_override if base_override is not None else sale_price),
        'final_price': int(base),
        'steps': steps,
        'items_used': items_used,
        'path': None,
    }
    return result


# ────────────────────────────────────────────────────────────────────────────
# Tagged 경로 (경로 열거 최저가)
# ────────────────────────────────────────────────────────────────────────────

def _compute_tagged(sale_price, effective, *, card_enabled, card_issuer, base_override):
    """세트 제약(결제택1 + 네이버경유↔캐시백) 경로를 열거해 최저가 경로를 반환."""
    # 카테고리 정렬 (stable)
    ordered = sorted(effective, key=lambda x: _benefit_priority(x[1]))

    # pay_choice 후보: enabled payment 항목의 distinct pay_method + None(무결제)
    payment_methods = list(dict.fromkeys(
        getattr(it, 'pay_method', None)
        for _k, it in ordered
        if (getattr(it, 'apply_mode', None) == 'payment' and bool(it.enabled)
            and getattr(it, 'pay_method', None) is not None)
    ))
    pay_choices = payment_methods + [None]  # None = 무결제

    # via 후보: naver_via 항목이 있으면 {False,True} 아니면 {False}
    has_naver_via = any(getattr(it, 'channel', None) == 'naver_via' for _k, it in ordered)
    via_choices = [False, True] if has_naver_via else [False]

    best = None
    best_path = None

    for pay_choice, via in _product(pay_choices, via_choices):
        def active(kind, it, _pc=pay_choice, _via=via):
            apply_mode = getattr(it, 'apply_mode', None)
            channel = getattr(it, 'channel', None)
            pay_method = getattr(it, 'pay_method', None)

            # payment 항목: 선택된 pay_choice 와 일치해야 활성
            if apply_mode == 'payment':
                return pay_method == _pc

            # cashback 항목: 네이버경유 시 비활성 (제약②)
            if apply_mode == 'cashback':
                return not _via

            # naver_via 전용 혜택: 경유일 때만 활성
            if channel == 'naver_via':
                return _via

            # 나머지: base enabled (card-off 는 _run 내부에서 처리)
            return True

        res = _run(sale_price, ordered, active,
                   card_enabled=card_enabled, card_issuer=card_issuer,
                   base_override=base_override)
        if best is None or res['final_price'] < best['final_price']:
            best = res
            best_path = {'pay_method': pay_choice, 'naver_via': via}

    best['path'] = best_path
    return best


# ────────────────────────────────────────────────────────────────────────────
# 공개 API
# ────────────────────────────────────────────────────────────────────────────

_FINAL_FLOOR_UNIT = 100  # [2026-07-02] 최종매입가 백원 단위 버림 (사용자 규칙)


def compute_final_price(sale_price, effective, *, card_enabled=True,
                        card_issuer=None, base_override=None) -> dict:
    """effective(조립된 혜택 리스트) → 순차 누적 차감 결과.

    태그 없음(legacy): 기존 동작 100% 보존 + path=None 추가.
    태그 있음(tagged): 세트 제약(결제택1·네이버경유↔캐시백) 경로 열거 → 최저가 반환.

    [2026-07-02] 최종매입가는 백원 단위까지만, 그 이하 버림(floor). 경로 선택(min)은
    버림 전 정확값으로 하고, 헤드라인 final_price 만 최종적으로 floor (경로 승자 불변).
    """
    effective = list(effective)  # 반복 소비 방지 (generator 대응)
    if _is_tagged(effective):
        res = _compute_tagged(sale_price, effective,
                              card_enabled=card_enabled, card_issuer=card_issuer,
                              base_override=base_override)
    else:
        res = _compute_legacy(sale_price, effective,
                              card_enabled=card_enabled, card_issuer=card_issuer,
                              base_override=base_override)
    res['final_price'] = (int(res['final_price']) // _FINAL_FLOOR_UNIT) * _FINAL_FLOOR_UNIT
    return res

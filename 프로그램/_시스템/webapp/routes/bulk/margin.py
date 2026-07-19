# -*- coding: utf-8 -*-
"""대량등록 수기 입력 — 최종매입가·마진 미리보기 (Phase 1B M2).

■ 이 파일이 하는 일 / 하지 않는 일
  하는 일  : 소싱처 혜택 템플릿 + 사용자가 화면에서 고른 4개 값(유입경로·결제카드·
             네이버페이·캐시백)을 **혜택 항목 리스트로 조립**한다.
  안 하는 일: 금액 계산. 산수는 전부 ``lemouton.pricing.final_price.compute_final_price``
             (= compute_breakdown 이 쓰는 바로 그 엔진)가 한다. 여기에는 곱셈·버림·
             반올림이 한 줄도 없다. 프론트(JS)에도 없다 — 파이썬과 어긋나는 순간
             화면 금액과 업로드 금액이 달라지기 때문(이 저장소에 전례가 있다).

■ 왜 compute_breakdown 을 직접 부르지 않나
  compute_breakdown 의 시그니처는 ``(sku, source_id, sale_price)`` 이고, 내부 대부분이
  **크롤된 상품**(OptionSourceUrl → SourceProduct.dynamic_benefits_json)을 찾는 일이다.
  수기 입력 상품은 sku 도 크롤 스냅샷도 없어 그 경로가 전부 빈손으로 끝난다. 게다가
  compute_breakdown 에는 "이 카드로 결제한다" 같은 **사용자 선택을 주입할 인자가 없다**.
  → 그래서 조립만 여기서 하고, 계산은 같은 엔진(compute_final_price)에 넘긴다.
  조립 재료도 새로 만들지 않고 기존 것을 그대로 쓴다:
     · 소싱처 기본 혜택 = ``SourceBenefitTemplate`` (compute_breakdown 과 같은 쿼리·정렬)
     · 카드 적립 항목   = ``card_candidates.CardBenefit``  (M1-4 가 만든 클래스)
     · 결제 항목 태깅   = ``card_candidates.TaggedProxy``  (M1-4 가 만든 클래스)
     · 결제성 판정      = ``final_price._is_payment``      (legacy 와 같은 기준)

■ 원본을 절대 변형하지 않는다 (M1-3 사고 재발 방지)
  ``SourceBenefitTemplate`` 은 ORM 행이다. 여기서 ``it.enabled = False`` 를 쓰면 같은
  세션의 다른 계산까지 오염된다. 그래서 끄고 켤 때는 항상 ``_Choice`` 복사본을 만든다.

■ 폴백 금지
  고른 값을 반영할 근거(소싱처 혜택 행·카드 마스터)가 없으면 **추정치를 만들지 않는다**.
  경고로 드러내고 그 항목은 0으로 두지도 않는다(애초에 항목을 만들지 않는다).
"""
from __future__ import annotations

from flask import jsonify, request

from shared.db import SessionLocal
from lemouton.sourcing.models import SourceBenefitTemplate
from lemouton.sourcing.models_pricing import SourceRegistry
# _is_cashback 은 계산 엔진에 **단 하나만** 정의돼 있다(final_price). 여기서 사본을
# 만들면 조립부와 엔진이 다른 기준으로 캐시백을 판정해, 화면 미리보기와 실제 매입가가
# 갈린다 — 이 저장소가 가장 경계하는 '조용한 실패'다. 재정의하지 말 것.
from lemouton.pricing.final_price import (
    _is_payment, _is_cashback, compute_final_price,
)
from lemouton.pricing.card_candidates import CardBenefit, TaggedProxy
from lemouton.margin.purchase_card_store import list_cards
from lemouton.registration.compile_common import coerce_int, CompileError
from . import bp


# ── 선택지 상수 ───────────────────────────────────────────────────────────────
#   '' (빈 문자열) = "소싱처 기본값" — 사용자가 고르지 않았다는 뜻. 아무것도 덮지 않는다.
#   'none'        = "없음을 명시적으로 골랐다" — 그 차원의 혜택을 전부 끈다.
INFLOW_CHOICES = ('', 'naver_via', 'cashback', 'none')
NAVER_PAY_CHOICES = ('', 'on', 'off')


class _Choice:
    """혜택 항목의 **복사본** — enabled 만 갈아끼우기 위한 그릇.

    TaggedProxy 와 형제지만 그쪽은 apply_mode/pay_method 를 강제로 덮는 용도라
    '끄기'에는 쓸 수 없다. 슬롯 구성은 엔진이 읽는 속성과 동일하게 맞춘다.
    """

    __slots__ = ('id', 'benefit_name', 'benefit_type', 'value', 'enabled',
                 'category', 'apply_mode', 'pay_method', 'channel',
                 'sort_order', 'template_id')

    def __init__(self, inner, *, enabled=None):
        self.id = getattr(inner, 'id', -1)
        self.benefit_name = getattr(inner, 'benefit_name', '')
        self.benefit_type = getattr(inner, 'benefit_type', 'rate')
        self.value = getattr(inner, 'value', 0.0)
        self.enabled = bool(getattr(inner, 'enabled', True)) if enabled is None else bool(enabled)
        self.category = getattr(inner, 'category', None)
        self.apply_mode = getattr(inner, 'apply_mode', None)
        self.pay_method = getattr(inner, 'pay_method', None)
        self.channel = getattr(inner, 'channel', None)
        self.sort_order = getattr(inner, 'sort_order', 0)
        self.template_id = getattr(inner, 'template_id', None)


# ── 항목 분류 (이름·태그 기준 — 엔진과 같은 판정) ─────────────────────────────
def _is_naver_pay(it) -> bool:
    """네이버페이 적립 항목.

    ⚠️ ``_is_payment`` 가 '네이버' 를 False 로 돌려주는 건 의도된 설계다(네이버페이는
    카드와 **동시 적용**). 그래서 결제카드 축과 별개 축으로 따로 본다.
    """
    return '네이버' in (getattr(it, 'benefit_name', '') or '')


def _is_naver_via(it) -> bool:
    return getattr(it, 'channel', None) == 'naver_via'


def _is_card(it) -> bool:
    """결제카드 축 항목 (네이버페이·캐시백 제외)."""
    if _is_naver_pay(it) or _is_cashback(it):
        return False
    if getattr(it, 'apply_mode', None) == 'payment':
        return True
    return _is_payment(getattr(it, 'benefit_name', '') or '')


def load_templates(session, source_id: int) -> list:
    """소싱처 기본 혜택 — compute_breakdown 과 같은 쿼리·같은 정렬."""
    return (session.query(SourceBenefitTemplate)
            .filter_by(source_id=source_id)
            .order_by(SourceBenefitTemplate.sort_order, SourceBenefitTemplate.id)
            .all())


def build_effective(session, *, source_id: int, choices: dict):
    """소싱처 템플릿 + 사용자 선택 → 엔진에 넣을 (kind, item) 리스트.

    Returns: (effective, warnings)
      warnings 는 "고른 값을 반영하지 못했다"는 사실을 화면에 드러내기 위한 것.
      조용히 넘어가면 사용자는 반영된 줄 안다(= 이 저장소가 가장 경계하는 조용한 실패).
    """
    warnings: list[str] = []
    tpls = load_templates(session, source_id)

    card_key = (choices.get('card_key') or '').strip()
    inflow = (choices.get('inflow') or '').strip()
    naver_pay = (choices.get('naver_pay') or '').strip()
    cashback_name = (choices.get('cashback_name') or '').strip()

    # ── 결제카드 ────────────────────────────────────────────────────────────
    chosen_card = None
    if card_key and card_key != 'none':
        chosen_card = next((c for c in list_cards(session) if c.key == card_key), None)
        if chosen_card is None:
            # 없는 카드 키 = 화면·DB 불일치. 추정하지 않고 계산을 멈춘다.
            raise ValueError(f'등록되지 않은 결제카드입니다: {card_key}')

    effective = []
    seen = {'naver_pay': False, 'naver_via': False, 'cashback': False,
            'card_tagged': False, 'card_untagged': 0}

    for tpl in tpls:
        enabled = None  # None = 템플릿 값 그대로

        if _is_naver_pay(tpl):
            seen['naver_pay'] = True
            if naver_pay == 'on':
                enabled = True
            elif naver_pay == 'off':
                enabled = False

        elif _is_cashback(tpl):
            seen['cashback'] = True
            if inflow in ('naver_via', 'none'):
                enabled = False            # 유입경로가 캐시백이 아니면 캐시백은 안 붙는다
            elif inflow == 'cashback':
                enabled = True
            if cashback_name == 'none':
                enabled = False
            elif cashback_name and cashback_name != (tpl.benefit_name or ''):
                enabled = False            # 캐시백은 택1 — 고른 것 외에는 끈다

        elif _is_naver_via(tpl):
            seen['naver_via'] = True
            if inflow == 'naver_via':
                enabled = True
            elif inflow in ('cashback', 'none'):
                enabled = False

        elif _is_card(tpl):
            pm = getattr(tpl, 'pay_method', None)
            if card_key == 'none':
                enabled = False
            elif chosen_card is not None:
                if pm == chosen_card.key:
                    seen['card_tagged'] = True
                    # 고른 카드의 청구할인 — 적립 항목과 **같은 pay_method** 로 묶여야
                    # 엔진의 경로 열거에서 둘이 함께 활성된다(M1-4 설계).
                    effective.append(('tpl', TaggedProxy(tpl, pay_method=pm)))
                    continue
                # 다른 카드에 묶였거나(pm != key) 태그가 없는 카드 항목(pm is None)은
                # "이 카드로 결제한다"는 사용자 선언과 어긋난다 → 끈다.
                if pm is None:
                    seen['card_untagged'] += 1
                enabled = False

        effective.append(('tpl', _Choice(tpl, enabled=enabled)))

    # ── 고른 카드의 적립율 주입 ─────────────────────────────────────────────
    #   적립율은 소싱처와 무관한 카드 고유값(PurchaseCard = 단일 진실 원천).
    #   청구할인과 별개 항목이고 둘 다 차감된다(사용자 확정).
    if chosen_card is not None:
        rate = float(chosen_card.accrual_rate or 0)
        if rate > 0:
            effective.append(('card', CardBenefit(
                name=f'{chosen_card.label} 적립 {rate * 100:g}%',
                value=rate, pay_method=chosen_card.key,
            )))
        elif not seen['card_tagged']:
            warnings.append(
                f'{chosen_card.label} 은 적립율 0% 이고 이 소싱처에 등록된 청구할인도 '
                f'없어 매입가가 내려가지 않습니다.')

    # ── 반영 못 한 선택 드러내기 ────────────────────────────────────────────
    if naver_pay == 'on' and not seen['naver_pay']:
        warnings.append(
            '네이버페이 적립 항목이 이 소싱처에 없어 반영하지 못했습니다 '
            '— 적립율을 지어내지 않습니다. 「가격계산로직」에서 항목을 추가하세요.')
    if inflow == 'naver_via' and not seen['naver_via']:
        warnings.append(
            'N쇼핑 경유(naver_via) 혜택 항목이 이 소싱처에 없어 반영하지 못했습니다.')
    if inflow == 'cashback' and not seen['cashback']:
        warnings.append(
            '캐시백 혜택 항목이 이 소싱처에 없어 반영하지 못했습니다 '
            '— 캐시백 적립율은 소싱처마다 달라 임의로 넣지 않습니다.')
    if cashback_name and cashback_name != 'none' and not any(
            _is_cashback(t) and (t.benefit_name or '') == cashback_name for t in tpls):
        warnings.append(f'캐시백 항목 「{cashback_name}」 을 이 소싱처에서 찾지 못했습니다.')
    if seen['card_untagged']:
        warnings.append(
            f'카드가 지정되지 않은 결제 혜택 {seen["card_untagged"]}건을 제외했습니다 '
            f'— 어느 카드의 혜택인지 알 수 없어 고른 카드에 붙일 수 없습니다.')
    if not tpls:
        warnings.append(
            '이 소싱처에 등록된 혜택이 하나도 없습니다 — 표면가가 그대로 최종매입가가 됩니다.')

    # ── 카드를 안 고른 경우 = "소싱처에 등록된 혜택만" ───────────────────────
    #   여기서 ``apply_card_candidates`` 를 태우지 않는다. 두 가지 이유:
    #   ① 수기 입력에서 결제카드는 **사용자가 아는 운영 사실**이다(엑셀도 주문 행마다
    #      직접 입력한다). 안 고른 사람에게 "아마 이 카드로 결제하겠지" 하고 적립율을
    #      몰래 깔면 그건 지어낸 금액이다 — 이 저장소의 폴백 금지 원칙에 어긋난다.
    #   ② apply_card_candidates 는 이름에 '캐시백' 이 들어간 항목을 legacy 호환 때문에
    #      결제 택1 경로(__otherN__)로 묶는다. 그러면 OK캐시백이 카드와 **경합**해
    #      한쪽이 죽는다(라이브에서 실제로 재현: 캐시백 2.5% 가 통째로 사라졌다).
    #      캐시백은 카드와 별개 축이고 N쇼핑 경유와만 배타다(사용자 확정 모델).
    #   ⇒ 카드 미선택 시에도 소싱처에 등록된 청구할인 행(pay_method 태그)은 그대로
    #     남아 엔진이 최유리 카드를 고른다. 빠지는 건 '적립율 추정'뿐이고, 그 방향은
    #     매입가를 **낮추는 게 아니라 높이는** 쪽이라 언더프라이싱 위험이 없다.

    return effective, warnings


def compute_manual_margin(session, *, source_id: int, surface_price: int,
                          sale_price=None, choices: dict = None) -> dict:
    """수기 입력 1건의 최종매입가·마진. 산수는 전부 엔진(compute_final_price)."""
    effective, warnings = build_effective(
        session, source_id=source_id, choices=choices or {})
    res = compute_final_price(surface_price, effective)
    out = {
        'surface_price': int(surface_price),
        'final_price': int(res['final_price']),
        'steps': res.get('steps') or [],
        'items_used': res.get('items_used') or [],
        'path': res.get('path'),
        'warnings': warnings,
    }
    # 마진 = 판매가 − 최종매입가. 판매가가 없으면 **0 으로 채우지 않는다** (None = 미입력).
    if sale_price is not None:
        out['sale_price'] = int(sale_price)
        out['margin'] = int(sale_price) - int(res['final_price'])
    else:
        out['sale_price'] = None
        out['margin'] = None
    return out


# ════════════════════════════════════════════════════════════════════════════
#  라우트
# ════════════════════════════════════════════════════════════════════════════
def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


@bp.get('/api/margin-meta')
def margin_meta():
    """드롭다운 재료 — 소싱처 목록 + 결제카드 목록 (+ source_id 주면 그 소싱처 혜택 요약)."""
    sid_raw = request.args.get('source_id')
    s = SessionLocal()
    try:
        sources = (s.query(SourceRegistry)
                   .order_by(SourceRegistry.sort_order, SourceRegistry.id).all())
        out = {
            'ok': True,
            'sources': [{'id': x.id, 'name': x.name} for x in sources],
            'cards': [{'key': c.key, 'label': c.label,
                       'accrual_rate': float(c.accrual_rate or 0)}
                      for c in list_cards(s)],
        }
        if sid_raw:
            try:
                sid = int(sid_raw)
            except (TypeError, ValueError):
                return _err('source_id 는 숫자여야 합니다.')
            tpls = load_templates(s, sid)
            out['cashback_items'] = [
                {'name': t.benefit_name,
                 'type': t.benefit_type,
                 'value': float(t.value or 0)}
                for t in tpls if _is_cashback(t)]
            out['has_naver_pay'] = any(_is_naver_pay(t) for t in tpls)
            out['has_naver_via'] = any(_is_naver_via(t) for t in tpls)
            out['benefit_count'] = len(tpls)
        return jsonify(out)
    finally:
        s.close()


@bp.post('/api/margin-preview')
def margin_preview():
    """표면가 + 소싱처 + 4개 선택 → 최종매입가·마진·영수증(steps).

    실패 시 0원·추정가를 절대 돌려주지 않는다 — 400 + 사유. 화면은 '계산 불가'로 표시.
    """
    p = request.get_json(silent=True) or {}
    try:
        source_id = coerce_int(p.get('source_id'), '소싱처')
        surface_price = coerce_int(p.get('surface_price'), '표면가')
        sale_price = coerce_int(p.get('sale_price'), '판매가')
    except CompileError as e:
        return _err(str(e))
    if source_id is None:
        return _err('소싱처를 선택해 주세요.')
    if not surface_price or surface_price <= 0:
        return _err('표면가를 입력해 주세요.')

    inflow = (p.get('inflow') or '').strip()
    naver_pay = (p.get('naver_pay') or '').strip()
    if inflow not in INFLOW_CHOICES:
        return _err(f'유입경로 값이 올바르지 않습니다: {inflow}')
    if naver_pay not in NAVER_PAY_CHOICES:
        return _err(f'네이버페이 값이 올바르지 않습니다: {naver_pay}')

    s = SessionLocal()
    try:
        try:
            out = compute_manual_margin(
                s, source_id=source_id, surface_price=surface_price,
                sale_price=sale_price,
                choices={'inflow': inflow, 'naver_pay': naver_pay,
                         'card_key': p.get('card_key') or '',
                         'cashback_name': p.get('cashback_name') or ''},
            )
        except ValueError as e:
            return _err(str(e))
        out['ok'] = True
        return jsonify(out)
    finally:
        s.close()

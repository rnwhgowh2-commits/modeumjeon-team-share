# -*- coding: utf-8 -*-
"""2층 계정 설정 읽기 — 마켓 전송 코드의 **단일 창구**.

🔴 되받기 사슬을 여기 한 곳에만 둔다. 호출부마다 `getattr(s, k, None) or s.extra.get(k)`
   식으로 흩어 놓으면 「어느 값이 실제로 나갔나」를 못 쫓는다(이 프로젝트에서 반복적으로
   사고가 났던 형태 — 공용 규칙은 쓰는 곳 전부를 세어야 한다).

읽는 순서:
  ① 공통 컬럼(as_phone·return_fee 등) → ② extra JSON(마켓 전용 칸) → ③ 호출부 기본값
"""
from __future__ import annotations

from lemouton.policy.models import MarketAccountSetting

#: 공통 컬럼 이름 — extra 보다 먼저 본다.
_COLUMNS = frozenset({
    'as_phone', 'as_message', 'return_fee', 'exchange_fee', 'jeju_fee',
    'island_fee', 'tax_type', 'origin_default', 'stock_default',
    'promotion_message',
})


def setting_for(session, upload_account_id: int):
    """그 계정의 설정 한 벌. 아직 안 만들었으면 ``None``."""
    return (session.query(MarketAccountSetting)
            .filter_by(upload_account_id=upload_account_id)
            .one_or_none())


def value_of(session, upload_account_id: int, key: str, default=None):
    """설정 값 하나. **안 정했으면** ``default``.

    🔴 「안 정함」은 오직 ``None`` 뿐이다 (2026-08-24 사장님 확정).
      0 과 빈 문자열은 **사장님이 그렇게 정한 값**이라 그대로 돌려준다.
      예전에는 ``got in (None, '')`` 로 빈 문자열까지 「안 정함」 취급했는데,
      그러면 「A/S 안내를 일부러 비워 둠」과 「아직 안 씀」이 구분되지 않는다.

    ★ 0 을 「없음」으로 바꾸지 않는다 — 반품비 0원(무료 반품)과 미설정은 다른 뜻이고,
      배송비는 금전 직결이라 이 혼동이 곧 손실이다.
    """
    s = setting_for(session, upload_account_id)
    if s is None:
        return default
    if key in _COLUMNS:
        got = getattr(s, key)
        return default if got is None else got
    return (s.extra or {}).get(key, default)


def is_set(session, upload_account_id: int, key: str) -> bool:
    """그 칸을 **정한 적이 있나**. 0·빈 문자열도 「정한 것」으로 센다.

    화면이 「아직 안 정함」 배지를 띄우거나, 전송 게이트가 필수값 누락을 막을 때 쓴다.
    ``value_of(...) == 0`` 으로는 이걸 판정할 수 없다 — 그래서 별도 함수로 둔다.
    """
    s = setting_for(session, upload_account_id)
    if s is None:
        return False
    if key in _COLUMNS:
        return getattr(s, key) is not None
    return key in (s.extra or {})


# ══ [Phase 2 · 2026-08-24] 마켓별 허용 키 ══════════════════════════════════
#
# 왜 화이트리스트인가:
#   `extra` 는 JSON 이라 아무 키나 들어간다. 오타 난 키(`retrunFee`)가 조용히 저장되면
#   화면엔 값이 보이는데 마켓엔 안 나가고, 「왜 안 먹지」로 한참 헤맨다. 이 저장소가
#   반복적으로 겪은 형태라 **저장 창구에서 막는다.**
#
# 출처: docs/superpowers/specs/2026-08-24-2층-계정설정-칸목록.md §2
#   (삼바 settings/config.ts 의 STORE_MARKETS 전수 추출 — 삼바는 이 칸들로 매일 등록한다)
#
# 🔴 자격증명(apiKey·secretKey 등)은 **여기 없다.** 시크릿 단일 원천은 `.env` 다
#   (`lemouton/auth/secrets.py`). 삼바는 DB 에 담지만 우리는 그 설계를 안 따른다.
# 🔴 재고 기본값(stockQuantity)도 **없다.** 「재고는 소싱처 실제 재고로만」이 절대
#   규칙이라, 삼바의 999 기본값을 들이면 없는 재고를 있다고 파는 셈이다.

#: 옥션·G마켓 공용 (ESM) — 두 마켓이 같은 칸을 쓴다. 갈라 두면 한쪽만 저장되는 사고가 난다.
_ESM_KEYS = frozenset({
    'shippingFeeType',    # 무료/유료
    'shippingPlaceNo',    # 출고지 '번호' (주소 아님 — ESM 에 미리 등록해 둔 것)
    'returnPlaceNo',      # 반품/교환지 번호
    'dispatchPolicyNo',   # 배송정책 번호
    'shippingCompanyNo',  # 발송 택배사
    'shippingFee',        # 배송비
})

MARKET_EXTRA_KEYS: dict = {
    'smartstore': frozenset({
        'discountRate', 'returnSafeguard', 'naverShopping',
        'multiPurchaseDiscount', 'multiPurchaseQty', 'multiPurchaseRate',
        'purchasePointEnabled', 'purchasePointRate', 'reviewPointEnabled',
        'reviewTextPoint', 'reviewPhotoPoint',
        'reviewMonthTextPoint', 'reviewMonthPhotoPoint',
    }),
    # 🔴 쿠팡 출고지·반품지는 여기 없다 — `coupang_vendor_settings` 표가 이미 갖고 있고
    #   읽는 곳이 5군데다. 두 벌로 만들면 「어느 출고지로 나갔나」를 못 쫓는다.
    'coupang': frozenset({'discountRate'}),
    'auction': _ESM_KEYS,
    'gmarket': _ESM_KEYS,
    'eleven11': frozenset({
        'sellerType', 'deliveryType', 'deliveryFee', 'discountRate',
        'shipFromAddress', 'returnAddress', 'dispatchTemplateNo',
        'returnExchangeGuide', 'minorRestrict',
        'multiPurchaseDiscount', 'multiPurchaseBasisType',
        'multiPurchaseDiscountMethod', 'multiPurchaseQty', 'multiPurchaseAmt',
        'multiPurchasePeriodEnabled', 'multiPurchaseStartDate', 'multiPurchaseEndDate',
        'llpayPointEnabled', 'llpayPointType', 'llpayPointValue',
    }),
    'lotteon': frozenset({
        'dvCstPolNo', 'dvIslandCstPolNo', 'owhpNo', 'rtrpNo',
        'bundleDelivery', 'dispatchDays',
        'reviewTextPoint', 'reviewPhotoPoint',
        'reviewMonthTextPoint', 'reviewMonthPhotoPoint',
        # 🔴 행사 제외 5칸 — 마켓이 우리 마진을 깎는 행사에서 빠지는 스위치. 금전 직결.
        'ownerDiscountExclude', 'unitCouponExclude', 'deliveryCouponExclude',
        'cmPcsExclude', 'pcsExclude',
    }),
}

#: 마켓 이름 — 오류 문구를 사람 말로 내기 위해
_MARKET_LABEL = {
    'smartstore': '스마트스토어', 'coupang': '쿠팡', 'auction': '옥션',
    'gmarket': 'G마켓', 'eleven11': '11번가', 'lotteon': '롯데ON',
}


class UnknownSettingKey(ValueError):
    """그 마켓에 없는 칸으로 저장하려 했다. 오타를 조용히 삼키지 않는다."""


def allowed_keys(market: str) -> frozenset:
    """그 마켓에서 쓸 수 있는 전용 칸 이름들. 모르는 마켓이면 빈 집합."""
    return MARKET_EXTRA_KEYS.get(str(market or '').strip(), frozenset())


def set_extra(session, upload_account_id: int, market: str, values: dict):
    """마켓 전용 칸을 저장한다. 허용 목록에 없는 키는 **거부**한다.

    🔴 SQLAlchemy 는 JSON 칸을 **제자리에서 고치면 못 알아챈다** — 새 dict 를 통째로
      다시 대입해야 저장된다(이 저장소에서 반복적으로 났던 조용한 저장 실패).
    """
    mk = str(market or '').strip()
    ok = allowed_keys(mk)
    bad = sorted(set(values or {}) - ok)
    if bad:
        raise UnknownSettingKey(
            f'{_MARKET_LABEL.get(mk, mk)} 에 없는 칸입니다: {", ".join(bad)} — '
            f'오타이거나 다른 마켓 칸일 수 있습니다.')

    s = setting_for(session, upload_account_id)
    if s is None:
        s = MarketAccountSetting(upload_account_id=upload_account_id)
        session.add(s)
    merged = dict(s.extra or {})
    merged.update(values or {})
    s.extra = merged          # ★ 통째 대입 — 제자리 수정이면 저장이 조용히 안 된다
    return s

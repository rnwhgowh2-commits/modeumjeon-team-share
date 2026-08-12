# -*- coding: utf-8 -*-
"""쿠팡 쿠폰을 **어느 상품에** 걸 것인가 — 대상 찾기 · 기록 남기기 · 자동연장.

셈과 순서는 `coupon_apply` 가 한다(정본). 여기는 우리 자료와 잇는 자리다:
  · 어느 옵션인가        `SetChannelOption.market_option_id`(= 쿠팡 vendorItemId)
  · 얼마를 깎나          그 구성에 붙은 정책의 `price.discount_*`
  · 결과를 어디 적나     `SetChannel.api_fields['coupang_coupon']`

■ 🔴 대상은 `status='matched'` 뿐
    unmatched·ambiguous·duplicate 는 **우리가 어느 마켓 옵션인지 모르는** 것이다.
    모르는 것에 쿠폰을 걸면 엉뚱한 상품이 깎인다.

■ 🔴 자동연장은 순서가 목숨이다 — **옛 쿠폰 내리기 → 새로 만들기 → 붙이기**
    쿠팡은 쿠폰을 고치지 못한다(문서: 「기존에 발행한 쿠폰을 중지하고 새로운 쿠폰을
    생성해야 합니다」). 그리고 한 옵션은 **쿠폰 하나에만** 붙는다 — 옛 것을 안 내리고
    새로 만들면 옵션이 전부 [CIR08]「이미 다른 쿠폰에 발행」으로 거부된다
    (2026-08-06 라이브 실측). **못 내렸으면 새로 만들지 않는다** — 만들어 봐야
    전부 거부되고 빈 쿠폰만 하나 더 생긴다.

■ 🔴 `api_fields` 는 다른 값이 같이 사는 주머니다
    통째로 덮어쓰지 않는다. 그리고 JSON 칸은 **새 dict 를 통째로 다시 대입**해야
    SQLAlchemy 가 바뀐 걸 안다(제자리에서 고치면 조용히 저장이 안 된다).
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timedelta
from typing import Optional

from lemouton.policy.coupon_apply import apply_coupon
from lemouton.sets.models import SetChannel, SetChannelOption

logger = logging.getLogger(__name__)

#: `SetChannel.api_fields` 안에서 쿠폰 기록이 사는 자리.
COUPON_KEY = 'coupang_coupon'

#: 쿠폰 이름 — 우리가 만든 것을 남의 쿠폰과 가르는 표. 45자 제한(쿠팡 문서).
COUPON_NAME = '모음전 즉시할인'

#: 끝나기 며칠 전부터 다시 걸 것인가.
RENEW_BEFORE_DAYS = 14


def record_of(channel) -> dict:
    """그 채널에 남은 쿠폰 기록. 없으면 빈 dict."""
    return dict(((channel.api_fields or {}).get(COUPON_KEY) or {}))


def targets_for(session, channel) -> list[str]:
    """쿠폰을 붙일 옵션(vendorItemId) — **matched 만**."""
    rows = (session.query(SetChannelOption.market_option_id)
            .filter(SetChannelOption.channel_id == channel.id,
                    SetChannelOption.status == 'matched').all())
    return [str(r[0]).strip() for r in rows if str(r[0] or '').strip()]


def _sale_price(session, channel) -> Optional[int]:
    """경고·배움에 쓸 판매가 — 그 채널 옵션 중 **가장 비싼** 것.

    🔴 가장 싼 것을 쓰면 비율이 커 보여 「거부될 수 있다」 경고를 놓친다.
      거부는 비싼 옵션에서 먼저 난다.
    """
    rows = (session.query(SetChannelOption.mkt_price)
            .filter(SetChannelOption.channel_id == channel.id,
                    SetChannelOption.status == 'matched').all())
    prices = [int(r[0]) for r in rows if r[0]]
    return max(prices) if prices else None


def _discount_for(session, channel) -> Optional[dict]:
    """그 구성 정책의 즉시할인 값. 없으면 None(→ 기본값 100원)."""
    try:
        from lemouton.policy.discount import discount_of
        from lemouton.policy.to_payload import rules_for
        rules, _policy, _origin = rules_for(session, set_id=channel.set_id,
                                            market='coupang')
        return discount_of(rules)
    except Exception as e:                                  # noqa: BLE001
        # 정책을 못 읽는 것과 「할인 없음」은 다르다 — 로그로 남기고 기본값으로 간다.
        logger.warning('[쿠팡쿠폰] 정책 즉시할인 조회 실패 set=%s: %s',
                       channel.set_id, e)
        return None


def _save(session, channel, result: dict, *, sale_price=None, now=None) -> None:
    """결과를 채널에 적는다. 🔴 실패도 적는다 — 안 적으면 「아직 안 해 봤다」와 못 가른다."""
    rec = {
        'ok': bool(result.get('ok')),
        'coupon_id': result.get('coupon_id'),
        'value': result.get('value'),
        'starts_at': result.get('starts_at'),
        'ends_at': result.get('ends_at'),
        'contract_id': result.get('contract_id'),
        'attached': list(result.get('attached') or []),
        'failed_items': list(result.get('failed_items') or []),
        'tried': result.get('tried'),
        'message': result.get('message'),
        'sale_price': sale_price,
        'at': (now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
    }
    # 🔴 통째 대입 — 제자리에서 고치면 SQLAlchemy 가 못 알아채 저장이 안 된다.
    #   그리고 남의 값을 지우지 않도록 기존 주머니를 펼쳐 담는다.
    channel.api_fields = {**(channel.api_fields or {}), COUPON_KEY: rec}
    session.add(channel)
    session.commit()


def run_for_channel(session, channel, *, client, now: Optional[datetime] = None,
                    sleep=_time.sleep, discount: Optional[dict] = None,
                    vendor_id: Optional[str] = None, name: str = COUPON_NAME,
                    poll_times: Optional[int] = None) -> dict:
    """이 채널(구성 × 쿠팡 계정)에 쿠폰을 건다."""
    if channel.market != 'coupang':
        # 스스는 즉시할인 칸이 따로 있다(customerBenefit) — 여기로 태우면 두 번 깎인다.
        return {'ok': False, 'message': '쿠폰은 쿠팡에서만 씁니다 — '
                                        f'이 채널은 {channel.market} 입니다.',
                'attempts': [], 'attached': [], 'failed_items': []}

    ids = targets_for(session, channel)
    price = _sale_price(session, channel)
    if discount is None:
        discount = _discount_for(session, channel)

    vid = vendor_id or _vendor_id_of(client)
    if not vid:
        return {'ok': False, 'message': '쿠팡 판매자ID(vendorId)를 못 읽어 쿠폰을 못 겁니다.',
                'attempts': [], 'attached': [], 'failed_items': []}

    kw = {}
    if poll_times is not None:
        kw['poll_times'] = poll_times
    result = apply_coupon(client, vendor_id=vid, name=name, vendor_item_ids=ids,
                          sale_price=price, discount=discount, now=now,
                          sleep=sleep, **kw)
    _save(session, channel, result, sale_price=price, now=now)
    return result


def renew_channel(session, channel, *, client, now: Optional[datetime] = None,
                  sleep=_time.sleep, vendor_id: Optional[str] = None,
                  name: str = COUPON_NAME, poll_times: Optional[int] = None) -> dict:
    """자동연장 — 🔴 **옛 쿠폰을 먼저 내리고** 새로 만든다.

    못 내렸으면 새로 만들지 않는다. 한 옵션은 쿠폰 하나에만 붙어서, 만들어 봐야
    전부 [CIR08] 로 거부되고 **빈 쿠폰만 하나 더** 생긴다.
    """
    from shared.platforms.coupang.promotions import expire_coupon

    rec = record_of(channel)
    old = rec.get('coupon_id')
    vid = vendor_id or _vendor_id_of(client)
    if not vid:
        return {'ok': False, 'message': '쿠팡 판매자ID(vendorId)를 못 읽어 연장하지 못했습니다.',
                'attempts': [], 'attached': [], 'failed_items': []}
    if old:
        ok = False
        try:
            ok = expire_coupon(client, vid, old)
        except Exception as e:                              # noqa: BLE001
            logger.error('[쿠팡쿠폰] 옛 쿠폰 %s 내리기 실패: %s', old, e)
        if not ok:
            # 🔴 기록을 지우지 않는다 — 옛 쿠폰은 아직 살아 있다.
            return {'ok': False, 'attempts': [], 'attached': [], 'failed_items': [],
                    'message': f'옛 쿠폰({old})을 내리지 못해 새로 만들지 않았습니다. '
                               f'쿠팡 윙에서 직접 내린 뒤 다시 해 주세요 — '
                               f'안 내린 채로 새로 만들면 옵션이 전부 거부됩니다.'}

    # 지난번에 통한 값에서 시작한다 — 100원부터 다시 헤매지 않는다(사장님 「배운다」).
    discount = None
    if rec.get('ok') and rec.get('value'):
        discount = {'value': int(rec['value']), 'unitType': 'WON'}
    return run_for_channel(session, channel, client=client, now=now, sleep=sleep,
                           discount=discount, vendor_id=vid, name=name,
                           poll_times=poll_times)


def due_renewals(session, *, now: Optional[datetime] = None,
                 days: int = RENEW_BEFORE_DAYS) -> list:
    """곧 끝나는(또는 이미 끝난) 쿠폰이 걸린 쿠팡 채널들.

    🔴 「건 적 없는」 채널은 대상이 아니다 — 연장은 **있던 것을 잇는** 일이지
      새로 거는 일이 아니다(새로 걸기는 정책 자동·단추가 한다).
    """
    cut = ((now or datetime.now()) + timedelta(days=int(days))
           ).strftime('%Y-%m-%d %H:%M:%S')
    out = []
    for ch in session.query(SetChannel).filter(SetChannel.market == 'coupang').all():
        rec = record_of(ch)
        if not rec.get('ok') or not rec.get('coupon_id') or not rec.get('ends_at'):
            continue
        if str(rec['ends_at']) <= cut:
            out.append(ch)
    return out


def _vendor_id_of(client):
    """⚠️ vendor_id 는 속성이 아니라 설정 주머니(`_cfg`) 안에 있다 — 2026-08-05 실사고."""
    from shared.platforms.coupang.promotions import vendor_id_of
    return vendor_id_of(client)

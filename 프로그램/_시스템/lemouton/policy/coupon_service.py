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

#: 「걸어 주세요」 요청이 사는 자리(단추·정책 자동이 남기고, 스케줄러가 지운다).
#:   🔴 왜 대기열인가 — 한 번 걸기는 「만들기 → 확인 → 붙이기 → 확인」이고 거부되면
#:     300원까지 최대 21번 되풀이한다. 몇 분이 걸릴 수 있어 **화면이 못 기다린다**.
#:   🔴 「대기열에 넣었다」 ≠ 「처리된다」 — 처리기(`run_pending`)를 같이 넣고
#:     스케줄러에 등록했다. 화면은 `COUPON_KEY` 기록을 읽어 진짜 상태를 말한다.
REQUEST_KEY = 'coupang_coupon_request'

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


def apply_or_renew(session, channel, *, client, now: Optional[datetime] = None,
                   sleep=_time.sleep, vendor_id: Optional[str] = None,
                   name: str = COUPON_NAME, poll_times: Optional[int] = None,
                   discount: Optional[dict] = None,
                   discount_for=None) -> dict:
    """쿠폰을 건다. 🔴 이미 걸린 게 있으면 **먼저 내리고** 새로 만든다.

    단추를 두 번 누르거나 할인값을 바꿨을 때도 같은 길을 탄다 — 옛 쿠폰을 안 내리면
    한 옵션은 쿠폰 하나에만 붙는 규칙 때문에 새 쿠폰이 전부 [CIR08] 로 거부된다.
    **못 내렸으면 새로 만들지 않는다.** 만들어 봐야 빈 쿠폰만 하나 더 생긴다.
    """
    from shared.platforms.coupang.promotions import expire_coupon

    if channel.market != 'coupang':
        return {'ok': False, 'attempts': [], 'attached': [], 'failed_items': [],
                'message': f'쿠폰은 쿠팡에서만 씁니다 — 이 채널은 {channel.market} 입니다.'}
    rec = record_of(channel)
    old = rec.get('coupon_id')
    vid = vendor_id or _vendor_id_of(client)
    if not vid:
        return {'ok': False, 'message': '쿠팡 판매자ID(vendorId)를 못 읽어 쿠폰을 못 겁니다.',
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

    if discount is None:
        # 정책이 정한 값이 먼저다 — 할인값을 바꾸려고 다시 거는 것이니 옛 값이 이기면 안 된다.
        discount = (discount_for or _discount_for)(session, channel)
    if discount is None and rec.get('ok') and rec.get('value'):
        # 정책에 값이 없을 때만 **지난번에 통한 값**에서 시작한다(사장님 「배운다」) —
        # 100원부터 21번 다시 헤매지 않는다.
        discount = {'value': int(rec['value']), 'unitType': 'WON'}
    return run_for_channel(session, channel, client=client, now=now, sleep=sleep,
                           discount=discount, vendor_id=vid, name=name,
                           poll_times=poll_times)


def renew_channel(session, channel, **kw) -> dict:
    """자동연장 — `apply_or_renew` 와 같은 길이다(이름만 뜻을 밝힌다)."""
    return apply_or_renew(session, channel, **kw)


# ── 대기열 — 단추·정책 자동이 요청하고, 스케줄러가 처리한다 ─────────────────

def request_for_channel(session, channel, *, now: Optional[datetime] = None,
                        by: str = '단추') -> dict:
    """「걸어 주세요」를 남긴다. 실제 걸기는 스케줄러가 한다.

    🔴 걸 수 없는 게 **지금 이미 분명하면** 대기열에 안 넣고 그 자리에서 말한다 —
      넣어 봐야 매번 실패하고, 사장님은 왜 안 되는지 모른 채 기다리게 된다.
    """
    if channel.market != 'coupang':
        return {'ok': False, 'message': '쿠폰은 쿠팡에서만 씁니다 — '
                                        f'이 채널은 {channel.market} 입니다.'}
    if not targets_for(session, channel):
        return {'ok': False,
                'message': '쿠팡에 연동된 옵션이 없어 쿠폰을 걸 수 없습니다. '
                           '쿠팡에 등록하고 옵션 연동(matched)이 끝나야 걸 수 있어요.'}
    stamp = (now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
    channel.api_fields = {**(channel.api_fields or {}),
                          REQUEST_KEY: {'at': stamp, 'by': by}}
    session.add(channel)
    session.commit()
    return {'ok': True, 'message': '쿠폰 걸기를 대기열에 넣었습니다 — 잠시 뒤 결과가 나옵니다. '
                                   '⏰ 쿠팡 쿠폰은 오늘 켤 수 없어 **다음날 0시부터** 적용됩니다.'}


def channels_of_model(session, model_code: str) -> list:
    """그 상품(모음전 코드)의 쿠팡 채널들 — 구성이 여럿이면 여럿이다."""
    from lemouton.sets.models import ProductSet
    set_ids = [r[0] for r in session.query(ProductSet.id)
               .filter(ProductSet.model_code == model_code).all()]
    if not set_ids:
        return []
    return (session.query(SetChannel)
            .filter(SetChannel.market == 'coupang',
                    SetChannel.set_id.in_(set_ids)).all())


def request_for_model(session, model_code: str, *, now=None, by='단추') -> dict:
    """상품 화면 단추 — 그 상품의 쿠팡 채널 전부에 요청을 남긴다."""
    chans = channels_of_model(session, model_code)
    if not chans:
        return {'ok': False, 'queued': 0,
                'message': '이 상품은 아직 쿠팡에 연동된 구성이 없습니다 — '
                           '쿠팡에 먼저 등록해 주세요.'}
    ok, skipped = 0, []
    for ch in chans:
        r = request_for_channel(session, ch, now=now, by=by)
        if r['ok']:
            ok += 1
        else:
            skipped.append(r['message'])
    if not ok:
        # 🔴 조용히 「넣었습니다」라고 하지 않는다 — 왜 못 넣었는지 그대로 돌려준다.
        return {'ok': False, 'queued': 0, 'message': ' / '.join(dict.fromkeys(skipped))}
    msg = (f'쿠폰 걸기를 대기열에 넣었습니다({ok}곳) — 잠시 뒤 결과가 나옵니다. '
           f'⏰ 쿠팡 쿠폰은 오늘 켤 수 없어 **다음날 0시부터** 적용됩니다.')
    if skipped:
        msg += ' 다만 ' + ' / '.join(dict.fromkeys(skipped))
    return {'ok': True, 'queued': ok, 'message': msg}


def request_for_policy(session, policy_id: int, *, now=None,
                       by='정책 자동') -> dict:
    """정책 자동 — 그 정책이 붙은 상품들의 쿠팡 채널에 요청을 남긴다.

    🔴 **즉시할인이 적힌 정책만** 태운다. 안 적힌 정책까지 태우면 온 상품에 기본값
      100원 쿠폰이 저절로 걸린다 — 사장님이 시킨 적 없는 할인이다.
    🔴 아직 연동이 안 끝난 채널은 조용히 건너뛰지 않고 **몇 곳인지 말한다**.
    """
    from lemouton.policy.discount import discount_of
    from lemouton.policy.models import BundlePolicyLink, SetPolicyLink
    from lemouton.policy.service import values_for
    from lemouton.sets.models import ProductSet

    if not discount_of(values_for(session, policy_id, 'coupang')):
        return {'ok': False, 'queued': 0,
                'message': '이 정책엔 즉시할인이 없어 쿠폰을 걸지 않았습니다.'}

    set_ids = {r[0] for r in session.query(SetPolicyLink.set_id)
               .filter(SetPolicyLink.policy_id == policy_id).all()}
    codes = [r[0] for r in session.query(BundlePolicyLink.model_code)
             .filter(BundlePolicyLink.policy_id == policy_id).all()]
    if codes:
        set_ids |= {r[0] for r in session.query(ProductSet.id)
                    .filter(ProductSet.model_code.in_(codes)).all()}
    if not set_ids:
        return {'ok': True, 'queued': 0, 'message': '이 정책이 붙은 상품이 없습니다.'}

    chans = (session.query(SetChannel)
             .filter(SetChannel.market == 'coupang',
                     SetChannel.set_id.in_(sorted(set_ids))).all())
    ok = sum(1 for ch in chans
             if request_for_channel(session, ch, now=now, by=by)['ok'])
    not_ready = len(chans) - ok
    msg = f'쿠폰 걸기를 대기열에 넣었습니다({ok}곳).'
    if not_ready:
        msg += (f' {not_ready}곳은 아직 쿠팡 옵션 연동이 안 끝나 못 넣었습니다 — '
                f'연동이 끝나면 다시 눌러 주세요.')
    return {'ok': True, 'queued': ok, 'not_ready': not_ready, 'message': msg}


def pending_requests(session) -> list:
    """아직 처리 안 된 요청들."""
    return [ch for ch in
            session.query(SetChannel).filter(SetChannel.market == 'coupang').all()
            if (ch.api_fields or {}).get(REQUEST_KEY)]


def _clear_request(session, channel) -> None:
    """🔴 처리했으면 **반드시** 지운다 — 안 지우면 1분마다 쿠폰을 또 만든다."""
    fields = dict(channel.api_fields or {})
    fields.pop(REQUEST_KEY, None)
    channel.api_fields = fields
    session.add(channel)
    session.commit()


def run_pending(session, *, client_for, now: Optional[datetime] = None,
                sleep=_time.sleep, limit: int = 10, days: int = RENEW_BEFORE_DAYS,
                poll_times: Optional[int] = None, discount_for=None) -> dict:
    """대기열 + 연장 대상을 처리한다. 스케줄러가 부른다.

    Args:
        client_for: 채널 → 쿠팡 클라이언트. 못 만들면 None 을 준다.
        limit: 한 틱에 처리할 최대 채널 수(대기열·연장 각각).
    """
    stat = {'done': 0, 'failed': 0, 'renewed': 0, 'renew_failed': 0}

    def _one(ch, *, renew):
        client = None
        try:
            client = client_for(ch)
        except Exception as e:                              # noqa: BLE001
            logger.warning('[쿠팡쿠폰] 계정 열쇠를 못 얻었습니다 channel=%s: %s', ch.id, e)
        if client is None:
            # 🔴 조용히 되풀이하지 않는다 — 사유를 기록에 남기고 요청은 지운다.
            _save(session, ch, {'ok': False, 'message':
                                '쿠팡 계정 열쇠를 못 얻어 쿠폰을 걸지 못했습니다 — '
                                '판매처관리에서 그 계정이 살아 있는지 봐 주세요.'},
                  sale_price=_sale_price(session, ch), now=now)
            return False
        r = apply_or_renew(session, ch, client=client, now=now, sleep=sleep,
                           poll_times=poll_times, discount_for=discount_for)
        return bool(r.get('ok'))

    for ch in pending_requests(session)[:max(0, int(limit))]:
        ok = _one(ch, renew=False)
        stat['done' if ok else 'failed'] += 1
        _clear_request(session, ch)          # 성공·실패 상관없이 지운다

    done_ids = set()
    for ch in due_renewals(session, now=now, days=days)[:max(0, int(limit))]:
        if ch.id in done_ids:
            continue
        done_ids.add(ch.id)
        ok = _one(ch, renew=True)
        stat['renewed' if ok else 'renew_failed'] += 1
    return stat


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

# -*- coding: utf-8 -*-
"""쿠팡 즉시할인쿠폰을 **실제로 걸어 주는** 한 곳 — 만들기 → 붙이기 → 확인 → 회수.

쿠팡엔 「즉시할인」을 적는 칸이 없다. 쿠폰을 만들어 **옵션 하나하나(vendorItemId)에
붙여야** 값이 깎인다. 부품(`shared/platforms/coupang/promotions.py`)과 값 규칙
(`lemouton/policy/discount.py`)은 있었는데 **부르는 곳이 없어서** 정책에 즉시할인을
적어도 쿠팡엔 아무것도 안 나갔다. 그 사이를 잇는 자리다.

■ 사장님 확정 (2026-08-13)
    기본값 100원 · 거부되면 **10원씩 올려 재시도** · 상한 **300원** ·
    쿠폰 기간은 **최대로**(=계약서 종료일) · 정책 자동과 단추 **둘 다**

■ 🔴 라이브에서 이미 데인 것 (커밋 `6d4164d9` · 2026-08-06)
    · 만들기·붙이기는 **접수만** 한다. `requestedId` 로 확인해야 결과를 안다.
    · **FAIL/ERROR 도 「끝」이다.** `done` 만 보고 돌면 실패를 성공으로 보고한다
      (앞 세션이 실제로 그렇게 보고했다).
    · 안 붙었으면 만든 쿠폰을 **그 자리에서 도로 내린다** — 빈 쿠폰이 윙에 쌓인다.
    · 내리기는 `PUT … action=expire`. 빼면 500.

■ 🔴 실패 사유를 **가려야** 한다 — 두 병의 약이 다르다
    `[CIE06]` 할인이 너무 작다        → 10원 올리면 낫는다   → 올린다
    `[CIR08]` 이미 다른 쿠폰에 물렸다 → 금액과 무관         → 안 올린다
    `[CIE00]/[CIR06]` 옵션이 이상하다 → 금액과 무관         → 안 올린다
    안 가르면 300원까지 21번 헛되이 올리며 쿠폰을 21개 만들었다 지운다.

■ 🔴 일부만 붙은 경우는 **성공으로 보되 못 붙은 것을 말한다**
    쿠폰은 나중에 대상을 못 바꾼다(쿠팡 문서: 「최초 생성 시 설정한 쿠폰 적용 상품을
    추후 삭제할 수 없습니다」). 그래서 붙은 게 있는데 금액을 올리려고 내려 버리면
    **이미 깎이던 옵션까지 같이 잃는다.** 붙은 것은 살리고, 못 붙은 것은 사유를 적어
    화면이 말하게 한다(조용한 절반 성공 금지).

■ 🔴 이 파일은 DB 를 모른다
    셈과 순서만 여기 있고, 「어느 상품인가·결과를 어디 적나」는 부르는 쪽이 정한다.
    (같은 순서를 두 벌 쓰면 갈린다 — 정본은 여기 하나.)
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime
from typing import Optional

from lemouton.policy.discount import (
    COUPANG_DEFAULT_WON, default_discount, problem_for,
)
from shared.platforms.coupang.promotions import (
    CoupangCouponError, add_items, check_request, create_coupon, expire_coupon,
    list_contracts, pick_contract, tomorrow_midnight,
)

logger = logging.getLogger(__name__)

#: 사장님 확정 — 거부되면 이만큼씩 올린다.
RETRY_STEP_WON = 10

#: 사장님 확정(2026-08-13) — **300원까지만**. 여기서 멈추고 다음 값을 말한다.
#:   🔴 무한 재시도 금지. 한 번 올릴 때마다 쿠폰을 만들었다 지우는 왕복이라
#:     쿠팡 API 를 두들기고, 무엇보다 **깎아 주는 돈이 그만큼 늘어난다.**
#:   실측 참고: 128,900원 상품은 1,400원(1.09%)에서 통과했다 — 그런 상품은 300원에서
#:     막힌다. 그때는 「300원까지 해 봤고 다음은 310원」이라고 **말하고 멈춘다**.
RETRY_MAX_WON = 300

#: 접수 결과를 기다리는 횟수·간격(초). 시험은 sleep 을 갈아끼운다.
POLL_TIMES = 10
POLL_SECONDS = 3

#: 「끝났다」로 볼 상태 — 🔴 DONE 만 보면 실패가 영원히 「진행 중」으로 남는다.
_END_STATES = {'DONE', 'FAIL', 'FAILED', 'ERROR', 'CANCEL', 'CANCELED'}

#: 금액이 작아서 거부된 것 — 이것만 10원씩 올려 다시 해 본다.
_MONEY_CODES = ('CIE06',)


def _is_money_reason(reason: str) -> bool:
    return any(code in str(reason or '') for code in _MONEY_CODES)


def _wait(client, vendor_id, requested_id, *, sleep, times, seconds):
    """접수 결과를 기다린다. 안 끝나면 None — **성공으로 단정하지 않는다**."""
    for _ in range(max(1, int(times))):
        sleep(seconds)
        st = check_request(client, vendor_id, requested_id)
        if st.get('done') or str(st.get('status') or '').upper() in _END_STATES:
            return st
    return None


def _result(ok, message, **kw):
    out = {'ok': bool(ok), 'message': message, 'coupon_id': None, 'value': None,
           'attempts': [], 'attached': [], 'failed_items': [], 'expired': [],
           'starts_at': None, 'ends_at': None, 'contract_id': None, 'tried': 0}
    out.update(kw)
    out['tried'] = len(out['attempts'])
    return out


def apply_coupon(client, *, vendor_id: str, name: str, vendor_item_ids: list,
                 sale_price: Optional[int] = None, discount: Optional[dict] = None,
                 now: Optional[datetime] = None, sleep=_time.sleep,
                 poll_times: int = POLL_TIMES, poll_seconds: int = POLL_SECONDS,
                 ) -> dict:
    """쿠폰을 만들어 옵션에 붙인다. 돌려주는 것은 **사람이 읽을 수 있는 결과**.

    Args:
        vendor_item_ids: 붙일 옵션(vendorItemId) 목록. 비면 아무것도 안 만든다.
        sale_price: 판매가(경고 문구용). 몰라도 된다 — 모르면 비율을 말하지 않는다.
        discount: 정책이 정한 값. 없으면 기본값 100원.

    Returns:
        {ok, message, coupon_id, value, attempts[], attached[], failed_items[],
         expired[], starts_at, ends_at, contract_id, tried}
    """
    ids = [str(v).strip() for v in (vendor_item_ids or []) if str(v or '').strip()]
    if not ids:
        # 🔴 옵션 없이 쿠폰부터 만들면 **반드시** 빈 쿠폰이 된다(윙에 쌓인다).
        return _result(False, '붙일 옵션이 없어 쿠폰을 만들지 않았습니다. '
                              '쿠팡에 먼저 등록하고 옵션 연동이 끝나야 쿠폰을 걸 수 있어요.')

    disc = discount or default_discount('coupang')
    if not disc:
        return _result(False, '깎을 값이 없어 쿠폰을 만들지 않았습니다.')
    problem = problem_for('coupang', disc)
    if problem:
        # 마켓이 「유효하지 않습니다」만 뱉기 전에 우리가 사람 말로 말한다.
        return _result(False, problem)

    contract = pick_contract(_safe_contracts(client, vendor_id), now=now)
    if not contract:
        # 🔴 계약ID를 지어내면 엉뚱한 계약에 쿠폰이 걸린다. 만들지 않는다.
        return _result(False, '쿠팡 계약서를 읽지 못해 쿠폰을 만들지 않았습니다 — '
                              '지금 유효한 계약이 없거나 조회에 실패했습니다.')

    start_at = tomorrow_midnight(now)
    # ⏰ 끝날은 **계약서 종료일** = 이 계정에서 걸 수 있는 최대 기간.
    #   쿠팡은 「계약의 유효기간 안에 쿠폰이 존재해야 한다」고 거부한다.
    end_at = contract['end']

    unit = disc['unitType']
    value = int(disc['value'])
    attempts: list = []
    expired: list = []
    remaining = list(ids)

    while True:
        att = {'value': value, 'ok': False, 'reason': '', 'coupon_id': None}
        attempts.append(att)
        try:
            rid = create_coupon(client, vendor_id, contract_id=contract['contract_id'],
                                name=name, unit=unit, value=value,
                                start_at=start_at, end_at=end_at)
        except CoupangCouponError as e:
            att['reason'] = str(e)
            return _result(False, f'쿠폰을 만들지 못했습니다: {e}', attempts=attempts,
                           starts_at=start_at, ends_at=end_at,
                           contract_id=contract['contract_id'], expired=expired)

        st = _wait(client, vendor_id, rid, sleep=sleep, times=poll_times,
                   seconds=poll_seconds)
        coupon_id = (st or {}).get('coupon_id')
        if not st or not st.get('done') or not coupon_id:
            # 🔴 「아직 모른다」를 성공으로도 실패로도 단정하지 않는다. 사람이 봐야 한다.
            att['reason'] = f"접수는 됐지만 결과를 못 봤습니다(status={(st or {}).get('status')})"
            return _result(False,
                           '쿠폰이 아직 만들어지지 않았습니다 — 잠시 뒤 다시 하거나 '
                           '쿠팡 윙에서 직접 확인해 주세요.',
                           attempts=attempts, starts_at=start_at, ends_at=end_at,
                           contract_id=contract['contract_id'], expired=expired)
        att['coupon_id'] = coupon_id

        failed, hard = _attach(client, vendor_id, coupon_id, remaining,
                               sleep=sleep, times=poll_times, seconds=poll_seconds)
        bad_ids = {str(f['vendorItemId']) for f in failed}
        attached = [i for i in remaining if i not in bad_ids] if not hard else []

        if attached:
            att['ok'] = True
            if failed:
                att['reason'] = _reasons_text(failed)
            logger.info('[쿠팡쿠폰] %s · %s원 · 옵션 %d개 붙음(%d번째 시도)',
                        name, value, len(attached), len(attempts))
            return _result(True, _ok_message(value, attached, failed, start_at),
                           coupon_id=coupon_id, value=value, attempts=attempts,
                           attached=attached, failed_items=failed, expired=expired,
                           starts_at=start_at, ends_at=end_at,
                           contract_id=contract['contract_id'])

        # 하나도 안 붙었다 → 빈 쿠폰을 남기지 않는다.
        att['reason'] = _reasons_text(failed) or hard or '붙은 옵션이 없습니다'
        expired.append(coupon_id)
        if not expire_coupon(client, vendor_id, coupon_id):
            logger.error('[쿠팡쿠폰] 🔴 쿠폰 %s 를 못 내렸습니다 — 윙에서 직접 내려야 합니다',
                         coupon_id)

        money = bool(failed) and all(_is_money_reason(f.get('reason')) for f in failed)
        nxt = value + RETRY_STEP_WON
        if not (money and unit == 'WON' and nxt <= RETRY_MAX_WON):
            return _result(False,
                           _stop_message(value, unit, money, failed, attempts),
                           attempts=attempts, failed_items=failed, expired=expired,
                           starts_at=start_at, ends_at=end_at,
                           contract_id=contract['contract_id'])
        value = nxt


def _safe_contracts(client, vendor_id) -> list:
    try:
        return list_contracts(client, vendor_id)
    except Exception as e:                                  # noqa: BLE001
        logger.warning('[쿠팡쿠폰] 계약서 조회 실패: %s', e)
        return []


def _attach(client, vendor_id, coupon_id, ids, *, sleep, times, seconds):
    """옵션 붙이기. (실패목록, 통째실패사유) — 통째실패면 실패목록이 비어 있을 수 있다."""
    try:
        rids = add_items(client, vendor_id, coupon_id, ids)
    except CoupangCouponError as e:
        return [], str(e)
    failed: list = []
    for r in rids:
        st = _wait(client, vendor_id, r, sleep=sleep, times=times, seconds=seconds)
        if st is None:
            return failed, '붙이기 결과를 못 봤습니다(아직 처리 중)'
        failed.extend(st.get('failed_items') or [])
        # 🔴 FAIL/ERROR 는 **끝**이다 — 실패 목록이 비어 있어도 성공이 아니다.
        #   `done` 만 보고 돌면 여기서 실패가 성공으로 둔갑한다(2026-08-06 실사고).
        if not st.get('done'):
            return failed, f"붙이기가 실패로 끝났습니다(status={st.get('status')})"
    return failed, ''


def _reasons_text(failed) -> str:
    return ' / '.join(f"옵션 {f.get('vendorItemId')}: {f.get('reason')}"
                      for f in (failed or []))


def _ok_message(value, attached, failed, start_at) -> str:
    day = str(start_at)[:10]
    msg = (f'{value:,}원 쿠폰을 옵션 {len(attached)}개에 붙였습니다. '
           f'⏰ 쿠팡 쿠폰은 오늘 켤 수 없어 **{day} 0시부터** 적용됩니다.')
    if failed:
        # 조용한 절반 성공 금지 — 못 붙은 것을 사유째로 말한다.
        msg += f' 다만 {len(failed)}개는 못 붙였습니다 — {_reasons_text(failed)}'
    return msg


def _stop_message(value, unit, money, failed, attempts) -> str:
    if money and unit == 'WON':
        start = attempts[0]['value']
        return (f'쿠팡이 계속 「할인이 너무 작다」고 거부했습니다. '
                f'{start:,}원부터 {RETRY_STEP_WON}원씩 {value:,}원까지 '
                f'{len(attempts)}번 해 봤습니다(사장님이 정한 상한 {RETRY_MAX_WON:,}원). '
                f'더 하려면 다음 값은 {value + RETRY_STEP_WON:,}원입니다 — '
                f'상한을 올릴지 정해 주세요. 만든 쿠폰은 모두 도로 내렸습니다.')
    if money:
        return (f'{value:,}%로는 쿠팡이 거부했습니다. 정률은 금액처럼 조금씩 올릴 수 없어 '
                f'한 번만 해 봤습니다. 만든 쿠폰은 도로 내렸습니다.')
    detail = _reasons_text(failed) or '쿠팡이 사유를 주지 않았습니다'
    return (f'{value:,}{"원" if unit == "WON" else "%"} 쿠폰을 어느 옵션에도 못 붙였습니다 — '
            f'{detail}. 금액 문제가 아니라 올려도 낫지 않습니다. '
            f'만든 쿠폰은 도로 내렸습니다.')


def learned_start_won(records, sale_price=None) -> int:
    """지난 성공에서 배운 **시작 금액**. 없으면 기본값 100원.

    사장님 말씀: 「몇 번 만에 얼마로 성공했는지 남겨야 다음 상품에 배운다」.
    같은 판매가대에서 100원부터 21번 헛도는 일을 두 번 하지 않게, 지난번에 통한
    **비율**을 지금 판매가에 대 본다.

    🔴 지어내지 않는다 — 기록이 없거나 판매가를 모르면 그냥 기본값 100원이다.
    🔴 배운 값도 상한(`RETRY_MAX_WON`)을 넘기지 않는다. 배움이 사장님이 정한
      한도를 넘어서면 안 된다.
    """
    ok = [r for r in (records or [])
          if r.get('ok') and r.get('value') and r.get('sale_price')]
    if not ok or not sale_price:
        return COUPANG_DEFAULT_WON
    try:
        price = int(sale_price)
    except (TypeError, ValueError):
        return COUPANG_DEFAULT_WON
    if price <= 0:
        return COUPANG_DEFAULT_WON
    pct = max(int(r['value']) / int(r['sale_price']) for r in ok)
    want = int(-(-(price * pct) // RETRY_STEP_WON)) * RETRY_STEP_WON   # 10원 단위 올림
    return max(COUPANG_DEFAULT_WON, min(want, RETRY_MAX_WON))

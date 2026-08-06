# -*- coding: utf-8 -*-
"""즉시할인 **실전송 검증** — 스마트스토어 시험 상품 1개 · 걸었다가 원래대로 되돌린다.

사장님 확정(2026-08-06): 「1번하고 검증까지!」 = 시험 상품 하나로 실전송 후 검증.

왜 이 상품인가
  · 이름에 TEST 가 붙어 있고 **판매중지** 상태 → 고객이 살 수 없어 **금전 위험 0**
  · 그래도 원래 값을 먼저 읽어 두고, 끝나면 **그대로 되돌린다**(원상복구 확인까지)

흐름 (읽기 → 쓰기 → 읽기 → 되돌리기 → 읽기)
  ① 지금 즉시할인 값을 읽어 둔다(원본 보관)
  ② 우리 코드로 알아볼 수 있는 값(12,345원)을 건다
  ③ 다시 읽어 실제로 바뀌었는지 확인
  ④ ①의 원본으로 되돌린다
  ⑤ 다시 읽어 원래대로 돌아왔는지 확인

🔴 되돌리기가 실패하면 **크게 외친다** — 조용히 끝나면 사장님 상품에 시험값이 남는다.
env: TEST_CHANNEL_NO(기본 12326862286) · TEST_ENV_PREFIX(기본 계정 자동 탐색)
"""
import json
import os
import sys

sys.path.insert(0, '/app')

CHANNEL_NO = os.environ.get('TEST_CHANNEL_NO') or '12326862286'
#: 우리가 건 것임을 한눈에 알 수 있는 값.
#: 🔴 **10원 단위**여야 한다 — 12,345 로 보냈다가 마켓이 거부했다(실측):
#:   「기본할인 항목은 10원 단위로 입력해 주세요」
MARK_VALUE = 12340
MARK_UNIT = 'WON'


def _disc_of(origin: dict):
    """지금 걸린 즉시할인 → {'value':int,'unitType':str} 또는 None."""
    cb = (origin or {}).get('customerBenefit') or {}
    idp = cb.get('immediateDiscountPolicy') or {}
    dm = idp.get('discountMethod') or {}
    v, u = dm.get('value'), dm.get('unitType')
    if v in (None, 0):
        return None
    return {'value': int(v), 'unitType': u or 'WON'}


def main() -> int:
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.catalog.models import MarketProduct
    from lemouton.uploader.market_fetch import _smartstore_client
    from shared.platforms.smartstore.edit_product import edit_options

    s = SessionLocal()
    try:
        mp = (s.query(MarketProduct)
              .filter_by(market='smartstore', market_product_id=str(CHANNEL_NO))
              .first())
        if mp is None:
            print(f'■ 캐시에 그 상품이 없습니다: {CHANNEL_NO}'); return 1
        acc = (s.query(UploadAccount)
               .filter_by(market='smartstore', account_key=mp.account_key).first())
        if acc is None:
            print(f'■ 계정을 못 찾았습니다: {mp.account_key}'); return 1
        name, acct, env = mp.name, mp.account_key, acc.env_prefix
    finally:
        s.close()

    print('=' * 70)
    print(f'■ 즉시할인 실전송 검증 — {name}')
    print(f'  계정 {acct} · 상품번호(채널) {CHANNEL_NO} · 상태 판매중지(고객 구매 불가)')
    print('=' * 70)

    client = _smartstore_client(env)

    # 채널상품번호 → 원상품번호 (고치는 API 는 원상품번호를 받는다)
    #   ⚠️ 실측(run 31093483820): 응답 최상위는 {originProduct, smartstoreChannelProduct}
    #     이고 originProductNo 는 그 안 어딘가에 있다. 자리를 **찍어서 맞히지 않고**
    #     키 이름으로 깊이 찾는다(추측한 자리가 틀리면 그대로 멈춘다).
    ch = client.request('GET', f'/external/v2/products/channel-products/{CHANNEL_NO}')

    def _find(obj, key, depth=0):
        if depth > 6 or obj is None:
            return None
        if isinstance(obj, dict):
            if obj.get(key) not in (None, '', 0):
                return obj[key]
            for v in obj.values():
                got = _find(v, key, depth + 1)
                if got:
                    return got
        elif isinstance(obj, list):
            for v in obj[:20]:
                got = _find(v, key, depth + 1)
                if got:
                    return got
        return None

    origin_no = _find(ch, 'originProductNo')
    if not origin_no:
        # ⚠️ 실측: 채널상품 조회 응답엔 원상품번호가 **아예 없다**
        #   (최상위 originProduct/smartstoreChannelProduct 어디에도).
        #   지도에 답이 있었다 — 검색 API 가 `channelProductNos` 로 찾아 준다
        #   (searchKeywordType=CHANNEL_PRODUCT_NO). 지도를 먼저 봤어야 했다.
        sr = client.request('POST', '/external/v1/products/search',
                            body={'searchKeywordType': 'CHANNEL_PRODUCT_NO',
                                  'channelProductNos': [int(CHANNEL_NO)],
                                  'page': 1, 'size': 10})
        for item in (sr or {}).get('contents') or []:
            for cp in item.get('channelProducts') or []:
                if str(cp.get('channelProductNo')) == str(CHANNEL_NO):
                    origin_no = item.get('originProductNo') or cp.get('originProductNo')
                    break
            if origin_no:
                break
    if not origin_no:
        print('■ 원상품번호를 못 찾았습니다(채널상품 조회·검색 둘 다).')
        return 1
    print(f'  원상품번호 = {origin_no}')

    def read():
        r = client.request('GET', f'/external/v2/products/origin-products/{origin_no}')
        o = (r or {}).get('originProduct') or {}
        return o.get('salePrice'), _disc_of(o)

    # ① 원본 보관
    price0, disc0 = read()
    print(f'\n① 지금 상태 — 판매가 {price0:,} · 즉시할인 {disc0}')

    # ② 우리 값 걸기
    print(f'\n② 즉시할인 {MARK_VALUE:,}원 걸기 (판매가·옵션은 안 건드림)')
    r = edit_options(int(origin_no), sale_price=None, option_updates={},
                     immediate_discount={'value': MARK_VALUE, 'unitType': MARK_UNIT},
                     client=client)
    if not r.success:
        print(f'  ✕ 실패: {r.error_code} {r.error_message}')
        # 🔴 「유효하지 않습니다」만 보고 추측하지 않는다 — 마켓이 준 사유를 그대로 찍는다
        print('  마켓이 말한 문제 칸:',
              json.dumps(r.invalid_inputs, ensure_ascii=False)[:1200]
              if r.invalid_inputs else '(안 알려줌)')
        return 1
    print('  ○ 보냈습니다')

    # ③ 진짜 바뀌었나
    price1, disc1 = read()
    ok_applied = bool(disc1 and disc1['value'] == MARK_VALUE)
    print(f'\n③ 다시 읽음 — 판매가 {price1:,} · 즉시할인 {disc1}'
          f'  → {"✅ 걸렸습니다" if ok_applied else "❌ 안 걸렸습니다"}')
    if price0 != price1:
        print(f'  ⚠️ 판매가가 바뀌었습니다({price0:,} → {price1:,}) — 즉시할인만 건드려야 한다')
    if ok_applied:
        print(f'  고객이 보는 값 = {price1:,} − {MARK_VALUE:,} = {price1 - MARK_VALUE:,}')

    # ④ 원래대로
    back = disc0 or {'value': 0}
    print(f'\n④ 되돌리기 — {back}')
    r2 = edit_options(int(origin_no), sale_price=None, option_updates={},
                      immediate_discount=back, client=client)
    if not r2.success:
        print(f'  🔴🔴 되돌리기 실패! 시험값 {MARK_VALUE}원이 남아 있습니다 — '
              f'셀러센터에서 직접 지워 주세요: {r2.error_code} {r2.error_message}')
        return 1

    # ⑤ 원상복구 확인
    price2, disc2 = read()
    restored = (disc2 == disc0)
    print(f'\n⑤ 다시 읽음 — 판매가 {price2:,} · 즉시할인 {disc2}'
          f'  → {"✅ 원래대로" if restored else "🔴🔴 원래와 다릅니다"}')
    if not restored:
        print(f'  🔴🔴 원본은 {disc0} 였습니다 — 셀러센터에서 확인해 주세요')

    print('\n' + '=' * 70)
    print('■ 결과 — 실전송', '성공' if ok_applied else '실패',
          '· 원상복구', '성공' if restored else '실패')
    print('=' * 70)
    return 0 if (ok_applied and restored) else 1


if __name__ == '__main__':
    sys.exit(main())

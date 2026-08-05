# -*- coding: utf-8 -*-
"""롯데온·11번가·ESM 목록 응답 원문 실측 (읽기 전용) — 가격·배송비 자리 찾기.

왜: 사장님 지적 「쿠팡뿐만 아니라 타마켓도 판매가/노출가/배송비가 안 보인다」.
  · 롯데온: 목록에서 지금 가격을 하나도 안 읽는데, 지도 res 가 플레이스홀더라
    실제로 뭐가 오는지 미확보(과거 오진 사례 — 지도의 params 를 전부로 믿지 말 것).
  · 11번가: selPrc(판매가)만 읽는 중 — 할인가·배송비가 목록에 있는지 미확보.
  · ESM: price(판매가)만 읽는 중 — 나머지 자리 미확보.
각 마켓 활성 계정 1개에서 목록 1페이지만 부르고 첫 상품의 **원문 그대로**를 찍는다.
"""
import json
import sys

sys.path.insert(0, '/app')


def _one(label, fn):
    print('=' * 70)
    print(f'[{label}]')
    try:
        item = fn()
        if item is None:
            print('  ✕ 상품 0건'); return
        print('  키:', json.dumps(sorted(item.keys()), ensure_ascii=False))
        print('  원문:', json.dumps(item, ensure_ascii=False)[:1600])
    except Exception as e:                              # noqa: BLE001
        print(f'  ✕ 실측 실패: {str(e)[:250]}')


def main() -> int:
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.catalog.sync import _client_for

    s = SessionLocal()
    try:
        accs = {}
        for a in (s.query(UploadAccount)
                  .filter(UploadAccount.is_active.is_(True)).all()):
            accs.setdefault(a.market, a)
    finally:
        s.close()

    def lotteon():
        a = accs['lotteon']
        client = _client_for('lotteon', a.env_prefix)
        from shared.platforms import LOTTEON
        from datetime import datetime, timedelta
        # ★ 실제 훑기(_lotteon)와 같은 body — trGrpCd/trNo 빠지면 0건(1차 실측 실패)
        cfg = getattr(client, '_cfg', None) or LOTTEON
        now = datetime.now()
        body = {'trGrpCd': cfg.get('tr_grp_cd', 'SR'), 'trNo': cfg.get('tr_no', ''),
                'regStrtDttm': (now - timedelta(days=3650)).strftime('%Y%m%d%H%M%S'),
                'regEndDttm': now.strftime('%Y%m%d%H%M%S'),
                'pageNo': 1, 'rowsPerPage': 3}
        r = client.request(method='POST', path=cfg['paths']['list'], body=body)
        data = r.get('data')
        raw = data if isinstance(data, list) else (
            next((v for v in (data or {}).values() if isinstance(v, list)), []))
        return raw[0] if raw else None

    def eleven11():
        a = accs['eleven11']
        client = _client_for('eleven11', a.env_prefix)
        from shared.platforms.eleven11 import products as P
        raw = P.search_products(client=client, limit=3, start=1, end=3)
        return (raw or [None])[0]

    def esm():
        a = accs.get('auction') or accs.get('gmarket')
        market = a.market
        client = _client_for(market, a.env_prefix)
        from shared.platforms import AUCTION, GMARKET
        cfg = AUCTION if market == 'auction' else GMARKET
        body = {'pageIndex': 1, 'pageSize': 3,
                'query': {'siteId': [1 if market == 'auction' else 2]}}
        r = client.request(method='POST', path=cfg['paths']['search'], body=body)
        data = r.get('data') if isinstance(r, dict) and 'data' in r else r
        items = (data or {}).get('items') or []
        return items[0] if items else None

    _one('롯데온 목록 1건 원문', lotteon)
    _one('11번가 목록 1건 원문', eleven11)
    _one('ESM(옥션/G마켓) 목록 1건 원문', esm)
    print('\n■ 끝')
    return 0


if __name__ == '__main__':
    sys.exit(main())

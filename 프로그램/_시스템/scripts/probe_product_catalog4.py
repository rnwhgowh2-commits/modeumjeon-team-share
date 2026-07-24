# -*- coding: utf-8 -*-
"""실측 4차 — 목록 응답 1행의 **실제 키 이름**을 본다. 읽기 전용.

왜: 라이브에서 옥션 1,605건·쿠팡 19건이 전부 상태 'unknown' 으로 저장됐다.
    상태 코드를 못 읽었다는 뜻 — 내가 짐작한 필드명(sellStatus / statusName)이
    실제와 다르다. 짐작을 고치려면 실제 키를 봐야 한다.

★ 상품명·가격도 같이 확인한다 — 이름이 비면 검색이 안 걸린다.
"""
from __future__ import annotations

import json
import os


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}"


def _pick(market: str):
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        a = (s.query(UploadAccount)
             .filter(UploadAccount.is_active.is_(True),
                     UploadAccount.market == market)
             .order_by(UploadAccount.account_key).first())
        return (a.account_key, a.env_prefix) if a else None
    finally:
        s.close()


def _shape(d: dict, depth: int = 0) -> dict:
    """키 이름 + 값 맛보기. 상태처럼 보이는 키는 값을 그대로 남긴다."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and depth < 2:
            out[k] = _shape(v, depth + 1)
        elif isinstance(v, list):
            out[k] = f"[list {len(v)}개]" + (
                f" 첫값={json.dumps(v[0], ensure_ascii=False)[:120]}" if v else "")
        else:
            out[k] = str(v)[:80]
    return out


def probe_esm() -> dict:
    from lemouton.uploader.market_fetch import _esm_client
    from shared.platforms import AUCTION
    got = _pick('auction')
    if not got:
        return {'skip': '옥션 계정 없음'}
    account_key, env_prefix = got
    c = _esm_client('auction', env_prefix)
    out = {'account': account_key}
    try:
        resp = c.request(method='POST', path=AUCTION['paths']['search'], body={
            'pageIndex': 1, 'pageSize': 2, 'query': {'siteId': [1]}})
        data = resp.get('data') if isinstance(resp, dict) and 'data' in resp else resp
        items = (data or {}).get('items') or []
        out['최상위_키'] = sorted(resp.keys()) if isinstance(resp, dict) else str(type(resp))
        out['data_키'] = sorted((data or {}).keys())
        out['items_개수'] = len(items)
        if items:
            out['첫_행_전체'] = _shape(items[0])
            out['상태처럼_보이는_키'] = {
                k: str(v)[:60] for k, v in items[0].items()
                if any(t in k.lower() for t in ('stat', 'sell', 'sale', 'state'))}
    except Exception as e:      # noqa: BLE001
        out['fatal'] = _err(e)
    return out


def probe_coupang() -> dict:
    from lemouton.uploader.market_fetch import _coupang_client
    got = _pick('coupang')
    if not got:
        return {'skip': '쿠팡 계정 없음'}
    account_key, env_prefix = got
    c = _coupang_client(env_prefix)
    vid = getattr(c, 'vendor_id', None) or getattr(c, '_cfg', {}).get('vendor_id')
    out = {'account': account_key, 'vendorId': vid}
    try:
        resp = c.request(
            'GET',
            '/v2/providers/seller_api/apis/api/v1/marketplace/seller-products',
            query=f'vendorId={vid}&maxPerPage=2')
        rows = resp.get('data') or []
        out['최상위_키'] = sorted(resp.keys())
        out['행_개수'] = len(rows)
        if rows:
            out['첫_행_전체'] = _shape(rows[0])
            out['상태처럼_보이는_키'] = {
                k: str(v)[:60] for k, v in rows[0].items()
                if any(t in k.lower() for t in ('stat', 'sell', 'sale', 'state'))}
    except Exception as e:      # noqa: BLE001
        out['fatal'] = _err(e)
    return out


def probe_eleven11() -> dict:
    from lemouton.uploader.market_fetch import _eleven11_client
    from shared.platforms.eleven11.products import search_products
    got = _pick('eleven11')
    if not got:
        return {'skip': '11번가 계정 없음'}
    account_key, env_prefix = got
    c = _eleven11_client(env_prefix)
    out = {'account': account_key}
    try:
        rows = search_products(client=c, limit=2, start=1, end=2)
        out['행_개수'] = len(rows)
        if rows:
            out['첫_행_전체'] = _shape(rows[0])
    except Exception as e:      # noqa: BLE001
        out['fatal'] = _err(e)
    return out


def probe_lotteon() -> dict:
    """롯데온은 이미 맞게 나오는지 대조용(spdNm·slStatCd)."""
    from datetime import datetime, timedelta

    from lemouton.uploader.market_fetch import _lotteon_client
    from shared.platforms import LOTTEON
    got = _pick('lotteon')
    if not got:
        return {'skip': '롯데온 계정 없음'}
    account_key, env_prefix = got
    c = _lotteon_client(env_prefix)
    cfg = getattr(c, '_cfg', None) or LOTTEON
    now = datetime.now()
    out = {'account': account_key}
    try:
        resp = c.request(method='POST', path=cfg['paths']['list'], body={
            'trGrpCd': cfg.get('tr_grp_cd', 'SR'), 'trNo': cfg.get('tr_no', ''),
            'regStrtDttm': (now - timedelta(days=3650)).strftime('%Y%m%d%H%M%S'),
            'regEndDttm': now.strftime('%Y%m%d%H%M%S'),
            'pageNo': 1, 'rowsPerPage': 2})
        data = resp.get('data')
        rows = data if isinstance(data, list) else (
            next((v for v in (data or {}).values() if isinstance(v, list)), []))
        out['dataCount'] = resp.get('dataCount')
        if rows:
            out['상태처럼_보이는_키'] = {
                k: str(v)[:60] for k, v in rows[0].items()
                if any(t in k.lower() for t in ('stat', 'sl', 'nm'))}
    except Exception as e:      # noqa: BLE001
        out['fatal'] = _err(e)
    return out


def main() -> int:
    only = (os.environ.get('ONLY_MARKET') or '').strip()
    parts = [('옥션(ESM)', probe_esm), ('쿠팡', probe_coupang),
             ('11번가', probe_eleven11), ('롯데온(대조)', probe_lotteon)]
    for title, fn in parts:
        if only and only not in title:
            continue
        print('\n' + '=' * 70)
        print('■ ' + title)
        print('=' * 70)
        try:
            print(json.dumps(fn(), ensure_ascii=False, indent=2))
        except Exception as e:      # noqa: BLE001
            print(f'실패: {_err(e)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""쿠팡 즉시할인쿠폰 실측 (읽기 전용) — 「쿠폰적용가」 배선 전 응답 모양 확인.

왜: 사장님 확정 — 쿠팡은 고객이 보는 값이 **쿠폰적용가**다. 그런데 상품 목록·조회
API 에는 쿠폰 정보가 없고(실측: 쿠폰 언급 0), [즉시할인쿠폰] 조회 API 는 지도에
**문서만 있고 라이브 미검증**(st=code)이다. 응답 모양을 안 보고 배선하면 날조가 된다.

무엇을 부르나 (전부 GET · 생성/수정/파기는 절대 안 부른다):
  ① GET /v2/.../vendors/{vendorId}/coupons?status=APPLIED   — 적용 중 쿠폰 목록
  ② GET /v2/.../vendors/{vendorId}/coupons/{couponId}/items — 쿠폰이 붙은 상품들
  ①의 raw 키·②의 raw 키와 할인 방식(정률/정액)·대상 상품 수를 그대로 찍는다.

env: ONLY_ACCOUNT (account_key 하나만 — 기본은 활성 쿠팡 계정 전부)
"""
import json
import os
import sys

sys.path.insert(0, '/app')


def main() -> int:
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.uploader.market_fetch import _coupang_client

    only = (os.environ.get('ONLY_ACCOUNT') or '').strip() or None
    s = SessionLocal()
    try:
        accs = (s.query(UploadAccount)
                .filter_by(market='coupang', is_active=True)
                .order_by(UploadAccount.id).all())
    finally:
        s.close()
    if only:
        accs = [a for a in accs if a.account_key == only]
    if not accs:
        print('■ 쿠팡 활성 계정이 없습니다'); return 1

    print('=' * 70)
    print(f'■ 쿠팡 즉시할인쿠폰 실측 (읽기 전용) — 계정 {len(accs)}개')
    print('=' * 70)
    any_ok = False
    for a in accs:
        print(f'\n[{a.account_key}] (env={a.env_prefix})')
        try:
            client = _coupang_client(a.env_prefix)
            # ⚠️ vendor_id 는 속성이 아니라 설정 주머니(_cfg) 안에 있다 —
            #   getattr 로 읽으면 8계정 전부 「없음」이 된다(1차 실측에서 겪음).
            vendor = (getattr(client, '_cfg', {}) or {}).get('vendor_id')
            if not vendor:
                print('  ✕ vendor_id 없음 — 건너뜀'); continue
            # ① 적용 중 쿠폰 목록
            # ⚠️ 이 클라이언트는 params dict 가 아니라 **query 문자열**을 받는다
            #   (HMAC 서명에 query 가 들어가서 형식이 정확해야 한다).
            r1 = client.request(
                'GET',
                f'/v2/providers/fms/apis/api/v2/vendors/{vendor}/coupons',
                query='status=APPLIED&page=1&size=10&sort=desc')
            print('  ① 쿠폰목록 raw 키:', sorted(r1.keys()) if isinstance(r1, dict) else type(r1).__name__)
            data = (r1.get('data') or {}) if isinstance(r1, dict) else {}
            content = (data.get('content') if isinstance(data, dict) else None) or \
                      (r1.get('content') if isinstance(r1, dict) else None) or []
            print(f'  ① 적용 중 쿠폰: {len(content)}건')
            for c in content[:3]:
                keys = sorted(c.keys()) if isinstance(c, dict) else c
                print('     쿠폰 키:', json.dumps(keys, ensure_ascii=False)[:200])
                print('     쿠폰 값 맛보기:', json.dumps(c, ensure_ascii=False)[:300])
            # ② 첫 쿠폰의 대상 상품
            if content and isinstance(content[0], dict):
                cid = content[0].get('couponId') or content[0].get('coupon_id')
                if cid is not None:
                    r2 = client.request(
                        'GET',
                        f'/v2/providers/fms/apis/api/v1/vendors/{vendor}/coupons/{cid}/items',
                        query='status=APPLIED&page=1&size=10&sort=desc')
                    d2 = (r2.get('data') or {}) if isinstance(r2, dict) else {}
                    items = (d2.get('content') if isinstance(d2, dict) else None) or \
                            (r2.get('content') if isinstance(r2, dict) else None) or []
                    print(f'  ② 쿠폰 {cid} 대상 상품: {len(items)}건')
                    for it in items[:3]:
                        print('     아이템 맛보기:', json.dumps(it, ensure_ascii=False)[:300])
            any_ok = True
        except Exception as e:                          # noqa: BLE001
            print(f'  ✕ 실측 실패: {str(e)[:250]}')
    print('\n■ 끝 —', '최소 1계정 성공' if any_ok else '전 계정 실패')
    return 0 if any_ok else 1


if __name__ == '__main__':
    sys.exit(main())

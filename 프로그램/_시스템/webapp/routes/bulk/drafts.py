# -*- coding: utf-8 -*-
"""대량등록 — 드래프트 CRUD + 등록 라우트."""
import json

from flask import jsonify, request

from shared.db import SessionLocal
from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.registration.service import register_draft, RegisterBlocked, MARKETS
from . import bp


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


@bp.post('/api/drafts')
def create_draft():
    """수기 입력 → ProductDraft 1건 저장."""
    p = request.get_json(silent=True) or {}
    if not (p.get('name') or '').strip():
        return _err('상품명을 입력해 주세요.')
    try:
        sale_price = int(p.get('sale_price') or 0)
    except (TypeError, ValueError):
        return _err('판매가는 숫자로 입력해 주세요.')
    if sale_price <= 0:
        return _err('판매가가 0원 이하입니다.')

    # ★ 옵션은 저장 전에 검증한다 — 여기서 통과시키면 잘못된 값이 Text 컬럼에 그대로
    #   박혀 있다가 나중에 등록 시점에 터진다(저장은 성공, 등록만 실패 = 원인 추적 어려움).
    #   options.py 의 빌더가 진짜 검증기이므로 그것을 그대로 호출해 미리 걸러낸다.
    raw_opts = p.get('options') or []
    if raw_opts:
        from lemouton.registration.options import build_smartstore_options, OptionError
        try:
            build_smartstore_options(raw_opts, sale_price=sale_price)
        except OptionError as e:
            return _err(f'옵션 오류: {e}')

    s = SessionLocal()
    try:
        d = ProductDraft(
            origin='bulk', source='manual',
            name=p['name'].strip(),
            brand=(p.get('brand') or '').strip(),
            sale_price=sale_price,
            normal_price=int(p['normal_price']) if p.get('normal_price') else None,
            stock_quantity=int(p.get('stock_quantity') or 0),
            notice_type=p.get('notice_type') or 'WEAR',
            notice_json=json.dumps(p.get('notice') or {}, ensure_ascii=False),
            images_json=json.dumps(p.get('images') or [], ensure_ascii=False),
            cdn_images_json=json.dumps(p.get('cdn_images') or [], ensure_ascii=False),
            detail_html=p.get('detail_html') or '',
            options_json=json.dumps(raw_opts, ensure_ascii=False),
            # ★ `or 0` 로 쓰면 안 된다 — 빈 칸이 0 이 되고, 쿠팡 컴파일러가 0 을
            #   deliveryChargeType='FREE'(무료배송=판매자 부담)로 보내 돈이 샌다.
            #   0 은 '무료배송' 이라는 뜻 있는 값이므로 '미입력' 과 구분해야 한다.
            delivery_fee=(int(p['delivery_fee'])
                          if p.get('delivery_fee') not in (None, '') else 3000),
            return_fee=(int(p['return_fee'])
                        if p.get('return_fee') not in (None, '') else 5000),
            minor_purchasable=bool(p.get('minor_purchasable', True)),
            after_service_phone=(p.get('after_service_phone') or '').strip(),
            after_service_guide=(p.get('after_service_guide') or '').strip(),
        )
        s.add(d)
        s.commit()
        return jsonify({'ok': True, 'draft_id': d.id})
    finally:
        s.close()


@bp.get('/api/drafts')
def list_drafts():
    s = SessionLocal()
    try:
        rows = (s.query(ProductDraft)
                .filter(ProductDraft.deleted_at.is_(None))
                .order_by(ProductDraft.id.desc()).limit(200).all())
        out = []
        for d in rows:
            markets = s.query(ProductDraftMarket).filter_by(draft_id=d.id).all()
            out.append({
                'id': d.id, 'name': d.name, 'brand': d.brand,
                'sale_price': d.sale_price, 'status': d.status,
                'markets': [{'market': m.market, 'account_key': m.account_key,
                             'status': m.status,
                             'market_product_id': m.market_product_id,
                             'error': m.error_message} for m in markets],
            })
        return jsonify({'ok': True, 'rows': out})
    finally:
        s.close()


@bp.post('/api/drafts/<int:draft_id>/register/<market>')
def register(draft_id: int, market: str):
    if market not in MARKETS:
        return _err(f'market 은 {MARKETS} 중 하나여야 해요.')
    p = request.get_json(silent=True) or {}
    if not p.get('category_code'):
        return _err('카테고리를 먼저 정해 주세요.')

    s = SessionLocal()
    try:
        try:
            r = register_draft(s, draft_id, market,
                               category_code=p['category_code'],
                               vendor=p.get('vendor') or {},
                               account_key=(p.get('account_key') or 'default'))
        except RegisterBlocked as e:
            # 게이트 OFF 는 '에러'가 아니라 '막힘' — 화면에 그대로 알린다
            return jsonify({'ok': False, 'blocked': True, 'error': str(e)})
        except ValueError as e:
            return _err(str(e), 404)
        return jsonify(r)
    finally:
        s.close()

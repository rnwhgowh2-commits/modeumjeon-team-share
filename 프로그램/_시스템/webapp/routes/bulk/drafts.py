# -*- coding: utf-8 -*-
"""대량등록 — 드래프트 CRUD + 등록 라우트."""
import json

from flask import jsonify, request

from shared.db import SessionLocal
from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.registration.service import register_draft, RegisterBlocked, MARKETS
# coerce_int = 자유형 입력('15,000'·'75800.0') → int, 실패만 CompileError.
# bare int() 는 '15,000'·'abc' 에 ValueError 를 던져 라우트가 500 을 냈다(코드리뷰 지적).
from lemouton.registration.compile_common import coerce_int, CompileError
# 「6 매입가·마진」 6칸의 저장 계약 — 파싱·유효값·폭 검사의 단일 진실 원천.
# (같은 규칙을 margin.py 도 쓴다. 라우트마다 복붙하면 한쪽만 고쳐져 갈린다.)
from lemouton.registration.pricing_inputs import (
    parse_pricing_inputs, pricing_payload,
)
from . import bp


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


@bp.post('/api/drafts')
def create_draft():
    """수기 입력 → ProductDraft 1건 저장."""
    p = request.get_json(silent=True) or {}
    if not (p.get('name') or '').strip():
        return _err('상품명을 입력해 주세요.')
    # 숫자 칸은 전부 coerce_int 로 파싱한다 — 폼·엑셀 붙여넣기가 '15,000'·'75800.0' 을
    # 보내도 500 대신 깔끔한 400. bare int() 였다면 여기서 ValueError → 500 이었다.
    try:
        sale_price = coerce_int(p.get('sale_price'), '판매가') or 0
        normal_price = coerce_int(p.get('normal_price'), '정상가')
        stock_quantity = coerce_int(p.get('stock_quantity'), '재고') or 0
        # 배송비·반품비: 빈 칸(None)은 기본값으로 두되, 0 은 '무료배송'이라는 뜻 있는 값이라
        # 구분한다. `or 3000` 이면 사용자가 넣은 0(무료배송)이 3000 으로 둔갑해 돈이 샌다.
        delivery_fee = coerce_int(p.get('delivery_fee'), '배송비')
        return_fee = coerce_int(p.get('return_fee'), '반품비')
    except CompileError as e:
        return _err(str(e))
    if sale_price <= 0:
        return _err('판매가가 0원 이하입니다.')

    # 매입가·마진 6칸 — 화면이 보낸 것만, 보낸 그대로. 안 보낸 칸은 NULL 로 남는다
    # (기본값을 채우면 '사용자가 고른 값'으로 둔갑한다 → 폴백 금지).
    try:
        pricing = parse_pricing_inputs(p)
    except CompileError as e:
        return _err(str(e))

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
            normal_price=normal_price,
            stock_quantity=stock_quantity,
            notice_type=p.get('notice_type') or 'WEAR',
            notice_json=json.dumps(p.get('notice') or {}, ensure_ascii=False),
            images_json=json.dumps(p.get('images') or [], ensure_ascii=False),
            cdn_images_json=json.dumps(p.get('cdn_images') or [], ensure_ascii=False),
            detail_html=p.get('detail_html') or '',
            options_json=json.dumps(raw_opts, ensure_ascii=False),
            # ★ 빈 칸이 0 이 되면 안 된다 — 쿠팡 컴파일러가 0 을 deliveryChargeType='FREE'
            #   (무료배송=판매자 부담)로 보내 돈이 샌다. 0 은 '무료배송' 이라는 뜻 있는 값이라
            #   coerce_int 가 None(미입력) 과 구분한다 → 미입력만 기본값으로.
            delivery_fee=delivery_fee if delivery_fee is not None else 3000,
            return_fee=return_fee if return_fee is not None else 5000,
            minor_purchasable=bool(p.get('minor_purchasable', True)),
            after_service_phone=(p.get('after_service_phone') or '').strip(),
            after_service_guide=(p.get('after_service_guide') or '').strip(),
            **pricing,
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


def _draft_detail(d) -> dict:
    """드래프트 1건 → 화면이 폼을 **그대로 되살릴 수 있는** 전체 payload.

    ★ 빈 값을 채우지 않는다. NULL 은 null 로, ''는 ''로 내보낸다. 여기서 ''로
      통일해 버리면 "입력받지 않음"이 "「소싱처 기본값」을 골랐음"으로 둔갑해,
      복원된 화면이 사장님이 하지 않은 선택을 한 것처럼 보인다.
    """
    out = {
        'id': d.id,
        'name': d.name,
        'brand': d.brand,
        'sale_price': d.sale_price,
        'normal_price': d.normal_price,
        'stock_quantity': d.stock_quantity,
        'notice_type': d.notice_type,
        'notice': json.loads(d.notice_json or '{}'),
        'images': json.loads(d.images_json or '[]'),
        'cdn_images': json.loads(d.cdn_images_json or '[]'),
        'detail_html': d.detail_html,
        'options': json.loads(d.options_json or '[]'),
        'delivery_fee': d.delivery_fee,
        'return_fee': d.return_fee,
        'minor_purchasable': d.minor_purchasable,
        'after_service_phone': d.after_service_phone,
        'after_service_guide': d.after_service_guide,
        'status': d.status,
        # M2: 소싱처 카테고리 — bulk_manual.js 가 등록 흐름에서 catmap/resolve 호출에 쓴다.
        # 수기 드래프트는 둘 다 None(=맵핑 판정 생략, 기존 검색 흐름).
        'source_site': d.source_site,
        'source_category_path': d.source_category_path,
    }
    out.update(pricing_payload(d))   # source_id·surface_price·inflow·card_key…
    return out


@bp.get('/api/drafts/<int:draft_id>')
def get_draft(draft_id: int):
    """저장한 드래프트를 다시 열기 위한 상세 — 폼 복원의 재료."""
    s = SessionLocal()
    try:
        d = (s.query(ProductDraft)
             .filter(ProductDraft.id == draft_id,
                     ProductDraft.deleted_at.is_(None)).first())
        if d is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)
        return jsonify({'ok': True, 'draft': _draft_detail(d)})
    finally:
        s.close()


@bp.put('/api/drafts/<int:draft_id>')
def update_draft(draft_id: int):
    """다시 열어 고친 내용을 **같은 행에** 덮어쓴다.

    이 라우트가 없으면 '열기 → 수정 → 저장'이 매번 새 행을 만들어, 같은 상품이
    조금씩 다른 값으로 여러 벌 남는다(= 어느 게 진짜인지 모르는 상태 = 이 저장소가
    금지하는 중복·모순).
    """
    p = request.get_json(silent=True) or {}
    try:
        pricing = parse_pricing_inputs(p)
        sale_price = coerce_int(p.get('sale_price'), '판매가')
        normal_price = coerce_int(p.get('normal_price'), '정상가')
        stock_quantity = coerce_int(p.get('stock_quantity'), '재고')
        delivery_fee = coerce_int(p.get('delivery_fee'), '배송비')
        return_fee = coerce_int(p.get('return_fee'), '반품비')
    except CompileError as e:
        return _err(str(e))

    s = SessionLocal()
    try:
        d = (s.query(ProductDraft)
             .filter(ProductDraft.id == draft_id,
                     ProductDraft.deleted_at.is_(None)).first())
        if d is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)

        if 'name' in p:
            if not (p.get('name') or '').strip():
                return _err('상품명을 입력해 주세요.')
            d.name = p['name'].strip()
        if 'sale_price' in p:
            if not sale_price or sale_price <= 0:
                return _err('판매가가 0원 이하입니다.')
            d.sale_price = sale_price
        if 'brand' in p:
            d.brand = (p.get('brand') or '').strip()
        if 'normal_price' in p:
            d.normal_price = normal_price
        if 'stock_quantity' in p:
            d.stock_quantity = stock_quantity or 0
        if 'notice_type' in p:
            d.notice_type = p.get('notice_type') or 'WEAR'
        if 'notice' in p:
            d.notice_json = json.dumps(p.get('notice') or {}, ensure_ascii=False)
        if 'images' in p:
            d.images_json = json.dumps(p.get('images') or [], ensure_ascii=False)
        if 'cdn_images' in p:
            d.cdn_images_json = json.dumps(p.get('cdn_images') or [], ensure_ascii=False)
        if 'detail_html' in p:
            d.detail_html = p.get('detail_html') or ''
        if 'options' in p:
            raw_opts = p.get('options') or []
            if raw_opts:
                from lemouton.registration.options import (
                    build_smartstore_options, OptionError)
                try:
                    build_smartstore_options(
                        raw_opts, sale_price=d.sale_price)
                except OptionError as e:
                    return _err(f'옵션 오류: {e}')
            d.options_json = json.dumps(raw_opts, ensure_ascii=False)
        # 배송비·반품비: 0 은 '무료배송'이라는 뜻 있는 값이라 미입력(None)과 구분한다.
        if 'delivery_fee' in p and delivery_fee is not None:
            d.delivery_fee = delivery_fee
        if 'return_fee' in p and return_fee is not None:
            d.return_fee = return_fee
        if 'after_service_phone' in p:
            d.after_service_phone = (p.get('after_service_phone') or '').strip()
        if 'after_service_guide' in p:
            d.after_service_guide = (p.get('after_service_guide') or '').strip()

        # 매입가·마진 6칸 — 화면이 보낸 칸만 덮는다. 안 보낸 칸은 그대로 둔다.
        for column, value in pricing.items():
            setattr(d, column, value)

        s.commit()
        return jsonify({'ok': True, 'draft': _draft_detail(d)})
    finally:
        s.close()


def _brand_restriction_block(session, draft, market, category_code=None):
    """M2: 브랜드·지재권 제한표 판정 — 걸리면 사유 문자열, 아니면 None.

    cat_path 산출 순서:
      1) 이 마켓에 confirmed 로 맵핑된 경로(추측 아닌 사장님 확정값 — 최우선).
      2) [I1, 2026-07-23 리뷰 수정] confirmed 맵핑이 없으면 이번 등록 요청의
         `category_code` 로 market_categories 사전에서 실제 full_path 를 조회해 쓴다.
         수기 드래프트는 소싱처 맵핑이 아예 없지만, 사용자가 이번에 직접 고른 코드로
         실제 카테고리 경로를 알 수 있다 — 이것도 추측이 아니라 실데이터(사전 그대로).
      3) 그래도 못 찾으면 ''(미정) — brand_restrict.is_blocked 가 미정 상태를 보수적으로
         차단하는 게 의도다(지재권은 잘못 막는 쪽이 잘못 올리는 쪽보다 싸다).
    """
    from lemouton.registration.models import BrandRestriction, CategoryMapRow, MarketCategory
    from lemouton.registration import brand_restrict as BR

    rules = [{'brand': r.brand, 'market': r.market, 'category_prefix': r.category_prefix,
             'active': r.active, 'reason': r.reason}
            for r in session.query(BrandRestriction).filter_by(active=True).all()]
    if not rules:
        return None

    cat_path = ''
    if draft.source_site and draft.source_category_path:
        mapped = (session.query(CategoryMapRow)
                  .filter_by(source_id=draft.source_site, source_path=draft.source_category_path,
                             market=market, status='confirmed').first())
        if mapped is not None:
            cat_path = mapped.market_cat_path or ''
    if not cat_path and category_code:
        cat = (session.query(MarketCategory)
               .filter_by(market=market, code=str(category_code))
               .filter(MarketCategory.removed_at.is_(None)).first())
        if cat is not None:
            cat_path = cat.full_path or ''
    return BR.is_blocked(rules, brand=draft.brand, market=market, cat_path=cat_path)


@bp.post('/api/drafts/<int:draft_id>/register/<market>')
def register(draft_id: int, market: str):
    if market not in MARKETS:
        return _err(f'market 은 {MARKETS} 중 하나여야 해요.')
    p = request.get_json(silent=True) or {}
    if not p.get('category_code'):
        return _err('카테고리를 먼저 정해 주세요.')

    s = SessionLocal()
    try:
        draft = s.query(ProductDraft).filter_by(id=draft_id).first()
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)

        # M2: 브랜드·지재권 제한 — 걸리면 마켓을 호출하지 않는다(선차단).
        reason = _brand_restriction_block(s, draft, market, category_code=p.get('category_code'))
        if reason:
            account_key = p.get('account_key') or 'default'
            row = (s.query(ProductDraftMarket)
                   .filter_by(draft_id=draft_id, market=market, account_key=account_key).first())
            if row is None:
                row = ProductDraftMarket(draft_id=draft_id, market=market, account_key=account_key)
                s.add(row)
            row.status = 'blocked'
            row.error_code = 'BRAND_RESTRICTED'
            row.error_message = reason
            row.category_code = str(p['category_code'])
            s.commit()
            return jsonify({'ok': False, 'blocked': True, 'reason': reason})

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


def _lotteon_sample_search(q):
    """[2026-07-21] 롯데온 전용 — 카테고리 대신 **본보기 상품**(최근 1년 등록분)을 이름으로
    찾아 spdNo 를 준다(롯데온 등록 body = 본보기 detail 스키마 — 실측 규약).
    기존 category_search 의 lotteon 분기를 코드 이동만(수정 없음)."""
    from lemouton.uploader import market_fetch as MF
    from lemouton.sourcing.models_v2 import UploadAccount
    from shared.platforms.lotteon.products import list_products
    s = SessionLocal()
    try:
        acct = (s.query(UploadAccount).filter_by(market='lotteon', is_active=True)
                .order_by(UploadAccount.id).first())
        envp = acct.env_prefix if acct else None
    finally:
        s.close()
    client = MF._lotteon_client(envp)
    rows = list_products(client=client, sale_status='SALE', rows_per_page=100)
    hits = [{'code': r.get('spdNo'), 'name': str(r.get('spdNm') or '')[:60]}
            for r in rows if isinstance(r, dict)
            and q.lower() in str(r.get('spdNm') or '').lower()][:30]
    return jsonify({'ok': True, 'market': 'lotteon', 'count': len(hits), 'rows': hits,
                    'note': '롯데온은 카테고리 대신 본보기 상품번호(spdNo)를 씁니다.'})


@bp.get('/api/category-search')
def category_search():
    """카테고리 이름 검색 — market_categories 사전 조회 (롯데온만 본보기 상품 검색 유지).

    [2026-07-22] 6마켓 전수 수집기(M1) 배선 — 5마켓(스마트스토어·쿠팡·옥션·G마켓·11번가)은
    설정 탭에서 수집해 둔 사전(market_categories)에서 리프+이름부분일치로 찾는다.
    11번가 실시간 XML 조회는 여기서 걷어냈다 — 파서는 category_harvest.parse_eleven11 로
    승격 완료(죽은 코드 이중화 금지). 롯데온은 카테고리가 아니라 본보기 상품 검색이라 그대로.
    """
    market = (request.args.get('market') or '').strip()
    q = (request.args.get('q') or '').strip()
    if not market or not q:
        return _err('market 과 q 가 필요합니다')
    if market == 'lotteon':
        return _lotteon_sample_search(q)
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        base = (s.query(MarketCategory)
                .filter_by(market=market)
                .filter(MarketCategory.removed_at.is_(None)))
        if base.count() == 0:
            return jsonify({'ok': False,
                            'error': f'{market} 카테고리 사전이 비어 있습니다 — 설정 탭에서 「카테고리 수집」을 먼저 실행하세요'})
        # q 안의 LIKE 와일드카드(%, _)와 이스케이프문자(\) 자체를 리터럴로 매치시킨다.
        # 이스케이프 없이 그대로 넣으면 예: q='90%' 검색이 "90 뒤에 아무거나"로 번져
        # 엉뚱한 카테고리까지 걸린다(리뷰 지적).
        escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        like = f'%{escaped}%'
        rows = (base.filter(MarketCategory.is_leaf.is_(True))
                .filter(MarketCategory.full_path.like(like, escape='\\'))
                .order_by(MarketCategory.full_path).limit(30).all())
        return jsonify({'ok': True, 'market': market, 'count': len(rows),
                        'rows': [{'code': r.code, 'name': r.name, 'path': r.full_path} for r in rows]})
    finally:
        s.close()

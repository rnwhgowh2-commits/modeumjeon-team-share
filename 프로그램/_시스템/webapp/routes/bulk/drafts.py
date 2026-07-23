# -*- coding: utf-8 -*-
"""대량등록 — 드래프트 CRUD + 등록 라우트."""
import json

from flask import jsonify, request
from sqlalchemy import case, func

from shared.db import SessionLocal
from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.registration.service import (
    register_draft, RegisterBlocked, MARKETS, MARKETS_MORE,
)
# coerce_int = 자유형 입력('15,000'·'75800.0') → int, 실패만 CompileError.
# bare int() 는 '15,000'·'abc' 에 ValueError 를 던져 라우트가 500 을 냈다(코드리뷰 지적).
from lemouton.registration.compile_common import coerce_int, CompileError
# 「6 매입가·마진」 6칸의 저장 계약 — 파싱·유효값·폭 검사의 단일 진실 원천.
# (같은 규칙을 margin.py 도 쓴다. 라우트마다 복붙하면 한쪽만 고쳐져 갈린다.)
from lemouton.registration.pricing_inputs import (
    parse_pricing_inputs, pricing_payload,
)
# M4-3 고시 기본값 — 저장값은 그대로 두고 **점검·컴파일에 넘길 사본**에만 병합한다.
from lemouton.registration.notice_defaults import apply_notice_defaults
# [2026-07-23 (나)안] 상세 안 타 마켓 브랜딩 이미지 — **감지·표면화만** 한다.
#   자동 제거는 오탐(멀쩡한 상품 사진 삭제)이 나서 사장님이 (나)안으로 정했다.
from lemouton.sourcing.crawlers.foreign_assets import (
    detect_foreign_market_assets, remove_assets_from_detail,
)
from . import bp

# 카테고리 검색이 한 번에 보여 주는 최대 건수. 넘치면 응답의 total 로 「전체 N건」을 알려
# 사장님이 검색어를 좁힐 수 있게 한다(조용히 자르지 않는다).
SEARCH_LIMIT = 30


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
        # 크롤에서 온 초안인지(그리고 어느 소싱처 URL 인지) — 화면이 「소싱처 보기」 링크에 쓴다.
        'source': d.source,
        'source_url': d.source_url,
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


def _brand_missing_block(session, draft):
    """브랜드가 비어 제한표를 판정조차 못 하는 상태면 사유, 아니면 None.

    ★ [2026-07-23 리뷰 C2] 크롤이 만드는 초안은 브랜드가 대개 비어 있고,
      `brand_restrict.is_blocked` 는 브랜드가 비면 None(무판정) 이다. 즉 이 기능이
      만드는 **모든 초안이 기본적으로 무판정**이라 제한표가 통째로 무력해진다.
      더구나 compile_eleven11 은 예전에 상품명 첫 토큰을 브랜드로 합성해 보냈다
      (「나이키 에어포스 1」 → brand='나이키') — 우리 게이트는 통과시키고 마켓에는
      제한 브랜드가 올라가는 최악의 조합이었다. 그 fallback 은 제거했고, 여기서는
      「모름」을 「통과」로 읽지 않는다.

    판정기는 :func:`brand_restrict.needs_brand` 하나 — 사전 점검과 등록 라우트가
    같은 답을 내야 한다(두 답이 갈리면 그게 곧 모순이다).
    """
    from lemouton.registration.models import BrandRestriction
    from lemouton.registration import brand_restrict as BR

    if BR.normalize(draft.brand):
        return None
    rules = [{'active': r.active} for r in
             session.query(BrandRestriction).filter_by(active=True).all()]
    return BR.needs_brand(rules, draft.brand)


def _vendor_for(session, market: str, p: dict) -> dict:
    """쿠팡 vendor 9키 — 요청이 보낸 게 있으면 그것, 없으면 **계정 저장값**.

    [2026-07-23 M4-2] 등록 화면은 vendor 를 안 보냈고, compile_coupang 은 그것을
    필수로 요구해 쿠팡 등록이 100% 실패했다. vendor 는 계정에 매인 고정값이므로
    설정 탭에 한 번 저장해 두고 여기서 자동으로 채운다.

    body 의 vendor 를 우선하는 이유는 기존 계약을 깨지 않기 위해서다(직접 보내는
    호출자·테스트가 이미 있다). 쿠팡이 아닌 마켓은 예전처럼 그대로 흘려보낸다.
    """
    given = p.get('vendor')
    if isinstance(given, dict) and given:
        return given
    if market != 'coupang':
        return {}
    from lemouton.registration import coupang_vendor as CV
    return CV.vendor_for_account(session, p.get('account_key'))


def _vendor_incomplete(vendor) -> bool:
    """쿠팡 계정정보에 빈 칸이 하나라도 있는가 — 판정기는 컴파일러와 **같은 함수**."""
    from lemouton.registration.compile_coupang import missing_vendor_keys
    return bool(missing_vendor_keys(vendor))


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
        #   [리뷰 C2] 브랜드가 비어 **판정 자체가 불가능한** 경우도 같이 막는다.
        #   사전 점검(_preflight_row)과 같은 판정기를 쓴다 — 두 답이 갈리면 모순이다.
        need_brand = _brand_missing_block(s, draft)
        reason = need_brand or _brand_restriction_block(
            s, draft, market, category_code=p.get('category_code'))
        if reason:
            account_key = p.get('account_key') or 'default'
            row = (s.query(ProductDraftMarket)
                   .filter_by(draft_id=draft_id, market=market, account_key=account_key).first())
            if row is None:
                row = ProductDraftMarket(draft_id=draft_id, market=market, account_key=account_key)
                s.add(row)
            row.status = 'blocked'
            row.error_code = 'BRAND_UNKNOWN' if need_brand else 'BRAND_RESTRICTED'
            row.error_message = reason
            row.category_code = str(p['category_code'])
            s.commit()
            return jsonify({'ok': False, 'blocked': True, 'reason': reason})

        vendor = _vendor_for(s, market, p)
        try:
            r = register_draft(s, draft_id, market,
                               category_code=p['category_code'],
                               vendor=vendor,
                               account_key=(p.get('account_key') or 'default'))
        except RegisterBlocked as e:
            # 게이트 OFF 는 '에러'가 아니라 '막힘' — 화면에 그대로 알린다
            return jsonify({'ok': False, 'blocked': True, 'error': str(e)})
        except ValueError as e:
            return _err(str(e), 404)
        # 쿠팡 계정정보가 **한 칸이라도** 비어 컴파일이 막힌 것이면 어디서 채우는지까지
        # 말한다. [2026-07-23 리뷰 C1] 전에는 `not vendor`(통째로 없음)만 봐서, 부분 저장
        # 상태에서는 「무엇이 비었다」만 나오고 어디서 채우는지는 안 나왔다.
        # (register_draft 는 실패 사유를 row 에도 남겼다 — 여기선 화면 문구만 보탠다.)
        if (not r.get('ok') and market == 'coupang'
                and _vendor_incomplete(vendor) and r.get('error')):
            r['error'] = r['error'] + COUPANG_VENDOR_HINT
        return jsonify(r)
    finally:
        s.close()


# ── M4-1 등록 사전 점검(드라이런) ───────────────────────────────────────────
#
# 「등록」을 눌러봐야 무엇이 부족한지 알던 것을, 누르기 **전에** 마켓별로 보여준다.
# 근거: register_draft 의 ①예비 컴파일은 마켓 호출 전·라이브 게이트 앞이라, 그 단계만
# 6마켓으로 돌리면 네트워크 0·위험 0 으로 필수값 점검이 된다. compile_* 가 던지는
# CompileError 메시지가 곧 "무엇이 없는가" 다.
#
# ★ 이 라우트는 **마켓 API 를 한 번도 부르지 않는다**. 순수 컴파일 + 우리 DB 조회뿐.
#   (send_more/_send_live 는 게이트 뒤 계층이라 여기서 절대 import·호출하지 않는다.)

#: 마켓별 「예비 컴파일을 통과해도 남는」 하드 블로커 — 게이트 뒤 선행자원.
#: ready 가 곧 '등록 성공'이 아니라는 사실을 화면에 그대로 실어 보낸다(거짓 ready 금지).
PREFLIGHT_CAVEATS = {
    'smartstore': [
        '등록할 때 이미지를 네이버 CDN 으로 다시 올립니다 — 그 업로드가 실패하면 '
        '등록도 실패합니다(사전 점검으로는 알 수 없습니다).',
    ],
    # 쿠팡 caveat 은 **고정 문구가 아니다** — 계정정보가 저장돼 있으면 사라진다.
    # (_preflight_row 가 저장 여부를 보고 붙인다. 저장했는데도 「화면이 안 보냄」을
    #  계속 띄우면 그게 거짓 안내다.)
    'coupang': [],
    'auction': [
        '카테고리 칸에 「ESM표준코드/사이트카테고리코드」 짝이 필요합니다 — 우리 사전에는 '
        '사이트코드만 있어 표준코드는 직접 넣어야 합니다.',
        '등록할 때 판매중인 기존 상품에서 출하지·발송정책·반품지·택배사·고시를 가져옵니다 — '
        '판매중 상품이 없으면 등록할 수 없습니다.',
        '옵션 상품은 등록 직후 옵션을 따로 붙입니다 — 붙이기가 실패하면 상품을 판매중지로 '
        '되돌립니다(등록 직후 2~3분은 수정이 막혀 실패할 수 있습니다).',
    ],
    'eleven11': [
        '등록할 때 셀러오피스의 출고지·반품지 주소를 조회합니다 — 등록돼 있지 않으면 '
        '등록할 수 없습니다.',
    ],
    'lotteon': [
        '롯데온 칸은 카테고리가 아니라 「본보기 기존 상품번호」(LO 로 시작)입니다 — '
        '같은 계정에서 판매중인, 비슷한 카테고리 상품이어야 합니다.',
        '등록할 때 그 본보기 상품의 상세를 그대로 복사해 씁니다 — 조회가 안 되면 '
        '등록할 수 없습니다.',
    ],
}
PREFLIGHT_CAVEATS['gmarket'] = list(PREFLIGHT_CAVEATS['auction'])

#: 카테고리가 아직 없을 때 「그 외에 무엇이 비었는지」만 보려고 쓰는 형식상 코드.
#: ★ 이 값으로 등록하지 않는다 — 오직 컴파일러의 카테고리 검사만 통과시켜 뒤쪽
#:   필수값 검사(재고·상세HTML·고시·A/S…)에 닿게 하는 용도다.
_PROBE_CATEGORY = {
    'smartstore': '0', 'coupang': '0', 'auction': '0/0', 'gmarket': '0/0',
    'eleven11': '0', 'lotteon': 'LO0',
}


def _compile_probe(draft, market, category_code, vendor):
    """마켓별 **예비 컴파일**(순수 함수) — 통과하면 None, 실패하면 CompileError 를 던진다.

    register_draft 가 마켓 호출 전에 하는 것과 같은 호출이다.
      · smartstore: require_cdn_images=False (CDN 이미지는 게이트 뒤에서만 생긴다)
      · coupang   : vendor 는 요청이 준 것만 — 없으면 컴파일러가 vendorId 없다고 말한다
      · 4마켓     : compile_more (선행자원 수확은 게이트 뒤 send_more 몫이라 여기 없음)
    """
    from lemouton.registration.compile_smartstore import compile_smartstore
    from lemouton.registration.compile_coupang import compile_coupang
    from lemouton.registration.compile_more import (
        compile_auction_gmarket, compile_eleven11, compile_lotteon)

    if market == 'smartstore':
        compile_smartstore(draft, category_code=str(category_code),
                           require_cdn_images=False)
    elif market == 'coupang':
        compile_coupang(draft, category_code=category_code, vendor=vendor or {})
    elif market in ('auction', 'gmarket'):
        compile_auction_gmarket(draft, category_code=category_code)
    elif market == 'eleven11':
        compile_eleven11(draft, category_code=category_code)
    else:
        compile_lotteon(draft, category_code=category_code)


def _mapped_category(session, draft, market):
    """드래프트의 소싱처 분류에 **confirmed** 로 맵핑된 마켓 카테고리 코드 (없으면 None)."""
    if not (draft.source_site and draft.source_category_path):
        return None
    from lemouton.registration.models import CategoryMapRow
    row = (session.query(CategoryMapRow)
           .filter_by(source_id=draft.source_site, source_path=draft.source_category_path,
                      market=market, status='confirmed').first())
    return (row.market_cat_code or None) if row is not None else None


#: 카테고리 칸이 마켓마다 다른 것을 뜻한다 — 없을 때 무엇을 채워야 하는지 그대로 말한다.
_CATEGORY_WHAT = {
    'smartstore': '스마트스토어 리프 카테고리 ID',
    'coupang': '쿠팡 카테고리 코드(displayCategoryCode)',
    'auction': '옥션 「ESM표준코드/사이트카테고리코드」 짝',
    'gmarket': 'G마켓 「ESM표준코드/사이트카테고리코드」 짝',
    'eleven11': '11번가 최하위 카테고리 번호(dispCtgrNo)',
    'lotteon': '롯데온 본보기 상품번호(spdNo, LO 로 시작)',
}


#: 쿠팡 계정정보가 없을 때 붙이는 길잡이 — 「무엇이 없다」로 끝내지 않고 어디서 채우는지까지.
COUPANG_VENDOR_HINT = (' 설정 탭의 「🛒 쿠팡 계정정보」에서 계정정보(반품지·출고지)를 '
                       '먼저 저장해 주세요 — 「쿠팡에서 불러오기」를 누르면 대부분 자동으로 채워집니다.')


#: [2026-07-23 (나)안] 상세 안 타 마켓 브랜딩 이미지가 있을 때 붙이는 주의.
#: ★ **막지 않는다.** 파일명 판정은 오탐이 나므로(멀쩡한 상품 사진이 걸린다) 상태는
#:   ready 그대로 두고 보여만 준다 — 뺄지 말지는 사장님이 화면에서 고른다.
FOREIGN_ASSET_CAVEAT = (
    '상세에 타 마켓 이미지가 {n}개 있습니다 — 그대로 올리면 판매금지 사유가 될 수 '
    '있습니다. 아래 목록에서 확인하고 「상세에서 빼기」로 골라 빼실 수 있습니다.')


def _preflight_row(session, draft, market, *, category_code, account_key, vendor,
                   foreign_assets=None):
    """마켓 1곳 점검 → 결과 1행. 마켓 API 는 부르지 않는다.

    [2026-07-23 M4-2] 쿠팡 vendor 는 요청이 안 보내면 **계정 저장값**으로 채운다.
    저장값 조회는 우리 DB 뿐이라 「마켓 API 를 안 부른다」는 이 라우트의 전제는 그대로다.

    [2026-07-23 (나)안] `foreign_assets` = 상세 HTML 안 타 마켓 브랜딩 이미지.
    상세를 본문으로 그대로 쓰는 4마켓(MARKETS_MORE)에만 싣는다 — 스스·쿠팡 행에
    붙이면 거짓 안내가 된다.
    """
    row = {'market': market, 'status': 'ready', 'reason': '',
           'category_code': None, 'category_source': None,
           'account_key': account_key,
           'foreign_assets': (list(foreign_assets or [])
                              if market in MARKETS_MORE else []),
           'caveats': list(PREFLIGHT_CAVEATS.get(market) or [])}
    if row['foreign_assets']:
        row['caveats'].append(
            FOREIGN_ASSET_CAVEAT.format(n=len(row['foreign_assets'])))

    if market == 'coupang':
        if not vendor:
            from lemouton.registration import coupang_vendor as CV
            vendor = CV.vendor_for_account(session, account_key)
        # 한 칸이라도 비면 caveat 으로도 남긴다(ready 로 둔갑 금지). [리뷰 C1] 전에는
        # 「통째로 없을 때」만 봐서, 한 칸만 저장한 상태가 조용히 통과했다.
        if _vendor_incomplete(vendor):
            row['caveats'].append(
                '쿠팡 계정정보(반품지·출고지 등)에 아직 비어 있는 칸이 있습니다 —'
                + COUPANG_VENDOR_HINT)

    # 1) 브랜드·지재권 제한 — 등록 라우트와 **같은 판정기**를 쓴다(두 답이 갈리면 안 된다).
    #    1-a) [리뷰 C2] 브랜드가 비면 제한표가 판정조차 못 한다 = 무판정으로 새 나간다.
    #         제한 규칙이 살아 있는 동안에는 「모름」을 「통과」로 읽지 않는다.
    need_brand = _brand_missing_block(session, draft)
    if need_brand:
        row['status'] = 'need_brand'
        row['reason'] = need_brand
        return row
    blocked = _brand_restriction_block(session, draft, market, category_code=category_code)
    if blocked:
        row['status'] = 'blocked'
        row['reason'] = blocked
        return row

    # 2) 계정 — register_draft 가 스스·쿠팡에 대해 실제로 막는 조건을 그대로 미리 알린다
    #    (기록과 전송 계정이 어긋나는 거짓 장부 방지 가드).
    if account_key != 'default' and market not in MARKETS_MORE:
        row['status'] = 'missing'
        row['reason'] = (f'{market} 는 아직 기본 계정만 됩니다 (받은 값: {account_key!r}) — '
                         f'계정을 비우거나 「default」 로 두세요.')
        return row

    # 3) 카테고리 — confirmed 맵핑 우선, 없으면 이번 요청이 준 코드.
    row['category_code'] = str(category_code) if category_code else None
    if not category_code:
        row['status'] = 'need_category'
        reason = f'아직 정해지지 않았습니다 — 필요한 값: {_CATEGORY_WHAT[market]}.'
        # 카테고리와 별개로 지금 비어 있는 값도 같이 보여준다 — 형식상 코드로 컴파일러의
        # 카테고리 검사만 통과시켜 뒤쪽 필수값 검사에 닿게 한 결과다(등록에 쓰지 않는다).
        try:
            _compile_probe(draft, market, _PROBE_CATEGORY[market], vendor)
        except CompileError as e:
            reason += f' (카테고리와 별개로 지금 비어 있는 값: {e})'
        row['reason'] = reason
        return row

    # 4) 예비 컴파일 — 마켓 호출 전·게이트 앞의 그 단계 그대로.
    try:
        _compile_probe(draft, market, category_code, vendor)
    except CompileError as e:
        row['status'] = 'missing'
        # 쿠팡 계정정보에 빈 칸이 있어 걸린 것이면, 원문 뒤에 어디서 채우는지를 덧붙인다.
        row['reason'] = str(e) + (COUPANG_VENDOR_HINT
                                  if market == 'coupang'
                                  and _vendor_incomplete(vendor) else '')
        return row

    row['reason'] = ''
    return row


@bp.post('/api/drafts/<int:draft_id>/preflight')
def preflight(draft_id: int):
    """등록 버튼을 누르기 **전에** — 어느 마켓에 올릴 수 있고, 어느 마켓은 무엇이 비었는지.

    body(전부 선택):
      markets        : ['smartstore', ...]  생략하면 6마켓 전부
      category_codes : {market: code}       confirmed 맵핑이 없을 때만 쓴다
      account_keys   : {market: key}        생략하면 'default'
      vendor         : {...}                쿠팡 계정정보

    응답: {ok, rows: [{market, status, reason, category_code, category_source,
                       account_key, caveats}]}
      status = ready(올릴 수 있음) / missing(보충 필요) / blocked(제외) / need_category(카테고리 필요)

    ⚠ ready 는 '등록 성공 보장'이 아니다 — 게이트 뒤 선행자원(출하지·본보기·CDN 이미지·
      쿠팡 계정정보)에서 실패할 수 있고, 그 사실은 caveats 로 마켓마다 실어 보낸다.
    """
    p = request.get_json(silent=True) or {}

    markets = p.get('markets')
    if markets is None:
        markets = list(MARKETS)
    if not isinstance(markets, list):
        return _err('markets 는 배열이어야 합니다.')
    unknown = [m for m in markets if m not in MARKETS]
    if unknown:
        return _err(f'모르는 마켓입니다: {unknown} — {list(MARKETS)} 중에서 골라 주세요.')

    codes = p.get('category_codes') if isinstance(p.get('category_codes'), dict) else {}
    keys = p.get('account_keys') if isinstance(p.get('account_keys'), dict) else {}
    vendor = p.get('vendor') if isinstance(p.get('vendor'), dict) else {}

    s = SessionLocal()
    try:
        draft = (s.query(ProductDraft)
                 .filter(ProductDraft.id == draft_id,
                         ProductDraft.deleted_at.is_(None)).first())
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)

        rows = preflight_rows(s, draft, markets, codes=codes, keys=keys, vendor=vendor)
        return jsonify({'ok': True, 'rows': rows})
    finally:
        s.close()


@bp.post('/api/drafts/<int:draft_id>/detail/remove-assets')
def remove_detail_assets(draft_id: int):
    """상세에서 **사장님이 고른 이미지만** 뺀다 (자동 제거 ❌ — 2026-07-23 (나)안).

    body: {urls: ['https://…/ssg_banner.jpg', …]}   ← 점검이 보여 준 주소 그대로
    응답: {ok, removed, detail_html, foreign_assets}  ← 뺀 뒤 다시 훑은 결과

    · 준 주소의 `<img>` 만 지운다. 나머지 사진·글은 그대로 남는다.
    · 되돌리기는 **재크롤**이다 — 원본을 따로 보관하지 않는다(중복 원천 금지).
    · 마켓 API 를 부르지 않는다(우리 DB 안 일).
    """
    p = request.get_json(silent=True) or {}
    urls = p.get('urls')
    if not isinstance(urls, list):
        return _err('urls 는 배열이어야 합니다.')
    urls = [str(u).strip() for u in urls if str(u or '').strip()]
    if not urls:
        return _err('빼실 이미지 주소가 없습니다 — 점검 목록에서 골라 주세요.')

    s = SessionLocal()
    try:
        d = (s.query(ProductDraft)
             .filter(ProductDraft.id == draft_id,
                     ProductDraft.deleted_at.is_(None)).first())
        if d is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)
        cleaned, removed = remove_assets_from_detail(d.detail_html or '', urls)
        if removed:
            d.detail_html = cleaned
            s.commit()
        return jsonify({'ok': True, 'removed': removed,
                        'detail_html': d.detail_html or '',
                        'foreign_assets': detect_foreign_market_assets(
                            d.detail_html or '')})
    finally:
        s.close()


def preflight_rows(session, draft, markets, *, codes=None, keys=None, vendor=None):
    """드래프트 1건 × 마켓들 → 점검 결과 행들. 마켓 API 는 부르지 않는다.

    [2026-07-23] 크롤→초안 자동 생성 라우트(from-url)가 「만들자마자 어느 마켓에 뭐가
    부족한지」를 같이 돌려주려고 이 계산을 공용화했다. 두 화면이 서로 다른 판정을
    내놓으면 그게 곧 모순이므로, 복붙하지 않고 **같은 함수**를 쓴다.
    """
    codes = codes or {}
    keys = keys or {}
    vendor = vendor or {}

    # M4-3: 고시정보 기본값(전역·소싱처)을 합친 **읽기 전용 사본**으로 점검한다.
    #   저장된 드래프트는 손대지 않는다. 기본값이 채운 칸은 filled_from 으로 그대로
    #   알려 준다 — 화면이 「내가 넣은 값」과 「기본값이 채운 값」을 구분할 수 있게.
    #   병합 후에도 비는 칸은 여전히 missing 으로 뜬다(폴백 금지 — 지어내지 않는다).
    probe_draft, notice_filled_from = apply_notice_defaults(session, draft)

    # [2026-07-23 (나)안] 상세 안 타 마켓 브랜딩 이미지 — 한 번만 훑어 4마켓에 나눠 싣는다.
    #   (감지만 한다. 지우는 것은 사장님이 「상세에서 빼기」를 누른 주소뿐.)
    foreign_assets = detect_foreign_market_assets(draft.detail_html or '')

    rows = []
    for market in markets:
        mapped = _mapped_category(session, draft, market)
        given = str(codes.get(market) or '').strip() or None
        # 사장님이 확정한 맵핑이 최우선 — 추측이 아니라 확정값이다.
        code = mapped or given
        source = 'mapped' if mapped else ('given' if given else None)
        account_key = str(keys.get(market) or '').strip() or 'default'
        row = _preflight_row(session, probe_draft, market, category_code=code,
                             account_key=account_key, vendor=vendor,
                             foreign_assets=foreign_assets)
        row['category_source'] = source if row['category_code'] else None
        # 고시를 쓰는 마켓은 스마트스토어뿐이다 — 다른 마켓에 붙이면 거짓 안내가 된다.
        row['filled_from'] = notice_filled_from if market == 'smartstore' else {}
        rows.append(row)
    return rows


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
        def _esc(t):
            return t.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

        # [2026-07-24 라이브] 화면은 「검색어를 좁혀 주세요」라고 안내하는데, 정작
        #   「남성의류 티셔츠」로 좁히면 **0건**이었다 — 검색어를 한 덩어리로만 훑어서
        #   그 두 말이 붙어 있는 경로가 없으면 아무것도 못 찾았다. 우리가 준 안내가
        #   작동하지 않는 상태였다. 띄어쓴 말은 **각각** 경로 어딘가에 있으면 된다.
        terms = q.split()
        hits = base.filter(MarketCategory.is_leaf.is_(True))
        for t in terms:
            hits = hits.filter(MarketCategory.full_path.like(f'%{_esc(t)}%', escape='\\'))
        # 순위는 **마지막 말** 기준 — 우리말은 뒤에 오는 말이 찾는 물건이다
        # (「패션잡화 티셔츠」에서 찾는 건 티셔츠). 한 단어면 지금까지와 똑같다.
        escaped = _esc(terms[-1])
        like = f'%{escaped}%'

        # [2026-07-24 라이브 실측] 예전엔 경로 가나다순으로 정렬한 뒤 30건을 잘랐다.
        #   그래서 「스니커즈」 1등이 `식품>…>초코바/스니커즈`(스니커즈 초콜릿), 「가방」
        #   상위가 `가구/홈데코>…>가죽공예DIY패키지`, 「티셔츠」 30건이 반려동물 옷·야구복으로
        #   가득 차 **정작 의류 카테고리는 목록에 나오지도 않았다**(30건 상한에 잘림).
        #   사장님이 맨 위를 고르면 신발이 과자 카테고리로 올라간다 — 화면이 잘못된 선택을
        #   유도하는 셈이라, **관련도로 먼저 줄 세운 뒤** 자른다.
        # 순위: ①리프 이름이 검색어와 정확히 같음 ②이름이 검색어로 **끝남** ③검색어로 시작
        #       ④이름 안에 들어 있음 ⑤윗 단계 경로에만 있음. 같은 순위면 **이름이 짧은 것**
        #       (덜 붙은 말 = 더 정확한 이름) → 경로 가나다순.
        # ★②가 ③보다 위인 이유 — 한국어·영어 합성어는 **뒤에 오는 말이 진짜 정체**다.
        #   「운동화크리너」는 크리너이지 운동화가 아니고, 「남성운동화」는 운동화다.
        #   [2026-07-24 라이브] 처음엔 시작을 위에 뒀다가 「운동화」 1위가
        #   `세탁세제>운동화크리너/세제` 로 나와 바로 잡았다.
        # 여기서 바꾸는 건 **순서뿐**이다 — 무엇이 걸리느냐(부분일치)는 그대로 두었다.
        # 매칭 규칙을 여기서 또 정의하면 규칙이 두 벌이 된다.
        name_col = MarketCategory.name
        rank = case(
            (name_col == terms[-1], 0),
            (name_col.like(f'%{escaped}', escape='\\'), 1),
            (name_col.like(f'{escaped}%', escape='\\'), 2),
            (name_col.like(like, escape='\\'), 3),
            else_=4,
        )
        total = hits.count()
        rows = (hits.order_by(rank, func.length(name_col), MarketCategory.full_path)
                .limit(SEARCH_LIMIT).all())
        # total 을 같이 준다 — 상한에 걸렸는지 알아야 「더 좁혀 검색」할 수 있다(조용한 잘림 금지).
        return jsonify({'ok': True, 'market': market, 'count': len(rows), 'total': total,
                        'limit': SEARCH_LIMIT,
                        'rows': [{'code': r.code, 'name': r.name, 'path': r.full_path} for r in rows]})
    finally:
        s.close()

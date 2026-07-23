# -*- coding: utf-8 -*-
"""대량등록 — 드래프트 CRUD + 등록 라우트."""
import json

from flask import jsonify, request

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
    'coupang': [
        '쿠팡은 계정정보 9칸(vendorId·Wing 로그인ID·반품지코드/반품지명/주소/상세주소/'
        '우편번호/전화·출고지코드)이 필요합니다 — 지금 등록 화면은 이 값을 보내지 않아 '
        '실제 등록은 막힙니다.',
    ],
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


def _preflight_row(session, draft, market, *, category_code, account_key, vendor):
    """마켓 1곳 점검 → 결과 1행. 마켓 API 는 부르지 않는다."""
    row = {'market': market, 'status': 'ready', 'reason': '',
           'category_code': None, 'category_source': None,
           'account_key': account_key,
           'caveats': list(PREFLIGHT_CAVEATS.get(market) or [])}

    # 1) 브랜드·지재권 제한 — 등록 라우트와 **같은 판정기**를 쓴다(두 답이 갈리면 안 된다).
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
        row['reason'] = str(e)
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

        rows = []
        for market in markets:
            mapped = _mapped_category(s, draft, market)
            given = str(codes.get(market) or '').strip() or None
            # 사장님이 확정한 맵핑이 최우선 — 추측이 아니라 확정값이다.
            code = mapped or given
            source = 'mapped' if mapped else ('given' if given else None)
            account_key = str(keys.get(market) or '').strip() or 'default'
            row = _preflight_row(s, draft, market, category_code=code,
                                 account_key=account_key, vendor=vendor)
            row['category_source'] = source if row['category_code'] else None
            rows.append(row)
        return jsonify({'ok': True, 'rows': rows})
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

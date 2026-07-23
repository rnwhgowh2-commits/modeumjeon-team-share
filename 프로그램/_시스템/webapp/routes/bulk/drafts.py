# -*- coding: utf-8 -*-
"""대량등록 — 드래프트 CRUD + 등록 라우트."""
import datetime
import json
import logging
import threading
import uuid

from flask import jsonify, request
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal
from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.registration.service import (
    register_draft, RegisterBlocked, RegisterUnknown, MARKETS, MARKETS_MORE,
    # 장부의 「확인 전까지 잠금」 상태값 — 이름을 두 곳에 복사하면 한쪽만 바뀌어 갈린다.
    LEDGER_UNCERTAIN,
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

logger = logging.getLogger(__name__)

#: 한국 시각 — 마켓이 받는 날짜/시각은 전부 KST 다. 컨테이너는 TZ 설정이 없어 UTC 로
#: 도니까, 마켓에 보낼 시각을 만들 땐 **반드시** 이걸 쓴다(naive now() 금지).
#: 저장소 규약: lemouton/markets/order_export.py 와 같은 정의.
KST = datetime.timezone(datetime.timedelta(hours=9))


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


def _ledger_row(session, draft_id, market, account_key):
    """장부 행을 얻는다(없으면 만든다) — UNIQUE 경합에도 예외로 터지지 않는다.

    [2026-07-23 3차리뷰 사소③] (draft_id, market, account_key) 에 UNIQUE 가 걸려 있어
    두 요청이 동시에 INSERT 하면 한쪽이 IntegrityError 로 죽는다. 그 예외가 등록 경로를
    끊으면 **장부 없는 유령**(마켓엔 있는데 우리 기록엔 없음)이 시작된다.
    """
    row = (session.query(ProductDraftMarket)
           .filter_by(draft_id=draft_id, market=market, account_key=account_key).first())
    if row is not None:
        return row
    row = ProductDraftMarket(draft_id=draft_id, market=market, account_key=account_key)
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        row = (session.query(ProductDraftMarket)
               .filter_by(draft_id=draft_id, market=market,
                          account_key=account_key).first())
        if row is None:
            raise
    return row


def _brand_block_row(session, draft_id, market, *, category_code, account_key, reason,
                     error_code='BRAND_RESTRICTED'):
    """브랜드·지재권으로 막힌 사실을 장부(ProductDraftMarket)에 남긴다.

    막힌 것도 기록이다 — 남기지 않으면 나중에 「왜 이 마켓만 안 올라갔지?」를 알 수 없다.
    error_code: 'BRAND_RESTRICTED'(제한표에 걸림) | 'BRAND_UNKNOWN'(브랜드가 비어 무판정).

    ★ 이미 등록됨(ok)·불확실(uncertain) 행은 **덮지 않는다** — 마켓에 상품이 있을 수도
      있다는 사실이 「막혔다」로 지워지면 그게 곧 중복 등록의 문이 된다.
    """
    row = _ledger_row(session, draft_id, market, account_key)
    if row.status in ('ok', LEDGER_UNCERTAIN):
        return
    row.status = 'blocked'
    row.error_code = error_code
    row.error_message = reason
    if category_code:
        row.category_code = str(category_code)
    session.commit()


def _ledger_extras(session, draft_id, market, account_key):
    """등록 시도 뒤 장부 행에서 **마켓 응답 원문**과 에러코드를 꺼낸다.

    ★ 원문을 버리지 않는다 — 4xx 본문(ESM resultCode 1000 message · 11번가 필드명 ·
      롯데온 data[].resultCode)이 곧 진짜 스펙이고 실패 원인은 거기에만 있다.
      과거이력: 「dry-run(조립 검증)은 마켓 수용성을 못 잡는다 — 400 본문이 진짜 스펙이다.
      raise_for_status 로 본문을 버리면 스펙 발굴이 불가능해진다.」
    """
    row = (session.query(ProductDraftMarket)
           .filter_by(draft_id=draft_id, market=market, account_key=account_key).first())
    if row is None:
        return {}
    raw = row.raw_json or None
    # 표에 그대로 뿌릴 것이라 길이만 자른다(원문 전체는 장부에 그대로 남아 있다).
    return {'error_code': row.error_code, 'raw': (raw[:2000] if raw else None)}


#: 장부 키로 쓰는 「계정 미지정」 센티넬 — 전송 계층에서는 **첫 활성 계정**으로 해석된다.
ACCOUNT_DEFAULT = 'default'


def _account_aliases(session, market, account_key):
    """[C-1 2026-07-23 재리뷰] 장부 계정 키를 **실제 전송 대상**으로 정규화한다.

    Returns:
        (정규화된 키, 같은 물리 계정을 가리키는 키 집합)

    왜 필요한가 — 장부 키는 사장님이 **타이핑한 글자**였는데, 실제 전송 대상은
    `send_more._env_prefix` 가 해석한 **첫 활성 계정**이었다. 그래서 같은 물리 계정인데
    키 문자열이 달라 중복 가드가 통째로 비켜갔다:
      ① 계정칸에 'acctA'(=첫 활성)를 넣고 등록 → 장부 ('lotteon','acctA')=ok
      ② 새로고침하면 화면 상태가 비어 계정칸이 빈칸 → 서버는 'default' 로 조회 →
         히트 없음 → ready + 미리 체크 → 한 번 누르면 **같은 계정에 또** 올라간다.

    해석 규칙은 전송 계층(`send_more._env_prefix`)과 **같아야만** 한다:
      · 4마켓(auction·gmarket·eleven11·lotteon): ''/'default' = 첫 활성 계정.
      · 스스·쿠팡: 계정 배선이 아직 없어 전송이 항상 전역 기본 클라이언트로 나간다
        (`register_draft` 가 'default' 외를 막는다) → 정규화하지 않는다. 여기서
        멋대로 실계정 이름을 붙이면 그게 거짓 장부다.
      · 계정 표가 비어 있으면 전송도 전역 기본으로 나간다 → 'default' 그대로.

    옛 장부 행(정규화 전에 'default' 로 적힌 것)은 **읽을 때 양쪽을 다 본다**(별칭 조회).
    마이그레이션으로 일괄 치환하지 않는 이유: 그건 「지금의 첫 활성 계정」을 과거 등록에
    소급 적용하는 추측이고, 그 사이 계정이 추가·비활성화됐으면 틀린 계정으로 굳는다.
    읽기에서 양쪽을 보면 어느 쪽으로 적혔든 **조용히 놓치는 일이 없다**.
    """
    key = str(account_key or '').strip() or ACCOUNT_DEFAULT
    if market not in MARKETS_MORE:
        return key, {key}

    from lemouton.sourcing.models_v2 import UploadAccount
    q = session.query(UploadAccount).filter_by(market=market, is_active=True)
    first = q.order_by(UploadAccount.id).first()
    first_key = (first.account_key if first else None) or None

    if key == ACCOUNT_DEFAULT:
        # 'default' = 첫 활성 계정. 계정이 하나도 없으면 전역 기본이라 'default' 그대로.
        canonical = first_key or ACCOUNT_DEFAULT
    else:
        canonical = key
    aliases = {canonical, key}
    if first_key and canonical == first_key:
        aliases.add(ACCOUNT_DEFAULT)      # 옛 장부가 'default' 로 적어 둔 같은 계정
    return canonical, aliases


def _ledger_guard(session, draft_id, market, account_key):
    """[C1·C-2] 이 (드래프트 × 마켓 × **물리 계정**)을 지금 올려도 되는가.

    Returns:
        (kind, pid, code, detail)
        kind   = None        올려도 된다(장부에 막을 근거가 없다)
               = 'registered' 이미 등록됐다(status='ok' + 상품번호) — 확실한 중복
               = 'uncertain'  올라갔는지 모른다(status='uncertain') — **확인 전까지 잠금**
        pid    = 아는 상품번호(없으면 None)
        code   = 그 행의 error_code — 문구를 여기서 고른다. 'PARTIAL' 은 상품이 **확정적으로
                 만들어진** 경우라 「모릅니다」라고 말하면 안 된다(3차리뷰 치명③).
        detail = 그 행의 error_message 원문. 회수(판매중지)가 됐는지가 여기에만 있다 —
                 안 읽고 「내려두었습니다」라고 단정하면 거짓 성공이다(4차리뷰 치명②).

    ★ 'registered' 의 근거는 `status=='ok'` **이고** 상품번호가 있는 것뿐이다(성공의
      유일한 증거 = 마켓이 준 상품번호. service.py 의 성공 판정과 같은 규약).
    ★ 'uncertain' 은 상품번호를 몰라도 잠근다 — 「모른다」는 「없다」가 아니다.
      ① ESM 옵션 부착 실패(상품은 생성됨) ② 전송 뒤 끊김. 둘 다 마켓에 상품이 있을 수
      있어서, 여기서 안 잠그면 다음 클릭이 같은 상품을 하나 더 만든다.
    ★ 실패(failed)·막힘(blocked)은 걸리지 않는다 — **재시도는 막지 않는다**.

    여러 별칭 행이 있으면 **잠그는 쪽이 이긴다**(registered > uncertain > 없음) —
    조용히 놓치는 것보다 한 번 더 확인하게 하는 쪽이 싸다.

    ★★ [3차리뷰 중요④] 장부만 보면 **스레드가 죽은 직후~다음 POST 사이**가 빈다.
      그 창에서는 위쪽 점검이 초록(ready·미리체크)인데 아래쪽 결과표는 「확인 필요」라,
      같은 화면이 서로 다른 말을 한다. 그래서 죽은 것으로 의심되는 실행이 **처리 중이던**
      마켓도 여기서 함께 잠근다(읽기 전용 판정 — 아무것도 쓰지 않는다).
      회수(새 POST)가 일어나면 그 사실이 장부에 굳어 이 경로 없이도 잠긴다.
    """
    _, aliases = _account_aliases(session, market, account_key)
    rows = (session.query(ProductDraftMarket)
            .filter(ProductDraftMarket.draft_id == draft_id,
                    ProductDraftMarket.market == market,
                    ProductDraftMarket.account_key.in_(sorted(aliases))).all())
    uncertain = None
    for row in rows:
        pid = (row.market_product_id or '').strip() or None
        if row.status == 'ok' and pid:
            return 'registered', pid, row.error_code, row.error_message
        if row.status == LEDGER_UNCERTAIN:
            uncertain = ('uncertain', pid, row.error_code, row.error_message)
    if uncertain:
        return uncertain
    if _stale_run_holds(session, draft_id, market, aliases):
        return 'uncertain', None, 'UNKNOWN', None
    return None, None, None, None


def _run_done_markets(run):
    """그 실행이 **끝냈다고 기록한** 마켓들(못 읽으면 빈 집합 = 보수적)."""
    if run is None or not run.result_json:
        return set()
    try:
        return {r.get('market') for r in json.loads(run.result_json)}
    except Exception:           # noqa: BLE001 — 못 읽으면 「끝난 기록 없음」으로 본다
        return set()


def _is_dead_run(run, now=None):
    """이 실행은 죽은 것으로 보이는가 — **판정은 이 함수 하나뿐이다.**

    ★★ [4차리뷰 중요①] 예전에는 판정이 세 벌이었다:
        · 폴링      stale or (running=False 인데 error 가 있음)
        · 잠금      running=True 일 때만
        · 장부기록  running=True 일 때만
      그런데 `_register_job` 의 예외 핸들러는 **running=False 로 내리면서 current_market 은
      일부러 남긴다**(어느 마켓에서 끊겼는지가 유령을 찾는 단서라서). 그 상태가 폴링엔
      「죽음」, 잠금엔 「죽음 아님」이라 같은 화면이 서로 다른 말을 했다.
      정의를 한 곳에 모아 셋이 같은 답을 쓴다.

    죽음의 두 모양:
      ① 돌고 있다고 표시돼 있는데 진행률이 STALE_AFTER 넘게 멈췄다(워커째 사망).
      ② 이미 멈췄는데 error 가 남아 있다(예상 밖 예외로 끝났다).
    """
    if run is None:
        return False
    now = now or datetime.datetime.utcnow()
    if run.running:
        reference = run.progress_at or run.started_at
        return reference is None or (now - reference) >= REGISTER_STALE_AFTER
    return bool(run.error)


def _stale_run_holds(session, draft_id, market, aliases):
    """죽은 것으로 **의심되는** 실행이 이 마켓을 처리 중이었나(읽기 전용).

    「의심」이지 단정이 아니다 — 그래서 아무것도 쓰지 않고, 화면을 잠그기만 한다.
    실제로 회수(새 POST)가 일어날 때 `_claim_register_run` 이 장부에 굳힌다.
    """
    from lemouton.registration.models import ProductDraftRegisterRun as R
    run = session.query(R).filter_by(draft_id=draft_id).first()
    if run is None or (run.current_market or None) != market:
        return False
    acct = getattr(run, 'current_account_key', None) or None
    if acct is not None and acct not in aliases:
        return False            # 다른 계정으로 돌던 실행이다(그 계정만 잠근다)
    if not _is_dead_run(run):
        return False            # 아직 멀쩡히 도는 중 — 중복 시작은 409 가 막는다
    return market not in _run_done_markets(run)


def _already_message(market, pid):
    """이미 올라가 있다는 사실 + 상품번호 + 그래도 올리려면 무엇을 해야 하는지."""
    return (f'{MARKET_LABEL.get(market, market)}에 이미 등록돼 있습니다 (상품번호 {pid}) — '
            f'마켓을 부르지 않았습니다. 같은 상품을 한 번 더 올리려면 「다시 올리기」를 '
            f'켜 주세요.')


#: 이름으로 찾는 조회 API 가 없는 마켓 — **어디서 무엇으로 찾는지**를 마켓별로 적는다.
#: [3차리뷰 사소⑤] 「판매자센터에서 확인하세요」로 끝내면 어디를 봐야 할지 모른다.
#: ★ [4차리뷰 사소①] 마크다운 별표를 쓰지 않는다 — 화면이 이 문구를 그대로 이스케이프해
#:   출력하므로 `**상품번호**` 가 별표째 보인다(문구는 평문이어야 한다).
#: ★ [4차리뷰 사소②] 근거: 각 마켓 판매자센터의 **화면 메뉴 이름**이다. 데이터 코드 지도
#:   (marketplace_api_map.json)는 API 스펙만 담고 화면 메뉴는 담지 않아 대조 원천이 없다 —
#:   메뉴가 개편되면 이 문구부터 바뀌어야 한다(코드 동작에는 영향 없음, 안내문 전용).
SELLER_CENTER_HINT = {
    'auction': '옥션 ESM플러스 > 상품관리 > 상품조회/수정 에서 상품번호로 찾으세요.',
    'gmarket': 'G마켓 ESM플러스 > 상품관리 > 상품조회/수정 에서 상품번호로 찾으세요.',
    'smartstore': '스마트스토어센터 > 상품관리 > 상품 조회/수정 에서 상품명으로 찾으세요.',
    'coupang': '쿠팡 Wing > 상품관리 > 상품 조회/수정 에서 상품명으로 찾으세요.',
    'eleven11': '11번가 셀러오피스 > 상품관리 에서 상품명으로 찾으세요.',
    'lotteon': '롯데온 셀러오피스 > 상품관리 에서 상품명으로 찾으세요.',
}

#: send_more 가 옵션 부착 실패 뒤 **회수(판매중지)까지 실패**했을 때 남기는 표식.
#: (lemouton/registration/send_more.py 의 rollback 문구와 짝 — 한쪽만 바뀌면 갈린다.)
ROLLBACK_FAILED_MARK = '판매중지 실패'
ROLLBACK_DONE_MARK = '판매중지로 내려두었습니다'


def _rollback_phrase(detail):
    """회수(판매중지)가 어떻게 됐는지 — **단정하지 않는다**(4차리뷰 치명②).

    옵션 부착 실패 시 send_more 는 판매중지를 시도하는데, 그 시도는 **실패할 수 있다**
    (등록 직후 2~3분은 수정이 막힌다 — 실측 주석). 실패했는데 「내려두었습니다」라고
    말하면 사장님이 안심하고 안 내려간다 → 옵션 없는 상품이 계속 판매중이다(금전 손실).
    장부에 남은 원문(error_message)에서 그 결과를 읽어 세 갈래로 말한다.
    """
    text = str(detail or '')
    if ROLLBACK_FAILED_MARK in text:
        return ('⚠ 판매중지에는 실패했습니다 — 그 상품이 아직 판매중일 수 있으니 '
                '셀러센터에서 직접 내려주세요.')
    if ROLLBACK_DONE_MARK in text:
        return '판매중지로 내려두었습니다.'
    return '판매중지까지 됐는지는 확인하지 못했습니다 — 셀러센터에서 상태를 확인해 주세요.'


def _where_to_check(market):
    """이 마켓에서 사람이 직접 확인하는 방법 한 줄(앞에 공백 하나)."""
    hint = SELLER_CENTER_HINT.get(market)
    return f' {hint}' if hint else ''


def _uncertain_ledger_message(market, pid, code=None, detail=None):
    """확인 전까지 잠근다는 사실 + 무엇을 확인해야 하는지.

    ★★ [3차리뷰 치명③] 상품이 **확정적으로 만들어진** 경우(PARTIAL)에는 「모릅니다」를
      쓰지 않는다. 상품번호를 찍어 놓고 「생겼는지 모릅니다」라고 하면 한 문장 안에서
      자기모순이고, 그 말을 들은 사람은 못 찾았다고 판단해 다시 올린다(= 중복).
    """
    label = MARKET_LABEL.get(market, market)
    if code == 'PARTIAL' and pid:
        return (f'{label}에 상품이 만들어졌습니다 (상품번호 {pid}). 옵션 부착만 실패했고 '
                f'{_rollback_phrase(detail)}'
                f'{_where_to_check(market)} 그 상품을 쓰실 거면 「이 상품번호로 확정」, '
                f'지우고 새로 올리실 거면 「다시 올리기」를 켜 주세요.')
    where = f'(마지막으로 받은 상품번호 {pid}) ' if pid else ''
    return (f'{label}에 상품이 생겼는지 아직 모릅니다 {where}— '
            f'마켓에서 확인하기 전까지 다시 올리지 않습니다.{_where_to_check(market)} '
            f'있으면 「이 상품번호로 확정」, 없으면 「다시 올리기」를 켜 주세요.')


def _register_one(session, draft_id, market, *, category_code, account_key, vendor,
                  allow_reregister=False):
    """마켓 1곳 등록 → 결과 1행. 단수·복수 라우트가 **같은 함수**를 쓴다.

    한 마켓의 실패가 예외로 새어 나가 다른 마켓을 막지 않도록 여기서 전부 행으로
    바꾼다(부분 성공 허용). status = ok / failed / blocked / already / unknown.

    allow_reregister: 「다시 올리기」 명시적 opt-in. 기본은 False —
        이미 등록된 마켓은 **마켓을 부르지 않는다**.
    """
    # ★ [C-1] 장부에 쓰고 읽는 계정 키를 **실제 전송 대상**으로 맞춘다. 이걸 안 하면
    #   빈칸('default')과 그 계정 이름이 서로 다른 키가 되어 가드가 통째로 비켜간다.
    account_key, _ = _account_aliases(session, market, account_key)

    out = {'market': market, 'status': 'failed', 'account_key': account_key,
           'category_code': str(category_code) if category_code else None,
           'market_product_id': None, 'error_code': None, 'error': None,
           'reason': '', 'raw': None, 'excluded': []}

    # ★★ [C1 2026-07-23 리뷰] 이미 등록된(또는 올라갔는지 모르는) 마켓은 **어떤 검사보다
    #    먼저** 막는다. 이 가드가 없으면 정상 워크플로가 그대로 사고였다: 6마켓 중 3개
    #    성공·3개 값부족 → 빠진 값을 채우고 「다시 점검」 → 6개가 전부 ready 로 나오고
    #    화면이 미리 체크까지 해 준다 → 한 번 누르면 이미 팔리고 있는 3개가 또 올라간다.
    #    ★ 판정을 화면이 아니라 여기서 한다 — 누가 markets 를 직접 POST 해도 버텨야 한다.
    if not allow_reregister:
        kind, pid, code, detail = _ledger_guard(session, draft_id, market, account_key)
        if kind == 'registered':
            out.update(status='already', market_product_id=pid,
                       error_code='ALREADY_REGISTERED',
                       reason=_already_message(market, pid))
            return out
        if kind == 'uncertain':
            # 「모른다」는 「없다」가 아니다 — 확인 전까지 마켓을 부르지 않는다(C-2).
            out.update(status='uncertain', market_product_id=pid,
                       error_code='UNCERTAIN_LEDGER',
                       reason=_uncertain_ledger_message(market, pid, code, detail),
                       lookup_supported=(market in LOOKUP_MARKETS))
            return out

    # M2: 브랜드·지재권 제한 — 걸리면 마켓을 호출하지 않는다(선차단).
    #   [리뷰 C2·머지] 브랜드가 비어 **판정 자체가 불가능한** 경우도 같은 자리에서 막는다.
    #   예전엔 단수 라우트가 이 검사를 인라인으로 한 벌 더 갖고 있었다 — 판정기가 둘이면
    #   언젠가 한쪽만 고쳐져 답이 갈린다. 여기 하나로 합쳐 단수·복수가 같은 답을 낸다.
    draft = session.query(ProductDraft).filter_by(id=draft_id).first()
    need_brand = _brand_missing_block(session, draft)
    reason = need_brand or _brand_restriction_block(
        session, draft, market, category_code=category_code)
    if reason:
        code = 'BRAND_UNKNOWN' if need_brand else 'BRAND_RESTRICTED'
        _brand_block_row(session, draft_id, market, category_code=category_code,
                         account_key=account_key, reason=reason, error_code=code)
        out.update(status='blocked', error_code=code, reason=reason)
        return out

    try:
        r = register_draft(session, draft_id, market,
                           category_code=category_code,
                           vendor=vendor,
                           account_key=account_key)
    except RegisterBlocked as e:
        # 게이트 OFF 는 '에러'가 아니라 '막힘' — 컴파일은 통과했다는 뜻이다.
        out.update(status='blocked', error_code='LIVE_OFF', error=str(e), reason=str(e))
        out.update(_ledger_extras(session, draft_id, market, account_key))
        return out
    except RegisterUnknown as e:
        # ★ [4차리뷰 중요②] 마켓 호출이 **나간 뒤** 우리 쪽에서 터졌다 — 상품이
        #   만들어졌을 수 있다. 「실패」로 적으면 다음 점검이 ready 로 내줘 중복이 된다.
        #   장부에도 '확인 필요'를 남겨 다음 점검이 잠그게 한다(결과표만 고치면 또 샌다).
        logger.exception('전송 뒤 예외 draft_id=%s market=%s', draft_id, market)
        _uncertain_ledger_row(session, draft_id, market, account_key=account_key,
                              reason=str(e))
        out.update(error_code='UNKNOWN_AFTER_SEND', error=str(e))
        _mark_uncertain(out, market)
        return out
    except ValueError as e:
        # 없는 드래프트·못 쓰는 계정키 — 요청이 잘못된 것이다(마켓 호출은 없었다).
        out.update(status='failed', error_code='BAD_REQUEST', error=str(e), reason=str(e))
        return out
    except Exception as e:      # noqa: BLE001 — 한 마켓의 뜻밖의 예외가 나머지를 막으면 안 된다
        logger.exception('등록 중 예상 못한 예외 draft_id=%s market=%s', draft_id, market)
        out.update(status='failed', error_code='UNEXPECTED', error=str(e), reason=str(e))
        return out

    # 쿠팡 계정정보가 **한 칸이라도** 비어 컴파일이 막힌 것이면 어디서 채우는지까지
    # 말한다. [2026-07-23 리뷰 C1] 전에는 `not vendor`(통째로 없음)만 봐서, 부분 저장
    # 상태에서는 「무엇이 비었다」만 나오고 어디서 채우는지는 안 나왔다.
    # (register_draft 는 실패 사유를 row 에도 남겼다 — 여기선 화면 문구만 보탠다.)
    err = r.get('error')
    if (not r.get('ok') and market == 'coupang'
            and _vendor_incomplete(vendor) and err):
        err = err + COUPANG_VENDOR_HINT
    ok = bool(r.get('ok'))
    out.update(status=('ok' if ok else 'failed'),
               market_product_id=r.get('market_product_id'),
               error=err, reason=('' if ok else (err or '')),
               excluded=(r.get('excluded') or []))
    out.update(_ledger_extras(session, draft_id, market, account_key))
    # ★ [I2 2026-07-23 리뷰] 「보낸 뒤(또는 보냈는지 모르는 채) 끊김」은 **실패가 아니다**.
    #   그 순간 마켓에는 상품이 만들어져 있을 수 있다 — 화면에 「실패」로 뜨면 그 유령
    #   상품을 아무도 찾지 않는다.
    #   ★★ [재리뷰 I-B] 반대로 **보내기 전 확정 실패(PREREQ)** 를 불확실로 칠하면 안 된다.
    #     확인할 것도 없는 「확인 필요」가 상시로 뜨면 진짜 유령 경고가 그 속에 묻힌다.
    #     판정 근거는 service.py 가 장부에 적은 error_code 다(문구가 아니라 코드로 분기).
    if out.get('error_code') in UNCERTAIN_ERROR_CODES:
        _mark_uncertain(out, market)
    return out


#: 「상품이 만들어졌(을 수도 있)다」는 뜻의 장부 error_code — service.py 가 붙인다.
#:   CALL          보낸 뒤(또는 보냈는지 모르는 채) 끊김 — 모른다
#:   NO_PRODUCT_ID 응답은 왔는데 상품ID 를 못 찾았다 — 모른다(3차리뷰 중요①)
#:   PARTIAL       상품은 **확정적으로** 만들어졌고 뒤 단계만 실패 — 안다
#: PREREQ(보내기 전 확정 실패)는 여기 **없다** — 그건 확정 실패다.
UNCERTAIN_ERROR_CODES = ('CALL', 'NO_PRODUCT_ID', 'PARTIAL', 'UNKNOWN_AFTER_SEND')


def _mark_uncertain(out, market):
    """결과행을 **불확실**로 바꾼다 — 장부와 같은 문구·같은 확인 수단.

    ★★ [3차리뷰 치명③] PARTIAL 은 상품이 확정적으로 만들어진 경우다. 「연결이 끊겼습니다
      — 올라갔는지 모릅니다」로 말하면 사실과 다르고, 그 말을 믿은 사람이 못 찾으면
      다시 올려 중복이 된다. 코드층에서 가른 것을 사람층에서 되돌리지 않는다.
    """
    detail = (out.get('error') or '').strip()
    if out.get('error_code') == 'PARTIAL':
        pid = out.get('market_product_id')
        # 회수(판매중지) 성공/실패는 원문에만 있다 — 그대로 넘겨 갈라 말하게 한다.
        msg = _uncertain_ledger_message(market, pid, 'PARTIAL', detail)
    else:
        msg = _uncertain_message(market) + _where_to_check(market)
    if detail:
        # 원문을 버리지 않는다 — 4xx 본문·예외 원문이 진짜 사유다.
        msg += f' (원문: {detail})'
    out.update(status='unknown', error=msg, reason=msg,
               lookup_supported=(market in LOOKUP_MARKETS),
               # 확정은 6마켓 전부 — 조회 API 가 없어도 사람이 번호를 넣을 수 있다.
               confirm_supported=True)


@bp.post('/api/drafts/<int:draft_id>/register/<market>')
def register(draft_id: int, market: str):
    """마켓 **1곳** 등록 — 하위 호환용. 복수 등록은 POST …/register (markets 배열).

    응답 모양은 예전 그대로 둔다(register_draft 반환 + blocked 플래그) — 이 라우트를
    직접 부르는 호출자·테스트가 이미 있다. 판정은 _register_one 하나로 합쳐,
    단수·복수가 서로 다른 답을 낼 수 없게 했다.

    body 의 `reregister: true` 는 「이미 등록된 마켓에 한 번 더 올린다」는 명시적
    opt-in 이다(기본 false — 안 보내면 이미 등록된 마켓은 아예 부르지 않는다).

    ★★ [재리뷰 I-C] 이 라우트도 **복수 등록과 같은 실행 잠금**에 참여한다. 예전에는
      참여하지 않아서, 복수 잡이 도는 중 같은 드래프트·마켓으로 단수 POST 가 들어오면
      409 없이 **동시에** 마켓을 불렀다(라이브는 DISABLE_AUTH=1 이라 누구나 부를 수 있다).
      진행 중이면 409, 끝나면 잠금을 반드시 돌려준다(안 풀면 그 드래프트는 스테일 5분이
      지나기 전까지 아무것도 못 올린다).
    """
    if market not in MARKETS:
        return _err(f'market 은 {MARKETS} 중 하나여야 해요.')
    p = request.get_json(silent=True) or {}
    if not p.get('category_code'):
        return _err('카테고리를 먼저 정해 주세요.')

    s = SessionLocal()
    job_id = None
    row = None
    try:
        draft = s.query(ProductDraft).filter_by(id=draft_id).first()
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)

        job_id = _claim_register_run(s, draft_id, [market])
        if job_id is None:
            return jsonify({'ok': False,
                            'error': '이 상품은 이미 등록이 진행 중입니다 — 끝날 때까지 '
                                     '기다려 주세요(다시 누르면 같은 상품이 두 번 '
                                     '올라갑니다).'}), 409
        # 복수 등록과 같은 규약 — 부르기 **전에** 어느 마켓을 **어느 계정으로**
        # 시작했는지 남긴다(여기서 워커가 죽으면 그 마켓이 '불확실'로 보고된다).
        _write_current_market(draft_id, job_id, market,
                              account_key=_account_aliases(
                                  s, market, p.get('account_key'))[0])

        # ★ 브랜드 무판정(BRAND_UNKNOWN)·지재권 제한 차단은 **_register_one 안에** 있다.
        #   예전엔 이 라우트가 같은 검사를 인라인으로 한 벌 더 갖고 있었는데, 판정기가
        #   둘이면 언젠가 한쪽만 고쳐져 답이 갈린다(이 파일이 반복해서 겪은 사고 형태다).

        vendor = _vendor_for(s, market, p)
        row = _register_one(s, draft_id, market,
                            category_code=p['category_code'],
                            account_key=(p.get('account_key') or 'default'),
                            vendor=vendor,
                            allow_reregister=bool(p.get('reregister')))
        # [C1] 이미 올라가 있어 부르지 않았다 — 「실패」가 아니라 「안 불렀다」다.
        if row['status'] == 'already':
            return jsonify({'ok': False, 'already': True,
                            'market_product_id': row['market_product_id'],
                            'error': row['reason']})
        # [C-2] 올라갔는지 모르는 장부가 있어 부르지 않았다 — 확인이 먼저다.
        if row['status'] == 'uncertain':
            return jsonify({'ok': False, 'uncertain': True,
                            'market_product_id': row['market_product_id'],
                            'error': row['reason'],
                            'lookup_supported': row.get('lookup_supported', False)})
        if row['status'] == 'blocked':
            if row['error_code'] in ('BRAND_RESTRICTED', 'BRAND_UNKNOWN'):
                return jsonify({'ok': False, 'blocked': True, 'reason': row['reason']})
            return jsonify({'ok': False, 'blocked': True, 'error': row['error']})
        if row['error_code'] == 'BAD_REQUEST':
            return _err(row['error'], 404)
        if row['error_code'] == 'UNEXPECTED':
            return _err(row['error'], 500)
        # [I2] 전송 중 끊김 — 실패로 단정하지 않는다(마켓에 상품이 생겼을 수 있다).
        if row['status'] == 'unknown':
            return jsonify({'ok': False, 'unknown': True,
                            'market_product_id': None, 'error': row['error'],
                            'lookup_supported': row.get('lookup_supported', False)})
        return jsonify({'ok': row['status'] == 'ok',
                        'market_product_id': row['market_product_id'],
                        'error': row['error'],
                        'excluded': row['excluded']})
    finally:
        # ★ 잠금은 반드시 돌려준다 — 예외로 빠져나가도(응답이 500 이어도) 여기를 지난다.
        #   결과행도 같이 남긴다: 안 남기면 폴링이 이 마켓을 pending(=「부른 적 없다」가
        #   확실한 칸)으로 보고한다 — 방금 불러 놓고 안 불렀다고 말하는 셈이다.
        if job_id is not None:
            _register_run_write(draft_id, job_id, running=False,
                                finished_at=datetime.datetime.utcnow(),
                                current_market=None,
                                result_json=(json.dumps([row]) if row else None),
                                done_count=(1 if row else 0))
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
                   draft_id=None, reregister=False, foreign_assets=None):
    """마켓 1곳 점검 → 결과 1행. 마켓 API 는 부르지 않는다.

    [2026-07-23 M4-2] 쿠팡 vendor 는 요청이 안 보내면 **계정 저장값**으로 채운다.
    저장값 조회는 우리 DB 뿐이라 「마켓 API 를 안 부른다」는 이 라우트의 전제는 그대로다.

    draft_id: 장부 조회용 **저장된** 드래프트 id (draft 는 고시 기본값을 합친 사본이라
        id 가 없을 수 있다). 없으면 '이미 등록됨' 판정을 건너뛴다.
    reregister: 이 마켓에 「다시 올리기」를 켰는가(명시적 opt-in).

    [2026-07-23 (나)안] `foreign_assets` = 상세 HTML 안 타 마켓 브랜딩 이미지.
    상세를 본문으로 그대로 쓰는 4마켓(MARKETS_MORE)에만 싣는다 — 스스·쿠팡 행에
    붙이면 거짓 안내가 된다.
    """
    # [C-1] 계정 키는 **실제 전송 대상**으로 정규화해서 보여주고 조회한다
    #   (빈칸 'default' 와 그 계정 이름이 다른 키가 되면 가드가 비켜간다).
    account_key = _account_aliases(session, market, account_key)[0]

    row = {'market': market, 'status': 'ready', 'reason': '',
           'category_code': None, 'category_source': None,
           'account_key': account_key, 'market_product_id': None,
           'foreign_assets': (list(foreign_assets or [])
                              if market in MARKETS_MORE else []),
           'caveats': list(PREFLIGHT_CAVEATS.get(market) or [])}
    if row['foreign_assets']:
        row['caveats'].append(
            FOREIGN_ASSET_CAVEAT.format(n=len(row['foreign_assets'])))

    # ★ [C1·C-2] 0) 이미 등록됨 / 올라갔는지 모름 — 다른 어떤 사유보다 **먼저** 본다.
    #    등록 판정기(_register_one)도 같은 순서로 막으므로 「점검은 초록인데 등록은
    #    안 나감」이 생길 수 없다. 화면은 두 상태 모두 체크박스를 잠그고 **끈다**
    #    (미리 체크된 채로 주면 그 한 번의 클릭이 곧 사고다).
    if draft_id is not None and not reregister:
        kind, pid, code, detail = _ledger_guard(session, draft_id, market, account_key)
        if kind == 'registered':
            row['status'] = 'registered'
            row['market_product_id'] = pid
            row['reason'] = _already_message(market, pid)
            return row
        if kind == 'uncertain':
            row['status'] = 'uncertain'
            row['market_product_id'] = pid
            row['reason'] = _uncertain_ledger_message(market, pid, code, detail)
            row['lookup_supported'] = market in LOOKUP_MARKETS
            # ★ [4차리뷰 치명①] 확정(「이 상품번호로 확정」)은 **6마켓 전부** 가능하다 —
            #   조회 API 유무와 무관하다(조회는 편의, 확정은 탈출구). 화면이 이 칸을 보고
            #   확정 UI 를 그린다. 이게 없으면 4마켓은 「다시 올리기」밖에 남지 않는다.
            row['confirm_supported'] = True
            return row

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


def preflight_rows(session, draft, markets, *, codes=None, keys=None, vendor=None,
                   reregister=None):
    """마켓 목록 → 사전점검 결과 행들. **마켓 API 를 한 번도 부르지 않는다.**

    [2026-07-23 M4-6] 이 함수가 「올릴 수 있는가」의 **단일 판정기**다. 점검 라우트와
    복수 등록 라우트가 같은 함수를 쓰기 때문에 두 화면의 답이 갈릴 수 없다. 예전처럼
    라우트 안에 판정을 인라인해 두면, 등록 쪽에서 조건 하나만 빠져도 「점검은 초록인데
    등록은 실패」(또는 그 반대)가 되어 사장님이 어느 쪽을 믿어야 할지 알 수 없게 된다.

    Args:
        draft: **저장된 원본** 드래프트. 고시 기본값 병합 사본은 여기서 만든다
            (호출자가 각자 병합하면 병합을 빼먹은 쪽만 다른 답을 낸다).
        codes/keys: {market: 값}. 카테고리는 confirmed 맵핑이 최우선이고, 여기 준 값은
            맵핑이 없을 때만 쓴다.
        reregister: 「다시 올리기」를 켠 마켓 목록. 여기 없는 마켓은 이미 등록돼 있으면
            registered 로 잠긴다(기본 = 아무것도 안 켬).

    [2026-07-23] 크롤→초안 자동 생성 라우트(from-url)도 「만들자마자 어느 마켓에 뭐가
    부족한지」를 이 함수로 받는다 — 두 화면이 다른 판정을 내면 그게 곧 모순이다.

    Returns:
        [{market, status, reason, category_code, category_source, account_key,
          market_product_id, caveats, filled_from}]
        status = ready / missing / blocked / need_category / registered / uncertain
        (account_key 는 **해석된 물리 계정** — 빈칸으로 보내도 실제로 나갈 계정이 온다)
    """
    codes = codes if isinstance(codes, dict) else {}
    keys = keys if isinstance(keys, dict) else {}
    vendor = vendor if isinstance(vendor, dict) else {}
    # 리스트든 {market: bool} 이든 받아 「켠 마켓 집합」으로 정규화한다.
    if isinstance(reregister, dict):
        redo = {m for m, v in reregister.items() if v}
    else:
        redo = {str(m) for m in (reregister or []) if m}

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
                             draft_id=draft.id, reregister=(market in redo),
                             foreign_assets=foreign_assets)
        row['category_source'] = source if row['category_code'] else None
        # 고시를 쓰는 마켓은 스마트스토어뿐이다 — 다른 마켓에 붙이면 거짓 안내가 된다.
        row['filled_from'] = notice_filled_from if market == 'smartstore' else {}
        rows.append(row)
    return rows


@bp.post('/api/drafts/<int:draft_id>/preflight')
def preflight(draft_id: int):
    """등록 버튼을 누르기 **전에** — 어느 마켓에 올릴 수 있고, 어느 마켓은 무엇이 비었는지.

    body(전부 선택):
      markets        : ['smartstore', ...]  생략하면 6마켓 전부
      category_codes : {market: code}       confirmed 맵핑이 없을 때만 쓴다
      account_keys   : {market: key}        생략하면 'default'
      vendor         : {...}                쿠팡 계정정보
      reregister     : ['smartstore', ...]  「다시 올리기」를 켠 마켓(기본 없음)

    응답: {ok, rows: [{market, status, reason, category_code, category_source,
                       account_key, market_product_id, caveats}]}
      status = ready(올릴 수 있음) / missing(보충 필요) / blocked(제외) /
               need_category(카테고리 필요) / registered(이미 등록됨 — 잠금)

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

    s = SessionLocal()
    try:
        draft = (s.query(ProductDraft)
                 .filter(ProductDraft.id == draft_id,
                         ProductDraft.deleted_at.is_(None)).first())
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)
        rows = preflight_rows(s, draft, markets,
                              codes=p.get('category_codes'),
                              keys=p.get('account_keys'),
                              vendor=p.get('vendor'),
                              reregister=p.get('reregister'))
        return jsonify({'ok': True, 'rows': rows})
    finally:
        s.close()


# ── M4-6 여러 마켓에 한 번에 등록 ───────────────────────────────────────────
#
# 마켓을 하나씩 골라 하나씩 결과를 보던 것을, 한 번 눌러 마켓별 결과표로 본다.
#
# 설계 고정 3가지:
#   ① **사전점검을 먼저** 돌려 ready 가 아닌 마켓은 아예 호출하지 않는다. 판정기는
#      preflight_rows 하나뿐이라 「점검은 초록인데 등록은 실패」가 나올 수 없다.
#   ② **마켓 간 병렬 금지** — 순차로 돈다. 이 저장소의 속도정책(계정별 버킷·ESM 5초/1회)
#      과 「다계정 순차 조회」 원칙을 등록에도 그대로 적용한다.
#   ③ **부분 성공 허용** — 한 마켓의 실패가 다른 마켓을 막지 않는다. 각 마켓은 끝날 때마다
#      제 장부 행을 커밋하므로, 중간에 요청이 죽어도 앞 마켓 기록은 남는다.

#: 등록이 **성공한 뒤에도** 사람이 반드시 알아야 하는 마켓별 사실.
#: 과거이력에서 실제로 사고가 났던 것들만 적는다(장식용 문구 금지).
POST_REGISTER_NOTES = {
    'smartstore': [
        '등록 직후 판매중지(초안)로 되돌립니다 — 그 전환이 실패하면 상품이 판매중으로 '
        '남습니다(결과에 그 사실이 기록됩니다).',
    ],
    'coupang': [],
    'auction': [
        '등록 직후 2~3분은 수정이 막힙니다 — 곧바로 가격·옵션을 고치면 실패할 수 있습니다.',
        '옵션 붙이기가 실패하면 상품을 자동으로 판매중지로 되돌립니다(유령 상품 방지).',
    ],
    'eleven11': [],
    'lotteon': [
        '본보기 상품(spdNo)의 상세를 복사해 등록합니다 — 상품번호가 나왔다고 내용까지 '
        '맞는 것은 아닙니다. 옵션·가격은 롯데온에서 실물로 확인해 주세요.',
    ],
}
POST_REGISTER_NOTES['gmarket'] = list(POST_REGISTER_NOTES['auction'])

#: 사전점검에서 걸러진 마켓의 결과 status — 점검의 세부 사유는 preflight_status 로 남긴다.
#: registered → already: 「안 올린 것」이 아니라 「이미 올라가 있어서 안 부른 것」이다.
#: uncertain  → uncertain: 「올라갔는지 몰라서 안 부른 것」 — 확인이 먼저다.
_SKIP_STATUS = {'missing': 'skipped', 'need_category': 'skipped', 'blocked': 'blocked',
                'need_brand': 'blocked',
                'registered': 'already', 'uncertain': 'uncertain'}
#: 걸러진 사유의 기계 판독용 코드 — 화면·로그가 문구가 아니라 이걸로 분기한다.
_SKIP_ERROR_CODE = {'blocked': 'BRAND_RESTRICTED', 'need_brand': 'BRAND_UNKNOWN',
                    'registered': 'ALREADY_REGISTERED',
                    'uncertain': 'UNCERTAIN_LEDGER'}
#: 점검 caveat 을 결과행에 붙이면 **안 되는** 상태 — 부르지도 않은 마켓에 「등록할 때
#: 이미지를 다시 올립니다」 같은 주의가 붙으면 읽는 사람이 시도한 줄 안다(리뷰 사소②).
_SKIP_NO_CAVEATS = ('registered', 'uncertain')

#: 화면에 쓰는 마켓 한글 이름 — 서버가 만드는 문구에도 같은 이름을 쓴다(화면·서버 불일치 금지).
MARKET_LABEL = {
    'smartstore': '스마트스토어', 'coupang': '쿠팡', 'auction': '옥션',
    'gmarket': 'G마켓', 'eleven11': '11번가', 'lotteon': '롯데온',
}

# ── M4-7 등록을 백그라운드로 (gunicorn 60초 워커 사망 차단) ──────────────────
#
# 이 저장소의 Dockerfile 은 gunicorn 을 `--timeout 60`(sync worker)로 띄운다. 6마켓
# 순차 등록은 마켓 하나당 수 초~수십 초라 한 요청 안에서 끝나지 않는다 — 60초를 넘기면
# 워커가 죽고 **요청도 응답도 증발**한다. 그때 이미 마켓에 만들어진 상품은 회수(판매중지)
# 로직이 돌지 못한 채 남는다. 과거이력의 「502 로 워커가 죽어 롤백이 안 돌아 유령 상품이
# 남은 사고」가 정확히 이 조건이다. 그래서:
#
#   POST …/register        → 202 {ok, started, job_id} 즉시 (이미 진행 중이면 409)
#   GET  …/register/status → 그때까지 확정된 결과행을 폴링으로 받는다
#
# 실행 상태는 DB 테이블(ProductDraftRegisterRun)에 둔다 — 라이브가 gunicorn 3워커라
# 프로세스 메모리는 무효다(카테고리 수집에서 이미 겪은 문제. 등록에서 그 오판은
# **중복 등록 = 유령 상품**으로 직결된다).

#: 진행률(progress_at)이 이만큼 안 움직이면 죽은 실행으로 **의심**한다.
#: 카테고리 수집은 20초 스로틀로 진행률을 갱신하지만(노드가 수천 개) 등록은 마켓이 최대
#: 6개뿐이라 스로틀 없이 마켓 시작·완료마다 기록한다. 그래서 이 값은 곧 「마켓 한 곳이
#: 이보다 오래 걸릴 리 없다」의 상한이다 — ESM 은 등록+옵션 PUT+판매중지까지 묶여 수 분이
#: 걸린 실측이 있어 넉넉히 5분으로 둔다(짧게 잡으면 멀쩡히 도는 실행을 죽었다고 오판해
#: 사장님이 중복 등록을 누르게 된다 — 오판의 대가가 비대칭이라 넉넉한 쪽으로).
REGISTER_STALE_AFTER = datetime.timedelta(minutes=5)

#: 불확실한 마켓의 결과행에 붙이는 주의 — 「확인해야 한다」는 행동을 말한다.
UNCERTAIN_NOTE = '마켓에서 상품 존재 확인 필요'

#: 상품 조회 API 가 **이미 있고, 상품번호 없이 이름으로 찾을 수 있는** 마켓.
#: 근거(shared/platforms/*/products.py 전수 확인):
#:   · eleven11.search_products(name=…)  → 상품명 검색 가능           ✅
#:   · lotteon.list_products(...)        → 목록을 받아 이름으로 거른다 ✅ (_lotteon_sample_search 와 같은 방식)
#:   · coupang.get_product(productId)    → 상품번호가 있어야 한다. 불확실하다는 건 그 번호를
#:                                          못 받았다는 뜻이라 조회에 쓸 수 없다        ❌
#:   · esm.resolve_goods_no(사이트상품번호) → 위와 같은 이유로 불가                      ❌
#:   · smartstore                        → products.py 자체가 없다                     ❌
#: 없는 마켓에 가짜 버튼을 붙이지 않는다 — 눌러도 못 찾는 버튼은 "없다"는 거짓 확신을 준다.
LOOKUP_MARKETS = ('eleven11', 'lotteon')

# ── [I1 2026-07-23 리뷰] 롯데온 유령 확인은 **페이지를 넘겨** 훑는다 ──────────
#
# 예전 구현은 `list_products(rows_per_page=100)` 한 번(=최근 1년·1페이지·100행)을 훑고
# 못 찾으면 「0건」이라 답했다. 그런데 지도(marketplace_api_map.json · lotteon.product.list)
# 의 실측 응답이 그 계정 카탈로그를 **dataCount 13,883** 으로 기록하고 있다 — 방금 올라간
# 상품이 그 100행 안에 들어 있을 리가 없다. 즉 **실제로 올라간 유령을 두고 「없다」고
# 답하는 거짓 답**이었고, 그 답을 믿고 다시 누르면 그게 곧 중복 등록(C1 이 막으려는
# 바로 그 사고)이다.
#
# 지도가 알려주는 요청 스펙(추측 금지 — 지도 그대로):
#   POST /v1/openapi/product/v1/product/list
#   필수 regStrtDttm·regEndDttm (YYYYMMDDHHMMSS **14자리**, 8자리면 INVALID_INPUT)
#        pageNo(1부터) · rowsPerPage(MAX 100)   ← 빠지면 returnCode 9000
#   (조회기간 자체의 상한은 지도에 없다 = 확인불가. 여기서 쓰는 값은 그보다 훨씬 짧다.)

#: 등록은 **최근에** 일어난 일이다 — 1년치를 훑으면 상한에 먼저 걸려 정작 새 상품을 놓친다.
#: [재리뷰 사소⑤] 1일이면 하루 지난 유령은 영영 못 찾는다(사고를 다음 날 알아채는 일이
#: 흔하다). 조회기간 상한이 「확인불가」인 지금은 넉넉한 7일 쪽이 안전하다 —
#: 2,000행 상한 안에서도 7일치 신규 등록은 대개 다 들어온다.
LOOKUP_RECENT_DAYS = 7
#: 무한 루프 방지 상한(100행 × 20 = 2,000행). ★ 상한에 걸린 사실은 응답에 그대로 싣는다 —
#: 숨기면 「못 다 봤다」가 「없다」로 둔갑한다.
LOOKUP_MAX_PAGES = 20
#: 11번가는 마켓이 이름으로 직접 찾아준다 — 이 수만큼 받아 보고, 꽉 차면 잘렸다고 본다.
ELEVEN11_LOOKUP_LIMIT = 50


def _lotteon_lookup(client, name):
    """롯데온에서 상품명으로 찾기 — 등록 직후 구간을 페이지를 넘겨 훑는다.

    Returns:
        (hits, scanned, pages, complete)
        hits     : [{code, name}]  이름이 포함된 상품
        scanned  : 실제로 훑은 행 수(= 확인한 범위)
        pages    : 실제로 부른 페이지 수
        complete : 목록을 **끝까지** 봤는가(False = 상한에 걸려 못 다 봤다)
    """
    from shared.platforms.lotteon import products as LP

    # ★★ [재리뷰 I-A] 시간대를 **KST 로 못 박는다.** 롯데온이 받는 regStrtDttm/regEndDttm
    #   은 한국 시각인데, 라이브 컨테이너는 TZ 설정이 없어 UTC 로 돈다(Dockerfile 확인).
    #   naive `datetime.now()` 를 쓰면 창이 9시간 과거로 밀려 [KST now-9h-Nd, KST now-9h]
    #   가 되고 **방금 올라간 유령은 언제나 창 밖**이다 — 조회는 늘 0건, 화면은 늘 「없다」.
    #   (저장소 규약: lemouton/markets/order_export.py 의 KST 상수와 같은 정의)
    now = datetime.datetime.now(KST)
    reg_start = (now - datetime.timedelta(days=LOOKUP_RECENT_DAYS)).strftime('%Y%m%d%H%M%S')
    reg_end = now.strftime('%Y%m%d%H%M%S')
    needle = name.lower()

    hits, scanned, pages, complete = [], 0, 0, False
    for page in range(1, LOOKUP_MAX_PAGES + 1):
        rows = LP.list_products(client=client, reg_start=reg_start, reg_end=reg_end,
                                page_no=page, rows_per_page=100)
        rows = [r for r in (rows or []) if isinstance(r, dict)]
        pages = page
        scanned += len(rows)
        hits += [{'code': str(r.get('spdNo') or ''), 'name': str(r.get('spdNm') or '')[:80]}
                 for r in rows if needle in str(r.get('spdNm') or '').lower()]
        if len(rows) < 100:
            complete = True          # 마지막 페이지까지 봤다
            break
        if hits:
            complete = True          # 찾았다 — 더 볼 이유가 없다(답이 확정됐다)
            break
    return hits, scanned, pages, complete


def _uncertain_message(market):
    """스레드가 죽은 채 남은 마켓에 대해 **성공/실패를 단정하지 않는** 문구.

    "실패했습니다" 라고 쓰면 안 된다 — 마켓 호출이 나간 뒤 죽었을 수도 있고, 그러면
    상품은 실제로 올라가 있다(유령 상품). "성공했습니다" 는 더 위험하다. 모르는 것은
    모른다고 말하고, 사람이 확인할 곳(마켓)을 알려주는 것이 유일하게 정직한 답이다.
    """
    return (f'{MARKET_LABEL.get(market, market)} 처리 중 연결이 끊겼습니다 — '
            '올라갔는지 모릅니다. 마켓에서 상품이 생겼는지 직접 확인해 주세요.')


def _claim_register_run(session, draft_id, markets):
    """실행 상태 행을 원자적으로 클레임한다 → 새 job_id, 실패하면 None(=409).

    ★★★ [2026-07-23 3차리뷰 — 구조] **죽은 실행을 회수하면, 그 사실을 이 함수가 직접
      장부에 남긴다**(같은 트랜잭션 흐름 안에서). 「죽은 실행을 회수했다」를 아는 지점은
      여기 하나뿐이라, 여기서 남겨야 호출자가 무엇을 하든 규약이 지켜진다.
      예전에는 호출자에게 `taken` 으로 알려 주고 처리를 맡겼는데, 그러면 호출자가 하나
      늘 때마다 구멍이 하나 는다 — 실제로 그렇게 뚫렸다:
        · 단수 등록 라우트는 `taken` 을 안 넘겨 회수 마켓을 그대로 다시 불렀다(치명①)
        · 회수한 마켓이 이번 등록 목록 밖이면 「확인 필요」가 DB 에서 증발했다(치명②)
      이제 회수 즉시 장부에 `uncertain` 이 남으므로 **점검·단수·복수·크롤 재적재가
      전부 같은 근거로 잠긴다**(판정기는 `_ledger_guard` 하나).

    이미 `running=True` 이고 진행률이 `REGISTER_STALE_AFTER` 안에 움직였으면 진짜 진행
    중이라 클레임 실패다. 그보다 오래 멈춰 있으면 죽은 실행으로 보고 회수한다 — 단
    **회수는 이 함수를 부르는 새 POST 가 있을 때만** 일어난다. 서버가 알아서 재시도하면
    그게 곧 중복 등록(같은 상품 2개)이다. 사장님이 마켓에서 확인한 뒤 다시 누르는
    흐름만 허용한다(자동 재시도 금지).

    ★ [I4 2026-07-23 리뷰] 잠금을 **엔진에 맡기지 않는다.** 예전에는 `with_for_update()`
      로 행을 잠갔는데, SQLite 는 그 구문을 조용히 무시한다 — 이 저장소는 SQLite 폴백
      이력이 실제로 있어서, 폴백으로 떨어지면 가드가 통째로 사라진다.
      대신 **단일 조건부 UPDATE + rowcount** 로 판정한다:
        UPDATE … WHERE draft_id=:d AND (running=0 OR 진행률이 cutoff 보다 오래됨)
      한 문장 안에서 조건 검사와 쓰기가 끝나므로 Postgres·SQLite 양쪽에서 원자적이다
      (읽고-비교하고-쓰기 사이에 남는 창이 없다).
    """
    from lemouton.registration.models import ProductDraftRegisterRun as R
    now = datetime.datetime.utcnow()
    cutoff = now - REGISTER_STALE_AFTER
    job_id = uuid.uuid4().hex
    fields = {
        'job_id': job_id, 'running': True,
        'started_at': now, 'progress_at': now, 'finished_at': None,
        'error': None, 'current_market': None, 'current_account_key': None,
        'markets_json': json.dumps(markets),
        'done_count': 0, 'total_count': len(markets),
        # 지난 실행의 결과행은 비운다 — 남겨 두면 이번 실행의 진행 상황과 섞여, 아직
        # 부르지도 않은 마켓이 「등록됨」으로 보인다(마켓별 이력·원문은 장부에 남아 있다).
        'result_json': None,
    }
    #: 회수해도 되는 조건 — ①안 돌고 있거나 ②진행률이 cutoff 보다 오래 멈췄거나
    #: ③시각이 아예 없는 망가진 행(그대로 두면 영영 아무도 못 쓴다).
    stale = or_(
        R.running.is_(False),
        R.running.is_(None),
        func.coalesce(R.progress_at, R.started_at) < cutoff,
        and_(R.progress_at.is_(None), R.started_at.is_(None)),
    )

    # [I-E] 덮어쓰기 **전에** 「죽은 실행이 어느 마켓을, 어느 계정으로 처리 중이었나」를
    #   읽어 둔다. 이 읽기는 잠금이 아니라 참고다 — 아래 조건부 UPDATE 가 성공했다는 건
    #   그 사이 아무도 이 행을 가져가지 않았다는 뜻이라(가져갔으면 fresh 가 되어 0행).
    prior = session.query(R).filter(R.draft_id == draft_id).first()
    # [4차리뷰 중요①] 「죽었나」는 _is_dead_run 하나로 — running=False + error 로 끝난
    #   실행(예외 핸들러가 current_market 을 일부러 남긴 그 상태)도 여기 걸린다.
    prior_dead = _is_dead_run(prior)
    prior_market = (prior.current_market or None) if prior is not None else None
    prior_acct = (getattr(prior, 'current_account_key', None) or None) if prior is not None else None
    prior_job = (prior.job_id or None) if prior is not None else None
    prior_done = _run_done_markets(prior)

    try:
        n = (session.query(R)
             .filter(R.draft_id == draft_id)
             .filter(stale)
             .update(fields, synchronize_session=False))
        session.commit()
    except Exception:           # noqa: BLE001 — 클레임 실패는 「모른다」다. 시작하지 않는다.
        session.rollback()
        raise
    if n:
        # ★★★ 회수했다면 **여기서** 장부에 남긴다. 죽은 실행이 처리 중이던 마켓은
        #   옛 스레드가 아직 그 호출 안에 있을 수 있어 「올라갔는지 모르는」 상태다.
        #   이 한 줄이 치명①(단수 라우트)·치명②(목록 밖 마켓)·중요④(점검과 결과표가
        #   다른 말)를 **한꺼번에** 막는다 — 호출자가 무엇을 하든 장부가 잠근다.
        if prior_dead and prior_market and prior_market not in prior_done:
            try:
                _uncertain_ledger_row(
                    session, draft_id, prior_market,
                    account_key=(prior_acct or ACCOUNT_DEFAULT),
                    reason=_uncertain_message(prior_market) + _where_to_check(prior_market))
                logger.warning('죽은 등록 실행을 회수했다 — %s 를 「확인 필요」로 장부에 '
                               '남긴다 draft_id=%s 옛job=%s 계정=%s',
                               prior_market, draft_id, prior_job, prior_acct)
            except Exception:   # noqa: BLE001 — 장부 기록 실패가 새 실행을 막지는 않는다.
                logger.exception('회수 마켓 「확인 필요」 장부 기록 실패 draft_id=%s '
                                 'market=%s — 그 마켓은 잠기지 않는다', draft_id, prior_market)
        return job_id

    # 0행 = ①행이 아직 없다 ②진짜 진행 중이다. INSERT 를 시도해 둘을 가른다
    # (draft_id 가 PK 라 ②면 IntegrityError 로 튕긴다 — 동시 POST 레이스도 같은 경로).
    try:
        session.add(R(draft_id=draft_id, **fields))
        session.commit()
        return job_id
    except IntegrityError:
        session.rollback()
        return None


def _register_run_write(draft_id, job_id, **fields):
    """실행 상태 행 갱신 — **job_id 가 같을 때만** 쓴다.

    Returns:
        True  — 내 실행의 행에 썼다.
        False — **내 실행이 아니다**(스테일 회수로 job_id 가 바뀌었거나 행이 사라졌다).
                호출자는 이걸 **중단 신호**로 다뤄야 한다 — 쓰기만 막고 마켓 호출을
                계속하면 두 스레드가 같은 드래프트를 같은 마켓에 동시에 올린다.
        None  — 기록에 실패해 **소유권을 확인하지 못했다**(DB 오류). 등록은 계속한다.

    스테일 회수로 새 실행이 시작된 뒤에 옛 좀비 스레드가 뒤늦게 깨어나 상태를 덮으면,
    새 실행의 진행 상황이 옛 결과로 되감긴다(사장님은 그걸 보고 또 누른다 = 중복 등록).

    ★ [I4] 읽고-비교하고-쓰기(TOCTOU)가 아니라 **조건부 UPDATE + rowcount** 다 —
      `UPDATE … WHERE draft_id=:d AND job_id=:j`. 예전 구현은 조회 뒤 job_id 를 파이썬에서
      비교하고 별도 UPDATE 를 날려, 그 사이에 회수된 행을 좀비가 덮어쓸 창이 남았다.
    """
    from lemouton.registration.models import ProductDraftRegisterRun as R
    s = SessionLocal()
    try:
        payload = dict(fields)
        payload['progress_at'] = datetime.datetime.utcnow()
        n = (s.query(R)
             .filter(R.draft_id == draft_id, R.job_id == job_id)
             .update(payload, synchronize_session=False))
        s.commit()
        return bool(n)
    except Exception as e:      # noqa: BLE001 — 상태 기록 실패가 등록을 죽이면 안 된다.
        s.rollback()
        logger.warning('등록 실행상태 기록 실패 draft_id=%s job=%s — %r', draft_id, job_id, e)
        # ★ False(=중단) 로 돌리면 안 된다 — 기록이 안 된 것과 남의 실행인 것은 다른
        #   사실이다. 모르는 것은 None 으로 말하고, 등록은 계속한다.
        return None
    finally:
        s.close()


#: 「부르기 전에 기록한다」를 연속으로 이만큼 못 하면 멈춘다 — 단서를 못 남기는 채로
#: 마켓을 계속 부르면, 거기서 죽었을 때 유령이 생긴 마켓을 아무도 못 찾는다(리뷰 I-D).
REGISTER_WRITE_BLIND_LIMIT = 3


def _write_current_market(draft_id, job_id, market, account_key=None):
    """부르기 **전에** current_market(+계정)을 기록한다 — 실패하면 한 번 더 시도.

    반환은 `_register_run_write` 규약 그대로(True/False/None). 재시도를 두는 이유:
    이 한 줄이 「이 마켓을 시작했다」는 유일한 단서이고, 그게 없으면 그 마켓에서 죽었을 때
    유령 상품을 찾을 실마리가 통째로 사라진다(리뷰 I-D).

    계정까지 남기는 이유: 장부 키가 (드래프트×마켓×**계정**) 이라, 회수할 때 계정을
    모르면 「확인 필요」를 엉뚱한 계정 행에 남겨 정작 그 계정 재등록이 안 잠긴다(3차리뷰).
    """
    r = _register_run_write(draft_id, job_id, current_market=market,
                            current_account_key=account_key)
    if r is None:
        r = _register_run_write(draft_id, job_id, current_market=market,
                                current_account_key=account_key)
    return r


def _uncertain_ledger_row(session, draft_id, market, *, account_key, reason):
    """「올라갔는지 모른다」를 장부에 남긴다 — 다음 「점검」에서도 잠기도록.

    이미 성공(ok)으로 적힌 행은 건드리지 않는다 — 확정된 사실을 모른다로 되돌리면
    그게 후퇴다. 결과표는 닫히면 사라지지만 장부는 남는다(리뷰 C-2·I-E).

    ★ 계정 키는 **해석된 물리 계정**으로 맞춘다 — 빈칸('default')으로 남기면 그 계정
      이름으로 다시 올릴 때 안 잠긴다(C-1 별칭 구멍과 같은 함정).
    """
    account_key = _account_aliases(session, market, account_key)[0]
    row = _ledger_row(session, draft_id, market, account_key)
    if row.status == 'ok':
        return
    row.status = LEDGER_UNCERTAIN
    row.error_code = 'UNKNOWN'
    row.error_message = reason
    session.commit()


def _register_job(draft_id, job_id, ordered, *, codes, keys, vendor_in, reregister=None):
    """백그라운드 스레드 본체 — 마켓을 **순차로** 돌며 한 마켓이 끝날 때마다 상태에 커밋.

    쓰기 순서가 이 함수의 핵심이다:
      ① 마켓을 부르기 **전에** `current_market` 을 기록한다(=마지막으로 시작한 마켓).
      ② 마켓이 끝나면 결과행을 `result_json` 에 붙이고 `done_count` 를 올린다.
    이 순서라야 스레드가 마켓 처리 도중 죽었을 때, 남은 행이 「○○ 를 시작했는데 끝난
    기록이 없다」를 말해 준다 — 폴링은 그것을 성공도 실패도 아닌 **불확실**로 보고한다.
    반대 순서(끝나고 나서 기록)였다면 죽은 마켓이 아예 흔적을 안 남겨, 안 올라간 것처럼
    보인다(그게 유령 상품을 못 찾게 만드는 거짓 안심이다).

    ★★ [C2 2026-07-23 리뷰] 상태 쓰기가 `False` 를 돌려주면 **그 자리에서 멈춘다**.
      False 는 「스테일 회수로 이 실행의 주인이 바뀌었다」는 뜻이다. 예전에는 그 반환값을
      전부 무시해서, 회수된 옛 스레드가 쓰기만 막힌 채 남은 마켓을 계속 불렀다 —
      새 스레드와 옛 스레드가 같은 드래프트를 같은 마켓에 동시에 올린다(같은 상품 2개).
      매 반복 맨 위의 `current_market` 쓰기가 소유권 재확인 지점이라, 중단은 언제나
      **다음 마켓을 부르기 전에** 일어난다.

    ★ [재리뷰 I-D] 기록 실패(None)는 중단이 아니다 — 소유권을 확인하지 못한 것뿐이라
      등록은 계속한다(멀쩡한 등록을 죽이는 쪽이 더 비싸다). 다만 그대로 두면 「부르기
      전에 기록한다」는 전제가 조용히 깨진다: 기록이 안 된 채 그 마켓에서 죽으면
      current_market 은 **이전 마켓**을 가리키고, 진짜 유령이 생긴 마켓은 pending
      (=「부른 적 없다」가 확실한 칸)으로 보고된다. 그래서 ①한 번 재시도하고
      ②연속 실패가 REGISTER_WRITE_BLIND_LIMIT 에 닿으면 멈춘다.

    ★ [3차리뷰 — 구조] 회수한 죽은 실행이 처리 중이던 마켓을 **여기서 따로 걸러내지
      않는다.** `_claim_register_run` 이 회수하는 순간 장부에 'uncertain' 을 남기므로,
      사전점검(`_ledger_guard`)이 그 마켓을 알아서 잠근다. 특례 분기를 두면 호출자가
      하나 늘 때마다 구멍이 하나 는다(그렇게 두 번 뚫렸다).

    마켓별 장부(`ProductDraftMarket`) 커밋은 `_register_one` 안에 이미 있다 — 그대로 둔다.
    이 실행 상태 행이 죽어도 장부는 남는다(이중 안전장치).
    """
    redo = {str(m) for m in (reregister or []) if m}
    blind = 0                      # 연속 「기록 실패(모름)」 횟수
    s = SessionLocal()
    try:
        draft = (s.query(ProductDraft)
                 .filter(ProductDraft.id == draft_id,
                         ProductDraft.deleted_at.is_(None)).first())
        if draft is None:
            _register_run_write(draft_id, job_id, running=False,
                                finished_at=datetime.datetime.utcnow(),
                                error='드래프트를 찾을 수 없습니다.')
            return

        # ① 사전점검 먼저 — 등록 라우트와 **같은 판정기**. 여기서 ready 가 아니면 호출 없음.
        pre = {r['market']: r for r in preflight_rows(
            s, draft, ordered, codes=codes, keys=keys, vendor=vendor_in,
            reregister=redo)}

        rows = []
        for market in ordered:                     # ② 순차 — 마켓 간 병렬 금지
            # ★ 부르기 전에 기록한다 — 여기서 죽으면 이 마켓이 '불확실' 로 남는다.
            # ★★ False = 내 실행이 아니다 → 마켓을 부르기 전에 멈춘다(C2).
            pr = pre[market]
            wrote = _write_current_market(draft_id, job_id, market,
                                          account_key=pr['account_key'])
            if wrote is False:
                logger.warning('등록 실행이 회수됐다 — 옛 스레드를 중단한다 '
                               'draft_id=%s job=%s (남은 마켓 없이 종료)', draft_id, job_id)
                return
            if wrote is None:
                # 재시도까지 실패 = 이 마켓을 「시작했다」는 단서를 못 남겼다.
                blind += 1
                if blind >= REGISTER_WRITE_BLIND_LIMIT:
                    logger.error('등록 진행상태를 %d번 연속 기록하지 못했다 — 단서 없이 '
                                 '마켓을 더 부르지 않는다 draft_id=%s job=%s',
                                 blind, draft_id, job_id)
                    return
            else:
                blind = 0

            if pr['status'] != 'ready':
                # 브랜드·지재권으로 막힌 것은 **장부에도** 남긴다(단수 라우트와 같은 규약).
                # 보충 필요(missing·need_category)는 아직 아무것도 시도하지 않은 상태라
                # 장부를 더럽히지 않는다 — 시도하지 않은 일을 기록으로 남기면 안 된다.
                if pr['status'] in ('blocked', 'need_brand'):
                    _brand_block_row(s, draft_id, market,
                                     category_code=pr['category_code'],
                                     account_key=pr['account_key'],
                                     reason=pr['reason'],
                                     error_code=_SKIP_ERROR_CODE[pr['status']])
                rows.append({
                    'market': market,
                    'status': _SKIP_STATUS.get(pr['status'], 'skipped'),
                    'preflight_status': pr['status'],
                    'account_key': pr['account_key'],
                    'category_code': pr['category_code'],
                    'category_source': pr['category_source'],
                    # 이미 등록된 마켓은 그 상품번호를 그대로 실어 보낸다 — 「왜 안 불렀나」의
                    # 답이 곧 그 번호다(화면이 마켓에서 바로 확인할 수 있게).
                    'market_product_id': pr.get('market_product_id'),
                    'error_code': _SKIP_ERROR_CODE.get(pr['status'], 'PREFLIGHT'),
                    'error': None,
                    'reason': pr['reason'],
                    'raw': None, 'excluded': [],
                    # [사소②] 부르지도 않은 마켓에 「등록할 때 …」 주의를 붙이지 않는다.
                    #   불확실은 대신 **확인하라는 말**을 붙인다(그게 필요한 행동이다).
                    'notes': ([UNCERTAIN_NOTE] if pr['status'] == 'uncertain'
                              else ([] if pr['status'] in _SKIP_NO_CAVEATS
                                    else list(pr['caveats'] or []))),
                    'lookup_supported': (market in LOOKUP_MARKETS
                                         if pr['status'] == 'uncertain' else False),
                    # [4차리뷰 사소⑤·치명①] 확정 UI 는 조회 지원과 무관하게 켠다.
                    'confirm_supported': pr['status'] == 'uncertain',
                })
            else:
                # 쿠팡 vendor 는 요청이 안 보내면 계정 저장값으로 채운다(우리 DB 조회뿐).
                vendor = _vendor_for(s, market, {'vendor': vendor_in,
                                                 'account_key': pr['account_key']})
                row = _register_one(s, draft_id, market,
                                    category_code=pr['category_code'],
                                    account_key=pr['account_key'],
                                    vendor=vendor,
                                    allow_reregister=(market in redo))  # ③ 실패해도 계속
                row['preflight_status'] = 'ready'
                row['category_source'] = pr['category_source']
                # 성공이면 「등록 뒤에 알아야 할 것」, 불확실이면 **확인하라는 말이 먼저**,
                # 그 외에는 점검이 알려준 주의를 그대로.
                if row['status'] == 'ok':
                    row['notes'] = list(POST_REGISTER_NOTES.get(market) or [])
                elif row['status'] == 'unknown':
                    row['notes'] = [UNCERTAIN_NOTE] + list(pr['caveats'] or [])
                else:
                    row['notes'] = list(pr['caveats'] or [])
                rows.append(row)
            # 마켓 하나가 끝날 때마다 커밋 — 폴링이 「그때까지 분량」을 바로 본다.
            # False = 회수됐다 → 여기서도 멈춘다(다음 마켓을 부르지 않는다).
            if _register_run_write(draft_id, job_id, result_json=json.dumps(rows),
                                   done_count=len(rows)) is False:
                logger.warning('등록 실행이 회수됐다 — 옛 스레드를 중단한다 '
                               'draft_id=%s job=%s market=%s', draft_id, job_id, market)
                return

        _register_run_write(draft_id, job_id, running=False,
                            finished_at=datetime.datetime.utcnow(),
                            current_market=None,
                            result_json=json.dumps(rows), done_count=len(rows))
    except Exception as e:      # noqa: BLE001 — 예상 밖 예외도 삼키지 않고 상태에 원문을 남긴다.
        logger.exception('복수 등록 백그라운드 실패 draft_id=%s job=%s', draft_id, job_id)
        # ★ running=False 로 내리되 current_market 은 **지우지 않는다** — 어느 마켓에서
        #   끊겼는지가 유령 상품을 찾는 유일한 단서다.
        _register_run_write(draft_id, job_id, running=False,
                            finished_at=datetime.datetime.utcnow(),
                            error=f'등록 중 예상 밖 오류 — {e!r}'[:500])
    finally:
        s.close()


def _register_run_payload(row):
    """실행 상태 행 → 폴링 응답 dict. **불확실 판정이 여기서 일어난다.**

    반환 rows 는 「그때까지 확정된 결과행」 + (불확실하면) 그 마켓 1행이다. 불확실 행은
    DB 에 저장하지 않고 읽을 때 만든다 — 저장하면 나중에 사실이 밝혀져도 그 거짓이
    남는다(장부의 진실은 ProductDraftMarket 이다).
    """
    rows = json.loads(row.result_json) if row.result_json else []
    markets = json.loads(row.markets_json) if row.markets_json else []
    running = bool(row.running)
    # 진행률이 멈춘 채 running=True → 스레드가 죽었다고 **의심**한다(단정 아님).
    stale = bool(running and _is_dead_run(row))
    done = {r.get('market') for r in rows}

    uncertain = None
    # 시작은 했는데 끝난 기록이 없는 마켓 = 올라갔는지 모르는 마켓.
    # (running 이 이미 내려간 경우 = 예상 밖 예외로 끝난 실행. 그때도 current_market 이
    #  남아 있고 그 마켓 결과행이 없으면 똑같이 불확실이다 — error 만 보고 「실패」로
    #  단정하면 마켓 호출 뒤에 죽은 경우를 놓친다.)
    # [4차리뷰 중요①] 죽음 판정은 _is_dead_run 하나 — 잠금·장부기록과 같은 정의.
    dead = _is_dead_run(row)
    if dead and row.current_market and row.current_market not in done:
        m = row.current_market
        uncertain = {
            'market': m,
            'message': _uncertain_message(m),
            'lookup_supported': m in LOOKUP_MARKETS,
        }
        rows = rows + [{
            'market': m, 'status': 'unknown', 'preflight_status': None,
            'account_key': None, 'category_code': None, 'category_source': None,
            'market_product_id': None, 'error_code': 'UNKNOWN',
            'error': None, 'reason': uncertain['message'],
            'raw': None, 'excluded': [],
            'notes': [UNCERTAIN_NOTE],
            'lookup_supported': uncertain['lookup_supported'],
            # [4차리뷰 치명①] 확정은 6마켓 전부 — 조회 지원 여부와 무관하다.
            #   (화면은 이 칸 하나만 보고 확정 UI 를 그린다 — 판정 조건이 둘이면 갈린다.)
            'confirm_supported': True,
        }]
        done.add(m)

    # already = 이미 등록돼 있어 **부르지 않은** 마켓. 실패도 건너뜀도 아니다.
    summary = {'ok': 0, 'failed': 0, 'blocked': 0, 'skipped': 0, 'unknown': 0,
               'already': 0, 'uncertain': 0}
    for r in rows:
        if r.get('status') in summary:
            summary[r['status']] += 1
    return {
        'ok': True,
        'job_id': row.job_id,
        'running': running,
        'stale': stale,
        'markets': markets,
        # 아직 손대지 않은 마켓 — 「안 올라갔다」가 확실한 유일한 칸이다(부른 적이 없다).
        'pending': [m for m in markets if m not in done],
        'current_market': row.current_market,
        'done': int(row.done_count or 0),
        'total': int(row.total_count or len(markets)),
        'started_at': (row.started_at.isoformat(sep=' ') if row.started_at else None),
        'finished_at': (row.finished_at.isoformat(sep=' ') if row.finished_at else None),
        'progress_at': (row.progress_at.isoformat(sep=' ') if row.progress_at else None),
        'error': row.error,
        'uncertain': uncertain,
        'rows': rows,
        'summary': summary,
    }


@bp.post('/api/drafts/<int:draft_id>/register')
def register_many(draft_id: int):
    """여러 마켓에 한 번에 등록 — **시작만** 확인해 준다(결과는 안 실린다).

    body:
      markets        : ['smartstore', ...]   (필수, 비어 있으면 400)
      category_codes : {market: code}        confirmed 맵핑이 있으면 그쪽이 이긴다
      account_keys   : {market: key}         생략하면 'default'
      vendor         : {...}                 쿠팡 계정정보(안 보내면 계정 저장값)
      reregister     : ['smartstore', ...]   「다시 올리기」 opt-in (기본 없음)

    ★ 이미 등록된 마켓(장부에 status='ok' + 상품번호)은 `reregister` 에 없으면 **마켓을
      부르지 않는다** — 결과는 status='already' 로 그 상품번호와 함께 돌아온다.

    응답 계약 (화면 JS 가 그대로 분기한다):
      - markets 가 비었거나 모르는 마켓 → 400 {'ok': False, 'error': …}
      - 없는 드래프트                   → 404
      - 이미 이 드래프트가 등록 중      → 409 {'ok': False, 'error': …, 'job_id': 진행중 job}
      - 시작 성공                       → 202 {'ok': True, 'started': True, 'job_id': …}

    결과(마켓별 성공·실패·원문)는 이 응답에 **없다** — GET …/register/status 로 폴링한다.
    (구 버전은 200 으로 6마켓 결과를 한 번에 돌려줬다. gunicorn `--timeout 60` sync 워커라
     그 사이 워커가 죽으면 요청도 응답도 증발하고, 이미 마켓에 만들어진 상품은 회수되지
     못한 채 남는다 — 과거이력의 유령 상품 사고가 정확히 그 조건이라 이 계약으로 바꿨다.)
    """
    p = request.get_json(silent=True) or {}

    markets = p.get('markets')
    if not isinstance(markets, list) or not markets:
        return _err('markets 는 비어 있지 않은 배열이어야 합니다 — 올릴 마켓을 골라 주세요.')
    unknown = [m for m in markets if m not in MARKETS]
    if unknown:
        return _err(f'모르는 마켓입니다: {unknown} — {list(MARKETS)} 중에서 골라 주세요.')
    # 같은 마켓이 두 번 들어와도 한 번만 부른다 — 중복 호출은 유령 상품(같은 상품 2개)이다.
    ordered = []
    for m in markets:
        if m not in ordered:
            ordered.append(m)

    vendor_in = p.get('vendor') if isinstance(p.get('vendor'), dict) else {}
    codes = p.get('category_codes')
    keys = p.get('account_keys')
    # 「다시 올리기」 — 요청한 마켓 중에서만 인정한다(안 고른 마켓이 opt-in 되면 안 된다).
    redo_in = p.get('reregister')
    if isinstance(redo_in, dict):
        redo_in = [m for m, v in redo_in.items() if v]
    reregister = [m for m in (redo_in or []) if m in ordered]

    s = SessionLocal()
    try:
        draft = (s.query(ProductDraft)
                 .filter(ProductDraft.id == draft_id,
                         ProductDraft.deleted_at.is_(None)).first())
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)
        # 회수(스테일)가 일어나면 _claim_register_run 이 **그 안에서** 장부에
        # 「확인 필요」를 남긴다 — 여기서 따로 처리할 것이 없다(3차리뷰 구조 수정).
        job_id = _claim_register_run(s, draft_id, ordered)
    finally:
        s.close()

    if job_id is None:
        from lemouton.registration.models import ProductDraftRegisterRun
        s2 = SessionLocal()
        try:
            cur = (s2.query(ProductDraftRegisterRun)
                   .filter_by(draft_id=draft_id).first())
            running_job = cur.job_id if cur else None
        finally:
            s2.close()
        return jsonify({'ok': False, 'job_id': running_job,
                        'error': '이 상품은 이미 등록이 진행 중입니다 — 끝날 때까지 '
                                 '기다려 주세요(다시 누르면 같은 상품이 두 번 올라갑니다).'}), 409

    t = threading.Thread(target=_register_job, args=(draft_id, job_id, ordered),
                         kwargs={'codes': codes, 'keys': keys, 'vendor_in': vendor_in,
                                 'reregister': reregister},
                         daemon=True)
    t.start()
    return jsonify({'ok': True, 'started': True, 'job_id': job_id,
                    'markets': ordered}), 202


@bp.get('/api/drafts/<int:draft_id>/register/status')
@bp.get('/api/drafts/register/status')
def register_status(draft_id: int = None):
    """복수 등록 진행 상황 — 그때까지 확정된 결과행을 그대로 준다.

    `/bulk/api/drafts/<id>/register/status` 와 `/bulk/api/drafts/register/status?draft_id=<id>`
    둘 다 받는다(호출부가 어느 쪽을 쓰든 같은 답).

    응답:
      {ok, job_id, running, stale, current_market, done, total, markets, pending,
       rows: […그때까지 확정된 행…], summary, uncertain, error, started_at/finished_at/progress_at}

    ★ `uncertain` 이 채워져 오면 그 마켓은 **성공도 실패도 아니다** — 등록 스레드가 그
      마켓을 부르던 중 죽었다는 뜻이고, 마켓에 상품이 생겼을 수도 있다. 화면은 그 문구를
      그대로 보여줘야 한다(요약·완곡화 금지).
    """
    from lemouton.registration.models import ProductDraftRegisterRun
    if draft_id is None:
        raw = (request.args.get('draft_id') or '').strip()
        if not raw.isdigit():
            return _err('draft_id 가 필요합니다.')
        draft_id = int(raw)
    s = SessionLocal()
    try:
        row = (s.query(ProductDraftRegisterRun)
               .filter_by(draft_id=draft_id).first())
        if row is None:
            # 한 번도 등록을 시작한 적이 없다 — 「없음」이지 「실패」가 아니다.
            return jsonify({'ok': True, 'job_id': None, 'running': False, 'stale': False,
                            'markets': [], 'pending': [], 'current_market': None,
                            'done': 0, 'total': 0, 'started_at': None, 'finished_at': None,
                            'progress_at': None, 'error': None, 'uncertain': None,
                            'rows': [], 'summary': {'ok': 0, 'failed': 0, 'blocked': 0,
                                                    'skipped': 0, 'unknown': 0,
                                                    'already': 0, 'uncertain': 0}})
        return jsonify(_register_run_payload(row))
    finally:
        s.close()


@bp.post('/api/drafts/<int:draft_id>/market-confirm')
def market_confirm(draft_id: int):
    """사람이 마켓에서 **확인한 결과**를 장부에 넣는다 — 「확인 필요」의 정직한 결말.

    ★★★ [2026-07-23 3차리뷰 중요③] 이 라우트가 없으면 `uncertain` 은 **영구 교착**이다:
      확인해 보니 상품이 **있더라** 라는 결과를 기록할 방법이 없어 행은 영원히 확인 필요로
      남고(칩도 ⚠ 고정), Phase 2 가격·재고 자동갱신 대상에서도 빠진다. 그러면 사장님에게
      남는 유일한 행동이 「다시 올리기 = 중복 감수」뿐이다 — 정직한 결말이 표현 불가능한
      상태 기계는 만들면 안 된다.

    body:
      market            : 마켓 id (필수 — **6마켓 전부** 받는다)
      market_product_id : 마켓에서 확인한 상품번호 (필수 — 이게 곧 성공의 증거다)
      account_key       : 생략하면 'default'(해석된 물리 계정으로 정규화)

    ★ 상품번호 없이는 확정하지 않는다. 이 저장소의 성공 판정은 언제나 「마켓이 준
      상품번호를 받았는가」 하나뿐이다(service.py 와 같은 규약).

    ★★ [4차리뷰 중요③] **조회 API 가 있는 마켓(11번가·롯데온)은 서버가 한 번 대조한다.**
      틀린 번호를 확정하면 그 뒤 가격·재고 자동갱신이 **남의 상품으로 나간다**(금전 사고).
      나머지 4마켓은 이름으로 찾는 조회 API 자체가 없어(LOOKUP_MARKETS 주석의 전수 근거)
      사람이 셀러센터에서 본 번호를 믿는 수밖에 없다 — 대신 그 사실을 응답에 적는다.

    ★★ [4차리뷰 중요④] 등록 실행 잠금에 **참여한다**. 그 드래프트가 등록 중이면 409 —
      잡이 그 마켓을 처리하는 중에 확정이 끼어들어 status='ok' 를 써 버리면, 뒤이어
      끝난 등록 결과와 장부가 어긋난다.
    """
    p = request.get_json(silent=True) or {}
    market = (p.get('market') or '').strip()
    pid = str(p.get('market_product_id') or '').strip()
    if market not in MARKETS:
        return _err(f'market 은 {list(MARKETS)} 중 하나여야 합니다.')
    if not pid:
        return _err('마켓에서 확인한 상품번호가 필요합니다 — 번호 없이는 「등록됨」으로 '
                    '바꾸지 않습니다(번호가 곧 그 상품이 있다는 증거입니다).')

    s = SessionLocal()
    job_id = None
    try:
        draft = (s.query(ProductDraft)
                 .filter(ProductDraft.id == draft_id,
                         ProductDraft.deleted_at.is_(None)).first())
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)

        # [중요④] 등록이 도는 중이면 확정하지 않는다 — 같은 행을 두 주인이 쓴다.
        job_id = _claim_register_run(s, draft_id, [market])
        if job_id is None:
            return jsonify({'ok': False,
                            'error': '이 상품은 지금 등록이 진행 중입니다 — 끝난 뒤에 '
                                     '확정해 주세요(지금 확정하면 등록 결과와 '
                                     '기록이 어긋납니다).'}), 409

        # [중요③] 조회 API 가 있는 마켓은 그 번호가 정말 있는지 서버가 대조한다.
        verified = None
        if market in LOOKUP_MARKETS:
            ok_or_err = _verify_market_product_id(s, draft, market, pid)
            if ok_or_err is not True:
                return ok_or_err            # 400(그 번호 없음) 또는 502(조회 불가)
            verified = True

        account_key = _account_aliases(s, market, p.get('account_key'))[0]
        row = _ledger_row(s, draft_id, market, account_key)
        prev = (row.market_product_id or '').strip()
        # 이전 번호가 다르면 원문에 남긴다 — 둘 다 살아 있을 수 있다(되돌릴 근거).
        if prev and prev != pid:
            try:
                row.raw_json = json.dumps(
                    {'previous_market_product_id': prev,
                     'confirmed_by': 'market-confirm'}, ensure_ascii=False)[:20000]
            except Exception:      # noqa: BLE001
                pass
        row.status = 'ok'
        row.market_product_id = pid
        row.error_code = None
        row.error_message = None
        if row.registered_at is None:
            row.registered_at = datetime.datetime.now(datetime.timezone.utc)
        s.commit()
        note = ('마켓에서 확인한 상품번호로 확정했습니다 — 이제 이 마켓은 '
                '「이미 등록됨」으로 잠깁니다(가격·재고 갱신 대상에 들어옵니다).')
        if verified:
            note += ' 이 번호는 마켓 조회로 대조까지 마쳤습니다.'
        else:
            note += (f' {MARKET_LABEL.get(market, market)} 는 상품명으로 찾는 조회 API 가 '
                     f'없어 대조 없이 입력하신 번호를 그대로 믿었습니다 — 번호가 맞는지 '
                     f'다시 한 번 확인해 주세요(틀리면 가격·재고가 남의 상품으로 나갑니다).')
        return jsonify({'ok': True, 'market': market, 'account_key': account_key,
                        'market_product_id': pid, 'verified': bool(verified),
                        'note': note})
    finally:
        # 잠금은 반드시 돌려준다(확정은 마켓에 아무것도 만들지 않는다 — 결과행도 없다).
        if job_id is not None:
            _register_run_write(draft_id, job_id, running=False,
                                finished_at=datetime.datetime.utcnow(),
                                current_market=None)
        s.close()


def _verify_market_product_id(session, draft, market, pid):
    """그 상품번호가 **정말 그 마켓에 있는지** 조회로 대조 → True, 아니면 오류 응답.

    [4차리뷰 중요③] 조회 API 가 이미 있는 2마켓(11번가·롯데온)만 대조한다. 추가 API 없이
    `market-lookup` 과 **같은 조회**를 쓴다. 틀린 번호를 확정하면 그 뒤 가격·재고 갱신이
    남의 상품으로 나가므로, 공짜로 막을 수 있는 자리는 막는다.

    ★ 조회 자체가 실패하면 **확정하지 않는다**(502). 「확인 못 했는데 확정」은 이 저장소가
      금지하는 폴백이다 — 잠시 뒤 다시 누르면 된다.
    """
    from lemouton.uploader import market_fetch as MF
    name = (draft.name or '').strip()
    env_prefix = _first_upload_env_prefix(session, market)
    if not name or env_prefix is None:
        return jsonify({'ok': False,
                        'error': f'{MARKET_LABEL.get(market, market)}: 대조에 필요한 '
                                 f'상품명·계정이 없어 확정하지 않았습니다.'}), 502
    try:
        if market == 'eleven11':
            from shared.platforms.eleven11.products import search_products
            found = search_products(client=MF._eleven11_client(env_prefix),
                                    name=name, limit=ELEVEN11_LOOKUP_LIMIT)
            codes = {str(r.get('prdNo') or '') for r in found if isinstance(r, dict)}
        else:   # lotteon
            hits, _scanned, _pages, _complete = _lotteon_lookup(
                MF._lotteon_client(env_prefix), name)
            codes = {h['code'] for h in hits}
    except Exception as e:      # noqa: BLE001 — 조회 실패는 「모른다」다. 확정하지 않는다.
        return jsonify({'ok': False,
                        'error': f'{MARKET_LABEL.get(market, market)} 조회에 실패해 '
                                 f'확정하지 않았습니다 — 잠시 뒤 다시 시도해 주세요. {e}'}), 502
    if str(pid) not in codes:
        return jsonify({'ok': False,
                        'error': f'{MARKET_LABEL.get(market, market)}에서 상품번호 {pid} '
                                 f'(상품명 「{name}」)를 찾지 못해 확정하지 않았습니다 — '
                                 f'번호를 다시 확인해 주세요.'}), 400
    return True


@bp.get('/api/drafts/<int:draft_id>/market-lookup')
def market_lookup(draft_id: int):
    """유령 상품 확인 — 그 마켓에 이 상품명이 실제로 있는지 **조회만** 한다(쓰기 없음).

    결과가 불확실한 마켓에서 「마켓에서 확인」 버튼이 이걸 부른다. 지원 마켓은
    `LOOKUP_MARKETS` 뿐이다(상품번호 없이 이름으로 찾을 수 있는 API 가 이미 있는 마켓만 —
    근거는 그 상수 주석 참조). 지원하지 않는 마켓에 가짜 버튼을 달지 않는다.

    ★ 0건이 「안 올라갔다」의 증명은 아니다 — 마켓 색인이 늦거나 이름이 잘려 저장됐을 수
      있다. 응답의 note 로 그 한계를 같이 말한다(조용한 거짓 안심 금지).
    """
    market = (request.args.get('market') or '').strip()
    if market not in LOOKUP_MARKETS:
        return _err(f'{MARKET_LABEL.get(market, market) or market} 은(는) 상품명으로 찾는 '
                    f'조회 API 가 없어 여기서 확인할 수 없습니다 — 마켓 판매자센터에서 '
                    f'직접 확인해 주세요.')
    s = SessionLocal()
    try:
        draft = (s.query(ProductDraft)
                 .filter(ProductDraft.id == draft_id,
                         ProductDraft.deleted_at.is_(None)).first())
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)
        name = (draft.name or '').strip()
        env_prefix = _first_upload_env_prefix(s, market)
    finally:
        s.close()
    if not name:
        return _err('상품명이 없어 조회할 수 없습니다.')
    if env_prefix is None:
        return _err(f'{MARKET_LABEL.get(market, market)}: 활성 계정이 없습니다 — '
                    f'판매처 계정 관리에서 먼저 등록해 주세요.', 502)

    from lemouton.uploader import market_fetch as MF
    try:
        if market == 'eleven11':
            from shared.platforms.eleven11.products import search_products
            found = search_products(client=MF._eleven11_client(env_prefix),
                                    name=name, limit=ELEVEN11_LOOKUP_LIMIT)
            found = [r for r in found if isinstance(r, dict)]
            hits = [{'code': str(r.get('prdNo') or ''), 'name': str(r.get('prdNm') or '')[:80]}
                    for r in found]
            scanned, pages = len(found), 1
            # 마켓이 이름으로 직접 찾아준다 — 상한까지 꽉 찼으면 그 뒤는 못 본 것이다.
            complete = len(found) < ELEVEN11_LOOKUP_LIMIT
            scope = f'상품명 「{name}」 검색 결과 {scanned}건 확인'
        else:   # lotteon
            hits, scanned, pages, complete = _lotteon_lookup(
                MF._lotteon_client(env_prefix), name)
            scope = (f'최근 {LOOKUP_RECENT_DAYS}일 등록분 {scanned}행'
                     f'({pages}페이지) 확인')
    except Exception as e:      # noqa: BLE001 — 조회 실패도 원문 그대로(추측 금지)
        return jsonify({'ok': False,
                        'error': f'{MARKET_LABEL.get(market, market)} 상품 조회 실패 — {e}'}), 502

    if hits:
        note = f'찾았습니다 — 그 상품은 올라가 있습니다. ({scope})'
    elif complete:
        # ★ 「없습니다」로 끝내지 않는다 — 훑은 범위 밖일 수도, 마켓 색인이 늦을 수도 있다.
        note = (f'{scope} — 확인한 범위 안에는 없습니다. 「안 올라갔다」의 증명은 '
                f'아닙니다(마켓 색인이 늦거나 이름이 다르게 저장됐을 수 있습니다) — '
                f'판매자센터에서 한 번 더 확인해 주세요.')
    else:
        note = (f'{scope}까지만 보고 멈췄습니다(한 번에 훑는 상한) — 그 뒤는 '
                f'못 봤습니다. 확인한 범위 안에는 없다는 뜻일 뿐, 「없다」가 아닙니다 — '
                f'판매자센터에서 직접 확인해 주세요.')

    return jsonify({
        'ok': True, 'market': market, 'query': name,
        'count': len(hits), 'rows': hits[:30],
        # ★ 「무엇을 어디까지 봤는가」를 그대로 싣는다 — 이게 없으면 0건이 「없다」인지
        #   「거기까진 못 봤다」인지 화면이 구분할 수 없다(그 구분이 곧 중복 등록 방지다).
        'scanned': scanned, 'pages': pages, 'scope': scope, 'complete': bool(complete),
        'note': note,
    })


def _first_upload_env_prefix(session, market):
    """그 마켓의 활성 업로드 계정 env_prefix(첫 번째). 없으면 None(예외 대신 None — 조회
    실패를 「계정이 없다」는 사실로 정확히 말하기 위해)."""
    from lemouton.sourcing.models_v2 import UploadAccount
    acct = (session.query(UploadAccount)
            .filter_by(market=market, is_active=True)
            .order_by(UploadAccount.id).first())
    return acct.env_prefix if acct else None


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

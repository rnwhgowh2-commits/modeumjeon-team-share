# -*- coding: utf-8 -*-
"""대량등록 — 드래프트 CRUD + 등록 라우트."""
import datetime
import json
import logging
import threading
import uuid

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

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
from . import bp

logger = logging.getLogger(__name__)


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


def _brand_block_row(session, draft_id, market, *, category_code, account_key, reason):
    """브랜드·지재권 제한으로 막힌 사실을 장부(ProductDraftMarket)에 남긴다.

    막힌 것도 기록이다 — 남기지 않으면 나중에 「왜 이 마켓만 안 올라갔지?」를 알 수 없다.
    """
    row = (session.query(ProductDraftMarket)
           .filter_by(draft_id=draft_id, market=market, account_key=account_key).first())
    if row is None:
        row = ProductDraftMarket(draft_id=draft_id, market=market, account_key=account_key)
        session.add(row)
    row.status = 'blocked'
    row.error_code = 'BRAND_RESTRICTED'
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


def _register_one(session, draft_id, market, *, category_code, account_key, vendor):
    """마켓 1곳 등록 → 결과 1행. 단수·복수 라우트가 **같은 함수**를 쓴다.

    한 마켓의 실패가 예외로 새어 나가 다른 마켓을 막지 않도록 여기서 전부 행으로
    바꾼다(부분 성공 허용). status = ok / failed / blocked.
    """
    out = {'market': market, 'status': 'failed', 'account_key': account_key,
           'category_code': str(category_code) if category_code else None,
           'market_product_id': None, 'error_code': None, 'error': None,
           'reason': '', 'raw': None, 'excluded': []}

    # M2: 브랜드·지재권 제한 — 걸리면 마켓을 호출하지 않는다(선차단).
    draft = session.query(ProductDraft).filter_by(id=draft_id).first()
    reason = _brand_restriction_block(session, draft, market, category_code=category_code)
    if reason:
        _brand_block_row(session, draft_id, market, category_code=category_code,
                         account_key=account_key, reason=reason)
        out.update(status='blocked', error_code='BRAND_RESTRICTED', reason=reason)
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
    return out


@bp.post('/api/drafts/<int:draft_id>/register/<market>')
def register(draft_id: int, market: str):
    """마켓 **1곳** 등록 — 하위 호환용. 복수 등록은 POST …/register (markets 배열).

    응답 모양은 예전 그대로 둔다(register_draft 반환 + blocked 플래그) — 이 라우트를
    직접 부르는 호출자·테스트가 이미 있다. 판정은 _register_one 하나로 합쳐,
    단수·복수가 서로 다른 답을 낼 수 없게 했다.
    """
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

        vendor = _vendor_for(s, market, p)
        row = _register_one(s, draft_id, market,
                            category_code=p['category_code'],
                            account_key=(p.get('account_key') or 'default'),
                            vendor=vendor)
        if row['status'] == 'blocked':
            if row['error_code'] == 'BRAND_RESTRICTED':
                return jsonify({'ok': False, 'blocked': True, 'reason': row['reason']})
            return jsonify({'ok': False, 'blocked': True, 'error': row['error']})
        if row['error_code'] == 'BAD_REQUEST':
            return _err(row['error'], 404)
        if row['error_code'] == 'UNEXPECTED':
            return _err(row['error'], 500)
        return jsonify({'ok': row['status'] == 'ok',
                        'market_product_id': row['market_product_id'],
                        'error': row['error'],
                        'excluded': row['excluded']})
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


def _preflight_row(session, draft, market, *, category_code, account_key, vendor):
    """마켓 1곳 점검 → 결과 1행. 마켓 API 는 부르지 않는다.

    [2026-07-23 M4-2] 쿠팡 vendor 는 요청이 안 보내면 **계정 저장값**으로 채운다.
    저장값 조회는 우리 DB 뿐이라 「마켓 API 를 안 부른다」는 이 라우트의 전제는 그대로다.
    """
    row = {'market': market, 'status': 'ready', 'reason': '',
           'category_code': None, 'category_source': None,
           'account_key': account_key,
           'caveats': list(PREFLIGHT_CAVEATS.get(market) or [])}

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


def preflight_rows(session, draft, markets, *, codes=None, keys=None, vendor=None):
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

    Returns:
        [{market, status, reason, category_code, category_source, account_key,
          caveats, filled_from}]
        status = ready / missing / blocked / need_category
    """
    codes = codes if isinstance(codes, dict) else {}
    keys = keys if isinstance(keys, dict) else {}
    vendor = vendor if isinstance(vendor, dict) else {}

    # M4-3: 고시정보 기본값(전역·소싱처)을 합친 **읽기 전용 사본**으로 점검한다.
    #   저장된 드래프트는 손대지 않는다. 기본값이 채운 칸은 filled_from 으로 그대로
    #   알려 준다 — 화면이 「내가 넣은 값」과 「기본값이 채운 값」을 구분할 수 있게.
    #   병합 후에도 비는 칸은 여전히 missing 으로 뜬다(폴백 금지 — 지어내지 않는다).
    probe_draft, notice_filled_from = apply_notice_defaults(session, draft)

    rows = []
    for market in markets:
        mapped = _mapped_category(session, draft, market)
        given = str(codes.get(market) or '').strip() or None
        # 사장님이 확정한 맵핑이 최우선 — 추측이 아니라 확정값이다.
        code = mapped or given
        source = 'mapped' if mapped else ('given' if given else None)
        account_key = str(keys.get(market) or '').strip() or 'default'
        row = _preflight_row(session, probe_draft, market, category_code=code,
                             account_key=account_key, vendor=vendor)
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
                              vendor=p.get('vendor'))
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
_SKIP_STATUS = {'missing': 'skipped', 'need_category': 'skipped', 'blocked': 'blocked'}

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

    이미 `running=True` 이고 진행률이 `REGISTER_STALE_AFTER` 안에 움직였으면 진짜 진행
    중이라 클레임 실패다. 그보다 오래 멈춰 있으면 죽은 실행으로 보고 회수한다 — 단
    **회수는 이 함수를 부르는 새 POST 가 있을 때만** 일어난다. 서버가 알아서 재시도하면
    그게 곧 중복 등록(같은 상품 2개)이다. 사장님이 마켓에서 확인한 뒤 다시 누르는
    흐름만 허용한다(자동 재시도 금지).

    카테고리 수집(`webapp/routes/bulk/categories.py:_claim_run`)과 같은 규약이다 —
    advisory lock 대신 행 자체를 표식으로 쓰고 `with_for_update()` 로 원자화한다.
    (SQLite 는 `with_for_update()` 를 조용히 무시하지만 개발·테스트는 단일 프로세스라
    무해하고, Postgres 라이브에서만 실제 잠금이 걸린다.)
    """
    from lemouton.registration.models import ProductDraftRegisterRun
    now = datetime.datetime.utcnow()
    row = (session.query(ProductDraftRegisterRun)
           .filter_by(draft_id=draft_id).with_for_update().first())
    if row is None:
        row = ProductDraftRegisterRun(draft_id=draft_id, running=False)
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            # 동시에 다른 트랜잭션이 먼저 행을 만든 레이스 — 방금 생긴 행을 다시 잠가 읽는다.
            session.rollback()
            row = (session.query(ProductDraftRegisterRun)
                   .filter_by(draft_id=draft_id).with_for_update().first())
            if row is None:
                return None
    if row.running:
        reference = row.progress_at or row.started_at
        if reference and (now - reference) < REGISTER_STALE_AFTER:
            session.rollback()
            return None
    job_id = uuid.uuid4().hex
    row.job_id = job_id
    row.running = True
    row.started_at = now
    row.progress_at = now
    row.finished_at = None
    row.error = None
    row.current_market = None
    row.markets_json = json.dumps(markets)
    row.done_count = 0
    row.total_count = len(markets)
    # 지난 실행의 결과행은 비운다 — 남겨 두면 이번 실행의 진행 상황과 섞여, 아직 부르지도
    # 않은 마켓이 「등록됨」으로 보인다(마켓별 이력·원문은 ProductDraftMarket 장부에 남아 있다).
    row.result_json = None
    session.commit()
    return job_id


def _register_run_write(draft_id, job_id, **fields):
    """실행 상태 행 갱신 — **job_id 가 같을 때만** 쓴다.

    스테일 회수로 새 실행이 시작된 뒤에 옛 좀비 스레드가 뒤늦게 깨어나 상태를 덮으면,
    새 실행의 진행 상황이 옛 결과로 되감긴다(사장님은 그걸 보고 또 누른다 = 중복 등록).
    job_id 대조가 그 경로를 막는 유일한 잠금이다.

    기록 실패는 삼키되 조용히 넘기지 않는다 — 로그 한 줄을 남기고 등록 자체는 계속한다
    (진행률 기록이 등록을 죽이면 원래 목적보다 손해가 크다 — 카테고리 수집과 같은 원칙).
    """
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        row = s.query(ProductDraftRegisterRun).filter_by(draft_id=draft_id).first()
        if row is None or row.job_id != job_id:
            return False
        for k, v in fields.items():
            setattr(row, k, v)
        row.progress_at = datetime.datetime.utcnow()
        s.commit()
        return True
    except Exception as e:      # noqa: BLE001 — 상태 기록 실패가 등록을 죽이면 안 된다.
        s.rollback()
        logger.warning('등록 실행상태 기록 실패 draft_id=%s job=%s — %r', draft_id, job_id, e)
        return False
    finally:
        s.close()


def _register_job(draft_id, job_id, ordered, *, codes, keys, vendor_in):
    """백그라운드 스레드 본체 — 마켓을 **순차로** 돌며 한 마켓이 끝날 때마다 상태에 커밋.

    쓰기 순서가 이 함수의 핵심이다:
      ① 마켓을 부르기 **전에** `current_market` 을 기록한다(=마지막으로 시작한 마켓).
      ② 마켓이 끝나면 결과행을 `result_json` 에 붙이고 `done_count` 를 올린다.
    이 순서라야 스레드가 마켓 처리 도중 죽었을 때, 남은 행이 「○○ 를 시작했는데 끝난
    기록이 없다」를 말해 준다 — 폴링은 그것을 성공도 실패도 아닌 **불확실**로 보고한다.
    반대 순서(끝나고 나서 기록)였다면 죽은 마켓이 아예 흔적을 안 남겨, 안 올라간 것처럼
    보인다(그게 유령 상품을 못 찾게 만드는 거짓 안심이다).

    마켓별 장부(`ProductDraftMarket`) 커밋은 `_register_one` 안에 이미 있다 — 그대로 둔다.
    이 실행 상태 행이 죽어도 장부는 남는다(이중 안전장치).
    """
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
            s, draft, ordered, codes=codes, keys=keys, vendor=vendor_in)}

        rows = []
        for market in ordered:                     # ② 순차 — 마켓 간 병렬 금지
            # ★ 부르기 전에 기록한다 — 여기서 죽으면 이 마켓이 '불확실' 로 남는다.
            _register_run_write(draft_id, job_id, current_market=market)
            pr = pre[market]
            if pr['status'] != 'ready':
                # 브랜드·지재권으로 막힌 것은 **장부에도** 남긴다(단수 라우트와 같은 규약).
                # 보충 필요(missing·need_category)는 아직 아무것도 시도하지 않은 상태라
                # 장부를 더럽히지 않는다 — 시도하지 않은 일을 기록으로 남기면 안 된다.
                if pr['status'] == 'blocked':
                    _brand_block_row(s, draft_id, market,
                                     category_code=pr['category_code'],
                                     account_key=pr['account_key'],
                                     reason=pr['reason'])
                rows.append({
                    'market': market,
                    'status': _SKIP_STATUS.get(pr['status'], 'skipped'),
                    'preflight_status': pr['status'],
                    'account_key': pr['account_key'],
                    'category_code': pr['category_code'],
                    'category_source': pr['category_source'],
                    'market_product_id': None,
                    'error_code': ('BRAND_RESTRICTED' if pr['status'] == 'blocked'
                                   else 'PREFLIGHT'),
                    'error': None,
                    'reason': pr['reason'],
                    'raw': None, 'excluded': [],
                    'notes': list(pr['caveats'] or []),
                })
            else:
                # 쿠팡 vendor 는 요청이 안 보내면 계정 저장값으로 채운다(우리 DB 조회뿐).
                vendor = _vendor_for(s, market, {'vendor': vendor_in,
                                                 'account_key': pr['account_key']})
                row = _register_one(s, draft_id, market,
                                    category_code=pr['category_code'],
                                    account_key=pr['account_key'],
                                    vendor=vendor)                 # ③ 실패해도 계속
                row['preflight_status'] = 'ready'
                row['category_source'] = pr['category_source']
                # 성공이면 「등록 뒤에 알아야 할 것」, 아니면 점검이 알려준 주의를 그대로.
                row['notes'] = (list(POST_REGISTER_NOTES.get(market) or [])
                                if row['status'] == 'ok' else list(pr['caveats'] or []))
                rows.append(row)
            # 마켓 하나가 끝날 때마다 커밋 — 폴링이 「그때까지 분량」을 바로 본다.
            _register_run_write(draft_id, job_id, result_json=json.dumps(rows),
                                done_count=len(rows))

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
    reference = row.progress_at or row.started_at
    now = datetime.datetime.utcnow()
    # 진행률이 멈춘 채 running=True → 스레드가 죽었다고 **의심**한다(단정 아님).
    stale = bool(running and reference and (now - reference) >= REGISTER_STALE_AFTER)
    done = {r.get('market') for r in rows}

    uncertain = None
    # 시작은 했는데 끝난 기록이 없는 마켓 = 올라갔는지 모르는 마켓.
    # (running 이 이미 내려간 경우 = 예상 밖 예외로 끝난 실행. 그때도 current_market 이
    #  남아 있고 그 마켓 결과행이 없으면 똑같이 불확실이다 — error 만 보고 「실패」로
    #  단정하면 마켓 호출 뒤에 죽은 경우를 놓친다.)
    dead = stale or (not running and bool(row.error))
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
        }]
        done.add(m)

    summary = {'ok': 0, 'failed': 0, 'blocked': 0, 'skipped': 0, 'unknown': 0}
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

    s = SessionLocal()
    try:
        draft = (s.query(ProductDraft)
                 .filter(ProductDraft.id == draft_id,
                         ProductDraft.deleted_at.is_(None)).first())
        if draft is None:
            return _err('드래프트를 찾을 수 없습니다.', 404)
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
                         kwargs={'codes': codes, 'keys': keys, 'vendor_in': vendor_in},
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
                                                    'skipped': 0, 'unknown': 0}})
        return jsonify(_register_run_payload(row))
    finally:
        s.close()


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
                                    name=name, limit=50)
            hits = [{'code': str(r.get('prdNo') or ''), 'name': str(r.get('prdNm') or '')[:80]}
                    for r in found if isinstance(r, dict)]
        else:   # lotteon
            from shared.platforms.lotteon.products import list_products
            found = list_products(client=MF._lotteon_client(env_prefix), rows_per_page=100)
            hits = [{'code': str(r.get('spdNo') or ''), 'name': str(r.get('spdNm') or '')[:80]}
                    for r in found if isinstance(r, dict)
                    and name.lower() in str(r.get('spdNm') or '').lower()]
    except Exception as e:      # noqa: BLE001 — 조회 실패도 원문 그대로(추측 금지)
        return jsonify({'ok': False,
                        'error': f'{MARKET_LABEL.get(market, market)} 상품 조회 실패 — {e}'}), 502

    return jsonify({
        'ok': True, 'market': market, 'query': name,
        'count': len(hits), 'rows': hits[:30],
        'note': ('찾은 게 있으면 그 상품이 올라간 것입니다. 0건이라도 「안 올라갔다」의 '
                 '증명은 아닙니다 — 마켓 색인이 늦을 수 있어 판매자센터에서 한 번 더 '
                 '확인해 주세요.'),
    })


def _first_upload_env_prefix(session, market):
    """그 마켓의 활성 업로드 계정 env_prefix(첫 번째). 없으면 None(예외 대신 None — 조회
    실패를 「계정이 없다」는 사실로 정확히 말하기 위해)."""
    from lemouton.sourcing.models_v2 import UploadAccount
    acct = (session.query(UploadAccount)
            .filter_by(market=market, is_active=True)
            .order_by(UploadAccount.id).first())
    return acct.env_prefix if acct else None


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

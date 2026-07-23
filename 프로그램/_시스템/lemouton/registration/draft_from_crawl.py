# -*- coding: utf-8 -*-
"""크롤한 소싱처 상품(SourceProduct) → 등록 초안(ProductDraft) 변환기.

지금까지 끊겨 있던 다리다. 재료는 다 있었다 —
    URL → 크롤 → SourceProduct(가격·재고·옵션·카테고리·이미지·상세) ✅
    ProductDraft → compile_* → 게이트 → 6마켓 등록 ✅
그 사이에 ProductDraft 를 **크롤 값으로** 만들어 주는 코드만 없었다(수기 1곳뿐).

■ 이 모듈이 지키는 것 — 지어내지 않는다
  크롤이 주는 것만 옮긴다. 크롤이 못 주는 것(판매가·고시·A/S·원산지·배송비)은
  **비운 채로 둔다.** 비면 compile_* 가 막고 preflight 가 "무엇이 없는지"를 그대로
  보여준다 — 그게 정직한 동작이다. 여기서 그럴듯한 값을 채우면 그 순간
  「사장님이 정한 값」과 구분이 영영 불가능해진다(notice_defaults.py 와 같은 규율).

■ ★ 매입가를 판매가로 쓰지 않는다 (절대)
  SourceProduct.last_price · SourceOption.current_price 는 **우리가 사는 값**이다.
  그걸 sale_price 에 넣으면 마진 0(수수료 감안 시 역마진)으로 팔린다 = 금전 손실.
  판매가는 마진 엔진(compute_final_price) 또는 사람이 정하는 값이라, 인자로 받지
  않으면 :data:`SALE_PRICE_UNSET`(0) 으로 둔다. 0 은 6마켓 컴파일러가 전부
  「판매가가 0 이하입니다」로 막으므로 조용히 새어나갈 수 없다.

■ 옵션 추가금도 0 이다
  옵션별 추가금은 **판매가 정책**이지 매입가가 아니다. current_price 차이를 그대로
  추가금으로 옮기면 '매입가 차이 = 판매가 차이' 라는 정하지도 않은 정책이 생긴다.
  대신 옵션마다 매입가가 다르면 :func:`fill_report` 가 경고로 띄운다 — 그대로 두면
  비싼 옵션이 싼 값에 팔린다(손해).
"""
# [2026-07-23] 크롤 → 등록 초안 자동 생성
from __future__ import annotations

import json
from datetime import datetime, timezone

from lemouton.registration.models import ProductDraft
from lemouton.sources.models import SourceOption, SourceProduct
from lemouton.sources.service import normalize_url

#: 판매가 미정. 컬럼이 ``nullable=False`` 라 NULL 을 넣을 수 없어 쓰는 값이다.
#: 6마켓 컴파일러가 전부 `판매가가 0 이하입니다` 로 막는다(= preflight 가 표면화).
#: ★ 절대 매입가로 바꾸지 말 것 — 이 상수의 존재 이유가 그 사고를 막는 것이다.
SALE_PRICE_UNSET = 0

#: 크롤이 소유한 칸 — 다시 만들 때 **갱신 대상**. 여기 없는 칸은 사람 몫이라 안 건드린다.
CRAWL_OWNED_FIELDS = (
    'options_json', 'stock_quantity', 'images_json', 'detail_html',
    'source_category_path',
)


class DraftFromCrawlError(ValueError):
    """변환 실패 — 라우트가 400/404 로 바꿔 보여준다."""


class SourceNotCrawled(DraftFromCrawlError):
    """그 URL 의 크롤 결과가 아직 없다. **여기서 크롤을 돌리지 않는다** —
    크롤은 로컬 PC 몫이고 서버가 소싱처에 접속하면 안 된다(CLAUDE.md 정합성 원칙 3)."""


class AmbiguousSourceUrl(DraftFromCrawlError):
    """같은 URL 이 여러 소싱처에 있다 — 어느 쪽인지는 사람만 안다(site 를 받아야 한다)."""


class DraftLocked(DraftFromCrawlError):
    """이미 등록했거나 등록 중인 초안이라 크롤 값으로 덮지 않았다.

    덮으면 마켓에 올라간 내용과 우리 장부가 갈린다(어느 쪽이 진짜인지 모르는 상태).
    """

    def __init__(self, message, draft):
        super().__init__(message)
        self.draft = draft


def _utcnow():
    return datetime.now(timezone.utc)


# ── 조회 ────────────────────────────────────────────────────────────────────

def find_source_product(session, url, *, site=None):
    """붙여넣은 URL → SourceProduct.

    ★ 반드시 :func:`normalize_url` 로 정규화해 조회한다. 저장은 정규화형인데
      사장님은 원문(광고 추적 파라미터가 붙은 주소)을 붙여넣는다 — 이걸 놓쳐
      조인이 통째로 빗나간 이력이 있다(2026-06-13 INV-2).
      정규화해도 못 찾으면 원문 그대로 한 번 더 본다(정규화 도입 전 레거시 행).

    Raises:
        SourceNotCrawled: 그 URL 로 크롤된 상품이 없음
        AmbiguousSourceUrl: 같은 URL 이 소싱처 여러 곳에 있음 (site 로 골라야 함)
    """
    raw = str(url or '').strip()
    if not raw:
        raise DraftFromCrawlError('소싱처 상품 URL 을 입력해 주세요.')
    norm = normalize_url(raw)

    q = (session.query(SourceProduct)
         .filter(SourceProduct.deleted_at.is_(None))
         .filter(SourceProduct.url.in_({norm, raw})))
    if site:
        q = q.filter(SourceProduct.site == str(site).strip())
    rows = q.order_by(SourceProduct.id).all()

    if not rows:
        raise SourceNotCrawled(
            f'이 URL 은 아직 크롤된 적이 없습니다 — 먼저 크롤이 돌아야 합니다. ({norm})')
    if len(rows) > 1:
        sites = sorted({r.site for r in rows})
        if len(sites) > 1:
            raise AmbiguousSourceUrl(
                f'같은 URL 이 소싱처 {sites} 에 모두 있습니다 — 어느 소싱처인지 '
                f'골라 주세요(site).')
        # 같은 소싱처에 정규화 전·후 행이 둘 다 남은 레거시. 정규화형을 진짜로 본다.
        rows.sort(key=lambda r: (r.url != norm, r.id))
    return rows[0]


# ── 옵션 변환 ───────────────────────────────────────────────────────────────

def _load_options(session, source_product):
    return (session.query(SourceOption)
            .filter(SourceOption.source_product_id == source_product.id)
            .filter(SourceOption.deleted_at.is_(None))
            .order_by(SourceOption.id).all())


def to_draft_options(source_options):
    """SourceOption 목록 → 드래프트 옵션 스키마 ``[{color,size,stock,extra_price,sku}]``.

    ■ 재고는 **그대로** 옮긴다 (options.py 의 규약과 같은 뜻)
        n>0  판매가능 / 0 품절 / -1 확인불가 / None 미크롤
      셋 다 등록에서 빠지지만 **사유가 다르다.** `or 0` 로 뭉개면 「아직 안 긁었다」가
      「품절」로 둔갑해, 사장님이 소싱처에 확인하러 갈 근거를 잃는다.

    ■ extra_price 는 항상 0
      옵션 추가금은 판매가 정책이다. current_price(매입가) 를 옮기면 안 된다(모듈 주석).

    ■ sku 는 비운다
      SourceOption.external_option_id 는 **소싱처의 옵션 ID** 다. 그걸 마켓의
      판매자관리코드(sellerManagerCode)로 올리면 우리가 어디서 떼 오는지가 마켓 쪽
      데이터에 그대로 남는다. 우리 품번은 따로 정하는 값이라 비운 채로 둔다.
    """
    out = []
    for o in source_options:
        out.append({
            'color': (o.color_text or '').strip(),
            'size': (o.size_text or '').strip(),
            'stock': o.current_stock,
            'extra_price': 0,
            'sku': '',
        })
    return out


# ── 변환 ────────────────────────────────────────────────────────────────────

def _images_list(raw):
    """SourceProduct.images_json → URL 문자열 목록. 깨져 있으면 빈 목록(지어내지 않는다)."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [u for u in parsed if isinstance(u, str) and u.strip()]


def find_existing_draft(session, source_product):
    """이 소싱처 URL 로 이미 만든 초안 (없으면 None).

    ★ ``deleted_at`` 이 있는 행은 **없는 것으로 본다.** 사장님이 지운 초안이다 —
      되살리면 지운 행위가 무시된다. 대신 새 행을 만든다(product_drafts 에는 URL
      유니크 제약이 없어 안전하다).
    """
    return (session.query(ProductDraft)
            .filter(ProductDraft.source_url == normalize_url(source_product.url))
            .filter(ProductDraft.deleted_at.is_(None))
            .order_by(ProductDraft.id.desc())
            .first())


def build_draft_from_source(session, source_product, *, sale_price=None, now=None):
    """SourceProduct → ProductDraft. **커밋은 호출자 몫**(세션에 add 만 한다).

    같은 소싱처 URL 로 이미 초안이 있으면 **새로 만들지 않고 갱신**한다.
      왜 갱신인가 — 새로 만들면 같은 상품의 초안이 조금씩 다른 값으로 여러 벌 남는다.
      그게 이 저장소가 금지하는 「중복·모순」이고, 어느 쪽을 마켓에 올렸는지 모르게 된다.
      (update_draft 라우트가 같은 이유로 PUT 을 둔 것과 같은 판단.)
    갱신할 때도 **크롤이 소유한 칸만** 덮는다(:data:`CRAWL_OWNED_FIELDS`).
      판매가·고시·A/S·배송비·매입가마진 6칸은 사람이 채운 값이라 절대 손대지 않는다.
      이름·브랜드는 사람이 다듬는 문구라 **비어 있을 때만** 채운다.

    Raises:
        DraftLocked: 이미 등록됐거나 등록 중인 초안 (덮지 않는다)
    """
    now = now or _utcnow()
    existing = find_existing_draft(session, source_product)

    if existing is not None and existing.status not in ('draft', 'failed'):
        raise DraftLocked(
            f'이 URL 의 초안(#{existing.id})은 이미 「{existing.status}」 상태입니다 — '
            f'마켓에 올라간 내용과 갈리지 않게 크롤 값으로 덮지 않았습니다.',
            existing)

    opts = to_draft_options(_load_options(session, source_product))
    images = _images_list(source_product.images_json)
    crawled = {
        'options_json': json.dumps(opts, ensure_ascii=False),
        # ★ 재고도 뭉개지 않는다 — None(미크롤) / -1(확인불가) / 0(품절) 은 다른 뜻이다.
        'stock_quantity': source_product.last_stock,
        'images_json': json.dumps(images, ensure_ascii=False),
        'detail_html': source_product.detail_html or '',
        'source_category_path': (source_product.category_path or '').strip() or None,
    }
    # 크롤 브랜드는 SourceProduct 에 저장되지 않는다(CrawlResult.brand 는 있지만 컬럼이
    # 없다). 나중에 생기면 자동으로 따라오도록 getattr 로 읽되, 없으면 지어내지 않는다.
    crawl_brand = str(getattr(source_product, 'brand', '') or '').strip()
    name = (source_product.product_name or '').strip()

    if existing is None:
        draft = ProductDraft(
            origin='bulk', source='crawl',
            source_site=source_product.site,
            source_url=normalize_url(source_product.url),
            name=name,
            brand=crawl_brand,
            # 크롤은 매입가만 안다 — 판매가는 여기서 절대 채우지 않는다(모듈 주석).
            sale_price=(SALE_PRICE_UNSET if sale_price is None else int(sale_price)),
            created_at=now, updated_at=now,
            **crawled,
        )
        session.add(draft)
        return draft

    for field, value in crawled.items():
        setattr(existing, field, value)
    # 이름·브랜드는 사람이 다듬는 문구다 — 비어 있을 때만 채운다(수정본을 되돌리지 않는다).
    if not (existing.name or '').strip() and name:
        existing.name = name
    if not (existing.brand or '').strip() and crawl_brand:
        existing.brand = crawl_brand
    # 판매가는 호출자가 **명시적으로** 준 경우에만 덮는다. 안 주면 손대지 않는다
    # (이미 사람이 정해 둔 판매가를 0 으로 되돌리면 등록이 조용히 막힌다).
    if sale_price is not None:
        existing.sale_price = int(sale_price)
    existing.source_site = source_product.site
    existing.source = 'crawl'
    existing.updated_at = now
    return existing


# ── 보고 (무엇이 채워졌고 무엇이 사람 몫인가) ───────────────────────────────

#: 크롤이 **원리상** 줄 수 없는 칸 — 화면이 "여기는 사람이 채웁니다" 로 쓰는 목록.
HUMAN_ONLY_NOTES = (
    '판매가 — 크롤은 매입가만 압니다. 마진을 보고 사람이 정합니다.',
    '상품고시정보 — 소재·제조자·품질보증기준·A/S책임자 (설정 탭의 「고시정보 기본값」이 '
    '채워 두면 사전 점검이 자동으로 씁니다).',
    'A/S 전화·안내 — 우리 셀러 정보라 소싱처에 없습니다.',
    '배송비·반품비 — 우리 정책입니다(기본 3,000원 / 5,000원).',
    '상품 종류(고시유형) — 기본 「의류」로 둡니다. 신발·가방이면 바꿔야 합니다.',
)


def fill_report(source_product, draft, source_options=None):
    """무엇이 크롤에서 채워졌는지 + 그대로 두면 위험한 것.

    Returns:
        {'filled': {...}, 'warnings': [...], 'human_only': [...]}
    """
    opts = json.loads(draft.options_json or '[]')
    images = _images_list(draft.images_json)
    filled = {
        'name': draft.name or '',
        'brand': draft.brand or '',
        'source_site': draft.source_site,
        'source_category_path': draft.source_category_path,
        'options': len(opts),
        'sellable_options': sum(1 for o in opts
                                if isinstance(o.get('stock'), int) and o['stock'] > 0),
        'stock_quantity': draft.stock_quantity,
        'images': len(images),
        'detail_html': bool((draft.detail_html or '').strip()),
        'sale_price': draft.sale_price,
    }

    warnings = []
    if not filled['name']:
        warnings.append('상품명이 비어 있습니다 — 크롤이 이름을 못 가져왔습니다.')
    if not filled['brand']:
        warnings.append('브랜드가 비어 있습니다 — 브랜드·지재권 제한표는 브랜드가 있어야 '
                        '판정합니다(비어 있으면 아무것도 막지 않습니다).')
    if not filled['options'] and (draft.stock_quantity is None or draft.stock_quantity <= 0):
        warnings.append('옵션도 재고도 없습니다 — 크롤 결과를 먼저 확인해 주세요.')
    if filled['options'] and not filled['sellable_options']:
        warnings.append(f"옵션 {filled['options']}개가 전부 판매 불가(품절·확인불가·미크롤)"
                        '입니다 — 이 상태로는 어느 마켓에도 올라가지 않습니다.')
    if any(not (o.get('color') or '').strip() for o in opts):
        warnings.append('색상이 빈 옵션이 있습니다 — 등록 규격상 색상은 필수입니다'
                        '(값을 지어내지 마세요, 구매자 화면에 그대로 노출됩니다).')
    if not images:
        warnings.append('이미지가 없습니다 — 6마켓 전부 대표 이미지가 필수입니다.')
    if not filled['detail_html']:
        warnings.append('상세설명(HTML)이 없습니다 — 옥션·G마켓·11번가·롯데온은 필수입니다.')
    if not draft.source_category_path:
        warnings.append('소싱처 카테고리 경로가 없습니다 — 카테고리 자동 맵핑을 쓸 수 없습니다.')

    # ★ 옵션별 매입가가 다른데 추가금이 0 이면, 비싼 옵션이 싼 값에 팔린다(손해).
    prices = sorted({o.current_price for o in (source_options or [])
                     if isinstance(o.current_price, int) and o.current_price > 0})
    if len(prices) > 1:
        warnings.append(
            f'옵션별 매입가가 다릅니다 ({prices[0]:,}원 ~ {prices[-1]:,}원) — '
            '옵션 추가금은 판매 정책이라 크롤이 정하지 않습니다. 비싼 옵션이 싼 값에 '
            '팔리지 않게 추가금을 직접 넣어 주세요.')
    if draft.sale_price is not None and draft.sale_price <= 0:
        last = source_product.last_price
        warnings.append(
            '판매가가 아직 없습니다 — 크롤이 아는 건 매입가'
            + (f'({last:,}원)' if isinstance(last, int) and last > 0 else '')
            + '뿐입니다. 매입가를 판매가로 쓰면 역마진입니다.')

    return {'filled': filled, 'warnings': warnings,
            'human_only': list(HUMAN_ONLY_NOTES)}

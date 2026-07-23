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

■ 옵션 추가금도 0 이다 — 단, **처음 만들 때만**
  옵션별 추가금은 **판매가 정책**이지 매입가가 아니다. current_price 차이를 그대로
  추가금으로 옮기면 '매입가 차이 = 판매가 차이' 라는 정하지도 않은 정책이 생긴다.
  대신 옵션마다 매입가가 다르면 :func:`fill_report` 가 경고로 띄운다 — 그대로 두면
  비싼 옵션이 싼 값에 팔린다(손해).

■ ★★ 재크롤이 사람이 넣은 추가금·품번을 지우지 않는다 (2026-07-23 리뷰 C1)
  추가금이 판매 정책이라면, **크롤은 그 칸을 되돌릴 권한도 없다.** 예전에는 갱신 때
  options_json 을 통째로 덮어써서 「260mm +30,000원」이 재크롤 한 번에 0 으로 돌아갔다
  (= 비싼 옵션이 기본가로 팔린다 = 금전 손실). 지금은 (색상, 사이즈) 키로 **머지**한다:
    · 재고(stock) 만 크롤 값으로 갱신
    · extra_price · sku 는 기존 값 그대로 유지
    · 크롤에서 사라진 조합은 제거, 새로 생긴 조합은 추가
  무엇이 바뀌고 무엇이 유지됐는지는 :func:`fill_report` 의 warnings 로 전부 표면화한다
  (조용한 덮어쓰기 금지).
"""
# [2026-07-23] 크롤 → 등록 초안 자동 생성
from __future__ import annotations

import json
from datetime import datetime, timezone

from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.sources.models import SourceOption, SourceProduct
from lemouton.sources.service import normalize_url

#: 판매가 미정. 컬럼이 ``nullable=False`` 라 NULL 을 넣을 수 없어 쓰는 값이다.
#: 6마켓 컴파일러가 전부 `판매가가 0 이하입니다` 로 막는다(= preflight 가 표면화).
#: ★ 절대 매입가로 바꾸지 말 것 — 이 상수의 존재 이유가 그 사고를 막는 것이다.
SALE_PRICE_UNSET = 0

#: 크롤이 소유한 칸 — 다시 만들 때 **갱신 대상**. 여기 없는 칸은 사람 몫이라 안 건드린다.
#: ★ 선언만 해 두고 코드가 따로 dict 를 쓰면 이중 관리다(한쪽만 고쳐져 갈린다).
#:   :func:`build_draft_from_source` 가 **이 순서대로** setattr 하고, 값 dict 의 키가
#:   여기와 정확히 같은지 검사한다 — 어긋나면 조용히 넘어가지 않고 KeyError 로 터진다.
CRAWL_OWNED_FIELDS = (
    'options_json', 'stock_quantity', 'images_json', 'cdn_images_json',
    'detail_html', 'source_category_path',
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


def live_drafts_for(session, source_product):
    """이 (소싱처, URL) 로 살아 있는 초안 전부 — 최신순.

    ★ ``deleted_at`` 이 있는 행은 **없는 것으로 본다.** 사장님이 지운 초안이다 —
      되살리면 지운 행위가 무시된다. 대신 새 행을 만든다.
    ★ [2026-07-23 리뷰 m2] 키에 ``source_site`` 를 넣는다. 같은 URL 이 소싱처 두 곳에
      있을 수 있고(:class:`AmbiguousSourceUrl` 가 그래서 있다), URL 만으로 찾으면
      A 소싱처 초안을 B 소싱처 크롤 값으로 덮는다.
    ★ [리뷰 I4] 여러 벌이면 그대로 돌려준다 — 조회→삽입 사이에 잠금이 없어(gunicorn
      워커 3개) 동시 요청이 초안을 2벌 만들 수 있다. 갱신은 최신 1벌만 되므로 나머지는
      유령이 된다. 그 사실을 세지 않으면 아무도 모른다.
    """
    return (session.query(ProductDraft)
            .filter(ProductDraft.source_url == normalize_url(source_product.url))
            .filter(ProductDraft.source_site == source_product.site)
            .filter(ProductDraft.deleted_at.is_(None))
            .order_by(ProductDraft.id.desc())
            .all())


def find_existing_draft(session, source_product):
    """이 소싱처 URL 로 이미 만든 초안 (없으면 None). 여러 벌이면 최신 1벌."""
    rows = live_drafts_for(session, source_product)
    return rows[0] if rows else None


def registered_market_rows(session, draft):
    """이 초안이 **실제로** 마켓에 올라간 흔적 — 상태 문자열이 아니라 사실로 본다.

    ★ [2026-07-23 리뷰 C3] ``draft.status`` 로 판정하면 안 된다. service.py 는 마켓
      **한 곳만** 실패해도 ``draft.status='failed'`` 로 쓴다(154·182·198·279·326·340·356).
      스스 성공 + 쿠팡 실패면 status='failed' 라, 상태 문자열만 보는 잠금은 **이미
      스스에 올라가 있는 상품**을 크롤 값으로 덮어버린다(마켓 내용 ≠ 우리 장부).
      그래서 ``ProductDraftMarket`` 에 ``status='ok'`` 이거나 ``market_product_id`` 가
      남은 행이 하나라도 있으면 잠근다.
    """
    if draft is None or getattr(draft, 'id', None) is None:
        return []
    rows = (session.query(ProductDraftMarket)
            .filter(ProductDraftMarket.draft_id == draft.id).all())
    return [r for r in rows
            if (r.status or '') == 'ok' or str(r.market_product_id or '').strip()]


# ── 옵션 머지 (사람이 넣은 추가금·품번을 지키는 자리) ───────────────────────

def _opt_key(o):
    """(색상, 사이즈) — 옵션 한 줄의 동일성 키. 컴파일러들이 쓰는 키와 같다."""
    return (str((o or {}).get('color') or '').strip(),
            str((o or {}).get('size') or '').strip())


def _as_int(v):
    """숫자로 읽히면 int, 아니면 None. 여기서 예외를 던지지 않는다(보고용 계산)."""
    try:
        return int(str(v).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def merge_options(old_options, crawl_options):
    """기존 옵션 + 크롤 옵션 → (머지 결과, 변경 요약).

    규칙 (★ 리뷰 C1 — 이 함수가 금전 손실을 막는 자리다):
      · 재고(stock)      — 크롤이 진실. 그대로 덮는다(3상태 유지: 0/-1/None).
      · extra_price·sku  — **사람이 정하는 값**. 기존 값을 그대로 옮긴다.
      · 크롤에 없는 조합  — 제거 (소싱처에서 사라진 옵션)
      · 크롤에만 있는 조합 — 추가 (extra_price=0, sku='')

    Returns:
        (merged, summary) — summary = {'added': [키…], 'removed': [키…],
            'stock_changed': [{'key':(색,사이즈),'before':…,'after':…}],
            'kept_extra_price': N, 'kept_sku': N}
    """
    prev = {}
    for o in (old_options or []):
        if isinstance(o, dict):
            prev[_opt_key(o)] = o

    merged, added, stock_changed = [], [], []
    kept_extra = kept_sku = 0
    seen = set()
    for c in (crawl_options or []):
        key = _opt_key(c)
        seen.add(key)
        row = dict(c)
        old = prev.get(key)
        if old is None:
            added.append(key)
            merged.append(row)
            continue
        # ★ 사람 값은 **그대로** 옮긴다 — 숫자로 다시 만들지 않는다(폼이 '30,000' 을
        #   넣어 뒀다면 그 문자열이 진실이고, 컴파일러의 coerce_int 가 해석한다).
        row['extra_price'] = old.get('extra_price', 0)
        row['sku'] = old.get('sku', '')
        if _as_int(row['extra_price']):
            kept_extra += 1
        if str(row['sku'] or '').strip():
            kept_sku += 1
        if old.get('stock') != row.get('stock'):
            stock_changed.append({'key': key, 'before': old.get('stock'),
                                  'after': row.get('stock')})
        merged.append(row)

    removed = [k for k in prev if k not in seen]
    return merged, {'added': added, 'removed': removed,
                    'stock_changed': stock_changed,
                    'kept_extra_price': kept_extra, 'kept_sku': kept_sku}


def brand_from_source_links(session, source_product):
    """이 소싱처 상품이 먹여 살리는 **실데이터** 브랜드 (못 정하면 '').

    ★ [2026-07-23 리뷰 C2] 브랜드를 지어내지 않으면서도 비워 두지 않는 유일한 길.
      경로는 ``option_source_links``(sku ↔ source_options) — 실제 FK 가 있는 표라
      URL 문자열 비교보다 정확하다. 정본은
      :func:`lemouton.sources.crawl_change_stats.brands_of_source_product`.

    비우는 경우(=지어내지 않는다):
      · 링크가 없어 ``(브랜드 미지정)`` 만 나올 때 → '' (제한표가 「브랜드 없음」으로 막는다)
      · 브랜드가 둘 이상 섞였을 때 → '' (어느 쪽인지는 사람만 안다)
    """
    try:
        from lemouton.sources.crawl_change_stats import (
            UNSPECIFIED_BRAND, brands_of_source_product)
        brands = brands_of_source_product(session, source_product)
    except Exception:      # noqa: BLE001 — 브랜드를 못 읽는다고 초안 생성을 막지 않는다
        return ''
    real = sorted({str(b).strip() for b in (brands or set())
                   if str(b).strip() and str(b).strip() != UNSPECIFIED_BRAND})
    return real[0][:120] if len(real) == 1 else ''


def build_draft_from_source(session, source_product, *, sale_price=None, now=None):
    """SourceProduct → ProductDraft. **커밋은 호출자 몫**(세션에 add 만 한다).

    같은 소싱처 URL 로 이미 초안이 있으면 **새로 만들지 않고 갱신**한다.
      왜 갱신인가 — 새로 만들면 같은 상품의 초안이 조금씩 다른 값으로 여러 벌 남는다.
      그게 이 저장소가 금지하는 「중복·모순」이고, 어느 쪽을 마켓에 올렸는지 모르게 된다.
      (update_draft 라우트가 같은 이유로 PUT 을 둔 것과 같은 판단.)
    갱신할 때도 **크롤이 소유한 칸만** 덮는다(:data:`CRAWL_OWNED_FIELDS`).
      판매가·고시·A/S·배송비·매입가마진 6칸은 사람이 채운 값이라 절대 손대지 않는다.
      이름·브랜드는 사람이 다듬는 문구라 **비어 있을 때만** 채운다.
      옵션은 통째로 덮지 않고 (색상,사이즈) 키로 머지한다 — :func:`merge_options`.

    갱신본에는 변경 요약을 :func:`fill_report` 가 읽을 수 있게 붙여 둔다
    (``draft._crawl_changes`` — 컬럼이 아니라 이번 요청 한정 메모).

    Raises:
        DraftLocked: 이미 마켓에 올라간 초안 (덮지 않는다)
    """
    now = now or _utcnow()
    live = live_drafts_for(session, source_product)
    existing = live[0] if live else None

    posted = registered_market_rows(session, existing)
    if posted:
        where = ', '.join(sorted({
            f"{r.market}"
            + (f"({r.market_product_id})" if r.market_product_id else '')
            for r in posted}))
        raise DraftLocked(
            f'이 URL 의 초안(#{existing.id})은 이미 마켓에 올라가 있습니다 ({where}) — '
            f'마켓에 올라간 내용과 갈리지 않게 크롤 값으로 덮지 않았습니다. '
            f'(초안 상태 표시: 「{existing.status}」)',
            existing)

    opts = to_draft_options(_load_options(session, source_product))
    images = _images_list(source_product.images_json)
    detail = source_product.detail_html or ''
    category = (source_product.category_path or '').strip() or None
    name = (source_product.product_name or '').strip()
    # 크롤 브랜드는 SourceProduct 에 컬럼이 없다(CrawlResult.brand 는 있다). 나중에 생기면
    # 자동으로 따라오도록 getattr 로 읽되, 없으면 **옵션 링크의 실데이터**로 채운다.
    # 둘 다 없으면 비운다 — 상품명에서 지어내지 않는다(리뷰 C2).
    crawl_brand = (str(getattr(source_product, 'brand', '') or '').strip()
                   or brand_from_source_links(session, source_product))

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
            options_json=json.dumps(opts, ensure_ascii=False),
            # ★ 재고도 뭉개지 않는다 — None(미크롤)/-1(확인불가)/0(품절)은 다른 뜻이다.
            stock_quantity=source_product.last_stock,
            images_json=json.dumps(images, ensure_ascii=False),
            cdn_images_json='[]',
            detail_html=detail,
            source_category_path=category,
        )
        session.add(draft)
        draft._crawl_changes = None          # 새로 만들었으니 '덮은 것' 이 없다
        draft._crawl_duplicates = len(live)
        return draft

    # ── 갱신 — 무엇을 덮는지 먼저 계산한다(리뷰 I3: 덮은 내용을 말하지 않으면 조용한 실패)
    old_opts = _safe_options(existing.options_json)
    old_images = _images_list(existing.images_json)
    old_detail = existing.detail_html or ''

    if old_opts and not opts:
        # ★ 크롤이 옵션을 하나도 주지 않았다 = 「옵션이 없어졌다」가 아니라 대개 파싱 실패다.
        #   사람이 넣어 둔 옵션(추가금·품번 포함)을 그 근거로 지우지 않는다(정합성 원칙 1).
        merged, opt_diff = old_opts, {'added': [], 'removed': [], 'stock_changed': [],
                                      'kept_extra_price': 0, 'kept_sku': 0,
                                      'crawl_gave_no_options': True}
    else:
        merged, opt_diff = merge_options(old_opts, opts)

    changes = {
        'options': opt_diff,
        'images_before': len(old_images), 'images_after': len(images),
        'detail_replaced': old_detail.strip() != detail.strip(),
        'detail_before_len': len(old_detail), 'detail_after_len': len(detail),
        'stock_before': existing.stock_quantity, 'stock_after': source_product.last_stock,
        'category_before': existing.source_category_path, 'category_after': category,
        'cdn_images_cleared': False,
    }
    # [리뷰 I1] 이미지가 바뀌었는데 cdn_images_json 을 그대로 두면, service.py:301 이
    #   「CDN 값이 있으니 업로드 생략」으로 판단해 **옛 사진**을 스스에 올린다.
    cdn = existing.cdn_images_json
    if old_images != images:
        cdn = '[]'
        changes['cdn_images_cleared'] = True

    crawled = {
        'options_json': json.dumps(merged, ensure_ascii=False),
        'stock_quantity': source_product.last_stock,
        'images_json': json.dumps(images, ensure_ascii=False),
        'cdn_images_json': cdn,
        'detail_html': detail,
        'source_category_path': category,
    }
    # ★ 크롤이 소유한 칸의 정본은 CRAWL_OWNED_FIELDS 하나다(m1 — 이중 관리 금지).
    #   키가 어긋나면 조용히 넘어가지 않고 KeyError 로 터진다.
    if set(crawled) != set(CRAWL_OWNED_FIELDS):
        raise DraftFromCrawlError(
            f'CRAWL_OWNED_FIELDS 와 갱신 값이 어긋납니다: '
            f'{sorted(set(crawled) ^ set(CRAWL_OWNED_FIELDS))}')
    for field in CRAWL_OWNED_FIELDS:
        setattr(existing, field, crawled[field])

    # 이름·브랜드는 사람이 다듬는 문구다 — 비어 있을 때만 채운다(수정본을 되돌리지 않는다).
    if not (existing.name or '').strip() and name:
        existing.name = name
    if not (existing.brand or '').strip() and crawl_brand:
        existing.brand = crawl_brand
        changes['brand_filled'] = crawl_brand
    # 판매가는 호출자가 **명시적으로** 준 경우에만 덮는다. 안 주면 손대지 않는다
    # (이미 사람이 정해 둔 판매가를 0 으로 되돌리면 등록이 조용히 막힌다).
    if sale_price is not None:
        existing.sale_price = int(sale_price)
    existing.source_site = source_product.site
    existing.source = 'crawl'
    existing.updated_at = now
    existing._crawl_changes = changes
    existing._crawl_duplicates = len(live)
    return existing


def _safe_options(raw):
    """options_json → 리스트. 깨져 있으면 빈 목록(여기서 500 을 내지 않는다)."""
    try:
        parsed = json.loads(raw or '[]')
    except (ValueError, TypeError):
        return []
    return [o for o in parsed if isinstance(o, dict)] if isinstance(parsed, list) else []


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


def _key_text(key):
    color, size = key
    return f'{color or "?"}/{size or "?"}'


def change_notes(changes):
    """갱신 요약 dict → 사람이 읽는 줄들 (덮은 것을 말하지 않으면 조용한 실패다 — 리뷰 I3).

    새로 만든 초안이면 ``changes`` 가 None 이라 빈 목록.
    """
    if not changes:
        return []
    out = []
    o = changes.get('options') or {}
    if o.get('crawl_gave_no_options'):
        out.append('⚠ 크롤이 옵션을 하나도 주지 않아 **기존 옵션을 그대로 두었습니다** — '
                   '소싱처에서 옵션이 없어진 것인지 크롤이 실패한 것인지 확인해 주세요.')
    bits = []
    if o.get('added'):
        bits.append(f"추가 {len(o['added'])}개({', '.join(_key_text(k) for k in o['added'][:5])}"
                    + ('…' if len(o['added']) > 5 else '') + ')')
    if o.get('removed'):
        bits.append(f"제거 {len(o['removed'])}개({', '.join(_key_text(k) for k in o['removed'][:5])}"
                    + ('…' if len(o['removed']) > 5 else '') + ')')
    if o.get('stock_changed'):
        sample = '; '.join(f"{_key_text(c['key'])} {c['before']}→{c['after']}"
                           for c in o['stock_changed'][:5])
        bits.append(f"재고변경 {len(o['stock_changed'])}개({sample}"
                    + ('…' if len(o['stock_changed']) > 5 else '') + ')')
    if bits:
        out.append('옵션 — ' + ' · '.join(bits))
    if o.get('kept_extra_price') or o.get('kept_sku'):
        out.append(f"사람이 넣은 값을 그대로 지켰습니다 — 추가금 {o.get('kept_extra_price', 0)}개 · "
                   f"품번 {o.get('kept_sku', 0)}개 (크롤은 재고만 갱신합니다).")
    if changes.get('images_before') != changes.get('images_after'):
        out.append(f"이미지 {changes.get('images_before')}장 → {changes.get('images_after')}장으로 "
                   '바뀌었습니다.')
    if changes.get('cdn_images_cleared'):
        out.append('사진이 바뀌어 업로드해 둔 CDN 사진을 비웠습니다 — 등록 때 새 사진으로 '
                   '다시 올라갑니다(옛 사진이 나가지 않게).')
    if changes.get('detail_replaced'):
        out.append(f"상세설명을 크롤 값으로 교체했습니다 ({changes.get('detail_before_len')}자 → "
                   f"{changes.get('detail_after_len')}자).")
    if changes.get('stock_before') != changes.get('stock_after'):
        out.append(f"평면 재고 {_stock_text(changes.get('stock_before'))} → "
                   f"{_stock_text(changes.get('stock_after'))}.")
    if changes.get('category_before') != changes.get('category_after'):
        out.append(f"소싱처 분류 {changes.get('category_before') or '(없음)'} → "
                   f"{changes.get('category_after') or '(없음)'}.")
    if changes.get('brand_filled'):
        out.append(f"브랜드가 비어 있어 소싱처 옵션 연결에서 「{changes['brand_filled']}」로 "
                   '채웠습니다(지어낸 값이 아니라 실데이터).')
    return out


def _stock_text(v):
    """재고 3상태를 뜻 그대로 — 숫자만 찍으면 -1 이 '재고 -1개' 로 읽힌다."""
    if v is None:
        return '미크롤'
    if isinstance(v, int) and v < 0:
        return '확인불가'
    if v == 0:
        return '품절(0)'
    return f'{v}개'


def fill_report(source_product, draft, source_options=None):
    """무엇이 크롤에서 채워졌는지 + 그대로 두면 위험한 것 + **이번에 무엇을 덮었는지**.

    Returns:
        {'filled': {...}, 'warnings': [...], 'human_only': [...], 'changes': [...]}
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

    # ★ [리뷰 I3] 갱신이 무엇을 덮었는지 — 「기존 초안을 갱신했습니다」 한 줄로 끝내지 않는다.
    notes = change_notes(getattr(draft, '_crawl_changes', None))
    warnings.extend(notes)

    # ★ [리뷰 I4] 같은 URL 초안이 여러 벌이면 갱신되는 건 최신 1벌뿐 — 나머지는 유령이다.
    dup = int(getattr(draft, '_crawl_duplicates', 0) or 0)
    if dup > 1:
        warnings.append(
            f'같은 소싱처 URL 로 살아 있는 초안이 {dup}벌 있습니다 — 갱신은 최신 1벌'
            f'(#{draft.id})에만 반영됩니다. 나머지는 지워 주세요(동시 요청으로 생긴 유령 초안).')

    return {'filled': filled, 'warnings': warnings,
            'human_only': list(HUMAN_ONLY_NOTES), 'changes': notes}

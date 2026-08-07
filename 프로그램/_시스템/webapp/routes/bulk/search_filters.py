# -*- coding: utf-8 -*-
"""검색필터 — 「검색형 URL 한 줄 = 수집 행위 하나」의 CRUD + 「지금 수집」.

대량등록은 모음전과 근본이 다르다. 모음전은 옵션별 URL 을 사람이 하나씩 넣고
소싱처를 **비교**하지만, 대량등록은 검색 결과 한 줄로 수십~수천 상품을 자동 수집한다.
그 한 줄을 개체로 만든 것이 `SearchFilter` 다(설계서 §3-1).

🔴 **훑는 일은 서버가 하지 않는다.** 페이지를 여는 건 로컬 PC 의 크롬 확장이다
  (「크롤은 로컬 PC」 원칙). 서버는 ①무엇을 훑을지 알려주고 ②결과를 받는다.
  이 두 라우트는 `webapp/routes/api.py` 쪽에 있다(확장이 부르는 곳과 같은 자리).
"""
from datetime import datetime, timezone

from flask import jsonify, request

from shared.db import SessionLocal

from . import bp


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _err(msg, code=400):
    return jsonify({'ok': False, 'message': msg}), code


#: 화면에 보여줄 소싱처 이름. 없으면 키를 그대로 쓴다(지어내지 않는다).
_SOURCE_LABEL = {'musinsa': '무신사'}


def _auto_name(session, source_key, listing_url):
    """`무신사_나이키_001` — 사장님이 이름을 안 지어도 목록에서 구분되게.

    검색어를 주소에서 뽑아 쓴다. 못 뽑으면 번호만 붙인다(추측해서 채우지 않는다).
    """
    import re
    from urllib.parse import unquote
    from lemouton.registration.models import SearchFilter

    label = _SOURCE_LABEL.get(source_key, source_key)
    m = re.search(r'[?&](?:keyword|q|query|searchWord)=([^&#]+)', listing_url or '')
    kw = unquote(m.group(1)) if m else ''
    n = session.query(SearchFilter).filter_by(source_key=source_key).count() + 1
    parts = [label] + ([kw] if kw else []) + [f'{n:03d}']
    return '_'.join(parts)[:160]


def _row(f):
    return {
        'id': f.id, 'name': f.name, 'source_key': f.source_key,
        'listing_url': f.listing_url, 'max_items': f.max_items,
        'page_from': f.page_from, 'page_to': f.page_to,
        'enabled': bool(f.enabled),
        'run_requested_at': f.run_requested_at.isoformat() if f.run_requested_at else None,
        'last_run_at': f.last_run_at.isoformat() if f.last_run_at else None,
        'last_new_count': f.last_new_count,
        'apply_policy_id': f.apply_policy_id,
    }


def _policy_name(session, policy_id):
    """정책 이름 — 번호만 보여주면 사장님이 어느 정책인지 알 수 없다."""
    if not policy_id:
        return None
    from lemouton.policy.models import MarketPolicy
    p = session.query(MarketPolicy).filter_by(id=policy_id).first()
    return p.name if p is not None else None


@bp.get('/api/price-policies')
def list_price_policies():
    """검색필터에 붙일 가격 정책 목록 — **드롭다운용으로 이름·번호만.**

    ★ 정책 화면(`/policies`)은 사람이 보는 표라 JSON 을 안 준다. 그 화면을 고쳐
      JSON 도 내게 하면 두 화면이 같은 코드를 나눠 갖게 되고, 한쪽을 고칠 때
      다른 쪽이 조용히 바뀐다. 여기서는 **고르는 데 필요한 것만** 따로 준다.
    """
    from lemouton.policy.models import MarketPolicy
    s = SessionLocal()
    try:
        rows = (s.query(MarketPolicy)
                .filter(MarketPolicy.deleted_at.is_(None))
                .order_by(MarketPolicy.is_default.desc(), MarketPolicy.id.desc())
                .limit(300).all())
        return jsonify({'ok': True, 'policies': [
            {'id': p.id, 'name': p.name, 'brand': p.brand,
             'is_default': bool(p.is_default)} for p in rows]})
    finally:
        s.close()


@bp.get('/api/search-filters')
def list_search_filters():
    from lemouton.registration.models import (
            ProductDraft, SearchFilter, SearchFilterItem)
    s = SessionLocal()
    try:
        rows = (s.query(SearchFilter)
                .filter(SearchFilter.deleted_at.is_(None))
                .order_by(SearchFilter.id.desc()).limit(300).all())
        out = []
        for f in rows:
            d = _row(f)
            # 「수집량」 — 이 필터가 지금까지 찾아낸 상품 주소 수(성적표의 밑변).
            d['found_total'] = (s.query(SearchFilterItem)
                                .filter_by(filter_id=f.id).count())
            # 「어디까지 왔나」 — 찾음 → (크롤 대기) → 상품.
            #   🔴 초안 수는 `search_filter_id` 로 센다. 이 연결이 없으면
            #     성적표(수집→생존→매출)가 통째로 성립하지 않는다.
            d['drafted_total'] = (s.query(ProductDraft)
                                  .filter(ProductDraft.search_filter_id == f.id,
                                          ProductDraft.deleted_at.is_(None)).count())
            d['apply_policy_name'] = _policy_name(s, f.apply_policy_id)
            out.append(d)
        return jsonify({'ok': True, 'filters': out})
    finally:
        s.close()


@bp.post('/api/search-filters')
def create_search_filter():
    """검색필터 1건 만들기.

    🔴 **규칙을 모르는 소싱처는 여기서 막는다.** 만들게 두면 「지금 수집」이 영원히
      0건이 되고, 사장님은 「왜 안 되지」를 화면에서 알 수 없다. 만들 때 말한다.
    """
    from lemouton.registration.models import SearchFilter
    from lemouton.sources import listing_discover as LD

    body = request.get_json(silent=True) or {}
    source_key = (body.get('source_key') or '').strip().lower()
    listing_url = (body.get('listing_url') or '').strip()
    if not source_key or not listing_url:
        return _err('소싱처와 검색 결과 주소가 모두 필요합니다.')
    try:
        LD.extract_product_urls('', source_key=source_key)   # 규칙 유무만 확인
    except ValueError as e:
        return _err(str(e))

    s = SessionLocal()
    try:
        f = SearchFilter(
            name=(body.get('name') or '').strip() or _auto_name(s, source_key, listing_url),
            source_key=source_key, listing_url=listing_url,
            max_items=body.get('max_items') or None,
            page_from=body.get('page_from') or None,
            page_to=body.get('page_to') or None,
            option_exclude_words=(body.get('option_exclude_words') or '').strip() or None,
            # 판매가를 정할 가격 정책. 안 붙이면 상품은 만들어지되 판매가가 0으로 남는다
            # (지어내지 않는다 — 사전 점검이 「판매가가 0 이하」로 막는다).
            apply_policy_id=body.get('apply_policy_id') or None,
        )
        s.add(f)
        s.commit()
        return jsonify({'ok': True, 'filter': _row(f)})
    finally:
        s.close()


@bp.post('/api/search-filters/<int:filter_id>/run')
def run_search_filter(filter_id: int):
    """「지금 수집」 — 도장만 찍는다. 실제로 훑는 건 로컬 PC 확장이다.

    이 도장(`run_requested_at`)이 곧 큐다. 안 찍힌 필터는 확장이 가져가지 않는다 —
    만들어 두기만 한 필터가 저절로 돌면 소싱처를 두들긴다(차단·계정 위험).
    """
    from lemouton.registration.models import SearchFilter
    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=filter_id).first()
        if f is None or f.deleted_at is not None:
            return _err('검색필터를 찾을 수 없습니다.', 404)
        f.run_requested_at = _now()
        s.commit()
        return jsonify({'ok': True, 'filter': _row(f)})
    finally:
        s.close()


def compute_price_for(session, source_product, policy_id):
    """이 소싱처 상품의 **판매가**. → `(판매가|None, 못 정한 사유|None)`.

    ━━ 산식은 한 줄도 여기 쓰지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        ① 표면가 → **최종매입가**  = `bulk/margin.compute_manual_margin`
           (혜택 순차차감 엔진 `pricing/final_price` 를 그대로 탄다)
        ② 최종매입가 → **판매가**  = `pricing/unified.compute_market_price`
           (마진율·마진금액·지정가 + 수수료·배송비·라운딩·가드레일)
        ③ 정책을 엔진이 읽는 모양으로 = `policy/as_template.policy_as_template`
      셋 다 이미 있고, 구성→초안 경로(`send/as_draft`)가 이미 이 조합을 쓴다.
      🔴 같은 숫자를 두 곳에서 만들면 반드시 갈린다.

    🔴 **못 정하면 0 이 아니라 None** 을 돌려준다. 호출부가 판매가를 안 넣고,
      사전 점검이 「판매가가 0 이하입니다」로 막는다. 아무 값이나 채우면 그 가격이
      그대로 마켓에 나간다(돈이 걸린 자리라 폴백 금지).

    🔴 **못 정한 이유를 반드시 함께 돌려준다.** 예전엔 `except` 가 예외를 삼켜
      판매가가 조용히 0 이 됐다(없는 함수를 부르는 버그가 시험에서야 드러났다).
      값을 못 만드는 것과 그 사실을 안 말하는 것은 다른 잘못이다.

    ★ 어느 마켓 기준인가 — 스마트스토어로 계산한다. 초안은 아직 마켓이 안 정해졌고,
      마켓별 값은 등록할 때 `ProductDraftMarket.sale_price` 가 따로 갖는다.
    """
    if not policy_id:
        return None, '가격 정책이 안 붙어 있습니다'
    surface = int(getattr(source_product, 'last_price', 0) or 0)
    if surface <= 0:
        # 표면가가 없으면 마진을 붙일 바탕이 없다.
        return None, '소싱처 표면가를 못 읽었습니다(크롤이 가격을 못 가져옴)'
    try:
        from .margin import compute_manual_margin
        from lemouton.policy.as_template import policy_as_template
        from lemouton.pricing.unified import compute_market_price
        from lemouton.sourcing.models import SourcingSource

        # 혜택 템플릿은 소싱처 **번호**에 붙어 있다(`SourceBenefitTemplate.source_id`).
        # 우리가 아는 건 키('musinsa')뿐이라 번호로 바꿔 준다.
        src = (session.query(SourcingSource)
               .filter(SourcingSource.source_key == source_product.site).first())
        if src is None:
            return None, f'모르는 소싱처({source_product.site}) — 혜택을 못 읽습니다'
        got = compute_manual_margin(session, source_id=src.id, surface_price=surface)
        cost = int((got or {}).get('final_price') or 0)
        if cost <= 0:
            return None, '최종매입가가 0 으로 나왔습니다'
        tpl = policy_as_template(session, int(policy_id))
        if tpl is None:
            return None, '그 정책은 판매가를 하나도 정하지 않았습니다'
        got = compute_market_price(tpl, 'ss', 'sourcing', cost)
        price = int(getattr(got, 'final_price', 0) or 0)
        if price <= 0:
            return None, '계산 결과가 0 원입니다'
        return price, None
    except Exception as e:     # noqa: BLE001 — 값은 안 만들되 **왜인지는 말한다**
        return None, f'가격 계산 중 오류: {str(e)[:120]}'


@bp.post('/api/search-filters/<int:filter_id>/build')
def build_from_filter(filter_id: int):
    """「상품 만들기」 — 찾은 주소를 **갈 수 있는 데까지** 밀어 준다.

    ━━ 한 단추가 두 걸음을 겸한다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        ① 아직 크롤 대상이 아닌 주소 → `SourceProduct` 로 등록(크롤 대기)
        ② 이미 크롤이 끝난 주소      → 초안(`ProductDraft`) 생성
    크롤 자체는 이 사이에서 **로컬 PC 확장**이 한다(크롤=로컬 원칙). 그래서 한 번
    눌러 끝나지 않는다 — 크롤이 돌고 나서 한 번 더 누르면 그만큼 초안이 는다.

    🔴 **자동으로 하지 않는다.** 검색 한 번에 수백~수천 주소가 들어오는데 찾자마자
      크롤 대기에 넣으면 사장님 모르는 사이 크롤 부하가 몇 배가 된다(「거를 말」 같은
      수집 시점 필터가 아직 안 먹는 상태라 더 그렇다). 사람이 눌러야 들어간다.

    ★ **재구현 금지** — 등록은 `sources.service.upsert_source_product`,
      초안은 `draft_from_crawl.build_draft_from_source` 를 그대로 쓴다.

    returns: {ok, queued, waiting, drafted, done, failed:[{url,error}]}
      queued  = 이번에 크롤 대기에 새로 넣은 수
      waiting = 대기에는 있으나 아직 크롤 전
      drafted = 이번에 초안이 된 수
      done    = 이미 초안이 있던 수
    """
    from lemouton.registration.models import (
            ProductDraft, SearchFilter, SearchFilterItem)
    from lemouton.registration import draft_from_crawl as DFC
    from lemouton.sources import service as SS
    from lemouton.sources.models import SourceProduct

    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=filter_id).first()
        if f is None or f.deleted_at is not None:
            return _err('검색필터를 찾을 수 없습니다.', 404)

        items = s.query(SearchFilterItem).filter_by(filter_id=filter_id).all()
        if not items:
            return jsonify({'ok': True, 'queued': 0, 'waiting': 0, 'drafted': 0,
                            'done': 0, 'failed': [], 'priced': 0, 'unpriced': 0,
                            'unpriced_reasons': [],
                            'message': '찾은 주소가 없습니다 — 먼저 「지금 수집」을 눌러 주세요.'})

        queued = waiting = drafted = done = 0
        priced = unpriced = 0   # 판매가를 정한 것 / 못 정한 것
        unpriced_reasons = []   # 못 정한 사유(같은 사유는 한 번만)
        failed = []
        for it in items:
            url = it.product_url
            sp = (s.query(SourceProduct)
                  .filter(SourceProduct.site == f.source_key,
                          SourceProduct.url == url,
                          SourceProduct.deleted_at.is_(None)).first())
            if sp is None:
                # ① 크롤 대기에 넣는다. 값은 비운 채로 — 크롤이 채운다(지어내지 않는다).
                SS.upsert_source_product(s, site=f.source_key, url=url)
                queued += 1
                continue
            if DFC.find_existing_draft(s, sp) is not None:
                done += 1
                continue
            # ★ 「크롤이 끝났다」의 증거는 `last_status=='ok'` 하나뿐이다.
            #   행이 있다고 크롤된 게 아니다 — 방금 우리가 만든 빈 행일 수 있다.
            #   빈 행으로 초안을 만들면 값이 텅 빈 상품이 조용히 생긴다.
            if (sp.last_status or '') != 'ok':
                waiting += 1
                continue
            try:
                # 🔴 판매가는 **초안을 만들 때** 넣는다. 나중에 채우려면 「어떤 초안이
                #   판매가가 없나」를 또 찾아야 하고, 그 사이 사람이 손으로 넣은 값을
                #   덮을 위험이 생긴다.
                # 🔴 가격을 못 정한 것이 **초안 만들기를 막으면 안 된다.**
                #   상품은 만들어 두고 판매가만 비운다 — 사장님이 나중에 채우면 된다.
                #   여기서 예외가 새어 나가면 초안 자체가 안 생겨 「찾았는데 아무것도
                #   없다」가 된다(시험이 이 실수를 잡았다).
                try:
                    price, why = compute_price_for(s, sp, f.apply_policy_id)
                except Exception as e:      # noqa: BLE001
                    price, why = None, f'가격 계산 중 오류: {str(e)[:120]}'
                d = DFC.build_draft_from_source(s, sp, sale_price=price)
                d.search_filter_id = filter_id   # 성적표(수집→생존→매출)의 연결고리
                s.flush()
                drafted += 1
                if price:
                    priced += 1
                else:
                    unpriced += 1
                    if why and why not in unpriced_reasons:
                        unpriced_reasons.append(why)
            except DFC.DraftLocked:
                done += 1
            except Exception as e:               # noqa: BLE001
                # 🔴 한 건이 실패해도 나머지를 멈추지 않는다. 대신 조용히 넘기지도 않는다.
                failed.append({'url': url, 'error': str(e)[:200]})
        # 🔴 크롤 자동 실행이 꺼져 있으면 대기에 넣어봐야 **영영 처리되지 않는다.**
        #   그 상태로 「조금 뒤 한 번 더 누르면 늘어납니다」라고 안내하면 거짓말이다
        #   (2026-08-07 라이브에서 실제로 겪음 — 30개를 넣었는데 크롤이 꺼져 있었다).
        #   「대기에 넣었다」와 「그게 언젠가 처리된다」는 다른 사실이라 따로 말한다.
        from lemouton.pricing.settings import get_or_init
        crawl_on = bool(get_or_init(s).crawl_auto_enabled)
        s.commit()
        return jsonify({'ok': True, 'queued': queued, 'waiting': waiting,
                        'drafted': drafted, 'done': done, 'failed': failed,
                        'priced': priced, 'unpriced': unpriced,
                        'unpriced_reasons': unpriced_reasons,
                        'crawl_enabled': crawl_on})
    finally:
        s.close()


@bp.delete('/api/search-filters/<int:filter_id>')
def delete_search_filter(filter_id: int):
    """🔴 **소프트 삭제만.** 이 필터로 찾은 상품은 절대 건드리지 않는다.

    더망고는 필터를 지우면 그 상품이 전부 삭제된다. 수집은 다시 하면 되지만
    **이미 마켓에 올라간 상품과의 연결**은 되살릴 수 없다.
    """
    from lemouton.registration.models import SearchFilter
    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=filter_id).first()
        if f is None:
            return _err('검색필터를 찾을 수 없습니다.', 404)
        f.deleted_at = _now()
        s.commit()
        return jsonify({'ok': True})
    finally:
        s.close()

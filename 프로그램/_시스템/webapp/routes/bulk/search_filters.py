# -*- coding: utf-8 -*-
"""검색필터 — 「검색형 URL 한 줄 = 수집 행위 하나」의 CRUD + 「지금 수집」.

대량등록은 모음전과 근본이 다르다. 모음전은 옵션별 URL 을 사람이 하나씩 넣고
소싱처를 **비교**하지만, 대량등록은 검색 결과 한 줄로 수십~수천 상품을 자동 수집한다.
그 한 줄을 개체로 만든 것이 `SearchFilter` 다(설계서 §3-1).

🔴 **훑는 일은 서버가 하지 않는다.** 페이지를 여는 건 로컬 PC 의 크롬 확장이다
  (「크롤은 로컬 PC」 원칙). 서버는 ①무엇을 훑을지 알려주고 ②결과를 받는다.
  이 두 라우트는 `webapp/routes/api.py` 쪽에 있다(확장이 부르는 곳과 같은 자리).
"""
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from shared.db import SessionLocal

from . import bp


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _err(msg, code=400):
    return jsonify({'ok': False, 'message': msg}), code


#: 화면에 보여줄 소싱처 이름. 없으면 키를 그대로 쓴다(지어내지 않는다).
_SOURCE_LABEL = {'musinsa': '무신사'}

_EXT_VER_CACHE = {}


def _manifest_path():
    """확장 manifest 의 자리. **시험이 다른 파일로 바꿔 끼울 수 있게** 따로 뺐다."""
    from pathlib import Path
    return (Path(__file__).resolve().parents[3]
            / 'extension' / 'moum-crawler' / 'manifest.json')


def expected_ext_version():
    """저장소에 있는 **확장의 최신 판 번호.** 못 읽으면 None.

    🔴 왜 필요한가 (2026-08-13 사장님 겪음)
      화면은 「확장 0.7.94」라고만 보여 줬다. 그게 **낡은 판인지 최신인지**를
      알 방법이 없어서, 사장님이 `chrome://extensions` 에서 ↻ 를 눌러도
      아무 일이 없는 헛걸음을 했다.
      (그때 로드 폴더가 이미 최신과 같아서 누를 것이 없었다.)

    ★ 이 값이 `last_ext_version` 보다 **새 것일 때만** 화면이 「새 판 있음」이라
      말한다(`ext_version_outdated`). 늘 뜨는 경고는 아무 말도 안 하는 것과 같다.

    🔴🔴 [2026-08-13 라이브 실측] 캐시에 **만료가 없어서** 배포한 뒤에도 옛 값을
      말했다. main 의 manifest 는 0.8.03 이고 배포도 success 인데 라이브 API 는
      워커 6개 전부 0.8.02 를 「최신」이라 답했다 — 프로세스가 살아 있는 한
      한 번 읽은 값을 영원히 붙들고 있었기 때문이다.
      → **파일이 바뀌면 다시 읽는다**(수정시각+크기를 캐시 열쇠로 삼는다).
      ★ 「한 번 읽고 영원히 기억한다」는 배포가 있는 곳에선 거짓말이 된다.
    """
    import json
    p = None
    key = None
    try:
        p = _manifest_path()
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except Exception:       # noqa: BLE001 — 파일이 없어도 화면은 떠야 한다
        key = None
    if key is not None and key in _EXT_VER_CACHE:
        return _EXT_VER_CACHE[key]
    v = None
    try:
        v = (json.loads(p.read_text(encoding='utf-8')) or {}).get('version') or None
    except Exception:       # noqa: BLE001 — 못 읽어도 화면은 떠야 한다
        v = None
    if key is not None:
        # 열쇠가 바뀌면 옛 항목은 쓸모가 없다 — 무한히 쌓이지 않게 갈아 끼운다.
        _EXT_VER_CACHE.clear()
        _EXT_VER_CACHE[key] = v
    return v


def _ver_tuple(v):
    """`"0.8.10"` → `(0, 8, 10)`. 숫자로 못 읽으면 None.

    🔴 **글자로 견주면 안 된다** — `"0.8.9" > "0.8.10"` 이 참이 된다(9 > 1).
    """
    parts = str(v or '').strip().split('.')
    if not parts or not all(x.isdigit() for x in parts):
        return None
    return tuple(int(x) for x in parts)


def ext_version_outdated(loaded, expected):
    """**지금 켜져 있는 확장이 저장소보다 낡았나.** 낡았을 때만 True.

    🔴 왜 서버가 판정하나 (2026-08-13 라이브)
      화면이 `expected !== loaded` 로 견줬다. 그래서 확장이 **더 새 판**일 때도
      「확장 0.8.03 · 새 판 0.8.02 있음」이라 떠서, 누를 것이 없는데 사장님더러
      `chrome://extensions` 에서 ↻ 를 누르라고 했다.
      ★ 견주는 법을 아는 곳은 **한 곳**이어야 한다. 화면·서버 두 곳이 각자
        견주면 언젠가 서로 다른 답을 낸다.

    ★ 모르면 겁주지 않는다 — 한 번도 안 돈 필터(`loaded` 없음)나 manifest 를
      못 읽은 경우(`expected` 없음)는 **False**. 「모른다」와 「낡았다」는 다르다.
    """
    if not loaded or not expected:
        return False
    a, b = _ver_tuple(loaded), _ver_tuple(expected)
    if a is None or b is None:
        # 숫자로 못 읽는 판 번호 — 그래도 다르면 알려는 준다(옛 방식으로 물러섬).
        return str(loaded) != str(expected)
    return b > a


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
        # 🔴 「못 봤다」와 「더 있는데 멈췄다」 — 둘 다 0건과 다른 사실이다.
        'last_error': getattr(f, 'last_error', None) or None,
        'last_capped': bool(getattr(f, 'last_capped', False)),
        'last_ext_version': getattr(f, 'last_ext_version', None) or None,
        # 「이어서 걷는 중」 — 다음 회차가 시작할 쪽. None = 처음부터.
        #   🔴 이 값을 화면이 모르면 사장님은 「또 눌러야 하나」를 알 수 없다.
        'next_page_from': getattr(f, 'next_page_from', None) or None,
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
            # 「지금 최신 판」 — 화면이 「낡았다/최신이다」를 스스로 말할 수 있게.
            #   🔴 견주는 일까지 서버가 한다. 화면이 글자로 견주다 확장이 더 새
            #     판일 때 거짓 경보를 냈다(2026-08-13 라이브).
            _exp = expected_ext_version()
            d['ext_version_expected'] = _exp
            d['ext_version_outdated'] = ext_version_outdated(
                d.get('last_ext_version'), _exp)
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


#: 「찾은 주소 보기」가 한 번에 내려주는 최대 건수.
#: 🔴 수천 건을 한 번에 내리면 화면이 멎는다. **자른 사실은 `total` 로 말한다** —
#:   조용히 자르면 「31건 찾았다는데 목록엔 20개뿐」이 되어 사장님이 못 믿게 된다.
ITEMS_LIMIT_DEFAULT = 200
ITEMS_LIMIT_MAX = 1000


@bp.get('/api/search-filters/<int:filter_id>/items')
def list_filter_items(filter_id: int):
    """이 필터가 **무엇을** 찾았나 — 주소 목록.

    ━━ 왜 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    화면은 「찾음 31」이라고만 말했다. **무엇을 31개 찾았는지 볼 방법이 없었다.**
    검색어가 엉뚱해 잡화가 딸려 와도 상품을 만들어 보기 전엔 모른다 —
    수백~수천 건이면 그때 되돌리는 값이 크다.

    ★ 주소마다 **어디까지 왔는지**도 같이 말한다. 주소만 보여주면
      「왜 상품이 안 생기지」를 여전히 못 푼다.
        crawled — 크롤이 끝났나(증거는 `last_status=='ok'` 하나뿐. 행이 있다고
                  크롤된 게 아니다 — 방금 우리가 만든 빈 행일 수 있다)
        drafted — 상품(초안)이 됐나

    returns: {ok, total, items:[{product_url, first_seen_at, crawled, drafted}]}
      total = **자르기 전** 전체 수(자른 것을 숨기지 않는다)
    """
    from lemouton.registration.models import (
        ProductDraft, SearchFilter, SearchFilterItem)
    from lemouton.sources.models import SourceProduct

    try:
        limit = int(request.args.get('limit') or ITEMS_LIMIT_DEFAULT)
    except (TypeError, ValueError):
        limit = ITEMS_LIMIT_DEFAULT
    limit = max(1, min(limit, ITEMS_LIMIT_MAX))

    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=filter_id).first()
        if f is None or f.deleted_at is not None:
            return _err('검색필터를 찾을 수 없습니다.', 404)

        total = s.query(SearchFilterItem).filter_by(filter_id=filter_id).count()
        rows = (s.query(SearchFilterItem)
                .filter_by(filter_id=filter_id)
                .order_by(SearchFilterItem.id).limit(limit).all())
        urls = [r.product_url for r in rows]

        # 크롤됨 — 「행이 있다」가 아니라 「last_status=='ok'」가 증거다.
        crawled = set()
        drafted = set()
        for i in range(0, len(urls), 900):          # IN 절 상한을 넘기지 않는다
            chunk = urls[i:i + 900]
            for (u,) in (s.query(SourceProduct.url)
                         .filter(SourceProduct.site == f.source_key,
                                 SourceProduct.url.in_(chunk),
                                 SourceProduct.last_status == 'ok',
                                 SourceProduct.deleted_at.is_(None)).all()):
                crawled.add(u)
            for (u,) in (s.query(ProductDraft.source_url)
                         .filter(ProductDraft.source_url.in_(chunk),
                                 ProductDraft.deleted_at.is_(None)).all()):
                drafted.add(u)

        items = [{'product_url': r.product_url,
                  'first_seen_at': r.first_seen_at.isoformat() if r.first_seen_at else None,
                  'crawled': r.product_url in crawled,
                  'drafted': r.product_url in drafted}
                 for r in rows]
        return jsonify({'ok': True, 'total': total, 'items': items,
                        'limit': limit})
    finally:
        s.close()


#: 성적표가 매출을 볼 기간(일). 전 기간을 훑으면 주문라인 전수 조회가 되어 느리다.
SCORECARD_DAYS = 90


@bp.get('/api/search-filters/<int:filter_id>/scorecard')
def filter_scorecard(filter_id: int):
    """필터 성적표 — 「수집 → 상품 → 등록 → 매출」.

    ━━ 왜 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    더망고에서 본 것 — 검색필터 12개 중 **돈이 된 건 3개**였다. 나머지 9개는 수천 개를
    긁어 올리고 관리비만 먹었다. 어느 필터가 그 3개인지 모르면 계속 다 돌린다.

    ━━ 지키는 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🔴 매출 기준은 `정산예정금(배송비포함)` — `orders/fulfillment.SETTLE_FIELD` 를
      **그대로** 쓴다. 수수료율로 되계산하면 「에러 없이 틀린 숫자」가 된다.
    🔴 **금액을 못 읽은 주문을 0 원으로 세지 않는다.** 0 으로 뭉개면 「안 팔렸다」와
      「팔렸는데 금액을 모른다」가 같아져, 잘 되는 필터를 꺼 버릴 수 있다.
      → `sales_unknown_lines` 로 따로 센다.
    🔴 마켓 상품번호를 뽑는 규칙은 `orders.price_diff` 가 이미 안다 — 여기서 다시
      만들지 않는다(두 화면이 다른 답을 내면 이 저장소에선 곧 금전 사고다).

    returns: {ok, found, drafted, registered, order_lines, sales,
              sales_unknown_lines, window_days}
    """
    from lemouton.markets.models_orders import MarketOrderLine
    from lemouton.orders.fulfillment import SETTLE_FIELD, _to_int
    from lemouton.orders.price_diff import _row_market_ids
    from lemouton.registration.models import (
        ProductDraft, ProductDraftMarket, SearchFilter, SearchFilterItem)

    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=filter_id).first()
        if f is None or f.deleted_at is not None:
            return _err('검색필터를 찾을 수 없습니다.', 404)

        found = s.query(SearchFilterItem).filter_by(filter_id=filter_id).count()
        draft_ids = [r.id for r in s.query(ProductDraft.id)
                     .filter(ProductDraft.search_filter_id == filter_id,
                             ProductDraft.deleted_at.is_(None)).all()]
        # 「만들었다」와 「마켓에 올라갔다」는 다른 사실이다 — 올라간 증거는
        # status=='ok' 이면서 마켓이 준 상품번호가 있는 것 하나뿐이다.
        pids, reg_drafts = set(), set()
        if draft_ids:
            for r in (s.query(ProductDraftMarket)
                      .filter(ProductDraftMarket.draft_id.in_(draft_ids),
                              ProductDraftMarket.status == 'ok',
                              ProductDraftMarket.market_product_id.isnot(None))
                      .all()):
                pids.add(str(r.market_product_id).strip())
                reg_drafts.add(r.draft_id)

        lines = sales = unknown = 0
        if pids:
            since = (_now() - timedelta(days=SCORECARD_DAYS)).strftime('%Y-%m-%d')
            for ol in (s.query(MarketOrderLine)
                       .filter(MarketOrderLine.order_date >= since).all()):
                row = ol.row if isinstance(ol.row, dict) else {}
                _oid, got = _row_market_ids(row)
                if not (set(got) & pids):
                    continue
                lines += 1
                amount = _to_int(row.get(SETTLE_FIELD))
                if amount is None:
                    unknown += 1        # 🔴 0 원으로 세지 않는다
                else:
                    sales += amount

        return jsonify({'ok': True, 'found': found, 'drafted': len(draft_ids),
                        'registered': len(reg_drafts), 'order_lines': lines,
                        'sales': sales, 'sales_unknown_lines': unknown,
                        'window_days': SCORECARD_DAYS})
    finally:
        s.close()


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
        excluded_options = 0    # 「뺄 옵션」에 걸려 안 담은 옵션 수
        # 🔴 [2026-08-08] 이 칸은 저장·표시만 되고 **아무 데서도 읽히지 않았다.**
        #   사장님은 「샘플」이라 적고 걸러진 줄 알지만 그대로 다 들어왔다.
        ex_words = DFC.parse_exclude_words(f.option_exclude_words)
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
                d = DFC.build_draft_from_source(s, sp, sale_price=price,
                                                exclude_words=ex_words)
                excluded_options += int(getattr(d, '_excluded_options', 0) or 0)
                d.search_filter_id = filter_id   # 성적표(수집→생존→매출)의 연결고리
                s.flush()
                drafted += 1
                if price:
                    priced += 1
                else:
                    unpriced += 1
                    if why and why not in unpriced_reasons:
                        unpriced_reasons.append(why)
            except DFC.AllOptionsExcluded as e:
                # 🔴 「뺄 옵션」에 전부 걸렸다 — 안 만드는 게 맞지만 **조용히 넘기지
                #   않는다.** 사장님은 「왜 상품이 안 생기지」를 영영 못 푼다.
                failed.append({'url': url, 'error': str(e)[:200]})
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
                        'excluded_options': excluded_options,
                        'crawl_enabled': crawl_on})
    finally:
        s.close()


#: 고칠 수 있는 칸 — (payload 키, 모델 칸, 다듬는 함수).
#:   🔴 여기 없는 칸은 못 고친다. 「무엇이든 받아 그대로 넣기」로 만들면
#:     남이 보낸 아무 키나 모델에 꽂히게 된다.
def _clean_int(v):
    v = None if v in ('', None) else int(v)
    return v if (v is None or v > 0) else None


_EDITABLE = (
    ('name', 'name', lambda v: (str(v or '').strip() or None)),
    ('max_items', 'max_items', _clean_int),
    ('page_from', 'page_from', _clean_int),
    ('page_to', 'page_to', _clean_int),
    ('option_exclude_words', 'option_exclude_words',
     lambda v: (str(v or '').strip() or None)),
    ('apply_policy_id', 'apply_policy_id', _clean_int),
)


@bp.patch('/api/search-filters/<int:filter_id>')
def edit_search_filter(filter_id: int):
    """검색필터 고치기 — 특히 **가격 정책을 나중에 붙이기**.

    ━━ 왜 필요한가 (라이브에서 드러남) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    만들기·실행·상품만들기·지우기는 있는데 **고치기가 없었다.** 그래서 이미 만든
    필터에 정책을 붙이려면 지우고 다시 만드는 수밖에 없었는데, 그러면
    **찾아 둔 주소를 다시 훑어야 한다**(라이브 필터는 이미 30개를 찾아 뒀다).
    소싱처를 또 두들기는 것이기도 하다.

    정책·상한·페이지 범위는 「처음에 정하고 끝」이 아니라 **해 보고 바꾸는 값**이다.

    🔴 **안 보낸 칸은 안 건드린다.** 일부만 고치려다 나머지가 비워지면
      조용한 데이터 손실이다. `payload 에 그 키가 있을 때만` 바꾼다.

    🔴 **소싱처와 검색 주소는 못 고친다.** 그걸 바꾸면 이미 찾아 둔 주소가
      「어디서 왔는지」와 어긋난다 — 그건 새 필터를 만드는 것이 맞다.
    """
    from lemouton.registration.models import SearchFilter
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=filter_id).first()
        if f is None or f.deleted_at is not None:
            return _err('검색필터를 찾을 수 없습니다.', 404)
        changed = []
        for key, col, clean in _EDITABLE:
            if key not in body:
                continue           # 안 보낸 칸은 그대로 둔다
            try:
                setattr(f, col, clean(body[key]))
            except (TypeError, ValueError):
                return _err(f'「{key}」 값이 숫자가 아닙니다.')
            changed.append(key)
        if not changed:
            return _err('고칠 값이 없습니다.')
        s.commit()
        return jsonify({'ok': True, 'filter': _row(f), 'changed': changed})
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

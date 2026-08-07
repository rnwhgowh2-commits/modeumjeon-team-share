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
    }


@bp.get('/api/search-filters')
def list_search_filters():
    from lemouton.registration.models import SearchFilter, SearchFilterItem
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

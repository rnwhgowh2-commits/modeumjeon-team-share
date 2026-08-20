# -*- coding: utf-8 -*-
"""검색필터(상품군) 목록에 카테고리 자동 맵핑 현황이 실려 나가는가 (#1060).

집계 로직 자체(경로 단위 확정/제안대기/없음)는
tests/registration/test_category_suggest.py 가 이미 전수 검증한다 — 여기서는
**목록 API 가 그 결과를 실제로 실어 보내는지**만 심어 놓고 본다.

🔴 공유 Supabase 를 쓴다 — 만든 것은 반드시 finally 에서 지운다
   (test_ext_version_staleness.py 와 같은 패턴).
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('client')

COLLECT = (Path(__file__).resolve().parents[2]
          / 'webapp' / 'templates' / 'bulk' / 'partials' / '_collect.html')


def test_수집탭_화면에_카테고리_맵핑_열이_있다():
    html = COLLECT.read_text(encoding='utf-8')
    assert 'catmapCell(f)' in html, '표 줄에 카테고리 맵핑 칸을 안 그립니다.'
    assert 'data-catmap=' in html, '「지금 다시 맞추기」 버튼이 없습니다.'
    assert "fetch('/bulk/api/catmap/suggest/'" in html, (
        '이미 있는 소싱처 단위 자동 제안 API 를 재사용하지 않습니다.'
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _make_filter(client, keyword):
    made = client.post('/bulk/api/search-filters', json=dict(
        source_key='musinsa',
        listing_url=f'https://www.musinsa.com/search/goods?keyword={keyword}'))
    assert made.status_code == 200, made.get_data(as_text=True)
    return made.get_json()['filter']['id']


def _cleanup_filter(fid, draft_ids=(), catmap_ids=()):
    from shared.db import SessionLocal
    from lemouton.registration.models import CategoryMapRow, ProductDraft, SearchFilter
    s = SessionLocal()
    try:
        for cid in catmap_ids:
            row = s.query(CategoryMapRow).filter_by(id=cid).first()
            if row is not None:
                s.delete(row)
        for did in draft_ids:
            row = s.query(ProductDraft).filter_by(id=did).first()
            if row is not None:
                s.delete(row)
        row = s.query(SearchFilter).filter_by(id=fid).first()
        if row is not None:
            s.delete(row)
        s.commit()
    finally:
        s.close()


def _row_of(client, fid):
    r = client.get('/bulk/api/search-filters')
    rows = [x for x in (r.get_json().get('filters') or []) if x['id'] == fid]
    assert rows, '방금 만든 상품군이 목록에 없습니다.'
    return rows[0]


def test_상품이_없는_상품군은_카테고리_맵핑이_전부_0이다(client):
    fid = _make_filter(client, '카테고리맵핑빈상품군')
    try:
        row = _row_of(client, fid)
        assert 'catmap' in row, '목록에 카테고리 맵핑 현황이 없습니다.'
        assert row['catmap'] == {'total': 0, 'confirmed': 0, 'suggested_only': 0, 'none': 0}
    finally:
        _cleanup_filter(fid)


def test_확정된_카테고리가_있으면_목록에_그대로_실린다(client):
    from shared.db import SessionLocal
    from lemouton.registration.models import CategoryMapRow, ProductDraft

    fid = _make_filter(client, '카테고리맵핑확정상품군')
    s = SessionLocal()
    try:
        d = ProductDraft(name='나이키 에어포스1', sale_price=139000,
                         search_filter_id=fid, source_site='musinsa',
                         source_category_path='신발>스니커즈>여성운동화')
        s.add(d)
        s.commit()
        did = d.id
        row = CategoryMapRow(source_id='musinsa', source_path='신발>스니커즈>여성운동화',
                             market='coupang', market_cat_code='TEST_CODE',
                             status='confirmed')
        s.add(row)
        s.commit()
        cid = row.id
    finally:
        s.close()
    try:
        got = _row_of(client, fid)['catmap']
        assert got == {'total': 1, 'confirmed': 1, 'suggested_only': 0, 'none': 0}
    finally:
        _cleanup_filter(fid, draft_ids=[did], catmap_ids=[cid])

# -*- coding: utf-8 -*-
"""POST /bulk/api/drafts/from-url — 소싱처 URL → 등록 초안.

가장 중요한 고정: **이 라우트는 소싱처에 접속하지 않는다.** 크롤은 로컬 PC 몫이고
(CLAUDE.md 데이터 정합성 원칙 3) 서버가 소싱처를 긁으면 설계가 무너진다. 크롤 결과가
없으면 조용히 빈 초안을 만들지 말고 404 로 "먼저 크롤이 돌아야 합니다" 라고 말해야 한다.
"""
import json
import uuid

import pytest

from lemouton.registration.models import ProductDraft
from lemouton.sources.models import SourceOption, SourceProduct


@pytest.fixture
def client(monkeypatch):
    # 이 저장소의 라우트 테스트 관례 (tests/registration/test_drafts_route.py:11-20)
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("LIVE_REGISTER_ARMED", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _seed(url, *, site='musinsa', options=(), **over):
    """크롤이 이미 저장해 둔 상태를 만든다 (라우트는 이걸 읽기만 한다)."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        body = dict(site=site, url=url, product_name='크롤 스니커즈',
                    last_price=89000, last_stock=5,
                    category_path='신발>스니커즈>여성운동화',
                    images_json=json.dumps(['https://img/1.jpg']),
                    detail_html='<p>상세</p>')
        body.update(over)
        sp = SourceProduct(**body)
        s.add(sp)
        s.flush()
        for o in options:
            s.add(SourceOption(source_product_id=sp.id, **o))
        s.commit()
        return sp.id
    finally:
        s.close()


def _uniq_url():
    return f'https://www.musinsa.com/products/{uuid.uuid4().hex[:10]}'


def _draft(draft_id):
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        return s.query(ProductDraft).filter_by(id=draft_id).first()
    finally:
        s.close()


# ── ★ 크롤을 트리거하지 않는다 ──────────────────────────────────────────────

def test_크롤_결과가_없으면_404_이고_소싱처에_접속하지_않는다(client, monkeypatch):
    calls = []

    def _boom(*a, **kw):
        calls.append(a)
        raise AssertionError('초안 생성이 소싱처에 접속했습니다 — 절대 금지 (크롤=로컬 PC)')

    import requests
    monkeypatch.setattr(requests.Session, 'request', _boom)
    monkeypatch.setattr(requests, 'request', _boom)

    r = client.post('/bulk/api/drafts/from-url', json={'url': _uniq_url()})
    assert r.status_code == 404
    body = r.get_json()
    assert body['ok'] is False
    assert '먼저 크롤이 돌아야' in body['error']
    assert body['code'] == 'NOT_CRAWLED'
    assert calls == []


# ── 정상 흐름 ───────────────────────────────────────────────────────────────

def test_URL_한_건이_초안이_되고_부족한_것까지_알려준다(client):
    url = _uniq_url()
    _seed(url, options=[
        {'color_text': '블랙', 'size_text': '230', 'current_stock': 3, 'current_price': 89000},
        {'color_text': '블랙', 'size_text': '240', 'current_stock': 0, 'current_price': 89000},
    ])
    r = client.post('/bulk/api/drafts/from-url', json={'url': url})
    assert r.status_code == 200
    b = r.get_json()
    assert b['ok'] is True and b['created'] is True

    d = _draft(b['draft_id'])
    assert d.source == 'crawl' and d.source_site == 'musinsa'
    assert d.source_url == url
    assert d.source_category_path == '신발>스니커즈>여성운동화'
    assert d.sale_price == 0            # 매입가 89,000 이 새어나오지 않았다

    assert b['filled']['options'] == 2
    assert b['filled']['sellable_options'] == 1
    # 6마켓 전부 「무엇이 부족한지」가 온다 — preflight 와 같은 판정기.
    assert {row['market'] for row in b['missing']} == {
        'smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'}
    assert all(row['status'] != 'ready' for row in b['missing'])
    assert any('판매가' in row['reason'] for row in b['missing'])


def test_원문_URL_붙여넣기도_같은_초안을_찾는다(client):
    url = _uniq_url()
    _seed(url)
    first = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()
    again = client.post('/bulk/api/drafts/from-url',
                        json={'url': url + '?utm_source=naver&NaPm=z'}).get_json()
    assert again['draft_id'] == first['draft_id']
    assert again['created'] is False


def test_복수_URL_은_행마다_성패를_돌려준다(client):
    good = _uniq_url()
    _seed(good)
    bad = _uniq_url()
    r = client.post('/bulk/api/drafts/from-url', json={'urls': [good, bad]})
    assert r.status_code == 200
    b = r.get_json()
    assert b['made'] == 1
    by_url = {row['url']: row for row in b['rows']}
    assert by_url[good]['ok'] is True
    assert by_url[bad]['ok'] is False and by_url[bad]['code'] == 'NOT_CRAWLED'


def test_판매가를_주면_그_값으로_들어간다(client):
    url = _uniq_url()
    _seed(url)
    b = client.post('/bulk/api/drafts/from-url',
                    json={'url': url, 'sale_price': '159,000'}).get_json()
    assert _draft(b['draft_id']).sale_price == 159000


def test_판매가_0_이하는_거부한다(client):
    url = _uniq_url()
    _seed(url)
    r = client.post('/bulk/api/drafts/from-url', json={'url': url, 'sale_price': 0})
    assert r.status_code == 400
    assert '0원 이하' in r.get_json()['error']


def test_URL_이_없으면_400(client):
    r = client.post('/bulk/api/drafts/from-url', json={})
    assert r.status_code == 400
    assert 'URL' in r.get_json()['error']


# ── [2026-07-23 리뷰 I3] 갱신이 무엇을 덮었는지 응답이 말한다 ────────────────

def test_갱신은_무엇을_덮었는지_응답에_담는다(client):
    """「기존 초안을 갱신했습니다」 한 줄로 끝내지 않는다 — 그게 조용한 실패의 근본이다."""
    from shared.db import SessionLocal
    from lemouton.sources.models import SourceProduct

    url = _uniq_url()
    _seed(url, options=[
        {'color_text': '블랙', 'size_text': '260', 'current_stock': 2}])
    first = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()

    # 사람이 추가금을 넣는다 (비싼 옵션)
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=first['draft_id']).first()
        opts = json.loads(d.options_json)
        opts[0]['extra_price'] = 30000
        opts[0]['sku'] = 'LM-260'
        d.options_json = json.dumps(opts, ensure_ascii=False)
        # 재크롤로 재고가 바뀌었다
        sp = s.query(SourceProduct).filter_by(url=url).first()
        from lemouton.sources.models import SourceOption
        s.query(SourceOption).filter_by(source_product_id=sp.id).update(
            {'current_stock': 9})
        s.commit()
    finally:
        s.close()

    again = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()
    assert again['created'] is False
    joined = ' / '.join(again['changes'])
    assert '재고변경' in joined and '2→9' in joined
    assert '추가금 1개' in joined
    # ★ 그리고 사람이 넣은 값은 실제로 살아 있어야 한다 (금전 손실 방지)
    d = _draft(again['draft_id'])
    o = json.loads(d.options_json)[0]
    assert o['extra_price'] == 30000 and o['sku'] == 'LM-260' and o['stock'] == 9


def test_새로_만든_초안은_덮은_것이_없다(client):
    url = _uniq_url()
    _seed(url)
    b = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()
    assert b['created'] is True and b['changes'] == []


# ── [리뷰 I4] 같은 URL 초안이 2벌이면 숨기지 않는다 ─────────────────────────

def test_같은_URL_초안은_2벌이_될_수_없고_되더라도_숨기지_않는다(client):
    """[리뷰 I4] 1차 방어 = 부분 유니크 인덱스(동시 요청이 2벌을 못 만든다).
    2차 방어 = 이미 중복이 있던 DB 라 인덱스가 못 걸린 경우에도 경고로 표면화."""
    from shared.db import SessionLocal

    url = _uniq_url()
    _seed(url)
    client.post('/bulk/api/drafts/from-url', json={'url': url})

    blocked = False
    s = SessionLocal()
    try:
        # 동시 요청이 만들던 유령 초안을 직접 재현한다.
        s.add(ProductDraft(origin='bulk', source='crawl', name='유령 초안',
                           sale_price=0, source_site='musinsa', source_url=url))
        try:
            s.commit()
        except Exception:      # noqa: BLE001 — IntegrityError = 인덱스가 막았다
            s.rollback()
            blocked = True
    finally:
        s.close()

    if blocked:
        return                 # 1차 방어가 작동 — 유령 초안 자체가 생기지 않는다

    again = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()
    assert any('2벌' in w for w in again['warnings']), again['warnings']

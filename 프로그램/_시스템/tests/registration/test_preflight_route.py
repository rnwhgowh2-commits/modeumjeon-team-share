# -*- coding: utf-8 -*-
"""M4-1 등록 사전 점검(드라이런) — POST /bulk/api/drafts/<id>/preflight.

이 라우트의 존재 이유는 「등록을 눌러봐야 뭐가 빈지 안다」를 없애는 것이다. 그래서
가장 중요한 고정은 **마켓 API 를 한 번도 부르지 않는다**는 것 — 점검이 라이브 호출을
동반하면 '위험 0' 이라는 전제 자체가 깨진다(속도한도·계정 정지).
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    # 이 저장소의 라우트 테스트 관례 (tests/registration/test_drafts_route.py:11-20)
    monkeypatch.setenv("DISABLE_AUTH", "1")
    # 실등록 게이트는 반드시 꺼진 상태로 (ambient 로 켜져 있으면 실호출 위험).
    monkeypatch.delenv("LIVE_REGISTER_ARMED", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _empty_draft(client, **over):
    """필수값이 거의 비어 있는 드래프트 — 마켓별 '무엇이 없는가' 를 보려는 재료."""
    body = {'name': '빈 드래프트 상품', 'sale_price': 39000}
    body.update(over)
    return client.post('/bulk/api/drafts', json=body).get_json()['draft_id']


def _rows(res):
    return {r['market']: r for r in res.get_json()['rows']}


ALL_CODES = {
    'smartstore': '50000167', 'coupang': '63955',
    'auction': '00120005002000000000/37500700',
    'gmarket': '00120005002100000000/300006243',
    'eleven11': '1011634', 'lotteon': 'LO2727500650',
}


# ── ★ 가장 중요한 고정: 마켓 클라이언트가 한 번도 안 불린다 ──────────────────

def test_preflight_는_마켓_API_를_한_번도_부르지_않는다(client, monkeypatch):
    """점검은 순수 컴파일 + 우리 DB 조회뿐 — 마켓 클라이언트 생성조차 없어야 한다.

    마켓 클라이언트 팩토리(market_fetch._xxx_client)와 게이트 뒤 실전송(send_more,
    service._send_live) 을 전부 폭탄으로 갈아끼운다. 하나라도 불리면 이 테스트가 터진다.
    ★ 이름 우회(클라이언트를 직접 만들어 부르는 경로)까지 막으려고 **HTTP 계층**
      (requests.Session.request / requests.request)도 함께 폭탄으로 만든다 — 6마켓
      클라이언트가 전부 requests 위에 올라가 있으므로 여기가 마지막 관문이다.
    """
    calls = []

    def _boom(*a, **kw):
        calls.append(a)
        raise AssertionError('점검이 마켓 API 를 불렀습니다 — 절대 금지')

    import requests
    monkeypatch.setattr(requests.Session, 'request', _boom)
    monkeypatch.setattr(requests, 'request', _boom)
    import lemouton.uploader.market_fetch as MF
    for name in ('_smartstore_client', '_coupang_client', '_esm_client',
                 '_eleven11_client', '_lotteon_client'):
        monkeypatch.setattr(MF, name, _boom, raising=False)
    import lemouton.registration.send_more as SM
    monkeypatch.setattr(SM, 'register_live', _boom)
    import lemouton.registration.service as SVC
    monkeypatch.setattr(SVC, '_send_live', _boom)

    did = _empty_draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'category_codes': ALL_CODES})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['ok'] is True
    assert calls == [], '마켓 API 가 불렸습니다'


# ── 빈 드래프트 → 마켓별 사유가 정확히 나온다 ────────────────────────────────

def test_빈_드래프트_스스는_고시와_AS_를_사유로_말한다(client):
    did = _empty_draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    row = _rows(r)['smartstore']
    assert row['status'] == 'missing', row
    # 고시(상품고시정보) 가 먼저 걸린다 — 그 다음이 A/S. 어느 쪽이든 원문이 그대로 온다.
    assert ('고시' in row['reason']) or ('A/S' in row['reason']), row['reason']


def test_빈_드래프트_스스_고시만_채우면_AS_전화번호를_말한다(client):
    """사유가 '첫 실패 하나' 라는 사실을 고정 — 고시를 채우면 다음 빈 칸이 드러난다."""
    did = _empty_draft(client, notice_type='WEAR', notice={
        'material': '면 100%', 'color': '블랙', 'size': 'M',
        'manufacturer': '테스트제조', 'caution': '단독세탁',
        'warranty_policy': '1년', 'after_service_director': '홍길동',
    })
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    row = _rows(r)['smartstore']
    assert row['status'] == 'missing'
    assert 'A/S 전화번호' in row['reason'], row['reason']


def test_빈_드래프트_4마켓은_재고_상세HTML_등을_사유로_말한다(client):
    """옥션·G마켓·11번가·롯데온은 재고 0 등록이 안 된다 — 그 사실이 사유에 그대로 나온다."""
    did = _empty_draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['auction', 'gmarket', 'eleven11', 'lotteon'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    for market in ('auction', 'gmarket', 'eleven11', 'lotteon'):
        assert rows[market]['status'] == 'missing', rows[market]
        assert '재고' in rows[market]['reason'], rows[market]


def test_4마켓_10원단위_아닌_판매가는_사유로_나온다(client):
    did = _empty_draft(client, sale_price=39001, stock_quantity=5)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['auction'], 'category_codes': ALL_CODES})
    row = _rows(r)['auction']
    assert row['status'] == 'missing'
    assert '10원 단위' in row['reason'], row['reason']


def test_4마켓_재고와_판매가만_있으면_상세HTML_을_말한다(client):
    did = _empty_draft(client, stock_quantity=5,
                       images=['https://example.com/a.jpg'])
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    row = _rows(r)['eleven11']
    assert row['status'] == 'missing'
    assert '상세설명' in row['reason'], row['reason']


def test_쿠팡은_vendor_없으면_vendorId_를_사유로_말한다(client):
    did = _empty_draft(client, stock_quantity=5,
                       images=['https://example.com/a.jpg'])
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['coupang'], 'category_codes': ALL_CODES})
    row = _rows(r)['coupang']
    assert row['status'] == 'missing'
    assert 'vendorId' in row['reason'], row['reason']


# ── ready — 필수값이 다 차면 초록, 그래도 주의는 남는다 ──────────────────────

def _complete_draft_body():
    """스스 예비 컴파일(require_cdn_images=False)과 4마켓 컴파일을 모두 통과하는 드래프트."""
    return {
        'name': '테스트 자켓', 'brand': '테스트브랜드', 'sale_price': 39000,
        'stock_quantity': 7,
        'notice_type': 'WEAR',
        'notice': {
            'material': '면 100%', 'color': '블랙', 'size': 'M / L',
            'manufacturer': '테스트제조', 'caution': '단독세탁',
            'warranty_policy': '구매일로부터 1년',
            'after_service_director': '홍길동 010-1234-5678',
        },
        'images': ['https://example.com/main.jpg'],
        'detail_html': '<p>상세</p>',
        'delivery_fee': '3000', 'return_fee': '5000',
        'after_service_phone': '010-1234-5678',
        'after_service_guide': '평일 09-18시',
    }


def test_완결된_드래프트는_ready_지만_caveats_가_반드시_붙는다(client):
    """거짓 ready 금지 — 예비 컴파일 통과가 곧 등록 성공이 아니라는 사실을 실어 보낸다."""
    did = client.post('/bulk/api/drafts',
                      json=_complete_draft_body()).get_json()['draft_id']
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore', 'auction', 'eleven11', 'lotteon'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    for market in ('smartstore', 'auction', 'eleven11', 'lotteon'):
        assert rows[market]['status'] == 'ready', rows[market]
        assert rows[market]['caveats'], f'{market}: caveats 가 비었다 — 거짓 ready'
    assert 'CDN' in ' '.join(rows['smartstore']['caveats'])
    assert 'ESM표준코드' in ' '.join(rows['auction']['caveats'])
    assert '본보기' in ' '.join(rows['lotteon']['caveats'])


def test_쿠팡_vendor_를_주면_ready_지만_9칸_주의가_남는다(client):
    did = client.post('/bulk/api/drafts',
                      json=_complete_draft_body()).get_json()['draft_id']
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['coupang'], 'category_codes': ALL_CODES,
                          'vendor': {'vendor_id': 'A00123456'}})
    row = _rows(r)['coupang']
    assert row['status'] == 'ready', row
    assert '9칸' in ' '.join(row['caveats']), row['caveats']


# ── 카테고리 ────────────────────────────────────────────────────────────────

def test_카테고리가_없으면_need_category_고_그_외_빈칸도_같이_알려준다(client):
    did = _empty_draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['eleven11']})
    row = _rows(r)['eleven11']
    assert row['status'] == 'need_category', row
    assert row['category_code'] is None
    assert row['category_source'] is None
    assert 'dispCtgrNo' in row['reason'], row['reason']
    # 카테고리와 별개로 지금 비어 있는 값(재고 등)도 함께 드러난다.
    assert '재고' in row['reason'], row['reason']


def test_요청이_준_코드는_category_source_given(client):
    did = _empty_draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    row = _rows(r)['smartstore']
    assert row['category_code'] == '50000167'
    assert row['category_source'] == 'given'


def test_기본은_6마켓_전부(client):
    did = _empty_draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/preflight', json={})
    got = {row['market'] for row in r.get_json()['rows']}
    assert got == {'smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'}


def test_모르는_마켓은_400(client):
    did = _empty_draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/preflight', json={'markets': ['11st']})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_없는_드래프트는_404(client):
    r = client.post('/bulk/api/drafts/9999999/preflight', json={})
    assert r.status_code == 404


def test_스스_쿠팡에_다른_계정키를_주면_보충_필요로_미리_막는다(client):
    """register_draft 가 실제로 던지는 ValueError 를 점검이 먼저 말해 준다."""
    did = client.post('/bulk/api/drafts',
                      json=_complete_draft_body()).get_json()['draft_id']
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES,
                          'account_keys': {'smartstore': 'acctB'}})
    row = _rows(r)['smartstore']
    assert row['status'] == 'missing'
    assert '기본 계정' in row['reason'], row['reason']


# ── DB 를 심는 경우 — 브랜드 제한 / confirmed 맵핑 ──────────────────────────

@pytest.fixture()
def seeded():
    """이 섹션이 심은 행을 되돌린다(다른 테스트에 새면 안 된다)."""
    bag = {'drafts': [], 'restrictions': [], 'categories': [], 'maps': []}
    yield bag
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        ProductDraft, BrandRestriction, MarketCategory, CategoryMapRow)
    s = SessionLocal()
    try:
        for model, ids in ((ProductDraft, bag['drafts']),
                           (BrandRestriction, bag['restrictions']),
                           (MarketCategory, bag['categories']),
                           (CategoryMapRow, bag['maps'])):
            for rid in ids:
                row = s.query(model).filter_by(id=rid).first()
                if row is not None:
                    s.delete(row)
        s.commit()
    except Exception:   # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def test_브랜드_제한에_걸린_마켓은_blocked(client, seeded):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft, BrandRestriction

    s = SessionLocal()
    try:
        d = ProductDraft(name='제한 테스트 운동화', brand='제한브랜드ZZ', sale_price=39000,
                         stock_quantity=5)
        s.add(d)
        rule = BrandRestriction(brand='제한브랜드ZZ', market='coupang',
                                category_prefix='', reason='지재권 제한 — 등록 불가',
                                active=True)
        s.add(rule)
        s.commit()
        seeded['drafts'].append(d.id)
        seeded['restrictions'].append(rule.id)
        did = d.id
    finally:
        s.close()

    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['coupang', 'eleven11'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    assert rows['coupang']['status'] == 'blocked', rows['coupang']
    assert '지재권' in rows['coupang']['reason']
    # 제한이 없는 마켓은 blocked 가 아니다 (전 마켓 도매금 차단 금지).
    assert rows['eleven11']['status'] != 'blocked', rows['eleven11']


def test_confirmed_맵핑이_있으면_category_source_mapped(client, seeded):
    import datetime
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        ProductDraft, MarketCategory, CategoryMapRow)

    s = SessionLocal()
    try:
        d = ProductDraft(name='맵핑 테스트 상품', brand='테스트', sale_price=39000,
                         stock_quantity=5,
                         source_site='zzsrc', source_category_path='의류>자켓')
        s.add(d)
        cat = MarketCategory(market='eleven11', code='zz11cat', name='자켓',
                             full_path='패션의류>자켓', depth=2, is_leaf=True,
                             harvested_at=datetime.datetime(2026, 7, 23))
        s.add(cat)
        m = CategoryMapRow(source_id='zzsrc', source_path='의류>자켓', market='eleven11',
                           market_cat_code='zz11cat', market_cat_path='패션의류>자켓',
                           status='confirmed', method='manual')
        s.add(m)
        s.commit()
        seeded['drafts'].append(d.id)
        seeded['categories'].append(cat.id)
        seeded['maps'].append(m.id)
        did = d.id
    finally:
        s.close()

    # 요청이 다른 코드를 줘도 **확정 맵핑이 이긴다** (추측보다 사장님 확정값 우선).
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['eleven11'],
                          'category_codes': {'eleven11': '9999999'}})
    row = _rows(r)['eleven11']
    assert row['category_code'] == 'zz11cat', row
    assert row['category_source'] == 'mapped', row

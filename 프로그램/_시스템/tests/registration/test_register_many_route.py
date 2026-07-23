# -*- coding: utf-8 -*-
"""M4-6 여러 마켓에 한 번에 등록 — POST /bulk/api/drafts/<id>/register.

이 라우트의 존재 이유는 「마켓을 하나씩 골라 하나씩 결과를 본다」를 없애는 것이다.
그래서 가장 중요한 고정 두 가지:

  ① **사전점검에서 ready 가 아닌 마켓은 등록을 호출하지 않는다.** 보충이 필요한 마켓에
     등록 요청이 나가면 마켓 쪽에 실패 이력이 쌓이고(계정 위험), 최악에는 반쯤 만들어진
     상품이 남는다(과거이력: 502 로 죽은 등록 시도의 유령 상품).
  ② **한 마켓의 실패가 다른 마켓을 막지 않는다.** 부분 성공을 그대로 표에 보여준다.

★ 실등록은 절대 하지 않는다 — 게이트(LIVE_REGISTER_ARMED)는 꺼진 채로 두고, 마켓
  호출 계층은 전부 monkeypatch 로 폭탄을 심는다.

[2026-07-23 M4-7] 등록이 **백그라운드 스레드**로 옮겨갔다(gunicorn --timeout 60 sync
워커가 6마켓 순차 등록 도중 죽으면 요청·응답이 증발하고 이미 만들어진 상품은 회수되지
못한다 — 과거이력의 유령 상품 사고). POST 는 202+job_id 만 주고, 결과는
GET …/register/status 폴링으로 읽는다. 이 파일의 기존 고정(①ready 마켓에만 호출
②부분 성공)은 그대로 두고, 결과를 읽는 방법만 `_run(...)` 헬퍼로 바꿨다.
"""
import time

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


ALL_CODES = {
    'smartstore': '50000167', 'coupang': '63955',
    'auction': '00120005002000000000/37500700',
    'gmarket': '00120005002100000000/300006243',
    'eleven11': '1011634', 'lotteon': 'LO2727500650',
}

#: 쿠팡 계정정보 9키가 **전부** 찬 값 (test_preflight_route.py 와 같은 재료).
_FULL_VENDOR = {
    'vendor_id': 'A00123456', 'vendor_user_id': 'wing_login',
    'return_center_code': '1000557004', 'return_charge_name': '르무통 반품지',
    'return_zip': '06236', 'return_address': '서울시 강남구',
    'return_address_detail': '1층', 'return_phone': '02-111-1111',
    'outbound_place_code': '1111222',
}


def _complete_draft_body():
    """스스 예비 컴파일과 4마켓 컴파일을 모두 통과하는 드래프트."""
    return {
        'name': '테스트 자켓(복수등록)', 'brand': '테스트브랜드', 'sale_price': 39000,
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


def _complete(client, **over):
    body = _complete_draft_body()
    body.update(over)
    return client.post('/bulk/api/drafts', json=body).get_json()['draft_id']


def _rows(body):
    """최종 status 본문(dict) → {market: row}."""
    return {r['market']: r for r in body['rows']}


def _wait_done(client, did, timeout=8.0, step=0.05):
    """백그라운드 등록이 끝날 때까지 status 를 폴링 → 최종 본문(dict).

    스레드 join 대신 DB 실행 상태(running)를 본다 — 라이브가 gunicorn 3워커라
    실행 상태는 프로세스 메모리가 아니라 테이블에 있고, 화면도 이 경로로 읽는다.
    """
    waited = 0.0
    while waited < timeout:
        body = client.get(f'/bulk/api/drafts/{did}/register/status').get_json()
        if body.get('ok') and not body.get('running'):
            return body
        time.sleep(step)
        waited += step
    raise AssertionError(f'백그라운드 등록이 {timeout}초 안에 끝나지 않았다 (draft={did})')


def _run(client, did, payload, timeout=8.0):
    """POST(202 즉시) → 완료까지 폴링 → 최종 status 본문.

    ★ POST 응답에는 결과가 없다 — 있으면 그건 동기 처리라는 뜻이고, 6마켓 순차 등록은
      gunicorn 60초 타임아웃에 워커째 죽는다(유령 상품 사고 조건).
    """
    r = client.post(f'/bulk/api/drafts/{did}/register', json=payload)
    assert r.status_code == 202, r.get_data(as_text=True)
    body = r.get_json()
    assert body['ok'] is True and body['started'] is True, body
    assert 'rows' not in body, 'POST 응답에 결과가 실렸다 — 동기 처리로 퇴화했다'
    return _wait_done(client, did, timeout=timeout)


def _spy_register(monkeypatch, result=None, fail_for=()):
    """register_draft 를 기록기로 갈아끼운다 → 어느 마켓에 호출이 나갔는지 증명용.

    Returns: calls (list of dict) — 호출된 순서대로 인자가 쌓인다.
    """
    calls = []

    def fake(session, draft_id, market, *, category_code, vendor=None,
             account_key='default', **kw):
        calls.append({'draft_id': draft_id, 'market': market,
                      'category_code': category_code, 'account_key': account_key,
                      'vendor': vendor})
        if market in fail_for:
            return {'ok': False, 'market_product_id': None,
                    'error': f'{market} 4xx 본문: {{"resultCode":1000,"message":"필수값 누락"}}'}
        if result is not None:
            return dict(result, market_product_id=f'{market}-PID')
        return {'ok': True, 'market_product_id': f'{market}-PID',
                'error': None, 'excluded': []}

    import webapp.routes.bulk.drafts as D
    monkeypatch.setattr(D, 'register_draft', fake)
    return calls


# ── ★ 가장 중요한 고정 ①: ready 마켓에만 호출이 나간다 ──────────────────────

def test_ready_가_아닌_마켓에는_등록_호출이_나가지_않는다(client, monkeypatch):
    """보충 필요(쿠팡 계정정보 없음)·카테고리 없음(11번가)은 **호출 없이** 결과에만 담긴다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)

    body = _run(client, did, {
        'markets': ['smartstore', 'coupang', 'eleven11'],
        # 11번가는 일부러 코드를 안 준다 → need_category
        'category_codes': {'smartstore': ALL_CODES['smartstore'],
                           'coupang': ALL_CODES['coupang']},
    })
    rows = _rows(body)

    # 호출이 나간 마켓은 스마트스토어 하나뿐이어야 한다.
    assert [c['market'] for c in calls] == ['smartstore'], calls

    assert rows['smartstore']['status'] == 'ok'
    assert rows['coupang']['status'] == 'skipped'
    assert rows['coupang']['preflight_status'] == 'missing'
    assert '계정정보' in rows['coupang']['reason'], rows['coupang']
    assert rows['eleven11']['status'] == 'skipped'
    assert rows['eleven11']['preflight_status'] == 'need_category'
    assert 'dispCtgrNo' in rows['eleven11']['reason'], rows['eleven11']


def test_브랜드_제한_마켓은_blocked_이고_호출이_없다(client, monkeypatch, seeded):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft, BrandRestriction

    s = SessionLocal()
    try:
        d = ProductDraft(name='제한 복수등록 상품', brand='제한브랜드YY', sale_price=39000,
                         stock_quantity=5, detail_html='<p>상세</p>',
                         images_json='["https://example.com/a.jpg"]')
        s.add(d)
        rule = BrandRestriction(brand='제한브랜드YY', market='eleven11',
                                category_prefix='', reason='지재권 제한 — 등록 불가',
                                active=True)
        s.add(rule)
        s.commit()
        seeded['drafts'].append(d.id)
        seeded['restrictions'].append(rule.id)
        did = d.id
    finally:
        s.close()

    calls = _spy_register(monkeypatch)
    body = _run(client, did, {'markets': ['eleven11'], 'category_codes': ALL_CODES})
    row = _rows(body)['eleven11']
    assert row['status'] == 'blocked', row
    assert row['error_code'] == 'BRAND_RESTRICTED'
    assert '지재권' in row['reason']
    assert calls == [], '제한된 마켓에 등록 호출이 나갔다'

    # 막힌 것도 장부에 남는다 — 남기지 않으면 「왜 이 마켓만 안 올라갔지?」를 알 수 없다.
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket
    s2 = SessionLocal()
    try:
        led = (s2.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='eleven11').first())
        assert led is not None, '브랜드 제한이 장부에 안 남았다'
        assert led.status == 'blocked'
        assert led.error_code == 'BRAND_RESTRICTED'
    finally:
        s2.close()


def test_게이트가_꺼져_있으면_마켓_API_를_한_번도_안_부른다(client, monkeypatch):
    """LIVE_REGISTER_ARMED=0 이면 컴파일까지만 — HTTP 계층까지 폭탄으로 막아 증명한다."""
    calls = []

    def _boom(*a, **kw):
        calls.append(a)
        raise AssertionError('등록이 마켓 API 를 불렀습니다 — 게이트가 꺼져 있는데 금지')

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

    did = _complete(client)
    body = _run(client, did, {'markets': ['smartstore', 'auction', 'lotteon'],
                              'category_codes': ALL_CODES})
    rows = _rows(body)
    for market in ('smartstore', 'auction', 'lotteon'):
        assert rows[market]['status'] == 'blocked', rows[market]
        assert rows[market]['error_code'] == 'LIVE_OFF', rows[market]
    assert calls == [], '마켓 API 가 불렸습니다'


# ── ★ 가장 중요한 고정 ②: 부분 성공 ────────────────────────────────────────

def test_한_마켓이_실패해도_나머지는_계속_등록된다(client, monkeypatch):
    calls = _spy_register(monkeypatch, fail_for=('auction',))
    did = _complete(client)
    body = _run(client, did, {'markets': ['smartstore', 'auction', 'lotteon'],
                              'category_codes': ALL_CODES})
    rows = _rows(body)
    assert [c['market'] for c in calls] == ['smartstore', 'auction', 'lotteon']
    assert rows['smartstore']['status'] == 'ok'
    assert rows['auction']['status'] == 'failed'
    assert rows['lotteon']['status'] == 'ok', '앞 마켓 실패가 뒤 마켓을 막았다'
    assert body['summary'] == {'ok': 2, 'failed': 1, 'blocked': 0, 'skipped': 0,
                               'unknown': 0}


def test_마켓이_준_실패_원문을_그대로_실어_보낸다(client, monkeypatch):
    """4xx 본문에 진짜 이유가 있다 — 요약·가공하지 않고 그대로 올린다."""
    _spy_register(monkeypatch, fail_for=('eleven11',))
    did = _complete(client)
    body = _run(client, did, {'markets': ['eleven11'], 'category_codes': ALL_CODES})
    row = _rows(body)['eleven11']
    assert row['status'] == 'failed'
    assert 'resultCode' in row['error'], row['error']
    assert '필수값 누락' in row['error'], row['error']


def test_장부에_적힌_마켓_원응답이_결과행에_실린다(client, monkeypatch, seeded):
    """register_draft 는 마켓 원응답을 장부(raw_json)에 남긴다 — 화면까지 그것이 와야 한다.

    원문이 화면에 안 오면 사장님은 「실패」만 보고 **왜** 실패했는지 영영 모른다.
    (과거이력: raise_for_status 로 본문을 버리면 스펙 발굴이 불가능해진다.)
    """
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)
    seeded['drafts'].append(did)
    raw_body = '{"resultCode":1000,"message":"isAdultProduct 누락"}'

    def fake(session, draft_id, market, *, category_code, vendor=None,
             account_key='default', **kw):
        # 진짜 register_draft 가 하는 그대로 — 장부 행에 원응답과 에러코드를 남긴다.
        row = ProductDraftMarket(draft_id=draft_id, market=market,
                                 account_key=account_key, status='failed',
                                 error_code='NO_PRODUCT_ID', error_message='실패',
                                 raw_json=raw_body)
        session.add(row)
        session.commit()
        return {'ok': False, 'market_product_id': None, 'error': '실패'}

    import webapp.routes.bulk.drafts as D
    monkeypatch.setattr(D, 'register_draft', fake)

    body = _run(client, did, {'markets': ['auction'], 'category_codes': ALL_CODES})
    row = _rows(body)['auction']
    assert row['status'] == 'failed'
    assert row['raw'] == raw_body, row
    # 에러코드도 장부의 정확한 값으로 덮인다(라우트가 뭉뚱그린 코드보다 구체적이다).
    assert row['error_code'] == 'NO_PRODUCT_ID', row


def test_한_마켓이_예외를_던져도_나머지는_계속된다(client, monkeypatch):
    """뜻밖의 예외도 그 마켓 한 행으로만 갇힌다(500 으로 전체가 죽지 않는다)."""
    seen = []

    def fake(session, draft_id, market, *, category_code, vendor=None,
             account_key='default', **kw):
        seen.append(market)
        if market == 'smartstore':
            raise RuntimeError('예상 못한 오류')
        return {'ok': True, 'market_product_id': f'{market}-PID',
                'error': None, 'excluded': []}

    import webapp.routes.bulk.drafts as D
    monkeypatch.setattr(D, 'register_draft', fake)

    did = _complete(client)
    body = _run(client, did, {'markets': ['smartstore', 'lotteon'],
                              'category_codes': ALL_CODES})
    rows = _rows(body)
    assert seen == ['smartstore', 'lotteon']
    assert rows['smartstore']['status'] == 'failed'
    assert rows['smartstore']['error_code'] == 'UNEXPECTED'
    assert '예상 못한 오류' in rows['smartstore']['error']
    assert rows['lotteon']['status'] == 'ok'


# ── 계약 세부 ───────────────────────────────────────────────────────────────

def test_마켓_간_병렬_금지_요청한_순서대로_순차_호출(client, monkeypatch):
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    order = ['lotteon', 'smartstore', 'auction']
    _run(client, did, {'markets': order, 'category_codes': ALL_CODES})
    assert [c['market'] for c in calls] == order


def test_같은_마켓을_두_번_넣어도_한_번만_부른다(client, monkeypatch):
    """중복 호출 = 같은 상품 2개 = 유령 상품."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    body = _run(client, did, {'markets': ['smartstore', 'smartstore'],
                              'category_codes': ALL_CODES})
    assert [c['market'] for c in calls] == ['smartstore']
    assert len(body['rows']) == 1


def test_성공_행에는_등록_뒤_주의가_붙는다(client, monkeypatch):
    """ESM 등록 직후 2~3분 수정 불가·옵션 실패 시 회수 — 결과표에서 알려야 한다."""
    _spy_register(monkeypatch)
    did = _complete(client)
    body = _run(client, did, {'markets': ['auction', 'gmarket', 'lotteon'],
                              'category_codes': ALL_CODES})
    rows = _rows(body)
    for market in ('auction', 'gmarket'):
        joined = ' '.join(rows[market]['notes'])
        assert '2~3분' in joined, rows[market]['notes']
        assert '판매중지' in joined, rows[market]['notes']
    assert '본보기' in ' '.join(rows['lotteon']['notes'])


def test_쿠팡은_vendor_를_안_보내도_계정_저장값으로_동작한다(client, monkeypatch):
    """[M4-2] 화면이 vendor 를 안 보내도 계정 저장값이 주입돼야 한다."""
    import lemouton.registration.coupang_vendor as CV
    monkeypatch.setattr(CV, 'vendor_for_account',
                        lambda session, account_key=None: dict(_FULL_VENDOR))
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    body = _run(client, did, {'markets': ['coupang'], 'category_codes': ALL_CODES})
    row = _rows(body)['coupang']
    assert row['status'] == 'ok', row
    assert len(calls) == 1
    assert calls[0]['vendor']['return_center_code'] == '1000557004', calls[0]['vendor']


def test_markets_가_비면_400(client):
    did = _complete(client)
    for body in ({}, {'markets': []}, {'markets': 'smartstore'}):
        r = client.post(f'/bulk/api/drafts/{did}/register', json=body)
        assert r.status_code == 400, body
        assert r.get_json()['ok'] is False


def test_모르는_마켓은_400(client):
    did = _complete(client)
    r = client.post(f'/bulk/api/drafts/{did}/register', json={'markets': ['11st']})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_없는_드래프트는_404(client):
    r = client.post('/bulk/api/drafts/9999999/register',
                    json={'markets': ['smartstore']})
    assert r.status_code == 404


# ── 하위 호환: 단수 라우트는 그대로 ─────────────────────────────────────────

def test_단수_라우트는_예전_응답_모양_그대로다(client):
    did = _complete(client)
    r = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                    json={'category_code': ALL_CODES['smartstore']})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['ok'] is False
    assert body['blocked'] is True          # 게이트 OFF
    assert 'LIVE_REGISTER_ARMED' in body['error']


def test_단수_라우트_스스에_다른_계정키는_404(client):
    """예전 계약(ValueError → 404) 유지."""
    did = _complete(client)
    r = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                    json={'category_code': ALL_CODES['smartstore'],
                          'account_key': 'acctB'})
    assert r.status_code == 404
    assert r.get_json()['ok'] is False


# ── confirmed 맵핑 자동 적용 ────────────────────────────────────────────────

@pytest.fixture()
def seeded():
    """이 파일이 심은 행을 되돌린다(다른 테스트에 새면 안 된다)."""
    bag = {'drafts': [], 'restrictions': [], 'categories': [], 'maps': []}
    yield bag
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        ProductDraft, ProductDraftMarket, BrandRestriction, MarketCategory,
        CategoryMapRow, ProductDraftRegisterRun)
    s = SessionLocal()
    try:
        # 마켓 행을 먼저 지운다 — 드래프트만 지우면 주인 없는 등록 기록이 남는다.
        for did in bag['drafts']:
            for row in s.query(ProductDraftMarket).filter_by(draft_id=did).all():
                s.delete(row)
            # 실행 상태 행도 같이 — 남으면 다음 실행이 running=True 를 물려받아 409 가 난다.
            for row in s.query(ProductDraftRegisterRun).filter_by(draft_id=did).all():
                s.delete(row)
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


def test_confirmed_맵핑이_있으면_그_코드로_등록한다(client, monkeypatch, seeded):
    """요청이 다른 코드를 줘도 **사장님 확정 맵핑이 이긴다** (추측보다 확정값)."""
    import datetime
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        ProductDraft, MarketCategory, CategoryMapRow)

    # 컴파일을 통과하는 완결 드래프트를 라우트로 만든 뒤, 소싱처 분류만 붙인다
    # (여기서 필수값이 비면 preflight 가 missing 이라 맵핑 검증 자체가 안 된다).
    did = _complete(client, name='맵핑 복수등록 상품')
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        d.source_site = 'yysrc'
        d.source_category_path = '의류>자켓'
        cat = MarketCategory(market='eleven11', code='yy11cat', name='자켓',
                             full_path='패션의류>자켓', depth=2, is_leaf=True,
                             harvested_at=datetime.datetime(2026, 7, 23))
        s.add(cat)
        m = CategoryMapRow(source_id='yysrc', source_path='의류>자켓', market='eleven11',
                           market_cat_code='yy11cat', market_cat_path='패션의류>자켓',
                           status='confirmed', method='manual')
        s.add(m)
        s.commit()
        seeded['drafts'].append(did)
        seeded['categories'].append(cat.id)
        seeded['maps'].append(m.id)
    finally:
        s.close()

    calls = _spy_register(monkeypatch)
    body = _run(client, did, {'markets': ['eleven11'],
                              'category_codes': {'eleven11': '9999999'}})
    row = _rows(body)['eleven11']
    assert row['category_code'] == 'yy11cat', row
    assert row['category_source'] == 'mapped', row
    assert calls[0]['category_code'] == 'yy11cat', calls

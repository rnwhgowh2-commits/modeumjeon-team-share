# -*- coding: utf-8 -*-
"""M4-3 고시정보 기본값 — 설정 라우트 + 사전 점검·등록 배선(라이브 호출 없음).

★ 이 파일은 실제 앱 DB(SessionLocal)를 쓴다 — 다른 테스트가 보는 전역 기본값을
  남기면 안 되므로 매 테스트 전후로 notice_defaults 행을 지운다.
"""
import json

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


@pytest.fixture(autouse=True)
def _clean_defaults():
    from shared.db import SessionLocal
    from lemouton.registration.notice_defaults import NoticeDefault

    def wipe():
        s = SessionLocal()
        try:
            s.query(NoticeDefault).delete()
            s.commit()
        finally:
            s.close()

    wipe()
    yield
    wipe()


WEAR_FULL = {
    'material': '면 100%', 'color': '블랙', 'size': '95 / 100',
    'manufacturer': '르무통', 'caution': '단독세탁',
    'warranty_policy': '구매일로부터 1년',
    'after_service_director': '테스트 담당자 (실제 연락처 아님)',
}


def _draft_without_notice(client, **over):
    """고시만 비어 있는 드래프트 — 스스 컴파일이 「상품고시정보 미완성」에서 걸린다."""
    body = {
        'name': '고시 없는 자켓', 'sale_price': 39000, 'notice_type': 'WEAR',
        'notice': {},
        'after_service_phone': '02-000-0000',
        'after_service_guide': '반품·교환 안내',
    }
    body.update(over)
    return client.post('/bulk/api/drafts', json=body).get_json()['draft_id']


def _set_source_site(draft_id, source_id):
    """소싱처 표시는 M3 크롤이 채우는 칸이라 수기 저장 라우트가 받지 않는다 → DB 로 직접."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        s.query(ProductDraft).filter_by(id=draft_id).update({'source_site': source_id})
        s.commit()
    finally:
        s.close()


def _row(res, market='smartstore'):
    return {r['market']: r for r in res.get_json()['rows']}[market]


# ── 설정 라우트 ─────────────────────────────────────────────────────────────

def test_칸_목록은_고시유형별로_달라진다(client):
    wear = client.get('/bulk/api/notice-defaults?notice_type=WEAR').get_json()
    bag = client.get('/bulk/api/notice-defaults?notice_type=BAG').get_json()
    assert wear['ok'] and bag['ok']
    wear_keys = [f['key'] for f in wear['fields']]
    bag_keys = [f['key'] for f in bag['fields']]
    assert 'type' not in wear_keys and 'type' in bag_keys   # 가방만 「종류」가 필수
    assert 'warranty_policy' in wear_keys


def test_저장하고_다시_불러온다(client):
    r = client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR',
        'values': {'warranty_policy': '구매일로부터 1년', 'material': ''}})
    assert r.status_code == 200 and r.get_json()['ok']
    assert r.get_json()['values'] == {'warranty_policy': '구매일로부터 1년'}

    got = client.get('/bulk/api/notice-defaults?scope=global&notice_type=WEAR').get_json()
    assert got['values'] == {'warranty_policy': '구매일로부터 1년'}


def test_모르는_칸과_모르는_유형은_400(client):
    r = client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': {'heel_height': '5cm'}})
    assert r.status_code == 400 and not r.get_json()['ok']

    r2 = client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'HAT', 'values': {}})
    assert r2.status_code == 400

    r3 = client.get('/bulk/api/notice-defaults?scope=musinsa&notice_type=WEAR')
    assert r3.status_code == 400


def test_소싱처_스코프를_보면_전역값도_함께_준다(client):
    client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': {'warranty_policy': '전역 보증'}})
    got = client.get(
        '/bulk/api/notice-defaults?scope=source:musinsa&notice_type=WEAR').get_json()
    assert got['values'] == {}
    assert got['global_values'] == {'warranty_policy': '전역 보증'}


# ── 설정 화면 ───────────────────────────────────────────────────────────────

def test_설정_탭에_고시정보_기본값_카드가_있다(client):
    """카드를 만들어도 템플릿에 안 붙으면 화면에 아예 안 뜬다 — 붙었는지 고정한다."""
    html = client.get('/bulk/?tab=settings').get_data(as_text=True)
    assert '고시정보 기본값' in html
    assert 'nd-root' in html
    assert '/bulk/api/notice-defaults' in html


# ── 사전 점검 배선 ──────────────────────────────────────────────────────────

def test_기본값이_없으면_고시_미완성_그대로_뜬다(client):
    did = _draft_without_notice(client)
    row = _row(client.post(f'/bulk/api/drafts/{did}/preflight',
                           json={'markets': ['smartstore'],
                                 'category_codes': {'smartstore': '50000167'}}))
    assert row['status'] == 'missing'
    assert '상품고시정보 미완성' in row['reason']
    assert row['filled_from'] == {}


def test_기본값을_채우면_점검이_통과하고_어디서_왔는지_알려준다(client):
    did = _draft_without_notice(client)
    client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': WEAR_FULL})

    row = _row(client.post(f'/bulk/api/drafts/{did}/preflight',
                           json={'markets': ['smartstore'],
                                 'category_codes': {'smartstore': '50000167'}}))
    assert row['status'] == 'ready', row['reason']
    assert row['filled_from']['material'] == 'global'
    assert set(row['filled_from']) == set(WEAR_FULL)


def test_일부만_채우면_남은_칸이_그대로_missing_으로_뜬다(client):
    """폴백 금지 — 병합 후에도 비는 칸은 지어내지 않고 빨간불로 남는다."""
    did = _draft_without_notice(client)
    partial = dict(WEAR_FULL)
    partial.pop('after_service_director')
    client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': partial})

    row = _row(client.post(f'/bulk/api/drafts/{did}/preflight',
                           json={'markets': ['smartstore'],
                                 'category_codes': {'smartstore': '50000167'}}))
    assert row['status'] == 'missing'
    assert 'afterServiceDirector' in row['reason']


def test_소싱처_기본값이_전역보다_우선한다(client):
    did = _draft_without_notice(client)
    _set_source_site(did, 'musinsa')
    client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': WEAR_FULL})
    client.post('/bulk/api/notice-defaults', json={
        'scope': 'source:musinsa', 'notice_type': 'WEAR',
        'values': {'material': '소싱처 소재'}})

    row = _row(client.post(f'/bulk/api/drafts/{did}/preflight',
                           json={'markets': ['smartstore'],
                                 'category_codes': {'smartstore': '50000167'}}))
    assert row['status'] == 'ready', row['reason']
    assert row['filled_from']['material'] == 'source:musinsa'
    assert row['filled_from']['warranty_policy'] == 'global'


def test_고시를_안_쓰는_마켓에는_filled_from_을_붙이지_않는다(client):
    did = _draft_without_notice(client)
    client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': WEAR_FULL})
    res = client.post(f'/bulk/api/drafts/{did}/preflight', json={})
    for r in res.get_json()['rows']:
        if r['market'] != 'smartstore':
            assert r['filled_from'] == {}


def test_점검해도_저장된_드래프트는_그대로다(client):
    """★ 병합은 사본에서만 — 사장님이 저장한 고시값이 프로그램 값으로 오염되면 안 된다."""
    did = _draft_without_notice(client, notice={'color': '블랙'})
    client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': WEAR_FULL})
    client.post(f'/bulk/api/drafts/{did}/preflight',
                json={'markets': ['smartstore'],
                      'category_codes': {'smartstore': '50000167'}})

    got = client.get(f'/bulk/api/drafts/{did}').get_json()['draft']
    assert got['notice'] == {'color': '블랙'}


# ── 등록 배선 (게이트 OFF — 마켓 호출 없음) ────────────────────────────────

def test_등록도_같은_기본값으로_컴파일한다(client):
    """게이트 OFF 라 실호출은 없다 — 컴파일이 통과했는지는 blocked 로 알 수 있다.

    기본값이 없으면 컴파일이 먼저 실패해 blocked 에 닿지도 못한다(= 고시 미완성).
    """
    did = _draft_without_notice(client)
    before = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                         json={'category_code': '50000167'}).get_json()
    assert not before['ok'] and '상품고시정보 미완성' in (before.get('error') or '')

    client.post('/bulk/api/notice-defaults', json={
        'scope': 'global', 'notice_type': 'WEAR', 'values': WEAR_FULL})
    after = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                        json={'category_code': '50000167'}).get_json()
    assert after.get('blocked') is True         # 컴파일 통과 → 라이브 게이트에서 멈춤
    assert 'LIVE_REGISTER_ARMED' in (after.get('error') or '')

    # 저장값은 여전히 그대로
    got = client.get(f'/bulk/api/drafts/{did}').get_json()['draft']
    assert got['notice'] == {}

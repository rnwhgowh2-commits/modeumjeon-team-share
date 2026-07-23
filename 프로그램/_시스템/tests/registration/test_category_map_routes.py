# -*- coding: utf-8 -*-
"""M2 Task 5·6 — 맵핑 판정(resolve)·확정(confirm)·제안생성(suggest)·브랜드제한 CRUD 라우트 +
재수집 re_confirm 강등 훅 + 등록 흐름 브랜드제한 선차단.

공유 Supabase 원칙 — 이 파일이 심은 행만 정확히 지운다(autouse 정리 fixture).
소싱처 id·마켓코드는 실존 이름과 안 겹치게 'zz-catmap-...' 접두를 쓴다.
"""
import datetime

import pytest


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    application = appmod.create_app()
    application.config['TESTING'] = True
    with application.test_client() as c:
        yield c


_MC_SEEDED = []       # [(market, code)]
_SC_SEEDED = []       # [(source_id, path)]
_CM_SEEDED = []       # [(source_id, path, market)]
_BR_SEEDED = []       # [id]
_DRAFT_SEEDED = []    # [draft_id]


def _seed_mc(market='smartstore', code='zz-mc-1', name='여성운동화',
             path='패션잡화>여성신발>여성운동화', leaf=True, removed=False):
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    row = MarketCategory(market=market, code=code, name=name, full_path=path,
                         depth=3, is_leaf=leaf,
                         harvested_at=datetime.datetime(2026, 7, 22),
                         removed_at=(datetime.datetime(2026, 7, 23) if removed else None))
    s.add(row)
    s.commit()
    s.close()
    _MC_SEEDED.append((market, code))


def _seed_sc(source_id='zz-catmap-src', path='신발>스니커즈>여성운동화', leaf_name='여성운동화'):
    from shared.db import SessionLocal
    from lemouton.registration.models import SourceCategory
    s = SessionLocal()
    s.add(SourceCategory(source_id=source_id, path=path, leaf_name=leaf_name, depth=3,
                         first_seen_at=datetime.datetime(2026, 7, 23)))
    s.commit()
    s.close()
    _SC_SEEDED.append((source_id, path))


def _seed_cm(source_id='zz-catmap-src', path='신발>스니커즈>여성운동화', market='smartstore',
             code='zz-mc-1', status='suggested', candidates=None):
    from shared.db import SessionLocal
    from lemouton.registration.models import CategoryMapRow
    import json
    s = SessionLocal()
    s.add(CategoryMapRow(source_id=source_id, source_path=path, market=market,
                         market_cat_code=code, market_cat_path='패션잡화>여성신발>여성운동화',
                         status=status, method='name_sim', confidence=0.9,
                         candidates_json=(json.dumps(candidates, ensure_ascii=False)
                                         if candidates is not None else None)))
    s.commit()
    s.close()
    _CM_SEEDED.append((source_id, path, market))


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        MarketCategory, SourceCategory, CategoryMapRow, BrandRestriction,
        ProductDraft, ProductDraftMarket)
    s = SessionLocal()
    try:
        for market, code in _MC_SEEDED:
            for row in s.query(MarketCategory).filter_by(market=market, code=code).all():
                s.delete(row)
        for source_id, path in _SC_SEEDED:
            for row in s.query(SourceCategory).filter_by(source_id=source_id, path=path).all():
                s.delete(row)
        for source_id, path, market in _CM_SEEDED:
            for row in (s.query(CategoryMapRow)
                       .filter_by(source_id=source_id, source_path=path, market=market).all()):
                s.delete(row)
        for rid in _BR_SEEDED:
            row = s.query(BrandRestriction).filter_by(id=rid).first()
            if row is not None:
                s.delete(row)
        for did in _DRAFT_SEEDED:
            for m in s.query(ProductDraftMarket).filter_by(draft_id=did).all():
                s.delete(m)
            row = s.query(ProductDraft).filter_by(id=did).first()
            if row is not None:
                s.delete(row)
        s.commit()
    except Exception:      # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MC_SEEDED.clear(); _SC_SEEDED.clear(); _CM_SEEDED.clear()
        _BR_SEEDED.clear(); _DRAFT_SEEDED.clear()


# ── resolve ──────────────────────────────────────────────────────────────

def test_resolve_행이_없으면_none이다(client):
    r = client.get('/bulk/api/catmap/resolve',
                   query_string={'source': 'zz-catmap-src', 'path': '없는>경로', 'market': 'smartstore'})
    data = r.get_json()
    assert data == {'ok': True, 'status': 'none', 'code': None, 'path': None, 'candidates': []}


def test_resolve_confirmed_행은_코드와_경로를_그대로_준다(client):
    _seed_cm(status='confirmed')
    r = client.get('/bulk/api/catmap/resolve',
                   query_string={'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
                                 'market': 'smartstore'})
    data = r.get_json()
    assert data['ok'] is True
    assert data['status'] == 'confirmed'
    assert data['code'] == 'zz-mc-1'
    assert data['path'] == '패션잡화>여성신발>여성운동화'


def test_resolve_suggested_행은_후보목록과_함께_suggested를_준다(client):
    cands = [{'code': 'zz-mc-1', 'path': '패션잡화>여성신발>여성운동화', 'name': '여성운동화', 'score': 1.0}]
    _seed_cm(status='suggested', candidates=cands)
    r = client.get('/bulk/api/catmap/resolve',
                   query_string={'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
                                 'market': 'smartstore'})
    data = r.get_json()
    assert data['status'] == 'suggested'
    assert data['candidates'] == cands


def test_resolve_re_confirm_행도_suggested로_노출된다(client):
    """re_confirm 은 「다시 골라야 함」 신호 — 등록 흐름 입장에선 suggested 와 동일 취급."""
    _seed_cm(status='re_confirm', candidates=[])
    r = client.get('/bulk/api/catmap/resolve',
                   query_string={'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
                                 'market': 'smartstore'})
    data = r.get_json()
    assert data['status'] == 'suggested'


def test_resolve_필수파라미터_누락은_400(client):
    r = client.get('/bulk/api/catmap/resolve', query_string={'source': 'x'})
    assert r.status_code == 400


# ── confirm ──────────────────────────────────────────────────────────────

def test_confirm_사전에_있는_코드는_confirmed로_승격한다(client):
    _seed_mc()
    r = client.post('/bulk/api/catmap/confirm', json={
        'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
        'market': 'smartstore', 'code': 'zz-mc-1'})
    _CM_SEEDED.append(('zz-catmap-src', '신발>스니커즈>여성운동화', 'smartstore'))
    data = r.get_json()
    assert data['ok'] is True
    assert data['row']['status'] == 'confirmed'
    assert data['row']['market_cat_path'] == '패션잡화>여성신발>여성운동화'

    r2 = client.get('/bulk/api/catmap/resolve',
                    query_string={'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
                                  'market': 'smartstore'})
    assert r2.get_json()['status'] == 'confirmed'


def test_confirm_사전에_없는_코드는_400을_거부한다(client):
    r = client.post('/bulk/api/catmap/confirm', json={
        'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
        'market': 'smartstore', 'code': 'zz-never-exists'})
    assert r.status_code == 400
    assert '없습니다' in r.get_json()['error']


def test_confirm_removed된_코드는_400을_거부한다(client):
    _seed_mc(code='zz-mc-removed', removed=True)
    r = client.post('/bulk/api/catmap/confirm', json={
        'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
        'market': 'smartstore', 'code': 'zz-mc-removed'})
    assert r.status_code == 400
    assert '사라졌습니다' in r.get_json()['error']


def test_confirm_동시성_IntegrityError는_rollback후_재조회로_UPDATE에_수렴한다(client, monkeypatch):
    """리뷰 이월 — keyword_store.get_config 관례 이식 검증.

    다른 요청이 먼저 같은 (source, path, market) 키로 confirmed 행을 커밋해 둔 상태에서,
    이 요청은 조회 시점에 '행 없음'을 봤다고 가정(stale read, 첫 조회만 monkeypatch 로 None)
    → INSERT 를 시도 → UNIQUE 위반 IntegrityError → rollback → 재조회로 그 행을 찾아
    UPDATE 로 수렴해야 한다(500 이 아니라 정상 confirmed 응답)."""
    from webapp.routes.bulk import category_map as cm_routes
    from shared.db import SessionLocal
    from lemouton.registration.models import CategoryMapRow

    _seed_mc()

    s = SessionLocal()
    s.add(CategoryMapRow(source_id='zz-catmap-src', source_path='신발>스니커즈>여성운동화',
                         market='smartstore', market_cat_code='zz-mc-1',
                         market_cat_path='패션잡화>여성신발>여성운동화', status='confirmed',
                         method='manual'))
    s.commit()
    s.close()
    _CM_SEEDED.append(('zz-catmap-src', '신발>스니커즈>여성운동화', 'smartstore'))

    real_find = cm_routes._find_map_row
    calls = {'n': 0}

    def stale_first(session, source, path, market):
        calls['n'] += 1
        return None if calls['n'] == 1 else real_find(session, source, path, market)

    monkeypatch.setattr(cm_routes, '_find_map_row', stale_first)

    r = client.post('/bulk/api/catmap/confirm', json={
        'source': 'zz-catmap-src', 'path': '신발>스니커즈>여성운동화',
        'market': 'smartstore', 'code': 'zz-mc-1'})
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert data['row']['status'] == 'confirmed'
    assert calls['n'] >= 2   # 충돌 후 재조회까지 갔다


# ── suggest ──────────────────────────────────────────────────────────────

def test_suggest_활성쿠팡계정이_없으면_앵커생략하고_유사도만_생성한다(client):
    _seed_sc()
    for i, market in enumerate(('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'), 1):
        _seed_mc(market=market, code=f'zz-{market[:2]}{i}', name='여성운동화',
                 path=f'패션잡화>운동화>여성운동화')
    r = client.post('/bulk/api/catmap/suggest/zz-catmap-src')
    data = r.get_json()
    assert data['ok'] is True
    assert data['coupang_anchor'] is False
    assert 'coupang_anchor_note' in data
    assert data['sources'] == 1
    for market in ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'):
        _CM_SEEDED.append(('zz-catmap-src', '신발>스니커즈>여성운동화', market))


def test_suggest_쿠팡자격증명로드실패하면_앵커생략하고_유사도만_생성한다(client, monkeypatch):
    """활성 쿠팡 계정은 있지만 MF._coupang_client 가 자격증명 로드 실패(RuntimeError 계열)로
    예외를 던지는 경우 — 앵커 생략 폴백일 뿐 500 이면 안 된다(계약 위반)."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount

    _seed_sc()
    for i, market in enumerate(('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'), 1):
        _seed_mc(market=market, code=f'zz-cred{i}', name='여성운동화',
                 path=f'패션잡화>운동화>여성운동화')

    s = SessionLocal()
    acct = UploadAccount(account_key='zz-catmap-coupang-cred-fail', display_name='zz 테스트 쿠팡계정',
                         market='coupang', env_prefix='ZZ_CATMAP_CRED_FAIL', is_active=True)
    s.add(acct)
    s.commit()
    acct_id = acct.id
    s.close()

    import lemouton.uploader.market_fetch as MF

    def _boom(env_prefix):
        raise RuntimeError('시크릿 누락 — ZZ_CATMAP_CRED_FAIL_ACCESS_KEY')
    monkeypatch.setattr(MF, '_coupang_client', _boom)

    try:
        r = client.post('/bulk/api/catmap/suggest/zz-catmap-src')
        data = r.get_json()
        assert r.status_code == 200
        assert data['ok'] is True
        assert data['coupang_anchor'] is False
        assert 'coupang_anchor_note' in data
        assert data['sources'] == 1
        for market in ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'):
            _CM_SEEDED.append(('zz-catmap-src', '신발>스니커즈>여성운동화', market))
    finally:
        s2 = SessionLocal()
        row = s2.query(UploadAccount).filter_by(id=acct_id).first()
        if row is not None:
            s2.delete(row)
        s2.commit()
        s2.close()


def test_suggest_소싱처카테고리가_없으면_404를_거부한다(client):
    """리뷰 이월 — 소싱처에 source_categories 행이 0건이면 조용히 200/제안0건 대신
    404 로 사유를 밝힌다(먼저 수집하거나 경로를 확인하라는 안내)."""
    r = client.post('/bulk/api/catmap/suggest/zz-catmap-never-harvested')
    assert r.status_code == 404
    data = r.get_json()
    assert data['ok'] is False
    assert 'zz-catmap-never-harvested' in data['error']
    assert '소싱처 카테고리가 없습니다' in data['error']


def test_suggest_리프200개초과면_쿠팡앵커를_생략한다(client):
    from shared.db import SessionLocal
    from lemouton.registration.models import SourceCategory
    s = SessionLocal()
    for i in range(201):
        s.add(SourceCategory(source_id='zz-catmap-big', path=f'식품>과일>사과{i}',
                             leaf_name=f'사과{i}', depth=3,
                             first_seen_at=datetime.datetime(2026, 7, 23)))
    s.commit()
    s.close()
    try:
        r = client.post('/bulk/api/catmap/suggest/zz-catmap-big')
        data = r.get_json()
        assert data['ok'] is True
        assert data['coupang_anchor'] is False
        assert '200' in data['coupang_anchor_note']
    finally:
        s2 = SessionLocal()
        for row in s2.query(SourceCategory).filter_by(source_id='zz-catmap-big').all():
            s2.delete(row)
        s2.commit()
        s2.close()


# ── catmap/status ────────────────────────────────────────────────────────

def test_catmap_status는_소싱처별_상태를_집계한다(client):
    _seed_cm(source_id='zz-catmap-agg', market='smartstore', status='suggested')
    _seed_cm(source_id='zz-catmap-agg', market='coupang', status='confirmed')
    r = client.get('/bulk/api/catmap/status')
    data = r.get_json()
    assert data['ok'] is True
    row = next(x for x in data['rows'] if x['source_id'] == 'zz-catmap-agg')
    assert row['suggested'] == 1
    assert row['confirmed'] == 1
    assert row['re_confirm'] == 0


# ── brand-limits CRUD ───────────────────────────────────────────────────

def test_brand_limits_추가조회삭제(client):
    r = client.post('/bulk/api/brand-limits', json={
        'brand': 'zz-테스트브랜드', 'market': 'coupang', 'reason': '테스트 지재권'})
    data = r.get_json()
    assert data['ok'] is True
    rid = data['row']['id']
    _BR_SEEDED.append(rid)

    r2 = client.get('/bulk/api/brand-limits')
    rows = r2.get_json()['rows']
    assert any(x['id'] == rid and x['brand'] == 'zz-테스트브랜드' for x in rows)

    r3 = client.delete('/bulk/api/brand-limits', json={'id': rid})
    assert r3.get_json()['ok'] is True
    _BR_SEEDED.remove(rid)

    r4 = client.get('/bulk/api/brand-limits')
    assert not any(x['id'] == rid for x in r4.get_json()['rows'])


def test_brand_limits_모르는_마켓은_400(client):
    r = client.post('/bulk/api/brand-limits', json={
        'brand': 'zz-테스트브랜드2', 'market': 'nosuch', 'reason': '테스트'})
    assert r.status_code == 400


def test_brand_limits_별표는_전마켓_차단이라_허용된다(client):
    r = client.post('/bulk/api/brand-limits', json={
        'brand': 'zz-테스트브랜드3', 'market': '*', 'reason': '테스트'})
    data = r.get_json()
    assert data['ok'] is True
    _BR_SEEDED.append(data['row']['id'])


# ── Task 7: 설정 탭 카드 마커 ────────────────────────────────────────────

def test_설정탭에_브랜드제한_카드가_뜬다(client):
    r = client.get('/bulk/?tab=settings')
    assert r.status_code == 200
    assert 'brand-limit-root' in r.get_data(as_text=True)


def test_설정탭에_카테고리맵핑_카드가_뜬다(client):
    r = client.get('/bulk/?tab=settings')
    assert r.status_code == 200
    assert 'catmap-root' in r.get_data(as_text=True)


# ── re_confirm 강등 훅 (save_snapshot) ────────────────────────────────────

def test_재수집에서_코드가_사라지면_confirmed_맵핑이_re_confirm으로_강등된다(client):
    """스펙 §C — 재수집 diff 가 re_confirm 강등의 주체. save_snapshot 이 그 세션 안에서
    같은 (market, market_cat_code) 를 가리키던 confirmed 행을 re_confirm 으로 내린다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory, CategoryMapRow
    from lemouton.registration import category_harvest as ch

    market = 'zz-catmap-market'   # 실존 마켓과 안 겹치는 이름 — save_snapshot 은 market 값을 안 가린다
    now0 = datetime.datetime(2026, 7, 20)
    s = SessionLocal()
    s.add(MarketCategory(market=market, code='zz-going-away', name='사라질카테고리',
                         full_path='루트>사라질카테고리', depth=1, is_leaf=True, harvested_at=now0))
    s.add(CategoryMapRow(source_id='zz-catmap-src', source_path='신발>스니커즈>여성운동화',
                         market=market, market_cat_code='zz-going-away',
                         market_cat_path='루트>사라질카테고리', status='confirmed', method='manual',
                         confirmed_at=now0))
    s.commit()
    s.close()
    _MC_SEEDED.append((market, 'zz-going-away'))
    _CM_SEEDED.append(('zz-catmap-src', '신발>스니커즈>여성운동화', market))

    s2 = SessionLocal()
    try:
        # 재수집 결과에 'zz-going-away' 가 더는 없다 — 남은 아무 코드로 스냅샷을 채운다
        # (save_snapshot 은 빈 rows 를 거부하므로 최소 1행은 있어야 한다).
        rows = [{'code': 'zz-still-here', 'name': '남은카테고리', 'parent_code': None,
                'depth': 1, 'is_leaf': True, 'full_path': '루트>남은카테고리', 'raw': '{}'}]
        ch.save_snapshot(s2, market, rows, now=datetime.datetime(2026, 7, 23))
    finally:
        s2.close()
    _MC_SEEDED.append((market, 'zz-still-here'))

    s3 = SessionLocal()
    try:
        row = (s3.query(CategoryMapRow)
              .filter_by(source_id='zz-catmap-src', source_path='신발>스니커즈>여성운동화',
                        market=market).one())
        assert row.status == 're_confirm'
        mc = s3.query(MarketCategory).filter_by(market=market, code='zz-going-away').one()
        assert mc.removed_at is not None
    finally:
        s3.close()


# ── Task 6: 등록 흐름 브랜드제한 선차단 ────────────────────────────────────

def test_등록시_브랜드제한에_걸리면_마켓호출없이_blocked를_반환한다(client, monkeypatch):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft, BrandRestriction, ProductDraftMarket

    s = SessionLocal()
    d = ProductDraft(name='제한테스트상품', brand='zz-지재권브랜드', sale_price=10000)
    s.add(d)
    s.commit()
    draft_id = d.id
    s.close()
    _DRAFT_SEEDED.append(draft_id)

    s2 = SessionLocal()
    rule = BrandRestriction(brand='zz-지재권브랜드', market='coupang', category_prefix='',
                            reason='테스트 지재권 신고', active=True)
    s2.add(rule)
    s2.commit()
    rid = rule.id
    s2.close()
    _BR_SEEDED.append(rid)

    from webapp.routes.bulk import drafts as drafts_routes

    def _boom(*a, **kw):
        raise AssertionError('브랜드 제한에 걸렸는데 register_draft 가 호출됐다 — 마켓 호출 금지 위반')
    monkeypatch.setattr(drafts_routes, 'register_draft', _boom)

    r = client.post(f'/bulk/api/drafts/{draft_id}/register/coupang',
                    json={'category_code': '12345'})
    data = r.get_json()
    assert data['ok'] is False
    assert data['blocked'] is True
    assert '지재권' in data['reason']

    s3 = SessionLocal()
    row = s3.query(ProductDraftMarket).filter_by(draft_id=draft_id, market='coupang').first()
    assert row is not None
    assert row.status == 'blocked'
    assert row.error_code == 'BRAND_RESTRICTED'
    s3.close()


def test_등록시_브랜드제한에_안걸리면_평소대로_register_draft를_호출한다(client, monkeypatch):
    """다른 마켓(브랜드제한 규칙이 coupang 만이면 smartstore)은 정상 진행돼야 한다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft, BrandRestriction

    s = SessionLocal()
    d = ProductDraft(name='제한없음테스트상품', brand='zz-무관브랜드', sale_price=10000)
    s.add(d)
    s.commit()
    draft_id = d.id
    s.close()
    _DRAFT_SEEDED.append(draft_id)

    s2 = SessionLocal()
    rule = BrandRestriction(brand='zz-다른브랜드', market='coupang', category_prefix='',
                            reason='무관', active=True)
    s2.add(rule)
    s2.commit()
    rid = rule.id
    s2.close()
    _BR_SEEDED.append(rid)

    from webapp.routes.bulk import drafts as drafts_routes
    called = {}

    def _fake(session, draft_id_, market, **kw):
        called['ok'] = True
        return {'ok': True, 'market_product_id': 'FAKE-1', 'error': None, 'excluded': []}
    monkeypatch.setattr(drafts_routes, 'register_draft', _fake)

    r = client.post(f'/bulk/api/drafts/{draft_id}/register/coupang',
                    json={'category_code': '12345'})
    data = r.get_json()
    assert data.get('blocked') is not True
    assert called.get('ok') is True

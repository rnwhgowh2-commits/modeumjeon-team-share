# -*- coding: utf-8 -*-
"""쿠팡 쿠폰 — 상품 화면 단추 · 상태 조회 · 정책 자동 · 스케줄러 등록.

■ 🔴 「대기열에 넣었다」 ≠ 「걸렸다」
    화면이 둘을 같은 말로 하면 사장님은 안 걸린 것을 걸린 줄 안다.
    상태는 네 갈래로 갈린다 — 아직(none) / 대기 중(queued) / 걸림(applied) / 실패(failed).

■ 🔴 처리기가 실제로 등록돼 있어야 한다
    처리기 없이 대기열만 있으면 「잠시 뒤 결과가 나옵니다」가 거짓말이 된다
    (라이브에서 실제로 겪었다). 스케줄러 등록까지 시험으로 잠근다.
"""
import datetime as _dt
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)
    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass
    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


def _seed(client, *, opt_status='matched'):
    """모음전 상품 1개 + 구성 1개 + 쿠팡 채널 1개 + 옵션 1개."""
    from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption
    from lemouton.sourcing.models import Model
    s = client._Session()
    try:
        s.add(Model(model_code='MC-1', model_name_raw='시험상품'))
        s.flush()
        ps = ProductSet(model_code='MC-1', name='기본구성')
        s.add(ps)
        s.flush()
        ch = SetChannel(set_id=ps.id, market='coupang', account_key='세소쿠팡',
                        market_product_id='157', status='linked', api_fields={})
        s.add(ch)
        s.flush()
        s.add(SetChannelOption(channel_id=ch.id, canonical_sku='K1',
                               market_option_id='111', status=opt_status,
                               mkt_price=128900, mkt_stock=3))
        s.commit()
        return ch.id
    finally:
        s.close()


# ── 상태 조회 ─────────────────────────────────────────────────

def test_아직_안_건_상품은_none(client):
    _seed(client)
    r = client.get('/api/bundles/MC-1/coupang-coupon')
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True and len(d['rows']) == 1
    assert d['rows'][0]['state'] == 'none'
    assert d['rows'][0]['targets'] == 1
    assert d['max_won'] == 300, '화면이 사장님이 정한 상한을 모른다'


def test_단추를_누르면_대기중으로_바뀐다(client):
    _seed(client)
    r = client.post('/api/bundles/MC-1/coupang-coupon')
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True and body['queued'] == 1
    # ⏰ 오늘 못 켠다는 사실을 화면이 말해야 한다(사장님 확정)
    assert '0시' in body['message'], f'다음날 0시 적용을 안 알린다: {body["message"]}'

    d = client.get('/api/bundles/MC-1/coupang-coupon').get_json()
    assert d['rows'][0]['state'] == 'queued', '넣었다면서 상태가 안 바뀐다'


def test_연동이_안_끝났으면_대기열에_안_넣고_이유를_말한다(client):
    _seed(client, opt_status='unmatched')
    r = client.post('/api/bundles/MC-1/coupang-coupon')
    assert r.status_code == 400
    body = r.get_json()
    assert body['ok'] is False
    assert '연동' in body['message'] or '옵션' in body['message']
    assert client.get('/api/bundles/MC-1/coupang-coupon'
                      ).get_json()['rows'][0]['state'] == 'none'


def test_쿠팡에_없는_상품은_그렇게_말한다(client):
    r = client.post('/api/bundles/없는코드/coupang-coupon')
    assert r.status_code == 400
    assert '쿠팡' in r.get_json()['message']


def test_처리하면_걸림으로_바뀐다(client):
    """대기 → 처리기 → 걸림. 「넣었다」가 거짓말이 아님을 끝까지 본다."""
    from lemouton.policy import coupon_service as CS
    from tests.policy.test_coupang_coupon_apply import _Fake
    ch_id = _seed(client)
    client.post('/api/bundles/MC-1/coupang-coupon')
    s = client._Session()
    try:
        CS.run_pending(s, client_for=lambda _ch: _Fake(ok_at=100),
                       now=_dt.datetime(2026, 8, 13, 15, 0, 0),
                       sleep=lambda _x: None)
    finally:
        s.close()
    row = client.get('/api/bundles/MC-1/coupang-coupon').get_json()['rows'][0]
    assert row['channel_id'] == ch_id
    assert row['state'] == 'applied'
    assert row['value'] == 100
    assert row['starts_at'] == '2026-08-14 00:00:00'
    assert row['ends_at'], '언제까지 걸렸는지를 화면이 모른다'


# ── 정책 자동 ────────────────────────────────────────────────

def test_즉시할인이_없는_정책은_쿠폰을_안_건다(client):
    """🔴 안 그러면 온 상품에 시킨 적 없는 100원 쿠폰이 저절로 걸린다."""
    from lemouton.policy import coupon_service as CS
    _seed(client)
    s = client._Session()
    try:
        from lemouton.policy.service import create_policy
        p = create_policy(s, name='할인없음')
        s.commit()
        out = CS.request_for_policy(s, p.id)
        assert out['queued'] == 0
        assert '즉시할인' in out['message']
        assert CS.pending_requests(s) == []
    finally:
        s.close()


def test_즉시할인이_적힌_정책을_붙이면_대기열에_들어간다(client):
    from lemouton.policy import coupon_service as CS
    _seed(client)
    s = client._Session()
    try:
        from lemouton.policy.service import create_policy, save_values
        p = create_policy(s, name='100원할인')
        save_values(s, policy=p, market='coupang',
                    values={'price': {'discount_unit': 'WON',
                                      'discount_value': 200}})
        s.commit()
        pid = p.id
    finally:
        s.close()
    r = client.post(f'/api/policies/{pid}/apply', json={'model_codes': ['MC-1']})
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True
    assert body['coupon']['queued'] == 1, f'정책은 붙었는데 쿠폰이 안 걸렸다: {body}'
    assert client.get('/api/bundles/MC-1/coupang-coupon'
                      ).get_json()['rows'][0]['state'] == 'queued'


# ── 처리기가 실제로 있는가 ───────────────────────────────────

def test_스케줄러에_쿠폰_처리기가_등록된다():
    """🔴 처리기 없이 대기열만 있으면 「잠시 뒤 결과가 나옵니다」가 거짓말이 된다."""
    import inspect

    from scheduler import main as SM
    assert hasattr(SM, '_coupang_coupon_tick'), '처리기 함수가 없다'
    src = inspect.getsource(SM)
    assert "id='coupang_coupon'" in src, '스케줄러에 등록하는 자리가 없다'
    assert '_coupang_coupon_tick' in src.split('def _coupang_coupon_tick')[0], \
        '함수는 있는데 add_job 이 그걸 안 부른다'


def test_처리기가_할_일이_없으면_아무것도_안_한다(client, monkeypatch):
    """1분마다 도는 틱이라, 놀 때 조용해야 한다."""
    from lemouton.policy import coupon_service as CS
    from scheduler import main as SM
    _seed(client)
    불렸나 = []
    monkeypatch.setattr(CS, 'run_pending',
                        lambda *a, **k: 불렸나.append(1) or {})
    SM._coupang_coupon_tick()
    assert 불렸나 == [], '할 일이 없는데 처리기를 돌렸다'

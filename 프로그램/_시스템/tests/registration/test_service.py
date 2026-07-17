# -*- coding: utf-8 -*-
"""등록 서비스 — 컴파일 → 호출 → 결과 기록. 마켓 호출은 가짜로 대체."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.registration.service import register_draft, RegisterBlocked, _send_live


@pytest.fixture
def session():
    engine = create_engine('sqlite://', future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def _draft(session, **kw):
    d = ProductDraft(
        name='르무통 스니커즈', brand='르무통', sale_price=75800,
        notice_type='SHOES',
        notice_json=json.dumps({
            'material': '천연가죽', 'color': '블랙', 'size': '250',
            'manufacturer': '르무통', 'caution': '직사광선 금지',
            'warranty_policy': '구매일로부터 1년',
            'after_service_director': '르무통 02-1234-5678'}, ensure_ascii=False),
        cdn_images_json=json.dumps(['https://shop-phinf.pstatic.net/a.jpg']),
        images_json=json.dumps(['https://r2.example.com/a.jpg']),
        options_json=json.dumps([{'color': '블랙', 'size': '250', 'stock': 3}],
                                ensure_ascii=False),
        # Task 6 이 A/S 폴백을 없애 이 둘이 비면 compile_smartstore 가 CompileError 를 낸다
        # → 컴파일이 게이트 전에 실패해 테스트가 엉뚱한 이유로 깨진다. 반드시 채운다.
        after_service_phone='02-1234-5678',
        after_service_guide='평일 10-18시 고객센터',
        **kw)
    session.add(d)
    session.commit()
    return d


def test_blocked_when_live_gate_off(session, monkeypatch):
    """게이트 OFF = 실등록 금지. 컴파일은 하되 blocked 로 기록."""
    monkeypatch.delenv('LIVE_REGISTER_ARMED', raising=False)
    d = _draft(session)
    with pytest.raises(RegisterBlocked):
        register_draft(session, d.id, 'smartstore', category_code='1')
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.status == 'blocked'
    assert row.market_product_id is None


def test_success_records_market_product_id(session, monkeypatch):
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session)

    def fake_send(market, body):
        assert market == 'smartstore'
        return {'originProductNo': 12345, 'smartstoreChannelProductNo': 999}

    r = register_draft(session, d.id, 'smartstore', category_code='1', _send=fake_send)
    assert r['ok'] is True
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.status == 'ok'
    assert row.market_product_id == '12345'
    assert row.registered_at is not None
    session.refresh(d)
    assert d.status == 'done'


def test_response_without_product_id_is_failure_not_success(session, monkeypatch):
    """200 을 받아도 상품ID 가 없으면 실패다 — 거짓 성공 금지."""
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session)

    def fake_send(market, body):
        return {'code': 'SUCCESS'}   # 상품ID 없음

    r = register_draft(session, d.id, 'smartstore', category_code='1', _send=fake_send)
    assert r['ok'] is False
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.status == 'failed'
    assert row.market_product_id is None
    session.refresh(d)
    assert d.status == 'failed'


def test_compile_error_recorded_and_not_sent(session, monkeypatch):
    """컴파일 실패면 마켓을 호출조차 하지 않는다."""
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session, )
    d.cdn_images_json = '[]'      # 이미지 없음 → CompileError
    session.commit()
    calls = []

    def fake_send(market, body):
        calls.append(market)
        return {}

    r = register_draft(session, d.id, 'smartstore', category_code='1', _send=fake_send)
    assert r['ok'] is False
    assert calls == [], '컴파일 실패인데 마켓을 호출했다'
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.status == 'failed'
    assert 'CDN' in (row.error_message or '')


def test_rerun_updates_same_row_not_duplicate(session, monkeypatch):
    """같은 드래프트×마켓×계정 재시도는 행을 하나만 유지한다."""
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session)
    register_draft(session, d.id, 'smartstore', category_code='1',
                   _send=lambda m, b: {'code': 'X'})
    register_draft(session, d.id, 'smartstore', category_code='1',
                   _send=lambda m, b: {'originProductNo': 7})
    rows = session.query(ProductDraftMarket).filter_by(draft_id=d.id).all()
    assert len(rows) == 1
    assert rows[0].status == 'ok'
    assert rows[0].market_product_id == '7'
    assert rows[0].account_key == 'default'


def test_non_default_account_is_rejected_not_silently_mis_recorded(session, monkeypatch):
    """★ 아직 전송에 계정이 안 붙었으므로 'default' 외에는 거절한다 — 거짓 장부 금지.

    _send_live 가 계정 없이 SmartStoreClient() 를 부르므로, 여기서 안 막으면
    'acctB' 로 기록해놓고 실제 호출은 기본 계정으로 나가 DB 가 거짓말을 하게 된다.
    (계정별 행 분리 자체는 스키마 레벨에서 tests/registration/test_models.py 가 덮는다.)
    """
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session)
    with pytest.raises(ValueError) as e:
        register_draft(session, d.id, 'smartstore', category_code='1',
                       account_key='acctB', _send=lambda m, b: {'originProductNo': 222})
    assert 'acctB' in str(e.value)
    assert session.query(ProductDraftMarket).filter_by(draft_id=d.id).count() == 0, \
        '거절했는데 행을 남기면 안 된다'


# ── _send_live: 유일하게 실마켓을 만지는 경로. 위 6개는 모두 _send 를 주입해
#    이 함수는 커버되지 않았다 → 아래 두 테스트가 SUSPENSION 후처리 사고를 잠근다.

class _FakeSSClient:
    """create 는 성공(originProductNo 반환), SUSPENSION PUT 은 주입한 대로 동작.

    실제 mark_suspension → change_sale_status 경로를 그대로 태운다:
      POST create_product → {'originProductNo': 8801}
      PUT  change_sale_status → suspend_effect() (raise 또는 에러응답)
    """
    def __init__(self, suspend_effect):
        self._suspend_effect = suspend_effect

    def path_for(self, name, **kwargs):
        return f'/fake/{name}'

    def request(self, method, path, query='', body=None, **kwargs):
        if method == 'POST':
            return {'originProductNo': 8801}
        # PUT = SUSPENSION 전환
        return self._suspend_effect()


def test_send_live_suspension_raise_does_not_eat_product_id():
    """★ create 성공 뒤 SUSPENSION 이 429/네트워크로 THROW 해도 상품ID 는 살아남는다.

    이걸 삼키지 않으면 register_draft 가 'failed·ID없음' 으로 기록 → 판매중 실상품이
    DB 밖에서 미아가 된다(거짓 성공 discipline 이 막으려는 바로 그 사고).
    """
    from shared.platforms.smartstore.client import SmartStoreRateLimitError

    def raise_429():
        raise SmartStoreRateLimitError(retry_after_sec=1)

    fake = _FakeSSClient(raise_429)
    resp = _send_live('smartstore', {'x': 1}, _client=fake)
    assert resp['originProductNo'] == 8801, '예외가 상품ID 를 먹어버렸다'
    assert resp.get('_suspend_failed') is True


def test_send_live_suspension_returns_failure_is_marked_not_fatal():
    """SUSPENSION 이 success=False 를 '반환' 하는 경우도 등록 성공을 깨지 않는다."""
    from shared.platforms.smartstore.client import SmartStoreAPIError

    def api_error():
        raise SmartStoreAPIError(status_code=400, code='X', message='거부')

    fake = _FakeSSClient(api_error)
    resp = _send_live('smartstore', {'x': 1}, _client=fake)
    assert resp['originProductNo'] == 8801
    assert resp.get('_suspend_failed') is True

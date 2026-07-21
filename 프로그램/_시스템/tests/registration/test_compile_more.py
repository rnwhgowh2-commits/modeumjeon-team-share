# -*- coding: utf-8 -*-
"""4마켓(옥션·G마켓·11번가·롯데온) 컴파일·서비스 경로 — 마켓 호출은 가짜로 대체."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration.models import ProductDraft, ProductDraftMarket
from lemouton.registration.service import register_draft, RegisterBlocked
from lemouton.registration.compile_common import CompileError
from lemouton.registration.compile_more import (
    compile_auction_gmarket, compile_eleven11, compile_lotteon)


@pytest.fixture
def session():
    engine = create_engine('sqlite://', future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def _draft(session, **kw):
    base = dict(
        name='르무통 메이트 스니커즈', brand='르무통', sale_price=135820,
        stock_quantity=1,
        images_json=json.dumps(['https://r2.example.com/a.jpg']),
        detail_html='<p>르무통 메이트</p>',
        options_json='[]',
        after_service_phone='010-1234-5678',
        after_service_guide='평일 10-18시 고객센터',
        return_fee=5000)
    base.update(kw)
    d = ProductDraft(**base)
    session.add(d)
    session.commit()
    return d


# ── compile_more 순수 검증 ──────────────────────────────────────

def test_esm_category_needs_slash(session):
    d = _draft(session)
    with pytest.raises(CompileError, match='형식'):
        compile_auction_gmarket(d, category_code='00120005002000000000')


def test_esm_spec_ok(session):
    d = _draft(session)
    spec, excluded = compile_auction_gmarket(
        d, category_code='00120005002000000000/37500700')
    assert spec['cat_code'] == '00120005002000000000'
    assert spec['site_cat_code'] == '37500700'
    assert spec['price'] == 135820 and spec['stock'] == 1
    assert excluded == []


def test_options_normalized(session):
    """[옵션 지원] 옵션이 spec 에 정규화되고 총재고=옵션합."""
    d = _draft(session, options_json=json.dumps([
        {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0},
        {'color': '블랙', 'size': '260', 'stock': 2, 'extra_price': 1000},
    ]))
    spec, excluded = compile_eleven11(d, category_code='1011634')
    assert len(spec['options']) == 2
    assert spec['stock'] == 5          # 총재고 = 옵션합
    assert excluded == []


def test_option_stock_zero_excluded_not_silent(session):
    """재고 0 옵션은 조용히 버리지 않고 excluded 로 보고."""
    d = _draft(session, options_json=json.dumps([
        {'color': '블랙', 'size': '250', 'stock': 3},
        {'color': '블랙', 'size': '270', 'stock': 0},
    ]))
    spec, excluded = compile_eleven11(d, category_code='1011634')
    assert len(spec['options']) == 1 and spec['stock'] == 3
    assert len(excluded) == 1 and excluded[0]['size'] == '270'


def test_all_options_zero_is_error(session):
    d = _draft(session, options_json=json.dumps(
        [{'color': '블랙', 'size': '250', 'stock': 0}]))
    with pytest.raises(CompileError, match='유효한 옵션'):
        compile_eleven11(d, category_code='1011634')


def test_option_extra_price_unit(session):
    """추가금 포함가도 10원 단위여야(ESM·11번가 규격)."""
    d = _draft(session, options_json=json.dumps(
        [{'color': '블랙', 'size': '250', 'stock': 1, 'extra_price': 5}]))
    with pytest.raises(CompileError, match='10원'):
        compile_eleven11(d, category_code='1011634')


def test_stock_zero_blocked(session):
    d = _draft(session, stock_quantity=0)
    with pytest.raises(CompileError, match='재고'):
        compile_lotteon(d, category_code='LO2727500650')


def test_price_unit_10won(session):
    d = _draft(session, sale_price=135825)
    with pytest.raises(CompileError, match='10원'):
        compile_eleven11(d, category_code='1011634')


def test_eleven11_needs_as_detail(session):
    d = _draft(session, after_service_guide='', after_service_phone='')
    with pytest.raises(CompileError, match='A/S'):
        compile_eleven11(d, category_code='1011634')


def test_lotteon_template_must_be_lo(session):
    """롯데온 칸에 카테고리 번호를 넣는 오입력을 즉시 잡는다."""
    d = _draft(session)
    with pytest.raises(CompileError, match='본보기'):
        compile_lotteon(d, category_code='1011634')


# ── service 경로(가짜 전송) ─────────────────────────────────────

def test_more_market_blocked_when_gate_off(session, monkeypatch):
    monkeypatch.delenv('LIVE_REGISTER_ARMED', raising=False)
    d = _draft(session)
    with pytest.raises(RegisterBlocked):
        register_draft(session, d.id, 'auction',
                       category_code='00120005002000000000/37500700')
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.status == 'blocked'


def test_more_market_success_records_pid(session, monkeypatch):
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session)
    sent = {}

    def fake_send(market, spec):
        sent['market'] = market
        sent['spec'] = spec
        return {'product_id': '6477606513', 'raw': {'ok': 1}}

    r = register_draft(session, d.id, 'auction',
                       category_code='00120005002000000000/37500700',
                       _send=fake_send)
    assert r['ok'] is True and r['market_product_id'] == '6477606513'
    assert sent['market'] == 'auction'
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.status == 'ok' and row.market_product_id == '6477606513'


def test_more_market_no_pid_is_failure(session, monkeypatch):
    """상품ID 없으면 실패(거짓 성공 금지) — 4마켓 공통 규약."""
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session)
    r = register_draft(session, d.id, 'lotteon', category_code='LO2727500650',
                       _send=lambda m, s: {'raw': {}})
    assert r['ok'] is False
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.status == 'failed' and row.error_code == 'NO_PRODUCT_ID'


def test_compile_fail_never_calls_send(session, monkeypatch):
    monkeypatch.setenv('LIVE_REGISTER_ARMED', '1')
    d = _draft(session, stock_quantity=0)
    called = []
    r = register_draft(session, d.id, 'eleven11', category_code='1011634',
                       _send=lambda m, s: called.append(m))
    assert r['ok'] is False and not called
    row = session.query(ProductDraftMarket).filter_by(draft_id=d.id).one()
    assert row.error_code == 'COMPILE'

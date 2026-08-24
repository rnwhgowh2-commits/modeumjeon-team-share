# -*- coding: utf-8 -*-
"""정책 × 마켓 → 어느 계정으로 보낼지 (Phase 4-3).

🔴 이 파일이 막는 사고
  ① 고를 방법이 없어 **늘 'default' 계정으로** 나가던 것 — 마켓마다 계정이
     여러 개여도 전부 한 계정으로 갔다.
  ② 없는 계정을 저장하면 화면엔 걸린 것처럼 보이는데 전송이 엉뚱한 데로 간다.
  ③ 값이 깨졌다고 전송이 멈추면 안 된다 — 기본 계정으로 계속 간다.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.policy import market_accounts as MA
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import MarketPolicy
from shared.db import Base


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _정책(db, **kw):
    p = MarketPolicy(name='시험 정책', **kw)
    db.add(p)
    db.commit()
    return p


def _계정(db, key, market, name=None):
    from lemouton.sourcing.models_v2 import UploadAccount
    a = UploadAccount(account_key=key, market=market,
                      display_name=name or key, env_prefix=key.upper())
    db.add(a)
    db.commit()
    return a


# ── 안 고른 상태가 정상 ───────────────────────────────────────────────────

def test_안_고르면_기본_계정이다(db):
    """🔴 이 칸이 생겼다고 달라지는 정책이 하나도 없어야 한다."""
    p = _정책(db)
    assert MA.account_for(p, 'coupang') == 'default'
    assert MA.all_for(p) == {}
    assert MA.keys_for(p, ['coupang', 'lotteon']) == {}


def test_값이_깨져도_전송이_안_멈춘다(db):
    """읽다 실패했다고 멈추면 잘 나가던 정책이 조용히 죽는다."""
    p = _정책(db, market_accounts='{이건 JSON 이 아니다')
    assert MA.all_for(p) == {}
    assert MA.account_for(p, 'coupang') == 'default'


def test_리스트가_들어와_있어도_안_터진다(db):
    p = _정책(db, market_accounts='["coupang"]')
    assert MA.all_for(p) == {}


# ── 고르면 그 계정으로 ────────────────────────────────────────────────────

def test_고른_계정이_남는다(db):
    _계정(db, '르무통_본계_coupang', 'coupang', '르무통 본계')
    p = _정책(db)
    MA.set_accounts(db, policy=p, values={'coupang': '르무통_본계_coupang'})
    db.commit()
    assert MA.account_for(p, 'coupang') == '르무통_본계_coupang'
    assert MA.account_for(p, 'lotteon') == 'default', '안 고른 마켓은 그대로'


def test_안_고른_마켓은_키_자체를_안_넣는다(db):
    """'default' 를 굳이 실어 보내면 「일부러 골랐다」와 「안 골랐다」가 안 갈린다."""
    _계정(db, 'A_coupang', 'coupang')
    p = _정책(db)
    MA.set_accounts(db, policy=p, values={'coupang': 'A_coupang'})
    assert MA.keys_for(p, ['coupang', 'lotteon']) == {'coupang': 'A_coupang'}


def test_빈_값으로_다시_안_고름으로_돌린다(db):
    _계정(db, 'A_coupang', 'coupang')
    p = _정책(db)
    MA.set_accounts(db, policy=p, values={'coupang': 'A_coupang'})
    MA.set_accounts(db, policy=p, values={'coupang': ''})
    db.commit()
    assert MA.account_for(p, 'coupang') == 'default'
    assert p.market_accounts is None, '다 지우면 칸도 비운다'


# ── 못 고르게 막는 것 ─────────────────────────────────────────────────────

def test_없는_계정은_못_고른다(db):
    """🔴 저장되면 화면엔 걸린 것처럼 보이는데 전송이 엉뚱한 데로 간다."""
    p = _정책(db)
    with pytest.raises(ValueError, match='그런 계정이 없'):
        MA.set_accounts(db, policy=p, values={'coupang': '없는계정'})


def test_다른_마켓_계정은_못_고른다(db):
    """롯데온 계정을 쿠팡 자리에 넣으면 전송이 죽는다."""
    _계정(db, 'A_lotteon', 'lotteon')
    p = _정책(db)
    with pytest.raises(ValueError, match='그런 계정이 없'):
        MA.set_accounts(db, policy=p, values={'coupang': 'A_lotteon'})


def test_모르는_마켓은_못_고른다(db):
    p = _정책(db)
    with pytest.raises(ValueError, match='모르는 마켓'):
        MA.set_accounts(db, policy=p, values={'11st': 'X'})


# ── 화면이 쓸 목록 ────────────────────────────────────────────────────────

def test_마켓별_계정_목록을_준다(db):
    _계정(db, 'A_coupang', 'coupang', '쿠팡 본계')
    _계정(db, 'B_coupang', 'coupang', '쿠팡 부계')
    _계정(db, 'A_lotteon', 'lotteon', '롯데온 본계')
    got = MA.choices_for(db)
    assert [x['label'] for x in got['coupang']] == ['쿠팡 본계', '쿠팡 부계']
    assert [x['key'] for x in got['lotteon']] == ['A_lotteon']
    assert got['smartstore'] == [], '계정이 없는 마켓은 빈 목록'


def test_안_쓰는_계정은_목록에_없다(db):
    a = _계정(db, 'A_coupang', 'coupang')
    a.is_active = False
    db.commit()
    assert MA.choices_for(db)['coupang'] == []


# ── 전송 경로까지 이어지나 ────────────────────────────────────────────────

def test_전송이_고른_계정을_실제로_쓴다(db):
    """🔴 이 다리가 없으면 화면에서 골라도 늘 기본 계정으로 나간다.

    `send/runner.py:_register` 가 `preflight_rows(keys=...)` 로 넘기는지를
    소스에서 확인한다 — 실제 전송을 태우려면 마켓 API 가 필요하다.
    """
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'send' / 'runner.py').read_text(encoding='utf-8')
    assert 'keys=_keys' in 소스, '전송이 정책이 고른 계정을 안 넘긴다'
    assert 'MA.keys_for' in 소스


# ── 창구·화면 ─────────────────────────────────────────────────────────────

import os  # noqa: E402

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


def _계정만들기(client, key, market, name):
    s = client._Session()
    try:
        from lemouton.sourcing.models_v2 import UploadAccount
        s.add(UploadAccount(account_key=key, market=market,
                            display_name=name, env_prefix=key.upper()))
        s.commit()
    finally:
        s.close()


def test_창구가_고른_계정과_목록을_준다(client):
    pid = client.post('/api/policies', json={'name': 'P'}).get_json()['id']
    _계정만들기(client, 'A_coupang', 'coupang', '쿠팡 본계')
    j = client.get(f'/api/policies/{pid}/accounts').get_json()
    assert j['ok'] is True
    assert j['chosen'] == {}
    assert [x['label'] for x in j['choices']['coupang']] == ['쿠팡 본계']


def test_창구로_고르고_다시_읽는다(client):
    pid = client.post('/api/policies', json={'name': 'P'}).get_json()['id']
    _계정만들기(client, 'A_coupang', 'coupang', '쿠팡 본계')
    r = client.post(f'/api/policies/{pid}/accounts',
                    json={'accounts': {'coupang': 'A_coupang'}})
    assert r.status_code == 200
    assert client.get(f'/api/policies/{pid}/accounts').get_json()['chosen'] == {
        'coupang': 'A_coupang'}


def test_창구도_없는_계정을_막는다(client):
    pid = client.post('/api/policies', json={'name': 'P'}).get_json()['id']
    r = client.post(f'/api/policies/{pid}/accounts',
                    json={'accounts': {'coupang': '없는것'}})
    assert r.status_code == 400
    assert '그런 계정이 없' in r.get_json()['message']


def test_화면에_계정_고르는_자리가_있다(client):
    pid = client.post('/api/policies', json={'name': 'P'}).get_json()['id']
    html = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert 'id="acctsel"' in html
    assert '보낼 계정' in html
    assert '/api/policies/' in html and '/accounts' in html


def test_마켓_공통_탭엔_계정_자리가_없다(client):
    """어느 마켓 얘긴지 정해지지 않았는데 계정을 고르게 하면 안 된다."""
    pid = client.post('/api/policies', json={'name': 'P'}).get_json()['id']
    html = client.get(f'/policies/{pid}').get_data(as_text=True)
    assert 'id="acctsel"' not in html

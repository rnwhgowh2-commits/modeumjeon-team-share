# -*- coding: utf-8 -*-
"""쿠폰 걸기 **대기열** — 단추·정책 자동이 요청하고, 스케줄러가 실제로 처리한다.

■ 왜 대기열인가
    쿠폰 한 번 걸기는 「만들기 → 접수 확인 → 붙이기 → 접수 확인」이고, 거부되면
    300원까지 최대 21번 되풀이한다. 한 번에 몇 분이 걸릴 수 있어 **화면이 기다릴 수
    없다.** 그래서 요청만 남기고 스케줄러가 처리한다.

■ 🔴 「대기열에 넣었다」 ≠ 「처리된다」
    처리기가 없으면 그 말은 거짓말이 된다(라이브에서 실제로 겪었다).
    그래서 처리기(`run_pending`)와 스케줄러 등록을 같이 넣고, 화면은 **기록**을 읽어
    「대기 중 / 걸림 / 실패」를 가른다.

■ 🔴 요청은 처리한 뒤 **반드시 지운다**
    안 지우면 스케줄러가 1분마다 같은 채널에 쿠폰을 또 만든다.
    (한 옵션은 쿠폰 하나에만 붙으므로 두 번째부터는 전부 거부되고 빈 쿠폰만 쌓인다.)

■ 🔴 이미 걸린 쿠폰이 있으면 **먼저 내리고** 새로 건다
    단추를 두 번 누르거나 정책 할인값을 바꿨을 때, 옛 쿠폰을 안 내리고 새로 만들면
    옵션이 전부 [CIR08] 로 거부된다.
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in ("lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
           "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
           "lemouton.uploader.models", "lemouton.templates.models",
           "lemouton.inventory.models", "lemouton.sources.models",
           "lemouton.multitenancy.models", "lemouton.audit.models",
           "lemouton.mapping.models", "lemouton.sets.models"):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.policy import coupon_service as CS              # noqa: E402
from lemouton.sets.models import SetChannel, SetChannelOption  # noqa: E402
from tests.policy.test_coupang_coupon_apply import _Fake       # noqa: E402

_NOW = _dt.datetime(2026, 8, 13, 15, 0, 0)


@pytest.fixture
def db():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _chan(db, *, set_id=1, market='coupang', api_fields=None, opt='111'):
    ch = SetChannel(set_id=set_id, market=market, account_key='세소쿠팡',
                    market_product_id='157', status='linked',
                    api_fields=api_fields if api_fields is not None else {})
    db.add(ch)
    db.flush()
    if opt:
        db.add(SetChannelOption(channel_id=ch.id, canonical_sku='K1',
                                market_option_id=opt, status='matched',
                                mkt_price=128900, mkt_stock=3))
    db.commit()
    return ch


def _pending(db, client, **kw):
    kw.setdefault('now', _NOW)
    kw.setdefault('sleep', lambda _s: None)
    kw.setdefault('client_for', lambda _ch: client)
    return CS.run_pending(db, **kw)


# ── 요청 남기기 ───────────────────────────────────────────────

def test_단추가_요청을_남기고_대기열에_뜬다(db):
    ch = _chan(db)
    CS.request_for_channel(db, ch, now=_NOW, by='단추')
    assert [c.id for c in CS.pending_requests(db)] == [ch.id]
    req = (ch.api_fields or {}).get(CS.REQUEST_KEY)
    assert req['by'] == '단추' and req['at']


def test_요청은_DB에_남는다(db):
    ch = _chan(db)
    CS.request_for_channel(db, ch, now=_NOW)
    db.expire_all()
    again = db.get(SetChannel, ch.id)
    assert (again.api_fields or {}).get(CS.REQUEST_KEY)


def test_요청해도_남의_값을_안_지운다(db):
    ch = _chan(db, api_fields={'남의값': 7})
    CS.request_for_channel(db, ch, now=_NOW)
    db.refresh(ch)
    assert ch.api_fields['남의값'] == 7


def test_쿠팡_아닌_채널은_대기열에_안_넣는다(db):
    ch = _chan(db, market='smartstore')
    r = CS.request_for_channel(db, ch, now=_NOW)
    assert r['ok'] is False
    assert CS.pending_requests(db) == []


def test_붙일_옵션이_없으면_대기열에_안_넣는다(db):
    """🔴 넣어 봐야 매번 실패한다 — 왜 안 되는지를 그 자리에서 말한다."""
    ch = _chan(db, opt=None)
    r = CS.request_for_channel(db, ch, now=_NOW)
    assert r['ok'] is False
    assert '옵션' in r['message']
    assert CS.pending_requests(db) == []


# ── 처리기 ───────────────────────────────────────────────────

def test_처리하면_실제로_쿠폰이_걸린다(db):
    ch = _chan(db)
    CS.request_for_channel(db, ch, now=_NOW)
    c = _Fake(ok_at=100)
    out = _pending(db, c)
    assert out['done'] == 1 and out['failed'] == 0
    assert len(c.created) == 1
    assert CS.record_of(ch)['ok'] is True


def test_처리한_요청은_지운다(db):
    """🔴 안 지우면 1분마다 같은 채널에 쿠폰을 또 만든다."""
    ch = _chan(db)
    CS.request_for_channel(db, ch, now=_NOW)
    c = _Fake(ok_at=100)
    _pending(db, c)
    assert CS.pending_requests(db) == []
    _pending(db, c)                       # 한 번 더 돌려도
    assert len(c.created) == 1, '요청이 안 지워져 쿠폰을 또 만들었다'


def test_실패해도_요청을_지우고_왜인지_남긴다(db):
    """🔴 안 지우면 영영 되풀이한다. 대신 **사유가 화면에 남아야** 한다."""
    ch = _chan(db)
    CS.request_for_channel(db, ch, now=_NOW)
    out = _pending(db, _Fake(ok_at=100000))
    assert out['done'] == 0 and out['failed'] == 1
    assert CS.pending_requests(db) == []
    rec = CS.record_of(ch)
    assert rec['ok'] is False and '310' in rec['message']


def test_클라이언트를_못_만들면_사유를_남기고_요청을_지운다(db):
    """계정이 없거나 열쇠가 없는 경우 — 조용히 되풀이하지 않는다."""
    ch = _chan(db)
    CS.request_for_channel(db, ch, now=_NOW)
    out = _pending(db, None, client_for=lambda _ch: None)
    assert out['failed'] == 1
    assert CS.pending_requests(db) == []
    assert '계정' in CS.record_of(ch)['message']


def test_한_번에_처리할_수를_지킨다(db):
    for i in range(5):
        CS.request_for_channel(db, _chan(db, set_id=i + 1), now=_NOW)
    out = _pending(db, _Fake(ok_at=100), limit=2)
    assert out['done'] == 2
    assert len(CS.pending_requests(db)) == 3


def test_연장_대상도_같은_틱에서_처리한다(db):
    """스윕 한 곳에서 「새로 걸기」와 「연장」을 다 본다."""
    새것 = _chan(db, set_id=1)
    CS.request_for_channel(db, 새것, now=_NOW)
    연장 = _chan(db, set_id=2, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 777, 'value': 100,
        'ends_at': '2026-08-20 23:59:59'}})
    c = _Fake(ok_at=100)
    out = _pending(db, c)
    assert out['done'] == 1 and out['renewed'] == 1
    assert 777 in c.expired, '연장인데 옛 쿠폰을 안 내렸다'
    assert CS.record_of(연장)['coupon_id'] != 777


# ── 다시 걸 때는 옛 쿠폰을 먼저 내린다 ────────────────────────

def test_이미_걸린_채널에_다시_요청하면_옛것을_먼저_내린다(db):
    """🔴 단추를 두 번 누르거나 할인값을 바꿨을 때 — 안 내리면 전부 [CIR08]."""
    ch = _chan(db, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 555, 'value': 100,
        'ends_at': '2027-12-31 23:59:59'}})
    CS.request_for_channel(db, ch, now=_NOW)

    order = []

    class _Watch(_Fake):
        def request(self, method, path, body=None, query=''):
            if method == 'PUT' and '/coupons/' in path:
                order.append(('expire', int(path.rsplit('/', 1)[1])))
            elif method == 'POST' and path.endswith('/coupon'):
                order.append(('create', None))
            return _Fake.request(self, method, path, body=body, query=query)

    c = _Watch(ok_at=100)
    _pending(db, c)
    assert order and order[0] == ('expire', 555), f'옛 쿠폰을 먼저 안 내렸다: {order}'
    assert CS.record_of(ch)['coupon_id'] != 555


def test_정책이_준_값이_배운_값을_이긴다(db):
    """할인값을 바꾸려고 다시 거는 것인데 옛 값을 쓰면 안 바뀐다."""
    ch = _chan(db, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 555, 'value': 100, 'ends_at': '2027-12-31 23:59:59'}})
    CS.request_for_channel(db, ch, now=_NOW)
    c = _Fake(ok_at=100)
    _pending(db, c, discount_for=lambda _s, _ch: {'value': 250, 'unitType': 'WON'})
    assert CS.record_of(ch)['value'] == 250

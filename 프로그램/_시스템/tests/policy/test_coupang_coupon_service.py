# -*- coding: utf-8 -*-
"""쿠팡 쿠폰을 **어느 상품에** 걸 것인가 — 대상 찾기 · 기록 남기기 · 자동연장.

셈과 순서는 `coupon_apply` 가 한다. 여기는 「우리 어느 옵션인가 · 결과를 어디 적나」다.

■ 🔴 자동연장은 **순서가 목숨이다**
    쿠팡은 쿠폰을 수정하지 못한다(문서: 「최초 생성 시 설정한 쿠폰 적용 상품을 추후
    삭제할 수 없습니다 … 기존에 발행한 쿠폰을 중지하고 새로운 쿠폰을 생성해야 합니다」).
    그래서 연장 = **옛 쿠폰 내리기 → 새 쿠폰 만들기 → 다시 붙이기**.
    옛 것을 안 내리고 새로 만들면 옵션이 전부 [CIR08]「이미 다른 쿠폰에 발행」으로
    거부된다 — 한 옵션은 쿠폰 **하나에만** 붙는다(2026-08-06 라이브 실측).

■ 🔴 대상은 `status='matched'` 옵션뿐
    unmatched/ambiguous/duplicate 는 우리가 어느 마켓 옵션인지 **모르는** 것이다.
    모르는 것에 쿠폰을 걸면 엉뚱한 상품이 깎인다.

■ 🔴 `api_fields` 는 통째로 갈아엎지 않는다
    다른 값이 같이 사는 주머니다. 덮어쓰면 남의 값이 조용히 사라진다.
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

from lemouton.policy import coupon_service as CS          # noqa: E402
from lemouton.sets.models import SetChannel, SetChannelOption   # noqa: E402
from tests.policy.test_coupang_coupon_apply import _Fake        # noqa: E402

_NOW = _dt.datetime(2026, 8, 13, 15, 0, 0)


@pytest.fixture
def db():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _chan(db, *, market='coupang', opts=(('K1', '111', 'matched'),),
          api_fields=None, set_id=1):
    ch = SetChannel(set_id=set_id, market=market, account_key='세소쿠팡',
                    market_product_id='15782833359', status='linked',
                    api_fields=api_fields if api_fields is not None else {})
    db.add(ch)
    db.flush()
    for sku, oid, st in opts:
        db.add(SetChannelOption(channel_id=ch.id, canonical_sku=sku,
                                market_option_id=oid, status=st,
                                mkt_price=128900, mkt_stock=5))
    db.commit()
    return ch


def _run(db, ch, client, **kw):
    kw.setdefault('now', _NOW)
    kw.setdefault('sleep', lambda _s: None)
    return CS.run_for_channel(db, ch, client=client, **kw)


# ── 대상 고르기 ───────────────────────────────────────────────

def test_matched_옵션만_대상이다(db):
    """🔴 모르는 옵션에 쿠폰을 걸면 엉뚱한 상품이 깎인다."""
    ch = _chan(db, opts=[('K1', '111', 'matched'),
                         ('K2', '222', 'unmatched'),
                         ('K3', '333', 'ambiguous'),
                         ('K4', '444', 'duplicate'),
                         ('K5', '555', 'matched')])
    assert sorted(CS.targets_for(db, ch)) == ['111', '555']


def test_옵션ID가_비면_안_넣는다(db):
    ch = _chan(db, opts=[('K1', None, 'matched'), ('K2', '', 'matched')])
    assert CS.targets_for(db, ch) == []


def test_쿠팡이_아닌_채널은_하지_않는다(db):
    """스스는 즉시할인 칸이 따로 있다 — 쿠폰 경로를 태우면 두 번 깎인다."""
    ch = _chan(db, market='smartstore')
    c = _Fake(ok_at=100)
    r = _run(db, ch, c)
    assert r['ok'] is False
    assert c.created == []
    assert '쿠팡' in r['message']


def test_붙일_옵션이_없으면_쿠폰을_안_만든다(db):
    ch = _chan(db, opts=[('K1', '111', 'unmatched')])
    c = _Fake(ok_at=100)
    r = _run(db, ch, c)
    assert r['ok'] is False
    assert c.created == []


# ── 결과 기록 ─────────────────────────────────────────────────

def test_성공하면_채널에_기록을_남긴다(db):
    """자동연장이 「언제 끝나나」를 알려면 남아 있어야 한다."""
    ch = _chan(db)
    c = _Fake(ok_at=100)
    r = _run(db, ch, c)
    assert r['ok'] is True
    rec = CS.record_of(ch)
    assert rec['coupon_id'] == r['coupon_id']
    assert rec['value'] == 100
    assert rec['ends_at'] == '2026-12-31 23:59:59'
    assert rec['starts_at'] == '2026-08-14 00:00:00'
    assert rec['attached'] == ['111']
    assert rec['ok'] is True
    assert rec['at'], '언제 걸었는지가 없다'
    assert rec['sale_price'] == 128900, '다음 상품이 배울 재료(판매가)가 없다'


def test_실패해도_기록을_남긴다(db):
    """🔴 실패가 안 남으면 화면이 「아직 안 해 봤다」와 못 가른다."""
    ch = _chan(db)
    r = _run(db, ch, _Fake(ok_at=100000))
    assert r['ok'] is False
    rec = CS.record_of(ch)
    assert rec['ok'] is False
    assert rec['coupon_id'] is None
    assert rec['tried'] == 21, '몇 번 해 봤는지가 안 남았다'
    assert '310' in rec['message']


def test_api_fields_의_다른_값을_안_지운다(db):
    """🔴 통째로 덮어쓰면 남의 값이 조용히 사라진다."""
    ch = _chan(db, api_fields={'남의값': 1, '또다른값': {'a': 2}})
    _run(db, ch, _Fake(ok_at=100))
    db.refresh(ch)
    assert ch.api_fields['남의값'] == 1
    assert ch.api_fields['또다른값'] == {'a': 2}
    assert ch.api_fields[CS.COUPON_KEY]['ok'] is True


def test_기록이_DB에_실제로_저장된다(db):
    """🔴 JSON 칸은 통째로 다시 넣어야 SQLAlchemy 가 바뀐 걸 안다."""
    ch = _chan(db)
    _run(db, ch, _Fake(ok_at=100))
    db.expire_all()
    again = db.get(SetChannel, ch.id)
    assert (again.api_fields or {}).get(CS.COUPON_KEY, {}).get('coupon_id')


# ── 자동연장 ─────────────────────────────────────────────────

def test_끝날이_가까운_채널을_찾아_준다(db):
    끝남 = _chan(db, set_id=1, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 1, 'ends_at': '2026-08-20 23:59:59'}})
    한참 = _chan(db, set_id=2, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 2, 'ends_at': '2027-12-31 23:59:59'}})
    없음 = _chan(db, set_id=3)
    due = CS.due_renewals(db, now=_NOW, days=14)
    ids = [c.id for c in due]
    assert 끝남.id in ids
    assert 한참.id not in ids, '한참 남았는데 괜히 다시 만든다'
    assert 없음.id not in ids, '건 적도 없는 채널을 연장 대상으로 봤다'


def test_이미_지난_쿠폰도_연장_대상이다(db):
    """만료된 채로 두면 그 상품만 조용히 할인이 사라진다."""
    ch = _chan(db, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 1, 'ends_at': '2026-01-01 00:00:00'}})
    assert ch.id in [c.id for c in CS.due_renewals(db, now=_NOW, days=14)]


def test_연장은_옛_쿠폰을_먼저_내리고_새로_만든다(db):
    """🔴🔴 순서가 목숨이다 — 안 내리고 만들면 옵션이 전부 [CIR08] 로 거부된다."""
    ch = _chan(db, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 777, 'value': 100,
        'ends_at': '2026-08-20 23:59:59'}})

    order = []

    class _Watch(_Fake):
        def request(self, method, path, body=None, query=''):
            if method == 'PUT' and '/coupons/' in path:
                order.append(('expire', int(path.rsplit('/', 1)[1])))
            elif method == 'POST' and path.endswith('/coupon'):
                order.append(('create', None))
            return _Fake.request(self, method, path, body=body, query=query)

    c = _Watch(ok_at=100)
    r = CS.renew_channel(db, ch, client=c, now=_NOW, sleep=lambda _s: None)
    assert r['ok'] is True
    assert order[0] == ('expire', 777), f'옛 쿠폰을 먼저 안 내렸다: {order}'
    assert order[1][0] == 'create'
    assert CS.record_of(ch)['coupon_id'] != 777


def test_옛_쿠폰을_못_내리면_새로_만들지_않는다(db):
    """🔴 못 내린 채로 만들면 옵션이 전부 거부되고 빈 쿠폰만 하나 더 생긴다."""
    ch = _chan(db, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 777, 'ends_at': '2026-08-20 23:59:59'}})

    class _NoExpire(_Fake):
        def request(self, method, path, body=None, query=''):
            if method == 'PUT' and '/coupons/' in path:
                return {'code': 500, 'message': 'nope', 'data': {'success': False}}
            return _Fake.request(self, method, path, body=body, query=query)

    c = _NoExpire(ok_at=100)
    r = CS.renew_channel(db, ch, client=c, now=_NOW, sleep=lambda _s: None)
    assert r['ok'] is False
    assert c.created == [], '옛 쿠폰을 못 내렸는데 새로 만들었다'
    assert '내리' in r['message'] or '내려' in r['message']
    assert CS.record_of(ch)['coupon_id'] == 777, '못 내렸는데 기록을 지웠다'


def test_연장이_기록의_값을_이어받는다(db):
    """지난번에 130원에서 됐으면 100원부터 다시 헤매지 않는다."""
    ch = _chan(db, api_fields={CS.COUPON_KEY: {
        'ok': True, 'coupon_id': 777, 'value': 130, 'sale_price': 128900,
        'ends_at': '2026-08-20 23:59:59'}})
    c = _Fake(ok_at=130)
    r = CS.renew_channel(db, ch, client=c, now=_NOW, sleep=lambda _s: None)
    assert r['ok'] is True
    assert [a['value'] for a in r['attempts']] == [130], \
        '지난번에 통한 값을 안 쓰고 100원부터 다시 헤맸다'

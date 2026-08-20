# -*- coding: utf-8 -*-
"""같은 소싱처 URL 을 **다른 초안으로** 두 번 올리는 것을 막는다.

━━ 지금 있는 가드의 빈틈 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`_ledger_guard`(drafts.py:484)는 `ProductDraftMarket.draft_id == draft_id` 로만 본다.
즉 **「이 초안이 이 마켓에 이미 올라갔나」** 만 답한다.

그런데 같은 상품을 두 번 수집하면 초안이 **두 벌**이 된다(크롤 재실행·검색필터 겹침·
소싱처가 URL 을 바꿔 다는 경우). 그러면 두 초안 모두 장부가 비어 있으므로 가드를
그대로 통과해 **같은 상품이 같은 마켓에 두 번 등록**된다 = 마켓 중복 = 계정 위험.

대량등록에서는 이 일이 손이 아니라 배치로 일어난다 — 한 번에 수백 건이 겹칠 수 있다.
설계서 §6-4 「등록 직전 `(소싱처URL, 마켓, 계정)` 중복 방어」가 이것이다.
이관(더망고 자산 16.8만 건) 때도 이 가드가 있어야 안전하다.

━━ 🔴 빠지기 쉬운 함정 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`source_url` 은 **수기 등록 초안에서 None/빈값**이다(models.py:106 — "수기 드래프트는
None, 「크롤에서 왔는가」의 판별자"). 빈값끼리 같다고 보면 **수기 초안 전부가 서로를
막는다.** 「빈 값은 0도 전체도 아니다」 — 빈값은 판정에서 아예 뺀다.
"""
import pytest

from webapp.routes.bulk.drafts import _ledger_guard

_MADE = []      # 이 파일이 만든 draft_id 만 정확히 지운다


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('LIVE_REGISTER_ARMED', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft, ProductDraftMarket
    s = SessionLocal()
    try:
        for did in _MADE:
            for row in s.query(ProductDraftMarket).filter_by(draft_id=did).all():
                s.delete(row)
            row = s.query(ProductDraft).filter_by(id=did).first()
            if row is not None:
                s.delete(row)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE.clear()


def _draft(session, *, source_url):
    """초안 1건을 직접 심는다 — 라우트를 타면 URL 을 지정할 수 없다."""
    from lemouton.registration.models import ProductDraft
    d = ProductDraft(name='중복차단 시험 상품', sale_price=39000,
                     source_url=source_url)
    session.add(d)
    session.commit()
    _MADE.append(d.id)
    return d.id


def _registered(session, draft_id, *, market, account_key='default',
                pid='X123', status='ok'):
    """그 초안이 그 마켓에 올라갔다는 장부 행."""
    from lemouton.registration.models import ProductDraftMarket
    row = ProductDraftMarket(draft_id=draft_id, market=market,
                             account_key=account_key, status=status,
                             market_product_id=pid)
    session.add(row)
    session.commit()


URL = 'https://www.musinsa.com/products/3976350'


# ── 🔴 막아야 하는 것 ──────────────────────────────────────────────────────

def test_같은_소싱처URL_의_다른_초안이_이미_올라갔으면_막는다(client):
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        first = _draft(s, source_url=URL)
        _registered(s, first, market='smartstore', pid='SS777')
        second = _draft(s, source_url=URL)        # 같은 상품을 또 수집한 상황

        kind, pid, _code, _detail = _ledger_guard(s, second, 'smartstore', 'default')

        assert kind == 'dup_source', f'막지 않았다: kind={kind!r}'
        assert pid == 'SS777', '어느 상품과 겹치는지 상품번호를 알려줘야 한다'
    finally:
        s.close()


# ── 🔴 막으면 안 되는 것 (막이개가 길을 막으면 그게 더 큰 사고다) ──────────

def test_소싱처URL_이_비어_있으면_서로_중복으로_보지_않는다(client):
    """수기 등록 초안은 URL 이 없다 — 빈값끼리 묶으면 전부 서로를 막는다."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        first = _draft(s, source_url=None)
        _registered(s, first, market='smartstore', pid='SS777')
        second = _draft(s, source_url=None)

        kind, _pid, _c, _d = _ledger_guard(s, second, 'smartstore', 'default')

        assert kind is None, f'수기 초안끼리 막혔다: kind={kind!r}'
    finally:
        s.close()


def test_다른_마켓이면_막지_않는다(client):
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        first = _draft(s, source_url=URL)
        _registered(s, first, market='smartstore', pid='SS777')
        second = _draft(s, source_url=URL)

        kind, _pid, _c, _d = _ledger_guard(s, second, 'coupang', 'default')

        assert kind is None, '스스에 올린 것이 쿠팡 등록을 막았다'
    finally:
        s.close()


def test_앞선_등록이_실패였으면_막지_않는다(client):
    """재시도는 막지 않는다 — 기존 `_ledger_guard` 규약과 같다."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        first = _draft(s, source_url=URL)
        _registered(s, first, market='smartstore', pid=None, status='failed')
        second = _draft(s, source_url=URL)

        kind, _pid, _c, _d = _ledger_guard(s, second, 'smartstore', 'default')

        assert kind is None, '실패한 등록이 다음 시도를 막았다'
    finally:
        s.close()


# ── 배선: 판정기가 답해도 화면·등록이 안 쓰면 「작동하는 척하는 가드」다 ──────

def test_사전점검_화면이_중복을_사유와_함께_보여준다(client):
    """판정만 하고 화면이 ready 로 내주면, 그 한 번의 클릭이 곧 중복 등록이다."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        first = _draft(s, source_url=URL)
        _registered(s, first, market='smartstore', pid='SS777')
        second = _draft(s, source_url=URL)
    finally:
        s.close()

    r = client.post(f'/bulk/api/drafts/{second}/preflight',
                    json={'markets': ['smartstore'],
                          'category_codes': {'smartstore': '50000167'}})
    row = {x['market']: x for x in r.get_json()['rows']}['smartstore']

    assert row['status'] == 'dup_source', row
    assert row['status'] != 'ready', '중복인데 올릴 수 있다고 보여줬다'
    assert 'SS777' in row['reason'], row['reason']


def test_등록_라우트도_같은_근거로_막는다(client):
    """점검과 등록의 판정기는 하나여야 한다 — 「점검은 초록인데 등록은 나감」 금지."""
    from webapp.routes.bulk.drafts import _register_one
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        first = _draft(s, source_url=URL)
        _registered(s, first, market='smartstore', pid='SS777')
        second = _draft(s, source_url=URL)

        out = _register_one(s, second, 'smartstore', category_code='50000167',
                            account_key='default', vendor=None)

        assert out['status'] == 'already', out
        assert out['error_code'] == 'DUP_SOURCE_URL', out
        assert out['market_product_id'] == 'SS777', out
    finally:
        s.close()


def test_자기_자신은_중복으로_치지_않는다(client):
    """자기 초안의 장부는 기존 'registered' 판정이 맡는다 — 두 번 세면 안 된다."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        only = _draft(s, source_url=URL)
        _registered(s, only, market='smartstore', pid='SS777')

        kind, pid, _c, _d = _ledger_guard(s, only, 'smartstore', 'default')

        assert kind == 'registered', f'자기 장부는 기존 판정이어야 한다: {kind!r}'
        assert pid == 'SS777'
    finally:
        s.close()

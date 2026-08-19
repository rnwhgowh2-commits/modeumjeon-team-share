# -*- coding: utf-8 -*-
"""내마켓 불러오기 — 여러 상품 선택 → 「모델」 축 매트릭스 1개로 병합.

사장님 확정(2026-08-19): 여러 마켓 상품을 고르면 상품마다 매트릭스를 따로
만들지 않고, 상품마다 「모델」 축 값 하나씩을 받는 매트릭스 1개로 합친다.
단건 가져오기(import_market_product)와 같은 원칙을 그대로 따른다 —
실패하면 아무것도 안 만든다(all-or-nothing), 마켓 상품번호·옵션번호를
빠짐없이 기록한다, 이미 가져온 상품은 다시 못 담는다.
"""
import pytest


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models          # noqa: F401
    import lemouton.sourcing.models_v2       # noqa: F401
    import lemouton.matrix.models            # noqa: F401
    import lemouton.catalog.models           # noqa: F401
    import lemouton.uploader.models          # noqa: F401
    import shared.display_no                 # noqa: F401
    from shared.db import Base
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _seed(s, *, pid, market='smartstore', acct='스스검사계정', name=None, brand='르무통'):
    from lemouton.catalog.models import MarketProduct
    from lemouton.sourcing.models_v2 import UploadAccount
    if not s.query(UploadAccount).filter_by(account_key=acct).first():
        s.add(UploadAccount(account_key=acct, display_name=acct,
                            market=market, env_prefix='SS_TEST', is_active=True))
    mp = MarketProduct(market=market, account_key=acct, market_product_id=pid,
                       name=(name or f'상품{pid}'), brand=brand, status='sale')
    s.add(mp)
    s.flush()
    return mp


class _FR:
    def __init__(self, success, name, options, error=None):
        self.success, self.product_name = success, name
        self.options, self.error = options, error


class _MO:
    def __init__(self, oid, color, size):
        self.option_id, self.color, self.size = oid, color, size


def _fetcher(per_pid: dict, *, fail_pid: str | None = None, fail_error='읽기 실패'):
    """pid → options 매핑을 답하는 가짜 fetcher. fail_pid 만 실패로 답한다."""
    def f(market, pid, env_prefix=None):
        f.calls = getattr(f, 'calls', []) + [pid]
        if pid == fail_pid:
            return _FR(False, None, [], error=fail_error)
        return _FR(True, f'마켓상품{pid}', per_pid[pid])
    return f


def _items(*specs):
    """[(pid, model_name), ...] → import_market_products_merged 의 items 인자."""
    return [{'market': 'smartstore', 'account_key': '스스검사계정',
             'market_product_id': pid, 'model_name': mn} for pid, mn in specs]


def test_두_상품이_모델_축_하나로_합쳐진다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    s = session
    _seed(s, pid='m1'); _seed(s, pid='m2')
    per_pid = {
        'm1': [_MO('a1', '블랙', '230'), _MO('a2', '블랙', '240')],
        'm2': [_MO('b1', '블랙', '230'), _MO('b2', '화이트', '230')],
    }
    out = import_market_products_merged(
        s, items=_items(('m1', '메이트'), ('m2', '스위트')),
        name='병합매트릭스', brand='르무통', fetcher=_fetcher(per_pid))
    s.commit()
    assert out['ok'] is True, out
    assert out['options'] == 4                       # 2 + 2, 서로 안 겹친다
    assert out['models'] == ['메이트', '스위트']

    from lemouton.sourcing.models import Option
    from lemouton.sourcing.option_combo import option_axis_values
    rows = s.query(Option).filter_by(model_code=out['code']).all()
    combos = {tuple(option_axis_values(o)) for o in rows}
    assert combos == {('메이트', '블랙', '230'), ('메이트', '블랙', '240'),
                      ('스위트', '블랙', '230'), ('스위트', '화이트', '230')}


def test_모델명이_비었으면_거절한다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    s = session
    _seed(s, pid='m1')
    with pytest.raises(ValueError, match='모델명'):
        import_market_products_merged(
            s, items=_items(('m1', '   ')), name='x', brand='르무통',
            fetcher=_fetcher({'m1': [_MO('a', '블랙', '230')]}))


def test_모델명이_겹치면_거절한다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    s = session
    _seed(s, pid='m1'); _seed(s, pid='m2')
    per_pid = {'m1': [_MO('a', '블랙', '230')], 'm2': [_MO('b', '화이트', '230')]}
    with pytest.raises(ValueError, match='모델명'):
        import_market_products_merged(
            s, items=_items(('m1', '메이트'), ('m2', '메이트')),
            name='x', brand='르무통', fetcher=_fetcher(per_pid))


def test_축_모양이_다르면_거절한다(session):
    """한쪽은 색상만, 한쪽은 색상×사이즈 — 격자가 어긋나므로 합치지 않는다."""
    from lemouton.matrix.import_from_market import import_market_products_merged
    s = session
    _seed(s, pid='m1'); _seed(s, pid='m2')
    per_pid = {
        'm1': [_MO('a', '블랙', '')],                     # 색상만(1축)
        'm2': [_MO('b', '블랙', '230')],                   # 색상×사이즈(2축)
    }
    with pytest.raises(ValueError, match='구성이 서로 달라'):
        import_market_products_merged(
            s, items=_items(('m1', '메이트'), ('m2', '스위트')),
            name='x', brand='르무통', fetcher=_fetcher(per_pid))


def test_하나라도_못_읽으면_전부_롤백된다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    from lemouton.sourcing.models import Model
    s = session
    _seed(s, pid='m1'); _seed(s, pid='m2')
    before = s.query(Model).count()
    per_pid = {'m1': [_MO('a', '블랙', '230')], 'm2': []}
    with pytest.raises(ValueError, match='읽기 실패'):
        import_market_products_merged(
            s, items=_items(('m1', '메이트'), ('m2', '스위트')),
            name='x', brand='르무통',
            fetcher=_fetcher(per_pid, fail_pid='m2'))
    assert s.query(Model).count() == before, '실패했는데 모델이 생겼다'


def test_이미_가져온_상품이_섞여있으면_거절한다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    from lemouton.catalog.models import MarketProductGroup
    s = session
    mp1 = _seed(s, pid='m1')
    _seed(s, pid='m2')
    g = MarketProductGroup(name='이미묶음', model_code='U-already')
    s.add(g); s.flush()
    mp1.group_id = g.id
    s.flush()
    per_pid = {'m1': [_MO('a', '블랙', '230')], 'm2': [_MO('b', '블랙', '230')]}
    with pytest.raises(ValueError, match='이미 가져온'):
        import_market_products_merged(
            s, items=_items(('m1', '메이트'), ('m2', '스위트')),
            name='x', brand='르무통', fetcher=_fetcher(per_pid))


def test_번호는_band1이다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    s = session
    _seed(s, pid='m1'); _seed(s, pid='m2')
    per_pid = {'m1': [_MO('a', '블랙', '230')], 'm2': [_MO('b', '화이트', '230')]}
    out = import_market_products_merged(
        s, items=_items(('m1', '메이트'), ('m2', '스위트')),
        name='x', brand='르무통', fetcher=_fetcher(per_pid))
    assert out['code'][-6] == '1'


def test_상품마다_마켓옵션번호가_기록된다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    s = session
    _seed(s, pid='m1'); _seed(s, pid='m2')
    per_pid = {'m1': [_MO('a1', '블랙', '230')], 'm2': [_MO('b1', '블랙', '230')]}
    out = import_market_products_merged(
        s, items=_items(('m1', '메이트'), ('m2', '스위트')),
        name='x', brand='르무통', fetcher=_fetcher(per_pid))

    from lemouton.sourcing.models import Option
    from lemouton.sourcing.option_combo import option_axis_values
    from lemouton.uploader.models import MarketRegistration
    rows = s.query(Option).filter_by(model_code=out['code']).all()
    want = {('메이트', '블랙', '230'): ('m1', 'a1'),
            ('스위트', '블랙', '230'): ('m2', 'b1')}
    for o in rows:
        vals = tuple(option_axis_values(o))
        reg = s.get(MarketRegistration, (o.canonical_sku, 'smartstore'))
        assert reg is not None, f'{vals} 에 마켓 기록이 없다'
        want_pid, want_oid = want[vals]
        assert reg.market_product_id == want_pid
        assert reg.market_option_id == want_oid


def test_N개_상품이_같은_그룹으로_묶인다(session):
    from lemouton.matrix.import_from_market import import_market_products_merged
    from lemouton.catalog.models import MarketProduct, MarketProductGroup
    s = session
    mp1 = _seed(s, pid='m1'); mp2 = _seed(s, pid='m2')
    per_pid = {'m1': [_MO('a', '블랙', '230')], 'm2': [_MO('b', '화이트', '230')]}
    out = import_market_products_merged(
        s, items=_items(('m1', '메이트'), ('m2', '스위트')),
        name='병합', brand='르무통', fetcher=_fetcher(per_pid))
    s.commit()          # 커밋은 호출자(라우트) 몫 — 단건 가져오기와 같은 계약
    s.expire_all()
    g1 = s.get(MarketProduct, mp1.id).group_id
    g2 = s.get(MarketProduct, mp2.id).group_id
    assert g1 is not None and g1 == g2
    assert s.get(MarketProductGroup, g1).model_code == out['code']


def test_한개만_골라도_된다(session):
    """N=1 은 사실상 단건 가져오기와 같다 — 모델 축 값 1개짜리 매트릭스."""
    from lemouton.matrix.import_from_market import import_market_products_merged
    s = session
    _seed(s, pid='m1')
    out = import_market_products_merged(
        s, items=_items(('m1', '메이트')), name='x', brand='르무통',
        fetcher=_fetcher({'m1': [_MO('a', '블랙', '230')]}))
    assert out['ok'] is True
    assert out['models'] == ['메이트']


# ════════════════════════════════════════════════════════════
#  라우트 — POST /optgen/api/import-from-market-merge
# ════════════════════════════════════════════════════════════

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _real_session():
    from shared.db import SessionLocal
    return SessionLocal()


def _seed_real(s, *, pid, market='smartstore', acct='스스검사계정', brand='르무통'):
    from lemouton.catalog.models import MarketProduct
    from lemouton.sourcing.models_v2 import UploadAccount
    if not s.query(UploadAccount).filter_by(account_key=acct).first():
        s.add(UploadAccount(account_key=acct, display_name=acct,
                            market=market, env_prefix='SS_TEST', is_active=True))
    mp = MarketProduct(market=market, account_key=acct, market_product_id=pid,
                       name=f'상품{pid}', brand=brand, status='sale')
    s.add(mp)
    s.commit()
    return mp


def _route_items(*specs, market='smartstore', acct='스스검사계정'):
    return [{'market': market, 'account_key': acct, 'market_product_id': pid,
             'model_name': mn} for pid, mn in specs]


def _import_merge(client, monkeypatch, per_pid, *, items, name='병합매트릭스', brand='르무통'):
    import lemouton.uploader.market_fetch as MF
    monkeypatch.setattr(MF, 'fetch_market_options', _fetcher(per_pid))
    return client.post('/optgen/api/import-from-market-merge',
                       json={'items': items, 'name': name, 'brand': brand})


def _cleanup_route(client, code):
    if code:
        client.delete(f'/optgen/api/option-box/{code}')


def test_라우트로_두_상품을_병합한다(client, monkeypatch):
    s = _real_session()
    _seed_real(s, pid='rm1'); _seed_real(s, pid='rm2')
    s.close()
    per_pid = {'rm1': [_MO('a', '블랙', '230')], 'rm2': [_MO('b', '화이트', '230')]}
    r = _import_merge(client, monkeypatch, per_pid,
                      items=_route_items(('rm1', '메이트'), ('rm2', '스위트')))
    j = r.get_json()
    assert j['ok'] is True, j
    try:
        assert j['options'] == 2
        assert j['models'] == ['메이트', '스위트']
    finally:
        _cleanup_route(client, j.get('code'))


def test_라우트도_실패_이유를_그대로_돌려준다(client, monkeypatch):
    r = _import_merge(client, monkeypatch, {}, items=[])
    assert r.status_code == 400
    j = r.get_json()
    assert j['ok'] is False and j['error']


def test_라우트도_품번_구분자를_지킨다(client, monkeypatch):
    s = _real_session()
    _seed_real(s, pid='rm3'); _seed_real(s, pid='rm4')
    s.close()
    per_pid = {'rm3': [_MO('a', '블랙', '230')], 'rm4': [_MO('b', '화이트', '230')]}
    r = _import_merge(client, monkeypatch, per_pid,
                      items=_route_items(('rm3', '메이트'), ('rm4', '스위트')))
    j = r.get_json()
    assert j['ok'] is True, j
    try:
        assert j['code'][-6] == '1'
    finally:
        _cleanup_route(client, j.get('code'))

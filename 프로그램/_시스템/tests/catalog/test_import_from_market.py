# -*- coding: utf-8 -*-
"""내마켓 불러오기 — 마켓 상품에서 옵션함이 **태어나는** 흐름 (스마트스토어 한정).

사장님 확정 모델: 「맞추기」가 아니라 「생성」 — 우리 쪽이 비어 있는 상태에서
마켓의 색상·사이즈가 그대로 축이 되고, 태어나면서 그 마켓의 상품번호·옵션번호가
저절로 기록된다.

🔴 이 기록이 본체다 — 안 남기면 정책 씌워 전송할 때 「처음 올리는 상품」으로 알고
   이미 팔던 그 마켓에 같은 상품이 하나 더 올라간다(send/runner: 번호 있으면 갱신).
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _session():
    from shared.db import SessionLocal
    return SessionLocal()


def _seed(s, *, pid='1311259', market='smartstore', acct='스스검사계정'):
    """캐시 상품 1건 + 활성 계정 1개."""
    from lemouton.catalog.models import MarketProduct
    from lemouton.sourcing.models_v2 import UploadAccount
    if not s.query(UploadAccount).filter_by(account_key=acct).first():
        s.add(UploadAccount(account_key=acct, display_name=acct,
                            market=market, env_prefix='SS_TEST', is_active=True))
    mp = MarketProduct(market=market, account_key=acct, market_product_id=pid,
                       name='르무통 검사화 스니커즈', brand='르무통', status='sale')
    s.add(mp)
    s.commit()
    return mp


class _FR:
    def __init__(self, success, name, options, error=None):
        self.success, self.product_name = success, name
        self.options, self.error = options, error


class _MO:
    def __init__(self, oid, color, size):
        self.option_id, self.color, self.size = oid, color, size


def _fake_fetch(options, *, success=True, error=None, name='마켓이 준 이름'):
    def f(market, pid, env_prefix=None):
        f.called_with = (market, pid, env_prefix)
        return _FR(success, name, options, error)
    return f


def _import(client, monkeypatch, options, *, pid='1311259', market='smartstore',
            acct='스스검사계정', **fk):
    import lemouton.uploader.market_fetch as MF
    monkeypatch.setattr(MF, 'fetch_market_options', _fake_fetch(options, **fk))
    return client.post('/optgen/api/import-from-market',
                       json={'market': market, 'account_key': acct,
                             'market_product_id': pid})


def _cleanup(client, code):
    if code:
        client.delete(f'/optgen/api/option-box/{code}')


def test_축과_옵션번호까지_태어난다(client, monkeypatch):
    s = _session()
    mp = _seed(s, pid='7000001')
    opts = [_MO('sso-1', '블랙', '230'), _MO('sso-2', '블랙', '240'),
            _MO('sso-3', '화이트', '230'), _MO('sso-4', '화이트', '240')]
    j = _import(client, monkeypatch, opts, pid='7000001').get_json()
    assert j['ok'] is True, j
    code = j['code']
    try:
        assert j['options'] == 4 and j['colors'] == 2 and j['sizes'] == 2
        assert j['linked'] == 4, '옵션마다 마켓 옵션번호가 붙어야 한다'

        from lemouton.sourcing.models import Option
        from lemouton.sourcing.option_combo import option_axis_values
        from lemouton.uploader.models import MarketRegistration
        rows = s.query(Option).filter_by(model_code=code).all()
        assert len(rows) == 4
        # 🔴 본체 — (색,사이즈) 짝이 맞는 마켓 옵션번호가 기록됐는가.
        want = {('블랙', '230'): 'sso-1', ('블랙', '240'): 'sso-2',
                ('화이트', '230'): 'sso-3', ('화이트', '240'): 'sso-4'}
        for o in rows:
            vals = tuple(option_axis_values(o))
            reg = s.get(MarketRegistration, (o.canonical_sku, 'smartstore'))
            assert reg is not None, f'{vals} 에 마켓 기록이 없다'
            assert reg.market_product_id == '7000001'
            assert reg.market_option_id == want[vals]
            assert reg.status == 'linked'
        # 「이미 가져옴」 — 캐시 행에 묶음이 붙고, 묶음이 옵션함을 가리킨다.
        from lemouton.catalog.models import MarketProduct, MarketProductGroup
        s.expire_all()
        mp2 = s.get(MarketProduct, mp.id)
        assert mp2.group_id is not None
        assert s.get(MarketProductGroup, mp2.group_id).model_code == code
    finally:
        s.close(); _cleanup(client, code)


def test_번호_앞자리로_직접생성과_갈린다(client, monkeypatch):
    """품번 구분자 — 내마켓 불러오기는 순번 앞자리가 1, 직접 생성(0)과 절대 안 겹친다."""
    s = _session(); _seed(s, pid='7000008'); s.close()
    j = _import(client, monkeypatch, [_MO('a', '블랙', '230')], pid='7000008').get_json()
    assert j['ok'] is True, j
    code = j['code']
    try:
        assert code[-6] == '1', f'내마켓 불러오기 매트릭스는 band=1 이어야 한다: {code}'
    finally:
        _cleanup(client, code)


def test_두_번_가져오면_거절한다(client, monkeypatch):
    """같은 상품을 두 번 가져오면 옵션 묶음이 둘로 갈린다 — 막는다."""
    s = _session(); _seed(s, pid='7000002'); s.close()
    j1 = _import(client, monkeypatch, [_MO('a', '블랙', '230')], pid='7000002').get_json()
    assert j1['ok'] is True
    try:
        r2 = _import(client, monkeypatch, [_MO('a', '블랙', '230')], pid='7000002')
        assert r2.status_code == 400
        assert '이미 가져온' in r2.get_json()['error']
    finally:
        _cleanup(client, j1.get('code'))


def test_읽기_실패면_아무것도_안_만든다(client, monkeypatch):
    """반쪽짜리 옵션함 금지 — 실패는 통째로 실패."""
    from lemouton.sourcing.models import Model
    s = _session(); _seed(s, pid='7000003')
    before = s.query(Model).count()
    r = _import(client, monkeypatch, [], success=False, error='IP 차단',
                pid='7000003')
    assert r.status_code == 400 and 'IP 차단' in r.get_json()['error']
    s.expire_all()
    assert s.query(Model).count() == before, '실패했는데 모델이 생겼다'
    s.close()


def test_스마트스토어_아니면_거절한다(client, monkeypatch):
    r = _import(client, monkeypatch, [_MO('a', '블랙', '230')], market='gmarket')
    assert r.status_code == 400
    assert '스마트스토어만' in r.get_json()['error']


def test_모르는_계정이면_거절한다(client, monkeypatch):
    s = _session(); _seed(s, pid='7000004'); s.close()
    r = _import(client, monkeypatch, [_MO('a', '블랙', '230')],
                pid='7000004', acct='없는계정')
    assert r.status_code == 400


def test_색상만_있는_1축도_된다(client, monkeypatch):
    s = _session(); _seed(s, pid='7000005'); s.close()
    j = _import(client, monkeypatch,
                [_MO('c1', '블랙', ''), _MO('c2', '화이트', '')],
                pid='7000005').get_json()
    assert j['ok'] is True, j
    try:
        assert j['options'] == 2 and j['sizes'] == 0
        assert j['linked'] == 2
    finally:
        _cleanup(client, j.get('code'))


def test_겹친_조합과_축없는_옵션은_알려준다(client, monkeypatch):
    s = _session(); _seed(s, pid='7000006'); s.close()
    j = _import(client, monkeypatch,
                [_MO('a', '블랙', '230'), _MO('b', '블랙', '230'),
                 _MO('c', '', '')],
                pid='7000006').get_json()
    assert j['ok'] is True, j
    try:
        assert j['options'] == 1
        assert j['dup'] == ['b'] and j['skipped'] == ['c']
    finally:
        _cleanup(client, j.get('code'))


def test_지우면_가져오기가_통째로_취소된다(client, monkeypatch):
    """🔴 옵션함 지우기 = 가져오기 취소.

    안 지워지면 ① 죽은 SKU 의 마켓 옵션번호 기록이 유령으로 남고
    ② 캐시 상품이 「이미 가져옴」에 영영 잠겨 다시 못 가져온다.
    """
    s = _session()
    mp = _seed(s, pid='7000007')
    j = _import(client, monkeypatch,
                [_MO('x1', '블랙', '230'), _MO('x2', '블랙', '240')],
                pid='7000007').get_json()
    assert j['ok'] is True, j
    code = j['code']

    from lemouton.catalog.models import MarketProduct
    from lemouton.sourcing.models import Option
    from lemouton.uploader.models import MarketRegistration
    skus = [r[0] for r in s.query(Option.canonical_sku)
            .filter_by(model_code=code).all()]
    assert skus and all(
        s.get(MarketRegistration, (k, 'smartstore')) for k in skus)

    r = client.delete(f'/optgen/api/option-box/{code}')
    assert r.get_json()['ok'] is True, r.get_json()

    s.expire_all()
    assert all(s.get(MarketRegistration, (k, 'smartstore')) is None
               for k in skus), '죽은 SKU 의 마켓 기록이 유령으로 남았다'
    assert s.get(MarketProduct, mp.id).group_id is None, \
        '「이미 가져옴」 잠금이 안 풀렸다 — 다시는 못 가져온다'

    # 잠금이 풀렸으니 **다시 가져올 수 있어야** 한다.
    j2 = _import(client, monkeypatch, [_MO('y1', '블랙', '230')],
                 pid='7000007').get_json()
    assert j2['ok'] is True, '지운 뒤 재가져오기가 막혀 있다'
    s.close(); _cleanup(client, j2.get('code'))

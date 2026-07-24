# -*- coding: utf-8 -*-
"""전체 훑기 — 계정 하나가 실패해도 나머지는 계속한다."""
from lemouton.catalog import sync as S


class _Acc:
    def __init__(self, market, key, prefix):
        self.market, self.account_key, self.env_prefix = market, key, prefix
        self.is_active = True


def test_계정_하나가_실패해도_나머지는_계속한다(monkeypatch):
    accounts = [_Acc('lotteon', 'A', 'LOTTEON_1'),
                _Acc('coupang', 'B', 'COUPANG_1'),
                _Acc('smartstore', 'C', 'SMARTSTORE_1')]
    monkeypatch.setattr(S, '_active_accounts', lambda session, market=None: accounts)
    monkeypatch.setattr(S, '_client_for', lambda market, env_prefix: object())

    def fake(session, market, account_key, *, client, **kw):
        if account_key == 'B':
            raise RuntimeError('쿠팡 키가 없습니다')
        return {'ok': True, 'saved': 10, 'pages': 1, 'missing': 0,
                'truncated': False, 'total': 10, 'error': None,
                'market': market, 'account_key': account_key}

    monkeypatch.setattr(S, 'sync_account', fake)
    out = S.sync_all(session=object())
    assert out['accounts'] == 3
    assert out['ok_count'] == 2
    assert out['failed_count'] == 1
    failed = [r for r in out['results'] if not r['ok']]
    assert failed[0]['account_key'] == 'B'
    assert '쿠팡 키가 없습니다' in failed[0]['error']


def test_클라이언트_만들다_터져도_계정_이름이_결과에_남는다(monkeypatch):
    """★ 어느 계정이 안 됐는지 모르면 사장님이 손쓸 수가 없다."""
    accounts = [_Acc('lotteon', '브랜드위시', 'LOTTEON_1')]
    monkeypatch.setattr(S, '_active_accounts', lambda session, market=None: accounts)

    def boom(market, env_prefix):
        raise RuntimeError('키가 등록되지 않았습니다')

    monkeypatch.setattr(S, '_client_for', boom)
    out = S.sync_all(session=object())
    assert out['failed_count'] == 1
    assert out['results'][0]['market'] == 'lotteon'
    assert out['results'][0]['account_key'] == '브랜드위시'
    assert '키가 등록되지 않았습니다' in out['results'][0]['error']


def test_마켓을_찍으면_그_마켓만_훑는다(monkeypatch):
    called = {}

    def fake_accounts(session, market=None):
        called['market'] = market
        return []

    monkeypatch.setattr(S, '_active_accounts', fake_accounts)
    S.sync_all(session=object(), market='lotteon')
    assert called['market'] == 'lotteon'


def test_결과에_합계가_들어있다(monkeypatch):
    accounts = [_Acc('lotteon', 'A', 'X'), _Acc('lotteon', 'B', 'Y')]
    monkeypatch.setattr(S, '_active_accounts', lambda session, market=None: accounts)
    monkeypatch.setattr(S, '_client_for', lambda market, env_prefix: object())
    monkeypatch.setattr(S, 'sync_account',
                        lambda session, market, account_key, *, client, **kw: {
                            'ok': True, 'saved': 100, 'pages': 1, 'missing': 2,
                            'truncated': False, 'total': 100, 'error': None,
                            'market': market, 'account_key': account_key})
    out = S.sync_all(session=object())
    assert out['saved_total'] == 200
    assert out['missing_total'] == 4

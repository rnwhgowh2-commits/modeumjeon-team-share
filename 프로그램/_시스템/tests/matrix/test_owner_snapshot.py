# -*- coding: utf-8 -*-
"""옵션 주인 이관 — 기준 지문(fingerprint).

★ 이관은 옵션이 어느 묶음에 속하는가를 바꾼다. 그 과정에서 **옵션 자체·색상·사이즈·
  소싱처 주소 연결**이 하나라도 달라지면 가격·재고가 조용히 틀린다.
  그래서 이관 전에 지문을 뜨고, 이관 후 같은 지문이 나오는지 대조한다.

🔴 지문에 **가격·재고를 넣지 않는다.** 크롤이 몇 분마다 그 값을 바꾸기 때문에,
  넣으면 이관과 무관하게 지문이 달라져 「틀렸다」는 거짓 경보가 난다.
  가격은 소싱처 연결이 같으면 같은 입력으로 계산되므로 연결만 지키면 된다.
"""
from lemouton.matrix.owner_snapshot import model_digest


def _rows(**over):
    base = dict(
        options=[
            ('SKU-AAAA1111', '블랙', '250', True),
            ('SKU-BBBB2222', '블랙', '255', True),
            ('SKU-CCCC3333', '그레이', '250', False),
        ],
        links=[
            ('SKU-AAAA1111', 'lemouton', 'https://lemouton.co.kr/p/1042', '단품'),
            ('SKU-AAAA1111', 'musinsa', 'https://musinsa.com/p/33921', '색상모음전'),
            ('SKU-BBBB2222', 'lemouton', 'https://lemouton.co.kr/p/1042', '단품'),
        ],
        legacy=[
            ('SKU-CCCC3333', 7, 'https://ssfshop.com/GM/GM01/good'),
        ],
    )
    base.update(over)
    return base


def test_같은_내용이면_순서가_달라도_같은_지문():
    """DB 가 돌려주는 순서는 보장되지 않는다. 순서 때문에 틀렸다고 하면 안 된다."""
    a = model_digest(**_rows())
    r = _rows()
    r['options'] = list(reversed(r['options']))
    r['links'] = list(reversed(r['links']))
    b = model_digest(**r)
    assert a == b


def test_옵션_하나가_빠지면_지문이_달라진다():
    r = _rows()
    r['options'] = r['options'][:-1]
    assert model_digest(**r) != model_digest(**_rows())


def test_소싱처_주소가_바뀌면_지문이_달라진다():
    r = _rows()
    r['links'] = [('SKU-AAAA1111', 'lemouton', 'https://lemouton.co.kr/p/9999', '단품')] + r['links'][1:]
    assert model_digest(**r) != model_digest(**_rows())


def test_옛_저장소_주소가_빠져도_지문이_달라진다():
    """소싱처 주소는 두 곳에 나뉘어 있다 — 한쪽만 보면 없어진 걸 못 잡는다."""
    r = _rows()
    r['legacy'] = []
    assert model_digest(**r) != model_digest(**_rows())


def test_옵션이_켜짐_꺼짐이_바뀌면_지문이_달라진다():
    """꺼진 옵션이 켜지면 팔리면 안 되는 게 팔린다."""
    r = _rows()
    r['options'] = [('SKU-CCCC3333', '그레이', '250', True)] + r['options'][:-1]
    assert model_digest(**r) != model_digest(**_rows())


def test_가격과_재고는_지문에_안_들어간다():
    """🔴 크롤이 몇 분마다 바꾸는 값 — 넣으면 거짓 경보가 난다.

    model_digest 는 가격·재고를 인자로 받지도 않는다. 이 테스트는 그 계약을 고정한다.
    """
    import inspect
    params = set(inspect.signature(model_digest).parameters)
    assert params == {'options', 'links', 'legacy'}


import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_지문_창구가_뜬다(client):
    r = client.get('/api/admin/option-owner/snapshot')
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True
    assert set(j['counts']) == {'models', 'options', 'links_new', 'links_legacy'}
    assert len(j['overall']) == 16


def test_없는_묶음은_없다고_말한다(client):
    """조용히 빈 결과를 주면 「달라진 게 없다」로 오해한다."""
    r = client.get('/api/admin/option-owner/snapshot/__없는묶음__zzz')
    assert r.status_code == 404
    assert r.get_json()['ok'] is False

# -*- coding: utf-8 -*-
"""한 상품의 옵션이 전부 품절되면 알린다. 설계서 규칙 9.

사장님 확정 — **상품은 안 내린다.** 옵션 재고만 0이 되고 마켓이 알아서 품절로
보여준다. 다만 **살 게 하나도 없는 상품 페이지**가 걸려 있는 걸 아셔야 한다.

🔴 알림 유형 「전체품절」은 예전부터 정의돼 있었지만 **부르는 곳이 0곳**이었다.
   즉 알림이 **한 번도 나간 적이 없다.** 정의만 있고 안 도는 거짓 기능이었다.

🔴 재고 0 과 「확인 불가」(None)는 다르다 — 못 구한 것을 품절로 단정하면
   팔 수 있는 걸 품절로 알린다. 확인 불가는 품절이 아니다.
"""
from lemouton.matrix.soldout_alert import option_sellable, product_all_soldout


def test_소싱처에_재고가_있으면_팔_수_있다():
    assert option_sellable(source_stocks=[0, 3], own_stock=0) is True


def test_사입_재고만_있어도_팔_수_있다():
    """소싱처가 전부 품절이어도 창고에 있으면 판다."""
    assert option_sellable(source_stocks=[0, 0], own_stock=5) is True


def test_둘_다_없으면_못_판다():
    assert option_sellable(source_stocks=[0, 0], own_stock=0) is False


def test_확인_불가는_품절이_아니다():
    """🔴 못 구한 것을 품절로 단정하면 팔 수 있는 걸 품절로 알린다."""
    assert option_sellable(source_stocks=[None], own_stock=0) is True
    assert option_sellable(source_stocks=[None, 0], own_stock=0) is True


def test_연결된_소싱처가_없으면_품절로_안_본다():
    """아직 주소를 안 붙인 새 옵션이다 — 품절이 아니라 «아직 모름»이다."""
    assert option_sellable(source_stocks=[], own_stock=0) is True


def test_옵션이_하나라도_팔_수_있으면_전수품절_아님():
    assert product_all_soldout([True, False, False]) is False


def test_전부_못_팔면_전수품절():
    assert product_all_soldout([False, False]) is True


def test_옵션이_없는_상품은_전수품절_아님():
    """🔴 아직 옵션을 안 만든 상품이다 — 품절이라고 알리면 거짓말이다."""
    assert product_all_soldout([]) is False


import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_먼저_읽기만_하는_창구가_있다(client):
    """알림을 보내기 전에 무엇이 품절인지 눈으로 먼저 본다."""
    r = client.get('/api/admin/option-owner/soldout')
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True
    assert set(['checked', 'soldout', 'new', 'recovered']) == set(j['counts'])


def test_알림_창구가_돈다(client):
    r = client.post('/api/admin/option-owner/soldout/notify')
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j['ok'] is True
    assert 'sent' in j


def test_두_번_보내도_같은_상품을_다시_안_알린다(client):
    client.post('/api/admin/option-owner/soldout/notify')
    j = client.post('/api/admin/option-owner/soldout/notify').get_json()
    assert j['sent'] == 0

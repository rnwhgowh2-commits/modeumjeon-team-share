# -*- coding: utf-8 -*-
"""옛 조정 버그가 실제로 남긴 흔적을 세는 창구 (읽기 전용).

사장님은 창고 2곳(사무실·로켓그로스)을 쓴다. 그래서
`create_adjustment` 가 차이의 기준을 **전 창고 합**으로 잡던 동안,
한 창고 실사가 그 창고를 음수로 만들고 총합에서 재고를 지웠을 수 있다.

무엇을 흔적으로 보나 — 둘 다 **정상 운영에서는 나올 수 없는** 값이다.
  ① 창고별 재고가 **음수**인 것 (있을 수 없다)
  ② 저장된 스냅샷(boxhero_stock_total) ≠ 원장 합
고치는 건 별도다. 이 창구는 **세기만** 한다(쓰기 없음).
"""
import pytest


@pytest.fixture
def client():
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_음수_창고재고를_찾아_돌려준다(client, monkeypatch):
    from webapp.routes.inventory import transactions as T
    monkeypatch.setattr(T, "_음수_창고재고", lambda s: [
        {"sku": "SKU-A", "location": "사무실", "qty": -2}])
    monkeypatch.setattr(T, "_스냅샷_어긋남", lambda s: [])
    r = client.get('/inventory/diag/adjust-damage')
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True
    assert j["음수재고"][0]["qty"] == -2
    assert j["음수재고건수"] == 1
    assert j["스냅샷어긋남건수"] == 0


def test_스냅샷_어긋남도_센다(client, monkeypatch):
    from webapp.routes.inventory import transactions as T
    monkeypatch.setattr(T, "_음수_창고재고", lambda s: [])
    monkeypatch.setattr(T, "_스냅샷_어긋남", lambda s: [
        {"sku": "SKU-B", "스냅샷": 8, "원장": 18}])
    r = client.get('/inventory/diag/adjust-damage')
    j = r.get_json()
    assert j["스냅샷어긋남"][0]["원장"] == 18
    assert j["스냅샷어긋남건수"] == 1


def test_아무_흔적도_없으면_그렇게_말한다(client, monkeypatch):
    from webapp.routes.inventory import transactions as T
    monkeypatch.setattr(T, "_음수_창고재고", lambda s: [])
    monkeypatch.setattr(T, "_스냅샷_어긋남", lambda s: [])
    j = client.get('/inventory/diag/adjust-damage').get_json()
    assert j["ok"] is True and j["음수재고건수"] == 0 and j["스냅샷어긋남건수"] == 0

# -*- coding: utf-8 -*-
"""옵션 생성 시 초기 재고 (2026-08-12 · 노션 옵션 d 「입력 시, 재고 연동 ㄱㄱ!」).

🔴 재고는 돈이다. 여기서 못 박는 것 네 가지:
  ① 재고는 **원장(InventoryTx)** 에 남는다 — 캐시 칸을 직접 고치면 화면과 실재고가 갈린다
  ② **두 번 눌러도 두 배가 되지 않는다** — 「초기」가 두 번 들어가면 이중 계상이다
  ③ 남의 SKU 에는 못 꽂는다
  ④ 건너뛴 것을 조용히 숨기지 않는다
"""
import pytest


@pytest.fixture
def client():
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture
def box(client):
    """옵션 2개짜리 옵션함."""
    code = client.post('/optgen/api/option-box',
                       json={'name': '초기재고 검사함', 'brand': '르무통',
                             'axes': ['색상', '사이즈']}).get_json()['code']
    client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '색상', 'values': ['블랙']},
                  {'axis_name': '사이즈', 'values': ['250', '260']}],
        'selected': [['블랙', '250'], ['블랙', '260']],
    })
    html = client.get(f'/optgen/box/{code}').get_data(as_text=True)
    import re
    skus = re.findall(r'data-sku="(SKU-[A-Z0-9]+)"', html)
    return code, sorted(set(skus))


def _stock(code, sku):
    from shared.db import SessionLocal
    from shared.inventory_stock import get_stock_batch
    s = SessionLocal()
    try:
        return int(get_stock_batch(s, [sku]).get(sku) or 0)
    finally:
        s.close()


def test_초기재고가_원장에_남는다(client, box):
    code, skus = box
    assert len(skus) == 2, skus
    r = client.post(f'/optgen/api/box/{code}/initial-stock',
                    json={'qty': {skus[0]: 5, skus[1]: 3}})
    j = r.get_json()
    assert j['ok'] and j['added'] == 2, j
    assert _stock(code, skus[0]) == 5
    assert _stock(code, skus[1]) == 3

    # 원장에 입고 이력이 실제로 남았는지 — 캐시 칸만 고친 게 아님을 확인
    from shared.db import SessionLocal
    from lemouton.inventory.models import InventoryTx
    s = SessionLocal()
    try:
        txs = (s.query(InventoryTx)
               .filter(InventoryTx.option_canonical_sku.in_(skus)).all())
        assert len(txs) == 2
        assert all(t.tx_type == 'in' and t.status == 'completed' for t in txs)
    finally:
        s.close()


def test_두_번_넣어도_두_배가_되지_않는다(client, box):
    """🔴 이중 계상 = 없는 재고를 팔게 된다."""
    code, skus = box
    client.post(f'/optgen/api/box/{code}/initial-stock', json={'qty': {skus[0]: 5}})
    r = client.post(f'/optgen/api/box/{code}/initial-stock', json={'qty': {skus[0]: 5}})
    j = r.get_json()
    assert j['ok'] and j['added'] == 0, j
    assert j['skipped'] == [skus[0]], '건너뛴 것을 조용히 숨기면 안 된다'
    assert _stock(code, skus[0]) == 5, '두 번째 저장에 재고가 늘었다 — 이중 계상'


def test_남의_SKU_에는_못_꽂는다(client, box):
    code, _ = box
    r = client.post(f'/optgen/api/box/{code}/initial-stock',
                    json={'qty': {'SKU-NOTMINE1': 3}})
    assert r.status_code == 400
    assert '이 묶음의 옵션이 아니' in r.get_json()['error']


def test_0이나_음수는_넣지_않는다(client, box):
    code, skus = box
    r = client.post(f'/optgen/api/box/{code}/initial-stock',
                    json={'qty': {skus[0]: 0, skus[1]: -2}})
    assert r.get_json()['added'] == 0
    assert _stock(code, skus[0]) == 0

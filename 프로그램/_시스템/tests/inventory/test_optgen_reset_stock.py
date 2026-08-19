# -*- coding: utf-8 -*-
"""옛 재고 기록 치우기 (2026-08-12 · 사장님 「옛날 재고야, 다시 재입력해야해」).

🔴 재고는 돈이다. 여기서 못 박는 것:
  ① 치우면 **재고가 0** 이 된다 (원장 합계 기준)
  ② **옵션·묶음은 그대로 남는다** — 지우는 건 재고 이력뿐이다
  ③ 얼마를 치웠는지 **숫자로 돌려준다** (조용히 사라지지 않는다)
  ④ 캐시 칸도 같이 0 이 된다 — 안 그러면 화면 숫자와 실제가 갈린다
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
    """🔴 [2026-08-20 병합 정리] SKU 목록은 box.html 이 아니라
    `/optgen/api/box/<code>/rows` 에서 얻는다(위 파일 머리말 참고 —
    옵션 조합 창의 재고 서랍이 이 API 로 클라이언트에서 그린다).

    🔴 [2026-08-19 ui-verify 감사] 옵션함 이름 중복이 이제 거절된다 — 매번 다른 이름."""
    import uuid
    code = client.post('/optgen/api/option-box',
                       json={'name': f'재고치우기 검사함 {uuid.uuid4().hex[:8]}',
                             'brand': '르무통',
                             'axes': ['색상', '사이즈']}).get_json()['code']
    client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '색상', 'values': ['블랙']},
                  {'axis_name': '사이즈', 'values': ['250', '260']}],
        'selected': [['블랙', '250'], ['블랙', '260']],
    })
    j = client.get(f'/optgen/api/box/{code}/rows').get_json()
    skus = sorted({r['sku'] for r in j['rows']})
    client.post(f'/optgen/api/box/{code}/initial-stock',
                json={'qty': {skus[0]: 7, skus[1]: 3}})
    return code, skus


def _stock(skus):
    from shared.db import SessionLocal
    from shared.inventory_stock import get_stock_batch
    s = SessionLocal()
    try:
        got = get_stock_batch(s, skus)
        return sum(int(got.get(k) or 0) for k in skus)
    finally:
        s.close()


def test_치우면_재고가_0이_된다(client, box):
    code, skus = box
    assert _stock(skus) == 10, '준비가 안 됐다'
    r = client.post('/optgen/api/box/reset-stock', json={'codes': [code]})
    j = r.get_json()
    assert j['ok'], j
    assert j['options'] == 2
    assert j['cleared_qty'] == 10, '얼마를 치웠는지 그대로 말해야 한다'
    assert j['removed_rows'] == 2
    assert _stock(skus) == 0


def test_옵션과_묶음은_그대로_남는다(client, box):
    """지우는 건 재고 이력뿐 — 옵션이 사라지면 다시 만들어야 한다."""
    code, skus = box
    client.post('/optgen/api/box/reset-stock', json={'codes': [code]})
    assert client.get(f'/optgen/box/{code}').status_code == 200
    j = client.get(f'/optgen/api/box/{code}/rows').get_json()
    still_there = {r['sku'] for r in j['rows']}
    for sku in skus:
        assert sku in still_there, f'{sku} 옵션이 사라졌다'


def test_캐시_칸도_같이_0이_된다(client, box):
    """화면이 캐시를 보면 숫자가 갈린다 — 원장과 같이 0 이어야 한다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    code, skus = box
    client.post('/optgen/api/box/reset-stock', json={'codes': [code]})
    s = SessionLocal()
    try:
        for sku in skus:
            o = s.get(Option, sku)
            assert int(o.boxhero_stock_total or 0) == 0, f'{sku} 캐시가 안 맞춰졌다'
    finally:
        s.close()


def test_묶음을_안_주면_거절한다(client):
    r = client.post('/optgen/api/box/reset-stock', json={'codes': []})
    assert r.status_code == 400

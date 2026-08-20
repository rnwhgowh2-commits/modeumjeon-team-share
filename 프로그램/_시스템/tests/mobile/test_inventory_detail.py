# -*- coding: utf-8 -*-
"""폰 「재고 목록」 제품 상세 펼침(A4·B1·C1+C4) — 시트·위치이동·색상×사이즈표·KPI.

사장님 확정(2026-08-05, 「모음전 폰 제품화면 시안 v1.html」 A4·B1·C1+C4):
목록 카드를 누르면 카드 바로 아래 상세 시트가 펼쳐진다(새 화면 아님). 시트 =
브랜드·모델·품번·바코드·평균매입가·위치별 재고·모음전 연결(읽기전용)·색상×사이즈
미니표·위치 이동(폰의 유일한 쓰기)·입고/출고 링크.

무엇을 지키나
    ① 새 API 3종 — /mobile/api/product/<sku>(정상+404) ·
       /mobile/api/transfer(정상+재고부족·같은위치·수량·404 거부) ·
       /mobile/api/options 의 kpi.
    ② 🔴 KPI drift — PC 「제품」(/inventory/data/items?format=json) kpi 와 폰 kpi 는
       **같은 계산**(shared.inventory_stock.master_kpi 공용) — 값 대조로 못 박는다.
    ③ 🔴 제품 필드 drift — product API 필드는 PC data_items JSON rows 와 같은 원천
       (barcode·article_no·brand·avg·usage·stock) — 값 대조.
    ④ 🔴 색상×사이즈 표 — 0(등록됐는데 재고 0)과 null(조합 자체가 없음)을 구분.
       0 을 「—」 로, 없음을 0 으로 둔갑시키면 여기서 잡힌다.
    ⑤ 🔴 위치 이동 부호 규약 — 데스크탑 create_move(inbound.py)와 **완전히 같은**
       기록(tx_type='move'·qty 양수·location_id=출발·location_to_id=도착) — 필드 대조.
    ⑥ 템플릿 — 펼침 훅·입고/출고 링크 보존·「—」 갈래·표 그릇 가로 스크롤·터치 44px 을
       **줄 단위 정규식**으로 (낱말 grep 헛통과 금지).

flask_app 픽스처는 tests/mobile/conftest.py (DISABLE_AUTH=1 + ENVIRONMENT=team-share-dev).
"""
import re
from pathlib import Path

import pytest

_TPL = Path(__file__).resolve().parents[2] / 'webapp' / 'templates' / 'mobile' / 'inventory.html'

_MODEL = 'MINVD-W2401'
_SKU_BK240 = 'SKU-MINVD-BK240'
_SKU_BK250 = 'SKU-MINVD-BK250'
_SKU_WH240 = 'SKU-MINVD-WH240'
_LOC_A = '창고A(폰상세시험)'
_LOC_B = '창고B(폰상세시험)'


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _tpl_src() -> str:
    assert _TPL.exists(), f'템플릿이 없다: {_TPL}'
    return _TPL.read_text(encoding='utf-8')


# ════════════════════════════════════════════════════════════
#  준비물 — 모델 1 + 옵션 3 + 위치 2 + 거래(in/out) + 모음전 링크 2
# ════════════════════════════════════════════════════════════

@pytest.fixture
def seeded(flask_app):
    """블랙240(재고 6-2=4 @창고A) · 블랙250(등록만, 재고 0) · 화이트240(재고 3 @창고A).
    화이트250 조합은 **만들지 않는다** — 표의 「—」(null) 검증용.

    🔴 데이터를 만드는 픽스처 — 진짜 DB(PostgreSQL)면 안 돈다.
    """
    from tests.mobile.conftest import require_sqlite
    require_sqlite()

    from lemouton.inventory.models import (
        InventoryLocation, InventoryTx, OptionProductLink,
    )
    from lemouton.sourcing.models import Model, Option
    from shared.db import SessionLocal

    s = SessionLocal()
    made = {'skus': [], 'locs': [], 'links': []}
    try:
        if not s.query(Model).filter_by(model_code=_MODEL).first():
            s.add(Model(model_code=_MODEL, model_name_raw='워커 2401',
                        model_name_display='워커 2401', brand='르무통',
                        article_no='W2401'))
        for sku, color, size, barcode, avg in (
                (_SKU_BK240, '블랙', '240', '8809691240117', 41250),
                (_SKU_BK250, '블랙', '250', '8809691240124', 41250),
                (_SKU_WH240, '화이트', '240', '8809691240131', 39800)):
            if not s.get(Option, sku):
                s.add(Option(canonical_sku=sku, model_code=_MODEL,
                             color_code=color, size_code=size,
                             color_display=color, size_display=size,
                             barcode=barcode, boxhero_sku=sku,
                             boxhero_avg_purchase_price=avg, is_active=True))
                made['skus'].append(sku)
        s.flush()

        locs = {}
        for name in (_LOC_A, _LOC_B):
            loc = s.query(InventoryLocation).filter_by(name=name).first()
            if not loc:
                loc = InventoryLocation(name=name)
                s.add(loc)
                s.flush()
                made['locs'].append(loc.id)
            locs[name] = loc
        loc_a = locs[_LOC_A]

        # 거래 — 데스크탑·모바일 공통 저장 규약: qty 양수, 부호는 tx_type 이 결정.
        # 블랙240: in 6, out 2 → SSOT 4 (raw 합이면 8 — SSOT 시험이 잡는다)
        for sku, tx_type, qty in ((_SKU_BK240, 'in', 6), (_SKU_BK240, 'out', 2),
                                  (_SKU_WH240, 'in', 3)):
            s.add(InventoryTx(tx_type=tx_type, location_id=loc_a.id,
                              option_canonical_sku=sku, qty=qty,
                              status='completed', source='local',
                              created_by='폰상세시험'))

        # 모음전 연결(usage) — PC usage_map 원천 그대로: product_canonical_sku 역참조 2건
        for opt_sku in ('SKU-MINVD-USE1', 'SKU-MINVD-USE2'):
            if not s.get(OptionProductLink, opt_sku):
                s.add(OptionProductLink(option_canonical_sku=opt_sku,
                                        product_canonical_sku=_SKU_BK240))
                made['links'].append(opt_sku)
        s.commit()
        yield {'loc_a': loc_a.id, 'loc_b': locs[_LOC_B].id}
    finally:
        try:
            for opt_sku in made['links']:
                s.query(OptionProductLink).filter_by(
                    option_canonical_sku=opt_sku).delete()
            s.query(InventoryTx).filter(
                InventoryTx.option_canonical_sku.in_(
                    [_SKU_BK240, _SKU_BK250, _SKU_WH240])).delete(
                synchronize_session=False)
            for sku in made['skus']:
                s.query(Option).filter_by(canonical_sku=sku).delete()
            if made['skus']:
                s.query(Model).filter_by(model_code=_MODEL).delete()
            for lid in made['locs']:
                s.query(InventoryLocation).filter_by(id=lid).delete()
            s.commit()
        finally:
            s.close()


# ════════════════════════════════════════════════════════════
#  ① product API
# ════════════════════════════════════════════════════════════

def test_product_API_정상(client, seeded):
    j = client.get(f'/mobile/api/product/{_SKU_BK240}').get_json()
    assert j['ok']
    p = j['product']
    assert p['canonical_sku'] == _SKU_BK240
    assert p['brand'] == '르무통'
    assert p['model_name'] == '워커 2401'
    assert p['article_no'] == 'W2401'
    assert p['barcode'] == '8809691240117'
    assert p['avg_purchase_price'] == 41250
    assert p['usage'] == 2, '모음전 연결(OptionProductLink 역참조) 개수가 틀렸다'
    assert p['stock'] == 4, 'SSOT 재고(in 6 - out 2)가 아니다'


def test_product_API_없는_SKU_404(client, seeded):
    r = client.get('/mobile/api/product/SKU-MINVD-GHOST')
    assert r.status_code == 404
    assert r.get_json()['ok'] is False


def test_product_필드는_PC_제품화면과_같은_원천이다(client, seeded):
    """🔴 drift 감시 — PC /inventory/data/items JSON rows 와 값 대조.

    폰 시트의 바코드·품번·브랜드·매입가·usage·재고가 PC 표와 다른 숫자를 말하면
    여기서 잡힌다(같은 사실 두 곳 적기 금지).
    """
    pc = client.get(f'/inventory/data/items?format=json&q={_SKU_BK240}').get_json()
    rows = [r for r in pc['items'] if r['sku'] == _SKU_BK240]
    assert rows, 'PC 제품 화면 JSON 에 시드 SKU 가 없다'
    row = rows[0]

    p = client.get(f'/mobile/api/product/{_SKU_BK240}').get_json()['product']
    assert p['barcode'] == row['barcode']
    assert p['article_no'] == row['article_no']
    assert p['brand'] == row['brand']
    assert p['model_name'] == row['name_raw']
    assert p['avg_purchase_price'] == row['avg']
    assert p['usage'] == row['usage']
    assert p['stock'] == row['stock']


# ════════════════════════════════════════════════════════════
#  ② KPI — PC 와 같은 계산 (공용 함수 + 값 대조 이중)
# ════════════════════════════════════════════════════════════

def test_KPI_는_PC_제품화면과_같은_값이다(client, seeded):
    mobile = client.get('/mobile/api/options').get_json()
    assert 'kpi' in mobile, '폰 목록 응답에 kpi 가 없다'
    pc = client.get('/inventory/data/items?format=json').get_json()
    assert mobile['kpi'] == pc['kpi'], \
        f"두 화면이 다른 숫자를 말한다 — 폰 {mobile['kpi']} vs PC {pc['kpi']}"
    assert mobile['kpi']['all_options'] >= 3, '시드가 반영 안 된 헛비교'


def test_KPI_공용_함수를_쓴다():
    """사본 계산이 생기면(값은 우연히 같아도) 여기서 잡는다 — import 확인."""
    import inspect
    from webapp.routes import mobile as m
    src = inspect.getsource(m.api_options)
    assert 'master_kpi' in src, \
        'api_options 가 shared.inventory_stock.master_kpi 를 안 쓴다(KPI 사본 금지)'


def test_목록_재고도_SSOT_부호규약이다(client, seeded):
    """in 6 · out 2(양수 저장) → 4. raw sum(qty) 이면 8 — 부호 무시가 잡힌다."""
    j = client.get(f'/mobile/api/options?q={_SKU_BK240}').get_json()
    row = next(it for it in j['items'] if it['canonical_sku'] == _SKU_BK240)
    assert row['stock'] == 4, f"목록 재고 {row['stock']} — SSOT(4)가 아니다(raw 합=8?)"


def test_입출고_응답의_new_total_stock_도_SSOT_다(client, seeded):
    """스캔 화면이 저장 직후 띄우는 숫자 — in 6 → 6, 이어서 out 2 → **4**.

    raw sum(qty) 이면 출고를 더해 8 을 돌려준다(양수 저장 규약). 화면은 이 값을
    그대로 띄우므로 여기가 틀리면 폰이 곧바로 거짓 재고를 말한다.
    응답 JSON **모양(키)** 은 화면들이 읽으니 같이 못 박는다.
    """
    loc = seeded['loc_a']

    j = client.post('/mobile/api/action', json={
        'sku': _SKU_BK250, 'action': 'in', 'location_id': loc, 'qty': 6}).get_json()
    assert j['ok'], j
    assert j['new_total_stock'] == 6, j

    j = client.post('/mobile/api/action', json={
        'sku': _SKU_BK250, 'action': 'out', 'location_id': loc, 'qty': 2}).get_json()
    assert j['ok'], j
    assert j['new_total_stock'] == 4, \
        f"new_total_stock {j['new_total_stock']} — SSOT(4)가 아니다(raw 합=8?)"
    for k in ('tx_id', 'action', 'applied_qty', 'new_total_stock',
              'location_name', 'actor'):
        assert k in j, f'응답 키가 사라졌다(화면이 읽는 모양 불변): {k}'
    assert j['applied_qty'] == 2, '출고도 양수 저장(부호는 SSOT 가 처리) 규약이 깨졌다'

    # 저장분 재조회도 같은 값 — 응답 숫자 지어내기 방지
    assert client.get(f'/mobile/api/stock/{_SKU_BK250}').get_json()['total'] == 4


def test_바코드_조회_재고도_SSOT_다(client, seeded):
    """스캔 직후 화면에 뜨는 재고 — in 6 · out 2 시드에서 4(raw 합이면 8)."""
    j = client.post('/mobile/api/lookup', json={'code': _SKU_BK240}).get_json()
    assert j['ok'], j
    o = j['option']
    assert o['canonical_sku'] == _SKU_BK240
    assert o['stock'] == 4, f"조회 재고 {o['stock']} — SSOT(4)가 아니다(raw 합=8?)"
    # 화면이 읽는 키 모양 불변
    for k in ('canonical_sku', 'stock', 'match_via', 'model_code', 'image_url'):
        assert k in o, f'조회 응답 키가 사라졌다: {k}'


def test_옵션_미등록_SKU_조회_재고도_SSOT_다(client, seeded):
    """api_lookup 의 「거래만 있는 SKU」 갈래(7번) — 여기도 같은 부호 규약이어야 한다."""
    from lemouton.inventory.models import InventoryTx
    from shared.db import SessionLocal

    sku = 'SKU-MINVD-ORPHAN'
    s = SessionLocal()
    try:
        for tx_type, qty in (('in', 6), ('out', 2)):
            s.add(InventoryTx(tx_type=tx_type, location_id=seeded['loc_a'],
                              option_canonical_sku=sku, qty=qty,
                              status='completed', source='local',
                              created_by='폰상세시험'))
        s.commit()
        j = client.post('/mobile/api/lookup', json={'code': sku}).get_json()
        assert j['ok'], j
        o = j['option']
        assert o['registered'] is False, '옵션 미등록 갈래가 아니다 — 헛시험'
        assert o['stock'] == 4, f"미등록 SKU 재고 {o['stock']} — SSOT(4)가 아니다(raw 합=8?)"
    finally:
        s.query(InventoryTx).filter_by(option_canonical_sku=sku).delete()
        s.commit()
        s.close()


def test_위치별_재고_API_도_SSOT_다(client, seeded):
    j = client.get(f'/mobile/api/stock/{_SKU_BK240}').get_json()
    assert j['ok']
    by = {r['location_name']: r['stock'] for r in j['by_location']}
    assert by[_LOC_A] == 4, f"창고A {by[_LOC_A]} — SSOT(4)가 아니다(raw 합=8?)"
    assert by[_LOC_B] == 0
    assert j['total'] == 4


# ════════════════════════════════════════════════════════════
#  ③ C4 색상×사이즈 표 — 0 과 「없음(null)」 구분
# ════════════════════════════════════════════════════════════

def test_색상사이즈_표_0과_없음을_구분한다(client, seeded):
    p = client.get(f'/mobile/api/product/{_SKU_BK240}').get_json()['product']
    mtx = p['matrix']
    assert mtx, '색상×사이즈 표가 없다'
    assert mtx['sizes'] == ['240', '250'], f"사이즈 축이 틀렸다: {mtx['sizes']}"
    rows = {r['color']: r['cells'] for r in mtx['rows']}
    assert set(rows) == {'블랙', '화이트'}
    # 블랙: 240=4(SSOT) · 250=0(옵션은 있는데 재고 0 — 0 이지 「—」 아님)
    assert rows['블랙'] == [4, 0]
    # 화이트: 240=3 · 250=조합 자체가 없음 → null (0 으로 둔갑 금지)
    assert rows['화이트'] == [3, None]


# ════════════════════════════════════════════════════════════
#  ④ A4 위치 이동 — 정상 + 거부 4종 + 부호 규약
# ════════════════════════════════════════════════════════════

def _post_move(client, sku, from_id, to_id, qty):
    return client.post('/mobile/api/transfer', json={
        'sku': sku, 'from_location_id': from_id,
        'to_location_id': to_id, 'qty': qty,
    })


def test_위치이동_정상_저장과_갱신재고_응답(client, seeded):
    r = _post_move(client, _SKU_BK240, seeded['loc_a'], seeded['loc_b'], 2)
    j = r.get_json()
    assert r.status_code == 200 and j['ok'], j
    # 응답에 양쪽 위치의 갱신 재고 — 4-2=2 / 0+2=2, 총합 불변 4
    assert j['from_location']['stock'] == 2
    assert j['to_location']['stock'] == 2
    assert j['total_stock'] == 4, '이동은 총합을 바꾸면 안 된다'

    # 저장 후 재조회도 같은 값 (응답 숫자 지어내기 방지)
    st = client.get(f'/mobile/api/stock/{_SKU_BK240}').get_json()
    by = {x['location_name']: x['stock'] for x in st['by_location']}
    assert by[_LOC_A] == 2 and by[_LOC_B] == 2 and st['total'] == 4


def test_위치이동_기록은_데스크탑_create_move_규약과_같다(client, seeded):
    """🔴 부호 규약 대조 — 폰 이동 InventoryTx ↔ 데스크탑 create_move 필드 완전 일치.

    실코드 확인(2026-08-05): 데스크탑 이동 = lemouton/inventory/inbound.py:create_move
    (tx_type='move'·qty 양수·location_id=출발·location_to_id=도착·completed·local).
    폰이 다른 부호·필드로 적기 시작하면 SSOT(_stock_expr) 합산이 틀어진다.
    """
    from lemouton.inventory.inbound import create_move
    from lemouton.inventory.models import InventoryTx
    from shared.db import SessionLocal

    j = _post_move(client, _SKU_BK240, seeded['loc_a'], seeded['loc_b'], 1).get_json()
    assert j['ok']
    s = SessionLocal()
    try:
        mob = s.get(InventoryTx, j['tx_id'])
        # 데스크탑 함수로 같은 이동을 만들어 필드 대조 (커밋 없이 flush 만 — rollback)
        desk = create_move(s, from_location_id=seeded['loc_a'],
                           to_location_id=seeded['loc_b'],
                           option_canonical_sku=_SKU_BK240, qty=1,
                           created_by='시험')
        for field in ('tx_type', 'qty', 'location_id', 'location_to_id',
                      'status', 'source'):
            assert getattr(mob, field) == getattr(desk, field), \
                f'{field}: 폰 {getattr(mob, field)!r} ≠ 데스크탑 {getattr(desk, field)!r}'
        assert mob.qty == 1 and mob.qty > 0, 'qty 는 양수 저장(부호는 SSOT 처리)'
        assert mob.tx_type == 'move'
        s.rollback()   # desk 는 시험용 — 저장 안 함
    finally:
        s.close()


def test_위치이동_재고부족_거부(client, seeded):
    from lemouton.inventory.models import InventoryTx
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        before = s.query(InventoryTx).filter_by(
            option_canonical_sku=_SKU_BK240, tx_type='move').count()
    finally:
        s.close()

    r = _post_move(client, _SKU_BK240, seeded['loc_a'], seeded['loc_b'], 999)
    assert r.status_code == 400
    assert '재고 부족' in r.get_json()['error']

    s = SessionLocal()
    try:
        after = s.query(InventoryTx).filter_by(
            option_canonical_sku=_SKU_BK240, tx_type='move').count()
        assert after == before, '거부됐는데 이동 기록이 생겼다'
    finally:
        s.close()


def test_위치이동_같은위치_거부(client, seeded):
    r = _post_move(client, _SKU_BK240, seeded['loc_a'], seeded['loc_a'], 1)
    assert r.status_code == 400
    assert '같은 위치' in r.get_json()['error']


def test_위치이동_수량은_양수만(client, seeded):
    for qty in (0, -3):
        r = _post_move(client, _SKU_BK240, seeded['loc_a'], seeded['loc_b'], qty)
        assert r.status_code == 400, f'qty={qty} 가 통과했다'
        assert '양수' in r.get_json()['error']


def test_위치이동_없는_SKU_와_없는_위치_404(client, seeded):
    r = _post_move(client, 'SKU-MINVD-GHOST', seeded['loc_a'], seeded['loc_b'], 1)
    assert r.status_code == 404
    r = _post_move(client, _SKU_BK240, seeded['loc_a'], 99999999, 1)
    assert r.status_code == 404


# ════════════════════════════════════════════════════════════
#  ⑤ 템플릿 — 훅·링크·갈래를 줄 단위로 못 박는다 (낱말 grep 금지)
# ════════════════════════════════════════════════════════════

def test_화면이_뜨고_KPI_와_펼침_훅이_있다(client):
    r = client.get('/mobile/inventory')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for kid in ('inv-kpi-total', 'inv-kpi-instock', 'inv-kpi-qty'):
        assert re.search(rf'id="{kid}"', html), f'KPI 칸 {kid} 이 없다'
    src = _tpl_src()
    # B1 펼침 훅 — 카드 markup 에 inv-card 클래스 + data-sku (id/class 로 못박기)
    assert re.search(r'class="m-card inv-card"\s+data-sku="\$\{esc\(sku\)\}"', src), \
        '카드에 펼침 훅(class=inv-card + data-sku)이 없다'
    assert re.search(r"addEventListener\('click',\s*\(\)\s*=>\s*toggleSheet\(card\)\)", src), \
        '카드 클릭 → toggleSheet 배선이 없다'
    # 시트 그릇 id
    assert "sheet.id = 'inv-sheet'" in src, '시트 그릇 id(inv-sheet)가 없다'


def test_카드_뼈대는_그대로다():
    """사진48 + 이름 + 오른쪽 숫자 — 기존 「재고 목록」 카드 구조 유지(바꾸지 말 것)."""
    src = _tpl_src()
    assert 'width: 48px; height: 48px' in src, '사진 48px 뼈대가 바뀌었다'
    assert re.search(r'>재고</div>', src), '오른쪽 「재고」 캡션이 사라졌다'


def test_입고출고_링크가_시트에_보존됐다():
    """기존 카드의 /mobile/sku/<sku> 이동 기능 — 시트 안 단추로 보존."""
    src = _tpl_src()
    assert re.search(
        r'id="inv-io-link"\s+href="/mobile/sku/\$\{encodeURIComponent\(sku\)\}"', src), \
        '입고·출고 링크(/mobile/sku/<sku>)가 시트에 없다'


def test_표는_없음을_빼기표로_그리고_그릇만_가로스크롤(client):
    src = _tpl_src()
    # 「—」 갈래 — null(조합 없음)만 —, 0 은 숫자 0 (회색)
    assert re.search(r"cell == null \? '<td class=\"none\">—</td>'", src), \
        '조합 없음(null) → 「—」 갈래가 없다'
    assert re.search(r'class="zero">\$\{fmt\(cell\)\}', src), \
        '0 은 숫자 그대로(회색) 그려야 한다 — 0 을 「—」 로 둔갑 금지'
    # 표 그릇만 가로 스크롤 (화면 전체는 안 밀림) — CSS 규칙 본문으로
    m = re.search(r'\.inv-mtx-wrap\s*\{([^}]*)\}', src)
    assert m and 'overflow-x: auto' in m.group(1), \
        '.inv-mtx-wrap 에 overflow-x: auto 가 없다 — 표가 화면을 민다'


def test_기능잠금은_CSS_까지_터치44_입력16(client):
    """함정 4종 ④ — 터치 목표·입력 크기를 CSS 규칙 본문으로 못 박는다."""
    src = _tpl_src()
    m = re.search(r'\.inv-btn\s*\{([^}]*)\}', src)
    assert m and 'min-height: 44px' in m.group(1), '.inv-btn 터치 44px 이 없다'
    m = re.search(r'\.inv-sheet select, \.inv-sheet input\s*\{([^}]*)\}', src)
    assert m and 'font-size: 16px' in m.group(1) and 'min-height: 44px' in m.group(1), \
        '시트 입력 16px·44px 규칙이 없다'


def test_모음전_연결은_읽기전용_배지다():
    """🔴 「모음전 적용」 스위치 발명 금지 — usage 개수 배지(읽기전용)만.

    시안 A4 에는 toggle 스위치가 그려져 있지만 실데이터에 켜고 끄는 축이 없다
    (실체 = OptionProductLink 개수). 템플릿에 토글·스위치가 생기면 빨강.
    """
    src = _tpl_src()
    assert re.search(r'inv-usage">\$\{fmt\(p\.usage\)\}곳', src), \
        '모음전 연결 N곳 배지가 없다'
    # 스위치 부품 자체가 없어야 한다 — 시안의 .toggle 스위치·체크박스 마크업 금지
    #  (toggleSheet 같은 함수 이름이 아니라 **부품 마크업**을 본다 — 낱말 오탐 방지)
    assert 'class="toggle' not in src, '시안의 toggle 스위치 부품이 들어왔다'
    assert 'type="checkbox"' not in src, '체크박스 — 모음전 적용은 읽기전용 배지다'
    assert '/api/usage' not in src and 'usage_toggle' not in src, \
        '모음전 적용을 켜고 끄는 쓰기 배선 냄새'


def test_KPI_는_서버값을_그대로_그린다():
    """같은 계산 두 곳 금지 — 폰 JS 가 kpi 를 재계산하면 PC 와 갈라진다."""
    src = _tpl_src()
    for key in ('kpi.all_options', 'kpi.in_stock', 'kpi.total_qty'):
        assert key in src, f'renderKpi 가 서버 {key} 를 안 쓴다'
    assert 'items.filter' not in src, '폰 JS 가 목록에서 KPI 를 재계산하는 냄새'

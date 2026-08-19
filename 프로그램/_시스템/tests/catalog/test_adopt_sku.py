# -*- coding: utf-8 -*-
"""미구성 SKU 편입 — 낱개 SKU 를 옵션 매트릭스의 축 값 자리로 이사시킨다.

여기서 지키는 것 (틀리면 에러 없이 데이터만 조용히 깨지는 것들)
  🔴 `canonical_sku` 는 **안 바뀐다** — 그 열쇠 하나로 재고 이력이 따라온다.
  🔴 `matrix_option_id` 는 **새 매트릭스**를 가리켜야 한다. 옛것을 계속 가리키면
     화면엔 새 묶음에 있는데 속은 옛 주인이라, 아무도 모른 채 전송에서 빠진다.
  🔴 `color_code`/`size_code`/`axis_values_json` 이 **축 이름대로** 채워져야 한다.
     빠뜨리면 옵션은 있는데 조합 격자에서 사라진다(큰 창이 축 수가 다른 옵션을 버린다).
"""
import json
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _new_box(client, name, brand='르무통'):
    """옵션함 하나 — 겉은 매트릭스(U…), 속은 모델 1 + 매트릭스 1."""
    r = client.post('/optgen/api/option-box', json={'name': name, 'brand': brand})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['code']


def _make_target(client, name, axes, brand='르무통'):
    """축 설계까지 마친 **편입 대상** 매트릭스.

    axes = [{'axis_name': '색상', 'values': ['블랙', '화이트']}, …]
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.option_service import save_step_design
    code = _new_box(client, name, brand)
    s = SessionLocal()
    try:
        save_step_design(s, code, axes)
        s.commit()
    finally:
        s.close()
    return code


def _make_unbuilt(client, name, *, color='블랙', size='250', brand='르무통'):
    """재고관리 「제품 추가」가 만드는 모양 그대로 — 옵션함 1 · 옵션 1 · 축 0개.

    🔴 시험용 DB 에 대상이 없으면 시험은 아무것도 안 본다. 그래서 심은 것이
       실제로 「미구성」으로 잡히는지는 `test_심은_미구성_SKU_가_실제로_잡힌다` 가 본다.
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    code = _new_box(client, name, brand)
    sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
    s = SessionLocal()
    try:
        s.add(Option(canonical_sku=sku, model_code=code, boxhero_sku=sku,
                     color_code=color, color_display=color,
                     size_code=size, size_display=size))
        s.commit()
    finally:
        s.close()
    return code, sku


def _opt(sku):
    """지금 저장돼 있는 옵션 한 줄을 그대로 읽어 온다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    s = SessionLocal()
    try:
        o = s.get(Option, sku)
        if o is None:
            return None
        return {'sku': o.canonical_sku, 'model_code': o.model_code,
                'matrix_option_id': o.matrix_option_id,
                'display_no': o.display_no,
                'color_code': o.color_code, 'size_code': o.size_code,
                'color_display': o.color_display, 'size_display': o.size_display,
                'axis_values': json.loads(o.axis_values_json or '[]')}
    finally:
        s.close()


def _matrix_id(code):
    """그 묶음의 원본 매트릭스 id — 「새 주인을 가리키나」를 재는 잣대."""
    from shared.db import SessionLocal
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    s = SessionLocal()
    try:
        mo = (s.query(MatrixOption)
              .filter_by(model_code=code, kind=KIND_ORIGIN).first())
        return mo.id if mo else None
    finally:
        s.close()


_TWO_AXES = [{'axis_name': '색상', 'values': ['블랙', '화이트']},
             {'axis_name': '사이즈', 'values': ['250', '260']}]


# ══════════════════════════════════════════════════════════════════
#  심은 것이 실제로 잡히나 — 이게 안 되면 아래 시험 전부가 헛것이다
# ══════════════════════════════════════════════════════════════════

def test_심은_미구성_SKU_가_실제로_잡힌다(client):
    code, sku = _make_unbuilt(client, '심은것확인')
    from shared.db import SessionLocal
    from lemouton.matrix.unbuilt import unbuilt_batch
    s = SessionLocal()
    try:
        assert unbuilt_batch(s, [code]) == {code}, \
            '심은 낱개 SKU 가 미구성으로 안 잡힌다 — 아래 시험이 전부 헛것이 된다'
    finally:
        s.close()
    r = client.get(f'/optgen/api/unbuilt-skus?q={sku}')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [it['sku'] for it in r.get_json()['items']] == [sku]


# ══════════════════════════════════════════════════════════════════
#  편입 — 잘 되는 길
# ══════════════════════════════════════════════════════════════════

def test_편입하면_묶음이_바뀌고_SKU_는_그대로다(client):
    """🔴 `canonical_sku` 가 바뀌면 재고 이력·URL 매핑·마켓 등록이 전부 유령이 된다."""
    target = _make_target(client, '편입대상', _TWO_AXES)
    src, sku = _make_unbuilt(client, '편입할낱개')

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙', '260']})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j['ok'] is True
    assert j['sku'] == sku and j['moved_from'] == src
    assert j['axis_values'] == ['블랙', '260']

    got = _opt(sku)
    assert got is not None, 'SKU 가 사라졌다 — 이사는 옮기는 것이지 새로 만드는 게 아니다'
    assert got['sku'] == sku, 'canonical_sku 가 바뀌었다'
    assert got['model_code'] == target


def test_원래_옵션함은_안_지운다(client):
    """텅 비어도 남긴다 — 되돌릴 수 있어야 한다(화면은 `hid` 규칙이 이미 감춘다)."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    target = _make_target(client, '대상_되돌리기', _TWO_AXES)
    src, sku = _make_unbuilt(client, '낱개_되돌리기')

    client.post(f'/optgen/api/box/{target}/adopt-sku',
                json={'sku': sku, 'axis_values': ['화이트', '250']})
    s = SessionLocal()
    try:
        assert s.query(Model).filter_by(model_code=src).first() is not None, \
            '원래 옵션함이 사라졌다 — 되돌릴 수 없게 된다'
        assert s.query(Option).filter_by(model_code=src).count() == 0
    finally:
        s.close()


def test_편입하면_새_매트릭스를_가리킨다(client):
    """🔴 옛 주인을 계속 가리키면 화면과 속이 갈리고 **아무도 모른다.**

    `owner_hook` 의 before_flush 는 **None 인 것만** 채우므로, 이사할 때 명시적으로
    비우지 않으면 옵션이 옛 매트릭스에 매달린 채 새 묶음 화면에 앉아 있게 된다.
    """
    target = _make_target(client, '대상_주인', _TWO_AXES)
    src, sku = _make_unbuilt(client, '낱개_주인')
    old_mo, new_mo = _matrix_id(src), _matrix_id(target)
    assert old_mo and new_mo and old_mo != new_mo, '시험 전제가 깨졌다'
    assert _opt(sku)['matrix_option_id'] == old_mo, '심을 때 옛 주인이 안 붙었다'

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙', '250']})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _opt(sku)['matrix_option_id'] == new_mo, \
        '옵션이 옛 매트릭스를 계속 가리킨다 — 전송·격자에서 조용히 빠진다'


def test_편입하면_축_배정대로_색상_사이즈_칸이_채워진다(client):
    """🔴 빠뜨리면 옵션은 있는데 조합 격자에서 사라진다(축 수 ≠ 값 수면 창이 버린다)."""
    target = _make_target(client, '대상_축배정', _TWO_AXES)
    _src, sku = _make_unbuilt(client, '낱개_축배정', color='빨강', size='999')

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['화이트', '260']})
    assert r.status_code == 200, r.get_data(as_text=True)

    got = _opt(sku)
    assert got['axis_values'] == ['화이트', '260'], '축 값이 저장 안 됐다'
    assert got['color_code'] == '화이트'
    assert got['size_code'] == '260'
    # 낱개 시절 표시 이름(빨강·999)이 남아 있으면 화면이 새 축 값과 다른 글자를 보인다
    assert got['color_display'] in (None, '화이트'), \
        f"옛 표시 이름이 남았다: {got['color_display']}"
    assert got['size_display'] in (None, '260'), \
        f"옛 표시 이름이 남았다: {got['size_display']}"


def test_모델_축이_있으면_색상_칸에_모델명이_안_들어간다(client):
    """🔴 「몇 번째 축인가」로 칸을 정하면 모델명이 `color_code` 에 박힌다.

    그 칸은 마켓 전송·재고·마진이 수백 곳에서 읽는다 — 경고 없이 값만 틀리는 자리다.
    규칙은 `lemouton/sourcing/axis_slot.py` 하나뿐이고, 여기서는 그것을 쓰는지만 본다.
    """
    target = _make_target(client, '대상_모델모음전', [
        {'axis_name': '모델', 'values': ['클래식', '메이트']},
        {'axis_name': '색상', 'values': ['블랙']},
        {'axis_name': '사이즈', 'values': ['250']},
    ])
    _src, sku = _make_unbuilt(client, '낱개_모델모음전')

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['클래식', '블랙', '250']})
    assert r.status_code == 200, r.get_data(as_text=True)

    got = _opt(sku)
    assert got['axis_values'] == ['클래식', '블랙', '250']
    assert got['color_code'] == '블랙', f"색상 칸에 모델명이 들어갔다: {got['color_code']}"
    assert got['size_code'] == '250'


def test_표시번호가_새_매트릭스_번호로_다시_붙는다(client):
    """번호 = 「매트릭스번호 + 순번」이라 이사하면 반드시 바뀐다."""
    target = _make_target(client, '대상_번호', _TWO_AXES)
    src, sku = _make_unbuilt(client, '낱개_번호')
    before = _opt(sku)['display_no']

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙', '250']})
    assert r.status_code == 200, r.get_data(as_text=True)

    after = _opt(sku)['display_no']
    assert after and after.startswith(target), \
        f'번호가 새 묶음 것이 아니다: {after} (대상 {target})'
    assert after != before, f'옛 묶음 번호를 그대로 달고 있다: {after}'
    assert r.get_json()['display_no'] == after, '응답이 실제 저장분과 다르다'


def test_편입해도_재고_이력이_같은_SKU_로_그대로_붙어_있다(client):
    """🔴 이 시험이 이 창구의 존재 이유다.

    `inventory_txs.option_canonical_sku` 는 FK 가 아니라 그냥 문자열 칸이라,
    SKU 를 새로 발급했다면 이력이 옛 SKU 에 남아 유령이 되고 재고가 조용히 0 이 된다.
    """
    from shared.db import SessionLocal
    from lemouton.inventory.inbound import create_inbound
    from lemouton.inventory.locations import ensure_default_location
    from lemouton.inventory.models import InventoryTx
    from shared.inventory_stock import get_stock_batch

    target = _make_target(client, '대상_재고', _TWO_AXES)
    _src, sku = _make_unbuilt(client, '낱개_재고')

    s = SessionLocal()
    try:
        loc = ensure_default_location(s)
        create_inbound(s, location_id=loc, option_canonical_sku=sku, qty=7,
                       unit_purchase_price=1000, memo='편입 시험 초기 재고',
                       created_by='시험')
        s.commit()
        assert get_stock_batch(s, [sku]).get(sku) == 7, '심은 재고가 안 잡힌다'
    finally:
        s.close()

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙', '260']})
    assert r.status_code == 200, r.get_data(as_text=True)

    s = SessionLocal()
    try:
        rows = (s.query(InventoryTx)
                .filter(InventoryTx.option_canonical_sku == sku).count())
        assert rows == 1, f'재고 이력이 같은 SKU 에 안 붙어 있다 (줄 수 {rows})'
        assert get_stock_batch(s, [sku]).get(sku) == 7, \
            '편입 뒤 재고가 달라졌다 — SKU 를 바꿨거나 이력을 옮겼다'
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════════
#  거절해야 하는 길 — 전부 한국어로 왜 안 되는지 말한다
# ══════════════════════════════════════════════════════════════════

def _has_korean(text: str) -> bool:
    return any('가' <= ch <= '힣' for ch in (text or ''))


def test_없는_축_값은_거절한다(client):
    """🔴 받아 주면 축 설계에 없는 유령 조합이 생겨 격자·전송에서 조용히 빠진다."""
    target = _make_target(client, '대상_없는값', _TWO_AXES)
    _src, sku = _make_unbuilt(client, '낱개_없는값')

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙', '999']})
    assert r.status_code == 400, r.get_data(as_text=True)
    err = r.get_json()['error']
    assert '사이즈' in err and '999' in err, f'어느 축의 무슨 값인지 안 알려준다: {err}'
    assert _has_korean(err)
    assert _opt(sku)['model_code'] != target, '거절했는데 옮겨졌다'


def test_축_수가_다르면_거절한다(client):
    target = _make_target(client, '대상_축수', _TWO_AXES)
    _src, sku = _make_unbuilt(client, '낱개_축수')

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙']})
    assert r.status_code == 400
    err = r.get_json()['error']
    assert '2' in err and '1' in err, f'몇 개가 필요한지 안 알려준다: {err}'
    assert _has_korean(err)


def test_중복_조합은_거절한다(client):
    """한 조합에 옵션이 둘이면 어느 쪽 가격·재고가 맞는지 알 수 없다."""
    target = _make_target(client, '대상_중복', _TWO_AXES)
    _s1, first = _make_unbuilt(client, '낱개_중복1')
    _s2, second = _make_unbuilt(client, '낱개_중복2')

    ok = client.post(f'/optgen/api/box/{target}/adopt-sku',
                     json={'sku': first, 'axis_values': ['블랙', '250']})
    assert ok.status_code == 200, ok.get_data(as_text=True)

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': second, 'axis_values': ['블랙', '250']})
    assert r.status_code == 400, r.get_data(as_text=True)
    err = r.get_json()['error']
    assert first in err, f'어느 옵션과 겹치는지 안 알려준다: {err}'
    assert _has_korean(err)
    assert _opt(second)['model_code'] != target, '거절했는데 옮겨졌다'


def test_미구성이_아닌_SKU_는_거절한다(client):
    """이미 축을 짠 매트릭스의 옵션을 빼 오면 그쪽 격자에 구멍이 난다."""
    built = _make_target(client, '이미짠매트릭스', _TWO_AXES)
    target = _make_target(client, '대상_미구성아님', _TWO_AXES)
    # 이미 축을 짠 묶음 안의 옵션 하나
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
    s = SessionLocal()
    try:
        s.add(Option(canonical_sku=sku, model_code=built, boxhero_sku=sku,
                     color_code='블랙', size_code='250',
                     axis_values_json=json.dumps(['블랙', '250'],
                                                 ensure_ascii=False)))
        s.commit()
    finally:
        s.close()

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['화이트', '260']})
    assert r.status_code == 400, r.get_data(as_text=True)
    err = r.get_json()['error']
    assert '축' in err, f'왜 미구성이 아닌지 안 알려준다: {err}'
    assert _has_korean(err)
    assert _opt(sku)['model_code'] == built, '거절했는데 옮겨졌다'


def test_판매용_모음전_옵션은_거절한다(client):
    """🔴 팔고 있는 상품의 옵션을 빼 오면 마켓에 옵션 빠진 상품이 남는다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    target = _make_target(client, '대상_판매용', _TWO_AXES)
    sell_code = f'파는것_{uuid.uuid4().hex[:8]}'
    sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
    s = SessionLocal()
    try:
        s.add(Model(model_code=sell_code, model_name_raw=sell_code, brand='르무통'))
        s.flush()
        s.add(Option(canonical_sku=sku, model_code=sell_code, boxhero_sku=sku,
                     color_code='블랙', size_code='250'))
        s.commit()
    finally:
        s.close()

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙', '250']})
    assert r.status_code == 400, r.get_data(as_text=True)
    assert '판매용' in r.get_json()['error']
    assert _opt(sku)['model_code'] == sell_code


def test_축이_없는_옵션함으로는_못_넣는다(client):
    """축 0개짜리 옵션함에 넣으면 미구성도 매트릭스도 아닌 어중간한 묶음이 된다."""
    empty = _new_box(client, '축없는대상')
    _src, sku = _make_unbuilt(client, '낱개_축없는대상')

    r = client.post(f'/optgen/api/box/{empty}/adopt-sku',
                    json={'sku': sku, 'axis_values': []})
    assert r.status_code == 400, r.get_data(as_text=True)
    assert '축' in r.get_json()['error']


def test_없는_대상과_없는_SKU_는_없다고_말한다(client):
    target = _make_target(client, '대상_없는것', _TWO_AXES)
    r = client.post('/optgen/api/box/U19700101-000000/adopt-sku',
                    json={'sku': 'SKU-NOPE', 'axis_values': ['블랙', '250']})
    assert r.status_code == 404
    assert _has_korean(r.get_json()['error'])

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': 'SKU-NOPE0000', 'axis_values': ['블랙', '250']})
    assert r.status_code == 404
    assert 'SKU-NOPE0000' in r.get_json()['error']


def test_축_값을_안_보내면_거절한다(client):
    target = _make_target(client, '대상_빈몸통', _TWO_AXES)
    _src, sku = _make_unbuilt(client, '낱개_빈몸통')
    r = client.post(f'/optgen/api/box/{target}/adopt-sku', json={'sku': sku})
    assert r.status_code == 400
    assert _has_korean(r.get_json()['error'])


# ══════════════════════════════════════════════════════════════════
#  목록 — 미구성만 내놓는다
# ══════════════════════════════════════════════════════════════════

def test_목록은_미구성만_내놓는다(client):
    """판매용 상품·구성 완료 매트릭스는 안 나와야 한다.

    🔴 판매용이 섞이면 사장님이 **팔고 있는 상품**을 다른 매트릭스에 편입시키게 된다.
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option

    _src, unbuilt_sku = _make_unbuilt(client, '목록_미구성')
    built = _make_target(client, '목록_구성완료', _TWO_AXES)
    sell_code = f'파는것_{uuid.uuid4().hex[:8]}'
    built_sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
    sell_sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
    s = SessionLocal()
    try:
        s.add(Option(canonical_sku=built_sku, model_code=built, boxhero_sku=built_sku,
                     color_code='블랙', size_code='250'))
        s.add(Model(model_code=sell_code, model_name_raw=sell_code, brand='르무통'))
        s.flush()
        s.add(Option(canonical_sku=sell_sku, model_code=sell_code,
                     boxhero_sku=sell_sku, color_code='블랙', size_code='250'))
        s.commit()
    finally:
        s.close()

    r = client.get('/optgen/api/unbuilt-skus?limit=500')
    assert r.status_code == 200, r.get_data(as_text=True)
    skus = {it['sku'] for it in r.get_json()['items']}
    assert unbuilt_sku in skus, '미구성 SKU 가 목록에서 빠졌다'
    assert built_sku not in skus, '축을 짠 매트릭스의 옵션이 섞였다'
    assert sell_sku not in skus, '🔴 판매용 상품의 옵션이 섞였다'


def test_목록은_재고를_원장에서_읽는다(client):
    """🔴 캐시 칸(`boxhero_stock_total`)을 읽으면 화면 숫자와 실재고가 갈린다.

    갱신을 빠뜨린 경로가 있어 실제로 갈린다 — 그래서 일부러 캐시에 **거짓 숫자**를
    박아 두고, 목록이 원장 합계를 내는지 본다.
    """
    from shared.db import SessionLocal
    from lemouton.inventory.inbound import create_inbound
    from lemouton.inventory.locations import ensure_default_location
    from lemouton.sourcing.models import Option

    _src, sku = _make_unbuilt(client, '목록_재고')
    s = SessionLocal()
    try:
        loc = ensure_default_location(s)
        create_inbound(s, location_id=loc, option_canonical_sku=sku, qty=3,
                       unit_purchase_price=0, memo='목록 재고 시험', created_by='시험')
        s.flush()
        s.get(Option, sku).boxhero_stock_total = 9999      # 일부러 틀린 캐시
        s.commit()
    finally:
        s.close()

    r = client.get(f'/optgen/api/unbuilt-skus?q={sku}')
    items = r.get_json()['items']
    assert len(items) == 1, f'심은 SKU 를 못 찾는다: {items}'
    assert items[0]['stock'] == 3, \
        f"캐시 칸을 읽고 있다(원장은 3): {items[0]['stock']}"


def test_목록은_편입한_뒤_사라진다(client):
    """미구성인지 아닌지는 그때그때 나오는 파생값 — 편입하면 저절로 벗겨져야 한다."""
    target = _make_target(client, '대상_목록에서빠짐', _TWO_AXES)
    _src, sku = _make_unbuilt(client, '낱개_목록에서빠짐')
    assert [it['sku'] for it in
            client.get(f'/optgen/api/unbuilt-skus?q={sku}').get_json()['items']] == [sku]

    client.post(f'/optgen/api/box/{target}/adopt-sku',
                json={'sku': sku, 'axis_values': ['블랙', '250']})
    assert client.get(f'/optgen/api/unbuilt-skus?q={sku}').get_json()['items'] == []


def test_브랜드로_추릴_수_있다(client):
    _src, mine = _make_unbuilt(client, '브랜드_내것', brand='나이키')
    _src2, other = _make_unbuilt(client, '브랜드_남의것', brand='아디다스')
    r = client.get('/optgen/api/unbuilt-skus?brand=나이키&limit=500')
    skus = {it['sku'] for it in r.get_json()['items']}
    assert mine in skus and other not in skus
    got = [it for it in r.get_json()['items'] if it['sku'] == mine][0]
    assert got['brand'] == '나이키', f"브랜드 상속이 안 된다: {got['brand']}"


def test_총건수는_자르기_전_숫자다(client):
    """🔴 상한값을 전체인 양 보여주면 화면이 거짓말을 한다(`_boxes` 가 겪은 사고)."""
    for i in range(3):
        _make_unbuilt(client, f'총건수_{i}')
    j = client.get('/optgen/api/unbuilt-skus?limit=1').get_json()
    assert len(j['items']) == 1
    assert j['total'] >= 3, f"자른 뒤 숫자를 전체라고 한다: {j['total']}"


# ── 옵션함이 많이 쌓인 날 ─────────────────────────────────────────────────────

def _심기_대량(n, prefix):
    """옵션함 n개 · 각각 옵션 1개 · 축 0개 — 미구성 SKU 를 한꺼번에 만든다.

    창구(`/optgen/api/option-box`)로 n번 부르면 느려서, 저장소에 바로 넣는다.
    모양은 `_make_unbuilt` 가 만드는 것과 같다(옵션함 · 옵션 1 · 축 없음).
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    s = SessionLocal()
    try:
        codes = [f'{prefix}{i:05d}' for i in range(n)]
        for code in codes:                      # 옵션함 먼저 — 옵션이 이걸 가리킨다
            s.add(Model(model_code=code, model_name_raw=code,
                        is_option_box=True, brand='르무통'))
        s.flush()
        skus = [f'SKU-{c}' for c in codes]
        for code, sku in zip(codes, skus):
            s.add(Option(canonical_sku=sku, model_code=code, boxhero_sku=sku,
                         color_code='블랙', size_code='250'))
        s.commit()
        return skus
    finally:
        s.close()


class _파라미터_최대치:
    """이 블록 안에서 나간 조회 중 **한 번에 넣은 값이 제일 많았던 개수**."""

    def __init__(self):
        from shared.db import engine
        self.engine = engine
        self.최대 = 0

    def _센다(self, conn, cursor, statement, parameters, context, executemany):
        if parameters is None:
            n = 0
        elif executemany:
            n = max((len(p) for p in parameters), default=0)
        else:
            try:
                n = len(parameters)
            except TypeError:
                n = 0
        self.최대 = max(self.최대, n)

    def __enter__(self):
        from sqlalchemy import event
        event.listen(self.engine, 'before_cursor_execute', self._센다)
        return self

    def __exit__(self, *exc):
        from sqlalchemy import event
        event.remove(self.engine, 'before_cursor_execute', self._센다)
        return False


def test_옵션함이_600개여도_한번에_다_묻지_않는다(client):
    """🔴 IN 절에 넣는 값 개수에는 DB 상한이 있다 — 넘기면 조회가 **통째로** 실패한다.

    이건 옵션함이 쌓인 날에만 나는 사고라, 몇 개 심어 두고 개발할 땐 영영 안 보이고
    라이브에서만 어느 날 갑자기 이 화면이 죽는다. 이 창구는 옵션함을 **전부** 넣고
    묻는 길이라 개수 상한이 없어 여기서 안 자르면 막을 곳이 없다.

    자르는 크기는 `readiness._CHUNK` 한 곳에서만 정하므로, 여기서도 그 값을 읽어 잰다
    (500 이라는 숫자를 시험이 또 적으면 저쪽을 고쳤을 때 이 시험이 낡는다).
    """
    from lemouton.matrix import readiness

    _심기_대량(600, 'U-대량-')

    with _파라미터_최대치() as 재기:
        r = client.get('/optgen/api/unbuilt-skus?limit=1')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['total'] >= 600, '심은 600개가 목록에 안 잡혔다'

    assert 재기.최대 <= readiness._CHUNK, (
        f'한 조회에 값을 {재기.최대}개나 넣었다 — {readiness._CHUNK}개씩 잘라야 한다')


def test_600개일_때도_최근_만든_순서가_지켜진다(client):
    """🔴 잘라서 물으면 SQL 의 `ORDER BY` 는 묶음 안에서만 맞다.

    묶음들을 그냥 이어 붙이면 전체 순서가 깨져, 첫 화면에 **가장 최근 것**이 아니라
    첫 묶음의 것이 올라온다 — 에러는 안 나고 화면만 틀리는 종류의 사고다.
    """
    import datetime as dt

    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model

    skus = _심기_대량(600, 'U-순서-')
    # 뒤쪽(코드가 큰 쪽)일수록 **오래된** 날짜를 준다. 그러면 「코드 내림차순」과
    # 「최근 만든 순」이 정반대가 되어, 날짜를 안 보고 세우면 바로 들킨다.
    # 날짜를 한참 미래로 두는 이유 — 시험용 DB 는 파일 하나를 같이 쓰므로 앞선
    # 시험들이 심어 둔 옵션함(오늘 날짜)이 섞여 있다. 그것들보다 확실히 앞에 서야
    # 이 시험이 「내가 심은 순서」만 본다.
    기준 = dt.datetime(2099, 1, 1, 0, 0, 0)
    s = SessionLocal()
    try:
        for i in range(600):
            (s.query(Model).filter_by(model_code=f'U-순서-{i:05d}').one()
             .created_at) = 기준 - dt.timedelta(minutes=i)
        s.commit()
    finally:
        s.close()

    items = client.get('/optgen/api/unbuilt-skus?limit=3').get_json()['items']
    # 가장 최근 = i 가 0·1·2 인 것들. 자르기 전 순서를 그대로 지켰다면 이 셋이다.
    assert [it['sku'] for it in items] == skus[:3], \
        f'묶음 안에서만 세워 첫 화면이 틀렸다: {[it["sku"] for it in items]}'

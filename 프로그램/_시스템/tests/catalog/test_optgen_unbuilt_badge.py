# -*- coding: utf-8 -*-
"""모음전 옵션 생성(직접) 목록의 「미구성 SKU」 이름 칸 배지.

🔴 판정은 여기서 다시 안 잰다 — `lemouton/matrix/unbuilt.py` 하나뿐이다.
   이 시험은 그 판정 결과가 `_boxes()`(목록 화면의 자료)에 **그대로** 실리는지,
   그리고 판매용·구성 완료 매트릭스에는 **안 실리는지**만 본다.
"""
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
    r = client.post('/optgen/api/option-box', json={'name': name, 'brand': brand})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['code']


def _make_unbuilt(client, name, brand='르무통'):
    """옵션함 1 · 옵션 1 · 축 0개 — `test_adopt_sku.py` 의 같은 이름 헬퍼와 같은 모양."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    code = _new_box(client, name, brand)
    sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
    s = SessionLocal()
    try:
        s.add(Option(canonical_sku=sku, model_code=code, boxhero_sku=sku,
                     color_code='블랙', color_display='블랙',
                     size_code='250', size_display='250'))
        s.commit()
    finally:
        s.close()
    return code, sku


def _make_target(client, name, axes, brand='르무통'):
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


_TWO_AXES = [{'axis_name': '색상', 'values': ['블랙', '화이트']},
             {'axis_name': '사이즈', 'values': ['250', '260']}]


def _row(client, code):
    from shared.db import SessionLocal
    from webapp.routes.optgen import _boxes
    s = SessionLocal()
    try:
        rows, _n = _boxes(s)
        found = [r for r in rows if r['code'] == code]
        assert found, f'{code} 가 목록에 없다'
        return found[0]
    finally:
        s.close()


def test_미구성_SKU는_목록에서_unbuilt가_참이다(client):
    code, _sku = _make_unbuilt(client, '배지_미구성')
    assert _row(client, code)['unbuilt'] is True


def test_축을_짠_매트릭스는_unbuilt가_거짓이다(client):
    """옵션이 여럿인데 축만 안 짠 것과 헷갈리면 안 된다 — 완성된 매트릭스는 배지가 없어야 정상."""
    code = _make_target(client, '배지_구성완료', _TWO_AXES)
    assert _row(client, code)['unbuilt'] is False


def test_옵션이_2개인_옵션함은_unbuilt가_거짓이다(client):
    """축 0개라도 옵션이 여럿이면 「짜다 만 매트릭스」지 미구성 SKU 가 아니다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    code = _new_box(client, '배지_옵션2개')
    s = SessionLocal()
    try:
        for i in range(2):
            sku = 'SKU-' + uuid.uuid4().hex[:8].upper()
            s.add(Option(canonical_sku=sku, model_code=code, boxhero_sku=sku,
                         color_code='블랙', size_code=str(250 + i)))
        s.commit()
    finally:
        s.close()
    assert _row(client, code)['unbuilt'] is False


def test_편입하면_배지가_사라진다(client):
    """미구성 여부는 저장하는 값이 아니라 그때그때 나오는 파생값이다."""
    target = _make_target(client, '배지_편입대상', _TWO_AXES)
    code, sku = _make_unbuilt(client, '배지_편입할것')
    assert _row(client, code)['unbuilt'] is True

    r = client.post(f'/optgen/api/box/{target}/adopt-sku',
                    json={'sku': sku, 'axis_values': ['블랙', '250']})
    assert r.status_code == 200, r.get_data(as_text=True)
    # 원래 옵션함은 안 지운다(adopt_sku 규칙) — 옵션 0개짜리로 남아 배지 판정도 거짓이어야 한다
    assert _row(client, code)['unbuilt'] is False


def test_목록_화면에도_배지_마크업이_뜬다(client):
    """`_boxes()` 값만이 아니라 실제 렌더된 HTML 에도 실리는지 — 템플릿 조건이 끊기지 않았는지."""
    _code, _sku = _make_unbuilt(client, '배지_렌더확인')
    r = client.get('/optgen/?tab=direct')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '배지_렌더확인' in html, '심은 옵션함이 화면에 없다'
    assert 'ub-d-wrap' in html, '미구성 배지 마크업이 화면에 안 실린다'
    assert '미구성 SKU' in html

# -*- coding: utf-8 -*-
"""수기 등록 화면 — 렌더 + 자동완성 차단."""
import re

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_manual_tab_renders_form(client):
    html = client.get('/bulk/?tab=manual').get_data(as_text=True)
    assert 'id="bulk-manual-form"' in html
    for field in ('name', 'brand', 'sale_price', 'notice_type', 'detail_html',
                  'delivery_fee', 'return_fee', 'as_phone', 'as_guide',
                  'notice_warranty', 'notice_as'):
        assert f'name="bd_{field}"' in html, f'입력칸 없음: {field}'


def test_all_inputs_block_autofill(client):
    """크롬 자동완성이 값을 덮어쓴 사고 재발 방지 — 모든 칸에 autocomplete=off."""
    html = client.get('/bulk/?tab=manual').get_data(as_text=True)
    form = html.split('id="bulk-manual-form"')[1].split('</form>')[0]
    inputs = re.findall(r'<(?:input|select|textarea)\b[^>]*>', form)
    assert inputs, '폼에 입력칸이 없다'
    for tag in inputs:
        assert 'autocomplete="off"' in tag, f'자동완성 차단 누락: {tag}'


def test_notice_type_has_four_options(client):
    html = client.get('/bulk/?tab=manual').get_data(as_text=True)
    for t in ('WEAR', 'SHOES', 'BAG', 'FASHION_ITEMS'):
        assert f'value="{t}"' in html

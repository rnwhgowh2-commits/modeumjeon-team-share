# -*- coding: utf-8 -*-
"""연동 확인(만들 것 5번) — 옵션함 화면의 소싱처 연동 성적표.

라이브 실측(2026-08-04): 옵션 24개 중 6개가 주소 없이 비어 있고, 등록된 주소
「무신사_베이지」는 어느 옵션도 안 덮는데 — **화면 어디에도 안 나왔다.**
그대로 팔면 사고인데 알 방법이 없었다. 이 성적표가 그걸 잡는다.

원칙: 저장된 값만 보여준다(「지금 다시 긁기」 없음 — 확정 ①+②) ·
      주소 없는 옵션의 매입가는 「확인 불가」(폴백 금지).

🔴 [2026-08-20 병합 정리] 이 성적표는 이제 box.html 에 서버 렌더되지 않는다 —
   옵션 조합 창의 「재고 입력」 서랍(`renderStockDrawer`, option_url_modal.js)이
   `/optgen/api/box/<code>/rows` 를 불러와 클라이언트에서 그린다. box.html 은
   그 창을 열기만 하는 껍데기가 됐다. 그래서:
   · 「배선돼 있다」·「칸이 생겼다」류(문구·구조 존재)는 정적 자산(JS 소스) 검사로,
   · 「지어내지 않는다」류(실제 계산 결과)는 API 응답 검사로 옮긴다.
   실제 화면에 그려지는지는 실브라우저로 직접 확인했다(이번 병합 검증).
"""
import os

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture
def box(client):
    """옵션 두 개짜리 옵션함을 만들어 (코드, 재고 서랍 API 응답)을 주고, 끝나면 지운다."""
    code = client.post('/optgen/api/option-box',
                       json={'name': '연동확인 검사함', 'brand': '르무통'}).get_json()['code']
    client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '색상', 'values': ['블랙']},
                  {'axis_name': '사이즈', 'values': ['230', '240']}],
        # 사용자 룰 — 자동 전체조합 금지, 만들 조합을 명시해야 생성된다
        'selected': [['블랙', '230'], ['블랙', '240']]})
    j = client.get(f'/optgen/api/box/{code}/rows').get_json()
    yield code, j
    client.delete(f'/optgen/api/option-box/{code}')


@pytest.fixture
def stock_drawer_js():
    js_path = os.path.join(os.path.dirname(__file__), '..', '..',
                           'webapp', 'static', 'option_url_modal.js')
    with open(js_path, encoding='utf-8') as f:
        return f.read()


def test_성적표가_배선돼_있다(stock_drawer_js):
    """이미 있는 창구(source-urls)를 그대로 읽는다 — 새 창구를 만들면 갈린다."""
    assert 'oum-stk-bar' in stock_drawer_js
    assert '/source-urls' in stock_drawer_js


def test_표에_연동_칸이_생겼다(stock_drawer_js):
    assert '소싱처' in stock_drawer_js
    assert '마지막 확인' in stock_drawer_js
    assert '최저 매입가' in stock_drawer_js


def test_행이_축_값을_실어_짝지을_수_있다(box):
    """행에 열쇠(SKU)가 아니라 축 값(색상·사이즈)이 실려 온다 — 서랍이 그걸로 짝짓는다."""
    _code, j = box
    assert j['rows'], '옵션 표본이 비었다 — 시험이 헛돈다'
    for r in j['rows']:
        assert 'color' in r and 'size' in r


def test_지어내지_않는다(box):
    """주소 없는 옵션 = 「확인 불가」 — 값 폴백 금지(정합성 3원칙).

    API 자체는 소싱처 연동을 안 세므로(그 계산은 서랍이 `/source-urls` 를
    따로 불러 한다), 주소를 안 붙인 이 표본이 실제로 화면에서 「확인 불가」로
    뜨는지는 실브라우저로 확인했다 — 여기서는 그 문구가 소스에 그대로
    남아 있는지만 지킨다(값 대신 대표가를 지어내는 코드로 바뀌면 걸린다).
    """
    js_path = os.path.join(os.path.dirname(__file__), '..', '..',
                           'webapp', 'static', 'option_url_modal.js')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    assert '확인 불가' in js
    assert '주소 없음' in js


def test_걸러보기가_있고_다시긁기는_없다(stock_drawer_js):
    assert '주소 없는 것만 보기' in stock_drawer_js
    assert '다시 긁' not in stock_drawer_js and '지금 다시' not in stock_drawer_js, \
        '크롤을 화면에서 돌리는 단추는 확정 범위 밖(무거움)'


def test_실패도_말한다(stock_drawer_js):
    """창구가 죽으면 조용히 사라지지 않고 「확인 못 함」을 띄운다."""
    assert '연동 상태를 확인하지 못했습니다' in stock_drawer_js

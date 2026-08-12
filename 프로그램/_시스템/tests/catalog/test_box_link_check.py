# -*- coding: utf-8 -*-
"""연동 확인(만들 것 5번) — 옵션함 화면의 소싱처 연동 성적표.

라이브 실측(2026-08-04): 옵션 24개 중 6개가 주소 없이 비어 있고, 등록된 주소
「무신사_베이지」는 어느 옵션도 안 덮는데 — **화면 어디에도 안 나왔다.**
그대로 팔면 사고인데 알 방법이 없었다. 이 성적표가 그걸 잡는다.

원칙: 저장된 값만 보여준다(「지금 다시 긁기」 없음 — 확정 ①+②) ·
      주소 없는 옵션의 매입가는 「확인 불가」(폴백 금지).
"""
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
def box_html(client):
    """옵션 두 개짜리 옵션함을 만들어 화면을 받고, 끝나면 지운다."""
    code = client.post('/optgen/api/option-box',
                       json={'name': '연동확인 검사함', 'brand': '르무통'}).get_json()['code']
    client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '색상', 'values': ['블랙']},
                  {'axis_name': '사이즈', 'values': ['230', '240']}],
        # 사용자 룰 — 자동 전체조합 금지, 만들 조합을 명시해야 생성된다
        'selected': [['블랙', '230'], ['블랙', '240']]})
    yield client.get(f'/optgen/box/{code}').get_data(as_text=True)
    client.delete(f'/optgen/api/option-box/{code}')


def test_성적표가_배선돼_있다(box_html):
    """이미 있는 창구(source-urls)를 그대로 읽는다 — 새 창구를 만들면 갈린다."""
    assert 'lc-bar' in box_html
    assert '/source-urls' in box_html


def test_표에_연동_칸이_생겼다(box_html):
    assert '<th class="c">소싱처</th>' in box_html
    assert '마지막 확인' in box_html
    assert '최저 매입가' in box_html


def test_행이_축_값을_실어_짝지을_수_있다(box_html):
    """행에 열쇠(SKU)를 안 싣는 화면이라(설계 확정) 축 값으로 짝짓는다."""
    assert 'data-color=' in box_html and 'data-size=' in box_html


def test_지어내지_않는다(box_html):
    """주소 없는 옵션 = 「확인 불가」 — 값 폴백 금지(정합성 3원칙)."""
    assert '확인 불가' in box_html
    assert '주소 없음' in box_html


def test_걸러보기가_있고_다시긁기는_없다(box_html):
    assert '주소 없는 것만 보기' in box_html
    assert '다시 긁' not in box_html and '지금 다시' not in box_html, \
        '크롤을 화면에서 돌리는 단추는 확정 범위 밖(무거움)'


def test_실패도_말한다(box_html):
    """창구가 죽으면 조용히 사라지지 않고 「확인 못 함」을 띄운다."""
    assert '연동 상태를 확인하지 못했습니다' in box_html

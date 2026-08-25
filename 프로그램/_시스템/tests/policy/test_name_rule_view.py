# -*- coding: utf-8 -*-
"""상품명 조립기가 **화면에 실제로 그려지나**.

🔴 이번 세션에서 이미 두 번 겪은 형태:
   ① 창구는 되는데 화면에 단추가 없어 사장님은 「안 된다」고 느낀다.
   ② 엔진은 있는데 부르는 곳이 0곳이라 아무 일도 안 일어난다.
   그래서 「화면에 그려지나」를 코드가 아니라 **렌더된 글자**로 확인한다.
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)

    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass

    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


@pytest.fixture()
def html(client):
    pid = client.post('/api/policies', json={'name': '시험 정책'}).get_json()['id']
    r = client.get(f'/policies/{pid}?market=coupang')
    assert r.status_code == 200, r.status_code
    return r.get_data(as_text=True)


def test_조립기가_화면에_있다(html):
    assert 'nr-wrap' in html
    assert '조립 순서' in html


def test_조각_단추_자리가_있다(html):
    """단추는 JS 가 그린다 — 그릴 자리와 불러올 주소가 둘 다 있어야 한다."""
    assert 'id="nr-toks"' in html
    assert '/api/name-rules/tokens' in html


def test_끌어서_순서를_바꿀_수_있다(html):
    """사장님이 명시적으로 요청한 것 — 드래그앤드랍."""
    assert 'draggable="true"' in html
    assert "addEventListener('dragstart'" in html
    assert "addEventListener('drop'" in html


def test_규칙_세트를_고르는_자리가_있다(html):
    assert 'id="nr-sel"' in html
    assert '직접 정함' in html


def test_미리보기는_서버_엔진을_부른다(html):
    """🔴 화면에서 조립을 흉내 내면 실제 전송과 갈린다."""
    assert '/api/name-rules/preview' in html


def test_빈_조립_순서의_위험을_화면이_말한다(html):
    assert '통째로 사라' in html


def test_규칙이_여러_정책에_퍼진다는_것을_말한다(html):
    """고쳤을 때 다른 정책까지 바뀐다는 걸 모르면 사고가 난다."""
    assert '정책 전부' in html


def test_잘림_표시_자리가_있다(html):
    """11번가·롯데온은 바이트 한도가 있어 잘린다 — 잘렸다는 걸 보여줘야 한다."""
    assert 'nr-cutbadge' in html
    assert '잘림' in html


def test_기존_항목_화면을_밀어내지_않았다(html):
    """회귀 — 상품명 블록을 끼우면서 다른 항목이 사라지지 않았나."""
    assert 'pull-one' in html          # 공통 불러오기 단추
    assert 'id="nr-prev"' in html


def test_고른_규칙이_새로고침해도_남는다(client):
    """🔴 [2026-08-24 실화면에서 잡음] 저장은 됐는데 화면이 안 보여줬다.

    화면에 넘기는 `policy` 는 **정해진 칸만 담은 사본**이라, 칸을 안 넣으면
    템플릿에서 조용히 빈 값이 된다. 그러면 규칙을 골라도 새로고침하면 풀린 것처럼
    보이고, 사장님은 「저장이 안 된다」고 느낀다(실제로는 저장돼 있다).
    """
    pid = client.post('/api/policies', json={'name': '시험 정책'}).get_json()['id']
    rid = client.post('/api/name-rules',
                      json={'name': '기본', 'token_order': ['brand', 'origin_name']}
                      ).get_json()['id']
    client.post(f'/api/policies/{pid}/name-rule', json={'name_rule_id': rid})

    html = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert f'data-rule="{rid}"' in html, '고른 규칙이 화면에 안 실렸다'


def test_규칙을_안_고른_정책은_빈_값이다(client):
    pid = client.post('/api/policies', json={'name': '시험 정책'}).get_json()['id']
    html = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert 'data-rule=""' in html

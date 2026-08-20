# -*- coding: utf-8 -*-
"""「정책 생성」 목록 화면 — 사이드바(S1)·만들기 카드·옮겨오기 삭제 (2026-08-04 사장님 확정).

시안 v3 확정 반영: A2(첫 칸 점선 「＋ 정책 생성」 카드) + B5(가운데 만들기 창)
+ S1(왼쪽 사이드바: 검색·브랜드·정책 상태·정렬) + 「가격 정책에서 옮겨오기」 상자 삭제
(라이브 대조 실측 — 옛 가격 템플릿 2개 모두 이사 완료, 남은 대상 0).
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """tests/policy/test_policy_routes.py 와 같은 격리 방식."""
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


def _new_policy(client, name, brand=''):
    from lemouton.policy.service import create_policy
    s = client._Session()
    try:
        p = create_policy(s, name=name, brand=brand)
        s.commit()
        return p.id
    finally:
        s.close()


def _body(client):
    return client.get('/policies').get_data(as_text=True)


# ── 사이드바 (S1) ────────────────────────────────────────────────────────

def test_사이드바가_있다(client):
    body = _body(client)
    assert 'pl-sb' in body
    assert '정책 이름·브랜드로 찾기' in body


def test_사이드바에_브랜드_부류가_나온다(client):
    _new_policy(client, '사이드바브랜드', brand='르무통')
    _new_policy(client, '사이드바무브랜드')
    body = _body(client)
    assert '르무통' in body
    assert '브랜드 없음' in body


def test_사이드바에_상태_부류와_설명이_나온다(client):
    """[2026-08-19 사장님 확정] 체크박스 4분류(동시거름) → 클릭식 3단(+하위 2단, 겹치지 않는 자리)."""
    body = _body(client)
    for label in ('전체', '기본정책', '정책 생성 완료', '적용 완료', '미적용', '정책 생성중'):
        assert label in body, f'상태 부류 「{label}」 이 없다'
    assert 'data-hv=' in body, '호버 설명창 앵커가 없다'
    assert 'data-s="default"' in body, '기본정책 줄에 거름 데이터가 없다'
    assert '판매가 계산에 쓰지 않아요' in body, '호버 설명창 내용(생성중)이 없다'
    assert '여러 번 재사용하는 기본 틀' in body, '호버 설명창 내용(기본정책)이 없다'
    # hover-info-card 표준 상수 — 열기 140ms·닫기 250ms 가 지켜지는지 문자열로 못박는다
    assert 'OPEN_DELAY = 140' in body and 'CLOSE_DELAY = 250' in body


def test_사이드바에_정렬이_있다(client):
    body = _body(client)
    assert '채움 많은 순' in body
    assert '정책명 순' in body


# ── 만들기 (2026-08-19 확정 — 옵션 매트릭스 생성과 같은 작은 단추 + B5 가운데 창) ──

def test_만들기_단추가_있다(client):
    body = _body(client)
    assert 'addcard' in body
    assert 'pl-addbtn' in body
    assert '+ 정책 생성' in body


def test_만들기_창이_있다(client):
    body = _body(client)
    assert 'npback' in body
    assert '새 정책 만들기' in body
    assert '안 적어도 돼요' in body


def test_옛_머리줄_입력폼은_없다(client):
    """시안 v3 확정 — 머리줄 오른쪽 검색창처럼 생긴 입력 2개+버튼을 없앴다."""
    assert 'pl-new' not in _body(client)


# ── 옮겨오기 삭제 ────────────────────────────────────────────────────────

def test_옮겨오기_상자가_없다(client):
    """2026-08-04 사장님 확정 — 옛 가격 템플릿 2개 모두 이사 완료(남은 대상 0).

    서버 API(/api/policies/price-parity·migrate-template)는 남겨 둔다 —
    화면만 없앴다. 되살릴 일이 생기면 이 파일 이력에서 마크업을 찾는다.
    """
    body = _body(client)
    assert '가격 정책에서 옮겨오기' not in body
    assert '대조해 보기' not in body


def test_옮겨오기_API는_그대로_산다(client):
    r = client.get('/api/policies/price-parity')
    assert r.status_code == 200
    assert r.get_json()['ok'] is True


# ── 거르기용 데이터 속성 ────────────────────────────────────────────────

def test_카드에_거르기_데이터가_붙는다(client):
    _new_policy(client, '데이터속성정책', brand='르무통')
    body = _body(client)
    assert 'data-brand="르무통"' in body
    assert 'data-ready="0"' in body
    assert 'data-applied="0"' in body
    assert 'data-find=' in body

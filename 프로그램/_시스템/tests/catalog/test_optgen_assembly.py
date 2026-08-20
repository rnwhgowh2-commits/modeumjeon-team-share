# -*- coding: utf-8 -*-
"""조립대 승격 — 상품 만들기는 「옵션생성 & 상품생성」 탭 안에서 한다.

🔴 2026-08-06 사장님 확정(1번a) — 전엔 하위탭③에서 줄을 누르면 `/matrix/<id>`
   (상품 관리 소속)로 가서, 생성 탭에서 시작한 작업이 상품관리 탭에서 진행됐다.
   설계서 §4 확정: /matrix 격자 = 보기 전용, 조립대 = 하위탭③으로 승격.

🔴 확정 2번 — 상품을 만들면 하위탭③ 초기화면으로 돌아와 배너로 알리고,
   다음 단계(상품 가공)를 가리킨다.
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


@pytest.fixture
def matrix_with_option(client):
    """옵션 1개가 담긴 옵션함 — 끝나면 지운다(테스트 DB 는 파일로 공유된다)."""
    from shared.db import SessionLocal
    from lemouton.matrix.models import MatrixOption
    from lemouton.sourcing.models import Option
    name = f'조립대시험_{uuid.uuid4().hex[:8]}'
    code = client.post('/optgen/api/option-box',
                       json={'name': name, 'brand': '르무통'}).get_json()['code']
    sku = f'SKU-{uuid.uuid4().hex[:12]}'
    s = SessionLocal()
    try:
        s.add(Option(canonical_sku=sku, model_code=code,
                     color_code='블랙', size_code='FREE'))
        s.commit()
        mo_id = s.query(MatrixOption).filter_by(model_code=code).first().id
    finally:
        s.close()
    yield {'code': code, 'id': mo_id, 'name': name}
    client.delete(f'/optgen/api/option-box/{code}')


def test_상품생성_목록의_줄은_이_탭의_조립대로_간다(client, matrix_with_option):
    """🔴 /matrix/… 로 가면 상단 탭이 「상품 관리」로 점프한다 — 그 어긋남 방지."""
    html = client.get('/optgen?tab=product').get_data(as_text=True)
    assert f"/optgen/product/{matrix_with_option['id']}" in html
    assert 'data-href="/matrix/' not in html


def test_조립대가_생성_탭_소속으로_열린다(client, matrix_with_option):
    r = client.get(f"/optgen/product/{matrix_with_option['id']}")
    assert r.status_code == 200, r.get_data(as_text=True)
    html = r.get_data(as_text=True)
    # [2026-08-19 노션 상품생성 3번] 카드 제목 문구는 지우고 만들기 버튼만 남겼다 —
    # 「조립대가 있다」는 이제 그 버튼(id=build)로 확인한다.
    assert 'id="build"' in html                      # 조립대가 있다
    assert '← 모음전 상품 생성 목록' in html          # 돌아가는 곳도 이 탭


def test_관리_탭의_매트릭스_상세는_보기_전용이다(client, matrix_with_option):
    """설계서 §4 — 확인은 상품관리, 작업은 생성 탭."""
    html = client.get(f"/matrix/{matrix_with_option['id']}").get_data(as_text=True)
    assert 'id="build"' not in html                   # 조립대 없음
    assert '확인 전용' in html
    assert f"/optgen/product/{matrix_with_option['id']}" in html  # 작업 입구 안내


def test_없는_묶음은_조립대도_없다고_한다(client):
    assert client.get('/optgen/product/999999999').status_code == 404


def test_만들기_성공_배너가_다음_단계를_가리킨다(client):
    """확정 2번 — 성공 정보 + 초기화면 + 다음 단계(상품 가공) 안내."""
    html = client.get('/optgen?tab=product&made=M20260806-000001'
                      '&code=M20260806-000001&opts=4').get_data(as_text=True)
    assert '상품이 만들어졌어요' in html
    assert '/policies/apply' in html                  # 다음 단계: 상품 정책 적용
    assert '옵션 4개' in html


def test_배너는_made_없으면_안_뜬다(client):
    html = client.get('/optgen?tab=product').get_data(as_text=True)
    assert '상품이 만들어졌어요' not in html

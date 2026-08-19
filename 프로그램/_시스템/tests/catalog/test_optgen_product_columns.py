# -*- coding: utf-8 -*-
"""「모음전 상품 생성」 탭 — 칼럼 재구성(체크리스트 [1]번, 이슈 #1081).

이 파일이 지키는 것
  🔴 왼쪽 판의 「어디까지 왔나」는 **삭제됐다** — 되살아나면 여기서 걸린다.
  🔴 칼럼 순서·내용은 사장님 확정 그대로: NO(체크박스) · 옵션 매트릭스(이름·
     브랜드·모델명 1행 + 매트릭스번호·원본/파생 딱지 2행) · 모음전 구성 ·
     옵션축 · SKU 연결상태 · 상품&정책 연결상태(2행 배지) · 소싱처.
  🔴 상품&정책 연결상태는 `made_ok`·`policy_ok` 값 그대로 초록/회색이 갈린다 —
     새 판정을 화면에서 다시 하지 않는다(`_attach_product_status` 가 이미 정함).
"""
import re

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _row(**over):
    base = {
        'id': 1, 'no': 'U-TEST-1', 'name': '판시험함', 'kind': 'origin',
        'box': True, 'brand': '르무통', 'options': 2, 'code': 'U-TEST-1',
        'phase': None, 'missing': [], 'show': 'wait',
        'moum_kind_label': None, 'axis_pairs': [], 'model_names': [],
        'sources': [], 'urls': 0, 'map': None, 'sku_info': None,
        'made_ok': False, 'policy_ok': False, 'made': [],
    }
    base.update(over)
    return base


def test_어디까지_왔나_판은_삭제됐다(client, monkeypatch):
    """되살아나면 여기서 잡는다 — 체크리스트 [1]번 확정 사항."""
    import webapp.routes.optgen as og
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [_row()])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    # .stg-block CSS 정의 자체는 matrix/index.html·bundles/tower.html 도 같이 쓰므로
    # 남아 있는 게 정상 — 이 화면이 그 마크업을 **렌더하지 않는지**만 본다.
    assert 'class="stg-block"' not in html, '「어디까지 왔나」 판이 되살아났다 — 삭제 확정 사항 위반'
    assert '어디까지 왔나' not in html
    # 브랜드 필터는 그대로 남아야 한다.
    assert 'og-rail-t">브랜드' in html


def test_칼럼_머리줄_순서(client, monkeypatch):
    import webapp.routes.optgen as og
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [_row()])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    heads = re.findall(r'<th[^>]*>([^<]*)</th>', html.split('og-tb og-c3 og-tb4')[1][:2000])
    heads = [h.strip() for h in heads if h.strip()]
    assert heads == ['NO', '옵션 매트릭스', '모음전 구성', '옵션축', 'SKU 연결상태',
                     '상품&amp;정책 연결상태', '소싱처'], heads


def test_옵션매트릭스_칸_1행에_이름_브랜드_모델명(client, monkeypatch):
    import webapp.routes.optgen as og
    row = _row(name='르무통 메이트', brand='르무통', model_names=['메이트', '스니커즈'])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    # 1행 = 이름 + 브랜드 + 모델명이 한 줄에.
    assert re.search(r'<b title="르무통 메이트">르무통 메이트</b> · 르무통 · 메이트, 스니커즈', html), \
        '1행에 이름·브랜드·모델명이 같이 안 뜬다'
    # 2행 = 매트릭스 번호 + 원본 딱지만(브랜드·모델명은 위로 옮겨졌으니 여기 없어야 함).
    frac = re.search(r'<div class="og-frac">(.*?)</div>', html, re.S)
    assert frac and 'U-TEST-1' in frac.group(1) and '원본' in frac.group(1)
    assert '르무통' not in frac.group(1)


def test_상품_정책_연결상태_배지_색(client, monkeypatch):
    import webapp.routes.optgen as og
    made_row = _row(id=1, code='U-A', made_ok=True, policy_ok=False)
    none_row = _row(id=2, code='U-B', made_ok=False, policy_ok=False)
    both_row = _row(id=3, code='U-C', made_ok=True, policy_ok=True)
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [made_row, none_row, both_row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    blocks = re.findall(r'<div class="og-pp2">(.*?)</div>', html, re.S)
    assert len(blocks) == 3
    assert 'stgb sale">상품 생성' in blocks[0] and 'stgb wait">정책 적용' in blocks[0]
    assert 'stgb wait">상품 생성' in blocks[1] and 'stgb wait">정책 적용' in blocks[1]
    assert 'stgb sale">상품 생성' in blocks[2] and 'stgb sale">정책 적용' in blocks[2]


def test_옵션축_칩과_모음전_구성(client, monkeypatch):
    import webapp.routes.optgen as og
    row = _row(moum_kind_label='색상 모음전', axis_pairs=[('색상', 3), ('사이즈', 4)])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert '색상 모음전' in html
    assert re.search(r'axis-chip">색상 <b>3</b>', html)
    assert re.search(r'axis-chip">사이즈 <b>4</b>', html)


def test_소싱처_SKU_호버배지_data속성(client, monkeypatch):
    """새 API 를 만들지 않는다 — 옵션 생성 탭과 같은 og-idbadge·og-srcbadge 를 그대로 쓴다."""
    import webapp.routes.optgen as og
    row = _row(code='U-HOV', sources=[{'key': 'musinsa', 'label': '무신사', 'n': 2}])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert 'class="og-idbadge" data-code="U-HOV"' in html
    assert 'class="og-srcbadge" data-code="U-HOV"' in html
    # data-labels 는 tojson 이라 한글이 \uXXXX 로 이스케이프된다(direct 탭과 같은 배선) —
    # 그대로도 JS JSON.parse 가 「무신사」로 정확히 복원한다. 키(musinsa)만 확인.
    assert '&#34;key&#34;: &#34;musinsa&#34;' in html or '"key": "musinsa"' in html


def test_만든_상품_바로가기는_그대로(client, monkeypatch):
    """상품&정책 칸에도 기존 「만든 상품 바로가기」 링크가 남아 있어야 한다(회귀 없음)."""
    import webapp.routes.optgen as og
    row = _row(made_ok=True, made=[{'code': 'M1', 'name': '만든상품', 'no': 'M-1',
                                    'policy_url': '/policies/apply?model=M1',
                                    'policy_tip': '이 상품에 정책 붙이기'}])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert '만든상품 →' in html
    assert '/policies/apply?model=M1' in html

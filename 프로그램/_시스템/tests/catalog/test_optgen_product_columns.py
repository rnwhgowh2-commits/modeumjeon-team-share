# -*- coding: utf-8 -*-
"""「모음전 상품 생성」 탭 — 칼럼 재구성(체크리스트 [1]번, 이슈 #1081).

이 파일이 지키는 것
  🔴 왼쪽 판의 「어디까지 왔나」는 **삭제됐다** — 되살아나면 여기서 걸린다.
  🔴 칼럼 순서·내용은 사장님 확정 그대로: NO(체크박스) · 옵션 매트릭스(이름·
     브랜드·모델명 1행 + 매트릭스번호·원본/파생 딱지 2행) · 모음전 구성 ·
     옵션축 · SKU 연결상태 · 상품&정책 연결상태(2행 배지) · 소싱처.
  🔴 상품&정책 연결상태는 `made_ok`·`policy_ok` 값 그대로 초록/회색이 갈린다 —
     새 판정을 화면에서 다시 하지 않는다(`_attach_product_status` 가 이미 정함).

[이슈 #1095 · 사장님 확정 「막대 채우기」] `made` 목록(파생 등으로 만든 상품이
실제로 있는 보통 줄)은 더 이상 단순 2행 배지가 아니라 **막대**를 쓴다 — 상품
여러 개 중 몇 개에 정책이 붙었는지(예 "2개 중 1개") 를 정확히 보여주기 위해서다.
단순 초록/회색으로는 "하나라도 있으면 초록"이 되어 부분완료를 다 됐다고 속인다.
2행 배지(`.og-pp2`)는 `made` 없이 `made_ok` 만 참인 드문 줄(이 매트릭스 자체가
이미 상품인 경우)에만 남는다.
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
    """`made` 리스트가 없는(=이 매트릭스 자체가 이미 상품인) 드문 줄만 2행 배지.

    [이슈 #1095] 셋 중 `made_ok=False` 인 줄은 이제 「대기중」 단일 배지로
    바뀌었다 — `.og-pp2` 는 만들었다/정책 있다 둘 중 하나라도 참인 줄에서만 쓴다.
    """
    import webapp.routes.optgen as og
    made_row = _row(id=1, code='U-A', made_ok=True, policy_ok=False)
    none_row = _row(id=2, code='U-B', made_ok=False, policy_ok=False)
    both_row = _row(id=3, code='U-C', made_ok=True, policy_ok=True)
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [made_row, none_row, both_row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    blocks = re.findall(r'<div class="og-pp2">(.*?)</div>', html, re.S)
    assert len(blocks) == 2, blocks
    assert 'stgb sale">상품 생성' in blocks[0] and 'stgb wait">정책 적용' in blocks[0]
    assert 'stgb sale">상품 생성' in blocks[1] and 'stgb sale">정책 적용' in blocks[1]
    assert re.search(r'<span class="og-badge stgb wait">대기중</span>', html), (
        'made_ok=False 인 줄은 「대기중」 단일 배지여야 한다')


def test_상품_여러개_중_일부만_정책이면_막대가_부분_채워진다(client, monkeypatch):
    """🔴 「막대 채우기」의 핵심(#1095) — 단순 초록/회색으론 "2개 중 1개"를
    표현 못 해 초록(=다 됐다)으로 거짓말한다."""
    import webapp.routes.optgen as og
    row = _row(code='U-BAR', made=[
        {'code': 'M1', 'name': '상품A', 'no': 'M-1',
         'policy_url': '/a', 'policy_tip': ''},
        {'code': 'M2', 'name': '상품B', 'no': 'M-2',
         'policy_url': '/b', 'policy_tip': ''},
    ])
    # has_policy 는 _attach_product_status 가 policy_models() 결과로 붙인다 —
    # 여기서는 그 함수가 실제로 도는 경로(og._matrices 대신 og._attach_product_status
    # 자체)로 확인해야 정확하지만, 목록 렌더 계약은 M1 만 정책 있는 걸로 심는다.
    row['made'][0]['has_policy'] = True
    row['made'][1]['has_policy'] = False
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert '상품 생성 2개' in html
    assert '<span class="og-polbar-n">1/2</span>' in html, (
        '정책 붙은 상품 1개 · 전체 2개 — 진행 표시가 1/2 이어야 한다')
    bar = re.search(r'<span class="og-polbar"[^>]*>(.*?)</span>', html).group(1)
    assert bar.count('<i class="on">') == 1 and bar.count('<i class="">') == 1, (
        f'막대 칸이 부분 채움(1/2)으로 안 그려진다: {bar}')
    # 기존 만든 상품 바로가기 목록은 막대 아래 그대로 남아야 한다(회귀 없음).
    assert '상품A →' in html and '상품B →' in html


def test_상품_생성_전이면_대기중_단일_배지(client, monkeypatch):
    import webapp.routes.optgen as og
    row = _row(made_ok=False, policy_ok=False, made=[])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [row])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert re.search(r'<span class="og-badge stgb wait">대기중</span>', html)
    # 'og-pp2'/'og-polbar' 는 <style> 정의 자체엔 늘 있다 — 이 줄 렌더에 실제로
    # 쓰였는지(class="…") 만 본다.
    assert 'class="og-pp2"' not in html
    assert 'class="og-polbar"' not in html


def test_attach_product_status가_made항목마다_has_policy를_붙인다(client, monkeypatch):
    """실제 배선 확인 — `policy_models()` 를 통해 얻은 정책 집합으로 `made` 각
    항목에 `has_policy` 가 붙는지(화면 렌더가 아니라 함수 계약 자체를 검사)."""
    import webapp.routes.optgen as og

    mats = [{'id': 1, 'code': 'U-X', 'box': True,
            'made': [{'code': 'M-HAS', 'name': 'a', 'no': '1'},
                     {'code': 'M-NOT', 'name': 'b', 'no': '2'}]}]
    monkeypatch.setattr('webapp.routes.bundles_tower.policy_models',
                        lambda s, codes: {'M-HAS'})
    og._attach_product_status(None, mats)

    made = mats[0]['made']
    by_code = {d['code']: d['has_policy'] for d in made}
    assert by_code == {'M-HAS': True, 'M-NOT': False}


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

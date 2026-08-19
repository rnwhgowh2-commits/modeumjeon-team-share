# -*- coding: utf-8 -*-
"""「모음전 상품 생성」 탭 — 전 옵션매트릭스 노출 + 상품&정책 연결상태 칼럼.

[이슈 #1090] 이 파일은 원래 왼쪽 「어디까지 왔나」 판(위상별로 줄을 숨기고
보여주는 판)을 지켰다. 그 판은 사장님 확정으로 **삭제됐다** — 이 탭은 이제
위상과 무관하게 **모든 옵션매트릭스를 늘 표에 보여줘야** 하므로, 판이 있던
전제 자체가 사라졌다. 그래서 이 파일이 지키는 것을 아래로 바꾼다:

  🔴 **모든 옵션매트릭스가 표(행)에 뜬다** — 이미 상품을 만든(PHASE_USED)
     매트릭스도 빠지지 않는다. 「옵션 생성」 목록과 달리 이 탭은 같은
     매트릭스로 파생 상품을 여러 번 만들 수 있어야 하므로(사장님 확정 항목1),
     한 번 썼다고 목록에서 빼면 다시 만들 방법이 없어진다.
  🔴 **「상품&정책 연결상태」 칼럼(막대 채우기)** — 상품을 안 만들었으면
     「대기중」, 만들었으면 개수 배지 + 정책 적용 진행 막대가 뜬다.
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


def _자리():
    """og-name 셀에 흔한 필수 자리를 채운 옵션매트릭스 한 줄 — 다른 필드는
    호출부가 덮어쓴다."""
    return {'id': 1, 'no': 'U-TEST-1', 'name': '판시험함', 'kind': 'origin',
            'box': True, 'brand': '르무통', 'options': 2, 'code': 'U-TEST-1',
            'missing': [], 'made': [], 'sources': [], 'axis_pairs': [],
            'moum_kind_label': None, 'map': None}


def test_이미_상품을_만든_매트릭스도_표에서_안_빠진다(client, monkeypatch):
    """🔴 옵션 생성 탭은 「상품 생성에 사용됨」을 목록에서 빼지만, 이 탭은 다르다
    (사장님 확정 항목1 — 파생으로 상품을 또 만들 수 있어야 한다)."""
    from lemouton.matrix.readiness import PHASE_USED
    import webapp.routes.optgen as og

    한줄 = dict(_자리(), phase=PHASE_USED,
               made=[{'code': 'M1', 'name': '만든상품', 'no': 'M-TEST-1',
                      'has_policy': True, 'policy_url': '/x', 'policy_tip': ''}])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [한줄])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert '판시험함' in html, f'상품 생성에 이미 쓴 매트릭스가 표에서 빠졌다'


def test_상품_생성_전이면_대기중_배지(client, monkeypatch):
    from lemouton.matrix.readiness import PHASE_READY
    import webapp.routes.optgen as og

    한줄 = dict(_자리(), phase=PHASE_READY, made=[])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [한줄])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert re.search(r'<span class="og-badge stgb wait">대기중</span>', html), (
        '상품을 아직 안 만들었으면 「대기중」 배지가 떠야 한다')


def test_상품_여러개_중_일부만_정책있으면_막대가_부분채워진다(client, monkeypatch):
    """🔴 「막대 채우기」의 핵심 — 단순 초록/회색 2색으로는 「2개 중 1개만 정책」을
    표현할 수 없어서 막대로 정했다(사장님 시안 확인 2번)."""
    import webapp.routes.optgen as og

    한줄 = dict(_자리(), phase='ready', made=[
        {'code': 'M1', 'name': '상품A', 'no': 'M-1', 'has_policy': True,
         'policy_url': '/a', 'policy_tip': ''},
        {'code': 'M2', 'name': '상품B', 'no': 'M-2', 'has_policy': False,
         'policy_url': '/b', 'policy_tip': ''},
    ])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [한줄])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert '상품 생성 2개' in html
    assert '<span class="og-polbar-n">1/2</span>' in html, (
        '정책 붙은 상품 1개 · 전체 2개 — 진행 표시가 1/2 이어야 한다')
    # 막대 칸 2개 중 정확히 1개만 채워졌는지(순서까지) 확인 — 첫 상품만 정책 있음
    bar = re.search(r'<span class="og-polbar"[^>]*>(.*?)</span>', html).group(1)
    assert bar.count('<i class="on">') == 1 and bar.count('<i class="">') == 1, (
        f'막대 칸이 부분 채움(1/2)으로 안 그려진다: {bar}')


def test_미완료_사유는_SKU연결상태_호버로_흡수된다(client, monkeypatch):
    """🔴 사장님 확정 — 사이드바가 없어지면서 「옵션 없음」 같은 미완료 사유는
    표에서 완전히 안 보이는 게 아니라, SKU 연결상태 호버(data-missing)로 옮겨간다."""
    import webapp.routes.optgen as og

    한줄 = dict(_자리(), phase='draft', missing=['축 없음', '소싱처 URL 없음'])
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [한줄])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert 'data-missing="축 없음 · 소싱처 URL 없음"' in html


def test_왼쪽_어디까지왔나_판은_더_이상_없다(client, monkeypatch):
    """🔴 회귀 방지 — 사이드바 삭제가 다시 슬그머니 돌아오지 않는지."""
    import webapp.routes.optgen as og

    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: [_자리()])

    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert 'id="og-stages"' not in html
    assert '브랜드' in html and 'id="og-find"' in html, (
        '브랜드 필터·검색창은 남아 있어야 한다')

# -*- coding: utf-8 -*-
"""[2026-08-05 A안] 매트릭스 목록 열 확장 + 오른쪽 미끄럼판.

지켜야 할 것:
  · 목록 집계는 매트릭스마다 쿼리를 돌리지 않고도 **맞는 값**을 준다
  · 품절 = 「아는 재고가 전부 0」 — 모르는 것(None)은 품절로 세지 않는다 (무결성 원칙 1)
  · 마켓 등록의 정본 = MarketRegistration(market_product_id 있는 행)
  · 판 API 는 원본·파생 모두 열리고, 파생에는 「원본으로 가기」가 실린다
  · 재고관리 전용(단독_)은 행에 solo 상태가 붙어 화면이 기본 숨김한다
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
def world():
    """모델(옵션 2색×2사이즈) + 원본·파생 매트릭스 + 상품 링크 + 마켓 + 소싱처.

    테스트 DB 는 파일로 공유된다 — 끝나면 만든 것을 전부 지운다.
    """
    import app as appmod                     # noqa: F401 — 모델 등록 + 테이블 생성
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import (
        BundleMatrixLink, MatrixOption, MatrixOptionMember,
    )
    from lemouton.matrix.service import create_derived, ensure_origin
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import BundleSourceUrl, Model, Option
    from lemouton.uploader.models import MarketRegistration

    tag = uuid.uuid4().hex[:8]
    code = f'판테스트_{tag}'
    prod = f'판테스트상품_{tag}'
    skus = [f'SKU-PANEL{tag[:4].upper()}{i}' for i in range(4)]
    s = SessionLocal()
    made = {'sp': [], 'so': [], 'mo': []}
    try:
        s.add(Model(model_code=code, model_name_raw='판테스트', model_name_display='판테스트',
                    brand='르무통', category='스니커즈'))
        for i, sku in enumerate(skus):
            s.add(Option(canonical_sku=sku, model_code=code,
                         color_code='블랙' if i < 2 else '네이비',
                         size_code=str(250 + (i % 2) * 10)))
        s.flush()
        mo = ensure_origin(s, s.get(Model, code))
        mo.display_no = f'U20260805-{tag[:6]}'
        d = create_derived(s, origin=mo, name='판테스트 일부', skus=skus[:2])
        made['mo'] = [mo.id, d.id]

        # 만들어 간 상품 + 그 상품의 마켓 등록
        s.add(Model(model_code=prod, model_name_raw='판테스트 상품',
                    model_name_display='판테스트 상품'))
        s.add(Option(canonical_sku=f'SKU-PROD{tag[:4].upper()}', model_code=prod,
                     color_code='블랙', size_code='250'))
        s.add(BundleMatrixLink(model_code=prod, matrix_option_id=mo.id, copied_count=2))
        s.add(MarketRegistration(canonical_sku=f'SKU-PROD{tag[:4].upper()}',
                                 market='smartstore', market_product_id='889900'))
        # 원본 자신의 옵션 하나도 마켓에 등록돼 있다 (목록 「마켓 등록」 열의 근거)
        s.add(MarketRegistration(canonical_sku=skus[0], market='coupang',
                                 market_product_id='C-1'))

        # 소싱처 — 정상 1곳(재고 0 = 품절), 실패 1곳(재고 모름 → 품절 아님)
        sp1 = SourceProduct(site='musinsa', url=f'https://musinsa.test/{tag}',
                            last_status='ok')
        sp2 = SourceProduct(site='ssf', url=f'https://ssf.test/{tag}',
                            last_status='error')
        s.add_all([sp1, sp2])
        s.flush()
        so1 = SourceOption(source_product_id=sp1.id, color_text='블랙',
                           size_text='250', current_stock=0, current_price=10000)
        so2 = SourceOption(source_product_id=sp2.id, color_text='블랙',
                           size_text='260', current_stock=None, current_price=None)
        s.add_all([so1, so2])
        s.flush()
        s.add(OptionSourceLink(canonical_sku=skus[0], source_option_id=so1.id))
        s.add(OptionSourceLink(canonical_sku=skus[1], source_option_id=so2.id))
        made['sp'] = [sp1.id, sp2.id]
        made['so'] = [so1.id, so2.id]
        # 모델에 주소만 붙어 있고 옵션 매칭은 아직 없는 소싱처 — 「주소만」으로 보여야 한다
        s.add(BundleSourceUrl(model_code=code, source_key='lotteon',
                              url=f'https://lotteon.test/{tag}'))
        s.commit()
        yield {'code': code, 'origin_id': mo.id, 'derived_id': d.id,
               'skus': skus, 'prod': prod}
    finally:
        s.rollback()
        s.query(BundleSourceUrl).filter(
            BundleSourceUrl.model_code == code).delete()
        s.query(OptionSourceLink).filter(
            OptionSourceLink.source_option_id.in_(made['so'] or [-1])).delete()
        s.query(SourceOption).filter(SourceOption.id.in_(made['so'] or [-1])).delete()
        s.query(SourceProduct).filter(SourceProduct.id.in_(made['sp'] or [-1])).delete()
        s.query(MarketRegistration).filter(
            MarketRegistration.canonical_sku.in_(
                skus + [f'SKU-PROD{tag[:4].upper()}'])).delete()
        s.query(BundleMatrixLink).filter(
            BundleMatrixLink.matrix_option_id.in_(made['mo'] or [-1])).delete()
        s.query(MatrixOptionMember).filter(
            MatrixOptionMember.matrix_option_id.in_(made['mo'] or [-1])).delete()
        s.query(MatrixOption).filter(MatrixOption.id.in_(made['mo'] or [-1])).delete()
        s.query(Option).filter(Option.model_code.in_([code, prod])).delete()
        s.query(Model).filter(Model.model_code.in_([code, prod])).delete()
        s.commit()
        s.close()


# ── 목록 집계 ───────────────────────────────────────────────────────────────

def test_목록_집계가_맞는_값을_준다(world):
    from shared.db import SessionLocal
    from lemouton.matrix.models import MatrixOption
    from webapp.routes.matrix import _index_stats
    s = SessionLocal()
    try:
        mos = (s.query(MatrixOption)
               .filter(MatrixOption.id.in_([world['origin_id'], world['derived_id']]))
               .all())
        st = _index_stats(s, mos)
    finally:
        s.close()
    org = st[world['origin_id']]
    assert org['products'] == 1, '이 묶음에서 만들어 간 상품 1개'
    assert org['markets'] == ['coupang'], 'market_product_id 있는 행만 정본'
    assert org['src'] == 3, '옵션 매칭 2 + 주소만(BundleSourceUrl) 1 — URL 합집합'
    assert org['src_fail'] == 1
    assert org['soldout'] == 1, '재고 0 인 옵션만 — 모르는 것(None)은 품절이 아니다'
    assert org['colors'] == 2 and org['sizes'] == 2 and org['active'] == 4
    drv = st[world['derived_id']]
    assert drv['src'] == 3, '파생도 원본 모델의 주소를 물려받아 같은 소싱처를 본다'


def test_목록_행에_상태가_실린다(client, world):
    html = client.get('/matrix').get_data(as_text=True)
    assert '담긴 상품' in html and '이상 신호' in html and '최근 확인' in html
    # 원본 행: 이상 있음(실패 1·품절 1) + 숨김 아님. <tr> 태그가 여러 줄이라 블록으로 본다.
    i = html.find(f'data-id="{world["origin_id"]}"')
    assert i >= 0
    tag = html[max(0, i - 600):i + 600]
    assert 'data-warn="1"' in tag
    assert 'data-hid="0"' in tag, '옵션 있는 정상 묶음을 숨기면 기본 화면에서 사라진다'
    # [2026-08-06 사장님 지적] 만들어 간 상품은 없지만 마켓 등록이 있으면
    # 「미사용」이 아니라 「직접 판매」 — 파생이 그 경우다(옵션이 쿠팡에 등록됨).
    j = html.find(f'data-id="{world["derived_id"]}"')
    assert j >= 0
    dtag = html[j:j + 1800]
    assert '직접 판매' in dtag and '미사용' not in dtag


def test_검색이_브랜드_SKU_상품명으로도_된다(client, world):
    """[2026-08-06 사장님 요청] 찾기 한 칸 = 이름·번호·브랜드·SKU·상품명 전부."""
    row_mark = f'data-id="{world["origin_id"]}"'
    # SKU 로 서버 검색
    html = client.get('/matrix?q=' + world['skus'][0]).get_data(as_text=True)
    assert row_mark in html, 'SKU 번호로 묶음을 역추적할 수 있어야 한다'
    # 담긴 상품명으로
    html = client.get('/matrix?q=판테스트 상품').get_data(as_text=True)
    assert row_mark in html
    # 브랜드로
    html = client.get('/matrix?q=르무통').get_data(as_text=True)
    assert row_mark in html
    # 엉뚱한 말은 안 나온다
    html = client.get('/matrix?q=없는말xyz9').get_data(as_text=True)
    assert row_mark not in html


# ── 미끄럼판 API ────────────────────────────────────────────────────────────

def test_판_원본_요약_연결_소싱처(client, world):
    j = client.get(f'/api/matrix/{world["origin_id"]}/panel').get_json()
    assert j['ok'], j
    assert j['summary']['count'] == 4 and j['summary']['brand'] == '르무통'
    assert j['summary']['editable'] is True
    # 연결 관계 — 만들어 간 상품과 그 상품의 마켓
    assert j['tree']['products'][0]['name'] == '판테스트 상품'
    assert j['tree']['products'][0]['markets'][0]['key'] == 'smartstore'
    assert j['tree']['derived'][0]['count'] == 2
    # 소싱처 — URL 단위 합산: 매칭 2곳 + 주소만 1곳, 실패 상태 실림
    assert len(j['sources']) == 3
    fails = [x for x in j['sources'] if x['status'] == 'error']
    assert len(fails) == 1
    only_addr = [x for x in j['sources'] if x['matched'] == 0]
    assert len(only_addr) == 1, '주소만 붙은 소싱처도 한 줄로 보인다'
    # 재고 0 만 아는 곳 = 품절, 모르는 곳 = None(확인 불가)
    stocks = sorted([str(x['stock']) for x in j['sources']])
    assert stocks == ['None', 'None', '품절']


def test_판_격자_칸에_최종매입가_소싱처이름_재고가_실린다(client, world):
    """[2026-08-06 사장님 요청] 칸 = 최종매입가 · 어느 소싱처인지 · 재고."""
    j = client.get(f'/api/matrix/{world["origin_id"]}/panel').get_json()
    cells = [c for row in j['summary']['grid'] for c in row['cells'] if c]
    assert cells, '격자에 칸이 있어야 한다'
    # 소싱처가 붙은 칸은 그 값이 「어디서 나온 것인지」를 들고 있다
    linked = [c for c in cells if c['n']]
    assert linked and all('best' in c for c in linked)
    assert any(c['best'] for c in linked), '연결된 칸엔 소싱처 이름이 실려야 한다'
    # 재고 0 인 옵션(픽스처의 skus[0])은 0 으로, 모르는 곳은 None 으로 — 지어내지 않는다
    by_sku = {c['sku']: c for c in cells}
    assert by_sku[world['skus'][0]]['stock'] == 0
    assert by_sku[world['skus'][1]]['stock'] is None


def test_판_파생에는_원본으로_가기가_실린다(client, world):
    j = client.get(f'/api/matrix/{world["derived_id"]}/panel').get_json()
    assert j['ok'], j
    assert j['summary']['editable'] is False
    assert j['summary']['origin']['id'] == world['origin_id']
    assert j['summary']['count'] == 2


def test_판_없는_묶음은_404(client):
    r = client.get('/api/matrix/99999999/panel')
    assert r.status_code == 404

# -*- coding: utf-8 -*-
"""매트릭스 일괄 조회 — 「일괄로 읽어도 답이 한 글자도 안 바뀐다」 대조.

무엇을 지키나
  `_option_matrix_data_many` 는 모델코드마다 똑같이 돌던 조회를 앞에서 한 번에 모아
  둔다(`_prime_matrix_batch`). 모아 둔 것을 **쪼개 쓰는** 자리가 하나라도 어긋나면
  소싱처 차례·가격·재고가 조용히 바뀐다 — 그게 곧 금전 손실이라 여기서 못 박는다.

어떻게 대조하나
  · **예전 길** = `_option_matrix_one(s, code, {})` — 그릇이 비어 있어 모든 조회를
    모델코드마다 스스로 한다(속도 개선 전과 같은 조회 경로).
  · **일괄 길** = `_option_matrix_data_many(codes)` — 앞에서 모아 담고 쪼개 쓴다.
  둘의 응답 전체(JSON)를 통째로 비교한다. 한 칸이라도 다르면 실패.

회귀 감시 (PR#814·#835 와 같은 방식)
  상품 종수를 늘려도 **쿼리 수가 종수에 비례해 늘지 않는다**를 못 박는다.
"""
import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lemouton.sourcing.models as M
import webapp.routes.api_pricing as AP
from lemouton.inventory.models import InventoryProduct, InventoryTx, OptionProductLink
from lemouton.pricing import fee_defaults as FD
from lemouton.sources.models import (
    CardDiscountUserPref, SourceOption, SourceProduct,
)
from lemouton.sourcing.models_pricing import (
    OptionPriceConfig, OptionSourceUrl, SourceRegistry,
)
from lemouton.templates.models import PriceTemplate
from shared.db import Base

#: 어느 상품도 안 쓰는 소싱상품 수 — 「소싱상품 표 전체를 몇 번 훑나」의 눈금.
N_LOOSE_SP = 300

SRC = [
    ('lemouton', 'https://lemouton.co.kr'),
    ('musinsa', 'https://musinsa.com'),
    ('ssf', 'https://ssfshop.com'),
    ('lotteon', 'https://lotteon.com'),
]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(autouse=True)
def _fee_seed(engine, monkeypatch):
    """요율 기본표는 프로세스 캐시라 시험 사이에 새 DB 를 못 본다 → 비우고 이 DB 로."""
    FD.invalidate()
    s = Session(engine)
    FD._seed_if_missing(s)
    s.commit()
    s.close()
    monkeypatch.setattr("shared.db.SessionLocal", sessionmaker(bind=engine))
    yield
    FD.invalidate()


@pytest.fixture
def seeded(engine):
    """가지가 골고루 갈리게 심는다 — 혜택·카드·정책·재고연결·축·그룹·매칭실패."""
    s = Session(engine)
    for i, (key, url) in enumerate(SRC, start=1):
        s.add(SourceRegistry(id=i, name=f'소싱처{i}', main_url=url, sort_order=i))
    tpl = PriceTemplate(id=1, name='기본', ss_margin_rate=0.12, ss_fee_rate=0.06,
                        coupang_fee_rate=0.1155, ss_delivery_fee=3000,
                        coupang_delivery_fee=0, rounding_unit=100,
                        boxhero_purchase_price=40000)
    s.add(tpl)
    # 소싱처 혜택(사이트 기본) + 옵션 예외 → 최종매입가가 표면가와 갈리게
    s.add(M.SourceBenefitTemplate(source_id=1, benefit_name='카드할인',
                                  benefit_type='rate', value=0.05, enabled=True,
                                  sort_order=1))
    s.add(M.SourceBenefitTemplate(source_id=2, benefit_name='쿠폰',
                                  benefit_type='amount', value=3000, enabled=True,
                                  sort_order=1))
    s.add(CardDiscountUserPref(scope='global', source_id=1, enabled=False))

    sp_id = 0
    codes = []
    for mi in range(8):
        mc = f'MC{mi}'
        codes.append(mc)
        s.add(M.Model(model_code=mc, model_name_raw=f'모델{mi}', brand='르무통',
                      price_template_id=(1 if mi % 2 == 0 else None)))
        if mi % 3 == 0:                      # 축 이름을 따로 정한 상품
            s.add(M.BundleOptionStep(model_code=mc, step_no=1, axis_name='컬러',
                                     values_json=json.dumps(['블랙', '화이트'])))
            s.add(M.BundleOptionStep(model_code=mc, step_no=2, axis_name='사이즈',
                                     values_json=json.dumps(['250', '260'])))
        skus = []
        for ci, color in enumerate(('블랙', '화이트')):
            for si, size in enumerate(('250', '260')):
                sku = f'{mc}-{color}-{size}'
                skus.append(sku)
                s.add(M.Option(canonical_sku=sku, model_code=mc,
                               color_code=color, color_display=color,
                               size_code=size, size_display=size,
                               sort_order=ci * 2 + si,
                               brand=('무신사' if si == 0 else None),
                               boxhero_avg_purchase_price=(38000 if mi % 2 else 0),
                               use_purchase_inventory=bool(mi % 2),
                               src_fixed_ss_active=bool(mi == 1),
                               src_fixed_ss_price=(99000 if mi == 1 else 0)))
        # 가격 설정 — 수기 가격·자동 끔이 섞이게
        s.add(OptionPriceConfig(canonical_sku=skus[0], auto_enabled=False,
                                manual_ss_price=123400, manual_cp_price=125600,
                                manual_stock=7, margin_rate=0.2))
        # 재고관리 연결 + 사입 재고
        s.add(InventoryProduct(canonical_sku=skus[1], option_name='재고품',
                               model_code=mc, brand='르무통'))
        s.add(OptionProductLink(option_canonical_sku=skus[1],
                                product_canonical_sku=skus[1]))
        s.add(InventoryTx(option_canonical_sku=skus[1], tx_type='in', qty=5,
                          status='completed'))
        # 소싱처 URL 2개 (하나는 옵션까지 크롤됨, 하나는 상품만)
        for u, (key, dom) in enumerate(SRC[:2]):
            sp_id += 1
            purl = f'{dom}/goods/{mc}-{u}?NaPm=ct%3Dx%7Cch%3D{sp_id}'
            s.add(SourceProduct(id=sp_id, site=key, url=purl,
                                product_name=f'{mc} 상품', last_price=90000 + mi * 100,
                                last_stock=12, last_status='ok'))
            if u == 0:
                for color in ('블랙', '화이트'):
                    for size in ('250', '260'):
                        # 한 조합만 일부러 빼서 「매칭 실패」 가지를 태운다
                        if mi % 4 == 0 and color == '화이트' and size == '260':
                            continue
                        s.add(SourceOption(source_product_id=sp_id,
                                           color_text=color, size_text=size,
                                           current_price=88000 + mi * 100,
                                           current_stock=(0 if size == '250' else 4)))
            bsu = M.BundleSourceUrl(model_code=mc, source_key=key, url=purl,
                                    label=f'URL{u}', url_type='단품')
            s.add(bsu)
            s.flush()
            for sku in skus:
                s.add(M.OptionSourceUrlLink(option_canonical_sku=sku,
                                            bundle_source_url_id=bsu.id))
        # 명부에 없는 커스텀 소싱처 2곳 — 셀·컬럼이 'key:' 합성 id 로 붙는 갈래
        if mi % 5 == 0:
            for ck in ('hmall', 'lotteimall'):
                sp_id += 1
                curl = f'https://{ck}.com/p/{mc}?utm_source=z'
                s.add(SourceProduct(id=sp_id, site=ck, url=curl,
                                    last_price=95000 + mi, last_stock=3,
                                    last_status='ok'))
                cb = M.BundleSourceUrl(model_code=mc, source_key=ck, url=curl,
                                       label=ck, url_type='단품')
                s.add(cb)
                s.flush()
                for sku in skus:
                    s.add(M.OptionSourceUrlLink(option_canonical_sku=sku,
                                                bundle_source_url_id=cb.id))
        # 레거시 URL 표(빈 표가 정상이지만 갈래는 살아 있다)
        if mi == 2:
            s.add(OptionSourceUrl(canonical_sku=skus[0], source_id=3,
                                  product_url='https://ssfshop.com/legacy/1',
                                  price_cached=70000, stock_cached=3))
        # 옵션 예외 혜택
        if mi == 5:
            s.add(M.OptionBenefitOverride(canonical_sku=skus[0], source_id=1,
                                          benefit_name='카드할인',
                                          benefit_type='amount', value=7000,
                                          enabled=True, sort_order=1))
    # 삭제된 소싱상품 — 색인에 안 들어가야 한다
    s.add(SourceProduct(id=9001, site='ssf', url='https://ssfshop.com/dead/1',
                        last_price=1, deleted_at=__import__('datetime').datetime(2026, 1, 1)))
    # 아무 상품도 안 쓰는 소싱상품 — 「표 전체 색인」이 몇 번 도는지 재는 눈금이 된다
    for i in range(N_LOOSE_SP):
        s.add(SourceProduct(id=10000 + i, site='ssf',
                            url=f'https://ssfshop.com/x/{i}?NaPm=ct%3Dz%7Cch%3D{i}',
                            last_price=1000 + i, last_status='ok'))
    s.commit()
    s.close()
    return codes


def _norm(d):
    return json.loads(json.dumps(d, default=str, sort_keys=True))


def test_일괄로_읽어도_한_건씩_읽은_것과_똑같다(engine, seeded, monkeypatch):
    monkeypatch.setattr(AP, 'SessionLocal', sessionmaker(bind=engine))
    s = Session(engine)
    before = {c: _norm(AP._option_matrix_one(s, c, {})) for c in seeded}
    s.close()

    after = {c: _norm(v) for c, v in AP._option_matrix_data_many(seeded).items()}

    assert set(before) == set(after)
    for c in seeded:
        assert after[c] == before[c], f'{c} 의 매트릭스가 일괄 조회에서 달라졌다'


def test_한_건_함수도_같은_답을_준다(engine, seeded, monkeypatch):
    monkeypatch.setattr(AP, 'SessionLocal', sessionmaker(bind=engine))
    s = Session(engine)
    one = _norm(AP._option_matrix_one(s, seeded[0], {}))
    s.close()
    assert _norm(AP._option_matrix_data(seeded[0])) == one


def test_묶음을_끊어_담아도_답이_같다(engine, seeded, monkeypatch):
    """램 때문에 `_WINDOW` 개씩 끊어 담는데, 끊는 자리가 답을 바꾸면 안 된다.

    🔴 특히 혜택 캐시(`bd_cache`)는 묶음마다 비워진다 — 앞 묶음 SKU 가 빠진 캐시를
      누가 되쓰면 그 상품 최종매입가가 표면가로 뜬다(금전). 그걸 여기서 잡는다.
    """
    monkeypatch.setattr(AP, 'SessionLocal', sessionmaker(bind=engine))
    whole = {c: _norm(v) for c, v in AP._option_matrix_data_many(seeded).items()}
    monkeypatch.setattr(AP, '_WINDOW', 3)
    cut = {c: _norm(v) for c, v in AP._option_matrix_data_many(seeded).items()}
    assert cut == whole


def test_없는_코드는_예전처럼_404_모양(engine, seeded, monkeypatch):
    monkeypatch.setattr(AP, 'SessionLocal', sessionmaker(bind=engine))
    got = AP._option_matrix_data('없는코드')
    assert got == {'ok': False, 'error': '모음전을 찾을 수 없어요.', 'status': 404}
    many = AP._option_matrix_data_many(['없는코드', seeded[0]])
    assert many['없는코드']['ok'] is False and many[seeded[0]]['ok'] is True


def test_상품_종수가_늘어도_쿼리가_비례해_늘지_않는다(engine, seeded, monkeypatch):
    """🔴 회귀 감시 — 이게 깨지면 「모델마다 다시 조회」가 되살아난 것이다."""
    monkeypatch.setattr(AP, 'SessionLocal', sessionmaker(bind=engine))
    n = {'q': 0}

    @event.listens_for(engine, 'before_cursor_execute')
    def _count(conn, cur, stmt, params, ctx, many):   # noqa: ANN001
        n['q'] += 1

    try:
        n['q'] = 0
        AP._option_matrix_data_many(seeded[:2])
        two = n['q']
        n['q'] = 0
        AP._option_matrix_data_many(seeded)
        eight = n['q']
    finally:
        event.remove(engine, 'before_cursor_execute', _count)

    # 상품이 4배(2→8)인데 쿼리는 2배 미만이어야 한다(비례 증가면 4배가 된다).
    assert eight < two * 2, f'쿼리가 상품 수에 비례해 늘었다 (2종 {two} → 8종 {eight})'
    # 상품 하나 늘 때마다 3쿼리를 넘으면 어딘가 모델별 조회가 남은 것이다.
    assert (eight - two) / 6 < 3, f'상품 1종당 {(eight - two) / 6:.1f}쿼리'


def test_소싱상품_표_전체_정규화는_요청당_한_벌이다(engine, seeded, monkeypatch):
    """🔴 회귀 감시 — 예전엔 같은 표를 매트릭스와 혜택 캐시가 **각자** 훑었고,
    그 훑기가 **모델코드마다** 다시 돌았다(합성 2만 행 = 4만 회·2.3초).

    상품별 URL 정규화(셀·매핑)는 그 상품 몫이라 당연히 늘지만, 「표 전체 훑기」는
    한 요청에 한 번이어야 한다. 상품을 6종 더 넣어도 늘어난 정규화가 **표 한 벌보다
    적으면** 표를 다시 훑지 않은 것이다.
    """
    monkeypatch.setattr(AP, 'SessionLocal', sessionmaker(bind=engine))
    import lemouton.sources.service as SVC
    real = SVC.normalize_url
    calls = {'n': 0}

    def counted(u):
        calls['n'] += 1
        return real(u)

    monkeypatch.setattr(SVC, 'normalize_url', counted)
    monkeypatch.setattr(AP, '_norm_url', counted, raising=False)

    calls['n'] = 0
    AP._option_matrix_data_many(seeded[:2])
    two = calls['n']
    calls['n'] = 0
    AP._option_matrix_data_many(seeded)
    eight = calls['n']
    assert eight - two < N_LOOSE_SP, (
        f'상품 6종 늘리는 데 정규화가 {eight - two}회 늘었다 — 소싱상품 표'
        f'({N_LOOSE_SP}행)를 다시 훑고 있다 (2종 {two} → 8종 {eight})')

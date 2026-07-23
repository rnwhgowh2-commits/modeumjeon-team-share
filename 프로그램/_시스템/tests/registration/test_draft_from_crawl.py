# -*- coding: utf-8 -*-
"""크롤한 소싱처 상품 → 등록 초안 변환기 (lemouton/registration/draft_from_crawl.py).

여기서 고정하는 것 중 **절대 깨지면 안 되는 것**:
  1. 매입가(last_price·current_price)가 판매가·옵션추가금으로 새어나가지 않는다.
  2. 재고 3상태(0=품절 / -1=확인불가 / None=미크롤)가 뭉개지지 않는다.
  3. 같은 소싱처 URL 로 초안이 여러 벌 생기지 않는다.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration import draft_from_crawl as DFC
from lemouton.registration.models import ProductDraft
from lemouton.sources.models import SourceOption, SourceProduct


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _crawled(session, *, url='https://www.musinsa.com/products/1234',
             site='musinsa', options=(), **over):
    body = dict(site=site, url=url, product_name='테스트 스니커즈',
                last_price=89000, last_stock=7,
                category_path='신발>스니커즈>여성운동화',
                images_json=json.dumps(['https://img/1.jpg', 'https://img/2.jpg']),
                detail_html='<p>상세</p>')
    body.update(over)
    sp = SourceProduct(**body)
    session.add(sp)
    session.flush()
    for o in options:
        session.add(SourceOption(source_product_id=sp.id, **o))
    session.flush()
    return sp


# ── 조회 (정규화 URL) ───────────────────────────────────────────────────────

def test_원문_URL_을_붙여넣어도_정규화해서_찾는다(session):
    """저장은 정규화형인데 사장님은 광고 추적 파라미터가 붙은 원문을 붙여넣는다.
    이걸 놓쳐 조인이 통째로 빗나간 이력이 있다."""
    sp = _crawled(session, url='https://www.musinsa.com/products/1234')
    found = DFC.find_source_product(
        session, 'https://www.musinsa.com/products/1234?utm_source=naver&NaPm=zz')
    assert found.id == sp.id


def test_크롤이_없으면_SourceNotCrawled(session):
    with pytest.raises(DFC.SourceNotCrawled) as e:
        DFC.find_source_product(session, 'https://www.musinsa.com/products/9999')
    assert '먼저 크롤이 돌아야' in str(e.value)


def test_같은_URL_이_소싱처_여러곳이면_고르게_한다(session):
    url = 'https://shop.example.com/p/1'
    _crawled(session, url=url, site='musinsa')
    _crawled(session, url=url, site='ssf')
    with pytest.raises(DFC.AmbiguousSourceUrl):
        DFC.find_source_product(session, url)
    assert DFC.find_source_product(session, url, site='ssf').site == 'ssf'


# ── 변환 ────────────────────────────────────────────────────────────────────

def test_크롤_값이_초안으로_옮겨진다(session):
    sp = _crawled(session, options=[
        {'color_text': '블랙', 'size_text': '230', 'current_stock': 3, 'current_price': 89000},
        {'color_text': '화이트', 'size_text': '240', 'current_stock': 0, 'current_price': 89000},
    ])
    d = DFC.build_draft_from_source(session, sp)
    session.commit()

    assert d.origin == 'bulk' and d.source == 'crawl'
    assert d.source_site == 'musinsa'
    assert d.source_url == sp.url
    assert d.source_category_path == '신발>스니커즈>여성운동화'
    assert d.name == '테스트 스니커즈'
    assert json.loads(d.images_json) == ['https://img/1.jpg', 'https://img/2.jpg']
    assert d.detail_html == '<p>상세</p>'
    assert d.stock_quantity == 7
    opts = json.loads(d.options_json)
    assert opts[0] == {'color': '블랙', 'size': '230', 'stock': 3,
                       'extra_price': 0, 'sku': ''}


# ★ 금전 손실 방지 — 이 두 개가 이 모듈의 존재 이유다.

def test_매입가를_판매가로_쓰지_않는다(session):
    sp = _crawled(session, last_price=89000)
    d = DFC.build_draft_from_source(session, sp)
    assert d.sale_price == DFC.SALE_PRICE_UNSET == 0
    assert d.sale_price != sp.last_price


def test_옵션_매입가를_추가금으로_옮기지_않는다(session):
    """옵션 추가금은 판매 정책이다. 매입가 차이를 그대로 넣으면 정하지도 않은 정책이 생긴다."""
    sp = _crawled(session, options=[
        {'color_text': '블랙', 'size_text': '230', 'current_stock': 3, 'current_price': 89000},
        {'color_text': '블랙', 'size_text': '250', 'current_stock': 2, 'current_price': 119000},
    ])
    d = DFC.build_draft_from_source(session, sp)
    assert [o['extra_price'] for o in json.loads(d.options_json)] == [0, 0]
    # 대신 경고로 띄운다 — 그대로 두면 비싼 옵션이 싼 값에 팔린다.
    rep = DFC.fill_report(sp, d, DFC._load_options(session, sp))
    assert any('옵션별 매입가가 다릅니다' in w for w in rep['warnings'])


def test_판매가_0_은_6마켓_컴파일이_전부_막는다(session):
    """0 을 넣는 게 '조용한 통과'가 아니라는 근거 — 실제 컴파일러가 거부한다."""
    from lemouton.registration.compile_common import CompileError
    from lemouton.registration.compile_smartstore import compile_smartstore
    from lemouton.registration.compile_more import compile_eleven11

    sp = _crawled(session, options=[
        {'color_text': '블랙', 'size_text': '230', 'current_stock': 3}])
    d = DFC.build_draft_from_source(session, sp)
    for fn in (lambda: compile_smartstore(d, category_code='1', require_cdn_images=False),
               lambda: compile_eleven11(d, category_code='1')):
        with pytest.raises(CompileError) as e:
            fn()
        assert '판매가가 0 이하' in str(e.value)


def test_재고_3상태가_뭉개지지_않는다(session):
    """0(품절) · -1(확인불가) · None(미크롤) 은 서로 다른 뜻이다 — `or 0` 금지."""
    sp = _crawled(session, options=[
        {'color_text': 'A', 'size_text': 'M', 'current_stock': 0},
        {'color_text': 'B', 'size_text': 'M', 'current_stock': -1},
        {'color_text': 'C', 'size_text': 'M', 'current_stock': None},
    ])
    d = DFC.build_draft_from_source(session, sp)
    assert [o['stock'] for o in json.loads(d.options_json)] == [0, -1, None]


def test_소싱처_옵션ID_를_품번으로_쓰지_않는다(session):
    sp = _crawled(session, options=[
        {'color_text': '블랙', 'size_text': '230', 'current_stock': 3,
         'external_option_id': 'MU-OPT-99'}])
    d = DFC.build_draft_from_source(session, sp)
    assert json.loads(d.options_json)[0]['sku'] == ''


def test_깨진_images_json_은_빈_목록(session):
    sp = _crawled(session, images_json='{나 JSON 아님')
    d = DFC.build_draft_from_source(session, sp)
    assert json.loads(d.images_json) == []


# ── 중복 방지 ───────────────────────────────────────────────────────────────

def test_같은_URL_은_새로_만들지_않고_갱신한다(session):
    sp = _crawled(session, options=[
        {'color_text': '블랙', 'size_text': '230', 'current_stock': 3}])
    first = DFC.build_draft_from_source(session, sp)
    session.commit()

    # 재크롤로 재고가 바뀐 상황
    session.query(SourceOption).update({'current_stock': 11})
    sp.last_stock = 11
    session.flush()

    again = DFC.build_draft_from_source(session, sp)
    session.commit()
    assert again.id == first.id
    assert session.query(ProductDraft).count() == 1
    assert json.loads(again.options_json)[0]['stock'] == 11


def test_갱신은_사람이_채운_칸을_건드리지_않는다(session):
    sp = _crawled(session)
    d = DFC.build_draft_from_source(session, sp)
    session.commit()
    d.sale_price = 159000
    d.name = '내가 다듬은 상품명'
    d.after_service_phone = '010-1111-2222'
    d.notice_json = '{"material": "가죽"}'
    d.delivery_fee = 0
    session.commit()

    sp.product_name = '소싱처가 바꾼 이름'
    again = DFC.build_draft_from_source(session, sp)
    session.commit()
    assert again.sale_price == 159000
    assert again.name == '내가 다듬은 상품명'
    assert again.after_service_phone == '010-1111-2222'
    assert json.loads(again.notice_json) == {'material': '가죽'}
    assert again.delivery_fee == 0


def test_이미_등록된_초안은_덮지_않는다(session):
    sp = _crawled(session)
    d = DFC.build_draft_from_source(session, sp)
    session.commit()
    d.status = 'done'
    session.commit()

    with pytest.raises(DFC.DraftLocked) as e:
        DFC.build_draft_from_source(session, sp)
    assert e.value.draft.id == d.id


def test_지운_초안은_되살리지_않고_새로_만든다(session):
    from datetime import datetime, timezone
    sp = _crawled(session)
    old = DFC.build_draft_from_source(session, sp)
    session.commit()
    old.deleted_at = datetime.now(timezone.utc)
    session.commit()

    fresh = DFC.build_draft_from_source(session, sp)
    session.commit()
    assert fresh.id != old.id
    assert session.query(ProductDraft).filter(
        ProductDraft.deleted_at.is_(None)).count() == 1


# ── 보고 ────────────────────────────────────────────────────────────────────

def test_사람이_채워야_하는_칸을_그대로_말한다(session):
    sp = _crawled(session, images_json=None, detail_html='', category_path='')
    d = DFC.build_draft_from_source(session, sp)
    rep = DFC.fill_report(sp, d, [])
    joined = ' / '.join(rep['warnings'])
    assert '이미지가 없습니다' in joined
    assert '상세설명' in joined
    assert '판매가가 아직 없습니다' in joined
    assert any('판매가' in n for n in rep['human_only'])

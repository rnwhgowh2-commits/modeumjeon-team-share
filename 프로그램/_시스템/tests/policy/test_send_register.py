# -*- coding: utf-8 -*-
"""신규 등록 — 구성을 초안으로 비춰 **있는 등록 경로**를 그대로 쓴다.

🔴 이 파일이 지키는 것 — **없는 값을 지어내지 않는다.**
   구성에는 아직 이미지·고시·A/S 칸이 없다. 채워 보내면 가짜 전화번호와 빈 고시가
   마켓에 그대로 게시된다. 비워 두고 「무엇이 없는지」를 말하는 게 옳은 답이다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.send import models as _sm      # noqa: F401 — 표 등록(create_all 전에)
from lemouton.send import as_draft as AD


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


def _seed(s, set_name='단품'):
    from lemouton.sets.models import ProductSet, SetOption, SetProduct
    from lemouton.sourcing.models import Model, Option
    s.add(Model(model_code='M1', model_name_raw='탑텐 탱크',
                model_name_display='탑텐 탱크', brand='르무통', category='상의>티셔츠'))
    s.flush()
    s.add(Option(canonical_sku='M1-검정-M', model_code='M1', color_code='검정',
                 color_display='검정', size_code='M', size_display='M', is_active=True))
    s.flush()
    ps = ProductSet(model_code='M1', name=set_name)
    s.add(ps); s.flush()
    sp = SetProduct(set_id=ps.id, model_code='M1', quantity=1)
    s.add(sp); s.flush()
    s.add(SetOption(set_product_id=sp.id, canonical_sku='M1-검정-M'))
    s.flush()
    return ps


def _draft(s, ps, market='coupang', price=12000):
    """판매가는 정책·원가가 있어야 나온다 — 여기선 그 계산만 대신한다."""
    import lemouton.send.as_draft as _AD
    orig = _AD._price_for
    _AD._price_for = lambda session, *, set_id, market: price
    try:
        return AD.upsert(s, set_id=ps.id, market=market)
    finally:
        _AD._price_for = orig


def test_구성을_초안으로_비춘다(s):
    ps = _seed(s, '2벌 묶음')
    d = _draft(s, ps)
    assert d.model_code == 'M1'
    assert d.name == '2벌 묶음'          # 구성 이름이 곧 마켓에 올라가는 이름
    assert d.brand == '르무통'
    assert d.origin == AD.ORIGIN         # 크롤 초안과 섞이지 않는다


def test_초안을_다시_쓰지_않고_갈아끼운다(s):
    """누를 때마다 새로 만들면 초안 표가 쓰레기로 찬다."""
    from lemouton.registration.models import ProductDraft
    ps = _seed(s)
    a = _draft(s, ps)
    b = _draft(s, ps)
    assert a.id == b.id
    assert s.query(ProductDraft).filter(ProductDraft.origin == AD.ORIGIN).count() == 1


def test_없는_칸을_지어내지_않는다(s):
    """🔴 가짜 전화번호·빈 고시가 마켓에 게시되면 안 된다."""
    ps = _seed(s)
    d = _draft(s, ps)
    assert not (d.after_service_phone or '')
    # 🔴 기본값이 '{}' 이라 「있다」로 읽히면 안 된다 — 빈 것으로 봐야 한다.
    assert AD._empty(d.notice_json)
    assert AD._empty(d.cdn_images_json)


def test_무엇이_없는지_사람_말로_알려준다(s):
    ps = _seed(s)
    d = _draft(s, ps)
    got = AD.missing_fields(d)
    for 있어야 in ('상품 이미지', '고시정보', 'A/S 전화번호'):
        assert any(있어야 in x for x in got), (
            f'{있어야} 를 안 알려준다 · 알려준 것={got} · '
            f'cdn={d.cdn_images_json!r} img={d.images_json!r} '
            f'notice={d.notice_json!r} as={d.after_service_phone!r}')


def test_정책_없으면_초안을_아예_안_만든다(s):
    """🔴 폴백 금지 — `sale_price` 는 비울 수 없는 칸이라 0 을 넣게 되는데,
    0 은 지어낸 가격이다. 반쯤 만든 초안을 남기느니 사유를 말한다."""
    from lemouton.registration.models import ProductDraft
    ps = _seed(s)
    with pytest.raises(AD.DraftIncomplete) as e:
        AD.upsert(s, set_id=ps.id, market='coupang')
    assert '0원으로 지어내지 않습니다' in str(e.value)
    assert s.query(ProductDraft).count() == 0, '반쯤 만든 초안이 남았다'


def test_마켓마다_따로_비춘다(s):
    """정책이 마켓별로 이름을 다르게 만들 수 있으니 마켓을 받아야 한다."""
    import inspect
    assert 'market' in inspect.signature(AD.upsert).parameters


def test_없는_구성은_막는다(s):
    with pytest.raises(ValueError):
        AD.upsert(s, set_id=999999, market='coupang')


def test_등록되면_구성에_마켓_상품번호를_붙인다(s):
    """🔴 안 붙이면 다음번에 **또 등록해** 마켓에 중복 상품이 생긴다."""
    from lemouton.send.runner import _link_channel, _split_by_listed
    ps = _seed(s)
    assert _split_by_listed(s, set_id=ps.id, markets=['coupang']) == ([], ['coupang'])
    _link_channel(s, set_id=ps.id, market='coupang', account_key='default',
                  market_product_id='CP123')
    s.flush()
    assert _split_by_listed(s, set_id=ps.id, markets=['coupang']) == (['coupang'], [])


# ── A/S 기본값 · 이미지 (사장님 확정 A안) ────────────────────────────────

def _as_defaults(s, phone='02-1234-5678', guide='교환·반품은 7일 이내'):
    from lemouton.pricing.settings import get_or_init
    g = get_or_init(s)
    g.after_service_phone = phone
    g.after_service_guide = guide
    s.flush()
    return g


def test_A_S는_전역_설정에서_가져온다(s):
    """회사에 하나뿐인 값 — 상품마다 넣게 하면 매번 같은 값을 다시 친다."""
    ps = _seed(s)
    _as_defaults(s)
    d = _draft(s, ps)
    assert d.after_service_phone == '02-1234-5678'
    assert '7일' in d.after_service_guide


def test_A_S가_비면_지어내지_않는다(s):
    """🔴 예전 코드는 `or "02-0000-0000"` 로 때웠다 — 가짜 번호가 실제 상품에 게시된다."""
    ps = _seed(s)
    _as_defaults(s, phone='', guide='')
    d = _draft(s, ps)
    assert not (d.after_service_phone or '')
    assert 'A/S 전화번호' in ' '.join(AD.missing_fields(d))


def test_옵션_사진을_전부_싣는다(s):
    """확정 A안 — 한 장만 실으면 흰색을 산 손님이 검정 사진을 본다."""
    import json as _j
    from lemouton.sets.models import SetOption, SetProduct
    from lemouton.sourcing.models import Option
    ps = _seed(s)
    sp = s.query(SetProduct).filter_by(set_id=ps.id).first()
    o1 = s.get(Option, 'M1-검정-M')
    o1.image_url = 'https://img/black.jpg'
    o2 = Option(canonical_sku='M1-흰색-M', model_code='M1', color_code='흰색',
                color_display='흰색', size_code='M', size_display='M', is_active=True,
                image_url='https://img/white.jpg')
    s.add(o2); s.flush()
    s.add(SetOption(set_product_id=sp.id, canonical_sku='M1-흰색-M', sort_order=1))
    s.flush()
    d = _draft(s, ps)
    got = _j.loads(d.images_json)
    assert got == ['https://img/black.jpg', 'https://img/white.jpg']


def test_같은_사진은_한_번만_싣는다(s):
    """같은 색의 여러 사이즈가 같은 사진을 가리키는 일이 흔하다."""
    import json as _j
    from lemouton.sets.models import SetOption, SetProduct
    from lemouton.sourcing.models import Option
    ps = _seed(s)
    sp = s.query(SetProduct).filter_by(set_id=ps.id).first()
    s.get(Option, 'M1-검정-M').image_url = 'https://img/black.jpg'
    o2 = Option(canonical_sku='M1-검정-L', model_code='M1', color_code='검정',
                color_display='검정', size_code='L', size_display='L', is_active=True,
                image_url='https://img/black.jpg')          # 같은 사진
    s.add(o2); s.flush()
    s.add(SetOption(set_product_id=sp.id, canonical_sku='M1-검정-L', sort_order=1))
    s.flush()
    assert _j.loads(_draft(s, ps).images_json) == ['https://img/black.jpg']


def test_사진이_없으면_없다고_말한다(s):
    """크롤이 사진을 못 받았을 수 있다 — 빈 채로 두고 알린다."""
    ps = _seed(s)
    d = _draft(s, ps)
    assert AD._loads_ok(d.images_json) == []
    assert '상품 이미지' in ' '.join(AD.missing_fields(d))


def test_고시정보는_여기서_안_채운다(s):
    """전역·소싱처별 기본값을 컴파일 직전에 병합한다 — 미리 쓰면 누가 넣은 값인지 뭉개진다."""
    ps = _seed(s)
    d = _draft(s, ps)
    assert AD._empty(d.notice_json)

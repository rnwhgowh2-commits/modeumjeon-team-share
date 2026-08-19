# -*- coding: utf-8 -*-
"""배선 — 정책 13항목이 구성(벌)에 실제로 적용되는가.

PR#678 이 진단한 「저장만 되고 아무 데도 안 가는 11항목」을 잇는 자리다.
이 파일이 지키는 것 셋:
  ① 가공 엔진을 **다시 만들지 않았다** (대량등록과 같은 결과가 나온다)
  ② 한 벌은 **한 정책만** 따른다 (상품명과 판매가가 뒤섞이지 않는다)
  ③ 정책이 없으면 **막는다** (정해진 적 없는 값이 마켓으로 나가지 않는다)
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import to_payload as TP


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


def _model(s, code='M1', name='기본 티셔츠', brand='르무통'):
    from lemouton.sourcing.models import Model
    m = Model(model_code=code, model_name_raw=name, model_name_display=name,
              brand=brand, category='상의>티셔츠')
    s.add(m)
    s.flush()
    return m


def _option(s, code, sku, color, size, stock):
    from lemouton.sourcing.models import Option
    o = Option(canonical_sku=sku, model_code=code,
               color_code=color, color_display=color,
               size_code=size, size_display=size,
               boxhero_stock_total=stock, is_active=True)
    s.add(o)
    s.flush()
    return o


def _set(s, code='M1', name='단품', skus=()):
    from lemouton.sets.models import ProductSet, SetOption, SetProduct
    ps = ProductSet(model_code=code, name=name)
    s.add(ps)
    s.flush()
    sp = SetProduct(set_id=ps.id, model_code=code, quantity=1)
    s.add(sp)
    s.flush()
    for i, sku in enumerate(skus):
        s.add(SetOption(set_product_id=sp.id, canonical_sku=sku, sort_order=i))
    s.flush()
    return ps


def _policy(s, name='정책A'):
    from lemouton.policy.service import create_policy
    p = create_policy(s, name=name)
    s.flush()
    return p


def _save(s, policy, market, item, cfg):
    from lemouton.policy.service import save_item
    save_item(s, policy=policy, market=market, item_key=item, config=cfg)
    s.flush()


# ── ① 정책 하나로 정해지는가 (되받기 사슬) ──────────────────────────────

def test_구성_정책이_상품_정책을_이긴다(s):
    from lemouton.policy.models import BundlePolicyLink, SetPolicyLink
    _model(s)
    ps = _set(s)
    a, b = _policy(s, '상품쪽'), _policy(s, '구성쪽')
    s.add(BundlePolicyLink(model_code='M1', policy_id=a.id))
    s.add(SetPolicyLink(set_id=ps.id, policy_id=b.id))
    s.flush()
    got, origin = TP.resolve_policy(s, set_id=ps.id)
    assert got.name == '구성쪽' and origin == 'set'


def test_구성에_없으면_상품_정책으로_되받는다(s):
    from lemouton.policy.models import BundlePolicyLink
    _model(s)
    ps = _set(s)
    a = _policy(s, '상품쪽')
    s.add(BundlePolicyLink(model_code='M1', policy_id=a.id))
    s.flush()
    got, origin = TP.resolve_policy(s, set_id=ps.id)
    assert got.name == '상품쪽' and origin == 'model'


def test_지운_정책은_안_따른다(s):
    from datetime import datetime
    from lemouton.policy.models import SetPolicyLink
    _model(s)
    ps = _set(s)
    p = _policy(s)
    p.deleted_at = datetime(2026, 8, 1)
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    assert TP.resolve_policy(s, set_id=ps.id) == (None, None)


def test_판매가를_안_정해도_구성_정책을_그대로_쓴다(s):
    """🔴 as_template 과 **일부러 다른** 자리.

    거기서는 「구성 정책이 판매가를 안 정했으면 상품 정책으로」 한 단계 더 되받는다.
    여기서 그렇게 하면 상품명은 구성 정책, 판매가는 상품 정책을 따르는
    **뒤섞인 상품**이 나간다. 한 벌은 한 정책만 따라야 한다.
    """
    from lemouton.policy.models import BundlePolicyLink, SetPolicyLink
    _model(s)
    ps = _set(s)
    상품 = _policy(s, '상품쪽')
    구성 = _policy(s, '구성쪽')             # 판매가는 하나도 안 정함
    _save(s, 상품, 'coupang', 'price', {'sourcing_mode': 'margin_rate',
                                        'sourcing_rate': 30})
    s.add(BundlePolicyLink(model_code='M1', policy_id=상품.id))
    s.add(SetPolicyLink(set_id=ps.id, policy_id=구성.id))
    s.flush()

    got, origin = TP.resolve_policy(s, set_id=ps.id)
    assert (got.name, origin) == ('구성쪽', 'set')
    # 가격 껍데기도 **같은 정책**에서 나온다 — 상품쪽 30% 가 새어 들어오면 안 된다.
    assert TP.price_template_for(s, set_id=ps.id) is None


def test_모르는_마켓은_막는다(s):
    _model(s)
    ps = _set(s)
    with pytest.raises(TP.PayloadError):
        TP.rules_for(s, set_id=ps.id, market='11st')


# ── ② 구성을 엔진이 읽을 모양으로 ───────────────────────────────────────

def test_구성_이름이_상품_이름보다_먼저다(s):
    """구성이 곧 마켓에 올라가는 한 상품이다 — 「긴팔 2벌 묶음」처럼 다를 수 있다."""
    _model(s, name='기본 티셔츠')
    ps = _set(s, name='긴팔 2벌 묶음')
    v = TP.set_view(s, set_id=ps.id)
    assert v.name == '긴팔 2벌 묶음'
    assert v.brand == '르무통'


def test_구성_이름이_비면_상품_이름을_쓴다(s):
    _model(s, name='기본 티셔츠')
    ps = _set(s, name='   ')
    assert TP.set_view(s, set_id=ps.id).name == '기본 티셔츠'


def test_옵션은_구성이_정한_순서로_실린다(s):
    _model(s)
    _option(s, 'M1', 'SKU-B', '검정', 'L', 5)
    _option(s, 'M1', 'SKU-A', '흰색', 'M', 3)
    ps = _set(s, skus=('SKU-B', 'SKU-A'))
    got = json.loads(TP.set_view(s, set_id=ps.id).options_json)
    assert [o['sku'] for o in got] == ['SKU-B', 'SKU-A']
    assert got[0]['color'] == '검정' and got[0]['size'] == 'L'


def test_재고를_지어내지_않는다(s):
    """🔴 재고 칸을 **아예 안 싣는다**.

    `Option.boxhero_stock_total` 은 사입(우리 창고) 재고이고 `default=0` 이라
    「모름」이 저장되는 순간 0(품절)으로 둔갑한다. 그걸 실으면 멀쩡한 상품이
    품절로 올라간다(반대 방향이면 오버셀). 소싱처 재고 판정은 정본 판정기
    `_resolve_stock` 이 해야 한다 — 붙이기 전까지는 아무 수도 안 적는다.
    """
    _model(s)
    _option(s, 'M1', 'SKU-X', '검정', 'M', None)
    ps = _set(s, skus=('SKU-X',))
    got = json.loads(TP.set_view(s, set_id=ps.id).options_json)
    assert 'stock' not in got[0], f'재고를 지어냈다: {got[0]}'
    assert got[0]['color'] == '검정'          # 옵션 축은 멀쩡히 실린다


def test_재고가_안_붙었으면_전송을_막는다(s):
    """지어낸 재고가 나가느니 안 보내는 게 낫다 — 4단계에서 판정기를 붙이며 뗀다."""
    from lemouton.policy.models import SetPolicyLink
    _model(s)
    ps = _set(s)
    p = _policy(s)
    _save(s, p, 'coupang', 'name', {'token_order': ['origin_name']})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    codes = [x['code'] for x in got['skipped']]
    assert TP.STOCK_NOT_WIRED in codes
    assert got['blocking'], '재고 없이 보낼 수 있게 열려 있다'


def test_사본은_읽기_전용이다(s):
    _model(s)
    ps = _set(s)
    v = TP.set_view(s, set_id=ps.id)
    with pytest.raises(AttributeError):
        v.name = '몰래 바꾸기'


def test_없는_구성은_막는다(s):
    with pytest.raises(TP.PayloadError):
        TP.set_view(s, set_id=999999)


# ── ③ 붙이기 ────────────────────────────────────────────────────────────

def test_정책이_없으면_막는다(s):
    """대량등록은 「크롤 값이 그대로 갑니다」라며 통과시킨다(초안이라 맞다).
    여기는 마켓으로 실제 나가는 자리라, 정해진 적 없는 값이 나가면 사고다."""
    _model(s)
    ps = _set(s)
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['policy'] is None
    assert got['blocking'], '정책 없이 통과했다'
    assert '「정책 매칭」' in got['blocking'][0]


def test_그_마켓에_저장된_항목이_없으면_막는다(s):
    from lemouton.policy.models import SetPolicyLink
    _model(s)
    ps = _set(s)
    p = _policy(s)
    _save(s, p, 'coupang', 'name', {'token_order': ['origin_name']})  # 쿠팡에만
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = TP.build_for_set(s, set_id=ps.id, market='gmarket')  # G마켓은 빔
    assert got['blocking']
    assert '정책 생성' in got['blocking'][0]


def test_상품명_규칙이_실제로_먹는다(s):
    """배선의 본체 — 정책에 적은 접두어가 진짜로 이름 앞에 붙는가."""
    from lemouton.policy.models import SetPolicyLink
    _model(s, name='기본 티셔츠')
    ps = _set(s, name='기본 티셔츠')
    p = _policy(s)
    _save(s, p, 'coupang', 'name',
          {'token_order': ['brand', 'origin_name'], 'separator': ' ',
           'brand_case': 'upper'})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    # 재고 게이트(4단계에서 뗀다) 말고 다른 이유로 막히면 안 된다.
    assert [x['code'] for x in got['skipped'] if x['blocking']] == [TP.STOCK_NOT_WIRED]
    assert got['view'].name.startswith('르무통'), got['view'].name
    assert got['applied'], '무엇이 바뀌었는지 안 알려준다'


def test_마켓마다_다른_규칙이_적용된다(s):
    """정책 화면이 마켓별로 따로 정하게 해 놨으니, 결과도 마켓별로 달라야 한다."""
    from lemouton.policy.models import SetPolicyLink
    _model(s, name='기본 티셔츠')
    ps = _set(s, name='기본 티셔츠')
    p = _policy(s)
    # 쿠팡만 「재킷 → 자켓」으로 바꾼다. G마켓은 원본 그대로.
    _save(s, p, 'coupang', 'name',
          {'token_order': ['origin_name'], 'replacements': [['티셔츠', '반팔티']]})
    _save(s, p, 'gmarket', 'name', {'token_order': ['origin_name']})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    cp = TP.build_for_set(s, set_id=ps.id, market='coupang')['view'].name
    gm = TP.build_for_set(s, set_id=ps.id, market='gmarket')['view'].name
    assert '반팔티' in cp, cp
    assert '티셔츠' in gm, gm
    assert cp != gm, '마켓별로 갈리지 않았다'


def test_업로드_금지어가_막는다(s):
    """보내면 안 되는 말이 든 상품은 그 마켓에서 빠져야 한다."""
    from lemouton.policy.models import SetPolicyLink
    _model(s, name='짝퉁 스니커즈')
    ps = _set(s, name='짝퉁 스니커즈')
    p = _policy(s)
    _save(s, p, 'coupang', 'name', {'token_order': ['origin_name']})
    _save(s, p, 'coupang', 'banned_words', {'upload_banned': ['짝퉁']})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['blocking'], '금지어가 든 채로 통과했다'


def test_같은_사본을_두_번_가공하지_않는다(s):
    """엔진이 막는 실수 — 두 번 넣으면 브랜드가 두 번 붙는다."""
    from lemouton.registration.process_apply import apply_rules
    from lemouton.policy.models import SetPolicyLink
    _model(s)
    ps = _set(s)
    p = _policy(s)
    _save(s, p, 'coupang', 'name', {'token_order': ['brand', 'origin_name']})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    once = TP.build_for_set(s, set_id=ps.id, market='coupang')['view']
    with pytest.raises(TypeError):
        apply_rules(once, {'name': {'token_order': ['brand', 'origin_name']}},
                    market='coupang', collect_banned_words=[])


# ── 재고 배선 (6단계) ────────────────────────────────────────────────────
#
# 🔴 재고는 **화면(매트릭스)이 쓰는 그 값**을 그대로 가져온다 —
#   `_option_matrix_data` 를 부른다(업로드 드라이런이 이미 같은 방식이다).
#   아래 검사는 그 결과가 payload 로 흘러 들어가는지, 그리고 못 읽으면
#   **막히는지**를 본다.

def _with_stock(monkeypatch, mapping):
    """`_stock_by_sku` 가 매트릭스에서 읽어 온 척한다."""
    monkeypatch.setattr(TP, '_stock_by_sku', lambda session, model_code: mapping)


def _ready(s):
    """정책 붙고 규칙 있는 구성 하나."""
    from lemouton.policy.models import SetPolicyLink
    _model(s)
    _option(s, 'M1', 'SKU-A', '검정', 'M', 5)
    ps = _set(s, skus=('SKU-A',))
    p = _policy(s)
    _save(s, p, 'coupang', 'name', {'token_order': ['origin_name']})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    return ps


def test_읽은_재고가_그대로_실린다(s, monkeypatch):
    ps = _ready(s)
    _with_stock(monkeypatch, {'SKU-A': [
        {'site': 'musinsa', 'crawled_price': 9000, 'crawled_stock': 3,
         'last_status': 'ok'}]})
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['blocking'] == [], got['blocking']
    opt = json.loads(got['view'].options_json)[0]
    assert opt['stock'] == 3
    assert opt['buy_source'] == 'musinsa'      # 어디서 사오는지도 실린다


def test_품절0도_읽은_값이라_보낸다(s, monkeypatch):
    """0 은 확인된 값이다 — 안 보내면 마켓에 옛 재고가 남는다."""
    ps = _ready(s)
    _with_stock(monkeypatch, {'SKU-A': [
        {'site': 'ssg', 'crawled_price': 9000, 'crawled_stock': 0, 'last_status': 'ok'}]})
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['blocking'] == []
    assert json.loads(got['view'].options_json)[0]['stock'] == 0


def test_확인불가면_막고_어느_옵션인지_말한다(s, monkeypatch):
    """🔴 있다고 단정하면 오버셀이다. 게다가 어느 옵션인지 말해야 손을 쓴다."""
    ps = _ready(s)
    _with_stock(monkeypatch, {'SKU-A': [
        {'site': 'musinsa', 'crawled_price': 9000, 'crawled_stock': -1,
         'last_status': 'ok'}]})
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['blocking'], '확인 불가인데 통과했다'
    assert '검정 M' in got['blocking'][0]
    assert TP.STOCK_UNREADABLE in [x['code'] for x in got['skipped']]


def test_매트릭스를_못_읽으면_막는다(s, monkeypatch):
    """조용히 0 으로 보내지 않는다 — 그게 품절 둔갑이다."""
    ps = _ready(s)
    _with_stock(monkeypatch, {})
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['blocking']
    opt = json.loads(got['view'].options_json)[0]
    assert 'stock' not in opt, '재고를 지어냈다'


def test_한_옵션만_못_읽어도_막는다(s, monkeypatch):
    """일부만 보내면 안 보낸 옵션이 마켓에 옛 재고로 남는다."""
    from lemouton.policy.models import SetPolicyLink
    _model(s)
    _option(s, 'M1', 'SKU-A', '검정', 'M', 5)
    _option(s, 'M1', 'SKU-B', '흰색', 'L', 5)
    ps = _set(s, skus=('SKU-A', 'SKU-B'))
    p = _policy(s)
    _save(s, p, 'coupang', 'name', {'token_order': ['origin_name']})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    _with_stock(monkeypatch, {'SKU-A': [
        {'site': 'ssg', 'crawled_price': 9000, 'crawled_stock': 4, 'last_status': 'ok'}]})
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['blocking']
    assert '흰색 L' in got['blocking'][0]


def test_옵션이_없으면_막는다(s, monkeypatch):
    from lemouton.policy.models import SetPolicyLink
    _model(s)
    ps = _set(s)                     # 옵션 0개
    p = _policy(s)
    _save(s, p, 'coupang', 'name', {'token_order': ['origin_name']})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    _with_stock(monkeypatch, {})
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert got['blocking'] and '보낼 것이 없습니다' in got['blocking'][0]


# ── [2026-08-13] 🔴 이미지 규칙만 저장해도 전 마켓 전송이 막히던 것 ──────────
#   구성 사본(SetProcessView)에 `images_json` 칸이 아예 없었다. 그래서 가공 엔진이
#   「이미지가 한 장도 없습니다」로 판정하고 **막았다**(blocking=True).
#   실제로는 옵션에 사진이 있는데도 그랬다 — 사장님이 정책에 이미지 항목을
#   저장하는 순간 그 상품이 어느 마켓에도 못 나가는 상태였다.

def _option_with_image(s, code, sku, color, size, stock, image_url):
    from lemouton.sourcing.models import Option
    o = Option(canonical_sku=sku, model_code=code,
               color_code=color, color_display=color,
               size_code=size, size_display=size,
               boxhero_stock_total=stock, is_active=True,
               image_url=image_url)
    s.add(o)
    s.flush()
    return o


def test_이미지_규칙만_저장해도_전송이_막히면_안_된다(s):
    """🔴 사진이 있는데도 「한 장도 없다」며 막던 자리."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy(s)
    _save(s, p, 'coupang', 'price', {'sourcing_mode': 'margin_rate', 'sourcing_rate': 20})
    _save(s, p, 'coupang', 'images', {'mode': 'rep_only'})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()

    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    막힌사유 = [b for b in got['blocking'] if '이미지' in b]
    assert not 막힌사유, f'사진이 있는데 막혔다: {막힌사유}'


def test_구성_사본이_옵션_사진을_들고_있다(s):
    """가공 엔진이 읽을 수 있어야 규칙이 먹는다 — 칸이 없으면 규칙이 헛돈다."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    _option_with_image(s, 'M1', 'SKU2', '화이트', 'M', 3, 'https://img/2.jpg')
    ps = _set(s, skus=('SKU1', 'SKU2'))
    view = TP.set_view(s, set_id=ps.id)
    urls = json.loads(getattr(view, 'images_json', '[]') or '[]')
    assert urls, '구성 사본에 사진이 하나도 없다'
    assert 'https://img/1.jpg' in urls


def test_사진이_정말_없으면_그때는_막는다(s):
    """막는 것 자체는 옳다 — 사진 없이 올릴 수 있는 마켓은 없다."""
    _model(s)
    _option(s, 'M1', 'SKU1', '블랙', 'M', 5)      # image_url 없음
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy(s)
    _save(s, p, 'coupang', 'price', {'sourcing_mode': 'margin_rate', 'sourcing_rate': 20})
    _save(s, p, 'coupang', 'images', {'mode': 'rep_only'})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = TP.build_for_set(s, set_id=ps.id, market='coupang')
    assert any('이미지' in b for b in got['blocking']), '사진이 없는데 안 막았다'


# ── [2026-08-13 2단계] 정책이 만든 값이 **초안까지** 가는가 ──────────────────
#   가공 엔진은 이미 배송비·반품비·원산지를 사본에 얹는다. 그런데 초안으로 옮기는
#   줄이 없어 상품 칸 기본값(3,000 / 5,000 / 국내산)이 그대로 마켓에 나갔다.
#   🔴 배송비는 판매가 계산에도 쓰인다 — 정책 2,500인데 3,000으로 등록되면 금액이 갈린다.

def _policy_with(s, market, items):
    from lemouton.policy.models import SetPolicyLink
    p = _policy(s)
    for k, cfg in items.items():
        _save(s, p, market, k, cfg)
    return p


def test_사본은_정책_배송비를_들고_있다(s):
    """엔진은 이미 제 일을 한다 — 끊긴 건 그다음이다."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy_with(s, 'coupang', {
        'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 20},
        'shipping': {'fee_mode': 'paid', 'fee_amount': 2500, 'return_fee': 4000},
    })
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    view = TP.build_for_set(s, set_id=ps.id, market='coupang')['view']
    assert getattr(view, 'delivery_fee', None) == 2500
    assert getattr(view, 'return_fee', None) == 4000


def _draft_fields(s, ps, market='coupang'):
    """정책 → 사본 → **초안 칸**까지. 판매가와 무관하게 옮기는 규칙만 본다.

    🔴 `as_draft.upsert` 를 통째로 부르면 판매가가 없어 건너뛰기로 빠져나간다 —
      그러면 시험이 아무것도 안 본다(처음에 그렇게 짰다가 잡았다).
    """
    from lemouton.send import as_draft as AD
    view = TP.build_for_set(s, set_id=ps.id, market=market)['view']
    return AD.policy_fields_from(view)


def test_초안까지_정책_배송비가_간다(s):
    """🔴 여기가 끊겨 있었다 — 상품 칸 기본값 3,000원이 그대로 마켓에 나갔다."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy_with(s, 'coupang', {
        'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 20},
        'shipping': {'fee_mode': 'paid', 'fee_amount': 2500, 'return_fee': 4000},
    })
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = _draft_fields(s, ps)
    assert got.get('delivery_fee') == 2500, f'정책 2,500원인데 초안엔 {got.get("delivery_fee")}'
    assert got.get('return_fee') == 4000


def test_정책이_배송비를_안_정하면_기본값을_건드리지_않는다(s):
    """🔴 정책이 말 안 한 것을 0원(무료배송)으로 만들면 배송비를 우리가 떠안는다."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy_with(s, 'coupang', {
        'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 20},
    })                                    # 배송 규칙 없음
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = _draft_fields(s, ps)
    assert 'delivery_fee' not in got, '정책이 말 안 했는데 초안 배송비를 건드린다'
    assert 'return_fee' not in got


def test_무료배송은_0원으로_제대로_옮겨진다(s):
    """0 은 「값 없음」이 아니라 「무료배송」이다 — 빈 값으로 거르면 유료로 나간다."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy_with(s, 'coupang', {
        'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 20},
        'shipping': {'fee_mode': 'free'},
    })
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = _draft_fields(s, ps)
    assert got.get('delivery_fee') == 0, '무료배송이 0원으로 안 옮겨졌다'


def test_초안까지_정책_원산지가_간다(s):
    """🔴 해외 상품이 전부 「국내산」으로 등록되던 자리."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy_with(s, 'coupang', {
        'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 20},
        'origin': {'mode': 'fixed', 'fixed_value': '0200038'},
    })
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = _draft_fields(s, ps)
    assert got.get('origin_area_code') == '0200038',         f'정책은 0200038 인데 {got.get("origin_area_code")!r} — 국내산 기본값이 나간다'


def test_사본에_있는_화면용_값까지_옮기지는_않는다(s):
    """통째로 옮기면 초안에 엉뚱한 값이 박힌다 — 정한 칸만 옮긴다."""
    _model(s)
    _option_with_image(s, 'M1', 'SKU1', '블랙', 'M', 5, 'https://img/1.jpg')
    ps = _set(s, skus=('SKU1',))
    from lemouton.policy.models import SetPolicyLink
    p = _policy_with(s, 'coupang', {'price': {'sourcing_mode': 'margin_rate',
                                              'sourcing_rate': 20},
                                    'shipping': {'fee_mode': 'paid', 'fee_amount': 2500}})
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    got = _draft_fields(s, ps)
    assert 'source_category_path' not in got
    assert 'set_id' not in got and 'model_code' not in got

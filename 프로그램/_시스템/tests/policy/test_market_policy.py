# -*- coding: utf-8 -*-
"""마켓별 정책 — 항목값 저장 · 채움 현황 · 상품 적용.

🔴 이 파일이 지키는 두 가지:
  ① **저장 안 한 항목은 「안 정함」이다.** 화면이 기본값을 보여줘도 정해진 게 아니다.
  ② **기본 정책 13항목은 대량등록 가공 규칙과 같은 정의를 쓴다.** 베껴 두면 갈린다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM     # noqa: F401 — 테이블 등록
from lemouton.policy.fields import (
    MARKET_KEYS, all_item_keys, base_items, item_keys_for, items_for,
)
from lemouton.policy.models import BundlePolicyLink, MarketPolicyValue
from lemouton.policy.service import (
    PolicyError, applied_count, apply_to, create_policy, policy_of, readiness,
    save_item, save_values, toggle_default, values_for,
)
from lemouton.sourcing.models import Model


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _models(s, *codes):
    for c in codes:
        s.add(Model(model_code=c, model_name_raw=c, brand='르무통'))
    s.flush()


# ── 항목표가 대량등록과 같은 원천인가 ─────────────────────────────────────

def test_기본_항목은_대량등록_가공규칙_그대로다():
    """베껴 두면 대량등록에서 항목이 바뀔 때 여기가 뒤처진다.

    [2026-08-12] 사장님 엑셀 「마켓별 상품등록 정보」 대조로 3항목이 늘었다
    (등록 기본값·가격비교 노출·모델번호/바코드) → 13 → 16.
    🔴 개수를 박아 두는 이유는 「몇 개인가」가 아니라 **두 원천이 안 갈리는가**다.
    """
    from lemouton.registration.process_policy import ITEM_KEYS
    assert [it['key'] for it in base_items()] == list(ITEM_KEYS)
    assert len(ITEM_KEYS) == 16


def test_엑셀_대조로_추가한_3항목이_있다():
    """사장님 엑셀에는 있는데 우리에만 없던 칸들 — 다시 빠지면 안 된다."""
    keys = {it['key'] for it in base_items()}
    assert {'listing', 'price_compare', 'ids'} <= keys


def test_등록_기본값은_사장님이_정한_값으로_미리_채워진다():
    """사장님 지시 — 「거의 유사한 것들은 기본설정으로 해두면 될듯해」.

    🔴 판매기간 기본값이 「설정 안 함」이면 안 된다 — 쿠팡은 판매종료일시가 필수라
       그 값으로는 등록이 안 된다(문서가 2099년까지 길게 잡으라고 안내).
    """
    it = next(x for x in base_items() if x['key'] == 'listing')
    d = {f['key']: f['default'] for f in it['fields']}
    assert d['tax_type'] == '과세'
    # [2026-08-13 사장님 확정] 상품상태·판매기간은 고를 것이 아니라 정해진 값이라
    #   정책 항목에서 뺐다 → `policy/fixed_sends.py`(「정해져 나가는 값」)가 보여준다.
    assert 'product_condition' not in d
    assert 'sale_period' not in d
    assert d['minor_purchase'] == '전연령 구매 가능'
    assert d['manufacturer_mode'] == '브랜드와 동일'
    # 🔴 판매기간이 「설정 안 함」이면 쿠팡 등록이 안 된다 — 그 걱정은 이제 정책이 아니라
    #   `fixed_sends` 가 진다. 그래서 **그 표에 실제로 있는지**를 여기서 지킨다.
    from lemouton.policy import fixed_sends as FS
    labels = {r['label'] for r in FS.for_market('coupang')['rows']}
    assert '상품 판매기간' in labels, '판매기간이 화면 어디에서도 안 보인다'
    assert '상품상태' in labels, '상품상태가 화면 어디에서도 안 보인다'


def test_상품명_항목에_가공규칙_칸들이_그대로_있다():
    name = next(it for it in base_items() if it['key'] == 'name')
    keys = {f['key'] for f in name['fields']}
    assert {'token_order', 'brand_case', 'separator',
            'max_len', 'dedupe_words', 'replacements'} <= keys


def test_치환표는_두_칸짜리_표로_그려진다():
    name = next(it for it in base_items() if it['key'] == 'name')
    rep = next(f for f in name['fields'] if f['key'] == 'replacements')
    assert rep['type'] == 'list' and rep['item_shape'] == 'pair'


def test_마켓_전용_항목은_그_마켓에만_나온다():
    cp = set(item_keys_for('coupang'))
    ss = set(item_keys_for('smartstore'))
    gm = set(item_keys_for('gmarket'))
    assert '_winner' in cp and '_winner' not in ss            # 쿠팡 전용
    assert '_site_discount' in gm and '_site_discount' not in cp  # G마켓·롯데온
    assert '_max_per_person' in cp and '_max_per_person' not in gm
    # [2026-08-01] '_size_unify'(사이즈별 가격 통일)는 스스 전용 항목에서 빠지고
    #   **판매가 항목 안**으로 옮겼다(확정 K3). 어느 마켓에도 별도 항목으로 없다.
    assert '_size_unify' not in ss and '_size_unify' not in cp


def test_13항목은_모든_마켓에_공통이다():
    base = {it['key'] for it in base_items()}
    for mk in MARKET_KEYS:
        assert base <= set(item_keys_for(mk))


# ── 만들기 ────────────────────────────────────────────────────────────────

def test_이름이_없으면_막는다(db):
    with pytest.raises(PolicyError, match='이름'):
        create_policy(db, name='   ')


def test_같은_이름은_두_번_못_만든다(db):
    create_policy(db, name='르무통 기본')
    with pytest.raises(PolicyError, match='이미 있어요'):
        create_policy(db, name='르무통 기본')


# ── [2026-08-19] 정책명 자동 조합 ([대량]/[모음전] + 브랜드 + 카테고리 + 소싱처) ──

def test_이름_없이_브랜드만_있으면_모음전_기본값으로_조합한다(db):
    p = create_policy(db, brand='르무통')
    assert p.name == '[모음전] 르무통'
    assert p.brand == '르무통'


def test_브랜드_카테고리_소싱처를_다_조합한다(db):
    p = create_policy(db, brand='르무통', category='스니커즈', sourcing='무신사')
    assert p.name == '[모음전] 르무통 스니커즈 무신사'
    assert p.category == '스니커즈' and p.sourcing == '무신사'


def test_구분을_대량으로_바꿀_수_있다(db):
    p = create_policy(db, brand='나이키', prefix='대량')
    assert p.name == '[대량] 나이키'


def test_조합할_조각이_하나도_없으면_그래도_이름을_요구한다(db):
    """「[모음전]」 하나만 덩그러니 남는 이름은 뜻이 없다 — 자동 조합을 안 하고
    기존처럼 이름을 직접 받는다(이 성질이 깨지면 위 test_이름이_없으면_막는다 도 깨진다)."""
    with pytest.raises(PolicyError, match='이름'):
        create_policy(db, category='', sourcing='')


def test_이름을_직접_적으면_자동_조합이_안_덮는다(db):
    p = create_policy(db, name='내가 지은 이름', brand='르무통', category='스니커즈')
    assert p.name == '내가 지은 이름'


# ── 항목값 ────────────────────────────────────────────────────────────────

def test_저장하고_다시_읽힌다(db):
    p = create_policy(db, name='기본')
    cfg = {'token_order': ['brand', 'origin_name'], 'max_len': 100,
           'dedupe_words': True, 'replacements': [['재킷', '자켓']]}
    save_item(db, policy=p, market='coupang', item_key='name', config=cfg)
    assert values_for(db, p.id, 'coupang')['name'] == cfg


def test_마켓마다_따로_저장된다(db):
    p = create_policy(db, name='기본')
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 30})
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 20})
    assert values_for(db, p.id, 'coupang')['price']['sourcing_rate'] == 30
    assert values_for(db, p.id, 'smartstore')['price']['sourcing_rate'] == 20


def test_안_저장한_항목은_키_자체가_없다(db):
    """★ 화면이 기본값을 보여줘도 저장 전에는 「정해진 것」이 아니다."""
    p = create_policy(db, name='기본')
    got = values_for(db, p.id, 'coupang')
    assert got == {}
    assert 'price' not in got


def test_빈_설정으로_저장하면_안_정함으로_돌아간다(db):
    p = create_policy(db, name='기본')
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 30})
    save_item(db, policy=p, market='coupang', item_key='price', config={})
    assert values_for(db, p.id, 'coupang') == {}
    assert db.query(MarketPolicyValue).count() == 0


def test_모르는_항목은_막는다(db):
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='모르는 항목'):
        save_item(db, policy=p, market='coupang', item_key='없는항목',
                  config={'a': 1})


def test_모르는_마켓은_막는다(db):
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='모르는 마켓'):
        save_item(db, policy=p, market='11st_wrong', item_key='price',
                  config={'margin_rate': 1})


def test_여러_항목을_한_번에_저장한다(db):
    p = create_policy(db, name='기본')
    n = save_values(db, policy=p, market='coupang', values={
        'price': {'sourcing_rate': 25},
        'shipping': {'fee_mode': '무료'},
    })
    assert n == 2
    assert set(values_for(db, p.id, 'coupang')) == {'price', 'shipping'}


def test_같은_값을_다시_저장하면_바뀐_것이_없다(db):
    p = create_policy(db, name='기본')
    v = {'price': {'sourcing_rate': 25}}
    save_values(db, policy=p, market='coupang', values=v)
    assert save_values(db, policy=p, market='coupang', values=v) == 0


# ── 채움 현황 ─────────────────────────────────────────────────────────────

def test_판매가를_정해야_가격을_쓸_수_있다(db):
    p = create_policy(db, name='기본')
    assert readiness(db, p.id)['coupang']['price_ready'] is False
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 25})
    rd = readiness(db, p.id)['coupang']
    assert rd['price_ready'] is True and rd['missing'] == []


def test_한_마켓만_정해도_다른_마켓은_그대로_못_쓴다(db):
    p = create_policy(db, name='기본')
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 25})
    rd = readiness(db, p.id)
    assert rd['coupang']['price_ready'] is True
    assert all(not rd[m]['price_ready'] for m in MARKET_KEYS if m != 'coupang')


def test_채움_수는_정한_항목_수다(db):
    p = create_policy(db, name='기본')
    rd0 = readiness(db, p.id)['coupang']
    assert rd0['filled'] == 0 and rd0['total'] == len(item_keys_for('coupang'))
    save_item(db, policy=p, market='coupang', item_key='price', config={'sourcing_rate': 25})
    save_item(db, policy=p, market='coupang', item_key='tags', config={'max_count': 5})
    assert readiness(db, p.id)['coupang']['filled'] == 2


# ── 상품 적용 ─────────────────────────────────────────────────────────────

def test_고른_상품에_붙는다(db):
    _models(db, 'A', 'B', 'C')
    p = create_policy(db, name='기본')
    assert apply_to(db, policy=p, model_codes=['A', 'B']) == 2
    assert policy_of(db, 'A').id == p.id
    assert policy_of(db, 'C') is None
    assert applied_count(db, p.id) == 2


def test_다시_붙이면_갈아끼워진다(db):
    """상품 하나에 정책 하나 — 두 개가 붙으면 어느 쪽이 진짜인지 알 수 없다."""
    _models(db, 'A')
    p1 = create_policy(db, name='정책1')
    p2 = create_policy(db, name='정책2')
    apply_to(db, policy=p1, model_codes=['A'])
    apply_to(db, policy=p2, model_codes=['A'])
    assert policy_of(db, 'A').id == p2.id
    assert db.query(BundlePolicyLink).filter_by(model_code='A').count() == 1


def test_같은_상품을_여러_번_골라도_한_번만(db):
    _models(db, 'A')
    p = create_policy(db, name='기본')
    assert apply_to(db, policy=p, model_codes=['A', 'A', 'A']) == 1


def test_없는_상품은_막는다(db):
    _models(db, 'A')
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='없는 상품'):
        apply_to(db, policy=p, model_codes=['A', '없는코드'])


def test_하나도_안_고르면_막는다(db):
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='하나도'):
        apply_to(db, policy=p, model_codes=[])


def test_기본정책은_여러_개_지정할_수_있다(db):
    """[2026-08-19 사장님 확정] 여러 번 재사용하는 템플릿이라 여러 개 허용 — 예전엔 하나 제한."""
    p1 = create_policy(db, name='정책1')
    p2 = create_policy(db, name='정책2')
    toggle_default(db, policy=p1)
    toggle_default(db, policy=p2)
    assert p1.is_default == 1 and p2.is_default == 1


def test_기본정책_지정은_다시_누르면_풀린다(db):
    p = create_policy(db, name='정책1')
    assert toggle_default(db, policy=p) is True
    assert p.is_default == 1
    assert toggle_default(db, policy=p) is False
    assert p.is_default == 0


# ── 정책 고르기 카드(#1059) — 마켓별 상태 3단계·적용 상품 목록 ─────────────────
#   옵션생성 화면의 위상 3종(draft/ready/used → wait/mid/sale)과 같은 이름 체계.
#   wait=작성중(가격 아직 못 씀) · mid=준비됨(가격은 되는데 붙은 상품 없음) ·
#   sale=적용됨(가격 되고 붙은 상품도 있음).

def test_안_켠_마켓은_작성중이다(db):
    from lemouton.policy.service import market_status
    p = create_policy(db, name='기본')
    assert market_status(db, p.id, markets=['coupang'])['coupang'] == 'wait'


def test_가격만_채우면_상품이_없어도_준비됨이다(db):
    from lemouton.policy.service import market_status
    p = create_policy(db, name='기본')
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 25})
    assert market_status(db, p.id, markets=['coupang'])['coupang'] == 'mid'


def test_가격_채우고_상품도_붙으면_적용됨이다(db):
    from lemouton.policy.service import market_status
    _models(db, 'A')
    p = create_policy(db, name='기본')
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 25})
    apply_to(db, policy=p, model_codes=['A'])
    assert market_status(db, p.id, markets=['coupang'])['coupang'] == 'sale'


def test_상품이_붙어도_가격_안_채우면_적용됨이_아니다(db):
    """🔴 붙었다고 무조건 「적용됨」이 아니다 — 그 마켓 가격이 아직 안 나갈 수 있다."""
    from lemouton.policy.service import market_status
    _models(db, 'A')
    p = create_policy(db, name='기본')
    apply_to(db, policy=p, model_codes=['A'])
    assert market_status(db, p.id, markets=['coupang'])['coupang'] == 'wait'


def test_마켓을_생략하면_켠_마켓만_돌려준다(db):
    from lemouton.policy.service import market_status, set_enabled_markets
    p = create_policy(db, name='기본')
    set_enabled_markets(db, policy=p, markets=['coupang', 'smartstore'])
    assert set(market_status(db, p.id)) == {'coupang', 'smartstore'}


def test_적용_상품이_없으면_빈_목록이다(db):
    from lemouton.policy.service import applied_products
    p = create_policy(db, name='기본')
    assert applied_products(db, p.id) == {'total': 0, 'sample': []}


def test_적용_상품은_총_개수와_최대_limit개까지만_돌려준다(db):
    from lemouton.policy.service import applied_products
    _models(db, 'A', 'B', 'C', 'D')
    p = create_policy(db, name='기본')
    apply_to(db, policy=p, model_codes=['A', 'B', 'C', 'D'])
    got = applied_products(db, p.id, limit=3)
    assert got['total'] == 4
    assert len(got['sample']) == 3
    assert {it['model_code'] for it in got['sample']} <= {'A', 'B', 'C', 'D'}
    assert all('name' in it for it in got['sample'])


def test_적용_상품_키_이름은_items가_아니다(db):
    """🔴 Jinja 에서 dict.items 는 값이 아니라 내장 메서드로 풀린다 — 화면이 조용히 깨진다."""
    from lemouton.policy.service import applied_products
    p = create_policy(db, name='기본')
    assert 'items' not in applied_products(db, p.id)

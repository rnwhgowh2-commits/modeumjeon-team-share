# -*- coding: utf-8 -*-
"""가격 템플릿 → 정책 이관 · 전수 대조.

🔴 이 파일이 지키는 것 — **옮긴 뒤 가격이 한 원도 안 바뀌어야** 전환할 수 있다.
   손으로 옮기면 반드시 빠지므로 옮기기도 기계가 한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM      # noqa: F401 — 테이블 등록
from lemouton.templates.models import PriceTemplate


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture()
def tpl(db):
    """기본값 그대로인 템플릿 — 라이브의 「기본 템플릿」과 같은 출발점."""
    t = PriceTemplate(name='대조용 템플릿')
    db.add(t)
    db.flush()
    return t


# ── 껍데기가 엔진이 묻는 말을 알아듣나 ──────────────────────────────────

def test_판매가가_없는_정책은_껍데기를_안_준다(db):
    """빈 정책을 물리면 엔진이 마켓 기본 마진율로 엉뚱한 가격을 만든다."""
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy
    p = create_policy(db, name='빈정책')
    assert policy_as_template(db, p.id) is None


def test_껍데기가_마진율을_소수로_준다(db):
    """정책은 퍼센트(9.45), 엔진은 소수(0.0945)로 읽는다."""
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy, save_item
    p = create_policy(db, name='소수변환')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 9.45})
    shim = policy_as_template(db, p.id)
    assert shim.ss_mode_sourcing == 'rate'
    assert abs(shim.ss_rate_sourcing - 0.0945) < 1e-9


def test_껍데기는_안_정한_칸에_None_을_준다(db):
    """0 을 채우면 그 가격이 그대로 마켓에 나간다."""
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy, save_item
    p = create_policy(db, name='빈칸')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 10})
    shim = policy_as_template(db, p.id)
    assert shim.ss_fee_rate is None, '수수료를 안 정했으면 엔진이 마켓 기본값을 쓰게 둔다'
    assert shim.coupang_rate_sourcing is None, '안 채운 마켓은 값이 없어야 한다'


def test_껍데기_지정가는_소싱_사입이_따로다(db):
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy, save_item
    p = create_policy(db, name='지정가')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'fixed_price', 'sourcing_fixed': 128900,
                      'purchase_mode': 'fixed_price', 'purchase_fixed': 115900})
    shim = policy_as_template(db, p.id)
    assert shim.ss_external_sale_price == 128900       # 소싱 지정가
    assert shim.ss_boxhero_sale_price == 115900        # 사입 지정가


def test_껍데기_배송비는_배송_항목에서_온다(db):
    """판매가에 배송비 칸을 안 만들었다 — 「배송」 항목이 주인이다."""
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy, save_item
    p = create_policy(db, name='배송비')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 10})
    save_item(db, policy=p, market='smartstore', item_key='shipping',
              config={'fee_mode': 'paid', 'fee_amount': 3000})
    assert policy_as_template(db, p.id).ss_delivery_fee == 3000


# ── 이관 ────────────────────────────────────────────────────────────────

def test_템플릿을_정책으로_옮긴다(db, tpl):
    from lemouton.policy.migrate_from_template import migrate_template
    got = migrate_template(db, tpl=tpl)
    assert got['policy_id']
    assert set(got['markets']) == {'smartstore', 'coupang', 'lotteon',
                                   'eleven11', 'auction', 'gmarket'}


def test_두_번_옮겨도_정책이_하나다(db, tpl):
    """멱등 — 다시 돌려도 같은 정책을 갱신한다."""
    from lemouton.policy.migrate_from_template import migrate_template
    a = migrate_template(db, tpl=tpl)
    b = migrate_template(db, tpl=tpl)
    assert a['policy_id'] == b['policy_id']


def test_옮긴_값이_새_칸_이름이다(db, tpl):
    from lemouton.policy.migrate_from_template import migrate_template
    from lemouton.policy.service import values_for
    got = migrate_template(db, tpl=tpl)
    cfg = values_for(db, got['policy_id'], 'smartstore')['price']
    assert 'sourcing_mode' in cfg and 'sourcing_rate' in cfg
    assert 'margin_rate' not in cfg, '옛 칸 이름으로 저장하면 안 된다'


# ── 🔴 전수 대조 — 여기가 전환의 관문이다 ────────────────────────────────

def test_옮긴_뒤_가격이_한_원도_안_바뀐다(db, tpl):
    from lemouton.policy.migrate_from_template import compare_prices, migrate_template
    got = migrate_template(db, tpl=tpl)
    res = compare_prices(db, tpl=tpl, policy_id=got['policy_id'])
    assert res['checked'] >= 36, '마켓 6 × 소싱/사입 2 × 매입가 3 = 36가지는 봐야 한다'
    assert res['ok'], (
        '옮긴 뒤 가격이 달라졌습니다 — 전환하면 안 됩니다:\n'
        + '\n'.join(f"  {r['market']} {r['side']} 매입가 {r['purchase']}: "
                    f"{r['template']} → {r['policy']}" for r in res['rows'][:10]))


def test_값을_고치면_대조가_잡아낸다(db, tpl):
    """대조가 진짜로 검사하는지 본다 — 늘 통과하는 검사는 검사가 아니다."""
    from lemouton.policy.migrate_from_template import compare_prices, migrate_template
    from lemouton.policy.service import save_item
    from lemouton.policy.models import MarketPolicy
    got = migrate_template(db, tpl=tpl)
    p = db.get(MarketPolicy, got['policy_id'])
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 99})
    res = compare_prices(db, tpl=tpl, policy_id=got['policy_id'])
    assert not res['ok']
    assert any(r['market'] == 'ss' and r['side'] == 'sourcing' for r in res['rows'])


def test_기본값이_아닌_값으로도_한_원도_안_바뀐다(db):
    """기본값만 맞으면 「늘 통과하는 검사」가 된다 — 라이브처럼 손댄 값으로도 본다.

    라이브 「기본 템플릿」이 스스 116,900 · 쿠팡 128,900 · 가드레일 99,000~120,000
    인 것을 흉내 냈다(2026-08-01 화면 실측).
    """
    from lemouton.policy.migrate_from_template import compare_prices, migrate_template
    t = PriceTemplate(
        name='라이브 흉내',
        guardrail_lower=99000, guardrail_upper=120000, rounding_unit=100,
        # 스스 — 소싱은 마진율, 사입은 지정가
        ss_mode_sourcing='rate', ss_rate_sourcing=0.0945, ss_fee_rate=0.06,
        ss_mode_purchase='fixed', ss_boxhero_sale_price=116900,
        ss_delivery_fee=3000, ss_return_fee=5000,
        # 쿠팡 — 양쪽 다 지정가
        coupang_mode_sourcing='fixed', coupang_external_sale_price=128900,
        coupang_mode_purchase='fixed', coupang_boxhero_sale_price=128900,
        coupang_fee_rate=0.1155, coupang_delivery_fee=0,
        # 롯데온 — 마진금액
        lotteon_mode_sourcing='amount', lotteon_amount_sourcing=12000,
        lotteon_fee_rate=0.13, lotteon_delivery_fee=2500,
        # 11번가 — 마진율 다르게
        eleven11_mode_sourcing='rate', eleven11_rate_sourcing=0.1542,
        eleven11_fee_rate=0.13,
        # 옥션·G마켓 — 사입만 지정가
        auction_mode_purchase='fixed', auction_boxhero_sale_price=124000,
        gmarket_mode_purchase='fixed', gmarket_boxhero_sale_price=124000,
    )
    db.add(t)
    db.flush()

    got = migrate_template(db, tpl=t)
    res = compare_prices(db, tpl=t, policy_id=got['policy_id'],
                         purchases=(30000, 92400, 200000))
    assert res['ok'], (
        '손댄 값에서 가격이 달라졌습니다 — 전환하면 안 됩니다:\n'
        + '\n'.join(f"  {r['market']} {r['side']} 매입가 {r['purchase']}: "
                    f"{r['template']} → {r['policy']}" for r in res['rows'][:10]))


def test_가드레일도_같이_옮겨진다(db):
    """안 내려갈/올라갈 값을 안 옮기면 상한·하한이 풀려 엉뚱한 가격이 나간다."""
    from lemouton.policy.migrate_from_template import migrate_template
    from lemouton.policy.service import values_for
    t = PriceTemplate(name='가드레일', guardrail_lower=99000, guardrail_upper=120000)
    db.add(t)
    db.flush()
    got = migrate_template(db, tpl=t)
    cfg = values_for(db, got['policy_id'], 'smartstore')['price']
    assert cfg['floor_price'] == 99000
    assert cfg['cap_price'] == 120000


# ── 🔴 되받기 — 정책이 값을 정한 자리에서만 가격이 바뀐다 ────────────────

def test_정책이_안_정한_마켓은_템플릿_가격_그대로(db, tpl):
    """마켓 하나만 채운 정책이 나머지 마켓 가격을 갈아엎으면 안 된다.

    되받기가 없으면 엔진이 **마켓 기본 마진율**로 계산해, 사장님이 정한 적 없는
    가격이 5마켓에 나간다.
    """
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy, save_item
    from lemouton.pricing.unified import compute_market_price

    p = create_policy(db, name='스스만 채움')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 30})
    shim = policy_as_template(db, p.id, fallback=tpl)

    for prefix in ('coupang', 'lotteon', 'eleven11', 'auction', 'gmarket'):
        for side in ('sourcing', 'purchase'):
            a = compute_market_price(tpl, prefix, side, 92400).final_price
            b = compute_market_price(shim, prefix, side, 92400).final_price
            assert a == b, f'{prefix} {side} 가 달라졌다: {a} → {b}'


def test_정책이_정한_마켓만_바뀐다(db, tpl):
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy, save_item
    from lemouton.pricing.unified import compute_market_price

    p = create_policy(db, name='스스만 바꿈')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 30})
    shim = policy_as_template(db, p.id, fallback=tpl)

    a = compute_market_price(tpl, 'ss', 'sourcing', 92400).final_price
    b = compute_market_price(shim, 'ss', 'sourcing', 92400).final_price
    assert a != b, '정책이 마진율을 30%로 정했으면 스스 가격은 바뀌어야 한다'


def test_판매가만_정하고_배송비는_안_정하면_템플릿_배송비를_쓴다(db, tpl):
    """배송비가 0 으로 떨어지면 그만큼 싼 값이 나간다(이관 때 실제로 겪었다)."""
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.service import create_policy, save_item

    p = create_policy(db, name='배송비 안 정함')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 30})
    shim = policy_as_template(db, p.id, fallback=tpl)
    assert shim.ss_delivery_fee == tpl.ss_delivery_fee


def test_붙은_정책이_없으면_껍데기도_없다(db, tpl):
    """정책이 안 붙은 상품은 쓰던 템플릿을 그대로 쓴다."""
    from lemouton.policy.as_template import policy_template_for_model
    assert policy_template_for_model(db, 'NO_SUCH_MODEL', fallback=tpl) is None
    assert policy_template_for_model(db, '', fallback=tpl) is None


# ── 🔴 전환 안전 — 정책이 없으면 가격이 한 원도 안 바뀐다 ────────────────

def test_정책이_안_붙은_상품은_템플릿_경로_그대로(db, tpl):
    """전환을 켠 뒤에도, 정책이 안 붙은 상품은 가격이 그대로여야 한다.

    라이브 상품 대부분이 여기 해당한다 — 이게 깨지면 배포 즉시 가격이 흔들린다.
    """
    from lemouton.policy.as_template import policy_template_for_model
    from lemouton.sourcing.models import Model

    db.add(Model(model_code='NOPOLICY', model_name_raw='정책없음',
                 brand='르무통', auto_enabled=True))
    db.flush()
    assert policy_template_for_model(db, 'NOPOLICY', fallback=tpl) is None


def test_정책은_붙었지만_판매가를_안_정했으면_템플릿_그대로(db, tpl):
    """정책만 붙이고 값을 안 채운 상태 — 라이브의 지금 모습이다."""
    from lemouton.policy.as_template import policy_template_for_model
    from lemouton.policy.service import apply_to, create_policy
    from lemouton.sourcing.models import Model

    db.add(Model(model_code='EMPTYPOL', model_name_raw='빈정책',
                 brand='르무통', auto_enabled=True))
    db.flush()
    p = create_policy(db, name='값 없는 정책')
    apply_to(db, policy=p, model_codes=['EMPTYPOL'])
    assert policy_template_for_model(db, 'EMPTYPOL', fallback=tpl) is None

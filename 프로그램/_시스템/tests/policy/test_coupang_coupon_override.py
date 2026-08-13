# -*- coding: utf-8 -*-
"""[2026-08-13 사장님 확정] 「정책 / 비정책」 토글 — 상품에서만 바꾸기.

■ 사장님 말씀
    「상품관리에서 정책 벗어나고, 상품이미지·상품명 등도 정책에서 벗어나서 특정 가공만
      변경 가능하거든. 이것도 마찬가지로 **상품에서만 변경할지, 정책변경으로 할지
      두 개 다** 되어야 된다.」
    화면 모양은 **A2 미끄럼 스위치** — 파랑이면 정책, 주황이면 이 상품만.

■ 🔴 이 파일에서 제일 중요한 규칙
    **비정책(own)으로 돌린 상품은 정책을 바꿔도 안 따라간다.**
    이게 깨지면 사장님이 상품에 따로 정해 둔 값이 **조용히 날아간다** — 에러도 없이.
    쿠폰은 돈이라 그 순간 그 상품의 할인액이 바뀌어 나간다.

■ 🔴 「정책으로 되돌리기」는 값을 지우는 것이지 0 으로 만드는 게 아니다
    `{'mode':'own','value':0}` = 「이 상품은 할인 0원」  (일부러 안 깎는 것)
    `{'mode':'policy'}`        = 「정책이 정한 값을 따른다」
    둘을 섞으면 0원 쿠폰을 만들려다 정책값이 나가거나, 그 반대가 된다.

■ 이 파일은 값의 **출처**만 다룬다. 실제로 거는 순서는 `coupon_apply`(정본).
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in ("lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
           "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
           "lemouton.uploader.models", "lemouton.templates.models",
           "lemouton.inventory.models", "lemouton.sources.models",
           "lemouton.multitenancy.models", "lemouton.audit.models",
           "lemouton.mapping.models", "lemouton.sets.models"):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.policy import coupon_service as CS               # noqa: E402
from lemouton.sets.models import SetChannel, SetChannelOption   # noqa: E402
from tests.policy.test_coupang_coupon_apply import _Fake        # noqa: E402

_NOW = _dt.datetime(2026, 8, 13, 15, 0, 0)


@pytest.fixture
def db():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _chan(db, *, set_id=1, api_fields=None, opt='111'):
    ch = SetChannel(set_id=set_id, market='coupang', account_key='세소쿠팡',
                    market_product_id='157', status='linked',
                    api_fields=api_fields if api_fields is not None else {})
    db.add(ch)
    db.flush()
    if opt:
        db.add(SetChannelOption(channel_id=ch.id, canonical_sku='K1',
                                market_option_id=opt, status='matched',
                                mkt_price=128900, mkt_stock=3))
    db.commit()
    return ch


# ── 기본값은 「정책 따름」 ─────────────────────────────────────

def test_아무것도_안_했으면_정책을_따른다(db):
    ch = _chan(db)
    assert CS.override_of(ch) == {'mode': 'policy', 'value': None}
    assert CS.is_own(ch) is False


def test_비정책으로_돌리면_그_값을_쓴다(db):
    ch = _chan(db)
    CS.set_override(db, ch, mode='own', value=250)
    assert CS.override_of(ch) == {'mode': 'own', 'value': 250}
    assert CS.is_own(ch) is True
    assert CS.effective_discount(db, ch, policy_value={'value': 100, 'unitType': 'WON'}) \
        == {'value': 250, 'unitType': 'WON'}


def test_정책으로_되돌리면_정책_값을_쓴다(db):
    ch = _chan(db, api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 250}})
    CS.set_override(db, ch, mode='policy')
    assert CS.is_own(ch) is False
    assert CS.effective_discount(db, ch, policy_value={'value': 100, 'unitType': 'WON'}) \
        == {'value': 100, 'unitType': 'WON'}


def test_이_상품은_할인_0원_과_정책_따름은_다르다(db):
    """🔴 둘을 섞으면 0원으로 만들려다 정책값이 나간다(또는 반대)."""
    ch = _chan(db)
    CS.set_override(db, ch, mode='own', value=0)
    assert CS.is_own(ch) is True
    assert CS.effective_discount(db, ch, policy_value={'value': 100, 'unitType': 'WON'}) \
        is None, '0원은 「안 깎는다」 — 정책값 100원이 나가면 안 된다'


def test_비정책인데_값이_비면_정책으로_본다(db):
    """스위치만 돌리고 값을 안 적은 상태 — 지어내지 않는다."""
    ch = _chan(db)
    CS.set_override(db, ch, mode='own', value=None)
    assert CS.effective_discount(db, ch, policy_value={'value': 100, 'unitType': 'WON'}) \
        == {'value': 100, 'unitType': 'WON'}


def test_10원_단위가_아니면_안_받는다(db):
    """쿠팡이 「유효하지 않습니다」만 뱉기 전에 여기서 사람 말로 막는다."""
    ch = _chan(db)
    with pytest.raises(ValueError) as e:
        CS.set_override(db, ch, mode='own', value=255)
    assert '10원' in str(e.value)


def test_남의_값을_안_지운다(db):
    ch = _chan(db, api_fields={'남의값': 7, CS.COUPON_KEY: {'ok': True, 'coupon_id': 9}})
    CS.set_override(db, ch, mode='own', value=250)
    db.refresh(ch)
    assert ch.api_fields['남의값'] == 7
    assert ch.api_fields[CS.COUPON_KEY]['coupon_id'] == 9


def test_DB에_실제로_저장된다(db):
    ch = _chan(db)
    CS.set_override(db, ch, mode='own', value=250)
    db.expire_all()
    again = db.get(SetChannel, ch.id)
    assert (again.api_fields or {})[CS.OVERRIDE_KEY]['value'] == 250


# ── 🔴 제일 중요 — 정책을 바꿔도 비정책 상품은 안 건드린다 ────

def test_정책_전수_반영이_비정책_상품을_건너뛴다(db):
    """🔴 이게 깨지면 상품에 따로 정해 둔 값이 **조용히** 날아간다."""
    따름 = _chan(db, set_id=1)
    벗어남 = _chan(db, set_id=2,
                   api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 250}})
    대상 = CS.policy_targets(db, [따름, 벗어남])
    assert [c.id for c in 대상['will']] == [따름.id]
    assert [c.id for c in 대상['skip']] == [벗어남.id]


def test_실제로_도는_정책_전수_반영도_비정책을_건너뛴다(db):
    """🔴 `policy_targets` 만 재면 헛돈다 — **사장님이 정책을 저장할 때 도는 길**을 잰다.

    뮤테이션으로 잡힌 구멍이다: 판을 짜 놓고 안 쓰면(전부 대상으로 두면) 위 시험은
    통과하는데 라이브에선 비정책 상품까지 쿠폰이 다시 걸린다.
    """
    from lemouton.policy.models import SetPolicyLink
    from lemouton.policy.service import create_policy, save_values
    따름 = _chan(db, set_id=1)
    벗어남 = _chan(db, set_id=2,
                   api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 250}})
    p = create_policy(db, name='할인정책')
    save_values(db, policy=p, market='coupang',
                values={'price': {'discount_unit': 'WON', 'discount_value': 100}})
    db.add(SetPolicyLink(set_id=1, policy_id=p.id))
    db.add(SetPolicyLink(set_id=2, policy_id=p.id))
    db.commit()

    out = CS.request_for_policy(db, p.id, now=_NOW)
    assert out['queued'] == 1, '비정책 상품까지 대기열에 넣었다'
    assert out['skipped_own'] == 1
    ids = [c.id for c in CS.pending_requests(db)]
    assert ids == [따름.id], f'비정책 상품이 대기열에 들어갔다: {ids}'
    assert 벗어남.id not in ids


def test_비정책_0원은_100원_하한이_아니라_그_규칙으로_막힌다(db):
    """🔴 앞 시험은 「100원 미만 거부」에 우연히 걸려 통과했다 — 의도한 방어가 아니다.

    100원을 넘는 값으로 눌러도 「0원이면 안 만든다」가 자기 힘으로 서야 한다.
    그래서 정책값을 **1,000원**으로 두고 이 상품만 0원으로 돌린다.
    """
    ch = _chan(db, api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 0}})
    c = _Fake(ok_at=100)
    r = CS.apply_or_renew(db, ch, client=c, now=_NOW, sleep=lambda _s: None,
                          discount_for=lambda _s, _ch: {'value': 1000,
                                                        'unitType': 'WON'})
    assert r['ok'] is False
    assert c.created == [], '안 깎기로 한 상품에 정책값 1,000원 쿠폰을 만들었다'
    # 🔴 `'0원' in 메시지` 로 재면 헛돈다 — 「깎을 금액이 **100원** 이상」 안에도
    #   「0원」이 들어 있어, 엉뚱한 이유(하한 미달)로 막혀도 통과한다(실제로 그랬다).
    #   「비정책」이라는 이 갈래에만 있는 말로 재야 그 방어가 자기 힘으로 섰는지 안다.
    assert '비정책' in r['message'], \
        f'0원 규칙이 아니라 딴 이유로 막혔다: {r["message"]}'


def test_정책으로_되돌리면_적어_뒀던_값도_지운다(db):
    """🔴 값이 남아 있으면 다음에 비정책으로 켤 때 옛 값이 되살아난다."""
    ch = _chan(db, api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 250}})
    rec = CS.set_override(db, ch, mode='policy', value=250)
    assert rec == {'mode': 'policy', 'value': None}
    assert CS.override_of(ch)['value'] is None, '되돌렸는데 옛 값이 남았다'


def test_확인창이_몇_개_바뀌는지_말해_준다(db):
    """사장님 확정 B5 — 몇 개가 바뀌고 몇 개는 안 건드리는지 먼저 보여 준다."""
    for i in range(3):
        _chan(db, set_id=i + 1)
    _chan(db, set_id=9, api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 250}})
    plan = CS.policy_targets(db, db.query(SetChannel).all())
    assert len(plan['will']) == 3
    assert len(plan['skip']) == 1
    assert plan['skip'][0].id


def test_고른_것만_다시_건다(db):
    """B5 — 전부가 아니라 고른 상품만. 안 고른 것은 손대지 않는다."""
    a, b = _chan(db, set_id=1), _chan(db, set_id=2)
    CS.request_for_channels(db, [a], now=_NOW)
    assert [c.id for c in CS.pending_requests(db)] == [a.id]


def test_비정책_상품도_단추로는_걸_수_있다(db):
    """정책 전수에서 빠지는 것이지, 그 상품을 못 거는 게 아니다."""
    ch = _chan(db, api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 250}})
    r = CS.request_for_channel(db, ch, now=_NOW)
    assert r['ok'] is True


# ── 실제로 걸 때 그 값이 쓰이나 ──────────────────────────────

def test_비정책_값으로_쿠폰이_걸린다(db):
    ch = _chan(db, api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 250}})
    c = _Fake(ok_at=250)
    r = CS.apply_or_renew(db, ch, client=c, now=_NOW, sleep=lambda _s: None)
    assert r['ok'] is True
    assert r['value'] == 250, '이 상품만의 값(250)이 아니라 딴 값이 나갔다'
    assert [a['value'] for a in r['attempts']] == [250], '100원부터 헤맸다'


def test_비정책_0원이면_쿠폰을_안_만든다(db):
    """「이 상품은 안 깎는다」 — 0원 쿠폰을 만들면 안 된다."""
    ch = _chan(db, api_fields={CS.OVERRIDE_KEY: {'mode': 'own', 'value': 0}})
    c = _Fake(ok_at=100)
    r = CS.apply_or_renew(db, ch, client=c, now=_NOW, sleep=lambda _s: None)
    assert r['ok'] is False
    assert c.created == [], '안 깎기로 한 상품에 쿠폰을 만들었다'

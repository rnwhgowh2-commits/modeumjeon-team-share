# -*- coding: utf-8 -*-
"""「판매가」 항목 — 옛 칸 번역 · 커버리지.

🔴 이미 저장된 정책이 있다. 칸 이름을 바꾸면서 옛 값을 못 읽으면
   사장님이 채워 둔 값이 조용히 「안 정함」이 된다.
"""
import pytest

from lemouton.policy.price_cfg import PriceSide, read_side


# ── 옛 칸 번역 ──────────────────────────────────────────────────────────

def test_새_칸을_그대로_읽는다():
    got = read_side({'sourcing_mode': 'margin_rate', 'sourcing_rate': 25}, 'sourcing')
    assert got == PriceSide(mode='margin_rate', rate=25.0, amount=None, fixed=None)


def test_사입품_칸을_읽는다():
    got = read_side({'purchase_mode': 'fixed_price', 'purchase_fixed': 115900}, 'purchase')
    assert got.mode == 'fixed_price'
    assert got.fixed == 115900


def test_옛_칸_마진율을_양쪽_모두에_준다():
    """옛 정책은 소싱·사입 구분이 없었다 — 양쪽 다 그 값으로 본다."""
    old = {'mode': 'margin_rate', 'margin_rate': 25}
    assert read_side(old, 'sourcing').rate == 25.0
    assert read_side(old, 'purchase').rate == 25.0


def test_옛_칸_고정금액은_지정가로_번역된다():
    old = {'mode': 'fixed_amount', 'fixed_amount': 128900}
    got = read_side(old, 'sourcing')
    assert got.mode == 'fixed_price'
    assert got.fixed == 128900


def test_새_칸이_있으면_옛_칸을_무시한다():
    """둘 다 있으면 새 것이 이긴다 — 안 그러면 고친 값이 안 먹는다."""
    mixed = {'mode': 'margin_rate', 'margin_rate': 25,
             'sourcing_mode': 'margin_rate', 'sourcing_rate': 32}
    assert read_side(mixed, 'sourcing').rate == 32.0


def test_안_정한_것은_None_이다():
    """0 과 「안 정함」은 다르다 — 0 으로 채우면 그 가격이 마켓에 나간다."""
    got = read_side({}, 'sourcing')
    assert got.rate is None and got.amount is None and got.fixed is None


def test_영은_값이다():
    assert read_side({'sourcing_mode': 'margin_rate', 'sourcing_rate': 0}, 'sourcing').rate == 0.0


def test_참거짓은_숫자가_아니다():
    """파이썬에선 True 가 1 로 통한다 — 마진율 100% 로 새면 안 된다."""
    assert read_side({'sourcing_rate': True}, 'sourcing').rate is None


def test_모르는_쪽은_거부한다():
    with pytest.raises(ValueError):
        read_side({}, '이상한쪽')


def test_지금_쓰는_값만_돌려준다():
    from lemouton.policy.price_cfg import effective_value
    cfg = {'sourcing_mode': 'fixed_price', 'sourcing_rate': 25,
           'sourcing_fixed': 128900}
    assert effective_value(cfg, 'sourcing') == 128900


# ── 커버리지 — 가격 템플릿이 가진 것을 다 담았나 ──────────────────────────

def _price_field_keys():
    from lemouton.registration.process_rule_schema import schema_for
    return {f.key for f in schema_for('price').fields}


def test_소싱품_사입품이_따로_있다():
    keys = _price_field_keys()
    for side in ('sourcing', 'purchase'):
        for suffix in ('mode', 'rate', 'amount', 'fixed'):
            assert f'{side}_{suffix}' in keys, f'{side}_{suffix} 가 없다'


def test_가격_안전장치_여섯_칸():
    keys = _price_field_keys()
    for k in ('floor_price', 'cap_price', 'rounding_unit',
              'normal_price', 'source_pick', 'size_unify'):
        assert k in keys, f'{k} 가 없다'


def test_수수료율은_그대로_있다():
    assert 'fee_rate' in _price_field_keys()


def test_배송비는_판매가에_없다():
    """정책 「배송」 항목에 이미 있다 — 여기 또 만들면 정책 안에서 중복이다."""
    keys = _price_field_keys()
    for k in ('fee_amount', 'delivery_fee', 'return_fee', 'exchange_fee'):
        assert k not in keys, f'{k} 가 판매가에도 있다(배송 항목과 중복)'


def test_돈_칸은_기본값을_두지_않는다():
    """「안 정함」과 「0원으로 정함」은 다르다 — 임의 기본값은 그 가격을 마켓에 보낸다.

    fee_rate 는 제외 — 사장님이 2026-08-02 에 「기본 다 13%」로 확정했다.
    수수료율만 예외인 이유가 있다: 빈칸을 0으로 읽으면 판매가가 **싸게** 나가
    손해가 나지만, 13% 는 **비싸게** 나가 손해가 나지 않는다. 방향이 반대다.
    (fee_rate 의 별도 규칙은 아래 두 테스트가 지킨다)
    """
    from lemouton.registration.process_rule_schema import schema_for
    money = {'sourcing_rate', 'sourcing_amount', 'sourcing_fixed',
             'purchase_rate', 'purchase_amount', 'purchase_fixed',
             'floor_price', 'cap_price', 'normal_price'}
    for f in schema_for('price').fields:
        if f.key in money:
            assert f.default is None, f'{f.key} 에 기본값 {f.default!r} 이 있다'


def test_수수료율은_항목표에_숫자를_안_적는다():
    """🔴 수수료율은 **마켓마다 다르다**(스스 6 · 쿠팡 11.55 · 롯데온 18 · 11번가 8 ·
    옥션/G마켓 15). 항목표는 마켓을 모르므로 한 숫자를 적으면 어느 마켓에서든
    그 값이 떠서, 사장님이 보는 값과 계산에 쓰는 값이 어긋난다.

    표의 주인은 `pricing/fee_defaults.py`(DB·화면에서 고침) 하나뿐이고,
    화면은 그 마켓 값을 받아 채운다.
    """
    from lemouton.registration.process_rule_schema import schema_for
    fee = next(f for f in schema_for('price').fields if f.key == 'fee_rate')
    assert fee.default is None, (
        f'항목표에 수수료율 숫자를 적었다: {fee.default!r} — 마켓마다 달라서 안 된다')


def test_화면이_그_마켓의_기본값을_받는다():
    """정책 화면 라우트가 `fee_default_pct` 를 넘겨야 칸이 채워진다.
    🔴 안 넘기면 빈칸이 뜨고, 사장님은 「안 정함」인 줄 아는데 계산은 기본값을 쓴다.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2]
           / 'webapp' / 'routes' / 'policy.py').read_text(encoding='utf-8')
    assert 'fee_default_pct' in src, '정책 화면에 마켓별 기본값을 안 넘긴다'
    assert 'default_fee_pct' in src, '숫자를 손으로 적었다 — 표에서 꺼내야 한다'


def test_수수료율은_소수를_잃지_않는다():
    """🔴 쿠팡 11.55% — `parseInt` 로 읽으면 11 로 잘려 판매가가 싸게 나간다."""
    from pathlib import Path
    tpl = (Path(__file__).resolve().parents[2]
           / 'webapp' / 'templates' / 'policy' / 'detail.html').read_text(encoding='utf-8')
    i = tpl.find('data-k="fee_rate"')
    assert 'data-t="num"' in tpl[max(0, i - 200):i + 200], (
        '수수료율이 정수 칸으로 저장된다 — 11.55 가 11 로 잘린다')
    assert "t === 'num'" in tpl and 'parseFloat' in tpl, '소수 저장 처리가 없다'


def test_방식은_세_가지():
    from lemouton.registration.process_rule_schema import schema_for
    for f in schema_for('price').fields:
        if f.key.endswith('_mode'):
            assert set(f.choices) == {'margin_rate', 'margin_amount', 'fixed_price'}


def test_사이즈_통일은_이제_판매가_안에_있다():
    """스스 전용 항목이 아니라 6마켓 모두의 판매가 안에 있다."""
    from lemouton.policy.fields import MARKET_KEYS, item_keys_for, items_for
    for mk in MARKET_KEYS:
        assert '_size_unify' not in item_keys_for(mk), f'{mk} 에 옛 항목이 남았다'
    for mk in MARKET_KEYS:
        price = [it for it in items_for(mk) if it['key'] == 'price'][0]
        assert any(f['key'] == 'size_unify' for f in price['fields']), \
            f'{mk} 판매가에 사이즈 통일이 없다'


# ── 읽는 쪽이 새 칸을 알아보나 ────────────────────────────────────────────

def test_미리보기가_새_칸을_읽는다():
    from lemouton.policy.preview import fixed_amount_of, margin_rate_of
    v = {'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 25}}
    assert margin_rate_of(v) == 25.0
    assert fixed_amount_of(v) is None


def test_미리보기가_지정가를_읽는다():
    from lemouton.policy.preview import fixed_amount_of, margin_rate_of
    v = {'price': {'sourcing_mode': 'fixed_price', 'sourcing_fixed': 128900}}
    assert fixed_amount_of(v) == 128900
    assert margin_rate_of(v) is None


def test_미리보기가_옛_값도_읽는다():
    """옛 정책이 조용히 「안 정함」이 되면 안 된다."""
    from lemouton.policy.preview import margin_rate_of
    assert margin_rate_of({'price': {'mode': 'margin_rate', 'margin_rate': 9}}) == 9.0


# ── 모르는 칸은 조용히 삼키지 않는다 ────────────────────────────────────

def _db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared.db import Base
    from lemouton.policy import models as PM     # noqa: F401 — 테이블 등록
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_모르는_칸은_저장을_거부한다():
    """오타난 칸이 조용히 저장되면 「왜 안 먹지」로 한참 헤맨다.

    칸이 15개로 늘면서 더 위험해졌다 — sourcing_rate 를 sourcing_ratio 로
    잘못 적어도 저장은 되고 계산에는 안 쓰이는 상태가 된다.
    """
    from lemouton.policy.service import PolicyError, create_policy, save_item
    s = _db()
    try:
        p = create_policy(s, name='오타')
        with pytest.raises(PolicyError) as e:
            save_item(s, policy=p, market='smartstore', item_key='price',
                      config={'sourcing_ratio': 25})
        assert '모르는 칸' in str(e.value)
    finally:
        s.close()


def test_옛_칸_이름도_새로_저장할_수는_없다():
    """읽기는 번역해 주지만, 새로 저장하는 값은 새 이름이어야 한다."""
    from lemouton.policy.service import PolicyError, create_policy, save_item
    s = _db()
    try:
        p = create_policy(s, name='옛이름')
        with pytest.raises(PolicyError):
            # 'margin_rate' 는 **옛 이름**이다 — 읽을 때만 번역해 주고, 저장은 막는다
            save_item(s, policy=p, market='smartstore', item_key='price',
                      config={'margin_rate': 25})
    finally:
        s.close()


def test_마켓_전용_항목의_칸은_통과한다():
    """쿠팡 「위너일 때 가격」처럼 스키마 밖에 정의된 항목도 막으면 안 된다."""
    from lemouton.policy.service import create_policy, save_item, values_for
    s = _db()
    try:
        p = create_policy(s, name='위너')
        save_item(s, policy=p, market='coupang', item_key='_winner',
                  config={'rule': '최저가 −1원', 'floor': 90000})
        assert values_for(s, p.id, 'coupang')['_winner']['floor'] == 90000
    finally:
        s.close()


def test_미리보기는_소싱품_기준이다():
    """미리보기의 매입가는 소싱처 값이라 소싱품 쪽을 봐야 한다."""
    from lemouton.policy.preview import margin_rate_of
    v = {'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 9,
                   'purchase_mode': 'margin_rate', 'purchase_rate': 30}}
    assert margin_rate_of(v) == 9.0


def test_판매가_화면이_항목표를_안_베낀다():
    """🔴 실제로 났던 사고 (2026-08-02):

    `policy/detail.html` 의 판매가 블록이 라벨·기본값·도움말을 **손으로 적어 두고**
    있었다. 그래서 항목표에서 수수료율 기본을 13 으로 바꿔도 화면은 옛 문구
    (「스스 6 · 쿠팡 11.55」)를 그대로 띄웠다 — 엔진은 13%, 화면은 6% 안내.
    「고쳤다」고 보고한 뒤 라이브에서 발각됐다.

    화면은 항목표에서 꺼내 써야 한다.
    """
    from pathlib import Path
    tpl = (Path(__file__).resolve().parents[2]
           / 'webapp' / 'templates' / 'policy' / 'detail.html').read_text(encoding='utf-8')
    i = tpl.find('data-k="fee_rate"')
    assert i > 0, '수수료율 칸이 사라졌다'
    block = tpl[max(0, i - 700):i + 700]
    assert "selectattr('key', 'equalto', 'fee_rate')" in block, (
        '수수료율 칸이 항목표를 안 읽는다 — 화면과 엔진이 또 갈린다')
    # 옛 숫자를 문구로 박아 두면 항목표를 고쳐도 화면이 안 따라온다
    for stale in ('스스 6 ', '11.55'):
        assert stale not in block, f'화면에 숫자를 손으로 적었다: {stale!r}'

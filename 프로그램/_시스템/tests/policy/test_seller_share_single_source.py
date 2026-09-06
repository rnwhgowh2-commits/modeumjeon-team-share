# -*- coding: utf-8 -*-
"""「이 할인 중 **우리가 내는 몫**은 얼마인가」 — 규칙은 한 곳에만 있어야 한다.

🔴 왜 — 이 규칙이 두 벌이 되면 한쪽만 고쳤을 때 **화면과 실제 업로드가가 갈린다.**
  이 저장소에서 그건 곧 금전 사고다(가이드 §4 철칙 3 단일 진실 원천).

  지금 이 규칙이 필요한 곳이 최소 세 곳이다:
    · `pricing/unified.resolve_market_policy` — 실제 업로드가
    · `policy/preview.py`                     — 사장님이 보는 미리보기
    · 리허설 스크립트                          — 승인용 표
"""
import pytest

from lemouton.policy.discount import seller_share


def test_판매자_부담이면_전액이_우리_몫():
    assert seller_share({'discount_unit': 'PERCENT', 'discount_value': 20,
                         'discount_burden': 'seller'}) == ('PERCENT', 20.0)


def test_마켓_부담이면_우리_몫은_없다():
    """🔴 마켓이 내는 몫까지 판매가에 얹으면 고객에게 괜히 비싸 보인다."""
    assert seller_share({'discount_unit': 'PERCENT', 'discount_value': 20,
                         'discount_burden': 'market'})[1] == 0


def test_반반이면_우리_몫만():
    assert seller_share({'discount_unit': 'WON', 'discount_value': 1000,
                         'discount_burden': 'split',
                         'discount_burden_pct': 40}) == ('WON', 400.0)


def test_부담_주체를_안_정했으면_판매자로_본다():
    """🔴 모르면 보수적으로 — 「마켓」으로 잘못 보면 판매가를 안 올려 그대로 손해다."""
    assert seller_share({'discount_unit': 'PERCENT', 'discount_value': 20})[1] == 20.0


def test_반반인데_몫을_안_적었으면_0_이_아니라_전액():
    """🔴 0 으로 보면 판매가를 안 올려 적자가 된다 — 모를 땐 우리가 다 낸다고 본다."""
    assert seller_share({'discount_unit': 'PERCENT', 'discount_value': 20,
                         'discount_burden': 'split'})[1] == 20.0


@pytest.mark.parametrize('cfg', [
    {}, None,
    {'discount_value': 0},
    {'discount_value': None},
    {'discount_value': '없음'},
    {'discount_value': 5, 'discount_unit': 'YEN'},          # 모르는 방식
    {'discount_value': 100, 'discount_unit': 'PERCENT'},    # 100% = 공짜
])
def test_할인이_아니면_0(cfg):
    """`discount_of` 가 이미 막는 것들을 여기서도 똑같이 막는다(판정이 갈리면 안 된다)."""
    assert seller_share(cfg)[1] == 0


def test_엔진이_이_함수를_쓴다():
    """🔴 규칙을 뽑아 놓고 엔진이 옛 계산을 그대로 들고 있으면 두 벌이 된 것이다."""
    import inspect

    from lemouton.pricing import unified
    src = inspect.getsource(unified.resolve_market_policy)
    assert 'seller_share' in src, 'resolve_market_policy 가 단일 원천을 안 쓴다'


def test_미리보기가_이_함수를_쓴다():
    import inspect

    from lemouton.policy import preview
    src = inspect.getsource(preview)
    assert 'seller_share' in src, '미리보기가 할인을 모른 채 판매가를 낸다'

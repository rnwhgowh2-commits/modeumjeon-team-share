# -*- coding: utf-8 -*-
"""「19세 이상만」이 마켓까지 가는가 — 지금은 **어디에도 안 간다.**

🔴 무엇이 잘못이었나 (2026-08-13 실측)
  정책에 「미성년자 구매」 칸이 있고 「전연령 구매 가능 / 19세 이상만」을 고를 수 있다.
  그런데:
    · `minor_purchase` 를 읽는 코드가 **0곳**이다
    · `ProductDraft.minor_purchasable` 은 `default=True` 인 채 **아무도 안 채운다**
    · 쿠팡은 `'adultOnly': 'EVERYONE'` 이 **상수로 박혀** 있다
    · 스스는 `draft.minor_purchasable` 을 읽지만, 그 값이 늘 기본값 True 다

  결과 — 「19세 이상만」을 고르셔도 **전연령으로 등록된다.** 성인 상품이면
  그대로 미성년자에게 노출된다. 값이 틀린 게 아니라 **고른 것이 무시된다.**

🔴 이 시험은 「정책 → 초안 → 마켓」 **세 마디를 각각** 잡는다. 한 마디만 이으면
  나머지에서 조용히 끊긴다 — 이 저장소가 반복해서 당한 형태다.
"""
import inspect

import pytest

from lemouton.policy.listing import minor_purchasable_of


# ── ① 규칙 자체 ────────────────────────────────────────────────────────
def test_19세_이상만이면_미성년자_구매_불가():
    assert minor_purchasable_of({'listing': {'minor_purchase': '19세 이상만'}}) is False


def test_전연령이면_구매_가능():
    assert minor_purchasable_of({'listing': {'minor_purchase': '전연령 구매 가능'}}) is True


@pytest.mark.parametrize('rules', [None, {}, {'listing': {}},
                                   {'listing': {'minor_purchase': None}},
                                   {'listing': {'minor_purchase': ''}}])
def test_안_고르셨으면_마켓_기본값_그대로(rules):
    """🔴 안 고른 것을 「19세 이상만」으로 지어내면 멀쩡한 상품이 안 팔린다."""
    assert minor_purchasable_of(rules) is True


def test_모르는_값을_성인전용으로_바꾸지_않는다():
    """🔴 반대로도 지어내지 않는다 — 오타 하나로 전 상품이 성인전용이 되면 안 된다."""
    assert minor_purchasable_of({'listing': {'minor_purchase': '19세이상'}}) is True


# ── ② 정책 → 초안 다리 ─────────────────────────────────────────────────
def test_초안_만들기가_정책의_미성년자_설정을_옮겨_담는다():
    """🔴 여기가 끊기면 마켓 쪽을 아무리 고쳐도 늘 기본값이 나간다."""
    src = inspect.getsource(__import__('lemouton.send.as_draft',
                                       fromlist=['upsert']).upsert)
    assert 'minor_purchasable' in src, \
        '초안이 정책의 미성년자 설정을 안 옮겨 담는다 — 늘 기본값(전연령)이 나간다'


# ── ③ 초안 → 마켓 ──────────────────────────────────────────────────────
def test_쿠팡이_상수_대신_초안을_읽는다():
    from lemouton.registration import compile_coupang as C
    src = inspect.getsource(C)
    assert "'adultOnly': 'EVERYONE'" not in src, \
        "쿠팡에 adultOnly='EVERYONE' 이 아직 박혀 있다 — 고르신 값이 무시된다"
    assert 'minor_purchasable' in src, '쿠팡이 초안의 미성년자 값을 안 읽는다'


def test_스스는_이미_초안을_읽는다():
    """이미 되어 있던 것이 되돌아가지 않게 잠근다."""
    from lemouton.registration import compile_smartstore as S
    assert 'minor_purchasable' in inspect.getsource(S)


def test_쿠팡_값이_마켓_어휘로_나간다():
    """ADULT_ONLY / EVERYONE — 마켓이 아는 말이어야 한다.

    🔴 어휘는 `policy/listing` **한 곳**에만 둔다. 조립기마다 문자열을 박으면
      한쪽만 고쳐졌을 때 마켓이 「유효하지 않은 값」만 뱉고 이유는 안 알려 준다.
    """
    from lemouton.policy.listing import coupang_adult_only
    assert coupang_adult_only(False) == 'ADULT_ONLY'
    assert coupang_adult_only(True) == 'EVERYONE'


# ── ④ 아직 안 되는 곳은 「된다」고 말하지 않는다 ────────────────────────
def test_아직_못_보내는_마켓은_체크리스트가_그대로_말한다():
    """🔴 11번가·옥션·G마켓·롯데온은 spec 에 칸 자체가 없다 — 고쳤다고 하면 안 된다."""
    from lemouton.policy.required import STORED_ONLY, WIRED, wiring_of
    state, note = wiring_of('listing')
    assert state in (WIRED, STORED_ONLY)
    if state == WIRED:
        assert '11번가' in note or '옥션' in note or '아직' in note, \
            '일부만 되는데 전부 되는 것처럼 적혀 있다'

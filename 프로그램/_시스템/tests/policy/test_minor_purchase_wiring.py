# -*- coding: utf-8 -*-
"""「19세 이상만」이 정책 → 초안 → 마켓까지 **끊기지 않고** 가는가.

🔴 무엇이 잘못이었나 (2026-08-13 발견) — 정책에 「전연령 구매 가능 / 19세 이상만」
  칸이 있는데, 고르신 값이 **어디에도 안 나갔다**. 쿠팡은 `adultOnly='EVERYONE'`
  이 상수로 박혀 있었고 초안 칸은 기본값 그대로였다. 성인 상품이면 그대로
  미성년자에게 노출된다 — 값이 틀린 게 아니라 **고른 것이 무시**되던 형태다.

🔴 고친 것은 **다른 세션**이다(main `0d0ddc03`·`3f64acfb`). 나도 같은 것을
  만들었는데 그쪽이 먼저 들어왔고 더 나았다 — 규칙을 `process_apply._MINOR_CHOICES`
  한 곳에 두고, 사본(`as_draft._POLICY_FIELDS`)을 거쳐 초안으로 옮긴다.
  내가 만든 두 번째 복사본(`policy/listing.py`)은 지웠다.

🔴 이 시험이 지키는 것은 **세 마디가 이어져 있는가**다. 한 마디만 이으면 나머지에서
  조용히 끊긴다 — 이 저장소가 반복해서 당한 형태다.
    ① 규칙      정책의 말 → True/False
    ② 다리      초안으로 옮겨 담기
    ③ 마켓      조립기가 그 값을 payload 에 싣기
"""
import inspect

import pytest


# ── ① 규칙 ─────────────────────────────────────────────────────────────
def test_두_선택지가_정확히_뒤집혀_있다():
    from lemouton.registration.process_apply import _MINOR_CHOICES
    assert _MINOR_CHOICES['19세 이상만'] is False
    assert _MINOR_CHOICES['전연령 구매 가능'] is True


def test_모르는_값은_지어내지_않고_말한다():
    """🔴 오타 하나로 전 상품이 성인전용이 되거나, 반대로 조용히 전연령이 되면 안 된다."""
    src = inspect.getsource(
        __import__('lemouton.registration.process_apply',
                   fromlist=['_apply_listing'])._apply_listing)
    assert 'UNKNOWN_MINOR_CHOICE' in src, '모르는 값을 조용히 넘긴다'
    assert '지어내지' in src or '모르는' in src, '왜 안 넣는지 사람 말로 안 적혀 있다'


# ── ② 정책 → 초안 다리 ─────────────────────────────────────────────────
def test_초안_만들기가_정책의_미성년자_설정을_옮겨_담는다():
    """🔴 여기가 끊기면 마켓 쪽을 아무리 고쳐도 늘 기본값이 나간다.

    🔴 **`upsert` 본문 글자를 세지 않는다.** 실제 배선은 「사본에서 옮길 칸 목록」에
      들어 있는지로 정해진다. 낱말만 세면 옮기는 경로가 바뀔 때 멀쩡한 코드를
      「끊겼다」고 말한다 — 실제로 그렇게 빨간불이 났다.
    """
    from lemouton.send import as_draft as AD
    assert 'minor_purchasable' in AD._POLICY_FIELDS, \
        '초안이 정책의 미성년자 설정을 안 옮겨 담는다 — 늘 기본값(전연령)이 나간다'
    assert 'policy_fields_from' in inspect.getsource(AD.upsert), \
        '옮겨 담는 함수를 초안 만들기가 부르지 않는다'


# ── ③ 초안 → 마켓 ──────────────────────────────────────────────────────
def test_쿠팡이_상수_대신_초안을_읽는다():
    from lemouton.registration import compile_coupang as C
    src = inspect.getsource(C)
    assert "'adultOnly': 'EVERYONE'" not in src, \
        "쿠팡에 adultOnly='EVERYONE' 이 아직 박혀 있다 — 고르신 값이 무시된다"
    assert 'minor_purchasable' in src, '쿠팡이 초안의 미성년자 값을 안 읽는다'


def test_스스도_초안을_읽는다():
    from lemouton.registration import compile_smartstore as S
    assert 'minor_purchasable' in inspect.getsource(S)


# ── ④ 아직 안 되는 곳을 「된다」고 말하지 않는다 ────────────────────────
def test_어디로_나가고_어디가_아직인지_둘_다_말한다():
    """🔴 [2026-08-13 갱신] 그 사이 main 이 11번가·옥션·G마켓까지 이었다.

    상태가 「나감」이 된 것은 맞다. 다만 **아직 안 되는 곳**도 같이 말해야 한다 —
    「나감」 한 마디로 뭉뚱그리면 롯데온이 조용히 묻힌다. 이 저장소가 반복해서
    당한 형태다(배선이 이어지면 그걸 말하는 표도 같이 낡는다).
    """
    from lemouton.policy.required import WIRED, wiring_of
    state, note = wiring_of('listing')
    assert state == WIRED, '미성년자 구매는 이제 실제로 나간다'
    assert '미성년자' in note, '무엇이 나가는지 안 적혀 있다'
    # 🔴 아직 확인 못 한 곳(롯데온)이 안 적혀 있으면 「전부 된다」로 읽힌다
    assert '롯데온' in note, '아직 확인 못 한 마켓이 안 적혀 있다'

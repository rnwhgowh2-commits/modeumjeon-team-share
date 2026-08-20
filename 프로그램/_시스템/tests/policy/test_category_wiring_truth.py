# -*- coding: utf-8 -*-
"""카테고리는 **나간다** — 「저장만 됩니다」는 거짓이었다.

🔴 무엇이 잘못이었나 (2026-08-13 실측) — 개발 체크리스트가 「[필수] 카테고리」를
  6마켓 **전부 🟡저장만** 으로 보여 주고 있었다. 그런데 실제로는:

    · `registration/service.register_draft(category_code=...)` 가 받아
    · `compile_smartstore`  → `leafCategoryId`
    · `compile_coupang`     → `displayCategoryCode`
    · `compile_eleven11`    → `dispCtgrNo`
    · `compile_auction_gmarket` → `cat_code` + `site_cat_code`
    · `compile_lotteon`     → `template_spd_no` (본보기 상품에서 카테고리를 물려받음)
  로 **payload 에 담겨 나간다.** 게다가 `require_category` 가 값이 없으면
  등록을 아예 **막는다** — 안 나갈 수가 없다.

  원인은 판정이 아니라 **기본값**이었다. `wiring_of()` 는 `WIRING` 에 없는 항목을
  전부 「저장만」으로 돌려준다. 카테고리는 정책이 코드를 들고 있는 게 아니라
  (정책엔 `auto_map`·`on_fail` 두 스위치뿐) 등록 때 고르는 값이라 표에 없었고,
  그래서 **판단한 적도 없는데 「저장만」이라고 단정**하고 있었다.

🔴 왜 위험한가 — 사장님이 「어차피 안 나가는구나」로 읽으신다. 실제로는 카테고리가
  없으면 등록이 통째로 막히는, 가장 중요한 칸이다. 반대 방향으로도 위험하다 —
  이 저장소는 이미 「저장만 됩니다」가 거짓이라 상품명·상세가 빈 채 나갈 뻔했다.
"""
import inspect

import pytest

from lemouton.policy.required import WIRED, wiring_of

#: 마켓별 (compile 함수, payload 에 실제로 들어가는 키)
#:   🔴 목록을 손으로 적지 않고 **함수를 실제로 뜯어본다** — 손으로 적으면 낡는다.
COMPILERS = [
    ('smartstore', 'lemouton.registration.compile_smartstore', 'compile_smartstore'),
    ('coupang', 'lemouton.registration.compile_coupang', 'compile_coupang'),
    ('eleven11', 'lemouton.registration.compile_more', 'compile_eleven11'),
    ('esm', 'lemouton.registration.compile_more', 'compile_auction_gmarket'),
    ('lotteon', 'lemouton.registration.compile_more', 'compile_lotteon'),
]


def _src(mod_name, fn_name):
    import importlib
    return inspect.getsource(getattr(importlib.import_module(mod_name), fn_name))


@pytest.mark.parametrize('market,mod,fn', COMPILERS)
def test_모든_마켓_조립기가_카테고리를_받는다(market, mod, fn):
    import importlib
    f = getattr(importlib.import_module(mod), fn)
    assert 'category_code' in inspect.signature(f).parameters, \
        f'{market}: 조립기가 카테고리를 아예 안 받는다'


@pytest.mark.parametrize('market,mod,fn', COMPILERS)
def test_카테고리가_없으면_등록을_막는다(market, mod, fn):
    """🔴 막는다는 것은 **반드시 나간다**는 뜻이다 — 빈 채로 통과할 길이 없다."""
    assert 'require_category' in _src(mod, fn), \
        f'{market}: 카테고리 없이도 조립이 통과한다'


def test_체크리스트가_카테고리를_나감으로_말한다():
    """🔴 이게 이 시험의 본론 — 표가 거짓말을 하고 있었다.

    🔴 **키가 둘인 이유** — 「정책 항목 category」와 「마켓 칸 카테고리」는 다르다.
      정책이 든 건 스위치 둘(자동 매핑·실패했을 때)뿐이고 초안이 안 옮겨 담는다.
      마켓에 나가는 **값**은 등록 때 반드시 실린다. 하나로 뭉개면 한쪽이 거짓말이
      된다(실제로 뭉갰다가 CI 가 8건으로 잡아 줬다).
    """
    state, note = wiring_of('category_field')
    assert state == WIRED, f'카테고리 칸이 아직 「{state}」로 잡힌다 — 실제로는 나간다'
    assert note.strip(), '왜 나가는지 설명이 없다'


def test_정책_항목은_여전히_저장만이다():
    """🔴 정책의 카테고리 **스위치**는 초안이 안 옮겨 담는다 — 그건 저장만이 맞다."""
    from lemouton.policy.required import STORED_ONLY
    state, note = wiring_of('category')
    assert state == STORED_ONLY
    assert '등록할 때 반드시 나갑니다' in note or '카테고리 값 자체는' in note, \
        '정책 스위치만 저장만이라는 사실이 안 적혀 있어, 값도 안 나가는 줄 읽힌다'


def test_체크리스트_열이_갈라진_키를_가리킨다():
    """🔴 열이 옛 키를 가리키면 표는 그대로 거짓말한다 — 정의 파일까지 확인한다."""
    import io
    import json
    from lemouton.policy import checklist as C

    cols = json.load(io.open(f'{C._DATA}/dev_checklist_columns.json', encoding='utf-8'))
    col4 = next(c for c in cols['columns'] if c['col'] == 4)
    assert col4.get('wiring_item') == 'category_field', \
        f"카테고리 열이 아직 「{col4.get('wiring_item') or col4.get('item')}」 를 본다"


def test_설명이_롯데온의_다른_방식을_말한다():
    """🔴 롯데온만 카테고리 번호가 아니라 **본보기 상품번호**를 보낸다.

    한 문장으로 뭉뚱그리면 사장님이 롯데온 칸에 카테고리 번호를 넣으신다.
    """
    _, note = wiring_of('category_field')
    assert '롯데온' in note, '롯데온이 다르다는 말이 없다'
    assert '본보기' in note or 'spdNo' in note or '기존 상품' in note, \
        '롯데온에 무엇을 넣어야 하는지 안 적혀 있다'


def test_정책_두_스위치도_읽힌다():
    """정책의 「자동 매핑」·「실패했을 때」가 실제로 판정에 쓰이는지."""
    from lemouton.registration import process_apply
    src = inspect.getsource(process_apply)
    assert "'auto_map'" in src or '"auto_map"' in src, '자동 매핑 스위치를 아무도 안 읽는다'
    assert "'on_fail'" in src or '"on_fail"' in src, '실패 처리 스위치를 아무도 안 읽는다'


def test_모르는_항목은_여전히_보수적으로_저장만():
    """🔴 카테고리를 고치면서 기본값까지 낙관적으로 바꾸면 안 된다."""
    from lemouton.policy.required import STORED_ONLY
    state, _ = wiring_of('아무도모르는항목키')
    assert state == STORED_ONLY

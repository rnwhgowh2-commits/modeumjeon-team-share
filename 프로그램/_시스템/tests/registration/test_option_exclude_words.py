# -*- coding: utf-8 -*-
"""「뺄 옵션」이 **실제로 걸러야 한다**.

━━ 왜 이 시험이 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`SearchFilter.option_exclude_words` 는 저장되고 화면에도 보였지만 **아무 데서도
읽히지 않았다**(2026-08-08 확인: 쓰는 곳이 저장·표시 3곳뿐). 사장님은 「샘플」이라
적어 두고 걸러진 줄 알지만 그대로 다 들어온다 — 이 저장소가 부르는 조용한 실패다.

━━ 무엇을 거르나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
화면 라벨이 「뺄 옵션」이므로 **옵션 이름**(색상·사이즈 글자) 기준이다.
상품 이름은 안 본다 — 그건 다른 일이고, 말없이 겸하면 사장님이 왜 빠졌는지 모른다.

━━ 🔴 전부 걸리면 초안을 만들지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
옵션이 하나도 안 남은 채 초안이 생기면 **옵션 없는 단품**으로 굳어 재고·가격이
통째로 틀린 상품이 조용히 마켓까지 간다. 안 만들고 사유를 말한다.
"""
import pytest

from lemouton.registration.draft_from_crawl import (
    drop_excluded_options, parse_exclude_words)


# ── 말 쪼개기 ────────────────────────────────────────────────────────
#   🔴 화면은 한 줄짜리 `<input>` 이라 **줄바꿈을 넣을 수가 없다.**
#     줄바꿈만 받으면 여러 개를 적을 방법이 아예 없다 — 쉼표도 받는다.

def test_쉼표와_줄바꿈_둘_다_구분자():
    assert parse_exclude_words('샘플, 중고\n리퍼') == ['샘플', '중고', '리퍼']


def test_빈칸과_빈_값은_말로_안_친다():
    assert parse_exclude_words('  샘플 , , \n\n ') == ['샘플']
    assert parse_exclude_words('') == []
    assert parse_exclude_words(None) == []


# ── 거르기 ───────────────────────────────────────────────────────────

def _opt(color='', size=''):
    return {'color': color, 'size': size, 'stock': 3, 'extra_price': 0, 'sku': ''}


def test_그_말이_든_옵션은_빠진다():
    opts = [_opt('블랙', '270'), _opt('블랙', '샘플용'), _opt('화이트', '280')]

    kept, dropped = drop_excluded_options(opts, ['샘플'])

    assert [o['size'] for o in kept] == ['270', '280'], kept
    assert dropped == 1


def test_색상칸에_있어도_걸린다():
    """말이 어느 칸에 있든 「그 옵션」이다."""
    kept, dropped = drop_excluded_options([_opt('샘플블랙', 'M'), _opt('블랙', 'M')],
                                          ['샘플'])

    assert dropped == 1 and len(kept) == 1, (kept, dropped)


def test_대소문자와_앞뒤공백은_무시한다():
    kept, dropped = drop_excluded_options([_opt('BLACK SAMPLE', 'M')], [' sample '])

    assert dropped == 1 and kept == [], (kept, dropped)


def test_말이_없으면_하나도_안_거른다():
    opts = [_opt('블랙', '270'), _opt('화이트', '280')]

    kept, dropped = drop_excluded_options(opts, [])

    assert kept == opts and dropped == 0


def test_한_글자도_안_지운다_원본은_그대로():
    """받은 목록을 제자리에서 고치면 부르는 쪽이 모르게 값이 바뀐다."""
    opts = [_opt('블랙', '샘플')]

    drop_excluded_options(opts, ['샘플'])

    assert len(opts) == 1, opts


# ── 🔴 전부 걸리는 경우 ──────────────────────────────────────────────

def test_전부_걸리면_빈_목록이_나온다():
    """부르는 쪽이 이 경우를 알아보고 초안을 안 만들 수 있어야 한다."""
    kept, dropped = drop_excluded_options([_opt('블랙', '샘플'), _opt('흰', '샘플2')],
                                          ['샘플'])

    assert kept == [] and dropped == 2, (kept, dropped)

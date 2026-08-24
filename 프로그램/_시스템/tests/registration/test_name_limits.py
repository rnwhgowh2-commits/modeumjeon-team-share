# -*- coding: utf-8 -*-
"""상품명 길이 — 바이트 상한 + 쿠팡 글자수 예외 (2026-08-24 사장님 확정).

■ 왜 이 시험이 있나
  마켓 문서는 「100자」처럼 글자수로 적어 두고도 실제 등록기는 **바이트**로 자른다.
  한글은 UTF-8 로 3바이트라, 「100자」를 믿고 보내면 300바이트가 되어 거부당한다.
  삼바(대조군)는 11번가 99바이트·롯데ON 149바이트로 자르고 매일 등록에 성공한다.

■ 절대 지켜야 하는 것
  ① 자른 결과가 **깨진 글자로 끝나면 안 된다** — 그대로 마켓에 올라간다.
  ② 한도를 **모르는** 마켓은 자르지 않는다 — 잘못 자르면 잘린 채 팔린다.
"""
import pytest

from lemouton.registration.market_limits import (
    NAME_MAX_BYTES, fit_name, name_limit_for, name_max_len,
)

_LONG = '르무통 스니커즈 정품 새상품 '  * 20   # 한글 위주 — 바이트가 글자수의 ~2.6배


def _b(s):
    return len(s.encode('utf-8'))


# ── 자르는 마켓 ──────────────────────────────────────────────────────────
def test_쿠팡은_글자수_100자로_자른다():
    got = fit_name('coupang', _LONG)
    assert len(got) == 100


def test_11번가는_99바이트_이하로_자른다():
    got = fit_name('eleven11', _LONG)
    assert _b(got) <= 99


def test_롯데온은_149바이트_이하로_자른다():
    got = fit_name('lotteon', _LONG)
    assert _b(got) <= 149


@pytest.mark.parametrize('market', ['eleven11', 'lotteon'])
def test_자른_결과가_깨진_글자로_끝나지_않는다(market):
    """🔴 바이트로 자르면 한글 중간이 쪼개진다 — 깨진 글자가 마켓에 올라간다."""
    got = fit_name(market, _LONG)
    assert got.encode('utf-8').decode('utf-8') == got     # 왕복이 되면 안 깨진 것
    assert '\ufffd' not in got                            # 대체문자도 없어야 한다


def test_11번가는_글자수와_바이트를_둘_다_본다():
    """둘 다 있으면 먼저 걸리는 쪽 — 한글에선 바이트가 먼저 걸린다."""
    lim = name_limit_for('eleven11')
    assert lim['chars'] == 100 and lim['bytes'] == 99
    got = fit_name('eleven11', _LONG)
    assert len(got) < 100          # 글자수보다 바이트가 먼저 걸렸다
    assert _b(got) <= 99


# ── 안 자르는 마켓 (확인 불가) ────────────────────────────────────────────
@pytest.mark.parametrize('market', ['smartstore', 'auction', 'gmarket'])
def test_한도를_모르는_마켓은_안_자른다(market):
    """🔴 「모른다」를 「0」이나 기본값으로 읽어 자르면 잘린 채 팔린다."""
    assert fit_name(market, _LONG) == _LONG
    assert name_limit_for(market) == {'chars': None, 'bytes': None}


# ── 손대면 안 되는 경우 ──────────────────────────────────────────────────
def test_한도_안에_들어가면_손대지_않는다():
    short = '르무통 스니커즈'
    for m in ('coupang', 'eleven11', 'lotteon', 'smartstore'):
        assert fit_name(m, short) == short


@pytest.mark.parametrize('value', ['', None])
def test_빈_값은_그대로_돌려준다(value):
    assert fit_name('coupang', value) == value


def test_모르는_마켓이름도_안전하다():
    assert fit_name('없는마켓', _LONG) == _LONG


# ── 기존 함수는 그대로 (회귀) ────────────────────────────────────────────
def test_기존_함수를_안_깼다():
    """name_max_len 을 쓰는 곳이 5군데 있다 — 그대로 돌아야 한다."""
    assert name_max_len('coupang') == 100
    assert name_max_len('eleven11') == 100
    assert name_max_len('smartstore') is None


def test_바이트_상한은_실측된_두_마켓만():
    """🔴 없는 값을 지어내지 않는다 — 확인된 것만 넣는다."""
    assert set(NAME_MAX_BYTES) == {'eleven11', 'lotteon'}
    assert NAME_MAX_BYTES['eleven11'] == 99
    assert NAME_MAX_BYTES['lotteon'] == 149

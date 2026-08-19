# -*- coding: utf-8 -*-
"""자체 바코드 만들기 — 숫자 13자리, 브랜드 공식 바코드와 절대 안 겹치게.

🔴 [2026-08-13 사장님 확정]
   · 브랜드 공식 바코드가 있으면 **그걸 그대로** 쓴다(대부분 있다).
   · 없을 때만 우리가 만들고, **자체 생성임이 구분돼야** 한다.
   · **숫자만** — 영문은 안 들어간다.

🔴 왜 `2` 로 시작하나 — 쿠팡이 「임의로 생성한 숫자」를 GTIN 으로 쓰는 것을 금지한다
   (2026-05-27 공지 · API 등록 상품은 2026-08-01 시행). 어기면 등록·노출 제한이다.
   그래서 우리 값은 **국제표준이 매장 내부용으로 비워 둔 200~299 대역**을 쓰고,
   그 대역이라는 사실만으로 「이건 공식 바코드가 아니다」를 코드가 알아볼 수 있게 한다.
   한국 정식 상품은 880 으로 시작하므로 겹칠 수가 없다.
"""
import pytest

from lemouton.inventory import barcode as BC


# ── 만들기 ────────────────────────────────────────────────────────────────

def test_숫자_13자리다():
    got = BC.make_internal(1)
    assert got.isdigit(), f'숫자가 아닌 글자가 있다: {got}'
    assert len(got) == 13, got


def test_사내용_대역으로_시작한다():
    """🔴 880(한국 정식)으로 시작하면 진짜 상품 바코드와 겹친다."""
    for n in (1, 7, 12345, 999999999):
        assert BC.make_internal(n).startswith('2'), n


def test_체크디지트가_맞다():
    """스캐너가 안 읽으면 라벨이 무용지물이다 — 표준 검사식으로 확인."""
    for n in (1, 2, 3, 87, 654321):
        got = BC.make_internal(n)
        odd = sum(int(c) for c in got[0:12:2])
        even = sum(int(c) for c in got[1:12:2])
        assert (odd + even * 3 + int(got[12])) % 10 == 0, got


def test_번호가_다르면_바코드도_다르다():
    got = [BC.make_internal(n) for n in range(1, 200)]
    assert len(set(got)) == len(got), '겹치는 값이 나왔다'


def test_같은_번호는_늘_같은_바코드():
    """다시 만들 때마다 달라지면 라벨과 화면이 어긋난다."""
    assert BC.make_internal(42) == BC.make_internal(42)


def test_너무_큰_번호는_지어내지_않고_거절한다():
    with pytest.raises(ValueError):
        BC.make_internal(10 ** 12)
    with pytest.raises(ValueError):
        BC.make_internal(0)


# ── 공식인지 우리 것인지 가르기 ────────────────────────────────────────────

def test_우리가_만든_것을_알아본다():
    assert BC.is_internal(BC.make_internal(5)) is True


def test_브랜드_공식_바코드는_우리_것이_아니다():
    for real in ('8801234567890', '4901234567894', '0194253941234'):
        assert BC.is_internal(real) is False, real


def test_빈값이나_이상한_값에_안_터진다():
    """🔴 화면이 이 함수를 매 행 부른다 — 하나라도 터지면 표가 통째로 안 뜬다."""
    for junk in ('', None, '   ', 'ABC', '12', '2' * 30, 12345):
        assert BC.is_internal(junk) is False


# ── 어느 값을 마켓에 보낼까 ────────────────────────────────────────────────

def test_쿠팡엔_공식만_보낸다():
    """🔴 쿠팡 공지가 임의 생성 번호를 금지한다 — 보내면 노출 제한."""
    assert BC.for_market('8801234567890', 'coupang') == '8801234567890'
    assert BC.for_market(BC.make_internal(3), 'coupang') == ''
    assert BC.for_market('', 'coupang') == ''


def test_자체_생성은_어느_마켓에도_안_나간다():
    """🔴 [2026-08-13 사장님 확정] 라벨·재고용이지 마켓에 보낼 값이 아니다.

    스스는 칸 이름이 「판매자 바코드」라 기술적으로는 되지만 「지금 불필요」로 정하셨다.
    판단이 `_SELF_OK` 한 곳에 모여 있어, 필요해지면 한 줄만 넣으면 된다.
    """
    mine = BC.make_internal(3)
    for mk in ('coupang', 'smartstore', 'auction', 'gmarket', 'eleven11', 'lotteon'):
        assert BC.for_market(mine, mk) == '', mk


def test_공식_바코드는_확인된_마켓으로_나간다():
    assert BC.for_market('8801234567890', 'smartstore') == '8801234567890'
    assert BC.for_market('8801234567890', 'coupang') == '8801234567890'


def test_모르는_마켓은_보내지_않는다():
    """🔴 「모른다」를 「보내도 된다」로 읽으면 안 된다."""
    assert BC.for_market('8801234567890', 'lotteon') == ''
    assert BC.for_market('8801234567890', '') == ''

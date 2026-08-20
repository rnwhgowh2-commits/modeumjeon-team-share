# -*- coding: utf-8 -*-
"""롯데아이몰은 **한 쪽씩** 넘어가야 한다 — 「다음」은 열 쪽씩 뛴다.

🔴🔴 왜 (2026-08-13 라이브 실측)
   `a.next.ico`(「다음」)를 한 번 눌렀더니 **1쪽 → 11쪽**으로 뛰었다.
   즉 우리는 60번을 눌러도 1·11·21… 쪽만 걷고 **아홉 쪽씩 통째로 건너뛰고** 있었다.
   (60번 눌러 705개 — 60쪽×60개=3,600 이어야 할 자리다.)

   **못 걷은 만큼 팔 상품이 줄어든다.**

★ 처방 — 「지금 쪽(`a.on`) 바로 다음 것」을 누른다. 12→13 으로 한 쪽씩 정확히 넘어간다(실측).
  묶음 끝(20쪽)에서는 그 다음 형제가 「다음」 단추라 21쪽으로 이어진다 — 한 벌로 끝난다.

★★ 배운 것 — **「다음」이라고 적혀 있다고 「다음 쪽」이 아니다.**
   단추 글자를 믿지 말고 **눌러서 쪽 번호가 몇으로 바뀌는지** 봐야 한다.
"""
from __future__ import annotations

from lemouton.sources import listing_discover as LD


def test_아이몰은_지금쪽_다음_것을_누른다():
    got = LD.dom_rule_for('lotteimall')['more_sel']
    assert got == '.wrap_page a.on + a', (
        f'아이몰 「다음」 선택자가 {got!r} 입니다. '
        '`a.next.ico` 는 열 쪽씩 뛰는 단추라 아홉 쪽을 건너뜁니다.'
    )


def test_열쪽씩_뛰는_단추를_안_쓴다():
    """🔴 되돌아가면 다시 아홉 쪽을 잃는다."""
    assert LD._MORE_SELECT.get('lotteimall') != 'a.next.ico'


def test_롯데온은_그대로다():
    """롯데온의 「다음」은 진짜 다음 쪽이다(실측: 35쪽까지 2,034개 수집).

    같이 바꾸면 멀쩡한 것을 망가뜨린다 — **소싱처마다 따로 재야 한다.**
    """
    assert LD.dom_rule_for('lotteon')['more_sel'] == 'a.srchPaginationNext'


def test_단추로_넘기는_곳은_둘뿐이다():
    """추측으로 늘리면 「더 있음」이 늘 켜지거나 늘 꺼져 둘 다 거짓말이 된다."""
    assert set(LD._MORE_SELECT) == {'lotteon', 'lotteimall'}, sorted(LD._MORE_SELECT)


def test_아이몰_상품번호_규칙은_그대로다():
    """쪽 넘김만 고친다 — 상품을 고르는 규칙은 건드리지 않는다."""
    rule = LD.dom_rule_for('lotteimall')
    assert rule['sel'] == '[data-goods-no]'
    assert rule['attr'] == 'data-goods-no'
    assert LD.product_url_for('123', source_key='lotteimall').endswith('goods_no=123')

# -*- coding: utf-8 -*-
"""옥션·G마켓 옵션 부착 실패 — **어느 카테고리에서 났는지**를 남긴다.

━━ 왜 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
옵션 부착 실패는 이미 잘 다루고 있다(`send_more.py` — 실패하면 상품을 즉시 판매중지로
회수하고 `PartialRegisterError` 로 표면화). 그런데 **그 실패가 어느 카테고리에서
났는지는 아무도 기억하지 않는다.** 그래서 같은 카테고리에 다음 상품을 또 올리면
또 실패하고, 또 회수하고, 그 사이 「옵션 없는 단일상품이 판매중」인 창이 또 열린다.
대량등록이면 이 일이 수십·수백 번 반복된다.

🔴 우리는 「어느 카테고리가 옵션을 못 받는지」를 **알 방법이 없다** — ESM 카테고리 API
  응답에 그 칸이 없다(catCode·catName·isLeaf 뿐). 더망고도 API 가 아니라 사람이 넣는
  목록(「단일상품등록설정」)이었다. 그러니 목록을 지어내지 않는다(실측값만 적용 원칙).
  대신 **실패한 카테고리를 실측으로 남긴다** — 그게 나중에 만들 목록의 씨앗이다.
"""
from lemouton.registration.send_more import _esm_option_fail_message


def test_실패_문구에_카테고리_코드가_들어간다():
    msg = _esm_option_fail_message(
        market='auction', goods_no='A12345',
        cat_code='00120005002000000000', site_cat_code='37500700',
        err='400 recommended-options rejected',
        rollback='상품은 판매중지로 내려두었습니다')

    assert '00120005002000000000' in msg, msg
    assert '37500700' in msg, msg


def test_상품번호와_되돌린_결과가_그대로_남는다():
    """상품번호는 셀러센터에서 찾는 유일한 열쇠다 — 빠지면 미아가 된다."""
    msg = _esm_option_fail_message(
        market='gmarket', goods_no='G999', cat_code='C1', site_cat_code='S1',
        err='boom', rollback='⚠️판매중지 실패 — 셀러센터에서 직접 내려주세요')

    assert 'G999' in msg
    assert '판매중지 실패' in msg
    assert 'boom' in msg


def test_이_카테고리가_옵션을_못_받을_수_있다고_알려준다():
    """다음 등록 때 사람이 판단할 수 있어야 한다 — 사유만 있고 힌트가 없으면 또 반복한다."""
    msg = _esm_option_fail_message(
        market='auction', goods_no='A1', cat_code='C1', site_cat_code='S1',
        err='x', rollback='y')

    assert '카테고리' in msg
    assert '옵션' in msg

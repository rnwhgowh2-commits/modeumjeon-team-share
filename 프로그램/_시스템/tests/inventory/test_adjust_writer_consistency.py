# -*- coding: utf-8 -*-
"""조정(adjust)을 **저장하는 세 곳**이 서로, 그리고 읽는 쪽과 같은 뜻인가.

🔴 왜 이 시험이 있나 — 2026-08-13 하루에 이 규약이 **세 번** 뒤집혔다.
   재고 4 → 6 → 4. 전부 **에러 없이 숫자만 틀리는** 사고였고, 매번 원인이 같았다:
   **쓰는 곳 세 개를 다 안 보고** 한 곳(문서 또는 시험)만 보고 맞췄다.

   쓰는 곳(세 곳 모두 같아야 한다)
     · lemouton/inventory/inbound.create_adjustment   (데스크탑 · ADR-002)
     · webapp/routes/api_inventory_link               (연동 화면)
     · webapp/routes/mobile.api_action                (모바일 스캔)
   읽는 쪽 정본
     · shared.inventory_stock.fold_tx_rows

🔴 이 시험은 「어느 쪽이 옳은가」를 정하지 않는다. **다 같은가**만 본다.
   그래서 규약을 절대값에서 델타로 (또는 그 반대로) 바꾸더라도, 세 곳을 같이 바꾸면
   그대로 통과한다. 한 곳만 바꾸면 반드시 깨진다 — 그게 이 시험의 존재 이유다.
"""
import inspect

import pytest

from shared.inventory_stock import fold_tx_rows


def _stored_for(counted: int, current: int) -> int:
    """읽는 쪽 정본이 뜻하는 「저장해야 할 값」.

    실사 결과가 `counted` 이고 지금 재고가 `current` 일 때, 원장에 무엇을 남겨야
    `fold_tx_rows` 가 `counted` 를 돌려주는가. 절대값 규약이면 counted, 델타 규약이면
    counted−current 가 나온다 — **규칙을 여기서 정하지 않고 정본에게 물어본다.**
    """
    # 🔴 조정 행 **하나만**으로는 두 규약이 같은 값을 낸다(절대값 999 · 델타 0+999=999).
    #   그래서 옛 판별은 델타를 절대값으로 오인해, 정본과 쓰는 곳이 다 델타로 맞아
    #   있는데도 엉뚱한 3건을 실패시켰다 — 시험이 스스로를 속인 것이다.
    #   앞에 입고 1 을 깔면 갈린다: 절대값 999 · 델타 1000.
    if fold_tx_rows([("in", 1), ("adjust", 999)]) == 999:
        return counted                      # 절대값 규약
    return counted - current                # 델타 규약


# 입고 2 · 출고 1 → 현재 1. 실사 5.
BASE = [("in", 2), ("out", 1)]
CURRENT, COUNTED = 1, 5


def test_읽는_쪽_정본이_스스로_모순이_없다():
    """정본이 뜻하는 저장값을 다시 접으면 실사한 수가 나와야 한다."""
    rows = BASE + [("adjust", _stored_for(COUNTED, CURRENT))]
    assert fold_tx_rows(rows) == COUNTED


def test_데스크탑_create_adjustment_가_정본과_같은_뜻으로_저장한다():
    """`inbound.create_adjustment(new_qty=…)` 가 원장에 넣는 qty."""
    from lemouton.inventory import inbound
    src = inspect.getsource(inbound.create_adjustment)
    want = _stored_for(COUNTED, CURRENT)
    if want == COUNTED:
        assert "qty=new_qty" in src, (
            "정본은 조정을 **절대값**으로 읽는데 데스크탑은 그 값을 안 넣는다: " + src)
    else:
        assert "qty=new_qty" not in src, (
            "정본은 조정을 **델타**로 읽는데 데스크탑은 절대값을 넣는다 — "
            "재고가 조용히 틀어진다: " + src)


@pytest.mark.parametrize("path,marker_abs,marker_delta", [
    ("webapp/routes/api_inventory_link.py", "qty=qty_after", "qty=diff"),
    ("webapp/routes/mobile.py", "tx_qty = int(qty)  ", "tx_qty = int(qty) - current"),
])
def test_나머지_쓰는_곳도_같은_뜻이다(path, marker_abs, marker_delta):
    """화면·모바일이 원장에 넣는 값이 정본과 같은 뜻인가.

    🔴 원문을 읽어서 본다 — 이 두 곳은 DB·요청 없이는 못 돌려서, 「무엇을 저장하는지」를
      코드에서 직접 확인하는 것이 가장 덜 깨지는 방법이다.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / path).read_text(encoding="utf-8")
    want_abs = _stored_for(COUNTED, CURRENT) == COUNTED
    if want_abs:
        assert marker_abs in src, (
            f"정본은 조정을 **절대값**으로 읽는데 {path} 는 그렇게 저장하지 않는다")
        assert marker_delta not in src, (
            f"{path} 가 아직 차이값을 저장한다 — 정본(절대값)과 어긋난다")
    else:
        assert marker_delta in src, (
            f"정본은 조정을 **델타**로 읽는데 {path} 는 그렇게 저장하지 않는다")


def test_모바일_응답은_변화량을_보여준다():
    """저장값이 절대값이어도 사람에겐 「몇 개 늘었다」를 보여줘야 한다."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "webapp/routes/mobile.py").read_text(encoding="utf-8")
    if _stored_for(COUNTED, CURRENT) == COUNTED:
        assert "applied_qty=(delta if action ==" in src, (
            "절대값을 저장하면 응답의 applied_qty 는 delta 로 갈라 줘야 한다 — "
            "안 그러면 「5개 늘었다」로 보인다(실제로는 4개)")

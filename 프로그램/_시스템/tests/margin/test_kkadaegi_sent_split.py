# -*- coding: utf-8 -*-
"""「까대기 송장번호 전송 완료」 카드 안 세 칸 — 겹치지 않고 합이 카드 숫자와 같아야 한다.

사장님 확정(2026-07-23 V1): 구매확정/배송완료 → 송장 입력 완료 → 송장 미입력 순서.
칸이 겹치면 합이 카드 숫자를 넘어 '숫자가 안 맞는 화면'이 된다.
"""
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "kkadaegi_sent_split_harness.js")


def _node():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node 없음")
    return exe


def test_three_cells_are_exclusive_and_sum_to_total():
    out = subprocess.run([_node(), HARNESS], cwd=os.path.dirname(os.path.dirname(HERE)),
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, f"harness 실패:\n{out.stdout}\n{out.stderr}"
    txt = out.stdout
    # ★2026-07-24: '배송중'·'발송완료'도 파란 칸(사장님 지시) → done 4→6, sent 2→1, none 2→1
    assert "배송중/구매확정   : 6" in txt, txt
    assert "송장 입력 완료   : 1" in txt, txt      # 취소건만(배송중은 파란 칸으로)
    assert "송장 미입력      : 1" in txt, txt
    assert "세 칸 합 = 전체  : OK" in txt, txt
    assert "배송중/구매확정 | 송장 입력 완료 | 송장 미입력" in txt, txt

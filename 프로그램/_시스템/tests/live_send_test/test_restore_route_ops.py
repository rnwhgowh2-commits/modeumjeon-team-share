# -*- coding: utf-8 -*-
"""손복구 경로가 **어느 어댑터를 집는지** — 두 구멍을 막는다(2026-08-12 발견).

① 11번가가 `else` 로 떨어져 **ESM 어댑터**를 쓰고 있었다.
   ESM 어댑터는 `_cfg['paths']` 를 요구해서 11번가 클라이언트로는 바로 죽는다.
   (`roundtrip-probe` 에서 이미 한 번 밟은 것과 **같은 부류**다 — 마켓을 늘리면서
    분기 하나를 빼먹으면 조용히 남의 어댑터로 간다.)

② ESM 손복구가 `allow_name=False` 라 **상품명을 못 되돌린다**.
   시험할 때 상품명을 끄는 것(재심사 회피)과, 되돌릴 때 켜는 것(표식 제거)은
   다른 문제다. 막아 두면 " (시험중)" 이 붙은 채 영영 남는다.
"""
from __future__ import annotations

import inspect

from webapp.routes import live_send_test as R


def _restore_source() -> str:
    return inspect.getsource(R.api_roundtrip_restore)


def test_손복구가_11번가_어댑터를_따로_집는다():
    src = _restore_source()

    assert "make_eleven11_ops" in src, (
        "11번가가 else 로 떨어져 ESM 어댑터를 쓴다 — 클라이언트가 달라 바로 죽는다")


def test_손복구_ESM은_상품명을_되돌릴_수_있다():
    src = _restore_source()
    esm_part = src[src.index("make_esm_ops"):]

    assert "allow_name=True" in esm_part, (
        "손복구인데 상품명 축이 막혀 있다 — 시험 표식이 영영 남는다")


def test_손복구가_모든_전송마켓을_다룬다():
    """마켓을 늘릴 때 여기 분기를 빼먹으면 남의 어댑터로 조용히 간다."""
    src = _restore_source()

    for mk in R.ROUNDTRIP_MARKETS:
        assert f'"{mk}"' in src or mk in ("auction", "gmarket"), \
            f"{mk} 이 손복구 분기에 없다"

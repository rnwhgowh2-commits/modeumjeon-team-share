# -*- coding: utf-8 -*-
"""저널로 되돌리기 — 원복이 실패했을 때의 **손복구 경로**.

🔴 [2026-08-07 라이브] 옥션 왕복에서 실제로 필요해졌다.
   첫 전송은 통했는데(가격·상품명·상세 바뀜) 원복이 마켓 제재로 거부됐다:
     resultCode=1000 [지식재산권침해 우려(1250)]의 사유로 사이트 내 상품 노출이 제한 되었습니다.

   마켓에 시험값이 남았고, **왕복을 다시 부르면 지금 값(시험값)을 원래값으로 삼아
   더 나빠진다** — 되돌리기 전용 경로가 반드시 따로 있어야 한다.

저널에 before 를 먼저 남기는 이유가 바로 이것이다(설계 §4 규칙 2).

원칙
    · 저널이 없거나 before 가 비면 **멈춘다**(지어내지 않는다).
    · 못 읽었던 축(missing)은 원래값을 모르므로 **보내지 않는다**.
    · 보냈다고 끝이 아니라 되읽어 원래값과 같은지 확인한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lemouton.uploader.roundtrip.snapshot import AXES


class RestoreError(RuntimeError):
    """되돌릴 근거가 없다. 조용한 폴백 금지 — 지어낸 값을 보내지 않는다."""


@dataclass
class RestoreReport:
    ok: bool = False
    error: str | None = None
    sent: dict = field(default_factory=dict)
    verified: bool | None = None
    mismatched: tuple = ()
    journal_path: str = ""
    market: str = ""
    product_id: str = ""


def _value_of(before: dict, axis: str):
    if axis == "stock":
        opts = before.get("options") or []
        if not opts:
            return None
        first = opts[0]
        return first[1] if isinstance(first, (list, tuple)) and len(first) > 1 else None
    return before.get(axis)


def restore_from_journal(journal_path, *, apply_fn, snapshot_fn=None,
                         axes=AXES) -> RestoreReport:
    """저널 파일의 before 값으로 마켓을 되돌린다.

    Args:
        journal_path: RoundtripJournal 이 남긴 파일 경로.
        apply_fn: (changes: dict) -> None. 마켓에 쓰기.
        snapshot_fn: () -> Snapshot. 주면 되돌린 뒤 확인까지 한다.
    """
    p = Path(journal_path)
    if not p.exists():
        raise RestoreError(f"저널 파일이 없습니다: {p} — 되돌릴 근거가 없어 멈춥니다.")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise RestoreError(f"저널을 읽지 못했습니다: {p} ({e})") from e

    before = (data or {}).get("before") or {}
    if not before:
        raise RestoreError(f"저널에 before 값이 없습니다: {p} — 지어내지 않고 멈춥니다.")

    report = RestoreReport(journal_path=str(p),
                           market=str(data.get("market") or before.get("market") or ""),
                           product_id=str(data.get("product_id")
                                          or before.get("product_id") or ""))

    missing = set(before.get("missing") or ())
    changes = {}
    for axis in axes:
        if axis in missing:
            continue          # 못 읽었던 축 — 원래값을 모른다. 보내지 않는다.
        v = _value_of(before, axis)
        if v is None:
            continue
        changes[axis] = tuple(v) if isinstance(v, list) and axis == "image_urls" else v
    if not changes:
        raise RestoreError("되돌릴 값이 하나도 없습니다(저널의 before 가 전부 확인불가).")

    report.sent = dict(changes)
    try:
        apply_fn(changes)
    except Exception as e:  # noqa: BLE001
        report.ok = False
        report.error = f"{type(e).__name__}: {e}"
        return report

    report.ok = True
    if snapshot_fn is None:
        return report

    # 보냈다고 끝이 아니다 — 되읽어 원래값과 같은지 본다.
    snap = snapshot_fn()
    bad = []
    for axis, want in changes.items():
        got = snap.value_of(axis)
        same = (tuple(got or ()) == tuple(want or ())
                if isinstance(want, (list, tuple)) else got == want)
        if not same:
            bad.append(axis)
    report.mismatched = tuple(bad)
    report.verified = not bad
    if bad:
        report.ok = False
        report.error = f"되돌렸는데 값이 원래대로가 아닙니다: {bad}"
    return report

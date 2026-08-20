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
    #: 시험 흔적이 아니라 **그 뒤에 정상적으로 바뀐 값**이라 건드리지 않은 축 {축: 현재값}.
    skipped: dict = field(default_factory=dict)
    #: 🔴 **판별 자체를 못 한** 축 {축: 현재값}. 조용히 건너뛰면 시험값이 남았는데
    #:    경보가 꺼진다 — 모르면 모른다고 말해야 사람이 본다.
    unknown: dict = field(default_factory=dict)


def _bears_our_mark(axis: str, cur, orig, sent=None) -> bool:
    """현재값이 **우리가 보낸 시험값 그대로**인가.

    🔴 [2026-08-12] 손복구가 저널의 5일 전 가격으로 현재가를 덮으려 했다. 그 사이
       우리 프로그램이 정상적으로 올려 둔 값이었다(마켓이 거부해서 무사했을 뿐).
       손복구의 목적은 「시험이 남긴 흔적 지우기」이지 「그날 이후를 되감기」가 아니다.
       시험 이후 정상적으로 바뀐 값을 옛값으로 덮으면 **금전 손실**이다.
    """
    from lemouton.uploader.roundtrip.runner import (
        _DETAIL_TOKEN, _NAME_SUFFIX, _PRICE_DELTA, _STOCK_DELTA,
    )
    if cur is None:
        return False

    # 🎯 [2026-08-13] 저널에 **우리가 보낸 값**이 적혀 있으면 짐작하지 않는다.
    #    지금 값이 그것과 같으면 우리 시험값이 그대로 남은 것 — 정확한 판정이다.
    #    (아래 낱말·주소 짐작은 옛 저널을 위한 예비 수단일 뿐이다)
    if sent is not None:
        return _same(cur, sent)
    if axis == "sale_price":
        try:
            return int(cur) == int(orig) + _PRICE_DELTA
        except (TypeError, ValueError):
            return False
    if axis == "stock":
        try:
            # 상한 상품은 -1 로 시험한다 — 위아래 둘 다 우리 흔적이다.
            return abs(int(cur) - int(orig)) == _STOCK_DELTA
        except (TypeError, ValueError):
            return False
    if axis == "name":
        return str(cur).endswith(_NAME_SUFFIX)
    if axis == "detail_html":
        return _DETAIL_TOKEN in str(cur)
    if axis == "image_urls":
        # 🔴 주소 표식은 **우리 창고(R2)에 올린 경우에만** 붙는다. 스마트스토어는
        #    네이버 CDN 에 올려 주소에 아무 표식이 없다 — 그때는 판별 불가다.
        first = str((tuple(cur) or ("",))[0])
        if _PROBE_MARK in first:
            return True
        return None                       # 모름 — 조용히 「아니다」로 넘기지 않는다
    return False


#: 시험 이미지 주소에 박히는 표식(probe_image.upload_probe_image_public 의 키).
_PROBE_MARK = "roundtrip/probe_"


def _same(got, want) -> bool:
    if isinstance(got, (list, tuple)) or isinstance(want, (list, tuple)):
        return tuple(got or ()) == tuple(want or ())
    return got == want


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

    # 🔴 [2026-08-12] **이미 원래값인 축은 건드리지 않는다.** 옥션 손복구가
    #    통째로 거부된 실사고 — 되돌려야 할 건 상품명·상세뿐인데 이미 맞는 재고까지
    #    같이 보냈고, 남의 옵션 재고가 0 이라 full-replace 가 전부 거부됐다.
    #    마켓 쓰기는 한 번이라도 덜 하는 게 낫다.
    #    ⚠️ 현재값을 못 읽으면(snapshot_fn 없음) 비교 근거가 없으니 저널대로 다 보낸다.
    sent_map = (data or {}).get("sent") or {}
    if snapshot_fn is not None:
        cur = snapshot_fn()
        keep, skip, unknown = {}, {}, {}
        for a, v in changes.items():
            now = cur.value_of(a)
            if _same(now, v):
                continue                  # 이미 원래대로 — 건드릴 이유가 없다
            mark = _bears_our_mark(a, now, v, sent_map.get(a))
            if mark is True:
                keep[a] = v
            elif mark is None:
                unknown[a] = now          # 판별 불가 — 안 건드리되 **모른다고 말한다**
            else:
                # 시험 흔적이 아니다 = 그 뒤에 정상적으로 바뀐 값이다. 덮지 않는다.
                skip[a] = now
        changes = keep
        report.skipped, report.unknown = dict(skip), dict(unknown)
        if not changes:
            report.ok = True
            # 🔴 판별 못 한 축이 하나라도 있으면 「확인됨」이 아니다.
            report.verified = None if unknown else True
            if unknown:
                report.error = (f"판별 불가 — {list(unknown)} 이 우리 시험값인지 알 수 없습니다"
                                f"(저널에 보낸 값이 안 적힌 옛 기록). 마켓 화면에서 직접 봐 주세요.")
            return report                 # 되돌릴 게 없다 — 쓰기를 안 한다

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

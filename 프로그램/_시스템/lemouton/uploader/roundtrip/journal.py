# -*- coding: utf-8 -*-
"""왕복 저널 — 원복 보험 파일.

**왜 파일인가**
    왕복 도중 프로세스가 죽거나 원복 전송이 실패하면, 마켓에는 시험값이 남는다.
    그때 되돌릴 근거는 「변경 전 마켓 값」이 적힌 파일 하나뿐이다.
    그래서 저널 쓰기는 전송보다 **먼저** 일어나고, 여기서 실패하면 전송 자체를 멈춘다.

**어디에 쓰나**
    ``shared/state_store.state_path()`` — 라이브(AWS Lightsail)는 배포마다 앱 컨테이너를
    새로 만들어 컨테이너 안 ``data/`` 가 사라진다. 원복 근거가 배포 한 번에 증발하면 안 된다.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from lemouton.uploader.roundtrip.snapshot import Snapshot

_STATUS_BEFORE = "전송전"
_STATUS_OK = "원복완료"
_STATUS_FAIL = "🔴원복실패"
#: 손복구로 「마켓에 시험 흔적이 없다」를 확인한 상태.
_STATUS_RESOLVED = "손복구확인"


def mark_resolved(journal_path, *, note: str = "") -> None:
    """손복구로 확인이 끝난 저널의 **상태만** 바꾼다.

    🔴 [2026-08-12] 손복구를 다 돌려 시험 흔적이 0건인 걸 확인했는데 목록은 계속
       「원복실패」로 떠 있었다. 고쳐진 걸 고쳐졌다고 안 적으면 다음 사람이 **또**
       손복구를 돌리고, 진짜 남은 문제가 해결된 소음에 묻힌다.

    ⚠️ `before`(원래값)는 절대 지우지 않는다 — 나중에 되돌릴 근거가 사라진다.
    """
    p = Path(journal_path)
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 못 읽는 파일은 건드리지 않는다
        return
    data["status"] = _STATUS_RESOLVED
    data["note"] = note or data.get("note") or ""
    data["resolved_at"] = datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_dir() -> Path:
    from shared.state_store import state_dir
    d = Path(state_dir()) / "roundtrip"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snap_to_dict(s: Snapshot) -> dict:
    d = asdict(s)
    # tuple → list (JSON), 그리고 raw 는 원본 그대로 남긴다.
    for k, v in list(d.items()):
        if isinstance(v, tuple):
            d[k] = list(v)
    d["options"] = [list(o) if isinstance(o, (list, tuple)) else o for o in (s.options or ())]
    return d


class RoundtripJournal:
    """왕복 1회 = 파일 1개. 같은 상품을 여러 번 시험해도 앞 파일을 덮지 않는다."""

    def __init__(self, *, dir_path=None, market: str, product_id: str, now=None):
        self._dir = Path(dir_path) if dir_path is not None else _default_dir()
        self.market = market
        self.product_id = str(product_id)
        stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
        self.path = self._dir / f"{market}_{self.product_id}_{stamp}.json"
        self._payload: dict = {}

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def write(self, before: Snapshot) -> None:
        """변경 전 값을 파일에 남긴다. 실패하면 예외 — runner 가 전송을 멈춘다."""
        self._payload = {
            "market": self.market,
            "product_id": self.product_id,
            "written_at": datetime.now().isoformat(timespec="seconds"),
            "status": _STATUS_BEFORE,
            "note": "",
            "before": _snap_to_dict(before),
            "손복구": "이 파일의 before 값으로 마켓을 직접 되돌리면 됩니다.",
        }
        self._flush()

    def record_sent(self, changes: dict) -> None:
        """**우리가 보낸 시험값**을 남긴다. 손복구가 짐작 대신 이걸로 대조한다.

        🔴 [2026-08-13] 예전엔 손복구가 「이게 우리 시험값인가」를 주소 모양(`roundtrip/probe_`)
           이나 낱말(「(시험중)」)로 짐작했다. 스마트스토어는 시험사진을 **네이버 CDN** 에
           올려 주소에 그 표식이 안 붙는다 → 못 알아보고 건너뛴 뒤 「시험 흔적 없음」
           도장까지 찍었다. 보낸 값을 그대로 적어 두면 짐작할 일이 없다.
        """
        if not self._payload:
            return
        self._payload["sent"] = {
            k: (list(v) if isinstance(v, tuple) else v) for k, v in (changes or {}).items()
        }
        self._flush()

    def close(self, ok: bool, note: str = "") -> None:
        if not self._payload:
            return
        self._payload["status"] = _STATUS_OK if ok else _STATUS_FAIL
        self._payload["note"] = note or ""
        self._payload["closed_at"] = datetime.now().isoformat(timespec="seconds")
        self._flush()

    def _flush(self) -> None:
        text = json.dumps(self._payload, ensure_ascii=False, indent=2)
        # 디스크까지 내려보낸다 — 여기서 죽어도 파일은 남아야 한다.
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

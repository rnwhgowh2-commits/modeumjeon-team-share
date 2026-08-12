# -*- coding: utf-8 -*-
"""개발 체크리스트 — 셀 판정 (순수 함수, Flask 의존 없음)."""
from __future__ import annotations

import json
import os

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                     "webapp", "data")


def load_columns(name: str = "dev_checklist_columns.json") -> list[dict]:
    with open(os.path.join(_DATA, name), encoding="utf-8") as f:
        return json.load(f)["columns"]

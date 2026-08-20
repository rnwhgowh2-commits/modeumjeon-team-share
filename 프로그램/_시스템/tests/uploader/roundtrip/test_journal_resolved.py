# -*- coding: utf-8 -*-
"""손복구로 확인이 끝난 저널은 「원복실패」로 남지 않는다.

🔴 [2026-08-12] 손복구를 다 돌려 시험 흔적이 0건인 걸 확인했는데, 목록은 계속
   「원복실패 11」로 떠 있었다. 상태가 갱신되지 않아서다.

   고쳐진 걸 고쳐졌다고 안 적으면, 다음 사람은 **또 손복구를 돌린다**.
   그리고 진짜 남은 문제(쿠팡 2건)가 9건의 해결된 소음에 묻힌다.
"""
from __future__ import annotations

import json

from lemouton.uploader.roundtrip.journal import mark_resolved


def _file(tmp_path, status="🔴원복실패"):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"market": "auction", "product_id": "G1",
                             "status": status, "note": "원복 거부",
                             "before": {"sale_price": 1000}}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def test_흔적이_없으면_해결로_적는다(tmp_path):
    p = _file(tmp_path)

    mark_resolved(p, note="손복구 확인 — 되돌릴 값 없음")

    d = json.loads(p.read_text(encoding="utf-8"))
    assert "실패" not in d["status"], f"여전히 실패로 남았다: {d['status']}"
    assert "손복구" in d["note"]
    assert d["before"]["sale_price"] == 1000, "원래값을 지우면 안 된다"


def test_원래값은_절대_지우지_않는다(tmp_path):
    """상태만 바꾼다 — before 가 사라지면 나중에 되돌릴 근거가 없어진다."""
    p = _file(tmp_path)

    mark_resolved(p, note="확인")

    assert json.loads(p.read_text(encoding="utf-8")).get("before")


def test_없는_파일은_조용히_넘어간다(tmp_path):
    mark_resolved(tmp_path / "없음.json", note="확인")

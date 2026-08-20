# -*- coding: utf-8 -*-
"""손복구는 **이미 맞는 축을 건드리지 않는다**(2026-08-12 라이브에서 막혔다).

옥션 6390703083 손복구가 통째로 거부됐다:
    ValueError: 옵션 재고가 1~99999 범위를 벗어납니다 —
                옵션 27304005160 의 iac=0 (goodsNo=6390703083)

되돌려야 할 건 **상품명·상세 두 축뿐**이었다. 재고는 이미 원래값(20)인데
저널에 있다는 이유로 같이 보냈고, 남의 옵션 재고가 0 이라 full-replace 가
통째로 거부됐다 — 고칠 수 있는 두 축까지 같이 죽었다.

🔴 되돌릴 필요 없는 축을 보내면 **위험만 커진다**. 마켓 쓰기는 한 번이라도
   덜 하는 게 낫다. 이미 원래값인 축은 건너뛴다.
"""
from __future__ import annotations

import json

from lemouton.uploader.roundtrip.restore import restore_from_journal
from lemouton.uploader.roundtrip.snapshot import Snapshot


def _journal(tmp_path, before):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"market": "auction", "product_id": "G1",
                             "before": before}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def test_이미_원래값인_축은_안_보낸다(tmp_path):
    """재고가 이미 맞는데 같이 보내다 통째로 거부된 실사고."""
    j = _journal(tmp_path, {"name": "원래이름", "sale_price": 68800,
                            "options": [["O1", 20, None]], "missing": []})
    now = Snapshot(market="auction", product_id="G1",
                   name="원래이름 (시험중)", sale_price=68800,
                   options=(("O1", 20, None),))
    sent = {}

    restore_from_journal(j, apply_fn=lambda c: sent.update(c),
                         snapshot_fn=lambda: now)

    assert "stock" not in sent, f"이미 맞는 재고를 또 보냈다: {sent}"
    assert "sale_price" not in sent, f"이미 맞는 가격을 또 보냈다: {sent}"
    assert sent.get("name") == "원래이름", f"정작 틀린 축을 안 보냈다: {sent}"


def test_되돌릴_게_없으면_보내지_않고_성공으로_본다(tmp_path):
    """마켓이 이미 원래대로다 — 굳이 쓰기를 한 번 더 할 이유가 없다."""
    j = _journal(tmp_path, {"name": "원래이름", "sale_price": 68800, "missing": []})
    now = Snapshot(market="auction", product_id="G1",
                   name="원래이름", sale_price=68800)
    calls = []

    rep = restore_from_journal(j, apply_fn=lambda c: calls.append(c),
                               snapshot_fn=lambda: now)

    assert calls == [], f"보낼 게 없는데 전송했다: {calls}"
    assert rep.ok is True
    assert rep.verified is True


def test_현재값을_못_읽으면_저널대로_전부_보낸다(tmp_path):
    """비교할 근거가 없으면 옛 방식대로 — 안전한 쪽(다 되돌리기)으로 간다."""
    j = _journal(tmp_path, {"name": "원래이름", "sale_price": 68800, "missing": []})
    sent = {}

    restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=None)

    assert sent == {"name": "원래이름", "sale_price": 68800}

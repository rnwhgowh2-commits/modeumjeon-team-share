# -*- coding: utf-8 -*-
"""손복구는 **우리 시험 흔적이 남아 있는 축만** 되돌린다.

🔴 [2026-08-12 아찔했던 일] 옥션 6390703083 손복구가 저널의 **5일 전 가격
   68,800** 으로 현재가 69,800 을 덮으려 했다. 그 사이 우리 프로그램이 정상적으로
   올려 둔 값이었다. 마켓이 노출제한 상품이라 거부해서 무사했을 뿐이다.

   손복구의 목적은 「시험이 남긴 흔적 지우기」이지 「그날 이후를 되감기」가 아니다.
   시험 이후 정상적으로 바뀐 값을 옛값으로 덮으면 **금전 손실**이다.

판정 규칙 — 현재값이 **우리가 보낸 시험값 그대로**일 때만 되돌린다:
    가격    현재 == 원래 + 100
    재고    현재 == 원래 ± 1
    상품명  " (시험중)" 으로 끝난다
    상세    ROUNDTRIP-TEST-MARK 가 들어 있다
    이미지  첫 장 주소에 roundtrip/probe_ 가 들어 있다
흔적이 없으면 **사람이 바꾼 값**이므로 건드리지 않고 그대로 보고한다.
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


def test_시험_이후_바뀐_가격은_되돌리지_않는다(tmp_path):
    """68,800 → (시험 68,900) → 이후 69,800 으로 정상 인상. 68,800 으로 덮으면 손해다."""
    j = _journal(tmp_path, {"sale_price": 68800, "name": "이름 (시험중)".replace(" (시험중)", ""),
                            "missing": []})
    now = Snapshot(market="auction", product_id="G1",
                   name="이름 (시험중)", sale_price=69800)
    sent = {}

    rep = restore_from_journal(j, apply_fn=lambda c: sent.update(c),
                               snapshot_fn=lambda: now)

    assert "sale_price" not in sent, f"5일치 인상을 옛 가격으로 덮었다: {sent}"
    assert sent.get("name") == "이름", "정작 시험 표식은 안 지웠다"
    assert "sale_price" in rep.skipped, f"건너뛴 이유를 안 알렸다: {rep}"


def test_시험값_그대로면_되돌린다(tmp_path):
    """현재가 = 원래 + 100 → 우리 시험값이 그대로 남았다는 뜻."""
    j = _journal(tmp_path, {"sale_price": 68800, "missing": []})
    now = Snapshot(market="auction", product_id="G1", sale_price=68900)
    sent = {}

    restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=lambda: now)

    assert sent.get("sale_price") == 68800


def test_재고는_위아래_어느_쪽_시험값이든_되돌린다(tmp_path):
    """상한 상품은 -1 로 시험한다 — 그쪽도 우리 흔적이다."""
    for cur in (11, 9):
        j = _journal(tmp_path, {"options": [["O1", 10, None]], "missing": []})
        now = Snapshot(market="auction", product_id="G1",
                       options=(("O1", cur, None),))
        sent = {}

        restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=lambda: now)

        assert sent.get("stock") == 10, f"현재 {cur} 인데 안 되돌렸다"


def test_사람이_바꾼_재고는_안_건드린다(tmp_path):
    j = _journal(tmp_path, {"options": [["O1", 10, None]], "missing": []})
    now = Snapshot(market="auction", product_id="G1", options=(("O1", 430, None),))
    sent = {}

    rep = restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=lambda: now)

    assert "stock" not in sent, f"사람이 채운 재고 430 을 10 으로 되돌렸다: {sent}"
    assert "stock" in rep.skipped


def test_상세는_표식이_있을_때만_되돌린다(tmp_path):
    j = _journal(tmp_path, {"detail_html": "<p>원래</p>", "missing": []})
    dirty = Snapshot(market="auction", product_id="G1",
                     detail_html="<p>원래</p><p>ROUNDTRIP-TEST-MARK</p>")
    edited = Snapshot(market="auction", product_id="G1",
                      detail_html="<p>사장님이 새로 쓴 상세</p>")

    sent1, sent2 = {}, {}
    restore_from_journal(j, apply_fn=lambda c: sent1.update(c), snapshot_fn=lambda: dirty)
    restore_from_journal(j, apply_fn=lambda c: sent2.update(c), snapshot_fn=lambda: edited)

    assert sent1.get("detail_html") == "<p>원래</p>"
    assert "detail_html" not in sent2, "사람이 새로 쓴 상세를 옛것으로 덮었다"


def test_이미지는_시험사진일_때만_되돌린다(tmp_path):
    j = _journal(tmp_path, {"image_urls": ["http://cdn/real.jpg"], "missing": []})
    probe = Snapshot(market="auction", product_id="G1",
                     image_urls=("https://r2/roundtrip/probe_auction_1.png",))
    other = Snapshot(market="auction", product_id="G1",
                     image_urls=("http://cdn/새사진.jpg",))

    sent1, sent2 = {}, {}
    restore_from_journal(j, apply_fn=lambda c: sent1.update(c), snapshot_fn=lambda: probe)
    restore_from_journal(j, apply_fn=lambda c: sent2.update(c), snapshot_fn=lambda: other)

    assert tuple(sent1.get("image_urls") or ()) == ("http://cdn/real.jpg",)
    assert "image_urls" not in sent2, "사람이 바꾼 사진을 옛것으로 덮었다"


def test_현재값을_못_읽으면_저널대로_보낸다(tmp_path):
    """비교 근거가 없다 — 옛 방식대로 간다(손복구를 아예 못 하는 것보다 낫다)."""
    j = _journal(tmp_path, {"sale_price": 68800, "missing": []})
    sent = {}

    restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=None)

    assert sent == {"sale_price": 68800}

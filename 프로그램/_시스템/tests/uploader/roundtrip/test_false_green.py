# -*- coding: utf-8 -*-
"""거짓 초록불 2건 — 실패했는데 「괜찮다」고 보고하던 것(2026-08-13 전수 조사).

🔴 ① 손복구가 **스마트스토어 시험사진을 못 알아본다.**
   시험사진 표식이 `roundtrip/probe_` 인데, 그건 **우리 창고(R2) 주소 형식**이다.
   스마트스토어만은 네이버 CDN 에 올린다(`probe_image.upload_probe_image`) —
   주소가 `shop-phinf.pstatic.net/...` 라 표식이 없다.
   그래서 손복구가 「시험 흔적이 아니라 사람이 바꾼 값」으로 보고 **건너뛴 뒤**
   「시험 흔적 없음」 도장을 찍고 경보를 끈다. 시험사진이 상품에 남는다.

🔴 ② 「이 마켓이 안 줍니다」라는 **거짓말**을 적는다.
   읽히는데 우리가 안 보내기로 한 축(예: 11번가 상품명)도 같은 문구가 나간다.
   「마켓이 안 줌」과 「우리가 안 보냄」은 다른 말이다 — 앞엣것은 마켓 탓이고
   뒤엣것은 우리 결정이다. 섞어 적으면 없는 제약을 있는 것처럼 굳힌다.
"""
from __future__ import annotations

import json

from lemouton.uploader.roundtrip.restore import restore_from_journal
from lemouton.uploader.roundtrip.runner import run_roundtrip
from lemouton.uploader.roundtrip.snapshot import Snapshot


# ── ① 손복구가 스스 시험사진을 알아본다 ──────────────────────────────────────
def _journal(tmp_path, before, sent=None):
    body = {"market": "smartstore", "product_id": "P1", "before": before}
    if sent is not None:
        body["sent"] = sent
    p = tmp_path / "j.json"
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return p


_NAVER = "https://shop-phinf.pstatic.net"


def test_보낸_값이_적혀_있으면_정확히_알아본다(tmp_path):
    """🎯 짐작하지 않는다 — 저널에 적힌 「보낸 값」과 같으면 우리 시험사진이다.

    스스는 시험사진을 **네이버 서버**에 올려 주소에 우리 표식이 안 붙는다.
    주소 모양으로 짐작하는 방식은 여기서 반드시 틀린다.
    """
    probe = f"{_NAVER}/20260813_1/aBcDeF_PNG/image_0.png"
    j = _journal(tmp_path, {"image_urls": [f"{_NAVER}/원본.jpg"], "missing": []},
                 sent={"image_urls": [probe]})
    now = Snapshot(market="smartstore", product_id="P1", image_urls=(probe,))
    sent = {}

    restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=lambda: now)

    assert tuple(sent.get("image_urls") or ()) == (f"{_NAVER}/원본.jpg",), \
        f"보낸 값이 적혀 있는데 못 알아봤다: {sent}"


def test_보낸_값이_적혀_있으면_남의_사진은_안_건드린다(tmp_path):
    j = _journal(tmp_path, {"image_urls": [f"{_NAVER}/원본.jpg"], "missing": []},
                 sent={"image_urls": [f"{_NAVER}/시험.png"]})
    now = Snapshot(market="smartstore", product_id="P1",
                   image_urls=(f"{_NAVER}/사장님이_새로_올린_사진.jpg",))
    sent = {}

    rep = restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=lambda: now)

    assert "image_urls" not in sent, f"사람이 바꾼 사진을 옛것으로 덮었다: {sent}"
    assert "image_urls" in rep.skipped


def test_옛_저널은_모른다고_말한다(tmp_path):
    """🔴 보낸 값이 안 적힌 옛 저널은 **판별할 방법이 없다.**

    예전엔 이때 조용히 건너뛰고 「시험 흔적 없음」 도장까지 찍었다 —
    시험사진이 상품에 남았는데 경보가 꺼졌다.
    모르면 「모른다」고 해야 사람이 본다.
    """
    j = _journal(tmp_path, {"image_urls": [f"{_NAVER}/원본.jpg"], "missing": []})
    now = Snapshot(market="smartstore", product_id="P1",
                   image_urls=(f"{_NAVER}/무언가_다른.png",))
    sent = {}

    rep = restore_from_journal(j, apply_fn=lambda c: sent.update(c), snapshot_fn=lambda: now)

    assert "image_urls" not in sent, "판별도 못 했는데 덮어썼다"
    assert "image_urls" in rep.unknown, f"모르는 걸 안다고 했다: {rep}"
    assert rep.verified is not True, "판별 못 한 게 있는데 「확인됨」으로 찍었다"


# ── ② 「마켓이 안 줌」과 「우리가 안 보냄」을 구분한다 ────────────────────────
class _Journal:
    def __init__(self):
        self.path = "j"
    def write(self, before): pass
    def close(self, ok, note=""): pass


def _run(before, axes):
    return run_roundtrip(snapshot_fn=lambda: before, apply_fn=lambda c: None,
                         journal=_Journal(), axes=axes,
                         on_sale_fn=lambda: False, recheck_sleep=0)


def test_마켓이_정말_안_주면_그렇게_적는다():
    before = Snapshot(market="lotteon", product_id="P1", sale_price=1000,
                      detail_html=None, missing=("detail_html",))

    rep = _run(before, ("detail_html",))
    note = rep.axes[0].note

    assert "마켓" in note and "안" in note, note


def test_읽히는데_우리가_안_보내는_것은_그렇게_적는다():
    """🔴 값이 읽히는데 「마켓이 안 준다」고 적으면 거짓말이다."""
    before = Snapshot(market="eleven11", product_id="P1", sale_price=1000,
                      name="읽히는 상품명", missing=("name",))

    rep = _run(before, ("name",))
    note = rep.axes[0].note

    assert "읽히" in note, f"읽히는 값인데 그렇게 안 적는다: {note}"
    assert "보내지 않" in note, f"우리가 안 보낸다는 말이 없다: {note}"

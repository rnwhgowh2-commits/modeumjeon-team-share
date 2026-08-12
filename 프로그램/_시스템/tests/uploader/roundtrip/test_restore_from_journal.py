# -*- coding: utf-8 -*-
"""저널로 되돌리기 — 원복이 실패했을 때의 손복구 경로.

🔴 [2026-08-07 라이브] 옥션 왕복에서 실제로 필요해졌다.
   첫 전송은 통했는데(가격·상품명·상세 바뀜) **원복이 마켓 제재로 거부**됐다:
     resultCode=1000 [지식재산권침해 우려(1250)]의 사유로 사이트 내 상품 노출이 제한 되었습니다.
   마켓에 시험값이 남았고, 왕복을 다시 부르면 **지금 값(시험값)을 원래값으로 삼아**
   더 나빠진다 — 되돌리기 전용 경로가 반드시 따로 있어야 한다.

설계 약속: 저널에 before 를 먼저 남기는 이유가 바로 이것이다.
"""
from __future__ import annotations

import json

import pytest

from lemouton.uploader.roundtrip.restore import RestoreError, restore_from_journal


def _journal_file(tmp_path, before):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"market": "auction", "product_id": "G1",
                             "status": "🔴원복실패", "before": before},
                            ensure_ascii=False), encoding="utf-8")
    return p


_BEFORE = {"market": "auction", "product_id": "G1",
           "name": "원래이름", "detail_html": "<p>원래</p>",
           "image_urls": ["http://img/a.jpg"], "sale_price": 68800,
           "options": [["__base__", 20, None]], "missing": [], "raw": {}}


def test_저널의_원래값으로_되돌린다(tmp_path):
    sent = []
    report = restore_from_journal(_journal_file(tmp_path, _BEFORE),
                                  apply_fn=lambda c: sent.append(dict(c)))

    assert report.ok is True
    assert sent[-1]["sale_price"] == 68800
    assert sent[-1]["name"] == "원래이름"
    assert sent[-1]["detail_html"] == "<p>원래</p>"
    assert tuple(sent[-1]["image_urls"]) == ("http://img/a.jpg",)
    assert sent[-1]["stock"] == 20


def test_확인불가였던_축은_되돌리지_않는다(tmp_path):
    """못 읽었던 축은 원래값을 모른다 — 지어내서 보내면 안 된다."""
    before = dict(_BEFORE, missing=["detail_html", "image_urls"],
                  detail_html=None, image_urls=None)
    sent = []

    restore_from_journal(_journal_file(tmp_path, before),
                         apply_fn=lambda c: sent.append(dict(c)))

    assert "detail_html" not in sent[-1]
    assert "image_urls" not in sent[-1]
    assert sent[-1]["sale_price"] == 68800


def test_전송이_실패하면_사유를_그대로_올린다(tmp_path):
    def boom(changes):
        raise RuntimeError("마켓이 거부: 노출 제한")

    report = restore_from_journal(_journal_file(tmp_path, _BEFORE), apply_fn=boom)

    assert report.ok is False
    assert "노출 제한" in report.error


def test_저널이_없으면_지어내지_않고_멈춘다(tmp_path):
    with pytest.raises(RestoreError):
        restore_from_journal(tmp_path / "없는파일.json", apply_fn=lambda c: None)


def test_before_가_비어_있으면_멈춘다(tmp_path):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"market": "auction", "before": {}}), encoding="utf-8")

    with pytest.raises(RestoreError):
        restore_from_journal(p, apply_fn=lambda c: None)


def test_되돌린_뒤_확인까지_한다(tmp_path):
    """보냈다고 끝이 아니다 — 되읽어 원래값과 같은지 본다.

    현재값은 **우리 시험값(원래 68,800 + 100)** 이어야 한다. 아무 값이나 쓰면
    그건 「시험 이후 정상적으로 바뀐 값」이라 손복구가 일부러 안 건드린다
    (2026-08-12 — 옛 가격으로 덮으면 금전 손실).
    """
    state = {"sale_price": 68900}

    def apply_fn(changes):
        state.update(changes)

    class Snap:
        def value_of(self, axis):
            return state.get(axis)

    report = restore_from_journal(_journal_file(tmp_path, _BEFORE),
                                  apply_fn=apply_fn, snapshot_fn=lambda: Snap())

    assert report.ok is True
    assert report.verified is True
    assert state["sale_price"] == 68800

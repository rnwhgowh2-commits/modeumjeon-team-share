# -*- coding: utf-8 -*-
"""저널 — 원복 보험 파일.

왕복 중에 프로세스가 죽으면 마켓에는 시험값이 남는다. 그때 되돌릴 근거는
**변경 전 값이 적힌 파일** 하나뿐이다. 그래서 저널은 전송보다 먼저 쓰이고,
쓰기가 끝난 뒤 디스크까지 내려가 있어야 한다.
"""
from __future__ import annotations

import json

import pytest

from lemouton.uploader.roundtrip.journal import RoundtripJournal
from lemouton.uploader.roundtrip.snapshot import Snapshot


def _snap():
    return Snapshot(market="smartstore", product_id="123",
                    name="원래이름", detail_html="<p>원래</p>",
                    image_urls=("http://cdn/a.jpg",), sale_price=10000,
                    options=(("111", 3, 0),), raw={"originProduct": {"name": "원래이름"}})


def test_쓰자마자_파일에_남는다(tmp_path):
    """close 를 못 부르고 죽어도 before 가 파일에 있어야 한다."""
    j = RoundtripJournal(dir_path=tmp_path, market="smartstore", product_id="123")

    j.write(_snap())

    text = (tmp_path / j.path.name).read_text(encoding="utf-8")
    saved = json.loads(text)
    assert saved["before"]["name"] == "원래이름"
    assert saved["before"]["sale_price"] == 10000
    assert saved["status"] == "전송전"


def test_원본_응답도_통째로_남긴다(tmp_path):
    """축 5개만 남기면, 마켓이 그 밖의 필드를 함께 덮었을 때 되돌릴 근거가 없다."""
    j = RoundtripJournal(dir_path=tmp_path, market="smartstore", product_id="123")

    j.write(_snap())

    saved = json.loads(j.path.read_text(encoding="utf-8"))
    assert saved["before"]["raw"]["originProduct"]["name"] == "원래이름"


def test_닫으면_결과가_남는다(tmp_path):
    j = RoundtripJournal(dir_path=tmp_path, market="smartstore", product_id="123")
    j.write(_snap())

    j.close(False, "원복 실패(시험)")

    saved = json.loads(j.path.read_text(encoding="utf-8"))
    assert saved["status"] == "🔴원복실패"
    assert saved["note"] == "원복 실패(시험)"


def test_성공으로_닫으면_원복완료로_남는다(tmp_path):
    j = RoundtripJournal(dir_path=tmp_path, market="smartstore", product_id="123")
    j.write(_snap())

    j.close(True)

    saved = json.loads(j.path.read_text(encoding="utf-8"))
    assert saved["status"] == "원복완료"


def test_같은_상품을_두_번_시험해도_앞_저널을_덮지_않는다(tmp_path):
    """앞 회차가 원복 실패로 끝났는데 파일이 덮이면 손복구 근거가 사라진다."""
    a = RoundtripJournal(dir_path=tmp_path, market="smartstore", product_id="123")
    a.write(_snap())
    b = RoundtripJournal(dir_path=tmp_path, market="smartstore", product_id="123")
    b.write(_snap())

    assert a.path != b.path
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_쓸_수_없는_곳이면_예외를_낸다(tmp_path):
    """조용히 넘어가면 저널 없이 전송된다 — runner 가 이 예외를 보고 멈춘다."""
    bad = tmp_path / "파일임"
    bad.write_text("x", encoding="utf-8")
    j = RoundtripJournal(dir_path=bad, market="smartstore", product_id="123")

    with pytest.raises(OSError):
        j.write(_snap())

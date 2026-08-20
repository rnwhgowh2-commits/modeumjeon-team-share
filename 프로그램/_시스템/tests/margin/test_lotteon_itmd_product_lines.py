# -*- coding: utf-8 -*-
"""롯데온 SettleItmdSales — **상품 판매대금 라인만** 정산액으로 센다.

🔴🔴 2026-08-04 라이브 정합성 검사에서 드러난 것
  셀러오피스 크롤 ↔ 공식 API 를 전수 대조하니 4건이 어긋났는데 **넷 다 공식 쪽이
  정확히 10,000원**이었다. 원문:
      정상  procSeq "1"    spdNo "LO2679592341"   165,207원
      문제  procSeq "202"  spdNo ""                10,000원
  옛 파서는 procSeq 구분 없이 전부 합산해, 그 주문에 상품 라인이 아직 없으면
  10,000원이 그 주문의 「정산예정금」이 됐다(실제 지급액은 9,868·54,187·−1,436).

★판별을 procSeq 목록이 아니라 **상품번호(spdNo) 유무**로 하는 이유 —
  라이브 전수(2026-05-01~08-04 · 7계정 833행):
      procSeq 1·2·3        760행 → 상품번호 전부 **있음**
      procSeq 202~207·빈값   73행 → 상품번호 전부 **없음**
  허용목록으로 거르면 롯데온이 새 번호를 쓰기 시작한 날 멀쩡한 상품 정산을 조용히 버린다.
"""
from shared.platforms.lotteon.settlement import parse_itmd, parse_itmd_lines


def _row(od, seq, amt, spd="LO123", proc="1", pcs=0):
    return {"odNo": od, "odSeq": seq, "pymtAmt": amt,
            "spdNo": spd, "procSeq": proc, "pcsCmsn": pcs}


def test_상품라인만_라인정산액에_들어간다():
    resp = {"data": [
        _row("A1", "1", 165207),                                   # 상품
        _row("A1", "1", 10000, spd="", proc="202"),                # 별도 항목
    ]}
    assert parse_itmd_lines(resp) == {("A1", "1"): 165207}


def test_상품라인이_없으면_그_주문은_아예_안_준다():
    """🔴 이게 실제 사고 모양 — 별도 라인만 있는 주문에 10,000 이 박혔다.

    값을 주지 않아야 셀러오피스 크롤값·추정이 그 자리를 채운다(그쪽이 실제 지급액을 안다).
    """
    resp = {"data": [_row("B2", "1", 10000, spd="", proc="202")]}
    assert parse_itmd_lines(resp) == {}
    assert parse_itmd(resp) == {}


def test_부분취소_음수는_그대로_합산된다():
    """procSeq 2(환불)는 상품번호가 있다 — 순액 규약을 깨면 안 된다."""
    resp = {"data": [
        _row("C3", "1", 50000),
        _row("C3", "1", -17426, proc="2"),
    ]}
    assert parse_itmd_lines(resp) == {("C3", "1"): 50000 - 17426}


def test_다품_주문은_벌마다_따로_유지된다():
    """라인 단위 규약(2026-07-25) 회귀 방지 — 별도 라인이 섞여도 벌 값은 안 흔들린다."""
    resp = {"data": [
        _row("D4", "1", 41624),
        _row("D4", "2", 41624),
        _row("D4", "1", 10000, spd="", proc="203"),
    ]}
    assert parse_itmd_lines(resp) == {("D4", "1"): 41624, ("D4", "2"): 41624}


def test_새_procSeq_라도_상품번호가_있으면_센다():
    """🔴 허용목록이 아니라 상품번호로 묻는 이유 — 롯데온이 새 번호를 써도 안 깨진다."""
    resp = {"data": [_row("E5", "1", 88000, proc="4")]}
    assert parse_itmd_lines(resp) == {("E5", "1"): 88000}


def test_주문단위_집계도_같은_규칙을_쓴다():
    """parse_itmd(odNo 단위)도 order_export 가 폴백으로 읽는다 — 한쪽만 고치면 갈린다."""
    resp = {"data": [
        _row("F6", "1", 70000, pcs=1400),
        _row("F6", "1", 10000, spd="", proc="205"),
    ]}
    got = parse_itmd(resp)
    assert got["F6"]["pymtAmt"] == 70000
    assert got["F6"]["pcs_cmsn"] == 1400 and got["F6"]["is_affiliate"] is True


def test_상품번호가_공백만이면_상품라인이_아니다():
    resp = {"data": [_row("G7", "1", 10000, spd="   ", proc="202")]}
    assert parse_itmd_lines(resp) == {}

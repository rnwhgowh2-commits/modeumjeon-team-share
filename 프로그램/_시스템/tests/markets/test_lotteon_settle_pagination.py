# -*- coding: utf-8 -*-
"""롯데온 SettleItmdSales 페이징 — 100건 조용한 절삭 방지.

🔴 롯데온 목록/정산 API 는 pageNo·rowsPerPage(MAX 100)를 요구하는 것들이 있고,
  안 넣으면 **첫 100건만 조용히 오고 나머지가 사라진다**(settle_orders._fetch_window
  주석의 실측 사고). SettleItmdSales 도 같은 계열이라 정산액이 많은 창에서 절삭되면
  스윕이 옛 주문 정산을 통째로 놓친다. → 페이징을 넣어 전량 수집.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from shared.platforms.lotteon import settlement as S


class _PagedClient:
    """pageNo/rowsPerPage 를 지원하는 가짜 클라이언트. dataCount 로 끝을 알린다."""

    def __init__(self, rows):
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "T", "lrtr_no": "L"}
        self._rows = rows
        self.calls = []

    def request(self, *, method, path, body):
        self.calls.append(dict(body))
        page = body.get("pageNo")
        size = body.get("rowsPerPage") or S.PAGE_SIZE
        if page is None:                      # 무페이징 요청 — 전량(구버전 경로)
            return {"returnCode": "0000", "dataCount": len(self._rows),
                    "data": list(self._rows)}
        start = (int(page) - 1) * size
        chunk = self._rows[start:start + size]
        return {"returnCode": "0000", "dataCount": len(self._rows), "data": chunk}


class _NoPageClient:
    """페이징 파라미터를 거부하는 클라이언트 — page 요청엔 실패코드, 무페이징만 성공."""

    def __init__(self, rows):
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "T", "lrtr_no": "L"}
        self._rows = rows
        self.calls = []

    def request(self, *, method, path, body):
        self.calls.append(dict(body))
        if body.get("pageNo") is not None:
            return {"returnCode": "9000", "returnMessage": "페이징 미지원"}
        return {"returnCode": "0000", "data": list(self._rows)}


def _rows(n):
    return [{"odNo": f"OD{i:04d}", "pymtAmt": 1000 + i, "pcsCmsn": 0,
             "spdNo": f"SP{i:04d}"} for i in range(n)]


def _win():
    until = _dt.datetime(2026, 7, 20)
    since = until - _dt.timedelta(days=5)     # 1개 창(≤29일)
    return since, until


def test_페이징으로_100건_넘게_전량_수집():
    since, until = _win()
    cli = _PagedClient(_rows(150))            # 100 초과

    got = S.itmd_map(since, until, client=cli)

    assert len(got) == 150, f"절삭되면 100만 옴 — 실제 {len(got)}"
    assert got["OD0149"]["pymtAmt"] == 1149
    # 최소 2페이지 이상 호출됐다.
    assert sum(1 for c in cli.calls if c.get("pageNo")) >= 2


def test_scan_도_전량_수집():
    since, until = _win()
    cli = _PagedClient(_rows(150))

    orders, products = S.scan(since, until, client=cli)
    assert len(orders) == 150
    assert len(products) == 150


def test_페이징_미지원이면_무페이징으로_폴백():
    since, until = _win()
    cli = _NoPageClient(_rows(40))

    got = S.itmd_map(since, until, client=cli)
    assert len(got) == 40                      # 폴백으로도 전량


class _IgnoresPageClient:
    """🔴 서버가 pageNo 를 무시하고 매 페이지 같은 100건을 dataCount 없이 준다.
      dedup 이 없으면 page 1000 까지 append → pymtAmt 1000배 블로업."""

    def __init__(self, rows):
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "T", "lrtr_no": "L"}
        self._rows = rows                     # 정확히 PAGE_SIZE 건
        self.calls = 0

    def request(self, *, method, path, body):
        self.calls += 1
        return {"returnCode": "0000", "data": list(self._rows)}   # dataCount 없음


class _TotalFailClient:
    """페이징도 무페이징도 실패코드 — 조용한 부분수집 대신 예외를 올려야 한다."""

    def __init__(self):
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "T", "lrtr_no": "L"}

    def request(self, *, method, path, body):
        return {"returnCode": "9000", "returnMessage": "권한 없음"}


def test_서버가_pageNo_무시해도_블로업하지_않는다():
    since, until = _win()
    rows = [{"odNo": f"OD{i:04d}", "odSeq": "1", "procSeq": "0",
             "pymtAmt": 100, "spdNo": f"SP{i}"} for i in range(S.PAGE_SIZE)]
    cli = _IgnoresPageClient(rows)

    got = S.itmd_map(since, until, client=cli)
    assert len(got) == S.PAGE_SIZE             # 1000배가 아니라 딱 100
    assert got["OD0000"]["pymtAmt"] == 100     # 중복 합산 없음
    assert cli.calls <= 3                      # 새 행 없으면 즉시 멈춘다


def test_전면_실패는_예외로_올린다_조용한_부분수집_금지():
    since, until = _win()
    with pytest.raises(RuntimeError):
        S.itmd_map(since, until, client=_TotalFailClient())

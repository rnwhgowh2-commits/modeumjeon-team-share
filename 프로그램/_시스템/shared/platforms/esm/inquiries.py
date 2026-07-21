# -*- coding: utf-8 -*-
"""ESM(옥션·G마켓) 고객문의 조회 — 판매자문의 + 긴급알리미.

  판매자문의: POST /item/v1/communications/customer/bulletin-board
    · qnaType — ★옥션은 1(일반)·2(비밀글)를 각각, G마켓은 3(전체)만(문서 명시)
    · status 1(전체) · type 1(접수일) · 기간 7일 단위
  긴급알리미: POST /assist/v1/Selling/GetEmergencyInformList
    · status 1(전체) · type 1(접수일)

  ★ 기간 규약은 클레임과 동일하게 방어한다(2026-07-21 실측 교훈):
    6일 분할 + endDate 하루 올림(마켓이 endDate 를 그날 00:00 로 해석).
  ★ resultCode 대소문자 혼재(판매자문의 소문자·긴급알리미 대문자) — 둘 다 본다.
"""
from __future__ import annotations

import datetime as _dt

QNA_PATH = "/item/v1/communications/customer/bulletin-board"
EMERGENCY_PATH = "/assist/v1/Selling/GetEmergencyInformList"

_WINDOW_DAYS = 6
# 판매자문의 조회 구분 — 옥션은 일반/비밀글 각각, G마켓은 3(전체)만 지원.
_QNA_TYPES = {"auction": (1, 2), "gmarket": (3,)}


def _windows(since, until):
    step = _dt.timedelta(days=_WINDOW_DAYS)
    cur = since
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def _ok(resp: dict) -> bool:
    rc = resp.get("ResultCode", resp.get("resultCode"))
    return rc in (0, "0", None) or str(rc).strip().lower() == "success"


def _rows(resp: dict, path: str) -> list:
    resp = resp or {}
    if not _ok(resp):
        raise RuntimeError(
            f"ESM {path} 실패 ResultCode={resp.get('ResultCode', resp.get('resultCode'))} "
            f"{resp.get('Message') or resp.get('message') or ''}".strip())
    data = resp.get("Data", resp.get("data"))
    return data if isinstance(data, list) else []


def iter_seller_qna(market, since, until, *, client):
    """판매자문의 — 문의ID(MessageNo) 중복 제거."""
    qna_types = _QNA_TYPES.get(market)
    if not qna_types:
        raise ValueError(f"ESM 마켓 아님: {market}")
    seen = set()
    for w_from, w_to in _windows(since, until):
        for qt in qna_types:
            body = {
                "qnaType": qt, "status": 1, "type": 1,
                "startDate": w_from.strftime("%Y-%m-%d"),
                "endDate": (w_to + _dt.timedelta(days=1)).strftime("%Y-%m-%d"),
            }
            for it in _rows(client.post(QNA_PATH, body), QNA_PATH):
                no = str(it.get("MessageNo") or "")
                if no and no in seen:
                    continue
                if no:
                    seen.add(no)
                yield it


def iter_emergency(market, since, until, *, client):
    """긴급알리미 — 문의ID(EmerMessageNo) 중복 제거."""
    if market not in _QNA_TYPES:
        raise ValueError(f"ESM 마켓 아님: {market}")
    seen = set()
    for w_from, w_to in _windows(since, until):
        body = {
            "status": 1, "type": 1,
            "startDate": w_from.strftime("%Y-%m-%d"),
            "endDate": (w_to + _dt.timedelta(days=1)).strftime("%Y-%m-%d"),
        }
        for it in _rows(client.post(EMERGENCY_PATH, body), EMERGENCY_PATH):
            no = str(it.get("EmerMessageNo") or "")
            if no and no in seen:
                continue
            if no:
                seen.add(no)
            yield it

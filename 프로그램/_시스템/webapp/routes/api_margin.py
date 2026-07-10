# -*- coding: utf-8 -*-
r"""마진 분석 라우트 — `/api/margin/*`.

흐름: 더망고 매입 엑셀 업로드(기간 자동 추론) → analyze(마켓 API 조회 + 선택 샵마인
concat → pipeline → aggregate → R2 + DB 저장) → 목록/로드/삭제/엑셀 내보내기.

원본 로직: C:\dev\대량등록 마진계산기\app.py 의 /api/analyze·/api/download.

■ 저장 순서(중요) — 마켓 조회를 **가장 먼저** 한다. 조회 실패(502)면 R2 업로드도 DB
  저장도 하지 않는다. 실패한 마켓의 매입 행이 전부 '매출 미매칭'으로 둔갑해 블랙스팟처럼
  보이는 적극적 오신호를 막기 위함(스펙 §9). 실패한 run 은 GET /analyses 에 남지 않는다.

■ settle_estimated 는 **matched**(분석된 행) 기준으로 센다. sell_df(조회된 행) 기준이
  아니다 — 사용자가 궁금한 건 '내 분석 결과 중 추정치에 기댄 게 몇 건인가'다(스펙 §5).

■ _PENDING 은 프로세스 전역 dict 다. 업로드→분석 사이 스테이징에만 쓰이며, 멀티유저
  동시 업로드에는 안전하지 않다(마지막 업로더가 이긴다). 팀 공유되는 것은 DB 에 저장된
  '분석 결과'뿐이고, 스테이징은 한 번의 업로드-분석 왕복 안에서만 산다 → 과설계하지
  않는다(YAGNI). 개선한다면 세션키/토큰 스테이징이나, 아예 업로드 없이 analyze 가
  파일을 직접 받는 단일 요청으로 합치는 방향.
"""
import datetime as _dt
import io
import math
import uuid

import numpy as np
import pandas as pd
from flask import Blueprint, jsonify, request, send_file

from shared.db import SessionLocal
from lemouton.margin import aggregator, export, pipeline, store
from lemouton.margin import sell_source
from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.config import DEFAULT_PRICE_RANGES

bp = Blueprint("api_margin", __name__, url_prefix="/api/margin")

PERIOD_MARGIN_DAYS = 3
_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# 업로드 스테이징(프로세스 전역, 단일 왕복 전용 — 모듈 docstring 참조).
_PENDING: dict = {}


# ── 헬퍼 ──────────────────────────────────────────────────────────────────

def _parse_date(v):
    """더망고 마켓주문일자 → date. '2026-07-04 12:00:00' / '26.04.08' 모두 대응."""
    s = str(v).strip()
    for fmt in ("%y.%m.%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return _dt.datetime.strptime(
                s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except Exception:  # noqa: BLE001
            continue
    return None


def _parse_dt(v) -> _dt.datetime:
    """date / datetime / 'YYYY-MM-DD' → datetime."""
    if isinstance(v, _dt.datetime):
        return v
    if isinstance(v, _dt.date):
        return _dt.datetime(v.year, v.month, v.day)
    return _dt.datetime.strptime(str(v)[:10], "%Y-%m-%d")


def _infer_period(buy_df):
    """[min(마켓주문일자) − 3일, max + 3일]. 날짜를 하나도 못 읽으면 (None, None)."""
    col = buy_df.get("마켓주문일자")
    dates = [d for d in (_parse_date(v) for v in (col if col is not None else []))
             if d is not None]
    if not dates:
        return None, None
    margin = _dt.timedelta(days=PERIOD_MARGIN_DAYS)
    return min(dates) - margin, max(dates) + margin


def _json_normalize(o):
    """numpy 스칼라 → 파이썬 기본형, NaN/Inf → 0. jsonify + store._pack(allow_nan=False)
    양쪽을 한 번에 통과시킨다. aggregator(바이트-정확 추출)를 건드리지 않고 라우트에서 방어.
    (실측: 260704 데이터의 aggregate 출력엔 numpy 스칼라 0개지만, group 키 등 이론적
    구멍을 여기서 닫는다.)"""
    if isinstance(o, dict):
        return {k: _json_normalize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_normalize(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return 0
    return o


def _put_object(data: bytes, key: str, content_type: str) -> str:
    """R2 업로드 seam — 테스트에서 monkeypatch. 저장한 key 를 반환."""
    from shared import storage
    storage.put_object(data, key, content_type)
    return key


def _r2_key(filename: str) -> str:
    safe = (filename or "file.xlsx").replace("/", "_").replace("\\", "_")
    return f"margin/{_dt.date.today():%Y%m}/{uuid.uuid4().hex}_{safe}"


def _created_by():
    try:
        from flask_login import current_user
        return getattr(current_user, "email", None)
    except Exception:  # noqa: BLE001  (bare Flask 테스트 앱엔 login manager 없음)
        return None


def _iso(d):
    return d.isoformat() if d is not None else None


def _row_meta(row) -> dict:
    return {
        "id": row.id,
        "created_at": _iso(row.created_at),
        "period_from": _iso(row.period_from),
        "period_to": _iso(row.period_to),
        "buy_filename": row.buy_filename,
        "shopmine_filename": row.shopmine_filename,
        "markets_fetched": row.markets_fetched,
        "markets_failed": row.markets_failed,
        "counts": row.counts,
    }


# ── 업로드 ────────────────────────────────────────────────────────────────

@bp.route("/upload", methods=["POST"])
def upload():
    """더망고 매입 엑셀 → 파싱 + 기간 자동 추론. 분석은 하지 않는다."""
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "파일이 없습니다 (field 'file')."}), 400
    raw = f.read()
    try:
        buy_df = parse_buy(raw, f.filename or "buy.xlsx")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    pf, pt = _infer_period(buy_df)
    markets = sorted(
        {str(m).strip() for m in buy_df.get("마켓명", []) if str(m).strip()})

    # 새 매입 업로드는 이전에 스테이징된 샵마인을 반드시 비운다(stale 방지, 규칙 §6).
    _PENDING.clear()
    _PENDING["buy"] = {
        "df": buy_df, "bytes": raw, "filename": f.filename or "buy.xlsx",
        "period_from": pf, "period_to": pt,
    }
    return jsonify({
        "rows": int(len(buy_df)),
        "markets": markets,
        "period_from": _iso(pf),
        "period_to": _iso(pt),
    })


@bp.route("/upload-shopmine", methods=["POST"])
def upload_shopmine():
    """옥션·G마켓 등 보조 매출 엑셀(샵마인 포맷) 스테이징. 선택 사항."""
    if "buy" not in _PENDING:
        return jsonify({"error": "먼저 더망고 매입 엑셀을 업로드하세요."}), 400
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "파일이 없습니다 (field 'file')."}), 400
    raw = f.read()
    try:
        sell_df = sell_source.from_shopmine_excel(raw, f.filename or "shopmine.xlsx")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    _PENDING["shopmine"] = {
        "df": sell_df, "bytes": raw, "filename": f.filename or "shopmine.xlsx",
    }
    markets = sorted(
        {str(m).strip() for m in sell_df.get("쇼핑몰", []) if str(m).strip()})
    return jsonify({"rows": int(len(sell_df)), "markets": markets})


# ── 분석 ──────────────────────────────────────────────────────────────────

@bp.route("/analyze", methods=["POST"])
def analyze():
    """마켓 API 조회 + 선택 샵마인 concat → pipeline → aggregate → R2 + DB 저장."""
    staged = _PENDING.get("buy")
    if not staged:
        return jsonify({"error": "먼저 더망고 매입 엑셀을 업로드하세요."}), 400

    body = request.get_json(silent=True) or {}
    since = _parse_dt(body.get("since") or staged["period_from"])
    until = _parse_dt(body.get("until") or staged["period_to"])

    # 1) 마켓 조회를 가장 먼저 — 한 마켓이라도 실패하면 502 로 전체 중단, 아무것도 저장 안 함.
    try:
        sell_df = sell_source.from_api(since, until)
    except Exception as e:  # noqa: BLE001
        return jsonify({
            "error": f"마켓 주문 조회 실패 — 분석을 중단했습니다: {e}",
            "stage": "from_api",
        }), 502
    warnings = list(sell_df.attrs.get("warnings", []) or [])

    # 선택 샵마인 보조 매출 concat
    shop = _PENDING.get("shopmine")
    if shop is not None:
        sell_df = pd.concat([sell_df, shop["df"]], ignore_index=True)

    # 2) 매칭 + 집계
    out = pipeline.run(staged["df"], sell_df)
    agg = aggregator.aggregate(out["matched"], DEFAULT_PRICE_RANGES)
    payload = _json_normalize({**out, **agg})
    matched = payload["matched"]

    counts = {
        "matched": len(matched),
        "unmatched_buy": len(payload.get("unmatched_buy", [])),
        "unmatched_sell": len(payload.get("unmatched_sell", [])),
        "buy_missing": len(payload.get("buy_missing", [])),
        # ★ matched(분석된 행) 기준. sell_df(조회된 행) 기준이 아니다 (스펙 §5).
        "settle_estimated": sum(
            1 for r in matched if r.get("_settle_source") == "estimated"),
        "settle_unknown": int(out["settle_unknown"]),
        "nan_coerced": int(out["nan_coerced"]),
    }

    # 3) R2 업로드 — 조회 성공 뒤에만. (실패 run 이 R2 고아를 남기지 않도록 순서 고정)
    buy_key = _put_object(staged["bytes"], _r2_key(staged["filename"]), _XLSX_CT)
    shop_key = shop_name = None
    if shop is not None:
        shop_key = _put_object(shop["bytes"], _r2_key(shop["filename"]), _XLSX_CT)
        shop_name = shop["filename"]

    # 4) DB 저장
    session = SessionLocal()
    try:
        row = store.save(
            session, payload=payload,
            period_from=since.date(), period_to=until.date(),
            buy_file_key=buy_key, buy_filename=staged["filename"],
            shopmine_file_key=shop_key, shopmine_filename=shop_name,
            markets_fetched=list(sell_source.API_MARKETS),
            markets_failed=warnings, counts=counts,
            created_by=_created_by(),
        )
        analysis_id = row.id
    finally:
        session.close()

    return jsonify({
        "analysis_id": analysis_id,
        "counts": counts,
        "markets_failed": warnings,
        "period_from": _iso(since.date()),
        "period_to": _iso(until.date()),
        **payload,
    })


# ── 목록 / 로드 / 삭제 ─────────────────────────────────────────────────────

@bp.route("/analyses", methods=["GET"])
def analyses_list():
    session = SessionLocal()
    try:
        return jsonify([_row_meta(r) for r in store.list_recent(session)])
    finally:
        session.close()


@bp.route("/analyses/<int:analysis_id>", methods=["GET"])
def analyses_get(analysis_id):
    session = SessionLocal()
    try:
        row = store.get(session, analysis_id)
        if row is None:
            return jsonify({"error": "분석을 찾을 수 없습니다."}), 404
        payload = store.load(session, analysis_id)
        return jsonify({**_row_meta(row), "payload": payload})
    finally:
        session.close()


@bp.route("/analyses/<int:analysis_id>", methods=["DELETE"])
def analyses_delete(analysis_id):
    session = SessionLocal()
    try:
        store.delete(session, analysis_id)
        return jsonify({"ok": True})
    finally:
        session.close()


# ── 엑셀 내보내기 ──────────────────────────────────────────────────────────

@bp.route("/export", methods=["POST"])
def export_route():
    """{analysis_id, tab, rows?, column_order?} → xlsx 다운로드."""
    body = request.get_json(silent=True) or {}
    aid = body.get("analysis_id")
    if aid is None:
        return jsonify({"error": "analysis_id 가 필요합니다."}), 400
    session = SessionLocal()
    try:
        payload = store.load(session, int(aid))
    except LookupError:
        return jsonify({"error": "분석을 찾을 수 없습니다."}), 404
    finally:
        session.close()

    data = export.to_xlsx(
        payload, tab=body.get("tab", "all"),
        rows=body.get("rows"), column_order=body.get("column_order"))
    return send_file(
        io.BytesIO(data), mimetype=_XLSX_CT, as_attachment=True,
        download_name=f"마진분석_{aid}.xlsx")

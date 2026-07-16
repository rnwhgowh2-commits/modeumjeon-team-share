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
import logging
import math
import uuid

import numpy as np
import pandas as pd
from flask import Blueprint, jsonify, request, send_file

from shared.db import SessionLocal
from lemouton.margin import aggregator, export, pipeline, store
from lemouton.margin import sell_source
from lemouton.margin import keyword_store
from lemouton.margin import matcher, classifier
from lemouton.margin.card_counts import compute_card_counts
from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.config import DEFAULT_PRICE_RANGES

logger = logging.getLogger(__name__)

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
    """numpy 스칼라 → 파이썬 기본형. jsonify 와 store._pack 양쪽을 통과시킨다.

    NaN/Inf 는 여기서 0 으로 덮지 않는다 — 덮으면 (a) store._pack(allow_nan=False) 의
    경보가 영원히 울리지 않고 (b) pipeline 이 세는 nan_coerced 와 달리 소리 없이 사라지며
    (c) summary 의 NaN 은 '합계가 0'이 아니라 '합계가 틀렸다'는 뜻이다.
    NaN 은 _assert_finite 가 경로를 짚어 크게 실패시킨다.
    """
    if isinstance(o, dict):
        return {k: _json_normalize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_normalize(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    return o


def _assert_finite(o, path="payload"):
    """NaN/Inf 를 경로와 함께 크게 실패시킨다. 조용한 0 으로 덮지 않는다."""
    if isinstance(o, dict):
        for k, v in o.items():
            _assert_finite(v, f"{path}.{k}")
    elif isinstance(o, (list, tuple)):
        for i, v in enumerate(o):
            _assert_finite(v, f"{path}[{i}]")
    elif isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        raise ValueError(f"계산 불가능한 값(NaN/Inf)이 {path} 에 있습니다")


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


# ── 블랙스팟 분류 계약 복원 (원본 app.py /api/analyze) ─────────────────────

def _has_trace(r: dict) -> bool:
    """raw 매입 흔적 판정 — 원본 app.py 1356~1374 그대로.

    구매가격 float>0(≠999999999.99 센티널) OR 국내송장번호 OR 사이트주문번호 OR
    간단메모에 http/HTTP OR 더망고주문상태(사용자 연동)에 배송대기중/국내배송중.
    """
    def _v(x):
        s = str(x or "").strip()
        return bool(s) and s not in ("nan", "0", "0.0", "None")

    try:
        buy = float(str(r.get("구매가격", 0)).replace(",", "") or 0)
        if buy > 0 and buy != 999999999.99:
            return True
    except (ValueError, TypeError):
        pass
    if _v(r.get("국내송장번호")) or _v(r.get("사이트주문번호")):
        return True
    memo = str(r.get("간단메모", "") or "")
    if "http" in memo or "HTTP" in memo:
        return True
    mg = str(r.get("더망고주문상태 (사용자 연동)", "") or "")
    if any(k in mg for k in ("배송대기중", "국내배송중")):
        return True
    return False


def _augment_blackspot(payload, buy_df, sell_df, out):
    """원본 app.py `/api/analyze`(1334~1422) 계약 복원 — payload 를 제자리 보강한다.

    추가/변경:
      · classified / blackspot_summary — 분류기 실행 결과.
      · unmatched_buy — 분류기 밖 매입흔적 raw 행 보강(원본 1336~1387).
      · summary.mango_total / mango_with_order_no / mango_with_trace — 검증 카운트(1401~1418).
      · missing_order_no — G열 미기입 매입 행(1419~1422).

    ★ finite 가드: classified·보강행은 matcher.match_for_classifier 의 raw .to_dict()
      에서 와 빈 셀이 NaN(float) 로 남는다. 라우트가 저장 전 _assert_finite 로 NaN 을 크게
      실패시키므로, buy_missing 과 동일하게 pipeline._json_safe(coerce_numeric=False) 로
      '표시 전용'(하류 집계 없음) NaN→"" 정리해 통과시킨다. (원본은 finite 가드 없이 저장했다.)

    ★ 분류기 입력 = buy_valid(사이트주문번호 있는 행) — 원본 app.py 355행과 동일.
      full staged df 를 넣으면 buy_missing 흔적행까지 classified 에 들어가 보강 로직이
      죽는다(match_data 가 모든 매입행을 matched/unmatched 로 이미 덮으므로).
    """
    # counter 는 _json_safe 의 nan_coerced 집계용이나 여기선 coerce_numeric=False(표시 전용,
    # NaN→"") 라 절대 증가하지 않는다 — 의도적으로 버린다. 훗날 coerce_numeric=True 로
    # 바꾸면 이 집계가 살아나야 하므로 인자는 계속 넘긴다(값만 무시).
    counter = [0]

    buy_valid, _buy_missing = pipeline.split_by_site_order_no(buy_df)
    mc = matcher.match_for_classifier(buy_valid, sell_df)
    cls = classifier.classify(mc["matched"], mc["mango_unmatched"], mc["shopmine_only"])
    classified = [pipeline._json_safe(r, False, counter) for r in cls["classified"]]
    payload["classified"] = classified
    payload["blackspot_summary"] = cls["summary"]

    # unmatched_buy 매입흔적 보강 (원본 1336~1387) — classified 밖 흔적행을 전체내역에 노출.
    # 원본 1340행처럼 classified 가 비면(전량 buy_missing 인 퇴화 케이스) 보강을 건너뛴다.
    unmatched_buy_list = list(payload.get("unmatched_buy") or [])
    if classified:
        existing_keys = set()
        for r in payload.get("matched") or []:
            mk = str(r.get("마켓주문번호", "")).strip()
            if mk:
                existing_keys.add(mk)
        for r in unmatched_buy_list:
            mk = str(r.get("마켓주문번호", "")).strip()
            if mk:
                existing_keys.add(mk)
        for r in classified:
            if r.get("데이터출처") in ("더망고+샵마인", "더망고만"):
                mk = str(r.get("마켓주문번호", "")).strip()
                if mk:
                    existing_keys.add(mk)

        for _, raw_row in buy_df.iterrows():
            raw_dict = raw_row.to_dict()
            mk = str(raw_dict.get("마켓주문번호", "")).strip()
            if not mk or mk in existing_keys:
                continue
            if _has_trace(raw_dict):
                unmatched_buy_list.append(pipeline._json_safe(raw_dict, False, counter))
                existing_keys.add(mk)
    payload["unmatched_buy"] = unmatched_buy_list

    # 블랙스팟 카드 집계 — 원본 app.py:1532 `_compute_card_counts(store['matched'], source='matched')` 이식.
    #   ★ source='matched' 로 원본 서버 계약을 그대로 재현한다. out["matched"] = match_data(full 더망고)
    #     + _주문미이행/_매입흔적 플래그(pipeline.run) = 원본 store['matched'] 와 동일 구성.
    #   ★ source='classified' 를 쓰면 안 된다: classified 행엔 분류기가 매긴 상세분류(1-1_정상거래 등)가
    #     실려 코드 기반 분기(is_normal_code)가 되살아나 정상 카드가 부풀고 기타가 0 이 된다
    #     (원본 스크린샷은 상세분류 없는 matched 로 메모·상태 분기만 → 정상 49·기타 19). 실측 검증 완료.
    #   ★ 표시 카드 타일은 페이지 JS `_getRowsByCardFilter`(matched+가상행) 가 단일 진실 원천이며 이 함수와
    #     바이트 동치(260704 골든). 서버 summary.card_* 는 배너 폴백·export·API 소비자용.
    #   ★ 팀 카드 키워드(cards) 주입 — 원본 load_card_keywords() 대체(DB 세션 격리).
    _cc_session = SessionLocal()
    try:
        _cc_kw = keyword_store.get_config(_cc_session).get("cards") or {}
    finally:
        _cc_session.close()
    summary = payload.setdefault("summary", {})
    summary.update(compute_card_counts(out.get("matched", []), source="matched", card_kw=_cc_kw))

    # 검증 카운트 (원본 1401~1418) — summary 에 주입.
    summary["mango_total"] = int(len(buy_df))
    # buy_valid = 전체 − buy_missing. split 은 partition 이므로 len 차 = buy_valid 수(원본과 동일).
    summary["mango_with_order_no"] = int(len(buy_df) - len(out.get("buy_missing", [])))
    summary["mango_with_trace"] = int(summary.get("card_all", 0))

    # G열 미기입 매입 행 (원본 1419~1422) — 이미 JSON-safe records.
    payload["missing_order_no"] = out.get("buy_missing", [])


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
    # 2b) 블랙스팟 분류 계약 복원 — classified·blackspot_summary·검증 카운트·흔적 보강.
    #     NaN 을 품은 raw 행은 _augment 내부에서 표시전용 sanitize → 아래 finite 가드 통과.
    _augment_blackspot(payload, staged["df"], sell_df, out)
    # ★ 팀 공유 카드 키워드를 summary 에 주입 — 원본 app.py:879 미러.
    #   페이지의 _getCardKeywords() 는 window.analysisData.summary._card_keywords 를
    #   읽는다 → 매 분석마다 팀 DB 값을 실어야, 편집 없이도 팀 설정이 즉시 반영된다.
    #   (여기서 안 실으면 페이지 내장 폴백으로 떨어져 팀 DB 가 무력화된다.)
    #   카드 값은 문자열/리스트뿐 → _assert_finite 안전.
    #   ★ 비어 있으면 아무것도 싣지 않는다: 페이지의 _getCardKeywords() 는 truthy 값을
    #     그대로 쓰는데 JS 는 {} 도 truthy → 빈 dict 를 실으면 페이지 내장 폴백(기본
    #     키워드맵)을 가로채 모든 키워드 조회가 [] 가 되고 블랙스팟 버킷팅이 조용히
    #     실패한다. 빈 cards 는 의도적 {cards:{}} POST 로만 도달 → 그땐 폴백을 살린다.
    _kw_session = SessionLocal()
    try:
        _cards = keyword_store.get_config(_kw_session).get("cards") or {}
    finally:
        _kw_session.close()
    if _cards:
        payload.setdefault("summary", {})["_card_keywords"] = _cards
    # NaN/Inf 는 저장 전에 크게 실패시킨다 — 조용한 0 으로 덮지 않는다(store._pack 경보 보존).
    try:
        _assert_finite(payload)
    except ValueError as e:
        logger.error("마진 분석 결과에 NaN/Inf — 저장하지 않음", exc_info=True)
        return jsonify({"error": f"분석 결과를 저장할 수 없습니다: {e}"}), 500
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


# ── 크롤 정산 수집(ingest) ──────────────────────────────────────────────────

@bp.route("/lotteon-settlement", methods=["POST"])
def lotteon_settlement_ingest():
    """크롤러 push: [{odNo, odSeq, pymtTgtAmt, slChNo, trNo}] → (od_no,od_seq)별 upsert."""
    from lemouton.sourcing.models_v2 import LotteonSettlement
    rows = request.get_json(silent=True) or []
    if not isinstance(rows, list):
        return jsonify({"error": "list 필요"}), 400
    n = 0
    with SessionLocal() as s:
        for r in rows:
            od = str(r.get("odNo") or "").strip()
            if not od:
                continue
            seq = str(r.get("odSeq") or "1")
            try:
                amt = int(round(float(r.get("pymtTgtAmt") or 0)))
            except (TypeError, ValueError):
                continue
            obj = s.get(LotteonSettlement, {"od_no": od, "od_seq": seq})
            if obj is None:
                obj = LotteonSettlement(od_no=od, od_seq=seq)
                s.add(obj)
            obj.pymt_tgt_amt = amt
            obj.sl_chnl = r.get("slChNo") or None
            obj.tr_no = r.get("trNo") or None
            n += 1
        s.commit()
    return jsonify({"upserted": n})


@bp.route("/_probe_11_settle", methods=["GET"])
def _probe_11_settle():
    """[임시] 11번가 settlementList 라인 부호·중복키 확인 — 반품 라인이 양수로 끼어
    같은 (ordNo,ordPrdSeq) 이중계상되는지(쿠팡 REFUND 버그 유무) 진단. 확인 후 제거."""
    import datetime as _d
    from lemouton.markets.order_export import _active_accounts
    from lemouton.uploader import market_fetch as _mf
    from shared.platforms.eleven11 import settlement as _st
    from shared.platforms.eleven11.orders import _localname, _parse
    days = int(request.args.get("days") or 25)
    until = _d.datetime.now()
    since = until - _d.timedelta(days=min(days, 31))
    out = {"accounts": [], "neg_lines": [], "dup_keys": [], "sample": [], "err": None}
    accs = _active_accounts("eleven11") or [(None, "default")]
    try:
        seen = {}
        for env_prefix, name in accs:
            client = _mf._eleven11_client(env_prefix)
            cnt = {"name": name, "lines": 0, "neg": 0}
            for w_from, w_to in _st._windows(since, until):
                path = _st._PATH.format(s=_st._fmt(w_from), e=_st._fmt(w_to))
                xml = client.request("GET", path)
                root = _parse(xml)
                if root is None:
                    continue
                for el in root.iter():
                    entry = {}
                    for child in el:
                        entry[_localname(child.tag)] = (child.text or "").strip()
                    ordno, stl = entry.get("ordNo"), entry.get("stlAmt")
                    if not ordno or stl in (None, "", "null"):
                        continue
                    cnt["lines"] += 1
                    sp, dd = entry.get("selPrcAmt"), entry.get("deductAmt")
                    key = ordno + "|" + (entry.get("ordPrdSeq") or "")
                    seen[key] = seen.get(key, 0) + 1
                    try:
                        spf = float(sp) if sp not in (None, "", "null") else None
                    except ValueError:
                        spf = None
                    is_neg = (spf is not None and spf < 0) or (float(stl or 0) < 0)
                    if is_neg:
                        cnt["neg"] += 1
                        if len(out["neg_lines"]) < 8:
                            out["neg_lines"].append({"ordNo": ordno, "selPrcAmt": sp,
                                                     "deductAmt": dd, "stlAmt": stl})
                    if len(out["sample"]) < 4:
                        out["sample"].append({"ordNo": ordno, "ordPrdSeq": entry.get("ordPrdSeq"),
                                              "selPrcAmt": sp, "deductAmt": dd, "stlAmt": stl})
            out["accounts"].append(cnt)
        out["dup_keys"] = [{"key": k, "count": v} for k, v in seen.items() if v > 1][:12]
    except Exception as e:  # noqa: BLE001
        out["err"] = repr(e)
    return jsonify(out)

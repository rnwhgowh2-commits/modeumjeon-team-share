# -*- coding: utf-8 -*-
r"""마진 분석 라우트 — `/api/margin/*`.

흐름: 더망고 매입 엑셀 업로드(기간 자동 추론) → analyze(마켓 API 조회 → pipeline →
aggregate → R2 + DB 저장) → 목록/로드/삭제/엑셀 내보내기.

원본 로직: C:\dev\대량등록 마진계산기\app.py 의 /api/analyze·/api/download.

■ 저장 순서(중요) — 마켓 조회를 **가장 먼저** 한다. 조회 실패(502)면 R2 업로드도 DB
  저장도 하지 않는다. 실패한 마켓의 매입 행이 전부 '매출 미매칭'으로 둔갑해 블랙스팟처럼
  보이는 적극적 오신호를 막기 위함(스펙 §9). 실패한 run 은 GET /analyses 에 남지 않는다.

■ settle_estimated 는 **matched**(분석된 행) 기준으로 센다. sell_df(조회된 행) 기준이
  아니다 — 사용자가 궁금한 건 '내 분석 결과 중 추정치에 기댄 게 몇 건인가'다(스펙 §5).

■ 업로드→분석 스테이징은 **DB 단일 행**(margin.pending_store)이다. 예전엔 이 모듈의
  전역 dict 였는데, 앱이 gunicorn 워커 3개로 돌아 업로드(A워커)와 분석(B워커)이 갈리면
  "먼저 더망고 매입 엑셀을 업로드하세요"가 떴다(2026-07-23 실제 사고 — 분석 전에 마켓별
  수집 6요청이 끼면서 워커가 갈릴 확률이 올라가 재현됨).
  워커가 여럿이면 프로세스 전역 변수는 '저장'이 아니다.
  동시에 둘이 올리면 마지막 업로더가 이긴다 — 팀 공유 단일 행이라 기존과 같은 성질이다.
"""
import datetime as _dt
import gc
import io
import logging
import math
import threading
import uuid

import numpy as np
from flask import Blueprint, jsonify, request, send_file

from shared.db import SessionLocal
from lemouton.margin import aggregator, export, pipeline, store
from lemouton.margin import sell_source
from lemouton.margin import settle_status
from lemouton.margin import keyword_store
from lemouton.margin import analyze_job_store
from lemouton.margin import matcher, classifier
from lemouton.margin.card_counts import compute_card_counts
from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.config import DEFAULT_PRICE_RANGES

logger = logging.getLogger(__name__)

bp = Blueprint("api_margin", __name__, url_prefix="/api/margin")


@bp.errorhandler(Exception)
def _always_json_error(e):
    """[2026-08-26] 미처리 예외가 HTML 500 페이지로 새면 margin_embed.html 의
    startAnalysis()가 res.json() 파싱에 실패해 이유 없이 "서버 오류"만 뜬다 — 같은
    문제를 이미 겪은 /api/sources/parse(O13)와 동일 패턴으로 이 blueprint 한정
    항상 JSON 응답을 보장한다.
    (프록시/컨테이너 메모리 상한(OOM)으로 연결 자체가 끊기는 경우는 Flask 밖이라
     이걸로는 못 잡는다 — 그건 별도로 컨테이너 메모리 여유를 확보해야 한다.)"""
    from werkzeug.exceptions import HTTPException
    code = e.code if isinstance(e, HTTPException) else 500
    if code == 500:
        logger.error("마진 API 처리 중 미처리 예외", exc_info=True)
    return jsonify({"error": f"{type(e).__name__}: {e}"[:300]}), code

PERIOD_MARGIN_DAYS = 3
_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

from lemouton.margin import pending_store


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
        "markets_fetched": row.markets_fetched,
        "markets_failed": row.markets_failed,
        "counts": row.counts,
    }


# ── 업로드 ────────────────────────────────────────────────────────────────

@bp.route("/margin/diag/match-probe")
def margin_match_probe():
    """[읽기 전용] 주문번호가 매출(마켓 API 저장분)에 있는지 진단 — 미매칭 원인 판별.

    사장님 신고(2026-07-30): 스스 주문 6건이 마진계산기에서 미매칭. 로컬 대조 결과
    더망고 원본·매칭 후보키·마켓 저장분 모두 정상(16자리 일치, 5/6건 존재)이라
    **주문번호 문제가 아니다**. 매출 조회 단계에서 빠지는지 갈라 보기 위한 창구.

    `?orders=번호,번호&from=YYYY-MM-DD&to=YYYY-MM-DD`
    응답은 존재 여부·상태·금액뿐 — 고객정보는 담지 않는다.
    """
    from flask import jsonify, request as _rq
    want = [o.strip() for o in (_rq.args.get("orders") or "").split(",") if o.strip()]
    if not want:
        return jsonify(ok=False, error="orders=번호,번호 가 필요해요."), 400
    import datetime as _dt

    def _d(v, dflt):
        try:
            return _dt.datetime.strptime(v, "%Y-%m-%d")
        except Exception:   # noqa: BLE001
            return dflt

    until = _d(_rq.args.get("to") or "", _dt.datetime.now())
    since = _d(_rq.args.get("from") or "", until - _dt.timedelta(days=30))
    from lemouton.margin import sell_source as _ss
    try:
        df = _ss.from_api(since, until)
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    keys = (df["오픈마켓주문번호"].astype(str).str.strip().tolist()) if len(df) else []
    kset = set(keys)
    by_mall = {}
    if len(df):
        for mall, grp in df.groupby(df["쇼핑몰"].astype(str)):
            by_mall[str(mall)] = len(grp)
    # 같은 주문번호가 매출에 여러 행이면 앞 매입이 선점해 뒤 매입이 미매칭될 수 있다.
    dup = {}
    if len(df):
        vc = df["오픈마켓주문번호"].astype(str).str.strip().value_counts()
        dup = {k: int(v) for k, v in vc.items() if k in set(want) and v > 1}
    found = []
    for w in want:
        val = None
        if w in kset:
            r = df[df["오픈마켓주문번호"].astype(str).str.strip() == w].iloc[0]
            val = {"쇼핑몰": str(r.get("쇼핑몰", "")), "주문상태": str(r.get("주문상태", "")),
                   "실결제금액": str(r.get("실결제금액", "")),
                   "정산예상금액_배송비포함": str(r.get("정산예상금액_배송비포함", ""))}
        found.append({"주문번호": w, "매출에있음": w in kset, "값": val})
    # 실제 매칭을 돌려 어느 단계에서 떨어지는지 본다(staged 더망고가 있을 때만).
    sim = {}
    try:
        _s2 = SessionLocal()
        try:
            staged = pending_store.get(_s2)
        finally:
            _s2.close()
        if staged and staged.get("buy_bytes"):
            from lemouton.margin.buy_parser import parse_buy as _pb
            from lemouton.margin.matcher import match_data as _md, order_match_keys as _omk
            bdf = _pb(staged["buy_bytes"], staged.get("buy_filename") or "buy.xlsx")
            m, ub, us = _md(bdf, df)
            mk = {str(r.get("마켓주문번호", "")) for r in m}
            sim["매칭수"] = len(m)
            sim["미매칭매입"] = len(ub)
            sim["미매칭매출"] = len(us)
            per = []
            for w in want:
                brow = bdf[bdf["마켓주문번호"].astype(str).str.contains(w, na=False)]
                cand = _omk(str(brow.iloc[0]["마켓주문번호"]), str(brow.iloc[0]["마켓명"])) if len(brow) else []
                per.append({"주문번호": w, "더망고행": len(brow), "후보키": cand,
                            "매칭됨": w in mk})
            sim["건별"] = per
            # 화면과 같은 경로(pipeline.run)로도 돌려 본다 — match_data 만으로는
            # 화면 재현이 안 될 수 있다(split_by_site_order_no·플래그·json_safe 등).
            try:
                from lemouton.margin import pipeline as _pl
                out2 = _pl.run(bdf, df)
                mk2 = {str(r.get("마켓주문번호", "")) for r in (out2.get("matched") or [])}
                ub2 = [str(r.get("마켓주문번호", "")) for r in (out2.get("unmatched_buy") or [])]
                sim["파이프라인시뮬"] = {
                    "매칭수": len(out2.get("matched") or []),
                    "미매칭매입": len(out2.get("unmatched_buy") or []),
                    "건별": [{"주문번호": w, "매칭됨": w in mk2,
                              "미매칭매입에": any(w in k for k in ub2)} for w in want],
                }
            except Exception as e2:   # noqa: BLE001
                sim["파이프라인시뮬"] = {"오류": f"{type(e2).__name__}: {str(e2)[:200]}"}
    except Exception as e:   # noqa: BLE001 — 진단이 본 응답을 막지 않는다
        sim["오류"] = f"{type(e).__name__}: {str(e)[:200]}"

    return jsonify(ok=True, 기간=f"{since.date()}~{until.date()}",
                   매출행수=len(df), 쇼핑몰별=by_mall, 결과=found,
                   매출중복=dup, 매칭시뮬=sim, 샘플키=keys[:5])


@bp.route("/margin/diag/eleven11-order-fact")
def margin_diag_eleven11_order_fact():
    """[읽기 전용] 11번가 실제 API 기준 진단 — 저장분(_settle_paid_date)이 아니라
    지금 이 순간 11번가가 실제로 뭐라고 답하는지를 직접 물어본다.

    2026-09-06 사장님 신고: 마진계산기가 취소완료 주문 2건을 "정산O"로 표시.
    settle_status.py 의 verdict 는 저장된 `_settle_paid_date`(과거 한 번 기록되면
    안 지워짐)만 보므로, 실제로 "정산 받은 게 맞는지" 는 라이브 API 를 다시
    불러야 확인된다 — 저장분 대조가 아니라 소싱처/판매처 실물 확인 원칙과 동일.

    반환: 계정별 ① 지금 주문상태(fetch_order_status) ② 지정 구간의 정산 실값
    (settlement_detail_map, ordNo 일치분 전체 ordPrdSeq). 고객정보는 담지 않는다.

    `?orders=번호,번호[&since=YYYY-MM-DD][&until=YYYY-MM-DD]`
    (since 생략 시 각 주문번호 앞 40일부터 — 주문번호가 여러 개면 그중 가장 이른
    주문일을 모르므로 90일 전부터 안전하게 잡는다.)
    """
    want = [o.strip() for o in (request.args.get("orders") or "").split(",") if o.strip()]
    if not want:
        return jsonify(ok=False, error="orders=번호,번호 가 필요해요."), 400

    def _d(v, dflt):
        try:
            return _dt.datetime.strptime(v, "%Y-%m-%d")
        except Exception:   # noqa: BLE001
            return dflt

    now = _dt.datetime.now()
    until = _d(request.args.get("until") or "", now)
    since = _d(request.args.get("since") or "", now - _dt.timedelta(days=180))

    from lemouton.markets.order_ingest import _esm_settlement_clients
    from shared.platforms.eleven11 import orders as _el_orders, settlement as _el_settle

    clients = _esm_settlement_clients("eleven11")
    if not clients:
        return jsonify(ok=False, error="11번가 등록 계정이 없어요."), 400

    results = {onno: {"현재주문상태(계정별)": {}, "정산실값(계정별)": {}} for onno in want}
    for name, cli in clients:
        acc = name or "대표"
        for onno in want:
            try:
                results[onno]["현재주문상태(계정별)"][acc] = _el_orders.fetch_order_status(
                    onno, client=cli)
            except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
                results[onno]["현재주문상태(계정별)"][acc] = f"조회실패: {type(e).__name__}: {e}"
        try:
            smap = _el_settle.settlement_detail_map(since, until, client=cli)
        except Exception as e:   # noqa: BLE001
            for onno in want:
                results[onno]["정산실값(계정별)"].setdefault(acc, []).append(
                    f"조회실패: {type(e).__name__}: {e}")
            continue
        for (ord_no, seq), ent in smap.items():
            if ord_no in want:
                results[ord_no]["정산실값(계정별)"].setdefault(acc, []).append(
                    {"ordPrdSeq": seq, **ent})

    return jsonify(ok=True, 조회구간=f"{since.date()}~{until.date()}", 결과=results)


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

    _sess = SessionLocal()
    try:
        pending_store.stage_buy(_sess, raw=raw, filename=f.filename or "buy.xlsx",
                                period_from=pf, period_to=pt)
    finally:
        _sess.close()
    shared = _share_to_purchase_store(buy_df, f.filename or "buy.xlsx")
    return jsonify({
        "rows": int(len(buy_df)),
        "markets": markets,
        "period_from": _iso(pf),
        "period_to": _iso(pt),
        # 주문 내역·상품관리와 **같은 값**을 쓰기 위해 같이 저장한 결과(설계서 §8).
        "shared": shared,
    })


def _share_to_purchase_store(buy_df, filename: str) -> dict:
    """마진 계산기에 올린 매입 엑셀을 **실매입가 단일 원천에도** 저장한다.

    [중요] 왜 필요한가 — 사장님 확정 규칙 6 「실매입가가 입력되면 실마진이 필요한 곳에
      데이터 공유한다」. 여기서 안 하면 같은 엑셀을 올려도 **마진 계산기만 알고
      주문 내역·상품관리는 모르는** 상태가 되어 같은 상품 마진이 화면마다 갈린다
      (설계서 §8 「같은 정보 두 화면 = 같은 값」).

    · 저장 경로는 주문 내역 업로드와 **완전히 같은 코드**(`purchase_mango.apply`)다 —
      규칙을 두 번 구현하지 않는다. 후보가 여럿이면 저장하지 않는 것도 그대로다.
    · [중요] 실패해도 업로드를 되돌리지 않는다. 대신 `error` 를 담아 **조용히 넘어가지 않는다**.
    """
    from lemouton.markets import order_store as _os
    from lemouton.markets import purchase_mango as _pm

    try:
        order_nos = _pm.order_keys_from_buy(buy_df)
        if not order_nos:
            return {"saved": 0, "matched": 0,
                    "error": "엑셀에 마켓주문번호가 없어 주문 줄에 붙이지 못했어요."}
        s = SessionLocal()
        try:
            rows = _os.load(order_nos=order_nos, include_claims=False, session=s)
            res = _pm.apply(s, buy_df, rows, filename=filename,
                            reason="margin")
        finally:
            s.close()
        if res.get("saved"):
            try:
                from webapp.routes.orders import _invalidate_tower_sales
                _invalidate_tower_sales(
                    f"마진 계산기 매입 엑셀 {filename} — {res['saved']}줄 공유 저장")
            except Exception:   # noqa: BLE001 — 캐시 비우기 실패가 저장을 되돌리면 안 된다
                logger.exception("판매 이력 캐시 무효화 실패 (도장으로는 갱신됨)")
        return {"saved": int(res.get("saved") or 0),
                "matched": int(res.get("matched") or 0),
                "unmatched": len(res.get("unmatched") or []),
                "ambiguous": len(res.get("ambiguous") or []),
                "skipped_zero": len(res.get("skipped_zero") or [])}
    except Exception as e:   # noqa: BLE001
        logger.exception("매입 엑셀 공유 저장 실패 %s", filename)
        return {"saved": 0, "matched": 0,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}


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


def _order_keys_for_dedup(order_no, market_name) -> list:
    """중복 판정용 주문번호 후보 — matcher 와 **같은 규칙**(괄호 안/밖 둘 다).

    matched 행은 매칭에 쓴 키만 갖고 있어 더망고 원본 'A(B)' 와 글자가 다르다.
    같은 규칙으로 후보를 펴야 "이미 매칭된 건"을 정확히 걸러낸다.
    """
    mk = str(order_no or "").strip()
    if not mk:
        return []
    try:
        from lemouton.margin.matcher import order_match_keys
        keys = list(order_match_keys(mk, market_name) or [])
    except Exception:   # noqa: BLE001 — 매칭 규칙을 못 읽어도 원본 키로는 거른다
        keys = []
    if mk not in keys:
        keys.append(mk)
    return keys


def _augment_blackspot(payload, buy_df, sell_df, out):
    """원본 app.py `/api/analyze`(1334~1422) 계약 복원 — payload 를 제자리 보강한다.

    추가/변경:
      · classified / blackspot_summary — 분류기 실행 결과.
      · unmatched_buy — 분류기 밖 매입흔적 raw 행 보강(원본 1336~1387).
      · summary.mango_total / mango_with_order_no / mango_with_trace — 검증 카운트(1401~1418).
      · missing_order_no — G열 미기입 매입 행(1419~1422).

     finite 가드: classified·보강행은 matcher.match_for_classifier 의 raw .to_dict()
      에서 와 빈 셀이 NaN(float) 로 남는다. 라우트가 저장 전 _assert_finite 로 NaN 을 크게
      실패시키므로, buy_missing 과 동일하게 pipeline._json_safe(coerce_numeric=False) 로
      '표시 전용'(하류 집계 없음) NaN→"" 정리해 통과시킨다. (원본은 finite 가드 없이 저장했다.)

     분류기 입력 = buy_valid(사이트주문번호 있는 행) — 원본 app.py 355행과 동일.
      full staged df 를 넣으면 buy_missing 흔적행까지 classified 에 들어가 보강 로직이
      죽는다(match_data 가 모든 매입행을 matched/unmatched 로 이미 덮으므로).
    """
    # counter 는 _json_safe 의 nan_coerced 집계용이나 여기선 coerce_numeric=False(표시 전용,
    # NaN→"") 라 절대 증가하지 않는다 — 의도적으로 버린다. 훗날 coerce_numeric=True 로
    # 바꾸면 이 집계가 살아나야 하므로 인자는 계속 넘긴다(값만 무시).
    counter = [0]

    buy_valid, _buy_missing = pipeline.split_by_site_order_no(buy_df)
    mc = matcher.match_for_classifier(buy_valid, sell_df)
    cls = classifier.classify(mc["matched"], mc["mango_unmatched"], mc["market_only"])
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
            if r.get("데이터출처") in ("더망고+판매처", "더망고만"):
                mk = str(r.get("마켓주문번호", "")).strip()
                if mk:
                    existing_keys.add(mk)

        for _, raw_row in buy_df.iterrows():
            raw_dict = raw_row.to_dict()
            mk = str(raw_dict.get("마켓주문번호", "")).strip()
            # 🔴 스마트스토어는 원본이 'A(B)' 형태다. matched 에는 **매칭에 쓴 키**(A 또는 B)
            #   만 남아, 원본 'A(B)' 와 글자가 달라 "이미 매칭됨"을 못 알아채고 미매칭
            #   목록에 또 넣었다 → 화면에 매칭된 주문이 미매칭으로 뜸(사장님 신고 6건,
            #   2026-07-30 실측: matched·unmatched_buy 양쪽에 동시 존재).
            #   후보키(괄호 안/밖) 중 하나라도 이미 있으면 건너뛴다.
            _dedup_keys = _order_keys_for_dedup(mk, raw_dict.get("마켓명"))
            if not mk or any(k in existing_keys for k in _dedup_keys):
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

class _AnalyzeError(Exception):
    """`_do_analyze` 실패 신호 — 동기 라우트와 백그라운드 잡이 같은 메시지·상태코드로 처리."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def _do_analyze(body: dict) -> dict:
    """마켓 API 조회 → pipeline → aggregate → R2 + DB 저장.

    `/analyze`(동기, 기존 호출부·테스트 호환)와 `/analyze/start`(백그라운드 잡)가
    이 함수 하나를 공유한다 — 분석 본체를 두 벌로 유지하지 않는다.
    """
    _sess = SessionLocal()
    try:
        staged = pending_store.get(_sess)
    finally:
        _sess.close()
    if not staged or not staged.get("buy_bytes"):
        raise _AnalyzeError("먼저 더망고 매입 엑셀을 업로드하세요.", 400)
    # 저장한 건 원본 바이트 — 분석 때 다시 파싱한다(DataFrame 피클 금지).
    staged = dict(staged)
    staged["df"] = parse_buy(staged["buy_bytes"], staged["buy_filename"] or "buy.xlsx")
    staged["bytes"] = staged["buy_bytes"]
    staged["filename"] = staged["buy_filename"] or "buy.xlsx"

    since = _parse_dt(body.get("since") or staged["period_from"])
    until = _parse_dt(body.get("until") or staged["period_to"])

    # 1) 마켓 조회를 가장 먼저 — 한 마켓이라도 실패하면 502 로 전체 중단, 아무것도 저장 안 함.
    try:
        sell_df = sell_source.from_api(since, until)
    except Exception as e:  # noqa: BLE001
        raise _AnalyzeError(f"마켓 주문 조회 실패 — 분석을 중단했습니다: {e}", 502)
    warnings = list(sell_df.attrs.get("warnings", []) or [])
    # notices = 제외가 아닌 안내(예: 저장분으로 분석함). warnings 와 섞으면 화면이
    # "매출에서 제외했어요" 빨간 배너로 보여줘 거짓 경보가 된다.
    notices = list(sell_df.attrs.get("notices", []) or [])

    # 2) 매칭 + 집계
    out = pipeline.run(staged["df"], sell_df)
    # 2a) 정산여부(O/확인불가/진행중) + 주문상태 이력 — 클레임(취소요청 등)으로 들어온
    #   상태가 그 뒤 실제로 어떻게 됐는지(철회·정산완료) 보여준다(2026-09-05 사장님 지시).
    #   실패해도 매출·마진 본체는 그대로 살린다(부가 정보 — settle_status 안에서 이미 삼킴).
    settle_status.attach_settlement_status(out["matched"])
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
        raise _AnalyzeError(f"분석 결과를 저장할 수 없습니다: {e}", 500)
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

    # 4) DB 저장
    session = SessionLocal()
    try:
        row = store.save(
            session, payload=payload,
            period_from=since.date(), period_to=until.date(),
            buy_file_key=buy_key, buy_filename=staged["filename"],
            markets_fetched=sell_source.api_markets(),
            markets_failed=warnings, counts=counts,
            created_by=_created_by(),
        )
        analysis_id = row.id
    finally:
        session.close()

    return {
        "analysis_id": analysis_id,
        "counts": counts,
        "markets_failed": warnings,
        "notices": notices,
        "period_from": _iso(since.date()),
        "period_to": _iso(until.date()),
        **payload,
    }


@bp.route("/analyze", methods=["POST"])
def analyze():
    """`_do_analyze` 동기 호출 — 기존 호출부·테스트 호환용(응답까지 최대 몇 분 대기).

    라이브(Cloudflare) 에서 대용량 매입 엑셀은 100초 벽에 걸려 524 가 난다.
    화면(margin_embed.html)의 「분석 시작」 버튼은 `/analyze/start` + `/analyze/status`
    폴링을 쓴다 — 이 라우트는 그대로 두되 새 화면 흐름의 기본 경로는 아니다.
    """
    body = request.get_json(silent=True) or {}
    try:
        result = _do_analyze(body)
    except _AnalyzeError as e:
        return jsonify({"error": e.message}), e.status
    return jsonify(result)


def _heartbeat_loop(job_id: str, stop: threading.Event) -> None:
    """오래 도는 분석 중 20초마다 살아있음을 기록 — analyze_job_store.STALE_AFTER 보다
    훨씬 촘촘해야 워커가 진짜 죽었을 때만 stale 판정이 뜬다."""
    while not stop.wait(20):
        session = SessionLocal()
        try:
            analyze_job_store.touch(session, job_id)
        except Exception:  # noqa: BLE001 — 하트비트 실패가 본 계산을 막으면 안 된다.
            logger.warning("분석 하트비트 기록 실패 job=%s", job_id, exc_info=True)
        finally:
            session.close()


def _run_analyze_job(job_id: str, body: dict) -> None:
    """스레드에서 실행 — Flask request/app 컨텍스트에 기대지 않는다(lemouton.margin 은
    Flask 의존이 없고, `_created_by()`는 컨텍스트 없으면 이미 None 으로 넘어간다).

    gc.collect() 먼저 — 이 컨테이너는 1코어·900MB 로 빠듯한데(Dockerfile 참고),
    「분석 시작」 직전에 화면이 6마켓 최신 주문 수집(run-sync)을 돌려 같은 워커
    프로세스에 큰 DataFrame 쓰레기가 남아있을 수 있다. 무거운 매칭을 시작하기
    전에 회수해 두면 피크 메모리가 줄어든다(라이브에서 「수집 직후 분석」 조합만
    워커가 죽는 게 반복 관측됨 — 수집 없이 바로 분석만 걸면 매번 성공).
    """
    gc.collect()
    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(job_id, stop_heartbeat), daemon=True)
    heartbeat.start()
    try:
        result = _do_analyze(body)
    except _AnalyzeError as e:
        stop_heartbeat.set()
        session = SessionLocal()
        try:
            analyze_job_store.mark_error(session, job_id, e.message, e.status)
        finally:
            session.close()
        return
    except Exception as e:  # noqa: BLE001 — 무슨 예외든 폴링 쪽에 "error"로 보여야 한다.
        logger.exception("마진 분석 백그라운드 작업 실패 job=%s", job_id)
        stop_heartbeat.set()
        session = SessionLocal()
        try:
            analyze_job_store.mark_error(session, job_id, f"{type(e).__name__}: {e}", 500)
        finally:
            session.close()
        return
    stop_heartbeat.set()
    meta = {k: result[k] for k in
            ("counts", "markets_failed", "notices", "period_from", "period_to")}
    session = SessionLocal()
    try:
        analyze_job_store.mark_done(session, job_id, result["analysis_id"], meta)
    finally:
        session.close()


@bp.route("/analyze/start", methods=["POST"])
def analyze_start():
    """분석을 백그라운드 스레드로 시작하고 즉시 job_id 를 돌려준다.

    2026-09-05: 매입 12,949행짜리 더망고 엑셀에서 동기 `/analyze` 가 100초를 넘겨
    Cloudflare 가 524 로 끊었다 — 원인은 `matcher.match_data`(원본 무수정 이식,
    손대지 않는다)가 매입행 수에 비례해 매출 전체를 훑는 알고리즘이라 대용량
    파일에서 항상 그 벽에 걸린다. 요청·응답 왕복만 짧게 만들고(즉시 반환), 실제
    계산은 스레드에서 시간 제약 없이 돈다 — 폴링은 `/analyze/status/<job_id>`.
    """
    body = request.get_json(silent=True) or {}
    job_id = uuid.uuid4().hex
    session = SessionLocal()
    try:
        analyze_job_store.create(session, job_id)
    finally:
        session.close()
    threading.Thread(target=_run_analyze_job, args=(job_id, body), daemon=True).start()
    return jsonify({"job_id": job_id})


@bp.route("/analyze/status/<job_id>", methods=["GET"])
def analyze_status(job_id):
    session = SessionLocal()
    try:
        job = analyze_job_store.get(session, job_id)
    finally:
        session.close()
    if job is None:
        return jsonify({"error": "알 수 없는 작업 id"}), 404
    return jsonify(job)


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
    """{analysis_id, tab, rows?, column_order?, payload?} → xlsx 다운로드.

    🔴 [2026-08-24 실측] `payload` 없이 늘 `analysis_id`로 DB 저장분(=「분석 시작」
    시점 원본, 전체기간)만 읽었다 — 화면에서 날짜를 좁히거나 행을 제외·수정해도
    다운로드에는 전혀 반영되지 않고 매번 전체기간이 나오던 버그의 근본 원인.
    `payload`가 오면(margin_embed.html 이 현재 화면의 getFilteredData() 결과를 실어
    보낸다) 그걸 그대로 쓴다 — DB 재조회 없이 "화면에 보이는 바로 그 숫자"가 나간다.
    `payload`가 없으면(예: 저장된 분석 목록에서 재다운로드하는 경로) 기존처럼
    DB 저장분으로 폴백한다 — 하위호환.
    """
    body = request.get_json(silent=True) or {}
    aid = body.get("analysis_id")
    if aid is None:
        return jsonify({"error": "analysis_id 가 필요합니다."}), 400

    client_payload = body.get("payload")
    if isinstance(client_payload, dict) and client_payload:
        payload = client_payload
    else:
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

@bp.route("/lotteon-settlement/stats", methods=["GET"])
def lotteon_settlement_stats():
    """제휴 판단 반영 현황(읽기 전용·집계) — 판매경로 값별 건수·계정별 커버리지.
    목적: '제휴'가 실제 주문건에 붙었는지를 추측이 아니라 데이터로 확인.
      판매경로가 코드번호로 저장되면 order_export 의 `"제휴" in sl_chnl` 이 영영 False →
      2% 미적용인데 에러는 안 난다(무증상 오류). distinct 값을 그대로 노출해 눈으로 판정한다.
      개인정보 없음(주문번호는 앞 4자리만).
    """
    from lemouton.sourcing.models_v2 import LotteonSettlement
    from sqlalchemy import func
    with SessionLocal() as s:
        by_chnl = [
            {"sl_chnl": v, "건수": n, "제휴로_판정됨": bool(v and "제휴" in v)}
            for v, n in s.query(LotteonSettlement.sl_chnl, func.count())
                          .group_by(LotteonSettlement.sl_chnl).all()
        ]
        by_tr = [
            {"tr_no": v, "건수": n}
            for v, n in s.query(LotteonSettlement.tr_no, func.count())
                          .group_by(LotteonSettlement.tr_no).all()
        ]
        total = s.query(func.count(LotteonSettlement.od_no)).scalar() or 0
        # ★정산예정금액 0 이 '취소로 상쇄된 정상 0' 인지 '미수집인데 0' 인지 가르는 게 핵심 —
        #   0을 실제값으로 믿고 덮어쓰면 정산금이 통째로 틀린다(에러 없이 틀린 숫자).
        zero = s.query(func.count(LotteonSettlement.od_no)).filter(
            LotteonSettlement.pymt_tgt_amt == 0).scalar() or 0
        neg = s.query(func.count(LotteonSettlement.od_no)).filter(
            LotteonSettlement.pymt_tgt_amt < 0).scalar() or 0
        # 실주문번호는 "2026…" 처럼 2로 시작. 그 외 = 시험·오염 데이터.
        # ★GLOB/정규식은 DB 종류를 타므로 쓰지 않는다(라이브에서 500 남 — 실측). LIKE 만 사용.
        bad = [
            {"od_no": x.od_no, "pymt_tgt_amt": x.pymt_tgt_amt, "sl_chnl": x.sl_chnl, "tr_no": x.tr_no}
            for x in s.query(LotteonSettlement)
                      .filter(LotteonSettlement.od_no.notlike("2%")).limit(20).all()
        ]
        zero_sample = [
            {"od_no": x.od_no, "od_seq": x.od_seq, "sl_chnl": x.sl_chnl, "tr_no": x.tr_no}
            for x in s.query(LotteonSettlement)
                      .filter(LotteonSettlement.pymt_tgt_amt == 0).limit(8).all()
        ]
        nonzero_sample = [
            {"od_no": x.od_no, "od_seq": x.od_seq, "pymt_tgt_amt": x.pymt_tgt_amt,
             "sl_chnl": x.sl_chnl, "tr_no": x.tr_no}
            for x in s.query(LotteonSettlement)
                      .filter(LotteonSettlement.pymt_tgt_amt > 0).limit(8).all()
        ]
        # ★뺄셈으로 유도하지 말 것 — 직접 센다(유도값이 표본과 어긋나 오판할 뻔했다).
        pos = s.query(func.count(LotteonSettlement.od_no)).filter(
            LotteonSettlement.pymt_tgt_amt > 0).scalar() or 0
        # 주문번호 앞 6자리 = 주문 연월. '오래된 주문일수록 0원' 가설을 데이터로 확인한다.
        month = {}
        for x in s.query(LotteonSettlement.od_no, LotteonSettlement.pymt_tgt_amt).all():
            ym = (x[0] or "")[:6]
            if not ym.startswith("20"):
                continue
            b = month.setdefault(ym, {"0원": 0, "양수": 0, "음수": 0})
            b["0원" if x[1] == 0 else ("양수" if x[1] > 0 else "음수")] += 1
        # ── [2026-08-02] 「자동 회차가 실제로 돌고 있나」 ─────────────────────
        #  이게 없어서 못 봤다: 표는 1,599건으로 차 있는데 그게 **언제** 채워진
        #  건지 알 길이 없어, 자동이 멈춘 걸 「크롤 버그」로 오해할 뻔했다.
        #  (실제 원인은 회차 창이 60일 고정이라 그 밖을 안 훑은 것.)
        #  마지막 수집 시각이 오래됐으면 그 자체가 경보다.
        def _iso(v):
            return v.isoformat(timespec="seconds") if v else None
        last_at = _iso(s.query(func.max(LotteonSettlement.updated_at)).scalar())
        by_source = [
            {"source": v or "(없음)", "건수": n, "마지막_수집": _iso(mx)}
            for v, n, mx in s.query(LotteonSettlement.source, func.count(),
                                    func.max(LotteonSettlement.updated_at))
                             .group_by(LotteonSettlement.source).all()
        ]
        last_by_tr = [
            {"tr_no": v, "마지막_수집": _iso(mx)}
            for v, mx in s.query(LotteonSettlement.tr_no,
                                 func.max(LotteonSettlement.updated_at))
                          .group_by(LotteonSettlement.tr_no).all()
        ]
    return jsonify({
        "총건수": total, "판매경로별": by_chnl, "계정별": by_tr,
        "정산금": {"0원": zero, "음수": neg, "양수": pos, "합": zero + neg + pos},
        "월별": dict(sorted(month.items())),
        "마지막_수집": last_at, "출처별": by_source, "계정별_마지막수집": last_by_tr,
        "오염_시험데이터": bad,
        "표본_0원": zero_sample, "표본_양수": nonzero_sample,
    })


@bp.route("/lotteon-settlement/dump", methods=["GET"])
def lotteon_settlement_dump():
    """계정(tr_no)별 수집값 전량 — 마켓 제공 정답지와 전수 대조용(읽기 전용)."""
    from lemouton.sourcing.models_v2 import LotteonSettlement
    tr = (request.args.get("tr_no") or "").strip()
    with SessionLocal() as s:
        q = s.query(LotteonSettlement)
        if tr:
            q = q.filter(LotteonSettlement.tr_no == tr)
        rows = [{"od_no": x.od_no, "od_seq": x.od_seq, "amt": x.pymt_tgt_amt,
                 "chnl": x.sl_chnl} for x in q.all()]
    return jsonify({"tr_no": tr, "건수": len(rows), "rows": rows})


@bp.route("/lotteon-crawl-run", methods=["POST"])
def lotteon_crawl_run_report():
    """확장이 회차를 끝내고 **계정별 결과**를 남긴다. 계정당 최신 1건.

    body: {"via": "auto"|"manual",
           "runs": [{env_prefix, tr_no?, display_name?, result, detail?, rows?, deep?}, ...]}
      result = ok | verify(본인인증 필요) | fail
      via    = auto(확장 자동 회차) / manual(화면에서 손으로 돌림). 기본 auto.

    [중요] via 를 나누는 이유 — 배너("정산 수집이 N시간째 멈춤")는 「**자동**이 살아 있나」를
      묻는다. 수동 실행까지 같이 세면 손으로 한 번 돌린 것만으로 배너가 조용해져
      **자동이 죽어 있어도 모른다**. 화면엔 둘 다 보여주고 배너는 auto 만 본다.

    [중요] 왜 이게 필요한가 — 예전엔 「자동이 돌고 있나」를 lotteon_settlements.updated_at 으로
      짐작했다. 그건 「값이 바뀐 시각」이지 「성공한 시각」이 아니라 두 방향으로 다 틀린다
      (안 바뀌면 멀쩡한데 낡아 보이고, 한 계정이 막혀도 다른 계정 값 하나면 경보가 안 뜬다).
      회차를 직접 기록해 짐작을 없앤다.

    실패도 반드시 받는다 — 정작 알아야 하는 게 실패인데 성공만 남기면 표가 늘 초록이다.
    """
    from lemouton.sourcing.models_v2 import LotteonCrawlRun
    body = request.get_json(silent=True) or {}
    runs = body.get("runs")
    if not isinstance(runs, list):
        return jsonify({"ok": False, "error": "runs 필요"}), 400
    via = "manual" if str(body.get("via") or "").strip() == "manual" else "auto"
    saved, skipped = 0, 0
    with SessionLocal() as s:
        for r in runs:
            if not isinstance(r, dict):
                skipped += 1
                continue
            pf = str(r.get("env_prefix") or "").strip()
            res = str(r.get("result") or "").strip()
            if not pf or res not in ("ok", "verify", "fail"):
                skipped += 1          # 조용한 실패 금지 — 버린 개수를 응답에 남긴다
                continue
            obj = s.get(LotteonCrawlRun, pf) or LotteonCrawlRun(env_prefix=pf)
            if obj not in s:
                s.add(obj)
            obj.result = res
            obj.detail = (str(r.get("detail") or "") or None) and str(r.get("detail"))[:300]
            obj.rows = int(r.get("rows") or 0)
            obj.deep = bool(r.get("deep"))
            obj.via = via
            # tr_no·이름은 **아는 경우에만** 덮는다 — 로그인 실패 회차가 빈 값으로
            # 덮어 버리면 지난 회차에 알아낸 판매자ID 를 잃는다.
            if r.get("tr_no"):
                obj.tr_no = str(r.get("tr_no"))[:20]
            if r.get("display_name"):
                obj.display_name = str(r.get("display_name"))[:80]
            obj.ran_at = _dt.datetime.now(_dt.timezone.utc)   # onupdate 는 값이 안 바뀌면 안 뛴다
            saved += 1
        s.commit()
    return jsonify({"ok": True, "saved": saved, "skipped": skipped, "via": via})


@bp.route("/lotteon-settle-parity", methods=["GET"])
def lotteon_settle_parity():
    """[읽기 전용] 셀러오피스 크롤 ↔ 롯데온 공식 API **전수 대조**.

    사장님 요청(2026-08-04): 「크롤과 공식 API 가 100% 일치하는지 정합성 검사도 돼?」
    → 손으로 한 번 맞대 본 걸(2026-08-04 실측: 활성 189라인 전수 일치) 언제든 다시
      돌릴 수 있게 만든다. 크롤이 맞는지를 **크롤에게 묻지 않는다** — 서로 모르는 두 곳
      (판매자센터 화면 / 공식 OpenAPI)에서 같은 라인의 지급액을 받아 맞댄다.

    `?days=30&alias=` — 기본 최근 30일. 계정을 안 주면 저장된 계정 전부를 순회한다.

    [중요] 「불일치 0」이 곧 「정확」은 아니다. 겹치는 라인만 비교할 수 있다 —
      공식 API 는 **구매확정 뒤**에만 값을 주므로 미정산 구간은 애초에 대조 대상이 아니다.
      그래서 겹친 수(`비교`)를 반드시 같이 낸다. 비교가 0이면 그건 「합격」이 아니라
      「아직 검사할 게 없음」이다.

    [중요] 알려진 잡음 — `procSeq` 가 1 이 아닌 행(예 202, spdNo 공란)은 상품 정산이 아닌
      별도 라인인데 parse_itmd_lines 가 구분 없이 합산한다(2026-08-04 실측 4건, 전부
      정확히 10,000원·전부 반품완료 클레임 행). 그 사정을 알 수 있게 응답에 raw 를 싣는다.
    """
    import datetime as _d
    from lemouton.sourcing.models_v2 import LotteonSettlement
    try:
        days = max(1, min(180, int(request.args.get("days") or 30)))
    except ValueError:
        days = 30
    alias = (request.args.get("alias") or "").strip()
    until = _d.datetime.now()
    since = until - _d.timedelta(days=days)

    # ① 크롤값 — (odNo, odSeq) → 지급액
    with SessionLocal() as s:
        crawl = {(str(x.od_no), str(x.od_seq or "1")): x.pymt_tgt_amt
                 for x in s.query(LotteonSettlement).all()}

    # ② 공식 API — **계정별로** 물어야 그 계정 주문이 나온다.
    #    대표 계정만 물으면 다른 계정 주문의 정산이 통째로 빠져 「비교 0 = 합격」처럼
    #    보인다(정산 스윕이 쓰는 것과 같은 열거를 그대로 재사용한다).
    from lemouton.markets.order_ingest import _esm_settlement_clients
    from shared.platforms.lotteon import settlement as _lo
    api: dict = {}
    errors: list = []
    pairs = _esm_settlement_clients("lotteon")
    if alias:
        pairs = [(n, c) for n, c in pairs if n == alias] or pairs[:1]
    for name, cli in pairs:
        try:
            for k, v in _lo.itmd_line_map(since, until, client=cli).items():
                api[(str(k[0]), str(k[1] or "1"))] = v
        except Exception as e:   # noqa: BLE001 — 한 계정이 막혀도 나머지는 대조한다
            errors.append(f"[{name or '대표'}] {type(e).__name__}: {str(e)[:150]}")

    same, diff, czero = 0, [], 0
    for k, a in api.items():
        if k not in crawl:
            continue
        c = crawl[k]
        if c == 0:
            czero += 1          # 크롤이 아직 금액을 안 매긴 것 — 불일치가 아니다
        elif a == c:
            same += 1
        elif len(diff) < 30:
            diff.append({"od_no": k[0], "od_seq": k[1], "공식": a, "크롤": c, "차이": c - a})
    비교 = same + len(diff)
    return jsonify({
        "ok": True, "기간": f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
        "계정수": len(pairs), "크롤라인": len(crawl), "공식라인": len(api),
        "비교": 비교, "일치": same, "불일치": len(diff),
        "일치율": (round(100.0 * same / 비교, 1) if 비교 else None),
        "크롤0원_대조제외": czero,
        "불일치목록": diff, "실패": errors,
        "주의": ("비교 0 = 합격이 아니라 「아직 대조할 게 없음」입니다"
                 " (공식 API 는 구매확정 뒤에만 값을 줍니다)") if not 비교 else "",
    })


@bp.route("/lotteon-crawl-run", methods=["GET"])
def lotteon_crawl_run_list():
    """계정별 마지막 회차 결과 — 화면이 계정 카드 옆에 뿌린다(읽기 전용)."""
    from lemouton.sourcing.models_v2 import LotteonCrawlRun
    with SessionLocal() as s:
        rows = [{
            "env_prefix": x.env_prefix, "tr_no": x.tr_no or "",
            "display_name": x.display_name or "",
            "result": x.result, "detail": x.detail or "",
            "rows": x.rows or 0, "deep": bool(x.deep), "via": x.via or "auto",
            "ran_at": x.ran_at.isoformat(timespec="seconds") if x.ran_at else None,
        } for x in s.query(LotteonCrawlRun).all()]
    return jsonify({"ok": True, "runs": rows})


@bp.route("/lotteon-settlement/purge-fake", methods=["POST"])
def lotteon_settlement_purge_fake():
    """시험·오염 행 제거 — **주문번호가 숫자가 아닌 행만** 지운다.

    왜 이 조건 하나뿐인가: 롯데온 주문번호는 숫자만이다(ingest 가 이제 그걸 강제한다).
    그러니 숫자가 아닌 행은 정의상 우리가 만든 진단 프로브의 잔재다 —
    실주문을 지울 여지가 원천적으로 없다. 금액·계정·기간 같은 조건은 **쓰지 않는다**
    (그런 조건은 멀쩡한 행을 지울 수 있다).
    2026-08-02 라이브 실측: 'TESTOD999'(12,345원) 1건.
    `{"confirm": true}` 없이는 지우지 않고 목록만 보여준다(실수 방지).
    """
    from lemouton.sourcing.models_v2 import LotteonSettlement
    body = request.get_json(silent=True) or {}
    with SessionLocal() as s:
        victims = [x for x in s.query(LotteonSettlement).all()
                   if not str(x.od_no or "").isdigit()]
        listed = [{"od_no": x.od_no, "od_seq": x.od_seq, "amt": x.pymt_tgt_amt,
                   "tr_no": x.tr_no} for x in victims]
        if not body.get("confirm"):
            return jsonify({"dry_run": True, "대상": listed, "건수": len(listed),
                            "안내": '지우려면 {"confirm": true} 로 다시 호출하세요.'})
        for x in victims:
            s.delete(x)
        s.commit()
    return jsonify({"deleted": len(listed), "대상": listed})


@bp.route("/lotteon-settlement", methods=["POST"])
def lotteon_settlement_ingest():
    """크롤러 push → (od_no,od_seq)별 upsert.

    본문 두 형태를 다 받는다:
      · [{odNo, odSeq, pymtTgtAmt, slChNo, trNo}, ...]        (옛 형태 — 수동 크롤·구버전 확장)
      · {"source": "auto"|"manual", "rows": [ ...위와 같음 ]}  (2026-08-02 — 자동 회차가 씀)
    옛 형태를 계속 받는 이유: 확장은 사장님 크롬에 설치돼 있어 서버와 동시에 안 바뀐다.
    새 서버 + 옛 확장이 조용히 0건이 되면 정산이 통째로 멈춘다.

    od_no 는 숫자만 받는다 — lotteon_so.upsert_rows 와 같은 규약.
      이 가드가 없어서 진단 프로브가 넣은 'TESTOD999'(12,345원)가 표에 남아 있었다
      (2026-08-02 라이브 stats 실측). 가짜 행이 실주문과 같은 표에 있으면
      대조·합계가 조용히 틀어진다.
    """
    from lemouton.sourcing.models_v2 import LotteonSettlement
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        # dict 인데 rows 가 없으면 = 잘못 보낸 것. 빈 목록으로 삼키면 '0건 성공'이라는
        # 거짓 응답이 되어 크롤이 멈춘 걸 아무도 모른다 → 그대로 400.
        if "rows" not in body:
            return jsonify({"error": "list 필요"}), 400
        rows = body.get("rows") or []
        source = str(body.get("source") or "manual").strip()[:12] or "manual"
    else:
        rows, source = body or [], "manual"
    if not isinstance(rows, list):
        return jsonify({"error": "list 필요"}), 400
    n = 0
    skipped = 0        # 조용한 실패 금지 — 몇 건을 왜 버렸는지 응답에 남긴다
    with SessionLocal() as s:
        for r in rows:
            if not isinstance(r, dict):
                skipped += 1
                continue
            od = str(r.get("odNo") or "").strip()
            if not od or not od.isdigit():
                skipped += 1
                continue
            seq = str(r.get("odSeq") or "1")
            try:
                amt = int(round(float(r.get("pymtTgtAmt") or 0)))
            except (TypeError, ValueError):
                skipped += 1
                continue
            obj = s.get(LotteonSettlement, {"od_no": od, "od_seq": seq})
            if obj is None:
                obj = LotteonSettlement(od_no=od, od_seq=seq)
                s.add(obj)
            obj.pymt_tgt_amt = amt
            obj.sl_chnl = r.get("slChNo") or None
            obj.tr_no = r.get("trNo") or None
            obj.source = source
            n += 1
        s.commit()
    return jsonify({"upserted": n, "skipped": skipped, "source": source})


@bp.route("/rg-settlement", methods=["POST"])
def rg_settlement_ingest():
    """로켓그로스 정산 회차 push → (group_key, ratio)별 upsert.

    [중요] 왜 크롤 push 인가(2026-08-07 실측) — 로켓그로스 정산액을 주는 **OpenAPI 가 없다**.
       Wing 화면 API(`/tenants/rfm/v2/settlements/status/api`)가 유일한데 로그인 세션
       쿠키가 필요해 서버에서 못 부른다 → 로컬 크롤이 긁어 여기로 보낸다(롯데온과 동형).

    본문: {"account": "세소(쿠팡)", "source": "auto"|"manual",
           "rows": [ settlementStatusReports[] 원형 그대로 ]}
     버린 행 수를 응답에 남긴다 — 조용히 삼키면 크롤이 멈춘 걸 아무도 모른다.
    """
    from lemouton.margin import rg_settlement as RG
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "rows" not in body:
        return jsonify({"error": "rows 필요"}), 400
    rows = body.get("rows")
    if not isinstance(rows, list):
        return jsonify({"error": "rows 는 배열이어야 해요"}), 400
    account = str(body.get("account") or "").strip()
    source = str(body.get("source") or "manual").strip()[:12] or "manual"
    parsed, skipped = RG.parse_rows(rows, account=account)
    with SessionLocal() as s:
        saved = RG.save(parsed, source=source, session=s)
    return jsonify({"saved": saved, "skipped": skipped,
                    "account": account, "source": source})


@bp.route("/lotteon-paid", methods=["POST"])
def lotteon_paid_ingest():
    """롯데온 지급내역 push → (판매자ID, 정산기준일)별 upsert.

    [중요] 왜(2026-08-07 실브라우저 실측) — 롯데온은 정산 OpenAPI 8종·정산예정금액조회·정산요약·
       셀러머니를 다 뒤져도 **실지급일이 없다**(pymtTgtAmt 는 예정액). 셀러오피스
       「중개거래정산관리 > 지급내역」의 `seCmptDt`(정산완료일)가 유일한 답이다.
       소스: GET soapi.lotteon.com/settle/v1/so/mediationSettleManagement/selectMediationSettleDetail

    본문: {"trNo": "LO10161082", "account": "브랜드박스(롯데온)", "source": "auto"|"manual",
           "rows": [ … 응답 그대로 또는 data.settleDetailList.dataList[] ]}
     버린 행 수를 응답에 남긴다 — 조용히 삼키면 크롤이 멈춘 걸 아무도 모른다.
    """
    from lemouton.margin import lotteon_paid as LP
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "rows" not in body:
        return jsonify({"error": "rows 필요"}), 400
    tr_no = str(body.get("trNo") or "").strip()
    if not tr_no:
        # 판매자ID 없이 넣으면 계정이 섞여 합계가 조용히 틀어진다 → 받지 않는다.
        return jsonify({"error": "trNo(판매자ID) 필요"}), 400
    account = str(body.get("account") or "").strip()
    source = str(body.get("source") or "manual").strip()[:12] or "manual"
    parsed, skipped = LP.parse_rows(body.get("rows"), tr_no=tr_no, account=account)
    with SessionLocal() as s:
        saved = LP.save(parsed, source=source, session=s)
    return jsonify({"saved": saved, "skipped": skipped,
                    "trNo": tr_no, "account": account, "source": source})


@bp.route("/eleven11-unconf", methods=["POST"])
def eleven11_unconf_ingest():
    """11번가 **구매확정 전** 정산예정액 push → 주문라인에 실값 반영.

    [중요] 왜(2026-08-08) — 하루 전 나는 「11번가는 구매확정 전 정산예정액을 안 준다」고
       잘못 결론 냈다. 조회 축을 구매확정일로만 봐서 0건이 나온 걸 「없다」로 읽었다.
       결제일(STL_DT) 축 + 정산 미확정(N) 으로 보니 주문번호·금액이 그대로 나온다.
       이 창구가 붙기 전까지 그 구간(라이브 246만)은 발송대기 때 값(store) 상속이었다.
       자세한 근거·응답 실측은 `lemouton/margin/eleven11_unconf.py` 머리말.

    본문: {"rows": [...응답 그대로 또는 list[]], "account": "…", "source": "auto"|"manual"}
     미매칭 건을 응답에 그대로 돌려준다 — 조인 축이 어긋나 0건이 되어도
      「성공」으로 보이면 안 된다(조용한 실패 방지).
    """
    from lemouton.margin import eleven11_unconf as EU
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "rows" not in body:
        return jsonify({"error": "rows 필요"}), 400
    account = str(body.get("account") or "").strip()
    parsed, skipped = EU.parse_rows(body.get("rows"), account=account)
    with SessionLocal() as s:
        rep = EU.apply_rows(parsed, session=s)
    rep["버린행"] = skipped
    rep["account"] = account
    return jsonify(rep)

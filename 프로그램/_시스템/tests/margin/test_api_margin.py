# -*- coding: utf-8 -*-
"""api_margin 라우트 — 업로드·분석·목록·삭제·내보내기.

바레 Flask 앱 + tmp sqlite 세션으로 라우트만 검증. sell_source.from_api 는
monkeypatch(마켓 API 실호출 없음). R2 업로드 seam(_put_object)도 no-op 로 대체.
"""
import io

import pandas as pd
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.margin.models import (  # 테이블 등록
    MarginAnalysis, CardKeywordConfig, MarginPendingUpload)
from lemouton.margin.sell_source import SELL_COLUMNS
from webapp.routes import api_margin


def _buy_xlsx(dates):
    """마켓주문일자 목록으로 더망고 매입 엑셀 바이트 생성. 각 행은 매칭 가능한 형태."""
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "마켓주문일자": d, "마켓명": "쿠팡", "마켓주문번호": f"100{i}",
            "수령인명": "홍길동", "마켓상품명": "코트", "옵션1": "블랙",
            "구매가격": 30000, "사이트주문번호": f"SITE{i}", "간단메모": "",
            "국내송장번호": "",
        })
    bio = io.BytesIO()
    pd.DataFrame(rows).to_excel(bio, index=False)
    return bio.getvalue()


def _sell_df(specs):
    """specs = [(order_no, settle_source, 정산, matches?)] → SellRow DF."""
    rows = []
    for order_no, src, settle in specs:
        rows.append({
            "오픈마켓주문번호": order_no, "상품명": "코트", "옵션": "블랙",
            "수량": 1, "단가": 80000, "실결제금액": 80000,
            "정산예상금액_배송비포함": settle, "마켓수수료": "", "수수료율": "",
            "쇼핑몰": "06.쿠팡", "수취고객명": "홍길동", "주문일": "2026-07-04",
            "송장입력": "", "주문상태": "배송완료",
            "_settle_source": src, "_sell_origin": "api",
        })
    df = pd.DataFrame(rows, columns=SELL_COLUMNS)
    df.attrs["warnings"] = []
    return df


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True)
    MarginAnalysis.__table__.create(eng, checkfirst=True)
    CardKeywordConfig.__table__.create(eng, checkfirst=True)  # analyze 가 카드 키워드 주입
    MarginPendingUpload.__table__.create(eng, checkfirst=True)  # 업로드→분석 스테이징(DB)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(api_margin, "SessionLocal", Session)
    from lemouton.margin import pending_store as _ps
    _sess = api_margin.SessionLocal()
    try: _ps.clear(_sess)
    finally: _sess.close()
    monkeypatch.setattr(api_margin, "_put_object", lambda data, key, ct: key)

    app = Flask(__name__)
    app.register_blueprint(api_margin.bp)
    return app.test_client()


def _upload(client, dates=("2026-07-04",)):
    return client.post("/api/margin/upload", data={
        "file": (io.BytesIO(_buy_xlsx(dates)), "더망고.xlsx")},
        content_type="multipart/form-data")


def _patch_from_api(monkeypatch, sell_df):
    monkeypatch.setattr(api_margin.sell_source, "from_api",
                        lambda since, until, markets=None: sell_df)


# ── 업로드 ──────────────────────────────────────────────────────────────

def test_upload_infers_period_with_3day_margin(client):
    r = _upload(client, ["2026-07-04", "2026-07-06"])
    assert r.status_code == 200
    j = r.get_json()
    assert j["period_from"] == "2026-07-01"
    assert j["period_to"] == "2026-07-09"
    assert j["rows"] == 2
    assert j["markets"] == ["쿠팡"]


def test_new_buy_upload_clears_staged_shopmine(client, monkeypatch):
    """새 매입 업로드는 이전 샵마인 스테이징을 비운다(옛 매출이 따라붙는 stale 방지)."""
    from lemouton.margin import pending_store as _ps
    _upload(client)
    s2 = api_margin.SessionLocal()
    try:
        _ps.stage_shopmine(s2, raw=b"x", filename="shopmine.xlsx")
        assert _ps.get(s2)["shop_bytes"] == b"x"
    finally:
        s2.close()

    _upload(client)  # 새 매입 업로드

    s3 = api_margin.SessionLocal()
    try:
        assert not _ps.get(s3).get("shop_bytes")
    finally:
        s3.close()


# ── 분석 ────────────────────────────────────────────────────────────────

def test_analyze_requires_upload_first(client, monkeypatch):
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    r = client.post("/api/margin/analyze", json={})
    assert r.status_code == 400
    assert "업로드" in r.get_json()["error"]


def test_analyze_stores_and_returns_full_payload(client, monkeypatch):
    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    r = client.post("/api/margin/analyze", json={})
    assert r.status_code == 200
    j = r.get_json()
    assert j["analysis_id"] > 0
    assert len(j["matched"]) == 1
    assert j["summary"]["총순마진"] == 20000
    assert "market" in j and "daily" in j and "filters" in j


def test_analyze_injects_team_db_card_keywords_into_summary(client, monkeypatch):
    """analyze 응답의 summary._card_keywords == 팀 DB cards dict (미편집=시드 기본값).

    원본 app.py:879 미러 — 페이지는 summary._card_keywords 를 읽으므로 매 분석마다
    실려야 한다. 안 실으면 페이지 내장 폴백으로 떨어져 팀 DB 가 무력화된다.
    """
    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    r = client.post("/api/margin/analyze", json={})
    j = r.get_json()
    kw = j["summary"]["_card_keywords"]
    assert isinstance(kw, dict)
    # 시드 기본값이 그대로 실려야 한다
    assert kw["confirmed_blackspot"]["memo"] == ["블랙"]
    assert kw["memo_settled"]["memo"] == ["입금", "철회"]


def test_analyze_reflects_keyword_change_from_db(client, monkeypatch):
    """DB → analyze 흐름: /api/keywords 로 카드를 바꾸면 이후 analyze 가 반영.

    에디터의 in-session 갱신이 아니라 팀 DB 를 읽어 실린다는 증명.
    같은 DB(엔진)를 공유하도록 api_keywords.SessionLocal 도 같은 Session 으로 패치.
    """
    from webapp.routes import api_keywords
    monkeypatch.setattr(api_keywords, "SessionLocal", api_margin.SessionLocal)
    kw_app = Flask(__name__)
    kw_app.register_blueprint(api_keywords.bp)
    kw_client = kw_app.test_client()

    # 팀 DB 에서 카드 하나 변경
    resp = kw_client.post("/api/keywords", json={
        "card": "confirmed_blackspot",
        "data": {"memo": ["변경됨"], "label": "확인된 블랙스팟"}})
    assert resp.status_code == 200

    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    j = client.post("/api/margin/analyze", json={}).get_json()
    assert j["summary"]["_card_keywords"]["confirmed_blackspot"]["memo"] == ["변경됨"]


def test_analyze_omits_empty_cards_to_preserve_frontend_fallback(client, monkeypatch):
    """빈 cards 는 summary 에 truthy-but-empty 로 실리면 안 된다.

    페이지 _getCardKeywords() 는 truthy 값을 그대로 쓰는데 JS 는 {} 도 truthy →
    빈 dict 를 실으면 내장 폴백(기본 키워드맵)을 가로채 모든 조회가 [] 가 되고
    블랙스팟 버킷팅이 조용히 실패한다. 빈 cards(의도적 {cards:{}} POST) 면 아무것도
    싣지 않아 프론트가 폴백하도록 한다.
    """
    from webapp.routes import api_keywords
    monkeypatch.setattr(api_keywords, "SessionLocal", api_margin.SessionLocal)
    kw_app = Flask(__name__)
    kw_app.register_blueprint(api_keywords.bp)
    kw_client = kw_app.test_client()
    # cards 를 의도적으로 비운다
    assert kw_client.post("/api/keywords", json={"cards": {}}).status_code == 200

    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    j = client.post("/api/margin/analyze", json={}).get_json()
    # 키가 아예 없거나(선호) 있어도 falsy 여야 한다 — truthy-but-empty 금지.
    assert not j["summary"].get("_card_keywords")


def test_analyze_aborts_when_a_market_fails(client, monkeypatch):
    _upload(client)

    def _boom(since, until, markets=None):
        raise RuntimeError("롯데온 조회 실패")
    monkeypatch.setattr(api_margin.sell_source, "from_api", _boom)

    r = client.post("/api/margin/analyze", json={})
    assert r.status_code == 502
    assert "롯데온" in r.get_json()["error"]
    # 아무것도 저장되지 않았다
    lst = client.get("/api/margin/analyses").get_json()
    assert lst == []


def test_account_warnings_surface_in_response_and_db(client, monkeypatch):
    _upload(client)
    sell = _sell_df([("1000", "real", 50000)])
    sell.attrs["warnings"] = ["옥션 계정 A: 키 없음 → 제외"]
    _patch_from_api(monkeypatch, sell)

    r = client.post("/api/margin/analyze", json={})
    j = r.get_json()
    assert j["markets_failed"] == ["옥션 계정 A: 키 없음 → 제외"]

    meta = client.get("/api/margin/analyses").get_json()[0]
    assert meta["markets_failed"] == ["옥션 계정 A: 키 없음 → 제외"]


def test_settle_estimated_counted_from_matched(client, monkeypatch):
    """settle_estimated 는 matched 기준이지 sell_df 기준이 아니다.

    sell_df 엔 estimated 2건 — 하나(1000)는 매칭, 하나(9999)는 매칭 안 됨.
    matched 기준 → 1. sell_df 기준으로 세면 2 가 되어 이 단언이 깨진다.
    """
    _upload(client)
    sell = _sell_df([("1000", "estimated", 50000),
                     ("9999", "estimated", 50000)])  # 9999 는 매칭 안 됨
    _patch_from_api(monkeypatch, sell)

    r = client.post("/api/margin/analyze", json={})
    j = r.get_json()
    assert j["counts"]["matched"] == 1
    assert j["counts"]["settle_estimated"] == 1


def test_settle_unknown_and_nan_coerced_are_reported(client, monkeypatch):
    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    r = client.post("/api/margin/analyze", json={})
    counts = r.get_json()["counts"]
    assert "settle_unknown" in counts
    assert "nan_coerced" in counts


def test_response_is_json_serializable(client, monkeypatch):
    """실 라우트 응답이 flask.jsonify 를 통과해야 한다 — numpy/NaN 하나면 프로덕션 500."""
    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    r = client.post("/api/margin/analyze", json={})
    assert r.status_code == 200
    assert r.get_json() is not None  # 파싱 성공 = NaN 리터럴 없음


def test_nan_in_payload_aborts_with_500_and_saves_nothing(client, monkeypatch):
    """NaN 을 0 으로 덮지 않는다 — summary 의 NaN 은 '합계 0'이 아니라 '합계가 틀림'이다."""
    import lemouton.margin.aggregator as A
    real = A.aggregate

    def _poisoned(rows, ranges):
        agg = real(rows, ranges)
        agg["summary"]["총순마진"] = float("nan")
        return agg

    monkeypatch.setattr("webapp.routes.api_margin.aggregator.aggregate", _poisoned)
    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    r = client.post("/api/margin/analyze",
                    json={"since": "2026-07-01", "until": "2026-07-09"})
    assert r.status_code == 500
    err = r.get_json()["error"]
    assert "NaN" in err or "계산 불가능" in err
    # 목록 엔드포인트는 bare list 를 반환한다(이 모듈 규약) → 아무것도 저장 안 됨
    assert client.get("/api/margin/analyses").get_json() == []


def test_numpy_scalars_still_normalized(client):
    import numpy as np
    assert api_margin._json_normalize(
        {"a": np.int64(5), "b": [np.float64(1.5)]}) == {"a": 5, "b": [1.5]}


# ── 목록 / 로드 / 삭제 ────────────────────────────────────────────────────

def test_analyses_list_get_delete(client, monkeypatch):
    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    aid = client.post("/api/margin/analyze", json={}).get_json()["analysis_id"]

    lst = client.get("/api/margin/analyses").get_json()
    assert [m["id"] for m in lst] == [aid]

    got = client.get(f"/api/margin/analyses/{aid}").get_json()
    assert got["payload"]["summary"]["총순마진"] == 20000

    assert client.delete(f"/api/margin/analyses/{aid}").get_json()["ok"] is True
    assert client.get("/api/margin/analyses").get_json() == []
    assert client.get(f"/api/margin/analyses/{aid}").status_code == 404


def test_export_returns_xlsx(client, monkeypatch):
    _upload(client)
    _patch_from_api(monkeypatch, _sell_df([("1000", "real", 50000)]))
    aid = client.post("/api/margin/analyze", json={}).get_json()["analysis_id"]

    r = client.post("/api/margin/export", json={"analysis_id": aid, "tab": "all"})
    assert r.status_code == 200
    assert r.data[:2] == b"PK"  # xlsx = zip

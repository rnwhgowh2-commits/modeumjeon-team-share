# -*- coding: utf-8 -*-
"""/api/margin/analyze — 원본 app.py `/api/analyze` 의 analysisData 계약 동결.

원본(C:\\dev\\대량등록 마진계산기\\app.py 1313~1459)이 프론트에 돌려주던 단일
analysisData 오브젝트의 키 집합을 프리즈한다. Task 2 로 복원한 블랙스팟 분류 키
(classified·blackspot_summary·missing_order_no·mango_* 검증 카운트)가 빠지면 실패.

harness 는 test_api_margin.py 와 동일 — sell_source.from_api monkeypatch + R2 seam no-op.
NaN 위험 재현: 매칭행/보강행은 raw .to_dict() 출신이라 빈 셀이 NaN(float) 로 남는다.
sanitize 를 빠뜨리면 라우트의 _assert_finite 가 500 을 내 이 테스트가 깨진다.
"""
import io

import pandas as pd
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.margin.models import (  # 테이블 등록
    MarginAnalysis, CardKeywordConfig, MarginPendingUpload)
from lemouton.margin.sell_source import SELL_COLUMNS
from webapp.routes import api_margin


def _buy_xlsx():
    """3행 더망고 매입 엑셀.

    row1 매칭 정상행(buy_valid): 쿠팡 1000, 사이트주문번호 있음 → classifier·pipeline 둘 다 매칭.
    row2 더망고만 흔적행(buy_missing): 쿠팡 7777, 사이트주문번호 없음·매칭 안 됨 → unmatched_buy.
    row3 스마트스토어 흔적행(buy_missing): '2000(3000)', 사이트주문번호 없음 →
         pipeline 은 3000 으로 매칭(matched 키='3000'), classifier(buy_valid)엔 없음.
         raw 키 '2000(3000)' 가 어디에도 없어 unmatched_buy 보강(원본 1336~1387)이 발동.
    국내송장번호는 빈칸 → 읽으면 NaN(float) → classified/보강행 sanitize 필요(finite 가드 위험).
    """
    rows = [
        {"마켓주문일자": "2026-07-04", "마켓명": "쿠팡", "마켓주문번호": "1000",
         "수령인명": "홍길동", "마켓상품명": "코트", "옵션1": "블랙",
         "구매가격": 30000, "사이트주문번호": "SITE0", "간단메모": "http://src/1",
         "국내송장번호": ""},
        {"마켓주문일자": "2026-07-05", "마켓명": "쿠팡", "마켓주문번호": "7777",
         "수령인명": "김철수", "마켓상품명": "셔츠", "옵션1": "화이트",
         "구매가격": 15000, "사이트주문번호": "", "간단메모": "",
         "국내송장번호": ""},
        {"마켓주문일자": "2026-07-06", "마켓명": "스마트스토어", "마켓주문번호": "2000(3000)",
         "수령인명": "이영희", "마켓상품명": "바지", "옵션1": "네이비",
         "구매가격": 25000, "사이트주문번호": "", "간단메모": "",
         "국내송장번호": ""},
    ]
    bio = io.BytesIO()
    pd.DataFrame(rows).to_excel(bio, index=False)
    return bio.getvalue()


def _sell_df():
    """매출 2행 — 1000(쿠팡, row1 매칭) + 3000(스마트스토어, row3 매칭)."""
    specs = [
        ("1000", "코트", "블랙", "06.쿠팡", "홍길동", 50000),
        ("3000", "바지", "네이비", "04.스마트스토어", "이영희", 40000),
    ]
    rows = []
    for order_no, prod, opt, mall, name, settle in specs:
        rows.append({
            "오픈마켓주문번호": order_no, "상품명": prod, "옵션": opt,
            "수량": 1, "단가": 80000, "실결제금액": 80000,
            "정산예상금액_배송비포함": settle, "마켓수수료": "", "수수료율": "",
            "쇼핑몰": mall, "수취고객명": name, "주문일": "2026-07-04",
            "송장입력": "", "주문상태": "배송완료",
            "_settle_source": "real", "_sell_origin": "api",
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


def _analyze(client, monkeypatch):
    client.post("/api/margin/upload", data={
        "file": (io.BytesIO(_buy_xlsx()), "더망고.xlsx")},
        content_type="multipart/form-data")
    monkeypatch.setattr(api_margin.sell_source, "from_api",
                        lambda since, until, markets=None: _sell_df())
    return client.post("/api/margin/analyze", json={})


# ── 계약 동결 ──────────────────────────────────────────────────────────────

_TOP_LEVEL = [
    "matched", "unmatched_buy", "unmatched_sell",
    "classified", "blackspot_summary", "missing_order_no", "summary",
]
_AGG_KEYS = ["market", "daily", "monthly", "brand", "priceRange", "product", "filters"]
_SUMMARY_KEYS = [
    "card_all", "card_immediate", "card_sourcing", "card_market",
    "card_normal", "card_pending", "card_kkadaegi", "card_margin",
    "mango_total", "mango_with_order_no", "mango_with_trace",
]


def test_analyze_returns_full_analysis_data_contract(client, monkeypatch):
    r = _analyze(client, monkeypatch)
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j is not None  # NaN 리터럴 없이 JSON 파싱 성공 (finite 가드 통과)

    for k in _TOP_LEVEL:
        assert k in j, f"analysisData 최상위 키 누락: {k}"
    for k in _AGG_KEYS:
        assert k in j, f"집계 탭 키 누락: {k}"
    for k in _SUMMARY_KEYS:
        assert k in j["summary"], f"summary 키 누락: {k}"


def test_classified_carries_category_labels(client, monkeypatch):
    j = _analyze(client, monkeypatch).get_json()
    classified = j["classified"]
    assert isinstance(classified, list) and classified, "classified 는 비어있지 않은 list 여야 한다"
    for row in classified:
        assert "대분류" in row and "상세분류" in row
    assert isinstance(j["blackspot_summary"], dict)


def test_verification_counts(client, monkeypatch):
    """mango_total = raw 전체, mango_with_order_no = 사이트주문번호 있는 행."""
    j = _analyze(client, monkeypatch).get_json()
    sm = j["summary"]
    assert sm["mango_total"] == 3            # raw buy_df 3행
    assert sm["mango_with_order_no"] == 1    # row1 만 사이트주문번호 보유
    assert sm["mango_with_trace"] == sm["card_all"]


def test_unmatched_buy_trace_augmentation(client, monkeypatch):
    """분류기 밖 매입흔적행(스마트스토어 raw 키)이 unmatched_buy 로 보강된다."""
    j = _analyze(client, monkeypatch).get_json()
    keys = [str(r.get("마켓주문번호", "")) for r in j["unmatched_buy"]]
    assert "2000(3000)" in keys, "보강행(raw 스마트스토어 키)이 unmatched_buy 에 없다"


def test_matched_present(client, monkeypatch):
    j = _analyze(client, monkeypatch).get_json()
    assert len(j["matched"]) >= 1


# ── 같은 라인은 최종 상태 1건만 매출·정산에 쓴다 (사장님 확정 2026-07-24) ────────

def test_같은_라인은_최종상태_한줄만_매출로_쓴다(monkeypatch):
    """저장 키가 시절마다 달랐던 주문이 옛 키·새 키 두 행으로 남아 있다
    (롯데온 실측: 출고지시 37,599 + 배송완료 38,505). 둘 다 매출 후보로 들어가면
    매입 한 건에 어느 쪽이 붙느냐로 정산이 906원씩 흔들린다."""
    from lemouton.margin import sell_source as SS
    rows = [
        {"_line_uid": "lotteon|A|1", "_seen_at": "2026-07-19T00:00:00",
         "주문상태": "출고지시", "정산예정금(배송비포함)": 37599},
        {"_line_uid": "lotteon|A|1", "_seen_at": "2026-07-24T00:00:00",
         "주문상태": "배송완료", "정산예정금(배송비포함)": 38505},
    ]
    got = SS._one_row_per_line(rows)
    assert len(got) == 1
    assert got[0]["주문상태"] == "배송완료" and got[0]["정산예정금(배송비포함)"] == 38505


def test_클레임과_식별자없는행은_안_합친다():
    """취소·반품은 정산 0 판정의 근거라 합치면 취소 사실이 사라진다.
    식별자 없는 행을 합치면 남의 주문과 섞인다."""
    from lemouton.margin import sell_source as SS
    rows = [
        {"_line_uid": "lotteon|B|1", "_kind": "change", "주문상태": "취소완료"},
        {"_line_uid": "lotteon|B|1", "_seen_at": "2026-07-24T00:00:00",
         "주문상태": "배송완료"},
        {"주문상태": "배송완료"},          # 식별자 없음
        {"주문상태": "배송중"},            # 식별자 없음
    ]
    got = SS._one_row_per_line(rows)
    assert len(got) == 4
    assert sum(1 for r in got if r.get("_kind") == "change") == 1

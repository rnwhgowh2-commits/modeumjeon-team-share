# -*- coding: utf-8 -*-
"""order_export._settle_source — real / estimated / none 태깅."""
import datetime as dt
import urllib.parse as _urlparse

import pytest

from lemouton.markets import order_export as oe


@pytest.fixture(autouse=True)
def _clear_learned_rates(tmp_path, monkeypatch):
    """상품별 실요율 '기억'을 **매번 새 DB** 에서 시작한다.

    쿠팡 요율 학습(2026-07-25)은 조회를 넘어 DB 에 남는다 — 그게 기능이다. 대신
    테스트가 서로의 기억을 물려받으면 **먼저 돈 테스트에 따라 결과가 갈린다**
    (실제로 test_coupang_settled_is_real 이 vid 9 = 12% 를 남겨 unsettled 쪽이
    8,845 대신 8,800 을 봤다). 기억 자체를 테스트할 때는 명시적으로 심는다.

    [2026-08-01] 전에는 공용 SQLite(`data/lemouton.db`)의 행만 지웠다. 그래서
      · 그 파일에 표가 없는 환경(새 워크트리·**CI 체크아웃**)에선 3건이 **늘** 실패했고
        (`no such table: market_learned_rates` → `load_safe()` 가 설계대로 삼켜
         빈 기억이 되고, 단언만 깨졌다)
      · 표가 있는 환경에선 앞 테스트가 남긴 기억을 물려받아 결과가 갈렸다.
    즉 '간헐 실패'가 아니라 **주변 DB 상태 의존**이었다. 테스트마다 빈 SQLite 를
    만들어 스키마를 세우고 `SessionLocal` 을 그리로 돌린다. 이 경로의 `SessionLocal`
    은 전부 함수 안에서 import 하므로 `shared.db` 한 곳만 갈아끼우면 된다.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import shared.db as db
    import lemouton.margin.models  # noqa: F401 — MarketLearnedRates 표 등록

    eng = create_engine(f"sqlite:///{tmp_path / 'learned.db'}")
    db.Base.metadata.create_all(eng)
    monkeypatch.setattr(
        db, "SessionLocal",
        sessionmaker(bind=eng, autoflush=False, autocommit=False,
                     future=True, expire_on_commit=False),
    )
    yield

KST = dt.timezone(dt.timedelta(hours=9))
SINCE = dt.datetime(2026, 7, 5, tzinfo=KST)
UNTIL = dt.datetime(2026, 7, 8, tzinfo=KST)


# 이 가짜 정산분의 '인식일'. 이 하루가 든 창에서만 돌려준다 — 실제 API 와 같은 규칙.
SETTLE_RECOGNIZED_ON = "2026-07-06"


def _asked_window(query: str) -> tuple[str, str]:
    """revenue-history 질의에서 recognitionDateFrom/To 를 꺼낸다."""
    q = dict(_urlparse.parse_qsl(query))
    return q.get("recognitionDateFrom", ""), q.get("recognitionDateTo", "")


class CoupangSettled:
    _cfg = {"vendor_id": "A1"}

    def request(self, method, path, query=""):
        if "ordersheets" in path:
            return {"data": [{"shipmentBoxId": 1, "orderId": 100, "status": "FINAL_DELIVERY",
                              "orderer": {}, "receiver": {}, "shippingPrice": 0,
                              "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                              "shippingCount": 1,
                                              "salesPrice": {"units": 10000}}]}],
                    "nextToken": ""}
        if "revenue-history" in path:
            # 🔴 [2026-08-01] 창(window)을 지켜야 한다. order_export 는 정산 인식일이
            #   주문일보다 늦는 걸 감안해 조회 끝을 **'지금'까지 넓히고** 25일 창으로
            #   쪼개 여러 번 부른다(_cp_windows). 날짜를 무시하고 매번 같은 정산을
            #   돌려주면 **창 수만큼 합산**돼 정산액이 배로 뛴다 —
            #     · 이 테스트를 쓴 2026-07-25 : 7/5~오늘 = 20일 → 창 1개 → 8,800 (통과)
            #     · 2026-08-01              : 27일      → 창 2개 → 17,600 (실패)
            #     · 2026-08-25              : 51일      → 창 3개 → 26,400
            #   즉 프로그램 결함이 아니라 **달력이 지나가면 썩는 가짜 응답**이었다.
            #   (창은 rec_to = 창끝−1일 이라 서로 안 겹친다 → 실제 API 는 한 번만 준다.)
            _from, _to = _asked_window(query)
            if not (_from <= SETTLE_RECOGNIZED_ON <= _to):
                return {"data": [], "hasNext": False}
            return {"data": [{"orderId": 100,
                              "items": [{"vendorItemId": 9, "settlementAmount": 8800}]}],
                    "hasNext": False}
        return {"data": [], "nextToken": ""}


class CoupangUnsettled(CoupangSettled):
    def request(self, method, path, query=""):
        if "revenue-history" in path:
            return {"data": [], "hasNext": False}
        return CoupangSettled.request(self, method, path, query)


def test_coupang_settled_is_real():
    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangSettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "real"
    assert r["정산예정금액"] == 8800


def test_coupang_unsettled_is_estimated():
    """실요율을 모르면(기억도 없으면) 계약 기본율 11.55%."""
    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangUnsettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "estimated"
    assert r["정산예정금액"] == round(10000 * oe.CP_FEE_FACTOR)


def test_coupang_unsettled_uses_remembered_rate():
    """지난 조회에서 정산 확정분으로 배운 그 상품의 실요율을 다시 쓴다.

    2026-07-25 샵마인 대조 회귀: 고정 11.55% 라서 미정산 주문 7건이 건당
    133~167원씩 정산 과다였다(실제 요율 11.67~12.56%).
    """
    from lemouton.margin import learned_rates_store as lrs
    from shared.db import SessionLocal

    with SessionLocal() as s:
        lrs.merge(s, coupang_fee_rates={"9": 0.12})

    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangUnsettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "estimated"
    assert r["정산예정금액"] == 8800          # 10,000 × (1 − 0.12), 기본율이면 8,845


def test_coupang_settled_teaches_the_rate():
    """정산 확정분을 지나가면 그 상품 요율이 기억에 남는다."""
    from lemouton.margin import learned_rates_store as lrs

    oe.coupang_order_rows(SINCE, UNTIL, client=CoupangSettled())
    assert lrs.load_safe()["coupang_fee_rates"].get("9") == pytest.approx(0.12)


def test_settle_source_survives_finalize():
    rows = oe._finalize_rows([{"주문일": "2026-07-05", "단가": 100, "수량": 1,
                               "정산예정금액": 88, "_settle_source": "estimated"}])
    assert rows[0]["_settle_source"] == "estimated"


def test_settle_source_not_in_xlsx_columns():
    """엑셀 출력 컬럼은 불변 — 기존 소비자 영향 없음."""
    assert "_settle_source" not in oe.ALL_COLUMNS
    assert "_settle_source" not in oe.resolve_columns(None)

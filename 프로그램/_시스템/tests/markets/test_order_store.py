"""주문·클레임 적재 — 중복·소실·이력유실을 막는 계약.

여기서 지키려는 사고:
  ① 같은 주문을 두 번 적재 → 금액 2배
  ② 서로 다른 라인이 한 행으로 합쳐짐 → 주문 소실
  ③ 클레임 이력이 덮어써짐 → 「언제 무슨 클레임이었나」를 못 답함
  ④ 나중 조회가 값을 덜 줄 때 기존 값이 지워짐 → 송장 '확인 불가' 재발
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import line_uid as L
from lemouton.markets import order_store as OS


@pytest.fixture
def session():
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401  — 테이블 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _order(uid="smartstore|P1", **kw):
    row = {L.FIELD: uid, "판매처": "스마트스토어", "오픈마켓주문번호": "P1",
           "주문일": "2026-07-01 10:00:00", "주문상태": "결제완료",
           "상품명": "티셔츠", "단가": 10000, "수량": 1}
    row.update(kw)
    return row


def _claim(uid="coupang|B1|V1", **kw):
    row = {L.FIELD: uid, "판매처": "쿠팡", "오픈마켓주문번호": "O1", "_kind": "change",
           "_change_date": "2026-07-02", "주문상태": "반품요청", "주문상태원본": "UC"}
    row.update(kw)
    return row


# ── ① 중복 적재 방지 ────────────────────────────────────────────
def test_같은_주문을_두번_저장해도_행이_늘지_않는다(session):
    OS.save([_order()], session=session)
    st = OS.save([_order()], session=session)
    assert st["orders_new"] == 0 and st["orders_updated"] == 1
    assert len(OS.load(session=session)) == 1


def test_한_배치에_같은_uid가_두번_와도_안_터진다(session):
    """autoflush=False 라 s.get 이 방금 add 한 형제를 못 본다 — pending 가드가 없으면
    PK 충돌로 commit 이 통째 실패해 0건 저장된다(invoice_ledger 가 겪은 사고)."""
    st = OS.save([_order(), _order(주문상태="배송준비중")], session=session)
    assert st["orders_new"] == 1
    rows = OS.load(session=session)
    assert len(rows) == 1 and rows[0]["주문상태"] == "배송준비중"


# ── ② 서로 다른 라인이 합쳐지지 않는다 ──────────────────────────
def test_같은_주문의_다른_라인은_별도로_쌓인다(session):
    OS.save([_order(uid="coupang|B1|V1", 판매처="쿠팡"),
             _order(uid="coupang|B1|V2", 판매처="쿠팡")], session=session)
    assert len(OS.load(session=session)) == 2


def test_line_uid_없는_주문행은_저장하지_않고_건수를_알린다(session):
    """키를 지어내 저장하면 서로 다른 주문이 합쳐진다. 조용히 버리지도 않는다."""
    row = _order()
    row.pop(L.FIELD)
    st = OS.save([row], session=session)
    assert st["orders_new"] == 0 and st["skipped_no_uid"] == 1
    assert OS.load(session=session) == []


# ── ③ 클레임 이력 ──────────────────────────────────────────────
def test_클레임_단계가_바뀌면_별도_이벤트로_쌓인다(session):
    OS.save([_claim(주문상태="반품요청", 주문상태원본="UC")], session=session)
    OS.save([_claim(주문상태="반품완료", 주문상태원본="CC")], session=session)
    claims = [r for r in OS.load(session=session) if r.get("_kind") == "change"]
    assert len(claims) == 2, "덮어쓰면 이력이 사라진다"


def test_같은_클레임을_두번_조회하면_안_늘어난다(session):
    OS.save([_claim()], session=session)
    st = OS.save([_claim()], session=session)
    assert st["claims_new"] == 0 and st["claims_updated"] == 1


def test_클레임은_주문테이블을_안_건드린다(session):
    OS.save([_order(), _claim()], session=session)
    assert OS.coverage(session=session)[0]["rows"] == 1   # 주문 라인은 1건뿐


def test_클레임이_주문행_상태를_최신으로_갱신한다(session):
    """취소돼도 매출 행은 남되 상태는 '취소완료'로 최신화돼야 한다 — 안 그러면
    적재분 조회에서 취소 주문이 '배송준비중' 매출로 계속 잡힌다(2026-07-21 검수)."""
    OS.save([_order(uid="smartstore|P1", 주문상태="배송준비중")], session=session)
    OS.save([_claim(uid="smartstore|P1", 판매처="스마트스토어",
                    주문상태="취소완료", 주문상태원본="CANCELED")], session=session)
    orders = [r for r in OS.load(session=session) if r.get("_kind") != "change"]
    assert len(orders) == 1
    assert orders[0]["주문상태"] == "취소완료"


def test_클레임이_와도_주문행의_다른_값은_안_지운다(session):
    """클레임행은 상품명·단가가 공란인 마켓이 많다 — 상태만 갱신하고 나머지는 보존."""
    OS.save([_order(uid="smartstore|P1", 상품명="티셔츠", 단가=10000)], session=session)
    OS.save([_claim(uid="smartstore|P1", 판매처="스마트스토어", 주문상태="취소완료")],
            session=session)
    orders = [r for r in OS.load(session=session) if r.get("_kind") != "change"]
    assert orders[0]["상품명"] == "티셔츠" and orders[0]["단가"] == 10000


# ── 클레임→주문상태 보정(백필·과거분 자가치유) ───────────────────
def test_sync가_클레임보다_늦게_들어온_주문행_상태를_보정한다(session):
    """백필은 순서를 보장 못 한다 — 클레임이 먼저 쌓이고 주문행이 나중에 오면
    주문행이 옛 상태로 남는다. 2026-07-21 이전 적재분(라이브 74쌍)도 같은 상태."""
    OS.save([_claim(uid="smartstore|P1", 판매처="스마트스토어",
                    주문상태="취소완료", 주문상태원본="CANCELED")], session=session)
    OS.save([_order(uid="smartstore|P1", 주문상태="배송준비중")], session=session)
    st = OS.sync_status_from_claims(session=session)
    assert st["fixed"] == 1
    orders = [r for r in OS.load(session=session) if r.get("_kind") != "change"]
    assert orders[0]["주문상태"] == "취소완료"


def test_sync는_진행중_클레임으로는_안_덮는다(session):
    """'반품요청'은 이후 철회됐을 수 있다 — 옛 이벤트로 현재 상태를 덮으면 오염.
    종결(…완료)만 보정하고, 진행중은 증분 수집(신선한 데이터)에 맡긴다."""
    OS.save([_claim(uid="smartstore|P1", 판매처="스마트스토어", 주문상태="반품요청")],
            session=session)
    OS.save([_order(uid="smartstore|P1", 주문상태="배송완료")], session=session)
    st = OS.sync_status_from_claims(session=session)
    assert st["fixed"] == 0
    orders = [r for r in OS.load(session=session) if r.get("_kind") != "change"]
    assert orders[0]["주문상태"] == "배송완료"


def test_sync는_여러_이벤트_중_마지막_종결상태를_쓴다(session):
    OS.save([_claim(uid="smartstore|P1", 판매처="스마트스토어",
                    주문상태="취소완료", _change_date="2026-07-02"),
             _claim(uid="smartstore|P1", 판매처="스마트스토어",
                    주문상태="반품완료", _change_date="2026-07-05", 주문상태원본="CC")],
            session=session)
    OS.save([_order(uid="smartstore|P1", 주문상태="배송준비중")], session=session)
    OS.sync_status_from_claims(session=session)
    orders = [r for r in OS.load(session=session) if r.get("_kind") != "change"]
    assert orders[0]["주문상태"] == "반품완료"


# ── ④ 나중 조회가 덜 줘도 기존 값을 지우지 않는다 ────────────────
def test_새_조회가_공란이면_기존값을_유지한다(session):
    """11번가는 구매확정 후 송장을 안 준다. 그때 공란으로 덮으면 '확인 불가'가 된다."""
    OS.save([_order(송장입력="123456789")], session=session)
    OS.save([_order(송장입력="")], session=session)
    assert OS.load(session=session)[0]["송장입력"] == "123456789"


def test_새_조회가_실값을_주면_갱신한다(session):
    OS.save([_order(송장입력="111")], session=session)
    OS.save([_order(송장입력="222")], session=session)
    assert OS.load(session=session)[0]["송장입력"] == "222"


def test_주문일이_나중에_교정되면_반영된다(session):
    """11번가는 주문번호 앞 8자리 근사값을 나중에 실주문일로 덮는다."""
    OS.save([_order(주문일="2026-07-03 00:00:00")], session=session)
    OS.save([_order(주문일="2026-07-06 12:00:00")], session=session)
    assert OS.load(session=session)[0]["주문일"] == "2026-07-06 12:00:00"


# ── 조회 ───────────────────────────────────────────────────────
def test_기간으로_거른다(session):
    OS.save([_order(uid="smartstore|A", 주문일="2026-01-05 10:00:00"),
             _order(uid="smartstore|B", 주문일="2026-07-05 10:00:00")], session=session)
    got = OS.load(since="2026-07-01", until="2026-07-31",
                  include_claims=False, session=session)
    assert len(got) == 1 and got[0][L.FIELD] == "smartstore|B"


def test_주문일이_공란인_행은_기간필터로_지우지_않는다(session):
    """주문일이 없는 게 정상인 마켓이 있다(롯데온·쿠팡 클레임). 거르면 통째로 사라진다."""
    OS.save([_order(uid="lotteon|X|1|S", 주문일="")], session=session)
    got = OS.load(since="2026-07-01", until="2026-07-31",
                  include_claims=False, session=session)
    assert len(got) == 1


def test_클레임도_기간으로_거른다_변경일_기준(session):
    """기간 필터가 클레임에 안 걸리면 모든 조회에 전체 이력(수천 건)이 딸려 온다
    (2026-07-21 라이브 실측: 3.5개월 조회에 기간 밖 클레임 1,998건)."""
    OS.save([_claim(uid="coupang|B1|V1", _change_date="2026-01-05"),
             _claim(uid="coupang|B2|V1", 오픈마켓주문번호="O2", _change_date="2026-07-02"),
             _claim(uid="coupang|B3|V1", 오픈마켓주문번호="O3", _change_date="")],
            session=session)
    claims = [r for r in OS.load(since="2026-07-01", until="2026-07-31", session=session)
              if r.get("_kind") == "change"]
    dates = sorted(str(r.get("_change_date")) for r in claims)
    assert dates == ["", "2026-07-02"], "기간 안 + 날짜모름(보존)만 남아야 한다"


def test_클레임_주문일이_기간안이면_변경일이_밖이어도_보존(session):
    """7월 주문이 9월에 취소된 경우 — 7월 조회에서 그 주문의 클레임이 보여야
    매출·취소가 짝으로 맞는다(라이브 경로 new_order_rows 와 같은 의미)."""
    OS.save([_claim(uid="lotteon|X|1|S", 판매처="롯데온", 주문일="2026-07-10 09:00:00",
                    _change_date="2026-09-01")], session=session)
    claims = [r for r in OS.load(since="2026-07-01", until="2026-07-31", session=session)
              if r.get("_kind") == "change"]
    assert len(claims) == 1


def test_마켓으로_거른다(session):
    OS.save([_order(uid="smartstore|A"),
             _order(uid="coupang|B1|V1", 판매처="쿠팡")], session=session)
    assert len(OS.load(["coupang"], include_claims=False, session=session)) == 1


def test_적재현황은_마켓별_기간을_알려준다(session):
    OS.save([_order(uid="smartstore|A", 주문일="2026-01-05 10:00:00"),
             _order(uid="smartstore|B", 주문일="2026-07-05 10:00:00")], session=session)
    cov = OS.coverage(session=session)[0]
    assert cov["market"] == "smartstore" and cov["rows"] == 2
    assert cov["oldest"].startswith("2026-01") and cov["newest"].startswith("2026-07")


# ── 저장 안전성 ────────────────────────────────────────────────
def test_직렬화_불가한_값이_있어도_적재가_안_죽는다(session):
    """빌더가 객체를 남기는 경우가 있다. 그것 때문에 주문 전체가 안 쌓이면 안 된다.

    (튜플은 JSON 이 리스트로 받아주므로 살아남는다 — 버리는 건 진짜 직렬화 불가한 값뿐.)
    """
    st = OS.save([_order(_obj=object(), _shipkey=("coupang", "O1"))], session=session)
    assert st["orders_new"] == 1
    saved = OS.load(session=session)[0]
    assert "_obj" not in saved            # 직렬화 불가 → 버림
    assert saved["상품명"] == "티셔츠"      # 나머지는 온전히 저장


def test_마켓키는_line_uid_앞부분에서_뽑는다(session):
    """판매처 표기는 '옥션'/'G마켓' 처럼 한글이라 그대로 쓰면 마켓 필터가 안 맞는다."""
    OS.save([_order(uid="auction|E1", 판매처="옥션")], session=session)
    assert OS.load(["auction"], include_claims=False, session=session)


# ── 날짜불명 클레임 보정 — 저장 주문행(line_uid 조인)에서 실주문일 ────────
def test_날짜없는_클레임에_주문행의_실주문일을_채운다(session):
    """11번가 클레임 727건이 변경일·주문일 둘 다 없어 기간 필터가 못 걸렀다.
    같은 라인의 저장 주문행(line_uid 정확 일치·clm 꼬리 제거)에서 실주문일을
    가져온다 — 추정이 아니라 우리가 이미 가진 실데이터 조인이다."""
    OS.save([_order(uid="eleven11|O1|1", 판매처="11번가",
                    주문일="2026-07-03 10:00:00")], session=session)
    OS.save([_claim(uid="eleven11|O1|1|C9", 판매처="11번가",
                    _change_date="", 주문일="")], session=session)
    st = OS.backfill_claim_dates_from_lines(session=session)
    assert st["filled"] == 1
    claims = [r for r in OS.load(session=session) if r.get("_kind") == "change"]
    assert claims[0]["주문일"].startswith("2026-07-03")
    # 이제 기간 필터가 작동한다
    got = [r for r in OS.load(since="2026-08-01", until="2026-08-31", session=session)
           if r.get("_kind") == "change"]
    assert got == []


def test_날짜있는_클레임은_보정하지_않는다(session):
    OS.save([_claim(uid="coupang|B1|V1", _change_date="2026-07-02")], session=session)
    st = OS.backfill_claim_dates_from_lines(session=session)
    assert st["filled"] == 0


def test_조인상대_없는_클레임은_그대로_둔다(session):
    """짝이 되는 주문행이 없으면 지어내지 않는다(날조 금지) — 공란 유지·보존."""
    OS.save([_claim(uid="eleven11|O9|1|C1", 판매처="11번가",
                    _change_date="", 주문일="")], session=session)
    st = OS.backfill_claim_dates_from_lines(session=session)
    assert st["filled"] == 0
    claims = [r for r in OS.load(session=session) if r.get("_kind") == "change"]
    assert len(claims) == 1 and not claims[0].get("주문일")


# ── 유령 클레임 제거 — 날짜가 생긴 쌍둥이가 있으면 날짜없는 이벤트 정리 ────
def test_날짜_생긴_쌍둥이가_있으면_날짜없는_유령을_지운다(session):
    """이벤트키에 변경일이 들어가서, 같은 클레임을 '날짜 없이 한 번(옛 clmDt 오독)·
    날짜 있게 한 번(재수집)' 받으면 두 이벤트가 된다. 같은 line_uid(클레임 식별자
    포함)·같은 상태원본이면 같은 실제 이벤트 — 정보가 적은 쪽만 지운다."""
    OS.save([_claim(uid="eleven11|O1|1|C1", 판매처="11번가",
                    _change_date="", 주문상태원본="601")], session=session)
    OS.save([_claim(uid="eleven11|O1|1|C1", 판매처="11번가",
                    _change_date="2026-07-03", 주문상태원본="601")], session=session)
    st = OS.dedupe_undated_claim_ghosts(session=session)
    assert st["removed"] == 1
    claims = [r for r in OS.load(session=session) if r.get("_kind") == "change"]
    assert len(claims) == 1
    assert str(claims[0].get("_change_date", "")).startswith("2026-07-03")


def test_유령제거는_상태가_다르면_안_지운다(session):
    """반품요청(날짜없음)과 반품완료(날짜있음)는 다른 이벤트다 — 지우면 이력 소실."""
    OS.save([_claim(uid="eleven11|O1|1|C1", 판매처="11번가",
                    _change_date="", 주문상태원본="601")], session=session)
    OS.save([_claim(uid="eleven11|O1|1|C1", 판매처="11번가",
                    _change_date="2026-07-03", 주문상태원본="A01")], session=session)
    st = OS.dedupe_undated_claim_ghosts(session=session)
    assert st["removed"] == 0
    assert len([r for r in OS.load(session=session)
                if r.get("_kind") == "change"]) == 2

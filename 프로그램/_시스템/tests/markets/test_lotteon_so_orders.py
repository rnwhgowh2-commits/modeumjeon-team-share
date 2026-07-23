# -*- coding: utf-8 -*-
"""롯데온 셀러오피스 크롤분 — 업서트·채움·누락 취소라인 추가·철회 잔존 교정.

배경(2026-07-23 샵마인 387건 대조): OpenAPI 가 구조적으로 못 주는 3종 —
①부분취소의 취소 라인(018057538·018074798) ②취소건 구매자(2218436713 등)
③철회 취소 후 정상 복귀 신호(1917781423). 셀러오피스 화면이 유일 원천.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import lotteon_so as SO


@pytest.fixture
def session():
    from shared.db import Base
    import lemouton.markets.models_shopmine  # noqa: F401 — lotteon_so_orders 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[Base.metadata.tables["lotteon_so_order_lines"]])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _so(od_no, **kw):
    base = {"od_no": od_no, "od_seq": "1", "proc_seq": "1", "status": "취소완료",
            "status_code": "21", "od_typ": "취소(주문취소)", "ch_no": "100195",
            "ordered_at": "2026-07-20 10:00:00", "product_name": "<매장정품> 잔스포츠",
            "option1": "블랙", "qty": "1", "unit_price": "24000",
            "paid_amount": "24000", "buyer": "김구매", "recipient": "김수령",
            "phone": "010-1111-2222", "address": "서울", "tr_no": "LO10161082"}
    base.update(kw)
    return base


# ── 업서트 ──────────────────────────────────────────────────────────────

def test_업서트는_멱등_같은키는_갱신(session):
    st = SO.upsert_rows([_so("2026070100000001"), _so("2026070100000002")], session=session)
    assert st == {"new": 2, "updated": 0, "skipped_no_odno": 0}
    st2 = SO.upsert_rows([_so("2026070100000001", buyer="박구매")], session=session)
    assert st2["updated"] == 1 and st2["new"] == 0
    from lemouton.markets.models_shopmine import LotteonSoOrder
    assert session.get(LotteonSoOrder, ("2026070100000001", "1", "1")).buyer == "박구매"


def test_od_no_없는_라인은_스킵_보고(session):
    st = SO.upsert_rows([_so(""), _so("2026070100000003")], session=session)
    assert st["skipped_no_odno"] == 1 and st["new"] == 1


def test_HTML_이스케이프_정규화(session):
    SO.upsert_rows([_so("2026070100000004", product_name="&lt;매장정품&gt; 커버낫")], session=session)
    from lemouton.markets.models_shopmine import LotteonSoOrder
    assert session.get(LotteonSoOrder, ("2026070100000004", "1", "1")).product_name == "<매장정품> 커버낫"


# ── 채움(빈칸만) ────────────────────────────────────────────────────────

def test_취소행_구매자_빈칸을_채운다(session):
    SO.upsert_rows([_so("2026070100000005")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000005", "주문상태": "취소완료",
         "구매자": "", "수령자": "", "단가": "", "실결제금액": "", "옵션": ""}
    SO.fill_from_so(session, [r])
    assert r["구매자"] == "김구매" and r["수령자"] == "김수령"
    assert r["단가"] == "24000"            # 단일 라인 — 금액도 채움
    assert "_so_filled" in r


def test_기존_값은_덮지_않는다(session):
    SO.upsert_rows([_so("2026070100000006")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000006", "주문상태": "취소완료",
         "구매자": "원래구매자", "단가": 999}
    SO.fill_from_so(session, [r])
    assert r["구매자"] == "원래구매자" and r["단가"] == 999


def test_다품_주문은_옵션_일치_라인만_금액을_채운다(session):
    SO.upsert_rows([_so("2026070100000007", od_seq="1", option1="블랙", unit_price="10000"),
                    _so("2026070100000007", od_seq="2", option1="화이트", unit_price="20000")],
                   session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000007", "주문상태": "취소완료",
         "옵션": "화이트", "단가": "", "구매자": ""}
    SO.fill_from_so(session, [r])
    assert r["단가"] == "20000"            # 옵션 일치 라인
    assert r["구매자"] == "김구매"          # 주문 단위는 어느 라인이든 동일
    r2 = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000007", "주문상태": "취소완료",
          "옵션": "", "단가": "", "구매자": ""}
    SO.fill_from_so(session, [r2])
    assert r2["단가"] == ""                # 라인 미특정 — 금액 안 붙임(날조 금지)
    assert r2["구매자"] == "김구매"


# ── 철회 잔존 교정 (실측 1917781423: 우리 철회 vs 셀러오피스 수취완료) ────────────

def test_철회_잔존을_SO_수취완료로_교정(session):
    SO.upsert_rows([_so("2026070100000008", status="수취완료")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000008", "주문상태": "철회",
         "_kind": "change", "_change_date": "2026-07-21", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "수취완료"
    assert "_kind" not in r                # 정상 행 복귀 → K=원금 강제 해제
    assert r["_so_status_fixed"] == "1"


def test_SO도_클레임이면_교정하지_않는다(session):
    SO.upsert_rows([_so("2026070100000009", status="철회(배송)")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000009", "주문상태": "철회",
         "_kind": "change", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "철회" and r.get("_kind") == "change"


# ── 누락 취소 라인 추가 (부분취소 — 실측 018057538: 수취완료만 있고 취소 라인 없음) ──

def test_우리에_없는_SO_취소라인을_추가한다(session):
    SO.upsert_rows([_so("2026070100000010", od_seq="2", proc_seq="2", status="취소완료")],
                   session=session)
    rows = [{"판매처": "롯데온", "오픈마켓주문번호": "2026070100000010", "주문상태": "수취완료",
             "상품명": "다른상품"}]
    out = SO.add_missing_claims(rows, session)
    assert len(out) == 2
    add = out[1]
    assert add["주문상태"] == "취소완료" and add["_kind"] == "change"
    assert add["단가"] == "24000" and add["구매자"] == "김구매"
    assert add["_so_added"] == "1"


def test_이미_취소행이_있으면_추가하지_않는다(session):
    SO.upsert_rows([_so("2026070100000011", proc_seq="2", status="취소완료")], session=session)
    rows = [{"판매처": "롯데온", "오픈마켓주문번호": "2026070100000011", "주문상태": "취소완료"}]
    assert len(SO.add_missing_claims(rows, session)) == 1


def test_취소완료가_아닌_SO라인은_추가하지_않는다(session):
    SO.upsert_rows([_so("2026070100000012", status="수취완료")], session=session)
    rows = [{"판매처": "롯데온", "오픈마켓주문번호": "2026070100000012", "주문상태": "수취완료"}]
    assert len(SO.add_missing_claims(rows, session)) == 1


# ── 라인 단위 최신 상태(odSeq 고정·procSeq 최대) 로 철회 교정 ────────────────────

def test_같은_라인의_최신_procSeq_가_정상완료면_철회를_교정(session):
    """실측 1917781423: 철회 접수(procSeq 1) 뒤 철회가 취소돼 같은 라인이 수취완료
    (procSeq 2)로 복귀. 옵션만 보면 두 라인이 같아 특정 실패 → 우리 상태(철회)와
    같은 라인을 골라 교정이 안 걸렸다. **같은 odSeq 안에서 procSeq 최대 = 현재 상태**."""
    SO.upsert_rows([_so("2026070100000013", od_seq="1", proc_seq="1", status="철회", status_code="22"),
                    _so("2026070100000013", od_seq="1", proc_seq="2", status="수취완료", status_code="15")],
                   session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000013", "주문상태": "철회",
         "_kind": "change", "_odseq": "1", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "수취완료"
    assert "_kind" not in r
    assert r["_so_status_fixed"] == "1"


def test_부분취소는_교정하지_않는다_다른_odSeq(session):
    """odSeq 가 다르면 '다른 상품 라인' — 한쪽이 수취완료라고 취소 라인을 되살리면 안 된다."""
    SO.upsert_rows([_so("2026070100000014", od_seq="1", proc_seq="2", status="취소완료"),
                    _so("2026070100000014", od_seq="2", proc_seq="1", status="수취완료")],
                   session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000014", "주문상태": "회수지시",
         "_kind": "change", "_odseq": "1", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "회수지시" and r.get("_kind") == "change"


def test_숫자가_아닌_주문번호는_적재하지_않는다(session):
    """진단 프로브 등 오염 행 차단 — 롯데온 주문번호는 숫자만."""
    st = SO.upsert_rows([_so("__PROBE__"), _so("2026072018057538")], session=session)
    assert st["new"] == 1 and st["skipped_no_odno"] == 1


# ── 제휴 판별 3상태 (사장님 요청 2026-07-23): 파악X / 파악O·제휴O / 파악O·제휴X ──

def test_제휴판별_3상태():
    """근거 없이 '롯데ON'으로 단정하면 2% 수수료를 안 뗀 정산이 맞는 것처럼 보인다.
    판별 못 한 건 '확인 불가'로 드러낸다(조용한 단정 금지)."""
    from lemouton.markets.order_export import _lo_affiliate_of as f
    # ① 크롤 판매경로(확정)
    assert f(chnl="제휴", chno="", hist=None) == (True, "제휴")
    assert f(chnl="롯데ON", chno="", hist=None) == (False, "롯데ON")
    # ② 주문 응답 chNo(확정) — 크롤 없을 때
    assert f(chnl=None, chno="100065", hist=None) == (True, "제휴")
    assert f(chnl=None, chno="100195", hist=None) == (False, "롯데ON")
    # ③ 채널을 아직 못 받음 → '미확인' / 받았는데 분류표에 없음 → '확인 불가'
    #    (이력 추정값은 계산에만 쓰고 라벨엔 안 쓴다)
    assert f(chnl=None, chno="999999", hist=True) == (True, "확인 불가")
    assert f(chnl=None, chno="", hist=False) == (False, "미확인")
    assert f(chnl=None, chno="", hist=None) == (False, "미확인")


def test_크롤_판매경로가_chNo보다_우선():
    """크롤은 판매자센터 화면 확정값 — 주문 응답보다 앞선다."""
    from lemouton.markets.order_export import _lo_affiliate_of as f
    assert f(chnl="롯데ON", chno="100065", hist=True) == (False, "롯데ON")


# ── 미확인 vs 확인 불가 구분 + 사유(호버 설명) — 사장님 요청 2026-07-23 ──

def test_판별_사유가_함께_나온다():
    from lemouton.markets.order_export import _lo_affiliate_of as f
    aff, label, why = f(chnl="제휴", chno="", hist=None, detail=True)
    assert (aff, label) == (True, "제휴") and "크롤" in why
    aff, label, why = f(chnl=None, chno="100065", hist=None, detail=True)
    assert (aff, label) == (True, "제휴") and "주문" in why
    # 근거 없음 = 아직 못 받은 것 → '미확인'(확인 불가 아님)
    aff, label, why = f(chnl=None, chno="", hist=True, detail=True)
    assert label == "미확인" and ("아직" in why or "수집" in why)
    # 채널번호는 받았는데 우리 분류표에 없는 새 채널 → 확인 불가(값은 있는데 판정 못 함)
    aff, label, why = f(chnl=None, chno="999999", hist=False, detail=True)
    assert label == "확인 불가" and "999999" in why


def test_SO크롤_채널로_취소행_제휴를_확정한다(session):
    """실측: 확인 못 한 19건이 전부 취소완료 클레임 행(주문 API 가 채널을 안 줌).
    셀러오피스 크롤엔 그 라인의 chNo 가 있다 → 그걸로 확정한다."""
    SO.upsert_rows([_so("2026072118259609", proc_seq="2", ch_no="100065")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026072118259609", "_kind": "change",
         "주문상태": "취소완료", "판매경로": "미확인", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["판매경로"] == "제휴"
    assert "셀러오피스" in r.get("_판매경로사유", "")


def test_SO에도_채널이_없으면_확인불가로_승격(session):
    """수집은 됐는데 원천에 값이 없다 = 봐도 없는 것 → '미확인' 아니라 '확인 불가'."""
    SO.upsert_rows([_so("2026072118234019", proc_seq="2", ch_no="")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026072118234019", "_kind": "change",
         "주문상태": "취소완료", "판매경로": "미확인", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["판매경로"] == "확인 불가"
    assert "없" in r.get("_판매경로사유", "")


def test_이미_확정된_판매경로는_SO가_덮지_않는다(session):
    SO.upsert_rows([_so("2026072118267200", ch_no="100195")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026072118267200", "_kind": "change",
         "주문상태": "취소완료", "판매경로": "제휴", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["판매경로"] == "제휴"


# ── 채널→판매경로 자동 학습 (하드코딩 분류표 드리프트 제거) ─────────────────────

def test_같은_조회의_크롤확정에서_새_채널을_학습한다():
    """분류표에 없는 새 채널이라도, 같은 조회 안에 '크롤로 확정된 같은 채널 주문'이
    있으면 그걸로 판정한다(실측: 채널 100008 이 분류표에 없어 확인 불가였음).
    학습 재료는 크롤 확정분만 — 추정으로 추정을 만들지 않는다."""
    from lemouton.markets.order_export import _lo_learn_channels
    rows = [
        {"_lo_chno": "100008", "판매경로": "제휴", "_판매경로사유": "판매자센터 크롤의 판매경로 값 「제휴」로 확정"},
        {"_lo_chno": "100008", "판매경로": "제휴", "_판매경로사유": "판매자센터 크롤의 판매경로 값 「제휴」로 확정"},
        {"_lo_chno": "100195", "판매경로": "롯데ON", "_판매경로사유": "판매자센터 크롤의 판매경로 값 「롯데ON」로 확정"},
        {"_lo_chno": "100009", "판매경로": "제휴", "_판매경로사유": "주문 데이터의 유입채널 100009 로 확정"},  # 크롤 아님 → 재료 아님
    ]
    learned = _lo_learn_channels(rows)
    assert learned == {"100008": True, "100195": False}


def test_학습된_채널로_미확정행을_승격한다():
    from lemouton.markets.order_export import _lo_apply_learned_channels as apply_
    rows = [
        {"판매경로": "확인 불가", "_lo_chno": "100008"},
        {"판매경로": "미확인", "_lo_chno": "100008"},
        {"판매경로": "미확인", "_lo_chno": ""},          # 채널 없음 → 그대로
        {"판매경로": "롯데ON", "_lo_chno": "100008"},     # 이미 확정 → 안 건드림
    ]
    apply_(rows, {"100008": True})
    assert [r["판매경로"] for r in rows] == ["제휴", "제휴", "미확인", "롯데ON"]
    assert "같은 조회" in rows[0]["_판매경로사유"]
    assert rows[0]["_lo_is_affiliate"] is True


def test_학습_재료가_엇갈리면_학습하지_않는다():
    """같은 채널이 제휴·롯데ON 둘 다로 확정돼 있으면 채널만으로 못 가른다 — 학습 제외."""
    from lemouton.markets.order_export import _lo_learn_channels
    rows = [
        {"_lo_chno": "100010", "판매경로": "제휴", "_판매경로사유": "판매자센터 크롤의 판매경로 값 「제휴」로 확정"},
        {"_lo_chno": "100010", "판매경로": "롯데ON", "_판매경로사유": "판매자센터 크롤의 판매경로 값 「롯데ON」로 확정"},
    ]
    assert _lo_learn_channels(rows) == {}

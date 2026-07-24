# -*- coding: utf-8 -*-
"""마켓이 한 번 알려준 값을 기억해 재사용하는 경로 — 2026-07-25 샵마인 전수 대조 회귀.

발견 경위: 샵마인 정산예상금액과 237개 주문을 대조해 41건이 어긋났고, 그중
  · 롯데온 2건 = 각 단가의 정확히 2.00%(998원·610원) — 제휴 2%가 정산에서 안 빠짐
  · 쿠팡 7건 = 133~167원 — 고정 11.55% 를 쓰는데 실제 요율은 11.67~12.56%
둘 다 근본은 같다: **한 조회 안에서만 아는 값**이라 근거가 그 조회에 없으면 매번 다시 모른다.
"""
import pytest

from lemouton.markets.order_export import (
    _cp_estimate_settle, _cp_learn_fee_rates,
    _lo_affiliate_of, _lo_apply_learned_channels, _lo_learn_channels,
)


# ── 롯데온 판매경로 라벨 ────────────────────────────────────────────────────

def test_분류표에_없는_채널은_확인불가가_아니라_미확인():
    """사장님 확정 2026-07-25 — 제휴가 확인 안 되면 낱말 하나로 '미확인'."""
    aff, label = _lo_affiliate_of(chno="999999", hist=False)
    assert label == "미확인"
    assert aff is False


def test_채널을_아예_못받아도_미확인():
    _, label = _lo_affiliate_of(chno="", hist=False)
    assert label == "미확인"


def test_미확인_두_사정은_사유_문구로_구분된다():
    """라벨은 합쳐도 '왜 모르는지'는 남아야 한다 — 화면 마우스 올림 설명."""
    _, _, why_unlisted = _lo_affiliate_of(chno="999999", hist=False, detail=True)
    _, _, why_missing = _lo_affiliate_of(chno="", hist=False, detail=True)
    assert "분류표에 없는" in why_unlisted
    assert "아직 못 받았" in why_missing
    assert why_unlisted != why_missing


def test_확정_라벨은_그대로():
    assert _lo_affiliate_of(chnl="제휴")[1] == "제휴"
    assert _lo_affiliate_of(chnl="롯데ON")[1] == "롯데ON"
    assert _lo_affiliate_of(chno="100065")[1] == "제휴"      # 하드코딩 제휴 채널
    assert _lo_affiliate_of(chno="100195")[1] == "롯데ON"    # 하드코딩 직영 채널


# ── 롯데온 채널 기억 ────────────────────────────────────────────────────────

def _row(chno, route="미확인", why=""):
    return {"_lo_chno": chno, "판매경로": route, "_판매경로사유": why}


def test_지난조회_기억으로_미확인이_제휴로_승격된다():
    """이 테스트가 고치려는 병 — 이번 조회에 근거가 없어도 기억이 있으면 판정된다."""
    rows = [_row("100008")]
    _lo_apply_learned_channels(rows, learned={}, remembered={"100008": True})
    assert rows[0]["판매경로"] == "제휴"
    assert rows[0]["_lo_is_affiliate"] is True
    assert rows[0]["제휴수수료율"] == 2
    assert "기억해 둔" in rows[0]["_판매경로사유"]


def test_이번조회_근거가_기억보다_우선():
    rows = [_row("100008")]
    _lo_apply_learned_channels(rows, learned={"100008": False},
                               remembered={"100008": True})
    assert rows[0]["판매경로"] == "롯데ON"
    assert "같은 조회" in rows[0]["_판매경로사유"]


def test_옛_확인불가_라벨_저장분도_승격_대상():
    """옛 스냅샷에 남은 라벨 때문에 승격이 건너뛰어지면 안 된다."""
    rows = [_row("100008", route="확인 불가")]
    _lo_apply_learned_channels(rows, learned={}, remembered={"100008": True})
    assert rows[0]["판매경로"] == "제휴"


def test_확정된_행은_기억이_덮지_않는다():
    rows = [_row("100008", route="롯데ON")]
    _lo_apply_learned_channels(rows, learned={}, remembered={"100008": True})
    assert rows[0]["판매경로"] == "롯데ON"


def test_학습은_크롤_확정분에서만():
    """추정분으로 다시 배우면 오류가 자기증식한다."""
    crawled = {"_lo_chno": "100008", "판매경로": "제휴",
               "_판매경로사유": "판매자센터 크롤의 판매경로 값 「제휴」로 확정"}
    guessed = {"_lo_chno": "100009", "판매경로": "제휴",
               "_판매경로사유": "주문 데이터의 유입채널 100009 로 확정"}
    assert _lo_learn_channels([crawled, guessed]) == {"100008": True}


def test_같은채널이_제휴와_직영_둘다면_학습에서_제외():
    a = {"_lo_chno": "100008", "판매경로": "제휴", "_판매경로사유": "크롤 확정"}
    b = {"_lo_chno": "100008", "판매경로": "롯데ON", "_판매경로사유": "크롤 확정"}
    assert _lo_learn_channels([a, b]) == {}


# ── 쿠팡 상품별 실요율 ──────────────────────────────────────────────────────

def test_실요율을_알면_고정값_대신_그걸_쓴다():
    """샵마인 실측 주문 14101725882457: 실결제 50,400 · 실요율 11.88%.

    고정 11.55% → 44,579 (샵마인보다 167원 많음). 실요율 → 44,412 (일치).
    """
    assert _cp_estimate_settle(50400, 1, 0) == 44579                      # 옛 동작
    assert _cp_estimate_settle(50400, 1, 0, fee_rate=0.1188) == 44412     # 고친 뒤


def test_실요율을_모르면_계약_기본율로():
    assert _cp_estimate_settle(50400, 1, 0, fee_rate=None) == 44579


def test_정산_확정분에서_요율을_역산한다():
    rows = [{"_oid": "1", "_vid": "V1", "단가": 50400, "수량": 1}]
    learned = _cp_learn_fee_rates(rows, {("1", "V1"): 44412})
    assert learned == {"V1": pytest.approx(0.1188, abs=1e-4)}


def test_판매자부담할인은_요율_역산에서_빠진다():
    rows = [{"_oid": "1", "_vid": "V1", "단가": 60400, "수량": 1,
             "_cp_seller_dc": 10000}]
    learned = _cp_learn_fee_rates(rows, {("1", "V1"): 44412})
    assert learned == {"V1": pytest.approx(0.1188, abs=1e-4)}


def test_상식_범위_밖_요율은_안_배운다():
    """부분취소·조정이 섞여 요율처럼 보이는 값 — 기억하면 그 상품이 통째로 틀린다."""
    rows = [{"_oid": "1", "_vid": "V1", "단가": 50400, "수량": 1}]
    assert _cp_learn_fee_rates(rows, {("1", "V1"): 5000}) == {}    # 90% 요율
    assert _cp_learn_fee_rates(rows, {("1", "V1"): 50390}) == {}   # 0.02% 요율


def test_같은상품_요율이_갈리면_제외():
    rows = [{"_oid": "1", "_vid": "V1", "단가": 50400, "수량": 1},
            {"_oid": "2", "_vid": "V1", "단가": 50400, "수량": 1}]
    assert _cp_learn_fee_rates(rows, {("1", "V1"): 44412, ("2", "V1"): 44579}) == {}


def test_미정산분은_학습_재료가_아니다():
    rows = [{"_oid": "1", "_vid": "V1", "단가": 50400, "수량": 1}]
    assert _cp_learn_fee_rates(rows, {}) == {}

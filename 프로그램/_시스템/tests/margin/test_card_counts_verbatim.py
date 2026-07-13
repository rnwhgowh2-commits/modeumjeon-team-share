# -*- coding: utf-8 -*-
r"""골든 회귀 — 서버측 블랙스팟 카드 집계 `compute_card_counts` (원본 verbatim 이식).

원본 마진계산기 app.py:1532 는 `_compute_card_counts(store['matched'], source='matched')`
로 ⚫블랙스팟 카드 숫자를 서버에서 계산한다. 우리 포트는 이 함수를
lemouton/margin/card_counts.py 로 그대로(verbatim) 옮겼고, api_margin._augment_blackspot
이 out['matched'] 로 호출해 summary.card_* 를 채운다. 이식 전에는 aggregator 가 0 으로
두고 덮어쓰지 않아 매입흔적(card_all)·mango_with_trace 가 0 이었다.

이 테스트는 원본과 동일 입력(260712 더망고 + 샵마인)을 우리 전체 체인
(parse_buy → from_shopmine_excel → pipeline.run → compute_card_counts) 에 흘려,
원본 스크린샷 카드 숫자를 정확히 재현하는지 매 변경마다 지킨다.

■ PII 비커밋 원칙 — 실주문 데이터(수령인·송장·주문번호)는 저장소에 넣지 않는다.
  실데이터 폴더가 없으면(팀원/CI PC) pytest.skip — 원본 260704 골든 테스트와 동일한
  '데이터 부재 시 스킵' 관례. dev PC 에서만 실행되어 회귀를 지킨다.

원본 스크린샷(260712) 확정값:
  매입흔적 219 · 정상 94 · 발송대기 36 · 까대기 63 · 반품/취소 진행중 20
  · 완료(메모O) 4 · 완료(메모X) 1 · 기타 1 · (즉시/소싱처/마켓 확인 0)
"""
import glob
import json
import os

import pytest

from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.card_counts import compute_card_counts
from lemouton.margin.sell_source import from_shopmine_excel
from lemouton.margin import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
SYS_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SEED = os.path.join(SYS_ROOT, "lemouton", "margin", "card_keywords_seed.json")
# 실주문 데이터 — 저장소 밖(원본 프로그램 데이터 폴더). 없으면 스킵.
DATA_DIR = r"C:/dev/대량등록 마진계산기/데이터/260712"

# 원본 스크린샷(260712) 고정값 — source='matched'.
EXPECTED = {
    "card_all": 219,
    "card_normal": 94,
    "card_pending": 36,
    "card_kkadaegi": 63,
    "card_inprogress": 20,
    "card_completed_memo_yes": 4,
    "card_completed_memo_no": 1,
    "card_etc": 1,
    "card_immediate": 0,
    "card_sourcing": 0,
    "card_market": 0,
    "card_tracking_failed": 0,
    "card_confirmed_blackspot": 0,
    "card_mango_check": 0,
    "card_status_mismatch": 0,
    "card_memo_settled": 0,
}


def _find(pat):
    g = glob.glob(os.path.join(DATA_DIR, pat))
    return g[0] if g else None


def _matched():
    """실 260712 더망고+샵마인 → 우리 파이프라인 matched (원본 store['matched'] 대응)."""
    bf, sf = _find("*더망고*.xls"), _find("*샵마인*.xls")
    if not (bf and sf):
        pytest.skip(f"260712 실데이터 폴더 부재: {DATA_DIR} (팀원/CI PC 에는 없음)")
    buy_df = parse_buy(open(bf, "rb").read(), os.path.basename(bf))
    sell_df = from_shopmine_excel(open(sf, "rb").read(), os.path.basename(sf))
    return pipeline.run(buy_df, sell_df)["matched"]


def _seed_cards():
    with open(SEED, encoding="utf-8") as f:
        return json.load(f).get("cards", {})


def test_card_counts_golden_260712():
    """전체 체인 × 원본 동일 입력 → 스크린샷 카드 숫자 정확 일치 (verbatim 회귀)."""
    cards = compute_card_counts(_matched(), source="matched", card_kw=_seed_cards())
    mism = {k: (EXPECTED[k], cards.get(k)) for k in EXPECTED if cards.get(k) != EXPECTED[k]}
    assert not mism, f"카드 숫자 불일치 (기대, 실제): {mism}"


def test_card_partition_sums_to_all():
    """상호배타 분류 → 비영 카드 합 == card_all(매입흔적 219). 누락/이중계상 감지."""
    cards = compute_card_counts(_matched(), source="matched", card_kw=_seed_cards())
    parts = sum(cards[k] for k in EXPECTED if k != "card_all")
    assert parts == cards["card_all"] == 219, (
        f"파티션 합 {parts} != card_all {cards['card_all']} (배타 분류 위반)"
    )

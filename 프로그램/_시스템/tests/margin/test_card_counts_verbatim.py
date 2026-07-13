# -*- coding: utf-8 -*-
r"""골든 회귀 — 블랙스팟 카드 집계 `compute_card_counts` (원본 verbatim 이식 + 매입흔적 anchor).

원본 app.py `_compute_card_counts` 를 lemouton/margin/card_counts.py 로 그대로(verbatim)
이식하고, api_margin._augment_blackspot 이 **source='classified'** 로 호출해 summary.card_*
를 채운다.

■ 왜 source='classified' 인가 — **더망고 매입흔적 주문건이 분석 기준(anchor)**:
  원본은 매출=샵마인(전건 커버)이라 source='matched'(store['matched'])가 곧 매입흔적 전건이었다.
  우리 매출=마켓 API 는 연동 안 된 마켓(옥션/G마켓)·정산 미확정분을 **부분 커버** 하므로,
  matched 만 세면 매입흔적 카운트가 API 커버리지에 따라 줄어드는 오검출이 난다.
  source='classified' 는 classified(매칭분) + buy_df 매입흔적 미매칭행(가상행)을 합쳐
  **더망고 매입흔적 전건**을 센다 → API 가 무엇을 커버하든 매입흔적 anchor 가 불변.
  (클라이언트 _getRowsByCardFilter('all') = matched+가상행 과 동일 계산.)

■ PII 비커밋 — 실주문(수령인·송장·주문번호)은 저장소에 넣지 않는다. 실데이터 폴더 없으면
  pytest.skip (원본 260704 골든과 동일 관례). dev PC 에서만 회귀 실행.

원본 스크린샷(260712, 전건 커버) 확정값(anchor 기준):
  매입흔적 220 · 정상 94 · 발송대기 35 · 까대기 63 · 진행중 20 · 완료O 4 · 완료X 1 · 기타 2
"""
import glob
import json
import os

import pytest

from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.card_counts import compute_card_counts
from lemouton.margin.sell_source import from_shopmine_excel
from lemouton.margin import classifier, matcher, pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
SYS_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SEED = os.path.join(SYS_ROOT, "lemouton", "margin", "card_keywords_seed.json")
DATA_DIR = r"C:/dev/대량등록 마진계산기/데이터/260712"

# 전건 커버(전체 샵마인) 시 anchor 카드값.
EXPECTED_FULL = {
    "card_all": 220,
    "card_normal": 94,
    "card_pending": 35,
    "card_kkadaegi": 63,
    "card_inprogress": 20,
    "card_completed_memo_yes": 4,
    "card_completed_memo_no": 1,
    "card_etc": 2,
}


def _find(pat):
    g = glob.glob(os.path.join(DATA_DIR, pat))
    return g[0] if g else None


def _seed_cards():
    with open(SEED, encoding="utf-8") as f:
        return json.load(f).get("cards", {})


def _cards_for(sell_df, buy_df):
    """api_margin._augment_blackspot 과 동일 경로: buy_valid classify + source='classified'."""
    buy_valid, _ = pipeline.split_by_site_order_no(buy_df)
    mc = matcher.match_for_classifier(buy_valid, sell_df)
    cls = classifier.classify(mc["matched"], mc["mango_unmatched"], mc["shopmine_only"])
    return compute_card_counts(
        cls["classified"], buy_df_raw=buy_df, source="classified", card_kw=_seed_cards())


def _load():
    bf, sf = _find("*더망고*.xls"), _find("*샵마인*.xls")
    if not (bf and sf):
        pytest.skip(f"260712 실데이터 폴더 부재: {DATA_DIR} (팀원/CI PC 에는 없음)")
    buy_df = parse_buy(open(bf, "rb").read(), os.path.basename(bf))
    sell_full = from_shopmine_excel(open(sf, "rb").read(), os.path.basename(sf))
    return buy_df, sell_full


def test_card_counts_golden_260712():
    """전건 커버 → 원본 스크린샷 anchor 카드값 정확 일치 (verbatim 회귀)."""
    buy_df, sell_full = _load()
    cards = _cards_for(sell_full, buy_df)
    mism = {k: (EXPECTED_FULL[k], cards.get(k)) for k in EXPECTED_FULL if cards.get(k) != EXPECTED_FULL[k]}
    assert not mism, f"카드 숫자 불일치 (기대, 실제): {mism}"


def test_maeip_anchor_invariant_to_api_coverage():
    """★핵심 — 매입흔적(card_all) 은 API 커버리지에 불변.

    매출원(샵마인)에서 옥션/G마켓을 빼 'API 미연동' 을 시뮬레이션해도 매입흔적 anchor 는
    그대로여야 한다. matched 만 세면(과거 버그) 이 값이 줄어든다."""
    buy_df, sell_full = _load()
    esm = sell_full["쇼핑몰"].astype(str).str.contains("옥션|G마켓|지마켓", na=False)
    sell_noesm = sell_full[~esm].reset_index(drop=True)
    full = _cards_for(sell_full, buy_df)["card_all"]
    noesm = _cards_for(sell_noesm, buy_df)["card_all"]
    assert full == noesm == 220, (
        f"매입흔적 anchor 가 API 커버리지에 흔들림: 전건={full} vs ESM제거={noesm} (불변이어야 220)"
    )

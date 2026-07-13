# -*- coding: utf-8 -*-
r"""골든 회귀 — 서버측 블랙스팟 카드 집계 `compute_card_counts` (원본 verbatim 이식).

원본 app.py:1532 `_compute_card_counts(store['matched'], source='matched')` 를
lemouton/margin/card_counts.py 로 그대로(verbatim) 이식하고, api_margin._augment_blackspot
이 out['matched'](= 원본 store['matched']: match_data(full 더망고) + _주문미이행/_매입흔적)로
**source='matched'** 호출해 summary.card_* 를 채운다.

■ 왜 source='matched' 인가 (source='classified' 아님):
  classified 행엔 분류기가 매긴 상세분류(1-1_정상거래 등)가 실려 코드 기반 분기(is_normal_code)가
  되살아나 정상 카드가 부풀고 기타가 0 이 된다(260714 실측: classified→정상 68·기타 0, 원본은
  정상 49·기타 19). 원본 스크린샷은 상세분류 없는 matched 로 메모·상태 분기만 태운다. → matched.

■ 표시 카드 타일은 페이지 JS `_getRowsByCardFilter`(matched+가상행) 가 단일 진실 원천이며
  이 함수와 바이트 동치(260704 골든 test_blackspot_card_numbers_golden). 서버 summary.card_* 는
  배너 폴백·export·API 소비자용. 즉 사용자가 보는 분류 = 클라 JS = 원본과 동일 데이터면 동일 결과.

■ PII 비커밋 — 실주문(수령인·송장·주문번호)은 저장소에 넣지 않는다. 실데이터 폴더 없으면
  pytest.skip (원본 260704 골든과 동일 관례). dev PC 에서만 회귀 실행.

원본 서버 `_compute_card_counts(store['matched'], source='matched')` 확정값(전건 커버=샵마인):
  260712 — 매입흔적 219·정상 94·발송대기 36·까대기 63·진행중 20·완료O 4·완료X 1·기타 1
  260714 — 매입흔적 154·정상 49·발송대기 60·까대기 19·진행중 4·기타 19·더망고점검 2·송장재전송 1
"""
import glob
import json
import os
import shutil
import subprocess
import tempfile

import pytest

from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.card_counts import compute_card_counts
from lemouton.margin.sell_source import from_shopmine_excel
from lemouton.margin import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
SYS_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SEED = os.path.join(SYS_ROOT, "lemouton", "margin", "card_keywords_seed.json")
DATA_ROOT = r"C:/dev/대량등록 마진계산기/데이터"

# 원본 서버 _compute_card_counts(store['matched'], source='matched') 확정값.
GOLDEN = {
    "260712": {
        "card_all": 219, "card_normal": 94, "card_pending": 36, "card_kkadaegi": 63,
        "card_inprogress": 20, "card_completed_memo_yes": 4, "card_completed_memo_no": 1,
        "card_etc": 1, "card_mango_check": 0, "card_tracking_failed": 0,
        "card_status_mismatch": 0, "card_confirmed_blackspot": 0, "card_memo_settled": 0,
        "card_immediate": 0, "card_sourcing": 0, "card_market": 0,
    },
    "260714": {
        "card_all": 154, "card_normal": 49, "card_pending": 60, "card_kkadaegi": 19,
        "card_inprogress": 4, "card_completed_memo_yes": 0, "card_completed_memo_no": 0,
        "card_etc": 19, "card_mango_check": 2, "card_tracking_failed": 1,
        "card_status_mismatch": 0, "card_confirmed_blackspot": 0, "card_memo_settled": 0,
        "card_immediate": 0, "card_sourcing": 0, "card_market": 0,
    },
}


def _seed_cards():
    with open(SEED, encoding="utf-8") as f:
        return json.load(f).get("cards", {})


def _matched(date):
    """실 date 더망고+샵마인 → 우리 파이프라인 matched (원본 store['matched'] 대응)."""
    ddir = os.path.join(DATA_ROOT, date)

    def find(pat):
        g = glob.glob(os.path.join(ddir, pat))
        return g[0] if g else None

    bf, sf = find("*더망고*.xls"), find("*샵마인*.xls")
    if not (bf and sf):
        pytest.skip(f"{date} 실데이터 폴더 부재: {ddir} (팀원/CI PC 에는 없음)")
    buy_df = parse_buy(open(bf, "rb").read(), os.path.basename(bf))
    sell_df = from_shopmine_excel(open(sf, "rb").read(), os.path.basename(sf))
    return pipeline.run(buy_df, sell_df)["matched"]


@pytest.mark.parametrize("date", sorted(GOLDEN))
def test_card_counts_golden(date):
    """전체 체인 × 원본 동일 입력 → 원본 서버 카드 숫자 정확 일치 (verbatim 회귀)."""
    cards = compute_card_counts(_matched(date), source="matched", card_kw=_seed_cards())
    exp = GOLDEN[date]
    mism = {k: (exp[k], cards.get(k)) for k in exp if cards.get(k) != exp[k]}
    assert not mism, f"[{date}] 카드 숫자 불일치 (기대, 실제): {mism}"


@pytest.mark.parametrize("date", sorted(GOLDEN))
def test_card_partition_sums_to_all(date):
    """상호배타 분류 → 비영 카드 합 == card_all. 누락/이중계상 감지."""
    cards = compute_card_counts(_matched(date), source="matched", card_kw=_seed_cards())
    parts = sum(cards[k] for k in GOLDEN[date] if k != "card_all")
    assert parts == cards["card_all"], (
        f"[{date}] 파티션 합 {parts} != card_all {cards['card_all']} (배타 분류 위반)"
    )


# 사용자가 화면에서 보는 카드 = 페이지 JS `_getRowsByCardFilter`(matched+가상행) 계산.
# 260714 원본 스크린샷(사용자 제공) 확정값 — 클라 카드체인이 그대로 재현해야 한다.
# (전건 커버=샵마인. 매입흔적 155 = matched 154 + 가상행 1 → 가상행은 더망고점검으로 분류.)
CLIENT_GOLDEN_260714 = {
    "all": 155, "normal": 49, "pending": 60, "kkadaegi": 19, "mango_check": 3,
    "etc": 19, "tracking_failed": 1, "inprogress": 4, "status_mismatch": 0,
    "confirmed_blackspot": 0, "memo_settled": 0, "completed_memo_yes": 0,
    "completed_memo_no": 0, "immediate": 0, "sourcing": 0, "market": 0,
}


def test_client_card_chain_matches_screenshot_260714():
    """★사용자 화면 검증 — 클라 JS 카드체인(matched+가상행)이 원본 260714 스크린샷과 정확 일치.

    표시 카드 타일은 서버 summary.card_* 가 아니라 이 클라 계산이 단일 진실 원천이다.
    node/데이터 부재 시 skip(원본 260704 골든과 동일)."""
    from tests.margin import _card_golden_helper as helper
    date = "260714"
    if not helper.data_available(date):
        pytest.skip(f"{date} 실데이터 폴더 부재 (팀원/CI PC 에는 없음)")
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 없음 — 카드체인 harness 실행 불가")
    harness = os.path.join(HERE, "card_chain_harness.js")
    rules = os.path.join(SYS_ROOT, "webapp", "static", "margin_rules.js")
    tmp = tempfile.mkdtemp()
    dp = os.path.join(tmp, f"analysisData_{date}.json")
    helper.write_analysis_data(date, dp)
    proc = subprocess.run([node, harness, dp, rules],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, f"harness 실패: {proc.stderr[:600]}"
    cards = json.loads(proc.stdout)["cards"]
    mism = {k: (v, cards.get(k)) for k, v in CLIENT_GOLDEN_260714.items() if cards.get(k) != v}
    assert not mism, f"클라 카드 ≠ 스크린샷 (기대, 실제): {mism}"

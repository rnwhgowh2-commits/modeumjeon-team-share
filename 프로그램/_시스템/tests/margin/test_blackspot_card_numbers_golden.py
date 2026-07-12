# -*- coding: utf-8 -*-
r"""골든 회귀 — ⚫블랙스팟 탭 카드 숫자 (260704 데이터, 원본 스크린샷 고정).

원본 마진계산기의 블랙스팟 탭 스크린샷(260704, matched=166)이 내는 카드 숫자를
'이식된 클론'이 정확히 재현하는지 매 변경마다 지킨다.

동작:
  1) analysisData 를 `_card_golden_helper` 로 빌드 — api_margin.analyze() 를 그대로
     미러(샵마인 EXCEL 을 sell_df 로 치환).
  2) 클라이언트 카드 체인(webapp/templates/orders/margin_embed.html 의
     _getRowsByCardFilter* + 키워드 헬퍼)을 byte-identical 하게 슬라이스한
     `card_chain_harness.js` 를 node 로 실행.
  3) 카드 숫자를 스크린샷 값과 정확 대조 + 파티션 합(3+11+60+91+1==166) 검증.

드리프트 방지:
  harness 의 모든 VERBATIM 블록이 '현재 margin_embed.html 의 substring' 인지 검사한다.
  누군가 페이지의 해당 함수를 고치면 슬라이스가 더 이상 substring 이 아니게 되어 이 가드가
  큰 소리로 실패한다(어느 블록이 어긋났는지 지목). 런타임 brace-추출 대신 substring-포함
  방식을 쓴 이유: _hasUnknownKoreanInMemo 등은 정규식 리터럴에 리터럴 중괄호 `\{ \}` 를
  담고 있어, 함수 경계를 brace 카운트로 찾으면 오판한다(제대로 하려면 JS 토크나이저가
  필요하고 그 자체가 오탐 위험). substring 포함은 파서 없이 동일한 'fail-loud' 보장을 준다.

스킵(에러 아님): 260704 데이터 폴더가 없거나(팀원/CI PC) node 가 없으면 pytest.skip.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from tests.margin import _card_golden_helper as helper

DATE = "260704"

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "card_chain_harness.js")
SYS_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MARGIN_EMBED = os.path.join(SYS_ROOT, "webapp", "templates", "orders", "margin_embed.html")
MARGIN_RULES = os.path.join(SYS_ROOT, "webapp", "static", "margin_rules.js")

# 원본 스크린샷 고정값 (과제 명시) ─────────────────────────────────────────────
EXPECTED_CARDS = {
    "all": 166,
    "immediate": 0, "sourcing": 0, "market": 0,
    "mango_check": 0, "status_mismatch": 0, "etc": 3,
    "normal": 11, "pending": 60, "kkadaegi": 91,
    "tracking_failed": 1,
    "confirmed_blackspot": 0, "memo_settled": 0,
    "inprogress": 0, "completed_memo_yes": 0, "completed_memo_no": 0,
    "margin": 0,
}
EXPECTED_TRACKING_SPLIT = {"normal": 1, "etc": 0, "total": 1}
EXPECTED_DATA_VERIFY = {"1-1": 166, "1-2": 0, "1-3": 0}
EXPECTED_UNFULFILLED = 0
EXPECTED_ABNORMAL = 1


def _node():
    return shutil.which("node")


# ── 가드 헬퍼 ────────────────────────────────────────────────────────────────

def _requires_data():
    if not helper.data_available(DATE):
        pytest.skip(f"260704 데이터 폴더 없음: {helper.DATA_ROOT} (팀원/CI PC 에는 부재)")


def _requires_node():
    if _node() is None:
        pytest.skip("node 실행파일 없음 — 카드 체인 harness 실행 불가")


def _extract_verbatim_blocks(harness_text):
    """harness 에서 표준 라인 마커로 감싼 VERBATIM 블록들을 순서대로 추출."""
    blocks, cur, inside = [], [], False
    for line in harness_text.splitlines():
        t = line.strip()
        if t == "/* VERBATIM_BEGIN */":
            assert not inside, "중첩된 VERBATIM_BEGIN"
            inside, cur = True, []
            continue
        if t == "/* VERBATIM_END */":
            assert inside, "짝 없는 VERBATIM_END"
            blocks.append("\n".join(cur))
            inside = False
            continue
        if inside:
            cur.append(line)
    assert not inside, "닫히지 않은 VERBATIM_BEGIN"
    return blocks


# ── 1) 드리프트 가드 — harness 슬라이스 == 현재 페이지 substring ────────────────

def test_harness_slices_match_current_page():
    """harness 의 모든 VERBATIM 슬라이스가 현재 margin_embed.html 안에 그대로 존재."""
    with open(HARNESS, encoding="utf-8") as f:
        harness_text = f.read()
    with open(MARGIN_EMBED, encoding="utf-8") as f:
        page_text = f.read()

    blocks = _extract_verbatim_blocks(harness_text)
    assert blocks, "harness 에 VERBATIM 블록이 하나도 없음 (마커 파괴?)"

    drifted = []
    for i, block in enumerate(blocks):
        if block not in page_text:
            first = block.splitlines()[0] if block.splitlines() else "(빈 블록)"
            drifted.append(f"블록 #{i} (시작: {first!r})")
    assert not drifted, (
        "margin_embed.html 이 바뀌어 harness 슬라이스가 드리프트했습니다. "
        "아래 블록을 페이지 현재 코드로 다시 복사하세요:\n  " + "\n  ".join(drifted)
    )


# ── 2) 골든 카드 숫자 ─────────────────────────────────────────────────────────

def _run_chain(tmp_path):
    _requires_data()
    _requires_node()
    data_path = os.path.join(str(tmp_path), f"analysisData_{DATE}.json")
    helper.write_analysis_data(DATE, data_path)
    proc = subprocess.run(
        [_node(), HARNESS, data_path, MARGIN_RULES],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, f"node harness 실패:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    return json.loads(proc.stdout)


def test_blackspot_card_numbers_golden(tmp_path):
    result = _run_chain(tmp_path)
    cards = result["cards"]

    # 카드별 정확 대조
    mism = {k: (EXPECTED_CARDS[k], cards.get(k))
            for k in EXPECTED_CARDS if cards.get(k) != EXPECTED_CARDS[k]}
    assert not mism, f"카드 숫자 불일치 (기대, 실제): {mism}"

    # 송장 재전송 실패 split (정상종료 1 / 기타 0)
    assert result["tracking_split"] == EXPECTED_TRACKING_SPLIT, (
        f"tracking split 불일치: {result['tracking_split']}"
    )

    # 매입 흔적 데이터검증 배너 (1-1 / 1-2 / 1-3)
    assert result["data_verify"] == EXPECTED_DATA_VERIFY, (
        f"데이터검증(1-1/1-2/1-3) 불일치: {result['data_verify']}"
    )

    # 주문 미이행 / 이상마진
    assert result["unfulfilled"] == EXPECTED_UNFULFILLED, (
        f"주문미이행 불일치: {result['unfulfilled']}"
    )
    assert result["abnormal_margin"] == EXPECTED_ABNORMAL, (
        f"이상마진 불일치: {result['abnormal_margin']}"
    )

    # 나머지 진행중/완료 split 은 전부 0 (스크린샷)
    for key in ("inprogress_split", "completed_memo_yes_split", "completed_memo_no_split"):
        assert result[key]["total"] == 0, f"{key} total != 0: {result[key]}"

    # banner_trace = mango_with_trace(0) || cnt('all')(166) = 166
    assert result["banner_trace"] == 166, f"banner_trace 불일치: {result['banner_trace']}"


def test_partition_sums_to_total(tmp_path):
    """if/elif 배타 분류 → 비영(非零) 카드 합이 전체(166)와 정확히 일치."""
    cards = _run_chain(tmp_path)["cards"]
    assert cards["etc"] + cards["normal"] + cards["pending"] \
        + cards["kkadaegi"] + cards["tracking_failed"] == cards["all"] == 166, (
        f"파티션 합 불일치: 3+11+60+91+1 != {cards['all']} "
        f"(etc={cards['etc']} normal={cards['normal']} pending={cards['pending']} "
        f"kkadaegi={cards['kkadaegi']} tracking_failed={cards['tracking_failed']})"
    )

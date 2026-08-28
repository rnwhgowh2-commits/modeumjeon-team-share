# -*- coding: utf-8 -*-
r"""_isExchangeRow 회귀 —
  1) 더망고 복합 라벨("반품/교환/취소완료" 등)만 있고 실제 마켓 상태(샵마인_주문상태)는
     정상 완료인 행을 반품·취소로 오판해 정산을 지우던 버그
     (2026-08-25 사장님 지적으로 발견, 라이브 실측 113건).
  2) 간단메모에 "철회"(취소철회·반품철회 = 취소/반품 신청했다가 철회돼 정상으로 되돌아간
     것)가 있으면 정상 처리해야 하는데, 그 상태 문자열 자체가 "취소"·"반품" 글자를
     포함해 반품/취소 키워드 매칭에 먼저 걸려 반대로 제외되던 버그
     (2026-08-26 사장님 명시).

이 함수는 tests/margin/card_chain_harness.js 의 VERBATIM 블록으로 보호돼 있고
(test_blackspot_card_numbers_golden.py::test_harness_slices_match_current_page 가
현재 margin_embed.html 의 substring 인지 매번 검사), 그 블록을 그대로 node 로 실행해
동작을 검증한다.
"""
import os
import re
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "card_chain_harness.js")


def _requires_node():
    if shutil.which("node") is None:
        pytest.skip("node 실행파일 없음")


def _extract_function(name):
    """harness 에서 `function <name>(...) { ... }` 블록을 중괄호 균형으로 추출."""
    text = open(HARNESS, encoding="utf-8").read()
    m = re.search(r"function %s\(" % re.escape(name), text)
    assert m, f"{name} 못 찾음"
    start = m.start()
    depth = 0
    i = text.index("{", start)
    j = i
    while True:
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return text[start:j + 1]


def test_is_exchange_row_trusts_shopmine_status_when_labels_ambiguous():
    _requires_node()
    fn_src = _extract_function("_isExchangeRow")
    script = fn_src + r"""
    // 카드 키워드 스텁 — sub_ex/sub_rtn 둘 다 실제 운영값(교환/반품·취소)으로 가정.
    function _kw(cardType, field) {
      if (field === 'sub_ex')  return ['교환'];
      if (field === 'sub_rtn') return ['반품', '취소'];
      return [];
    }

    // 1) 더망고 복합 라벨("반품/교환/취소완료")만 있고, 실제 마켓 상태(샵마인)는
    //    배송완료 — 라벨을 벗겨내면 신호가 통째로 사라지는 케이스. 정산을 지우면 안 됨.
    const ambiguousButDone = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소완료',
      '샵마인_주문상태': '배송완료', '샵마인_샵마인주문상태': '',
    };
    // 2) 실제 마켓 상태 자체가 반품완료 — 진짜 반품이므로 그대로 제외돼야 함.
    const realReturn = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소완료',
      '샵마인_주문상태': '반품완료', '샵마인_샵마인주문상태': '',
    };
    // 3) 명시적으로 '교환' 키워드가 걸리는 케이스(기존 동작 유지 확인).
    const explicitExchange = {
      '간단메모': '교환 처리함', '더망고주문상태 (사용자 연동)': '국내배송중',
      '샵마인_주문상태': '배송중', '샵마인_샵마인주문상태': '',
    };
    // 4) 실제 마켓 상태도 불명(회수지시 등, 정상완료 목록에 없음) — 기존대로 보수적 제외.
    const genuinelyAmbiguous = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소 진행중',
      '샵마인_주문상태': '회수지시', '샵마인_샵마인주문상태': '',
    };
    // 5) 간단메모에 "철회" — 상태 자체는 "취소철회"처럼 "취소" 글자를 포함해 반품/취소
    //    키워드에 먼저 걸릴 뻔하지만, 철회는 그보다 우선해 정상(true) 처리돼야 함.
    const withdrawnCancel = {
      '간단메모': '26.08.20 무신사 / 영빈 취소철회 처리함', '더망고주문상태 (사용자 연동)': '국내배송중',
      '샵마인_주문상태': '취소철회(구매확정)', '샵마인_샵마인주문상태': '',
    };
    console.log(JSON.stringify({
      ambiguousButDone: _isExchangeRow(ambiguousButDone, 'completed_memo_yes'),
      realReturn: _isExchangeRow(realReturn, 'completed_memo_yes'),
      explicitExchange: _isExchangeRow(explicitExchange, 'completed_memo_yes'),
      genuinelyAmbiguous: _isExchangeRow(genuinelyAmbiguous, 'inprogress'),
      withdrawnCancel: _isExchangeRow(withdrawnCancel, 'inprogress'),
    }));
    """
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout.strip())
    assert out["ambiguousButDone"] is True     # 정상 완료 → 정산 유지(교환과 동일 취급)
    assert out["realReturn"] is False           # 진짜 반품완료 → 그대로 제외
    assert out["explicitExchange"] is True      # 명시적 교환 키워드 → 기존대로 유지
    assert out["genuinelyAmbiguous"] is False   # 둘 다 불명 → 기존대로 보수적 제외
    assert out["withdrawnCancel"] is True       # 메모에 "철회" → 반품/취소 키워드보다 우선해 정상

# -*- coding: utf-8 -*-
r"""_isExchangeRow 회귀 —
  2026-09-05 사장님 확정 — "교환"은 간단메모 또는 마켓상태(샵마인_주문상태·
  마켓주문상태)에 sub_ex 키워드("교환")가 명확히 있을 때만. 그 전엔 더망고 복합
  라벨("반품/교환/취소완료" 등)만 있고 실제 마켓 상태가 정상 진행/완료류 문자열과
  우연히 일치하면 "교환"으로 넘기는 fallback 이 있었는데(2026-08-25 도입,
  113건 정산 오삭제를 막으려던 것), 실측 결과 그 fallback 이 잡은 건 전부 "교환"
  근거가 없었다(사장님 지적) — 이번에 제거.
  간단메모 "철회"(취소철회·반품철회)는 카드 배정 우선순위 3순위(has_settled_memo)에서
  이미 'memo_settled' 카드로 먼저 걸러지므로 이 함수까지 오지 않는다 — 함수 자체는
  더 이상 "철회"를 특별 취급하지 않는다.

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


def test_is_exchange_row_requires_explicit_exchange_evidence():
    _requires_node()
    fn_src = _extract_function("_isExchangeRow")
    script = fn_src + r"""
    // 카드 키워드 스텁 — sub_ex 실제 운영 기본값('교환')으로 가정.
    function _kw(cardType, field) {
      if (field === 'sub_ex') return ['교환'];
      return [];
    }
    function _matchesAny(text, keywords) {
      if (!keywords || !keywords.length) return false;
      for (var i = 0; i < keywords.length; i++) {
        if (text.indexOf(keywords[i]) >= 0) return true;
      }
      return false;
    }

    // 1) 더망고 복합 라벨("반품/교환/취소완료")만 있고 샵마인_주문상태는 "배송완료" —
    //    간단메모/마켓상태 어디에도 "교환" 글자가 없다 → 반품/취소(false). 더망고주문상태는
    //    이제 검사 대상이 아니므로 이 필드값은 무시된다.
    const noExchangeEvidence = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소완료',
      '샵마인_주문상태': '배송완료', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '',
    };
    // 2) 실제 마켓 상태 자체가 반품완료 — 진짜 반품이므로 그대로 제외.
    const realReturn = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소완료',
      '샵마인_주문상태': '반품완료', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '',
    };
    // 3) 간단메모에 명시적 '교환' 키워드.
    const explicitExchangeMemo = {
      '간단메모': '교환 처리함', '더망고주문상태 (사용자 연동)': '국내배송중',
      '샵마인_주문상태': '배송중', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '',
    };
    // 4) 샵마인_주문상태에 명시적 '교환' — 마켓상태 신호로도 인정돼야 함(신규).
    const explicitExchangeShopmine = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소완료',
      '샵마인_주문상태': '교환접수', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '',
    };
    // 5) 마켓주문상태(오픈 마켓 연동)에 명시적 '교환신청' — 이 필드도 신규로 검사 대상.
    const explicitExchangeMarketField = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소 진행중',
      '샵마인_주문상태': '', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '교환신청',
    };
    // 6) 마켓주문상태가 복합 라벨("취소/반품/교환 완료") 그 자체 — 벗겨내면 "교환" 근거가
    //    안 남으므로 반품/취소(false). 복합 라벨 자체를 "교환"으로 오판하면 안 됨.
    const compositeMarketLabelOnly = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '',
      '샵마인_주문상태': '', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '취소/반품/교환 완료',
    };
    // 7) 실제 마켓 상태도 불명(회수지시 등) — "교환" 근거 없음 → 보수적으로 반품/취소.
    const genuinelyAmbiguous = {
      '간단메모': '', '더망고주문상태 (사용자 연동)': '반품/교환/취소 진행중',
      '샵마인_주문상태': '회수지시', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '',
    };
    // 8) 간단메모에 "철회" — 함수 자체는 더 이상 "철회"를 특별 취급하지 않는다(카드 배정
    //    3순위 has_settled_memo 가 실제 앱에서는 이 함수 호출 전에 이미 걸러낸다). 함수를
    //    단독 호출하면 "교환" 글자가 없으므로 false 가 나오는 게 새 기대값.
    const withdrawnCancelIsolatedCall = {
      '간단메모': '26.08.20 무신사 / 영빈 취소철회 처리함', '더망고주문상태 (사용자 연동)': '국내배송중',
      '샵마인_주문상태': '취소철회(구매확정)', '샵마인_샵마인주문상태': '', '마켓주문상태 (오픈 마켓 연동)': '',
    };
    console.log(JSON.stringify({
      noExchangeEvidence: _isExchangeRow(noExchangeEvidence, 'completed_memo_no'),
      realReturn: _isExchangeRow(realReturn, 'completed_memo_no'),
      explicitExchangeMemo: _isExchangeRow(explicitExchangeMemo, 'completed_memo_yes'),
      explicitExchangeShopmine: _isExchangeRow(explicitExchangeShopmine, 'completed_memo_no'),
      explicitExchangeMarketField: _isExchangeRow(explicitExchangeMarketField, 'inprogress'),
      compositeMarketLabelOnly: _isExchangeRow(compositeMarketLabelOnly, 'completed_memo_no'),
      genuinelyAmbiguous: _isExchangeRow(genuinelyAmbiguous, 'inprogress'),
      withdrawnCancelIsolatedCall: _isExchangeRow(withdrawnCancelIsolatedCall, 'inprogress'),
    }));
    """
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout.strip())
    assert out["noExchangeEvidence"] is False           # "교환" 근거 없음 → 반품/취소
    assert out["realReturn"] is False                   # 진짜 반품완료 → 그대로 제외
    assert out["explicitExchangeMemo"] is True           # 간단메모 "교환" → 교환
    assert out["explicitExchangeShopmine"] is True       # 샵마인_주문상태 "교환접수" → 교환
    assert out["explicitExchangeMarketField"] is True    # 마켓주문상태(오픈마켓연동) "교환신청" → 교환
    assert out["compositeMarketLabelOnly"] is False      # 복합 라벨 그 자체는 "교환" 근거 아님
    assert out["genuinelyAmbiguous"] is False            # 둘 다 불명 → 보수적 제외
    assert out["withdrawnCancelIsolatedCall"] is False   # 함수 단독 호출 시 "철회" 특별 취급 없음

# -*- coding: utf-8 -*-
"""margin_rules.js — 원본 그대로 이식됐는지 + 분류 규칙(Node 실행)."""
import pathlib
import shutil
import subprocess

import pytest

PORTED = pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static" / "margin_rules.js"
ORIGINAL = pathlib.Path(r"C:\dev\대량등록 마진계산기\static\js\margin_rules.js")


def test_file_exists():
    assert PORTED.exists()


def _undo_shopmine_word_purge(text: str) -> str:
    """2026-09 "샵마인" 단어 제거 작업(사장님 지시)에서 의도적으로 바꾼 주석 문구를
    원본 표기로 되돌린다 — 로직은 원래부터 손대지 않았으므로, 이 되돌림 이후 원본과
    바이트가 같아야 "이번 개명 말고는 원본과 100% 동일"이 증명된다."""
    return text.replace("판매처_주문상태", "샵마인_주문상태")


def test_verbatim_from_original():
    if not ORIGINAL.exists():
        pytest.skip(f"원본 없음: {ORIGINAL}")
    ported = _undo_shopmine_word_purge(PORTED.read_text(encoding="utf-8"))
    original = ORIGINAL.read_text(encoding="utf-8")
    assert ported == original, \
        "margin_rules.js 가 원본과 다릅니다(승인된 샵마인 리네임 제외) — 규칙은 원본 그대로 이식"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_classify_rules_via_node():
    script = r"""
    const MR = require(process.argv[1]);
    const loss = {정산예상금액:0, 구매가격:50000};
    const high = {정산예상금액:70000, 구매가격:0};
    const normal = {정산예상금액:70000, 구매가격:50000};
    const uncomp = {정산예상금액:0, 구매가격:0};
    const out = [MR.classify(loss), MR.classify(high), MR.classify(normal), MR.classify(uncomp)];
    console.log(JSON.stringify(out));
    """
    r = subprocess.run(["node", "-e", script, str(PORTED)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith('["loss","highmargin","normal","uncomputable"]')


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_settle_does_not_trust_mango_status_over_settlement_amount():
    """2026-08-25 되돌림 회귀 테스트 — 더망고주문상태(사용자 연동)만 보고 정산을 0으로 깎으면
    안 된다. 더망고는 반품·교환·취소를 전부 "반품/교환/취소완료" 한 라벨로 뭉뚱그리는데,
    실측 결과 그 라벨이 걸린 105건 중 93건이 실제 마켓 상태(판매처_주문상태)는 배송완료·
    구매확정 등 정상 진행 중이었다(교환 처리 등으로 더망고만 앞서 갱신). 정산은 서버
    (sell_source._settlement_for)가 마켓 API 원문 상태로 이미 정확히 0 처리하므로, settle()
    은 정산예상금액을 그대로 읽어야 한다 — 더망고 라벨로 다시 덮어쓰면 정상 매출이 지워진다.
    """
    script = r"""
    const MR = require(process.argv[1]);
    // 더망고=반품/교환/취소완료 라벨이 붙어 있어도, 실제 마켓 상태(판매처)는 정상 진행 중
    // (교환 처리 등) → 정산예상금액을 그대로 신뢰해야 한다.
    const mangoLabelButActive = {정산예상금액:123830, 구매가격:0,
      '더망고주문상태 (사용자 연동)':'반품/교환/취소완료',
      '마켓주문상태 (오픈 마켓 연동)':'취소/반품/교환 완료',
      '판매처_주문상태':'배송완료'};
    const out = {
      settle: MR.settle(mangoLabelButActive),
      classify: MR.classify(mangoLabelButActive),
    };
    console.log(JSON.stringify(out));
    """
    r = subprocess.run(["node", "-e", script, str(PORTED)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout.strip())
    assert out["settle"] == 123830           # 정산예상금액 그대로 — 더망고 라벨로 안 지움
    assert out["classify"] == "highmargin"   # 정산>0, 매입0 → 원래 규칙대로

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


def test_verbatim_from_original():
    if not ORIGINAL.exists():
        pytest.skip(f"원본 없음: {ORIGINAL}")
    assert PORTED.read_bytes() == ORIGINAL.read_bytes(), \
        "margin_rules.js 가 원본과 다릅니다 — 규칙은 원본 그대로 이식"


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
def test_final_cancel_status_zeroes_settle_via_node():
    """더망고·마켓 상태가 취소완료/반품완료 확정이면, 정산예상금액이 취소 전 값(양수)으로
    남아 있어도 0으로 본다 — 정산이 마켓 API 재수집 지연으로 취소 전 값 그대로 남아 매출·
    마진에 얹히던 버그(2026-08-25 라이브 실측: 106건, 유령매출 1,628만원·유령마진 1,419만원).
    """
    script = r"""
    const MR = require(process.argv[1]);
    // 더망고=반품/교환/취소완료, 마켓=취소신청(아직 미확정) → 그래도 취소로 본다.
    const mangoDone = {정산예상금액:41005, 구매가격:0,
      '더망고주문상태 (사용자 연동)':'반품/교환/취소완료', '마켓주문상태 (오픈 마켓 연동)':'취소신청'};
    // 마켓 상태만 반품완료
    const marketDone = {정산예상금액:9000, 구매가격:0, '마켓주문상태 (오픈 마켓 연동)':'반품완료'};
    // 매입이 있는 취소 → 손실(-매입)
    const cancelWithBuy = {정산예상금액:20000, 구매가격:15000, '더망고주문상태 (사용자 연동)':'취소완료'};
    // 정상 배송 중 주문은 그대로
    const normal = {정산예상금액:70000, 구매가격:50000, '더망고주문상태 (사용자 연동)':'국내배송중'};
    const out = {
      mangoDone_settle: MR.settle(mangoDone), mangoDone_classify: MR.classify(mangoDone),
      marketDone_settle: MR.settle(marketDone),
      cancelWithBuy_classify: MR.classify(cancelWithBuy), cancelWithBuy_margin: MR.rowMargin(cancelWithBuy),
      normal_settle: MR.settle(normal), normal_classify: MR.classify(normal),
    };
    console.log(JSON.stringify(out));
    """
    r = subprocess.run(["node", "-e", script, str(PORTED)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout.strip())
    assert out["mangoDone_settle"] == 0
    assert out["mangoDone_classify"] == "uncomputable"
    assert out["marketDone_settle"] == 0
    assert out["cancelWithBuy_classify"] == "loss"
    assert out["cancelWithBuy_margin"] == -15000
    assert out["normal_settle"] == 70000      # 취소 아닌 행은 그대로
    assert out["normal_classify"] == "normal"

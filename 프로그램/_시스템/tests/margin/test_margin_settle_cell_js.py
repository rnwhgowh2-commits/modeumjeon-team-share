# -*- coding: utf-8 -*-
"""margin_settle_cell.js — 정산 칸 정직성(추정/미확인 배지+호버·요약 색칩) Node 실행 검증."""
import pathlib
import shutil
import subprocess

import pytest

CELL = pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static" / "margin_settle_cell.js"


def test_file_exists():
    assert CELL.exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_settle_cell_and_chips_via_node():
    script = r"""
    require(process.argv[1]);
    const esc = s => String(s == null ? '' : s);
    const cell = globalThis._moumSettleCell, chips = globalThis._moumSettleChips;

    // 1) 추정 행 — 배지 + 호버(타임라인·산정식) 있어야
    const est = cell({'_settle_source':'estimated','마켓':'스마트스토어',
      '마켓주문상태 (오픈 마켓 연동)':'배송중','마켓주문번호':'A123','주문일':'2026-07-19 10:00:00',
      '실결제금액':119000,'수수료율':'6%'}, 111860, esc);

    // 2) 실정산 행 — 배지 없이 원본 그대로
    const real = cell({'_settle_source':'real'}, 82150, esc);

    // 3) 미확인 행 — 미확인 배지
    const unk = cell({'_settle_source':'unknown','마켓':'옥션'}, '', esc);

    // 4) 취소완료 — 배지 없음(정산0 확정)
    const zc = cell({'_settle_source':'zero_cancel'}, 0, esc);

    // 5) 색칩 카운트
    const chipHtml = chips([
      {'_settle_source':'real'},{'_settle_source':'store'},{'_settle_source':'estimated'},
      {'_settle_source':'estimated'},{'_settle_source':'unknown'},{'_settle_source':'zero_cancel'}
    ]);

    const out = {
      est_has_badge: /moum-sbadge est/.test(est) && est.indexOf('추정') >= 0,
      est_has_timeline: est.indexOf('moum-tl') >= 0,
      est_has_formula: est.indexOf('←') >= 0,           // '←' 유래 표기
      est_has_reason: est.indexOf('구매확정 전') >= 0,
      est_has_order: est.indexOf('A123') >= 0,
      real_plain: real.indexOf('moum-sbadge') < 0,
      unk_badge: /moum-sbadge unk/.test(unk) && unk.indexOf('미확인') >= 0,
      zc_plain: zc.indexOf('moum-sbadge') < 0,
      chips_real2: (chipHtml.match(/실정산 확정/) && /실정산 확정<\/span><span class="num">2/.test(chipHtml.replace(/\s+/g,''))) ? true : chipHtml.indexOf('실정산 확정') >= 0,
      chips_est: chipHtml.indexOf('추정치') >= 0,
      chips_unk: chipHtml.indexOf('미확인') >= 0
    };
    console.log(JSON.stringify(out));
    """
    r = subprocess.run(["node", "-e", script, str(CELL)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["est_has_badge"], "추정 배지 누락"
    assert out["est_has_timeline"], "타임라인 누락"
    assert out["est_has_formula"], "산정식(←) 누락"
    assert out["est_has_reason"], "사유(배송중→구매확정 전) 누락"
    assert out["est_has_order"], "주문번호 누락"
    assert out["real_plain"], "실정산 행에 배지가 붙음(원본 유지 위반)"
    assert out["unk_badge"], "미확인 배지 누락"
    assert out["zc_plain"], "취소완료 행에 배지가 붙음"
    assert out["chips_est"] and out["chips_unk"], "색칩 라벨 누락"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_chips_counts_exact_via_node():
    script = r"""
    require(process.argv[1]);
    const chips = globalThis._moumSettleChips;
    const html = chips([
      {'_settle_source':'real'},{'_settle_source':'store'},   // 실정산 2
      {'_settle_source':'estimated'},                          // 추정 1
      {'_settle_source':'unknown'},{'_settle_source':'none'},  // 미확인 2
      {'_settle_source':'zero_cancel'}                         // 제외
    ]);
    const nums = (html.match(/class="num">(\d+)/g) || []).map(s => s.replace(/\D/g,''));
    console.log(JSON.stringify(nums));
    """
    r = subprocess.run(["node", "-e", script, str(CELL)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    import json
    nums = json.loads(r.stdout.strip().splitlines()[-1])
    # 실정산 2 · 추정 1 · 미확인 2 (취소완료 제외)
    assert nums == ["2", "1", "2"], f"색칩 카운트 어긋남: {nums}"

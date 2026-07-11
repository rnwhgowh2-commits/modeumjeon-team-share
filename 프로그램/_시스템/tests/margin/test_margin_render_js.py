# -*- coding: utf-8 -*-
"""margin_render.js — 파이 각도 계산 등 순수 함수."""
import pathlib
import shutil
import subprocess

import pytest

R = pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static" / "margin_render.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_pie_slices_sum_full_circle():
    r = subprocess.run(["node", "-e",
        f"const R=require('{R.as_posix()}');"
        "const s=R.__test.pieSlices([{v:30},{v:70}],'v');"
        "console.log(JSON.stringify([s.length, Math.round(s[1].end)]))"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[2,360]"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_pie_empty_is_safe():
    r = subprocess.run(["node", "-e",
        f"const R=require('{R.as_posix()}');console.log(R.__test.pieSlices([],'v').length)"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.stdout.strip() == "0"


RULES = R.parent / "margin_rules.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_summary_minicards_count_from_rules():
    """미니카드 4카운트가 서버 summary(없음) 가 아니라 margin_rules.summarize(matched)
    로 계산됨을 증명 — 손실/계산불가가 조용히 0 이 되면 실패한다."""
    script = (
        "global.window=global;"
        f"require('{RULES.as_posix()}');"          # margin_rules.js → global.MR
        f"require('{R.as_posix()}');"              # margin_render.js → global.MG_RENDERERS
        "var d={summary:{},counts:{},market:[],matched:["
        "{정산예상금액:0,구매가격:50000},"          # settle0+buy>0 → 의심손실(loss)
        "{정산예상금액:0,구매가격:0},"              # settle0+buy0 → 계산불가(uncomputable)
        "{정산예상금액:70000,구매가격:50000}"       # settle>0+buy>0 → 정상(normal)
        "]};"
        "var h=global.MG_RENDERERS.summary(d);"
        "var loss=/의심손실<\\/span><span class=\"v\">1<\\/span>/.test(h);"
        "var unc=/계산불가<\\/span><span class=\"v\">1<\\/span>/.test(h);"
        "var norm=/정상<\\/span><span class=\"v\">1<\\/span>/.test(h);"
        "console.log(JSON.stringify({loss:loss,unc:unc,norm:norm}));"
    )
    r = subprocess.run(["node", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == '{"loss":true,"unc":true,"norm":true}', r.stdout

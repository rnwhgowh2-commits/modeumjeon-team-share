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


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_row_class_from_classify():
    import pathlib
    RULES = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static" / "margin_rules.js").as_posix()
    r = subprocess.run(["node", "-e",
        f"global.window=global; require('{RULES}');"
        f"const R=require('{R.as_posix()}');"
        "console.log(R.__test.rowClass({정산예상금액:0,구매가격:50000})+'|'+R.__test.rowClass({정산예상금액:70000,구매가격:0}))"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "mg-loss|mg-high"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_pie_svg_shapes():
    """pieSvg 계약 고정 — 단일행=full-circle(<circle), 2행=조각 2개(<path)."""
    script = (
        "global.window=global;"
        f"require('{R.as_posix()}');"              # margin_render.js → global.MG_RENDERERS
        "var pieSvg=global.MG_RENDERERS.__pieSvg;"
        "var one=pieSvg([{매출:100,마켓:'A'}],'매출','마켓');"
        "var two=pieSvg([{매출:30,마켓:'A'},{매출:70,마켓:'B'}],'매출','마켓');"
        "var pathCount=(two.match(/<path/g)||[]).length;"
        "console.log(JSON.stringify({"
        "circle:one.indexOf('<circle')>=0,"
        "oneHasPath:one.indexOf('<path')>=0,"
        "twoPaths:pathCount"
        "}));"
    )
    r = subprocess.run(["node", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == '{"circle":true,"oneHasPath":false,"twoPaths":2}', r.stdout

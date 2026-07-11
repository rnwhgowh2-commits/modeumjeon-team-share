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
def test_price_bucket_matches_python_ranges():
    """priceBucket 이 aggregator._classify(판매가) 와 동일 라벨을 낸다 —
    금액대 필터가 매칭행에 없는 필드로 무동작하던 결함의 회귀 방지.
    기대값을 config.DEFAULT_PRICE_RANGES 에서 파생 → 파이썬만 바꾸면 이 테스트가 깨진다."""
    from lemouton.margin.config import DEFAULT_PRICE_RANGES
    expected = "|".join(lbl for _, _, lbl in DEFAULT_PRICE_RANGES)
    # pick a value clearly inside each range (midpoint; for the open top range use low+1)
    import math
    vals = []
    for lo, hi, _ in DEFAULT_PRICE_RANGES:
        vals.append(lo + 1 if math.isinf(hi) else (lo + hi)//2)
    js_vals = ",".join("{판매가:%d}" % v for v in vals)
    r = subprocess.run(["node", "-e",
        f"const R=require('{R.as_posix()}');const f=R.__test.priceBucket;"
        f"console.log([{js_vals}].map(f).join('|'))"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_row_data_attr_escapes_doublequote():
    """브랜드에 큰따옴표가 있어도 data-br 속성이 잘리지 않는다 —
    escAttr(&quot;) 이 없으면 속성이 truncate 되어 브랜드 필터가 해당 행을 숨긴다."""
    r = subprocess.run(["node", "-e",
        "global.window=global;"
        f"require('{RULES.as_posix()}');"
        f"require('{R.as_posix()}');"
        "var d={filters:{},matched:[{브랜드:'a\"b',마켓:'X',판매가:5000,상품명:'p',옵션_매출:'o'}]};"
        "var h=global.MG_RENDERERS.all(d);"
        "console.log(h.indexOf('data-br=\"a&quot;b\"')>=0);"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "true", r.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_price_bucket_missing_or_nonnumeric_is_blank():
    r = subprocess.run(["node", "-e",
        f"const R=require('{R.as_posix()}');"
        "const f=R.__test.priceBucket;"
        "console.log(JSON.stringify([f({}),f({판매가:''}),f({판매가:'abc'})]))"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == '["","",""]'


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_group_label_keys():
    r = subprocess.run(["node", "-e",
        f"const R=require('{R.as_posix()}');console.log(R.__test.groupLabelKey('daily')+'|'+R.__test.groupLabelKey('brand'))"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "일자|브랜드"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_render_group_market_output():
    r = subprocess.run(["node", "-e",
        "global.window=global;"
        f"const R=require('{R.as_posix()}');"
        "const html=global.MG_RENDERERS.market({market:[{마켓:'A&B',매출:1234,순마진:56,건수:2}]});"
        "console.log([/A&amp;B/.test(html), /1,234/.test(html), /<th>마켓<\\/th>/.test(html), /(>|\\s)2(<)/.test(html)].join(','))"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    # label escaped (A&B → A&amp;B), 매출 comma-formatted, header = 마켓, 건수=2 present
    assert r.stdout.strip() == "true,true,true,true"


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

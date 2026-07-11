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

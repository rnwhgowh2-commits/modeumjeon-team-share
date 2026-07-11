# -*- coding: utf-8 -*-
"""margin_app.js 순수 함수 — Node 로 직접 실행."""
import pathlib
import shutil
import subprocess

import pytest

APP = pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static" / "margin_app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_won_formats_thousands():
    r = subprocess.run(["node", "-e",
        f"const M=require('{APP.as_posix()}');"
        "console.log(M.__test.won(1325722)+'|'+M.__test.won('')+'|'+M.__test.won(-98000))"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1,325,722|0|-98,000"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_margin_app_exports_testhook():
    r = subprocess.run(["node", "-e",
        f"const M=require('{APP.as_posix()}');console.log(typeof M.__test.won)"],
        capture_output=True, text=True, encoding="utf-8")
    assert r.stdout.strip() == "function"

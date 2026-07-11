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
    assert PORTED.read_text(encoding="utf-8") == ORIGINAL.read_text(encoding="utf-8"), \
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
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith('["loss","highmargin","normal","uncomputable"]')

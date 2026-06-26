"""크롤가이드 ↔ 코드 동기화 검사 (guide_sync). 2026-06-26."""
import os

from webapp.routes.guide_sync import (
    missing_sources,
    missing_symbols,
    SYMBOL_MANIFEST,
    compute_guide_drift,
    GUIDE_EXT_BASELINE,
)

APP_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_flags_source_absent_in_html():
    md = "무신사 표면가, crawlers/ssf.py 파싱"
    html = "무신사"
    sources = [
        {"key": "musinsa", "label": "무신사"},
        {"key": "ssf", "label": "SSF샵"},
    ]
    out = missing_sources(md, html, sources)
    assert len(out) == 1
    assert out[0]["key"] == "ssf"
    assert out[0]["in_md"] is True
    assert out[0]["in_html"] is False


def test_empty_when_all_present_by_key_or_label():
    md = html = "무신사 crawlers/ssf.py SSG 롯데온"
    sources = [
        {"key": "musinsa", "label": "무신사"},
        {"key": "ssf", "label": "SSF샵"},
    ]
    assert missing_sources(md, html, sources) == []


def test_missing_symbols_real_repo_is_clean():
    assert missing_symbols(APP_ROOT) == []


def test_missing_symbols_flags_renamed(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def other(): pass", encoding="utf-8")
    manifest = [("build_crawlers", "a.py")]
    out = missing_symbols(str(tmp_path), manifest=manifest)
    assert out == [{"symbol": "build_crawlers", "file": "a.py"}]


def test_compute_guide_drift_real_repo_clean():
    d = compute_guide_drift(APP_ROOT)
    assert d["missing_sources"] == []
    assert d["missing_symbols"] == []
    assert d["ext_baseline"] == GUIDE_EXT_BASELINE
    assert isinstance(GUIDE_EXT_BASELINE, str) and GUIDE_EXT_BASELINE

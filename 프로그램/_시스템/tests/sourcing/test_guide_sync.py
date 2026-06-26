"""크롤가이드 ↔ 코드 동기화 검사 (guide_sync). 2026-06-26."""
from webapp.routes.guide_sync import missing_sources


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

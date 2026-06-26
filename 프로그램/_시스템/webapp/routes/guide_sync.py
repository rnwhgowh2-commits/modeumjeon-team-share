"""크롤 가이드 ↔ 코드 동기화 검사 (순수 함수). data_code_map 라우트에서 호출.

best-effort: 어떤 검사도 예외를 던지지 않고 빈 결과로 degrade.
"""
from __future__ import annotations
import os


def missing_sources(md_text, html_text, sources):
    """빌트인 소싱처 중 원문/보기에서 키·라벨 어느 것도 안 보이는 것 목록.

    sources: [{'key':..,'label':..}, ...]
    반환: [{'key','label','in_md','in_html'}, ...] (둘 중 하나라도 빠진 것만)
    """
    out = []
    for s in sources or []:
        key = (s.get("key") or "").strip()
        label = (s.get("label") or key).strip()

        def _present(text):
            text = text or ""
            return bool((key and key in text) or (label and label in text))

        in_md = _present(md_text)
        in_html = _present(html_text)
        if not (in_md and in_html):
            out.append({"key": key, "label": label, "in_md": in_md, "in_html": in_html})
    return out


# C2 — §7 등이 인용하는 핵심 코드 심볼: (심볼, 앱루트(_시스템) 기준 상대경로)
SYMBOL_MANIFEST = [
    ("build_crawlers",        "lemouton/sourcing/crawlers/__init__.py"),
    ("_SITE_BY_SRC",          "webapp/routes/api_benefits.py"),
    ("compute_breakdown",     "webapp/routes/api_benefits.py"),
    ("_detect_site_from_url", "webapp/routes/api_pricing.py"),
    ("_resolve_stock",        "webapp/routes/api_pricing.py"),
    ("_persist_option_stocks","webapp/routes/api_pricing.py"),
    ("PRODUCT_DYNAMIC_KEYS",  "lemouton/sources/service.py"),
    ("SOURCES",               "lemouton/sourcing/source_registry.py"),
    ("SOURCE_ORDER",          "webapp/static/crawl_log.js"),
    ("EXTRACTORS",            "extension/moum-crawler/background.js"),
]


def missing_symbols(app_root, manifest=None):
    """매니페스트 심볼 중 해당 파일에서 안 보이는(또는 파일 없는) 것 목록.
    반환: [{'symbol','file'}, ...]
    """
    manifest = manifest if manifest is not None else SYMBOL_MANIFEST
    out = []
    for symbol, rel in manifest:
        path = os.path.join(app_root, *rel.split("/"))
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            out.append({"symbol": symbol, "file": rel})
            continue
        if symbol not in text:
            out.append({"symbol": symbol, "file": rel})
    return out


# C1 — 가이드가 기준 삼는 전체크롤 확장 버전. 확장 방식 갱신·§7 정정 시 함께 올림.
GUIDE_EXT_BASELINE = "0.7.6"

_MD_REL = ("docs", "크롤링-가이드.md")
_HTML_REL = ("webapp", "templates", "sourcing_guide", "map.html")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _builtin_sources():
    """source_registry.SOURCES 중 빌트인만 [{'key','label'}]. import 실패 시 빈 목록."""
    try:
        from lemouton.sourcing.source_registry import SOURCES
    except Exception:
        return []
    return [{"key": s.get("key"), "label": s.get("label")}
            for s in SOURCES if s.get("builtin")]


def compute_guide_drift(app_root):
    """라우트용 조립 — 원문/보기 읽고 두 검사 + 기준버전 반환. 절대 예외 안 던짐."""
    md = _read(os.path.join(app_root, *_MD_REL))
    html = _read(os.path.join(app_root, *_HTML_REL))
    try:
        ms = missing_sources(md, html, _builtin_sources())
    except Exception:
        ms = []
    try:
        msym = missing_symbols(app_root)
    except Exception:
        msym = []
    return {"missing_sources": ms, "missing_symbols": msym,
            "ext_baseline": GUIDE_EXT_BASELINE}

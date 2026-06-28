"""크롤 가이드 ↔ 코드 동기화 검사 (순수 함수). data_code_map 라우트에서 호출.

best-effort: 어떤 검사도 예외를 던지지 않고 빈 결과로 degrade.
"""
from __future__ import annotations
import json
import os


def missing_sources(md_text, html_text, sources):
    """빌트인 소싱처 중 원문/보기에서 키·라벨 어느 것도 안 보이는 것 목록.

    sources: [{'key':..,'label':..}, ...]
    반환: [{'key','label','in_md','in_html'}, ...] (둘 중 하나라도 빠진 것만)

    매칭 계약: 대소문자 구분 부분문자열(case-sensitive substring) 검사.
    소싱처는 key 또는 label 중 하나라도 텍스트에 있으면 "존재"로 판정.
    key 가 정식 토큰(예: 'ssf'는 'crawlers/ssf.py' 에 매칭)이므로 한국어 label 이
    없어도 key 만으로 "존재" 처리될 수 있음.
    """
    out = []
    for s in sources or []:
        key = (s.get("key") or "").strip()
        label = (s.get("label") or key).strip()

        # default-arg 바인딩으로 루프 변수 클로저 캡처 문제 해소 (Fix 1)
        def _present(text, k=key, lbl=label):
            text = text or ""
            return bool((k and k in text) or (lbl and lbl in text))

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
    ("EXTRACTORS",            "extension/moum-crawler/background.js"),  # 리포 사본(stale v0.4.3)만 검사; 라이브 크롤은 사용자 데스크톱 로드 확장에서 실행되므로 여기 "이상 없음"이 라이브 확장과 동기화됨을 보장하지 않음. 리포 측 리네임은 잡아줌.
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
    # 파일 없음 → "" 반환 (보수적 degrade: 하위 검사가 drift 로 플래그함)
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
    try:
        cat = load_catalog(app_root)
    except Exception:
        cat = []
    try:
        cat_sym = catalog_symbol_drift(app_root, cat)
    except Exception:
        cat_sym = []
    try:
        cat_dup = duplicate_ids(cat)
    except Exception:
        cat_dup = []
    try:
        cat_doc = catalog_doc_drift(md, cat)
    except Exception:
        cat_doc = []
    try:
        cat_shared = shared_code_map(cat)
    except Exception:
        cat_shared = {}
    return {"missing_sources": ms, "missing_symbols": msym,
            "ext_baseline": GUIDE_EXT_BASELINE,
            "catalog_symbol_drift": cat_sym, "catalog_duplicate_ids": cat_dup,
            "catalog_doc_drift": cat_doc, "catalog_shared_code": cat_shared}


_CATALOG_REL = ("webapp", "static", "error_catalog.json")


def load_catalog(app_root):
    """error_catalog.json 의 items 리스트. 파일 없음/깨짐 → []. 절대 예외 안 던짐."""
    path = os.path.join(app_root, *_CATALOG_REL)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def catalog_symbol_drift(app_root, catalog=None):
    """crawl=='ok' 인데 code.func 가 code.file 에 없는 항목(거짓 ok). rule 항목·code 없음은 skip."""
    items = catalog if catalog is not None else load_catalog(app_root)
    out = []
    for it in items:
        if it.get("rule"):
            continue
        code = it.get("code") or {}
        func, rel = code.get("func"), code.get("file")
        if not func or not rel:
            continue
        if it.get("crawl") != "ok":
            continue
        path = os.path.join(app_root, *rel.split("/"))
        try:
            with open(path, encoding="utf-8") as f:
                present = func in f.read()
        except OSError:
            present = False
        if not present:
            out.append({"id": it.get("id"), "func": func, "file": rel, "crawl": "ok"})
    return out


def shared_code_map(items):
    """code.file::func 별 소싱처 집합. 2+ 서로 다른 소싱처가 쓰는 심볼만 반환."""
    groups = {}
    for it in items or []:
        code = it.get("code") or {}
        func, rel = code.get("func"), code.get("file")
        if not func or not rel:
            continue
        key = rel + "::" + func
        src = it.get("src")
        bucket = groups.setdefault(key, [])
        if src and src not in bucket:
            bucket.append(src)
    return {k: v for k, v in groups.items() if len(v) >= 2}


def duplicate_ids(items):
    """중복된 id 목록(정렬, 유일)."""
    seen, dups = set(), set()
    for it in items or []:
        i = it.get("id")
        if not i:
            continue
        (dups if i in seen else seen).add(i)
    return sorted(dups)


def catalog_doc_drift(md_text, items):
    """사건 id 가 원문(.md)에 안 보이는 것. rule/ id없음 skip."""
    md = md_text or ""
    out = []
    for it in items or []:
        if it.get("rule"):
            continue
        i = it.get("id")
        if i and i not in md:
            out.append(i)
    return out

"""소싱처 크롤링 가이드 카드 = SourceRegistry.crawl_guide(JSON 문자열) 의
스켈레톤·검증·검증결과 병합. 순수 로직(DB 의존 없음) — 유닛 테스트 대상.

스펙: docs/superpowers/specs/2026-06-06-소싱처-크롤링-가이드-design.md (스키마 v3)
"""
from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = 3

FIELD_KEYS = ("thumbnail", "title", "price", "benefit", "option_stock", "detail_image")
FIELD_METHODS = {"crawl", "manual", "none", "crawl_per_product", "uniform"}
FIELD_STATUSES = {"ok", "warn", "none"}
# 수집 방법 2축 상세 분류 (Claude가 분석해 채움) — JSON 키라 DB 마이그레이션 불필요.
#  mechanism = 수집 방식: html(HTML 스크래핑) · api(API 크롤링) · crawl(크롤·방식 미분류=하위호환) · manual · none
#  auth      = 인증:      open(비인증) · auth(인증=로그인 세션 필요)
FIELD_MECHANISMS = {"html", "api", "crawl", "manual", "none"}
FIELD_AUTH = {"open", "auth"}

BENEFIT_APPLY = {"preapplied", "deduct", "accrue", "payment", "cashback"}
BENEFIT_STATUSES = {"always", "conditional", "optional", "planned"}
BENEFIT_COLLECTION = {"per_product", "uniform"}

# 혜택 모아보기 속성 (드롭다운) — 값은 표시 문자열 그대로 저장(화이트리스트)
BENEFIT_METHODS = {"정률(%)", "정액(원)", "정액·정률", "적립(%→원)", "고정액", "옵션(개월)", "-"}
BENEFIT_BASES = {"표면 노출가", "베이스금액①", "베이스금액②", "—", "-"}
BENEFIT_FREQS = {"무제한", "정기", "1회성", "-"}
BENEFIT_MATCH = {"any", "all"}  # 혜택 적용 기준: any=키워드 1개 이상 / all=키워드 모두


def _strlist(v: Any) -> list:
    """문자열(쉼표) 또는 리스트 → 비어있지 않은 문자열 리스트."""
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        return []
    return [str(t).strip() for t in v if str(t).strip()]


def _clean_excludes(arr: Any) -> list:
    """공통 제외 키워드 정제: [{word, with[], except[]}]. with=함께(있으면 제외) / except=예외(있으면 포함)."""
    if not isinstance(arr, list):
        return []
    out = []
    for e in arr:
        if not isinstance(e, dict):
            continue
        word = str(e.get("word", "")).strip()
        if not word:
            continue
        out.append({"word": word, "with": _strlist(e.get("with")), "except": _strlist(e.get("except"))})
    return out


def _derive_mechanism(method: str) -> str:
    """기존 카드(mechanism 키 없음)의 하위호환 기본값 — method 에서 유추."""
    if method in ("crawl", "crawl_per_product", "uniform"):
        return "crawl"   # 크롤이지만 HTML/API 미분류 → 재분석 신호
    if method == "manual":
        return "manual"
    return "none"


def _derive_method(name: str, apply: str, rule: str) -> str:
    if apply == "accrue":
        return "적립(%→원)"
    if "고정" in rule or "500원" in rule or "600" in rule:
        return "고정액"
    if "할부" in name:
        return "옵션(개월)"
    return "정률(%)"


def _derive_base(apply: str) -> str:
    if apply == "preapplied":
        return "표면 노출가"
    if apply in ("payment", "cashback"):
        return "베이스금액②"
    return "베이스금액①"


def _derive_freq(name: str) -> str:
    if "후기" in name or "리뷰" in name or "첫" in name:
        return "1회성"
    return "무제한"

FLAG_VALUES = {"ok", "warn"}
VERIFY_STATUSES = {"pending", "claimed", "running", "done", "failed"}


def empty_skeleton() -> dict:
    """미작성 카드의 빈 스켈레톤(v3)."""
    return {
        "version": SCHEMA_VERSION,
        "sample_urls": [],
        "fields": {k: {"method": "none", "mechanism": "none", "auth": "open",
                       "locator": "", "status": "none", "note": ""}
                   for k in FIELD_KEYS},
        "pricing": {
            "base_label": "표면 노출가",
            "benefit_collection": "per_product",
            "benefits": [],
            "note": "",
        },
        "exclude_keywords": [],
        "verification": {"lead_cache": None, "last_new_check": None, "examples": []},
        "updated_at": None,
    }


def _is_http_url(v: Any) -> bool:
    return isinstance(v, str) and (v.startswith("http://") or v.startswith("https://"))


def validate_guide(data: dict) -> dict:
    """입력 JSON(dict)을 화이트리스트 검증하고 정제본을 반환. 위반 시 ValueError."""
    if not isinstance(data, dict):
        raise ValueError("crawl_guide must be an object")

    out = empty_skeleton()
    out["version"] = SCHEMA_VERSION

    urls = data.get("sample_urls", [])
    if not isinstance(urls, list):
        raise ValueError("sample_urls must be a list")
    clean_urls = []
    for u in urls:
        if not isinstance(u, dict) or not _is_http_url(u.get("url")):
            raise ValueError(f"invalid sample url: {u!r}")
        clean_urls.append({"url": u["url"], "is_lead": bool(u.get("is_lead", False))})
    out["sample_urls"] = clean_urls

    fields = data.get("fields", {})
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object")
    for k in FIELD_KEYS:
        f = fields.get(k, {}) or {}
        method = f.get("method", "none")
        status = f.get("status", "none")
        if method not in FIELD_METHODS:
            raise ValueError(f"fields.{k}.method invalid: {method}")
        if status not in FIELD_STATUSES:
            raise ValueError(f"fields.{k}.status invalid: {status}")
        # 2축 상세 분류 — 없으면(기존 카드) method 에서 유추(하위호환)
        mechanism = f.get("mechanism")
        if mechanism not in FIELD_MECHANISMS:
            mechanism = _derive_mechanism(method)
        auth = f.get("auth")
        if auth not in FIELD_AUTH:
            auth = "open"
        out["fields"][k] = {
            "method": method,
            "mechanism": mechanism,
            "auth": auth,
            "locator": str(f.get("locator", "")),
            "status": status,
            "note": str(f.get("note", "")),
        }

    pricing = data.get("pricing", {}) or {}
    collection = pricing.get("benefit_collection", "per_product")
    if collection not in BENEFIT_COLLECTION:
        raise ValueError(f"benefit_collection invalid: {collection}")
    benefits_in = pricing.get("benefits", [])
    if not isinstance(benefits_in, list):
        raise ValueError("pricing.benefits must be a list")
    clean_benefits = []
    for b in benefits_in:
        if not isinstance(b, dict):
            raise ValueError("each benefit must be an object")
        name = str(b.get("name", "")).strip()
        apply = b.get("apply")
        status = b.get("status")
        if not name:
            raise ValueError("benefit.name must be non-empty")
        if apply not in BENEFIT_APPLY:
            raise ValueError(f"benefit.apply invalid: {apply}")
        if status not in BENEFIT_STATUSES:
            raise ValueError(f"benefit.status invalid: {status}")
        rule = str(b.get("rule", ""))
        method = b.get("method")
        if method not in BENEFIT_METHODS:
            method = _derive_method(name, apply, rule)
        base = b.get("base")
        if base not in BENEFIT_BASES:
            base = _derive_base(apply)
        freq = b.get("freq")
        if freq not in BENEFIT_FREQS:
            freq = _derive_freq(name)
        # 포함 키워드(triggers): 페이지에 이 단어가 있으면 해당 혜택 적용 (크롤 게이트)
        triggers = _strlist(b.get("triggers", []))
        # 혜택 적용 기준: any=1개 이상 포함 / all=모두 포함
        match = b.get("match")
        if match not in BENEFIT_MATCH:
            match = "any"
        clean_benefits.append({
            "name": name, "apply": apply, "rule": rule, "status": status,
            "method": method, "base": base, "freq": freq, "triggers": triggers,
            "match": match,
        })
    out["pricing"] = {
        "base_label": str(pricing.get("base_label", "표면 노출가")),
        "benefit_collection": collection,
        "benefits": clean_benefits,
        "note": str(pricing.get("note", "")),
    }

    out["exclude_keywords"] = _clean_excludes(data.get("exclude_keywords"))

    ver = data.get("verification", {}) or {}
    out["verification"] = {
        "lead_cache": _clean_check(ver.get("lead_cache")),
        "last_new_check": _clean_check(ver.get("last_new_check")),
        "examples": _clean_examples(ver.get("examples")),
    }

    out["updated_at"] = data.get("updated_at")
    return out


def _clean_check(c: Any) -> dict | None:
    if not isinstance(c, dict):
        return None
    flags = c.get("flags", {}) or {}
    clean_flags = {k: v for k, v in flags.items() if v in FLAG_VALUES}
    return {
        "url": c.get("url") if _is_http_url(c.get("url")) else None,
        "surface_price": _int_or_none(c.get("surface_price")),
        "benefit_total": _int_or_none(c.get("benefit_total")),
        "final_price": _int_or_none(c.get("final_price")),
        "option_stock": str(c.get("option_stock", "")),
        "flags": clean_flags,
        "job_id": _int_or_none(c.get("job_id")),
        "status": c.get("status") if c.get("status") in VERIFY_STATUSES else None,
        "crawled_at": c.get("crawled_at"),
    }


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clean_examples(arr: Any) -> list:
    """verification.examples 배열 정제."""
    if not isinstance(arr, list):
        return []
    out = []
    for e in arr:
        if not isinstance(e, dict):
            continue
        pay_raw = e.get("pay")
        pay = ({"label": str(pay_raw.get("label", "")),
                "amount": _int_or_none(pay_raw.get("amount"))}
               if isinstance(pay_raw, dict) else None)
        out.append({
            "url": e.get("url") if _is_http_url(e.get("url")) else None,
            "name": str(e.get("name", "")),
            "surface_price": _int_or_none(e.get("surface_price")),
            "pre": [{"label": str(p.get("label", "")), "amount": _int_or_none(p.get("amount"))}
                    for p in (e.get("pre") or []) if isinstance(p, dict)],
            "base1": _int_or_none(e.get("base1")),
            "deducts": [{"label": str(d.get("label", "")), "amount": _int_or_none(d.get("amount"))}
                        for d in (e.get("deducts") or []) if isinstance(d, dict)],
            "base2": _int_or_none(e.get("base2")),
            "pay": pay,
            "final_price": _int_or_none(e.get("final_price")),
            "note": str(e.get("note", "")),
            "captured_at": e.get("captured_at"),
            "screenshot_url": e.get("screenshot_url"),
        })
    return out


def loads(raw: str | None) -> dict:
    """DB Text → dict. None/빈/파싱실패 시 빈 스켈레톤."""
    if not raw:
        return empty_skeleton()
    try:
        data = json.loads(raw)
        return validate_guide(data)
    except (ValueError, json.JSONDecodeError):
        return empty_skeleton()


def dumps(guide: dict) -> str:
    """dict → DB Text(JSON 문자열). 검증 후 직렬화."""
    return json.dumps(validate_guide(guide), ensure_ascii=False)


def merge_verification(guide: dict, kind: str, result: dict) -> dict:
    """검증 크롤 결과를 guide.verification[kind] 에 병합. kind in {lead_cache,last_new_check}."""
    if kind not in ("lead_cache", "last_new_check"):
        raise ValueError(f"invalid verification kind: {kind}")
    out = validate_guide(guide)
    out["verification"][kind] = _clean_check(result)
    return out

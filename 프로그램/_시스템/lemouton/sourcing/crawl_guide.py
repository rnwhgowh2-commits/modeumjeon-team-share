"""소싱처 크롤링 가이드 카드 = SourceRegistry.crawl_guide(JSON 문자열) 의
스켈레톤·검증·검증결과 병합. 순수 로직(DB 의존 없음) — 유닛 테스트 대상.

스펙: docs/superpowers/specs/2026-06-06-소싱처-크롤링-가이드-design.md (스키마 v2)
"""
from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = 2

FIELD_KEYS = ("thumbnail", "title", "price", "benefit", "option_stock", "detail_image")
FIELD_METHODS = {"crawl", "manual", "none", "crawl_per_product", "uniform"}
FIELD_STATUSES = {"ok", "warn", "none"}

BENEFIT_METHODS = {"rate", "accrue", "amount", "amount_or_rate", "payment"}
BENEFIT_STATUSES = {"always", "conditional", "optional", "planned"}
BENEFIT_COLLECTION = {"per_product", "uniform"}

FLAG_VALUES = {"ok", "warn"}
VERIFY_STATUSES = {"pending", "claimed", "running", "done", "failed"}


def empty_skeleton() -> dict:
    """미작성 카드의 빈 스켈레톤(v2)."""
    return {
        "version": SCHEMA_VERSION,
        "sample_urls": [],
        "fields": {k: {"method": "none", "locator": "", "status": "none", "note": ""}
                   for k in FIELD_KEYS},
        "pricing": {
            "base_label": "표면 노출가",
            "benefit_collection": "per_product",
            "benefits": [],
            "note": "",
        },
        "verification": {"lead_cache": None, "last_new_check": None},
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
        out["fields"][k] = {
            "method": method,
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
        method = b.get("method")
        status = b.get("status")
        if not name:
            raise ValueError("benefit.name must be non-empty")
        if method not in BENEFIT_METHODS:
            raise ValueError(f"benefit.method invalid: {method}")
        if status not in BENEFIT_STATUSES:
            raise ValueError(f"benefit.status invalid: {status}")
        clean_benefits.append({
            "name": name, "method": method,
            "rule": str(b.get("rule", "")), "status": status,
        })
    out["pricing"] = {
        "base_label": str(pricing.get("base_label", "표면 노출가")),
        "benefit_collection": collection,
        "benefits": clean_benefits,
        "note": str(pricing.get("note", "")),
    }

    ver = data.get("verification", {}) or {}
    out["verification"] = {
        "lead_cache": _clean_check(ver.get("lead_cache")),
        "last_new_check": _clean_check(ver.get("last_new_check")),
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

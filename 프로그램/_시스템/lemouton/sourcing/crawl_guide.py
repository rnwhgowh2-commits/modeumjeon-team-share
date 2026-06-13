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

# ─────────────────────────────────────────────────────────────
# 재고 반영 규칙 (option_stock 전용) + 검증 체크리스트 (2026-06-13)
#   조용한 실패 버그클래스(한정재고가 '재고있음'으로 둔갑) 재발 방지를 위한 구조.
#   소싱처별 재고 표기는 제각각(잔여/N개 남음/마지막/품절임박/usablInvQty…)이라
#   "어떤 신호로 품절·한정수량을 잡는지"를 카드에 명시하고, 신규 소싱처 추가 시
#   수집(collect)·가공(process)·전송(transmit) 3단계를 체크리스트로 강제 검증한다.
# ─────────────────────────────────────────────────────────────
STOCK_NO_MARKER = {"in_stock", "unknown"}  # 표식 없을 때 처리: 충분(재고있음) / 미상

CHECKLIST_PHASES = {"integrity", "collect", "process", "transmit"}
CHECKLIST_STATUSES = {"pass", "fail", "pending"}

# 표준 검증 체크리스트(전 소싱처 공통). (key, label, phase, required).
#   label/phase/required 는 본 템플릿이 단일 진실원천 — 카드별로 status/note 만 편집.
#   누락 항목은 자동 보강(pending), 모르는 key 는 폐기 → 항상 일관된 체크리스트 유지.
_CHECKLIST_TEMPLATE = (
    # ── 동시·무결성(integrity): 빠르게·많이 긁어도 정확, 어긋나면 실패 처리 ──
    #   "엉뚱한 값 저장으로 인한 큰 손실 방지" — 사용자 최우선 원칙(2026-06-13).
    ("integrity_batch_accuracy", "여러 상품 동시·고속 크롤에도 상품 간 값 안 섞이고 정확",            "integrity", True),
    ("integrity_fail_loud",      "수집값이 가이드 로직과 불일치 시 크롤실패 처리 (엉뚱한 값 저장·성공 위장 금지)", "integrity", True),
    ("integrity_recrawl_reset",  "모음전 재크롤 시 해당 상품 가격·재고 먼저 리셋 (옛 데이터 잔존 → 오발주 치명적 손실 방지)", "integrity", True),
    # ── 수집(collect): 6항목이 실제로 긁히는가 ──
    ("collect_title",        "상품명 수집",                                  "collect",  True),
    ("collect_price",        "모든 가격 정보(표면가·정가·혜택금액) 정확 수집",   "collect",  True),
    ("collect_benefit",      "혜택 라인 수집",                               "collect",  True),
    ("collect_option_match", "옵션(색×사이즈) 정확 수집",                     "collect",  True),
    ("collect_thumbnail",    "썸네일 수집",                                  "collect",  False),
    ("collect_detail_image", "상세이미지 수집",                              "collect",  False),
    # ── 재고 3단계 (조용한 실패의 핵심 지점) ──
    ("stock_soldout", "품절 → 재고 0 으로 수집 (품절 마커 인식)",                          "collect", True),
    ("stock_qty",     "한정수량 → 실수량 N 수집 (잔여·N개 남음·마지막·품절임박 등 표기 전부)", "collect", True),
    ("stock_none",    "표식 없을 때만 '충분(재고있음)' 처리 (표식 있는데 못 읽으면 버그)",      "collect", True),
    # ── 가공(process): 표면가→매입가, 센티넬·매칭 ──
    ("process_sequential_deduct", "매입가 순차 차감 정확 (표면가 − Σ혜택)",                 "process", True),
    ("process_sentinel",          "재고 센티넬(999·cap) 해석 정확 → '재고있음'/'N개' 구분",   "process", True),
    ("process_no_fallback_price", "매칭/크롤 실패 시 폴백가(평균·최저) 금지 → 가격없음 표면화", "process", True),
    # ── 전송(transmit): DB→매트릭스 표시까지 값 보존 ──
    ("transmit_stock_preserved",  "크롤 수량이 DB→매트릭스 표시까지 보존 (둔갑 없음)",        "transmit", True),
    ("transmit_inactive_no_leak", "비활성(OFF) 옵션 가격·재고 누출 없음",                   "transmit", True),
    ("transmit_price_match",      "매트릭스 최종가 = 실제 화면값 100% 일치",                "transmit", True),
)


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


def default_stock_rules() -> dict:
    """option_stock 재고 규칙 기본값(빈 카드). 신규 소싱처가 채워 넣는다."""
    return {"soldout_markers": [], "qty_patterns": [], "no_marker_means": "in_stock"}


def _clean_stock_rules(d: Any) -> dict:
    """재고 규칙 정제 — soldout_markers/qty_patterns 리스트 + no_marker_means enum."""
    if not isinstance(d, dict):
        return default_stock_rules()
    nmm = d.get("no_marker_means")
    if nmm not in STOCK_NO_MARKER:
        nmm = "in_stock"
    return {
        "soldout_markers": _strlist(d.get("soldout_markers")),
        "qty_patterns": _strlist(d.get("qty_patterns")),
        "no_marker_means": nmm,
    }


def default_checklist() -> list:
    """표준 검증 체크리스트(전 항목 pending). 빈 카드·하위호환 보강에 사용."""
    return _clean_checklist([])


def _clean_checklist(arr: Any) -> list:
    """검증 체크리스트 정제 — 템플릿이 label/phase/required 의 단일 진실원천.

    카드별로는 status(pass/fail/pending)·note 만 보존. 누락 항목은 pending 으로
    자동 보강, 템플릿에 없는 key 는 폐기 → 전 소싱처가 항상 같은 체크리스트를 갖는다.
    (기존 카드: checklist 키 없음 → 전체 pending 으로 자동 생성 = 하위호환.)
    """
    by_key: dict[str, dict] = {}
    if isinstance(arr, list):
        for it in arr:
            if not isinstance(it, dict):
                continue
            key = str(it.get("key", "")).strip()
            if key:
                by_key[key] = it
    out = []
    for key, label, phase, required in _CHECKLIST_TEMPLATE:
        it = by_key.get(key, {})
        status = it.get("status")
        if status not in CHECKLIST_STATUSES:
            status = "pending"
        out.append({
            "key": key, "label": label, "phase": phase,
            "required": required, "status": status,
            "note": str(it.get("note", "")),
        })
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
    fields = {k: {"method": "none", "mechanism": "none", "auth": "open",
                  "locator": "", "status": "none", "note": ""}
              for k in FIELD_KEYS}
    # option_stock 만 재고 규칙(품절/한정수량 마커 + 표식없음 처리) 보유.
    fields["option_stock"]["stock_rules"] = default_stock_rules()
    return {
        "version": SCHEMA_VERSION,
        "sample_urls": [],
        "fields": fields,
        "pricing": {
            "base_label": "표면 노출가",
            "benefit_collection": "per_product",
            "benefits": [],
            "note": "",
        },
        "exclude_keywords": [],
        "verification": {"lead_cache": None, "last_new_check": None, "examples": [],
                         "saved_checks": [], "checklist": default_checklist()},
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
        # option_stock 만 재고 규칙(품절/한정수량 마커 + 표식없음 처리) 보존.
        if k == "option_stock":
            out["fields"][k]["stock_rules"] = _clean_stock_rules(f.get("stock_rules"))

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
        # 혜택 '값' — 화면의 숫자 입력칸(시안 B). 단위는 method 가 결정(정률→%, 정액→원).
        #   인간 입력값 그대로 보존(15 = 15%, 5000 = 5,000원). None=미입력.
        value = _num_or_none(b.get("value"))
        clean_benefits.append({
            "name": name, "apply": apply, "rule": rule, "status": status,
            "method": method, "base": base, "freq": freq, "triggers": triggers,
            "match": match, "value": value,
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
        "saved_checks": _clean_saved_checks(ver.get("saved_checks")),
        "checklist": _clean_checklist(ver.get("checklist")),
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


def _num_or_none(v: Any) -> float | int | None:
    """혜택 '값' 입력 정제 — 숫자(또는 '5,000' 같은 쉼표 포함 문자열) → 숫자.
    빈값·파싱실패 시 None. 정수는 정수로(15), 소수는 float 로(2.73) 보존."""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
            if v == "":
                return None
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else f


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


def _clean_saved_checks(arr: Any) -> list:
    """verification.saved_checks 정제 — ④ 신규 검증 '저장된 검증' 리스트 (최신순, 최대 50)."""
    if not isinstance(arr, list):
        return []
    out = []
    for c in arr[:50]:
        if not isinstance(c, dict):
            continue
        url = c.get("url")
        out.append({
            "url": url if _is_http_url(url) else None,
            "name": str(c.get("name", ""))[:80],
            "final_price": _int_or_none(c.get("final_price")),
            "summary": str(c.get("summary", ""))[:200],
            "saved_at": c.get("saved_at"),
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


def auto_checklist_updates(result: Any, truth: Any = None) -> dict:
    """[동시·무결성 8단계] 검증 크롤 결과(result) + 정답(truth)을 대조해 자동 판정
    가능한 체크리스트 항목의 status 만 반환 {key: 'pass'|'fail'}.

    확신 가능한 항목만 판정한다 — 나머지는 손대지 않아(pending 유지) 사람이 판단.
      · collect_price            : 표면가 > 0 → pass
      · process_sequential_deduct: 0 < 최종가 ≤ 표면가 → pass
      · collect_option_match     : option_stock 문자열 존재 → pass
      · transmit_price_match     : 정답 final_price 와 ±0.1% 이내 → pass / 아니면 fail
    """
    out: dict = {}
    if not isinstance(result, dict):
        return out
    sp = result.get("surface_price")
    fp = result.get("final_price")
    if isinstance(sp, int) and sp > 0:
        out["collect_price"] = "pass"
    if isinstance(sp, int) and isinstance(fp, int) and 0 < fp <= sp:
        out["process_sequential_deduct"] = "pass"
    if str(result.get("option_stock") or "").strip():
        out["collect_option_match"] = "pass"
    if isinstance(fp, int) and isinstance(truth, dict) and isinstance(truth.get("final_price"), int):
        tfp = truth["final_price"]
        tol = max(1, round(tfp * 0.001))
        out["transmit_price_match"] = "pass" if abs(fp - tfp) <= tol else "fail"
    return out


def apply_checklist_updates(guide: dict, updates: dict) -> dict:
    """auto_checklist_updates 결과를 guide.verification.checklist 의 status 에 반영.
    템플릿에 없는 key·잘못된 status 는 무시(안전). 정제본 반환."""
    out = validate_guide(guide)
    by_key = {c["key"]: c for c in out["verification"]["checklist"]}
    for k, st in (updates or {}).items():
        if k in by_key and st in CHECKLIST_STATUSES:
            by_key[k]["status"] = st
    return out

import pytest
from lemouton.sourcing.crawl_guide import (
    empty_skeleton, validate_guide, merge_verification,
    default_checklist, _CHECKLIST_TEMPLATE,
    auto_checklist_updates, apply_checklist_updates,
)

def test_empty_skeleton_shape():
    sk = empty_skeleton()
    assert sk["version"] == 3
    assert sk["sample_urls"] == []
    assert set(sk["fields"]) == {
        "thumbnail", "title", "price", "benefit", "option_stock", "detail_image"}
    assert sk["pricing"]["benefits"] == []
    assert sk["pricing"]["benefit_collection"] == "per_product"

def test_validate_accepts_minimal_valid():
    data = {
        "version": 3,
        "sample_urls": [{"url": "https://www.musinsa.com/products/1", "is_lead": True}],
        "fields": empty_skeleton()["fields"],
        "pricing": {
            "base_label": "표면 노출가",
            "benefit_collection": "per_product",
            "benefits": [
                {"name": "등급 할인", "apply": "deduct", "rule": "잔액 × 등급 %", "status": "always"}
            ],
            "note": "",
        },
    }
    out = validate_guide(data)
    assert out["pricing"]["benefits"][0]["name"] == "등급 할인"
    assert out["version"] == 3

def test_validate_rejects_bad_benefit_apply():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "x", "apply": "WRONG", "rule": "r", "status": "always"}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_validate_rejects_bad_status():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "x", "apply": "deduct", "rule": "r", "status": "WRONG"}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_validate_rejects_non_http_url():
    data = empty_skeleton()
    data["sample_urls"] = [{"url": "javascript:alert(1)", "is_lead": True}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_validate_rejects_empty_benefit_name():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "  ", "apply": "deduct", "rule": "r", "status": "always"}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_field_mechanism_auth_preserved():
    """수집 방식(html/api)·인증(open/auth) 2축이 보존된다."""
    data = empty_skeleton()
    data["fields"]["benefit"] = {
        "method": "crawl_per_product", "mechanism": "api", "auth": "auth",
        "locator": "/api/goods", "status": "warn", "note": "오독주의"}
    out = validate_guide(data)["fields"]["benefit"]
    assert out["mechanism"] == "api"
    assert out["auth"] == "auth"
    assert out["note"] == "오독주의"


def test_field_mechanism_derived_for_legacy_card():
    """기존 카드(mechanism/auth 키 없음)는 method에서 하위호환 유추한다."""
    legacy = {"version": 3, "sample_urls": [],
              "fields": {"price": {"method": "crawl", "locator": "x", "status": "ok"}},
              "pricing": {"benefit_collection": "per_product", "benefits": []}}
    out = validate_guide(legacy)["fields"]["price"]
    assert out["mechanism"] == "crawl"   # 크롤·방식 미분류
    assert out["auth"] == "open"


def test_field_bad_mechanism_falls_back():
    """잘못된 mechanism/auth 값은 안전 기본으로 폴백(기존 값 보존 정책)."""
    data = empty_skeleton()
    data["fields"]["price"] = {"method": "crawl", "mechanism": "WRONG", "auth": "X",
                               "locator": "", "status": "ok", "note": ""}
    out = validate_guide(data)["fields"]["price"]
    assert out["mechanism"] == "crawl"
    assert out["auth"] == "open"


def test_merge_verification_last_new_check():
    guide = empty_skeleton()
    result = {
        "url": "https://www.musinsa.com/products/4112020",
        "surface_price": 42000, "benefit_total": -2100, "final_price": 39900,
        "option_stock": "그레이/250 재고○",
        "flags": {"benefit": "warn", "surface_price": "ok"},
        "job_id": 1234, "status": "done", "crawled_at": "2026-06-06T00:00:00Z",
    }
    out = merge_verification(guide, "last_new_check", result)
    assert out["verification"]["last_new_check"]["final_price"] == 39900
    assert out["verification"]["last_new_check"]["flags"]["benefit"] == "warn"
    assert out["verification"]["lead_cache"] is None

def test_merge_verification_rejects_bad_kind():
    with pytest.raises(ValueError):
        merge_verification(empty_skeleton(), "WRONG", {})


# ─────────────────────────────────────────────────────────────
# 재고 반영 규칙 (option_stock.stock_rules) + 검증 체크리스트 (2026-06-13)
# ─────────────────────────────────────────────────────────────
def test_empty_skeleton_has_stock_rules():
    """option_stock 만 재고 규칙을 가진다 (기본 in_stock)."""
    sk = empty_skeleton()
    sr = sk["fields"]["option_stock"]["stock_rules"]
    assert sr == {"soldout_markers": [], "qty_patterns": [], "no_marker_means": "in_stock"}
    # 다른 필드엔 stock_rules 없음
    assert "stock_rules" not in sk["fields"]["price"]


def test_stock_rules_preserved():
    """소싱처별 품절 마커·한정수량 표기·표식없음 처리가 보존된다."""
    data = empty_skeleton()
    data["fields"]["option_stock"]["stock_rules"] = {
        "soldout_markers": ["품절", "재입고 알림"],
        "qty_patterns": ["잔여 N개", "N개 남음", "마지막 N개", "품절임박 (N)"],
        "no_marker_means": "in_stock",
    }
    out = validate_guide(data)["fields"]["option_stock"]["stock_rules"]
    assert out["soldout_markers"] == ["품절", "재입고 알림"]
    assert "N개 남음" in out["qty_patterns"]
    assert out["no_marker_means"] == "in_stock"


def test_stock_rules_bad_no_marker_falls_back():
    """잘못된 no_marker_means → 안전 기본(in_stock)."""
    data = empty_skeleton()
    data["fields"]["option_stock"]["stock_rules"] = {"no_marker_means": "WRONG"}
    out = validate_guide(data)["fields"]["option_stock"]["stock_rules"]
    assert out["no_marker_means"] == "in_stock"


def test_stock_rules_accepts_unknown_marker_policy():
    data = empty_skeleton()
    data["fields"]["option_stock"]["stock_rules"] = {"no_marker_means": "unknown"}
    out = validate_guide(data)["fields"]["option_stock"]["stock_rules"]
    assert out["no_marker_means"] == "unknown"


def test_checklist_default_covers_template():
    """기본 체크리스트 = 템플릿 전체 (전부 pending)."""
    cl = default_checklist()
    assert len(cl) == len(_CHECKLIST_TEMPLATE)
    keys = {c["key"] for c in cl}
    # 재고 3단계가 반드시 포함
    assert {"stock_soldout", "stock_qty", "stock_none"} <= keys
    # 동시·무결성 3항목(손실 방지 핵심: 동시정확·실패처리·재크롤 리셋)도 포함
    assert {"integrity_batch_accuracy", "integrity_fail_loud", "integrity_recrawl_reset"} <= keys
    # 4단계(phase) 모두 존재
    assert {c["phase"] for c in cl} == {"integrity", "collect", "process", "transmit"}
    assert all(c["status"] == "pending" for c in cl)


def test_checklist_status_preserved_and_normalized():
    """카드별 status/note 보존, label/phase 는 템플릿이 진실원천(덮어씀)."""
    sk = empty_skeleton()
    sk["verification"]["checklist"] = [
        {"key": "stock_qty", "status": "pass", "note": "잔여/남음/마지막 매칭 확인",
         "label": "사용자가 바꾼 라벨(무시됨)", "phase": "transmit"},
        {"key": "UNKNOWN_KEY", "status": "pass"},  # 폐기되어야 함
    ]
    out = validate_guide(sk)["verification"]["checklist"]
    keys = {c["key"] for c in out}
    assert "UNKNOWN_KEY" not in keys                       # 모르는 key 폐기
    sq = next(c for c in out if c["key"] == "stock_qty")
    assert sq["status"] == "pass"                          # status 보존
    assert sq["note"] == "잔여/남음/마지막 매칭 확인"        # note 보존
    assert sq["phase"] == "collect"                        # 템플릿이 진실원천(덮어씀)
    assert sq["label"] != "사용자가 바꾼 라벨(무시됨)"


def test_legacy_card_gets_full_checklist():
    """checklist 키 없는 기존 카드 → 전체 pending 으로 자동 보강(하위호환)."""
    legacy = {"version": 3, "sample_urls": [],
              "fields": {}, "pricing": {"benefit_collection": "per_product", "benefits": []},
              "verification": {"lead_cache": None}}
    out = validate_guide(legacy)["verification"]["checklist"]
    assert len(out) == len(_CHECKLIST_TEMPLATE)
    assert all(c["status"] == "pending" for c in out)


# ─────────────────────────────────────────────────────────────
# [동시·무결성 8단계] 정답 자동 대조 (auto_checklist_updates / apply)
# ─────────────────────────────────────────────────────────────
def test_auto_checklist_basic_pass():
    r = {"surface_price": 42000, "final_price": 39900, "option_stock": "그레이/250 재고○"}
    u = auto_checklist_updates(r)
    assert u["collect_price"] == "pass"
    assert u["process_sequential_deduct"] == "pass"
    assert u["collect_option_match"] == "pass"
    assert "transmit_price_match" not in u   # 정답 없으면 미판정


def test_auto_checklist_price_match_vs_truth():
    r = {"surface_price": 42000, "final_price": 39900}
    assert auto_checklist_updates(r, {"final_price": 39900})["transmit_price_match"] == "pass"
    assert auto_checklist_updates(r, {"final_price": 35000})["transmit_price_match"] == "fail"


def test_auto_checklist_ignores_bad_input():
    assert auto_checklist_updates({"surface_price": 0}) == {}     # 표면가 0 → 판정 없음
    assert auto_checklist_updates(None) == {}
    # 최종가 > 표면가(비정상) → 순차차감 pass 안 함
    assert "process_sequential_deduct" not in auto_checklist_updates(
        {"surface_price": 100, "final_price": 200})


def test_apply_checklist_updates_safe():
    g = empty_skeleton()
    g2 = apply_checklist_updates(g, {"collect_price": "pass", "UNKNOWN": "pass", "stock_qty": "BAD"})
    by = {c["key"]: c["status"] for c in g2["verification"]["checklist"]}
    assert by["collect_price"] == "pass"
    assert by["stock_qty"] == "pending"     # 잘못된 status 무시
    assert "UNKNOWN" not in by              # 모르는 key 무시


# ─────────────────────────────────────────────────────────────
# Task 1a-2: 혜택 value_source(fixed/crawl) + 혜택별 excludes/exclude_match
# ─────────────────────────────────────────────────────────────
def test_benefit_value_source_and_excludes():
    from lemouton.sourcing import crawl_guide as cg
    g = cg.validate_guide({"version": 3, "pricing": {"benefits": [
        {"name": "등급적립", "apply": "accrue", "status": "conditional", "value_source": "crawl",
         "excludes": ["불가", " "], "exclude_match": "all", "triggers": ["적립"], "match": "any"},
        {"name": "현대카드", "apply": "deduct", "status": "conditional", "value_source": "fixed", "value": 2.73},
        {"name": "레거시", "apply": "deduct", "status": "always"},   # value_source 키 없음 → fixed 기본
    ]}})
    b = {x["name"]: x for x in g["pricing"]["benefits"]}
    # 크롤값+조건부 보존
    assert b["등급적립"]["value_source"] == "crawl"
    assert b["등급적립"]["excludes"] == ["불가"] and b["등급적립"]["exclude_match"] == "all"
    assert b["등급적립"]["status"] == "conditional"
    # 고정값 → status 강제 always (조건부 불가)
    assert b["현대카드"]["value_source"] == "fixed" and b["현대카드"]["status"] == "always"
    # 레거시(키 없음) → fixed + 빈 excludes + exclude_match any
    assert b["레거시"]["value_source"] == "fixed"
    assert b["레거시"]["excludes"] == [] and b["레거시"]["exclude_match"] == "any"

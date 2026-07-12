# -*- coding: utf-8 -*-
"""brand_suggest — 미확정 상품명 → 브랜드 후보 추출·순위·정규화 (원본 이식).

원본 `tests/test_brand_suggest.py` 의 순수 로직 테스트를 모음전 import 로 이식.
(원본의 app/store 기반 테스트는 tests/margin/test_brand_dict_routes.py 로 대체.)
"""
from lemouton.margin.brand_suggest import suggest_from_names, _candidate, normalize_brand


def _fake_extract(name):
    # 사전에 '나이키'만 있다고 가정
    return "나이키" if "나이키" in name else "미확정"


def test_candidate_extracts_brand_after_prefix():
    assert _candidate("매장정품 라코스테 여성 반팔 TF7215") == "라코스테"


def test_candidate_skips_gender_word():
    assert _candidate("국내매장판 여성 커버낫 그래픽 반팔") == "커버낫"


def test_candidate_none_when_no_prefix():
    assert _candidate("그냥 상품명 12345") is None


def test_suggest_ranks_by_frequency():
    names = [
        "매장정품 라코스테 반팔 A", "매장정품 라코스테 반팔 B",
        "매장정품 커버낫 반팔 C", "나이키 에어포스",  # 나이키는 이미 분류됨 → 제외
        "브랜드없는 상품명",  # unresolvable
    ]
    r = suggest_from_names(names, _fake_extract)
    kws = [s["keyword"] for s in r["suggestions"]]
    assert kws[0] == "라코스테"  # 2건으로 1위
    assert any(s["keyword"] == "라코스테" and s["count"] == 2 for s in r["suggestions"])
    assert r["unresolvable"] == 1
    assert r["total_unclassified"] == 4  # 나이키 제외


def test_normalize_english_to_korean():
    assert normalize_brand("CHAMPION") == "챔피언"
    assert normalize_brand("LULULEMON") == "룰루레몬"
    assert normalize_brand("champion") == "챔피언"   # 대소문자 무관


def test_normalize_subline_to_parent():
    assert normalize_brand("조던") == "나이키"
    assert normalize_brand("NSW") == "나이키"
    assert normalize_brand("아디컬러") == "아디다스"


def test_normalize_keen_to_korean():
    # ★ 이번 이식의 트리거 — KEEN→킨 한글 별칭
    assert normalize_brand("KEEN") == "킨"
    assert normalize_brand("keen") == "킨"


def test_normalize_passthrough_korean():
    assert normalize_brand("라코스테") == "라코스테"   # 매핑 없어도 그대로
    assert normalize_brand("커버낫") == "커버낫"


def test_suggest_includes_normalized_brand():
    def ex(n): return "나이키" if "나이키" in n else "미확정"
    names = ["매장정품 CHAMPION 반팔 A", "매장정품 CHAMPION 반팔 B", "매장정품 라코스테 반팔 C"]
    r = suggest_from_names(names, ex)
    byk = {s["keyword"]: s["brand"] for s in r["suggestions"]}
    assert byk.get("CHAMPION") == "챔피언"
    assert byk.get("라코스테") == "라코스테"


def test_suggest_returns_unresolved_products():
    def ex(n): return "미확정"   # 전부 미확정
    names = ["브랜드없는 상품 A", "브랜드없는 상품 A", "이름만상품 B"]
    r = suggest_from_names(names, ex)
    up = {x["name"]: x["count"] for x in r["unresolved_products"]}
    assert up.get("브랜드없는 상품 A") == 2
    assert up.get("이름만상품 B") == 1

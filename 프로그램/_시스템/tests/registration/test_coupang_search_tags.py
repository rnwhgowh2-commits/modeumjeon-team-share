# -*- coding: utf-8 -*-
"""[2026-08-13 사장님 확정] 쿠팡 검색태그 — 2개 하드코딩을 걷어내고 한도까지 채운다.

■ 종전
    registration/coupang.py:  "searchTags": [bundle.model_code, o.color_code]
  모음전 코드(내부 관리번호)와 색상 **딱 2개**. 모음전 코드는 구매자가 검색할 말이 아니다.

■ 지도에서 확인한 한도 (webapp/data/marketplace_api_map.json)
    coupang.products.product-creation · items.searchTags
      "검색어 — **1개당 20자 이내, 최대 20개**"
  🔴 개수(20개)뿐 아니라 **개당 글자수(20자)** 도 제한이다. 개수만 맞추면 긴 태그에서
    쿠팡이 거부한다.

■ 🔴 스마트스토어 10개는 근거를 못 찾았다
  지도의 `seoInfo.sellerTags` 에는 개수 제한이 **적혀 있지 않다**(object[] 선언만).
  `market_limits.py` 의 규율대로 「확인 불가」에 남기고 **상한을 적용하지 않는다** —
  지어낸 상한으로 태그를 잘라내면 그게 더 큰 손해다.
"""
from types import SimpleNamespace as NS

from lemouton.registration import market_limits as ML
from lemouton.registration.coupang import (
    CoupangRegistrationInputs, _build_payload,
)
from lemouton.registration.options import coupang_search_tags


# ── 한도는 지도에서 확인된 것만 ───────────────────────────────

def test_쿠팡_한도는_지도에_적힌_그대로():
    assert ML.TAG_MAX_COUNT["coupang"] == 20
    assert ML.TAG_MAX_LEN["coupang"] == 20


def test_스스는_확인불가로_남기고_상한을_안_건다():
    """🔴 지어내지 않는다 — 지도에 개수 제한이 없다."""
    assert "smartstore" not in ML.TAG_MAX_COUNT
    assert "smartstore" in ML.TAG_LIMIT_UNKNOWN
    assert ML.TAG_LIMIT_UNKNOWN["smartstore"]


# ── 태그 만들기 ───────────────────────────────────────────────

def _opt(color="블랙", size="250"):
    return NS(market_visible_coupang=True, color_code=color, size_code=size,
              option_coupang_price_override=None, canonical_sku="SKU-1",
              barcode=None)


def _bundle(**kw):
    d = dict(model_code="르무통-코트-01", brand="르무통", category="코트",
             model_name_display="캐시미어 코트", model_name_raw="캐시미어 코트",
             coupang_product_name_override=None)
    d.update(kw)
    return NS(**d)


def test_구매자가_검색할_말을_담는다():
    tags = coupang_search_tags(_bundle(), [_opt("블랙"), _opt("네이비")])
    assert "르무통" in tags and "코트" in tags
    assert "블랙" in tags and "네이비" in tags


def test_모음전_코드는_태그로_안_나간다():
    """내부 관리번호는 구매자가 검색할 말이 아니다 — 검색 노출만 갉아먹는다."""
    tags = coupang_search_tags(_bundle(model_code="르무통-코트-01"), [_opt()])
    assert "르무통-코트-01" not in tags


def test_같은_말은_한_번만():
    tags = coupang_search_tags(_bundle(), [_opt("블랙"), _opt("블랙"), _opt("블랙")])
    assert len(tags) == len(set(tags))


def test_없는_값은_안_지어낸다():
    """브랜드·카테고리가 비면 그 자리는 그냥 없다 — 빈 문자열을 넣지 않는다."""
    tags = coupang_search_tags(_bundle(brand="", category=""), [_opt("블랙")])
    assert all(t.strip() for t in tags)
    assert tags == ["블랙"]


# ── 한도 지키기 ───────────────────────────────────────────────

def test_20개를_안_넘는다():
    opts = [_opt(f"색상{i}") for i in range(40)]
    tags = coupang_search_tags(_bundle(), opts)
    assert len(tags) <= 20


def test_개당_20자를_넘는_태그는_뺀다():
    """🔴 개수만 맞추면 긴 태그에서 쿠팡이 거부한다. 자르지 않고 **뺀다** —
    잘라 만든 말은 구매자가 검색하지 않는 엉뚱한 말이 된다."""
    긴색 = "아주아주기다란색상이름을가진옵션입니다정말길다"      # 20자 초과
    assert len(긴색) > 20
    tags = coupang_search_tags(_bundle(), [_opt(긴색), _opt("블랙")])
    assert 긴색 not in tags
    assert "블랙" in tags
    assert all(len(t) <= 20 for t in tags)


# ── 등록 페이로드까지 ─────────────────────────────────────────

def test_등록_페이로드의_태그가_바뀌었다():
    p = _build_payload(bundle=_bundle(), options=[_opt("블랙"), _opt("네이비")],
                       sale_price=100000,
                       inputs=CoupangRegistrationInputs(display_category_code=1))
    tags = p["items"][0]["searchTags"]
    assert "르무통-코트-01" not in tags, '모음전 코드가 아직 태그로 나간다'
    assert "르무통" in tags and "코트" in tags
    assert len(tags) <= 20 and all(len(t) <= 20 for t in tags)


def test_한_상품의_모든_옵션이_같은_태그를_받는다():
    """옵션마다 태그가 다르면 같은 상품인데 검색 노출이 들쭉날쭉해진다."""
    p = _build_payload(bundle=_bundle(), options=[_opt("블랙"), _opt("네이비")],
                       sale_price=100000,
                       inputs=CoupangRegistrationInputs(display_category_code=1))
    첫, 둘 = p["items"][0]["searchTags"], p["items"][1]["searchTags"]
    assert 첫 == 둘

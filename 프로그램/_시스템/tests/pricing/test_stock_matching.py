# -*- coding: utf-8 -*-
"""[TEST] 매트릭스 소싱처 재고/가격 핵심 로직 회귀 테스트 (2026-06-03).

배경: 매트릭스 재고가 "전혀 안 맞던" 근본원인 6개를 수정하며 돈 직결(가격·재고)
      순수 로직을 재작성했다. 이 테스트가 그 로직을 영구히 잠근다 —
      나중에 누가 건드려 조용히 재고/가격이 틀어지는 것을 방지.

대상 (webapp.routes.api_pricing 의 순수 함수):
  - _resolve_stock      : site+raw → (수량, 라벨, 품절여부). 사이트별 센티넬 해석.
  - _match_option_stock : 옵션(색상+사이즈) ↔ SourceOption 매칭. size가 color_text에
                          든 사이트(롯데온/SSG), 1URL=여러색(르무통/SSF) 대응.
  - _build_so_index     : source_product_id 별 SourceOption 그룹.
  - _pick_cheapest_buyable : 재고존재+크롤성공+가격>0 중 최저가 (winner·원가 정의).
"""
import types

import pytest

from webapp.routes.api_pricing import (
    _resolve_stock,
    _match_option_stock,
    _build_so_index,
    _pick_cheapest_buyable,
    _resolve_sourcing_cost,
    _STOCK_CAP,
)


def _so(pid, size_text, color_text, stock):
    """가벼운 SourceOption 스텁."""
    return types.SimpleNamespace(
        source_product_id=pid, size_text=size_text,
        color_text=color_text, current_stock=stock,
    )


# ─────────────────────────────────────────────────────────────
# _resolve_stock — 사이트별 센티넬 의미 확정
# ─────────────────────────────────────────────────────────────
class TestResolveStock:
    def test_zero_is_soldout(self):
        assert _resolve_stock('lemouton', 0) == (0, '품절', True)
        assert _resolve_stock('ssg', 0) == (0, '품절', True)

    def test_unknown_sentinel_is_warning_and_out(self):
        # -1 = 불명(크롤됐으나 신호 못 읽음): 수량0·판매제외·라벨은 품절과 구분
        from webapp.routes.api_pricing import _STOCK_UNKNOWN
        assert _STOCK_UNKNOWN == -1
        qty, label, out = _resolve_stock('musinsa', -1)
        assert qty == 0
        assert out is True
        assert label == '⚠️확인필요'
        assert label != '품절'

    def test_lotteon_999_is_unknown_not_instock(self):
        # 롯데온 999 = 대체상품 센티넬 → ⚠️확인필요(out). 다른 소싱처 999는 '재고있음' 유지.
        assert _resolve_stock('lotteon', 999) == (0, '⚠️확인필요', True)
        assert _resolve_stock('lotte', 6993) == (None, '재고있음', False)  # 상품합계 더미는 충분 유지
        assert _resolve_stock('ssf', 999) == (None, '재고있음', False)      # 타 소싱처 불변
        assert _resolve_stock('lotteon', 41) == (41, '41개', False)         # 실수량 불변
        assert _resolve_stock('lotteon', 0) == (0, '품절', True)            # 품절 불변

    def test_unknown_distinct_from_none_and_zero(self):
        # None(미크롤)·0(품절)·-1(불명) 셋이 각각 다른 라벨
        assert _resolve_stock('lotteon', None)[1] == '미크롤'
        assert _resolve_stock('lotteon', 0)[1] == '품절'
        assert _resolve_stock('lotteon', -1)[1] == '⚠️확인필요'

    def test_none_by_last_status(self):
        # [2026-06-28] raw None = 재고값 없음 → last_status 로 구분 (가짜 '재고있음' 금지).
        #   시도조차 안 함(pending·None·no_crawler) → '미크롤' / 시도+실패(error) → '크롤실패'
        #   / 성공·수량미상(ok) → '재고있음'(드묾, 본래 999여야)
        assert _resolve_stock('lemouton', None) == (None, '미크롤', False)
        assert _resolve_stock('lemouton', None, 'pending') == (None, '미크롤', False)
        assert _resolve_stock('lemouton', None, 'no_crawler') == (None, '미크롤', False)
        assert _resolve_stock('lemouton', None, 'error') == (None, '크롤실패', False)
        assert _resolve_stock('lemouton', None, 'ok') == (None, '재고있음', False)

    def test_999_sentinel_is_instock(self):
        # 르무통/롯데온/SSF '충분' 센티넬
        assert _resolve_stock('ssf', 999) == (None, '재고있음', False)

    def test_dummy_sum_over_900_is_instock(self):
        # last_stock 상품합계 더미(999×N) → '재고있음'
        assert _resolve_stock('lotteon', 6993) == (None, '재고있음', False)

    def test_musinsa_cap_is_instock(self):
        # 무신사는 '충분'을 stock_cap(=10)으로 저장 → '재고있음' (가짜 '재고 10' 방지)
        assert _STOCK_CAP == 10
        assert _resolve_stock('musinsa', 10) == (None, '재고있음', False)
        assert _resolve_stock('musinsa', 50) == (None, '재고있음', False)

    def test_musinsa_real_limited_quantity(self):
        # 무신사 1~9 = 실제 제한 재고 → 숫자 표기
        assert _resolve_stock('musinsa', 3) == (3, '3개', False)

    def test_ssg_real_quantity_including_10(self):
        # SSG는 실수량 노출 — 10은 진짜 10 (무신사 cap과 의미 다름, 사이트별 처리)
        assert _resolve_stock('ssg', 10) == (10, '10개', False)
        assert _resolve_stock('ssg', 50) == (50, '50개', False)
        assert _resolve_stock('ssg', 177) == (177, '177개', False)

    def test_smartstore_real_small_quantity(self):
        assert _resolve_stock('ss_lemouton', 1) == (1, '1개', False)


# ─────────────────────────────────────────────────────────────
# _match_option_stock — 색상+사이즈 매칭
# ─────────────────────────────────────────────────────────────
class TestMatchOptionStock:
    def test_multicolor_url_disambiguates_by_color(self):
        # 르무통/SSF: 1 URL = 여러 색. size_text='240mm', color_text=진짜색.
        #   그레이 240 을 찾을 때 블랙 240 재고(0)가 아니라 그레이 240 재고(999)를 가져와야 함.
        idx = _build_so_index([
            _so(5, '240mm', '블랙', 0),
            _so(5, '240mm', '그레이', 999),
        ])
        assert _match_option_stock(idx, 5, '그레이', '240') == 999
        assert _match_option_stock(idx, 5, '블랙', '240') == 0

    def test_size_in_color_text_single_color_url(self):
        # 롯데온/SSG: size_text='' (빈칸), 사이즈가 color_text 에. 단일색 URL → 사이즈만 매칭.
        idx = _build_so_index([
            _so(57, '', '220', 0),
            _so(57, '', '230', 999),
            _so(57, '', '250mm', 999),
        ])
        assert _match_option_stock(idx, 57, '그레이', '220') == 0
        assert _match_option_stock(idx, 57, '그레이', '230') == 999
        assert _match_option_stock(idx, 57, '그레이', '250') == 999

    def test_musinsa_empty_color_text_size_only(self):
        # 무신사: size_text='245mm', color_text='' → 색 정보 없음(단일색 URL) → 사이즈 매칭.
        idx = _build_so_index([
            _so(4, '230mm', '', 0),
            _so(4, '245mm', '', 10),
        ])
        assert _match_option_stock(idx, 4, '그레이', '245') == 10
        assert _match_option_stock(idx, 4, '그레이', '230') == 0

    def test_no_size_match_returns_none(self):
        idx = _build_so_index([_so(5, '240mm', '블랙', 999)])
        assert _match_option_stock(idx, 5, '블랙', '290') is None

    def test_unknown_product_returns_none(self):
        idx = _build_so_index([_so(5, '240mm', '블랙', 999)])
        assert _match_option_stock(idx, 999, '블랙', '240') is None

    def test_color_normalization_spaces_parens(self):
        # 색 비교는 공백·괄호 제거 후. '화이트 (아우터)' vs '화이트(아우터)' 매칭.
        idx = _build_so_index([_so(1, '280mm', '화이트 (아우터)', 7)])
        assert _match_option_stock(idx, 1, '화이트(아우터)', '280') == 7

    def test_zero_stock_preserved_not_treated_as_missing(self):
        # current_stock=0 은 '품절'로 보존돼야 함 (None 과 구분).
        idx = _build_so_index([_so(57, '', '220', 0)])
        assert _match_option_stock(idx, 57, '그레이', '220') == 0

    # ── H1 회귀: 색상 부분일치(substring) 오매칭 봉쇄 (2026-06-12) ──
    def test_exact_color_preferred_over_substring(self):
        # '그레이' 는 '라이트그레이'(부분포함)가 후보 먼저 와도 정확매칭을 골라야 한다.
        #   기존: oc in sc 로 '라이트그레이'(111) 를 먼저 잡아 엉뚱한 색 재고/가격 반환.
        idx = _build_so_index([
            _so(5, '240mm', '라이트그레이', 111),
            _so(5, '240mm', '그레이', 999),
        ])
        assert _match_option_stock(idx, 5, '그레이', '240') == 999
        # 순서 반대여도 동일.
        idx2 = _build_so_index([
            _so(5, '240mm', '그레이', 999),
            _so(5, '240mm', '라이트그레이', 111),
        ])
        assert _match_option_stock(idx2, 5, '그레이', '240') == 999

    def test_ambiguous_substring_returns_none(self):
        # 정확매칭 없고 부분매칭 후보가 2개 이상이면 추측 금지 → None.
        #   (엉뚱한 색을 비결정적으로 찍느니 미매칭이 안전 — 금전 사고 방지)
        idx = _build_so_index([
            _so(5, '240mm', '라이트그레이', 111),
            _so(5, '240mm', '다크그레이', 222),
        ])
        assert _match_option_stock(idx, 5, '그레이', '240') is None

    def test_single_substring_descriptor_still_matches(self):
        # 정당한 부분매칭은 유지: '블랙' ↔ '블랙(아웃솔)' 단일 후보면 매칭.
        idx = _build_so_index([_so(5, '250mm', '블랙(아웃솔)', 7)])
        assert _match_option_stock(idx, 5, '블랙', '250') == 7


# ─────────────────────────────────────────────────────────────
# _resolve_sourcing_cost — 소싱 카드 원가는 크롤 실제가만(폴백 금지, #4)
# ─────────────────────────────────────────────────────────────
class TestResolveSourcingCost:
    def test_uses_crawled_cost(self):
        assert _resolve_sourcing_cost({'crawled_price': 112000}) == 112000

    def test_none_when_no_source(self):
        # 전 소싱처 실패(_pick_cheapest_buyable=None) → 폴백 금지 → None.
        #   (기존엔 boxhero 사입가/95000 으로 메워 가짜 판매가 표시 → 손실)
        assert _resolve_sourcing_cost(None) is None

    def test_none_when_zero_or_missing(self):
        assert _resolve_sourcing_cost({'crawled_price': 0}) is None
        assert _resolve_sourcing_cost({}) is None


# ─────────────────────────────────────────────────────────────
# _pick_cheapest_buyable — 재고존재+최저가 winner/원가 정의
# ─────────────────────────────────────────────────────────────
class TestPickCheapestBuyable:
    def _src(self, price, status='ok', out=False):
        return {'crawled_price': price, 'last_status': status, 'stock_out': out}

    def test_cheapest_among_instock_success(self):
        srcs = [self._src(120000), self._src(116900), self._src(118000)]
        assert _pick_cheapest_buyable(srcs)['crawled_price'] == 116900

    def test_soldout_excluded_even_if_cheapest(self):
        # 품절(stock_out)인 최저가는 winner 가 될 수 없음.
        srcs = [self._src(100000, out=True), self._src(118000)]
        assert _pick_cheapest_buyable(srcs)['crawled_price'] == 118000

    def test_crawl_error_excluded_even_if_cheapest(self):
        # 크롤 실패(stale 가격)인 최저가 제외.
        srcs = [self._src(100000, status='error'), self._src(118000)]
        assert _pick_cheapest_buyable(srcs)['crawled_price'] == 118000

    def test_fallback_skips_error_keeps_soldout(self):
        # [2026-06-05] 재고있는 게 없으면(전부 품절/실패) → 크롤 성공(error X)한 것 중 최저로 fallback.
        #   error(stale)는 폴백에서도 절대 제외. 품절이라도 '실가격'인 130000 을 선택
        #   (기존엔 더 싼 error 120000 을 끌어쓰던 stale 누수 — 봉쇄).
        srcs = [self._src(130000, out=True), self._src(120000, status='error')]
        assert _pick_cheapest_buyable(srcs)['crawled_price'] == 130000

    def test_fallback_never_uses_error_as_last_resort(self):
        # 유일 후보가 크롤 실패면 None — stale 가격을 끝까지 원가로 쓰지 않음.
        assert _pick_cheapest_buyable([self._src(120000, status='error')]) is None

    def test_no_priced_returns_none(self):
        srcs = [self._src(None), self._src(0)]
        assert _pick_cheapest_buyable(srcs) is None

    def test_empty_returns_none(self):
        assert _pick_cheapest_buyable([]) is None


# ─────────────────────────────────────────────────────────────
# _stock_state — 재고 원시값 → 상태 문자열 (프론트 스타일/툴팁용)
# ─────────────────────────────────────────────────────────────
class TestStockState:
    def test_states(self):
        from webapp.routes.api_pricing import _stock_state
        assert _stock_state('lotteon', -1) == 'unknown'
        assert _stock_state('lotteon', 0) == 'soldout'
        assert _stock_state('lotteon', 5) == 'limited'
        assert _stock_state('lotteon', 999) == 'unknown'
        assert _stock_state('lotteon', None) == 'uncrawled'
        assert _stock_state('musinsa', 10) == 'ample'

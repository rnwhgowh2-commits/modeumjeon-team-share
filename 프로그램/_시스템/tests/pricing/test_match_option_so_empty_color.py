# -*- coding: utf-8 -*-
"""[TEST] 무신사 단품 빈 색(color='') 재고 매칭 버그 수정 (2026-06-24).

확인된 버그(라이브 실증):
  - 단품 SourceOption: size_text='230mm', color_text='올리브그린'
  - 무신사 단품 API 색 축 없음 → 확장이 color='' 전송
  - 기존: has_color=True(SO color_text 있음) → 색 일치 분기 → oc='' → if oc and sc → False → continue → None
  - 결과: 재고 영속 불가 → 매트릭스 거짓 품절

수정:
  if has_color: → if has_color and oc:
  → 크롤이 색을 안 줬을 때(단품)는 사이즈만으로 매칭(안전: 단품 SP = 단일색)

안전성:
  - oc 가 비어야 사이즈 폴백 → 다색 소싱처(르무통 등)는 영향 없음
  - 색 제공 크롤에서 색이 다르면 여전히 None(잘못 매칭 방지)
  - 매트릭스 표시 쪽은 실제 색 전달 → oc 비어 있지 않음 → 기존 경로 유지
"""
import types

import pytest

from webapp.routes.api_pricing import (
    _match_option_so,
    _build_so_index,
)


def _so_obj(pid, size_text, color_text, stock=999):
    """SourceOption 스텁 — _match_option_so 가 읽는 속성만."""
    return types.SimpleNamespace(
        source_product_id=pid,
        size_text=size_text,
        color_text=color_text,
        current_stock=stock,
    )


def _idx(*sos):
    return _build_so_index(list(sos))


# ─────────────────────────────────────────────────────────────
# 핵심 버그 케이스 — 수정 전 FAIL, 수정 후 PASS
# ─────────────────────────────────────────────────────────────

class TestEmptyColorMatchesBySize:
    """크롤 color='' (단품 소싱처) 일 때 사이즈만으로 매칭."""

    def test_empty_crawl_color_matches_instock_size(self):
        """무신사 단품 핵심 케이스: color='' + size='230' → SO(올리브그린 230) 반환."""
        idx = _idx(
            _so_obj(11, '220mm', '올리브그린', 999),
            _so_obj(11, '230mm', '올리브그린', 2),
            _so_obj(11, '265mm', '올리브그린', 1),
        )
        so = _match_option_so(idx, 11, opt_color='', opt_size='230')
        assert so is not None, (
            "color='' 단품 크롤에서 SO 매칭 실패 — 거짓 품절 버그 재현"
        )
        assert so.current_stock == 2

    def test_empty_crawl_color_soldout_matched(self):
        """품절(0) 사이즈도 color='' 로 매칭 — 거짓 재고있음(999 잔류) 방지."""
        idx = _idx(
            _so_obj(11, '220mm', '올리브그린', 0),   # 품절
            _so_obj(11, '230mm', '올리브그린', 999),
        )
        so = _match_option_so(idx, 11, opt_color='', opt_size='220')
        assert so is not None
        assert so.current_stock == 0

    def test_empty_crawl_color_all_sizes(self):
        """3개 사이즈 전부 color='' 로 각각 올바른 SO 에 매칭."""
        sos = [
            _so_obj(11, '220mm', '올리브그린', 999),
            _so_obj(11, '230mm', '올리브그린', 2),
            _so_obj(11, '265mm', '올리브그린', 1),
        ]
        idx = _build_so_index(sos)
        assert _match_option_so(idx, 11, '', '220').current_stock == 999
        assert _match_option_so(idx, 11, '', '230').current_stock == 2
        assert _match_option_so(idx, 11, '', '265').current_stock == 1


# ─────────────────────────────────────────────────────────────
# 기존 동작 보존 케이스 — 수정 전·후 모두 PASS
# ─────────────────────────────────────────────────────────────

class TestColorMatchPreserved:
    """크롤이 실제 색을 줬을 때 기존 색+사이즈 매칭이 그대로."""

    def test_real_color_exact_match(self):
        """oc='올리브그린' 이면 색+사이즈 정확 매칭 경로 유지."""
        idx = _idx(_so_obj(11, '230mm', '올리브그린', 2))
        so = _match_option_so(idx, 11, opt_color='올리브그린', opt_size='230')
        assert so is not None
        assert so.current_stock == 2

    def test_wrong_color_rejected_when_crawl_provides_color(self):
        """크롤이 색을 줬는데 색이 다르면 None — 다색 소싱처 오매칭 방지(핵심 안전망)."""
        idx = _idx(_so_obj(11, '230mm', '올리브그린', 2))
        so = _match_option_so(idx, 11, opt_color='블랙', opt_size='230')
        assert so is None, "다른 색 크롤(블랙) → 올리브그린 SO 매칭돼선 안 됨"

    def test_multicolor_url_color_disambiguation_intact(self):
        """르무통 다색 URL: 크롤이 색 줄 때 블랙/그레이 240 을 정확히 구분."""
        idx = _idx(
            _so_obj(22, '240mm', '블랙', 0),
            _so_obj(22, '240mm', '그레이', 999),
        )
        assert _match_option_so(idx, 22, '그레이', '240').current_stock == 999
        assert _match_option_so(idx, 22, '블랙', '240').current_stock == 0

    def test_multicolor_empty_crawl_color_fallback_not_none(self):
        """다색 URL에도 color='' 크롤이 오면 사이즈로 매칭(어느 색이든 반환). None 이면 안 됨."""
        idx = _idx(
            _so_obj(22, '240mm', '블랙', 0),
            _so_obj(22, '240mm', '그레이', 999),
        )
        so_empty = _match_option_so(idx, 22, opt_color='', opt_size='240')
        assert so_empty is not None   # size-only fallback; 어느 색이든 매칭

"""[TEST] 무신사 단품 SP 색상 스코프 — 등록색 옵션만 저장, 형제색 병합 폴루션 차단.

배경(ROOT pollution bug):
  무신사 단품 SourceProduct 를 크롤하면 MusinsaCrawler._discover_color_variants 가
  오렌지·블랙·아이보리 등 모든 색 변형을 합쳐 반환한다. save_crawl_result 가 필터 없이
  그대로 upsert → 오렌지 SP 에 블랙·아이보리 행이 섞이는 오염(pollution).

정책(TDD Step 2 → 3):
  1. 단품(url_type='단품') SP 에서 BundleSourceUrl.label 로 등록색 판별.
  2. _scope_options_to_color(options, reg_color) — 등록색 일치·빈색 옵션만 통과,
     통과된 옵션의 color_text 를 등록색으로 정규화.
  3. save_crawl_result 가 scoped 옵션만 upsert + prune.
  4. 모음전(색상모음전/모델모음전) SP 는 동작 변경 없음(reg_color=None → 전부 통과).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

# 전체 모델 등록 (FK 타겟 누락 방지)
for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.sources.models import SourceProduct, SourceOption
from lemouton.sourcing.models import BundleSourceUrl
from lemouton.sources.service import (
    upsert_source_product,
    save_crawl_result,
    _scope_options_to_color,
    _resolve_reg_color,
)
from lemouton.sourcing.crawlers.base import CrawlResult

_MUSINSA_URL = "https://www.musinsa.com/products/4800825"


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _cr(opts):
    return CrawlResult(
        source="musinsa",
        product_url=_MUSINSA_URL,
        product_name_raw="메이트",
        options=opts,
    )


def _opt(color, size, price=116900, stock=5):
    return {
        "color_text": color,
        "size_text": size,
        "sale_price": price,
        "price": price,
        "stock": stock,
        "option_id": f"4800825|{color}|{size}",
    }


def _active(db, sp):
    return db.query(SourceOption).filter_by(
        source_product_id=sp.id, deleted_at=None
    ).all()


# ─── unit: _scope_options_to_color ──────────────────────────────────────────

class TestScopeOptionsToColor:
    """_scope_options_to_color 순수함수 단위 테스트."""

    _RAW_OPTS = [
        {"color_text": "메이트 블랙", "size_text": "220mm"},
        {"color_text": "오렌지", "size_text": "220mm"},
        {"color_text": "", "size_text": "225mm"},
        {"color_text": "메이트 아이보리", "size_text": "230mm"},
    ]

    def test_keeps_matching_color(self):
        result = _scope_options_to_color(list(self._RAW_OPTS), "오렌지")
        colors = [o["color_text"] for o in result]
        assert "메이트 블랙" not in colors
        assert "메이트 아이보리" not in colors

    def test_keeps_empty_color(self):
        result = _scope_options_to_color(list(self._RAW_OPTS), "오렌지")
        sizes = [o["size_text"] for o in result]
        assert "225mm" in sizes  # 빈 색 → 통과

    def test_canonicalizes_to_reg_color(self):
        result = _scope_options_to_color(list(self._RAW_OPTS), "오렌지")
        # 오렌지 220mm 와 빈색 225mm 둘 다 color_text='오렌지' 로 정규화
        for o in result:
            assert o["color_text"] == "오렌지", f"expected 오렌지, got {o['color_text']!r}"

    def test_result_count(self):
        result = _scope_options_to_color(list(self._RAW_OPTS), "오렌지")
        assert len(result) == 2  # 오렌지220 + 빈225 (블랙220·아이보리230 제외)

    def test_noop_when_no_reg_color(self):
        """reg_color 가 None/빈 문자열이면 전부 그대로 반환."""
        result_none = _scope_options_to_color(list(self._RAW_OPTS), None)
        result_empty = _scope_options_to_color(list(self._RAW_OPTS), "")
        assert len(result_none) == len(self._RAW_OPTS)
        assert len(result_empty) == len(self._RAW_OPTS)

    def test_immutable_input(self):
        """원본 리스트가 변형되지 않아야 한다."""
        original = [dict(o) for o in self._RAW_OPTS]
        _scope_options_to_color(list(self._RAW_OPTS), "오렌지")
        for orig, after in zip(original, self._RAW_OPTS):
            assert orig == after


# ─── unit: _resolve_reg_color ────────────────────────────────────────────────

class TestResolveRegColor:

    def test_dan_url_returns_color(self, db):
        """url_type='단품', label='musinsa_오렌지' → '오렌지'"""
        sp = SourceProduct(site="musinsa", url=_MUSINSA_URL)
        db.add(sp)
        db.flush()
        bsu = BundleSourceUrl(
            model_code="MATE001",
            source_key="musinsa",
            url=_MUSINSA_URL,
            label="musinsa_오렌지",
            url_type="단품",
        )
        db.add(bsu)
        db.flush()

        color = _resolve_reg_color(db, sp)
        assert color == "오렌지"

    def test_moumjun_url_returns_none(self, db):
        """url_type='색상모음전' → None (필터 안 함)."""
        sp = SourceProduct(site="musinsa", url=_MUSINSA_URL)
        db.add(sp)
        db.flush()
        bsu = BundleSourceUrl(
            model_code="MATE001",
            source_key="musinsa",
            url=_MUSINSA_URL,
            label="musinsa_오렌지",
            url_type="색상모음전",
        )
        db.add(bsu)
        db.flush()

        color = _resolve_reg_color(db, sp)
        assert color is None

    def test_no_bsu_returns_none(self, db):
        """BundleSourceUrl 매핑이 없으면 None (보수적 — 필터 안 함)."""
        sp = SourceProduct(site="musinsa", url=_MUSINSA_URL)
        db.add(sp)
        db.flush()
        color = _resolve_reg_color(db, sp)
        assert color is None

    def test_label_without_underscore_uses_whole_label(self, db):
        """label 에 '_' 없으면 label 자체를 색상으로 사용."""
        sp = SourceProduct(site="musinsa", url=_MUSINSA_URL)
        db.add(sp)
        db.flush()
        bsu = BundleSourceUrl(
            model_code="MATE001",
            source_key="musinsa",
            url=_MUSINSA_URL,
            label="오렌지",
            url_type="단품",
        )
        db.add(bsu)
        db.flush()
        color = _resolve_reg_color(db, sp)
        assert color == "오렌지"


# ─── integration: save_crawl_result 색상 스코프 ──────────────────────────────

class TestSaveCrawlResultDanScope:
    """save_crawl_result 가 단품 SP 에서 형제색 옵션을 차단하는지 통합 검증."""

    _MIXED_OPTS = [
        _opt("메이트 블랙", "220mm"),
        _opt("오렌지", "220mm"),
        _opt("", "225mm"),
        _opt("메이트 아이보리", "230mm"),
    ]

    def _setup_dan(self, db):
        """단품 SP + BundleSourceUrl(단품, 오렌지) 세팅."""
        sp = upsert_source_product(db, site="musinsa", url=_MUSINSA_URL)
        db.flush()
        bsu = BundleSourceUrl(
            model_code="MATE001",
            source_key="musinsa",
            url=_MUSINSA_URL,
            label="musinsa_오렌지",
            url_type="단품",
        )
        db.add(bsu)
        db.flush()
        return sp

    def test_dan_filters_sibling_colors(self, db):
        """단품 SP → 메이트블랙·메이트아이보리 제거, 오렌지만 남아야 한다."""
        sp = self._setup_dan(db)
        save_crawl_result(db, source_product=sp, crawl_result=_cr(self._MIXED_OPTS))
        db.flush()

        active = _active(db, sp)
        color_sizes = {(o.color_text, o.size_text) for o in active}

        # 메이트 블랙·아이보리는 없어야 함
        assert all("블랙" not in (ct or "") for ct, _ in color_sizes), \
            f"블랙이 남아있음: {color_sizes}"
        assert all("아이보리" not in (ct or "") for ct, _ in color_sizes), \
            f"아이보리가 남아있음: {color_sizes}"

    def test_dan_keeps_matching_and_empty_color(self, db):
        """단품 SP → 오렌지220 + 빈색225(→오렌지225) 두 행 유지."""
        sp = self._setup_dan(db)
        save_crawl_result(db, source_product=sp, crawl_result=_cr(self._MIXED_OPTS))
        db.flush()

        active = _active(db, sp)
        sizes = {o.size_text for o in active}
        assert "220mm" in sizes
        assert "225mm" in sizes
        assert len(active) == 2, f"expected 2 rows, got {len(active)}: {[(o.color_text, o.size_text) for o in active]}"

    def test_dan_canonicalizes_color_text(self, db):
        """단품 SP → 저장된 모든 옵션의 color_text == '오렌지'."""
        sp = self._setup_dan(db)
        save_crawl_result(db, source_product=sp, crawl_result=_cr(self._MIXED_OPTS))
        db.flush()

        active = _active(db, sp)
        for o in active:
            assert o.color_text == "오렌지", \
                f"color_text 정규화 실패: {o.color_text!r} (size={o.size_text})"

    def test_moumjun_keeps_all_colors(self, db):
        """색상모음전 SP → 모든 색 옵션 유지 (동작 변경 없음)."""
        sp = upsert_source_product(db, site="musinsa", url=_MUSINSA_URL)
        db.flush()
        bsu = BundleSourceUrl(
            model_code="MATE001",
            source_key="musinsa",
            url=_MUSINSA_URL,
            label="musinsa_오렌지",
            url_type="색상모음전",
        )
        db.add(bsu)
        db.flush()

        save_crawl_result(db, source_product=sp, crawl_result=_cr(self._MIXED_OPTS))
        db.flush()

        active = _active(db, sp)
        colors = {o.color_text for o in active}
        # 모든 색(정규화 후) 존재해야 함
        assert len(active) == 4, f"색상모음전은 4행 유지해야 함: {colors}"

    def test_no_bsu_keeps_all_options(self, db):
        """BundleSourceUrl 매핑 없으면 보수적으로 전부 저장 (필터 안 함)."""
        sp = upsert_source_product(db, site="musinsa", url=_MUSINSA_URL)
        db.flush()
        # BundleSourceUrl 없음

        save_crawl_result(db, source_product=sp, crawl_result=_cr(self._MIXED_OPTS))
        db.flush()

        active = _active(db, sp)
        assert len(active) == 4, f"매핑없음=전부저장: {len(active)}"

    def test_prune_uses_scoped_keys(self, db):
        """단품 prune 은 scoped 옵션 기준 — 형제색 행이 먼저 있어도 soft-delete."""
        sp = self._setup_dan(db)
        # 첫 크롤: 오렌지 + 블랙 (오염된 상태 시뮬레이션)
        from lemouton.sources.service import upsert_source_option
        upsert_source_option(db, source_product_id=sp.id,
                             color_text="메이트 블랙", size_text="220mm", current_price=100)
        upsert_source_option(db, source_product_id=sp.id,
                             color_text="오렌지", size_text="220mm", current_price=100)
        db.flush()
        assert len(_active(db, sp)) == 2  # 오염 상태 확인

        # 두 번째 크롤: save_crawl_result 가 scoped 옵션만 남겨야 함
        save_crawl_result(db, source_product=sp, crawl_result=_cr([_opt("오렌지", "220mm")]))
        db.flush()

        active = _active(db, sp)
        assert len(active) == 1
        assert active[0].color_text == "오렌지"

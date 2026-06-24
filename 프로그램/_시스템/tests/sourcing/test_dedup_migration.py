"""[TEST] 무신사 단품 SourceOption dedup 마이그레이션 — TDD Step 2 (Failing tests first).

배경:
  무신사 단품 SourceProduct (예: 오렌지 sp id=68)에 121개 행이 있고, 그 중에는
  '메이트 블랙', '메이트 아이보리', '르무통 메이트 운동화' 등 타색 행과
  '220MM' (대문자) 같은 사이즈 대소문자 중복이 섞여 있다.

  dedup_dan_sp(session, sp, reg_color, dry_run) 함수가:
  1. dry_run=True  → keep/delete 분류만, DB 변경 없음
  2. dry_run=False → delete 목록 soft-delete (deleted_at 설정), keep 유지
  3. reg_color=None → 전부 keep, delete=[] (보수적 — 변경 없음)
  4. 사이즈마다 등록색 후보가 없으면 보수적으로 유지(skipped)
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

_MUSINSA_URL = "https://www.musinsa.com/products/4800825"


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _make_sp(db) -> SourceProduct:
    """오렌지 단품 SP + BundleSourceUrl(단품, musinsa_오렌지) 생성."""
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
    return sp


def _add_option(db, sp, color, size, stock=5, price=116900) -> SourceOption:
    so = SourceOption(
        source_product_id=sp.id,
        color_text=color,
        size_text=size,
        current_stock=stock,
        current_price=price,
    )
    db.add(so)
    db.flush()
    return so


def _active(db, sp):
    return db.query(SourceOption).filter_by(
        source_product_id=sp.id, deleted_at=None
    ).all()


# ─── Import 대상 ──────────────────────────────────────────────────────────────

from lemouton.sources.dedup_migration import dedup_dan_sp


# ─── dry_run=True 동작 ────────────────────────────────────────────────────────

class TestDedupDanSpDryRun:
    """dry_run=True: 분류 결과 반환, DB 무변경."""

    def _setup(self, db):
        sp = _make_sp(db)
        so_orange_220 = _add_option(db, sp, "오렌지", "220mm", stock=5)
        so_black_220  = _add_option(db, sp, "메이트 블랙", "220mm", stock=999)
        so_long_220   = _add_option(db, sp, "르무통 메이트 운동화", "220mm", stock=3)
        so_orange_220U= _add_option(db, sp, "오렌지", "220MM", stock=2)   # dup uppercase
        so_ivory_225  = _add_option(db, sp, "메이트 아이보리", "225mm", stock=4)
        so_orange_225 = _add_option(db, sp, "오렌지", "225mm", stock=1)
        return sp, [so_orange_220, so_black_220, so_long_220,
                    so_orange_220U, so_ivory_225, so_orange_225]

    def test_dry_run_returns_dict(self, db):
        sp, _ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        assert isinstance(result, dict)
        for key in ("sp_id", "reg_color", "total", "keep", "delete", "skipped"):
            assert key in result, f"key '{key}' missing from result"

    def test_dry_run_no_db_change(self, db):
        sp, _ = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        # 모든 6개 행이 deleted_at=None 으로 유지되어야 함
        all_rows = db.query(SourceOption).filter_by(source_product_id=sp.id).all()
        assert all(r.deleted_at is None for r in all_rows), \
            "dry_run=True 에서 deleted_at 이 설정됨 — DB 변경 금지"

    def test_dry_run_total(self, db):
        sp, _ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        assert result["total"] == 6

    def test_dry_run_keep_one_orange_per_size(self, db):
        """keep 목록: 정규화 사이즈 기준 오렌지 행 1개씩 — 220mm, 225mm."""
        sp, _ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        keep_sizes = {r["size"] for r in result["keep"]}
        assert "220mm" in keep_sizes
        assert "225mm" in keep_sizes
        assert len(result["keep"]) == 2, \
            f"keep 2개 예상, got {len(result['keep'])}: {result['keep']}"

    def test_dry_run_delete_non_orange_rows(self, db):
        """delete 목록: 메이트블랙·르무통·메이트아이보리 3행 + 오렌지 220MM 중복 1행 = 4행."""
        sp, _ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        delete_colors = [r["color"] for r in result["delete"]]
        assert "메이트 블랙" in delete_colors
        assert "메이트 아이보리" in delete_colors
        # 르무통 메이트 운동화 also in delete
        assert any("르무통" in c or "운동화" in c for c in delete_colors), \
            f"르무통 행이 delete 에 없음: {delete_colors}"
        # 오렌지 220mm 중복(220MM) 은 하나는 keep, 하나는 delete
        delete_ids = {r["id"] for r in result["delete"]}
        keep_ids = {r["id"] for r in result["keep"]}
        assert delete_ids.isdisjoint(keep_ids), "keep/delete 중복 id 있음"

    def test_dry_run_sp_id(self, db):
        sp, _ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        assert result["sp_id"] == sp.id

    def test_dry_run_reg_color_in_result(self, db):
        sp, _ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        assert result["reg_color"] == "오렌지"


# ─── dry_run=False 동작 ───────────────────────────────────────────────────────

class TestDedupDanSpReal:
    """dry_run=False: delete 행 soft-delete, keep 행 유지, hard-delete 없음."""

    def _setup(self, db):
        sp = _make_sp(db)
        so_orange_220 = _add_option(db, sp, "오렌지", "220mm", stock=5)
        so_black_220  = _add_option(db, sp, "메이트 블랙", "220mm", stock=999)
        so_long_220   = _add_option(db, sp, "르무통 메이트 운동화", "220mm", stock=3)
        so_orange_220U= _add_option(db, sp, "오렌지", "220MM", stock=2)
        so_ivory_225  = _add_option(db, sp, "메이트 아이보리", "225mm", stock=4)
        so_orange_225 = _add_option(db, sp, "오렌지", "225mm", stock=1)
        return sp, so_orange_220, so_black_220, so_long_220, so_orange_220U, so_ivory_225, so_orange_225

    def test_real_run_soft_deletes_non_orange(self, db):
        sp, *_ = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        # deleted_at 설정된 행이 있어야 함
        deleted = db.query(SourceOption).filter(
            SourceOption.source_product_id == sp.id,
            SourceOption.deleted_at.isnot(None),
        ).all()
        assert len(deleted) > 0, "real run: 아무것도 soft-delete 되지 않음"

    def test_real_run_no_hard_delete(self, db):
        """hard-delete 절대 금지 — 전체 행 수 = 6 유지."""
        sp, *_ = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        total = db.query(SourceOption).filter_by(source_product_id=sp.id).count()
        assert total == 6, f"hard-delete 발생: 행이 {total}개 남음 (6개 유지 필요)"

    def test_real_run_keep_rows_not_deleted(self, db):
        """keep 행의 deleted_at 은 None — 활성 유지."""
        sp, *_ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        for r in result["keep"]:
            so = db.get(SourceOption, r["id"])
            assert so.deleted_at is None, \
                f"keep 행 id={r['id']} 가 soft-delete 됨"

    def test_real_run_delete_rows_have_deleted_at(self, db):
        """delete 행의 deleted_at 이 설정되어야 함."""
        sp, *_ = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        for r in result["delete"]:
            so = db.get(SourceOption, r["id"])
            assert so.deleted_at is not None, \
                f"delete 행 id={r['id']} 의 deleted_at 이 None"

    def test_real_run_active_count_is_two(self, db):
        """real run 후 활성(deleted_at=None) 오렌지 행 = 220mm + 225mm 2개."""
        sp, *_ = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        active = _active(db, sp)
        assert len(active) == 2, \
            f"활성행 2개 예상, got {len(active)}: {[(o.color_text, o.size_text) for o in active]}"

    def test_real_run_canonicalizes_color(self, db):
        """keep 행 color_text 가 등록색 '오렌지' 로 정규화된다."""
        sp, *_ = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        active = _active(db, sp)
        for o in active:
            assert o.color_text == "오렌지", \
                f"color_text 미정규화: {o.color_text!r}"

    def test_real_run_canonicalizes_size(self, db):
        """220MM 행이 keep 됐다면 size_text 가 220mm 로 정규화된다."""
        sp, *_ = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        active = _active(db, sp)
        sizes = {o.size_text for o in active}
        # 220mm 은 있어야 하고 220MM 는 없어야 함 (정규화됐거나 dupe가 delete됨)
        assert "220mm" in sizes
        assert "220MM" not in sizes, "220MM 가 정규화 없이 남아있음"


# ─── edge: reg_color=None ─────────────────────────────────────────────────────

class TestDedupDanSpNoneColor:
    """reg_color=None → 전부 keep, DB 변경 없음 (보수적)."""

    def _setup(self, db):
        sp = _make_sp(db)
        _add_option(db, sp, "오렌지", "220mm", stock=5)
        _add_option(db, sp, "메이트 블랙", "220mm", stock=999)
        _add_option(db, sp, "메이트 아이보리", "225mm", stock=4)
        return sp

    def test_none_color_keep_all(self, db):
        sp = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color=None, dry_run=True)
        assert len(result["delete"]) == 0, \
            f"reg_color=None 이면 delete=[] 이어야 함, got {result['delete']}"

    def test_none_color_no_db_change(self, db):
        sp = self._setup(db)
        dedup_dan_sp(db, sp, reg_color=None, dry_run=False)
        all_rows = db.query(SourceOption).filter_by(source_product_id=sp.id).all()
        assert all(r.deleted_at is None for r in all_rows), \
            "reg_color=None 이면 아무것도 soft-delete 하면 안 됨"

    def test_none_color_keep_list_has_all(self, db):
        sp = self._setup(db)
        result = dedup_dan_sp(db, sp, reg_color=None, dry_run=True)
        assert len(result["keep"]) + len(result["skipped"]) == 3


# ─── edge: 사이즈에 등록색 없으면 보수적 유지 ──────────────────────────────────

class TestDedupDanSpZeroRowGuard:
    """한 사이즈에 등록색 후보가 없으면 기존 행 유지 (절대 0행 금지)."""

    def test_size_with_no_orange_kept_in_skipped(self, db):
        """235mm 에 오렌지 없고 블랙만 있음 → 블랙 행이 skipped 로 보존."""
        sp = _make_sp(db)
        _add_option(db, sp, "오렌지", "220mm", stock=5)
        _add_option(db, sp, "메이트 블랙", "235mm", stock=3)  # 이 사이즈 오렌지 없음
        result = dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=True)
        # 블랙 235mm 는 delete 에 있으면 안 되고 skipped 에 있어야 함
        delete_ids = {r["id"] for r in result["delete"]}
        all_so = db.query(SourceOption).filter_by(source_product_id=sp.id).all()
        black_235 = next(o for o in all_so if o.color_text == "메이트 블랙")
        assert black_235.id not in delete_ids, \
            "등록색 없는 사이즈의 행을 delete 목록에 넣으면 안 됨 (0행 방지)"
        skipped_ids = {r["id"] for r in result["skipped"]}
        assert black_235.id in skipped_ids, \
            "등록색 없는 사이즈 행은 skipped 에 있어야 함"

    def test_size_with_no_orange_not_soft_deleted(self, db):
        """235mm 블랙 행: dry_run=False 에서도 soft-delete 금지."""
        sp = _make_sp(db)
        _add_option(db, sp, "오렌지", "220mm", stock=5)
        so_black_235 = _add_option(db, sp, "메이트 블랙", "235mm", stock=3)
        dedup_dan_sp(db, sp, reg_color="오렌지", dry_run=False)
        db.refresh(so_black_235)
        assert so_black_235.deleted_at is None, \
            "등록색 없는 사이즈 행이 soft-delete 됨 — 0행 방지 위반"


# ─── Bug regression: already-canonical row 유니크 충돌 ───────────────────────
#
# 재현 시나리오 (SP 66, reg_color='라이트블루'):
#   사이즈 230mm 에 두 후보:
#     A) color='라이트블루', size='230mm', stock=5   ← 이미 canonical
#     B) color='메이트 라이트블루', size='230mm', stock=999 ← stock 더 많음
#
#   기존 로직: B(stock=999)를 winner 로 선택 → soft-delete 로 A(deleted) →
#   B.color_text = '라이트블루' 로 rename → UniqueViolation (A 가 이미 키 점유)
#
#   올바른 동작: A 가 이미 canonical → A 를 winner, B 를 soft-delete.
#               A.current_stock 을 max(5, 999)=999 로 갱신.

class TestDedupCanonicalFirst:
    """이미 canonical 인 행이 있으면 그것을 winner 로 — rename 없이 충돌 회피."""

    def _setup(self, db):
        """SP 66 유사: 라이트블루, 230mm 에 이미-canonical + 더높은-stock 후보."""
        sp = SourceProduct(site="musinsa", url="https://www.musinsa.com/products/66")
        db.add(sp)
        db.flush()
        # A: 이미 canonical — (reg_color, norm_size) 그대로
        so_canonical = _add_option(db, sp, "라이트블루", "230mm", stock=5)
        # B: reg_color 포함 but 더 긴 색명, stock 더 높음
        so_mate = _add_option(db, sp, "메이트 라이트블루", "230mm", stock=999)
        return sp, so_canonical, so_mate

    def test_no_unique_violation(self, db):
        """dry_run=False 에서 UniqueViolation 이 발생하면 안 된다."""
        sp, so_canonical, so_mate = self._setup(db)
        # 예외 없이 완료돼야 함
        dedup_dan_sp(db, sp, reg_color="라이트블루", dry_run=False)

    def test_canonical_row_is_winner(self, db):
        """실행 후 활성 행 = 이미-canonical 행 (라이트블루/230mm) 단 1개."""
        sp, so_canonical, so_mate = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="라이트블루", dry_run=False)
        active = db.query(SourceOption).filter_by(
            source_product_id=sp.id, deleted_at=None
        ).all()
        assert len(active) == 1, \
            f"활성 행 1개 예상, got {len(active)}: {[(o.color_text, o.size_text) for o in active]}"
        winner = active[0]
        assert winner.color_text == "라이트블루", \
            f"winner color_text 가 '라이트블루' 가 아님: {winner.color_text!r}"
        assert winner.size_text == "230mm", \
            f"winner size_text 가 '230mm' 가 아님: {winner.size_text!r}"

    def test_mate_row_soft_deleted(self, db):
        """'메이트 라이트블루' 행은 soft-delete 되어야 함."""
        sp, so_canonical, so_mate = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="라이트블루", dry_run=False)
        db.refresh(so_mate)
        assert so_mate.deleted_at is not None, \
            "'메이트 라이트블루' 행이 soft-delete 되지 않음"

    def test_canonical_stock_updated_to_best(self, db):
        """canonical winner 의 current_stock = max(5, 999) = 999 (최고 재고 보존)."""
        sp, so_canonical, so_mate = self._setup(db)
        dedup_dan_sp(db, sp, reg_color="라이트블루", dry_run=False)
        db.refresh(so_canonical)
        assert so_canonical.current_stock == 999, \
            f"canonical 행 current_stock 이 999 로 갱신되지 않음: {so_canonical.current_stock}"

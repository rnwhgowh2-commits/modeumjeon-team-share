# -*- coding: utf-8 -*-
"""[TEST] 확장 크롤 결과 — 옵션단위 실재고 영속 (_persist_option_stocks).

배경(project_smartstore_stock_not_persisted_extension_path, 2026-06-22):
  스마트스토어 등 '확장 전용'(네이버 WAF) 소싱처 재고가 매트릭스에서 전부 999
  ('재고있음')로 둔갑. 원인 = 확장이 색·사이즈별 재고를 긁고 parse 가 품절(0)까지
  교정해 보내는데, 라우트 save_crawl_result 가 그 옵션단위 stock 을 current_stock 에
  쓰지 않아서(서버사이드 _ingest 만 채워 옴) 옛 999 가 그대로 노출됐다.
  이 테스트가 '옵션단위 재고 영속 + 품절(0) 보존 + None 건너뜀'을 영구 잠근다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

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
from lemouton.sources.service import upsert_source_product
from webapp.routes.api_pricing import _persist_option_stocks


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _sp(db):
    sp = upsert_source_product(
        db, site="ss_lemouton",
        url="https://brand.naver.com/lemouton/products/5844147017")
    db.commit()
    return sp


def _seed_so(db, sp, color, size, stock):
    """크롤 전 상태 — 옛 999 센티넬로 시드된 SourceOption."""
    so = SourceOption(source_product_id=sp.id, color_text=color,
                      size_text=size, current_stock=stock, current_price=108961)
    db.add(so)
    db.commit()
    return so


def _stock(db, sp, color, size):
    so = (db.query(SourceOption)
          .filter_by(source_product_id=sp.id, color_text=color,
                     size_text=size, deleted_at=None).first())
    return so.current_stock if so else "MISSING"


def test_soldout_zero_is_persisted_over_999(db):
    """품절(0)이 옛 999 를 덮어쓴다 — 핵심 버그(품절 사이즈 '있음' 둔갑) 수정."""
    sp = _sp(db)
    _seed_so(db, sp, "다크네이비", "265", 999)
    _seed_so(db, sp, "그레이", "265", 999)
    n = _persist_option_stocks(db, sp.id, [
        {"color": "다크네이비", "size": "265", "stock": 0},
        {"color": "그레이", "size": "265", "stock": 0},
    ])
    db.commit()
    assert n == 2
    assert _stock(db, sp, "다크네이비", "265") == 0     # 품절 영속 ✓
    assert _stock(db, sp, "그레이", "265") == 0


def test_real_quantity_persisted(db):
    """실수량(예: 14개)이 999 를 덮어쓴다."""
    sp = _sp(db)
    _seed_so(db, sp, "블랙", "230", 999)
    n = _persist_option_stocks(db, sp.id, [
        {"color": "블랙", "size": "230", "stock": 14},
    ])
    db.commit()
    assert n == 1
    assert _stock(db, sp, "블랙", "230") == 14


def test_999_unknown_is_kept(db):
    """999=수량미상 센티넬은 그대로 유지(있음 표시 보존)."""
    sp = _sp(db)
    _seed_so(db, sp, "블랙", "240", 999)
    _persist_option_stocks(db, sp.id, [
        {"color": "블랙", "size": "240", "stock": 999},
    ])
    db.commit()
    assert _stock(db, sp, "블랙", "240") == 999


def test_none_stock_skipped_preserves_hardreset_null(db):
    """stock=None(수집 실패) → 건너뜀. 크롤시작 하드리셋의 NULL 보존(옛값·폴백 금지)."""
    sp = _sp(db)
    so = _seed_so(db, sp, "올리브그린", "250", None)  # 하드리셋 직후 NULL
    n = _persist_option_stocks(db, sp.id, [
        {"color": "올리브그린", "size": "250", "stock": None},
    ])
    db.commit()
    assert n == 0
    assert _stock(db, sp, "올리브그린", "250") is None


def test_unmatched_option_no_crash_no_change(db):
    """크롤엔 있으나 DB SO 에 없는 조합 → 조용히 건너뜀(생성 안 함·예외 없음)."""
    sp = _sp(db)
    _seed_so(db, sp, "블랙", "220", 999)
    n = _persist_option_stocks(db, sp.id, [
        {"color": "없는색", "size": "999", "stock": 0},
    ])
    db.commit()
    assert n == 0
    assert _stock(db, sp, "블랙", "220") == 999       # 무관 SO 불변


def test_mixed_batch(db):
    """혼합 배치 — 품절·실수량·999·None·미매칭이 섞여도 각자 규칙대로."""
    sp = _sp(db)
    _seed_so(db, sp, "그레이", "255", 999)
    _seed_so(db, sp, "그레이", "260", 999)
    _seed_so(db, sp, "그레이", "265", 999)
    _seed_so(db, sp, "블랙", "230", 999)
    n = _persist_option_stocks(db, sp.id, [
        {"color": "그레이", "size": "255", "stock": 0},     # 품절
        {"color": "그레이", "size": "260", "stock": 0},     # 품절
        {"color": "그레이", "size": "265", "stock": 0},     # 품절
        {"color": "블랙", "size": "230", "stock": 7},       # 실수량
        {"color": "없는색", "size": "300", "stock": 0},     # 미매칭
        {"color": "그레이", "size": "270", "stock": None},  # SO 없음 + None
    ])
    db.commit()
    assert n == 4
    assert _stock(db, sp, "그레이", "255") == 0
    assert _stock(db, sp, "그레이", "260") == 0
    assert _stock(db, sp, "그레이", "265") == 0
    assert _stock(db, sp, "블랙", "230") == 7


def test_empty_options_noop(db):
    sp = _sp(db)
    _seed_so(db, sp, "블랙", "230", 999)
    assert _persist_option_stocks(db, sp.id, []) == 0
    assert _persist_option_stocks(db, sp.id, None) == 0
    assert _stock(db, sp, "블랙", "230") == 999

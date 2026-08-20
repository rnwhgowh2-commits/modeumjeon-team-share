"""[TEST] SourceOption upsert size/color 정규화 — 중복행 방지 (2026-06-24).

배경: upsert_source_option 이 color_text/size_text 를 raw 그대로 조회·저장 →
      '220MM' vs '220mm', ' 235 mm ' vs '235mm' 등 표기 차이로 유니크 제약을
      우회해 중복행이 쌓임. 특히 무신사 단품(SourceProduct) 에서 재발.

정책: 저장 전 _norm_size/_norm_color 로 정규화(lower+trim+숫자→Nmm). 조회 키도
      같은 함수 통과 → 같은 (sp, color, size) 는 항상 1행.
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
from lemouton.sources.service import upsert_source_option, _norm_size, _norm_color


# ─── unit: _norm_size ────────────────────────────────────────────────────────

def test_norm_size():
    assert _norm_size('220MM') == '220mm'
    assert _norm_size('220mm') == '220mm'
    assert _norm_size('220') == '220mm'
    assert _norm_size(' 235 mm ') == '235mm'
    assert _norm_size('') == ''
    assert _norm_size(None) == ''


# ─── unit: _norm_color ───────────────────────────────────────────────────────

def test_norm_color():
    assert _norm_color('  오렌지 ') == '오렌지'
    assert _norm_color(None) == ''


# ─── integration: upsert dedup ───────────────────────────────────────────────

@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_upsert_dedup_case_insensitive_size(db):
    """같은 (sp, color, size) 가 대소문자만 달라도 1행으로 dedup."""
    sp = SourceProduct(site="musinsa", url="https://musinsa.com/products/1")
    db.add(sp)
    db.flush()

    # 첫 번째 upsert: '220MM'
    so1 = upsert_source_option(
        db,
        source_product_id=sp.id,
        color_text='오렌지',
        size_text='220MM',
        current_price=100,
        current_stock=5,
    )
    db.flush()

    # 두 번째 upsert: '220mm' (표기만 다름)
    so2 = upsert_source_option(
        db,
        source_product_id=sp.id,
        color_text='오렌지',
        size_text='220mm',
        current_price=110,
        current_stock=3,
    )
    db.flush()

    # 같은 행 — id 일치
    assert so1.id == so2.id

    # 최신 값으로 갱신됨
    rows = db.query(SourceOption).filter_by(source_product_id=sp.id).all()
    assert len(rows) == 1, f"중복행 발생: {len(rows)}행"
    assert rows[0].current_price == 110
    assert rows[0].current_stock == 3

    # 저장된 size_text 가 정규화 형태
    assert rows[0].size_text == '220mm'
    assert rows[0].color_text == '오렌지'

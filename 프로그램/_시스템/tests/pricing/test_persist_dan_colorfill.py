# -*- coding: utf-8 -*-
"""[TEST] 단품 확장크롤 빈색 → 등록색 채움 (_persist_option_stocks reg_color 방어).

배경(Task 3 TDD):
  무신사 단품 크롤 시 확장이 color='' 로 POST 함(단일색 URL = 색 미포함).
  기존 _match_option_so 는 빈 색 → size_only 로 첫 번째 사이즈 일치 행 반환.
  같은 사이즈에 오렌지+블랙 잔류 오염행이 있으면 어느 행이 갱신될지 비결정적.

정책(방어):
  _persist_option_stocks 호출 전, 호출자가 _resolve_reg_color(s, sp) 로 등록색 취득 →
  reg_color 를 넘겨 빈 color 를 등록색으로 채워 매칭 → 항상 오렌지 행 갱신.
  reg_color=None 이면 기존 동작 유지(size_only fallback).
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
from lemouton.sourcing.models import BundleSourceUrl
from lemouton.sources.service import upsert_source_product, _resolve_reg_color
from webapp.routes.api_pricing import _persist_option_stocks

_SP_URL = "https://www.musinsa.com/products/4800825"


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _make_sp(db):
    sp = upsert_source_product(db, site="musinsa", url=_SP_URL)
    db.commit()
    return sp


def _make_bsu(db, sp, label="musinsa_오렌지"):
    """단품 BundleSourceUrl — 등록색 소스."""
    bsu = BundleSourceUrl(
        model_code="MATE001",   # NOT NULL — 더미값
        source_key="musinsa",   # NOT NULL — 더미값
        url=_SP_URL,
        url_type="단품",
        label=label,
    )
    db.add(bsu)
    db.commit()
    return bsu


def _seed_so(db, sp, color, size, stock=999):
    so = SourceOption(
        source_product_id=sp.id,
        color_text=color,
        size_text=size,
        current_stock=stock,
        current_price=116900,
    )
    db.add(so)
    db.commit()
    return so


def _stock_of(db, sp, color, size):
    so = (db.query(SourceOption)
          .filter_by(source_product_id=sp.id, color_text=color,
                     size_text=size, deleted_at=None).first())
    return so.current_stock if so else "MISSING"


# ─── 핵심 테스트 ──────────────────────────────────────────────────────────────

def test_empty_color_filled_with_reg_color_picks_correct_row(db):
    """빈 color='' 를 등록색 '오렌지' 로 채워 오렌지 225 행만 갱신, 블랙 225 불변.

    구시나리오(오염 상태):
      SourceOption 에 오렌지 225 + 블랙 225 가 공존 (잔류 오염 행).
      확장이 color='' size='225' stock=7 로 POST.

    기대:
      reg_color='오렌지' 주입 → 오렌지 225 가 7 로 갱신.
      블랙 225 는 999 그대로.
    """
    sp = _make_sp(db)
    _make_bsu(db, sp, label="musinsa_오렌지")  # 등록색 '오렌지'
    so_orange = _seed_so(db, sp, "오렌지", "225mm", stock=999)
    so_black = _seed_so(db, sp, "블랙", "225mm", stock=999)

    # _resolve_reg_color 로 등록색 취득
    reg_color = _resolve_reg_color(db, sp)
    assert reg_color == "오렌지", f"등록색 예상=오렌지, 실제={reg_color!r}"

    # reg_color 를 넘겨 persist
    n = _persist_option_stocks(db, sp.id,
                               [{"color": "", "size": "225", "stock": 7}],
                               reg_color=reg_color)
    db.commit()

    assert n == 1, f"갱신 수 예상=1, 실제={n}"
    assert _stock_of(db, sp, "오렌지", "225mm") == 7, "오렌지 225 → 7 이어야 함"
    assert _stock_of(db, sp, "블랙", "225mm") == 999, "블랙 225 → 불변(999) 이어야 함"


def test_no_reg_color_falls_back_to_size_only(db):
    """reg_color=None → 기존 동작(size_only). 오렌지가 첫 번째면 그쪽 갱신.

    reg_color 가 없으면 기존 _match_option_so size_only 경로를 탄다.
    동작 변경 없음을 보장(비단품 소싱처 회귀 방지).
    """
    sp = _make_sp(db)
    # BundleSourceUrl 없음 → _resolve_reg_color 가 None 반환
    _seed_so(db, sp, "오렌지", "225mm", stock=999)

    n = _persist_option_stocks(db, sp.id,
                               [{"color": "", "size": "225", "stock": 3}],
                               reg_color=None)
    db.commit()

    # size_only 경로 → 225mm 를 가진 첫 행(오렌지)이 갱신되거나 매칭됨(단독행이므로 안전)
    assert n == 1
    assert _stock_of(db, sp, "오렌지", "225mm") == 3


def test_explicit_color_in_option_ignores_reg_color(db):
    """color 가 이미 채워진 옵션은 reg_color 와 무관하게 색+사이즈 매칭 우선."""
    sp = _make_sp(db)
    _make_bsu(db, sp, label="musinsa_오렌지")
    _seed_so(db, sp, "오렌지", "230mm", stock=999)
    _seed_so(db, sp, "블랙", "230mm", stock=999)

    reg_color = _resolve_reg_color(db, sp)
    # 명시 color='블랙' → reg_color='오렌지' 여도 블랙 230 갱신
    n = _persist_option_stocks(db, sp.id,
                               [{"color": "블랙", "size": "230", "stock": 2}],
                               reg_color=reg_color)
    db.commit()

    assert n == 1
    assert _stock_of(db, sp, "블랙", "230mm") == 2
    assert _stock_of(db, sp, "오렌지", "230mm") == 999   # 오렌지 불변


def test_reg_color_resolve_none_when_no_bsu(db):
    """BundleSourceUrl 없는 SP → _resolve_reg_color=None → 기존 경로 이상 없음."""
    sp = _make_sp(db)
    # BundleSourceUrl 없이 바로
    _seed_so(db, sp, "그레이", "260mm", stock=999)

    reg_color = _resolve_reg_color(db, sp)
    assert reg_color is None

    n = _persist_option_stocks(db, sp.id,
                               [{"color": "", "size": "260", "stock": 0}],
                               reg_color=None)
    db.commit()
    assert n == 1
    assert _stock_of(db, sp, "그레이", "260mm") == 0

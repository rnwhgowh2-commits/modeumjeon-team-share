# -*- coding: utf-8 -*-
"""[TEST] 3단계 — 매트릭스가 새 판정기(3단 계단)를 쓴다.

설계: docs/사전점검_옵션URL매핑_설계.md §15-C·§15-D, §16 3단계

무엇을 증명하나 (화면에 보이는 값으로)
  1. 되찾음  : 소싱처가 「BLACK」이라 불러도 우리 「블랙」 칸에 **가격이 뜬다**
               (옛 판정은 부분일치라 못 붙어 빈칸이었다)
  2. 되찾음  : 사이즈 「7US」 ↔ 우리 「250」
  3. 오매칭 제거: 소싱처 「오프화이트」가 우리 「화이트」 칸에 **안 붙는다**
               (옛 판정은 붙여서 남의 색 가격을 보여줬다)
  4. 되살리기: 축 매핑에 한 줄 가르치면 3번이 다시 붙는다
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.sourcing.axis_alias",
    "lemouton.matrix.models",   # options.matrix_option_id FK 타겟
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M  # noqa: E402
import lemouton.sources.models as SM  # noqa: E402
from shared.db import Base  # noqa: E402

URL = "https://www.musinsa.com/products/1"


def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.execute(text("PRAGMA foreign_keys=ON"))
    return s


def _seed(s, *, our_color, our_size, src_color, src_size, price=109900):
    """모음전 1개 · 옵션 1개 · 무신사 URL 1개 · 크롤된 소싱처 옵션 1개."""
    s.add(M.Model(model_code="LT", model_name_raw="르무통테스트"))
    sku = f"LT-{our_color}-{our_size}"
    s.add(M.Option(canonical_sku=sku, model_code="LT",
                   color_code=our_color, size_code=our_size, is_active=True))
    s.commit()                      # FK 타겟(Model·Option)을 먼저 확정
    bsu = M.BundleSourceUrl(model_code="LT", source_key="musinsa",
                            url=URL, sort_order=0, url_type="단품")
    s.add(bsu)
    s.commit()
    s.add(M.OptionSourceUrlLink(option_canonical_sku=sku,
                                bundle_source_url_id=bsu.id))
    sp = SM.SourceProduct(site="musinsa", url=URL, last_status="ok")
    s.add(sp)
    s.commit()
    s.add(SM.SourceOption(source_product_id=sp.id, color_text=src_color,
                          size_text=src_size, current_price=price, current_stock=5))
    s.commit()
    return sku


def _cell(s, sku):
    """매트릭스에서 그 옵션의 무신사 칸을 꺼낸다."""
    from unittest.mock import patch

    import webapp.routes.api_pricing as mod
    with patch.object(mod, "SessionLocal", return_value=s):
        out = mod._option_matrix_data("LT")
    assert out.get("ok"), out
    row = next((o for o in out["options"] if o.get("sku") == sku), None)
    assert row is not None, [o.get("sku") for o in out["options"]]
    ent = next((e for e in row.get("sources", []) if e.get("source_key") == "musinsa"), None)
    assert ent is not None, row.get("sources")
    return ent


# ── 되찾음 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("src_color,our_color", [
    ("BLACK", "블랙"),
    ("블랙", "검정"),
    ("Dark Navy", "다크네이비"),
])
def test_color_dictionary_now_shows_price(src_color, our_color):
    """소싱처가 영문·동의어로 불러도 우리 칸에 가격이 뜬다."""
    s = _db()
    sku = _seed(s, our_color=our_color, our_size="250",
                src_color=src_color, src_size="250")
    ent = _cell(s, sku)
    assert ent.get("crawled_price") == 109900
    assert ent.get("match_failed") is not True


def test_us_size_now_shows_price():
    """사이즈 「7US」 ↔ 우리 「250」."""
    s = _db()
    sku = _seed(s, our_color="블랙", our_size="250",
                src_color="블랙", src_size="7US")
    ent = _cell(s, sku)
    assert ent.get("crawled_price") == 109900


# ── 오매칭 제거 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("src_color,our_color", [
    ("오프화이트", "화이트"),
    ("네이비", "다크네이비"),
])
def test_partial_match_no_longer_borrows_other_color_price(src_color, our_color):
    """남의 색 가격을 가져다 쓰지 않는다 — 값 없이 「매칭 실패」로 표면화."""
    s = _db()
    sku = _seed(s, our_color=our_color, our_size="250",
                src_color=src_color, src_size="250")
    ent = _cell(s, sku)
    assert ent.get("crawled_price") is None
    assert ent.get("match_failed") is True


# ── 가르치면 되살아난다 ─────────────────────────────────────────────────

def test_teaching_axis_alias_restores_the_cell():
    """「화이트 = 오프화이트」라고 한 줄 가르치면 그 칸이 다시 채워진다."""
    from lemouton.sourcing import axis_alias as ax
    s = _db()
    sku = _seed(s, our_color="화이트", our_size="250",
                src_color="오프화이트", src_size="250")
    assert _cell(s, sku).get("crawled_price") is None

    ax.set_alias(s, source_key="musinsa", axis_name="색상",
                 our_value="화이트", source_value="오프화이트")
    s.commit()

    ent = _cell(s, sku)
    assert ent.get("crawled_price") == 109900
    assert ent.get("match_failed") is not True


# ── 안 건드린 것 ────────────────────────────────────────────────────────

def test_exact_match_still_works():
    """원래 붙던 정확 일치는 그대로 붙는다."""
    s = _db()
    sku = _seed(s, our_color="블랙", our_size="250",
                src_color="블랙", src_size="250")
    assert _cell(s, sku).get("crawled_price") == 109900


def test_single_color_url_size_only_still_works():
    """단품 URL(크롤 색 없음) — 사이즈만으로 붙던 것 유지."""
    s = _db()
    sku = _seed(s, our_color="다크네이비", our_size="250",
                src_color="", src_size="250")
    assert _cell(s, sku).get("crawled_price") == 109900

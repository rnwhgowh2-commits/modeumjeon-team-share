# -*- coding: utf-8 -*-
"""[TEST] 단품 주소는 색을 맞출 게 없다 — 색 축에 끼어들지 않는다.

사장님 확정 (2026-08-02):
  「어차피 단품이면 색 맵핑할 필요 없을 것 같아. 사이즈만 맵핑하면 될 듯해.
   색상모음전·모델모음전의 경우 소싱처 URL의 옵션을 그대로 불러와서 맵핑 가능한지가 중요해.」

왜 그런가
  단품 주소는 **URL 하나 = 색 하나**다. 어느 색인지는 주소를 등록할 때 이미 정해졌으니
  맞출 것이 없다. 그런데 억지로 색을 맞추려다 **주소 라벨(사람이 적은 이름)을 소싱처가 준
  사실처럼** 써버렸다 — 라벨 「무신사_화이트」의 실물은 「클래식 2 블랙(화이트 아웃솔)」이었다.

  라이브 실측: DB 에 저장된 색 4개(다크네이비·화이트·베이지·블랙)와 무신사 실제 상품명
  4개가 **하나도 겹치지 않았다.** 그런데 화면은 「자동 4 · 전부 초록」이라고 했다.

바로잡음
  색 후보는 **색상모음전·모델모음전 주소에서만** 모은다. 단품 주소는 **사이즈만** 기여한다.
  단품만 있는 소싱처는 색 축을 「맞출 것 없음」으로 접는다.
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
    "lemouton.matrix.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M  # noqa: E402
import lemouton.sources.models as SM  # noqa: E402
from shared.db import Base  # noqa: E402

U_DAN = "https://www.musinsa.com/products/1"     # 단품 (라벨 색이 DB 에 박혀 있는 상태)
U_BUNDLE = "https://www.musinsa.com/products/2"  # 색상모음전
AXES = [{"axis_name": "색상", "values": ["화이트", "블랙"]},
        {"axis_name": "사이즈", "values": ["250", "260"]}]


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.execute(text("PRAGMA foreign_keys=ON"))
    s.add(M.Model(model_code="LT", model_name_raw="르무통테스트"))
    s.commit()
    # 단품 — 옛 크롤이 라벨 색('화이트')을 박아 둔 상태를 재현
    sp1 = SM.SourceProduct(site="musinsa", url=U_DAN, last_status="ok",
                           product_name="클래식 2 블랙(화이트 아웃솔)")
    s.add(sp1)
    s.commit()
    for z in ("250", "260"):
        s.add(SM.SourceOption(source_product_id=sp1.id, color_text="화이트",
                              size_text=z, current_price=119900, current_stock=3))
    # 색상모음전 — 소싱처가 준 진짜 색
    sp2 = SM.SourceProduct(site="musinsa", url=U_BUNDLE, last_status="ok",
                           product_name="르무통 메이트")
    s.add(sp2)
    s.commit()
    for c in ("블랙", "아이보리"):
        s.add(SM.SourceOption(source_product_id=sp2.id, color_text=c,
                              size_text="250", current_price=119900, current_stock=3))
    s.commit()

    import pathlib
    from unittest.mock import patch

    from flask import Flask
    from webapp.routes import bundles as b
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(b.__file__).parents[2].as_posix())
    app.register_blueprint(b.bp)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=True)
    with patch.object(b, "SessionLocal", return_value=s):
        yield app.test_client()
    s.close()


def _preview(c, items):
    return c.post("/api/bundles/LT/axis-mapping/preview",
                  json={"source_key": "musinsa", "url_items": items,
                        "axes": AXES}).get_json()


def test_dan_only_source_has_no_color_axis(env):
    """단품만 있는 소싱처 — 색 축은 「맞출 것 없음」으로 접힌다."""
    d = _preview(env, [{"url": U_DAN, "url_type": "단품", "label": "무신사_화이트"}])
    color = d["axes"][0]
    assert color["available"] is False
    assert "단품" in color["reason"]
    assert color["source_values"] == []


def test_collapsed_axis_is_not_counted_as_not_found(env):
    """접힌 축은 「못 찾음」이 아니다 — 맞출 것이 없는 것이다.

    라이브에서 「못 찾음 4」로 떠서 사장님이 「4개를 못 찾았구나」로 오해했다.
    실제로는 단품이라 색을 맞출 필요가 없는 것이고, 못 찾은 것은 0개다.
    """
    d = _preview(env, [{"url": U_DAN, "url_type": "단품", "label": "무신사_화이트"}])
    color = d["axes"][0]
    assert color["available"] is False
    assert color["summary"]["none"] == 0        # 못 찾음으로 세지 않는다
    assert d["summary"]["none"] == 0


def test_dan_still_contributes_sizes(env):
    """단품이어도 사이즈는 맞춘다 — 그건 필요하다."""
    d = _preview(env, [{"url": U_DAN, "url_type": "단품", "label": "무신사_화이트"}])
    size = d["axes"][1]
    assert size["available"] is True
    rows = {r["our_value"]: r["source_value"] for r in size["rows"]}
    assert rows == {"250": "250", "260": "260"}


def test_dan_label_color_no_longer_leaks(env):
    """단품에 박혀 있던 라벨 색('화이트')이 후보로 새지 않는다."""
    d = _preview(env, [{"url": U_DAN, "url_type": "단품", "label": "무신사_화이트"}])
    assert "화이트" not in d["axes"][0]["source_values"]


def test_bundle_url_gives_real_colors(env):
    """색상모음전 — 소싱처가 준 색이 그대로 후보가 된다."""
    d = _preview(env, [{"url": U_BUNDLE, "url_type": "색상모음전"}])
    color = d["axes"][0]
    assert color["available"] is True
    assert set(color["source_values"]) == {"블랙", "아이보리"}
    rows = {r["our_value"]: r["source_value"] for r in color["rows"]}
    assert rows["블랙"] == "블랙"
    assert rows["화이트"] is None       # 이 상품엔 화이트가 없다 — 없는 게 정답


def test_mixed_source_uses_only_bundle_colors(env):
    """단품 + 색상모음전 섞여 있으면 색은 모음전 것만 쓴다."""
    d = _preview(env, [{"url": U_DAN, "url_type": "단품", "label": "무신사_화이트"},
                       {"url": U_BUNDLE, "url_type": "색상모음전"}])
    color = d["axes"][0]
    assert color["available"] is True
    assert set(color["source_values"]) == {"블랙", "아이보리"}
    assert "화이트" not in color["source_values"]
    # 사이즈는 둘 다 기여
    assert set(d["axes"][1]["source_values"]) >= {"250", "260"}


def test_missing_url_type_defaults_to_dan(env):
    """유형을 안 주면 단품으로 본다 (기존 데이터 기본값과 같음)."""
    d = _preview(env, [{"url": U_DAN}])
    assert d["axes"][0]["available"] is False

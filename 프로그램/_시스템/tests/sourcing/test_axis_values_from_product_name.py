# -*- coding: utf-8 -*-
"""[TEST] 색을 안 주는 주소 — 후보는 **소싱처가 준 상품명**이어야 한다.

라이브에서 잡힌 오류 (2026-08-02):
  앞선 고침은 색이 빈 옵션을 **주소 라벨**(`무신사_화이트`)로 채웠다. 그런데 라벨은
  **사장님이 손으로 적은 이름**이지 소싱처가 준 사실이 아니다. 실제 무신사 상품은
  「클래식 2 블랙(화이트 아웃솔)」이고 화이트라는 색은 팔지 않는다.
  → 라벨로 채우면 「내가 적은 걸 내가 확인해주는」 순환이 되어, 없는 색을 있다고 말한다.

바로잡음
  색이 빈 옵션의 후보 = **크롤이 가져온 상품명**(SourceProduct.product_name).
  그게 소싱처가 실제로 부르는 이름이다. 라벨은 쓰지 않는다.
  우리 값과 자동으로 안 붙는 게 정상이고, 사장님이 드롭다운에서 고르면 사전에 쌓인다.
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

U_WHITE = "https://www.musinsa.com/products/3728431"   # 라벨 '무신사_화이트'
NAME_WHITE = "르무통(LEMOUTON) 클래식 2 블랙(화이트 아웃솔)"   # 소싱처 실제 상품명
U_MULTI = "https://www.musinsa.com/products/9"          # 색을 주는 주소
AXES = [{"axis_name": "색상", "values": ["화이트", "블랙"]},
        {"axis_name": "사이즈", "values": ["250"]}]


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.execute(text("PRAGMA foreign_keys=ON"))
    s.add(M.Model(model_code="LT", model_name_raw="르무통테스트"))
    s.commit()

    sp1 = SM.SourceProduct(site="musinsa", url=U_WHITE, last_status="ok",
                           product_name=NAME_WHITE)
    s.add(sp1)
    s.commit()
    s.add(SM.SourceOption(source_product_id=sp1.id, color_text="", size_text="250",
                          current_price=119900, current_stock=3))
    sp2 = SM.SourceProduct(site="musinsa", url=U_MULTI, last_status="ok",
                           product_name="르무통 클래식 2 모음")
    s.add(sp2)
    s.commit()
    s.add(SM.SourceOption(source_product_id=sp2.id, color_text="블랙", size_text="250",
                          current_price=119900, current_stock=3))
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
        yield app.test_client(), s
    s.close()


def _preview(c, items):
    return c.post("/api/bundles/LT/axis-mapping/preview",
                  json={"source_key": "musinsa", "url_items": items,
                        "axes": AXES}).get_json()


def test_candidate_is_the_crawled_product_name(env):
    """색을 안 주는 주소 → 후보는 소싱처가 준 **상품명**."""
    c, _s = env
    d = _preview(c, [{"url": U_WHITE, "label": "무신사_화이트"}])
    vals = d["axes"][0]["source_values"]
    assert NAME_WHITE in vals


def test_label_is_not_used_as_a_color(env):
    """라벨(사람이 적은 이름)을 색으로 쓰지 않는다 — 없는 색을 있다고 하면 안 된다."""
    c, _s = env
    d = _preview(c, [{"url": U_WHITE, "label": "무신사_화이트"}])
    vals = d["axes"][0]["source_values"]
    assert "화이트" not in vals                      # 라벨 유래 값이 없어야
    rows = {r["our_value"]: r for r in d["axes"][0]["rows"]}
    assert rows["화이트"]["source_value"] is None     # 자동으로 안 붙는 게 정상
    assert rows["화이트"]["status"] in ("review", "none")


def test_user_can_pick_the_product_name_from_candidates(env):
    """사장님이 고를 수 있게 후보 목록에 들어 있어야 한다."""
    c, _s = env
    d = _preview(c, [{"url": U_WHITE, "label": "무신사_화이트"}])
    rows = {r["our_value"]: r for r in d["axes"][0]["rows"]}
    assert NAME_WHITE in (rows["화이트"]["candidates"] or d["axes"][0]["source_values"])


def test_crawled_color_still_wins(env):
    """크롤이 색을 준 주소는 그 색이 후보 — 상품명으로 대체하지 않는다."""
    c, _s = env
    d = _preview(c, [{"url": U_MULTI, "label": "무신사_모음"}])
    vals = d["axes"][0]["source_values"]
    assert vals == ["블랙"]


def test_no_product_name_means_no_candidate(env):
    """상품명도 없으면 지어내지 않는다 — 「모른다」가 정답."""
    c, s = env
    sp = s.query(SM.SourceProduct).filter_by(url=U_WHITE).first()
    sp.product_name = None
    s.commit()
    d = _preview(c, [{"url": U_WHITE, "label": "무신사_화이트"}])
    assert d["axes"][0]["source_values"] == []

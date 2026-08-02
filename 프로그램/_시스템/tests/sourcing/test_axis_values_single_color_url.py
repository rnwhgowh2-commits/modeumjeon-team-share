# -*- coding: utf-8 -*-
"""[TEST] 단품 주소의 색이 축 후보에서 빠지던 것.

라이브에서 발견 (2026-08-02 · U20260802-000177 · 무신사):
  매트릭스는 「다크네이비 250 = 119,900 · 매칭 성공」인데
  축 맞추기는 「다크네이비 = 소싱처에 없음」이라고 했다. **같은 데이터, 다른 답.**

왜
  단품 주소(무신사 색상별 페이지)는 **색을 안 준다.** 사이즈만 주고 색은 주소 라벨
  (`무신사_다크네이비`)에만 있다. 매트릭스는 「크롤 색이 비면 사이즈만으로 붙인다」는
  규칙이 있어 통과했는데, 축 값 목록은 color_text 가 빈 옵션을 그냥 빼버려
  그 색이 후보에 아예 안 떴다.

고침
  축 값을 모을 때, 색이 빈 옵션은 **그 주소 라벨에서 색을 보강**한다
  (서버 크롤러의 `_label_color` 와 같은 규칙 — `무신사_다크네이비` → `다크네이비`).
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

DN = "https://www.musinsa.com/products/3728480"   # 무신사_다크네이비 (단품 = 색 안 줌)
BK = "https://www.musinsa.com/products/3728475"   # 무신사_블랙 (색 줌)
AXES = [{"axis_name": "색상", "values": ["블랙", "다크네이비"]},
        {"axis_name": "사이즈", "values": ["250"]}]


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.execute(text("PRAGMA foreign_keys=ON"))
    s.add(M.Model(model_code="LT", model_name_raw="르무통테스트"))
    s.commit()
    for url, color in ((DN, ""), (BK, "블랙")):     # 단품(색 없음) + 색 주는 주소
        sp = SM.SourceProduct(site="musinsa", url=url, last_status="ok")
        s.add(sp)
        s.commit()
        s.add(SM.SourceOption(source_product_id=sp.id, color_text=color,
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


def _preview(c, url_items):
    return c.post("/api/bundles/LT/axis-mapping/preview",
                  json={"source_key": "musinsa", "url_items": url_items,
                        "axes": AXES}).get_json()


def test_single_color_url_color_comes_from_label(env):
    """색을 안 주는 단품 주소도, 라벨의 색이 축 후보로 올라온다."""
    d = _preview(env, [{"url": DN, "label": "무신사_다크네이비"},
                       {"url": BK, "label": "무신사_블랙"}])
    color = d["axes"][0]
    assert "다크네이비" in color["source_values"]
    rows = {r["our_value"]: r for r in color["rows"]}
    assert rows["다크네이비"]["source_value"] == "다크네이비"
    assert rows["다크네이비"]["status"] == "auto"
    assert rows["블랙"]["source_value"] == "블랙"


def test_label_without_underscore_is_ignored(env):
    """라벨 규칙(소싱처_색)이 아니면 색을 지어내지 않는다 — 날조 금지."""
    d = _preview(env, [{"url": DN, "label": "그냥라벨"},
                       {"url": BK, "label": "무신사_블랙"}])
    color = d["axes"][0]
    assert "다크네이비" not in color["source_values"]
    rows = {r["our_value"]: r for r in color["rows"]}
    assert rows["다크네이비"]["source_value"] is None


def test_label_color_does_not_override_crawled_color(env):
    """크롤이 준 색이 있으면 그게 우선 — 라벨이 덮어쓰지 않는다."""
    d = _preview(env, [{"url": BK, "label": "무신사_다크네이비"}])   # 라벨은 다크네이비, 크롤은 블랙
    vals = d["axes"][0]["source_values"]
    assert "블랙" in vals
    assert "다크네이비" not in vals


def test_plain_urls_still_work(env):
    """옛 형식(urls: [str]) 도 계속 받는다 — 라벨이 없으면 보강만 못 할 뿐."""
    d = env.post("/api/bundles/LT/axis-mapping/preview",
                 json={"source_key": "musinsa", "urls": [DN, BK], "axes": AXES}).get_json()
    assert d["ok"] is True
    assert "블랙" in d["axes"][0]["source_values"]
    assert d["crawled_urls"] == 2

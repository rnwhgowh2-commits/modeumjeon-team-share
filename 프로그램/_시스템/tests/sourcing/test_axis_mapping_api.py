# -*- coding: utf-8 -*-
"""[TEST] 5단계 — 축 맞추기 화면이 쓸 조회·저장 API.

설계: docs/사전점검_옵션URL매핑_설계.md §15·§16 5단계

두 개
  POST /api/bundles/<code>/axis-mapping/preview
      화면의 **미저장** 축 설계 + URL 목록을 받아, 축마다 「우리 값 → 소싱처 표기」 제안을 돌려준다.
      저장 전에도 되어야 한다 — 그게 이 기능의 존재 이유다.
  POST /api/bundles/<code>/axis-mapping
      한 줄 맞추기 / 되돌리기. 1:1 위반이면 누가 쓰는지 알려주며 막는다.
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

URL = "https://www.musinsa.com/products/1"
AXES = [
    {"axis_name": "색상", "values": ["검정", "화이트", "블랙&화이트"]},
    {"axis_name": "사이즈", "values": ["250", "260"]},
]


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.execute(text("PRAGMA foreign_keys=ON"))
    s.add(M.Model(model_code="LT", model_name_raw="르무통테스트"))
    s.commit()
    sp = SM.SourceProduct(site="musinsa", url=URL, last_status="ok")
    s.add(sp)
    s.commit()
    for c, z in (("BLACK", "250"), ("BLACK", "260"),
                 ("WHITE", "250"), ("BLACK & WHITE", "250")):
        s.add(SM.SourceOption(source_product_id=sp.id, color_text=c,
                              size_text=z, current_price=109900, current_stock=3))
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


# ── 미리보기 ────────────────────────────────────────────────────────────

def test_preview_suggests_per_axis(env):
    c, _s = env
    r = c.post("/api/bundles/LT/axis-mapping/preview",
               json={"source_key": "musinsa",
                     "url_items": [{"url": URL, "url_type": "색상모음전"}],
                     "axes": AXES})
    assert r.status_code == 200, r.data
    d = r.get_json()
    assert d["ok"] is True
    by_axis = {a["axis_name"]: a for a in d["axes"]}

    color = {x["our_value"]: x for x in by_axis["색상"]["rows"]}
    assert color["검정"]["source_value"] == "BLACK"       # 사전
    assert color["화이트"]["source_value"] == "WHITE"
    assert color["블랙&화이트"]["source_value"] is None    # 사람이 골라야
    assert color["블랙&화이트"]["status"] in ("review", "none")

    size = {x["our_value"]: x for x in by_axis["사이즈"]["rows"]}
    assert size["250"]["source_value"] == "250"
    assert size["260"]["source_value"] == "260"


def test_preview_reports_source_values_and_uncrawled(env):
    c, _s = env
    r = c.post("/api/bundles/LT/axis-mapping/preview",
               json={"source_key": "musinsa",
                     "url_items": [{"url": URL, "url_type": "색상모음전"},
                                   {"url": "https://www.musinsa.com/products/999",
                                    "url_type": "색상모음전"}],
                     "axes": AXES})
    d = r.get_json()
    by_axis = {a["axis_name"]: a for a in d["axes"]}
    assert set(by_axis["색상"]["source_values"]) == {"BLACK", "WHITE", "BLACK & WHITE"}
    assert d["uncrawled_urls"] == ["https://www.musinsa.com/products/999"]
    assert d["crawled_urls"] == 1


def test_preview_third_axis_is_marked_unavailable(env):
    """모델 축은 아직 소싱처에서 회수하지 않는다 — 조용히 비우지 말고 이유를 말한다."""
    c, _s = env
    axes = AXES + [{"axis_name": "모델", "values": ["클래식", "메이트"]}]
    r = c.post("/api/bundles/LT/axis-mapping/preview",
               json={"source_key": "musinsa",
                     "url_items": [{"url": URL, "url_type": "색상모음전"}],
                     "axes": axes})
    model_axis = next(a for a in r.get_json()["axes"] if a["axis_name"] == "모델")
    assert model_axis["available"] is False
    assert model_axis["reason"]
    assert all(x["status"] == "none" for x in model_axis["rows"])


def test_preview_works_before_save(env):
    """URL 이 bundle_source_urls 에 없어도 된다 — 저장 전에 쓰는 기능이다."""
    c, s = env
    assert s.query(M.BundleSourceUrl).count() == 0
    r = c.post("/api/bundles/LT/axis-mapping/preview",
               json={"source_key": "musinsa",
                     "url_items": [{"url": URL, "url_type": "색상모음전"}],
                     "axes": AXES})
    assert r.get_json()["axes"][0]["summary"]["auto"] == 2


# ── 저장 ────────────────────────────────────────────────────────────────

def test_set_alias_then_preview_marks_saved(env):
    c, _s = env
    r = c.post("/api/bundles/LT/axis-mapping",
               json={"source_key": "musinsa", "axis_name": "색상",
                     "our_value": "블랙&화이트", "source_value": "BLACK & WHITE"})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    d = c.post("/api/bundles/LT/axis-mapping/preview",
               json={"source_key": "musinsa",
                     "url_items": [{"url": URL, "url_type": "색상모음전"}],
                     "axes": AXES}).get_json()
    row = next(x for x in d["axes"][0]["rows"] if x["our_value"] == "블랙&화이트")
    assert (row["status"], row["origin"], row["source_value"]) == (
        "saved", "manual", "BLACK & WHITE")


def test_conflict_is_rejected_with_owner_name(env):
    c, _s = env
    c.post("/api/bundles/LT/axis-mapping",
           json={"source_key": "musinsa", "axis_name": "색상",
                 "our_value": "검정", "source_value": "BLACK"})
    r = c.post("/api/bundles/LT/axis-mapping",
               json={"source_key": "musinsa", "axis_name": "색상",
                     "our_value": "화이트", "source_value": "BLACK"})
    assert r.status_code == 409
    assert "검정" in r.get_json()["error"]


def test_reset_gives_it_back_to_the_dictionary(env):
    """↩ 자동으로 되돌리기 — 내 지정을 거두고 사전에 다시 맡긴다."""
    c, _s = env
    c.post("/api/bundles/LT/axis-mapping",
           json={"source_key": "musinsa", "axis_name": "색상",
                 "our_value": "검정", "source_value": "BLACK"})
    r = c.post("/api/bundles/LT/axis-mapping",
               json={"source_key": "musinsa", "axis_name": "색상",
                     "our_value": "검정", "reset": True})
    assert r.status_code == 200 and r.get_json()["cleared"] is True


def test_blank_means_absent_not_clear(env):
    """빈 값 = 「이 소싱처엔 없음」으로 **정함** (사전이 다시 못 붙인다)."""
    c, _s = env
    r = c.post("/api/bundles/LT/axis-mapping",
               json={"source_key": "musinsa", "axis_name": "색상",
                     "our_value": "검정", "source_value": None})
    assert r.status_code == 200 and r.get_json()["absent"] is True

    d = c.post("/api/bundles/LT/axis-mapping/preview",
               json={"source_key": "musinsa",
                     "url_items": [{"url": URL, "url_type": "색상모음전"}],
                     "axes": AXES}).get_json()
    row = next(x for x in d["axes"][0]["rows"] if x["our_value"] == "검정")
    assert row["status"] == "absent" and row["source_value"] is None


def test_bad_request_is_rejected(env):
    c, _s = env
    r = c.post("/api/bundles/LT/axis-mapping",
               json={"source_key": "", "axis_name": "색상",
                     "our_value": "검정", "source_value": "BLACK"})
    assert r.status_code == 400

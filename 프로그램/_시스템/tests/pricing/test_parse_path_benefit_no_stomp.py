# -*- coding: utf-8 -*-
"""[TEST] Task 10 — parse 소싱처 혜택: crawl-result 무(無)스톰프 + 확장 전달 필드 영속.

배경(Case A 실측): parse 소싱처(lemouton·ssf·ssg·ss_lemouton·hmall·lotteimall)는
  /api/sources/parse 가 혜택을 서버측 영속하고(api_sources_parse.py:75·:86),
  그 뒤 확장이 POST /api/sources/crawl-result(혜택 키 없는 구버전 payload)를 보낸다.
  이때 parse 가 방금 저장한 dynamic_benefits_json 을 지우면 안 된다(스톰프 금지):
    - 옵션 레벨: service.py persist_crawled_options `_dyn or None`(:747) →
      upsert_source_option `if dynamic_benefits_json is not None`(:195-196) = 보존.
    - 상품 레벨: api_pricing.py save_crawl_result `if _pdyn:`(:1797) = 키 있을 때만 기록.
  이 테스트가 그 보존(preserve-on-absent) 시맨틱을 잠근다 — 무너지면 SSG·SSF 혜택이
  매 크롤마다 소실 = 매입가 과대(금전 손실).

또한 확장 v0.7.56 이 BENEFIT_PASSTHROUGH 로 실어 보내는 새 payload(옵션 레벨 +
  item 레벨) 를 서버가 실제 영속하는지 end-to-end 로 잠근다(hmall 은 per-size 교체로
  options 에 혜택이 없어 item 레벨 전달이 유일한 경로).
"""
import json
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import patch
from flask import Flask

os.environ.setdefault("ENVIRONMENT", "test")

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

import lemouton.sourcing.models as M
from lemouton.sources.models import SourceProduct, SourceOption
from lemouton.sources.service import (
    upsert_source_product, upsert_source_option)
from shared.db import Base

SSF_URL = "https://www.ssfshop.com/LEMOUTON/GM0024031234567/good"


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    seed = Session(eng)
    seed.add(M.Model(model_code="SF", model_name_raw="SSF테스트"))
    seed.commit()
    upsert_source_product(seed, site="ssf", url=SSF_URL)
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as _mod
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client(), eng


def _seed_parse_persisted_benefits(eng):
    """parse 시점 영속을 재현 — 상품·옵션 레벨 dynamic_benefits_json 채움."""
    s = Session(eng)
    try:
        sp = s.query(SourceProduct).filter_by(site="ssf").first()
        assert sp is not None
        sp.dynamic_benefits_json = json.dumps(
            {"point_rate": 0.05, "gift_point_amount": 3000}, ensure_ascii=False)
        upsert_source_option(
            s, source_product_id=sp.id, color_text="블랙", size_text="260mm",
            current_price=100000, current_stock=5,
            dynamic_benefits_json=json.dumps(
                {"point_rate": 0.05, "auto_card_discount": 2730},
                ensure_ascii=False))
        s.commit()
        return sp.id
    finally:
        s.close()


def _post(client, item_extra=None, options=None):
    item = {"url": SSF_URL, "price": 100000, "stock": 999, "status": "ok",
            "product_name": "SSF 상품",
            "options": options if options is not None else [
                {"color": "블랙", "size": "260", "stock": 5, "price": 100000}]}
    item.update(item_extra or {})
    return client.post("/api/sources/crawl-result", json={"items": [item]})


def test_product_level_benefits_survive_benefitless_crawl_result(env):
    """[무스톰프 핀] parse 가 저장한 상품 혜택 → 혜택 키 없는 crawl-result 후에도 보존."""
    client, eng = env
    _seed_parse_persisted_benefits(eng)
    r = _post(client)   # 구버전 확장 payload(혜택 키 없음)
    assert r.status_code == 200, r.get_data(as_text=True)
    q = Session(eng)
    try:
        sp = q.query(SourceProduct).filter_by(site="ssf").first()
        assert sp.dynamic_benefits_json, "상품 혜택 JSON 이 crawl-result 로 지워짐(스톰프)"
        dyn = json.loads(sp.dynamic_benefits_json)
        assert dyn.get("point_rate") == 0.05
        assert dyn.get("gift_point_amount") == 3000
    finally:
        q.close()


def test_option_level_benefits_survive_benefitless_crawl_result(env):
    """[무스톰프 핀] parse 가 저장한 옵션 혜택 → 같은 (색,사이즈) 재-upsert 에도 보존.

    persist_crawled_options 가 _dyn 빈 dict 를 '{}'(덮어씀)이 아닌 None(보존)으로
    넘기는지 잠근다(service.py:747·:774-777 + upsert:195-196).
    """
    client, eng = env
    _seed_parse_persisted_benefits(eng)
    r = _post(client)   # 같은 옵션, 혜택 키 없음
    assert r.status_code == 200, r.get_data(as_text=True)
    q = Session(eng)
    try:
        so = (q.query(SourceOption)
              .filter_by(color_text="블랙", size_text="260mm", deleted_at=None).first())
        assert so is not None, "옵션행이 prune 됨(같은 키인데 소실)"
        assert so.dynamic_benefits_json, "옵션 혜택 JSON 이 crawl-result 로 지워짐(스톰프)"
        dyn = json.loads(so.dynamic_benefits_json)
        assert dyn.get("point_rate") == 0.05
        assert dyn.get("auto_card_discount") == 2730
    finally:
        q.close()


def test_forwarded_option_benefits_persist_both_levels(env):
    """[확장 v0.7.56 payload] 옵션 dict 에 실린 혜택 키 → 옵션+상품 레벨 모두 영속.

    auto_card_discount 는 옵션 전용(PRODUCT_DYNAMIC_KEYS 제외) — 옵션 레벨에만 저장.
    """
    client, eng = env
    r = _post(client, options=[
        {"color": "블랙", "size": "260", "stock": 5, "price": 100000,
         "point_rate": 0.05, "gift_point_amount": 3000, "auto_card_discount": 2730},
    ])
    assert r.status_code == 200, r.get_data(as_text=True)
    q = Session(eng)
    try:
        so = (q.query(SourceOption)
              .filter_by(color_text="블랙", size_text="260mm", deleted_at=None).first())
        assert so is not None and so.dynamic_benefits_json
        odyn = json.loads(so.dynamic_benefits_json)
        assert odyn.get("point_rate") == 0.05
        assert odyn.get("gift_point_amount") == 3000
        assert odyn.get("auto_card_discount") == 2730
        sp = q.query(SourceProduct).filter_by(site="ssf").first()
        assert sp.dynamic_benefits_json, "상품 레벨 미영속(첫 크롤 신규 URL 갭 G1 재발)"
        pdyn = json.loads(sp.dynamic_benefits_json)
        assert pdyn.get("point_rate") == 0.05
        assert "auto_card_discount" not in pdyn, "옵션 전용 키가 상품 레벨로 새 나감"
    finally:
        q.close()


def test_extension_passthrough_list_matches_server_whitelist():
    """[드리프트 핀] 확장 BENEFIT_PASSTHROUGH ⊆ 서버 OPTION_DYNAMIC_KEYS.

    확장이 실어 보내는 키를 서버 화이트리스트가 모르면 조용히 버려진다(무결성 위반).
    background.js 를 정적 파싱해 목록을 대조 — 서버 키 추가/삭제 시 여기서 잡힌다.
    """
    import re
    from pathlib import Path
    from lemouton.sources.service import OPTION_DYNAMIC_KEYS
    bg = (Path(__file__).resolve().parents[2]
          / "extension" / "moum-crawler" / "background.js").read_text(encoding="utf-8")
    m = re.search(r"const BENEFIT_PASSTHROUGH = \[(.*?)\];", bg, re.S)
    assert m, "background.js 에 BENEFIT_PASSTHROUGH 정의가 없음"
    ext_keys = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert ext_keys, "BENEFIT_PASSTHROUGH 파싱 실패"
    unknown = ext_keys - set(OPTION_DYNAMIC_KEYS)
    assert not unknown, f"서버 화이트리스트에 없는 키(조용히 버려짐): {unknown}"
    # parse 6소싱처 대표 키가 실제로 포함되는지(실수 삭제 방지)
    for k in ("point_rate", "gift_point_amount", "ssg_money_rate", "card_benefit_price",
              "hmall_point_amount", "lotteimall_card_discount", "point_rewards",
              "review_point_max", "auto_card_discount"):
        assert k in ext_keys, k


def test_forwarded_item_level_benefits_persist_product(env):
    """[확장 v0.7.56 payload] item 레벨 혜택 키(hmall 패턴 — per-size 교체로 options 엔
    혜택 없음) → save_crawl_result 의 [it]+options 스캔이 집어 상품 레벨 영속."""
    client, eng = env
    r = _post(client, item_extra={"point_rate": 0.05, "gift_point_amount": 3000})
    assert r.status_code == 200, r.get_data(as_text=True)
    q = Session(eng)
    try:
        sp = q.query(SourceProduct).filter_by(site="ssf").first()
        assert sp.dynamic_benefits_json, "item 레벨 혜택 키가 상품 레벨로 영속 안 됨"
        dyn = json.loads(sp.dynamic_benefits_json)
        assert dyn.get("point_rate") == 0.05
        assert dyn.get("gift_point_amount") == 3000
    finally:
        q.close()

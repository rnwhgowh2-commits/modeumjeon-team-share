# -*- coding: utf-8 -*-
"""재고관리 결함 4건 회귀 시험 (2026-08-06 전수 검증에서 나온 것).

① 복사·일괄생성이 구형식 SKU 를 바코드 없이 발급 → 라벨 못 찍고 미매핑으로 쌓임
② 제품목록 부제에 색상이 없어 색만 다른 옵션이 같은 줄로 보임
③ 승격(모음전 일괄 등록) 후 빈 「단독_」 모델이 유령으로 남음
④ 축이 하나면 스마트스토어 옵션명이 「블랙 / 」 로 꼬리가 남음
"""
import io
import os
import pathlib

import pytest

_시스템 = pathlib.Path(__file__).resolve().parents[1]


# ── ④ 옵션명 꼬리 (순수 함수 — DB 불필요) ──────────────────────────────────

def _ss_option_names(decisions):
    from lemouton.formatter.smartstore import build_smartstore_payload
    payload = build_smartstore_payload(
        decisions, {"naver_product_id": 1, "model_name_display": "M"},
        {d["canonical_sku"]: 1 for d in decisions})
    return [o["option_name"] for o in payload["options"]]


def _d(sku, color, size):
    return {"canonical_sku": sku, "naver_option_id": 1,
            "color_display": color, "size_display": size,
            "ss": {"displayed": True, "price": 10000}}


def test_축이_하나면_옵션명에_꼬리가_안_남는다():
    assert _ss_option_names([_d("S1", "블랙", "")]) == ["블랙"]


def test_색상이_비어도_슬래시가_안_남는다():
    assert _ss_option_names([_d("S1", "", "250")]) == ["250"]


def test_두_축이면_기존대로_이어_붙인다():
    assert _ss_option_names([_d("S1", "블랙", "250")]) == ["블랙 / 250"]


# ── ② 제품목록 부제에 색상 (템플릿 문자열 고정) ───────────────────────────

def test_제품목록_부제_조립에_색상이_들어간다():
    """서버 렌더·라이브검색 JS 양쪽 — 한쪽만 고치면 화면이 두 말을 한다."""
    src = io.open(_시스템 / "webapp" / "templates" / "inventory" / "home.html",
                  encoding="utf-8").read()
    assert "_meta_parts.append(_color)" in src, "서버 렌더 부제에 색상이 없다"
    assert "metaParts.push(o.color)" in src, "라이브검색 JS 부제에 색상이 없다"


# ── ①③ DB 를 쓰는 것 ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    saved = {k: os.environ.get(k) for k in ("ENVIRONMENT", "DISABLE_AUTH")}
    os.environ["ENVIRONMENT"] = "team-share-dev"
    os.environ["DISABLE_AUTH"] = "1"
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def src_option(client):
    """기준 옵션 1개 — 「단독_」 모델 밑에 둔다(증식 사고의 실제 모양)."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    CODE = "단독_SKU-DEFECT01"
    with SessionLocal() as s:
        s.query(Option).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.query(Model).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.add(Model(model_code=CODE, model_name_raw=CODE,
                    model_name_display=CODE, brand="TEST"))
        s.add(Option(canonical_sku="SKU-DEFECT01", model_code=CODE,
                     color_code="블랙", size_code="250"))
        s.commit()
    return {"code": CODE, "sku": "SKU-DEFECT01"}


def test_복사는_표준SKU와_바코드를_발급한다(client, src_option):
    """① 구형식 `{모델}-{색}-{사이즈}` + 바코드 없음 이 재발하면 실패."""
    from shared.sku_format import SKU_RE
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option

    r = client.post("/api/inventory/products/copy", json={
        "src_sku": src_option["sku"], "color_code": "화이트", "size_code": "260"})
    assert r.status_code == 200, r.get_data(as_text=True)
    new_sku = r.get_json()["canonical_sku"]
    assert SKU_RE.match(new_sku), f"표준 SKU 가 아님: {new_sku}"
    assert src_option["code"] not in new_sku, "모델코드가 SKU 에 박혔다(구형식)"

    with SessionLocal() as s:
        o = s.query(Option).filter_by(canonical_sku=new_sku).one()
        assert o.barcode and len(o.barcode) == 13, "바코드가 없다 — 라벨을 못 찍는다"
        assert o.boxhero_sku == new_sku
        assert o.color_code == "화이트" and o.size_code == "260"


def test_같은_조합_복사는_막힌다(client, src_option):
    """SKU 가 랜덤이라 문자열로는 못 잡는다 — 축 조합으로 막아야 한다."""
    r = client.post("/api/inventory/products/copy", json={
        "src_sku": src_option["sku"], "color_code": "블랙", "size_code": "250"})
    assert r.status_code == 409


def test_일괄생성도_표준SKU_이고_중복은_건너뛴다(client, src_option):
    from shared.sku_format import SKU_RE
    r = client.post("/api/inventory/products/bulk-generate", json={
        "src_sku": src_option["sku"],
        "combos": [{"color_code": "블랙", "size_code": "250"},    # 이미 있음
                   {"color_code": "네이비", "size_code": "270"},
                   {"color_code": "네이비", "size_code": "270"}]})  # 요청 안 중복
    j = r.get_json()
    assert j["ok"] is True
    assert j["created_count"] == 1 and j["skipped_count"] == 1
    assert all(SKU_RE.match(s) for s in j["created"])


def test_승격하면_빈_단독_모델을_치운다(client, src_option):
    """③ 옵션이 다 빠진 「단독_」 껍데기가 유령으로 남으면 실패."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option

    with SessionLocal() as s:
        skus = [o.canonical_sku for o in
                s.query(Option).filter_by(model_code=src_option["code"]).all()]
    assert skus, "기준 옵션이 없다"

    r = client.post("/inventory/data/items/bulk-bundle-register", json={
        "skus": skus, "bundle_name": "승격시험모음전", "brand": "TEST"})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True
    assert src_option["code"] in (j.get("removed_shells") or []), \
        "빈 단독_ 모델을 안 지웠다"

    with SessionLocal() as s:
        assert s.query(Model).filter_by(model_code=src_option["code"]).first() is None
        # 정리: 새로 만든 모음전
        s.query(Option).filter_by(model_code=j["new_model_code"]).delete(
            synchronize_session=False)
        s.query(Model).filter_by(model_code=j["new_model_code"]).delete(
            synchronize_session=False)
        s.commit()

# -*- coding: utf-8 -*-
"""옵션 직접 추가(/api/bundles/<code>/options) SKU 표준화 회귀 시험.

2026-08-05 라이브 실증: 이 라우트가 구형식 `{code}-{색상}-{사이즈}` SKU 를
바코드 없이 발급 → 라벨은 한글 SKU 를 CODE128 로 인쇄 시도(깨짐 위험),
SKU 매핑 큐에 영구 미매핑 89건 축적. 조합 생성(combo)과 같은 표준
(SKU-8자 + EAN-13 자동 발급 + boxhero_sku 자기참조)으로 통일한다.
"""
import os

import pytest


@pytest.fixture(scope="module")
def client():
    # ★ setdefault 금지 — 다른 테스트 모듈이 ENVIRONMENT 를 선점하면 순서 의존 실패.
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
def bundle(client):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    code = "옵션추가시험번들"
    with SessionLocal() as s:
        s.query(Option).filter_by(model_code=code).delete()
        if not s.query(Model).filter_by(model_code=code).first():
            s.add(Model(model_code=code, model_name_raw=code, model_name_display=code))
        s.commit()
    return code


def test_direct_add_issues_standard_sku_and_barcode(client, bundle):
    from shared.sku_format import SKU_RE
    r = client.post(f"/api/bundles/{bundle}/options",
                    json={"color_code": "블랙", "size_code": "250"})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True
    sku = j["canonical_sku"]
    assert SKU_RE.match(sku), f"표준 SKU 형식이 아님: {sku}"

    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    with SessionLocal() as s:
        o = s.query(Option).filter_by(canonical_sku=sku).one()
        assert o.barcode and len(o.barcode) == 13 and o.barcode.startswith("200")
        assert o.boxhero_sku == sku
        assert o.color_code == "블랙" and o.size_code == "250"


def test_direct_add_blocks_duplicate_combo(client, bundle):
    r1 = client.post(f"/api/bundles/{bundle}/options",
                     json={"color_code": "화이트", "size_code": "260"})
    assert r1.get_json()["ok"] is True
    r2 = client.post(f"/api/bundles/{bundle}/options",
                     json={"color_code": "화이트", "size_code": "260"})
    assert r2.status_code == 409

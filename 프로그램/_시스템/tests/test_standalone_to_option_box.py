# -*- coding: utf-8 -*-
"""A안 — 「단독_」 가짜 모음전 대신 정식 옵션함 (사장님 확정 2026-08-06).

왜
  「단독_」 는 목록 두 곳에서 숨겨질 뿐 시스템은 **판매 가능**으로 취급했다
  (모상품번호 발급·품절 스캔·전송 목록 노출). 「아직 안 파는 물건」을 뜻하는 정식
  상태(`Model.is_option_box`)가 이미 있는데 문자열 접두어로 흉내 낸 것이었다.

무엇을
  ① 새로 만드는 것은 애초에 **옵션함**으로 태어난다(재고관리 「제품 추가」 · 체크 안 함)
  ② 기존 「단독_」 은 데이터를 옮기지 않고 **표시만** 옵션함으로 바꾼다(되돌릴 수 있다)
"""
import os

import pytest


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


def test_제품추가는_옵션함으로_태어난다(client):
    """체크 안 하면 「단독_」 가 아니라 옵션함이어야 한다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option

    r = client.post("/inventory/data/items/create", data={
        "model_name": "A안시험제품", "brand": "TEST",
        "color": "블랙", "size": "250"}, follow_redirects=True)
    assert r.status_code == 200

    with SessionLocal() as s:
        opt = (s.query(Option)
               .join(Model, Option.model_code == Model.model_code)
               .filter(Model.model_name_raw == "A안시험제품")
               .first())
        assert opt is not None, "제품이 안 만들어졌다"
        m = s.query(Model).filter_by(model_code=opt.model_code).one()
        assert not m.model_code.startswith("단독_"), \
            f"아직 가짜 모음전으로 만든다: {m.model_code}"
        assert m.is_option_box is True, "옵션함 표시가 없다 — 판매 배선에서 안 빠진다"
        # 정리
        s.query(Option).filter_by(model_code=m.model_code).delete(
            synchronize_session=False)
        s.query(Model).filter_by(model_code=m.model_code).delete(
            synchronize_session=False)
        s.commit()


def test_옵션함은_전송_목록에서_빠진다(client):
    """표시를 켜는 실익 — 판매 배선에서 자동으로 빠지는 것."""
    from lemouton.send import listing
    import inspect
    src = inspect.getsource(listing)
    assert "is_option_box" in src, \
        "전송 목록이 옵션함을 안 거른다면 A안의 전제가 깨진다"


def test_기존_단독은_표시만_바꾼다(client):
    """데이터는 한 줄도 안 옮긴다 — 되돌릴 수 있어야 한다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option

    CODE = "단독_SKU-ABOX0001"
    with SessionLocal() as s:
        s.query(Option).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.query(Model).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.add(Model(model_code=CODE, model_name_raw=CODE, model_name_display=CODE,
                    brand="TEST", is_option_box=False))
        s.add(Option(canonical_sku="SKU-ABOX0001", model_code=CODE,
                     color_code="블랙", size_code="250"))
        s.commit()

    # dry_run 이 기본 — 세기만 하고 안 바꾼다
    r = client.post("/inventory/data/items/mark-standalone-as-box", json={})
    j = r.get_json()
    assert j["ok"] is True and j["dry_run"] is True and j["count"] >= 1
    with SessionLocal() as s:
        assert s.query(Model).filter_by(model_code=CODE).one().is_option_box is False

    # 실제 적용
    r2 = client.post("/inventory/data/items/mark-standalone-as-box",
                     json={"dry_run": False})
    assert r2.get_json()["ok"] is True
    with SessionLocal() as s:
        m = s.query(Model).filter_by(model_code=CODE).one()
        assert m.is_option_box is True
        # 옵션은 그대로 — 데이터 이동 없음
        assert s.query(Option).filter_by(model_code=CODE).count() == 1
        # 정리
        s.query(Option).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.query(Model).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.commit()


def test_두_번_돌려도_안전하다(client):
    """이미 옵션함인 것은 다시 세지 않는다(멱등)."""
    r1 = client.post("/inventory/data/items/mark-standalone-as-box",
                     json={"dry_run": False})
    r2 = client.post("/inventory/data/items/mark-standalone-as-box",
                     json={"dry_run": False})
    assert r1.get_json()["ok"] and r2.get_json()["ok"]
    assert r2.get_json()["count"] == 0

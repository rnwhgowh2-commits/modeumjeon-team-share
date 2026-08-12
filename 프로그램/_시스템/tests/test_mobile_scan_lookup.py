# -*- coding: utf-8 -*-
"""모바일 스캔 lookup·action 회귀 시험 — 2026-08-05 라이브 실측 버그 2건 고정.

버그 1 (P0): 라벨 인쇄(barcode_print.html)는 Option.barcode 를 최우선으로
  인코딩하는데 /mobile/api/lookup 이 Option.barcode 를 어느 단계에서도 조회하지
  않아, 우리가 뽑은 라벨 890건이 전부 「매칭 안 됨」 (표본 30/30 실패 실측).

버그 2 (P0): lookup·action 의 재고 표시가 raw sum(qty) — 이 시스템은
  「qty 양수 저장, 부호는 tx_type 이 결정」이라 raw 합은 출고를 더해 버린다.
  라이브 실측: 입고2·출고2 상태에서 new_total_stock=4 (실제 0).
"""
import os

import pytest


@pytest.fixture(scope="module")
def client():
    # ★ setdefault 는 안 된다 — test_icon_store.py 가 먼저 import 되며
    #   ENVIRONMENT=test 를 선점해 모바일 BP 가 등록되지 않는다(전체 실행에서만
    #   실패하는 순서 의존). create_app 호출 직전 강제 설정 + 종료 후 원복.
    saved = {k: os.environ.get(k) for k in ("ENVIRONMENT", "DISABLE_AUTH")}
    os.environ["ENVIRONMENT"] = "team-share-dev"
    os.environ["DISABLE_AUTH"] = "1"  # 로그인 벽 우회 (webapp/auth/__init__.py 공식 플래그)
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
def seeded(client):
    """옵션 1개 (barcode 설정) + 위치 1개 + 입고2·출고1 거래."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    from lemouton.inventory.models import InventoryLocation, InventoryTx, InventoryProduct

    SKU = "SKU-TESTSCAN"
    BARCODE = "2009999999012"  # Option.barcode 에만 존재 (InventoryProduct 에 없음)
    with SessionLocal() as s:
        s.query(InventoryTx).filter_by(option_canonical_sku=SKU).delete()
        s.query(Option).filter_by(canonical_sku=SKU).delete()
        s.query(InventoryProduct).filter_by(canonical_sku=SKU).delete()
        loc = s.query(InventoryLocation).filter_by(name="시험위치").first()
        if not loc:
            loc = InventoryLocation(name="시험위치")
            s.add(loc)
            s.flush()
        opt = Option(canonical_sku=SKU, model_code="TESTSCAN",
                     color_code="BK", size_code="250", barcode=BARCODE)
        s.add(opt)
        # 입고 2, 출고 1 — 저장 규약대로 qty 는 양수, 부호는 tx_type 이 결정
        s.add(InventoryTx(tx_type="in", qty=2, option_canonical_sku=SKU,
                          location_id=loc.id, status="completed"))
        s.add(InventoryTx(tx_type="out", qty=1, option_canonical_sku=SKU,
                          location_id=loc.id, status="completed"))
        s.commit()
        loc_id = loc.id
    return {"sku": SKU, "barcode": BARCODE, "loc_id": loc_id}


def test_lookup_matches_option_barcode(client, seeded):
    """라벨에 인쇄되는 값(Option.barcode)을 스캔하면 반드시 매칭돼야 한다."""
    r = client.post("/mobile/api/lookup", json={"code": seeded["barcode"]})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True
    assert j["option"]["canonical_sku"] == seeded["sku"]
    assert j["option"]["match_via"] == "option_barcode"


def test_lookup_stock_uses_ssot_sign(client, seeded):
    """입고2·출고1 → 재고 1. raw 합(3)이 아니라 SSOT 부호 규약이어야 한다."""
    r = client.post("/mobile/api/lookup", json={"code": seeded["sku"]})
    j = r.get_json()
    assert j["ok"] is True
    assert j["option"]["stock"] == 1


def test_action_new_total_uses_ssot_sign(client, seeded):
    """출고 1 추가 → new_total_stock 은 0 이어야 한다 (raw 합이면 4)."""
    r = client.post("/mobile/api/action", json={
        "sku": seeded["sku"], "action": "out", "qty": 1,
        "location_id": seeded["loc_id"], "memo": "시험",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True
    assert j["new_total_stock"] == 0


def test_action_adjust_delta_from_ssot(client, seeded):
    """seeded 상태 = 입고2·출고1 → 현재 1. 조정 5 → delta +4, 최종 5.

    raw 합 기준이면 현재를 3 으로 잘못 읽어 delta +2 → 최종 재고가 3 이 된다.
    """
    r = client.post("/mobile/api/action", json={
        "sku": seeded["sku"], "action": "adjust", "qty": 5,
        "location_id": seeded["loc_id"], "memo": "시험",
    })
    j = r.get_json()
    assert j["ok"] is True, j
    assert j["applied_qty"] == 4
    assert j["new_total_stock"] == 5


def test_adjust_저장값이_읽는_쪽과_같은_뜻이다(client, seeded):
    """🔴 저장값까지 못 박는다 — 응답만 보면 「어떻게 저장됐는지」를 안 본다.

    ⚠️ 2026-08-13 이 한 줄이 하루에 **세 번** 뒤집혔다(재고 4 → 6 → 4).
      전부 에러 없이 숫자만 틀렸다. 그래서 **규칙을 여기 박아 두지 않고**
      읽는 쪽 정본(`fold_tx_rows`)에게 물어 그와 같은지만 본다 —
      규약이 바뀌어도 세 곳을 같이 바꾸면 그대로 통과한다.
      쓰는 곳 세 곳을 한꺼번에 보는 시험은
      `tests/inventory/test_adjust_writer_consistency.py`.
    """
    from lemouton.inventory.models import InventoryTx
    from shared.db import SessionLocal
    from shared.inventory_stock import fold_tx_rows

    client.post("/mobile/api/action", json={
        "sku": seeded["sku"], "action": "adjust", "qty": 5,
        "location_id": seeded["loc_id"], "memo": "시험",
    })
    with SessionLocal() as s:
        rows = (s.query(InventoryTx.tx_type, InventoryTx.qty)
                .filter_by(option_canonical_sku=seeded["sku"], status="completed")
                .order_by(InventoryTx.id).all())
    # 저장한 것을 읽는 쪽 규칙으로 접으면 **실사한 수**가 나와야 한다.
    assert fold_tx_rows(rows) == 5, f"저장 뜻과 읽는 뜻이 어긋났다: {rows}"

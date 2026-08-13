# -*- coding: utf-8 -*-
"""실사 조정의 **기준**이 「그 창고」인가 — 창고가 둘 이상일 때.

🔴 2026-08-13 감사에서 실행으로 재현한 것들. 기존 시험은 **전부 창고 1곳**(loc=1)이라
   이 자리를 한 번도 안 봤다 — 창고가 하나면 「그 창고 재고」와 「전 창고 합」이 같아
   증상이 안 난다. 통과하면서 뚫린 전형이다.

세 가지를 못 박는다.
  ① 차이의 기준 — `create_adjustment` 가 「전 창고 합」으로 빼면, 창고A 실사가
     창고A 를 음수로 만들고 총합에서 재고가 증발한다.
  ② 스냅샷 — 한 창고 실사가 `boxhero_stock_total`(전체 스냅샷)을 그 창고 수로 덮으면,
     그걸 기준으로 읽는 화면이 없던 재고를 만든다.
  ③ 조정서 폼 — 금지된 스냅샷이 아니라 **원장**을 기준으로 ± 해야 한다.
"""
import pytest


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models   # noqa: F401
    import lemouton.inventory.models  # noqa: F401
    from shared.db import Base
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _두창고(db, sku='SKU-LOC001'):
    """창고 A(10개) · 창고 B(10개) — 합 20."""
    from datetime import datetime, timezone
    from lemouton.sourcing.models import Model, Option
    from lemouton.inventory.models import InventoryLocation, InventoryTx
    db.add(Model(model_code='MLOC', model_name_raw='위치검사', brand='르무통'))
    db.flush()
    db.add(Option(canonical_sku=sku, model_code='MLOC',
                  color_code='블랙', size_code='250'))
    a = InventoryLocation(name='창고A')
    b = InventoryLocation(name='창고B')
    db.add_all([a, b])
    db.flush()
    for loc in (a.id, b.id):
        db.add(InventoryTx(tx_type='in', option_canonical_sku=sku, qty=10,
                           status='completed', location_id=loc,
                           created_at=datetime(2026, 8, 13, tzinfo=timezone.utc)))
    db.flush()
    return sku, a.id, b.id


def _재고(db, sku, loc=None):
    from shared.inventory_stock import get_stock_batch
    return int(get_stock_batch(db, [sku], location_id=loc).get(sku) or 0)


def test_창고A_실사가_창고B_재고를_안_건드린다(db):
    """🔴 A(10)·B(10) 에서 A 를 8 로 실사 → A=8 · B=10 · 합=18.

    옛 코드는 기준을 **전 창고 합(20)** 으로 잡아 차이 −12 를 A 에 박았다:
      A = 10 − 12 = **−2** · 합 = **8** — 10개가 에러 없이 증발한다.
    """
    from lemouton.inventory.inbound import create_adjustment
    sku, A, B = _두창고(db)
    create_adjustment(db, location_id=A, option_canonical_sku=sku, new_qty=8)
    db.flush()
    assert _재고(db, sku, A) == 8, "창고A 가 실사한 수와 다르다"
    assert _재고(db, sku, B) == 10, "창고B 재고가 휩쓸렸다"
    assert _재고(db, sku) == 18, "총합이 틀어졌다(재고 증발)"


def test_음수_실사도_그_창고_기준이다(db):
    """A 를 0 으로 실사 → A=0 · 합=10. 기준이 전체면 −20 이 박혀 합이 0 이 된다."""
    from lemouton.inventory.inbound import create_adjustment
    sku, A, B = _두창고(db)
    create_adjustment(db, location_id=A, option_canonical_sku=sku, new_qty=0)
    db.flush()
    assert _재고(db, sku, A) == 0
    assert _재고(db, sku) == 10


def test_스냅샷이_원장과_어긋나지_않는다(db):
    """🔴 한 창고 실사가 **전체 스냅샷**을 그 창고 수로 덮으면 안 된다.

    A 를 8 로 실사한 뒤 참값은 18 인데, 옛 코드는 스냅샷에 8 을 박았다.
    그 스냅샷을 기준으로 읽는 화면이 없던 재고를 만든다.
    """
    from lemouton.sourcing.models import Option
    from lemouton.inventory.inbound import create_adjustment
    sku, A, B = _두창고(db)
    create_adjustment(db, location_id=A, option_canonical_sku=sku, new_qty=8)
    db.flush()
    snap = db.query(Option).filter_by(canonical_sku=sku).first().boxhero_stock_total
    assert int(snap or 0) == 18, "스냅샷(%s)이 원장 합(18)과 다르다" % snap


def _코드만(src: str) -> str:
    """주석 줄을 걷어낸 원문 — 설명에 적은 낱말이 시험을 흔들지 않게."""
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


# ── ③ 조정서 폼(± 모드)이 무엇을 기준으로 삼나 ────────────────────────────────

def test_습득_분실은_원장을_기준으로_센다():
    """🔴 옛 코드는 `opt.boxhero_stock_total`(스냅샷)을 기준으로 ± 했다.

    스냅샷은 `shared/inventory_stock.py` 머리말이 **「신뢰 X」**라 못 박은 값이고,
    폰 조정 등은 그 값을 안 고친다 → 원장과 벌어진다.
    실측: 원장 합 18 · 스냅샷 20 인 상태에서 「+5 습득」 → 25 (기대 23).
    **없던 2개가 생긴다.**
    """
    import inspect
    import re
    from webapp.routes.inventory import transactions as T
    # 🔴 주석에 적힌 낱말이 아니라 **실제 대입문**을 본다 — 낱말만 세면 설명을
    #   쓴 것만으로 시험이 깨지거나(거짓 빨강), 반대로 남아 있어도 통과한다.
    src = _코드만(inspect.getsource(T))
    assert not re.search(r"cur_stock\s*=\s*opt\.boxhero_stock_total", src), \
        "조정서가 아직 금지된 스냅샷을 기준으로 삼는다"
    i = src.find("mode == 'plus'")
    assert i > 0, "습득 분기를 못 찾음"
    앞 = src[max(0, i - 500):i]
    assert "get_stock_batch" in 앞, "원장(get_stock_batch)을 기준으로 안 읽는다"


def test_화면이_보여주는_현재도_원장_기준이다():
    """사장님이 「현재 20」을 보고 +5 했는데 결과가 23 이면 어긋난 것이다.
    화면에 넣는 stock 도 스냅샷이 아니라 원장에서 와야 한다."""
    import inspect
    import re
    from webapp.routes.inventory import transactions as T
    src = _코드만(inspect.getsource(T))
    assert not re.search(r"'stock':\s*o\.boxhero_stock_total", src), \
        "화면 「현재 재고」가 아직 스냅샷이다"


# ── ① 조정 「수정」 화면이 옛 뜻(절대값)으로 남아 있다 ────────────────────────

def test_수정화면_안내가_증감분이라고_말한다():
    """안내대로 「재고를 5로」 뜻으로 5 를 넣으면 원장은 그 5 를 **더한다**
    → 입고 100 인 상품이 105 가 된다(100개 과대)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    html = (root / "webapp/templates/inventory/tx_edit.html").read_text(encoding="utf-8")
    assert "절대값" not in html, "수정 화면이 아직 「절대값」이라 안내한다"
    assert "증감분" in html or "변화량" in html, "증감분이라고 말하지 않는다"


def test_수정화면이_음수_조정을_막지_않는다():
    """차이값은 음수가 정상이다(예 −95). `min="0"` 이면 저장 자체가 막힌다 —
    메모만 고치려 해도 못 고친다."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[2]
    html = (root / "webapp/templates/inventory/tx_edit.html").read_text(encoding="utf-8")
    m = re.search(r'<input[^>]*name="qty"[^>]*>', html)
    assert m, "수량 입력칸을 못 찾음"
    assert 'min="0"' not in m.group(0), "음수 조정을 막는다: " + m.group(0)

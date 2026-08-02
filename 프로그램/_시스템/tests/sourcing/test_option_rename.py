"""옵션 값 이름 바꾸기 + 매트릭스 밖 옵션(유령) 관리.

설계서 — docs/superpowers/specs/2026-08-02-옵션값-이름바꾸기-design.md

🔴 이 파일이 지키는 사실 한 줄:
   **이름을 고치는 것은 「지우고 새로 만들기」가 아니라 「갈아끼우기」다.**
   옵션번호·소싱처 URL 매핑·재고 이력이 그대로 따라와야 한다.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.matrix.models",
    "lemouton.sets.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from lemouton.sourcing.option_service import create_combination_options


_COLOR = "색상"
_SIZE = "사이즈"


def _steps(colors, sizes):
    return [{"axis_name": _COLOR, "values": list(colors)},
            {"axis_name": _SIZE, "values": list(sizes)}]


def _all_combos(colors, sizes):
    return [[c, s] for c in colors for s in sizes]


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def seeded(db):
    """테스트 이름(색상1·색상2)으로 4개 만들어 둔 상태 — 사장님 화면의 재현."""
    create_combination_options(
        db, "AF", _steps(["색상1", "색상2"], ["250", "260"]),
        selected=_all_combos(["색상1", "색상2"], ["250", "260"]), prune=True)
    return db


def _axes(opt):
    try:
        v = json.loads(opt.axis_values_json or "[]")
    except (ValueError, TypeError):
        v = []
    return tuple(v) or tuple(x for x in [opt.color_code, opt.size_code] if x)


# ── ① 이름 바꾸기 ────────────────────────────────────────────────────────

def test_rename_keeps_option_and_creates_nothing(seeded):
    """색상1 → 블랙: 새 옵션 0개, 옵션 수 그대로."""
    before = {o.canonical_sku for o in seeded.query(M.Option).filter_by(model_code="AF")}

    r = create_combination_options(
        seeded, "AF", _steps(["블랙", "색상2"], ["250", "260"]),
        selected=_all_combos(["블랙", "색상2"], ["250", "260"]), prune=True,
        renames=[{"axis": 0, "from": "색상1", "to": "블랙"}])

    assert r["created"] == 0, "이름만 고쳤는데 새 옵션이 생기면 안 된다"
    assert r["renamed"] == 2
    after = {o.canonical_sku for o in seeded.query(M.Option).filter_by(model_code="AF")}
    assert after == before, "옵션번호(canonical_sku)가 그대로여야 한다"


def test_rename_rewrites_axis_values(seeded):
    create_combination_options(
        seeded, "AF", _steps(["블랙", "색상2"], ["250", "260"]),
        selected=_all_combos(["블랙", "색상2"], ["250", "260"]), prune=True,
        renames=[{"axis": 0, "from": "색상1", "to": "블랙"}])

    opts = seeded.query(M.Option).filter_by(model_code="AF").all()
    assert {_axes(o) for o in opts} == {
        ("블랙", "250"), ("블랙", "260"), ("색상2", "250"), ("색상2", "260")}
    for o in opts:
        assert o.color_code == _axes(o)[0], "레거시 칸(color_code)도 같이 따라와야 한다"


def test_rename_leaves_no_orphan_and_keeps_selling(seeded):
    """이름을 고쳐도 유령이 생기지 않고, 팔리던 옵션은 계속 켜져 있어야 한다."""
    create_combination_options(
        seeded, "AF", _steps(["블랙", "색상2"], ["250", "260"]),
        selected=_all_combos(["블랙", "색상2"], ["250", "260"]), prune=True,
        renames=[{"axis": 0, "from": "색상1", "to": "블랙"}])

    opts = seeded.query(M.Option).filter_by(model_code="AF").all()
    assert len(opts) == 4
    assert all(o.is_active for o in opts)


def test_rename_keeps_source_url_mapping(seeded):
    """🔴 본체 — 소싱처 URL 매핑이 이름 바꾸기를 견뎌야 한다."""
    opt = (seeded.query(M.Option)
           .filter_by(model_code="AF", color_code="색상1", size_code="250").one())
    seeded.add(M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                                 url="https://www.musinsa.com/products/1"))
    seeded.flush()
    url = seeded.query(M.BundleSourceUrl).one()
    seeded.add(M.OptionSourceUrlLink(option_canonical_sku=opt.canonical_sku,
                                     bundle_source_url_id=url.id))
    seeded.commit()

    create_combination_options(
        seeded, "AF", _steps(["블랙", "색상2"], ["250", "260"]),
        selected=_all_combos(["블랙", "색상2"], ["250", "260"]), prune=True,
        renames=[{"axis": 0, "from": "색상1", "to": "블랙"}])

    link = seeded.query(M.OptionSourceUrlLink).one()
    assert link.option_canonical_sku == opt.canonical_sku
    seeded.refresh(opt)
    assert _axes(opt) == ("블랙", "250")


def test_rename_without_pairs_still_creates_new(seeded):
    """짝을 안 지으면 예전 그대로 — 새로 만든다(사장님이 확인 안 한 것을 기계가 단정하지 않는다)."""
    r = create_combination_options(
        seeded, "AF", _steps(["블랙", "색상2"], ["250", "260"]),
        selected=_all_combos(["블랙", "색상2"], ["250", "260"]), prune=True)
    assert r["created"] == 2


# ── ② 이번 저장으로 밖이 된 옵션만 자동 판매끄기 ──────────────────────────

def test_newly_orphaned_disappears(seeded):
    """🔴 사장님 확정 — 설계에서 뺀 값의 옵션은 **없던 것처럼 사라진다**(묻지 않는다)."""
    r = create_combination_options(
        seeded, "AF", _steps(["색상1"], ["250", "260"]),
        selected=_all_combos(["색상1"], ["250", "260"]), prune=True)

    assert r["orphaned"] == 2 and r["orphan_deleted"] == 2 and r["orphan_kept"] == 0
    left = seeded.query(M.Option).filter_by(model_code="AF").all()
    assert {_axes(o)[0] for o in left} == {"색상1"}


def test_newly_orphaned_with_history_is_kept_but_off(seeded):
    """🔴 기록이 걸린 옵션은 지우지 않는다 — 지난 주문·정산을 되짚을 수 없게 된다."""
    keep = (seeded.query(M.Option)
            .filter_by(model_code="AF", color_code="색상2", size_code="250").one())
    seeded.add(M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                                 url="https://www.musinsa.com/products/2"))
    seeded.flush()
    url = seeded.query(M.BundleSourceUrl).one()
    seeded.add(M.OptionSourceUrlLink(option_canonical_sku=keep.canonical_sku,
                                     bundle_source_url_id=url.id))
    seeded.commit()

    r = create_combination_options(
        seeded, "AF", _steps(["색상1"], ["250", "260"]),
        selected=_all_combos(["색상1"], ["250", "260"]), prune=True)

    assert r["orphan_deleted"] == 1 and r["orphan_kept"] == 1
    survivor = seeded.get(M.Option, keep.canonical_sku)
    assert survivor is not None and not survivor.is_active


def test_pre_existing_orphan_is_not_touched(db):
    """🔴 단계 설계가 생기기 전부터 있던 옛 옵션을 한 번의 저장이 조용히 내리면 안 된다."""
    db.add(M.Option(canonical_sku="SKU-LEGACY1", model_code="AF",
                    color_code="옛색", size_code="999", is_active=True))
    db.commit()

    create_combination_options(
        db, "AF", _steps(["블랙"], ["250"]), selected=[["블랙", "250"]], prune=True)

    legacy = db.query(M.Option).filter_by(canonical_sku="SKU-LEGACY1").one()
    assert legacy.is_active, "직전 설계에 없던 옛 옵션은 건드리지 않는다"


def test_user_turned_off_option_can_come_back(seeded):
    """매트릭스 안에서 사장님이 끈 옵션은 다시 켜면 돌아온다 (기존 동작 유지)."""
    create_combination_options(
        seeded, "AF", _steps(["색상1", "색상2"], ["250", "260"]),
        selected=[["색상1", "250"]], prune=True)
    create_combination_options(
        seeded, "AF", _steps(["색상1", "색상2"], ["250", "260"]),
        selected=_all_combos(["색상1", "색상2"], ["250", "260"]), prune=True)
    opts = seeded.query(M.Option).filter_by(model_code="AF").all()
    assert all(o.is_active for o in opts)


# ── ③ 유령 목록·정리 ─────────────────────────────────────────────────────

def _leave_behind(db):
    """옛 결함이 남긴 상태 재현 — 설계만 바뀌고 옛 옵션이 그대로 남은 모양.

    (지금 저장 흐름에서는 안 생긴다. 이미 라이브에 쌓인 것을 치우는 창구용.)
    """
    from lemouton.sourcing.option_service import save_step_design
    save_step_design(db, "AF", _steps(["블랙"], ["250"]))
    db.commit()


def test_list_orphans_finds_options_outside_matrix(seeded):
    from lemouton.sourcing.option_orphans import list_orphans

    _leave_behind(seeded)

    rows = list_orphans(seeded, "AF")
    assert {r["axis_values"][0] for r in rows} == {"색상1", "색상2"}
    assert len(rows) == 4


def test_list_orphans_empty_without_step_design(db):
    """🔴 설계가 없으면 무엇이 밖인지 알 수 없다 — 아무것도 유령이라고 부르지 않는다."""
    from lemouton.sourcing.option_orphans import list_orphans

    db.add(M.Option(canonical_sku="SKU-NOSTEP1", model_code="AF",
                    color_code="블랙", size_code="250"))
    db.commit()
    assert list_orphans(db, "AF") == []


def test_resolve_off_turns_orphans_off(seeded):
    from lemouton.sourcing.option_orphans import list_orphans, resolve_orphans

    _leave_behind(seeded)
    skus = [r["canonical_sku"] for r in list_orphans(seeded, "AF")]

    res = resolve_orphans(seeded, "AF", skus, action="off")

    assert res["turned_off"] == len(skus)
    assert res["deleted"] == 0
    assert all(not seeded.get(M.Option, sku).is_active for sku in skus)


def test_resolve_delete_removes_unlinked(seeded):
    from lemouton.sourcing.option_orphans import list_orphans, resolve_orphans

    _leave_behind(seeded)
    skus = [r["canonical_sku"] for r in list_orphans(seeded, "AF")]

    res = resolve_orphans(seeded, "AF", skus, action="delete")

    assert res["deleted"] == len(skus)
    assert seeded.query(M.Option).filter_by(model_code="AF").count() == 0


def test_resolve_delete_protects_linked_option(seeded):
    """🔴 걸린 데가 있으면 지우지 않는다 — 끄고, 그 사실을 돌려준다."""
    from lemouton.sourcing.option_orphans import list_orphans, resolve_orphans

    keep = (seeded.query(M.Option)
            .filter_by(model_code="AF", color_code="색상1", size_code="250").one())
    seeded.add(M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                                 url="https://www.musinsa.com/products/1"))
    seeded.flush()
    url = seeded.query(M.BundleSourceUrl).one()
    seeded.add(M.OptionSourceUrlLink(option_canonical_sku=keep.canonical_sku,
                                     bundle_source_url_id=url.id))
    seeded.commit()

    _leave_behind(seeded)
    skus = [r["canonical_sku"] for r in list_orphans(seeded, "AF")]

    res = resolve_orphans(seeded, "AF", skus, action="delete")

    assert keep.canonical_sku in res["kept"]
    assert res["deleted"] == len(skus) - 1
    survivor = seeded.get(M.Option, keep.canonical_sku)
    assert survivor is not None and not survivor.is_active


def test_audit_all_finds_every_bundle_with_ghosts(seeded):
    """전 상품 전수 조사 — 상품 하나씩 묻지 않고 한 번에 훑는다."""
    from lemouton.sourcing.option_orphans import audit_all

    seeded.add(M.Model(model_code="BB", model_name_raw="깨끗한상품"))
    seeded.commit()
    create_combination_options(seeded, "BB", _steps(["블랙"], ["250"]),
                               selected=[["블랙", "250"]], prune=True)
    _leave_behind(seeded)                       # AF 에만 유령 4개

    r = audit_all(seeded)

    assert r["orphans"] == 4 and r["bundles_with_orphans"] == 1
    assert r["items"][0]["model_code"] == "AF"
    assert r["items"][0]["selling"] == 4 and r["items"][0]["deletable"] == 4
    assert "BB" not in [i["model_code"] for i in r["items"]], "깨끗한 상품은 안 뜬다"


def test_audit_all_skips_bundles_without_design(db):
    """🔴 설계가 없으면 무엇이 밖인지 알 수 없다 — 「없다」고 단정하지 않고 세지도 않는다."""
    from lemouton.sourcing.option_orphans import audit_all

    db.add(M.Option(canonical_sku="SKU-NODESIGN", model_code="AF",
                    color_code="블랙", size_code="250"))
    db.commit()

    r = audit_all(db)
    assert r["orphans"] == 0 and r["bundles_scanned"] == 0
    assert r["bundles_without_design"] == 1


def test_scan_suspicious_catches_test_names_without_design(db):
    """🔴 설계가 없는 상품이 대부분이라 매트릭스 대조로는 아무것도 못 잡는다 — 이름 그물."""
    from lemouton.sourcing.option_orphans import scan_suspicious_values

    db.add(M.Option(canonical_sku="SKU-T1", model_code="AF",
                    color_code="색상1", size_code="250"))
    db.add(M.Option(canonical_sku="SKU-T2", model_code="AF",
                    color_code="테스트색", size_code="250"))
    db.add(M.Option(canonical_sku="SKU-OK", model_code="AF",
                    color_code="블랙", size_code="250"))
    db.commit()

    r = scan_suspicious_values(db)
    assert r["suspect_options"] == 2 and r["suspect_bundles"] == 1
    assert r["options_total"] == 3


def test_scan_suspicious_does_not_flag_normal_colors(db):
    """🔴 헛걸림 금지 — 멀쩡한 색·사이즈를 테스트로 몰면 그물이 쓸모없어진다."""
    from lemouton.sourcing.option_orphans import scan_suspicious_values

    for i, (c, sz) in enumerate([("블랙", "250"), ("차콜", "260"), ("아이보리", "270"),
                                 ("네이비2", "280"), ("501", "M")]):
        db.add(M.Option(canonical_sku=f"SKU-N{i}", model_code="AF",
                        color_code=c, size_code=sz))
    db.commit()

    assert scan_suspicious_values(db)["suspect_options"] == 0


def test_resolve_refuses_options_inside_matrix(seeded):
    """🔴 매트릭스 안 옵션은 이 창구로 못 지운다 — 팔리는 상품을 실수로 내리는 길을 막는다."""
    from lemouton.sourcing.option_orphans import resolve_orphans

    inside = (seeded.query(M.Option)
              .filter_by(model_code="AF", color_code="색상1", size_code="250").one())
    res = resolve_orphans(seeded, "AF", [inside.canonical_sku], action="delete")
    assert res["deleted"] == 0 and res["turned_off"] == 0
    assert res["refused"] == [inside.canonical_sku]

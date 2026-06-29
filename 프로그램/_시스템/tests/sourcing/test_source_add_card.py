from lemouton.sourcing import crawl_guide as cg


def test_skeleton_has_update_requested_none():
    sk = cg.empty_skeleton()
    assert sk["update_requested"] is None


def test_validate_keeps_update_requested():
    g = cg.empty_skeleton()
    g["update_requested"] = {"at": "2026-06-29T00:00:00+00:00", "note": "재고 둔갑"}
    out = cg.validate_guide(g)
    assert out["update_requested"]["note"] == "재고 둔갑"
    assert out["update_requested"]["at"] == "2026-06-29T00:00:00+00:00"


def test_validate_rejects_bad_update_requested():
    g = cg.empty_skeleton()
    g["update_requested"] = "nope"          # dict 아님 → None 으로 정제
    out = cg.validate_guide(g)
    assert out["update_requested"] is None


def test_validate_caps_note_at_200():
    g = cg.empty_skeleton()
    g["update_requested"] = {"at": "2026-06-29T00:00:00+00:00", "note": "x" * 250}
    out = cg.validate_guide(g)
    assert len(out["update_requested"]["note"]) == 200


def test_validate_update_requested_missing_at_becomes_none():
    g = cg.empty_skeleton()
    g["update_requested"] = {"note": "사유만 있음"}
    out = cg.validate_guide(g)
    assert out["update_requested"]["at"] is None
    assert out["update_requested"]["note"] == "사유만 있음"

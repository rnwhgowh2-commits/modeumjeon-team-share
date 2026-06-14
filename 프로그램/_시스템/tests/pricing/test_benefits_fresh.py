from lemouton.pricing.unified import benefits_fresh


def test_fresh_when_ok_and_status_not_error():
    snap = {"benefits_ok": True, "lines": ["쿠폰 5%"], "amounts": {}}
    assert benefits_fresh(snap, "ok") is True


def test_stale_when_status_error():
    snap = {"benefits_ok": True, "lines": ["쿠폰 5%"], "amounts": {}}
    assert benefits_fresh(snap, "error") is False


def test_stale_when_no_snapshot():
    assert benefits_fresh(None, "ok") is False


def test_stale_when_benefits_not_ok():
    snap = {"benefits_ok": False, "lines": [], "amounts": {}}
    assert benefits_fresh(snap, "ok") is False

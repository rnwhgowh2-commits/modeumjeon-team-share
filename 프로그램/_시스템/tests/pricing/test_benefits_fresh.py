from lemouton.pricing.unified import benefits_fresh


def test_fresh_when_benefits_ok():
    snap = {"benefits_ok": True, "lines": ["쿠폰 5%"], "amounts": {}}
    assert benefits_fresh(snap, "ok") is True
    assert benefits_fresh(snap) is True  # last_status 인자 없이도 동작


def test_keeps_last_good_even_when_status_error():
    # N1(2026-06-14): _crawl 은 성공 크롤에서만 갱신되므로 '마지막 성공 스냅샷'.
    #   이후 재크롤이 error 여도 마지막 성공값을 유지(미수집 아님). 표면가는 별도 게이트가 차단.
    snap = {"benefits_ok": True, "lines": ["쿠폰 5%"], "amounts": {}}
    assert benefits_fresh(snap, "error") is True


def test_stale_when_no_snapshot():
    assert benefits_fresh(None, "ok") is False


def test_stale_when_benefits_not_ok():
    snap = {"benefits_ok": False, "lines": [], "amounts": {}}
    assert benefits_fresh(snap, "ok") is False

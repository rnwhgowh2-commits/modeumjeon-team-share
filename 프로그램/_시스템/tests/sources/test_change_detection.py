from lemouton.sources.change_detection import detect_changes


def _opt(color, size, price, stock):
    return {"color_text": color, "size_text": size, "price": price, "stock": stock}


def test_no_change():
    old = [_opt("블랙", "220", 50000, 3)]
    new = [_opt("블랙", "220", 50000, 3)]
    r = detect_changes(old, new)
    assert r["stock_changed"] is False and r["price_changed"] is False


def test_stock_only():
    old = [_opt("블랙", "220", 50000, 3)]
    new = [_opt("블랙", "220", 50000, 0)]
    r = detect_changes(old, new)
    assert r["stock_changed"] is True and r["price_changed"] is False


def test_price_only():
    old = [_opt("블랙", "220", 50000, 3)]
    new = [_opt("블랙", "220", 48000, 3)]
    r = detect_changes(old, new)
    assert r["stock_changed"] is False and r["price_changed"] is True


def test_both():
    old = [_opt("블랙", "220", 50000, 3)]
    new = [_opt("블랙", "220", 48000, 1)]
    r = detect_changes(old, new)
    assert r["stock_changed"] is True and r["price_changed"] is True


def test_new_option_counts_as_stock_change():
    old = [_opt("블랙", "220", 50000, 3)]
    new = [_opt("블랙", "220", 50000, 3), _opt("블랙", "230", 50000, 2)]
    r = detect_changes(old, new)
    assert r["stock_changed"] is True


def test_detail_is_human_readable():
    old = [_opt("블랙", "220", 50000, 3)]
    new = [_opt("블랙", "220", 48000, 0)]
    r = detect_changes(old, new)
    assert "220" in r["detail"]

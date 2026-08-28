from lemouton.policy.fields import item_keys_for


def test_auction_has_site_discount_item():
    """required.py 지도: 옥션도 사이트부담 지원할인이 필수다 — G마켓만 있으면 안 된다."""
    assert '_site_discount' in item_keys_for('auction'), (
        '옥션 정책 화면에 사이트부담 지원할인 항목이 없다 — '
        'ESM 전문(addtionalInfo.siteDiscount.iac)이 필수인데 입력할 곳이 없다')

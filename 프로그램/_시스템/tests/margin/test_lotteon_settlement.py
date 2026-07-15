from lemouton.margin.lotteon_settlement import compute_settlement

def test_matches_excel_row_1():
    # 상품가 32200, 배송비 0, 셀러부담 966, 롯데부담 3864 → 엑셀 정산예정금액 26404
    got = compute_settlement(product_price=32200, shipping=0,
                             seller_discount=966, platform_discount=3864)
    assert got == 26404

def test_shipping_included():
    # 정산대상 13000 - (1300 + 99 + 200 - 0) = 11401
    got = compute_settlement(product_price=10000, shipping=3000,
                             seller_discount=0, platform_discount=0)
    assert got == 11401

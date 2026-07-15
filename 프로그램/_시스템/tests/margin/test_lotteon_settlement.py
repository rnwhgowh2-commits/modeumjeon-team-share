from lemouton.margin.lotteon_settlement import compute_settlement

def test_affiliate_no_shipping():
    # 주문 2026070814649375: 상품가 32200, 배송 0/0, 셀러 966, 롯데 3864, 제휴 → 26404
    got = compute_settlement(product_price=32200, shipping_sale=0, shipping_fee_base=0,
                             seller_discount=966, platform_discount=3864, is_affiliate=True)
    assert got == 26404

def test_direct_channel_no_affiliate_fee():
    # 판매경로 '롯데ON'(직접): 상품가 153600, 셀러 7866, 롯데 31464, 배송 0 → 125766 (제휴 0%)
    got = compute_settlement(product_price=153600, shipping_sale=0, shipping_fee_base=0,
                             seller_discount=7866, platform_discount=31464, is_affiliate=False)
    assert got == 125766

def test_shipping_fee_base_differs_from_settled_shipping():
    # 주문 2026071015251063: 상품가 80900, 배송매출 10000, 수수료적용배송비 0, 셀러 3134,
    # 롯데 12536, 제휴 → 배송비수수료는 0(수수료적용배송비 0 기준), 정산 75631
    got = compute_settlement(product_price=80900, shipping_sale=10000, shipping_fee_base=0,
                             seller_discount=3134, platform_discount=12536, is_affiliate=True)
    assert got == 75631

def test_affiliate_flag_changes_result():
    base = dict(product_price=100000, shipping_sale=0, shipping_fee_base=0,
                seller_discount=0, platform_discount=0)
    aff = compute_settlement(**base, is_affiliate=True)
    dir_ = compute_settlement(**base, is_affiliate=False)
    assert dir_ - aff == round(100000 * 0.02)  # 제휴면 2% 더 차감

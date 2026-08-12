# -*- coding: utf-8 -*-
"""정책 「판매방식·통관(listing)」이 실제로 초안에 닿는가.

🔴 이 항목은 **읽는 사람이 아무도 없었다.** 사장님이 「19세 이상만」으로 바꿔도
   초안에는 그대로 전연령이 남았고, 화면은 조용했다 — 값을 못 만드는 것과
   **그 사실을 안 말하는 것은 다른 잘못**이다.

🔴 칸이 있는 것(미성년자 구매)은 잇는다. 칸이 없는 것(과세·상품상태·판매기간·
   제조사)은 **지어내지 말고 사유로 말한다** — 마켓별 payload 를 열어 보기 전에
   붙이면 금전 사고가 난다.
"""
from lemouton.registration.process_apply import apply_rules


class _Draft:
    """ProductDraft 흉내 — 이 시험이 보는 칸만."""

    def __init__(self, **kw):
        self.name = '테스트 상품'
        self.brand = '나이키'
        self.minor_purchasable = True
        for k, v in kw.items():
            setattr(self, k, v)


def _skips(sk, item='listing'):
    return {s['field']: s for s in sk if s['item'] == item}


# ── 칸이 있는 값: 실제로 닿는가 ─────────────────────────────────────────────

def test_19세_이상만으로_정하면_초안이_바뀐다():
    view, applied, _ = apply_rules(_Draft(), {'listing': {'minor_purchase': '19세 이상만'}})
    assert view.minor_purchasable is False, '정책을 바꿨는데 초안이 그대로다'
    a = [x for x in applied if x['field'] == 'minor_purchase']
    assert a, '무엇이 바뀌었는지 말하지 않았다'


def test_전연령이면_그대로_둔다():
    view, _, _ = apply_rules(_Draft(minor_purchasable=False),
                             {'listing': {'minor_purchase': '전연령 구매 가능'}})
    assert view.minor_purchasable is True


def test_안_정하면_손대지_않는다():
    """정책에 항목만 있고 값이 비면 초안 값이 이긴다."""
    d = _Draft(minor_purchasable=False)
    view, applied, _ = apply_rules(d, {'listing': {}})
    assert view.minor_purchasable is False
    assert not [x for x in applied if x['field'] == 'minor_purchase']


def test_모르는_값은_지어내지_않는다():
    _, applied, skipped = apply_rules(_Draft(), {'listing': {'minor_purchase': '몰라요'}})
    assert not [x for x in applied if x['field'] == 'minor_purchase']
    assert 'minor_purchase' in _skips(skipped)


# ── 칸이 없는 값: 조용히 넘기지 않는가 ──────────────────────────────────────

def test_담을_칸이_없는_값은_사유로_말한다():
    """🔴 「저장은 되는데 안 나간다」를 화면이 말해야 한다."""
    _, _, skipped = apply_rules(_Draft(), {'listing': {
        'tax_type': '면세', 'product_condition': '중고상품',
        'sale_period': '무제한', 'manufacturer_mode': '직접 입력',
        'manufacturer_fixed': '한국제화',
    }})
    got = _skips(skipped)
    for f in ('tax_type', 'product_condition', 'sale_period', 'manufacturer_mode'):
        assert f in got, f'{f} 를 조용히 넘겼다'
        assert got[f]['gap'] is True, f'{f} 가 「빠진 칸」으로 표시되지 않았다'
        assert not got[f]['blocking'], f'{f} 때문에 등록이 막히면 안 된다'


def test_기본값과_같으면_사유를_안_만든다():
    """전부 기본값인데 경고가 뜨면 화면이 사유로 뒤덮인다."""
    _, _, skipped = apply_rules(_Draft(), {'listing': {
        'tax_type': '과세', 'product_condition': '새상품',
        'sale_period': '가장 길게', 'manufacturer_mode': '브랜드와 동일',
    }})
    assert _skips(skipped) == {}


# ── 사슬 전체: 정책 → 가공 사본 → 쿠팡 payload ─────────────────────────────

def test_정책부터_쿠팡_payload_까지_실제로_이어진다():
    """🔴 중간 한 칸만 이어도 「이어졌다」고 착각한다 — 끝까지 본다."""
    import json
    from lemouton.registration.compile_coupang import compile_coupang

    class Full(_Draft):
        sale_price = 75800
        stock_quantity = 0
        detail_html = '<p>상세</p>'
        cdn_images_json = '[]'
        images_json = json.dumps(['https://r2.example.com/a.jpg'])
        options_json = json.dumps([{'color': '블랙', 'size': '250', 'stock': 3,
                                    'extra_price': 0, 'sku': 'BK-250'}],
                                  ensure_ascii=False)
        delivery_fee = 3000
        return_fee = 5000

    vendor = {'vendor_id': 'A1', 'vendor_user_id': 'u', 'return_center_code': 'RC1',
              'return_charge_name': 'r', 'return_zip': '06236', 'return_address': 'a',
              'return_address_detail': 'b', 'return_phone': '02-0000-0000',
              'outbound_place_code': 74010}

    view, _, _ = apply_rules(Full(), {'listing': {'minor_purchase': '19세 이상만'}})
    p, _ = compile_coupang(view, category_code=1, vendor=vendor)
    assert p['items'][0]['adultOnly'] == 'ADULT_ONLY'

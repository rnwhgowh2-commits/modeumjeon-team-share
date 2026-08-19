# -*- coding: utf-8 -*-
"""정책 「판매방식·통관(listing)」이 실제로 초안에 닿는가.

🔴 이 항목은 **읽는 사람이 아무도 없었다.** 사장님이 「19세 이상만」으로 바꿔도
   초안에는 그대로 전연령이 남았고, 화면은 조용했다 — 값을 못 만드는 것과
   **그 사실을 안 말하는 것은 다른 잘못**이다.

🔴 칸이 있는 것은 잇는다 — 미성년자 구매·과세구분·제조사, 그리고 자동 가격 조정
   최저가(쿠팡 전용). 칸이 없거나 **값을 새로 만들어야 하는 것**은 지어내지 말고
   사유로 말한다. 상품상태·판매기간은 고를 것이 아니라 정해진 값이라 정책 항목에서
   빠졌다(`policy/fixed_sends.py` 의 「정해져 나가는 값」이 보여준다).
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

def test_이제_못_보내는_칸은_없다():
    """[2026-08-13] 넷 다 나간다 — 「저장은 되는데 안 나간다」가 사라졌다.

    · 과세구분·제조사 → 초안 칸 + 4마켓 배선
    · 상품상태·판매기간 → 고를 것이 아니라 정해진 값이라 정책에서 뺐다
    🔴 새로 「못 보내는 칸」이 생기면 `_LISTING_NO_FIELD` 에 적어야 화면이 말한다.
      비워 둔 채 값만 늘리면 다시 조용히 사라진다.
    """
    _, _, skipped = apply_rules(_Draft(), {'listing': {
        'tax_type': '면세',
        'manufacturer_mode': '직접 입력', 'manufacturer_fixed': '한국제화',
    }})
    gaps = [s for s in skipped if s['item'] == 'listing' and s.get('gap')]
    assert gaps == [], f'못 보내는 칸이 남아 있다: {gaps}'

    from lemouton.registration.process_apply import _LISTING_NO_FIELD
    assert _LISTING_NO_FIELD == (), '목록이 비어야 하는데 남아 있다'


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


# ── 모음전 경로: 사본 → **초안 행** → 컴파일 (다리가 하나 더 있다) ──────────

def test_모음전은_초안_행을_컴파일한다_사본이_아니다():
    """🔴 대량등록은 사본을 그대로 컴파일하지만, 모음전은 사본을 **초안 행에 옮겨 담고**
    그 행을 컴파일한다(`send/runner.py` → `as_draft.upsert` → `register_draft`).

    그래서 사본에만 실린 값은 **옮겨 담는 목록에 없으면 조용히 사라진다.**
    배송비·반품비·원산지가 그랬고, 미성년자 구매도 같은 자리다.
    """
    from lemouton.send.as_draft import policy_fields_from

    view, _, _ = apply_rules(_Draft(), {'listing': {'minor_purchase': '19세 이상만'}})
    assert view.minor_purchasable is False, '사본에는 실렸다'

    got = policy_fields_from(view)
    assert 'minor_purchasable' in got, \
        '초안 행으로 옮겨 담지 않는다 — 모음전은 전연령으로 나간다'
    assert got['minor_purchasable'] is False


def test_False_를_안_정함으로_읽지_않는다():
    """🔴 「19세 이상만」은 False 다 — `if v` 로 거르면 그 값만 영영 안 옮겨진다."""
    from lemouton.send.as_draft import policy_fields_from

    class V:
        minor_purchasable = False
        delivery_fee = 0            # 0 = 무료배송, 이것도 값이다
        return_fee = None
        origin_area_code = ''

    got = policy_fields_from(V())
    assert got.get('minor_purchasable') is False
    assert got.get('delivery_fee') == 0
    assert 'return_fee' not in got and 'origin_area_code' not in got


# ── [2026-08-13] 정책 → 초안 다리 ──────────────────────────────────────────

def test_과세구분이_초안까지_간다():
    """🔴 컴파일러가 초안 칸을 읽게 됐어도, 정책값이 그 칸까지 와야 뜻이 있다."""
    view, applied, _ = apply_rules(_Draft(), {'listing': {'tax_type': '면세'}})
    assert view.tax_type == '면세'
    assert [a for a in applied if a['field'] == 'tax_type']


def test_과세구분을_안_정하면_손대지_않는다():
    d = _Draft()
    d.tax_type = '면세'                       # 사람이 상품에 직접 넣어 둔 값
    view, _, _ = apply_rules(d, {'listing': {}})
    assert view.tax_type == '면세', '정책이 조용히 과세로 덮었다'


def test_모르는_과세구분은_지어내지_않는다():
    _, applied, skipped = apply_rules(_Draft(), {'listing': {'tax_type': '영세'}})
    assert not [a for a in applied if a['field'] == 'tax_type']
    assert 'tax_type' in {s['field'] for s in skipped}


def test_제조사는_브랜드와_동일이_기본이다():
    """쿠팡 문서 권고 그대로 — 정책이 「브랜드와 동일」이면 초안엔 안 넣는다."""
    view, _, _ = apply_rules(_Draft(), {'listing': {'manufacturer_mode': '브랜드와 동일'}})
    assert getattr(view, 'manufacturer', '') == ''


def test_제조사_직접_입력이_초안까지_간다():
    view, applied, _ = apply_rules(_Draft(), {'listing': {
        'manufacturer_mode': '직접 입력', 'manufacturer_fixed': '한국제화'}})
    assert view.manufacturer == '한국제화'
    assert [a for a in applied if a['field'] == 'manufacturer_fixed']


def test_직접_입력인데_값이_비면_막지_말고_말한다():
    """🔴 등록을 멈추면 안 된다 — 브랜드로 갈음되니 사고가 아니다."""
    _, _, skipped = apply_rules(_Draft(), {'listing': {'manufacturer_mode': '직접 입력'}})
    s = [x for x in skipped if x['field'] == 'manufacturer_fixed']
    assert s and s[0]['blocking'] is False


def test_다리에_실린_칸이_초안_행으로도_옮겨진다():
    """🔴 모음전은 사본이 아니라 **초안 행**을 컴파일한다 — 옮김 목록에 있어야 한다."""
    from lemouton.send.as_draft import _POLICY_FIELDS
    for k in ('tax_type', 'manufacturer'):
        assert k in _POLICY_FIELDS, f'{k} 가 초안 행으로 안 옮겨진다'


# ── [2026-08-13] 자동 가격 조정 최저가 (쿠팡 전용) ──────────────────────────

def test_최저가_직접_입력이_초안에_닿는다():
    view, applied, _ = apply_rules(
        _Draft(auto_pricing_min=None),
        {'listing': {'_auto_pricing': {'mode': '씀 — 최저가 직접 입력',
                                       'min_price': 70000}}})
    assert view.auto_pricing_min == 70000
    assert [x for x in applied if x['field'] == 'auto_pricing_min']


def test_안_쓰면_손대지_않는다():
    view, applied, skipped = apply_rules(
        _Draft(auto_pricing_min=None), {'listing': {'_auto_pricing': {'mode': '안 씀'}}})
    assert getattr(view, 'auto_pricing_min', None) is None
    assert 'auto_pricing_min' not in _skips(skipped)


def test_직접_입력인데_값이_비면_켜지_않고_말한다():
    """🔴 최저가 없이 켜면 바닥 없이 값이 내려간다 — 켜지 않는 쪽이 안전하다."""
    view, _, skipped = apply_rules(
        _Draft(auto_pricing_min=None),
        {'listing': {'_auto_pricing': {'mode': '씀 — 최저가 직접 입력', 'min_price': 0}}})
    assert getattr(view, 'auto_pricing_min', None) is None
    s = _skips(skipped)['auto_pricing_min']
    assert s['blocking'] is False, '이것 때문에 등록이 멈추면 안 된다'


def test_마진율_계산은_지어내지_않고_못_했다고_말한다():
    """🔴 판매가를 가공 사본에서 만들면 「에러 없이 틀린 숫자」가 된다 — 금전 사고."""
    view, _, skipped = apply_rules(
        _Draft(auto_pricing_min=None),
        {'listing': {'_auto_pricing': {'mode': '씀 — 최저가를 마진율로 계산',
                                       'min_margin_pct': 5}}})
    assert getattr(view, 'auto_pricing_min', None) is None
    s = _skips(skipped)['auto_pricing_min']
    assert s['blocking'] is False and s.get('gap') is True


def test_자동_가격_조정도_초안_행으로_옮겨진다():
    from lemouton.send.as_draft import _POLICY_FIELDS
    assert 'auto_pricing_min' in _POLICY_FIELDS

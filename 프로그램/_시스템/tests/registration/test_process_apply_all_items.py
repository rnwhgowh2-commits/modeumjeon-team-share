# -*- coding: utf-8 -*-
"""[TEST] 가공 규칙 13항목 — 옵션·이미지·상세·배송·원산지·KC 까지 실제로 적용된다.

배경 (2026-07-31 사장님 지시): 「13항목 세부항목 모두 적용」.
그전까지 실제로 동작하던 것은 4항목(상품명·브랜드·금지어·태그)뿐이었고, 나머지 9항목은
화면에서 값을 넣어도 아무 일도 일어나지 않았다.

여기서 못 박는 것:
  · 저장된 드래프트는 **절대 바뀌지 않는다** (가공은 읽기 전용 사본에서만)
  · 사람이 넣은 배송비·원산지는 규칙이 **덮지 않는다** (빈 칸만 채운다)
  · 못 한 것은 전부 사유로 남는다 — 조용히 넘어가지 않는다
"""
import json
from types import SimpleNamespace

import pytest

from lemouton.registration import process_apply as PA


def _draft(**kw):
    base = dict(
        name='원본 상품명', brand='르무통',
        options_json=json.dumps([
            {'color': '블랙', 'size': '250', 'stock': 5, 'extra_price': 0, 'sku': 'A'},
            {'color': '블랙', 'size': '260', 'stock': 0, 'extra_price': 0, 'sku': 'B'},
            {'color': '화이트', 'size': '250', 'stock': None, 'extra_price': 0, 'sku': 'C'},
            {'color': '화이트', 'size': '260', 'stock': -1, 'extra_price': 0, 'sku': 'D'},
        ], ensure_ascii=False),
        images_json=json.dumps(['http://x/1.jpg', 'http://x/2.jpg', 'http://x/3.jpg',
                                'http://x/4.jpg']),
        detail_html='<p>원본 상세</p>',
        delivery_fee=None, return_fee=None, origin_area_code=None,
        sale_price=50000, source_category_path='', notice_json='{}',
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _codes(rows):
    return {r['code'] for r in rows}


def _by_code(rows, code):
    return next(r for r in rows if r['code'] == code)


# ── 옵션 (§7-9) ─────────────────────────────────────────────────────────────

def test_품절_옵션만_빠지고_모름은_남는다():
    """재고 0 만 뺀다. None(미크롤)·-1(확인불가)은 **품절이 아니다**."""
    d = _draft()
    view, applied, skipped = PA.apply_rules(d, {'options': {'exclude_soldout': True}})
    rows = json.loads(view.options_json)
    assert [r['sku'] for r in rows] == ['A', 'C', 'D'], '0 만 빠져야 한다'
    assert any(a['item'] == 'options' and a['field'] == 'exclude_soldout' for a in applied)


def test_저장된_옵션은_바뀌지_않는다():
    d = _draft()
    before = d.options_json
    PA.apply_rules(d, {'options': {'exclude_soldout': True}})
    assert d.options_json == before, '저장값을 건드렸다 — 사본에서만 가공해야 한다'


def test_품절_제외를_끄면_왜_못_끄는지_말한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'options': {'exclude_soldout': False}})
    assert 'SOLDOUT_ALWAYS_EXCLUDED' in _codes(skipped)


def test_전부_품절이면_막는다():
    d = _draft(options_json=json.dumps([
        {'color': '블랙', 'size': '250', 'stock': 0, 'extra_price': 0, 'sku': 'A'}]))
    _v, _a, skipped = PA.apply_rules(d, {'options': {'exclude_soldout': True}})
    assert _by_code(skipped, 'ALL_SOLDOUT')['blocking'] is True


def test_색상별_이미지는_자료가_없어_못_한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'options': {'color_image_link': True}})
    assert 'NO_PER_COLOR_IMAGE' in _codes(skipped)


# ── 이미지 (§7-3) ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('cfg,expect', [
    ({'mode': 'rep_only'}, 1),
    ({'mode': 'rep_plus_extra', 'extra_count': 2}, 3),
    ({'mode': 'range', 'range_from': 2, 'range_to': 4}, 3),
])
def test_올릴_이미지_장수를_고른다(cfg, expect):
    d = _draft()
    view, _a, _s = PA.apply_rules(d, {'images': cfg})
    assert len(json.loads(view.images_json)) == expect


def test_이미지_범위가_거꾸로면_막는다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(
        d, {'images': {'mode': 'range', 'range_from': 3, 'range_to': 1}})
    assert _by_code(skipped, 'BAD_RANGE')['blocking'] is True


def test_이미지_제외_브랜드는_등록을_막는다():
    d = _draft(brand='르무통')
    _v, _a, skipped = PA.apply_rules(
        d, {'images': {'mode': 'rep_only', 'excluded_brands': ['르무통']}})
    assert _by_code(skipped, 'BRAND_IMAGE_BLOCKED')['blocking'] is True


def test_정사각_자르기는_기능이_없어_못_한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(
        d, {'images': {'mode': 'rep_only', 'square_crop': True}})
    assert 'NO_CROP' in _codes(skipped)


# ── 상세설명 (§7-4) ─────────────────────────────────────────────────────────

def test_상단_원본_하단_순서로_다시_조립한다():
    d = _draft()
    view, _a, _s = PA.apply_rules(d, {'detail': {
        'mode': 'recombine', 'top_images': ['http://x/top.jpg'],
        'bottom_images': ['http://x/bot.jpg']}})
    html = view.detail_html
    assert html.index('top.jpg') < html.index('원본 상세') < html.index('bot.jpg')
    assert d.detail_html == '<p>원본 상세</p>', '저장값을 건드렸다'


def test_틀만_이면_원본_상세가_빠진다():
    d = _draft()
    view, _a, _s = PA.apply_rules(d, {'detail': {
        'mode': 'frame', 'top_images': ['http://x/top.jpg']}})
    assert '원본 상세' not in view.detail_html
    assert 'top.jpg' in view.detail_html


def test_원본_그대로면_아무것도_덧붙이지_않는다():
    d = _draft()
    view, _a, skipped = PA.apply_rules(d, {'detail': {
        'mode': 'original', 'top_images': ['http://x/top.jpg']}})
    assert getattr(view, 'detail_html') == '<p>원본 상세</p>'
    assert 'ORIGINAL_KEEPS_ALL' in _codes(skipped)


def test_소싱처_로고_가리기는_못_한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'detail': {'hide_source_logo': True}})
    assert 'NO_LOGO_MASK' in _codes(skipped)


# ── 배송 (§7-10) ────────────────────────────────────────────────────────────

def test_배송비가_비어_있으면_규칙값을_넣는다():
    d = _draft(delivery_fee=None, return_fee=None)
    view, applied, _s = PA.apply_rules(d, {'shipping': {
        'fee_mode': 'paid', 'fee_amount': 3000, 'return_fee': 5000}})
    assert view.delivery_fee == 3000
    assert view.return_fee == 5000
    assert d.delivery_fee is None, '저장값을 건드렸다'


def test_사람이_넣은_배송비는_규칙이_덮지_않는다():
    """상품마다 다르게 정한 값이 조용히 사라지면 안 된다."""
    d = _draft(delivery_fee=0)          # 0 = 「무료」로 **정한** 값이다(빈칸 아님)
    view, _a, skipped = PA.apply_rules(d, {'shipping': {
        'fee_mode': 'paid', 'fee_amount': 3000}})
    assert view.delivery_fee == 0
    assert 'KEEP_HUMAN_VALUE' in _codes(skipped)


def test_조건부_무료배송은_보낼_자리가_없어_막는다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'shipping': {
        'fee_mode': 'free_over', 'fee_amount': 3000, 'free_over': 50000}})
    assert _by_code(skipped, 'NO_FREE_OVER_FIELD')['blocking'] is True


def test_제주_도서산간_묶음배송_출고일은_칸이_없다고_말한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'shipping': {
        'fee_mode': 'free', 'jeju_extra': 3000, 'island_extra': 5000,
        'bundle': True, 'ship_days': 3}})
    fields = {s['field'] for s in skipped if s['code'] == 'NO_SHIPPING_FIELD'}
    assert fields == {'jeju_extra', 'island_extra', 'bundle', 'ship_days'}


# ── 원산지 (§7-6) · KC (§7-7) ───────────────────────────────────────────────

def test_원산지_고정값은_빈_칸만_채운다():
    d = _draft(origin_area_code=None)
    view, _a, _s = PA.apply_rules(d, {'origin': {'mode': 'fixed',
                                                 'fixed_value': '0200037'}})
    assert view.origin_area_code == '0200037'

    d2 = _draft(origin_area_code='0200038')
    view2, _a2, skipped2 = PA.apply_rules(d2, {'origin': {'mode': 'fixed',
                                                          'fixed_value': '0200037'}})
    assert view2.origin_area_code == '0200038'
    assert 'KEEP_HUMAN_VALUE' in _codes(skipped2)


def test_원산지_고정인데_값이_비면_막는다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'origin': {'mode': 'fixed', 'fixed_value': ''}})
    assert _by_code(skipped, 'NO_FIXED_ORIGIN')['blocking'] is True


def test_KC는_담을_칸이_없다고_말한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'kc': {'safety_target': True,
                                                'collect_kc_no': True}})
    assert {'NO_KC_FIELD', 'NO_KC_COLLECT'} <= _codes(skipped)


# ── 담당처가 따로 있는 항목 (§7-5 / §7-8 / §7-2) ────────────────────────────

def test_판매가_마진율은_계산에_안_쓰인다고_말한다():
    out = PA.crosscheck_delegated({'price': {'mode': 'margin_rate', 'margin_rate': 25}})
    assert 'PRICE_BY_MARGIN_ENGINE' in _codes(out)


def test_고정_판매가가_상품_판매가와_다르면_말한다():
    out = PA.crosscheck_delegated(
        {'price': {'mode': 'fixed_amount', 'fixed_amount': 90000}}, sale_price=50000)
    assert 'PRICE_NOT_APPLIED' in _codes(out)


def test_기본_카테고리로_떨구지_않는다():
    out = PA.crosscheck_delegated(
        {'category': {'auto_map': True, 'on_fail': 'default_category'}},
        category_code='123')
    assert 'NO_DEFAULT_CATEGORY' in _codes(out)


def test_카테고리를_못_찾으면_막는다():
    out = PA.crosscheck_delegated(
        {'category': {'auto_map': True, 'on_fail': 'hold'}}, category_code=None)
    assert _by_code(out, 'CATEGORY_HELD')['blocking'] is True


def test_고시_기본값이_하나도_안_채워지면_알린다():
    out = PA.crosscheck_delegated(
        {'notice': {'auto_from_crawl': True, 'warn_on_missing': True}},
        notice_filled_from={})
    assert 'NOTICE_NOT_FILLED' in _codes(out)


# ── 사본 규율 ───────────────────────────────────────────────────────────────

def test_바뀐_칸만_가공됨으로_센다():
    d = _draft()
    view, _a, _s = PA.apply_rules(d, {'images': {'mode': 'rep_only'}})
    assert view.processed_fields == ('images_json',)


def test_아무것도_안_바뀌면_원본을_그대로_돌려준다():
    d = _draft()
    view, _a, _s = PA.apply_rules(d, {})
    assert view is d


# ── 기능 공백 vs 상품 문제 ──────────────────────────────────────────────────

def test_기능이_없어서_못_한_것은_상품_문제와_섞이지_않는다():
    """정사각 자르기처럼 기본값이 켜진 항목은 상품마다 상시로 뜬다 —
    상품 문제와 섞으면 진짜 문제가 그 속에 묻힌다."""
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'images': {'mode': 'rep_only',
                                                    'square_crop': True}})
    gaps = PA.capability_gaps(skipped)
    issues = PA.product_issues(skipped)
    assert 'NO_CROP' in _codes(gaps)
    assert 'NO_CROP' not in _codes(issues)


def test_사람이_넣은_값을_지킨_것은_상품_문제로_남는다():
    """이건 상품 화면에서 고칠 수 있는 일이라 접어 두면 안 된다."""
    d = _draft(delivery_fee=0)
    _v, _a, skipped = PA.apply_rules(d, {'shipping': {'fee_mode': 'paid',
                                                      'fee_amount': 3000}})
    assert 'KEEP_HUMAN_VALUE' in _codes(PA.product_issues(skipped))


# ── 노션 (2)(3) 에 있는데 칸이 없던 것들 (2026-07-31) ───────────────────────

def test_AS_안내는_빈_칸만_채운다():
    """스마트스토어는 A/S 가 없으면 등록을 거부한다 — 정책에 적어두면 채워진다."""
    d = _draft(after_service_phone=None, after_service_guide='')
    view, applied, _s = PA.apply_rules(d, {'shipping': {
        'fee_mode': 'free', 'as_phone': '02-1234-5678',
        'as_guide': '수령 후 7일 내 반품 가능합니다.'}})
    assert view.after_service_phone == '02-1234-5678'
    assert view.after_service_guide.startswith('수령 후')
    assert d.after_service_phone is None, '저장값을 건드렸다'


def test_사람이_넣은_AS_번호는_덮지_않는다():
    d = _draft(after_service_phone='070-1111-2222', after_service_guide='기존 안내')
    view, _a, skipped = PA.apply_rules(d, {'shipping': {
        'fee_mode': 'free', 'as_phone': '02-1234-5678'}})
    assert view.after_service_phone == '070-1111-2222'
    assert 'KEEP_HUMAN_VALUE' in _codes(skipped)


def test_출하지_회송지_택배사_교환비는_보낼_자리가_없다고_말한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'shipping': {
        'fee_mode': 'free', 'ship_from': '서울시 강남구', 'return_to': '경기도 성남시',
        'courier': 'CJ대한통운', 'exchange_fee': 6000}})
    fields = {s['field'] for s in skipped if s['code'] == 'NO_SHIPPING_FIELD'}
    assert {'ship_from', 'return_to', 'courier', 'exchange_fee'} <= fields
    # 상품 문제가 아니라 기능 공백이다
    assert {'ship_from'} <= {s['field'] for s in PA.capability_gaps(skipped)}


def test_옵션_추가금을_판매가에_합칠_수_없다고_말한다():
    d = _draft()
    _v, _a, skipped = PA.apply_rules(d, {'options': {'extra_price_mode': 'into_price'}})
    assert 'NO_EXTRA_INTO_PRICE' in _codes(skipped)


# ── 옵션 축 구성 (노션 「(1) 마켓별 옵션 1/2/3축 구성 정책」) ────────────────

def test_기본은_색상_사이즈_두_갈래다():
    d = _draft()
    view, _a, _s = PA.apply_rules(d, {'options': {}})
    assert view.process_option_axis == 'two'


def test_한_갈래로_합칠_수_있다():
    d = _draft()
    view, applied, _s = PA.apply_rules(d, {'options': {'axis': 'one'}})
    assert view.process_option_axis == 'one'
    assert any(a['field'] == 'axis' for a in applied)


def test_3축으로_올릴_수_있다():
    """[2026-08-13] 열었다 — 예전엔 `NO_MODEL_AXIS` 로 2축 강등이었다.

    강등 사유가 「옵션에 모델명을 담는 칸이 없습니다」였는데, **마켓 탓이 아니라
    우리 칸이 없던 것**이었다. 칸을 만들었다(`policy/to_payload._options_json`).
    마켓 근거(스스 개발자센터 원문, 판매처 지도 수록):
      「최대 등록 가능한 옵션 개수는 조합형은 3개, 지점형은 4개입니다.」
    쪼개는 모양은 tests/registration/test_options_axis3.py 가 지킨다.
    """
    d = _draft()
    view, applied, skipped = PA.apply_rules(d, {'options': {'axis': 'three'}})
    assert view.process_option_axis == 'three'
    assert 'NO_MODEL_AXIS' not in _codes(skipped)
    assert any(a['field'] == 'axis' for a in applied)


def test_모르는_축은_지어내지_않고_기본으로_간다():
    d = _draft()
    view, _a, skipped = PA.apply_rules(d, {'options': {'axis': 'four'}})
    assert view.process_option_axis == 'two'
    assert 'UNKNOWN_AXIS' in _codes(skipped)


def test_축은_저장_칸이_아니라_바뀐_칸으로_세지_않는다():
    d = _draft()
    view, _a, _s = PA.apply_rules(d, {'options': {'axis': 'one'}})
    assert 'process_option_axis' not in view.processed_fields

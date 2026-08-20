# -*- coding: utf-8 -*-
"""즉시할인 미리보기 — **서버가 준 판매가**에 붙는지 끝까지 확인.

사장님 「검증해줘」(2026-08-06). 라이브에서는 정책 3개 모두 고른 계산 방식의 값이
비어 서버가 계산을 거부해(안전장치 정상) 실숫자를 볼 수 없었다. 사장님 실데이터를
고치지 않고, **같은 경로**(preview_for_model → rows[].policy_price → 화면)를 여기서 돈다.

🔴 이 검사가 지키는 것 — 화면이 값을 **새로 계산하지 않는다**.
   화면이 따로 계산하면 미리보기와 실제 업로드가가 갈린다(이 저장소에선 곧 금전 사고).
"""
import re

from lemouton.policy.discount import discount_of, exposed_price


def test_서버가_준_판매가로_고객가가_계산된다():
    """preview → policy_price → (즉시할인) → 고객가. 산식은 한 곳에서만."""
    from lemouton.policy.preview import preview_for_model

    values = {'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 10,
                        'fee_rate': 6, 'discount_unit': 'WON',
                        'discount_value': 1400}}

    def fake_matrix(_mc):
        return {'ok': True, 'options': [
            {'sku': 'SKU-A', 'color': '블랙', 'size': '230', 'ss_price': 150000},
            {'sku': 'SKU-B', 'color': '블랙', 'size': '240', 'ss_price': 150000}]}

    import lemouton.orders.price_diff as pd
    orig = pd._current_purchase
    pd._current_purchase = lambda s, skus, matrix_loader=None: (
        {'SKU-A': 100000, 'SKU-B': 120000}, {})
    try:
        out = preview_for_model(None, model_code='M1', values=values,
                                market='smartstore', matrix_loader=fake_matrix)
    finally:
        pd._current_purchase = orig

    assert out['ok'] is True, out.get('reason')
    prices = [r['policy_price'] for r in out['rows']]
    assert all(isinstance(p, int) for p in prices), prices

    # 화면이 쓰는 기준 = 서버가 준 값들의 **최저**(detail.html 과 같은 규칙)
    base = min(prices)
    disc = discount_of(values)
    assert disc == {'value': 1400, 'unitType': 'WON'}
    assert exposed_price(base, disc) == base - 1400


def test_매입가를_모르는_옵션은_계산에_안_들어간다():
    """🔴 지어낸 값으로 미리보기를 채우면 그 숫자가 그대로 마켓에 나간다."""
    from lemouton.policy.preview import preview_for_model

    values = {'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 10,
                        'fee_rate': 6}}

    def fake_matrix(_mc):
        return {'ok': True, 'options': [
            {'sku': 'SKU-A', 'color': '블랙', 'size': '230'},
            {'sku': 'SKU-B', 'color': '블랙', 'size': '240'}]}

    import lemouton.orders.price_diff as pd
    orig = pd._current_purchase
    pd._current_purchase = lambda s, skus, matrix_loader=None: (
        {'SKU-A': 100000}, {'SKU-B': '크롤 실패'})     # B 는 매입가 모름
    try:
        out = preview_for_model(None, model_code='M1', values=values,
                                market='smartstore', matrix_loader=fake_matrix)
    finally:
        pd._current_purchase = orig

    by = {r['sku']: r['policy_price'] for r in out['rows']}
    assert isinstance(by['SKU-A'], int)
    assert by['SKU-B'] is None, '모르는 매입가로 판매가를 지어내면 안 된다'
    # 화면은 숫자인 것만 골라 최저를 잡는다 → None 이 섞여도 안 깨진다
    nums = [v for v in by.values() if isinstance(v, int)]
    assert min(nums) == by['SKU-A']


def _tpl():
    from pathlib import Path
    return (Path(__file__).resolve().parents[2] / 'webapp' / 'templates'
            / 'policy' / 'detail.html').read_text(encoding='utf-8')


def test_화면은_서버값만_쓴다():
    """미리보기 기준값이 rows[].policy_price 에서만 온다(자체 계산 금지)."""
    src = _tpl()
    m = re.search(r'const base = rows\.map\(r => r\.(\w+)\)', src)
    assert m and m.group(1) == 'policy_price', '기준값이 서버 판매가가 아니다'
    assert 'discBase = base.length ? Math.min.apply(null, base) : null' in src


def test_화면_계산은_한_줄뿐이고_바닥이_0이다():
    """깎기 자체는 화면에서 하되(입력 즉시 반응), 산식은 서버 규칙과 같아야 한다."""
    src = _tpl()
    assert "Math.round(discBase * (100 - val) / 100)" in src   # 정률
    assert "Math.max(discBase - val, 0)" in src                # 정액 · 바닥 0
    # 파이썬 쪽 단일 원천과 같은 결과인지 대조
    assert exposed_price(144500, {'value': 1400, 'unitType': 'WON'}) == 143100
    assert exposed_price(144500, {'value': 10, 'unitType': 'PERCENT'}) == 130050

"""[2026-07-19] 소싱 원가 = 최종매입가(혜택 차감 후) — 표면노출가 아님.

사장님 확정: "원가는 이전에도 최종매입가였어. 원가로부터 마진을 붙이는 거야.
그리고 판매가가 고정 필요할 때는 지정가로 하면 되고."

여기서 고정하는 계약 4가지:
  1. 원가는 compute_breakdown 의 final_price 에서 온다 (표면가 아님).
  2. 최종매입가를 못 구하면 None — 표면가로 대체하지 않는다(폴백 금지).
  3. 최저가 winner 판정도 최종매입가 기준 (표면가 최저 ≠ 실제 최저일 수 있음).
  4. 지정가(고정 판매가)는 원가와 무관하게 그대로 — 이번 변경에 안 흔들린다.
  5. N+1 금지 — 소싱처 N개라도 _build_breakdown_cache 는 1회.
"""
import types

import pytest

from webapp.routes.api_pricing import (
    _attach_final_purchase, _pick_cheapest_buyable, _resolve_sourcing_cost,
)
from lemouton.uploader.preview import _resolve_option_upload


def _tpl(**kw):
    """소싱 side = rate 모드(원가 연동) 기본. 지정가 테스트는 fixed 로 덮어쓴다."""
    base = dict(
        rounding_unit=100, price_source_priority='template', boxhero_purchase_price=0,
        ss_mode_sourcing='rate', ss_rate_sourcing=0.10, ss_amount_sourcing=0,
        ss_external_sale_price=0, ss_boxhero_sale_price=0,
        ss_fee_rate=0.06, ss_delivery_fee=0,
        coupang_mode_sourcing='rate', coupang_rate_sourcing=0.10, coupang_amount_sourcing=0,
        coupang_external_sale_price=0, coupang_boxhero_sale_price=0,
        coupang_fee_rate=0.1155, coupang_delivery_fee=0,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _opt(**kw):
    base = dict(
        boxhero_avg_purchase_price=0, purchase_priority='auto',
        src_fixed_ss_active=False, src_fixed_ss_price=0,
        src_fixed_cp_active=False, src_fixed_cp_price=0,
        pur_fixed_ss_active=False, pur_fixed_ss_price=0,
        pur_fixed_cp_active=False, pur_fixed_cp_price=0,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _src(price, final=None, **kw):
    d = {'source_id': 1, 'crawled_price': price, 'last_status': 'ok',
         'final_purchase_price': final}
    d.update(kw)
    return d


# ── 1·2. 원가 = 최종매입가 / 폴백 금지 ────────────────────────────────────────

def test_upload_price_uses_final_purchase_not_surface():
    """표면가가 아니라 최종매입가로 마진을 붙인다 → 판매가가 그만큼 낮아진다."""
    tpl = _tpl()
    high = _resolve_option_upload(_opt(), None, tpl, [_src(100000, 100000)], 0)
    low = _resolve_option_upload(_opt(), None, tpl, [_src(100000, 80000)], 0)
    # 표면가는 같은데 혜택이 큰 쪽(최종매입가 80,000)이 더 싸게 나가야 한다.
    assert low['upload']['ss'] < high['upload']['ss']
    assert low['upload']['cp'] < high['upload']['cp']


def test_no_surface_fallback_when_final_missing():
    """최종매입가 미상 → 가격 없음(None). 표면가로 메우면 원가 과대계상."""
    r = _resolve_option_upload(_opt(), None, _tpl(), [_src(100000, None)], 0)
    assert r['upload']['ss'] is None
    assert r['upload']['cp'] is None


# ── 3. winner 판정도 최종매입가 기준 ─────────────────────────────────────────

def test_cheapest_picked_by_final_not_surface():
    """표면가는 A 가 싸도, 혜택 반영 후엔 B 가 실제로 더 싸면 B 가 winner."""
    a = _src(100000, 99000, source_id=1)   # 혜택 1천원
    b = _src(105000, 90000, source_id=2)   # 혜택 1만5천원 → 실제 최저
    assert _pick_cheapest_buyable([a, b]) is b
    assert _resolve_sourcing_cost(_pick_cheapest_buyable([a, b])) == 90000


# ── 4. 지정가(고정 판매가) 보존 ──────────────────────────────────────────────

def test_option_level_fixed_price_unaffected_by_cost_change():
    """옵션 지정가 토글 = 사용자 확정값. 원가가 뭐든 그대로 나간다."""
    tpl = _tpl()
    o = _opt(src_fixed_ss_active=True, src_fixed_ss_price=149000,
             src_fixed_cp_active=True, src_fixed_cp_price=159000)
    for final in (100000, 80000, 50000):
        r = _resolve_option_upload(o, None, tpl, [_src(100000, final)], 0)
        assert r['upload']['ss'] == 149000
        assert r['upload']['cp'] == 159000


def test_template_fixed_mode_unaffected_by_cost_change():
    """템플릿 소싱 지정가(mode='fixed') 도 원가와 무관하게 고정."""
    tpl = _tpl(ss_mode_sourcing='fixed', ss_external_sale_price=139000,
               coupang_mode_sourcing='fixed', coupang_external_sale_price=149000)
    for final in (100000, 70000):
        r = _resolve_option_upload(_opt(), None, tpl, [_src(100000, final)], 0)
        assert r['upload']['ss'] == 139000
        assert r['upload']['cp'] == 149000


# ── 5. N+1 금지 ──────────────────────────────────────────────────────────────

def test_attach_final_purchase_builds_cache_once(monkeypatch):
    """소싱처 셀이 N개라도 _build_breakdown_cache 는 1회, compute_breakdown 은 셀당 1회.

    (옵션마다 캐시를 새로 만들면 매트릭스가 N+1 로 수십 초 느려진다.)
    """
    import webapp.routes.api_benefits as ab

    calls = {'cache': 0, 'bd': 0}

    def fake_cache(session, items, sp_rows=None):
        calls['cache'] += 1
        return {'link_by': {}, 'sp_by_norm': {}, 'sp_by_id': {},
                'tpl_by_src': {}, 'ovr_by': {}, 'prefs': []}

    def fake_bd(session, *, sku, source_id, sale_price, _cache=None,
                source_product_id=None, **kw):
        calls['bd'] += 1
        assert _cache is not None, 'compute_breakdown 에 캐시가 안 넘어감 = N+1'
        return {'final_price': int(sale_price) - 1000}

    monkeypatch.setattr(ab, '_build_breakdown_cache', fake_cache)
    monkeypatch.setattr(ab, 'compute_breakdown', fake_bd)

    sku_to_sources = {
        f'SKU{i}': [_src(100000 + i, None, source_id=j) for j in (1, 2, 3)]
        for i in range(10)
    }
    _attach_final_purchase(None, sku_to_sources)

    assert calls['cache'] == 1, f"캐시 {calls['cache']}회 — 1회여야 함(N+1)"
    assert calls['bd'] == 30
    assert sku_to_sources['SKU0'][0]['final_purchase_price'] == 99000


def test_attach_final_purchase_leaves_none_on_failure(monkeypatch):
    """breakdown 이 터져도 표면가로 채우지 않는다 — None 유지(폴백 금지)."""
    import webapp.routes.api_benefits as ab

    monkeypatch.setattr(ab, '_build_breakdown_cache',
                        lambda s, items, sp_rows=None: {})

    def boom(session, **kw):
        raise RuntimeError('혜택 계산 실패')

    monkeypatch.setattr(ab, 'compute_breakdown', boom)

    srcs = {'SKU1': [_src(100000, None)]}
    _attach_final_purchase(None, srcs)
    assert srcs['SKU1'][0]['final_purchase_price'] is None


def test_attach_final_purchase_skips_uncrawled_cells():
    """표면가 없는 셀(크롤 실패·매칭실패)은 계산 대상 자체가 아니고 None 으로 남는다."""
    srcs = {'SKU1': [{'source_id': 1, 'crawled_price': None},
                     {'source_id': None, 'crawled_price': 100000}]}
    _attach_final_purchase(None, srcs)   # DB 접근 없이 통과해야 함
    assert all(d['final_purchase_price'] is None for d in srcs['SKU1'])

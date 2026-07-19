"""[2026-06-05] 회귀 — 크롤 실패(error) 소싱처의 옛 가격(stale)이 절대
'성공·원가·최저가·업로드'로 쓰이지 않음을 검증. (거짓 100% / 금전 손실 재발 방지)

배경: 무신사·롯데온 크롤이 error 인데 last_price>0(옛 가격 잔존)이라,
  · 상단 진행률 카드가 100%로 거짓 표시
  · 매트릭스 원가 폴백이 stale 가격을 끌어씀
  · 업로드 미리보기가 status 확인 없이 stale 가격을 원가로 씀
3곳을 is_crawl_valid 단일 게이트로 통일했다. 이 테스트가 게이트를 고정한다.
"""
import types

from lemouton.pricing.unified import is_crawl_valid
from webapp.routes.api_pricing import _pick_cheapest_buyable
from lemouton.uploader.preview import _resolve_option_upload


# ── 단일 게이트 ──────────────────────────────────────────────
def test_is_crawl_valid_rejects_error_even_with_price():
    assert is_crawl_valid(122850, 'error') is False     # 핵심: 가격 있어도 error 면 무효
    assert is_crawl_valid(122850, 'ok') is True
    assert is_crawl_valid(122850, None) is True          # 상태 미상(legacy price_cached) 은 허용
    assert is_crawl_valid(0, 'ok') is False
    assert is_crawl_valid(None, 'ok') is False


# ── 매트릭스/최저가 원가 선정 ─────────────────────────────────
def test_cheapest_excludes_error_as_sole_source():
    # 유일 소싱처가 크롤 실패 → 폴백으로도 stale 가격을 쓰지 않음 → None
    assert _pick_cheapest_buyable([{'crawled_price': 122850, 'last_status': 'error'}]) is None


def test_cheapest_prefers_valid_over_cheaper_error():
    # error 가 더 싸도(100) 유효한 200 을 선택
    src = [{'crawled_price': 100, 'last_status': 'error'},
           {'crawled_price': 200, 'last_status': 'ok'}]
    assert _pick_cheapest_buyable(src)['crawled_price'] == 200


def test_cheapest_soldout_but_valid_allowed_as_fallback():
    # 품절(stock_out)이지만 크롤 성공 → 실가격 유효 → 폴백 후보 허용
    src = [{'crawled_price': 150, 'last_status': 'ok', 'stock_out': True}]
    assert _pick_cheapest_buyable(src)['crawled_price'] == 150


# ── 업로드 미리보기 원가 ──────────────────────────────────────
def _tpl(**kw):
    base = dict(
        boxhero_purchase_price=95000, price_source_priority='template', rounding_unit=100,
        ss_mode_sourcing='amount', ss_rate_sourcing=0.0945, ss_amount_sourcing=5000,
        ss_mode_purchase='fixed', ss_rate_purchase=0.0945, ss_amount_purchase=0,
        ss_external_sale_price=0, ss_boxhero_sale_price=116900,
        ss_fee_rate=0.0945, ss_delivery_fee=0,
        coupang_mode_sourcing='fixed', coupang_rate_sourcing=0.1242, coupang_amount_sourcing=0,
        coupang_mode_purchase='fixed', coupang_rate_purchase=0.1242, coupang_amount_purchase=0,
        coupang_external_sale_price=133900, coupang_boxhero_sale_price=128900,
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


def test_upload_ignores_error_source_cost():
    tpl = _tpl()
    STALE = 122850
    # 크롤 실패 + 옛 가격 → 원가로 쓰면 안 됨 → 무소스(템플릿 95000) 와 동일해야 함
    # [2026-07-19] 원가 = 최종매입가(final_purchase_price, 매트릭스가 compute_breakdown 으로 주입).
    err = _resolve_option_upload(
        _opt(), None, tpl, [{'source_id': 'lemouton', 'crawled_price': STALE,
                             'final_purchase_price': STALE, 'last_status': 'error'}], 0)
    none = _resolve_option_upload(_opt(), None, tpl, [], 0)
    assert err['src']['ss'] == none['src']['ss']

    # 같은 가격이라도 status=ok 면 원가로 쓰여 결과가 달라져야 함 (게이트가 status 로 구분함을 증명)
    ok = _resolve_option_upload(
        _opt(), None, tpl, [{'source_id': 'lemouton', 'crawled_price': STALE,
                             'final_purchase_price': STALE, 'last_status': 'ok'}], 0)
    assert ok['src']['ss'] != none['src']['ss']

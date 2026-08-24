# -*- coding: utf-8 -*-
"""사입(우리 창고) 재고로도 팔 수 있나 (2026-08-24 사장님 확정).

■ 사장님 말씀 그대로
  「기본적으로 소싱처 URL 의 재고를 따르면 되고, 수기로 입력하는 경우는 사입용으로
   재고 입력할 경우임 … 재고관리에서 수량을 컨트롤 … 해당 재고는 사입용으로 구분이
   되어야 함 … 관련한 사입 재고 수량은 프로그램 전체에 반영되어야 함.」

🔴 이 파일이 막는 사고
  ① 전송이 **소싱 재고만** 봐서, 창고에 있는데도 소싱처가 품절이면 그 옵션이
     통째로 빠졌다 — 팔 수 있는 물건을 못 팔았다.
  ② 반대로 사입 재고가 소싱 재고를 **덮으면** 안 된다. 소싱으로 보낼 수 있으면
     그대로 둔다(사입은 소싱이 막혔을 때 살리는 길이다).
  ③ 재고를 지어내지 않는다 — 사입 수량은 재고관리 원장의 실제 값이고, 화면(매트릭스)이
     이미 같은 값을 보여 준다. 최상위 규칙이 금지하는 것은 **소싱 재고의 추정·폴백**이다.
"""
import json

import pytest


class _가짜매트릭스:
    """`_option_matrix_data` 를 대신한다 — 마켓·DB 없이 판정만 본다."""

    def __init__(self, options):
        self.options = options

    def __call__(self, code, **kw):
        return {'ok': True, 'options': self.options}


@pytest.fixture()
def 옵션칸(monkeypatch):
    """`_options_json` 을 직접 부르되 DB 조회는 가짜로 막는다."""
    from lemouton.policy import to_payload as TP

    def 만들기(*, sources, purchase, sku='SKU1'):
        class _O:
            canonical_sku = sku
            color_display = '블랙'
            color_code = 'BK'
            size_display = '270'
            size_code = '270'
            model_code = 'M1'
            image_url = 'https://r2/a.jpg'
            is_active = True

        monkeypatch.setattr(TP, '_options_json', TP._options_json)
        # 옵션 목록·이름 조회를 가짜로 — 판정 로직만 본다
        import types
        결과 = []

        def _가짜(session, set_id, stock_by_sku=None, purchase_by_sku=None):
            cell = {'sku': sku, 'color': '블랙', 'size': '270', 'model': '',
                    'image_url': 'https://r2/a.jpg', 'active': True}
            srcs = (stock_by_sku or {}).get(sku)
            if srcs:
                from lemouton.sourcing.option_sources import sendable_for_option
                ok, qty, why, picked = sendable_for_option([dict(x) for x in srcs])
                if ok:
                    cell['stock'] = qty
                    cell['buy_source'] = (picked or {}).get('site')
                else:
                    cell['stock_blocked'] = why
            사입 = (purchase_by_sku or {}).get(sku)
            if 사입:
                _소싱 = cell.get('stock', '없음')
                if _소싱 == '없음' or _소싱 == 0:
                    cell['stock'] = int(사입)
                    cell['buy_source'] = 'purchase'
                    cell.pop('stock_blocked', None)
            결과.append(cell)
            return json.dumps(결과, ensure_ascii=False)

        return json.loads(_가짜(None, 1, sources, purchase))[0]

    return 만들기


def test_소싱이_되면_소싱_재고를_쓴다(옵션칸):
    """🔴 사입이 소싱을 덮으면 안 된다 — 소싱으로 팔 수 있으면 그대로."""
    cell = 옵션칸(sources={'SKU1': [{'site': 'musinsa', 'crawled_price': 50000,
                                    'last_status': 'ok', 'stock_out': False,
                                    'crawled_stock': 7}]},
                purchase={'SKU1': 99})
    assert cell['stock'] == 7
    assert cell['buy_source'] == 'musinsa'


def test_소싱이_품절이면_사입_재고로_살린다(옵션칸):
    """창고에 있는데 소싱처 사정으로 판매가 멈추면 안 된다."""
    cell = 옵션칸(sources={'SKU1': [{'site': 'musinsa', 'crawled_price': 50000,
                                    'last_status': 'ok', 'stock_out': True,
                                    'crawled_stock': 0}]},
                purchase={'SKU1': 5})
    assert cell['stock'] == 5
    assert cell['buy_source'] == 'purchase', '어디서 온 재고인지 구분돼야 한다'
    assert 'stock_blocked' not in cell, '사입으로 보낼 수 있으니 막을 이유가 없다'


def test_소싱처가_아예_없어도_사입으로_판다(옵션칸):
    """사입 전용 상품 — 예전엔 통째로 빠졌다."""
    cell = 옵션칸(sources={}, purchase={'SKU1': 3})
    assert cell['stock'] == 3
    assert cell['buy_source'] == 'purchase'


def test_사입도_소싱도_없으면_재고_칸을_안_넣는다(옵션칸):
    """🔴 0 을 넣으면 품절로 나간다 — 「모른다」와 「없다」는 다르다."""
    cell = 옵션칸(sources={}, purchase={})
    assert 'stock' not in cell


def test_사입_재고가_0이면_안_살린다(옵션칸):
    """0개를 가졌다는 건 못 판다는 뜻이다."""
    cell = 옵션칸(sources={}, purchase={'SKU1': 0})
    assert 'stock' not in cell


# ── 실제 배선이 이어졌나 ──────────────────────────────────────────────────

def test_구성_사본이_사입_재고를_거둔다():
    """🔴 이 다리가 없으면 판정을 아무리 잘해도 사입 재고가 도달을 못 한다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'policy' / 'to_payload.py').read_text(encoding='utf-8')
    코드만 = chr(10).join(l for l in 소스.splitlines()
                        if not l.lstrip().startswith('#'))
    assert 'def _purchase_stock_by_sku' in 코드만
    assert '_purchase_stock_by_sku(session, ps.model_code)' in 코드만
    assert "purchase_by_sku" in 코드만


def test_사입_수량은_매트릭스가_보여_주는_그_값이다():
    """화면과 전송이 다른 숫자를 쓰면 사장님이 어느 쪽을 믿어야 할지 모른다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'policy' / 'to_payload.py').read_text(encoding='utf-8')
    블록 = 소스.split('def _purchase_stock_by_sku')[1].split('def ')[0]
    assert '_option_matrix_data' in 블록, '전송이 재고를 새로 계산하고 있다'
    assert "o.get('purchase_stock')" in 블록


def test_소싱이_있음_수량미상이면_안_덮는다(옵션칸):
    """🔴 「있음」인데 사입 수량으로 덮으면 팔 수 있는 양이 줄어든다."""
    cell = 옵션칸(sources={'SKU1': [{'site': 'musinsa', 'crawled_price': 50000,
                                    'last_status': 'ok', 'stock_out': False,
                                    'crawled_stock': None}]},
                purchase={'SKU1': 2})
    assert cell['buy_source'] == 'musinsa'
    assert cell['stock'] is None, '소싱이 「있음」이면 수량 미상 그대로 둔다'


def test_소싱_수량에_사입을_더하지_않는다(옵션칸):
    """🔴 둘을 합치면 실제보다 많이 팔릴 수 있다(오버셀). 적게 파는 쪽이 안전하다."""
    cell = 옵션칸(sources={'SKU1': [{'site': 'musinsa', 'crawled_price': 50000,
                                    'last_status': 'ok', 'stock_out': False,
                                    'crawled_stock': 3}]},
                purchase={'SKU1': 5})
    assert cell['stock'] == 3, '3+5=8 로 부풀리면 안 된다'

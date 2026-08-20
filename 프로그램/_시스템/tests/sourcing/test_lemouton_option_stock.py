# -*- coding: utf-8 -*-
"""tests/sourcing/test_lemouton_option_stock.py

르무통 정적 크롤러가 Cafe24 ``option_stock_data`` 를 파싱해 색상별 **실제 판매
사이즈만** 수집하는지 검증 (회귀 방지).

배경(버그): 기존 정적 파서는 ``ul.ec-product-button`` 버튼 목록의 색상 × 사이즈
데카르트 곱을 만들어, 그 색상이 실제로 팔지 않는 사이즈까지 ``stock=999`` 센티넬로
SourceOption 에 적재했다 (예: 오렌지 220~290mm 전체). Playwright 미설치 서버(AWS)는
이 정적 경로로 폴백하므로 라이브에서 그대로 노출됨.

실제 제품 130 구조(라이브 확인):
  · 블랙/다크네이비/아이보리/그레이 → 14 사이즈
  · 오렌지/라이트블루/스카이블루/크림핑크 → 8 사이즈 (오렌지 250mm 품절)
  · 올리브그린 → 14 사이즈 (235mm·240mm 품절)
Cafe24 ``option_stock_data`` 는 색상별 실제 조합만 키로 가지므로 미판매 사이즈가
원천 배제되고 품절(stock_number=0)·실수량이 정확하다.
"""
import json

from lemouton.sourcing.crawlers.lemouton import (
    _parse_option_stock_data,
    LemoutonCrawler,
)


def _make_option_stock_html(combos: dict) -> str:
    """{code: entry} → Cafe24 와 동일한 ``var option_stock_data = '...';`` 형태 HTML.

    실제 페이지처럼 JSON 을 JS 단일따옴표 문자열로 이스케이프(``\\"`` · ``\\uXXXX``)한다.
    """
    # ensure_ascii=True → 한글이 \uXXXX 로 (실제 Cafe24 포맷과 동일)
    json_text = json.dumps(combos, ensure_ascii=True)
    # JS 단일따옴표 문자열 본문으로 이스케이프: json.dumps 로 한 번 더 감싼 뒤 바깥 따옴표 제거
    js_body = json.dumps(json_text, ensure_ascii=True)[1:-1]
    return (
        "<html><head><title>테스트</title></head><body>"
        "<script>var option_type = 'T';"
        f"var option_stock_data = '{js_body}';</script>"
        "</body></html>"
    )


def _entry(color, size, stock, *, selling="T", display="T", price=116900):
    return {
        "stock_price": "0.00",
        "use_stock": True,
        "use_soldout": "T",
        "is_display": display,
        "is_selling": selling,
        "option_price": price,
        "option_value": f"{color}-{size}",
        "stock_number": stock,
        "option_value_orginal": [color, size],
        "option_name_original": ["색상", "사이즈선택"],
    }


# ─────────────────────────────────────────────────────────────────
#  _parse_option_stock_data — 핵심 회귀 테스트
# ─────────────────────────────────────────────────────────────────

def test_excludes_unsold_sizes_per_color():
    """오렌지는 8 사이즈만, 블랙은 14 사이즈 — 데카르트 곱(색상별 전 사이즈) 금지."""
    combos = {}
    black_sizes = [f"{s}mm" for s in range(230, 290 + 1, 5)]  # 14 사이즈
    orange_sizes = [f"{s}mm" for s in range(220, 255 + 1, 5)]  # 8 사이즈 (220~255)
    for i, s in enumerate(black_sizes):
        combos[f"B{i}"] = _entry("블랙", s, 21 + i)
    for i, s in enumerate(orange_sizes):
        combos[f"O{i}"] = _entry("오렌지", s, 16 + i)

    rows = _parse_option_stock_data(_make_option_stock_html(combos))
    assert rows is not None

    by_color = {}
    for r in rows:
        by_color.setdefault(r["color_text"], []).append(r["size_text"])

    # 오렌지는 220~255 만 (260/270/280/290 절대 포함 X — 버그 핵심)
    assert sorted(by_color["오렌지"]) == sorted(orange_sizes)
    for bad in ("260mm", "270mm", "280mm", "290mm"):
        assert bad not in by_color["오렌지"], f"미판매 사이즈 {bad} 가 오렌지에 섞임(데카르트 곱 회귀)"
    assert sorted(by_color["블랙"]) == sorted(black_sizes)


def test_soldout_size_is_stock_zero_not_excluded():
    """판매 사이즈인데 품절(stock_number=0)이면 stock=0 으로 표면화(제외 X)."""
    combos = {
        "A": _entry("오렌지", "245mm", 11),
        "B": _entry("오렌지", "250mm", 0),    # 품절
    }
    rows = _parse_option_stock_data(_make_option_stock_html(combos))
    by_size = {r["size_text"]: r["stock"] for r in rows}
    assert by_size["245mm"] == 11
    assert by_size["250mm"] == 0


def test_real_stock_numbers_preserved_not_sentinel():
    """999 센티넬이 아니라 실재고 숫자를 그대로 보존(_resolve_stock 가 'N개' 표시)."""
    combos = {"A": _entry("그레이", "290mm", 3), "B": _entry("그레이", "270mm", 25)}
    rows = _parse_option_stock_data(_make_option_stock_html(combos))
    stocks = {r["size_text"]: r["stock"] for r in rows}
    assert stocks == {"290mm": 3, "270mm": 25}
    assert 999 not in stocks.values()


def test_not_selling_option_marked_zero():
    """is_selling=F(판매중지) → 재고 0."""
    combos = {"A": _entry("블랙", "240mm", 50, selling="F")}
    rows = _parse_option_stock_data(_make_option_stock_html(combos))
    assert len(rows) == 1
    assert rows[0]["stock"] == 0


def test_not_displayed_option_excluded():
    """is_display=F(미노출) → 조합 자체 제외."""
    combos = {
        "A": _entry("블랙", "240mm", 50),
        "B": _entry("블랙", "245mm", 50, display="F"),
    }
    rows = _parse_option_stock_data(_make_option_stock_html(combos))
    sizes = {r["size_text"] for r in rows}
    assert sizes == {"240mm"}


def test_color_size_split_axis_order_independent():
    """축 순서(mm 토큰)로 색상/사이즈를 구분 — option_value_orginal 순서 무관."""
    # 사이즈가 먼저 오는 비정상 순서도 안전 처리
    combos = {"A": {**_entry("블랙", "240mm", 5),
                    "option_value_orginal": ["240mm", "블랙"]}}
    rows = _parse_option_stock_data(_make_option_stock_html(combos))
    assert rows[0]["color_text"] == "블랙"
    assert rows[0]["size_text"] == "240mm"


def test_per_combo_price_used():
    """조합별 option_price 를 가격으로 사용."""
    combos = {"A": _entry("블랙", "240mm", 5, price=129000)}
    rows = _parse_option_stock_data(_make_option_stock_html(combos))
    assert rows[0]["price"] == 129000


def test_returns_none_when_absent():
    """option_stock_data 없으면 None → 호출자 레거시 폴백."""
    assert _parse_option_stock_data("<html><body>no data</body></html>") is None
    assert _parse_option_stock_data("var option_stock_data = '{bad json';") is None


# ─────────────────────────────────────────────────────────────────
#  _fetch_static 통합 — option_stock_data 우선 경로
# ─────────────────────────────────────────────────────────────────

def test_fetch_static_uses_option_stock_data(monkeypatch):
    """_fetch_static 가 option_stock_data 를 우선 사용해 실조합만 반환."""
    combos = {
        "A": _entry("오렌지", "220mm", 16),
        "B": _entry("오렌지", "250mm", 0),
        "C": _entry("블랙", "290mm", 3),
    }
    html = _make_option_stock_html(combos)

    class _Resp:
        text = html
        def raise_for_status(self):
            pass

    import lemouton.sourcing.crawlers.lemouton as mod
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp())

    cr = LemoutonCrawler(prefer_playwright=False).fetch(
        "https://lemouton.co.kr/product/detail.html?product_no=130"
    )
    combos_out = {(o["color_text"], o["size_text"]): o["stock"] for o in cr.options}
    assert combos_out == {
        ("오렌지", "220mm"): 16,
        ("오렌지", "250mm"): 0,
        ("블랙", "290mm"): 3,
    }
    # 미판매 오렌지 290mm 는 없어야 함
    assert ("오렌지", "290mm") not in combos_out

# -*- coding: utf-8 -*-
"""현대H몰·롯데아이몰 크롤러 — 재고 3상태(품절0/실수량N) 핵심 로직 단위 테스트.

금전 직결(가격·재고)이라 실수량 파싱이 정확한지 고정한다.
라이브 검증(실 URL·WAF·로그인 혜택)은 별도 — 여기선 파싱 로직만.
"""
import json

from bs4 import BeautifulSoup

from lemouton.sourcing.crawlers.hmall import HmallCrawler
from lemouton.sourcing.crawlers.lotteon import _build_inv_qty_by_size


# ─── 현대H몰: __NEXT_DATA__ itemPtc.stockList[].stockCount ───

def _hmall_html(stock_list):
    nd = {"props": {"pageProps": {"respData": {"itemPtc": {
        "slitmCd": "100", "slitmNm": "테스트 운동화 블랙", "brndNm": "르무통",
        "sellPrc": 100000, "bbprc": 90000, "stockList": stock_list,
    }}}}}
    return ('<html><body><script id="__NEXT_DATA__">'
            + json.dumps(nd, ensure_ascii=False)
            + '</script></body></html>')


def test_hmall_parse_stock_3state():
    html = _hmall_html([
        {"uitm1AttrNm": "260", "sellPrc": 90000, "stockCount": 5, "uitmCd": "A"},
        {"uitm1AttrNm": "270", "sellPrc": 90000, "stockCount": 0, "uitmCd": "B"},  # 품절
        {"uitm1AttrNm": "280", "sellPrc": 90000, "stockCount": 17, "uitmCd": "C"},
    ])
    res = HmallCrawler().parse_html(html, "https://www.hmall.com/p/pdp/x?slitmCd=100")
    assert res.source == "hmall"
    assert res.product_name_raw == "테스트 운동화 블랙"
    by_size = {o["size_text"]: o["stock"] for o in res.options}
    assert by_size == {"260": 5, "270": 0, "280": 17}     # 실수량·품절 정확 (999 둔갑 없음)
    assert all(o["price"] == 90000 for o in res.options)   # bbprc(표면가) 우선


def test_hmall_no_data_is_honest_empty():
    """itemPtc 없으면 옛값 금지 — 빈 옵션 + 실패 표기."""
    nd = {"props": {"pageProps": {"respData": {}}}}
    html = ('<script id="__NEXT_DATA__">' + json.dumps(nd) + '</script>')
    res = HmallCrawler().parse_html(html, "https://www.hmall.com/p/pdp/x")
    assert res.options == []


# ─── 롯데아이몰: itemInvQtyInfo.inv_qty → {size: 실재고} ───

def test_lotteimall_inv_qty_by_size():
    html = """
    <script>
      var a = { opt_cd_0:'001', opt_val_cd_0:'1', item_no:'A', inv_qty:17, master_yn:'Y' };
      var b = { opt_cd_0:'001', opt_val_cd_0:'2', item_no:'B', inv_qty:0, master_yn:'N' };
      var c = { opt_cd_0:'001', opt_val_cd_0:'3', item_no:'C', inv_qty:5, master_yn:'N' };
    </script>
    <div class="inp_option inpOptList">
      <li id="500_1"><p class="txt_option">240mm</p></li>
      <li id="500_2"><p class="txt_option">270mm (품절)</p></li>
      <li id="500_3"><p class="txt_option">255mm</p></li>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    assert _build_inv_qty_by_size(soup, html) == {"240mm": 17, "270mm": 0, "255mm": 5}


def test_lotteimall_no_inv_qty_returns_empty():
    """itemInvQtyInfo 없으면 {} — 호출부가 기존 soldout 2상태로 폴백."""
    soup = BeautifulSoup('<div class="inp_option inpOptList"><li id="1_1">'
                         '<p class="txt_option">240mm</p></li></div>', "lxml")
    assert _build_inv_qty_by_size(soup, "<html>no inv</html>") == {}


def test_lotteimall_2axis_color_size_inv_qty():
    """롯데아이몰 색상모음전(2축): (색,사이즈) 조합별 실재고 — opt_val_cd_0=색·opt_val_cd_1=사이즈."""
    from lemouton.sourcing.crawlers.lotteon import _build_inv_qty_by_color_size
    html = """
    <script>
      var a = { opt_cd_0:'99', opt_val_cd_0:'1', opt_cd_1:'99', opt_val_cd_1:'1', item_no:'A', inv_qty:20, master_yn:'Y' };
      var b = { opt_cd_0:'99', opt_val_cd_0:'1', opt_cd_1:'99', opt_val_cd_1:'2', item_no:'B', inv_qty:0 };
      var c = { opt_cd_0:'99', opt_val_cd_0:'2', opt_cd_1:'99', opt_val_cd_1:'1', item_no:'C', inv_qty:5 };
    </script>
    <div class="inp_option inpOptList">
      <li id="10_1"><p class="txt_option">블랙</p></li>
      <li id="10_2"><p class="txt_option">아이보리</p></li>
    </div>
    <div class="inp_option inpOptList">
      <li id="20_1"><p class="txt_option">230mm</p></li>
      <li id="20_2"><p class="txt_option">240mm (품절)</p></li>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    out = _build_inv_qty_by_color_size(soup, html)
    assert out == {("블랙", "230mm"): 20, ("블랙", "240mm"): 0, ("아이보리", "230mm"): 5}

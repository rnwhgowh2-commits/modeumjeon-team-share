# -*- coding: utf-8 -*-
"""현대H몰·롯데아이몰 크롤러 — 재고 3상태(품절0/실수량N) 핵심 로직 단위 테스트.

금전 직결(가격·재고)이라 실수량 파싱이 정확한지 고정한다.
라이브 검증(실 URL·WAF·로그인 혜택)은 별도 — 여기선 파싱 로직만.
"""
import json

from bs4 import BeautifulSoup

from lemouton.sourcing.crawlers.hmall import (
    HmallCrawler,
    build_combo_persize_options,
)
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


def test_hmall_parse_dan_soldout_by_sellgbcd():
    """[S21] 단품(1축 SSR stockList)도 품절판정=sellGbcd. 품절 사이즈는 stockCount=1
    센티넬을 주므로 stockCount 만 보면 '1개 있음' 둔갑(거짓 재고=금전손실)."""
    html = _hmall_html([
        {"uitm1AttrNm": "255", "sellPrc": 126900, "sellGbcd": "00", "stockCount": 2, "uitmCd": "A"},
        {"uitm1AttrNm": "260", "sellPrc": 126900, "sellGbcd": "11", "stockCount": 1, "uitmCd": "B"},  # 품절(센티넬1)
        {"uitm1AttrNm": "265", "sellPrc": 126900, "sellGbcd": "11", "stockCount": 1, "uitmCd": "C"},  # 품절
        {"uitm1AttrNm": "275", "sellPrc": 126900, "sellGbcd": "11", "stockCount": 1, "uitmCd": "D"},  # 품절
    ])
    res = HmallCrawler().parse_html(html, "https://www.hmall.com/p/pdp/x?slitmCd=100")
    by_size = {o["size_text"]: o["stock"] for o in res.options}
    assert by_size == {"255": 2, "260": 0, "265": 0, "275": 0}   # 품절은 0 (1 둔갑 없음)


def test_hmall_no_data_is_honest_empty():
    """itemPtc 없으면 옛값 금지 — 빈 옵션 + 실패 표기."""
    nd = {"props": {"pageProps": {"respData": {}}}}
    html = ('<script id="__NEXT_DATA__">' + json.dumps(nd) + '</script>')
    res = HmallCrawler().parse_html(html, "https://www.hmall.com/p/pdp/x")
    assert res.options == []


# ─── 현대H몰 모음전(2축): item-stockcount 프로브 → per-(색,사이즈,재고) ───
#   라이브 역공학으로 드러난 2버그를 고정: (1) uitmSeq 비순차(색 위치 아님) → 중간 seq 는
#   MIX(여러색×한사이즈) 쓰레기 / (2) 품절판정 = sellGbcd(stockCount=1 은 품절 센티넬).

def _row(color, size, gbcd="00", cnt=10):
    return {"uitm1AttrNm": color, "uitm2AttrNm": size, "sellGbcd": gbcd, "stockCount": cnt}


def test_combo_persize_basic_3state_by_sellgbcd():
    """판매중(00)=실수량 / 품절(11)=0(stockCount=1 센티넬 무시)."""
    responses = {
        1: [_row("블랙", "220mm", "00", 3), _row("블랙", "260mm", "11", 1)],  # 260=품절
    }
    opts = build_combo_persize_options("100", responses, {"블랙": 126900})
    by = {o["size_text"]: o["stock"] for o in opts}
    assert by == {"220mm": 3, "260mm": 0}            # 품절은 0 (1 둔갑 없음)
    assert all(o["price"] == 126900 for o in opts)


def test_combo_persize_rejects_mix_and_keeps_nonsequential():
    """MIX(여러색 섞인 seq) 는 버리고, 비순차 uitmSeq 의 단일색 응답만 채택."""
    responses = {
        1: [_row("블랙", "230mm")],                              # 단일색 ✓
        7: [_row("그레이", "230mm"), _row("크림핑크", "230mm")],   # MIX(여러색) ✗ → 버림
        18: [_row("크림핑크", "240mm", "00", 1),                  # 비순차(18) 단일색 ✓
             _row("크림핑크", "260mm", "11", 1)],                 #   240=재고1·260=품절0
    }
    opts = build_combo_persize_options("100", responses, {})
    colors = {o["color_text"] for o in opts}
    assert colors == {"블랙", "크림핑크"}                          # 그레이(MIX발) 미포함
    cream = {o["size_text"]: o["stock"] for o in opts if o["color_text"] == "크림핑크"}
    assert cream == {"240mm": 1, "260mm": 0}


def test_combo_persize_dedup_color_first_win():
    """같은 색이 여러 seq 에 나와도 한 번만(첫 채택)."""
    responses = {
        1: [_row("블랙", "220mm", "00", 5)],
        9: [_row("블랙", "220mm", "00", 99)],   # 중복 색 → 무시
    }
    opts = build_combo_persize_options("100", responses, {})
    assert [o["stock"] for o in opts] == [5]


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


def test_lotteimall_disp_qty_matches_site_thresholds():
    """롯데아이몰 재고 3상태 = 사이트 자체 JS 기준에 정렬.
    라이브 근거(2026-07-13, goods 2559329941 페이지 JS 원문):
        if (optInvQty <= 0)      -> ' (품절)'
        else if (optInvQty > 500)-> ' (판매중)'          # 충분(대량)
        else if (optInvQty < 5)  -> ' (N개 남음)'         # ★ 한정 = 실수량
        else (5 <= inv_qty <=500)-> 라벨 없음 = 충분
    → 경계는 5(한정)와 500(판매중). 파서는 <5=실수량N, >=5=충분(999)로 판정한다.
    (구 로직의 '30 상한' 은 특정 상품 1회 관찰의 오일반화였음.)"""
    from lemouton.sourcing.crawlers.lotteon import _lotteimall_disp_qty
    assert _lotteimall_disp_qty(0) == 0      # 품절
    assert _lotteimall_disp_qty(1) == 1      # 한정: 실수량 그대로
    assert _lotteimall_disp_qty(2) == 2      # "2개 남음"
    assert _lotteimall_disp_qty(4) == 4      # 한정 상한(<5)
    assert _lotteimall_disp_qty(5) == 999    # 충분(사이트=라벨없음)
    assert _lotteimall_disp_qty(10) == 999   # ★ 구 로직은 10을 '10개 남음'으로 오표기했음
    assert _lotteimall_disp_qty(30) == 999   # 충분
    assert _lotteimall_disp_qty(600) == 999  # 판매중=충분


def test_lotteimall_limited_size_stored_without_paren_suffix():
    """★ 2026-07-14 회귀 — 한정('N개 남음') 사이즈가 매트릭스에서 '미크롤' 둔갑하던 버그.

    단품(단일색)은 사이즈가 color_text 에 담기는데, 한정 사이즈 li 텍스트가
    "250mm (2개 남음)" 이라 그대로 저장됐다. 매칭(_stk_digits = 모든 숫자 이어붙임)이
    "250"+"2"="2502" → 우리 사이즈 "250" 과 불일치 → 그 사이즈만 미크롤(품절은 괄호에
    숫자 없어 우연히 정상). 저장 라벨에서 상태 꼬리표를 제거해 매칭을 복구한다.
    재고 값 자체(한정=2)는 보존돼야 한다."""
    from lemouton.sourcing.crawlers.lotteon import LotteCrawler
    html = """
    <div class="title">르무통 메이트 그레이</div>
    <div class="price"><span class="num">113,630</span>
      <div class="final"><span class="num">122,180</span></div></div>
    <div class="inp_option inpOptList"><ul>
      <li id="0_0"><p class="txt_option">사이즈 선택</p></li>
      <li id="0_1"><p class="txt_option">230mm</p></li>
      <li id="0_2"><p class="txt_option">250mm (2개 남음)</p></li>
      <li class="soldout" id="0_3"><p class="txt_option">220mm (품절)</p></li>
    </ul></div>
    <script>itemInvQtyInfo = [];
      itemInvQtyInfo[0] = {opt_cd_0:'99',opt_val_cd_0:'1',item_no:1,inv_qty:30,master_yn:'N'};
      itemInvQtyInfo[1] = {opt_cd_0:'99',opt_val_cd_0:'2',item_no:2,inv_qty:2,master_yn:'N'};
      itemInvQtyInfo[2] = {opt_cd_0:'99',opt_val_cd_0:'3',item_no:3,inv_qty:0,master_yn:'N'};
    </script>
    """
    res = LotteCrawler().parse_html(
        html, "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559329941")
    by_stock = {}
    for o in res.options:
        # 저장 라벨(색·사이즈 어디에 담기든)에 상태 꼬리표('(...)')가 남으면 안 된다.
        assert "(" not in (o.get("color_text") or ""), o
        assert "(" not in (o.get("size_text") or ""), o
        # 사이즈 숫자만 남아야 _stk_digits 매칭이 정확 (예: '250mm' → '250')
        by_stock[(o.get("color_text") or "").replace("mm", "")] = o.get("stock")
    # 3상태 값 보존: 250=한정 2 / 230=충분 999 / 220=품절 0
    assert by_stock.get("250") == 2, by_stock
    assert by_stock.get("230") == 999, by_stock
    assert by_stock.get("220") == 0, by_stock

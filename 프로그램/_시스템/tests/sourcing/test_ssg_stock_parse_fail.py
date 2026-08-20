"""[2026-07-02 A1 회귀 → 2026-07-08 재정의] SSG usablInvQty 필드 부재(파싱 실패)는
품절(0)로도, 재고있음(999)으로도 둔갑시키지 않고 '확인 불가'(-1 센티넬)로 표면화한다.

배경: SSG 는 페이지 인라인 JS 의 usablInvQty 로 재고를 준다('0'=진짜 품절, 'N'=실수량).
필드가 아예 없으면(필드명/포맷 변경 등 파싱 실패) 재고를 신뢰할 수 없다.
  - 옛날①: stock=0(품절) → 재고 있는 옵션이 품절 둔갑(판매중단) = 기회손실.
  - 옛날②(A1): stock=999(재고있음) → 실제 품절 옵션이 '충분'으로 둔갑 판매 = 오버셀·주문취소.
둘 다 금전위험. 🔒 재고 3대 원칙(폴백 금지·못하면 '확인 불가') → 파싱 실패는
_STOCK_UNKNOWN(-1) 로 emit → 화면 '⚠️확인필요' + 수량0 취급(판매 제외), 재크롤 대상.
"""
from lemouton.sourcing.crawlers.ssg import _parse_uitem_options, _STOCK_UNKNOWN


def _block(uid, optn1, size, *, inv=None, price="109900"):
    inv_field = f"usablInvQty:'{inv}'," if inv is not None else ""
    return (
        f"uitemObj = {{itemId:'1000000000001', uitemId:'{uid}', "
        f"uitemOptnNm1:'{optn1}', uitemOptnTypeNm1:'색상', "
        f"uitemOptnNm2:'{size}', uitemOptnTypeNm2:'사이즈', "
        f"sellprc:parseInt('{price}', 10) || 0, bestAmt:'{price}', "
        f"{inv_field}}};uitemObjArr.push(uitemObj);"
    )


def _stock_by_size(rows):
    return {r["size_text"]: r["stock"] for r in rows}


def test_usabl_inv_present_zero_is_soldout():
    """usablInvQty:'0' 은 진짜 품절 → stock 0."""
    html = _block("0001", "블랙", "250", inv="0")
    rows = _parse_uitem_options(html, "1000000000001")
    assert _stock_by_size(rows)["250"] == 0


def test_usabl_inv_present_real_qty():
    """usablInvQty:'5' → 실수량 5."""
    html = _block("0002", "블랙", "260", inv="5")
    rows = _parse_uitem_options(html, "1000000000001")
    assert _stock_by_size(rows)["260"] == 5


def test_usabl_inv_absent_is_unknown_not_soldout_not_instock():
    """usablInvQty 필드 부재(파싱 실패) → 확인불가(-1). 품절(0)도 재고있음(999)도 금지.

    [2026-07-08] 파싱 실패를 '충분(999)'으로 둔갑시키면 실제 품절 옵션이 팔려 오버셀.
    폴백 금지·확인불가 표면화 → _STOCK_UNKNOWN(-1). resolver 가 '⚠️확인필요'+수량0 처리.
    """
    html = _block("0003", "블랙", "270", inv=None)
    rows = _parse_uitem_options(html, "1000000000001")
    stock = _stock_by_size(rows)["270"]
    assert stock == _STOCK_UNKNOWN, f"필드 부재는 확인불가(-1)여야 하는데 {stock}"
    assert stock != 0, "품절 둔갑 금지"
    assert stock != 999, "재고있음(충분) 둔갑 금지 — 오버셀 위험"

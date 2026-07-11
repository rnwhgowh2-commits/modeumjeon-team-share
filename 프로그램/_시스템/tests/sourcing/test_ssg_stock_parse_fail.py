"""[2026-07-02 A1 회귀] SSG usablInvQty 필드 부재(파싱 실패)를 품절(0)로 둔갑시키지 않는다.

배경: SSG 는 페이지 인라인 JS 의 usablInvQty 로 재고를 준다('0'=진짜 품절).
필드가 아예 없으면(필드명/포맷 변경 등 파싱 실패) 예전엔 stock=0(품절)로 처리 →
재고 있는 옵션이 통째로 품절 둔갑(최저가 선정 제외·판매중단) = 금전손실.
타 크롤러(무신사·SSF·롯데)와 동일하게 필드 부재는 999(수량미상='재고있음')여야 한다.
"""
from lemouton.sourcing.crawlers.ssg import _parse_uitem_options


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


def test_usabl_inv_absent_is_unknown_not_soldout():
    """usablInvQty 필드 부재(파싱 실패) → 999(수량미상), 0(품절 둔갑) 금지. [A1 fix]"""
    html = _block("0003", "블랙", "270", inv=None)
    rows = _parse_uitem_options(html, "1000000000001")
    stock = _stock_by_size(rows)["270"]
    assert stock == 999, f"필드 부재는 999(수량미상)여야 하는데 {stock} (품절 둔갑 재발)"
    assert stock != 0

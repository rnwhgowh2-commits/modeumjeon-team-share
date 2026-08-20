import pytest

from lemouton.delivery.mango_parser import parse_mango_xls, MangoParseError

HEADERS = ["마켓주문일자", "마켓명", "마켓주문번호", "수령인명", "마켓상품명",
           "옵션1", "사이트주문번호", "구매가격", "국제운송료", "국내송장번호 택배사",
           "국내송장번호", "더망고주문상태 (사용자\r\n  연동)", "마켓주문상태 (오픈 마켓\r\n  연동)",
           "간단메모", "휴대폰번호", "더망고주문고유번호"]


def _sheet_html(data_rows):
    def tr(cells):
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
    body = tr(HEADERS) + "".join(tr(r) for r in data_rows)
    return "<html><body><table>" + body + "</table></body></html>"


def test_parse_basic_rows():
    html = _sheet_html([
        ["2026-07-11 07:28:40", "쿠팡", "3101540255864", "이주연", "매장정품\r\n  살로몬 캡",
         "블랙", "", "", "", "", "", "결제완료", "특이사항없음", "", "0502-1736-4794", "12039"],
        ["2026-07-10 22:49:08", "롯데ON", "2026071015418571", "염수경", "잔스포츠 미니백팩",
         "ONESIZE", "1231231", "30000.00", "0.00", "", "6812345678", "해외현지배송중",
         "송장전송완료", "까대기", "01026584242", "12038"],
    ])
    rows = parse_mango_xls(html.encode("utf-8"))
    assert len(rows) == 2
    assert rows[0]["mango_uid"] == "12039"
    assert rows[0]["recipient"] == "이주연"
    assert rows[0]["mango_status"] == "결제완료"
    assert rows[0]["invoice_no"] == ""       # 빈 송장
    assert "살로몬 캡" in rows[0]["product_name"]
    assert "\r" not in rows[0]["product_name"]
    assert rows[1]["invoice_no"] == "6812345678"
    assert rows[1]["market_status"] == "송장전송완료"


def test_frameset_shell_raises():
    shell = ('<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head>'
             '<meta name="Excel Workbook Frameset"></head>'
             '<frameset><frame src="20260711.files/sheet001.htm"></frameset></html>')
    with pytest.raises(MangoParseError):
        parse_mango_xls(shell.encode("utf-8"))


def test_no_table_raises():
    with pytest.raises(MangoParseError):
        parse_mango_xls(b"<html><body>hello</body></html>")

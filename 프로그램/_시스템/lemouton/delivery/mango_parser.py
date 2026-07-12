"""더망고 주문내역 .xls(HTML 위장) 파서.

더망고 엑셀은 확장자만 .xls 이고 실체는 HTML <table> 이다.
프레임셋 껍데기 파일(실제 표가 없는)은 조용히 통과시키지 않고 MangoParseError 를 던진다.
"""
import re

from bs4 import BeautifulSoup

# A~P 16열 고정. 헤더는 개행/공백이 섞이므로 위치(인덱스)로 매핑한다.
_COLS = [
    "ordered_at",       # A 마켓주문일자
    "market_name",      # B 마켓명
    "market_order_no",  # C 마켓주문번호
    "recipient",        # D 수령인명
    "product_name",     # E 마켓상품명
    "option1",          # F 옵션1
    "site_order_no",    # G 사이트주문번호
    "buy_price",        # H 구매가격
    "intl_ship",        # I 국제운송료
    "courier",          # J 국내송장번호 택배사
    "invoice_no",       # K 국내송장번호
    "mango_status",     # L 더망고주문상태
    "market_status",    # M 마켓주문상태
    "memo",             # N 간단메모
    "phone",            # O 휴대폰번호
    "mango_uid",        # P 더망고주문고유번호
]
_NCOLS = len(_COLS)


class MangoParseError(Exception):
    pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def parse_mango_xls(raw) -> list:
    """더망고 엑셀 바이트/문자열 → 주문 dict 리스트."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw

    low = text.lower()
    # 프레임셋 껍데기 감지: 실제 데이터 <table> 없이 frameset 만 있으면 실패
    if "excel workbook frameset" in low or ("<frameset" in low and "<table" not in low):
        raise MangoParseError(
            "실제 주문 표가 없는 껍데기 파일입니다. 더망고에서 단일 파일로 내보내거나 "
            "'{이름}.files/sheet001.htm' 을 올려주세요.")

    soup = BeautifulSoup(text, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) >= _NCOLS:
            rows.append(cells)

    if not rows:
        raise MangoParseError("표(행)를 찾지 못했습니다. 더망고 주문내역 엑셀이 맞는지 확인해주세요.")

    header = rows[0]
    if "마켓주문" not in _norm(header[0]) or "고유번호" not in _norm(header[_NCOLS - 1]):
        raise MangoParseError("헤더가 더망고 양식과 다릅니다. 첫 열=마켓주문일자, 끝 열=더망고주문고유번호 확인.")

    out = []
    for cells in rows[1:]:
        rec = {key: _norm(cells[i]) for i, key in enumerate(_COLS)}
        if not rec["mango_uid"]:
            continue  # 고유번호 없는 행(합계/빈행) 건너뜀
        out.append(rec)
    return out

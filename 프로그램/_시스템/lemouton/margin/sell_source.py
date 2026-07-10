# -*- coding: utf-8 -*-
"""매출(SellRow) 생산자 2종 — 마켓 API / 샵마인 엑셀.

두 생산자는 동일한 SELL_COLUMNS 스키마를 뱉는다. matcher 는 출처를 모른다.
컬럼명은 기존 샵마인 이름을 그대로 쓴다 — matcher 를 무수정으로 두기 위한 의도적 선택.

정산예정금액 정책의 유일한 자리. 스펙 §4 참조.

주의: from_shopmine_excel 은 원본 modules/data_loader.py::parse_sell 의 DataFrame
변환(컬럼 정규화·쿠팡 '알수없음' 보정)을 그대로 재현한다. 골든테스트(Task 10)가
옛 프로그램과의 정확한 회귀 동치를 요구하고, matcher.match_for_classifier 가
샵마인 측 모든 컬럼을 '샵마인_{col}' 로 그대로 복사하므로, 컬럼명 정규화를 빠뜨리면
결과가 달라진다. 따라서 원본 col_map 전체 + bare '정산예상금액' 보정을 유지한다.
"""
import datetime as _dt
import io
import logging
import re
from typing import Optional

import pandas as pd

from lemouton.margin.config import COUPANG_FEE_RATE

logger = logging.getLogger(__name__)

# matcher 가 읽는 컬럼 + 마진 표시에 필요한 컬럼
SELL_COLUMNS = [
    "오픈마켓주문번호", "상품명", "옵션", "수량", "단가", "실결제금액",
    "정산예상금액_배송비포함", "마켓수수료", "수수료율", "쇼핑몰",
    "수취고객명", "주문일", "송장입력", "주문상태",
    "_settle_source",   # real | estimated | none
    "_sell_origin",     # api | shopmine
]

_SENTINEL_999 = 999999999.99


def _to_numeric_safe(series: pd.Series) -> pd.Series:
    """숫자 컬럼 안전 변환. NaN→0, 999999999.99 센티널→0.

    원본 modules/data_loader.py::_to_numeric_safe 와 동일 동작.
    """
    result = pd.to_numeric(series, errors="coerce").fillna(0)
    return result.replace(_SENTINEL_999, 0)


def _read_excel_any(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """xls(xlrd) → xlsx(openpyxl) → HTML 형식 xls(html5lib) 순 fallback.

    원본 parse_sell 의 3단계 fallback 을 그대로 재현. 모든 엔진 실패 시
    시도한 방식 목록(attempts)을 담아 ValueError 를 던진다.
    """
    attempts = []
    for engine in ("xlrd", "openpyxl"):
        try:
            return pd.read_excel(io.BytesIO(file_bytes), engine=engine)
        except Exception as e:  # noqa: BLE001
            attempts.append(f"{engine}: {e}")

    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("euc-kr", errors="replace")

    # Excel "웹 페이지로 저장" frameset 감지 — 실제 데이터는 옆 .files 폴더에 있음
    if "Excel Workbook Frameset" in text or ("File-List" in text and ".files/" in text):
        m = re.search(r'href\s*=\s*["\']?([^"\'>\s]+\.files)/', text)
        folder = m.group(1) if m else f"{filename.rsplit('.', 1)[0]}.files"
        raise ValueError(
            f'이 파일은 "Excel 웹 페이지" 포맷입니다 — 실제 데이터는 옆의 '
            f'"{folder}" 폴더 안 sheet001.htm 에 있습니다. '
            f'다시 업로드하실 때 **xls 와 {folder} 폴더를 함께** 드래그하세요.')

    try:
        dfs = pd.read_html(io.StringIO(text), flavor="html5lib")
        df = max(dfs, key=len)
        if df.iloc[0].astype(str).str.contains("주문|상품|쇼핑몰|단가", regex=True).any():
            df.columns = df.iloc[0]
            df = df.iloc[1:].reset_index(drop=True)
        return df
    except Exception as e:  # noqa: BLE001
        attempts.append(f"pd.read_html: {e}")

    raise ValueError(
        "매출 엑셀 파싱 실패 — 지원되지 않는 형식입니다. 시도한 방식: "
        + " / ".join(f"[{i+1}] {a}" for i, a in enumerate(attempts)))


def from_shopmine_excel(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """샵마인 통합주문관리 엑셀 → SellRow DF.

    쿠팡 '알수없음' 정산금액·수수료는 실결제금액 × (1 − 0.1155) 로 보정한다
    (원본 data_loader.parse_sell 과 동일). 보정값도 샵마인이 그렇게 써 왔으므로
    _settle_source='real' 로 둔다 — 옛 프로그램과의 회귀 동치를 깨지 않기 위함.
    """
    df = _read_excel_any(file_bytes, filename)

    # ★ 컬럼명 1차 정규화 — 연속 공백(전각 포함)을 단일 공백으로 (원본 line 214~216)
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]

    # 전각 공백 포함 컬럼명 정규화 (원본 col_map 전체 재현)
    col_map = {}
    for c in df.columns:
        s = str(c)
        if "오픈마켓" in s and "주문번호" in s:
            col_map[c] = "오픈마켓주문번호"
        elif "오픈마켓" in s and "상품번호" in s:
            col_map[c] = "오픈마켓상품번호"
        elif "샵마인" in s and "주문고유코드" in s:
            col_map[c] = "샵마인주문고유코드"
        elif "정산예상금액" in s and "배송비" in s:
            col_map[c] = "정산예상금액_배송비포함"
        elif "해외매입금액" in s and "ＣＮＹ" in s:
            col_map[c] = "해외매입금액_CNY"
        elif "해외매입금액" in s and "원화" in s:
            col_map[c] = "해외매입금액_원화"
        elif c == "정산예상금액":
            col_map[c] = "정산예상금액"
    df = df.rename(columns=col_map)

    # '삼품명' → '상품명' 오타 보정
    if "삼품명" in df.columns and "상품명" not in df.columns:
        df = df.rename(columns={"삼품명": "상품명"})

    # 필수 컬럼 검증 — 없는 채로 통과시키면 matcher 가 판매가·마진을 0 으로 계산해
    # 조용히 틀린 표를 보여준다(조용한 실패 금지). 원본의 무방비 df['단가'] KeyError 를
    # 명시적 에러로 대체. buy_parser.parse_buy 의 필수 컬럼 검증 패턴과 동일.
    required = ["오픈마켓주문번호", "상품명", "단가", "수량",
                "실결제금액", "정산예상금액_배송비포함", "수취고객명"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"매출 엑셀에 필수 컬럼이 없습니다: {missing}")

    # 쿠팡 '알수없음' 정산금액·수수료 보정 (원본과 동일: bare 정산예상금액 포함)
    for col in ("정산예상금액", "정산예상금액_배송비포함", "마켓수수료"):
        if col in df.columns:
            mask = df[col].astype(str).str.contains("알수없음", na=False)
            paid = pd.to_numeric(df.loc[mask, "실결제금액"], errors="coerce")
            if col in ("정산예상금액", "정산예상금액_배송비포함"):
                df.loc[mask, col] = paid * (1 - COUPANG_FEE_RATE)
            else:  # 마켓수수료
                df.loc[mask, col] = paid * COUPANG_FEE_RATE
            df[col] = _to_numeric_safe(df[col])

    # 쿠팡 수수료율 '알수없음' → '11.55%'
    if "수수료율" in df.columns:
        mask = df["수수료율"].astype(str).str.contains("알수없음", na=False)
        df.loc[mask, "수수료율"] = "11.55%"

    # 숫자형 변환 (단가·실결제금액 센티널 제거, 수량 정수화)
    # — 위 required 검증이 세 컬럼 존재를 보장하므로 직접 대입.
    df["단가"] = _to_numeric_safe(df["단가"])
    df["실결제금액"] = _to_numeric_safe(df["실결제금액"])
    df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(1).astype(int)

    # 출처·정산 근거 태깅
    df["_settle_source"] = "real"
    df["_sell_origin"] = "shopmine"

    # SELL_COLUMNS 스키마 보장 (누락 컬럼은 빈 값으로 채움 — matcher 가 .get 으로 읽음)
    for col in SELL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df


# ── API 생산자 ────────────────────────────────────────────────────────────

API_MARKETS = ["smartstore", "coupang", "lotteon", "eleven11"]
"""order_export.SUPPORTED 와 일치. 옥션·G마켓은 라이브 미검증 → 샵마인 엑셀 보조 업로드."""

# order_export 의 '판매처' 한글값 → 샵마인 '쇼핑몰' 코드값
_PANMAECHEO_TO_SHOPMINE = {
    "스마트스토어": "04.스마트스토어",
    "쿠팡": "06.쿠팡",
    "롯데온": "18.롯데온",
    "11번가": "03.11번가",
    "옥션": "02.옥션",
    "G마켓": "01.지마켓",
}


def market_to_shopmine(panmaecheo: str) -> str:
    """order_export '판매처' → 샵마인 '쇼핑몰'. 미지원 값은 원본 그대로."""
    return _PANMAECHEO_TO_SHOPMINE.get(str(panmaecheo).strip(), str(panmaecheo).strip())


def _to_int_or_blank(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return ""


def _settlement_for(row: dict):
    """SellRow 의 정산예상금액_배송비포함 + _settle_source 결정. 스펙 §4.

    정산 없음(none) 은 빈칸이 아니라 0 이다. matcher 가 빈칸을 NaN 으로 바꾸는데,
    NaN 은 (a) JSON 직렬화를 깨뜨리고 (b) pandas sum() 이 건너뛰어 매입 손실을
    총합에서 지워버린다. 0 은 margin_rules.js 가 이미 '정산 없음'으로 읽는 센티널이며
    (정산 0 + 매입>0 → 의심손실), 실제로 0원에 정산되는 주문은 없다.
    출처의 정직성은 _settle_source='none' 태그가 보존한다.

    롯데온만 재계산한다 — order_export 가 정산액 자리에 actualAmt(실결제)를 넣기 때문.
    actualAmt 는 배송비를 이미 포함하므로 배송비를 다시 더하지 않는다.
    """
    src = row.get("_settle_source", "none")
    if row.get("판매처") == "롯데온":
        paid = _to_int_or_blank(row.get("실결제금액"))
        fee = _to_int_or_blank(row.get("마켓수수료"))
        if paid == "" or fee == "" or fee <= 0:
            return 0, "none"
        return paid - fee, "real"

    if src == "none":
        return 0, "none"
    settle = _to_int_or_blank(row.get("정산예정금(배송비포함)"))
    if settle == "":
        return 0, "none"
    return settle, src


def _rows_to_df(rows: list) -> pd.DataFrame:
    """order_export 행 리스트 → SellRow DF."""
    out = []
    for r in rows:
        settle, src = _settlement_for(r)
        out.append({
            "오픈마켓주문번호": str(r.get("오픈마켓주문번호", "") or ""),
            "상품명": r.get("상품명", ""),
            "옵션": r.get("옵션", ""),
            "수량": int(r.get("수량") or 1),
            "단가": _to_int_or_blank(r.get("단가")) or 0,
            "실결제금액": _to_int_or_blank(r.get("실결제금액")) or 0,
            "정산예상금액_배송비포함": settle,
            "마켓수수료": r.get("마켓수수료", ""),
            "수수료율": r.get("수수료율", ""),
            "쇼핑몰": market_to_shopmine(r.get("판매처", "")),
            "수취고객명": r.get("수령자", ""),
            "주문일": r.get("주문일", ""),
            "송장입력": r.get("송장입력", ""),
            "주문상태": r.get("주문상태", ""),
            "_settle_source": src,
            "_sell_origin": "api",
        })
    df = pd.DataFrame(out, columns=SELL_COLUMNS)
    if df.empty:
        df = pd.DataFrame(columns=SELL_COLUMNS)
    return df


def _fetch_rows(since, until, markets):
    """order_export 호출 seam — 테스트에서 monkeypatch 한다.

    한 마켓이라도 실패하면 예외가 전파된다(order_export._fetch_combined 설계).
    부분 성공을 숨기면, 실패한 마켓의 매입 행이 전부 '매출 미매칭'으로 둔갑해
    블랙스팟처럼 보인다 — 조용한 실패보다 나쁜 적극적 오신호. 스펙 §9.
    """
    from lemouton.markets import order_export as oe
    warnings: list = []
    rows = oe.combined_order_rows(markets, since=since, until=until, warnings=warnings)
    return rows, warnings


def from_api(since: _dt.datetime, until: _dt.datetime,
             markets: Optional[list] = None) -> pd.DataFrame:
    """판매처 마켓 API → SellRow DF. df.attrs['warnings'] 에 계정 제외 사유가 담긴다."""
    rows, warnings = _fetch_rows(since, until, markets or API_MARKETS)
    df = _rows_to_df(rows)
    df.attrs["warnings"] = warnings
    logger.info("from_api: rows=%d warnings=%d", len(df), len(warnings))
    return df

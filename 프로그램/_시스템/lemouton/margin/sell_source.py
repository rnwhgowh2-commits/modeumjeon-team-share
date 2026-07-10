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
import io
import logging
import re

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
    for col in ("단가", "실결제금액"):
        if col in df.columns:
            df[col] = _to_numeric_safe(df[col])
    if "수량" in df.columns:
        df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(1).astype(int)

    # 출처·정산 근거 태깅
    df["_settle_source"] = "real"
    df["_sell_origin"] = "shopmine"

    # SELL_COLUMNS 스키마 보장 (누락 컬럼은 빈 값으로 채움 — matcher 가 .get 으로 읽음)
    for col in SELL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df

# -*- coding: utf-8 -*-
r"""더망고 솔루션 매입 엑셀 파싱 + G열(사이트주문번호) 유무로 분할.

원본: C:\dev\대량등록 마진계산기\modules\data_loader.py (parse_buy / split_by_site_order_no)
parse_sell 은 sell_source.from_shopmine_excel 로 이관됨.
"""
import io
import re
import logging

import pandas as pd

from lemouton.margin.config import MANGO_COLS

logger = logging.getLogger(__name__)


def _normalize_order_no(val) -> str:
    """주문번호 정규화: NaN → '', float '.0' 제거, 공백 trim."""
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


# 미입력 센티널값 — 더망고 엑셀에서 구매가격 미기입 행이 이 값으로 저장됨
_SENTINEL_999 = 999999999.99


def _to_numeric_safe(series: pd.Series) -> pd.Series:
    """숫자 컬럼 안전 변환. NaN→0, 999999999.99 센티널→0.

    블랙스팟 프로그램의 동명 함수와 동일한 동작. 미입력 센티널이
    집계에 포함되어 매입·마진 왜곡되는 것을 방지.
    """
    result = pd.to_numeric(series, errors="coerce").fillna(0)
    result = result.replace(_SENTINEL_999, 0)
    return result


def parse_buy(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """더망고 매입 엑셀 파싱.

    xlsx 는 openpyxl, 바이너리 xls 는 xlrd, HTML 형식 xls 는 html5lib/BeautifulSoup fallback.
    """
    df = None
    attempts = []  # 각 fallback 시도 결과 — 실패 시 사용자에게 전달용

    # 1차: openpyxl (xlsx 표준)
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), engine='openpyxl')
    except Exception as e:
        attempts.append(f"openpyxl: {e}")
        logger.info(f"openpyxl 실패 → xlrd fallback 시도: {e}")

    # 2차: xlrd (바이너리 xls)
    if df is None:
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), engine='xlrd')
        except Exception as e:
            attempts.append(f"xlrd: {e}")
            logger.info(f"xlrd 실패 → HTML fallback 시도: {e}")

    # 3차: HTML 형식 xls (더망고 구버전 다운로드)
    if df is None:
        try:
            text = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            text = file_bytes.decode('euc-kr', errors='replace')

        # Excel "웹 페이지로 저장" frameset 감지 — 실제 데이터는 외부 .files/ 폴더에 분리됨
        if 'Excel Workbook Frameset' in text or ('File-List' in text and '.files/' in text):
            # frameset HTML 에서 실데이터 폴더 이름 추출 (href="<name>.files/filelist.xml")
            m = re.search(r'href\s*=\s*["\']?([^"\'>\s]+\.files)/', text)
            folder_name = m.group(1) if m else f"{filename.rsplit('.',1)[0]}.files"
            raise ValueError(
                f'이 파일은 "Excel 웹 페이지" 포맷입니다 — 실제 데이터는 옆의 '
                f'"{folder_name}" 폴더 안 sheet001.htm 에 있습니다. '
                f'다시 업로드하실 때 **xls 와 {folder_name} 폴더를 함께** 드래그하세요 '
                f'(또는 폴더 안 sheet001.htm 만 단독 업로드도 가능).'
            )

        try:
            dfs = pd.read_html(io.StringIO(text), flavor='html5lib')
            df = dfs[0]
            if df.iloc[0].astype(str).str.contains('마켓|주문|상품', regex=True).any():
                df.columns = df.iloc[0]
                df = df.iloc[1:].reset_index(drop=True)
        except Exception as e:
            attempts.append(f"pd.read_html: {e}")
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(text, 'html5lib')
                tables = soup.find_all('table')
                if not tables:
                    raise ValueError(
                        '매입 엑셀 파싱 실패 — 지원되지 않는 형식입니다. '
                        '시도한 방식: ' + ' / '.join(f'[{i+1}] {a}' for i, a in enumerate(attempts))
                    )
                rows = []
                for tr in tables[0].find_all('tr'):
                    cells = [td.get_text(strip=True) for td in tr.find_all('td')]
                    if cells:
                        rows.append(cells)
                try:
                    df = pd.DataFrame(rows[1:], columns=rows[0])
                except (IndexError, ValueError) as ie:
                    raise ValueError(
                        f'매입 엑셀 테이블 파싱 실패 (행/헤더 부족): {ie}. '
                        f'시도한 방식: ' + ' / '.join(f'[{i+1}] {a}' for i, a in enumerate(attempts))
                    ) from ie
            except ValueError:
                raise  # 위에서 직접 올린 상세 에러 그대로 전파

    # ★ 컬럼명 정규화 — 연속 공백을 단일 공백으로 (Jinja2 HTML 렌더링과 일치)
    #   더망고 헤더에 "더망고주문상태 (사용자\n  연동)" 같은 줄바꿈/이중공백이
    #   data_loader 에서 그대로 들어오면 JS 키 매칭 실패.
    import re as _re
    df.columns = [_re.sub(r'\s+', ' ', str(c)).strip() for c in df.columns]

    # 필수 컬럼 검증
    required = ['마켓주문일자', '마켓명', '마켓주문번호', '수령인명',
                '마켓상품명', '옵션1', '구매가격']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'매입 엑셀에 필수 컬럼이 없습니다: {missing}')

    # 구매가격 숫자 변환 (센티널 999999999.99 → 0)
    df['구매가격'] = _to_numeric_safe(df['구매가격'])
    # 국제운송료 (있으면)
    if '국제운송료' in df.columns:
        df['국제운송료'] = _to_numeric_safe(df['국제운송료'])

    # 마켓주문번호 정규화
    df['마켓주문번호'] = df['마켓주문번호'].apply(_normalize_order_no)

    # 간단메모 보존 (분류 엔진에서 사용, NaN → '')
    memo_col = MANGO_COLS.get('memo', '간단메모')
    if memo_col in df.columns:
        df[memo_col] = df[memo_col].fillna('').astype(str)

    # 사이트주문번호 문자열 유지 (split 에서 사용)
    site_col = MANGO_COLS.get('site_order_no', '사이트주문번호')
    if site_col in df.columns:
        df[site_col] = df[site_col].fillna('').astype(str).str.strip()

    # _uid 생성: 마켓주문번호 + 수령인명 + 인덱스 (고유성 보장)
    df['_uid'] = (
        df.index.astype(str) + '_' +
        df['마켓주문번호'].astype(str) + '_' +
        df['수령인명'].astype(str).str.slice(0, 10)
    )

    return df


def split_by_site_order_no(buy_df: pd.DataFrame) -> tuple:
    """사이트주문번호(G열) 공백 여부로 더망고 DF 분할.

    Returns:
        (buy_valid_df, buy_missing_df)
        - buy_valid_df: G열에 값 있음 → 매칭·마진 집계 대상
        - buy_missing_df: G열 공백 → 블랙스팟 전용, 집계 제외
    """
    site_col = MANGO_COLS.get('site_order_no', '사이트주문번호')
    if site_col not in buy_df.columns:
        # 컬럼 자체가 없으면 전부 valid 로 간주 (기존 엑셀 호환)
        logger.warning(f"'{site_col}' 컬럼이 없습니다. 전체를 valid 로 처리.")
        return buy_df.copy(), buy_df.iloc[0:0].copy()

    def _is_missing(v):
        if pd.isna(v):
            return True
        s = str(v).strip()
        return s in ('', '0', 'nan', 'None', 'NaN')

    is_missing = buy_df[site_col].apply(_is_missing)
    buy_missing = buy_df[is_missing].copy().reset_index(drop=True)
    buy_valid   = buy_df[~is_missing].copy().reset_index(drop=True)

    logger.info(
        f"G열 분리: valid={len(buy_valid)}, missing={len(buy_missing)} "
        f"(전체 {len(buy_df)})"
    )
    return buy_valid, buy_missing

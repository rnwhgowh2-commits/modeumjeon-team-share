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

# 롯데온 미정산(구매확정 전) 정산 추정 계수 — 원본(샵마인) 정산과 마켓주문번호 조인해 역산.
#  실결제(actualAmt) 확보분: 원본정산/실결제 = 0.947(수수료 ~5.3%).
#  실결제 미확보분(actualAmt 누락): 원본정산/판매가(단가×수량) = 0.884.
#  ⚠️ 실결제 미확보는 롯데온 주문 API 가 actualAmt 를 못 준 것 → 근본은 그 조회 보강.
LO_FEE_FACTOR_PAID = 0.947
LO_FEE_FACTOR_LIST = 0.884

# 11번가 미정산(배송완료·배송중 = stlPlnAmt 없음) 정산 추정 — 원본 조인 역산.
#  실결제(ordPayAmt) 확보분: 원본정산/실결제 = 0.964. 실결제 미확보(단가만): 원본정산/단가×수량 = 0.869.
EL_FEE_FACTOR_PAID = 0.964
EL_FEE_FACTOR_LIST = 0.869

# matcher 가 읽는 컬럼 + 마진 표시에 필요한 컬럼
SELL_COLUMNS = [
    "오픈마켓주문번호", "상품명", "옵션", "수량", "단가", "실결제금액",
    "정산예상금액_배송비포함", "마켓수수료", "수수료율", "쇼핑몰",
    "쇼핑몰별칭",        # 계정명 — matcher 가 extract_account 로 '계정' 산출(다계정 구분)
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


# order_export '판매처'별 API 주문상태 → 샵마인 정산 어휘 정규화.
# 위험값(정산O 로 오분류되는 값)만 remap + '우연히 맞던' 값 명시 pin.
# 이미 SETTLEMENT_* 에 정확히 있는 값은 여기 없으면 identity 통과.
_ESM_STATUS = {"구매결정": "구매확정"}   # 옥션·G마켓 공통 (ESM 2.0). esm 클레임 값은 여기에 추가.
_STATUS_TO_SHOPMINE = {
    "롯데온": {
        "철회": "취소완료",        # ★odPrgsStepCd 22 — 기본값 O 로 새던 것
        "회수확정": "반품완료",     # ★odPrgsStepCd 26 — 기본값 O 로 새던 것
        "발송완료": "발송완료(배송중)",  # pin: 정산O
    },
    "옥션":  _ESM_STATUS,   # pin: 정산O
    "G마켓": _ESM_STATUS,
    "쿠팡":  {"업체직접배송": "배송중"},  # pin: 정산O
}


def status_to_shopmine(panmaecheo, api_status):
    """(판매처, API 주문상태) → 샵마인 정산 정규 문자열. 미지 값은 원본 통과."""
    status = "" if api_status is None else str(api_status).strip()
    if not status:
        return status
    per = _STATUS_TO_SHOPMINE.get(str(panmaecheo).strip())
    if per and status in per:
        return per[status]
    return status


def _to_int_or_blank(v):
    """정수로. 못 하면 "" (0 으로 폴백하지 않는다 — 0 은 '정산 0원'을 뜻하므로).

    쉼표(`"103,000"`)·소수점 문자열(`"88000.0"`)·float 을 모두 받는다. 이걸 놓치면
    정산액이 조용히 사라져 `none` 으로 강등되고, 사용자는 이유 없이 '정산 확인 불가'를 본다.
    파싱 실패는 빈 값이 아닐 때만 로그로 남긴다.
    """
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return ""
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        logger.debug("정수 변환 실패(무시): %r", v)
        return ""


def _settlement_for(row: dict):
    """SellRow 의 정산예상금액_배송비포함 + _settle_source 결정. 스펙 §4.

    정산 없음(none) 은 빈칸이 아니라 0 이다. matcher 가 빈칸을 NaN 으로 바꾸는데,
    NaN 은 (a) JSON 직렬화를 깨뜨리고 (b) pandas sum() 이 건너뛰어 매입 손실을
    총합에서 지워버린다. 0 은 margin_rules.js 가 이미 '정산 없음'으로 읽는 센티널이며
    (정산 0 + 매입>0 → 의심손실), 실제로 0원에 정산되는 주문은 없다.
    출처의 정직성은 _settle_source='none' 태그가 보존한다.

    ★ 어느 필드를 읽는가 — `정산예정금(배송비포함)` 이 아니라 `정산예정금액` 이다.
      order_export 의 `정산예정금액` 은 이미 **상품정산 + 배송비정산**이고
      (COLUMN_META: "상품정산 + 배송비정산(수수료 차감)"),
      `정산예정금(배송비포함)` 은 거기에 **고객배송비 총액**을 한 번 더 더한다.
      그걸 마진 분자로 쓰면 배송건당 배송비만큼 마진이 부풀려진다.
      (샵마인 실파일 대조: 정산예상금액 25330 + 고객배송비 3000 = (배송비포함) 28330.
       샵마인의 (배송비포함)은 '상품정산 + 고객배송비' 라, 우리 `정산예정금액` 과
       배송건에서 배송비 수수료만큼 차이가 난다. 우리 쪽이 보수적(작다) — 실수취액에 가깝다.
       정확한 차이는 골든테스트 2단계(scripts/margin_api_parity.py, 서버 실행)로 정량화한다.)

    롯데온만 재계산한다 — order_export 가 정산액 자리에 actualAmt(실결제)를 넣기 때문.
    actualAmt 는 배송비를 이미 포함하므로 배송비를 다시 더하지 않는다.
    """
    src = row.get("_settle_source", "none")
    # ★ 배송비(고객배송비) — 샵마인 정산예상금액_배송비포함 = 상품정산(수수료차감) + 배송비(전액).
    #   ★★실결제금액 = 상품가(배송비 미포함) 이다. 샵마인 실증: 실결제=정산+수수료, 고객배송비는
    #     별도 컬럼(실결제 30,318 + 수수료 1,744 = 정산 28,574, 배송비 4,000은 실결제 밖).
    #     따라서 추정 정산 = (상품 추정: 실결제 또는 단가×수량 × 수수료율) + 배송비(전액 가산).
    #     수수료율은 상품에만, 배송비는 원본 정의대로 전액(수수료 안 깎음).
    #   order_export 가 배송건 첫 행에만 배송비를 싣고 나머지 0 → 행별 그대로 더해 중복 없음.
    #   정산완료(real: 롯데온 실결제−실수수료·11번가 stlPlnAmt)는 이미 배송비 포함 → 재가산 안 함.
    _ship = _to_int_or_blank(row.get("배송비")) or 0
    if row.get("판매처") == "롯데온":
        paid = _to_int_or_blank(row.get("실결제금액"))
        fee = _to_int_or_blank(row.get("마켓수수료"))
        if paid != "" and fee != "" and fee > 0:
            return paid - fee, "real"            # 실수수료 확보 → 정확(배송비 포함 실정산)
        # ★ 미정산(구매확정 전 → 마켓수수료 미기록) 추정. 실수수료 없다고 0(손실 둔갑) 금지.
        #   실결제(상품가)×0.947 + 배송비, 없으면 단가×수량×0.884 + 배송비.
        if paid != "" and paid > 0:
            return round(paid * LO_FEE_FACTOR_PAID) + _ship, "estimated"
        unit = _to_int_or_blank(row.get("단가"))
        if unit != "" and unit > 0:
            try:
                qty = int(row.get("수량") or 1)
            except (TypeError, ValueError):
                qty = 1
            return round(unit * qty * LO_FEE_FACTOR_LIST) + _ship, "estimated"
        return 0, "none"

    if row.get("판매처") == "11번가":
        if src != "none":                        # stlPlnAmt(정산예정금액) 확보 → real(배송비 포함)
            settle = _to_int_or_blank(row.get("정산예정금액"))
            if settle != "":
                return settle, src
        # ★ 미정산(배송완료·배송중 = stlPlnAmt 없음) 추정. 실수수료 없다고 0(손실 둔갑) 금지.
        paid = _to_int_or_blank(row.get("실결제금액"))
        if paid != "" and paid > 0:
            return round(paid * EL_FEE_FACTOR_PAID) + _ship, "estimated"
        unit = _to_int_or_blank(row.get("단가"))
        if unit != "" and unit > 0:
            try:
                qty = int(row.get("수량") or 1)
            except (TypeError, ValueError):
                qty = 1
            return round(unit * qty * EL_FEE_FACTOR_LIST) + _ship, "estimated"
        return 0, "none"

    if src == "none":
        return 0, "none"
    settle = _to_int_or_blank(row.get("정산예정금액"))
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
            # order_export 가 _rows_for 에서 계정명(display_name)을 쇼핑몰별칭에 태깅함(L1050).
            # 이걸 실어야 matcher 가 '계정'을 산출해 다계정(롯데온 7계정 등)을 구분한다.
            "쇼핑몰별칭": r.get("쇼핑몰별칭", ""),
            "수취고객명": r.get("수령자", ""),
            "주문일": r.get("주문일", ""),
            "송장입력": r.get("송장입력", ""),
            "주문상태": status_to_shopmine(r.get("판매처", ""), r.get("주문상태", "")),
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

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
    "배송비",            # 고객배송비(API) — 샵마인 고객배송비와 대조·정산 검증용
    # ── 주문내역 매출 필드 동기화(사장님 지시 2026-07-23) ──────────────────
    #  마진계산기가 매출 금액을 스스로 다시 만들면 주문내역과 조용히 어긋난다
    #  (matcher 는 `판매가`를 단가×수량으로만 계산해 **옵션추가금을 빠뜨린다**).
    #  주문내역이 이미 확정한 값을 그대로 실어 두 화면이 같은 숫자를 보게 한다.
    "옵션추가금", "상품금액", "총주문금액",
    "정산예상금액_배송비포함", "마켓수수료", "수수료율", "쇼핑몰",
    "쇼핑몰별칭",        # 계정명 — matcher 가 extract_account 로 '계정' 산출(다계정 구분)
    "수취고객명", "주문일", "송장입력", "택배사", "주문상태",
    "판매경로",          # 롯데온 유입경로(제휴=상품가 2% / 롯데ON=0) — 크롤 확정, 마진 표시용
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

_API_MARKET_ORDER = ["smartstore", "coupang", "lotteon", "eleven11", "auction", "gmarket"]


def api_markets() -> list:
    """마진계산기가 API 로 끌어올 마켓 — order_export.supported_markets() 단일 원천.

    ★ 상수로 고정하면 안 된다. 라이브 검증으로 옥션·G마켓이 열려도 마진계산기만
      옛 목록에 묶여, 주문내역엔 보이는데 마진엔 안 잡히는 모순이 생긴다.
    아직 안 열린 마켓은 기존대로 샵마인 엑셀 보조 업로드로 채운다.
    """
    from lemouton.markets import order_export as _oe
    sup = _oe.supported_markets()
    return [m for m in _API_MARKET_ORDER if m in sup]

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


# 주문내역 탭이 화면에 뿌리는 정산 필드 이름(order_export._finalize_rows 산출).
#  ⚠️ 엑셀 열 위치로 부르지 말 것(구조는 계속 바뀐다) — 필드명이 유일한 식별자다.
_SETTLE_INCL_FIELD = "정산예정금(배송비포함)"

# 주문내역이 정산액을 확정했다고 보는 태그. 이 태그가 아니면 그 값을 믿지 않는다
# (order_export 는 취소·미정산 행에도 계산 흔적을 남길 수 있다).
_TRUSTED_SETTLE_TAGS = ("real", "store", "estimated")


def _settlement_for(row: dict):
    """SellRow 의 정산예상금액_배송비포함 + _settle_source 결정. 스펙 §4.

    ■ 단일 원천 = 주문내역 탭이 보여주는 그 값 (`정산예정금(배송비포함)`)
      order_export._finalize_rows 가 6마켓 공통 규약으로 만든다:
        `정산예정금액`(상품분) + `배송비`(고객배송비·배송건 첫 행에만) = `정산예정금(배송비포함)`
      마진계산기는 **이 값을 다시 계산하지 않는다**. 예전엔 여기서 `정산예정금액` 을
      읽어 마켓별로 배송비를 손으로 더했는데, 주문내역이 규약을 바꿀 때마다(2026-07-23
      쿠팡 정산예정금액을 상품분만으로 전환) 이쪽만 옛 정의로 남아 조용히 어긋났다:
        · 쿠팡 = 고객배송비만큼 마진 **과소**
        · 롯데온 취소완료 = 수수료 0 을 '미정산'으로 오해해 **가짜 추정 정산**을 만들어 냄
        · 옥션·G마켓 취소완료 = 배송비가 정산으로 잔존
      두 화면이 같은 숫자를 보게 하는 것이 이 함수의 유일한 책임이다.

    ■ 우선순위
      ① 취소완료 → 0 확정(주문내역과 동일 규약: 거래 무산이면 정산·수수료 없음)
      ② 주문내역이 확정한 `정산예정금(배송비포함)` → 그대로
      ③ 주문내역이 정산을 못 채운 마켓(11번가 배송중·롯데온 조회 실패) → 상품 추정 + 배송비
      ④ 재료 없음 → 0 (`none`)

    ■ 왜 0 이고 빈칸이 아닌가
      정산 없음(none)은 빈칸이 아니라 0 이다. matcher 가 빈칸을 NaN 으로 바꾸는데,
      NaN 은 (a) JSON 직렬화를 깨뜨리고 (b) pandas sum() 이 건너뛰어 매입 손실을
      총합에서 지워버린다. 0 은 margin_rules.js 가 이미 '정산 없음'으로 읽는 센티널이며
      (정산 0 + 매입>0 → 의심손실), 실제로 0원에 정산되는 주문은 없다.
      출처의 정직성은 _settle_source 태그가 보존한다.
    """
    src = str(row.get("_settle_source") or "none")

    # ── ① 취소완료 = 거래 무산 → 정산 0 확정 ──────────────────────────────
    #  order_export 가 zero_cancel 로 태깅한다. 주문상태 문자열도 함께 본다 —
    #  적재분(order_store)에 태그가 없던 시절 행이 남아 있어도 같은 판정이 나오게.
    if src == "zero_cancel" or "취소완료" in str(row.get("주문상태") or ""):
        return 0, "zero_cancel"

    # ── ② 주문내역이 확정한 값을 그대로 ───────────────────────────────────
    incl = _to_int_or_blank(row.get(_SETTLE_INCL_FIELD))
    if incl != "" and src in _TRUSTED_SETTLE_TAGS:
        return incl, src

    # ── ③ 주문내역이 못 채운 정산 추정 ────────────────────────────────────
    #  실수수료가 없다고 0 으로 두면 매출이 통째로 사라져 '손실'로 둔갑한다.
    #  ★실결제금액 = 상품가(배송비 미포함) 규약이라, 상품분에만 수수료율을 곱하고
    #    배송비는 원본 정의대로 전액 가산한다(샵마인 실증: 실결제 30,318 + 수수료
    #    1,744 = 정산 28,574, 고객배송비 4,000 은 실결제 밖).
    #  배송비는 order_export 가 배송건 첫 행에만 실으므로 행별 가산에 중복이 없다.
    factors = {"롯데온": (LO_FEE_FACTOR_PAID, LO_FEE_FACTOR_LIST),
               "11번가": (EL_FEE_FACTOR_PAID, EL_FEE_FACTOR_LIST)}.get(
        str(row.get("판매처") or ""))
    if factors:
        f_paid, f_list = factors
        ship = _to_int_or_blank(row.get("배송비")) or 0
        paid = _to_int_or_blank(row.get("실결제금액"))
        if paid != "" and paid > 0:
            return round(paid * f_paid) + ship, "estimated"
        unit = _to_int_or_blank(row.get("단가"))
        if unit != "" and unit > 0:
            try:
                qty = int(row.get("수량") or 1)
            except (TypeError, ValueError):
                qty = 1
            return round(unit * qty * f_list) + ship, "estimated"

    # ── ④ 재료 없음 ───────────────────────────────────────────────────────
    return 0, "none"


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
            "배송비": _to_int_or_blank(r.get("배송비")) or 0,   # order_export 가 배송건 첫 행에만 실음
            # ── 주문내역 매출 필드 그대로(재계산 금지) ──
            #  `상품금액`=단가×수량 / `총주문금액`=상품금액+옵션추가금.
            #  matcher 의 `판매가`(단가×수량)는 옵션추가금을 못 담으므로, 옵션가가 붙은
            #  주문에서 마진탭 매출이 주문내역보다 작게 나온다. 그 차이를 눈으로 볼 수
            #  있도록 두 값을 함께 싣는다(pipeline 이 matched 행에 재부착).
            "옵션추가금": _to_int_or_blank(r.get("옵션추가금")) or 0,
            "상품금액": _to_int_or_blank(r.get("상품금액")) or 0,
            "총주문금액": _to_int_or_blank(r.get("총주문금액")) or 0,
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
            # 판매처 택배사 — 지금은 ESM(옥션·G마켓)만 실값(TakbaeName). 다른 마켓은 빈 값이라
            #  화면에서 송장번호만 나온다(코드가 불안정한 곳의 택배사명을 지어내지 않는다).
            "택배사": r.get("택배사", ""),
            "주문상태": status_to_shopmine(r.get("판매처", ""), r.get("주문상태", "")),
            "판매경로": r.get("판매경로", ""),   # 롯데온 제휴/롯데ON(제휴 2% 표시)
            "_settle_source": src,
            "_sell_origin": "api",
        })
    df = pd.DataFrame(out, columns=SELL_COLUMNS)
    if df.empty:
        df = pd.DataFrame(columns=SELL_COLUMNS)
    return df


# 마진 분석의 기본 라이브 보충 일수 = 0(저장분만).
#
# 🔴 왜 0 인가 — 2026-07-23 라이브 실측:
#   마진 분석은 6마켓을 **한 요청**에 묶어 조회한다. 마켓별 소요는
#   옥션 58.1초 · G마켓 46.5초 · 스스 26.4초 · 쿠팡 11.5초 · 11번가 8.3초 · 롯데온 4.1초,
#   6마켓 합류 61.7초. 그 뒤에 매칭·집계·블랙스팟 분류·파일 업로드·DB 저장이 더 붙는다.
#   gunicorn 이 워커를 끊으면(당시 60초) 응답이 JSON 이 아니게 되고 화면엔 "서버 오류"만
#   뜬다 — 실제로 분석이 매번 실패했다. 앞단 Cloudflare 도 100초에서 끊는다.
#   그래서 분석은 **이미 쌓인 주문만 읽는다**(DB 읽기, 몇 초). 최신 주문은 화면의
#   「분석 시작」이 분석에 들어가기 전에 static/margin_refresh_orders.js 로 마켓별
#   /api/orders-ingest/run-sync 를 나눠 호출해 채운다(요청 하나가 길어지지 않게
#   쪼개는 게 핵심). 2026-08-02 이전엔 이걸 「최신까지 불러오기」 버튼으로 직접
#   눌렀는데, 분석이 어차피 같은 걸 먼저 돌려 중복이라 버튼은 삭제했다.
#   적재 자체는 스케줄러가 20분마다 채운다.
MARGIN_LIVE_TAIL_DAYS = 0


def _fetch_rows(since, until, markets, live_tail_days: int = MARGIN_LIVE_TAIL_DAYS):
    """주문 행 조회 seam — 테스트에서 monkeypatch 한다.

    **적재분(order_store)만 읽는다**(기본). live_tail_days>0 이면 그만큼 라이브로 보충한다
    — 다만 그 경로는 위 상수 주석의 이유로 마진 분석에선 쓰지 않는다.

    조용한 실패 금지(스펙 §9): 적재 범위가 요청보다 짧거나 라이브 보충이 실패하면
    warnings 에 사유를 담아 화면 배너로 노출한다(부분 결과를 완전한 것처럼 보이지 않게).
    """
    from lemouton.markets import order_source as _src
    warnings: list = []
    rows = _src.fetch_rows(since, until, markets, warnings=warnings,
                           live_tail_days=live_tail_days)
    return rows, warnings


def _one_row_per_line(rows: list) -> list:
    """같은 상품라인은 **최종 상태 한 줄만** 매출·정산에 쓴다(사장님 확정 2026-07-24).

    왜 필요한가 — 저장 키(마켓 식별자 조합)가 시절마다 달랐던 주문은 옛 키·새 키
    두 행으로 남아 있다(롯데온 실측 3건: 출고지시 37,599 + 배송완료 38,505 등).
    둘 다 매출 후보로 들어가면 매입 한 건에 어느 쪽이 붙느냐에 따라 정산이 906원씩
    흔들리고, 매칭이 어긋나면 같은 라인이 두 번 셀 위험도 있다.

    고르는 기준은 **마켓이 가장 최근에 알려준 행**(`_seen_at`, order_store 가 실어 준
    관측 시각)이다. 상태 이름으로 서열을 매기면(배송완료 > 출고지시 …) 마켓마다 용어가
    달라 새 마켓·용어 변경에서 조용히 틀린다 — 지어낸 서열 대신 관측 사실을 쓴다.

    ★ 클레임 행(_kind='change')은 건드리지 않는다 — 취소·반품은 이력이자 정산 0 판정의
      근거라 합치면 취소 사실이 사라진다.
    ★ 식별자(_line_uid)가 없으면 합치지 않는다 — 정체 불확실한 행을 합치면 남의 주문과
      섞인다(그쪽이 더 위험).
    """
    picked: dict = {}
    out: list = []
    for r in rows or []:
        uid = str((r or {}).get("_line_uid") or "").strip()
        if not uid or str((r or {}).get("_kind") or "") == "change":
            out.append(r)                       # 합치지 않는 행은 그대로 통과
            continue
        seen = str((r or {}).get("_seen_at") or "")
        prev = picked.get(uid)
        if prev is None or seen > prev[0]:
            picked[uid] = (seen, r)
    dropped = sum(1 for r in rows or []
                  if str((r or {}).get("_line_uid") or "").strip()
                  and str((r or {}).get("_kind") or "") != "change") - len(picked)
    if dropped:
        logger.info("마진 매출: 같은 라인 중복 %d행을 최종 상태 1건으로 접었다", dropped)
    out.extend(r for _s, r in picked.values())
    return out


# 실정산을 실제로 주는 마켓별 '이만큼 지났는데도 실정산이 안 들어왔으면 못 받아온 것'
#  판정 임계일. 정산 확정 시점이 마켓마다 달라 임계도 다르다(거짓 경보 방지):
#   · 옥션·G마켓·스마트스토어 = 구매확정 며칠 뒤 → 40일이면 확정됐어야 한다.
#   · 쿠팡 = 배송완료 후 주간 인식 → 조금 넉넉히 50일.
#   · 11번가 = 배송완료 후 정산이 가장 늦다 → 60일.
#   · 롯데온 = 정산 스윕 미구현(2026-07-25) — 여기서 드러내 눈에 보이게 한다.
#  ★한 마켓이라도 이 값이 계속 안 줄면 그 마켓 정산 수집이 막힌 것 → 화면에 숫자로 노출.
_SETTLE_STALE_DAYS_BY_MARKET = {
    "옥션": 40, "G마켓": 40, "스마트스토어": 40,
    "쿠팡": 50, "롯데온": 45, "11번가": 60,
}
_SETTLE_STALE_DAYS = 40   # 하위호환(기존 참조)


# 롯데온 정산 크롤이 이만큼 안 돌면 「멈춘 것」으로 본다.
#  회차는 60분이라 12시간이면 12번을 내리 놓친 것 — 크롬이 꺼져 있거나 로그인이
#  막힌 것이다. 너무 짧게 잡으면 밤새 PC 를 끈 것만으로 경보가 떠 거짓 경보가 된다.
LOTTEON_CRAWL_STALE_HOURS = 12


def lotteon_crawl_stalled_notice(session=None) -> Optional[str]:
    """롯데온 정산 크롤이 멈췄으면 화면에 띄울 문구. 안 멈췄으면 None.

    🔴🔴 왜 이게 필요한가 — 2026-08-03 실측으로 드러난 것:
      롯데온 정산 자동 수집이 **한 번도 돈 적이 없었다**(`last: null`). 표는 1,599건으로
      차 있었지만 전부 손으로 돌린 것이었고, 마지막 수집은 **10일 전**이었다. 그동안
      아무 에러도 없었다 — 실패가 아니라 「안 돈 것」이라 로그도 경보도 안 남는다.
      그 결과 롯데온 실정산율이 49% 까지 떨어져 있었는데 아무도 몰랐다.
      고치는 것만으로는 같은 종류를 또 놓친다 → **멈추면 화면에 뜨게** 만든다.

    ★왜 화면인가 — shared/notifier 의 채널(카카오톡·슬랙)은 전부 `enabled: False` 라
      notify() 를 불러도 아무 데도 안 간다(2026-08-03 설정 실측). 실제로 사장님 눈에
      닿는 자리는 화면뿐이다. 안 가는 알림을 붙여 놓고 「알림 됨」이라 하면 그게 더 위험하다.

    ★롯데온만 보는 이유 — 미정산 구간 정산예정금을 **크롤만이** 가져올 수 있는 마켓이
      롯데온뿐이다(공식 API 6종은 전부 구매확정 뒤). 나머지 5마켓은 서버가 API 로
      가져오므로 크롬과 무관하고, 그쪽 지연은 위 `_stale_settle_notice` 가 이미 센다.
    """
    import datetime as _d
    try:
        from lemouton.sourcing.models_v2 import LotteonSettlement
        from sqlalchemy import func
        own = False
        if session is None:
            from shared import db as _db
            if getattr(_db, "_is_sqlite", False):   # 폴백 SQLite = 테스트 잔재라 무의미
                return None
            session = _db.SessionLocal()
            own = True
        try:
            # ★[2026-08-03] 회차 기록이 있으면 **그걸 본다**. 아래 정산 표의 updated_at 은
            #   「값이 바뀐 시각」이라 양방향으로 틀린다:
            #     · 로그인은 됐는데 바뀐 정산이 없으면 → 멀쩡한데 「멈췄다」 (거짓 경보)
            #     · 한 계정이 막혀도 다른 계정 값 하나만 바뀌면 → 갱신돼 **경보가 안 뜬다**
            #   라이브 실측이 그 상태였다: 화면은 「7계정 성공」인데 두 계정 시각이
            #   7~10시간 낡아 있었다(막힌 게 아니라 바뀐 값이 없었던 것).
            #   회차 기록은 「돌았다」 자체라 짐작이 필요 없다.
            #  ★[2026-08-04] **자동 회차만** 센다. 수동 실행(화면에서 손으로 돌림)까지
            #    같이 세면 한 번 눌러 본 것만으로 배너가 조용해져 **자동이 죽어 있어도
            #    모른다**. 이 배너가 묻는 건 「손댈 필요 없이 굴러가고 있나」다.
            from lemouton.sourcing.models_v2 import LotteonCrawlRun
            last = (session.query(func.max(LotteonCrawlRun.ran_at))
                    .filter(LotteonCrawlRun.via == "auto").scalar())
            if last is None:
                # 기록이 아직 없는 과도기(확장 업데이트 전)에는 옛 방식으로 —
                # 갑자기 「한 번도 안 돌았다」고 외치면 그게 거짓 경보다.
                last = session.query(func.max(LotteonSettlement.updated_at)).scalar()
        finally:
            if own:
                session.close()
    except Exception:   # noqa: BLE001 — 진단이 본 기능을 죽이면 안 된다
        return None
    if last is None:
        return ("롯데온 정산 수집이 **한 번도 돌지 않았어요**. 크롬에서 「크롤 로그인」 화면을 "
                "열어 「자동 반복」을 켜 주세요 — 롯데온은 정산예정금을 판매자센터에서만 "
                "가져올 수 있어 이게 꺼져 있으면 그 금액이 추정치로 남습니다.")
    now = _d.datetime.now(_d.timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=_d.timezone.utc)
    hours = (now - last).total_seconds() / 3600.0
    if hours < LOTTEON_CRAWL_STALE_HOURS:
        return None
    since_txt = (f"{int(hours)}시간째" if hours < 48 else f"{int(hours // 24)}일째")
    return (f"롯데온 정산 수집이 **{since_txt} 멈춰 있어요**(마지막 "
            f"{last.astimezone().strftime('%m월 %d일 %H:%M')}). 크롬이 꺼져 있거나 "
            "판매자센터 로그인이 막힌 것일 수 있어요 — 크롬을 켜 두시고, 계속 이러면 "
            "「크롤 로그인」 화면에서 본인인증이 필요한 계정이 있는지 봐 주세요. "
            "그동안 롯데온 정산예정금은 추정치로 남습니다.")


def _stale_settle_notice(rows: list) -> Optional[str]:
    """실정산이 오래도록 안 들어온 주문을 **마켓별로 숫자로 드러낸다**(조용한 실패 금지).

    🔴 왜 필요한가 — 2026-07-25 사장님 신고("정상 정산인데 왜 0이냐")의 두 원인은
    **둘 다 에러를 남기지 않았다**: ①저장 병합이 근거 태그를 덮어씀 ②정산은 구매확정
    뒤에 확정되는데 오래된 주문을 다시 안 봄. 실패가 아니라 「안 본 것」이라 로그도 경보도
    없었고, 조용히 추정치로 남았다. 전 마켓 검수(2026-07-25)에서 스마트스토어 1,682·
    쿠팡 1,361·롯데온 453 이 같은 식으로 고착돼 있었다. 고치는 것만으로는 같은 종류를
    또 놓친다 — **마켓별로 안 들어온 건수가 보이게** 만든다(임계는 마켓별 정산 시점 반영).
    """
    import datetime as _d
    now = _d.datetime.now()
    per: dict = {}          # 마켓 → [건수, 최고령주문일]
    for r in rows or []:
        mk = str((r or {}).get("판매처") or "")
        thr = _SETTLE_STALE_DAYS_BY_MARKET.get(mk)
        if thr is None:
            continue
        if str((r or {}).get("_kind") or "") == "change":
            continue
        if str((r or {}).get("_settle_source") or "") in ("real", "zero_cancel"):
            continue
        od = str((r or {}).get("주문일") or "")[:10]
        if not od or od >= (now - _d.timedelta(days=thr)).strftime("%Y-%m-%d"):
            continue
        cnt, oldest = per.get(mk, (0, "9999-99-99"))
        per[mk] = (cnt + 1, min(oldest, od))
    if not per:
        return None
    total = sum(c for c, _ in per.values())
    parts = ", ".join(f"{mk} {c}건" for mk, (c, _) in
                      sorted(per.items(), key=lambda x: -x[1][0]))
    oldest_all = min(o for _, o in per.values())
    return (f"마켓 실정산액이 아직 안 들어와 **추정치**로 계산한 주문이 {total}건 있어요 "
            f"({parts} · 가장 오래된 주문 {oldest_all}). 정산은 구매확정·배송완료 뒤에 "
            "확정되므로 보통 자동으로 채워집니다 — 이 숫자가 계속 줄지 않으면 그 마켓 "
            "정산 수집이 막힌 것이니 알려 주세요.")


def from_api(since: _dt.datetime, until: _dt.datetime,
             markets: Optional[list] = None,
             live_tail_days: int = MARGIN_LIVE_TAIL_DAYS) -> pd.DataFrame:
    """판매처 주문 → SellRow DF. df.attrs['warnings'] 에 빠진 구간·계정 사유가 담긴다.

    기본은 저장분만 읽는다(MARGIN_LIVE_TAIL_DAYS=0). 저장분은 스케줄러가 20분마다
    갱신하므로, 그 사이에 들어온 주문은 빠질 수 있다 — 그 사실을 warnings 로 **반드시**
    표면화한다(빈 구간을 완전한 것처럼 보이면 금전 오판).
    """
    rows, warnings = _fetch_rows(since, until, markets or api_markets(),
                                 live_tail_days=live_tail_days)
    rows = _one_row_per_line(rows)
    # ★ warnings 와 notices 를 섞지 않는다 — warnings 는 화면에서 "이 마켓은 연동이
    #   안 됐거나 조회 실패해 **매출에서 제외**했어요" 라는 빨간 배너로 렌더된다.
    #   저장분으로 분석했다는 건 제외가 아니라 안내다. 섞으면 멀쩡한 마켓이 빠진 것처럼
    #   보여 거짓 경보가 된다(2026-07-23 배선 직후 발견).
    notices: list = []
    if live_tail_days <= 0:
        notices.append(
            "저장해둔 주문으로 분석했어요 — 「분석 시작」이 **최근 며칠치(마켓별 2~5일)를 "
            "먼저 받아온 뒤** 저장분을 읽습니다. 그보다 과거 구간은 20분마다 도는 자동 "
            "수집이 채운 것이라, **방금 추가한 판매처 계정**의 옛 주문은 아직 빠져 있을 "
            "수 있어요.")
    stale_note = _stale_settle_notice(rows)
    if stale_note:
        notices.append(stale_note)
    # 롯데온 정산 크롤이 멈췄으면 맨 앞에 — 위 문구("보통 자동으로 채워집니다")가
    #  멈춰 있는 동안엔 **틀린 안내**가 되므로, 원인을 먼저 보여준다.
    crawl_note = lotteon_crawl_stalled_notice()
    if crawl_note:
        notices.insert(0, crawl_note)
    df = _rows_to_df(rows)
    df.attrs["warnings"] = warnings
    df.attrs["notices"] = notices
    logger.info("from_api: rows=%d warnings=%d notices=%d live_tail_days=%d",
                len(df), len(warnings), len(notices), live_tail_days)
    return df

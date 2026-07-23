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
    "수취고객명", "주문일", "송장입력", "주문상태",
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
            "주문상태": status_to_shopmine(r.get("판매처", ""), r.get("주문상태", "")),
            "판매경로": r.get("판매경로", ""),   # 롯데온 제휴/롯데ON(제휴 2% 표시)
            "_settle_source": src,
            "_sell_origin": "api",
        })
    df = pd.DataFrame(out, columns=SELL_COLUMNS)
    if df.empty:
        df = pd.DataFrame(columns=SELL_COLUMNS)
    return df


def _fetch_rows(since, until, markets):
    """주문 행 조회 seam — 테스트에서 monkeypatch 한다.

    **적재분(order_store) 우선 + 최근 며칠 라이브 보충**(order_source.fetch_rows).
    예전엔 매번 라이브(combined_order_rows)라 과거 1년치를 부르면 수백~수천 호출로
    수십 분·실패했다. 이제 과거는 저장분을 즉시 읽고 최근 꼬리만 라이브라 빠르다.

    조용한 실패 금지(스펙 §9): 적재 범위가 요청보다 짧거나 라이브 보충이 실패하면
    warnings 에 사유를 담아 화면 배너로 노출한다(부분 결과를 완전한 것처럼 보이지 않게).
    """
    from lemouton.markets import order_source as _src
    warnings: list = []
    rows = _src.fetch_rows(since, until, markets, warnings=warnings)
    return rows, warnings


def from_api(since: _dt.datetime, until: _dt.datetime,
             markets: Optional[list] = None) -> pd.DataFrame:
    """판매처 마켓 API → SellRow DF. df.attrs['warnings'] 에 계정 제외 사유가 담긴다."""
    rows, warnings = _fetch_rows(since, until, markets or api_markets())
    df = _rows_to_df(rows)
    df.attrs["warnings"] = warnings
    logger.info("from_api: rows=%d warnings=%d", len(df), len(warnings))
    return df

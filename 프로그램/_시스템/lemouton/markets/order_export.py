# -*- coding: utf-8 -*-
"""판매처 주문 → 발송관리 엑셀(샵마인 형식) 재사용 모듈.

책임: 마켓 주문 조회 + 정산예정금액 조인 → 16컬럼 행 → xlsx 바이트.
현재 스마트스토어만 실배선(주문+정산 코드·실계정 검증 완료 2026-07-07).
쿠팡=키/검증 후, 롯데온=주문 API 신규 후. 추측·폴백 금지(CLAUDE.md).
서버(등록 IP)에서 실행. 인증·rate limit 은 각 플랫폼 client 담당.
"""
from __future__ import annotations

import datetime as _dt
import io
from typing import Optional

KST = _dt.timezone(_dt.timedelta(hours=9))

# 선택·순서 조정 가능한 전체 열(사용자 요청: B=판매처, C=주문상태). 기본 순서 = 이 목록.
ALL_COLUMNS = ["주문일", "판매처", "주문상태", "상품명", "옵션", "수량",
               "수령자", "수령자전화번호", "주소", "우편번호", "배송메시지",
               "구매자", "구매자번호", "단가", "배송비", "상품금액", "주문금액",
               "정산예정금액",
               # 샵마인 대조로 추가(2026-07-08) — 판매처관리 계정명·주문번호·수수료·송장 등.
               "오픈마켓주문번호", "쇼핑몰별칭", "송장입력", "실결제금액",
               "총주문금액", "옵션추가금", "마켓수수료", "수수료율", "정산예정금(배송비포함)"]
# 상품금액 = 단가×수량 / 주문금액 = 상품금액 + 배송비(배송건당 1회) / 정산예정금액 = 상품정산+배송비정산.
# 배송비는 배송건(묶음) 단위 → 배송건 첫 행에만 표시(나머지 0, 합계 중복 방지).
# 정산예정금액 = 상품 정산 + 배송비 정산(각자 수수료 차감). 배송비는 별도 정산 라인
# (쿠팡 deliveryFee.settlementAmount·스스 DELIVERY행·롯데온 실결제 포함).
DEFAULT_COLUMNS = list(ALL_COLUMNS)
HEADER = DEFAULT_COLUMNS   # 하위호환 별칭

# 열 구분자(메타): kind=calc(우리가 별도 계산) / api(마켓 원본). desc=계산식·출처.
# 양식 설정에서 열마다 이 구분자를 보여줘 추가/삭제/순서변경을 명확히 한다.
COLUMN_META = {
    "주문상태":     {"kind": "api",  "desc": "마켓 상태코드→한글"},
    "단가":         {"kind": "api",  "desc": "상품 개당가"},
    "배송비":       {"kind": "api",  "desc": "배송건(묶음) 배송비"},
    "상품금액":     {"kind": "calc", "desc": "단가 × 수량"},
    "주문금액":     {"kind": "calc", "desc": "상품금액 + 배송비"},
    "정산예정금액": {"kind": "calc", "desc": "상품정산 + 배송비정산(수수료 차감)"},
    "오픈마켓주문번호": {"kind": "api",  "desc": "마켓 주문번호(ordNo·odNo·orderId 등)"},
    "쇼핑몰별칭":   {"kind": "calc", "desc": "판매처관리 계정명(별칭)"},
    "송장입력":     {"kind": "api",  "desc": "송장번호(없으면 '송장미입력')"},
    "실결제금액":   {"kind": "api",  "desc": "고객 실결제(할인 반영). 없으면 총주문금액"},
    "총주문금액":   {"kind": "calc", "desc": "단가×수량 + 옵션추가금"},
    "옵션추가금":   {"kind": "api",  "desc": "옵션 추가금(마켓 제공 시)"},
    "마켓수수료":   {"kind": "calc", "desc": "실결제 − 정산예정금액(둘 다 있을 때)"},
    "수수료율":     {"kind": "calc", "desc": "마켓수수료 ÷ 총주문금액"},
    "정산예정금(배송비포함)": {"kind": "calc", "desc": "정산예정금액 + 고객배송비"},
}


def column_meta(col: str) -> dict:
    """열의 구분자(kind·desc). 미등록은 마켓 원본으로 간주."""
    return COLUMN_META.get(col, {"kind": "api", "desc": "마켓 원본"})


def columns_meta() -> dict:
    """전체 열 → 구분자 매핑(양식 설정 UI 표시용)."""
    return {c: column_meta(c) for c in ALL_COLUMNS}

# 마켓별 원시 상태코드 → 한글. 미매핑은 원값 그대로(추측 금지).
_STATUS_KO = {
    "smartstore": {"PAYMENT_WAITING": "결제대기", "PAYED": "결제완료", "DELIVERING": "배송중",
                   "DELIVERED": "배송완료", "PURCHASE_DECIDED": "구매확정",
                   "CANCELED": "취소완료", "RETURNED": "반품완료", "EXCHANGED": "교환완료",
                   "CANCEL_REQUEST": "취소요청", "RETURN_REQUEST": "반품요청",
                   "EXCHANGE_REQUEST": "교환요청"},
    "coupang": {"ACCEPT": "결제완료", "INSTRUCT": "상품준비중", "DEPARTURE": "배송지시",
                "DELIVERING": "배송중", "FINAL_DELIVERY": "배송완료",
                "NONE_TRACKING": "업체직접배송"},
    # 롯데온 odPrgsStepCd(공식문서 apiNo140 실측 12코드 전체). 209는 11 고정 → 140으로 현재단계 반영.
    "lotteon": {"11": "출고지시", "12": "상품준비", "13": "발송완료", "14": "배송완료",
                "15": "수취완료", "21": "취소완료", "22": "철회", "23": "회수지시",
                "24": "회수진행", "25": "회수완료", "26": "회수확정", "27": "반품완료"},
    # 옥션·G마켓(ESM 2.0) 공통 — orderStatus 1~5.
    "esm": {"1": "결제완료", "2": "배송준비중", "3": "배송중",
            "4": "배송완료", "5": "구매결정"},
}

# 이미 발송/완료 단계 — 송장이 비어 있으면 '미입력'(발송 전)이 아니라 '확인 불가'
#   (발송은 됐으나 마켓이 번호를 안 줌)로 구분 표기한다.
#   특히 11번가는 구매확정 주문의 invcNo 를 API로 제공하지 않아, '미입력'으로 두면 오해된다.
_SHIPPED_STATES = {"배송중", "배송완료", "발송완료", "수취완료", "구매확정", "구매결정", "배송지시"}


def _status_ko(market, raw):
    if raw in (None, ""):
        return ""
    return _STATUS_KO.get(market, {}).get(str(raw), str(raw))

SUPPORTED = {"smartstore", "lotteon", "coupang", "eleven11"}   # UI 엑셀버튼 노출. 실키=서버 UI저장.
# 마켓 키 → 한글 표시명(사용자 배너·경고용). 미등록 키는 원문 그대로.
_MARKET_KO = {"smartstore": "스마트스토어", "lotteon": "롯데온", "coupang": "쿠팡",
              "eleven11": "11번가", "auction": "옥션", "gmarket": "G마켓"}


def market_label(market: str) -> str:
    """마켓 키의 한글 표시명. 미등록은 원문."""
    return _MARKET_KO.get(market, market)


def _ensure_kst(dt_val):
    """naive datetime → KST-aware(이미 aware 면 그대로, None/비datetime 은 그대로).

    ★ 마켓 빌더(smartstore_order_rows 등)는 now=datetime.now(KST)(aware)와 since/until 을
      비교한다. 라이브 마진 경로는 naive(_parse_dt: strptime/date)를 넘겨
      'can't compare offset-naive and offset-aware datetimes' 로 그 마켓 조회가 통째 실패했다
      → 스마트스토어 제외 → 매출 누락·마진 마이너스(라이브 실측). 여기서 KST 로 통일한다.
    """
    if isinstance(dt_val, _dt.datetime) and dt_val.tzinfo is None:
        return dt_val.replace(tzinfo=KST)
    return dt_val


def _market_fail_msg(market: str, err: Exception) -> str:
    """마켓 통째 실패 → 사용자 배너 문구(한글 마켓명 + 사유). 조용한 실패 금지."""
    return (f"[{market_label(market)}] 매출(주문) 조회에 실패해 이 마켓을 분석에서 "
            f"제외했어요: {err}")
# 11번가 = 서버 실호출 검증 완료(2026-07-08): 주문(complete)+정산예정금액(stlPlnAmt) 실응답 확인.
# 옥션·G마켓(auction·gmarket)은 키 입력+실호출 검증 후 추가.
# 마켓 → 계정 시크릿 env_prefix(판매처 계정 기본). load_credentials 로 실키 로드.
_ENV_PREFIX = {"smartstore": "SMARTSTORE_MAIN", "coupang": "COUPANG_MAIN",
               "lotteon": "LOTTEON_MAIN",
               "auction": "AUCTION_MAIN", "gmarket": "GMARKET_MAIN",
               "eleven11": "ELEVEN11_MAIN"}


def _g(o, *keys, default=""):
    """중첩 dict 후보 키 탐색(값 있으면 반환)."""
    for k in keys:
        cur, ok = o, True
        for p in k.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return default


def smartstore_order_rows(since: _dt.datetime, until: _dt.datetime,
                          client=None, include_settlement: bool = True) -> list:
    """스마트스토어 [since,until] 주문 → 16컬럼 행(dict) 리스트.

    변경 상품주문 내역 조회(정식 코드) → 상세 → 정산예정금액(결제일 기준) 조인.
    정산 없는 주문은 빈칸(폴백 0 금지).
    """
    from shared.platforms.smartstore.orders import (
        iter_changed_product_order_ids, fetch_order_detail)
    from shared.platforms.smartstore import settlements as _settle
    from shared.platforms.smartstore.client import SmartStoreClient

    client = client or SmartStoreClient()

    # 변경 주문내역은 '상태변경일' 기준이라, 주문일이 창 안이어도 최근 상태변경(구매확정 등)이
    # 창 밖으로 밀리면 빠진다(며칠 지난 주문의 드리프트). 조회 끝을 살짝 넉넉히 잡고
    # combined_order_rows 가 주문일 기준으로 트리밍(기간=주문일 유지).
    # ⚠️ 네이버 last-changed 는 미래일·과도한 범위 = 400(조회 범위 초과). 그래서:
    #  (1) 미래 금지(now 로 상한) (2) 전체 스팬 ≤ 10일일 때만 버퍼 적용(아니면 버퍼 포기).
    now = _dt.datetime.now(KST)
    # ★ until 미래 금지 — 마진 기간추론이 +3일 마진으로 period_to 를 미래(예: 오늘 07-13,
    #   until 07-15)로 만들면 아래 버퍼 리셋(fetch_until=until)이 미래를 그대로 넘겨
    #   naver last-changed 가 HTTP 400 [104139] 조회범위초과로 거절 → 스마트스토어 매출
    #   통째 누락·마진 마이너스(라이브 실측). 조회·정산 루프 모두 now 로 상한.
    if until > now:
        until = now
    fetch_until = min(until + _dt.timedelta(days=3), now)
    if fetch_until <= until or (fetch_until - since).days > 10:
        fetch_until = until
    ids = iter_changed_product_order_ids(since, fetch_until, client=client)
    detail = []
    for i in range(0, len(ids), 300):
        d = fetch_order_detail(ids[i:i + 300], client=client)
        detail += (d.get("data", d) if isinstance(d, dict) else d) or []

    # 정산(결제일 기준, 하루씩): 상품(productOrderId) + 배송비(DELIVERY→orderId) 별도 맵.
    # include_settlement=False(배송검사 등 주문상태·송장만 필요) 면 이 하루씩 루프를 건너뛴다
    # — 넓은 조회창에서 하루씩 정산 호출이 타임아웃의 원인.
    prod_settle, deliv_settle = {}, {}
    day = since
    while include_settlement and day <= until:
        try:
            p, d = _settle.settle_expect_maps(
                search_date=day.strftime("%Y-%m-%d"),
                period_type="SETTLE_CASEBYCASE_PAY_DATE", client=client)
            prod_settle.update(p)
            for k, v in d.items():
                deliv_settle[k] = deliv_settle.get(k, 0) + v
        except Exception:
            pass
        day += _dt.timedelta(days=1)

    rows = []
    _deliv_used = set()   # 배송비 정산은 주문당 1회만 더함
    for it in detail:
        po = it.get("productOrder", {}) if isinstance(it, dict) else {}
        od = it.get("order", {}) if isinstance(it, dict) else {}
        sa = po.get("shippingAddress", {}) if isinstance(po, dict) else {}
        dv = it.get("delivery", {}) if isinstance(it, dict) else {}
        poid = _g(po, "productOrderId")
        oid = _g(od, "orderId")
        prod_amt = prod_settle.get(poid)
        settle_val, settle_src = "", "none"
        if prod_amt is not None:                       # 상품 정산 있으면 = 상품정산 + 배송비정산(1회)
            settle_val = prod_amt
            if oid and oid not in _deliv_used and oid in deliv_settle:
                settle_val += deliv_settle[oid]
                _deliv_used.add(oid)
            settle_src = "real"
        else:
            # 최근 주문(정산 전) — 실결제금액 × (1-6%) 로 추정(쿠팡 미정산 추정과 동형).
            #  네이버는 오늘 주문의 정산을 아직 안 줘서 빈칸이면 순마진=0-매입=손실로 둔갑한다.
            est = _ss_estimate_settle(_g(po, "totalPaymentAmount"),
                                      _g(po, "unitPrice"), _g(po, "quantity"))
            if est != "":
                settle_val, settle_src = est, "estimated"
        rows.append({
            "_shipkey": ("smartstore", oid),   # 배송건(주문) 단위 배송비 정규화용
            "주문일": _g(od, "orderDate", "paymentDate"),   # 시간 포함(_finalize 에서 통일)
            "판매처": "스마트스토어",
            "상품명": _g(po, "productName"),
            "옵션": _g(po, "productOption"),
            "수량": _g(po, "quantity", default=""),
            "주소": (str(_g(sa, "baseAddress")) + " " + str(_g(sa, "detailedAddress"))).strip(),
            "우편번호": _g(sa, "zipCode"),
            "수령자": _g(sa, "name"),
            "배송메시지": _g(po, "shippingMemo") or _g(od, "shippingMemo"),
            "구매자": _g(od, "ordererName"),
            "수령자전화번호": _g(sa, "tel1", "tel2"),
            "구매자번호": _g(od, "ordererTel"),
            "쇼핑몰": "04.스마트스토어",
            "쇼핑몰ID": "",
            "단가": _g(po, "unitPrice", "totalPaymentAmount", default=""),
            "배송비": _g(po, "deliveryFeeAmount", default=""),
            "정산예정금액": settle_val,
            "_settle_source": settle_src,
            "주문상태": _status_ko("smartstore", _g(po, "productOrderStatus")),
            "주문상태원본": _g(po, "productOrderStatus"),
            "오픈마켓주문번호": poid or oid,
            "실결제금액": _g(po, "totalPaymentAmount", default=""),   # 할인 반영 실결제
            "옵션추가금": _g(po, "optionPrice", default=""),
            # 이미 등록된 송장은 마켓이 정본 — 안 읽어오면 사용자가 손으로 다시 치게 되고,
            # 그 값이 실제와 어긋나도 화면상 알 길이 없다(2026-07-10 실제 발생).
            "송장입력": _g(dv, "trackingNumber", default=""),
            "발송처리일": _g(dv, "sendDate", "sendDate", default=""),   # 스스 발송일 → 경과시간용
        })
    return rows


def lotteon_order_rows(since: _dt.datetime, until: _dt.datetime,
                       client=None, include_settlement: bool = True) -> list:
    """롯데온 출고/회수지시(주문정보) → 16컬럼 행(dict) 리스트.

    apiNo=209 SellerDeliveryOrdersSearch(하루 윈도우) 응답 deliveryOrderList 매핑.
    정산예정금액은 주문 API엔 없음(실결제 actualAmt 로 근사) — 정밀 정산은 정산 그룹 API 후속.
    """
    import html as _html
    from shared.platforms.lotteon.orders import iter_delivery_orders

    # ★ 209(출고/회수지시)는 '배송지시생성일시' 기준 조회다. 기간 안(주문일) 주문이라도
    #   배송지시가 나중에(예: 07-12 주문 → 07-13 지시생성) 잡히면 [since,until] 창 밖이라
    #   통째 누락된다(라이브: 07-12 신규주문 6건, 서버 프로브 확인). 조회 끝을 now 로 넓히고
    #   combined_order_rows 가 주문일 기준으로 다시 트리밍(기간=주문일 유지).
    _lo_fetch_until = max(until, _dt.datetime.now(KST))
    rows = []
    for od in iter_delivery_orders(since, _lo_fetch_until, client=client):
        opt = _g(od, "sitmNm") or (
            (str(_g(od, "adtnOptNm")) + " " + str(_g(od, "adtnOptVal"))).strip())
        addr = (str(_g(od, "dvpStnmZipAddr")) + " " + str(_g(od, "dvpStnmDtlAddr"))).strip()
        odc = str(_g(od, "odCmptDttm"))
        rows.append({
            "_shipkey": ("lotteon", _g(od, "odNo")),   # 배송건(주문) 단위 배송비 정규화용
            "_odseq": _g(od, "odSeq", default=""),      # 140 진행단계 조인 키(odNo+odSeq)
            # 송장 전송용 식별자 — 배송상태 통보(apiNo=137) 필수값 전부.
            #   _odseq 는 조인 후 _finalize_rows 가 pop 하므로, 살아남는 사본을 따로 둔다.
            "_send_ids": {"od_no": str(_g(od, "odNo", default="")),
                          "od_seq": str(_g(od, "odSeq", default="")),
                          "proc_seq": str(_g(od, "procSeq", default="1")),
                          "spd_no": str(_g(od, "spdNo", default="")),
                          "sitm_no": str(_g(od, "sitmNo", default="")),
                          "qty": str(_g(od, "odQty", default=""))},
            "주문일": odc,   # YYYYMMDDHHMMSS — _finalize 에서 시간 포함 통일
            "판매처": "롯데온",
            "상품명": _html.unescape(str(_g(od, "spdNm"))),   # &lt;매장정품&gt; → <매장정품>
            "옵션": _html.unescape(str(opt)),
            "수량": _g(od, "odQty", default=""),
            "주소": addr,
            "우편번호": _g(od, "dvpZipNo"),
            "수령자": _g(od, "dvpCustNm"),
            "배송메시지": _g(od, "dvMsg"),
            "구매자": _g(od, "odrNm"),
            "수령자전화번호": _g(od, "dvpMphnNo", "dvpTelNo"),
            "구매자번호": _g(od, "mphnNo", "telNo"),
            "쇼핑몰": "롯데온",
            "쇼핑몰ID": "",
            "단가": _g(od, "slPrc", default=""),
            "배송비": _g(od, "dvCst", default=""),
            "정산예정금액": _g(od, "actualAmt", default=""),   # 실결제(상품+배송비-할인) 근사
            "_settle_source": "none",   # 아래 SettleCommission 조인 성공 시 real 로 승격
            "주문상태": _status_ko("lotteon", _g(od, "odPrgsStepCd")),
            "주문상태원본": _g(od, "odPrgsStepCd"),
            "오픈마켓주문번호": _g(od, "odNo"),
            "실결제금액": _g(od, "actualAmt", default=""),   # 실결제(정산예상은 주문API 없음→수수료 공란)
            # 송장은 출고지시(209) 응답에 **없다** — 진행단계(140)의 invcNo 가 정본.
            #   옛 코드가 여기서 invNo·dvInvNo 를 찾아 154행 전부 공란이었다(2026-07-10).
            "송장입력": "",
        })

    # ── 취소/반품/교환 병합(claimservice, MCP 실측 2026-07-09) ──
    #  활성(출고/회수지시)에 없는 주문만 추가(취소는 출고목록에 없음). 조회 실패는 활성 유지(부가).
    from shared.platforms.lotteon import claims as _clm

    def _claim_row(it, status, qty_key, raw_code=""):
        addr = (str(_g(it, "rtrvStnmZipAddr")) + " " + str(_g(it, "rtrvStnmDtlAddr"))).strip()
        return {
            "주문일": str(_g(it, "odAccpDttm", "clmReqDttm")),   # 주문접수일(기간=주문일)
            "판매처": "롯데온",
            "상품명": _html.unescape(str(_g(it, "spdNm"))),
            "옵션": _html.unescape(str(_g(it, "sitmNm"))),
            "수량": _g(it, qty_key, "odQty", default=""),
            "주소": addr,
            "우편번호": _g(it, "rtrvZipNo", default=""),
            "수령자": _g(it, "rtrvCustNm", default=""),
            "배송메시지": _g(it, "clmRsnCnts", default=""),   # 클레임 사유
            "구매자": _g(it, "rtrvCustNm", default=""),
            "수령자전화번호": _g(it, "rtrvMphnNo", "rtrvTelNo", default=""),
            "구매자번호": "",
            "쇼핑몰": "롯데온", "쇼핑몰ID": "",
            "단가": _g(it, "itmSlPrc", default=""),
            "배송비": 0, "정산예정금액": "", "_settle_source": "none",
            "주문상태": status,
            "주문상태원본": raw_code,   # odPrgsStepCd(21취소완료·27반품완료 등) — API코드 칸
            "오픈마켓주문번호": _g(it, "odNo"),
            "실결제금액": "", "송장입력": "",
        }

    seen = {r["오픈마켓주문번호"] for r in rows if r.get("오픈마켓주문번호")}
    #  요청↔완료 세분: 클레임 itemList의 odPrgsStepCd 로 판정(21취소완료·27반품완료). 교환 완료코드
    #  미확정 → 교환요청 유지(라이브 재측정으로 실코드 확인 후 보정). 그 외(회수지시·진행)=요청.
    _lo_done = {"취소": "21", "반품": "27"}   # 교환=None(완료코드 미확정)
    # ★ 클레임은 '클레임 접수일' 기준 조회 → 기간 안 주문이 나중에 취소되면 [since,until] 밖이라
    #   통째 누락(라이브: 롯데온 4건). 조회 끝을 now 로 넓힌다(주문번호 매칭이라 넓혀도 안전).
    _lo_claim_until = max(until, _dt.datetime.now(KST))
    for fn, base, qkey in ((_clm.iter_cancel, "취소", "cnclQty"),
                           (_clm.iter_return, "반품", "rtngQty"),
                           (_clm.iter_exchange, "교환", "xchgQty")):
        try:
            for it in fn(since, _lo_claim_until, client=client):
                on = _g(it, "odNo")
                if on and on in seen:
                    continue
                if on:
                    seen.add(on)
                done_code = _lo_done.get(base)
                step = str(_g(it, "odPrgsStepCd"))
                status = (base + "완료") if (done_code and step == done_code) else (base + "요청")
                rows.append(_claim_row(it, status, qkey, step))
        except Exception:   # noqa: BLE001 — 클레임 조회 실패는 활성 주문 유지
            pass

    # ── 현재 주문진행단계(SellerDeliveryProgressStateSearch, apiNo140) 반영 ──
    #  209(출고/회수지시) 행은 단계가 11(출고지시)에 고정 → 140으로 현재단계(발송완료·배송완료·
    #  수취완료·취소완료·반품완료 등)를 덮어쓴다. 검색일=배송지시생성일시(209와 동일)라 같은
    #  [since,until] 창으로 odNo+odSeq 조인. 여러 진행이력이면 배송상태발생일시(dvTrcStatDttm) 최신 채택.
    from shared.platforms.lotteon.orders import iter_progress_states as _iter_prog
    now = _dt.datetime.now(KST)
    #  송장(invcNo)도 여기서만 온다 — 같은 조인으로 주문상태와 함께 채운다.
    prog = {}      # (odNo, odSeq) → (dvTrcStatDttm, step, invcNo) — 정밀 조인
    prog_od = {}   # odNo → (dvTrcStatDttm, step, invcNo) — odSeq 없을 때 폴백(최신 단계)
    try:
        for it in _iter_prog(since, until, client=client):
            step = str(_g(it, "odPrgsStepCd"))
            if not step:
                continue
            odno = str(_g(it, "odNo"))
            dttm = str(_g(it, "dvTrcStatDttm"))
            invc = str(_g(it, "invcNo", default="") or "")
            key = (odno, str(_g(it, "odSeq")))
            if key not in prog or dttm >= prog[key][0]:
                prog[key] = (dttm, step, invc)
            if odno not in prog_od or dttm >= prog_od[odno][0]:
                prog_od[odno] = (dttm, step, invc)
    except Exception:   # noqa: BLE001 — 진행단계 조회 실패는 209 단계(출고지시) 유지
        prog, prog_od = {}, {}
    if prog:
        for r in rows:
            if not r.get("_shipkey"):     # 209 배송행만(클레임행은 자체 상태 유지)
                continue
            odno = str(r.get("오픈마켓주문번호"))
            hit = prog.get((odno, str(r.get("_odseq")))) or prog_od.get(odno)
            if hit:
                r["주문상태"] = _status_ko("lotteon", hit[1])
                r["주문상태원본"] = hit[1]
                r["발송처리일"] = hit[0]        # 배송상태발생일시(dvTrcStatDttm)=발송처리 시각(경과시간용)
                if hit[2]:
                    r["송장입력"] = hit[2]

    # ── 마켓수수료 실값(SettleCommission, apiNo45) — odNo별 수수료 합으로 마켓수수료 채움 ──
    #  ★정산 기준일=구매확정일이라, 주문일이 창 안인 주문의 수수료는 구매확정(=나중) 시점에 기록됨.
    #  따라서 수수료 조회창을 [주문창 시작 ~ 지금]으로 넓혀 odNo로 조인(창을 주문창으로만 두면 안 겹침).
    #  odNo 매칭이라 넓혀도 안전(우리 주문에 없는 odNo는 무시). _finalize가 실값 우선 사용.
    try:
        cmap = _clm.commission_map(since, max(until, now), client=client) \
            if include_settlement else {}
    except Exception:   # noqa: BLE001
        cmap = {}
    if cmap:
        for r in rows:
            fee = cmap.get(r.get("오픈마켓주문번호"))
            if fee:
                r["마켓수수료"] = int(round(fee))
                r["_settle_source"] = "real"   # 실결제 − 실수수료 로 정산 산출 가능
    return rows


def _won(obj):
    """쿠팡 금액 객체 {currencyCode,units,nanos} → 정수 원. 없으면 ''(폴백 0 금지)."""
    if isinstance(obj, dict) and obj.get("units") is not None:
        try:
            return int(obj["units"])
        except (TypeError, ValueError):
            return ""
    return ""


def _cp_windows(since: _dt.datetime, until: _dt.datetime, days: int = 30):
    """쿠팡 조회 최대 31일 제약(발주서·revenue) → [since,until]을 ≤days 윈도우로 분할."""
    cur = since
    step = _dt.timedelta(days=days)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def coupang_order_rows(since: _dt.datetime, until: _dt.datetime,
                       client=None, include_settlement: bool = True) -> list:
    """쿠팡 발주서 목록 → 16컬럼 행(dict). status별(공식 필수) 순회 + nextToken 페이징.
    조회 최대 31일 제약 → _cp_windows 로 30일 분할(긴 기간·통합 조회 400 방지).

    발주서(shipmentBox) 하위 orderItems[] 평탄화(옵션 단위 1행). 정산예정금액은 발주서엔
    없어 revenue-history(별도 API)를 (주문번호,옵션ID)로 조인 — 미정산(최근주문)은 빈칸
    (폴백 금지). 스펙=GET_ORDERSHEET v5.
    """
    from shared.platforms.coupang.orders import fetch_orders

    statuses = ["ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY"]
    seen, rows = set(), []
    for _w0, _w1 in _cp_windows(since, until):   # 발주서 조회 최대 31일 → 30일 윈도우(seen 이 창 간 중복 제거)
      for st in statuses:
        token = None
        for _ in range(50):   # nextToken 페이징 안전 상한
            resp = fetch_orders(_w0, _w1, client=client, status=st, next_token=token)
            for box in (resp.get("data") or []):
                orderer = box.get("orderer") or {}
                rcv = box.get("receiver") or {}
                addr = (str(rcv.get("addr1") or "") + " " + str(rcv.get("addr2") or "")).strip()
                ordered = str(box.get("orderedAt") or box.get("paidAt") or "")   # 시간 포함
                for it in (box.get("orderItems") or []):
                    key = (box.get("shipmentBoxId"), it.get("vendorItemId"))
                    if key in seen:
                        continue
                    seen.add(key)
                    ship = _won(box.get("shippingPrice"))
                    rows.append({
                        "_oid": box.get("orderId"), "_vid": it.get("vendorItemId"),  # 정산 조인용
                        # 송장 전송용 식별자 — coupang/orders.py::send_tracking 이 요구.
                        #   shipment_box_id = 발주서(묶음배송) 번호 → 요청 경로
                        #   order_sheet_id  = 발주서의 orderId → 요청 본문 orderSheetId
                        #   ⚠️ 본문 필드명(orderSheetId)이 달라, 라이브 1건 전송으로 최종 확인 필요.
                        "_send_ids": {"shipment_box_id": box.get("shipmentBoxId"),
                                      "order_sheet_id": box.get("orderId")},
                        "_shipkey": ("coupang", box.get("orderId")),   # 배송건 단위 배송비 정규화
                        "주문일": ordered,
                        "판매처": "쿠팡",
                        "상품명": it.get("sellerProductName") or it.get("vendorItemName") or "",
                        "옵션": it.get("sellerProductItemName") or "",
                        "수량": it.get("shippingCount", ""),
                        "주소": addr,
                        "우편번호": rcv.get("postCode") or "",
                        "수령자": rcv.get("name") or "",
                        "배송메시지": box.get("parcelPrintMessage") or "",
                        "구매자": orderer.get("name") or "",
                        "수령자전화번호": rcv.get("receiverNumber") or rcv.get("safeNumber") or "",
                        "구매자번호": orderer.get("ordererNumber") or orderer.get("safeNumber") or "",
                        "쇼핑몰": "쿠팡",
                        "쇼핑몰ID": "",
                        "단가": _won(it.get("salesPrice")),
                        "배송비": ship,
                        "정산예정금액": "",
                        "주문상태": _status_ko("coupang", box.get("status") or st),
                        "주문상태원본": box.get("status") or st,
                        "오픈마켓주문번호": box.get("orderId") or "",
                        "송장입력": it.get("invoiceNumber") or box.get("invoiceNumber") or "",
                    })
            token = resp.get("nextToken")
            if not token:
                break

    # 정산예정금액 = 상품 정산 + 배송비 정산(주문당 1회).
    #  1) 실제(revenue-history): items.settlementAmount + deliveryFee.settlementAmount.
    #  2) 미정산(최근): 추정 = round(단가×수량×0.8845) + round(배송비×0.8845).
    #     ⚠️ 배송비 실수수료율은 상품과 달라(문서 확인) 추정의 배송비분은 근사.
    try:
        item_settle, deliv_settle = _coupang_settle_map(since, until, client) \
            if include_settlement else ({}, {})
    except Exception:
        item_settle, deliv_settle = {}, {}
    _deliv_used = set()
    for r in rows:
        oid, vid = str(r.pop("_oid", "")), r.pop("_vid", None)
        ship = r.get("배송비") or 0
        actual = item_settle.get((oid, vid))
        if actual is not None:                        # 확정: 상품정산 + 배송비정산(주문당 1회)
            val = actual
            if oid not in _deliv_used and oid in deliv_settle:
                val += deliv_settle[oid]
                _deliv_used.add(oid)
            r["정산예정금액"] = val
            r["_settle_source"] = "real"
        else:                                          # 미정산: 상품추정 + 배송비추정(주문당 1회)
            prod_est = _cp_estimate_settle(r.get("단가"), r.get("수량"), 0)
            if prod_est == "":
                r["정산예정금액"] = ""
                r["_settle_source"] = "none"
            else:
                deliv_est = 0
                if oid not in _deliv_used and str(ship).lstrip("-").isdigit():
                    deliv_est = round(int(ship) * CP_SHIP_FEE_FACTOR)
                    _deliv_used.add(oid)
                r["정산예정금액"] = prod_est + deliv_est
                r["_settle_source"] = "estimated"

    # ── 취소/반품/교환 병합(returnRequests + exchangeRequests, MCP 실측 2026-07-09) ──
    #  활성 발주서에 없는 주문만 추가. 쿠팡 주문번호는 날짜 미인코딩 → 주문일=접수일(createdAt) 근사.
    from shared.platforms.coupang import claims as _cc

    def _cp_claim_row(odno, status, name, opt, qty, unit, reason, buyer, cdt, raw_code=""):
        return {
            "주문일": str(cdt or ""), "판매처": "쿠팡",
            "상품명": name or "", "옵션": opt or "",
            "수량": qty if qty not in (None, "") else "",
            "주소": "", "우편번호": "", "수령자": buyer or "",
            "배송메시지": reason or "", "구매자": buyer or "",
            "수령자전화번호": "", "구매자번호": "",
            "쇼핑몰": "쿠팡", "쇼핑몰ID": "",
            "단가": unit if unit not in (None, "") else "",
            "배송비": 0, "정산예정금액": "", "_settle_source": "none",
            "주문상태": status, "주문상태원본": raw_code or "",   # receiptStatus/exchangeStatus — API코드 칸
            "오픈마켓주문번호": str(odno or ""),
            "실결제금액": "", "송장입력": "",
        }

    # ★ 클레임(취소/반품/교환)은 '클레임 생성일' 기준 조회다. 기간 안 주문이 나중에(기간 밖)
    #   취소되면 그 클레임은 [since,until] 창에 안 잡혀 통째 누락된다(라이브: 쿠팡 취소완료
    #   62건 미조회 = 손실 미포착). 롯데온 commission_map 처럼 조회 끝을 now 로 넓힌다
    #   (주문번호로 매칭하므로 넓혀도 우리 주문에 없는 건 무시돼 안전).
    _claim_until = max(until, _dt.datetime.now(KST))
    seen_ord = {r.get("오픈마켓주문번호") for r in rows if r.get("오픈마켓주문번호")}
    try:
        for rq in _cc.iter_returns(since, _claim_until, client=client):
            odno = str(rq.get("orderId") or "")
            if odno and odno in seen_ord:
                continue
            # 요청↔완료 세분: receiptStatus RETURNS_COMPLETED=완료, 그 외(RU 접수·PR 진행 등)=요청.
            _base = "취소" if rq.get("receiptType") == "CANCEL" else "반품"
            st = _base + ("완료" if rq.get("receiptStatus") == "RETURNS_COMPLETED" else "요청")
            for it in (rq.get("returnItems") or [{}]):
                rows.append(_cp_claim_row(
                    odno, st, it.get("sellerProductName"), it.get("vendorItemName"),
                    it.get("cancelCount"), None, rq.get("reasonCodeText"),
                    rq.get("requesterName"), rq.get("createdAt"),
                    rq.get("receiptStatus") or rq.get("receiptType")))
    except Exception:   # noqa: BLE001 — 클레임 조회 실패는 활성 주문 유지
        pass
    try:
        for ex in _cc.iter_exchanges(since, _claim_until, client=client):
            odno = str(ex.get("orderId") or "")
            if odno and odno in seen_ord:
                continue
            _exst = "교환완료" if ex.get("exchangeStatus") == "SUCCESS" else "교환요청"
            for it in (ex.get("exchangeItemDtoV1s") or [{}]):
                rows.append(_cp_claim_row(
                    odno, _exst, it.get("orderItemName") or it.get("targetItemName"),
                    None, it.get("quantity"), it.get("orderItemUnitPrice"),
                    ex.get("reasonCodeText"), None, ex.get("createdAt"),
                    ex.get("exchangeStatus")))
    except Exception:   # noqa: BLE001
        pass
    return rows


CP_FEE_FACTOR = 0.8845        # 1 - 0.1155 (쿠팡 상품 판매수수료 11.55%)
CP_SHIP_FEE_FACTOR = 0.97     # 1 - 0.03  (쿠팡 배송비 수수료 3% — 상품과 별도 요율)


def _cp_estimate_settle(unit, qty, ship):
    """미정산 쿠팡 주문 정산예정금액 추정 = round((단가×수량 + 배송비) × 0.8845).

    단가 없으면 빈칸(폴백 0 금지). 확정액 아님(추정) — 실제 정산으로 검증 필요.
    """
    try:
        u = int(unit)
    except (TypeError, ValueError):
        return ""            # 단가 없음 → 추정 안 함
    q = int(qty) if str(qty).strip().isdigit() else 1
    s = int(ship) if str(ship).strip().lstrip("-").isdigit() else 0
    return round((u * q + s) * CP_FEE_FACTOR)


SS_FEE_FACTOR = 0.94          # 1 - 0.06 (스마트스토어 판매수수료 추정 6% — 사용자 지정)


def _ss_estimate_settle(paid, unit, qty):
    """미정산(최근·정산 전) 스마트스토어 주문 정산예정금액 추정 = round(매출 × 0.94).

    매출 = 실결제금액(할인 반영, 우선) → 없으면 단가×수량. 둘 다 없으면 빈칸(폴백 0 금지).
    확정액 아님(추정) — _settle_source='estimated' 로 태그해 실정산과 구분한다.
    네이버는 최근 주문 정산을 미래에 확정하므로(오늘 주문=오늘 정산 없음), 실정산 없을 때만 사용.
    """
    base = None
    try:
        base = int(paid)
    except (TypeError, ValueError):
        try:
            u = int(unit)
            q = int(qty) if str(qty).strip().isdigit() else 1
            base = u * q
        except (TypeError, ValueError):
            return ""             # 매출 근거 없음 → 추정 안 함
    return round(base * SS_FEE_FACTOR)


def _coupang_settle_map(since, until, client):
    """쿠팡 revenue-history →
       (상품정산 {(orderId, vendorItemId): items.settlementAmount 합},
        배송비정산 {orderId: deliveryFee.settlementAmount 합}).

    배송비는 주문 레벨 deliveryFee.settlementAmount(총배송비−배송비수수료−VAT) 별도 필드라
    페이지를 직접 순회해 뽑는다(iter_revenue_items 는 items 만 평탄화).
    """
    from shared.platforms.coupang.settlements import fetch_revenue_page
    item_map, deliv_map = {}, {}
    for _w0, _w1 in _cp_windows(since, until):   # revenue-history 도 장기간 제약 → 30일 분할
      rec_from = _w0.strftime("%Y-%m-%d")
      rec_to = (_w1 - _dt.timedelta(days=1)).strftime("%Y-%m-%d")   # 종료는 전일까지
      token = ""
      for _ in range(200):   # 페이징 안전 상한
        resp = fetch_revenue_page(rec_from, rec_to, token=token, max_per_page=50, client=client)
        for order in (resp.get("data") or []):
            oid = str(order.get("orderId") or "")
            damt = (order.get("deliveryFee") or {}).get("settlementAmount")
            if damt is not None:
                try:
                    deliv_map[oid] = deliv_map.get(oid, 0) + int(damt)
                except (TypeError, ValueError):
                    pass
            for it in (order.get("items") or []):
                vid, amt = it.get("vendorItemId"), it.get("settlementAmount")
                if amt is None:
                    continue
                try:
                    item_map[(oid, vid)] = item_map.get((oid, vid), 0) + int(amt)
                except (TypeError, ValueError):
                    pass
        if not resp.get("hasNext"):
            break
        token = resp.get("nextToken") or ""
        if not token:
            break
    return item_map, deliv_map


def _esm_option(lst) -> str:
    """ESM ItemOptionSelectList → 옵션 문자열. 옵션 dict 의 문자열 값 결합(방어적).

    정확한 하위 필드명은 라이브 검증에서 확정(공개문서 미명시). 실데이터만 표시, 날조 없음.
    """
    if not lst:
        return ""
    parts = []
    for it in lst:
        if isinstance(it, dict):
            vals = [str(v).strip() for v in it.values()
                    if isinstance(v, (str, int)) and str(v).strip()]
            if vals:
                parts.append(" ".join(vals))
        elif it:
            parts.append(str(it))
    return " / ".join(p for p in parts if p)


def esm_order_rows(market: str, since: _dt.datetime, until: _dt.datetime,
                   client=None, include_settlement: bool = True) -> list:
    """옥션·G마켓(ESM 2.0) 주문조회 → 행(dict) 리스트. RequestOrders 응답 매핑.

    market = "auction" | "gmarket". 정산예정금액 = 판매대금 정산조회(getsettleorder)를 주문번호
    (OrderNo↔ContrNo)로 조인. 미정산(최근 주문)은 공란(폴백 금지, 스스·쿠팡과 동일 정직성).
    ⚠️ 라이브 미검증(키 입력 후 서버 검증 필요). 검증 전 SUPPORTED 미포함.
    """
    from shared.platforms.esm.orders import iter_orders
    label = {"auction": "옥션", "gmarket": "G마켓"}.get(market, market)
    rows = []
    for od in iter_orders(market, since, until, client=client):
        addr = (str(_g(od, "DelFrontAddress")) + " " + str(_g(od, "DelBackAddress"))).strip()
        rows.append({
            "_shipkey": (market, _g(od, "OrderNo")),   # 배송건(주문) 단위 배송비 정규화용
            "_ono": str(_g(od, "OrderNo")),            # 정산 조인용(ContrNo)
            "주문일": _g(od, "OrderDate"),
            "판매처": label,
            "상품명": _g(od, "GoodsName"),
            "옵션": _esm_option(od.get("ItemOptionSelectList")),
            "수량": _g(od, "ContrAmount", default=""),
            "주소": addr,
            "우편번호": _g(od, "ZipCode"),
            "수령자": _g(od, "ReceiverName"),
            "배송메시지": _g(od, "DelMemo"),
            "구매자": _g(od, "BuyerName"),
            "수령자전화번호": _g(od, "HpNo", "TelNo"),
            "구매자번호": _g(od, "BuyerId"),
            "쇼핑몰": label,
            "쇼핑몰ID": "",
            "단가": _g(od, "SalePrice", default=""),
            "배송비": _g(od, "ShippingFee", default=""),
            "정산예정금액": "",   # 아래 정산 조인으로 채움(미정산=공란)
            "_settle_source": "none",   # 아래 정산 조인 성공 시 real 로 승격
            "주문상태": _status_ko("esm", _g(od, "OrderStatus")),
            "주문상태원본": _g(od, "OrderStatus"),
            "오픈마켓주문번호": _g(od, "OrderNo"),
        })

    # 정산예정금액 = 판매대금 정산조회(getsettleorder) SettlementPrice 를 ContrNo(=OrderNo)로 조인.
    #  미정산(최근 주문)은 맵에 없어 공란(폴백 금지). 정산 API 실패는 조용히 공란(주문은 살림).
    try:
        from shared.platforms.esm.settlements import settle_price_map
        srch = (getattr(client, "_cfg", {}) or {}).get("settle_srch_type", "D1") if client else "D1"
        smap = settle_price_map(market, since, until, client=client, srch_type=srch)
    except Exception:   # noqa: BLE001 — 정산 조회 실패는 정산액만 공란(주문 데이터는 유지)
        smap = {}
    for r in rows:
        ono = r.pop("_ono", "")
        if ono in smap:
            r["정산예정금액"] = smap[ono]
            r["_settle_source"] = "real"
    return rows


def auction_order_rows(since: _dt.datetime, until: _dt.datetime, client=None,
                       include_settlement: bool = True) -> list:
    return esm_order_rows("auction", since, until, client=client,
                          include_settlement=include_settlement)


def gmarket_order_rows(since: _dt.datetime, until: _dt.datetime, client=None,
                       include_settlement: bool = True) -> list:
    return esm_order_rows("gmarket", since, until, client=client,
                          include_settlement=include_settlement)


def eleven11_order_rows(since: _dt.datetime, until: _dt.datetime, client=None,
                        include_settlement: bool = True) -> list:
    """11번가 주문 → 행(dict). 상태별 API 3종 병합(전체 라이프사이클).

    11번가는 주문을 상태별 API로 나눠 줌 → 3종을 합쳐 전체 상태 표시:
    · 결제완료(발송대기, complete): 전체 필드(수령자·주소·단가 selPrc·정산예정 stlPlnAmt).
    · 배송완료(dlvcompleted): 전체 필드(수령자·주소·단가·송장·dlvEndDt). 정산예정 없음→공란.
    · 구매확정(completed): 배송정보·단가 미제공(완료·정산 단계) → 해당 열 공란(폴백 금지).
    (ordNo,ordPrdSeq) 상태 간 중복 제거. 배송비는 묶음배송(bndlDlvYN=Y)이면 bmDlvCst,
    아니면 dlvCst; 배송건(_shipkey=bndlDlvSeq) 단위 1회 정규화.
    배송준비중=packaging(전체), 배송중=shipping(송장만), 취소/반품/교환=claimservice 병합.
    """
    from shared.platforms.eleven11.orders import (
        iter_orders, iter_delivered, iter_completed, iter_preparing, iter_shipping,
        iter_cancel, iter_canceled, iter_return, iter_exchange)

    def _g11(od, *keys):
        for k in keys:
            v = od.get(k)
            if v not in (None, "", "null"):
                return v
        return ""

    def _row(od, status):
        addr = (str(_g11(od, "rcvrBaseAddr")) + " " + str(_g11(od, "rcvrDtlsAddr"))).strip()
        ship = _g11(od, "bmDlvCst") if od.get("bndlDlvYN") == "Y" else _g11(od, "dlvCst")
        # 주문일: ordDt(있으면). 배송중(shipping) 목록은 ordDt 미제공 → ordNo 앞 8자리(YYYYMMDD)로 보정.
        ordno = str(_g11(od, "ordNo"))
        ord_dt = _g11(od, "ordDt") or (ordno[:8] if ordno[:2] == "20" and len(ordno) >= 8 else "")
        return {
            "_shipkey": ("eleven11", _g11(od, "bndlDlvSeq") or _g11(od, "ordNo")),
            # 송장 전송용 식별자 — 발송처리(/rest/ordservices/reqdelivery)의 대상 단위는
            #   **배송번호(dlvNo)** 다(주문번호로 대체 불가). 부분발송용 ordPrdSeq 도 함께 보존.
            "_send_ids": {"ord_no": ordno,
                          "ord_prd_seq": str(_g11(od, "ordPrdSeq") or ""),
                          "dlv_no": str(_g11(od, "dlvNo") or "")},
            "주문일": ord_dt,
            "판매처": "11번가",
            "상품명": _g11(od, "prdNm"),
            "옵션": _g11(od, "slctPrdOptNm"),
            "수량": _g11(od, "ordQty"),
            "주소": addr,
            "우편번호": _g11(od, "rcvrMailNo"),
            "수령자": _g11(od, "rcvrNm"),
            "배송메시지": _g11(od, "ordDlvReqCont"),
            "구매자": _g11(od, "ordNm", "memID"),
            "수령자전화번호": _g11(od, "rcvrPrtblNo", "rcvrTlphn"),
            "구매자번호": _g11(od, "ordPrtblTel", "ordTlphnNo"),
            "쇼핑몰": "11번가",
            "쇼핑몰ID": "",
            "단가": _g11(od, "selPrc"),   # 구매확정 목록엔 없음 → 공란(폴백 금지)
            "배송비": ship,
            # 정산예정금액 = 주문 응답의 stlPlnAmt(정산예정금액) — 서버 실호출로 확인(2026-07-08).
            #  구매확정 목록엔 없어 공란. 실정산액(정산완료분)은 settlementList.stlAmt(후속).
            "정산예정금액": _g11(od, "stlPlnAmt"),
            "_settle_source": "real" if _g11(od, "stlPlnAmt") not in ("", None) else "none",
            "주문상태": status,
            "오픈마켓주문번호": _g11(od, "ordNo"),
            "실결제금액": _g11(od, "ordPayAmt"),   # 결제금액 = 주문금액+배송비-할인(공문 확인)
            "송장입력": _g11(od, "invcNo"),
            "발송처리일": _g11(od, "sndEndDt", "dlvEndDt"),   # 발송일(배송중)·배송완료일 → 경과시간용
            "주문상태원본": _g11(od, "ordPrdStat"),   # 11번가 상품주문상태코드 → API코드 칸(엔드포인트별 상태)
        }

    def _claim_row(od, status):
        """취소/반품/교환 목록 → 행. 클레임 목록은 상품명·단가 미제공(주문번호·옵션·수량·사유·상태만)."""
        ordno = str(_g11(od, "ordNo"))
        addr = (str(_g11(od, "rcvrBaseAddr")) + " " + str(_g11(od, "rcvrDtlsAddr"))).strip()
        return {
            # ★ 주문일 공란(폴백 금지). 클레임 목록엔 ordDt 가 없고, ordNo 앞 8자리는 주문일이
            #   아니다(라이브: 주문번호 20260703… 인데 실주문일 07-06 → 07-03 으로 오추정돼
            #   기간필터에서 통째 탈락). 공란이면 combined_order_rows 가 유지하고(주문일 파싱실패
            #   =보존), 매처가 주문번호로 매칭해 더망고(매입)의 실주문일을 쓴다.
            "주문일": "",
            "판매처": "11번가",
            "상품명": "",   # 클레임 목록 미제공
            "옵션": _g11(od, "slctPrdOptNm", "optName"),
            "수량": _g11(od, "ordCnQty", "clmReqQty", "ordQty"),
            "주소": addr,
            "우편번호": _g11(od, "rcvrMailNo"),
            "수령자": _g11(od, "rcvrNm"),
            "배송메시지": _g11(od, "ordCnDtlsRsn", "clmReqCont", "clmReqRsn"),   # 클레임 사유
            "구매자": _g11(od, "ordNm"),
            "수령자전화번호": _g11(od, "rcvrPrtblNo", "rcvrTlphn"),
            "구매자번호": _g11(od, "ordPrtblTel", "ordTlphnNo"),
            "쇼핑몰": "11번가", "쇼핑몰ID": "",
            "단가": "", "배송비": 0, "정산예정금액": "", "_settle_source": "none",
            "주문상태": status,
            "주문상태원본": _g11(od, "ordPrdStat"),   # 11번가 상품주문상태코드 → API코드 칸
            "오픈마켓주문번호": ordno,
            "실결제금액": "",
            "송장입력": _g11(od, "twPrdInvcNo"),
        }

    def _return_row(od, _status):
        """반품 목록 → 행. ordPrdStat A01=반품완료, 그 외(601 클레임진행중 등)=반품요청."""
        return _claim_row(od, "반품완료" if str(_g11(od, "ordPrdStat")) == "A01" else "반품요청")

    # 활성 5상태 + 클레임 3종 병합(전체 라이프사이클). (ordNo,ordPrdSeq) 로 중복 제거.
    #  발송대기(complete)는 필수(오류 전파), 나머지는 부가(실패 시 조용히 스킵). 클레임은 활성에
    #  없는 건(취소 등)만 추가 — 이미 활성에 있으면 그 상태 유지(중복 방지).
    rows, seen = [], set()
    # 발송·배송완료·정산은 주문일보다 늦게 찍혀, 주문일이 창 안이어도 그 상태일이 창 밖이면
    # 상태별 API가 안 준다(배송준비중→배송중→배송완료 진행). 조회 끝을 +14일 넉넉히 잡되
    # ★미래 금지(now 상한). 미래일을 넣으면 11번가 API가 그 창을 거부(400)해 _collect 의
    #   try/except 로 그 상태(취소완료 등)가 통째 빠진다(라이브: 07-06 취소완료 1건 누락).
    #   combined_order_rows 가 최종적으로 주문일 기준으로 트리밍한다(기간=주문일 유지).
    f_until = min(until + _dt.timedelta(days=14), _dt.datetime.now(KST))

    def _collect(iter_fn, status, required, builder=_row, code=""):
        try:
            for od in iter_fn(since, f_until, client=client):
                key = (od.get("ordNo"), od.get("ordPrdSeq"))
                if key in seen:
                    continue
                seen.add(key)
                r = builder(od, status)
                # API코드 = 마켓이 실제로 준 상태코드만(clmStat 클레임 / ordPrdStat). 없으면 비운다.
                #  ★엔드포인트 이름(shipping·completed 등) 같은 합성값은 넣지 않는다 — 실제 API 코드
                #   아닌 건 추정이라, 못 받으면 빈칸으로 둔다(정합성: 확실히 API로 받은 것만).
                r["주문상태원본"] = (od.get("clmStat") or od.get("ordPrdStat")
                                 or r.get("주문상태원본") or "")
                rows.append(r)
        except Exception:   # noqa: BLE001
            if required:
                raise

    _collect(iter_orders, "결제완료", True, code="complete")       # 발송대기(필수)
    _collect(iter_preparing, "배송준비중", False, code="packaging")  # 배송준비중 전체(packaging)
    _collect(iter_shipping, "배송중", False, code="shipping")      # 배송중(송장·주문번호만 — 상세 미제공)
    _collect(iter_delivered, "배송완료", False, code="dlvcompleted")   # 배송완료
    _collect(iter_completed, "구매확정", False, code="completed")   # 구매확정
    _collect(iter_cancel, "취소요청", False, _claim_row, code="cancel")     # 취소처리중(cancelorders)
    _collect(iter_canceled, "취소완료", False, _claim_row, code="canceled")   # 주문취소 완료(canceledorders)
    _collect(iter_return, "반품", False, _return_row, code="return")        # 반품(ordPrdStat A01=완료)
    _collect(iter_exchange, "교환요청", False, _claim_row, code="exchange")   # 교환요청(완료코드 미확정)
    return rows


# 마켓별 행 빌더(코드 존재). SUPPORTED = 그중 실계정 검증까지 끝나 UI 노출 가능한 것.
# 옥션·G마켓·11번가 = 빌더/조회 코드 준비됨(공개문서 스펙). 실키 입력+서버 라이브검증 후 SUPPORTED 추가.
_BUILDERS = {"smartstore": smartstore_order_rows, "lotteon": lotteon_order_rows,
             "coupang": coupang_order_rows,
             "auction": auction_order_rows, "gmarket": gmarket_order_rows,
             "eleven11": eleven11_order_rows}


def _account_client(market: str, env_prefix: Optional[str] = None):
    """판매처관리에 저장된 실키로 마켓 클라이언트 생성. env_prefix 미지정 시 대표 계정.

    핵심: 마켓 config dict 는 import 시 env 를 한 번만 읽어(모듈 전역) UI 저장 키를
    못 본다. market_fetch 의 빌더가 refresh_env()+load_credentials 로 최신 시크릿을
    설정에 주입한다(멀티워커 불일치 해소, 롯데온 선례).
    None 반환 = 그 계정 키 미등록/불량(자격증명 min_length=1 검증 실패) → 호출부가 판단.
    """
    prefix = env_prefix or _ENV_PREFIX.get(market)
    if not prefix:
        return None
    try:
        from lemouton.auth import secrets as S
        S.refresh_env()
        from lemouton.uploader import market_fetch as _mf
        builder = {"smartstore": _mf._smartstore_client,
                   "coupang": _mf._coupang_client,
                   "lotteon": _mf._lotteon_client,
                   "auction": _mf._auction_client,
                   "gmarket": _mf._gmarket_client,
                   "eleven11": _mf._eleven11_client}.get(market)
        return builder(prefix) if builder else None
    except Exception:
        return None   # 키 미설정 등 → row builder 가 기본 클라(app.env)로 폴백


def _active_accounts(market: str) -> list:
    """판매처관리(UploadAccount)의 그 마켓 활성 계정 [(env_prefix, display_name)].

    계정 등록 = 자동 연동(별도 배선 불필요). 등록 순(id)으로 반환.
    조회 실패·미등록은 빈 리스트 → 호출부가 대표 계정(_ENV_PREFIX) 단일 조회로 폴백.
    """
    try:
        from shared.db import SessionLocal
        from lemouton.sourcing.models_v2 import UploadAccount
        with SessionLocal() as s:
            accs = (s.query(UploadAccount)
                    .filter(UploadAccount.market == market,
                            UploadAccount.is_active == True)  # noqa: E712
                    .order_by(UploadAccount.id).all())
            return [(a.env_prefix, a.display_name) for a in accs if a.env_prefix]
    except Exception:   # noqa: BLE001
        return []


def _account_alias(market: str) -> str:
    """그 마켓 활성 계정 중 첫 번째 표시명(폴백 경로 전용). 없으면 빈 문자열(추측 금지)."""
    accs = _active_accounts(market)
    return accs[0][1] if accs else ""


# 마켓별 '셀러를 식별하는' 설정 키 — 이 값이 같으면 이름이 달라도 같은 셀러 계정이다.
_IDENTITY_KEYS = {
    "coupang": ("vendor_id",),
    "smartstore": ("client_id",),
    "lotteon": ("tr_no",),
    "eleven11": ("api_key", "openapi_key"),
    "auction": ("seller_id",),
    "gmarket": ("seller_id",),
}


# 마켓별 '계정 동시 조회 수'. 스마트스토어는 계정 병렬 시 429 로 전멸한 전례가 있어 1(순차).
#  나머지는 한도가 넉넉해 소폭 병렬 → 계정 수가 많은 마켓의 대기시간을 줄인다.
_ACCOUNT_WORKERS = {
    "smartstore": 1,
    "coupang": 2,
    "eleven11": 2,
    "lotteon": 3,
    "auction": 2,
    "gmarket": 2,
}


def _ident_fingerprint(ident: str) -> str:
    """자격증명 식별자의 지문(해시 앞 6자). 키 값 자체는 절대 노출하지 않는다.

    같은 지문 = 같은 키/셀러번호. 사용자가 '어느 계정끼리 같은 키인지' 대조할 수 있다.
    """
    import hashlib
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()[:6]


def _client_identity(market: str, cli) -> Optional[str]:
    """클라이언트가 가리키는 실제 셀러 식별자. 판정 불가면 None(중복 제거하지 않음).

    같은 셀러를 두 계정으로 등록하면 같은 주문이 2배로 잡히므로, 조회 전에 이 값으로
    중복을 접는다. 키 값 자체는 로그·화면에 노출하지 않는다(식별용 내부 비교만).
    """
    cfg = getattr(cli, "_cfg", None)
    if not isinstance(cfg, dict):
        return None
    for k in _IDENTITY_KEYS.get(market, ()):
        v = cfg.get(k)
        if v:
            return f"{market}:{k}:{v}"
    return None


def order_rows(market: str, days: int = 7, client=None,
               now: Optional[_dt.datetime] = None,
               since: Optional[_dt.datetime] = None,
               until: Optional[_dt.datetime] = None,
               include_settlement: bool = True,
               warnings: Optional[list] = None) -> list:
    """마켓별 주문 행. 미지원(UI) 마켓은 ValueError(추측 데이터 안 만듦).

    기간 = since~until 명시 시 그대로 사용(빠른 기간 버튼·직접 날짜), 아니면 최근 days일.
    client 미지정 시 **판매처관리에 등록된 그 마켓 활성 계정 전부**를 계정별 실키로
    병렬 조회해 합친다(계정 등록 = 자동 연동). 각 행의 쇼핑몰별칭 = 그 주문을 가져온 계정명.

    · 키 미등록 계정은 건너뛴다(대표 계정으로 폴백하면 같은 주문이 중복 계상되므로 금지).
    · 등록 계정 0개 또는 전부 키 미등록이면 기존 동작(대표 계정 1개 조회)으로 폴백.
    · 일부 계정 조회 실패(IP 미등록·인증 등):
        - warnings 리스트를 받으면 → 그 계정만 빼고 나머지를 반환하고 사유를 warnings 에 담는다
          (화면은 나머지를 보여주되 빠진 계정을 배너로 명시 — 조용한 실패 금지).
        - warnings 없이 호출되면(엑셀 등) → 예외 전파(불완전한 발송 파일 생성 방지).
    · 모든 계정이 실패하면 warnings 유무와 무관하게 예외 전파(보여줄 게 없음).
    """
    if market not in SUPPORTED:
        raise ValueError(f"'{market}' 주문 엑셀 미지원(UI) — 코드/키/검증 필요")
    if until is None:
        until = now or _dt.datetime.now(KST)
    if since is None:
        since = until - _dt.timedelta(days=days)
    # ★ tz 통일 — 빌더가 aware(KST) now 와 비교하므로 naive since/until 을 KST 로 강제.
    #   (라이브: 스마트스토어가 offset-naive/aware TypeError 로 통째 실패 → 매출 누락·마진 왜곡)
    since, until = _ensure_kst(since), _ensure_kst(until)

    def _rows_for(cli, alias):
        rs = _finalize_rows(_BUILDERS[market](since, until, client=cli,
                                              include_settlement=include_settlement))
        if alias:
            for r in rs:
                r["쇼핑몰별칭"] = alias
        return rs

    if client is not None:                      # 클라이언트 명시(테스트·단일 계정 호출)
        return _rows_for(client, _account_alias(market))

    import logging as _logging
    _log = _logging.getLogger(__name__)

    built = []                                  # [(계정명, 클라이언트)]
    accounts = _active_accounts(market)
    for prefix, name in accounts:
        cli = _account_client(market, prefix)
        if cli is None:                         # 키 미등록 → 건너뜀(중복 방지)
            _log.warning("주문조회 계정 건너뜀(키 미등록): market=%s account=%s", market, name)
            if warnings is not None:
                warnings.append(f"[{market}·{name}] API 키가 없어 조회에서 제외됐어요.")
            continue
        built.append((name, cli))

    # ★ 같은 셀러를 가리키는 계정이 여러 개 등록돼 있으면 한 번만 조회한다.
    #   (판매처관리에 같은 마켓 셀러가 이름만 달리 두 번 등록된 사례 — 그대로 두면 같은 주문이
    #    2배로 계상돼 발송·정산이 배로 잡힌다. CLAUDE 🔒 중복·모순 절대 금지.)
    seen_ident, uniq, dups = {}, [], []      # ident → 먼저 등록된 계정명
    for name, cli in built:
        ident = _client_identity(market, cli)
        if ident is not None and ident in seen_ident:
            dups.append((name, seen_ident[ident], _ident_fingerprint(ident)))
            continue
        if ident is not None:
            seen_ident[ident] = name
        uniq.append((name, cli))
    if dups:
        _log.warning("동일 자격증명 계정 제외: market=%s accounts=%s",
                     market, [d[0] for d in dups])
        if warnings is not None:
            # 원인을 '같은 키가 입력됨'으로 명확히 말한다(주문이 같아 접은 경우와 구분).
            #  키 지문 = 자격증명 해시 앞 6자 — 키 값을 노출하지 않으면서 어느 계정끼리 같은
            #  키인지 사용자가 대조할 수 있게 한다.
            for name, first, fp in dups:
                warnings.append(
                    f"[{market}·{name}] 「{first}」와 API 키(셀러 식별자)가 같아 조회에서 "
                    f"제외했어요 — 키 지문 {fp}. 다른 가게라면 그 가게의 키를 다시 입력하세요.")
    built = uniq

    if not built:                               # 등록 0개/전부 키 없음
        cli0 = _account_client(market)          # 대표 계정(env 폴백) 시도
        if cli0 is None:                        # 자격증명이 하나도 없음 = API 연동 안 됨
            if warnings is not None:            # 화면·분석 → 제외 표면화 + 빈 결과(계속 진행)
                warnings.append(
                    f"[{market_label(market)}] API 연동(키)이 등록돼 있지 않아 "
                    f"매출 조회에서 제외했어요. 판매처 계정 관리에서 키를 등록하세요.")
                return []
            raise RuntimeError(                 # 엑셀 등 → 조용한 빈 파일 대신 전파
                f"'{market_label(market)}' API 자격증명이 등록돼 있지 않습니다.")
        return _rows_for(cli0, _account_alias(market))
    if len(built) == 1:
        return _rows_for(built[0][1], built[0][0])

    # ★ 계정 간 '주문 단위' 중복 제거 (최후 방어선).
    #   같은 스토어를 API 앱만 달리해 여러 계정으로 등록하면 자격증명(client_id 등)이 서로 달라
    #   _client_identity 로는 못 잡는다(스스 5계정이 같은 스토어인 실제 사례). 그러나 마켓
    #   주문번호는 그 마켓 안에서 유일하므로, 다른 계정이 같은 주문을 또 주면 같은 주문이다.
    #   → 앞선 계정에서 이미 본 행은 버린다(주문 2배 계상 = 발송·정산 2배 방지).
    def _row_key(r):
        return (str(r.get("오픈마켓주문번호", "")), str(r.get("상품명", "")),
                str(r.get("옵션", "")))

    # ── 계정 조회 (속도) ──
    #  스마트스토어는 계정을 병렬로 때리면 429(어댑티브 리미터·IP 기준)로 전멸한 전례가 있어
    #  반드시 순차. 나머지 마켓은 한도가 넉넉해 소폭 병렬로 대기시간을 줄인다.
    #  ★병합은 항상 '등록 순서'로 한다 — 중복 판정(어느 계정을 남길지)이 실행마다 달라지면 안 됨.
    workers = min(_ACCOUNT_WORKERS.get(market, 1), len(built))
    fetched = [None] * len(built)               # i → rows(list) | Exception
    if workers > 1:
        with _ThreadPool(max_workers=workers) as ex:
            futs = {ex.submit(_rows_for, cli, name): i
                    for i, (name, cli) in enumerate(built)}
            for fut, i in futs.items():
                try:
                    fetched[i] = fut.result()
                except Exception as e:          # noqa: BLE001
                    fetched[i] = e
    else:
        for i, (name, cli) in enumerate(built):
            try:
                fetched[i] = _rows_for(cli, name)
            except Exception as e:              # noqa: BLE001
                fetched[i] = e

    out, errors, ok_cnt = [], [], 0
    seen_rows, same_store = set(), []           # seen_rows = '앞선 계정들'이 이미 준 주문
    for i, (name, cli) in enumerate(built):
        rs = fetched[i]
        if isinstance(rs, Exception):           # 어느 계정인지 표면화
            errors.append(RuntimeError(
                f"[{market}·{name}] 주문 조회 실패: {type(rs).__name__}: {rs}"))
            continue
        ok_cnt += 1
        # 계정 '사이'의 중복만 제거한다. 한 계정이 준 행끼리는 그대로 둔다
        # (같은 주문의 여러 옵션행 등 정상 데이터를 지우지 않기 위해).
        fresh = [r for r in rs if _row_key(r) not in seen_rows]
        if rs and not fresh:                    # 이 계정 주문이 전부 앞 계정과 동일 = 같은 스토어
            same_store.append(name)
        out += fresh
        seen_rows.update(_row_key(r) for r in rs)

    if same_store:
        _log.warning("주문 전부 동일한 계정(같은 스토어로 보임): market=%s accounts=%s",
                     market, same_store)
        if warnings is not None:
            # 키는 서로 다른데 주문이 완전히 같은 경우 — '같은 키' 경고와 원인이 다르다.
            warnings.append(
                f"[{market}] 앞 계정과 주문이 완전히 같아 한 번만 반영했어요"
                f"(같은 스토어로 보임): " + ", ".join(same_store))

    if errors and (ok_cnt == 0 or warnings is None):
        # 전부 실패(보여줄 게 없음) 또는 경고 채널 없음(엑셀) → 전파. 불완전 결과 숨김 금지.
        raise errors[0]
    if errors:                                  # 일부 실패 → 나머지 반환 + 사유를 배너로
        warnings.extend(str(e) for e in errors)
    return out


def _to_int(v, default=None):
    """'4,000'·'4000.00'·4000 → 4000. 실패 시 default."""
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return default


import re as _re_dt


def _norm_order_dt(v) -> str:
    """주문일을 'YYYY-MM-DD HH:MM:SS'(시간 없으면 'YYYY-MM-DD')로 통일.

    마켓별 형식(ISO·공백구분·YYYYMMDDHHMMSS 등)을 정규화 → 시간 표시 + 문자열 정렬=시간순.
    못 알아보면 원본 유지.
    """
    s = str(v or "").strip()
    if not s:
        return ""
    # 순수 숫자(YYYYMMDD[HHMM[SS]]) — 롯데온 등
    if s.isdigit():
        d = s
        if len(d) >= 8:
            out = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
            if len(d) >= 12:
                out += f" {d[8:10]}:{d[10:12]}" + (f":{d[12:14]}" if len(d) >= 14 else ":00")
            return out
        return s
    dm = _re_dt.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if not dm:
        return s
    date = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
    tm = _re_dt.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if tm:
        return f"{date} {int(tm.group(1)):02d}:{tm.group(2)}:{tm.group(3) or '00'}"
    return date


def _finalize_rows(rows: list) -> list:
    """상품금액(단가×수량)·주문금액(상품+배송비)·배송비 배송건당 1회 정규화 + 주문일 시간 통일.

    배송비는 배송건(_shipkey=주문번호) 단위라, 같은 배송건의 두 번째 행부터 배송비 0
    (합계 중복 방지). 정산예정금액 delivery 는 빌더에서 이미 배송건당 1회 처리.
    주문일은 'YYYY-MM-DD HH:MM:SS' 로 통일(마켓 간 형식 차이 제거 → 시간 표시·정렬 정확).
    """
    seen = set()
    for r in rows:
        r["주문일"] = _norm_order_dt(r.get("주문일"))
        unit = _to_int(r.get("단가"))
        qty = _to_int(r.get("수량"), 1) or 1
        prod = unit * qty if unit is not None else ""
        r["상품금액"] = prod
        r.pop("_odseq", None)              # 140 진행단계 조인 임시키 제거(출력 누출 방지)
        sk = r.pop("_shipkey", None)
        ship = _to_int(r.get("배송비"), 0) or 0
        if sk is not None and sk in seen:
            ship = 0                       # 이미 계산한 배송건 → 0
        elif sk is not None:
            seen.add(sk)
        r["배송비"] = ship
        r["주문금액"] = (prod + ship) if prod != "" else ""

        # ── 샵마인 대조 파생(2026-07-08): 총주문금액·마켓수수료·수수료율 ──
        opt_add = _to_int(r.get("옵션추가금"), 0) or 0
        total = (prod + opt_add) if prod != "" else ""   # 총주문금액 = 단가×수량 + 옵션추가금
        r["총주문금액"] = total
        settle = _to_int(r.get("정산예정금액"))
        paid = _to_int(r.get("실결제금액"))
        if paid is None and isinstance(total, int):
            paid = total                     # 실결제 미제공(쿠팡 등) → 총주문금액(할인 없음 가정)
        # 마켓수수료: 빌더가 정산 API 실값으로 미리 채웠으면(롯데온 SettleCommission) 그대로 사용,
        #  아니면 실결제 − 정산예정금액 파생(둘 다 있고 양수일 때). 아니면 공란(폴백 금지).
        preset_fee = _to_int(r.get("마켓수수료"))
        if preset_fee is not None and preset_fee > 0:
            fee = preset_fee
        elif paid is not None and settle is not None and paid - settle > 0:
            fee = paid - settle
        else:
            fee = None
        if fee is not None:
            r["마켓수수료"] = fee
            r["수수료율"] = (f"{round(fee / total * 100, 2)}%"
                             if isinstance(total, int) and total > 0 else "")
        else:
            r["마켓수수료"] = ""
            r["수수료율"] = ""
        # 정산예정금(배송비포함) = 정산예정금액 + 고객배송비(무료배송이면 동일)
        r["정산예정금(배송비포함)"] = (settle + ship) if settle is not None else ""
        # 새 열 기본값 보장(빌더 미설정 시).
        r.setdefault("실결제금액", "")
        r.setdefault("옵션추가금", "")
        r.setdefault("오픈마켓주문번호", "")
        r.setdefault("쇼핑몰별칭", "")
        # 송장 없음의 두 의미를 구분(정직성): 발송 전이면 '송장미입력'(넣어야 함),
        #   이미 발송된 주문인데 비어 있으면 '확인 불가'(발송은 됐으나 마켓이 번호를 안 줌).
        #   11번가는 구매확정 주문의 invcNo 를 API로 제공하지 않아, 여기서 '미입력'으로 두면
        #   발송 안 한 것처럼 오해된다(2026-07-10 확인).
        if not str(r.get("송장입력") or "").strip():
            r["송장입력"] = ("확인 불가"
                             if str(r.get("주문상태") or "").strip() in _SHIPPED_STATES
                             else "송장미입력")
        r.setdefault("_settle_source", "none")
    return rows


# ── 성능: 마켓 병렬 조회 + 단기 캐시 ──────────────────────────────────
# 대시보드(preview.json)와 엑셀(export.xlsx)이 각각 3마켓 API를 처음부터 다시
# 조회해 느렸음. (1) 마켓별 조회를 병렬로(합계→최댓값) (2) 짧은 TTL 캐시로 대시보드
# 조회를 다운로드가 재사용(→ 즉시). 캐시는 웹 라우트만 opt-in(use_cache=True);
# 직접 호출·테스트는 기존대로 항상 실조회(결정적).
import threading as _threading
import time as _time
from concurrent.futures import ThreadPoolExecutor as _ThreadPool

CACHE_TTL = 90.0                      # 초 — 이 안에서 같은 (마켓,기간) 재조회는 캐시 히트
_CACHE: dict = {}                     # (markets, days) -> (monotonic_ts, rows)
_CACHE_LOCK = _threading.Lock()


def _fetch_combined(markets, days, now, since=None, until=None,
                    include_settlement=True, warnings=None) -> list:
    """마켓별 주문을 병렬 조회 후 최신순 통합.

    ★ 마켓 단위 부분 실패 정책 — 계정 단위(order_rows) 정책과 동일하게 warnings 게이트:
      · warnings(list) 있음(화면·마진 분석) → 통째로 실패한 마켓은 그 사유를 warnings 에
        담아 '제외'로 표면화하고 성공한 마켓만 반환(부분 성공 허용·조용한 실패 금지).
        단 모든 마켓이 실패하면(보여줄 게 없음) 전파.
      · warnings 없음(엑셀 다운로드) → 한 마켓이라도 실패하면 전파(불완전 파일 방지).
    warnings 있을 때 일부 계정 실패 사유도 함께 담긴다(order_rows 참조).
    """
    def _one(mk):
        return order_rows(mk, days=days, now=now, since=since, until=until,
                          include_settlement=include_settlement, warnings=warnings)
    results, errors = {}, []          # errors = [(market, Exception)]
    if len(markets) == 1:             # 단일 마켓은 스레드 오버헤드 불필요
        try:
            results[markets[0]] = _one(markets[0])
        except Exception as e:        # noqa: BLE001
            errors.append((markets[0], e))
    else:
        with _ThreadPool(max_workers=min(4, len(markets))) as ex:
            futs = {ex.submit(_one, mk): mk for mk in markets}
            for fut, mk in futs.items():
                try:
                    results[mk] = fut.result()
                except Exception as e:   # noqa: BLE001 — 어느 마켓인지 함께 보관
                    errors.append((mk, e))
    if errors:
        # 전부 실패(보여줄 게 없음) 또는 경고 채널 없음(엑셀) → 전파. 부분 결과 숨김 금지.
        if warnings is None or not results:
            raise errors[0][1]
        for mk, e in errors:            # 일부 실패 → 나머지 반환 + 실패 마켓을 배너로
            warnings.append(_market_fail_msg(mk, e))
    all_rows = []
    for mk in markets:                # 입력 순서 유지 후 정렬
        all_rows += results.get(mk, [])
    all_rows.sort(key=lambda r: str(r.get("주문일", "")), reverse=True)  # 최신 먼저
    return all_rows


def clear_cache() -> None:
    """캐시 비우기(테스트·강제 새로고침용)."""
    with _CACHE_LOCK:
        _CACHE.clear()


import re as _re


def _row_order_date(r):
    """행의 '주문일'에서 날짜(date) 추출. 형식 무관(YYYY-MM-DD, YYYY.MM.DD, ISO 등)."""
    m = _re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", str(r.get("주문일") or ""))
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _filter_by_order_date(rows, since, until):
    """주문일이 [since, until] 안에 든 행만 남김(기간 = 주문일 기준 통일).

    마켓·상태별 API 는 기준일이 제각각(결제완료일·배송완료일·변경일 등)이라, 화면의 '기간'을
    사용자 기대대로 '주문일' 기준으로 맞추기 위해 최종 행을 주문일로 다시 거른다.
    주문일 파싱 실패 행은 남긴다(데이터 손실 방지).
    """
    if not since or not until:
        return rows
    lo, hi = since.date(), until.date()
    out = []
    for r in rows:
        d = _row_order_date(r)
        if d is None or (lo <= d <= hi):
            out.append(r)
    return out


def combined_order_rows(markets, days: int = 7,
                        now: Optional[_dt.datetime] = None,
                        use_cache: bool = False,
                        since: Optional[_dt.datetime] = None,
                        until: Optional[_dt.datetime] = None,
                        include_settlement: bool = True,
                        warnings: Optional[list] = None) -> list:
    """여러 마켓 주문을 합쳐 최신순(주문일 내림차순)으로. 판매처 열로 마켓 구분.

    기간 = since~until 명시(빠른 기간 버튼·직접 날짜) 또는 최근 days일. 미지원 마켓이
    섞이면 ValueError. 한 마켓 조회 실패는 전체 실패로 전파. use_cache=True(웹 라우트) +
    now 미지정이면 TTL 캐시 사용(대시보드↔다운로드 공유, 캐시 키에 기간 포함).
    warnings(list) 전달 시 제외된 계정 사유가 담긴다. ★캐시에도 경고를 함께 저장한다 —
    캐시 적중 때 경고가 사라지면 그 자체로 조용한 실패가 되기 때문.
    """
    markets = list(markets)

    def _build(warns):
        rows = _fetch_combined(markets, days, now, since=since, until=until,
                               include_settlement=include_settlement, warnings=warns)
        # 기간 명시(빠른 버튼·직접 날짜) 시 주문일 기준으로 최종 필터 → '기간=주문일' 통일.
        return _filter_by_order_date(rows, since, until)

    if use_cache and now is None:
        key = (tuple(markets), days,
               since.isoformat() if since else None,
               until.isoformat() if until else None,
               include_settlement)
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
            if hit and (_time.monotonic() - hit[0]) < CACHE_TTL:
                if hit[2] and warnings is None:
                    # 화면(부분 허용)이 채운 캐시를 엑셀(전량 필요)이 받으면 불완전 파일이
                    # 조용히 나간다 → 경고가 있으면 경고 채널 없는 호출엔 캐시를 주지 않는다.
                    raise RuntimeError(hit[2][0])
                if warnings is not None:
                    warnings.extend(hit[2])       # 캐시된 경고도 함께 되살림
                return hit[1]
        rows = _build(warnings)                   # warnings=None 이면 order_rows 가 전파
        with _CACHE_LOCK:
            _CACHE[key] = (_time.monotonic(), rows, list(warnings or []))
        return rows
    return _build(warnings)


def resolve_columns(columns=None) -> list:
    """사용자 지정 열(순서 유지)을 유효 열로 필터. 비면 기본 전체."""
    if not columns:
        return list(DEFAULT_COLUMNS)
    seen, out = set(), []
    for c in columns:
        c = (c or "").strip()
        if c in ALL_COLUMNS and c not in seen:
            seen.add(c)
            out.append(c)
    return out or list(DEFAULT_COLUMNS)


def rows_to_xlsx(rows: list, columns=None) -> bytes:
    """행(dict) → xlsx 바이트. columns 로 열 구성·순서 지정(A5 양식 설정)."""
    import openpyxl
    cols = resolve_columns(columns)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "주문"
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

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

from lemouton.markets import line_uid as _line_uid

KST = _dt.timezone(_dt.timedelta(hours=9))


def _until_now(until):
    """max(until, 지금 KST) — until 이 naive(마진계산기)면 now 도 naive 로 맞춰 비교(TypeError 방지)."""
    now = _dt.datetime.now(KST)
    if getattr(until, "tzinfo", None) is None:
        now = now.replace(tzinfo=None)
    return max(until, now)

# 선택·순서 조정 가능한 전체 열(사용자 요청: B=판매처, C=주문상태). 기본 순서 = 이 목록.
ALL_COLUMNS = ["주문일", "판매처", "주문상태", "상품명", "옵션", "수량",
               "수령자", "수령자전화번호", "주소", "우편번호", "배송메시지",
               "구매자", "구매자번호", "단가", "배송비", "상품금액", "주문금액",
               "정산예정금액", "판매경로",
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
    "판매경로":     {"kind": "api",  "desc": "롯데온 유입경로(제휴=상품가 2% 수수료 / 롯데ON=0). 크롤 1회 확정·재판단 없음"},
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


def _ss_status(product_order_status, place_order_status):
    """스마트스토어 표시 상태 — 발주확인(placeOrderStatus=OK)을 반영.

    ★네이버는 발주확인(배송준비)해도 productOrderStatus 를 PAYED(결제완료) 그대로 둔다.
      productOrderStatus 만 보면 이미 배송준비된 주문이 「결제완료」로 둔갑한다(2026-07-15 실측:
      placeOrderStatus=OK·placeOrderDate 있는데 productOrderStatus=PAYED). placeOrderStatus=OK 면
      발주확인 완료 → 「배송준비중」으로 표시(자동전환 대상에서도 자동 제외됨).
    """
    base = _status_ko("smartstore", product_order_status)
    if base == "결제완료" and str(place_order_status or "").upper() == "OK":
        return "배송준비중"
    return base

SUPPORTED = {"smartstore", "lotteon", "coupang", "eleven11"}   # UI 엑셀버튼 노출. 실키=서버 UI저장.

# 라이브 검증(판매처관리 「🧪 라이브 검증」)으로 열 수 있는 마켓 — 조회 코드는 준비 완료,
# 실계정 왕복 확인만 남은 것들. 여기 없는 마켓은 검증 기록이 있어도 열리지 않는다.
LIVE_VERIFIABLE = {"auction", "gmarket"}


def verified_markets() -> set:
    """라이브 검증이 끝나 공개해도 되는 마켓.

    조건 = 그 마켓의 **활성 계정이 1개 이상**이고 **전부** live_verified_at 이 있을 것.

    ★ 한 계정이라도 미검증이면 마켓 전체를 잠근다. 검증된 계정만 부분 공개하면
      나머지 가게 주문이 통째로 빠진 채 '전체 주문'처럼 보인다 — 조용한 누락은
      발송 사고로 직결된다(11번가 같은 키 사고와 같은 계열).
    DB 미연결·컬럼 미생성 등에서는 빈 집합(=아무것도 안 염)으로 안전하게 떨어진다.
    """
    try:
        from shared.db import SessionLocal
        from lemouton.sourcing.models_v2 import UploadAccount
        s = SessionLocal()
    except Exception:  # noqa: BLE001 — DB 미연결/모델 미로드. 열지 않는 쪽이 안전.
        return set()
    try:
        rows = (s.query(UploadAccount.market, UploadAccount.live_verified_at)
                .filter(UploadAccount.market.in_(sorted(LIVE_VERIFIABLE)),
                        UploadAccount.is_active == True)      # noqa: E712
                .all())
    except Exception:  # noqa: BLE001 — 컬럼 미생성(마이그레이션 전) 등.
        return set()
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass

    by: dict = {}
    for market, verified_at in rows:
        by.setdefault(market, []).append(verified_at)
    return {m for m, stamps in by.items()
            if stamps and all(t is not None for t in stamps)}


def supported_markets() -> set:
    """UI 노출·조회가 허용된 마켓 = 정적 SUPPORTED ∪ 라이브 검증 완료 마켓.

    소비처는 `SUPPORTED` 상수 대신 **반드시 이 함수**를 쓴다. 상수를 직접 참조하면
    검증 후에도 안 열리거나(모듈 로드 시점 복사) 검증 전에 열린다.
    송장 전송(invoice_send.SUPPORTED_SEND)·CS 문의는 '마켓에 쓰는' 동작이라
    조회 검증으로 열지 않는다 — 별도 게이트 유지.
    """
    return set(SUPPORTED) | verified_markets()
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
                          client=None, include_settlement: bool = True,
                          changed_to_now: bool = True) -> list:
    """스마트스토어 [since,until] 주문 → 16컬럼 행(dict) 리스트.

    변경 상품주문 내역 조회(정식 코드) → 상세 → 정산예정금액(결제일 기준) 조인.
    정산 없는 주문은 빈칸(폴백 0 금지).
    """
    from shared.platforms.smartstore.orders import (
        iter_changed_product_order_ids, fetch_order_detail)
    from shared.platforms.smartstore import settlements as _settle
    from shared.platforms.smartstore.client import SmartStoreClient

    client = client or SmartStoreClient()
    since, until = _ensure_kst(since), _ensure_kst(until)   # naive(_parse_dt/probe)→KST(비교 TypeError 방지)

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
    # ★ 조회 끝은 now 까지 확장(_until_now = max(until, now) = now). last-changed 는 24h 윈도우로
    #   끊어 호출하므로(orders.iter_changed_product_order_ids) 넓은 범위도 단일 호출 400 조회범위초과를
    #   유발하지 않고, 미래일은 위 until>now 상한이 막는다. 소심한 +3일/10일 버퍼는 구매확정·반품 등
    #   상태변경이 until+3 을 넘어간 주문(주문일은 창내)을 통째 누락시켜 정산 매칭 불가 → 제거.
    #   창밖 여분 행은 하류 _filter_by_order_date(마진)·probe want 셋(검증)이 주문일로 되잘라낸다.
    # 과거 백필(changed_to_now=False)에선 확장하지 않는다 — back=100 이면 100일치를 하루씩
    #   스캔해(~100회) 창 하나가 50초를 넘긴다(2026-07-21 실측, 504의 진짜 원인). 백필은
    #   '변경일이 이 창에 속한 주문'만 잡고, 호출부가 모든 창(1년)을 훑어 union 으로 전체를
    #   빠짐없이 모은다(주문은 마지막 변경일이 속한 창에 정확히 한 번 나타난다). 주문일 트리밍도
    #   안 한다(직접 호출 경로) → 변경일-주문일이 다른 창이어도 누락 없음.
    fetch_until = _until_now(until) if changed_to_now else until
    ids = iter_changed_product_order_ids(since, fetch_until, client=client)
    detail = []
    for i in range(0, len(ids), 300):
        d = fetch_order_detail(ids[i:i + 300], client=client)
        detail += (d.get("data", d) if isinstance(d, dict) else d) or []

    # 정산(결제일 기준, 하루씩): 상품(productOrderId) + 배송비(DELIVERY→orderId) 별도 맵.
    # include_settlement=False(배송검사 등 주문상태·송장만 필요) 면 이 하루씩 루프를 건너뛴다
    # — 넓은 조회창에서 하루씩 정산 호출이 타임아웃의 원인.
    # ⚠️ 스마트스토어는 병렬 조회 시 429(어댑티브 리미터·IP 기준)로 rate 가 반감돼 오히려 느려지고
    #    다른 스스 작업까지 위협하는 전례가 있어(라이브 실측) 순차 유지. 속도개선은 서버 캐시(use_cache)
    #    와 프론트 캐시·프리페치로 얻는다. 쿠팡은 단순 토큰버킷이라 병렬화 유지(별개).
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
            # 배송비 실정산은 상품정산 유무와 무관하게 붙어야 한다 — 반품·'배송비만 정산'(상품
            # 없음) 케이스가 누락되던 조용한실패(쿠팡과 동일 버그클래스) 방지. 상품 추정치엔 더하고,
            # 상품이 아예 없으면 배송비만으로 real 처리.
            if oid and oid not in _deliv_used and oid in deliv_settle:
                if settle_val == "":
                    settle_val, settle_src = deliv_settle[oid], "real"
                else:
                    settle_val += deliv_settle[oid]
                _deliv_used.add(oid)
        _ss_st = _ss_status(_g(po, "productOrderStatus"), _g(po, "placeOrderStatus"))
        _row = {
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
            "주문상태": _ss_st,
            "주문상태원본": _g(po, "productOrderStatus"),
            "오픈마켓주문번호": poid or oid,
            # ── M4 가격 전후 표시용 상품 식별자(내부 전용 `_pd_` — 엑셀·화면 열에 안 나감) ──
            #  공식문서(마켓 API 지도 smartstore.seller-get-product-orders-pay-order-seller)에
            #  productId=채널 상품 번호 / originalProductId=원상품 번호 로 명시돼 있다.
            #  판매처 연동(SetChannel.market_product_id)은 둘 중 무엇으로도 등록될 수 있어
            #  (market_fetch._fetch_smartstore 가 채널·원상품 둘 다 받아 resolve 한다) 둘 다 보존한다.
            #  ★옵션 단위 id 는 담지 않는다 — 응답의 optionCode 는 뜻이 명시돼 있지 않고
            #   2026-07-22 deprecated 예정, optionId 는 '판매 옵션 ID'라
            #   SetChannelOption.market_option_id(=조합형 옵션 id, optionCombinations[].id)와
            #   같다는 근거가 없다. 추측해서 이으면 엉뚱한 옵션의 가격을 보여주므로,
            #   롯데온과 동형으로 상품 단위 + 옵션 텍스트(색·사이즈)로만 좁힌다.
            "_pd_market_product_id": _g(po, "productId"),
            "_pd_market_product_id_alt": _g(po, "originalProductId"),
            "실결제금액": _g(po, "totalPaymentAmount", default=""),   # 할인 반영 실결제
            "옵션추가금": _g(po, "optionPrice", default=""),
            # 이미 등록된 송장은 마켓이 정본 — 안 읽어오면 사용자가 손으로 다시 치게 되고,
            # 그 값이 실제와 어긋나도 화면상 알 길이 없다(2026-07-10 실제 발생).
            "송장입력": _g(dv, "trackingNumber", default=""),
            "발송처리일": _g(dv, "sendDate", "sendDate", default=""),   # 스스 발송일 → 경과시간용
        }
        # ── 취소/반품/교환 = 상태변경(#2 CS) 태그 ──
        #  스스는 다른 마켓과 달리 '변경 상품주문 내역 조회' 한 피드가 클레임 상태(CANCELED·
        #  RETURNED·EXCHANGED → 취소완료/반품완료/교환완료)까지 함께 준다. 그 행을 _kind='change'
        #  로 태그해야 status_change_rows(=CS 반품·교환·취소)에 잡힌다(태그 없으면 CS 0건).
        #  구매자·수령자·주소·상품명은 위에서 이미 채워져 CS 카드에 그대로 노출된다.
        if _ss_st[:2] in ("취소", "반품", "교환"):
            _row["_kind"] = "change"
            # 변경일 — 클레임/최근변경일(있으면) → 없으면 주문일(폴백). 공란도 보존됨(status_change_rows).
            _cl = po.get("claim") if isinstance(po.get("claim"), dict) else {}
            _row["_change_date"] = str(
                _g(_cl, "claimRequestDate", "claimDate")
                or _g(po, "lastChangedDate", "claimRequestDate")
                or _g(od, "orderDate") or "")
        rows.append(_row)
    return rows


# 롯데온 odPrgsStepCd 중 회수·반품·취소 '진행/종결' 코드(클레임 이벤트).
#   21취소완료·22철회·23회수지시·24회수진행·25회수완료·26회수확정·27반품완료.
_LO_CLAIM_STEP_CODES = {"21", "22", "23", "24", "25", "26", "27"}


def _lotteon_odno_date(odno) -> Optional[str]:
    """롯데온 주문번호 앞 8자리(YYYYMMDD)=실주문일 → 'YYYY-MM-DD'. 형식·날짜 무효면 None.

    (라이브 2026-07-16: 정상 주문행 108/108 이 주문번호 앞자리=주문일 일치. 11번가 ordNo[:8]
    보정과 동일 관행.)
    """
    s = str(odno or "")
    if len(s) >= 8 and s[:2] == "20" and s[:8].isdigit():
        try:
            _dt.date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        except ValueError:
            return None
    return None


def _reclassify_lotteon_returns(rows: list) -> list:
    """209(출고/회수지시) 경로 행의 주문일 이벤트일 오염을 바로잡는다.

    209(SellerDeliveryOrdersSearch)는 회수지시·교환 재출고 건도 돌려주는데, 그 행의
    odCmptDttm 는 '배송(회수/재출고)지시 생성일시'라 옛 주문(예: 07-14 주문)의 주문일이
    지시일(오늘)로 오염돼 new_order_rows(오늘 신규주문)에 잘못 섞인다(라이브 실측 2026-07-16:
    회수지시 3건). 회수지시(코드 23)뿐 아니라 교환 재출고(정상 출고코드 11~15로 재유입)도 같은
    버그클래스라, **상태코드와 무관하게** 주문번호 앞 8자리(실주문일)와 주문일의 날짜가 다르면
    이벤트일 오염으로 보고 실주문일로 복원한다(당일 출고 정상건은 날짜 동일 → 시각 포함 원값 유지).

    복원 후: new_order_rows 는 실주문일로 오늘에서 제외한다. 나아가 회수·반품·취소 진행상태
    (코드 21~27)는 클레임 이벤트이므로 _kind='change'(+_change_date=이벤트 시각)로 재분류해
    status_change_rows(CS 상태변경 탭)가 변경일로 잡게 하고, 같은 주문·상품의 원출고행+회수행
    중복은 (주문번호·상품·옵션) 기준으로 최신 이벤트 1건만 남긴다. 교환 재출고(11~15)는 주문일만
    복원하고 order 로 유지(재출고=배송 진행이라 CS 대상 아님) — 실주문일 덕에 오늘엔 안 섞인다.
    """
    others: list = []
    claims: dict = {}   # (odNo, 상품명, 옵션) → 유지행(최신 _change_date)
    for r in rows:
        if not r.get("_shipkey"):
            others.append(r)            # 비209행(클레임행 등)은 그대로
            continue
        code = str(r.get("주문상태원본") or "")
        odno = str(r.get("오픈마켓주문번호") or "")
        odt = str(r.get("주문일") or "")   # 209 원본 주문일(정상=주문일 / 회수·재출고=이벤트일)
        real = _lotteon_odno_date(odno)
        # 이벤트일 오염 복원 — 코드 무관: 주문번호(실주문일) ≠ 주문일 날짜면 이벤트일로 판단.
        if real and odt[:10] != real:
            r["주문일"] = real
        if code not in _LO_CLAIM_STEP_CODES:
            others.append(r)            # 정상 출고·교환 재출고(11~15) → order 유지(날짜만 복원됨)
            continue
        r["_kind"] = "change"           # 회수·반품·취소(21~27) → 클레임 이벤트로 재분류
        r["_change_date"] = odt         # 이벤트 시각(복원 전 원 주문일)
        gk = (odno, str(r.get("상품명") or ""), str(r.get("옵션") or ""))
        prev = claims.get(gk)
        if prev is None or odt > str(prev.get("_change_date") or ""):
            claims[gk] = r               # 원출고행+회수행 중복 → 최신 이벤트 1건만
    return others + list(claims.values())


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
    _lo_fetch_until = _until_now(until)
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
            # 209 정산 성분(2026-07-15 실검증 매핑) — 아래 정산 조인에서 compute_settlement 입력.
            "_lo_slAmt": _g(od, "slAmt", default=""),              # 상품가
            "_lo_seller_dc": _g(od, "sptDcPgmCmsnSum", default=""),  # 셀러부담 할인
            "_lo_platform_dc": _g(od, "prSfcoShrAmtSum", default=""),  # 롯데부담 할인
            "_lo_dvcst": _g(od, "dvCst", default=""),              # 수수료적용배송비
            "_lo_spdno": _g(od, "spdNo", default=""),              # 상품번호(제휴 학습 키)
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
            # 롯데온 클레임 API는 실주문일 미제공(clmReqDttm=클레임일뿐) → 현재 공란.
            # odAccpDttm은 API가 훗날 주면 자동 승격되도록 남겨둔 forward-compat 키.
            "주문일": str(_g(it, "odAccpDttm", default="")),
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
            # 라인·클레임 식별자 — 데이터 코드 지도 fields 확인(2026-07-20):
            #   clmNo=클레임번호 · odSeq=주문순번(단품별) · sitmNo=판매자단품번호.
            #   앞서 "롯데온 클레임엔 고유번호가 없다"고 판단했는데 틀렸다. clmNo 가 있다.
            "_send_ids": {"od_no": str(_g(it, "odNo", default="")),
                          "od_seq": str(_g(it, "odSeq", default="")),
                          "sitm_no": str(_g(it, "sitmNo", default="")),
                          "clm_no": str(_g(it, "clmNo", default=""))},
            "_kind": "change",
            "_change_date": str(_g(it, "clmReqDttm", default="")),   # 변경일(#2용)
        }

    # seen_active = 활성 주문(209)이 이미 준 주문번호 / seen_claim = 클레임끼리의 라인 중복
    seen_active = {r["오픈마켓주문번호"] for r in rows if r.get("오픈마켓주문번호")}
    seen_claim: set = set()
    #  요청↔완료 세분: 클레임 itemList의 odPrgsStepCd 로 판정(21취소완료·27반품완료). 교환 완료코드
    #  미확정 → 교환요청 유지(라이브 재측정으로 실코드 확인 후 보정). 그 외(회수지시·진행)=요청.
    _lo_done = {"취소": "21", "반품": "27"}   # 교환=None(완료코드 미확정)
    # ★ 클레임은 '클레임 접수일' 기준 조회 → 기간 안 주문이 나중에 취소되면 [since,until] 밖이라
    #   통째 누락(라이브: 롯데온 4건). 조회 끝을 now 로 넓힌다(주문번호 매칭이라 넓혀도 안전).
    _lo_claim_until = _until_now(until)
    for fn, base, qkey in ((_clm.iter_cancel, "취소", "cnclQty"),
                           (_clm.iter_return, "반품", "rtngQty"),
                           (_clm.iter_exchange, "교환", "xchgQty")):
        try:
            for it in fn(since, _lo_claim_until, client=client):
                on = _g(it, "odNo")
                # ① 활성 주문에 이미 있는 주문이면 클레임행을 안 만든다(기존 의도 유지).
                if on and on in seen_active:
                    continue
                # ② 클레임끼리는 **라인 단위**로 중복 제거한다. 예전엔 odNo 하나로 접어서
                #    한 주문에서 두 상품을 반품하면 1건만 잡혔다(누락). 단품번호(sitmNo)가
                #    있으면 그걸로, 없으면 상품·옵션명까지 붙여 최대한 좁힌다.
                #  clmNo(클레임번호)가 가장 정확하고, 없으면 단품번호, 그것도 없으면 상품·옵션명.
                line_key = (on, str(_g(it, "clmNo", default="")) or
                            str(_g(it, "sitmNo", default="")) or
                            f"{_g(it, 'spdNm')}|{_g(it, 'sitmNm')}")
                if line_key in seen_claim:
                    continue
                seen_claim.add(line_key)
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

    # ── 정산예정금액(2026-07-15 실검증 오차0) ────────────────────────────────
    #  구매확정 주문 = SettleItmdSales.pymtAmt(마켓 실지급액, 정확) — 계산 불필요.
    #  미정산 주문   = 209 성분 + compute_settlement(제휴는 상품별 이력으로 추정).
    #  ★정산 기준일=구매확정일이라 조회창을 [주문창 시작 ~ 지금]으로 넓혀 odNo/spdNo 로 조인.
    from lemouton.margin.lotteon_settlement import compute_settlement as _lo_calc
    itmd, aff_by_spd = {}, {}
    if include_settlement:
        try:
            from shared.platforms.lotteon import settlement as _lo_settle
            itmd, aff_by_spd = _lo_settle.scan(since, _lo_fetch_until, client=client)
        except Exception:   # noqa: BLE001
            itmd, aff_by_spd = {}, {}

    # ── 크롤 정산(판매자센터) 캐시 로드 — 라인별 실정산액(pymtTgtAmt)+판매경로(제휴 여부).
    #    ★제휴 판단은 크롤로 1회 확정되면 sl_chnl 에 박혀 여기서 재사용(재판단·중복작업 불필요).
    cmap, chnlmap = {}, {}
    try:
        from lemouton.sourcing.models_v2 import LotteonSettlement
        from shared.db import SessionLocal as _SL
        ods = {str(r.get("오픈마켓주문번호") or "") for r in rows}
        ods.discard("")
        if ods:
            with _SL() as _s:
                for x in _s.query(LotteonSettlement).filter(
                        LotteonSettlement.od_no.in_(list(ods))).all():
                    cmap[(x.od_no, str(x.od_seq))] = x.pymt_tgt_amt
                    if x.sl_chnl:
                        chnlmap[(x.od_no, str(x.od_seq))] = x.sl_chnl
    except Exception:   # noqa: BLE001 — DB 없거나 조회 실패 시 추정 경로로 폴백(추측 폴백 아님)
        cmap, chnlmap = {}, {}

    def _lo_affiliate(r):
        """제휴 여부 — 크롤 저장 판매경로(확정) 최우선, 없으면 상품별 이력(추정). (is_aff, 판매경로라벨)."""
        key = (str(r.get("오픈마켓주문번호") or ""), str(r.get("_odseq") or "1"))
        chnl = chnlmap.get(key)
        if chnl is not None:
            return ("제휴" in chnl), chnl                       # 확정(크롤 1회 판단)
        aff = bool(aff_by_spd.get(str(r.get("_lo_spdno") or ""), False))
        return aff, ("제휴" if aff else "롯데ON")               # 추정(상품별 이력)

    for r in rows:
        odno = str(r.get("오픈마켓주문번호") or "")
        aff, chnl_label = _lo_affiliate(r)
        r["판매경로"] = chnl_label                              # 표시용(제휴/롯데ON)
        r["제휴수수료율"] = 2 if aff else 0                     # 제휴면 2%(표시)
        r["_lo_is_affiliate"] = aff
        hit = itmd.get(odno)
        if hit:                                  # 구매확정 = 마켓 실지급액(정확)
            r["정산예정금액"] = hit["pymtAmt"]
            r["_settle_source"] = "real"
            continue
        slamt = _to_int(r.get("_lo_slAmt"))
        if slamt is None:                        # 209 성분 없음(클레임행 등) → 유지
            continue
        dvc = _to_int(r.get("_lo_dvcst"), 0) or 0
        r["정산예정금액"] = _lo_calc(
            slamt, dvc, dvc,
            _to_int(r.get("_lo_seller_dc"), 0) or 0,
            _to_int(r.get("_lo_platform_dc"), 0) or 0,
            aff)
        r["_settle_source"] = "estimated"        # 구매확정 전 추정(제휴는 크롤확정 or 상품별 이력)

    # ── 크롤 정산(판매자센터 pymtTgtAmt) 최우선 — 미정산 포함 오차0 ──
    for r in rows:
        v = cmap.get((str(r.get("오픈마켓주문번호") or ""), str(r.get("_odseq") or "1")))
        if v is not None:
            r["정산예정금액"] = v
            r["_settle_source"] = "real"

    # 회수·반품·취소 진행상태(209 경로)는 주문일이 회수지시 시각으로 오염됨 →
    #   실주문일 복원 + change 재분류(옛 주문이 '오늘 신규주문'에 새는 것 방지).
    rows = _reclassify_lotteon_returns(rows)
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
                       client=None, include_settlement: bool = True,
                       claim_to_now: bool = True) -> list:
    """쿠팡 발주서 목록 → 16컬럼 행(dict). status별(공식 필수) 순회 + nextToken 페이징.
    조회 최대 31일 제약 → _cp_windows 로 30일 분할(긴 기간·통합 조회 400 방지).

    발주서(shipmentBox) 하위 orderItems[] 평탄화(옵션 단위 1행). 정산예정금액은 발주서엔
    없어 revenue-history(별도 API)를 (주문번호,옵션ID)로 조인 — 미정산(최근주문)은 빈칸
    (폴백 금지). 스펙=GET_ORDERSHEET v5.
    """
    from shared.platforms.coupang.orders import fetch_orders

    statuses = ["ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY"]
    # ── 병렬 조회(속도) — 주문상태별 발주서·정산·반품·교환 조회는 서로 독립이라 한 번에 동시로 쏜다.
    #   같은 client 를 여러 스레드가 써도 안전: request()가 매 호출 새 requests.request 를 만들고
    #   스레드락 토큰버킷 리미터(초당 rate 캡 + 429 자동 백오프)가 요청률을 조절 → 경합·요청률
    #   증가 없음(429 위험 불변). 행 구성·중복제거·정산적용·클레임구성은 조회 후 순차(인메모리)로
    #   하므로 결과는 순차 실행과 동일하다(느린 왕복만 겹쳐 대기시간 단축).
    from shared.platforms.coupang import claims as _cc
    _settle_until = _until_now(until)
    # 평소엔 클레임 조회를 '지금'까지 확장해 늦은 취소·반품을 놓치지 않는다. 그러나
    # 과거 백필(claim_to_now=False)에선 그 확장이 back=315면 315일치 클레임을 스캔해
    # 창 하나가 50초를 넘긴다(2026-07-21 실측). 백필은 창 안 클레임만 본다(그 시점 이후
    # 늦은 클레임은 최근 조회가 이미 잡았다). → 과거 주문 채우기가 빨라진다.
    _claim_until = _until_now(until) if claim_to_now else until

    def _cp_fetch_boxes(w0, w1, st):
        out, token = [], None
        for _ in range(50):   # nextToken 페이징 안전 상한
            resp = fetch_orders(w0, w1, client=client, status=st, next_token=token)
            for box in (resp.get("data") or []):
                out.append((st, box))
            token = resp.get("nextToken")
            if not token:
                break
        return out

    def _cp_safe_list(fn):
        try:
            return list(fn(since, _claim_until, client=client))
        except Exception:   # noqa: BLE001 — 클레임 조회 실패는 활성 주문 유지
            return []

    _box_tasks = [(w0, w1, st) for (w0, w1) in _cp_windows(since, until) for st in statuses]
    with _ThreadPool(max_workers=8) as _ex:
        _fut_boxes = [_ex.submit(_cp_fetch_boxes, w0, w1, st) for (w0, w1, st) in _box_tasks]
        _fut_settle = _ex.submit(_coupang_settle_map, since, _settle_until, client) \
            if include_settlement else None
        _fut_ret = _ex.submit(_cp_safe_list, _cc.iter_returns)
        _fut_exc = _ex.submit(_cp_safe_list, _cc.iter_exchanges)
        _box_results = [f.result() for f in _fut_boxes]     # 태스크 순서 보존 = 순차와 동일 중복제거
        try:
            item_settle, deliv_settle = _fut_settle.result() if _fut_settle else ({}, {})
        except Exception:
            item_settle, deliv_settle = {}, {}
        _ret_raw, _exc_raw = _fut_ret.result(), _fut_exc.result()

    seen, rows = set(), []
    for _boxes in _box_results:
        for st, box in _boxes:
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

    # 정산예정금액 = 상품 정산(item_settle) + 배송비 정산(deliv_settle, 주문당 1회).
    #  revenue-history 조회는 위 스레드풀에서 주문·클레임과 동시에 끝냈다(_settle_until=now 로 넓혀
    #  조회 — 정산 인식일 기준이라 주문 기간 뒤 인식분까지 포함). 아래는 그 결과 적용(인메모리).
    _deliv_used = set()
    for r in rows:
        # vid 도 oid 처럼 str 정규화(양쪽 대칭). ordersheets(문자열)↔revenue-history(정수)
        # vendorItemId 타입 불일치로 (oid,vid) 튜플키가 전량 미스→estimated 폴백하던 버그 수정.
        oid, vid = str(r.pop("_oid", "")), str(r.pop("_vid", "") or "")
        # M4 가격 전후 표시 — vendorItemId 는 이 주문이 우리 어느 옵션(SKU)인지 아는
        #  유일한 열쇠다(SetChannelOption.market_option_id 와 같은 값). 정산 조인 후
        #  버려지면 주문↔소싱처를 연결할 방법이 사라져 전 행이 '확인 불가'가 된다.
        if vid:
            r["_pd_market_option_id"] = vid
        ship = r.get("배송비") or 0
        actual = item_settle.get((oid, vid))
        if actual is not None:                        # 확정: 상품정산 + 배송비정산(주문당 1회)
            val = actual
            if oid not in _deliv_used and oid in deliv_settle:
                val += deliv_settle[oid]
                _deliv_used.add(oid)
            r["정산예정금액"] = val
            r["_settle_source"] = "real"
        else:
            # 상품정산 없음. 단, 배송비 정산(deliv_map)은 상품 유무와 무관하게 주문당 1회 붙어야
            # 한다 — 반품·조건부무료배송미달 등 '배송비만 정산'(상품 판매수량 0) 케이스를 안 붙이면
            # 실 배송비정산이 통째 누락(조용한실패, 실측 24100197897393=9670 배송료-only). 실
            # 배송비정산 있으면 real, 없으면 상품추정+배송비추정.
            has_real_deliv = oid in deliv_settle and oid not in _deliv_used
            prod_est = _cp_estimate_settle(r.get("단가"), r.get("수량"), 0)
            if prod_est == "":
                if has_real_deliv:                     # 배송비만 정산되는 주문 = real
                    r["정산예정금액"] = deliv_settle[oid]
                    r["_settle_source"] = "real"
                    _deliv_used.add(oid)
                else:
                    r["정산예정금액"] = ""
                    r["_settle_source"] = "none"
            else:
                deliv_val = 0
                if has_real_deliv:                     # 상품추정이라도 배송비는 실정산 우선(이중계상 방지)
                    deliv_val = deliv_settle[oid]
                    _deliv_used.add(oid)
                elif oid not in _deliv_used and str(ship).lstrip("-").isdigit():
                    deliv_val = round(int(ship) * CP_SHIP_FEE_FACTOR)
                    _deliv_used.add(oid)
                r["정산예정금액"] = prod_est + deliv_val
                r["_settle_source"] = "estimated"

    # ── 취소/반품/교환 병합(returnRequests + exchangeRequests, MCP 실측 2026-07-09) ──
    #  활성 발주서에 없는 주문만 추가. 쿠팡 주문번호는 날짜 미인코딩 → 주문일=접수일(createdAt) 근사.
    #  ★반품·교환 원시 목록은 위 스레드풀에서 이미 받아 _ret_raw·_exc_raw 에 담겨 있다(동시 조회).

    def _cp_claim_row(odno, status, name, opt, qty, unit, reason, buyer, cdt, raw_code="",
                      phone="", addr="", zipcode=""):
        # 구매자 연락처·주소(#3) — 반품/취소 목록조회(returnRequests)가 requesterPhoneNumber·
        #  requesterAddress·requesterAddressDetail·requesterZipCode 를 함께 준다(공식 문서 확인
        #  2026-07-16). 추가 API 호출 0. 교환(exchangeRequests)은 미제공 → 공란 유지.
        return {
            "주문일": "", "판매처": "쿠팡",   # 쿠팡 클레임은 실주문일 미제공 → 공란(cdt=클레임일은 _change_date로)
            "상품명": name or "", "옵션": opt or "",
            "수량": qty if qty not in (None, "") else "",
            "주소": addr or "", "우편번호": zipcode or "", "수령자": buyer or "",
            "배송메시지": reason or "", "구매자": buyer or "",
            "수령자전화번호": phone or "", "구매자번호": phone or "",
            "쇼핑몰": "쿠팡", "쇼핑몰ID": "",
            "단가": unit if unit not in (None, "") else "",
            "배송비": 0, "정산예정금액": "", "_settle_source": "none",
            "주문상태": status, "주문상태원본": raw_code or "",   # receiptStatus/exchangeStatus — API코드 칸
            "오픈마켓주문번호": str(odno or ""),
            "실결제금액": "", "송장입력": "",
            "_kind": "change",
            "_change_date": str(cdt or ""),   # createdAt=변경일(#2용)
        }

    # ★ 클레임(취소/반품/교환)은 '클레임 생성일' 기준 조회다. 기간 안 주문이 나중에(기간 밖)
    #   취소되면 그 클레임은 [since,until] 창에 안 잡혀 통째 누락된다(라이브: 쿠팡 취소완료
    #   62건 미조회 = 손실 미포착). 롯데온 commission_map 처럼 조회 끝을 now 로 넓힌다
    #   (주문번호로 매칭하므로 넓혀도 우리 주문에 없는 건 무시돼 안전).
    seen_ord = {r.get("오픈마켓주문번호") for r in rows if r.get("오픈마켓주문번호")}
    try:
        for rq in _ret_raw:
            odno = str(rq.get("orderId") or "")
            if odno and odno in seen_ord:
                continue
            # 요청↔완료 세분: receiptStatus RETURNS_COMPLETED=완료, 그 외(RU 접수·PR 진행 등)=요청.
            _base = "취소" if rq.get("receiptType") == "CANCEL" else "반품"
            st = _base + ("완료" if rq.get("receiptStatus") == "RETURNS_COMPLETED" else "요청")
            _cp_addr = (str(rq.get("requesterAddress") or "") + " "
                        + str(rq.get("requesterAddressDetail") or "")).strip()
            for it in (rq.get("returnItems") or [{}]):
                rows.append(_cp_claim_row(
                    odno, st, it.get("sellerProductName"), it.get("vendorItemName"),
                    it.get("cancelCount"), None, rq.get("reasonCodeText"),
                    rq.get("requesterName"), rq.get("createdAt"),
                    rq.get("receiptStatus") or rq.get("receiptType"),
                    phone=rq.get("requesterPhoneNumber"), addr=_cp_addr,
                    zipcode=rq.get("requesterZipCode")))
    except Exception:   # noqa: BLE001 — 클레임 조회 실패는 활성 주문 유지
        pass
    try:
        for ex in _exc_raw:
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
            # ★부호 규칙(2026-07-16 라이브 raw 실증):
            #  · deliveryFee.settlementAmount 는 REFUND 주문에서 이미 음수(-9670)로 부호가 실려온다
            #    → 그대로 합산.
            #  · items[].settlementAmount 는 REFUND 주문에서도 양수(+93668)로 부호가 없다
            #    → order.saleType=="REFUND" 면 차감해야 순정산액이 맞다(안 그러면 반품 상품이
            #    판매처럼 더해져 정산액 2배 과다계상). aggregate_settlements 와 동일 규칙.
            is_refund = (order.get("saleType") == "REFUND")
            sign = -1 if is_refund else 1
            damt = (order.get("deliveryFee") or {}).get("settlementAmount")
            if damt is not None:
                try:
                    deliv_map[oid] = deliv_map.get(oid, 0) + int(damt)   # 이미 부호 실림
                except (TypeError, ValueError):
                    pass
            for it in (order.get("items") or []):
                vid, amt = str(it.get("vendorItemId") or ""), it.get("settlementAmount")
                if amt is None or not vid:   # 빈 vid 는 조인 불가(빈키 "" 충돌 방지)
                    continue
                try:
                    item_map[(oid, vid)] = item_map.get((oid, vid), 0) + sign * int(amt)
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


# 클레임 상태코드 → 화면 표기. 다른 마켓과 같은 말(취소완료·반품완료·교환요청…)을 쓴다.
_ESM_CLAIM_KO = {
    "cancel":   {1: "취소요청", 2: "취소중", 3: "취소완료", 4: "취소철회",
                 5: "취소완료(직권)", 6: "취소완료(송금후)"},
    "return":   {1: "반품요청", 2: "반품수거완료", 3: "반품보류", 4: "반품완료",
                 5: "반품철회", 6: "반품완료(직권)"},
    "exchange": {0: "교환재발송", 1: "교환요청", 2: "교환수거완료", 3: "교환보류",
                 4: "교환완료", 5: "교환철회"},
    "uncollected": {},
}
_ESM_CLAIM_STATUS_FIELD = {"cancel": "CancelStatus", "return": "ReturnStatus",
                           "exchange": "ExchangeStatus"}
# 한 번 조회에서 상세 보강을 시도할 클레임 건수 상한.
# 1건당 주문번호 조회 3모양 + 상품 API 2회가 붙어, 클레임이 많으면 응답이 30초를 넘고
# 앞단 게이트웨이가 502 로 끊는다(2026-07-20 라이브 실측).
_ESM_DETAIL_BUDGET = 8
# 클레임 건에 대해 '주문번호로 주문조회'를 시도할지. 라이브 3회 실측 결과 세 가지 요청
# 모양 모두 0건이라 False. 마켓이 돌려주기 시작하면 True 로 바꾸면 된다.
_ESM_CLAIM_ORDER_LOOKUP = False

# 클레임 사유 코드 → 사람 말. 마켓 취소관리 화면에 보이는 것과 같은 정보다.
#   Reason     = 귀책 주체 / ReasonCode = 상세 사유
#   ★ 취소와 반품·교환의 코드표가 서로 다르다(공식문서) — 섞으면 엉뚱한 사유가 찍힌다.
_ESM_FAULT_KO = {0: "판매자 귀책", 1: "구매자 귀책", 2: "기타"}
_ESM_REASON_KO = {
    "cancel": {0: "기타", 1: "단순변심", 2: "사이즈/색상 등 변경", 3: "오배송",
               4: "상품미도착", 5: "상품불량", 6: "재고없음(판매자요청)",
               7: "선물수락기한만료", 8: "선물거절", 11: "구매자 취소요청"},
    "return": {1: "단순변심", 2: "옵션변경", 3: "다른상품 오배송",
               4: "상품 미도착", 5: "상품 불량", 6: "판매자 요청"},
}
_ESM_REASON_KO["exchange"] = _ESM_REASON_KO["return"]   # 문서상 반품과 같은 체계


def _esm_claim_reason_ko(od: dict) -> str:
    """클레임 사유 — "판매자 귀책 · 재고없음(판매자요청)" 형태.

    마켓 화면엔 보이는데 우리 주문내역엔 없던 정보다(CS 대응에 바로 쓰인다).
    코드표에 없는 값은 숫자를 그대로 남긴다 — 임의로 해석하면 틀린 사유가 찍힌다.
    """
    kind = od.get("_claim_kind")
    parts = []
    fault = od.get("Reason")
    if fault not in (None, ""):
        try:
            parts.append(_ESM_FAULT_KO.get(int(fault), f"귀책코드{fault}"))
        except (TypeError, ValueError):
            parts.append(str(fault))
    detail = str(od.get("ReasonDetail") or "").strip()
    code = od.get("ReasonCode")
    if code not in (None, ""):
        table = _ESM_REASON_KO.get(kind) or {}
        try:
            label = table.get(int(code), f"사유코드{code}")
        except (TypeError, ValueError):
            label = str(code)
        # 코드가 '기타'인데 상세 문구가 따로 오면 "기타 · 재고부족(품절)" 처럼 겹친다.
        # 실제 사유는 상세 문구 쪽이므로 '기타'는 생략한다(라이브 실측으로 확인).
        if not (label == "기타" and detail):
            parts.append(label)
    if detail:
        parts.append(detail)
    return " · ".join(parts)


def _esm_claim_status_ko(od: dict) -> str:
    """클레임 행의 주문상태 문구."""
    kind = od.get("_claim_kind")
    if kind == "uncollected":
        return "미수령신고"
    if kind == "pre_order":
        return "입금확인중"
    table = _ESM_CLAIM_KO.get(kind) or {}
    raw = od.get(_ESM_CLAIM_STATUS_FIELD.get(kind, ""))
    try:
        return table.get(int(raw), "") or (str(raw) if raw not in (None, "") else "")
    except (TypeError, ValueError):
        return str(raw or "")


def _esm_all_orders(market, since, until, *, client, diag=None):
    """주문조회 + 주문조회가 안 주는 것 전부(입금확인중·취소·반품·교환·미수령).

    ★ 왜 필요한가 — RequestOrders 는 "클레임(취소, 반품, 교환, 미수령신고) 주문은
      조회되지 않습니다"(공식문서). 이걸 안 붙이면 옥션·G마켓만 취소·반품이 통째로
      빠진 채 집계돼, 취소·반품이 잡히는 다른 4개 마켓과 기준이 어긋난다.

    ★ 클레임 응답에는 상품명·판매가·수량이 아예 없다(주문번호와 상태뿐).
      공식문서가 "주문번호로 조회하는 경우 제한 없습니다"라고 하므로, 주문번호로
      상세를 다시 불러 합친다. 상세를 못 얻으면 그 행은 빈칸으로 두되 **버리지 않는다**
      (클레임 주문이 존재한다는 사실 자체가 정보다 — 조용한 누락 금지).

    ★ 클레임은 '클레임 신청일' 기준 조회다. 기간 안에 주문됐다가 나중에 취소되면
      [since, until] 밖이라 통째 누락된다 → 조회 끝을 now 로 넓힌다(롯데온과 같은 처리).
    """
    import logging as _lg
    from shared.platforms.esm import claims as _clm
    from shared.platforms.esm.orders import (iter_orders, fetch_by_order_no,
                                             fill_from_product)

    log = _lg.getLogger(__name__)
    seen = set()
    # 조회별 건수·실패를 여기 남긴다. 검증 화면이 이걸 그대로 쓰므로 **다시 부를 필요가 없다**
    # (예전엔 진단이 클레임 4종을 재조회해 호출이 2배가 되고 42초 → 게이트웨이 502).
    if diag is None:
        diag = {}
    diag.setdefault("counts", {})
    diag.setdefault("errors", {})
    # 클레임 상세 보강 예산(호출 폭증 → 게이트웨이 502 방지). 리스트인 이유는
    # 제너레이터 안에서 감소시키기 위함. 상한을 넘으면 보강만 생략하고 주문은 유지.
    budget = [_ESM_DETAIL_BUDGET]
    pname_cache = {}                 # SiteGoodsNo → (상품명, 사유) 재조회 방지
    _n_order = 0
    for od in iter_orders(market, since, until, client=client):
        on = od.get("OrderNo")
        if on is not None:
            seen.add(on)
        _n_order += 1
        yield od
    diag["counts"]["주문조회"] = _n_order

    if since is None or until is None:
        # 기간 없이 부르는 경로(단위테스트 등)는 클레임을 합치지 않는다.
        # 클레임 조회는 기간이 필수라 없는 기간을 만들어낼 수 없다(추측 금지).
        return

    claim_until = _until_now(until)
    try:
        extra = list(_clm.iter_all(market, since, claim_until, client=client))
    except Exception as e:      # noqa: BLE001 — 클레임 조회 실패는 주문을 죽이지 않는다.
        log.warning("[%s] 클레임 조회 실패(주문은 유지): %s: %s", market, type(e).__name__, e)
        diag["errors"]["클레임조회"] = f"{type(e).__name__}: {e}"[:200]
        return

    _KIND_KO = {"pre_order": "입금확인중", "cancel": "취소", "return": "반품",
                "exchange": "교환", "uncollected": "미수령"}
    for od in extra:
        k = _KIND_KO.get(od.get("_claim_kind"))
        if k:
            diag["counts"][k] = diag["counts"].get(k, 0) + 1

    no_detail = 0
    for od in extra:
        on = od.get("OrderNo")
        if on is None or on in seen:
            continue
        seen.add(on)
        if od.get("_claim_kind") == "pre_order":
            # 입금확인중은 상세(상품명·금액)를 이미 주므로 재조회가 필요 없다.
            # 다만 상태 문구는 붙여야 한다 — 없으면 OrderStatus 매핑이 빈칸이 된다.
            od = dict(od)
            od["_claim_status_ko"] = "입금확인중"
            yield od
            continue
        # ★ 보강 호출 상한 — 클레임 1건마다 주문번호 조회 3모양 + 상품 API 2회가 붙는다.
        #   클레임이 많으면 호출이 폭증해 응답이 30초를 넘고 앞단 게이트웨이가 502 로 끊는다
        #   (라이브 실측). 상한을 넘으면 보강을 생략하되 **주문 자체는 그대로 내보낸다**
        #   — 상품명이 비는 것보다 주문이 사라지는 게 훨씬 위험하다.
        if budget[0] <= 0:
            merged = dict(od)
            merged["_detail_missing"] = "보강 생략(클레임이 많아 상한 초과)"
            merged["_claim_kind"] = od.get("_claim_kind")
            merged["_claim_status_ko"] = _esm_claim_status_ko(od)
            merged["_claim_reason_ko"] = _esm_claim_reason_ko(od)
            merged["_claim_date"] = (od.get("RequestDate") or od.get("ClaimDate")
                                     or od.get("CompleteDate") or "")
            yield merged
            continue
        budget[0] -= 1

        # ★ 클레임 건은 주문번호 조회를 건너뛴다.
        #   라이브에서 3회 확인했다 — 주문일+기간 / 주문번호만 / 결제일+기간 **세 모양 모두
        #   0건**. 공식문서도 "클레임 주문은 조회되지 않습니다"라고 못박는다.
        #   그런데 한 건당 3회를 던지느라 응답이 30초를 넘어 게이트웨이가 502 로 끊었다
        #   (사장님이 검증 버튼을 아예 못 누르는 상태). 안 되는 걸 계속 두드릴 이유가 없다.
        #   → 바로 상품 API 로 간다(호출 1/3). 마켓이 훗날 돌려주기 시작하면 이 조건만 푼다.
        if _ESM_CLAIM_ORDER_LOOKUP:
            try:
                detail, why = fetch_by_order_no(market, on, client=client,
                                                since=since, until=claim_until)
            except Exception as e:        # noqa: BLE001
                detail, why = None, f"{type(e).__name__}: {e}"
        else:
            detail, why = None, "클레임 주문은 주문조회로 상세가 오지 않음(문서·실측 확정)"
        if detail:
            merged = dict(detail)
            merged.update({k: v for k, v in od.items() if k.startswith("_")
                           or k in _ESM_CLAIM_STATUS_FIELD.values()})
        else:
            # 주문번호로 못 받았으면 상품번호로 이름만이라도 채운다.
            # 가격은 채우지 않는다 — 상품 API 는 '지금 판매가'라 주문 시점 금액이 아니다.
            merged = dict(od)
            sgn, gno = od.get("SiteGoodsNo"), od.get("GoodsNo")
            ckey = (gno, sgn)
            if ckey in pname_cache:                # 같은 상품 재조회 방지(호출 절약)
                name, why2 = pname_cache[ckey]
            else:
                name, why2 = fill_from_product(market, sgn, client=client, goods_no=gno)
                pname_cache[ckey] = (name, why2)
            if name:
                merged["GoodsName"] = name
                merged["_detail_partial"] = "상품명만 상품API로 채움(단가는 마켓 미제공)"
            else:
                no_detail += 1
                if no_detail == 1:        # 첫 실패 사유만 대표로 남긴다(로그 폭주 방지)
                    log.warning("[%s] 클레임 주문 %s 상세 실패: 주문번호=%s / 상품번호=%s",
                                market, on, why, why2)
                merged["_detail_missing"] = f"주문번호:{why or '-'} · 상품번호:{why2 or '-'}"
        merged["_claim_kind"] = od.get("_claim_kind")
        merged["_claim_status_ko"] = _esm_claim_status_ko(od)
        merged["_claim_reason_ko"] = _esm_claim_reason_ko(od)
        merged["_claim_date"] = (od.get("RequestDate") or od.get("ClaimDate")
                                 or od.get("CompleteDate") or "")
        yield merged

    if no_detail:
        log.warning("[%s] 클레임 %d건은 주문 상세를 못 받아 상품명·금액이 빈칸입니다.",
                    market, no_detail)


def esm_order_rows(market: str, since: _dt.datetime, until: _dt.datetime,
                   client=None, include_settlement: bool = True, diag=None) -> list:
    """옥션·G마켓(ESM 2.0) 주문조회 → 행(dict) 리스트. RequestOrders 응답 매핑.

    market = "auction" | "gmarket". 정산예정금액 = 판매대금 정산조회(getsettleorder)를 주문번호
    (OrderNo↔ContrNo)로 조인. 미정산(최근 주문)은 공란(폴백 금지, 스스·쿠팡과 동일 정직성).
    ⚠️ 라이브 미검증(키 입력 후 서버 검증 필요). 검증 전 SUPPORTED 미포함.
    """
    from shared.platforms.esm.orders import iter_orders
    label = {"auction": "옥션", "gmarket": "G마켓"}.get(market, market)
    rows = []
    for od in _esm_all_orders(market, since, until, client=client, diag=diag):
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
            # 클레임 행은 배송메시지 대신 클레임 사유를 넣는다(롯데온과 같은 규약).
            #  마켓 취소관리 화면의 「취소사유 / 상세취소사유」와 같은 정보다.
            "배송메시지": (od.get("_claim_reason_ko") or _g(od, "DelMemo")),
            "구매자": _g(od, "BuyerName"),
            "수령자전화번호": _g(od, "HpNo", "TelNo"),
            "구매자번호": _g(od, "BuyerId"),
            "쇼핑몰": label,
            "쇼핑몰ID": "",
            "단가": _g(od, "SalePrice", default=""),
            "배송비": _g(od, "ShippingFee", default=""),
            "정산예정금액": "",   # 아래 정산 조인으로 채움(미정산=공란)
            "_settle_source": "none",   # 아래 정산 조인 성공 시 real 로 승격
            # 클레임(취소·반품·교환·미수령)·입금확인중이면 그 상태를 쓴다.
            # 주문조회가 준 행은 _claim_status_ko 가 없으므로 기존 매핑 그대로.
            "주문상태": (od.get("_claim_status_ko")
                     or _status_ko("esm", _g(od, "OrderStatus"))),
            "주문상태원본": _g(od, "OrderStatus"),
            "오픈마켓주문번호": _g(od, "OrderNo"),
            # ── M4 가격 전후 표시용 상품 식별자(내부 전용 `_pd_`) ──
            #  공식문서(ESM 주문조회 RequestOrders 응답): SiteGoodsNo = '주문 G마켓 or 옥션
            #  상품번호' = 판매처 연동에 넣는 사이트 상품번호(market_fetch._fetch_esm 입력).
            #  GoodsNo 는 문서상 'null 로만 내려감'이라 쓰지 않는다.
            #  ★옵션 단위 id 는 담지 않는다 — 응답의 ItemOptionSelectList.ItemOptionCode 는
            #   '주문 옵션 코드'라고만 돼 있어, 우리가 옵션 식별자로 쓰는 판매자옵션코드
            #   (manageCode — esm/products.extract_options) 와 같은 값이라는 근거가 없다.
            "_pd_market_product_id": _g(od, "SiteGoodsNo"),
        })
        # ── 취소/반품/교환 = 상태변경(#2 CS) 태그 ──
        #  태그가 없으면 status_change_rows(=CS 반품·교환·취소)에 안 잡혀 CS 0건이 된다
        #  (스마트스토어·롯데온과 같은 규약).
        if od.get("_claim_kind") in ("cancel", "return", "exchange", "uncollected"):
            rows[-1]["_kind"] = "change"
            rows[-1]["_change_date"] = str(od.get("_claim_date") or "")
            # 상세(상품명·단가)를 못 받은 클레임 행은 사유를 달아둔다 — 검증 화면이 그대로 보여준다.
            if od.get("_detail_missing"):
                rows[-1]["_detail_missing"] = od["_detail_missing"]
            if od.get("_detail_partial"):
                rows[-1]["_detail_partial"] = od["_detail_partial"]

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


def _eleven11_fill_shipping_ordt(rows: list) -> list:
    """배송중(ordDt 미제공→ordNo[:8] 근사) 라인의 주문일을 같은 주문의 실주문일로 교정.

    11번가 배송중(shipping) 목록은 주문일(ordDt)을 안 줘 order 행이 ordNo 앞8자리로 근사한다
    (라이브 82/82 일치라 대개 정확하나, 부분발송처럼 같은 주문의 일부만 배송중이면 나머지 라인은
    실주문일을 갖는다). 같은 주문번호가 날짜목록(결제완료·배송준비중·배송완료 등)에도 있으면 그
    실주문일(ordDt)로 배송중 라인을 덮어 정밀화한다 — 실주문일 소스만 사용(폴백 아님).
    클레임행(_kind='change')은 주문일 공란 유지(의도)라 교정 대상 아님. 임시 출처 플래그는 제거.
    """
    ordt_by_no: dict = {}
    for r in rows:
        if r.get("_ordt_real") and r.get("주문일"):
            ordt_by_no.setdefault(str(r.get("오픈마켓주문번호") or ""), r["주문일"])
    for r in rows:
        if not r.get("_ordt_real") and r.get("_kind") != "change":
            real = ordt_by_no.get(str(r.get("오픈마켓주문번호") or ""))
            if real:
                r["주문일"] = real
        r.pop("_ordt_real", None)   # 임시 출처 플래그 제거(출력 누출 방지)
    return rows


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
    since, until = _ensure_kst(since), _ensure_kst(until)   # naive→KST(_until_now 비교 TypeError 방지)
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
        #   (라이브 82/82 ordNo[:8]=실주문일 일치라 근사는 정확하지만) 같은 주문의 날짜목록 라인이
        #   있으면 실주문일로 교정한다(부분발송 대비) → _ordt_real 로 출처 표시.
        ordno = str(_g11(od, "ordNo"))
        real_ordt = _g11(od, "ordDt")
        ord_dt = real_ordt or (ordno[:8] if ordno[:2] == "20" and len(ordno) >= 8 else "")
        return {
            "_ordt_real": bool(real_ordt),   # 주문일이 API ordDt 출처인가(아니면 ordNo[:8] 근사)
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
            # ── M4 가격 전후 표시용 식별자(내부 전용 `_pd_` — 엑셀·화면 열에 안 나감) ──
            #  prdStckNo = '주문상품옵션코드'(공식문서 11번가 주문 상태조회 응답, 필수 필드)이며
            #  판매처 연동이 옵션 식별자로 쓰는 그 재고번호와 같은 값이다
            #  (uploader/adapters/eleven11.py: market_option_id = prdStckNo,
            #   market_fetch._fetch_eleven11: option_id = prd_stck_no).
            #  prdNo = 11번가상품번호 = SetChannel.market_product_id.
            #  ★목록 조회(complete/{s}/{e}) 응답에 prdStckNo 가 실제로 실리는지는 라이브
            #   미검증이다. 없으면 빈값 → price_diff 가 상품 단위로 내려가고, 그것도 안 되면
            #   '확인 불가'로 남는다(조용히 엉뚱한 옵션에 붙지 않는다).
            "_pd_market_option_id": _g11(od, "prdStckNo"),
            "_pd_market_product_id": _g11(od, "prdNo"),
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
            # 클레임(취소·반품·교환) 목록은 공식문서상 prdNo 는 주지만 prdStckNo(옵션코드) 는
            #  목록에 없다 → 상품 단위만 보존(옵션은 옵션명으로 좁힌다). 없는 필드를 읽어
            #  조용히 None 이 되게 두지 않는다.
            "_pd_market_product_id": _g11(od, "prdNo"),
            "실결제금액": "",
            "송장입력": _g11(od, "twPrdInvcNo"),
            # 라인 식별자 — 클레임 응답에도 ordPrdSeq 가 실려 온다(2026-07-20 raw 실측).
            #  이게 없으면 다품목 주문의 부분취소 2건이 같은 키가 돼 한 건으로 접힌다.
            #  clmReqSeq(클레임 요청 seq)는 같은 라인의 재접수(반품요청→반품완료 등)를 가른다.
            "_send_ids": {"ord_no": ordno,
                          "ord_prd_seq": str(_g11(od, "ordPrdSeq") or ""),
                          "clm_req_seq": str(_g11(od, "clmReqSeq") or "")},
            "_kind": "change",
            "_change_date": str(_g11(od, "clmDt") or ""),   # 변경일 best-effort(#2용)
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

    # ── 11번가 정산금액(settlementList, 구매확정분) 있으면 최우선 = 오차0 ──
    if include_settlement:
        try:
            from shared.platforms.eleven11 import settlement as _el_settle
            smap = _el_settle.settlement_map(since, _until_now(until), client=client)
            for r in rows:
                # (주문번호, 주문순번) 라인 단위 매칭 — ordNo 만으로 매칭하면 다상품 주문의
                # ordNo 합계가 각 행에 브로드캐스트돼 N배 계상(라이브 실 XML 다ordPrdSeq 확인).
                ono = str(r.get("오픈마켓주문번호") or "")
                seq = str((r.get("_send_ids") or {}).get("ord_prd_seq") or "")
                v = smap.get((ono, seq))
                if v is not None:
                    r["정산예정금액"] = v
                    r["_settle_source"] = "real"
        except Exception:   # noqa: BLE001 — 조회 실패 시 기존 stlPlnAmt/추정 유지(폴백 아님)
            pass

    return _eleven11_fill_shipping_ordt(rows)


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


# 마켓별 '계정 동시 조회 수' **상한**.
#
# ★ 2026-07-20: 이 표는 상한일 뿐이고, **최종 판정은 판매처 데이터코드지도**가 한다
#   (:func:`lemouton.uploader.market_concurrency.must_be_sequential`).
#   지도에 「순차 필수」로 적힌 마켓은 여기 숫자가 몇이든 1 로 깎인다.
#
#   그동안 이 표가 지도와 어긋나 있었다 — 지도에 「계정 순차 조회 필수, 병렬 시
#   429 전체 다운」이라고 적힌 **11번가가 2로 병렬**이었다. 지도를 읽는 판정 함수는
#   이미 있었지만 화면 배지에만 쓰였고 실제 호출부는 이 표만 봤다.
#   → 표를 손대도 지도와 어긋날 수 없게 판정을 통과시킨다.
_ACCOUNT_WORKERS = {
    "smartstore": 1,
    "coupang": 2,
    "eleven11": 2,      # ← 지도가 「순차 필수」라 실제로는 1 로 깎인다
    "lotteon": 3,
    # 옥션·G마켓 — ESM 주문조회 5초/1회 제한은 **판매자 계정별**이다(2026-07-20 라이브 실측:
    # 다른 계정 3개를 1.5초 간격 연속 호출 → 3개 모두 성공 / 같은 계정 1.5초 재호출 → 실패).
    # 계정마다 제한 버킷이 따로라 계정 수만큼 병렬로 돌려도 초과가 나지 않는다.
    # 실제 동시 실행 수는 아래에서 min(값, 등록 계정 수) 로 잘린다.
    "auction": 3,
    "gmarket": 3,
}


def account_workers(market: str) -> int:
    """그 마켓에서 **동시에** 때려도 되는 계정 수.

    상한표(:data:`_ACCOUNT_WORKERS`)와 판매처 지도 중 **엄격한 쪽**을 쓴다.
    지도가 「순차 필수」라고 적었으면 상한이 몇이든 1 이다.

    ★ 지도를 못 읽어도(파일 손상 등) 상한표대로 돈다 — 조회가 멈추는 것보다 낫다.
      대신 지도에 적힌 마켓은 절대 병렬로 새지 않는다.
    """
    cap = int(_ACCOUNT_WORKERS.get(market, 1))
    try:
        from lemouton.uploader.market_concurrency import must_be_sequential
        if must_be_sequential(market):
            return 1
    except Exception:       # noqa: BLE001
        pass
    return max(1, cap)


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
    if market not in supported_markets():
        raise ValueError(f"'{market}' 주문 엑셀 미지원(UI) — 코드/키/검증 필요")
    if until is None:
        until = now or _dt.datetime.now(KST)
    if since is None:
        since = until - _dt.timedelta(days=days)
    # ★ tz 통일 — 빌더가 aware(KST) now 와 비교하므로 naive since/until 을 KST 로 강제.
    #   (라이브: 스마트스토어가 offset-naive/aware TypeError 로 통째 실패 → 매출 누락·마진 왜곡)
    since, until = _ensure_kst(since), _ensure_kst(until)

    def _rows_for(cli, alias):
        raw = _BUILDERS[market](since, until, client=cli,
                                include_settlement=include_settlement)
        # ★ line_uid 는 여기서 심는다 — _finalize_rows 가 _odseq·_shipkey 를 pop 하므로
        #   그 뒤에는 키 조각이 이미 사라진다(빌더 반환 직후·finalize 이전이 유일한 시점).
        _line_uid.stamp(market, raw)
        rs = _finalize_rows(raw)
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
    #   ★ 키는 line_uid(마켓이 주는 불변 식별자)를 쓴다. 예전엔 (주문번호,상품명,옵션)이었는데
    #     상품명은 바뀐다(마켓에서 수정·롯데온 언이스케이프·11번가 클레임행은 아예 공란) →
    #     바뀌면 중복이 안 걸려 같은 주문이 2배로 계상됐다. line_uid 를 못 만든 행만 옛 방식 폴백.
    _row_key = _line_uid.dedupe_key

    # ── 계정 조회 (속도) ──
    #  스마트스토어·11번가는 계정을 병렬로 때리면 429 로 **전체가** 죽는다(지도 기록).
    #  그 판정은 account_workers() 가 지도를 읽어서 한다 — 여기서 다시 정하지 않는다.
    #  ★병합은 항상 '등록 순서'로 한다 — 중복 판정(어느 계정을 남길지)이 실행마다 달라지면 안 됨.
    workers = min(account_workers(market), len(built))
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
    for _r in all_rows:
        _r.setdefault("_kind", "order")   # 클레임 빌더가 'change'로 override(후속 태스크)
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


def _window(since, until, days, now=None):
    """필터용 [lo, hi] date 튜플. since/until 우선, 없으면 최근 days일."""
    if since and until:
        return since.date(), until.date()
    now = now or _dt.datetime.now(KST)
    return (now - _dt.timedelta(days=days)).date(), now.date()


def new_order_rows(markets, days: int = 7, now=None, use_cache: bool = False,
                   since=None, until=None, include_settlement: bool = True,
                   warnings=None) -> list:
    """주문일 탭 전용 — 실주문일이 기간 안인 주문만.

    order 행은 항상 유지(취소완료여도 그날 들어온 주문이면 남김 = '상태 무관').
    change 행(취소/교환/반품 이벤트)은 실주문일이 기간 안일 때만 유지(롯데온 등),
    실주문일 공란/기간밖(쿠팡·11번가·옛주문)은 제외 → 기능 #2가 변경일 기준으로 잡는다.
    """
    rows = combined_order_rows(markets, days=days, now=now, use_cache=use_cache,
                               since=since, until=until,
                               include_settlement=include_settlement, warnings=warnings)
    lo, hi = _window(since, until, days, now)
    out = []
    for r in rows:
        if r.get("_kind") == "change":
            d = _row_order_date(r)               # 실주문일 파싱(공란/실패→None)
            if d is None or not (lo <= d <= hi):
                continue
        out.append(r)
    return out


def _change_date_of(r):
    """행의 '_change_date'(변경일)에서 날짜(date) 추출. 컴팩트(YYYYMMDD…)·ISO 모두."""
    m = _re.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", str(r.get("_change_date") or ""))
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


_ENRICH_BUYER_FIELDS = ("구매자", "수령자", "수령자전화번호", "구매자번호", "주소", "우편번호")


def _enrich_change_from_active(rows) -> None:
    """클레임(change) 행의 빈 구매자정보·상품명을, 같은 주문번호의 활성(order) 행에서 채운다.

    #3(구매자 정보) — 각 마켓 빌더가 이미 함께 받아온 '활성 주문'(수령자·전화·주소·상품명
    전부 있음)을 재사용한다. **새 API 호출 없음**(추가 조회 비용·실패 위험 0). 활성 목록에
    없는 주문(발주 전 취소 등)은 채우지 못하고 '정보 없음'으로 남는다(정직 — 폴백 금지).

    · 구매자 필드(이름·전화·주소·우편번호)는 주문번호만으로 안전(한 주문 내 동일).
    · 상품명은 여러 상품라인이면 어느 라인인지 모호 → 그 주문의 활성 상품명이 '한 종류'일
      때만 채운다(다품목 주문은 오채움 금지).
    """
    buyer_src, names = {}, {}
    for r in rows:
        if r.get("_kind") == "change":
            continue
        on = str(r.get("오픈마켓주문번호") or "")
        if not on:
            continue
        key = (r.get("판매처", ""), on)
        buyer_src.setdefault(key, r)
        nm = str(r.get("상품명") or "").strip()
        if nm:
            names.setdefault(key, set()).add(nm)
    for r in rows:
        if r.get("_kind") != "change":
            continue
        key = (r.get("판매처", ""), str(r.get("오픈마켓주문번호") or ""))
        src = buyer_src.get(key)
        if src:
            for f in _ENRICH_BUYER_FIELDS:
                if not str(r.get(f) or "").strip() and str(src.get(f) or "").strip():
                    r[f] = src[f]
        if not str(r.get("상품명") or "").strip():
            ns = names.get(key)
            if ns and len(ns) == 1:
                r["상품명"] = next(iter(ns))


def status_change_rows(markets, days: int = 7, now=None,
                       since=None, until=None, warnings=None) -> list:
    """상태변경(취소/교환/반품) 이벤트만 — 변경일(_change_date) 기준 수집.

    #1의 _kind='change' 태그 재사용. combined_order_rows는 주문일로 트리밍해 '옛 주문의
    이번 기간 변경'을 놓치므로, 여기선 _fetch_combined(트리밍 전)에서 change 행만 뽑아
    _change_date 로 트리밍한다.

    #3: 클레임 행의 구매자정보·상품명은 같은 주문번호의 활성 주문에서 채운다(추가 조회 없음).
    """
    rows = _fetch_combined(markets, days, now, since=since, until=until,
                           include_settlement=False, warnings=warnings)
    _enrich_change_from_active(rows)   # 활성 주문 → 클레임 빈칸 채움(구매자·상품명)
    if not (since and until):
        return [r for r in rows if r.get("_kind") == "change"]
    lo, hi = since.date(), until.date()
    out = []
    for r in rows:
        if r.get("_kind") != "change":
            continue
        d = _change_date_of(r)
        if d is not None and not (lo <= d <= hi):
            continue   # 변경일이 있고 창밖이면 제외 / 없으면(파싱실패) 보존(누락 방지, 스펙 §4.1)
        out.append(r)
    return out


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

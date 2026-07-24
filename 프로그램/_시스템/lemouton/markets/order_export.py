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
    "판매경로":     {"kind": "api",  "desc": "롯데온 유입경로 3상태 — 제휴(상품가 2% 수수료)/롯데ON(0)/미확인(재료 아직 못 받음)/확인 불가(재료는 있으나 판정 불가). 근거=크롤 판매경로 > 주문 chNo"},
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

# 롯데온 유입 채널번호(209 chNo) → 제휴/직영 — 2026-07-23 라이브 70건 전수 프로브 실측.
#  제휴 채널 주문은 판매가×2% 제휴수수료가 정산에서 추가 차감된다(샵마인 대조로 발견,
#  compute_settlement rate_affiliate). 여기 없는 새 chNo 는 상품별 이력 추정으로 폴백.
_LO_AFFILIATE_CHNOS = {"100065", "100071", "100077", "101148"}
_LO_DIRECT_CHNOS = {"100195", "101508", "100279", "101507", "101677", "100002", "100176"}


def _lo_learn_channels(rows):
    """같은 조회 안의 **크롤 확정분**에서 chNo → 제휴여부를 학습한다. {chNo: bool}.

    하드코딩 분류표(_LO_AFFILIATE_CHNOS/_LO_DIRECT_CHNOS)는 새 채널이 생기면 낡는다
    (2026-07-23 실측: 채널 100008 미등재 → '확인 불가' 3건). 판매자센터 크롤로 이미
    판매경로가 확정된 주문이 같은 채널에 있으면 그게 곧 정답이다.
    ★재료는 **크롤 확정분만** — 추정·chNo 판정분으로 다시 배우면 오류가 자기증식한다.
    ★같은 채널이 제휴·롯데ON 둘 다면 채널만으로 못 가르는 것 → 학습에서 제외.
    """
    seen: dict = {}
    for r in rows or []:
        if "크롤" not in str(r.get("_판매경로사유") or ""):
            continue
        route = str(r.get("판매경로") or "")
        if route not in ("제휴", "롯데ON"):
            continue
        ch = str(r.get("_lo_chno") or "").strip()
        if not ch:
            continue
        seen.setdefault(ch, set()).add(route == "제휴")
    return {ch: next(iter(v)) for ch, v in seen.items() if len(v) == 1}


def _lo_apply_learned_channels(rows, learned):
    """미확정(미확인·확인 불가) 행을 학습된 채널 매핑으로 승격. 확정 행은 안 건드림."""
    if not learned:
        return rows
    for r in rows or []:
        if str(r.get("판매경로") or "") not in ("미확인", "확인 불가"):
            continue
        ch = str(r.get("_lo_chno") or "").strip()
        if ch not in learned:
            continue
        aff = learned[ch]
        r["판매경로"] = "제휴" if aff else "롯데ON"
        r["_lo_is_affiliate"] = aff
        r["제휴수수료율"] = 2 if aff else 0
        r["_판매경로사유"] = (f"같은 조회에서 크롤로 확정된 같은 유입채널 {ch} 주문이 있어 "
                           + ("제휴" if aff else "롯데ON") + "로 판정")
    return rows


def _lo_affiliate_of(chnl=None, chno="", hist=None, detail=False):
    """롯데온 제휴 판별 — (제휴여부, 표시라벨[, 사유]).

    라벨 4종(사장님 요청 2026-07-23 — '아직 못 본 것'과 '봐도 없는 것'을 구분):
      · "제휴"      = 판별됨 + 제휴 경유(상품가 2% 수수료 부과)
      · "롯데ON"    = 판별됨 + 직영(수수료 0)
      · "미확인"    = 판별 재료를 **아직 못 받음**(크롤이 그 주문을 아직 안 담음)
      · "확인 불가" = 재료는 받았는데 **판정이 안 됨**(채널번호가 우리 분류표에 없음 등)

    ★근거 없이 '롯데ON'으로 단정하면 2%를 안 뗀 정산이 맞는 값처럼 보인다(조용한 단정).
     그래서 상품별 이력 추정(hist)은 **계산에만** 쓰고 라벨엔 안 쓴다.
    우선순위: ①크롤 판매경로(판매자센터 화면 확정) ②주문 응답 chNo(확정) ③이력(추정·표시 제외).
    detail=True 면 사유 문자열까지 — 화면이 마우스 올림 설명으로 보여준다.
    """
    def _out(aff, label, why):
        return (aff, label, why) if detail else (aff, label)

    if chnl is not None:
        is_aff = "제휴" in str(chnl)
        return _out(is_aff, "제휴" if is_aff else "롯데ON",
                    f"판매자센터 크롤의 판매경로 값 「{chnl}」로 확정")
    c = str(chno or "").strip()
    by_chno = _lo_channel_affiliate(c)
    if by_chno is not None:
        return _out(by_chno, "제휴" if by_chno else "롯데ON",
                    f"주문 데이터의 유입채널 {c} 로 확정"
                    + ("(제휴 채널)" if by_chno else "(롯데ON 직영 채널)"))
    if c:
        return _out(bool(hist), "확인 불가",
                    f"유입채널 {c} 를 받았지만 제휴/직영 분류표에 없는 채널입니다. "
                    "판매자센터에서 이 주문의 판매경로를 한 번 확인하면 이후 자동 판별됩니다.")
    return _out(bool(hist), "미확인",
                "유입채널을 아직 못 받았습니다(주문 API 가 취소건엔 채널을 안 줌). "
                "롯데온 자동 수집이 이 주문을 담으면 자동으로 확정됩니다.")


def _lo_channel_affiliate(chno):
    """롯데온 chNo → True(제휴)/False(직영)/None(미지 — 이력 추정으로 폴백)."""
    c = str(chno or "").strip()
    if c in _LO_AFFILIATE_CHNOS:
        return True
    if c in _LO_DIRECT_CHNOS:
        return False
    return None

# 마켓별 원시 상태코드 → 한글. 미매핑은 원값 그대로(추측 금지).
_STATUS_KO = {
    "smartstore": {"PAYMENT_WAITING": "결제대기", "PAYED": "결제완료", "DELIVERING": "배송중",
                   "DELIVERED": "배송완료", "PURCHASE_DECIDED": "구매확정",
                   "CANCELED": "취소완료", "RETURNED": "반품완료", "EXCHANGED": "교환완료",
                   "CANCEL_REQUEST": "취소요청", "RETURN_REQUEST": "반품요청",
                   "EXCHANGE_REQUEST": "교환요청",
                   # 미결제 자동취소 — 영문 원코드가 그대로 노출되면 zero_cancel('취소완료'
                   # 포함 검사)이 안 걸려 정산이 추정으로 날조된다(2026-07-23 실측 913547351).
                   "CANCELED_BY_NOPAYMENT": "취소완료(미결제)"},
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


def is_invoice_no(v) -> str:
    """송장번호로 볼 수 있는 값만 돌려준다(아니면 '').

    ★대조 자료의 '송장' 열이 **번호가 아니라 상태**를 적는 경우가 있다 — 샵마인은
      '송장입력됨'이라고 쓴다(2026-07-23 라이브 실측: 쿠팡 4건·11번가 1건이 화면 번호
      칸에 이 문구로 떴다). 문구가 번호 칸에 앉으면 ①사장님이 번호를 못 보고
      ②송장 원장(invoice_ledger)에 가짜 송장으로 저장되며 ③다품 주문 라인 매칭
      (_mango_fill 의 송장 대조)까지 어긋난다.
    판정: 한글이 섞였거나 숫자가 하나도 없으면 송장번호가 아니다(해외 택배의 영문+숫자는 통과).
    """
    s = str(v or "").strip()
    if not s or _re.search(r"[가-힣]", s) or not any(ch.isdigit() for ch in s):
        return ""
    return s


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
                       client=None, include_settlement: bool = True,
                       claims_only: bool = False, claim_to_now: bool = True,
                       orders_to_now: bool = True, od_no: str = None) -> list:
    """롯데온 출고/회수지시(주문정보) → 16컬럼 행(dict) 리스트.

    apiNo=209 SellerDeliveryOrdersSearch(하루 윈도우) 응답 deliveryOrderList 매핑.
    정산예정금액은 주문 API엔 없음(실결제 actualAmt 로 근사) — 정밀 정산은 정산 그룹 API 후속.

    claims_only=True + claim_to_now=False = **과거 클레임 백필 모드**(2026-07-22).
    확정 전 취소는 정산API(구매확정건만)에 안 나와 과거 취소 233건이 통째 빠졌다
    (샵마인 대사 실측). 이 모드는 209 를 안 돌고 클레임 3종만 창 안에서 걷는다.
    """
    import html as _html
    from shared.platforms.lotteon.orders import (iter_delivery_orders,
                                                 iter_delivery_orders_by_no)

    # ★ 209(출고/회수지시)는 '배송지시생성일시' 기준 조회다. 기간 안(주문일) 주문이라도
    #   배송지시가 나중에(예: 07-12 주문 → 07-13 지시생성) 잡히면 [since,until] 창 밖이라
    #   통째 누락된다(라이브: 07-12 신규주문 6건, 서버 프로브 확인). 조회 끝을 now 로 넓히고
    #   combined_order_rows 가 주문일 기준으로 다시 트리밍(기간=주문일 유지).
    # orders_to_now=False = **과거 209 백필 모드**(2026-07-22 샵마인 전열 대조): 창 안(지시
    #   생성일)만 조회한다. now 확장을 켜면 back=90 창이 90일치를 하루씩 전부 스캔한다
    #   (백필 스캔범위 폭발 — 과거이력 2026-07-21 교훈). 호출부가 창을 이어 붙여 전체를 덮는다.
    _lo_fetch_until = _until_now(until) if orders_to_now else until
    # od_no = 주문번호 단건 조회(209 는 「기간 또는 odNo」를 받는다). 창 조회가 못 준
    #  주문(정산 백필로만 들어와 상품명·단가가 빈 행 등)의 정밀 복구 통로.
    #  ★ 반드시 전용 이터레이터로 — 기간 순회에 od_no 를 얹으면 하루씩 쪼개 365회를
    #    호출한다(2026-07-24 라이브 504 실측).
    def _lo_source():
        if claims_only:
            return []
        if od_no:
            return iter_delivery_orders_by_no(od_no, client=client,
                                              since=since, until=_lo_fetch_until)
        return iter_delivery_orders(since, _lo_fetch_until, client=client)

    rows = []
    for od in _lo_source():
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
            "_lo_chno": _g(od, "chNo", default=""),                # 유입 채널(제휴 판별 실데이터)
            # 상품 단위 식별자 공용 키 — 샵마인 '오픈마켓상품번호' 대조·M4 표시용(spdNo 동일값).
            "_pd_market_product_id": _g(od, "spdNo", default=""),
            "실결제금액": _g(od, "actualAmt", default=""),   # 실결제(정산예상은 주문API 없음→수수료 공란)
            # 롯데온 단품(sitm)=옵션 단위 상품이라 단가에 옵션가 포함 → 추가금 구조적 0.
            "옵션추가금": 0,
            # 송장은 출고지시(209) 응답에 **없다** — 진행단계(140)의 invcNo 가 정본.
            #   옛 코드가 여기서 invNo·dvInvNo 를 찾아 154행 전부 공란이었다(2026-07-10).
            "송장입력": "",
        })

    # ★ odNo 단건 복구는 여기서 끝 — 목적은 **그 주문행의 상품·금액을 채우는 것**이고,
    #   클레임은 창 조회가 이미 적재한다. 아래 병합은 취소·반품·교환 3종을 기간만큼
    #   하루씩 훑어서, 1년 창이면 1,000회가 넘는다(2026-07-24 라이브 504 2차 원인).
    #
    #   🔴 단, **추가 호출이 없는 정리 단계는 반드시 통과시킨다.** 처음엔 여기서 그냥
    #   반환했다가 `_reclassify_lotteon_returns` 를 건너뛰어, 209 가 회수지시로 준 행이
    #   order 로 남아 같은 line_uid 가 order·claim 두 행이 됐다(라이브 실측 3건).
    #   그 함수는 순수 변환이다 — 마켓을 부르지 않으므로 504 와 무관하다.
    if od_no:
        return _reclassify_lotteon_returns(rows)

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
            "옵션추가금": 0,        # 단품=옵션 단위라 구조적 0(활성 행과 동일)
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
    #   백필(claim_to_now=False)은 창 안만 — 창마다 to-now 스캔이 붙으면 과거 창일수록 느려진다.
    _lo_claim_until = _until_now(until) if claim_to_now else until
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
            if claims_only:
                # 백필 모드에선 클레임이 전부다 — 삼키면 그 창이 조용히 빈다.
                # 창 실패로 전파해 백필 러너가 에러로 적고 재시도할 수 있게 한다.
                raise
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
        """제휴 여부 — ①크롤 판매경로(확정) ②주문 자체 chNo(확정) ③상품별 이력(추정).

        ②는 209 응답의 유입 채널번호 — 2026-07-23 라이브 70건 전수 프로브로 확정:
        제휴(2% 부과) 채널 = 100065(네이버 등)·100071·100077·101148 / 직영 = 100195·
        101508·100279·101507·101677·100002·100176. 이력 추정만 쓰던 때는 제휴 40건
        미포착(+2%)·직영 1건 오포착(−2%, 218651206=100195)이 실측됐다. 미지의 chNo
        만 ③으로 떨어진다.
        """
        key = (str(r.get("오픈마켓주문번호") or ""), str(r.get("_odseq") or "1"))
        aff, label, why = _lo_affiliate_of(
            chnl=chnlmap.get(key),
            chno=r.get("_lo_chno"),
            hist=aff_by_spd.get(str(r.get("_lo_spdno") or ""), False),
            detail=True)
        r["_판매경로사유"] = why          # 화면 마우스 올림 설명(내부 키 — 엑셀 열 아님)
        return aff, label

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

    # ── 샵마인 M열 정합(2026-07-23 대조 실측: +배송비 차이 55건) ──
    #  롯데온 지급액(실·추정 모두)은 배송비를 포함한다 — K열(정산예정금액)은 상품분
    #  (−배송비)으로 표기하고, '배송비포함' 열은 _finalize 가 +고객배송비로 N열 정합.
    #  배송비는 주문당 1회만 뺀다(다품 라인 과차감 방지 — _finalize _shipkey 규약 동일).
    _lo_ship_done = set()
    for r in rows:
        if r.get("_kind") == "change":
            continue
        st = _to_int(r.get("정산예정금액"))
        ship = _to_int(r.get("_lo_dvcst"), 0) or 0
        odno = str(r.get("오픈마켓주문번호") or "")
        if st is not None and ship and odno and odno not in _lo_ship_done:
            r["정산예정금액"] = st - ship
            _lo_ship_done.add(odno)

    # 회수·반품·취소 진행상태(209 경로)는 주문일이 회수지시 시각으로 오염됨 →
    #   실주문일 복원 + change 재분류(옛 주문이 '오늘 신규주문'에 새는 것 방지).
    rows = _reclassify_lotteon_returns(rows)
    # 클레임 행의 구매자·수령자·주소·실결제 공란을 저장분에서 채움(라이브 감사 73/76건).
    try:
        fill_claim_blanks_from_history(rows, "lotteon")
    except Exception:   # noqa: BLE001 — 이력 채움 실패는 빈칸 유지(주문은 살림)
        pass
    # 부분취소의 취소 라인은 OpenAPI 가 안 준다(018057538 실측: 수취완료 라인만) —
    # 셀러오피스 크롤분(lotteon_so_orders)에서 누락 취소 라인을 복원해 붙인다.
    try:
        from shared import db as _db2
        if not getattr(_db2, "_is_sqlite", False):   # 폴백 SQLite = 테스트 오염 방지
            from lemouton.markets import lotteon_so as _lo_so2
            _s2 = _db2.SessionLocal()
            try:
                rows = _lo_so2.add_missing_claims(rows, _s2)
            finally:
                _s2.close()
    except Exception:   # noqa: BLE001 — 부가 소스(테이블 없어도 무해)
        pass
    # 채널 자동 학습 — 같은 조회의 크롤 확정분으로 미확정(미확인·확인 불가) 승격.
    #  하드코딩 분류표가 새 채널을 못 따라가 생기는 '확인 불가'를 스스로 지운다.
    try:
        _lo_apply_learned_channels(rows, _lo_learn_channels(rows))
    except Exception:   # noqa: BLE001 — 학습 실패는 라벨만 미확정 유지(무해)
        pass
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
                    # 배송비 = 기본(shippingPrice) + 도서산간 추가(remotePrice) — 라이브
                    #  프로브 실측(2026-07-23, 6101762660613: shipping 0 + remote 5,000,
                    #  remoteArea=True). remotePrice 를 안 더하면 L·N열이 통째 누락된다.
                    ship = _won(box.get("shippingPrice"))
                    _remote = _won(box.get("remotePrice"))
                    if isinstance(_remote, int) and _remote:
                        ship = (ship if isinstance(ship, int) else 0) + _remote
                    # 실결제 = orderPrice(결제가격) **그대로** — 샵마인 규약(2026-07-23
                    # 사장님 확정: 샵마인 K열=할인 차감 전 결제가). orderPrice 없으면 빈칸.
                    _paid = _won(it.get("orderPrice"))
                    # 판매자부담할인(즉시+다운로드쿠폰) — 정산 추정 시 매출에서 차감.
                    #  쿠팡지원할인(coupangDiscount)은 쿠팡이 보전하므로 차감 금지.
                    _sdc_a = _won(it.get("instantCouponDiscount"))
                    _sdc_b = _won(it.get("downloadableCouponDiscount"))
                    _sdc = ((_sdc_a if isinstance(_sdc_a, int) else 0)
                            + (_sdc_b if isinstance(_sdc_b, int) else 0))
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
                        "실결제금액": _paid if isinstance(_paid, int) else "",
                        # 쿠팡 vendorItem=옵션 단위 상품 — 단가에 옵션가 포함 → 추가금 구조적 0.
                        "옵션추가금": 0,
                        "_cp_seller_dc": _sdc,   # 정산 추정용(내부) — 판매자부담할인
                        "정산예정금액": "",
                        "주문상태": _status_ko("coupang", box.get("status") or st),
                        "주문상태원본": box.get("status") or st,
                        "오픈마켓주문번호": box.get("orderId") or "",
                        "송장입력": it.get("invoiceNumber") or box.get("invoiceNumber") or "",
                        # 상품 단위 식별자 — ordersheet orderItems[].sellerProductId(지도 예시 실물
                        # 확인 2026-07-22). 없으면 샵마인 '오픈마켓상품번호' 대조가 전량 공란이었다.
                        "_pd_market_product_id": str(it.get("sellerProductId") or ""),
                        # 쿠팡 노출용 상품번호(productId) — 샵마인 '오픈마켓상품번호'는 이 값이다
                        # (2026-07-23 재대조 실측: 샵 92억대=productId ≠ sellerProductId 159억대).
                        # 스스의 main/alt 이중 보존과 동형.
                        "_pd_market_product_id_alt": str(it.get("productId") or ""),
                    })

    # 정산예정금액(M열) = 상품 정산(item_settle)만 — 배송비는 N열(_finalize)이 M+고객배송비로.
    #  revenue-history 조회는 위 스레드풀에서 주문·클레임과 동시에 끝냈다(_settle_until=now 로 넓혀
    #  조회 — 정산 인식일 기준이라 주문 기간 뒤 인식분까지 포함). 아래는 그 결과 적용(인메모리).
    for r in rows:
        # vid 도 oid 처럼 str 정규화(양쪽 대칭). ordersheets(문자열)↔revenue-history(정수)
        # vendorItemId 타입 불일치로 (oid,vid) 튜플키가 전량 미스→estimated 폴백하던 버그 수정.
        oid, vid = str(r.pop("_oid", "")), str(r.pop("_vid", "") or "")
        # M4 가격 전후 표시 — vendorItemId 는 이 주문이 우리 어느 옵션(SKU)인지 아는
        #  유일한 열쇠다(SetChannelOption.market_option_id 와 같은 값). 정산 조인 후
        #  버려지면 주문↔소싱처를 연결할 방법이 사라져 전 행이 '확인 불가'가 된다.
        if vid:
            r["_pd_market_option_id"] = vid
        # ★M열 = 상품 정산만(2026-07-23 샵마인 45건 전수 실측: 샵 M=상품분, N=M+고객배송비
        #  **전액**). 배송비 정산(97%)을 M에 더하면 N열(_finalize 가 M+고객배송비로 계산)이
        #  이중 가산돼 +4,014 씩 어긋났다(3건 실측). 배송비 실정산액(deliv_settle)은 마진
        #  계산 등 다른 소비처가 없어 M에서 뺀 채 버려도 정보 손실은 N열 규약 안에서 흡수된다.
        actual = item_settle.get((oid, vid))
        if actual is not None:
            r["정산예정금액"] = actual
            r["_settle_source"] = "real"
        else:
            prod_est = _cp_estimate_settle(r.get("단가"), r.get("수량"), 0,
                                           seller_dc=r.get("_cp_seller_dc"))
            if prod_est == "":
                r["정산예정금액"] = ""
                r["_settle_source"] = "none"
            else:
                r["정산예정금액"] = prod_est
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
            "옵션추가금": 0,        # vendorItem=옵션 단위라 구조적 0(활성 행과 동일)
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
    # 클레임 행의 실주문일·실결제 + 배송완료 후 폐기된 안심번호를 저장분에서 채움.
    try:
        fill_claim_blanks_from_history(rows, "coupang",
                                       include_blank_contact_orders=True)
    except Exception:   # noqa: BLE001 — 이력 채움 실패는 빈칸 유지(주문은 살림)
        pass
    return rows


CP_FEE_FACTOR = 0.8845        # 1 - 0.1155 (쿠팡 상품 판매수수료 11.55%)
# (쿠팡 배송비 수수료 3% 상수는 M열=상품정산만 규약 전환(2026-07-23)으로 제거 —
#  N열 = M + 고객배송비 전액, 샵마인 45건 전수 실측.)


def _cp_estimate_settle(unit, qty, ship, seller_dc=0):
    """미정산 쿠팡 주문 정산예정금액 추정 (2026-07-21 사장님 확정 요율).

    = round((단가×수량 − 판매자부담할인) × 0.8845) + (배송비는 호출부에서 ×0.97 별도).
    판매자부담할인(즉시+다운로드쿠폰)은 정산 매출에서 빠진다 — 쿠팡지원할인은 쿠팡이
    보전하므로 차감하지 않는다. 단가 없으면 빈칸(폴백 0 금지). 확정액 아님(추정).
    """
    try:
        u = int(unit)
    except (TypeError, ValueError):
        return ""            # 단가 없음 → 추정 안 함
    q = int(qty) if str(qty).strip().isdigit() else 1
    s = int(ship) if str(ship).strip().lstrip("-").isdigit() else 0
    try:
        dc = int(seller_dc)
    except (TypeError, ValueError):
        dc = 0
    base = max(0, u * q - dc)
    return round((base + s) * CP_FEE_FACTOR)


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


def _esm_daystr(v):
    """다양한 형식의 날짜/일시에서 'YYYY-MM-DD' 만 뽑는다. 파싱 실패 시 ''.

    클레임 응답의 OrderDate 는 "2026-07-15T09:00:00" / "2026-07-15 09:00" 등으로 온다.
    since/until 은 datetime. 문자열 앞 10자만 비교하면 날짜 기준 판정에 충분하다.
    """
    if v is None or v == "":
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip().replace("T", " ")
    return s[:10] if len(s) >= 10 else ""


def _esm_claim_contact(row: dict, od: dict) -> None:
    """반품·교환 클레임 행의 구매자·수령자·주소 공란을 클레임 응답 자체로 채운다.

    데이터코드지도(esm:53 반품조회·esm:59 교환조회) 확정 필드:
      · PickupInfo > SenderInfo   = 수거지(발송인) — 반품 보내는 사람 = 구매자
      · ResendInfo > ReceiverInfo = 재발송 수령인 — 교환 재배송 목적지
    교환은 재발송 수령인이 곧 배송지라 우선, 반품은 수거지가 유일한 연락처다.
    빈 칸만 채운다(다른 소스가 먼저 채웠으면 유지).
    """
    def _d(obj, *path):
        for k in path:
            obj = obj.get(k) if isinstance(obj, dict) else None
        return obj if isinstance(obj, dict) else {}

    sender = _d(od, "PickupInfo", "SenderInfo")
    resend = _d(od, "ResendInfo", "ReceiverInfo")
    dest = resend if (resend.get("Name") or resend.get("Address")
                      or resend.get("AddressFront")) else sender

    def _addr(d):
        full = str(d.get("Address") or "").strip()
        if full:
            return full
        return (str(d.get("AddressFront") or "").strip() + " "
                + str(d.get("AddressBack") or "").strip()).strip()

    def _put(col, val):
        if val and not str(row.get(col) or "").strip():
            row[col] = val

    _put("수령자", str(dest.get("Name") or "").strip())
    _put("수령자전화번호", str(dest.get("HpNo") or dest.get("TelNo") or "").strip())
    _put("우편번호", str(dest.get("ZipCode") or "").strip())
    _put("주소", _addr(dest))
    _put("구매자", str(sender.get("Name") or "").strip())   # 발송인(수거지) = 구매자


def _esm_all_orders(market, since, until, *, client, diag=None, orders_only=False,
                    claims_only=False, claim_to_now=True):
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
    if not claims_only:
        for od in iter_orders(market, since, until, client=client):
            on = od.get("OrderNo")
            if on is not None:
                seen.add(on)
            _n_order += 1
            yield od
    diag["counts"]["주문조회"] = _n_order

    if since is None or until is None or orders_only:
        # 기간 없이 부르는 경로(단위테스트 등)·과거 백필(orders_only)은 클레임을 안 합친다.
        #  클레임 조회는 '신청일 기준'이라 _until_now(now)로 확장해야 하는데, 과거 백필에서
        #  그러면 창 하나가 (창시작~지금) 을 스캔해 느려진다(쿠팡·스스와 같은 문제).
        #  백필은 주문일 기준 주문만 모으면 되고, 클레임 상태는 증분/화면 조회가 최신으로 덮는다.
        return

    # 백필(claim_to_now=False)은 '지금까지' 확장 없이 창 안만 — 창마다 to-now 스캔이
    # 붙으면 과거 창일수록 느려진다(backfill-until-now-scan 사고와 같은 유형).
    claim_until = _until_now(until) if claim_to_now else until
    try:
        if claim_to_now:
            extra = list(_clm.iter_all(market, since, claim_until, client=client))
        else:
            # 입금확인중(pre_orders)은 '현재 상태' 조회라 과거 창에 의미가 없고,
            # 주문조회의 5초/1회 스로틀을 공유해 백필만 느려진다 — 뺀다.
            extra = []
            for _fn in (_clm.iter_cancels, _clm.iter_returns,
                        _clm.iter_exchanges, _clm.iter_uncollected):
                extra.extend(_fn(market, since, claim_until, client=client))
    except Exception as e:      # noqa: BLE001 — 클레임 조회 실패는 주문을 죽이지 않는다.
        log.warning("[%s] 클레임 조회 실패(주문은 유지): %s: %s", market, type(e).__name__, e)
        diag["errors"]["클레임조회"] = f"{type(e).__name__}: {e}"[:200]
        return

    # ★ 클레임도 '주문일 기준'으로 담는다 (2026-07-21 사장님 확정: 검증 기간은 "고객이
    #   실제로 발주한 날"이다. 취소일이 아니다). 클레임은 신청/완료일 기준으로 조회되므로
    #   주문일이 [since, until] 밖인 것이 섞여 온다 → 여기서 주문일로 걸러낸다.
    #   · 주문일 기간 안 → 나중에 취소돼도 포함
    #   · 주문일 기간 밖 → 최근 취소됐어도 제외(그 취소는 주문일 기준 다른 주에 속함)
    #   · OrderDate 를 못 받은 건(미수령 등)은 판정 불가 → 안전하게 포함(누락보다 낫다).
    _since_s = _esm_daystr(since)
    _until_s = _esm_daystr(until)

    def _in_order_window(od):
        d = _esm_daystr(od.get("OrderDate"))
        if not d:
            return True                      # 주문일 모름 → 버리지 않는다
        return _since_s <= d <= _until_s

    if claim_to_now:
        # 백필은 이 필터를 끈다 — 창 축이 클레임 신청·완료일이라, 주문일(창 밖) 필터를
        # 걸면 옛 주문의 클레임이 어느 창에서도 안 담긴다. 기간 판정은 load()가 한다.
        extra = [od for od in extra if _in_order_window(od)]

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
                   client=None, include_settlement: bool = True, diag=None,
                   orders_only: bool = False, claims_only: bool = False,
                   claim_to_now: bool = True) -> list:
    """옥션·G마켓(ESM 2.0) 주문조회 → 행(dict) 리스트. RequestOrders 응답 매핑.

    market = "auction" | "gmarket". 정산예정금액 = 판매대금 정산조회(getsettleorder)를 주문번호
    (OrderNo↔ContrNo)로 조인. 미정산(최근 주문)은 공란(폴백 금지, 스스·쿠팡과 동일 정직성).
    ⚠️ 라이브 미검증(키 입력 후 서버 검증 필요). 검증 전 SUPPORTED 미포함.
    """
    from shared.platforms.esm.orders import iter_orders
    label = {"auction": "옥션", "gmarket": "G마켓"}.get(market, market)
    rows = []
    for od in _esm_all_orders(market, since, until, client=client, diag=diag,
                              orders_only=orders_only, claims_only=claims_only,
                              claim_to_now=claim_to_now):
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
            # ★ESM 금액은 "99600.0000" 처럼 소수 표기로 온다 — 원문 그대로 두면 화면
            #  숫자 포맷터(숫자 아닌 문자 제거)가 소수점을 지워 **×10,000 으로 둔갑**한다
            #  (2026-07-23 사장님 화면 실측: 단가 996,000,000). 원천에서 정수 정규화.
            #  값이 없으면 빈칸 유지(0 대체 금지).
            "단가": (lambda v: "" if v is None else v)(_to_int(_g(od, "SalePrice"))),
            "배송비": (lambda v: "" if v is None else v)(_to_int(_g(od, "ShippingFee"))),
            # 옵션추가금 = OptSelPrice(옵션단가×수량) + OptAddPrice(추가구성단가×수량)
            #  — 지도 esm:67 확정 필드. 클레임 행(응답에 없음)은 빈칸 유지.
            "옵션추가금": ((_to_int(_g(od, "OptSelPrice"), 0) or 0)
                          + (_to_int(_g(od, "OptAddPrice"), 0) or 0)
                          if (od.get("OptSelPrice") is not None
                              or od.get("OptAddPrice") is not None
                              or od.get("_claim_kind") is None) else ""),
            # 실결제(K열) = 원금(단가×수량+옵션) — 샵마인 규약(2026-07-23 G마켓 13/13 전수:
            #  샵 K=단가×수량, 판매자 쿠폰 할인 전). 빌더에서 채워야 미정산 신규 주문도
            #  estimate_settle_from_history 가 돈다(실측 471551517: K 공란→추정 불발).
            #  _finalize_rows 의 ESM K=원금 규칙과 같은 값이라 이중 계산 아님.
            "실결제금액": ((lambda _u, _q: ("" if _u is None else _u * (_q or 1)))(
                _to_int(_g(od, "SalePrice")), _to_int(_g(od, "ContrAmount"), 1))
                if od.get("_claim_kind") is None else ""),
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
            # ★송장은 주문조회 응답이 **이미 준다** — NoSongjang(발송 송장번호)·
            #  TakbaeName(발송 택배사명), 데이터 코드 지도 esm:67 확정 필드.
            #  안 읽으면 발송된 주문이 화면에서 전부 '확인 불가'로 뜬다(2026-07-23 사장님
            #  화면 실측: G마켓 배송완료 줄 전부). 스스·롯데온 때와 같은 사고 —
            #  빈칸은 '없다'가 아니라 '안 봤다'였고, 그게 손입력 오기의 원인이다.
            #  클레임(반품·교환) 행은 주문조회로 오지 않으므로 클레임 응답의 원배송 송장
            #  (ShippingInfo.InvoiceNo — 지도 esm:53 반품·esm:59 교환)을 쓴다.
            #  둘 다 없으면 빈칸 유지 → _finalize_rows 가 '송장미입력/확인 불가'로 구분 표기.
            "송장입력": _g(od, "NoSongjang", "ShippingInfo.InvoiceNo"),
            # 화면 열은 아니지만 송장 원장(invoice_ledger)이 택배사를 여기서 읽는다.
            "택배사": _g(od, "TakbaeName"),
        })
        # ── 취소/반품/교환 = 상태변경(#2 CS) 태그 ──
        #  태그가 없으면 status_change_rows(=CS 반품·교환·취소)에 안 잡혀 CS 0건이 된다
        #  (스마트스토어·롯데온과 같은 규약).
        if od.get("_claim_kind") in ("cancel", "return", "exchange", "uncollected"):
            rows[-1]["_kind"] = "change"
            rows[-1]["_change_date"] = str(od.get("_claim_date") or "")
            # 반품·교환은 클레임 응답이 수거지/재발송 연락처를 준다(지도 esm:53·59).
            if od.get("_claim_kind") in ("return", "exchange"):
                _esm_claim_contact(rows[-1], od)
            # 상세(상품명·단가)를 못 받은 클레임 행은 사유를 달아둔다 — 검증 화면이 그대로 보여준다.
            if od.get("_detail_missing"):
                rows[-1]["_detail_missing"] = od["_detail_missing"]
            if od.get("_detail_partial"):
                rows[-1]["_detail_partial"] = od["_detail_partial"]

    # 정산예정금액 = 판매대금 정산조회(getsettleorder) SettlementPrice 를 ContrNo(=OrderNo)로 조인.
    #  미정산(최근 주문)은 맵에 없어 공란(폴백 금지). 정산 API 실패는 조용히 공란(주문은 살림).
    #  ★ 정산 응답은 단가·수량·구매자실결제도 준다 → 클레임(취소·반품)처럼 주문조회로 이 값이
    #    안 오는 빈 칸을 **주문 시점 정산 실값**으로 채운다(같은 조회 1회, 추가 호출 없음).
    #    빈 칸만 채운다 — 주문조회가 준 정상 주문 값은 절대 덮지 않는다.
    try:
        from shared.platforms.esm.settlements import settle_detail_map
        srch = (getattr(client, "_cfg", {}) or {}).get("settle_srch_type", "D1") if client else "D1"
        smap = settle_detail_map(market, since, until, client=client, srch_type=srch)
    except Exception:   # noqa: BLE001 — 정산 조회 실패는 정산액만 공란(주문 데이터는 유지)
        smap = {}
    for r in rows:
        ono = r.pop("_ono", "")
        ent = smap.get(ono)
        if not ent:
            continue
        if ent.get("정산예정금액") is not None:
            r["정산예정금액"] = ent["정산예정금액"]
            r["_settle_source"] = "real"
        # 빈 칸을 정산 실값으로 채움(주문 시점 금액 — 폴백 아님). 단가·수량이 채워지면
        # _finalize_rows 가 상품금액·주문금액까지 자동 계산한다.
        for col in ("단가", "수량", "실결제금액"):
            if ent.get(col) is not None and not str(r.get(col) or "").strip():
                r[col] = ent[col]
                r["_settle_filled"] = (r.get("_settle_filled") or "") + col + " "

    # 남은 빈칸(상품명·옵션·구매자 등)은 「주문 들어왔던 내역」에서 채운다(사장님 지시).
    #  마켓이 안 주는 건(삭제된 상품 등) 우리 저장분·등록DB가 마지막 실데이터 소스다.
    #  실패해도 주문은 그대로 내보낸다(이력 채움은 부가 — 조회를 죽이지 않는다).
    try:
        fill_claim_blanks_from_history(rows, market)
    except Exception:   # noqa: BLE001
        pass
    # 미정산(당일 주문 등)은 과거 실효 수수료율로 역산 추정(estimated 표식).
    try:
        estimate_settle_from_history(rows, market)
    except Exception:   # noqa: BLE001
        pass
    return rows


# 클레임 이력 채움 대상 열 — **빈 칸만** 채운다. 주문상태·배송메시지(클레임 사유)·
# 내부(_) 키는 제외: 저장분의 '배송준비중'이 '취소완료'를 덮으면 클레임이 사라져 보인다.
_HISTORY_FILL_COLS = ("상품명", "옵션", "수량", "단가", "구매자", "구매자번호",
                      "수령자", "수령자전화번호", "주소", "우편번호", "배송비",
                      "실결제금액", "옵션추가금", "주문일")


def fill_claim_blanks_from_history(rows: list, market: str, *, session=None,
                                   include_blank_orders: bool = False,
                                   settle_from_store_for_orders: bool = False,
                                   include_blank_contact_orders: bool = False) -> list:
    """클레임(전마켓)·빈 정상행의 빈칸을 「주문 들어왔던 내역」으로 채운다.

    마켓 클레임 응답은 주문번호+상태뿐인 경우가 많고(ESM), 롯데온 클레임도 구매자·
    실결제를 안 준다(라이브 감사 73/76건). 상품이 삭제되면 상품 API 도 이름을 못 준다
    ("삭제된 상품 입니다" — 2026-07-21 라이브 실측). 남은 실데이터 소스를 뒤진다:
      ⓪ line_uid 정확 일치 — 다품 주문도 어느 라인인지 특정된다(최우선).
      ① 주문 적재분(market_order_lines) — 그 주문이 **활성일 때 실제로 잡힌 행 전체**
         (상품명·옵션·구매자·주소…). 오픈마켓주문번호로 조인(다품이면 특정 불가 → 건너뜀).
      ② 우리 등록 DB(set_channels→product_sets) — 그 사이트상품번호로 우리가 등록한
         구성 이름(상품명만). 우리가 만든 등록명이라 실데이터다.
    빈 칸만 채운다 — 정산·주문조회가 이미 준 값은 절대 덮지 않는다(날조 금지).
    대상 = 클레임(_kind=change) + (include_blank_orders 면) 상품명 빈 정상 행
    (11번가 배송중 목록처럼 목록 API 가 상세를 안 주는 마켓용).
    """
    targets = [r for r in rows if r.get("_kind") == "change"
               or (include_blank_orders and not str(r.get("상품명") or "").strip())
               or (settle_from_store_for_orders and r.get("_kind") != "change"
                   and not str(r.get("정산예정금액") or "").strip())
               # 배송완료 후 안심번호 폐기(쿠팡 등) — 활성 때 잡아둔 저장분이 유일 소스.
               or (include_blank_contact_orders and r.get("_kind") != "change"
                   and not str(r.get("수령자전화번호") or "").strip())]
    if not targets:
        return rows
    own = False
    if session is None:
        # ★ 폴백 SQLite(.env 없는 개발기·테스트)에서는 건너뛴다 — 다른 테스트가 남긴
        #   잔재 행을 읽어 값이 **비결정적으로** 채워질 수 있다(골든테스트 오염 위험).
        #   라이브·개발 모두 실DB(Supabase PG)라 이 가드는 실환경에 영향 없다.
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):
            return rows
        session = _db.SessionLocal()
        own = True
    try:
        from lemouton.markets.models_orders import MarketOrderLine

        # ⓪ line_uid 정확 일치(PK) — 다품 주문도 어느 라인인지 특정된다.
        uids = {str(r.get("_line_uid") or "").strip() for r in targets}
        uids.discard("")
        stored_by_uid: dict = {}
        if uids:
            for o in (session.query(MarketOrderLine)
                      .filter(MarketOrderLine.line_uid.in_(sorted(uids))).all()):
                stored_by_uid[o.line_uid] = dict(o.row or {})

        onos = {str(r.get("오픈마켓주문번호") or "").strip() for r in targets}
        onos.discard("")
        stored: dict = {}
        if onos:
            for o in (session.query(MarketOrderLine)
                      .filter(MarketOrderLine.market == market,
                              MarketOrderLine.order_no.in_(sorted(onos))).all()):
                # 같은 주문번호에 여러 라인이면 첫 행만(어느 상품인지 특정 불가 시 안 섞는다).
                if o.order_no in stored:
                    stored[o.order_no] = None      # 다품 주문 — 특정 불가로 표시
                else:
                    stored[o.order_no] = dict(o.row or {})

        pids = {str(r.get("_pd_market_product_id") or "").strip() for r in targets}
        pids.discard("")
        reg_names: dict = {}
        if pids:
            from lemouton.sets.models import ProductSet, SetChannel
            q = (session.query(SetChannel.market_product_id, ProductSet.name)
                 .join(ProductSet, ProductSet.id == SetChannel.set_id)
                 .filter(SetChannel.market == market,
                         SetChannel.market_product_id.in_(sorted(pids))))
            for pid, name in q.all():
                reg_names.setdefault(str(pid), name)

        # ③같은 조회창의 정상주문 행 — 같은 사이트상품번호면 같은 상품이라 이름이 같다.
        #   (실사례 F575628540: 삭제된 상품이라 상품API 실패, 같은 상품의 다른 주문이
        #    같은 창에 정상으로 잡혀 GoodsName 을 들고 있었다.) 추가 호출 0회.
        sibling_names: dict = {}
        for r in rows:
            if r.get("_kind") == "change":
                continue
            pid = str(r.get("_pd_market_product_id") or "").strip()
            nm = str(r.get("상품명") or "").strip()
            if pid and nm:
                sibling_names.setdefault(pid, nm)

        # ④저장분을 상품번호로도 뒤진다 — 주문번호가 달라도 같은 상품이면 이름은 같다.
        #   ESM 저장분은 마켓당 수십~수백 행이라 전량 스캔해도 가볍다.
        need_pids = {str(r.get("_pd_market_product_id") or "").strip() for r in targets
                     if not str(r.get("상품명") or "").strip()}
        need_pids.discard("")
        need_pids -= set(sibling_names)
        store_pid_names: dict = {}
        if need_pids:
            for o in (session.query(MarketOrderLine)
                      .filter(MarketOrderLine.market == market).all()):
                sr = o.row or {}
                pid = str(sr.get("_pd_market_product_id") or "").strip()
                nm = str(sr.get("상품명") or "").strip()
                if pid in need_pids and nm and pid not in store_pid_names:
                    store_pid_names[pid] = nm

        # 라인 단위 금액류 — 주문번호 채움(어느 라인인지 근사)일 때 옵션이 서로 다르면
        # 다른 옵션의 값이라 붙이면 날조다(2026-07-23 실측: 쿠팡 769047062 반품 클레임
        # 옵션 409567 에 저장분 436563 라인의 단가 39,000이 붙음 — 실제 39,900).
        _LINE_AMOUNT_COLS = {"단가", "실결제금액", "옵션추가금", "판매가", "수량"}

        def _opt_mismatch(a, b):
            a, b = str(a or "").strip(), str(b or "").strip()
            return bool(a) and bool(b) and a != b

        for r in targets:
            by_uid = stored_by_uid.get(str(r.get("_line_uid") or "").strip())
            src = by_uid or stored.get(str(r.get("오픈마켓주문번호") or "").strip())
            if src:
                # line_uid 정확 일치는 라인이 특정된 것 — 옵션 검사 불필요.
                skip_amounts = (by_uid is None
                                and _opt_mismatch(r.get("옵션"), src.get("옵션")))
                filled = []
                for col in _HISTORY_FILL_COLS:
                    if skip_amounts and col in _LINE_AMOUNT_COLS:
                        continue                    # 다른 옵션 라인의 금액 — 날조 금지
                    if str(r.get(col) or "").strip():
                        continue                    # 이미 있는 값은 안 덮는다
                    v = src.get(col)
                    if v in (None, ""):
                        continue
                    r[col] = v
                    filled.append(col)
                if filled:
                    r["_store_filled"] = " ".join(filled)
                # 정산예정액 물려받기 — **정상 행만**(11번가 배송중·배송완료: 결제완료 때
                # 마켓이 준 stlPlnAmt 가 저장분에 있다). 클레임은 정산이 취소·차감되므로
                # 활성 시절 예정액을 물려받으면 날조가 된다 — 제외.
                if (settle_from_store_for_orders and r.get("_kind") != "change"
                        and not str(r.get("정산예정금액") or "").strip()
                        and src.get("정산예정금액") not in (None, "")):
                    # 저장분 값 그대로 물려받는다. ⚠️구 저장분(_stl_net 표식 없음)은
                    # gross(stlPlnAmt 원값)·net(정산조인 후) 혼재라 배송비 보정을 **추측으로
                    # 가하면 안 된다**(2026-07-23 라이브 실측: 일괄 −배송비 보정이 net 저장분을
                    # 이중 차감시킴 — 085421439 31,117→28,117 오답). 새 저장분(_stl_net)은
                    # 이미 net 이라 그대로가 정답; 옛 gross 행 잔차는 새 스냅샷 적재가 해소.
                    r["정산예정금액"] = src["정산예정금액"]
                    r["_settle_source"] = "store"
            if not str(r.get("상품명") or "").strip():
                pid = str(r.get("_pd_market_product_id") or "").strip()
                if pid and pid in sibling_names:
                    r["상품명"] = sibling_names[pid]
                    r["_pdname_filled"] = "같은조회"
                elif pid and pid in store_pid_names:
                    r["상품명"] = store_pid_names[pid]
                    r["_pdname_filled"] = "저장분"
                else:
                    nm = reg_names.get(pid)
                    if nm:
                        r["상품명"] = nm
                        r["_regname_filled"] = "1"

        # ⑤ 더망고 업로드분(mango_orders) — 사장님이 올리는 전 마켓 주문 대조 자료.
        #   롯데온 취소 API 는 구매자 정보를 안 준다(2026-07-21 라이브 프로브로 확정:
        #   부모·아이템 어디에도 이름·주소·전화 필드 없음) — 더망고가 마지막 실데이터
        #   소스다(수령인·휴대폰·상품명·옵션 + raw 의 주소류 키).
        try:
            _mango_fill(session, targets)
        except Exception:   # noqa: BLE001 — 더망고는 부가 소스(테이블 없어도 무해)
            pass

        # ⑥ 샵마인 적재분 — 마켓 취소 API 가 안 주는 값을 샵마인이 취소 전에 받아뒀다
        #   (2026-07-22 사장님 제공 3개월치. 라이브 대조: 롯데온 공란 38건 중 24건 보유).
        try:
            _shopmine_fill(session, market, targets)
        except Exception:   # noqa: BLE001 — 부가 소스(테이블 없어도 무해)
            pass

        # ⑦ 롯데온 셀러오피스 크롤분 — 취소건 구매자·라인 금액 + 철회 잔존 교정.
        #   OpenAPI 전수 소진으로 확정된 유일 원천(2026-07-23, lotteon_so 모듈 참조).
        if market == "lotteon":
            try:
                from lemouton.markets import lotteon_so as _lo_so
                _lo_so.fill_from_so(session, targets)
            except Exception as _e:   # noqa: BLE001 — 부가 소스(테이블 없어도 무해)
                # ★조용한 실패 금지 — 중간에 터지면 그 뒤 행이 통째로 안 채워지는데
                #   화면엔 '원래 빈칸'처럼 보인다(2026-07-23 실제로 겪음). 사유를 데이터에
                #   남겨 화면·엑셀에서 바로 보이게 한다.
                import logging as _lg
                _lg.getLogger(__name__).exception("lotteon SO fill failed")
                if targets:
                    targets[0]["_so_error"] = f"{type(_e).__name__}: {_e}"[:200]
    finally:
        if own:
            session.close()
    return rows


def _shopmine_fill(session, market: str, targets: list) -> None:
    """샵마인 행으로 빈 구매자·수령자·전화·주소·상품·금액을 채운다(빈 칸만).

    연락처(구매자·수령자·전화·주소·우편)는 **주문 단위** 정보라 다품 주문이어도 안전.
    상품명·옵션·수량·단가·실결제는 **라인 단위** — 주문에 라인이 하나뿐이거나 상품명이
    일치할 때만 채운다(어느 상품인지 특정 못 하면 섞지 않는다 — 날조 금지).
    """
    from lemouton.markets.models_shopmine import ShopmineOrder

    need = [r for r in targets
            if not str(r.get("구매자") or "").strip()
            or not str(r.get("수령자") or "").strip()
            or not str(r.get("상품명") or "").strip()
            or not str(r.get("실결제금액") or "").strip()
            # 쿠팡 취소주문 실주문일 — 마켓 API 3경로 전부 구조적 미제공 실측(2026-07-23:
            # 단건=400 'cancelled or returned' 거부·목록=미노출·클레임=미제공).
            # 샵마인이 취소 전에 받아둔 주문일이 유일한 실데이터다.
            or not str(r.get("주문일") or "").strip()]
    if not need:
        return
    onos = {str(r.get("오픈마켓주문번호") or "").strip() for r in need}
    onos.discard("")
    if not onos:
        return
    sm: dict = {}
    for o in (session.query(ShopmineOrder)
              .filter(ShopmineOrder.market == market,
                      ShopmineOrder.order_no.in_(sorted(onos))).all()):
        sm.setdefault(o.order_no, []).append(o)

    for r in need:
        lines = sm.get(str(r.get("오픈마켓주문번호") or "").strip()) or []
        if not lines:
            continue
        first = lines[0]
        filled = []
        # 주문 단위(어느 라인이든 동일) — 다품이어도 안전.
        # 주문일도 주문 단위 — 샵마인 '26.04.22' → '2026-04-22' 정규화해 채운다.
        _odt = ""
        _m = _re.match(r"^(\d{2})\.(\d{2})\.(\d{2})$", str(first.ordered_at or "").strip())
        if _m:
            _odt = f"20{_m.group(1)}-{_m.group(2)}-{_m.group(3)}"
        for col, val in (("구매자", first.buyer), ("수령자", first.recipient),
                         ("수령자전화번호", first.phone),
                         ("구매자번호", first.buyer_phone),
                         ("우편번호", first.zipcode), ("주소", first.address),
                         ("주문일", _odt)):
            if val and not str(r.get(col) or "").strip():
                r[col] = val
                filled.append(col)
        # 라인 단위 — 단일 라인이거나 상품명이 일치할 때만.
        line = lines[0] if len(lines) == 1 else next(
            (x for x in lines
             if str(r.get("상품명") or "").strip()
             and str(x.product_name or "").strip() == str(r.get("상품명")).strip()),
            None)
        if line is not None:
            for col, val in (("상품명", line.product_name), ("옵션", line.option1),
                             ("수량", line.qty), ("단가", line.unit_price),
                             ("실결제금액", line.paid_amount),
                             # 샵마인 송장 열은 '송장입력됨' 같은 상태를 적기도 한다 →
                             # 진짜 번호일 때만 채운다(문구는 번호 칸에 넣지 않는다).
                             ("송장입력", is_invoice_no(line.invoice))):
                if val and not str(r.get(col) or "").strip():
                    r[col] = val
                    filled.append(col)
        if filled:
            r["_shopmine_filled"] = " ".join(filled)


def _mango_fill(session, targets: list) -> None:
    """더망고 행으로 빈 수령자·전화·상품명·옵션·주소를 채운다(빈 칸만).

    마켓명 불일치면 안 채운다 — 주문번호가 우연히 같은 남의 마켓 건을 섞으면 날조다.
    """
    from lemouton.delivery.models import MangoOrder

    need = [r for r in targets
            if not str(r.get("수령자") or "").strip()
            or not str(r.get("상품명") or "").strip()
            or not str(r.get("수령자전화번호") or "").strip()]
    if not need:
        return
    onos = {str(r.get("오픈마켓주문번호") or "").strip() for r in need}
    onos.discard("")
    if not onos:
        return
    mango: dict = {}
    for mo in (session.query(MangoOrder)
               .filter(MangoOrder.market_order_no.in_(sorted(onos))).all()):
        mango.setdefault(mo.market_order_no, []).append(mo)

    def _norm(s):
        return str(s or "").replace(" ", "").lower()

    for r in need:
        cands = mango.get(str(r.get("오픈마켓주문번호") or "").strip()) or []
        lbl = _norm(r.get("판매처"))
        # 마켓명 앞 2글자 상호 포함 매칭("롯데"↔"롯데온"/"롯데ON", "g마"↔"g마켓").
        hit = [m for m in cands if lbl and _norm(m.market_name)
               and (lbl[:2] in _norm(m.market_name) or _norm(m.market_name)[:2] in lbl)]
        if not hit:
            continue
        # 주문 단위(어느 라인이든 동일) — 다품이어도 안전.
        mo = hit[0]
        pairs = [("수령자", mo.recipient), ("수령자전화번호", mo.phone)]
        raw = mo.raw or {}
        if isinstance(raw, dict):
            addr = next((str(v).strip() for k, v in raw.items()
                         if "주소" in str(k) and str(v or "").strip()), "")
            if addr:
                pairs.append(("주소", addr))
        # 라인 단위(상품명·옵션) — 단일 라인이거나 **송장번호 일치** 라인만.
        #  실사례(2026-07-22): 11번가 다품 주문 — 배송중 목록은 송장만 주는데 더망고엔
        #  실제 송장번호가 있어 라인을 정확히 특정할 수 있다. 특정 못 하면 안 섞는다
        #  (예전엔 첫 라인을 임의로 붙여 다품에서 엉뚱한 상품명이 붙을 수 있었다).
        inv = str(r.get("송장입력") or "").strip()
        line = hit[0] if len(hit) == 1 else next(
            (m for m in hit if inv and str(m.invoice_no or "").strip() == inv), None)
        if line is not None:
            pairs += [("상품명", line.product_name), ("옵션", line.option1)]
        filled = []
        for col, val in pairs:
            if val and not str(r.get(col) or "").strip():
                r[col] = val
                filled.append(col)
        if filled:
            r["_mango_filled"] = " ".join(filled)


def estimate_settle_from_history(rows: list, market: str, *, session=None) -> list:
    """미정산 정상 행의 정산예정금액을 **과거 실효 수수료율**로 역산 추정한다.

    비율 = 실정산 ÷ 실결제 (저장분의 _settle_source='real' 행만 재료 — 추정으로 추정을
    만들면 오차가 복리로 는다). 이 실측 비율에는 카테고리 수수료·판매자부담할인·경유
    (제휴·가격비교) 수수료가 **전부 녹아 있다** — 요율표 조합보다 실제에 가깝다.
    같은 상품(_pd_market_product_id) 평균 우선, 없으면 마켓 전체 중앙값.
    대상 = 정상 행(_kind≠change)만 — 클레임 정산은 zero_cancel·실정산이 담당.
    결과는 _settle_source='estimated' 로 표식(실정산 나오면 다음 조회가 real 로 덮음).
    """
    esm = market in ("auction", "gmarket")

    def _rate_base(d):
        """비율 분모·추정 밑값 — ESM은 **원금(단가×수량)**: 저장분 실결제가 옛 규약
        (BuyerPayAmt=쿠폰 할인후)과 새 규약(K=원금)이 섞여 있어 실결제 기반 비율이
        오염된다(2026-07-23 G마켓 +3,041·+2,141 실측 — 샵마인 M=원금×0.87).
        단가×수량은 두 시절 모두 원금이라 안정적. 그 외 마켓은 실결제 기준 유지."""
        if esm:
            u = _to_int(d.get("단가"))
            q = _to_int(d.get("수량"), 1) or 1
            return u * q if u and u > 0 else None
        p = _to_int(d.get("실결제금액"))
        return p if p and p > 0 else None

    targets = [r for r in rows
               if r.get("_kind") != "change"
               and not str(r.get("정산예정금액") or "").strip()
               and _rate_base(r)]
    if not targets:
        return rows
    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):   # 폴백 SQLite = 테스트 잔재 오염 방지
            return rows
        session = _db.SessionLocal()
        own = True
    try:
        from lemouton.markets.models_orders import MarketOrderLine

        by_pid: dict = {}
        all_rates: list = []
        # 재료 = 최근 90일 실정산만 — 판매 구성(카테고리 수수료)이 바뀌면 옛 이력이
        # 비율을 오염시킨다(2026-07-23 G마켓 실측: 최근 실정산 13/13 = 0.87 인데
        # 1년치 저장분의 옛 카테고리(0.85) 다수가 최빈을 끌어감). order_date 는
        # 'YYYY-MM-DD…' 정규화 문자열이라 문자열 비교가 곧 시간 비교.
        _cut = (_dt.datetime.now(KST) - _dt.timedelta(days=90)).strftime("%Y-%m-%d")
        for o in (session.query(MarketOrderLine)
                  .filter(MarketOrderLine.market == market,
                          MarketOrderLine.order_date >= _cut).all()):
            sr = o.row or {}
            if sr.get("_settle_source") != "real" or sr.get("_kind") == "change":
                continue
            paid = _rate_base(sr)
            settle = _to_int(sr.get("정산예정금액"))
            if not paid or settle is None or settle <= 0:
                continue
            rate = settle / paid
            if not (0.5 <= rate <= 1.0):     # 비정상 비율(부분환불 등 섞임)은 재료에서 제외
                continue
            all_rates.append((rate, str(o.order_date or "")))
            pid = str(sr.get("_pd_market_product_id") or "").strip()
            if pid:
                by_pid.setdefault(pid, []).append(rate)

        if not all_rates:
            return rows
        import statistics as _st
        if esm:
            # ESM 계약율은 **카테고리별로 실제로 다르다**(2026-07-23 G마켓 저장분 실측:
            # 나이키·LEE 등 0.87=13% / 잔스포츠·아이더 0.85=15%). 시장 폴백은 '지금
            # 팔리는 구성'을 따라야 하므로 **최근 30일** 실정산의 0.5% 최빈 구간 평균
            # (동률이면 높은 쪽). 중앙값은 혼합 구성에서 이도저도 아닌 값이 된다.
            # 상품 자체 이력(by_pid)이 있으면 아래에서 그게 우선(카테고리 실율 정확).
            _cut30 = (_dt.datetime.now(KST) - _dt.timedelta(days=30)).strftime("%Y-%m-%d")
            _recent = [x for x, d0 in all_rates if d0 >= _cut30] or [x for x, _ in all_rates]
            _bins: dict = {}
            for x in _recent:
                _bins.setdefault(round(x * 200) / 200, []).append(x)
            _best = max(_bins.values(), key=lambda v: (len(v), sum(v) / len(v)))
            market_rate = sum(_best) / len(_best)
        else:
            market_rate = _st.median([x for x, _ in all_rates])
        for r in targets:
            pid = str(r.get("_pd_market_product_id") or "").strip()
            rates = by_pid.get(pid)
            # 상품 자체의 과거 실정산율이 최우선 — ESM 은 카테고리별 계약율(13%/15%)이
            # 달라 같은 상품의 실측 이력이 가장 정확하다. 이력 없는 신상품만 시장 폴백.
            rate = (sum(rates) / len(rates)) if rates else market_rate
            r["정산예정금액"] = round(_rate_base(r) * rate)
            r["_settle_source"] = "estimated"
    finally:
        if own:
            session.close()
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
                        include_settlement: bool = True, order_nos=None) -> list:
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
            # 배송키 — 묶음배송번호(bndlDlvSeq), 단 **'0'은 비묶음 기본값**이라 키로 쓰면
            #  서로 다른 주문 전부가 같은 키를 공유해 첫 행 빼고 배송비가 전부 소거된다
            #  (2026-07-23 라이브 실측: 배송준비중 23행 배송비 전멸 → L·N열 샵마인 불일치).
            "_shipkey": ("eleven11",
                         (lambda _b: _b if _b not in ("", "0") else "")(
                             str(_g11(od, "bndlDlvSeq"))) or _g11(od, "ordNo")),
            # 송장 전송용 식별자 — 발송처리(/rest/ordservices/reqdelivery)의 대상 단위는
            #   **배송번호(dlvNo)** 다(주문번호로 대체 불가). 부분발송용 ordPrdSeq 도 함께 보존.
            "_send_ids": {"ord_no": ordno,
                          "ord_prd_seq": str(_g11(od, "ordPrdSeq") or ""),
                          "dlv_no": str(_g11(od, "dlvNo") or "")},
            "주문일": ord_dt,
            "판매처": "11번가",
            "상품명": _g11(od, "prdNm"),
            "옵션": _g11(od, "slctPrdOptNm"),
            # ★ordQty 는 **잔여수량**(주문−취소−반품)이다 — 취소완료 주문을 단건 조회하면
            #   0 이 온다(2026-07-23 by-no 복구 실측 274건). 원주문 수량이 0일 수는 없으므로
            #   0 은 '미제공'으로 비워 저장한다(_merge_row 가 기존 실값 보존).
            "수량": ("" if str(_g11(od, "ordQty")).strip() in ("0", "")
                     else _g11(od, "ordQty")),
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
            # 우리 등록 파이프라인은 11번가 옵션가를 0으로 등록(optionAllAddPrc 0원
            # 설정) + 정산 optAmt 실측 전부 0(2026-07-22) → 구조적 0. 정산에 실값이
            # 오면 아래 정산 조인이 무조건 덮는다(실값 우선).
            "옵션추가금": 0,
            "배송비": ship,
            # 정산예정금액(M열) = stlPlnAmt − 배송비 — stlPlnAmt 는 배송비를 포함한다
            #  (라이브 프로브 실측 2026-07-23, 086650134: stlPlnAmt 32,913 = 샵마인 M
            #   29,913 + dlvCst 3,000). '배송비포함' 열은 _finalize 가 +배송비로 복원.
            #  구매확정 목록엔 stlPlnAmt 없어 공란. 실정산액은 settlementList 조인이 덮음.
            "정산예정금액": (lambda _sp, _sv: ("" if _sp is None else _sp - (_sv or 0)))(
                _to_int(_g11(od, "stlPlnAmt")), _to_int(ship, 0)),
            "_stl_net": True,   # M열=배송비 제외 규약으로 저장됨(구 저장분 상속 시 구분자)
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
            # 실결제 = ordPayAmt − 배송비 + (tmall 표기할인 − 적용할인) — 샵마인 K열 규약.
            #  ①배송비 제외(2026-07-23 대조 17건 실측). ②11번가 할인은 '표기'(tmallDscPrc)와
            #  '적용'(tmallApplyDscAmt)이 다를 수 있고 ordPayAmt 는 표기 기준 차감이라,
            #  샵마인 K(=ordAmt−적용할인)보다 그 차액만큼 작아진다(라이브 프로브 실측
            #  086884234: 28,100+300=28,400·086157090: 27,790+324=28,114 = 샵 정확 일치).
            #  ★차액은 **양·음 양방향** 이다 — 적용할인이 표기보다 큰 주문이 있고(2026-07-23
            #   재대조 7건 전부 −159 균일), 하한 0 을 두면 그만큼 K 가 과대해진다.
            #   적용할인 필드가 아예 없으면(배송완료 목록 등) 0(보정 안 함).
            "실결제금액": (lambda _pv, _sv, _gap: ("" if _pv is None
                                                   else _pv - (_sv or 0) + _gap))(
                _to_int(_g11(od, "ordPayAmt")),
                _to_int(_g11(od, "bmDlvCst") if _g11(od, "bndlDlvYN") == "Y"
                        else _g11(od, "dlvCst"), 0),
                ((_to_int(_g11(od, "tmallDscPrcPerSeq", "tmallDscPrc"), 0) or 0)
                 - (_to_int(_g11(od, "tmallApplyDscAmt"), 0) or 0)
                 if _g11(od, "tmallApplyDscAmt") not in ("", None) else 0)),
            "송장입력": _g11(od, "invcNo"),
            "발송처리일": _g11(od, "sndEndDt", "dlvEndDt"),   # 발송일(배송중)·배송완료일 → 경과시간용
            "주문상태원본": _g11(od, "ordPrdStat"),   # 11번가 상품주문상태코드 → API코드 칸(엔드포인트별 상태)
            # ── 할인 성분(내부 `_e11_`) — 샵마인 대조 재현식 확정용(2026-07-22).
            #  샵마인 '실결제'는 할인 차감 범위가 우리(ordPayAmt=전체 할인 차감)와 달라
            #  143건이 어긋났다. 성분을 보존해야 재현식(판매자할인만 차감 등)을 검증·계산
            #  할 수 있다. ordAmt=주문총액(할인 전), sellerDsc=판매자 할인, tmallDsc=11번가 할인.
            "_e11_ord_amt": _g11(od, "ordAmt"),
            "_e11_seller_dc": _g11(od, "lstSellerDscPrc", "sellerDscPrcPerSeq", "sellerDscPrc"),
            "_e11_tmall_dc": _g11(od, "lstTmallDscPrc", "tmallDscPrcPerSeq", "tmallDscPrc"),
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
            "단가": "", "옵션추가금": 0, "배송비": 0,
            "정산예정금액": "", "_settle_source": "none",
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
            # 변경일 — 지도 fields 확정(2026-07-21): 반품·교환 목록=reqDt(클레임 요청
            #  일시)·취소 목록=createDt. 예전의 clmDt 는 **존재하지 않는 필드**라 전부
            #  공란으로 쌓였다(727건 날짜불명 → 기간 필터 무력화). clmDt 는 혹시 몰라
            #  마지막 폴백으로만 남긴다.
            "_change_date": str(_g11(od, "reqDt", "createDt", "clmDt") or ""),
        }

    def _return_row(od, _status):
        """반품 목록 → 행. ordPrdStat A01=반품완료, 그 외(601 클레임진행중 등)=반품요청."""
        return _claim_row(od, "반품완료" if str(_g11(od, "ordPrdStat")) == "A01" else "반품요청")

    if order_nos:
        # ★ 주문번호 단건 정밀 복구(eleven11.110 + 115) — 상태별 창 조회 9경로가
        #   구조적으로 못 주는 주문(반품완료·구매확정 옛 건, 2026-07-22 샵마인 대사
        #   잔여 26건)의 통로. 창 조회는 안 돌고 단건만 부른다.
        from shared.platforms.eleven11.orders import fetch_order, fetch_order_status
        out = []
        for _no in order_nos:
            _ods = fetch_order(_no, client=client)
            _st = fetch_order_status(_no, client=client) if _ods else ""
            for _od in _ods:
                _r = _row(_od, _st or "")
                _r["_recovered_by_ordno"] = True
                out.append(_r)
        return out

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
            smap = _el_settle.settlement_detail_map(since, _until_now(until),
                                                    client=client)
            for r in rows:
                # (주문번호, 주문순번) 라인 단위 매칭 — ordNo 만으로 매칭하면 다상품 주문의
                # ordNo 합계가 각 행에 브로드캐스트돼 N배 계상(라이브 실 XML 다ordPrdSeq 확인).
                ono = str(r.get("오픈마켓주문번호") or "")
                seq = str((r.get("_send_ids") or {}).get("ord_prd_seq") or "")
                ent = smap.get((ono, seq))
                if ent is None:
                    continue
                # ★정산금액에서 배송비(dlvAmt)를 분리 — 샵마인 M열(배송비 제외)과 정합.
                #  '배송비포함' 열은 _finalize 가 +고객배송비로 만들어 N열과 정합
                #  (분리 안 하면 K열 +배송비 과대·L열 이중 가산 — 2026-07-23 대조 실측).
                r["정산예정금액"] = ent["정산금액"] - ent.get("배송비정산", 0)
                r["_settle_source"] = "real"
                # 옵션추가금 — 주문 목록 API 엔 필드가 없어(지도 전수조사) 정산 optAmt 가
                # 유일한 실값 소스. 기본 0(등록 파이프라인 옵션가 0 구조)을 실값이 덮는다.
                if "옵션추가금" in ent:
                    r["옵션추가금"] = ent["옵션추가금"]
        except Exception:   # noqa: BLE001 — 조회 실패 시 기존 stlPlnAmt/추정 유지(폴백 아님)
            pass

    rows = _eleven11_fill_shipping_ordt(rows)
    # 배송중 목록은 상품 상세를 안 준다(라이브 감사 8건 통째 공란) → 저장분에서 채움.
    #  클레임 행 + 상품명 빈 정상 행 모두 대상(include_blank_orders).
    #  정산예정액도 물려받는다(배송완료 조회는 stlPlnAmt 미제공 — 결제완료 저장분이 원본).
    try:
        # include_blank_contact_orders: 구매확정 목록은 상품명은 주고 단가·배송정보를
        # 안 준다(2026-07-22 엑셀 감사 실사례) — 연락처 빈 정상행도 대상에 넣는다.
        fill_claim_blanks_from_history(rows, "eleven11", include_blank_orders=True,
                                       settle_from_store_for_orders=True,
                                       include_blank_contact_orders=True)
    except Exception:   # noqa: BLE001 — 이력 채움 실패는 빈칸 유지(주문은 살림)
        pass
    # 그래도 빈 정산은 과거 실효 수수료율로 역산 추정(estimated 표식).
    try:
        estimate_settle_from_history(rows, "eleven11")
    except Exception:   # noqa: BLE001
        pass
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
        # ── 취소완료 = 거래 무산 → 정산·수수료 0 (2026-07-23 샵마인 규약으로 강화) ──
        #  '취소요청'은 철회될 수 있어 제외(미확정). 잔존 실정산·추정값이 있어도 0 으로
        #  통일한다 — 샵마인(정답지)이 취소건 정산을 항상 '없음'으로 표기(사장님 확정).
        zero_cancel = "취소완료" in str(r.get("주문상태") or "")
        if zero_cancel:
            settle = 0
            r["정산예정금액"] = 0
            r["_settle_source"] = "zero_cancel"
        # ── K열(실결제) = 원금(단가×수량+옵션) 으로 통일하는 경우 — 샵마인 규약 ──
        #  ① 취소완료(사장님 확정 2026-07-23) ② 취소요청·철회(616897117 실측: 샵 K=원금)
        #  ③ 쿠팡 반품완료(749312893 실측) ④ 옥션·G마켓 전체(13/13 전수: 샵 K=단가×수량,
        #    판매자 쿠폰 할인 전 — 할인 있던 12건 전부 이 차이였다. M열은 이미 일치).
        #  원금을 못 구하면(단가 공란) 기존 값 유지 — 날조 금지.
        _st = str(r.get("주문상태") or "")
        _mk = str(r.get("판매처") or "")
        force_orig = (zero_cancel or "취소요청" in _st or "철회" in _st
                      or (_mk == "쿠팡" and "반품완료" in _st)
                      or _mk in ("옥션", "G마켓"))
        if force_orig and isinstance(total, int) and total > 0:
            r["실결제금액"] = total
            paid = total
        # 마켓수수료: 빌더가 정산 API 실값으로 미리 채웠으면(롯데온 SettleCommission) 그대로 사용,
        #  아니면 실결제 − 정산예정금액 파생(둘 다 있고 양수일 때). 아니면 공란(폴백 금지).
        #  취소완료 0 확정 행은 파생 금지 — 실결제−0 이 수수료로 날조된다.
        preset_fee = _to_int(r.get("마켓수수료"))
        if zero_cancel:
            fee = None
            r["마켓수수료"] = 0
            r["수수료율"] = "0%"     # 취소 = 수수료 없음(공란이면 '모름'처럼 보인다)
        elif preset_fee is not None and preset_fee > 0:
            fee = preset_fee
        elif paid is not None and settle is not None and paid - settle > 0:
            fee = paid - settle
        else:
            fee = None
        if fee is not None:
            r["마켓수수료"] = fee
            r["수수료율"] = (f"{round(fee / total * 100, 2)}%"
                             if isinstance(total, int) and total > 0 else "")
        elif not zero_cancel:                # 취소완료 0 확정은 위에서 이미 채움
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
# 단일비행 — 같은 키의 실조회가 진행 중이면 새로 시작하지 않고 그 결과를 기다린다.
#  옥션·G마켓은 5초/1콜 제한으로 미리보기 1회가 ~60초 — 화면 자동 재시도·동시 탭이
#  같은 조회를 또 시작하면 호출 버킷을 두 배로 태워 더 느려진다(크롤큐 폴링 폭주와 동일 패턴).
_INFLIGHT: dict = {}                  # key -> threading.Event (완료·실패 시 set)
_INFLIGHT_WAIT = 300.0                # 초 — 이 이상 늘어진 빌더는 더 기다리지 않고 직접 조회

# ── L2 캐시(DB, 워커 간 공유) ──────────────────────────────────────────
# L1(_CACHE)은 프로세스 메모리라 gunicorn 워커 3개가 각자 캐시 → 같은 계정 주문을 최대
# 3번 재조회(ESM 5초 throttle 대기 3배). '다음 허용 시각' throttle 수정의 짝으로, 조회
# 결과를 DB 한 행에 담아 워커·프로세스가 공유한다. **화면 경로(warnings 있음)에만** 적용:
# 엑셀(전량 필요·warnings 없음)은 늘 실조회로 완전성을 보장한다. 어떤 실패든 조용히
# 건너뛰고 L1 만으로 현행 동작(절대 악화 없음).
_ORDER_CACHE_TABLE_READY = False
_ORDER_CACHE_TABLE_LOCK = _threading.Lock()


def _ensure_order_cache_table() -> None:
    global _ORDER_CACHE_TABLE_READY
    if _ORDER_CACHE_TABLE_READY:
        return
    with _ORDER_CACHE_TABLE_LOCK:
        if _ORDER_CACHE_TABLE_READY:
            return
        from shared.db import engine
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS order_rows_cache ("
                "cache_key TEXT PRIMARY KEY, "
                "cached_at_epoch DOUBLE PRECISION NOT NULL, "
                "payload TEXT NOT NULL)"))
        _ORDER_CACHE_TABLE_READY = True


def _l2_key(key: tuple) -> str:
    import json as _json
    return _json.dumps(key, ensure_ascii=False, default=str, sort_keys=True)


def _l2_get(key: tuple):
    """(rows, warnings) 또는 None. 만료·미존재·실패는 None(→ L1/실조회 폴백)."""
    try:
        _ensure_order_cache_table()
        import json as _json
        from shared.db import engine
        from sqlalchemy import text
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT cached_at_epoch, payload FROM order_rows_cache "
                "WHERE cache_key = :k"), {"k": _l2_key(key)}).first()
        if not row:
            return None
        if (_time.time() - float(row[0])) >= CACHE_TTL:
            return None
        data = _json.loads(row[1])
        return data.get("rows") or [], data.get("warnings") or []
    except Exception:      # noqa: BLE001 — 공유 캐시 실패가 조회를 막으면 안 된다
        return None


def _l2_put(key: tuple, rows: list, warnings: list) -> None:
    """best-effort 저장. 직렬화·DB 실패는 조용히 무시(L1 만으로 동작)."""
    try:
        _ensure_order_cache_table()
        import json as _json
        from shared.db import engine
        from sqlalchemy import text
        payload = _json.dumps({"rows": rows, "warnings": warnings},
                              ensure_ascii=False, default=str)
        is_pg = engine.dialect.name == "postgresql"
        with engine.begin() as conn:
            if is_pg:
                conn.execute(text(
                    "INSERT INTO order_rows_cache (cache_key, cached_at_epoch, payload) "
                    "VALUES (:k, :t, :p) ON CONFLICT (cache_key) DO UPDATE "
                    "SET cached_at_epoch = :t, payload = :p"),
                    {"k": _l2_key(key), "t": _time.time(), "p": payload})
            else:
                conn.execute(text(
                    "INSERT INTO order_rows_cache (cache_key, cached_at_epoch, payload) "
                    "VALUES (:k, :t, :p) ON CONFLICT (cache_key) DO UPDATE "
                    "SET cached_at_epoch = excluded.cached_at_epoch, payload = excluded.payload"),
                    {"k": _l2_key(key), "t": _time.time(), "p": payload})
    except Exception:      # noqa: BLE001
        pass


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
    """캐시 비우기(테스트·강제 새로고침용) — L1(프로세스) + L2(DB 공유) 둘 다.

    ★ L2 도 비워야 '강제 새로고침'이 진짜다 — 안 그러면 다른 워커가 채운 L2 가 최대
      90초 남아 새로고침이 헛돈다. (워커 사이 공유는 L1 을 직접 비워 시뮬레이션할 것.)
    """
    with _CACHE_LOCK:
        _CACHE.clear()
    try:
        from shared.db import engine
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM order_rows_cache"))
    except Exception:      # noqa: BLE001 — 캐시 비우기 실패가 조회를 막으면 안 된다
        pass


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
                        warnings: Optional[list] = None,
                        fresh: bool = False) -> list:
    """여러 마켓 주문을 합쳐 최신순(주문일 내림차순)으로. 판매처 열로 마켓 구분.

    기간 = since~until 명시(빠른 기간 버튼·직접 날짜) 또는 최근 days일. 미지원 마켓이
    섞이면 ValueError. 한 마켓 조회 실패는 전체 실패로 전파. use_cache=True(웹 라우트) +
    now 미지정이면 TTL 캐시 사용(대시보드↔다운로드 공유, 캐시 키에 기간 포함).
    warnings(list) 전달 시 제외된 계정 사유가 담긴다. ★캐시에도 경고를 함께 저장한다 —
    캐시 적중 때 경고가 사라지면 그 자체로 조용한 실패가 되기 때문.
    fresh=True(실패 계정 「다시 시도」) 는 캐시 '읽기'만 건너뛰어 실조회를 강제한다.
    결과는 평소처럼 캐시에 저장 — 안 그러면 TTL 이 남은 옛 실패본이 다음 일반
    조회에 되살아난다. 호출 뒤 완료된 조회(단일비행 대기 중 완성분 포함)는 fresh 로 인정.
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
        started = _time.monotonic()       # fresh 판정 기준 — 이 호출 이후 담긴 캐시만 인정
        mine, ev = False, None
        while True:
            with _CACHE_LOCK:
                hit = _CACHE.get(key)
                if fresh and hit and hit[0] < started:
                    hit = None            # 클릭 전 저장본(실패본일 수 있음)은 무시하고 실조회
                if hit and (_time.monotonic() - hit[0]) < CACHE_TTL:
                    if hit[2] and warnings is None:
                        # 화면(부분 허용)이 채운 캐시를 엑셀(전량 필요)이 받으면 불완전 파일이
                        # 조용히 나간다 → 경고가 있으면 경고 채널 없는 호출엔 캐시를 주지 않는다.
                        raise RuntimeError(hit[2][0])
                    if warnings is not None:
                        warnings.extend(hit[2])   # 캐시된 경고도 함께 되살림
                    return hit[1]
                ev = _INFLIGHT.get(key)
                if ev is None:                    # 진행 중인 같은 조회 없음 → 내가 빌더
                    ev = _threading.Event()
                    _INFLIGHT[key] = ev
                    mine = True
                    break
            # 같은 조회가 진행 중 — 끝나기를 기다렸다 캐시로 받는다(실조회 중복 금지).
            if not ev.wait(timeout=_INFLIGHT_WAIT):
                break                             # 빌더가 너무 늘어짐 → 등록 없이 직접 조회
            # set 됨 → 루프 재진입: 캐시 재확인. 빌더가 실패했으면(캐시 없음) 내가 빌더가 된다.
        try:
            # L2(DB) 크로스워커 캐시 — 다른 워커가 이미 채웠으면 실조회 없이 받는다.
            #   화면 경로(warnings 있음)에만. 엑셀(warnings=None)은 늘 실조회로 완전성 보장.
            #   경고도 함께 복원한다(적중 때 경고가 사라지면 조용한 실패).
            if warnings is not None and not fresh:
                l2 = _l2_get(key)
                if l2 is not None:
                    rows2, warns2 = l2
                    warnings.extend(warns2)
                    with _CACHE_LOCK:
                        _CACHE[key] = (_time.monotonic(), rows2, list(warns2))
                    return rows2
            rows = _build(warnings)               # warnings=None 이면 order_rows 가 전파
            with _CACHE_LOCK:
                _CACHE[key] = (_time.monotonic(), rows, list(warnings or []))
            if warnings is not None:              # 화면 경로 결과만 워커 간 공유(엑셀 제외)
                _l2_put(key, rows, list(warnings or []))
            return rows
        finally:
            if mine:
                with _CACHE_LOCK:
                    _INFLIGHT.pop(key, None)
                ev.set()
    return _build(warnings)


def _window(since, until, days, now=None):
    """필터용 [lo, hi] date 튜플. since/until 우선, 없으면 최근 days일."""
    if since and until:
        return since.date(), until.date()
    now = now or _dt.datetime.now(KST)
    return (now - _dt.timedelta(days=days)).date(), now.date()


def new_order_rows(markets, days: int = 7, now=None, use_cache: bool = False,
                   since=None, until=None, include_settlement: bool = True,
                   warnings=None, fresh: bool = False) -> list:
    """주문일 탭 전용 — 실주문일이 기간 안인 주문만.

    order 행은 항상 유지(취소완료여도 그날 들어온 주문이면 남김 = '상태 무관').
    change 행(취소/교환/반품 이벤트)은 실주문일이 기간 안일 때만 유지(롯데온 등),
    실주문일 공란/기간밖(쿠팡·11번가·옛주문)은 제외 → 기능 #2가 변경일 기준으로 잡는다.
    """
    rows = combined_order_rows(markets, days=days, now=now, use_cache=use_cache,
                               since=since, until=until,
                               include_settlement=include_settlement,
                               warnings=warnings, fresh=fresh)
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


# 마켓별 보강 옵션 — **각 빌더가 라이브 조회 때 쓰는 값 그대로**여야 한다.
#  목표는 「저장분을 주문내역 수준까지」이지 그 이상이 아니다. 여기서 더 켜면 저장분
#  경로가 라이브보다 더 채워져, 같은 주문이 화면마다 또 달라진다(방향만 반대).
#    eleven11 = eleven11_order_rows / coupang = coupang_order_rows /
#    auction·gmarket = esm_order_rows / lotteon = lotteon_order_rows(기본값·추정 없음) /
#    smartstore = 보강 호출 없음.
_ENRICH_SPEC = {
    "eleven11": ({"include_blank_orders": True, "settle_from_store_for_orders": True,
                  "include_blank_contact_orders": True}, True),
    "coupang":  ({"include_blank_contact_orders": True}, False),
    "lotteon":  ({}, False),
    "auction":  ({}, True),
    "gmarket":  ({}, True),
    "smartstore": (None, False),      # 라이브도 안 태운다 → 여기서도 안 태운다
}


def _enrich_log():
    import logging as _lg2
    return _lg2.getLogger(__name__)


def enrich_stored_rows(rows: list, *, session=None) -> list:
    """저장분에서 **읽은** 행을 주문내역 화면과 같은 수준으로 보강한다(쓰기 없음).

    왜 필요한가 — 주문내역(90일 이내)은 마켓을 라이브로 조회한 뒤 그 결과에 이력 채움·
    정산 추정·클레임 빈칸 채움을 태워서 보여준다. 그런데 그 보강은 **화면에 뿌릴 때
    메모리에서만** 일어나고 저장분에는 안 남는다. 그래서 저장분을 그대로 읽는 경로
    (마진계산기 · 90일 초과 주문내역)는 같은 주문을 덜 채워진 채로 본다.
      2026-07-24 실측(같은 14일 창, 같은 line_uid 로 대조):
        11번가 — 정산예정금 16 · 실결제 19 · 단가 10 · 수령자 10 · 상품명 6
        롯데온 — 실결제 32 · 수령자 16
      (거의 전부 취소완료 행. 적재 당시엔 같은 주문의 활성 행이 아직 저장분에 없어
       채움이 빈손이었고, 그 뒤 저장분이 채워져도 클레임 행은 다시 안 채워졌다.)
    사장님 지시(2026-07-24): "오픈마켓 주문번호가 매칭되는 건 공란이 있으면 안 된다 —
    적어도 주문내역 수준만큼은 채워져야 한다."

    ★ 읽기 전용이다. 새 API 호출도, 저장분 쓰기도 없다 — 이미 우리가 가진 값을 같은
      함수로 한 번 더 통과시킬 뿐이라 없는 값을 지어내지 않는다(빈 칸만 채운다).
    """
    rows = list(rows or [])
    if not rows:
        return rows
    # 보강 전에 '이력 줄이 누구였는지' 기억해 둔다 — 아래 채움 단계가 그 표시를 떼는
    #  경우가 있어서(마지막 블록 주석 참조), 끝나고 정체를 되돌려야 한다.
    _was_claim = {id(r) for r in rows if str(r.get("_kind") or "") == "change"}
    from lemouton.markets.order_store import _market_key
    by_market: dict = {}
    for r in rows:
        mk = _market_key(r)
        if mk:
            by_market.setdefault(mk, []).append(r)
    for market, mrows in by_market.items():
        fill_kw, do_estimate = _ENRICH_SPEC.get(market, ({}, False))
        if fill_kw is not None:
            try:
                fill_claim_blanks_from_history(mrows, market, session=session, **fill_kw)
            except Exception:   # noqa: BLE001 — 보강 실패는 빈칸 유지(주문은 살림)
                _enrich_log().exception("저장분 보강(이력 채움) 실패 market=%s", market)
        if do_estimate:
            try:
                estimate_settle_from_history(mrows, market, session=session)
            except Exception:   # noqa: BLE001
                _enrich_log().exception("저장분 보강(정산 추정) 실패 market=%s", market)
    # 클레임 행의 빈 구매자·상품명은 같은 주문의 활성 행에서 (마켓 구분 없이 한 번에).
    try:
        _enrich_change_from_active(rows)
    except Exception:   # noqa: BLE001
        _enrich_log().exception("저장분 보강(클레임 빈칸) 실패")
    # ★ 파생값 재계산 — 라이브와 **같은 순서**(빌더 채움 → _finalize_rows).
    #   `정산예정금(배송비포함)`·`상품금액`·`총주문금액`·수수료율은 _finalize_rows 만
    #   계산한다. 이걸 빼면 위에서 정산·단가를 채워도 마진계산기가 읽는 열
    #   (`정산예정금(배송비포함)`)이 빈칸 그대로라 채운 보람이 없다.
    #   재실행은 멱등하다: 배송건 중복 배송비 제거는 `_shipkey`(저장 전에 제거됨) 기준이라
    #   저장분엔 다시 적용되지 않고, 나머지는 같은 입력 → 같은 출력이다.
    try:
        _finalize_rows(rows)
    except Exception:   # noqa: BLE001
        _enrich_log().exception("저장분 보강(파생값 재계산) 실패")
    # 정산액은 있는데 근거 태그가 떨어져 나간 행 되살리기(저장분 잔재).
    #  ★ `_finalize_rows` **뒤** — 비교 상대인 `실결제금액`을 거기서 채운다(함수 주석 참조).
    try:
        _retag_orphan_settlement(rows)
    except Exception:   # noqa: BLE001
        _enrich_log().exception("저장분 보강(정산 근거 태깅) 실패")
    # ★ 이력 줄은 보강 뒤에도 이력이다 — 저장 출처가 진실이다.
    #   🔴 2026-07-24 실측(롯데온 3건): `fill_claim_blanks_from_history` 안의
    #   `lotteon_so.fill_from_so` 는 "철회가 취소된 것"으로 판단하면 그 행의
    #   `_kind`(change) 를 **떼어낸다**(_so_status_fixed 표식). 라이브 빌더 경로에선
    #   그 행이 그 라인의 유일한 행이라 맞는 동작이지만, **저장분 경로에선 같은 라인의
    #   주문 줄이 이미 따로 있다** — 이력 줄까지 주문 줄로 승격되면서 한 주문이 두 줄이
    #   됐다(출고지시+배송완료 / 회수지시+배송완료 / 철회+배송완료).
    #   상태 교정(주문상태·원본)은 그대로 살리고 **줄의 정체만** 되돌린다.
    for r in rows:
        if id(r) in _was_claim and str(r.get("_kind") or "") != "change":
            r["_kind"] = "change"
    return rows


def _retag_orphan_settlement(rows) -> int:
    """정산액은 있는데 근거 태그(`_settle_source`)가 없는 행 → `store` 로 태깅.

    왜 필요한가 — 저장 병합이 「정산액을 못 가져온 조회」의 태그(`none`)로 기존 태그를
    덮던 시절에 금액과 근거가 갈라진 행이 남았다(2026-07-25 실측 226건). 마진계산기는
    근거 없는 금액을 안 쓰므로 주문내역이 69,530 을 보여주는 주문을 **0** 으로 봤다.
    이 행들은 대부분 `구매결정`(DONE_STATUSES)이라 재조회로도 안 고쳐진다 — 읽을 때
    고친다. 병합 규칙 자체는 `order_store._merge_row` 에서 이미 막았다(재발 방지).

    ★ 금액은 손대지 않는다. 붙이는 태그는 `store` = "저장분에서 물려받은 값" —
      사실 그대로다. `real` 로 올리지 않는 이유: 그 금액이 마켓 실정산인지 우리 추정인지
      저장분만으로는 구분할 수 없다. 약한 쪽에 붙인다(과대 주장 금지).
    ★ 클레임 행(_kind='change')·취소완료는 건드리지 않는다 — 취소·반품은 정산이 취소·
      차감되므로 잔존 금액을 정산으로 되살리면 날조가 된다(태그 검사를 넣은 바로 그 이유).
    ★ **수수료가 실제로 빠진 값만** 정산으로 인정한다(`정산예정금액 < 실결제금액`).
      주문상태 이름으로 거르지 않는 이유: 마켓마다 용어가 달라 조용히 틀린다. 대신 돈
      자체를 본다 — 매출과 한 푼도 다르지 않은 값은 정산이 아니라 판매가가 잘못 실린 것이다.
      🔴 2026-07-25 라이브 실측이 이 조건을 요구했다: 롯데온 `회수지시` 112건(1,240만원)이
      `정산예정금액 == 실결제금액 == 44,800`(수수료 4,032 별도)이었다. 상태만 보고 걸렀다면
      매출을 정산으로 셀 뻔했다. 수수료 0%라 정말 같은 금액인 주문은 여기서 빠지지만,
      그건 기존 동작(추정 폴백 또는 0)으로 남을 뿐 돈을 부풀리지 않는다 — 안전한 쪽.
    ★ **`_finalize_rows` 뒤에 돌려야 한다.** 저장분의 `실결제금액`은 빈칸인 행이 흔하고
      (`_settle_filled='실결제금액'` — 마켓이 안 준 걸 정산조회로 메운 흔적), 그 칸은
      `_finalize_rows` 가 원금(단가×수량+옵션추가금)으로 채운다. 앞에서 돌리면 비교할
      매출이 없어 「수수료가 빠졌는지 모르겠다」로 건너뛴다 — 2026-07-25 배포 직후 실측:
      G마켓 43건 중 12건(495,640원)이 이 이유로 안 고쳐졌다.
    """
    n = 0
    for r in rows or []:
        if str((r or {}).get("_settle_source") or "").strip() not in ("", "none"):
            continue
        if str((r or {}).get("_kind") or "") == "change":
            continue
        if "취소완료" in str((r or {}).get("주문상태") or ""):
            continue
        settle = _to_int(r.get("정산예정금액"))
        if settle is None or settle <= 0:
            continue                       # 금액이 없으면 지어내지 않는다
        paid = _to_int(r.get("실결제금액"))
        if paid is None or settle >= paid:
            continue                       # 수수료가 안 빠졌다 = 정산액이 아니다
        r["_settle_source"] = "store"
        n += 1
    if n:
        _enrich_log().info("저장분 보강: 근거 없이 남아 있던 정산액 %d행을 'store' 로 태깅", n)
    return n


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

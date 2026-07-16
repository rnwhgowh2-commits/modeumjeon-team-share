"""CS 고객문의 서비스 — 마켓별 조회 정규화 + 그룹핑 + 완료 7일/삭제 필터.

★쿠팡/스스 응답 필드는 미검증 → _normalize_* 에서 방어적 폴백. 라이브 보정 대상.
전송(reply)은 LEMOUTON_LIVE_INQUIRY_REPLY OFF(기본) — 미리보기만.
"""
import datetime as _dt
import os as _os
import re as _re

from shared.db import SessionLocal
from lemouton.cs_inquiries.models import InquiryHandling
from shared.platforms.coupang.inquiries import (
    fetch_online_inquiries as _cp_fetch,
    fetch_call_center_inquiries as _cp_cc_fetch,
    reply_online_inquiry as _cp_reply,
)
from shared.platforms.smartstore.orders import (
    fetch_inquiries as _ss_fetch,
    fetch_product_qnas as _ss_qna,
    reply_inquiry as _ss_reply,
)
from shared.platforms.lotteon.inquiries import (
    iter_product_qna as _lo_pdqna,
    iter_seller_inquiries as _lo_seller,
)

_SUPPORTED = {"coupang", "smartstore", "lotteon"}   # 실조회 코드 있음. 11번가=준비중
_MK_KO = {"coupang": "쿠팡", "smartstore": "스마트스토어", "lotteon": "롯데온", "eleven11": "11번가"}


def _ymd(s):
    m = _re.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", str(s or ""))
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _g(d, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _normalize_coupang(it):
    answered = bool(_g(it, "answered", "answeredAt", default="")) or _g(it, "answeredType") == "ANSWERED"
    return {"마켓": "쿠팡", "문의형태": "온라인문의", "문의ID": str(_g(it, "inquiryId", "onlineInquiryId")),
            "고객": _g(it, "buyerName", "orderer", "name", "writerName", "custName", "buyerEmail", "memberId"),
            "상품": _g(it, "sellerProductName", "productName", "vendorItemName", "sellerItemName", "itemName", "sellerProductItemName"),
            "문의내용": _g(it, "content", "inquiryContent", "question"), "일시": _g(it, "inquiryAt", "createdAt", "receiptDate"),
            "상태": "답변완료" if answered else "미답변", "답변내용": _g(it, "replyContent", "answerContent"),
            "답변일": _g(it, "answeredAt", "replyAt")}


def _normalize_coupang_cc(it):
    """쿠팡 고객센터 문의. ★필드명 라이브 보정 대상."""
    status = _g(it, "partnerCounselingStatus", "counselingStatus")
    answered = status == "ANSWER" or bool(_g(it, "answeredAt", "answered", default=""))
    return {"마켓": "쿠팡", "문의형태": "고객센터문의", "문의ID": str(_g(it, "inquiryId", "counselingId", "callCenterInquiryId")),
            "고객": _g(it, "buyerName", "orderer", "name", "custName", "buyerEmail"),
            "상품": _g(it, "sellerProductName", "productName", "vendorItemName", "itemName"),
            "문의내용": _g(it, "content", "inquiryContent", "counselingContent", "question"),
            "일시": _g(it, "inquiryAt", "createdAt", "counselingAt"),
            "상태": "답변완료" if answered else "미답변", "답변내용": _g(it, "replyContent", "answerContent"),
            "답변일": _g(it, "answeredAt", "replyAt")}


def _normalize_ss_customer(it):
    """스스 고객 문의(주문·고객문의, pay-user/inquiries). ★API 센터 실측 필드."""
    ttl = _g(it, "title")
    body = _g(it, "inquiryContent")
    return {"마켓": "스마트스토어", "문의형태": "주문고객문의", "문의ID": str(_g(it, "inquiryNo")),
            "고객": _g(it, "customerName"), "상품": _g(it, "productName", "productOrderOption"),
            "문의내용": (f"[{_g(it,'category')}] {ttl} · {body}" if ttl else body),
            "일시": _g(it, "inquiryRegistrationDateTime"),
            "상태": "답변완료" if bool(it.get("answered")) else "미답변",
            "답변내용": _g(it, "answerContent"), "답변일": _g(it, "answerRegistrationDateTime")}


def _normalize_ss_qna(it):
    """스스 상품 문의(상품Q&A, contents/qnas). ★API 센터 실측 필드."""
    return {"마켓": "스마트스토어", "문의형태": "상품문의", "문의ID": str(_g(it, "questionId")),
            "고객": _g(it, "maskedWriterId"), "상품": _g(it, "productName"),
            "문의내용": _g(it, "question"), "일시": _g(it, "createDate"),
            "상태": "답변완료" if bool(it.get("answered")) else "미답변",
            "답변내용": _g(it, "answer"), "답변일": ""}


def _normalize_lotteon_pdqna(it):
    """롯데온 상품QnA(상품문의). 응답에 고객명·상품명 없음(spdNo=판매자상품번호만)."""
    st = _g(it, "qnaStatCd")
    return {"마켓": "롯데온", "문의형태": "상품문의", "문의ID": str(_g(it, "pdQnaNo")),
            "고객": "", "상품": _g(it, "spdNo"),
            "문의내용": _g(it, "qstCnts"), "일시": _g(it, "regDttm"),
            "상태": "미답변" if st == "NPROC" else "답변완료",   # PROC/CC_TCTL=처리됨
            "답변내용": "", "답변일": ""}


def _normalize_lotteon_seller_inq(it):
    """롯데온 판매자문의. 상품명(pdNm)·답변(ansCnts) 있음."""
    st = _g(it, "slrInqProcStatCd")
    ttl = _g(it, "inqTtl")
    body = _g(it, "inqCnts")
    return {"마켓": "롯데온", "문의형태": "판매자문의", "문의ID": str(_g(it, "slrInqNo")),
            "고객": "", "상품": _g(it, "pdNm", "spdNm"),
            "문의내용": (f"{ttl} · {body}" if ttl else body),
            "일시": _g(it, "accpDttm"),
            "상태": "답변완료" if st == "ANS" else "미답변",
            "답변내용": _g(it, "ansCnts"), "답변일": _g(it, "procDttm")}


def _acct_clients(market):
    """판매처관리 등록 계정별 설정 클라이언트(인증키·IP 포함). 없으면 대표계정 폴백."""
    from lemouton.markets.order_export import _account_client, _active_accounts
    out = []
    for prefix, _name in _active_accounts(market):
        c = _account_client(market, prefix)
        if c is not None:
            out.append(c)
    if not out:
        c = _account_client(market, None)
        if c is not None:
            out.append(c)
    return out


def _coupang_clients():
    """판매처관리에 등록된 쿠팡 계정별 설정 클라이언트(_cfg.vendor_id 포함). 없으면 대표계정 폴백."""
    from lemouton.markets.order_export import _account_client, _active_accounts
    out = []
    for prefix, _name in _active_accounts("coupang"):
        c = _account_client("coupang", prefix)
        if c is not None:
            out.append(c)
    if not out:
        c = _account_client("coupang", None)
        if c is not None:
            out.append(c)
    return out


def _cp_items(raw):
    """쿠팡 문의 응답에서 문의 리스트 추출. 응답이 봉투형(data.content 등)이든 평탄이든 안전하게.

    ★실제 키는 라이브 검증 대상 — content/inquiries/onlineInquiries/items 순으로 시도.
    """
    if not isinstance(raw, dict):
        return []
    data = raw.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("content", "inquiries", "onlineInquiries", "items", "list"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    # data 없거나 구조 다름 — 최상위에서도 흔한 키 시도
    for k in ("content", "inquiries", "items"):
        v = raw.get(k)
        if isinstance(v, list):
            return v
    return []


def _cp_inq_windows(since, until, days=6):
    """쿠팡 문의 조회 최대 7일 제약 → [since,until]을 ≤days 청크로 분할(경계 안전 6일)."""
    cur = since
    step = _dt.timedelta(days=days)
    if until <= since:
        yield since, until
        return
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def _fetch_market(market, since, until, status):
    """마켓 어댑터 → 정규화 dict 리스트. 페이지네이션(안전상한). ★필드명 라이브 보정 대상."""
    if market == "coupang":
        out = []
        for _cli in _coupang_clients():
            for _w0, _w1 in _cp_inq_windows(since, until):   # 쿠팡 문의 조회 최대 7일 → 6일 청크 분할
                page = 1
                for _ in range(30):   # 온라인 고객문의(상품)
                    raw = _cp_fetch(_w0, _w1, client=_cli, answered_type="ALL", page_size=50, page_num=page)
                    items = _cp_items(raw)   # data 가 봉투(dict{content}) or 리스트 — 방어적 추출
                    out.extend(_normalize_coupang(it) for it in items if isinstance(it, dict))
                    if len(items) < 50:
                        break
                    page += 1
                page = 1
                for _ in range(30):   # 고객센터 문의(상담 경유)
                    try:
                        raw = _cp_cc_fetch(_w0, _w1, client=_cli, counseling_status="NONE", page_size=50, page_num=page)
                    except Exception:   # noqa: BLE001 — 고객센터 조회 실패는 온라인 문의 유지(부가)
                        break
                    items = _cp_items(raw)
                    out.extend(_normalize_coupang_cc(it) for it in items if isinstance(it, dict))
                    if len(items) < 50:
                        break
                    page += 1
        return out
    if market == "smartstore":
        out = []
        for _cli in _acct_clients("smartstore"):
            page = 1   # 고객문의(주문·고객) — content[] / last
            for _ in range(30):
                raw = _ss_fetch(since, until, client=_cli, page_size=200, page_number=page)
                items = raw.get("content") or []
                out.extend(_normalize_ss_customer(it) for it in items if isinstance(it, dict))
                if raw.get("last") is True or len(items) < 200:
                    break
                page += 1
            page = 1   # 상품Q&A — contents[] / last
            for _ in range(30):
                try:
                    raw = _ss_qna(since, until, client=_cli, page_size=100, page_number=page)
                except Exception:   # noqa: BLE001 — Q&A 실패는 고객문의 유지(부분성공)
                    break
                items = raw.get("contents") or []
                out.extend(_normalize_ss_qna(it) for it in items if isinstance(it, dict))
                if raw.get("last") is True or len(items) < 100:
                    break
                page += 1
        return out
    if market == "lotteon":
        out = []
        for _cli in _acct_clients("lotteon"):
            try:   # 상품QnA(상품문의)
                out.extend(_normalize_lotteon_pdqna(it) for it in _lo_pdqna(since, until, client=_cli))
            except Exception:   # noqa: BLE001 — 한 종류 실패는 다른 종류 유지
                pass
            try:   # 판매자문의
                out.extend(_normalize_lotteon_seller_inq(it) for it in _lo_seller(since, until, client=_cli))
            except Exception:   # noqa: BLE001
                pass
        return out
    raise RuntimeError(f"{_MK_KO.get(market, market)} 문의 연동 준비 중")


def inquiry_key_of(row):
    return f'{row.get("마켓","")}:{row.get("문의ID","")}'


def list_inquiries(markets, *, since, until, now=None, session=None):
    own = session is None
    session = session or SessionLocal()
    try:
        today = (now or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9)))).date()
        _KST = _dt.timezone(_dt.timedelta(hours=9))
        _until = until or (now or _dt.datetime.now(_KST))
        _since = since or (_until - _dt.timedelta(days=7))
        all_rows, warnings = [], []
        for mk in markets:
            if mk not in _SUPPORTED:
                warnings.append(f"[{_MK_KO.get(mk, mk)}] 문의 연동 준비 중")
                continue
            try:
                all_rows.extend(_fetch_market(mk, _since, _until, "ALL"))
            except Exception as e:   # noqa: BLE001
                warnings.append(f"[{_MK_KO.get(mk, mk)}] 문의 조회 실패: {e}")
        keys = [inquiry_key_of(r) for r in all_rows]
        dismissed = {h.inquiry_key for h in
                     session.query(InquiryHandling).filter(InquiryHandling.inquiry_key.in_(keys or [""])).all()
                     if h.dismissed_at is not None}
        groups = {"미답변": [], "답변완료": []}
        counts = {"전체": 0}
        for r in all_rows:
            r = dict(r)
            r["inquiry_key"] = inquiry_key_of(r)
            if r["상태"] == "답변완료":
                d = _ymd(r.get("답변일") or r.get("일시"))
                if r["inquiry_key"] in dismissed or (d is not None and (today - d).days > 7):
                    continue
            groups[r["상태"]].append(r)
            counts["전체"] += 1
            counts[r["마켓"]] = counts.get(r["마켓"], 0) + 1
        return {"groups": groups, "market_counts": counts, "warnings": warnings}
    finally:
        if own:
            session.close()


def dismiss_inquiry(inquiry_key, *, market="", session=None):
    own = session is None
    session = session or SessionLocal()
    try:
        row = session.query(InquiryHandling).filter_by(inquiry_key=inquiry_key).one_or_none()
        if row is None:
            row = InquiryHandling(inquiry_key=inquiry_key, market=market)
            session.add(row)
        row.dismissed_at = _dt.datetime.now(_dt.timezone.utc)
        session.commit()
    finally:
        if own:
            session.close()


def _live_reply_on():
    return _os.getenv("LEMOUTON_LIVE_INQUIRY_REPLY", "").strip().lower() in ("1", "true", "on", "yes")


def reply_preview(market, inquiry_id, content):
    """답변 미리보기. LIVE OFF(기본)면 실전송 안 함(거짓 전송 금지)."""
    if not _live_reply_on():
        return {"sent": False, "preview": content, "note": "전송 준비 중(검증 후 열림)"}
    if market == "coupang":
        _cp_reply(inquiry_id, content)
    elif market == "smartstore":
        _ss_reply(inquiry_id, content)
    else:
        raise RuntimeError(f"{market} 답변 전송 미지원")
    return {"sent": True, "preview": content}

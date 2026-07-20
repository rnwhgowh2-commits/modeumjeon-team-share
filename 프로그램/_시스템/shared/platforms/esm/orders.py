# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 주문조회 — RequestOrders.

근거(공개문서 etapi.gmarket.com/67, 2026-07-07 실측):
  POST /shipping/v1/Order/RequestOrders
  요청: siteType(1:옥션,2:G마켓)·orderStatus(1:결제완료 2:배송준비중 3:배송중 4:배송완료
        5:구매결정완료)·requestDateType(1:주문일)·requestDateFrom/To("YYYY-MM-DD hh:mm",31일 제한)
        ·pageIndex·pageSize
  응답: {ResultCode:0, Message, Data:{TotalCount, RequestOrders:[...]}}

기간이 31일 초과면 31일 윈도우로 분할, orderStatus 별로 순회(발송관리=미발송+진행 전체),
OrderNo 로 중복 제거. 5초/1회 rate limit 은 client 가 담당.
"""
from __future__ import annotations

import datetime as _dt

_SITE_TYPE = {"auction": 1, "gmarket": 2}
# 최근 주문 전체(주문상태 열 의미 유지) — 결제완료~구매결정완료.
_DEFAULT_STATUSES = (1, 2, 3, 4, 5)
# 조회기간 상한은 마켓마다 다르다(공식문서 etapi.gmarket.com/67).
#   G마켓 "31일 이하의 범위만 조회할 수 있습니다" / 옥션 180일 이하.
# 둘 다 31일로 쪼개면 옥션은 호출이 6배가 되고, 주문조회는 5초/1회(계정별) 제한이라
# 그대로 대기 시간이 된다(180일 조회 기준 150초 → 25초).
_MAX_WINDOW_DAYS = {"auction": 180, "gmarket": 31}
_MAX_WINDOW_DAYS_DEFAULT = 31   # 모르는 마켓은 좁은 쪽(상한 초과 호출은 마켓이 거부)
_PAGE_SIZE = 100


def _fmt(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M")


def _windows(since: _dt.datetime, until: _dt.datetime, market: str = ""):
    """[since, until] 을 그 마켓의 조회기간 상한 이하 구간들로 분할(빈틈·겹침 없음)."""
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS.get(market, _MAX_WINDOW_DAYS_DEFAULT))
    cur = since
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def fetch_by_order_no(market: str, order_no, *, client,
                      since: _dt.datetime = None, until: _dt.datetime = None):
    """주문번호 1건 상세 조회(orderStatus=0) → (행, 실패사유).

    왜 필요한가 — 클레임 조회(취소·반품·교환)는 **주문번호와 상태만** 준다.
    상품명·판매가·수량이 응답에 아예 없어서, 그것만으로는 주문내역 행을 만들 수 없다.
    다행히 공식문서가 길을 열어둔다: "주문조회는 5초당 1회 호출 가능합니다.
    **단, 주문번호로 조회하는 경우 제한 없습니다**"(etapi.gmarket.com/67).

    ★ requestDateType/From/To 는 orderStatus=0 에서도 문서상 필수다. 안 보내면
      2000(파라메터 유효성 검사 실패)이 돌아온다 — 예전엔 그걸 조용히 None 으로
      삼켜서 "단가가 빈칸"으로만 보였다. 기간 미지정 시 넉넉히 최근 180일을 준다
      (주문번호로 특정하므로 기간을 넓혀도 다른 주문이 섞이지 않는다).
    ★ 실패 사유를 함께 돌려준다 — 삼키면 원인을 영영 알 수 없다.
    """
    site_type = _SITE_TYPE.get(market)
    if site_type is None:
        raise ValueError(f"ESM 마켓 아님: {market} (auction|gmarket)")
    if until is None:
        until = _dt.datetime.now()
    if since is None:
        since = until - _dt.timedelta(days=_MAX_WINDOW_DAYS.get(market,
                                                                _MAX_WINDOW_DAYS_DEFAULT))
    base = {"siteType": site_type, "orderStatus": 0, "orderNo": int(order_no)}
    dated = dict(base, requestDateType=1,
                 requestDateFrom=_fmt(since), requestDateTo=_fmt(until))
    # 문서만 보고 한 가지 모양으로 단정하지 않는다 — 마켓이 어느 조합을 받는지는
    # 실제로 던져봐야 안다. 앞의 것이 0건이면 다음 모양으로 재시도한다.
    #   ① 주문일 기준 + 기간   ② 기간 없이 주문번호만   ③ 결제일 기준 + 기간
    variants = [
        ("주문일+기간", dated),
        ("주문번호만", base),
        ("결제일+기간", dict(dated, requestDateType=2)),
    ]
    path = (client._cfg.get("paths") or {}).get("orders")
    reasons = []
    for label, body in variants:
        resp = client.post(path, body) or {}
        rc = resp.get("ResultCode")
        if rc not in (0, "0", None, "success", "Success"):
            reasons.append(f"{label}:ResultCode={rc} {resp.get('Message') or ''}".strip())
            continue
        data = resp.get("Data") or {}
        rows = (data.get("RequestOrders") or []) if isinstance(data, dict) else (data or [])
        if rows:
            row = dict(rows[0])
            row["_detail_via"] = label
            return row, None
        reasons.append(f"{label}:0건")
    return None, " / ".join(reasons)[:220]


def fill_from_product(market, site_goods_no, *, client, goods_no=None):
    """상품번호로 상품명을 채운다 → (상품명, 실패사유).

    주문번호로 상세를 못 받는 클레임 건의 마지막 경로. 클레임 응답이 SiteGoodsNo 는
    주므로 상품 API 로 이름을 얻을 수 있다.

    ★ **가격은 여기서 가져오지 않는다.** 상품 API 가 주는 건 '지금 판매가'라서
      주문 시점 결제금액과 다르다. 그걸 단가에 채우면 없는 숫자를 만들어내는 것이라
      매출·정산 대조가 조용히 틀어진다(폴백 금지). 이름은 사실이라 안전하다.
    """
    if not (site_goods_no or goods_no):
        return None, "상품번호 없음(GoodsNo·SiteGoodsNo 둘 다 없음)"
    try:
        from .products import get_goods_detail, resolve_goods_no
        # 시그니처 주의: 두 함수 모두 market 을 받지 않는다(상품번호 + client 만).
        # ★ goods_no(마스터 상품번호)가 있으면 변환을 건너뛴다.
        #   단 클레임 응답의 GoodsNo 는 **값이 0**으로 온다(2026-07-20 라이브 프로브 확인 —
        #   문서의 "현재 null 로만 내려감"이 맞았다). 그래서 실제로는 아래 변환 경로를 탄다.
        #   마켓이 훗날 값을 주기 시작하면 이 분기가 그대로 살아난다.
        if goods_no and str(goods_no) not in ("0", "None", ""):
            gn = str(goods_no)
        else:
            gn = resolve_goods_no(str(site_goods_no), client=client)
            if not gn:
                return None, "goodsNo 변환 실패"
            # ★ resolve_goods_no 는 매핑에 실패해도 **입력을 그대로 돌려준다**(마스터번호일
            #   수도 있으니 시도해보는 폴백). 그래서 성공한 척 사이트번호가 goodsNo 자리에
            #   들어가 404 가 난다. 같은 값이 돌아왔으면 '변환 안 됨'으로 보고 여기서 끊는다
            #   — 그래야 "404" 대신 진짜 사유를 말할 수 있다.
            if str(gn) == str(site_goods_no):
                return None, (f"상품번호 {site_goods_no} 가 마켓 상품 조회에 없습니다"
                              f"(삭제·판매종료 추정)")
        detail = get_goods_detail(gn, client=client) or {}
    except Exception as e:      # noqa: BLE001
        if goods_no and site_goods_no and str(goods_no) != str(site_goods_no):
            # 마스터번호로 실패했으면 사이트번호 변환 경로로 한 번 더 시도한다.
            try:
                gn2 = resolve_goods_no(str(site_goods_no), client=client)
                detail = get_goods_detail(gn2, client=client) or {}
            except Exception as e2:     # noqa: BLE001
                return None, f"{type(e).__name__}: {e} / 재시도 {type(e2).__name__}"[:150]
        else:
            return None, f"{type(e).__name__}: {e}"[:120]
    if not isinstance(detail, dict):
        return None, "상품 상세 형식 불명"

    # 상품 상세조회의 상품명은 평평하지 않다 — 데이터 코드 지도 기준:
    #   itemBasicInfo > goodsName > kor        (검색용 국문 = 화면에 보이는 이름)
    #   itemBasicInfo > goodsName > promotion  (프로모션명, 공통·지마켓)
    #   itemBasicInfo > goodsName > promotionIac (프로모션명, 옥션)
    # 주문조회의 GoodsName(평평) 과 다르므로 둘 다 훑는다.
    basic = detail.get("itemBasicInfo")
    if isinstance(basic, dict):
        gn = basic.get("goodsName")
        if isinstance(gn, dict):
            for k in ("kor", "promotion", "promotionIac", "eng"):
                if gn.get(k):
                    return str(gn[k]), None
        elif gn:
            return str(gn), None

    for k in ("GoodsName", "goodsName", "goods_name", "name", "itemName"):
        v = detail.get(k)
        if isinstance(v, str) and v:
            return v, None

    return None, f"상품 상세에 상품명 없음(키: {sorted(detail)[:8]})"


def iter_orders(market: str, since: _dt.datetime, until: _dt.datetime, *,
                client, statuses=_DEFAULT_STATUSES, page_size: int = _PAGE_SIZE):
    """옥션/G마켓 주문(dict) 제너레이터. OrderNo 중복 제거."""
    site_type = _SITE_TYPE.get(market)
    if site_type is None:
        raise ValueError(f"ESM 마켓 아님: {market} (auction|gmarket)")

    seen = set()
    for w_from, w_to in _windows(since, until, market):
        for status in statuses:
            page = 1
            while True:
                body = {
                    "siteType": site_type,
                    "orderStatus": int(status),
                    "requestDateType": 1,               # 주문일 기준
                    "requestDateFrom": _fmt(w_from),
                    "requestDateTo": _fmt(w_to),
                    "pageIndex": page,
                    "pageSize": page_size,
                }
                resp = client.request_orders(body) or {}
                if resp.get("ResultCode") not in (0, None):
                    # 오류코드는 사유와 함께 전파(추측·무시 금지)
                    raise RuntimeError(f"ESM 주문조회 실패 ResultCode={resp.get('ResultCode')} "
                                       f"{resp.get('Message') or ''}")
                data = resp.get("Data") or {}
                orders = data.get("RequestOrders") or []
                if not orders:
                    break
                for od in orders:
                    key = od.get("OrderNo")
                    if key in seen:
                        continue
                    seen.add(key)
                    yield od
                total = data.get("TotalCount") or 0
                if page * page_size >= total or len(orders) < page_size:
                    break
                page += 1

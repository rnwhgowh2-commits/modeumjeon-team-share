# -*- coding: utf-8 -*-
"""폰 전용 주문 화면 — `/mobile/orders` (배치5 · 사장님 확정 1-C·2-A·3-C).

mobile_shell.py 가 아니라 따로 둔 이유: 껍데기(메뉴·탭·설치)와 주문은 관심사가
다르다. 껍데기에 주문 로직이 붙기 시작하면 mobile_shell 이 orders 의존을 갖게 되고,
주문 쪽을 고칠 때마다 껍데기 시험이 같이 흔들린다(mobile.py 를 스캔·재고로 분리해
둔 것과 같은 결).

데이터는 새 집계를 만들지 않는다 — PC 주문 화면(/orders)이 쓰는 **같은 엔드포인트**
(preview.json · price-diff.json · fulfillment.json)를 폰 JS 가 그대로 부른다.
서버 쪽 숫자 원천이 하나면 두 화면이 다른 답을 낼 수 없다(같은 숫자 두 곳 금지).
"""
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("mobile_orders", __name__, url_prefix="/mobile")


@bp.route("/orders")
def orders():
    """주문 폰 화면 — KPI 3칸(3-C) + 칩 4개(2-A) + 1-C 목록 + 2차 알약(송장·CS·마진).

    마켓 목록은 서버가 준다(supported_markets — 코드·키·검증이 갖춰진 마켓만).
    JS 에 마켓을 직접 적으면 검증으로 새 마켓이 열려도 폰만 조용히 빠진다.

    [배치5-2차] 송장 판이 쓰는 판정 원천 둘도 서버가 준다 — JS 사본 금지:
      · sendable = invoice_send.SUPPORTED_SEND (송장 전송 지원 마켓. PC 는 템플릿에
        사본을 두고 주석으로 동기화하는데, 그 방식이 낳는 drift 를 폰에선 원천 주입으로 없앤다)
      · shipped_states = order_export._SHIPPED_STATES (「이미 발송 흐름에 든」 상태 —
        「송장 없음」 칸의 판정 기준. 정규식을 새로 지으면 flow_daily 와 갈라진다)
    """
    from lemouton.markets import order_export as _oe
    from lemouton.markets.invoice_send import SUPPORTED_SEND
    from lemouton.markets.order_export import _SHIPPED_STATES
    mks = sorted(_oe.supported_markets())
    return render_template(
        "mobile/orders.html",
        markets=[{"key": m, "label": _oe.market_label(m)} for m in mks],
        sendable=sorted(SUPPORTED_SEND),
        shipped_states=sorted(_SHIPPED_STATES))

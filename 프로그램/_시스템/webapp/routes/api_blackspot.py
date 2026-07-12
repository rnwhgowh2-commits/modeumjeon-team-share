# -*- coding: utf-8 -*-
r"""블랙스팟 소싱처 주문번호 추출 API — `/api/blackspot/fetch_order_no` (POST).

마진 계산기 페이지(orders/margin_embed.html)의 '주문번호 미기입' 표에서 [🔍 소싱처]
버튼이 이 리터럴 경로를 호출한다(`fetchOrderNoFromSource`). `/api/margin` 프리픽스가
아니라 최상위 `/api/blackspot/...` 여야 한다 — 이식된 원본 페이지가 그 경로를
하드코딩했기 때문(api_keywords 와 동일한 이유).

■ 순수 파싱 (브라우저 없음).
  `lemouton.margin.sourcing_parser.fetch_order_no(memo)` 는 간단메모 텍스트를 regex 로
  파싱하고 소싱처 order_detail_url 템플릿을 역매칭해 주문번호를 뽑는다. Playwright·
  네트워크·확장 없음. 주문 '상태' 확인(check_order_sync / `/api/check-sourcing`)은
  로컬 확장이 필요한 별개 작업(E2)이며 여기 없다.

■ 무상태 적응 (원본과의 유일한 구조 차이).
  원본 서버는 `store['buy_missing_df']` 에서 uid 로 행을 찾아 그 행의 간단메모를 읽고,
  성공 시 supplement 저장 + 전체 재매칭까지 했다. 모음전 analyze 는 무상태라 그런 서버
  저장소가 없다 → 페이지가 uid 만 보내면 서버가 메모를 알 수 없다. 그래서 페이지 씨앗
  (build_margin_embed.py SEAMS) 으로 **메모를 클라이언트에서 함께 POST** 하도록 바꿨고,
  이 라우트는 그 memo 로 순수 파싱만 한다. supplement 저장·재매칭(matched_count/
  missing_count)은 무상태 서버가 정직하게 계산할 수 없으므로 이 라우트에서 만들어내지
  않는다(거짓 숫자 금지). 파싱 결과만 정직하게 돌려준다.
"""
from flask import Blueprint, jsonify, request

from lemouton.margin.sourcing_parser import fetch_order_no

bp = Blueprint("api_blackspot", __name__, url_prefix="/api/blackspot")


@bp.route("/fetch_order_no", methods=["POST"])
def api_fetch_order_no():
    """간단메모에서 소싱처 주문번호 자동 추출(순수 파싱).

    Body: {uid, memo}  (uid = 미기입 행 식별자, memo = 그 행의 간단메모)
    Returns: {success, order_no, site_key, site_name, account_id, source, logs[], error}
      — 원본 fetch_order_no() 반환 형태 그대로. 무상태라 matched_count/missing_count 는
        정직하게 계산 불가 → 포함하지 않는다(옵션 필드).
    """
    body = request.get_json(silent=True) or {}
    memo = body.get("memo", "")
    # 메모가 아예 안 오면(씨앗 미적용 캐시 등) 파서가 '간단메모 비어있음' 실패를 정직하게 반환.
    return jsonify(fetch_order_no(memo))

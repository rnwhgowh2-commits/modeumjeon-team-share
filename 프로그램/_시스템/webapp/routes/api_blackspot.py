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


@bp.route("/manual_order_no", methods=["POST"])
def api_manual_order_no():
    """[정직한 미지원 스텁] 주문번호 수동 반영·재매칭.

    페이지의 [✏️ 반영] 버튼(`submitManualOrderNo`)이 이 경로로 POST 한다. 원본은
    supplement 저장 + 전체 재매칭을 했지만, 그건 무상태 모음전 서버가 갖지 못한
    stateful 워크플로(별도 후속 작업)다. 아직 미구현이므로 **재매칭을 꾸며내지 않고**
    HTTP 200 + success:false + 명확한 안내 문구를 돌려준다. 이렇게 해야 페이지가
    404 raw 실패(‘통신 오류’)로 사용자를 혼란시키지 않고, 안내 메시지를 그대로 띄운다
    (submitManualOrderNo 는 `res.error` 를 alert 로 표시).
    """
    return jsonify({
        "success": False,
        "error": "주문번호 반영·재매칭은 아직 지원되지 않습니다 "
                 "(더망고 매입 엑셀에 직접 입력 후 재분석하세요).",
    })

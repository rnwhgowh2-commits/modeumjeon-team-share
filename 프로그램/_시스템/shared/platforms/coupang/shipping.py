# -*- coding: utf-8 -*-
"""쿠팡 택배사 코드표.

⚠ [2026-07-23 리뷰 M2] 여기 있던 `list_outbound_places` / `list_return_centers` 는
  **삭제했다.** 두 함수는 `COUPANG["paths"]["outbound_places"]` ·
  `COUPANG["paths"]["return_centers"]` 를 읽었는데 그런 설정키가 없어 부르는 즉시
  KeyError 로 죽는 죽은 코드였고, 부르는 곳도 없었다. 같은 조회의 **살아 있는 구현체**는
  하나뿐이다 —

      shared/platforms/coupang/logistics.py
        · list_return_centers(vendor_id, client=...)
        · list_outbound_places(client=...)

  (그쪽은 지도 근거·응답 shape 차이·pageNum/pageSize 필수까지 문서화돼 있고 테스트가
   있다.) 두 벌로 두면 죽은 쪽을 고쳐 놓고 「고쳤는데 안 바뀐다」가 난다.

이 파일에는 실제로 쓰이는 것만 남긴다 — 택배사 코드표(lemouton/markets/invoice_send.py).
"""
from __future__ import annotations


# 쿠팡 공식 택배사 코드 (자주 쓰는 것만)
# 전체 목록: https://developers.coupangcorp.com/hc/ko/articles/360034156033
DELIVERY_COMPANY_CODES = {
    "CJ대한통운": "CJGLS",
    "한진택배":   "HANJIN",
    "롯데택배":   "LOTTE",
    "우체국택배": "EPOST",
    "로젠택배":   "KGB",
    "대신택배":   "DAESIN",
    "경동택배":   "KDEXP",
    "건영택배":   "KUNYOUNG",
    "합동택배":   "HDEXP",
    "일양로지스": "ILYANG",
    "천일택배":   "CHUNIL",
}

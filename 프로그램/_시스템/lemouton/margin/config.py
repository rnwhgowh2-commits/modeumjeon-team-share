# -*- coding: utf-8 -*-
r"""마진계산기 상수. 로직 없음.

원본: C:\dev\대량등록 마진계산기\config.py 에서 경로·서버 상수를 제외하고 이식.
SETTLEMENT_* 집합은 ①에서 미사용이나 matcher.match_for_classifier 가 import 하므로 보존.
"""

# ── 마켓명 매핑 (기존 margin_calculator.py 에서 이전) ──
MARKET_MAP = {
    '11번가':       '03.11번가',
    'G마켓2.0':     '01.지마켓',
    '옥션2.0':      '02.옥션',
    '스마트스토어': '04.스마트스토어',
    '쿠팡':         '06.쿠팡',
    '롯데ON':       '18.롯데온',
}
MARKET_REVERSE = {v: k for k, v in MARKET_MAP.items()}

COUPANG_FEE_RATE = 0.1155

DEFAULT_PRICE_RANGES = [
    (0,      10000,  '~1만'),
    (10000,  30000,  '1~3만'),
    (30000,  50000,  '3~5만'),
    (50000,  100000, '5~10만'),
    (100000, float('inf'), '10만~'),
]

# ── 더망고 칼럼명 ──
MANGO_COLS = {
    "order_date":     "마켓주문일자",
    "market":         "마켓명",
    "order_no":       "마켓주문번호",
    "recipient":      "수령인명",
    "product":        "마켓상품명",
    "option":         "옵션1",
    "site_order_no":  "사이트주문번호",     # ★ G열 — 미기입 판정 기준
    "purchase_price": "구매가격",
    "intl_shipping":  "국제운송료",
    "courier":        "국내송장번호 택배사",
    "tracking":       "국내송장번호",
    "mango_status":   "더망고주문상태 (사용자 연동)",
    "market_status":  "마켓주문상태 (오픈 마켓 연동)",
    "memo":           "간단메모",
}

# ── 샵마인 칼럼명 ──
SHOPMINE_COLS = {
    "order_no":       "오픈마켓주문번호",
    "order_status":   "주문상태",
    "settlement":     "정산예상금액(배송비포함)",
    "price":          "단가",
    "market":         "쇼핑몰",
    "product":        "삼품명",
    "invoice":        "송장입력",
    "payment":        "실결제금액",
    "fee":            "마켓수수료",
    "fee_rate":       "수수료율",
    "shopmine_status": "샵마인주문상태",
}

# ── 더망고주문상태 값 ──
MANGO_STATUS_PAID          = "결제완료"
MANGO_STATUS_WAITING       = "배송대기중"
MANGO_STATUS_SHIPPING      = "국내배송중"
MANGO_STATUS_DELIVERED     = "배송완료"
MANGO_STATUS_REC_PROGRESS  = "반품/교환/취소 진행중"
MANGO_STATUS_REC_DONE      = "반품/교환/취소완료"
MANGO_STATUS_KKADAEGI      = "해외현지배송중"
MANGO_PENDING_STATUSES     = [MANGO_STATUS_PAID, MANGO_STATUS_WAITING]
MANGO_KKADAEGI_STATUSES    = [MANGO_STATUS_KKADAEGI]

# ── 마켓주문상태 값 ──
MARKET_STATUS_NORMAL       = "특이사항없음"
MARKET_STATUS_SENT         = "송장전송완료"
MARKET_STATUS_FAIL         = "송장전송실패"
MARKET_STATUS_CANCEL_REQ   = "취소신청"
MARKET_STATUS_RETURN_REQ   = "반품신청"
MARKET_STATUS_EXCHANGE_REQ = "교환신청"
MARKET_STATUS_REC_DONE     = "취소/반품/교환 완료"

# ── 간단메모 미이행 사유 코드 ──
MEMO_NO_STOCK    = ["S", "s", "ㄴㄴ", "ㄴ", "ㅍㅈ"]
MEMO_NO_MARGIN   = ["P", "p", "ㅔ"]
MEMO_CANT_ORDER  = ["x", "X"]
MEMO_SKIP_CODES  = MEMO_NO_STOCK + MEMO_NO_MARGIN + MEMO_CANT_ORDER

# ── 장기 미처리 기준 ──
STALE_DAYS = 7

# ── 마진 이상치 기준 (classifier 의 1-2, 1-3 판정용) ──
MARGIN_HIGH_RATE     = 0.30     # 30% 초과 마진율
MARGIN_HIGH_AMOUNT   = 5000     # 5천원 초과 마진
MARGIN_NEGATIVE_RATE = 0.0      # 0% 미만 역마진

# ── 샵마인 정산 판정 (블랙스팟 config.py 에서 전체 이전) ──
SETTLEMENT_O_EXACT = {
    "결제완료", "교환", "구매확정",
    "발송대기", "발송대기(발주확인)", "발송대기(신규주문)",
    "발송완료(배송중)", "배송완료", "배송준비중", "배송중", "배송지시",
    "상품준비", "상품준비중",
    "수취완료", "신규주문",
    "정산예정", "정산완료", "출고지시", "확정",
}

SETTLEMENT_X_EXACT = {
    "교환발송완료", "교환수거완료", "교환신청취소",
    "교환완료(교환됨)", "교환완료[COMPLETE_DELIVERY]",
    "교환진행[COMPLETE_DIRECTION]", "교환진행[DELIVERING]",
    "교환취소[WITHDRAW]",
    "반품신청", "반품완료", "반품완료(반품)",
    "반품완료[배송완료]", "반품완료[배송지시]",
    "반품요청", "반품접수[배송완료]",
    "직권취소(취소)",
    "철회(배송)", "철회(배송구매의사 없어짐)", "철회(배송판매자 취소(품절))",
    "출고중지완료[상품준비중]",
    "취소거부",
    "취소된거래", "취소완료",
    "취소완료(미결제)", "취소완료(배송)",
    "취소완료(배송가격오등록)", "취소완료(배송구매의사 없어짐)",
    "취소완료(배송자동 접수(요청 정책 접수))",
    "취소완료(배송판매자 취소(고객변심))",
    "취소완료(배송판매자 취소(품절))",
    "취소완료(취소)",
    "환불승인완료",
    "회수완료", "회수지시",
}

SETTLEMENT_X_EXCEPT_TO_O = {
    "RETURN_REJECT(구매확정)",
    "취소철회(구매확정)",
    "취소철회(배송완료)",
}

SETTLEMENT_REVERT_KEYWORDS = [
    "(구매확정)", "취소철회(구매확정)", "취소철회(배송완료)",
    "반품철회", "반품 철회", "교환철회",
    "취소후배송", "취소후재배송", "취소후재발송",
    "취소신청취소", "반품신청취소",
    "철회완료", "정상화", "재발송완료",
]

MEMO_SETTLE_OK_KEYWORDS = [
    "거부 후 발송", "거부후 발송", "거부 후 배송",
    "발송처리", "발송 처리", "재발송", "정상 발송",
]
MEMO_SETTLE_CANCEL_KEYWORDS = [
    "취소승인", "취소 승인", "취소처리", "취소 처리",
    "직접 취소", "직권 취소", "결국 취소", "주문취소",
    "고객 취소", "취소 완료", "취소완료",
]
MEMO_SETTLE_RETURN_KEYWORDS = [
    "반품완료", "반품 완료", "반품처리", "반품 처리",
    "결국 반품", "반품 함", "반품했",
]
MEMO_TRIGGER_STATUSES = ["취소거부", "직권취소"]

SETTLEMENT_CANCEL_KEYWORDS = [
    "취소완료", "취소된거래", "취소요청",
    "주문취소", "결제취소", "거래취소",
    "출고중지완료",
    "구매의사 없어짐", "판매자 취소",
    "품절취소", "품절로취소",
]
SETTLEMENT_RETURN_KEYWORDS = [
    "반품완료", "반품요청", "반품접수",
    "수거중", "수거완료",
    "회수지시", "회수완료", "회수진행", "회수중",
    "환불승인완료", "환불완료",
    "철회(배송)",
    "반품요청(배송완료)", "수거중(배송완료)",
]
SETTLEMENT_EXCHANGE_KEYWORDS = [
    "교환완료", "교환발송완료", "교환수거완료",
]
SETTLEMENT_OK_KEYWORDS = [
    "확정", "정산완료", "정산예정", "수취완료", "구매확정",
    "배송완료", "배송중", "발송완료", "발송대기", "상품준비",
    "배송준비중",
]

# ── 블랙스팟 프로그램의 블랙스팟 마켓명 매핑 (중복되지만 블랙스팟 분류에서 사용) ──
BLACKSPOT_MARKET_MAP = {
    "11번가":       "03.11번가",
    "G마켓2.0":     "01.지마켓",
    "옥션2.0":      "02.옥션",
    "스마트스토어": "04.스마트스토어",
    "쿠팡":         "06.쿠팡",
    "롯데ON":       "18.롯데온",
}

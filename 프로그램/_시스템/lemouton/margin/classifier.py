# -*- coding: utf-8 -*-
"""탭1 분류 엔진. 5대분류 × 49개 상세 케이스.

(매입상태, 배송상태, 정산상태) 조합을 룩업 테이블로 매핑.
블랙스팟 프로그램의 modules/classifier_tab1.py 에서 포팅.
"""
import logging
from datetime import datetime

import pandas as pd

from lemouton.margin.config import (
    MANGO_COLS, SHOPMINE_COLS,
    MEMO_SKIP_CODES,
    MANGO_PENDING_STATUSES, MANGO_KKADAEGI_STATUSES,
    MARKET_STATUS_FAIL,
    SETTLEMENT_O_EXACT, SETTLEMENT_X_EXACT, SETTLEMENT_X_EXCEPT_TO_O,
    SETTLEMENT_REVERT_KEYWORDS,
    SETTLEMENT_CANCEL_KEYWORDS, SETTLEMENT_RETURN_KEYWORDS,
    SETTLEMENT_EXCHANGE_KEYWORDS, SETTLEMENT_OK_KEYWORDS,
    MEMO_SETTLE_OK_KEYWORDS, MEMO_SETTLE_CANCEL_KEYWORDS,
    MEMO_SETTLE_RETURN_KEYWORDS, MEMO_TRIGGER_STATUSES,
    STALE_DAYS,
)

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 룩업 테이블: (매입, 배송, 정산) → (대분류, 상세코드, 판단)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLASSIFICATION_MAP = {
    # 대분류 1: 매입O
    ("O", "O", "O"):        ("1_매입O", "1-1", "정상거래"),
    # 1-2, 1-3 은 margin_checker 에서 후처리 (마진율 기준)
    ("O", "O", "X_취소"):   ("1_매입O", "1-4", "블랙스팟(매입O+취소)"),
    ("O", "O", "X_반품"):   ("1_매입O", "1-5", "블랙스팟(매입O+반품)"),
    ("O", "O", "X_미매칭"): ("1_매입O", "1-6", "데이터누락"),
    ("O", "X", "O"):        ("1_매입O", "1-7", "배송누락"),
    ("O", "X", "X_취소"):   ("1_매입O", "1-8", "매입후취소"),
    ("O", "X", "X_반품"):   ("1_매입O", "1-9", "매입후반품"),
    ("O", "X", "X_미매칭"): ("1_매입O", "1-10", "이상건"),

    # 대분류 2: 매입O(불완전)
    ("O_불완전", "O", "O"):        ("2_매입O(불완전)", "2-1", "매입가미입력(정산O)"),
    ("O_불완전", "O", "X_취소"):   ("2_매입O(불완전)", "2-2", "블랙스팟의심(흔적O+취소)"),
    ("O_불완전", "O", "X_반품"):   ("2_매입O(불완전)", "2-3", "블랙스팟의심(흔적O+반품)"),
    ("O_불완전", "O", "X_미매칭"): ("2_매입O(불완전)", "2-4", "데이터미비+샵마인누락"),
    ("O_불완전", "X", "O"):        ("2_매입O(불완전)", "2-5", "배송누락+데이터미비"),
    ("O_불완전", "X", "X_취소"):   ("2_매입O(불완전)", "2-6", "매입흔적+취소"),
    ("O_불완전", "X", "X_반품"):   ("2_매입O(불완전)", "2-7", "매입흔적+반품"),
    ("O_불완전", "X", "X_미매칭"): ("2_매입O(불완전)", "2-8", "이상건+데이터미비"),

    # 대분류 3: 매입X(사유O)
    ("X_사유O", "X", "X_취소"):   ("3_매입X(사유O)", "3-1", "정상(PS+취소)"),
    ("X_사유O", "X", "X_반품"):   ("3_매입X(사유O)", "3-2", "정상(PS+반품)"),
    ("X_사유O", "X", "O"):        ("3_매입X(사유O)", "3-3", "이상(PS인데정산O)"),
    ("X_사유O", "O", "O"):        ("3_매입X(사유O)", "3-4", "이상(PS인데배송+정산O)"),
    ("X_사유O", "O", "X_취소"):   ("3_매입X(사유O)", "3-5", "이상(PS인데배송O+취소)"),
    ("X_사유O", "O", "X_반품"):   ("3_매입X(사유O)", "3-6", "이상(PS인데배송O+반품)"),
    ("X_사유O", "X", "X_미매칭"): ("3_매입X(사유O)", "3-7", "확인필요"),
    ("X_사유O", "O", "X_미매칭"): ("3_매입X(사유O)", "3-8", "이상"),

    # 대분류 4: 매입X(불명)
    ("X_불명", "X", "X_취소"):   ("4_매입X(불명)", "4-1", "소싱전취소"),
    ("X_불명", "X", "X_반품"):   ("4_매입X(불명)", "4-2", "반품(소싱여부불명)"),
    ("X_불명", "X", "O"):        ("4_매입X(불명)", "4-3", "이상(매입X인데정산O)"),
    ("X_불명", "O", "O"):        ("4_매입X(불명)", "4-4", "이상(매입불명+배송+정산)"),
    ("X_불명", "O", "X_취소"):   ("4_매입X(불명)", "4-5", "이상(매입불명+배송+취소)"),
    ("X_불명", "O", "X_반품"):   ("4_매입X(불명)", "4-6", "이상(매입불명+배송+반품)"),
    ("X_불명", "X", "X_미매칭"): ("4_매입X(불명)", "4-7", "유령건"),
    ("X_불명", "O", "X_미매칭"): ("4_매입X(불명)", "4-8", "이상(매입불명+배송+샵마인없음)"),
}

# 발송대기: 매입상태별 (정산 무시)
PENDING_MAP = {
    "O":         ("1_매입O",         "1-11", "발송대기"),
    "O_불완전":  ("2_매입O(불완전)", "2-9",  "발송대기"),
    "X_사유O":   ("3_매입X(사유O)",  "3-9",  "발송대기(마켓취소필요)"),
}

# 까대기: 해외현지배송중 (사무실 입고 후 고객 발송 예정) — 정산 무시
KKADAEGI_MAP = {
    "O":         ("1_매입O",         "1-12", "까대기(정상)"),
    "O_불완전":  ("2_매입O(불완전)", "2-10", "까대기(매입불완전)"),
    "X_사유O":   ("3_매입X(사유O)",  "3-10", "까대기(미이행-사유O)"),
    "X_불명":    ("4_매입X(불명)",   "4-10", "까대기(매입불명)"),
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 확인사항 룩업: 상세코드 → (소싱처확인, 마켓확인, 확인사항)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHECK_INFO = {
    "1-1":  (False, False, ""),
    "1-2":  (True,  False,
             "[문제] 마진율 30%+, 마진 5천원+ → 구매가격 오입력 또는 정산금액 이상 가능\n"
             "[확인] 소싱처: 간단메모URL → 실제 결제금액 확인\n"
             "[대응] 구매가격 틀리면 더망고 G/H열 수정"),
    "1-3":  (True,  False,
             "[문제] 마진율 0% 미만 → 팔수록 손해. 구매가격 오입력 또는 할인 미적용\n"
             "[확인] 소싱처: 간단메모URL → 실제 결제금액 확인\n"
             "[대응] 실제 역마진이면 해당 상품 판매가 조정 필요"),
    "1-4":  (True,  True,
             "[문제] 소싱처 매입+배송 완료했으나 마켓에서 취소 → 매입비 손실 가능\n"
             "[확인1] 소싱처: 간단메모URL → 반품/환불 신청 여부\n"
             "[확인2] 마켓: 취소 사유 확인 (고객변심/품절/가격오류)\n"
             "[대응] 소싱처 환불 미처리 시 → 즉시 반품 신청"),
    "1-5":  (True,  True,
             "[문제] 소싱처 매입+배송 완료했으나 고객이 반품 → 매입비 손실 가능\n"
             "[확인1] 소싱처: 간단메모URL → 반품 회수/환불 처리 상태\n"
             "[확인2] 마켓: 반품 사유, 환불 진행 상태\n"
             "[대응] 소싱처 반품 미접수 시 → 즉시 반품 신청, 회수 확인"),
    "1-6":  (False, True,
             "[문제] 매입+배송 완료했는데 샵마인에 주문기록 없음 → 정산 누락 가능\n"
             "[확인] 마켓: 해당 주문번호로 마켓에 직접 검색 → 주문 존재 여부\n"
             "[대응] 샵마인 동기화 오류면 재동기화, 마켓에서 삭제되었으면 CS 확인"),
    "1-7":  (True,  False,
             "[문제] 매입+정산은 되는데 송장번호가 없음 → 배송 안 됐거나 송장 미입력\n"
             "[확인] 소싱처: 간단메모URL → 소싱처에서 발송했는지, 송장번호 확인\n"
             "[대응] 발송됐으면 더망고에 송장 입력, 미발송이면 소싱처에 발송 요청"),
    "1-8":  (True,  False,
             "[문제] 매입했는데 마켓 취소됨, 배송도 안 됨 → 소싱처 환불 필요\n"
             "[확인] 소싱처: 간단메모URL → 주문취소/환불 처리 여부\n"
             "[대응] 소싱처 취소 미처리 시 → 즉시 주문취소 요청"),
    "1-9":  (True,  False,
             "[문제] 매입했는데 마켓 반품됨, 배송 안 됨 → 소싱처 환불 필요\n"
             "[확인] 소싱처: 간단메모URL → 반품/환불 처리 상태\n"
             "[대응] 소싱처에 반품 접수, 환불 확인"),
    "1-10": (True,  True,
             "[문제] 매입했는데 샵마인 미매칭+배송 안 됨 → 주문 자체 의심\n"
             "[확인1] 소싱처: 간단메모URL → 주문상태 확인\n"
             "[확인2] 마켓: 주문번호로 마켓 직접 검색\n"
             "[대응] 마켓에 주문 없으면 소싱처 취소, 있으면 샵마인 동기화"),
    "1-11": (False, False, "정상 프로세스 진행중 (매입 완료, 배송 대기)"),
    "1-12": (False, False, "정상 까대기 진행중 (매입 완료, 해외 현지 배송 중 → 사무실 입고 후 발송 예정)"),

    "2-1":  (True,  False,
             "[문제] 배송+정산 정상이나 더망고에 구매가격/주문번호 미입력 → 마진 계산 불가\n"
             "[확인] 소싱처: 간단메모URL → 실제 구매가격 확인\n"
             "[대응] 더망고 G열(주문번호), H열(구매가격) 보완 입력"),
    "2-2":  (True,  True,
             "[문제] 매입 흔적만 있고 마켓 취소됨 → 손실액 파악 불가\n"
             "[확인1] 소싱처: 간단메모URL → 실제 결제금액, 환불 여부\n"
             "[확인2] 마켓: 취소 사유\n"
             "[대응] 소싱처 환불 확인 후 더망고 정보 보완"),
    "2-3":  (True,  True,
             "[문제] 매입 흔적만 있고 고객이 반품 → 손실액 파악 불가\n"
             "[확인1] 소싱처: 간단메모URL → 반품/환불 처리 상태\n"
             "[확인2] 마켓: 반품 사유\n"
             "[대응] 소싱처 반품 접수 확인 후 더망고 정보 보완"),
    "2-4":  (True,  True,
             "[문제] 매입 흔적만 있고 샵마인에도 없음 → 주문 자체 의심\n"
             "[확인1] 소싱처: 간단메모URL → 매입 실제 여부\n"
             "[확인2] 마켓: 주문 존재 여부\n"
             "[대응] 확인 후 더망고 정보 보완 또는 정리"),
    "2-5":  (False, True,
             "[문제] 정산 O인데 송장 없음 + 더망고 정보 미비 → 배송 누락 가능\n"
             "[확인] 마켓: 실제 배송 상태\n"
             "[대응] 배송 완료면 더망고 송장 입력, 미배송이면 조치"),
    "2-6":  (True,  False,
             "[문제] 매입 흔적+미배송+취소 → 매입 실제로 했는지 불확실\n"
             "[확인] 소싱처: 간단메모URL → 매입/취소 처리 확인\n"
             "[대응] 매입했다면 소싱처 환불"),
    "2-7":  (True,  False,
             "[문제] 매입 흔적+미배송+반품 → 매입 실제로 했는지 불확실\n"
             "[확인] 소싱처: 간단메모URL → 매입/반품 처리 확인\n"
             "[대응] 매입했다면 소싱처 환불"),
    "2-8":  (True,  True,
             "[문제] 매입 흔적+미배송+샵마인 미매칭 → 전체 추적 불가\n"
             "[확인1] 소싱처: 매입 여부 확인\n"
             "[확인2] 마켓: 주문 존재 여부\n"
             "[대응] 확인 후 정리"),
    "2-9":  (False, False, "정상 프로세스 진행중 (매입 흔적 있음, 배송 대기)"),
    "2-10": (True,  False,
             "[문제] 까대기 진행중인데 더망고 매입 정보 불완전 → 마진 계산 불가\n"
             "[확인] 소싱처: 간단메모URL → 실제 구매가격/주문번호 확인\n"
             "[대응] 더망고 G열(주문번호), H열(구매가격) 보완 입력"),

    "3-1":  (False, False, "정상 프로세스 — 미이행 사유(S/P/x 등)로 인한 취소, 매입하지 않음"),
    "3-2":  (False, False, "정상 프로세스 — 미이행 사유로 인한 반품, 매입하지 않음"),
    "3-3":  (False, True,
             "[문제] 미이행 사유인데 정산 O → 이상. 실제로는 다른 경로 이행했을 수 있음\n"
             "[확인] 마켓: 실제 이행 경로 확인\n"
             "[대응] 이행했다면 더망고 정보 보완"),
    "3-4":  (False, True,
             "[문제] 미이행 사유인데 배송+정산 O → 이상\n"
             "[확인] 마켓: 이행 경로\n"
             "[대응] 더망고 정보 보완"),
    "3-5":  (True,  True,
             "[문제] 미이행 사유인데 배송 O + 취소 → 이상\n"
             "[확인1] 소싱처: 실제 매입·배송 여부\n"
             "[확인2] 마켓: 취소 사유\n"
             "[대응] 매입했다면 소싱처 환불"),
    "3-6":  (True,  True,
             "[문제] 미이행 사유인데 배송 O + 반품 → 이상\n"
             "[확인1] 소싱처: 매입·반품 처리\n"
             "[확인2] 마켓: 반품 사유\n"
             "[대응] 매입했다면 소싱처 반품 처리"),
    "3-7":  (False, True,
             "[문제] 미이행 사유 + 미배송 + 샵마인 미매칭 → 정상 취소 대기 상태일 수 있음\n"
             "[확인] 마켓: 주문 존재 여부\n"
             "[대응] 마켓에 있으면 즉시 취소 처리"),
    "3-8":  (False, True,
             "[문제] 미이행 사유 + 배송 O + 샵마인 미매칭 → 배송된 경로 불명\n"
             "[확인] 마켓: 배송 이력\n"
             "[대응] 확인 후 정리"),
    "3-9":  (False, True,
             "[문제] S/P 미이행으로 결정했는데 마켓에서 아직 취소 안 됨\n"
             "[확인] 마켓: 주문 상태 확인\n"
             "[대응] 마켓에서 즉시 취소 처리 필요"),
    "3-10": (False, True,
             "[문제] 미이행 사유 있는데 더망고가 해외현지배송중 → 이상 케이스\n"
             "[확인] 마켓: 주문 취소 처리 여부\n"
             "[대응] 소싱처 취소 및 마켓 취소 처리"),

    "4-1":  (False, False,
             "[문제] 매입 기록도 미이행 사유도 없이 취소됨 → 사유 불명\n"
             "[확인] 더망고: 해당 주문 검색 → 왜 미이행했는지 담당자 확인\n"
             "[대응] 정상 취소건이면 OK, 아니면 사유 기록"),
    "4-2":  (True,  False,
             "[문제] 매입 기록 없이 반품됨 → 매입 후 내역 삭제했을 가능성\n"
             "[확인] 소싱처: 더망고에서 주문 검색 → 간단메모/주문이력 확인\n"
             "[대응] 실제 매입했다면 소싱처 반품/환불 처리 확인"),
    "4-3":  (False, True,
             "[문제] 매입 기록 없는데 정산됨 → 다른 경로로 이행했을 수 있음\n"
             "[확인] 마켓: 주문 이력, 배송 이력 확인\n"
             "[대응] 다른 소싱처 이행건이면 더망고 정보 보완"),
    "4-4":  (True,  False,
             "[문제] 매입 기록 없는데 배송+정산 됨 → 내역 삭제 관행 가능성 높음\n"
             "[확인] 소싱처: 더망고에서 주문 검색 → 누가 주문했는지 확인\n"
             "[대응] 매입 정보 복원 (더망고 G/H/N열 보완)"),
    "4-5":  (True,  True,
             "[문제] 매입 기록 없이 배송됨+취소 → 손실 가능성, 확인 불가\n"
             "[확인1] 소싱처: 더망고 주문 검색 → 매입 여부\n"
             "[확인2] 마켓: 취소 사유\n"
             "[대응] 매입했다면 소싱처 환불 처리"),
    "4-6":  (True,  True,
             "[문제] 매입 기록 없이 배송됨+반품 → 손실 가능성, 확인 불가\n"
             "[확인1] 소싱처: 더망고 주문 검색 → 매입 여부\n"
             "[확인2] 마켓: 반품 사유\n"
             "[대응] 매입했다면 소싱처 반품/환불 처리"),
    "4-7":  (False, True,
             "[문제] 더망고에만 주문 흔적, 샵마인 미매칭, 매입/배송 기록 없음\n"
             "[확인] 마켓: 주문번호로 마켓에 직접 검색 → 주문 존재 여부\n"
             "[대응] 마켓에 없으면 유령건으로 정리, 있으면 처리 필요"),
    "4-8":  (True,  True,
             "[문제] 매입불명+배송됨+샵마인 미매칭 → 전체 추적 불가\n"
             "[확인1] 소싱처: 더망고 주문 검색 → 매입/배송 확인\n"
             "[확인2] 마켓: 주문 존재 여부\n"
             "[대응] 전방위 데이터 확인 후 정리"),
    "4-9":  (False, True,
             "[문제] 매입 기록 없이 발송대기 상태 → 이행할지 취소할지 판단 필요\n"
             "[확인] 마켓: 주문 상태, 재고/가격 확인\n"
             "[대응] 이행 가능하면 주문 진행, 불가하면 마켓 취소"),
    "4-10": (True,  True,
             "[문제] 매입 기록 없는데 해외현지배송중 → 누가 주문한 건지 확인 불가\n"
             "[확인1] 소싱처: 더망고 주문 검색 → 매입 여부\n"
             "[확인2] 마켓: 주문 상태\n"
             "[대응] 매입 정보 복원 또는 취소 처리"),

    "5-1":  (False, False, "송장전송실패 + 정산 정상 → 중복 전송 시도였을 가능성 (정상)"),
    "5-2":  (False, False, "송장전송실패 + 취소건 → 이미 취소된 건에 송장 시도 (정상)"),
    "5-3":  (False, False, "송장전송실패 + 반품건 → 이미 반품된 건에 송장 시도 (정상)"),
    "5-4":  (False, True,
             "[문제] 송장전송실패 + 샵마인 미매칭 → 주문 자체 확인 필요\n"
             "[확인] 마켓: 주문번호로 검색\n"
             "[대응] 마켓에 주문 있으면 송장 재전송"),
    "5-5":  (False, True,
             "[문제] 결제완료 후 7일+ 미처리 → 마켓 취소 위험\n"
             "[확인] 마켓: 주문 상태, 자동취소 임박 여부\n"
             "[대응] 즉시 이행 또는 취소 결정"),
    "5-6":  (False, True,
             "[문제] 샵마인에만 있고 더망고에 없음 → 더망고 누락 또는 다른 경로 주문\n"
             "[확인] 마켓: 주문 경로 확인 (더망고 외 채널?)\n"
             "[대응] 더망고에서 해당 주문 검색, 누락이면 등록"),
    "5-7":  (False, False, "샵마인에만 있는 취소/반품건 → 더망고에서 삭제되었을 가능성 (정상)"),
    "5-8":  (False, False, "샵마인에만 있는 반품건 → 반품 처리 후 더망고에서 삭제됨 (정상)"),
}


def _get_check_info(detail_code: str) -> tuple:
    """상세코드 → (소싱처확인필요, 마켓확인필요, 확인사항)."""
    return CHECK_INFO.get(detail_code, (False, False, ""))


def _assign_category(purchase: str, delivery: str, settlement: str) -> tuple:
    """(매입, 배송, 정산) 조합으로 대분류 + 상세코드 + 판단 배정."""
    if delivery == "까대기":
        if purchase in KKADAEGI_MAP:
            return KKADAEGI_MAP[purchase]
        return ("4_매입X(불명)", "4-10", "까대기(매입불명)")

    if delivery == "발송대기":
        if purchase in PENDING_MAP:
            return PENDING_MAP[purchase]
        return ("4_매입X(불명)", "4-9", "발송대기")

    key = (purchase, delivery, settlement)
    if key in CLASSIFICATION_MAP:
        return CLASSIFICATION_MAP[key]

    logger.warning(f"미매핑 조합: P={purchase}, D={delivery}, S={settlement}")
    return ("4_매입X(불명)", "4-7", f"미분류(P={purchase}_D={delivery}_S={settlement})")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 매입 상태 판단
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _determine_purchase_status(row: dict) -> str:
    """매입 이행 여부 판단.

    O:        사이트주문번호 + 구매가격 + 간단메모 URL 3개 모두
    O_불완전: 위 3개 중 일부만 (미이행 사유코드 아닌 경우)
    X_사유O:  G/H 없고 간단메모에 S/P/x/ㄴㄴ/ㅔ/ㅍㅈ 등
    X_불명:   G/H 없고 간단메모 비어있음
    """
    site_order = str(row.get(MANGO_COLS["site_order_no"], "")).strip()
    price      = float(row.get(MANGO_COLS["purchase_price"], 0) or 0)
    memo       = str(row.get(MANGO_COLS["memo"], "")).strip()

    has_site_order = bool(site_order) and site_order not in ("0", "nan", "None")
    has_price      = price > 0
    has_url        = any(tok in memo.lower() for tok in ("http", "www.", ".com", ".kr", ".co.kr"))

    if memo in MEMO_SKIP_CODES:
        return "X_사유O"
    if has_site_order and has_price and has_url:
        return "O"
    if has_site_order or has_price or has_url:
        return "O_불완전"
    return "X_불명"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 배송 상태 판단
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _determine_delivery_status(row: dict) -> str:
    """배송 여부 판단.

    발송대기: 더망고주문상태 = 결제완료 or 배송대기중
    O:        국내송장번호 존재
    X:        송장번호 없음
    """
    mango_status = str(row.get(MANGO_COLS["mango_status"], "")).strip()
    tracking     = str(row.get(MANGO_COLS["tracking"], "")).strip()

    if mango_status in MANGO_KKADAEGI_STATUSES:
        return "까대기"
    if mango_status in MANGO_PENDING_STATUSES:
        return "발송대기"
    if tracking and tracking not in ("", "0", "nan", "None"):
        return "O"
    return "X"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메모 오버라이드 — 애매한 주문상태일 때 메모에서 최종 판정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _memo_override(status: str, memos: list) -> str:
    """메모 기반 오버라이드 — '취소거부'·'직권취소' 등 애매한 상태에서만 적용.

    우선순위: OK(발송처리) > RETURN(반품처리) > CANCEL(취소처리)
    Returns: 'O' / 'X_취소' / 'X_반품' / '' (결정 불가)
    """
    is_trigger = any(t in status for t in MEMO_TRIGGER_STATUSES)
    if not is_trigger:
        return ""
    combined = " ".join(str(m or "") for m in memos)
    for kw in MEMO_SETTLE_OK_KEYWORDS:
        if kw in combined:
            return "O"
    for kw in MEMO_SETTLE_RETURN_KEYWORDS:
        if kw in combined:
            return "X_반품"
    for kw in MEMO_SETTLE_CANCEL_KEYWORDS:
        if kw in combined:
            return "X_취소"
    return "X_취소"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 정산 상태 판단
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _determine_settlement_status(row: dict) -> str:
    """정산/매칭 여부 판단.

    O:        매칭됨 + 정상 정산 상태
    X_취소:   매칭됨 + 취소 키워드
    X_반품:   매칭됨 + 반품 키워드
    X_미매칭: 샵마인 매칭 안됨
    """
    if not row.get("샵마인_매칭", False):
        return "X_미매칭"

    # 최우선 0: 정상건 존재 플래그
    if row.get("샵마인_정상건존재", False):
        return "O"

    shopmine_status = str(
        row.get(f"샵마인_{SHOPMINE_COLS['order_status']}", "")
    ).strip()

    if shopmine_status in SETTLEMENT_O_EXACT:
        return "O"
    if shopmine_status in SETTLEMENT_X_EXCEPT_TO_O:
        return "O"
    for kw in SETTLEMENT_REVERT_KEYWORDS:
        if kw in shopmine_status:
            return "O"

    # 2순위: 애매한 상태 → 메모 오버라이드
    memos = [
        row.get(f"샵마인_{SHOPMINE_COLS.get('shopmine_status', '샵마인주문상태')}", ""),
        row.get("샵마인_메모", ""),
        row.get("샵마인_판매처", ""),
        row.get(MANGO_COLS.get("memo", "간단메모"), ""),
    ]
    memo_result = _memo_override(shopmine_status, memos)
    if memo_result:
        return memo_result

    if shopmine_status in SETTLEMENT_X_EXACT:
        if any(kw in shopmine_status for kw in ["반품", "회수", "환불", "수거"]):
            return "X_반품"
        if any(kw in shopmine_status for kw in ["교환"]):
            return "X_반품"
        return "X_취소"

    for kw in SETTLEMENT_CANCEL_KEYWORDS:
        if kw in shopmine_status:
            return "X_취소"
    for kw in SETTLEMENT_RETURN_KEYWORDS:
        if kw in shopmine_status:
            return "X_반품"
    for kw in SETTLEMENT_EXCHANGE_KEYWORDS:
        if kw in shopmine_status:
            return "O"

    return "O"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 교차검증 (대분류 5)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _cross_validate(row: dict, settlement: str):
    """5-1 ~ 5-5 교차검증 플래그."""
    market_status  = str(row.get(MANGO_COLS["market_status"], "")).strip()
    mango_status   = str(row.get(MANGO_COLS["mango_status"], "")).strip()
    order_date_raw = row.get(MANGO_COLS["order_date"], "")

    if market_status == MARKET_STATUS_FAIL:
        if settlement == "O":
            return "5-1_송장전송실패+정산O(정상가능)"
        elif settlement == "X_취소":
            return "5-2_송장전송실패+취소(정상)"
        elif settlement == "X_반품":
            return "5-3_송장전송실패+반품"
        else:
            return "5-4_송장전송실패+미매칭(확인필요)"

    if mango_status in MANGO_PENDING_STATUSES:
        try:
            if order_date_raw:
                order_date = pd.Timestamp(order_date_raw)
                if pd.notna(order_date):
                    days = (pd.Timestamp.now() - order_date).days
                    if days >= STALE_DAYS:
                        return f"5-5_장기미처리({days}일)"
        except Exception:
            pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 샵마인만 있는 행 정산 분류 (5-6, 5-7, 5-8)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _classify_shopmine_only(row: dict) -> tuple:
    shopmine_status = str(row.get(SHOPMINE_COLS["order_status"], "")).strip()

    is_reverted = any(kw in shopmine_status for kw in SETTLEMENT_REVERT_KEYWORDS)
    is_cancel   = any(kw in shopmine_status for kw in SETTLEMENT_CANCEL_KEYWORDS)
    is_return   = any(kw in shopmine_status for kw in SETTLEMENT_RETURN_KEYWORDS)
    is_exchange = any(kw in shopmine_status for kw in SETTLEMENT_EXCHANGE_KEYWORDS)

    if is_reverted:
        return ("5-6", "더망고누락(정산O/철회복구)")
    if is_cancel:
        return ("5-7", "더망고누락+취소건")
    if is_return or is_exchange:
        return ("5-8", "더망고누락+반품건")
    return ("5-6", "더망고누락(정산O)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인 분류 함수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def classify(matched: list, mango_unmatched: list, shopmine_only: list) -> dict:
    """탭1 전체 분류 실행.

    Returns:
        {
            "classified": list[dict],  # 각 행에 분류 필드 추가
            "summary":    dict,        # 대분류 > 상세분류별 건수
        }
    """
    classified = []

    for row in matched + mango_unmatched:
        purchase   = _determine_purchase_status(row)
        delivery   = _determine_delivery_status(row)
        settlement = _determine_settlement_status(row)

        major, detail_code, detail_label = _assign_category(purchase, delivery, settlement)
        sourcing_chk, market_chk, note = _get_check_info(detail_code)
        cross = _cross_validate(row, settlement)

        row["매입상태"]       = purchase
        row["배송상태"]       = delivery
        row["정산상태"]       = settlement
        row["대분류"]         = major
        row["상세분류"]       = f"{detail_code}_{detail_label}"
        row["소싱처확인필요"] = sourcing_chk
        row["마켓확인필요"]   = market_chk
        row["확인사항"]       = note
        row["교차검증"]       = cross
        row["데이터출처"]     = "더망고+샵마인" if row.get("샵마인_매칭", False) else "더망고만"
        classified.append(row)

    for row in shopmine_only:
        detail_code, detail_label = _classify_shopmine_only(row)
        sourcing_chk, market_chk, note = _get_check_info(detail_code)

        row["매입상태"]       = "확인불가"
        row["배송상태"]       = "확인불가"
        row["정산상태"]       = "샵마인만"
        row["대분류"]         = "5_교차검증"
        row["상세분류"]       = f"{detail_code}_{detail_label}"
        row["소싱처확인필요"] = sourcing_chk
        row["마켓확인필요"]   = market_chk
        row["확인사항"]       = note
        row["교차검증"]       = None
        row["데이터출처"]     = "샵마인만"
        classified.append(row)

    # 요약 통계
    summary = {}
    for row in classified:
        major  = row.get("대분류", "미분류")
        detail = row.get("상세분류", "미분류")
        summary.setdefault(major, {})
        summary[major][detail] = summary[major].get(detail, 0) + 1

    logger.info(f"탭1 분류 완료: 총 {len(classified)}건")
    return {"classified": classified, "summary": summary}

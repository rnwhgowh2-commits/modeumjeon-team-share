# -*- coding: utf-8 -*-
"""결제카드 마스터(PurchaseCard) 저장소 + 시드.

적립율의 단일 진실 원천. 값은 영빈 「대량위탁」 관리엑셀에서 확정된 실제 값이며
지어내지 않는다 — 새 카드가 필요하면 엑셀에 먼저 확정한 뒤 SEED 에 추가한다.

■ 시드 멱등 방식: **key 단위 insert-if-missing (기존 행은 절대 덮지 않음)**
  근거 ① 사용자 수정 보존 — 화면에서 적립율/표시명을 고친 뒤 앱을 재시작하면
        시드가 다시 도는데, upsert 면 그 수정이 매 부팅마다 조용히 원복된다.
        (금액 계산 입력값이 사용자 모르게 되돌아가는 = 이 저장소가 가장 경계하는
         '조용한 실패')
  근거 ② 코드베이스 관례 일치 — source_registry.seed_builtins() 는 "이미
        source_key 가 있으면 skip → 라벨·로고 사용자 수정분 보존", keyword_store 는
        "행이 없을 때만 시드", MarketRegistry 시드는 count()==0 일 때만 삽입.
        전부 insert-if-missing 이고 upsert 시드는 이 저장소에 하나도 없다.
  근거 ③ count()==0 게이트가 아니라 **key 단위**로 도는 이유 — 나중에 카드를
        한 장 추가했을 때 count()>0 이라 신규 카드가 영영 안 들어오는 일을 막는다
        (seed_builtins 와 같은 이유로 같은 선택).

■ 범위 방어: 클램프가 아니라 ValueError.
  0~1 밖의 적립율은 입력 사고(2.7 을 2.7% 로 착각 등)다. 조용히 1.0 으로 깎으면
  "에러 없이 틀린 금액"이 나와 매입가가 오염된다. lemouton/inventory/cogs.py 의
  `raise ValueError(f"qty_in must be positive, got {qty_in}")` 와 같은 관례.
"""
from __future__ import annotations

from lemouton.margin.models import PurchaseCard

# (key, label, accrual_rate, is_hyundai_default) — 순서가 곧 화면 표시 순서.
#
# ■ key 는 왜 이렇게 짧은가 — 진짜 제약은 PurchaseCard.key 가 아니다.
#   PurchaseCard.key 자체는 String(64) 라 여유가 많다. 하지만 소싱처별 카드
#   청구할인은 ``SourceBenefitTemplate.pay_method = <PurchaseCard.key>`` 로 이
#   카드를 가리키고(card_candidates.py 가 실제로 ``pay_method=c.key``), 그
#   **pay_method 가 VARCHAR(16)** 이다(sourcing/models.py 의 두 테이블 모두).
#   → 16자를 넘는 key 를 만들면 그 카드는 청구할인 행을 저장할 수 없다.
#
#   그리고 이건 개발기에서 절대 안 잡힌다: .env 없는 개발 워크트리는 SQLite 로
#   뜨는데 SQLite 는 VARCHAR 길이를 강제하지 않아 조용히 통과하고, 라이브
#   (Supabase PostgreSQL)에서만 저장이 깨진다. 폭을 넓히는 것도 답이 아니다 —
#   shared/db.py 의 _apply_lightweight_migrations() 에는 ADD COLUMN 밖에 없어
#   **컬럼 폭 확장 경로가 아예 없다**.
#
#   → 새 카드를 추가할 때 key 는 반드시 16자 이하로. 어기면
#     test_seed_keys_fit_pay_method_column 이 잡는다(폭은 모델에서 읽어오므로
#     나중에 pay_method 가 넓어지면 테스트가 자동으로 따라간다).
PURCHASE_CARD_SEED: list[tuple[str, str, float, bool]] = [
    ("nexon_hyundai",        "넥슨현대카드",         0.027, True),
    ("lotte_prof",           "롯데프로페셔널",       0.02,  False),
    ("lotte_liiv",           "롯데 라이키",          0.015, False),
    ("kbank",                "케이뱅크",             0.011, False),
    ("samsung_select",       "삼성셀렉트",           0.01,  False),
    ("bc_baro",              "BC바로",               0.01,  False),
    ("musinsa_hyundai",      "무신사현대",           0.0,   True),
    ("shinhan",              "신한카드",             0.0,   False),
    ("hana",                 "하나카드",             0.0,   False),
    ("kookmin",              "국민카드",             0.0,   False),
    ("kb_pay",               "KB PAY",               0.0,   False),
    ("kakao_money",          "카카오뱅크(머니)",     0.0,   False),
    ("toss_money",           "토스페이(머니)",       0.0,   False),
    ("mus_money",            "무신사머니",           0.0,   False),
    ("mus_money_black",      "무신사머니(블랙)",     0.0,   False),
    ("mus_money_dia",        "무신사머니(다이아)",   0.0,   False),
    ("mus_money_plgold",     "무신사머니(플골)",     0.0,   False),
]


def validate_accrual_rate(rate) -> float:
    """적립율 0~1 검증. 벗어나면 ValueError — 클램프하지 않는다.

    클램프는 잘못된 입력을 '에러 없이 틀린 금액'으로 바꿔 매입가를 오염시킨다.
    """
    try:
        r = float(rate)
    except (TypeError, ValueError):
        raise ValueError(f"accrual_rate 는 숫자여야 합니다 — 받은 값: {rate!r}")
    if r != r:  # NaN — 비교 연산이 전부 False 라 아래 범위 검사를 그대로 통과한다.
        raise ValueError("accrual_rate 가 NaN 입니다")
    if r < 0.0 or r > 1.0:
        raise ValueError(
            f"accrual_rate 는 0~1 이어야 합니다 (0.027 = 2.7%) — 받은 값: {r}")
    return r


def seed_purchase_cards(session) -> int:
    """확정 카드 목록을 key 단위로 멱등 시드. 새로 넣은 행 수를 반환.

    이미 있는 key 는 건드리지 않는다 → 사용자가 화면에서 고친 적립율·표시명 보존.
    """
    existing = {k for (k,) in session.query(PurchaseCard.key).all()}
    added = 0
    for i, (key, label, rate, hyundai) in enumerate(PURCHASE_CARD_SEED):
        if key in existing:
            continue
        session.add(PurchaseCard(
            key=key, label=label,
            accrual_rate=validate_accrual_rate(rate),
            is_hyundai_default=hyundai, active=True, sort_order=i + 1,
        ))
        added += 1
    if added:
        session.commit()
    return added


def list_cards(session, include_inactive: bool = False) -> list[PurchaseCard]:
    """표시 순서대로 카드 목록. 기본은 active 만."""
    q = session.query(PurchaseCard)
    if not include_inactive:
        q = q.filter(PurchaseCard.active.is_(True))
    return q.order_by(PurchaseCard.sort_order, PurchaseCard.id).all()


def get_card(session, key: str) -> PurchaseCard | None:
    """key 로 카드 1장. 없으면 None."""
    return session.query(PurchaseCard).filter_by(key=key).one_or_none()


def set_accrual_rate(session, key: str, rate) -> PurchaseCard:
    """적립율 수정. 범위를 벗어나면 ValueError, 없는 key 면 ValueError."""
    card = get_card(session, key)
    if card is None:
        raise ValueError(f"없는 카드 key: {key}")
    card.accrual_rate = validate_accrual_rate(rate)
    session.commit()
    return card

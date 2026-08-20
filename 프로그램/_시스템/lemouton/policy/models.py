"""마켓별 정책 — 정책 1개 · 항목값 · 상품 적용.

값은 (정책 × 마켓 × 항목) 한 칸씩 저장한다. 항목이 늘 때마다 칼럼을 늘리면
마켓 6개 × 항목 30개 = 180칼럼이 된다 — 그래서 세로로 쌓는다.
항목표는 lemouton/policy/fields.py 가 단일 진실 원천.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MarketPolicy(Base):
    """정책 한 벌. 여러 상품에 같은 정책을 붙일 수 있다."""
    __tablename__ = 'market_policies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    memo = Column(Text)
    # 브랜드별 분류(노션). 비어 있으면 목록에서 「브랜드 없음」으로 모인다.
    brand = Column(String(128))
    # [2026-08-19] 정책명 자동 조합용 — 카테고리·소싱처. 셋 다 비워 두면 이름을
    #   직접 적어야 한다(create_policy 참조). 목록 칼럼·거르기에는 아직 안 쓴다 —
    #   이름 조합 전용 칸이라 브랜드처럼 화면에 별도로 노출하지 않는다.
    category = Column(String(120))
    sourcing = Column(String(120))
    # 내보낼 마켓 (JSON 배열 문자열). NULL = 아직 안 정함 = **전부 켜짐**.
    #   🔴 빈 배열 '[]' 은 「전부 끔」이다 — NULL 과 다르다. 「안 정함」을
    #     「전부 꺼짐」으로 읽으면 잘 나가던 정책이 이 기능을 붙이는 순간 멈춘다.
    enabled_markets = Column(Text)
    # 기본 정책 — 새 상품에 자동으로 붙는다(노션 「기본 셋팅 해두고 전체 적용」).
    is_default = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)


class MarketPolicyValue(Base):
    """(정책 × 마켓 × 항목) 값 한 칸. 비어 있으면 「안 정함」 — 0 이 아니다."""
    __tablename__ = 'market_policy_values'

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey('market_policies.id'),
                       nullable=False, index=True)
    market = Column(String(20), nullable=False)
    field_key = Column(String(40), nullable=False)
    value = Column(Text)                       # 전부 문자열로 보관 — 화면 입력 그대로
    # 「마켓 공통」에서 받은 시각. 직접 저장하면 None 으로 돌아간다.
    #   🔴 값 비교로 「공통 따름」을 판정하면 안 된다 — 공통이 나중에 바뀌면
    #     받은 적 있는 마켓이 「직접 고침」으로 잘못 뜬다.
    from_common_at = Column(DateTime)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('policy_id', 'market', 'field_key', name='uq_policy_value'),
        Index('ix_policy_value_lookup', 'policy_id', 'market'),
    )


class BundlePolicyLink(Base):
    """어느 모음전 상품에 어느 정책을 붙였나. 상품 하나에 정책 하나.

    ★ 구성(벌)에 따로 정하지 않았을 때 쓰는 **바탕값**이다.
      구성마다 다른 정책을 주려면 [[SetPolicyLink]] 를 쓴다.
    """
    __tablename__ = 'bundle_policy_links'

    model_code = Column(String(64), ForeignKey('models.model_code'), primary_key=True)
    policy_id = Column(Integer, ForeignKey('market_policies.id'),
                       nullable=False, index=True)
    applied_at = Column(DateTime, default=_utcnow, nullable=False)


class SetPolicyLink(Base):
    """어느 **구성(벌)** 에 어느 정책을 붙였나 — 「한 상품에 여러 정책」의 실체.

    ■ 왜 상품이 아니라 구성인가 (2026-08-02 조사)
      사장님 확정은 「같은 마켓에 여러 벌 올리기」다. 그 「벌」은 이미 집에 있다 —
      이름이 **구성(ProductSet)** 이고, `model_code` 가 UNIQUE 가 아니라 상품 하나에
      여러 개 달린다. 구성마다 `SetChannel`(마켓×계정×마켓상품번호)을 따로 들고 있어
      **같은 마켓에 이미 여러 벌이 나갈 수 있다**(라이브 `르무통_메이트` 가 구성 2개).
      빠져 있던 건 딱 하나 — 정책이 상품에만 붙어 구성별로 갈라 줄 자리가 없었다.

    ■ 구성 하나에 정책 하나 (set_id 가 PK)
      한 구성이 마켓에 나가는 모습은 하나뿐이다. 정책을 둘 붙이면 어느 값으로 올릴지
      정할 수 없다 — 그건 구성을 하나 더 만들어야 하는 상황이다.

    🔴 **되받기(fallback)를 반드시 지킨다** — 구성에 정책이 없으면 상품 정책, 그것도
      없으면 쓰던 가격 템플릿. 이게 없으면 정책을 안 붙인 구성의 가격이 조용히 바뀐다.
    """
    __tablename__ = 'set_policy_links'

    set_id = Column(Integer, ForeignKey('product_sets.id', ondelete='CASCADE'),
                    primary_key=True)
    policy_id = Column(Integer, ForeignKey('market_policies.id'),
                       nullable=False, index=True)
    applied_at = Column(DateTime, default=_utcnow, nullable=False)

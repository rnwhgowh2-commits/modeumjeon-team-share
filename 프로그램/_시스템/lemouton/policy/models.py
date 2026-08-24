"""마켓별 정책 — 정책 1개 · 항목값 · 상품 적용.

값은 (정책 × 마켓 × 항목) 한 칸씩 저장한다. 항목이 늘 때마다 칼럼을 늘리면
마켓 6개 × 항목 30개 = 180칼럼이 된다 — 그래서 세로로 쌓는다.
항목표는 lemouton/policy/fields.py 가 단일 진실 원천.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
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
    # [2026-08-24] 0층 규칙 저장소 참조 — 규칙 한 벌을 여러 정책이 공유한다.
    #   🔴 NULL 이 정상이다: 규칙을 안 고른 정책은 지금까지처럼 상품 원본 값을 그대로
    #     쓴다(기존 동작 그대로 — 이 컬럼이 생겼다고 달라지는 정책은 하나도 없다).
    name_rule_id = Column(Integer, ForeignKey('name_rules.id'))
    detail_template_id = Column(Integer, ForeignKey('detail_templates.id'))
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


class MarketAccountSetting(Base):
    """2층 — 그 **계정**에 고정인 등록 설정. 정책 개수와 무관하게 값이 하나다.

    ■ 왜 정책이 아니라 계정에 두나 (2026-08-24 사장님 확정)
      출고지·반품지·A/S 전화·택배사는 정책을 100개 만들어도 값이 같다. 정책에 두면
      ① 정책을 새로 만들 때마다 같은 값을 다시 입력해야 하고 ② 반품지를 바꾼 날
      옛 정책들이 조용히 틀린 주소로 등록한다. 쿠팡은 이미 이 형태를 갖고 있다
      (`registration/models.py:CoupangVendorSetting`) — 그걸 6마켓으로 넓힌 것.

    🔴 **자격증명(API 키)은 여기 담지 않는다.** 시크릿 단일 원천은 `.env` 다
      (`lemouton/auth/secrets.py` — DB 이중 저장 금지). 삼바는 DB 에 담지만 우리는
      그 설계를 따라가지 않는다.

    ★ `extra` 가 JSON 인 이유: 마켓 전용 칸(옥션 출고지번호·롯데ON 배송정책번호 등)을
      컬럼으로 못박으면 마켓이 늘 때마다 마이그레이션이 필요해진다. 모든 마켓이 쓰는
      칸만 컬럼으로 두고 나머지는 JSON — 오타 위험이 큰 쪽만 못박는 절충이다.

    🔴 **「안 정함」과 「0원」은 다르다** (2026-08-24 사장님 확정 · 실측으로 잡은 사고)
      금액 칸을 `default=0, nullable=False` 로 두면 **아직 안 정한 계정**과 **0원이라고
      정한 계정**이 둘 다 0 으로 읽힌다. 배송비는 금전 직결이라 이 혼동이 곧 손실이다.
      그래서 금액·문자 칸은 전부 **NULL 허용**으로 둔다 — NULL = 「안 정함」, 0 = 「0원」.
      기본값이 필요하면 :data:`DEFAULT_FEES` 를 호출부가 **명시적으로** 가져다 쓴다
      (모델이 몰래 채우지 않는다 — 그게 「지어내지 않는다」 원칙이다).
    """
    __tablename__ = 'market_account_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_account_id = Column(Integer, ForeignKey('upload_accounts.id'),
                               unique=True, nullable=False)

    # ── 모든 마켓이 쓰는 칸 ──
    #   🔴 전부 nullable — NULL 은 「아직 안 정함」이고 0/'' 은 「그렇게 정함」이다.
    as_phone = Column(String(32))
    as_message = Column(Text)
    return_fee = Column(Integer)
    exchange_fee = Column(Integer)
    jeju_fee = Column(Integer)
    island_fee = Column(Integer)
    tax_type = Column(String(16))
    origin_default = Column(String(64))
    stock_default = Column(Integer)
    promotion_message = Column(String(200))

    # ── 그 마켓에만 있는 칸 ──
    extra = Column(JSON, default=dict, nullable=False)

    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


#: 사장님 확정 기본값 (2026-08-24). **모델이 몰래 채우지 않는다** — 계정 설정 화면이
#: 새 계정을 만들 때 이 값을 넣어 주고, 사장님이 화면에서 고칠 수 있다.
#: 안 정한 칸(NULL)을 전송 직전에 이 값으로 때우면 안 된다 — 그러면 「안 정함」을
#: 없애 버리는 것이라 이 표를 만든 뜻이 사라진다.
DEFAULT_FEES = {
    'return_fee': 5000,     # 반품 배송비 — 편도
    'exchange_fee': 10000,  # 교환 배송비 — 왕복(편도의 2배)
}


class NameRule(Base):
    """0층 — 상품명 조립 규칙 한 벌. 여러 정책이 **참조**한다(복사가 아니다).

    ■ 왜 정책 밖으로 빼나 (2026-08-24 사장님 확정 · 삼바 구조 채택)
      삼바는 상품명 규칙을 별도 저장소(`samba_name_rule`)에 두고 정책이 ID 로 참조한다.
      그래서 치환표를 한 번만 채우면 그 규칙을 쓰는 정책 전부에 반영된다. 모음전은
      값이 정책 안에 있어 정책 수만큼 다시 채워야 했다.

    ★ `max_len_mode` — 상품명 길이를 무엇으로 재나. 'byte'(기본) / 'char' / 'both'.
      삼바 실측이 바이트 기준이라 기본을 byte 로 둔다. 쿠팡만 등록 API 원문에 100자로
      명시돼 있어 예외인데, 그 예외는 이 칸이 아니라 `registration/market_limits.py`
      가 마켓별로 판단한다(근거가 마켓 스펙이지 사장님 취향이 아니므로).
    """
    __tablename__ = 'name_rules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    token_order = Column(JSON, default=list, nullable=False)
    replacements = Column(JSON, default=list, nullable=False)
    market_overrides = Column(JSON, default=dict, nullable=False)
    max_len_mode = Column(String(16), default='byte', nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class DetailTemplate(Base):
    """0층 — 상세페이지 템플릿 한 벌. 여러 정책이 참조한다.

    `market_overrides` = {마켓키: 다른 템플릿 id} — 그 마켓만 다른 템플릿을 쓰고 싶을 때.
    """
    __tablename__ = 'detail_templates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    top_html = Column(Text, default='', nullable=False)
    bottom_html = Column(Text, default='', nullable=False)
    market_overrides = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class CategoryMappingReview(Base):
    """AI 카테고리·태그 매핑 「보류함」 — 확신 낮은 것만 쌓인다.

    ■ 왜 전량 자동이 아닌가 (2026-08-24 사장님 확정)
      카테고리는 틀리면 노출이 죽고 마켓 제재 대상이 된다. AI 가 확신하는 것만
      바로 넣고 애매한 것은 여기로 보내, 사장님은 **보류함만** 보면 된다.

    🔴 `ai_suggestion` 은 확정·수정 후에도 **덮어쓰지 않는다** — 나중에 「AI 가 무엇을
      얼마나 틀렸나」를 세려면 추천값과 실제값이 둘 다 남아 있어야 한다.
    """
    __tablename__ = 'category_mapping_reviews'

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String(64), nullable=False, index=True)
    market = Column(String(20), nullable=False)
    ai_suggestion = Column(String(200))
    confidence = Column(Float)
    status = Column(String(16), default='pending', nullable=False)  # pending|confirmed|corrected
    resolved_value = Column(String(200))
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class BrandRegistryCache(Base):
    """쿠팡 브랜드 API 판별 결과 캐시 — brandId + 정품코드(소명) 필요 여부.

    ■ 왜 필요한가 (2026-08-24)
      ① 쿠팡이 2026-08-01 부터 등록에 `brandId` 를 요구하는데 우리는 브랜드 **이름만**
         보내고 있었다(`registration/compile_coupang.py` 실측) — 등록 거부 위험.
      ② 소명 필요 브랜드는 마켓이 계속 늘려서 사람이 만든 제한표로는 못 따라간다.
      기존 수동 제한표(`registration/models.py:BrandRestriction`)는 그대로 두고,
      **자동 판별 결과를 여기 따로** 쌓는다(사장님이 손으로 넣은 판단을 덮지 않는다).

    🔴 `uid_required=None` 은 **「모름」**이다 — 「소명 필요 없음」이 아니다.
      판정 못 한 브랜드는 막는다(사장님 확정: 계정 정지 손해 > 못 판 손해, 손실 비대칭).
    """
    __tablename__ = 'brand_registry_cache'

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand = Column(String(120), nullable=False, unique=True)
    coupang_brand_id = Column(String(64))
    uid_required = Column(Boolean)      # None = 판정 불가
    matched = Column(Boolean, default=False, nullable=False)
    checked_at = Column(DateTime, default=_utcnow, nullable=False)

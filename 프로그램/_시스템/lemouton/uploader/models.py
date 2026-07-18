"""[D] 마켓 등록·동기화 추적 테이블."""
from sqlalchemy import (
    Column, String, Integer, DateTime, JSON, Text, Index, PrimaryKeyConstraint,
)
from datetime import datetime, timezone

from shared.db import Base


class MarketRegistration(Base):
    """옵션 × 마켓 단위 등록·동기화 추적."""
    __tablename__ = "market_registrations"

    canonical_sku = Column(String(128), nullable=False)
    market = Column(String(16), nullable=False)  # 'smartstore' | 'coupang'
    market_product_id = Column(String(64))
    market_option_id = Column(String(128))
    last_synced_price = Column(Integer)
    last_synced_stock = Column(Integer)
    status = Column(String(16), default="pending", nullable=False)
    last_attempt_at = Column(DateTime)
    last_success_at = Column(DateTime)
    sync_error = Column(String(500))
    sync_attempts = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime)
    pricing_reason = Column(String(64))

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        PrimaryKeyConstraint("canonical_sku", "market"),
    )


# [2026-07-19 대량등록 Phase 1B M3-1] ────────────────────────────────────────
class PriceSnapshot(Base):
    """"언제 · 어떤 값으로 · 왜" 마켓에 올렸나(또는 안 올렸나) 1건 = 1행.

    ■ 왜 MarketRegistration 으로 부족한가
      ``market_registrations`` 는 (canonical_sku, market) 이 PK 인 **현재 상태 1행**
      이다. 덮어쓰기라 이력이 없다. 그래서
        · 「그때 왜 그 값으로 올렸나」(계산근거) 를 되짚을 수 없고,
        · M4 의 「주문 시점 가격 대조」(주문이 들어온 시각에 우리가 올려둔 값이
          얼마였나) 를 물어볼 대상이 아예 없다.
      PriceSnapshot 은 **append-only 이력**이다. 그래서 (sku, market, account_key)
      에 UNIQUE 를 걸지 않는다 — 걸면 이력이 1행으로 뭉개져 M4 가 불가능해진다.
      대신 「직전 스냅샷」 조회용 복합 인덱스를 둔다(아래 __table_args__).
      ※ shared/db.py 의 경량 마이그레이션에는 CREATE INDEX 경로가 있어 인덱스는
        나중에도 추가할 수 있지만 **ADD CONSTRAINT 경로는 없다** → 유니크 여부는
        지금 결정해야 하는 항목이라 명시적으로 "안 건다"를 선택한 것이다.

    ■ 왜 lemouton/uploader/models.py 인가
      app.py 가 ``lemouton.uploader.models`` 를 이미 import 한다(app.py:64) =
      create_all 등록 보장. Alembic 이 없는 이 프로젝트에서 신규 모듈을 만들면
      import 배선을 빠뜨리는 순간 **조용히 테이블이 없다**. 도메인상으로도 이 파일이
      "마켓 등록·동기화 추적" 이라 정확히 같은 자리다.

    ■ 컬럼을 처음에 다 넣는 이유
      create_all 은 **기존 테이블에 컬럼을 추가하지 않는다**. 나중 추가는
      shared/db.py::_apply_lightweight_migrations() 의 ADD COLUMN 뿐이라 번거롭다.
      그래서 이번 M3-1 에서 안 쓰는 것도 미리 넣는다 — 특히 ``action``/``skip`` 계열:
      게이트가 "스킵했다 + 왜" 를 반환하므로 M3-2 가 스킵 이력까지 이 표에 적재하려
      할 때 스키마 변경 없이 되도록 한다.

    ■ 문자열 폭 (라이브 = Supabase PostgreSQL, 개발기 SQLite 는 길이 미강제)
      · canonical_sku String(128) — 집 표준. inventory/models.py, multitenancy/models.py,
        market_registrations 전부 128.
      · market String(32) — 실제 최장값은 'smartstore'(10자). market_registrations 는
        String(16) 이지만 registration/models.py(Phase 1A) 가 String(32) 를 쓰므로
        더 넉넉한 쪽에 맞춘다.
      · account_key String(64) — registration/models.py:ProductDraftMarket 와 동일.
      · source_key String(64) — sources/models.py:211 의 source_key 가 String(64) 로
        가장 넓다(sourcing/models.py 는 32·40). 가장 넓은 정의에 맞춰야 잘리지 않는다.
      · reason String(200) — 사람이 읽는 한국어 사유 한 문장("가격변동 115,000→119,900").
        PostgreSQL VARCHAR(n) 은 바이트가 아니라 **문자** 수라 한글 200자면 충분.
      · reason_code String(32) — 기계용 고정 코드(가장 긴 게 'margin_below_min' 16자).
    """

    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── 대상 식별 ───────────────────────────────────────────────────────────
    canonical_sku = Column(String(128), nullable=False)
    market = Column(String(32), nullable=False)      # 'smartstore' | 'coupang' | ...
    # 마켓당 다계정(롯데온 7계정 등). NULL 은 쓰지 않는다 — 'default' 센티넬.
    # (registration/models.py:ProductDraftMarket 와 동일 관례.)
    account_key = Column(String(64), nullable=False, default="default")
    # 이 값이 어느 소싱처에서 왔나. 'musinsa' 처럼 SourceProduct.site 와 같은 키.
    # 매트릭스가 쓰는 'key:lotteimall' 합성 id 는 접두를 뗀 뒤 저장한다
    # (api_benefits.py:_resolve_site_key 와 같은 규칙).
    source_key = Column(String(64))

    # ── 값 ──────────────────────────────────────────────────────────────────
    # 전부 nullable — '모름' 과 '0원' 은 다르다. 크롤 실패를 0 으로 채우면 그게 곧
    # 금전 손실이다(집 원칙: 폴백 금지).
    surface_price = Column(Integer)          # 표면노출가 (소싱처 화면 가격)
    final_purchase_price = Column(Integer)   # 최종매입가 (compute_final_price.final_price)
    upload_price = Column(Integer)           # 실제로 마켓에 올린 판매가
    margin_amount = Column(Integer)          # upload_price 기준 마진(원). 역마진 가드 근거
    # 재고 센티넬은 집 관례를 그대로 따른다(lemouton/sources/lap_report.py:43):
    #   None=미크롤 / -1=확인불가 / 0=품절 / 999=있음(상한 미상)
    stock = Column(Integer)

    # ── 판정 근거 ───────────────────────────────────────────────────────────
    # compute_final_price 가 돌려준 steps 리스트를 그대로 담는다
    # ([{name,type,value,deduct,base_after}, ...]). 나중에 "왜 이 값이 나왔나" 를
    # 사람이 되짚는 유일한 근거 — 요약해서 담지 않는다.
    steps_json = Column(JSON)
    # 'upload' | 'skip' | 'hold'  — hold = 역마진 가드 등으로 보류(판매중지 후보)
    action = Column(String(16), nullable=False, default="upload")
    priority = Column(String(2))             # 'P0' | 'P1' | 'P2'
    reason_code = Column(String(32))         # 기계용 고정 코드
    reason = Column(String(200))             # 사람이 읽는 사유
    # 게이트가 붙인 경고(역마진·재고 확인불가 등) 원문 리스트. 조용한 실패 방지용.
    warnings_json = Column(JSON)

    # 실제 마켓 전송이 끝난 시각. action='skip'/'hold' 면 NULL 이다
    # (= "올린 적 없음" 을 시각으로도 구분할 수 있게).
    uploaded_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        nullable=False)

    __table_args__ = (
        # 「직전 스냅샷」 조회 = 이 3키로 좁히고 최신 1건. id 는 append-only 라
        # 시간 순서와 같아 정렬 키로 안전(같은 초에 여러 건 들어와도 유일).
        Index("ix_price_snapshots_target",
              "canonical_sku", "market", "account_key", "id"),
        Index("ix_price_snapshots_created", "created_at"),
    )

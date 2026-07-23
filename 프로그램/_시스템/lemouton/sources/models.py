"""[v2] 소싱 정규화 DB 모델.

핵심: 같은 URL을 N 모음전이 입력해도 SourceProduct 1행만 생기게.
크롤러는 SourceProduct 단위로 1번만 fetch → 모든 모음전이 공유.

설계 문서: docs/architecture_v2.md §3.1
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float,
    UniqueConstraint, Index,
)

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class SourceProduct(Base):
    """소싱처 상품 — 1 (site, url) = 1 row. 전역 단일 진실."""
    __tablename__ = "source_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site = Column(String(32), nullable=False)
    url = Column(Text, nullable=False)
    external_product_id = Column(String(128))
    product_name = Column(String(255))

    last_fetched_at = Column(DateTime)
    last_status = Column(String(16))
    last_error_msg = Column(Text)
    last_price = Column(Integer)
    last_stock = Column(Integer)

    # 2026-05-13 추가: 사이트가 판매가에 자동 적용한 카드 할인 정보.
    # JSON 직렬화 dict: {"issuer": "국민카드", "rate": 5.0, "label": "국민카드 5%"} 또는 NULL.
    # 매트릭스 팝업 시안 B 가 "판매가" 라인 옆 보조 텍스트로 렌더링.
    auto_card_discount_json = Column(Text)

    # ★ 2026-05-15 추가: 상품 단위 동적 혜택 (옵션 dict 에서 추출).
    # JSON 직렬화 dict: point_rate / gift_point_amount / ssg_money_rate / already_applied /
    #   card_benefit_price / lotteon_coupons / money_active 등 사이트 특화 동적 키들.
    # compute_breakdown 이 lookup 해서 매트릭스 매입가 산식에 추가 차감으로 자동 반영.
    dynamic_benefits_json = Column(Text)

    # 2026-07-04: 자동화 연속 배수 큐
    crawl_weight = Column(Integer, default=1, nullable=False)      # 계수 1~5
    # 2026-07-19: 뜸하게 긁는 쪽 손잡이. 유효간격 = 기준주기 ÷ 계수 × 느리게배수.
    #   ★계수는 Integer 라 「3일에 1회」(=1/3)를 못 담는다 — int() 가 0 으로 만들고
    #     계수 0 은 '크롤 제외'라 상품이 영영 안 긁힌다. 그래서 방향을 갈랐다.
    #     계수 = 자주(1~5) · 느리게배수 = 뜸하게(1.0 이상). 1.0 = 예전과 동일.
    crawl_slowdown = Column(Float, default=1.0, nullable=False)
    no_change_streak = Column(Integer, default=0, nullable=False)  # 무변동 연속 횟수
    # 2026-07-06: 가중 라운드로빈 랩 — 이번 랩에 이 URL을 몇 번 크롤했나(계수만큼 채우면 소진).
    crawl_lap_count = Column(Integer, default=0, nullable=False)

    # [2026-07-23 M3] 소싱처 카테고리 경로(빵부스러기). '신발>스니커즈>여성운동화'.
    #   크롤 CrawlResult.category_path 가 채운다. 빈 값이면 기존값 보존(무스톰프).
    category_path = Column(String(500))

    # [2026-07-23 M4-4] 소싱처 상품 이미지·상세페이지
    #   images_json  : JSON 배열 ["https://...", ...] — 대표(첫 원소) + 추가 이미지 **URL만**.
    #                  ★ 이미지는 브랜드 저작물이다. 여기 저장하는 건 URL 수집까지고,
    #                    마켓 업로드는 브랜드별 지재권 제외 정책 통과 후 별도 단계에서 한다.
    #   detail_html  : 소싱처 상세설명 영역 HTML(스크립트·추적 태그 제거본).
    #   둘 다 크롤 CrawlResult 가 채운다. 빈 값이면 기존값 보존(무스톰프) —
    #   한 번 실패한 크롤이 이미 확보한 이미지를 지워 등록을 막는 사고를 낸다.
    images_json = Column(Text)
    detail_html = Column(Text)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('site', 'url', name='uq_source_product_site_url'),
        Index('ix_source_products_site', 'site'),
        Index('ix_source_products_status', 'last_status'),
    )


class SourceOption(Base):
    """소싱처 옵션 — 1 SourceProduct × (color_text, size_text) = 1 row."""
    __tablename__ = "source_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_product_id = Column(Integer, ForeignKey('source_products.id'), nullable=False)
    color_text = Column(String(64))
    size_text = Column(String(32))
    external_option_id = Column(String(128))

    current_price = Column(Integer)
    current_stock = Column(Integer)
    last_fetched_at = Column(DateTime)

    # ★ 2026-05-15 — 옵션별 동적 혜택 (사이트 자체 가변값 — 카드사/적립률/카드혜택가 등)
    #   크롤러 옵션 dict 의 동적 키 (point_rate, point_amount, gift_point_amount,
    #   auto_card_discount, ssg_money_*, card_benefit_*, lotteon_coupons 등) JSON.
    #   compute_breakdown 이 이 JSON 을 lookup 해서 매트릭스 매입가 산식에 자동 반영.
    dynamic_benefits_json = Column(Text)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            'source_product_id', 'color_text', 'size_text',
            name='uq_source_option_product_color_size',
        ),
        Index('ix_source_options_product', 'source_product_id'),
    )


class ModelSourceLink(Base):
    """모음전 ↔ SourceProduct M:N 매핑.

    한 모음전이 여러 사이트의 URL 가질 수 있고,
    한 URL이 여러 모음전에 공유될 수 있음.
    """
    __tablename__ = "model_source_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey('models.model_code'), nullable=False)
    source_product_id = Column(Integer, ForeignKey('source_products.id'), nullable=False)

    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('model_code', 'source_product_id', name='uq_model_source_link'),
        Index('ix_model_source_links_model', 'model_code'),
        Index('ix_model_source_links_source', 'source_product_id'),
    )


class CardDiscountUserPref(Base):
    """2026-05-13 추가: 사용자 카드 보유 미반영 설정 (3 scope).

    scope:
      - 'option': 옵션·사이트 단위 (canonical_sku + source_id)
      - 'bundle': 모음전·사이트 단위 (bundle_code + source_id)
      - 'global': 사이트 글로벌 (source_id 만)

    조회 우선순위: option > bundle > global > default ON.
    enabled = 0 (OFF, 카드 미보유 → 카드할인 미반영).
    """
    __tablename__ = "card_discount_user_pref"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(16), nullable=False)
    canonical_sku = Column(String(128))
    bundle_code = Column(String(64))
    source_id = Column(Integer, nullable=False)
    enabled = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class OptionSourceLink(Base):
    """옵션 ↔ SourceOption M:N 매핑.

    canonical_sku 가 여러 SourceOption (사이트별 옵션) 과 매핑됨.
    한 SourceOption 이 여러 옵션에 공유될 수도 있음 (옵션 슬롯 재사용 케이스).
    """
    __tablename__ = "option_source_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(String(128), ForeignKey('options.canonical_sku'), nullable=False)
    source_option_id = Column(Integer, ForeignKey('source_options.id'), nullable=False)

    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('canonical_sku', 'source_option_id', name='uq_option_source_link'),
        Index('ix_option_source_links_sku', 'canonical_sku'),
        Index('ix_option_source_links_source', 'source_option_id'),
    )


class CrawlDelta(Base):
    """URL(소싱처 상품) 1건을 크롤할 때마다 직전 대비 변동 여부 1행 기록.

    판매처 쪽 ChannelChangeEvent(전송 시점)과 다른 층 — 이건 크롤 시점.
    """
    __tablename__ = "crawl_deltas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_product_id = Column(Integer, ForeignKey("source_products.id"),
                               nullable=False, index=True)
    crawled_at = Column(DateTime, default=_utcnow, nullable=False)
    stock_changed = Column(Boolean, default=False, nullable=False)
    price_changed = Column(Boolean, default=False, nullable=False)
    detail = Column(Text)  # 무엇이 얼마→얼마로 (사람이 읽는 요약)


class CrawlLapRun(Base):
    """가중 랩 1바퀴 완료 = 1행. 자정(KST) 이후 개수 = '오늘 몇 바퀴',
    연속 완료 간격 = '1바퀴 걸린 시간'(평균·막대). 완료 시 start_new_lap 이 append."""
    __tablename__ = "crawl_lap_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    completed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class CrawlChangeStat(Base):
    """[Phase 1B M5] 랩 × 소싱처 × 브랜드 변동 집계 — '계수를 정하는 근거'.

    사람이 감으로 정하던 계수(1~5)에 숫자를 대주는 표다.

    ■ ★기준선은 '소싱처' 다 (마켓이 아니다) — 2026-07-19 교정
      물음이 다르면 기준선도 달라야 한다.
        · "얼마나 자주 크롤할까" = **소싱처가 얼마나 자주 바뀌나** → :class:`CrawlDelta`
        · "마켓에 올릴까"        = 마켓이 든 값과 다른가        → GateDecision
      크롤 빈도는 마켓과 무관하다. 처음엔 ``decide_upload`` 의 판정을 그대로 셌는데,
      그 기준선은 ``last_confirmed_snapshot``(마켓이 실제 받은 값)이라 실전송이 잠기면
      (``MOUM_LIVE_UPLOAD`` OFF) ``uploaded_at`` 이 영원히 안 채워져 **모든 판정이
      first_upload 로 떨어지고 통계가 통째로 비었다**. CrawlDelta 로 바꾸면 잠금 여부와
      무관하게 오늘부터 숫자가 나온다.

    ■ 지표별 출처가 섞이지 않게 (같은 표에 두되 칸을 갈라 놓는다)
      · ``observed`` ``changed`` ``price_changed`` ``stock_changed`` ``soldout``
        ``first_seen`` → **CrawlDelta** (소싱처 기준선)
      · ``p2_skipped`` → **GateDecision** (업로드 판정 — 본질적으로 마켓 쪽 물음)

    ■ 왜 랩 단위 집계인가 (관측 1건 = 1행 이 아니라)
      한 랩에 URL×SKU 조합이 수천 건이고 하루 100 바퀴가 넘는다. 관측마다 1행이면
      무료 티어 500MB 를 며칠에 태운다. 그래서 (랩, 소싱처, 브랜드) 하나에 1행을 두고
      카운터만 올린다. 그래도 (소싱처×브랜드)/랩 로 늘기 때문에 오래된 랩은
      :func:`~lemouton.sources.crawl_change_stats.prune_old_stats` 가 정리한다.

    ■ 분모(observed)에서 빠지는 것 — 무결성
      · **크롤 실패**: 실패하면 CrawlDelta 자체가 안 생긴다(저장 성공한 크롤만 1행).
        구조적으로 '변동 없음'에 섞일 수 없다 — 실패를 안정으로 오독하면 계수가
        잘못 내려가 정작 자주 바뀌는 곳을 덜 보게 된다.
      · ``first_seen``: 처음 수집(이전 값이 없어 '바뀌었나'를 물을 수조차 없는 것).
        버리지 않고 따로 센다 — 안 세면 '조용한 실패'와 구분되지 않는다.

    lap_run_id = 0 은 **아직 안 끝난(진행 중) 랩**이다. NULL 을 쓰지 않는 이유:
    PostgreSQL 은 UNIQUE 에서 NULL 을 서로 다른 값으로 보기 때문에 같은
    (소싱처, 브랜드) 열린 행이 여러 개 생겨 카운터가 쪼개진다.
    """
    __tablename__ = "crawl_change_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 0 = 진행 중인 랩. 랩 완료 시 start_new_lap 이 그 CrawlLapRun.id 로 도장을 찍는다.
    #   (FK 를 걸지 않는 이유: 0 은 실재하지 않는 id 이고, 이 프로젝트엔 나중에
    #    제약을 추가할 마이그레이션 경로가 없다.)
    lap_run_id = Column(Integer, default=0, nullable=False, index=True)
    # SourceProduct.site(32) 보다 넉넉하게, CrawlConcurrencyRule.source_key 와 같은 폭.
    source_key = Column(String(64), nullable=False)
    # Model.brand(100) · Option.brand(100) 와 같은 폭. 미지정은 센티넬 문자열로 채운다
    #   (NULL 이면 위 UNIQUE 가 PostgreSQL 에서 또 쪼개진다).
    brand = Column(String(100), nullable=False)

    # ── ① 소싱처 기준 (출처 = CrawlDelta) ────────────────────────────────
    #   단위는 '크롤 1회(=CrawlDelta 1행)'다. 옵션 수만큼 부풀리지 않는다.
    observed = Column(Integer, default=0, nullable=False)      # 직전 값과 견줄 수 있었던 크롤
    changed = Column(Integer, default=0, nullable=False)       # 그중 가격 또는 재고가 바뀐 크롤
    # 내역(가격·재고는 한 크롤에서 동시에 바뀔 수 있어 합이 changed 를 넘을 수 있다)
    price_changed = Column(Integer, default=0, nullable=False)
    stock_changed = Column(Integer, default=0, nullable=False)
    soldout = Column(Integer, default=0, nullable=False)       # 품절 전환이 있었던 크롤
    # 처음 수집(이전 값 없음)이 섞인 크롤 수. 변동이 아니라 분모에도 안 들어간다.
    first_seen = Column(Integer, default=0, nullable=False)

    # ── ② 마켓 기준 (출처 = GateDecision) ────────────────────────────────
    #   ★위 칸들과 기준선이 다르다. 화면도 칸을 갈라 표시한다(같은 기준인 척 금지).
    #   재고가 바뀌었는데 P2 로 스킵된 건수 — 스킵이 묻히지 않게 보고서에 그대로 띄운다.
    p2_skipped = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("lap_run_id", "source_key", "brand",
                         name="uq_crawl_change_stat_lap_source_brand"),
        Index("ix_crawl_change_stats_source_brand", "source_key", "brand"),
    )


class CrawlWeightRule(Base):
    """계수 규칙 — 소싱처/브랜드/모음전/URL 범위별. 없으면 상속·기본 ×1."""
    __tablename__ = "crawl_weight_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope_type = Column(String(8), nullable=False)   # source|brand|model|url
    scope_key = Column(String(512), nullable=False)  # site / brand / model_code / 정규화 url
    weight = Column(Integer, nullable=False)          # 1~5
    # 2026-07-19: 뜸하게 긁는 쪽 (SourceProduct.crawl_slowdown 과 같은 뜻). 1.0 = 기본.
    slowdown = Column(Float, default=1.0, nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_type", "scope_key", name="uq_crawl_weight_rule"),
    )


class CrawlConcurrencyRule(Base):
    """소싱처별 '동시 상한' — 한 소싱처를 한 번에 몇 갈래로 나눠 긁을지(1~10).

    별도 테이블(create_all 로 신규 생성 — 기존 DB 컬럼 마이그레이션 불필요).
    행 없으면 소싱처 성격 기본값(창없이 8 / 창 필요 3)을 쓴다.
    """
    __tablename__ = "crawl_concurrency_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String(64), nullable=False, unique=True)   # hmall/musinsa/lotteon…
    limit_val = Column(Integer, nullable=False)                    # 1~10

# -*- coding: utf-8 -*-
"""대량등록 — 마켓 공통 상품 그릇.

Alembic 없음 — shared/db.py:init_db() 의 Base.metadata.create_all 이 생성한다.
create_all 은 기존 테이블에 컬럼을 추가하지 않으므로, Phase 2~3 에서 쓸 컬럼까지
처음부터 선언한다. 나중에 늘리려면 shared/db.py 의 migrations 리스트를 써야 한다.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, Text, DateTime, ForeignKey, UniqueConstraint, Index,
    Float,
)
from sqlalchemy.orm import relationship

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ProductDraft(Base):
    """마켓 공통 상품 1건. 크롤이 채우든(Phase 3) 사람이 채우든(Phase 1A) 같은 그릇."""
    __tablename__ = "product_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 등록경로 — 주문·CS 「등록경로」 필터의 근거. 'bulk'(대량등록) | 'bundle'(모음전)
    origin = Column(String(16), default='bulk', nullable=False)
    # 채운 주체 — 'manual'(수기) | 'crawl'(소싱처 크롤, Phase 3)
    source = Column(String(16), default='manual', nullable=False)
    # 모음전 상품에서 온 경우 연결 (없으면 NULL)
    model_code = Column(String(64))

    name = Column(String(255), nullable=False)
    brand = Column(String(120))
    sale_price = Column(Integer, nullable=False)      # 원. 1A 는 사람이 입력. 1B 에서 마진엔진이 채움
    normal_price = Column(Integer)                    # 정가(할인 전). 미입력 시 마켓 기본
    stock_quantity = Column(Integer, default=0)       # 옵션 없는 상품용 평면 재고

    # 상품고시정보 — 'WEAR'|'SHOES'|'BAG'|'FASHION_ITEMS'
    notice_type = Column(String(32), default='WEAR', nullable=False)
    notice_json = Column(Text, default='{}')          # {필드명: 값} — notice.py 가 해석

    images_json = Column(Text, default='[]')          # ["https://...", ...] 원본(업로드 전)
    cdn_images_json = Column(Text, default='[]')      # 스스 업로드 후 CDN URL
    detail_html = Column(Text, default='')

    options_json = Column(Text, default='[]')         # [{color,size,stock,extra_price,sku}]

    origin_area_code = Column(String(32), default='0200037')  # 국내산 기본
    importer = Column(String(120), default='')
    delivery_fee = Column(Integer, default=3000)      # 0 = 무료배송
    return_fee = Column(Integer, default=5000)

    # 스스 detailAttribute 필수 — 라이브 검증된 create_product.py:85-89 payload 에 있음
    minor_purchasable = Column(Boolean, default=True, nullable=False)
    after_service_phone = Column(String(32), default='')
    # 스스 afterServiceGuideContent — 실제 반품·교환 안내문은 255자를 넘는다.
    # String(255) 면 Postgres(개발·라이브)에서 StringDataRightTruncation 로 저장 실패.
    # (SQLite 는 VARCHAR 길이를 무시해 테스트로는 절대 안 잡힘) → Text 필수.
    after_service_guide = Column(Text, default='')

    # ── 매입가·마진 입력 (Phase 1B M2-저장) ──────────────────────────────────
    #   화면 「6 매입가·마진」 6칸의 저장소. 크롤로 못 가져오는 **운영 사실**이라
    #   사람이 고른 값을 그대로 보관한다. 계산은 저장하지 않는다 — 소싱처 혜택이
    #   바뀌면 옛 금액이 되므로, 금액은 매번 엔진(compute_final_price)이 다시 낸다.
    #
    #   ★ 전부 nullable, 기본값 없음. '안 고름'과 '없음'은 다른 뜻이다:
    #       NULL  = 그 칸을 아예 입력받지 않았다 (예: 옛 드래프트)
    #       ''    = 화면에서 「소싱처 기본값」으로 남겨뒀다 (= 아무것도 덮지 않음)
    #       'none'= 「없음」을 명시적으로 골랐다 (= 그 축의 혜택을 전부 끈다)
    #     여기에 default 를 걸면 셋이 한 값으로 뭉개져, 나중에 사장님이 의도적으로
    #     비운 것인지 프로그램이 채운 것인지 영영 알 수 없게 된다.
    pricing_source_id = Column(Integer)          # SourceRegistry.id (혜택 템플릿의 주인)
    surface_price = Column(Integer)              # 소싱처 표면 노출가(원). 0 과 NULL 은 다르다
    # 폭 근거 — 최장값 'naver_via'(9자). 후보가 코드 상수(INFLOW_CHOICES)라 늘 짧다.
    pricing_inflow = Column(String(16))          # ''|'naver_via'|'cashback'|'none'
    # 폭 근거 — PurchaseCard.key 와 **같은 String(64)**. 카드표에 저장될 수 있는 키는
    #   여기에도 반드시 들어가야 한다(더 좁으면 라이브 PostgreSQL 에서만 잘린다).
    #   실사용 키는 pay_method VARCHAR(16) 제약 때문에 16자 이하다
    #   (tests/margin/test_purchase_card.py::test_seed_keys_fit_pay_method_column).
    pricing_card_key = Column(String(64))        # PurchaseCard.key | 'none' | ''
    pricing_naver_pay = Column(String(16))       # ''|'on'|'off'
    # 폭 근거 — SourceBenefitTemplate.benefit_name 과 **같은 String(120)**.
    #   값이 그 컬럼에서 그대로 온다(캐시백 항목명 택1). 좁히면 긴 항목명이 잘린다.
    pricing_cashback_name = Column(String(120))  # benefit_name | 'none' | ''

    # 상품별 업데이트 ON/OFF (Phase 2 상품관리 탭). 컬럼은 지금 만든다.
    update_product = Column(Boolean, default=True, nullable=False)
    update_price = Column(Boolean, default=True, nullable=False)
    update_stock = Column(Boolean, default=True, nullable=False)

    # 'draft' | 'registering' | 'done' | 'failed'
    status = Column(String(16), default='draft', nullable=False)

    # M2: 소싱처 카테고리 (M3 크롤이 채움 — 수기 드래프트는 None)
    source_site = Column(String(40))              # source_registry id
    source_category_path = Column(String(500))    # '신발>스니커즈>여성운동화'

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    markets = relationship("ProductDraftMarket", back_populates="draft",
                           cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_product_drafts_origin_status", "origin", "status"),
        Index("ix_product_drafts_model_code", "model_code"),
    )


class ProductDraftMarket(Base):
    """드래프트 × 마켓 — 마켓별 카테고리·판매가·등록결과."""
    __tablename__ = "product_draft_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("product_drafts.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    market = Column(String(32), nullable=False)       # 'smartstore' | 'coupang' | ...
    # [2026-07-17] 마켓당 다계정(롯데온 7계정 등) — 같은 드래프트를 계정 A·B 에 각각 등록하면
    # 마켓 상품번호가 계정마다 다르다. account_key 없이 (draft_id, market) 만 유니크면 B 등록이
    # A 의 market_product_id 를 덮어써 Phase 2 업데이트가 엉뚱한 스토어로 나간다(금전 손실).
    # nullable=False + 'default' 센티넬 — NULL 이면 유니크 제약이 무력화(NULL≠NULL)되므로.
    # (sets/models.py SetChannel 관례 동일). Phase 1A 는 단일계정 → 전부 'default'.
    account_key = Column(String(64), nullable=False, default="default")

    category_code = Column(String(64))                # 스스 leafCategoryId / 쿠팡 displayCategoryCode
    # 마켓별 판매가. Phase 1B 마진엔진이 채운다 — 1A 에서는 미배선(draft.sale_price 사용)
    sale_price = Column(Integer)

    # 'pending' | 'ok' | 'failed' | 'blocked'('blocked' = LIVE_REGISTER_ARMED 게이트 차단)
    # | 'uncertain'
    #
    # ★ [2026-07-23 리뷰 C-2] 'uncertain' = 「등록됨」도 「실패」도 아닌 **확인 전까지 잠금**.
    #   두 경로에서 생긴다: ①상품은 만들어졌는데 뒤 단계가 실패(ESM 옵션 부착 — 상품번호를
    #   안다) ②전송 뒤 끊김(상품번호를 모른다). 둘 다 마켓에 상품이 있을 수 있어서, 이걸
    #   'failed' 로 적으면 다음 「점검」이 그 마켓을 다시 ready 로 내주고 한 번 더 누르는
    #   순간 같은 상품이 두 개가 된다(= 유령 상품). 등록 가드(webapp/routes/bulk/drafts.py
    #   _ledger_guard)가 이 값을 「잠금」으로 읽는다 — 값 이름을 바꾸면 가드도 같이 고칠 것.
    status = Column(String(16), default='pending', nullable=False)
    market_product_id = Column(String(64))            # 스스 originProductNo / 쿠팡 sellerProductId
    error_code = Column(String(64))
    error_message = Column(Text)
    raw_json = Column(Text)                           # 마켓 원응답 (디버깅·감사)
    registered_at = Column(DateTime)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    draft = relationship("ProductDraft", back_populates="markets")

    __table_args__ = (
        UniqueConstraint("draft_id", "market", "account_key",
                         name="uq_product_draft_markets_draft_market_account"),
    )


class MarketCategory(Base):
    """판매처 마켓 카테고리 사전 — 6마켓 전수 수집 스냅샷 (스펙 2026-07-22 §A).

    재수집 시 사라진 코드는 지우지 않고 removed_at 마킹(맵핑 재확정 강등의 근거).
    """
    __tablename__ = 'market_categories'

    id = Column(Integer, primary_key=True)
    market = Column(String(20), nullable=False, index=True)   # smartstore|coupang|auction|gmarket|eleven11|lotteon
    code = Column(String(40), nullable=False)                 # 마켓 카테고리 코드 (ESM 은 site-cat 코드)
    name = Column(String(200), nullable=False)
    full_path = Column(String(500), nullable=False)           # '패션잡화>운동화>여성운동화' (구분자 '>')
    parent_code = Column(String(40))                          # 루트는 None
    depth = Column(Integer, nullable=False, default=1)
    is_leaf = Column(Boolean, nullable=False, default=False)
    extra_code = Column(String(40))                           # ESM: 짝 ESM표준(sd) 코드. 그 외 None
    raw_json = Column(Text)                                   # 마켓 응답 원문 조각 (버리지 않는다)
    harvested_at = Column(DateTime, nullable=False)           # 마지막으로 존재 확인된 수집 시각
    removed_at = Column(DateTime)                             # 재수집에서 사라진 시각 (None=현존)
    # [2026-07-23 이어받기 자식누락 차단] 이 노드를 fetch 했을 때 마켓이 알려준 자식 수
    # (리프는 0). NULL = 모름(옛 데이터, child_count 컬럼 추가 전에 저장된 행) — 이어받기
    # 판정(harvest_coupang known=...)은 NULL 이면 "완전히 확보했는지" 알 수 없으므로 안전하게
    # 재fetch 한다. len(children) == child_count 일 때만 "이 부모는 자식을 전부 저장했다"고
    # 믿고 skip 한다(자식 일부만 저장된 채 죽은 경우를 걸러낸다).
    child_count = Column(Integer)

    __table_args__ = (
        UniqueConstraint('market', 'code', name='uq_market_categories_market_code'),
    )


class MarketCategoryHarvestRun(Base):
    """마켓별 카테고리 전수 수집(harvest) 실행 상태 — 프로세스가 아닌 DB 가 진실 원천.

    [2026-07-22] 라이브 배포는 gunicorn `--workers 3`(OS 프로세스 3개)이다. 이전 구현은
    이 상태를 모듈 레벨 dict + threading.Lock 으로 들고 있었는데, 그건 프로세스 로컬이라
    ①같은 마켓 중복실행 방지(409)가 워커 간에 안 먹히고 ②GET status 폴링이 harvest 를
    돌린 워커가 아닌 다른 워커에 떨어지면 running=False·낡은 결과로 보인다(결과 증발처럼
    보이는 버그 재현 가능). 그래서 이 실행 상태를 테이블로 옮긴다 — 어느 워커가 요청을
    받아도 같은 행을 보고 같은 답을 준다.

    advisory lock(webapp/routes/api.py:pg_advisory_xact_lock 참조)은 쓰지 않는다 — 그건
    트랜잭션 수명(커밋/롤백까지)만 유효한데, harvest 는 수 분짜리 백그라운드 스레드라
    트랜잭션을 그렇게 오래 열어 둘 수 없다. 대신 행 자체를 "누가 실행 중"의 표식으로 쓰고
    `with_for_update()` 로 클레임을 원자적으로 만든다.

    스테일 회수: `running=True` 인데 `started_at` 이 30분을 넘겼으면 죽은 실행으로 보고
    새 POST 가 회수한다(워커 재시작으로 데몬 스레드가 함께 죽으면 running=True 로 영영
    남는 케이스 대비 — 데몬 스레드는 종료 시 자기 상태를 못 정리한다).
    """
    __tablename__ = 'category_harvest_runs'

    market = Column(String(20), primary_key=True)
    running = Column(Boolean, nullable=False, default=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    summary_json = Column(Text)
    error = Column(Text)
    # [2026-07-23 M1 실측 후속] 수 시간 걸리는 수집(쿠팡 등)이 "돌고 있는지 멈췄는지"
    # 구분이 안 되는 문제 — 지금까지 수집한 노드 수 + 마지막으로 그 숫자를 기록한 시각.
    # progress_at 이 오래 안 움직이면(예: 20분 전) 죽은 실행으로 의심할 근거가 된다.
    progress_count = Column(Integer)
    progress_at = Column(DateTime)
    # [2026-07-23 사고 #5 — 콜 예산 자기종료] 이 실행이 "완주" 인지 "예산 소진으로 미완" 인지.
    # 쿠팡은 한 실행이 COUPANG_MAX_CALLS_PER_RUN 콜만 쓰고 큐가 남아도 정상 종료한다(서버가
    # 백그라운드 스레드를 2~3분밖에 못 살리는 실측 대응 — 죽는 대신 스스로 끝내야 부분저장·
    # 마무리가 보장된다). True 면 화면에 "완료" 가 아니라 "이어받는 중 (N건 확보)" 로 보여야
    # 하고, 그 실행의 최종 저장은 반드시 partial=True 여야 한다(안 그러면 아직 안 훑은
    # 카테고리가 전부 removed_at 으로 마킹된다 — webapp/routes/bulk/categories.py 참조).
    # None/False = 완주(또는 이 컬럼 추가 전의 옛 행).
    incomplete = Column(Boolean)


class ProductDraftRegisterRun(Base):
    """드래프트 1건의 **복수 마켓 등록** 실행 상태 — 프로세스가 아닌 DB 가 진실 원천.

    왜 테이블인가 (두 가지 사고 이력):
      ① gunicorn 은 `--timeout 60`(sync worker) 이다. 6마켓 순차 등록을 한 HTTP 요청
         안에서 돌리면 60초를 넘겨 워커가 죽는다 — 그러면 **요청도 응답도 증발**하고,
         이미 마켓에 만들어진 상품은 롤백 없이 남는다(과거이력: 502 로 워커가 죽어
         회수 로직이 안 돌아 유령 상품이 남은 사고). 그래서 POST 는 202 만 주고
         실제 등록은 백그라운드 스레드가 돌린다(카테고리 수집과 같은 패턴).
      ② 라이브는 gunicorn `--workers 3`(OS 프로세스 3개)다. 실행 상태를 모듈 전역
         dict 로 들면 프로세스 로컬이라 ⓐ중복 실행 방지(409)가 다른 워커에 안 먹히고
         ⓑ진행률 폴링이 등록을 돌린 워커가 아닌 워커에 떨어지면 "실행 중인 게 없다"로
         보인다. 등록에서 그 오판은 **중복 등록**(같은 상품 2개 = 유령 상품)으로
         직결된다 — 카테고리 수집에서 이미 겪은 문제라 처음부터 테이블로 둔다.

    ★ 이 테이블의 존재 이유 중 절반은 「죽어도 진실을 잃지 않기」다. `current_market`
      은 **마지막으로 시작한**(끝난 게 아니라) 마켓이다. 스레드가 그 마켓 처리 도중
      죽으면 행은 `running=True` 인 채 남고, 폴링은 그 마켓을 "성공"도 "실패"도 아닌
      **불확실**로 보고한다("올라갔는지 모릅니다 — 마켓에서 확인하세요"). 등록은
      돈·계정이 걸린 경로라 모르는 것을 안다고 말하면 안 된다.

    ★★ 자동 재시도는 없다. 스테일(진행률이 STALE_AFTER 넘게 안 움직임) 행은 **새 POST
      가 있을 때만** 회수된다 — 서버가 알아서 다시 등록하면 그게 곧 중복 등록이다.
      사장님이 마켓에서 확인한 뒤 직접 다시 누르는 흐름만 허용한다.

    행은 드래프트당 1개(draft_id = PK)다. 같은 드래프트를 두 번 등록하는 일 자체가
    막아야 할 일이라 이력 테이블이 아니라 상태 테이블로 둔다(마켓별 이력·원문은
    `ProductDraftMarket` 장부가 이미 갖고 있다 — 여기서 중복 보관하지 않는다).
    """
    __tablename__ = 'draft_register_runs'

    draft_id = Column(Integer, primary_key=True)
    # 이번 실행의 식별자(uuid4 hex). 폴링이 "내가 시작한 그 실행인가"를 확인한다 —
    # 스테일 회수로 새 실행이 시작되면 job_id 가 바뀌므로 화면이 낡은 결과를 안 믿는다.
    job_id = Column(String(40))
    running = Column(Boolean, nullable=False, default=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    # 마지막으로 **시작한** 마켓(끝난 마켓이 아니다) — 죽었을 때 "어디서" 를 말해준다.
    current_market = Column(String(20))
    # 요청받은 마켓 순서 JSON(총 몇 개 중 몇 번째인지 화면이 그린다).
    markets_json = Column(Text)
    done_count = Column(Integer)      # 결과행이 확정된 마켓 수
    total_count = Column(Integer)     # 이번 실행이 처리할 마켓 수
    progress_at = Column(DateTime)    # 마지막으로 진행 상황을 기록한 시각(스테일 판정 기준)
    # 그때까지 확정된 결과행(list[dict]) — 폴링이 "그때까지 분량" 을 그대로 돌려준다.
    result_json = Column(Text)
    error = Column(Text)              # 실행 전체가 죽은 사유(마켓별 실패는 result_json 안)


class SourceCategory(Base):
    """소싱처 카테고리 사전 — 빵부스러기 축적(M3)과 트리 전수조사가 채운다 (스펙 §B)."""
    __tablename__ = 'source_categories'

    id = Column(Integer, primary_key=True)
    # 크롤 소싱처 키 = SourceProduct.site (musinsa·ssf·ssg·lemouton·lotteon·ss_lemouton·hmall·lotteimall)
    source_id = Column(String(40), nullable=False, index=True)
    path = Column(String(500), nullable=False)                   # '신발>스니커즈>여성운동화'
    leaf_name = Column(String(200), nullable=False)
    depth = Column(Integer, nullable=False, default=1)
    product_count = Column(Integer, nullable=False, default=0)   # 이 경로로 크롤된 상품 수(M3 증가)
    first_seen_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('source_id', 'path', name='uq_source_categories_source_path'),
    )


class CategoryMapRow(Base):
    """소싱처 카테고리 → 마켓 카테고리 맵핑 (스펙 §C — 하이브리드: 제안/확정/재확정).

    자동 확정 금지 — confirmed 는 사장님 클릭으로만 승격된다.
    """
    __tablename__ = 'category_map'

    id = Column(Integer, primary_key=True)
    source_id = Column(String(40), nullable=False)
    source_path = Column(String(500), nullable=False)
    market = Column(String(20), nullable=False)
    market_cat_code = Column(String(80), nullable=False)   # ESM 은 'sd코드/site코드' 조합 저장
    market_cat_path = Column(String(500))                  # 표시용
    status = Column(String(12), nullable=False, default='suggested')  # suggested|confirmed|re_confirm
    method = Column(String(20))                            # coupang_reco|name_sim|manual
    confidence = Column(Float)                             # 제안 근거 점수(0~1). 수기는 None
    candidates_json = Column(Text)                         # 상위 3 후보 [{code,path,score}] — 확정 게이트 표시용
    confirmed_at = Column(DateTime)
    updated_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('source_id', 'source_path', 'market',
                         name='uq_category_map_source_market'),
        Index('ix_category_map_market_code', 'market', 'market_cat_code'),
    )


class BrandRestriction(Base):
    """브랜드·지재권 제한표 (스펙 §D) — 걸린 마켓만 자동 제외, 사유 표시. 사장님이 직접 관리."""
    __tablename__ = 'brand_restrictions'

    id = Column(Integer, primary_key=True)
    brand = Column(String(120), nullable=False)      # 비교는 brand_restrict.normalize() 로
    market = Column(String(20), nullable=False)      # 6마켓 중 하나 또는 '*'(전마켓)
    category_prefix = Column(String(500), default='')# 비우면 그 마켓 전체, 채우면 그 경로 이하만
    reason = Column(String(300), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    # [2026-07-23 리뷰 수정 I4] 같은 (brand, market, category_prefix) 스코프로 중복 행이
    # 쌓이는 걸 막는다 — 테이블이 아직 라이브에 배포되지 않아 안전하게 추가 가능(신규
    # 배포 시 create_all 이 제약까지 함께 만든다. 기존 배포본이면 마이그레이션이 필요했겠지만
    # 이 테이블은 그 상태가 아니다). POST /api/brand-limits 는 이 스코프로 먼저 조회해
    # 있으면 갱신(upsert), 없으면 새로 만든다.
    __table_args__ = (
        UniqueConstraint('brand', 'market', 'category_prefix',
                         name='uq_brand_restrictions_scope'),
    )


class CoupangVendorSetting(Base):
    """쿠팡 계정정보 — 등록 payload 의 vendor 고정값 (M4-2).

    왜 계정별 1행인가: 반품지·출고지는 사장님이 **쿠팡 Wing 에 미리 등록해 둔 것**이라
    드래프트마다 달라지지 않는다. 드래프트에 붙이면 상품 수만큼 같은 값이 복제되고,
    반품지를 바꾼 날 옛 값이 남은 드래프트가 조용히 틀린 주소로 나간다.

    ★ vendor_id 는 여기 **없다** — `.env` 의 ``{env_prefix}_VENDOR_ID`` 가 단일 원천이다.
      (CoupangCredentials.vendor_id, lemouton/auth/secrets.py:149) DB 에 사본을 두면
      키를 바꾼 날 두 값이 갈려 **다른 계정 이름으로 등록**되는 사고가 난다.

    ★ outbound_place_code 는 쿠팡 문서상 Long 이지만 String 으로 둔다 — 코드는 계산에
      쓰지 않는 식별자이고, 앞자리 0·자릿수 변화에 안전하다(컴파일 시 int 로 바꾼다).
    """
    __tablename__ = 'coupang_vendor_settings'

    id = Column(Integer, primary_key=True)
    #: `.env` 접두사 = 계정 식별자. UploadAccount.env_prefix 와 같은 값.
    env_prefix = Column(String(64), nullable=False, unique=True)

    vendor_user_id = Column(String(64), default='')        # Wing 로그인 ID
    return_center_code = Column(String(32), default='')    # 반품지 센터코드
    return_charge_name = Column(String(128), default='')   # 반품지'명'(코드 아님)
    return_zip = Column(String(16), default='')
    return_address = Column(String(255), default='')
    return_address_detail = Column(String(255), default='')
    return_phone = Column(String(32), default='')          # companyContactNumber
    outbound_place_code = Column(String(32), default='')   # 출고지 코드

    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

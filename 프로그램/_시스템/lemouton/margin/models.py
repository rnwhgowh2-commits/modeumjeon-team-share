# -*- coding: utf-8 -*-
"""마진 분석 세션 영속화.

Alembic 없음 — shared/db.py:init_db() 의 Base.metadata.create_all 이 생성한다.
등록 조건: app.py 가 이 모듈을 import 할 것.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    Boolean, Date, DateTime, Float, Integer, JSON, LargeBinary, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


class MarginAnalysis(Base):
    """분석 1회 = 레코드 1개. 팀 전체가 같은 목록을 본다. 최근 20건 보관."""

    __tablename__ = "margin_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # webapp/auth/models.py 와 동일하게 utcnow — 저장소 표준(naive UTC)에 맞춘다.
    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, index=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    period_from: Mapped[_dt.date] = mapped_column(Date)
    period_to: Mapped[_dt.date] = mapped_column(Date)

    buy_file_key: Mapped[str] = mapped_column(String(512))
    buy_filename: Mapped[str] = mapped_column(String(255))

    markets_fetched: Mapped[list] = mapped_column(JSON, default=list)
    markets_failed: Mapped[list] = mapped_column(JSON, default=list)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)

    result_blob: Mapped[bytes] = mapped_column(LargeBinary)


class MarginPendingUpload(Base):
    """업로드→분석 사이 스테이징 — 팀 공유 단일 row (id=1 고정).

    🔴 왜 DB 인가 (2026-07-23 사고)
      예전엔 라우트 모듈의 전역 dict(`_PENDING`)에 뒀다. 그런데 앱은 gunicorn **워커 3개**로
      돈다 → 업로드가 A워커에 저장되고 분석이 B워커로 가면 "먼저 더망고 매입 엑셀을
      업로드하세요"가 뜬다. 파일은 멀쩡히 올렸는데도. 분석 전에 마켓별 수집(6요청)을
      먼저 돌리게 되면서 워커가 갈릴 확률이 확 올라가 실제로 터졌다.
      ★프로세스 전역 변수는 이 앱에서 '저장'이 아니다 — 워커가 여럿이면 매번 다른 곳을 본다.

    DataFrame 이 아니라 **원본 바이트**를 저장하고 분석 때 다시 파싱한다(피클 금지 —
    pandas 버전이 바뀌면 못 읽는다). 406행 재파싱은 수백 ms 라 문제되지 않는다.

    팀 공유 단일 행인 이유: 이 앱은 팀 전체가 같은 데이터를 본다(CLAUDE.md). 동시에 둘이
    올리면 마지막 업로더가 이긴다 — 기존 전역 dict 와 같은 성질이라 새로 생기는 위험은 없다.
    """

    __tablename__ = "margin_pending_upload"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    buy_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    buy_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    period_from: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)


class MarginAnalyzeJob(Base):
    """분석 백그라운드 작업 상태 — job_id(문자열 uuid) 로 조회.

    🔴 왜 DB 인가 (MarginPendingUpload 와 같은 이유, 2026-07-23 사고 재발 방지)
      앱은 gunicorn 워커 여러 개로 돈다. `/analyze/start` 가 스레드를 띄운 워커와
      뒤이은 `/analyze/status` 폴링을 받는 워커가 다를 수 있다 — 작업 상태를
      프로세스 전역 dict 에 두면 다른 워커에서 "알 수 없는 작업 id"가 뜬다.

    🔴 왜 백그라운드로 도는가 (2026-09-05)
      매입행 12,949개짜리 더망고 엑셀에서 동기 `/api/margin/analyze` 가 100초를
      넘겨 Cloudflare 가 524(게이트웨이 타임아웃)로 연결을 끊었다 — 원인은
      `matcher.match_data`(원본 무수정 이식, 손대지 않는다)가 매입행 수에 비례해
      매출 전체를 훑는 알고리즘이라 대용량 파일에서 항상 그 벽에 걸린다.
      요청·응답 왕복만 짧게(즉시 job_id 반환) 만들고, 실제 계산은 스레드에서
      시간 제약 없이 돈다.
    """

    __tablename__ = "margin_analyze_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|done|error
    analysis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # {counts, markets_failed, notices, period_from, period_to} — analyze() 응답의
    # payload 이외 부분만. payload 본체(수 MB)는 MarginAnalysis.result_blob 에 이미
    # 있으므로(store.save) 여기 또 담지 않는다 — 같은 자료를 두 곳에 안 둔다.
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)


class CardKeywordConfig(Base):
    """카드별 분류 키워드 설정 — 팀 공유 단일 row (id=1 고정).

    원본(대량등록 마진계산기)은 단일 사용자 card_keywords.json 이었으나, 팀 공유
    앱에서는 DB 한 행으로 승격한다(멀티유저가 같은 설정을 본다). `config` 에 전체
    설정 JSON(top-level `cards` + `_comment`/`version` 등)을 통째로 담는다 — 원본
    계약이 top-level 키를 그대로 보존하도록 요구하므로 컬럼 분해하지 않는다.
    비어 있으면 lemouton/margin/card_keywords_seed.json 으로 시드한다.
    """

    __tablename__ = "card_keyword_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)


class ProductCountConfig(Base):
    """계층 분석 경로별 등록수 — 팀 공유 단일 row (id=1 고정).

    원본(대량등록 마진계산기)은 단일 사용자 product_counts.json({경로키: 등록수}) 이었으나,
    팀 공유 앱에서는 DB 한 행으로 승격한다(멀티유저가 같은 등록수를 본다). `counts` 에
    {경로키: int} dict 를 통째로 담는다 — 계층 분석의 매출효율·마진효율(매출÷등록수) 입력.
    CardKeywordConfig 와 동일 패턴. 비어 있으면 빈 dict(시드 불필요).
    """

    __tablename__ = "product_count_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)


class SourcingAccountOwner(Base):
    """소싱처 계정 담당자(owner) 라벨 — 마진 계산기 소싱처 계정 관리 탭 전용.

    ``sourcing_credentials`` 에는 owner 컬럼이 없다(create_all 은 기존 테이블에
    컬럼을 추가하지 못하므로 그 테이블을 건드리면 라이브 DB 가 깨진다). 또한
    ``SourcingAccount.display_name`` 은 소싱처 운영센터 라벨로 이미 쓰이므로
    덮어쓰면 그 화면 표시가 오염된다(accounts.py:1660). 그래서 담당자 라벨은
    (source, account_key)→owner 를 담는 작은 사이드 테이블로 분리한다.
    owner 는 비밀이 아닌 라벨 → 평문 컬럼으로 충분. Alembic 없음 —
    shared/db.py:init_db() 의 create_all 이 생성한다(margin.models 는 무조건 import).
    """

    __tablename__ = "sourcing_account_owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    account_key: Mapped[str] = mapped_column(String(64), nullable=False)
    owner: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "account_key",
                         name="uq_sourcing_account_owners_source_key"),
    )


class PurchaseCard(Base):
    """소싱처 매입가 계산에 쓰는 결제카드 마스터 — 카드 1장 = 행 1개.

    ■ 왜 별도 테이블인가
      적립율은 **소싱처와 무관한 카드 고유값**이다(넥슨현대카드는 어느 소싱처에서
      결제하든 2.7%). 소싱처별 혜택 테이블(``source_benefit_templates``)에 카드마다
      적립율을 복제하면 소싱처 N개 × 카드 M개로 같은 숫자가 흩어져, 한 곳만 고치면
      나머지가 조용히 옛값을 쓴다(= 매입가 오차 = 금전 손실). 적립율의 단일 진실
      원천을 여기 한 곳으로 둔다. 소싱처별 혜택은 ``pay_method`` 로 이 표의 ``key``
      를 가리키기만 한다(배선은 M1-4).

    ■ 왜 margin 패키지인가
      app.py 가 ``lemouton.margin.models`` 를 이미 import 한다(= create_all 등록
      보장). ``lemouton.sourcing.models`` 는 소싱처 스코프 도메인이라 "소싱처 무관"
      인 이 표를 두면 스코프를 오해하게 만든다. ``lemouton.pricing.models`` 는
      dataclass 전용(Base 미등록)이라 신규 import 배선이 더 필요하다.

    ■ 컬럼을 처음에 다 넣는 이유
      Alembic 없음 — create_all 은 **기존 테이블에 컬럼을 추가하지 않는다**.
      나중 추가는 shared/db.py 의 ``_apply_lightweight_migrations()`` (ADD COLUMN·
      CREATE INDEX 만 가능, **ADD CONSTRAINT 경로 없음**) 뿐이라, unique 제약은
      지금이 유일하게 싼 순간이다. ``sort_order`` 도 나중에 붙이기 곤란해 선반영
      (카드 17장 드롭다운은 표시 순서가 반드시 필요).
    """

    __tablename__ = "purchase_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 코드에서 pay_method 태그로 쓰는 식별자 (예: 'nexon_hyundai'). 불변 취급.
    #
    # ⚠ 실제 길이 제약은 이 String(64) 가 아니라 **pay_method 의 VARCHAR(16)** 이다.
    #   소싱처별 청구할인은 SourceBenefitTemplate/OptionBenefitOverride 의
    #   ``pay_method = <이 key>`` 로 카드를 가리키므로(sourcing/models.py), 16자를
    #   넘는 key 는 라이브(PostgreSQL)에서 그 행을 저장하지 못한다. 개발기는
    #   SQLite 라 길이를 강제하지 않아 조용히 통과 → 테스트가 유일한 방어선
    #   (tests/margin/test_purchase_card.py::test_seed_keys_fit_pay_method_column).
    #   폭을 넓히는 선택지는 없다 — shared/db.py 에 ADD COLUMN 경로뿐.
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)   # 화면 표시명
    # 카드 고유 적립율. 0~1 (0.027 = 2.7%). 범위 방어는 purchase_card_store 에서
    # ValueError — 조용한 클램프는 '틀린 숫자를 에러 없이' 통과시켜 금액을 오염시킨다.
    accrual_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 현대카드 계열 표식 — 기존 '현대카드 2.73% fallback' 플로어 판정용(M1-4 배선).
    is_hyundai_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)


class MarketLearnedRates(Base):
    """마켓이 한 번 알려준 값을 기억해 두는 곳 — 팀 공유 단일 row (id=1 고정).

    🔴 왜 필요한가 (2026-07-25 정답지 전수 대조에서 발견)
      두 곳에서 같은 병이 났다 — **조회 한 번 안에서만 아는 값**이라, 그 조회에 근거가
      안 들어오면 매번 다시 모른다:

      · 롯데온 제휴 판별 — `_lo_learn_channels` 가 같은 조회의 크롤 확정분으로 chNo 를
        배우지만 조회가 끝나면 버린다. 다음 조회에 그 채널 확정분이 없으면 또 '미확인'
        으로 떨어지고, 제휴 2%(상품가)가 정산에서 안 빠진다.
        실측: 주문 2026072318882737 = 998원(단가 49,900의 2.00%),
              2026072318947800 = 610원(단가 30,500의 2.00%) 만큼 정산이 과다.
      · 쿠팡 미정산 추정 — 고정 11.55% 를 쓰는데 실제 요율은 상품마다 다르다
        (실측 11.67~12.56%). 같은 상품의 정산 확정분이 이미 실요율을 알려줬는데도
        조회가 끝나면 잊는다.

    ★기억은 **확정 근거에서만** 만든다(추정에서 다시 배우면 오류가 자기증식한다).
    ★JSON 컬럼은 in-place 변경을 감지 못한다 — store 가 새 dict 를 재대입한다.
    """

    __tablename__ = "market_learned_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # {chNo(str): 제휴여부(bool)} — 근거=판매자센터 크롤 확정 판매경로.
    lotteon_channels: Mapped[dict] = mapped_column(JSON, default=dict)
    # {vendorItemId(str): 수수료율(float 0~1)} — 근거=revenue-history 실정산액 역산.
    coupang_fee_rates: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)

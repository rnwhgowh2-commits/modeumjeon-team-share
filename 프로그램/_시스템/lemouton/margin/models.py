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
    shopmine_file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    shopmine_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
    shop_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    shop_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

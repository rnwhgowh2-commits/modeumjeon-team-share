# -*- coding: utf-8 -*-
"""PurchaseCard — 모델 등록/컬럼 + unique 제약 + 시드 멱등 + 적립율 범위 방어."""
import pytest
from sqlalchemy.exc import IntegrityError

from shared.db import Base
from lemouton.margin import purchase_card_store as PCS
from lemouton.margin.models import PurchaseCard


@pytest.fixture
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.margin.models  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["purchase_cards"]])
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


# ── 모델 ────────────────────────────────────────────────────────────

def test_model_registered_on_base():
    """Alembic 없음 — create_all 이 유일한 생성 경로라 Base 등록이 곧 테이블 생성."""
    assert "purchase_cards" in Base.metadata.tables


def test_columns():
    """create_all 은 기존 테이블에 컬럼을 못 붙인다 → 컬럼 집합을 못 박아둔다."""
    cols = {c.name for c in PurchaseCard.__table__.columns}
    assert cols == {
        "id", "key", "label", "accrual_rate", "is_hyundai_default",
        "active", "sort_order", "created_at", "updated_at",
    }


def test_app_imports_margin_models():
    """모델을 app.py 가 import 하지 않으면 테이블이 조용히 안 생긴다."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "app.py"
    assert "import lemouton.margin.models" in src.read_text(encoding="utf-8")


def test_create_and_defaults(session):
    session.add(PurchaseCard(key="test_card", label="테스트카드", accrual_rate=0.02))
    session.commit()
    row = PCS.get_card(session, "test_card")
    assert row.label == "테스트카드"
    assert row.accrual_rate == 0.02
    assert row.is_hyundai_default is False
    assert row.active is True
    assert row.created_at is not None


def test_key_is_unique(session):
    """unique 제약은 지금이 유일하게 싼 순간 — 경량 마이그레이션에 ADD CONSTRAINT 경로가 없다."""
    session.add(PurchaseCard(key="dup", label="A", accrual_rate=0.0))
    session.commit()
    session.add(PurchaseCard(key="dup", label="B", accrual_rate=0.0))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ── 시드 ────────────────────────────────────────────────────────────

def test_seed_inserts_confirmed_values(session):
    added = PCS.seed_purchase_cards(session)
    assert added == 17
    cards = {c.key: c for c in PCS.list_cards(session)}
    assert len(cards) == 17
    # 관리엑셀 확정값 — 지어낸 값이 섞이면 매입가가 조용히 틀어진다.
    assert cards["nexon_hyundai"].label == "넥슨현대카드"
    assert cards["nexon_hyundai"].accrual_rate == 0.027
    assert cards["nexon_hyundai"].is_hyundai_default is True
    assert cards["lotte_prof"].accrual_rate == 0.02
    assert cards["lotte_liiv"].accrual_rate == 0.015
    assert cards["kbank"].accrual_rate == 0.011
    assert cards["samsung_select"].accrual_rate == 0.01
    assert cards["bc_baro"].accrual_rate == 0.01
    assert cards["mus_money_plgold"].accrual_rate == 0.0


def test_seed_hyundai_flags(session):
    """현대카드 계열은 정확히 2장 — 플로어 판정이 엉뚱한 카드로 새지 않도록."""
    PCS.seed_purchase_cards(session)
    hyundai = {c.key for c in PCS.list_cards(session) if c.is_hyundai_default}
    assert hyundai == {"nexon_hyundai", "musinsa_hyundai"}


def test_seed_is_idempotent(session):
    PCS.seed_purchase_cards(session)
    assert PCS.seed_purchase_cards(session) == 0
    assert PCS.seed_purchase_cards(session) == 0
    assert session.query(PurchaseCard).count() == 17


def test_seed_preserves_user_edits(session):
    """재부팅 시드가 사용자 수정을 되돌리면 = 에러 없이 틀린 매입가."""
    PCS.seed_purchase_cards(session)
    PCS.set_accrual_rate(session, "kbank", 0.05)
    card = PCS.get_card(session, "kbank")
    card.label = "케이뱅크(수정)"
    session.commit()

    PCS.seed_purchase_cards(session)  # 재부팅 재현

    card = PCS.get_card(session, "kbank")
    assert card.accrual_rate == 0.05
    assert card.label == "케이뱅크(수정)"


def test_seed_adds_newly_appended_card(session):
    """count()==0 게이트였다면 나중에 추가한 카드가 영영 안 들어온다."""
    PCS.seed_purchase_cards(session)
    session.query(PurchaseCard).filter_by(key="bc_baro").delete()
    session.commit()
    assert PCS.seed_purchase_cards(session) == 1
    assert PCS.get_card(session, "bc_baro").accrual_rate == 0.01


def test_seed_order_matches_seed_list(session):
    PCS.seed_purchase_cards(session)
    keys = [c.key for c in PCS.list_cards(session)]
    assert keys == [k for (k, _l, _r, _h) in PCS.PURCHASE_CARD_SEED]


# ── 적립율 범위 방어 (클램프 아님 — ValueError) ──────────────────────

@pytest.mark.parametrize("bad", [-0.01, -1, 1.01, 2.7, 100])
def test_accrual_rate_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        PCS.validate_accrual_rate(bad)


@pytest.mark.parametrize("ok", [0, 0.0, 0.027, 0.5, 1, 1.0])
def test_accrual_rate_accepts_range(ok):
    assert PCS.validate_accrual_rate(ok) == float(ok)


def test_accrual_rate_rejects_non_numeric():
    with pytest.raises(ValueError):
        PCS.validate_accrual_rate("2.7%")
    with pytest.raises(ValueError):
        PCS.validate_accrual_rate(None)


def test_accrual_rate_rejects_nan():
    """NaN 은 모든 비교가 False 라 범위 검사를 그냥 통과한다 — 별도 차단."""
    with pytest.raises(ValueError):
        PCS.validate_accrual_rate(float("nan"))


def test_set_accrual_rate_rejects_bad_value_without_writing(session):
    """거부 시 DB 에 반쯤 쓰인 값이 남으면 안 된다."""
    PCS.seed_purchase_cards(session)
    with pytest.raises(ValueError):
        PCS.set_accrual_rate(session, "kbank", 2.7)
    session.rollback()
    assert PCS.get_card(session, "kbank").accrual_rate == 0.011


def test_set_accrual_rate_unknown_key(session):
    PCS.seed_purchase_cards(session)
    with pytest.raises(ValueError):
        PCS.set_accrual_rate(session, "no_such_card", 0.01)


def test_list_cards_excludes_inactive_by_default(session):
    PCS.seed_purchase_cards(session)
    PCS.get_card(session, "hana").active = False
    session.commit()
    assert "hana" not in {c.key for c in PCS.list_cards(session)}
    assert "hana" in {c.key for c in PCS.list_cards(session, include_inactive=True)}


# ── pay_method 폭 가드 ──────────────────────────────────────────────

def _pay_method_widths():
    """청구할인 행이 카드키를 담는 두 컬럼의 폭. 모델에서 읽어온다(하드코딩 금지).

    폭을 나중에 넓히면 이 테스트가 자동으로 따라간다.
    """
    from lemouton.sourcing.models import (
        SourceBenefitTemplate, OptionBenefitOverride)
    return {
        f"{m.__name__}.pay_method": m.__table__.columns["pay_method"].type.length
        for m in (SourceBenefitTemplate, OptionBenefitOverride)
    }


def test_seed_keys_fit_pay_method_column():
    """모든 카드키가 pay_method 폭 이하여야 한다.

    ■ 왜 이 테스트가 필요한가 (개발기에서 절대 안 잡히는 유형)
      소싱처별 카드 청구할인은 ``pay_method = <PurchaseCard.key>`` 로 카드를
      가리킨다(card_candidates.py 가 실제로 ``pay_method=c.key`` 를 쓴다).
      그런데 pay_method 는 VARCHAR(16) 이고, PurchaseCard.key 는 String(64) 다.
      → key 가 16자를 넘으면 **그 카드는 청구할인 행을 저장할 수 없다.**

      개발 워크트리는 .env 가 없어 SQLite 로 뜨는데 SQLite 는 VARCHAR 길이를
      강제하지 않아 **조용히 통과**한다. 라이브(Supabase PostgreSQL)에서만
      저장이 깨진다. 그래서 런타임이 아니라 이 테스트가 유일한 방어선이다.

      shared/db.py 의 _apply_lightweight_migrations() 에는 ADD COLUMN 밖에 없어
      **컬럼 폭을 넓히는 경로가 없다** → 넓히는 쪽이 아니라 키를 줄이는 쪽이 답.
    """
    widths = _pay_method_widths()
    limit = min(widths.values())
    over = [
        (key, len(key)) for (key, _lab, _r, _h) in PCS.PURCHASE_CARD_SEED
        if len(key) > limit
    ]
    assert not over, (
        f"카드키가 pay_method 폭({limit}자)을 초과 — 이 카드들은 라이브"
        f"(PostgreSQL)에서 청구할인 행 저장이 실패한다. 컬럼 폭을 넓히는 경로가"
        f" 없으니(shared/db.py 는 ADD COLUMN 뿐) **키를 줄여라**.\n"
        + "\n".join(f"  - {k!r}: {n}자 ({n - limit}자 초과)" for k, n in over)
        + f"\n폭 출처: {widths}"
    )

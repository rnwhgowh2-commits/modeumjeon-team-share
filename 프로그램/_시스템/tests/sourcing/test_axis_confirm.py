# -*- coding: utf-8 -*-
"""[TEST] 소싱처별 「확인 도장」 — 사장님이 눈으로 한 번 본 것을 남긴다.

사장님 확정 (2026-08-02):
  「소싱처별 매칭된 결과를 보여주도록 해. 사용자가 직접 한번 확인하는게 필수야. 그래야 사고가 안나.」

왜 소싱처 단위인가
  같은 색을 소싱처마다 다르게 부른다. 무신사에서 확인한 것이 롯데온을 확인해준 게 아니다.

핵심 규칙
  · 도장은 (상품, 소싱처) 단위.
  · **그 소싱처의 맞춤이 바뀌면 도장이 풀린다.** 안 그러면 「확인했다」가 옛 상태를 가리킨다.
"""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

CODE = "LT-CONFIRM"


@pytest.fixture
def s():
    for _m in ("lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
               "lemouton.sources.models", "lemouton.templates.models",
               "lemouton.inventory.models", "lemouton.multitenancy.models",
               "lemouton.sourcing.axis_alias", "lemouton.sourcing.axis_confirm",
               "lemouton.matrix.models"):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, SessionLocal, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()

    from lemouton.sourcing.axis_alias import SourceAxisAlias
    from lemouton.sourcing.axis_confirm import AxisConfirmation
    session = SessionLocal()

    def clean():
        session.query(AxisConfirmation).filter_by(model_code=CODE).delete(synchronize_session=False)
        session.query(SourceAxisAlias).filter(
            SourceAxisAlias.source_key.in_(["musinsa", "lotteon"])).delete(synchronize_session=False)
        session.commit()

    clean()
    yield session
    clean()
    session.close()


def test_confirm_and_read(s):
    from lemouton.sourcing import axis_confirm as ac
    assert ac.is_confirmed(s, CODE, "musinsa") is False
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    assert ac.is_confirmed(s, CODE, "musinsa") is True


def test_confirm_is_per_source(s):
    """무신사를 확인해도 롯데온은 여전히 안 본 것이다."""
    from lemouton.sourcing import axis_confirm as ac
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    assert ac.is_confirmed(s, CODE, "lotteon") is False


def test_confirm_is_per_bundle(s):
    from lemouton.sourcing import axis_confirm as ac
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    assert ac.is_confirmed(s, "OTHER-BUNDLE", "musinsa") is False


def test_confirm_twice_does_not_duplicate(s):
    from lemouton.sourcing import axis_confirm as ac
    from lemouton.sourcing.axis_confirm import AxisConfirmation
    ac.confirm(s, CODE, "musinsa")
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    assert s.query(AxisConfirmation).filter_by(model_code=CODE, source_key="musinsa").count() == 1


def test_unconfirm(s):
    from lemouton.sourcing import axis_confirm as ac
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    assert ac.unconfirm(s, CODE, "musinsa") is True
    s.commit()
    assert ac.is_confirmed(s, CODE, "musinsa") is False


# ── 핵심: 맞춤이 바뀌면 도장이 풀린다 ───────────────────────────────────

def test_changing_alias_releases_the_stamp(s):
    """맞춤을 고치면 「확인했다」가 옛 상태를 가리키므로 도장을 푼다."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_confirm as ac
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    ax.set_alias(s, source_key="musinsa", axis_name="색상",
                 our_value="검정", source_value="BLACK")
    s.commit()
    assert ac.is_confirmed(s, CODE, "musinsa") is False


def test_clearing_alias_also_releases(s):
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_confirm as ac
    ax.set_alias(s, source_key="musinsa", axis_name="색상",
                 our_value="검정", source_value="BLACK")
    s.commit()
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    ax.clear_alias(s, "musinsa", "색상", "검정")
    s.commit()
    assert ac.is_confirmed(s, CODE, "musinsa") is False


def test_other_source_stamp_survives(s):
    """무신사 맞춤을 고쳐도 롯데온 도장은 그대로."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_confirm as ac
    ac.confirm(s, CODE, "musinsa")
    ac.confirm(s, CODE, "lotteon")
    s.commit()
    ax.set_alias(s, source_key="musinsa", axis_name="색상",
                 our_value="검정", source_value="BLACK")
    s.commit()
    assert ac.is_confirmed(s, CODE, "musinsa") is False
    assert ac.is_confirmed(s, CODE, "lotteon") is True


def test_confirmed_map(s):
    from lemouton.sourcing import axis_confirm as ac
    ac.confirm(s, CODE, "musinsa")
    s.commit()
    m = ac.confirmed_map(s, CODE, ["musinsa", "lotteon", "ssf"])
    assert m == {"musinsa": True, "lotteon": False, "ssf": False}


def test_empty_values_rejected(s):
    from lemouton.sourcing import axis_confirm as ac
    with pytest.raises(ValueError):
        ac.confirm(s, "", "musinsa")
    with pytest.raises(ValueError):
        ac.confirm(s, CODE, "")

# -*- coding: utf-8 -*-
"""[TEST] 「이 소싱처엔 없다」를 저장할 수 있어야 한다 (라이브에서 잡힌 결함).

라이브 실측 (2026-08-02)
  사전이 「250 = 250mm」로 붙인 칸에서 「✕ 비워 두기」를 골랐는데 **그대로 250mm 로 돌아왔다.**
  이유 — 저장소가 「이 값 = 저 표기」만 담을 수 있고 「이 소싱처엔 이 값이 없다」는 담지 못했다.
  지울 게 없으니 지워지지 않고, 다음 조회에서 사전이 다시 붙였다.

왜 중요한가
  사전이 **틀리게** 붙였을 때 사장님이 거부할 방법이 없다.
  「사용자가 직접 한번 확인하는게 필수」라는 요구가 여기서 깨진다 —
  확인 화면인데 **아니라고 말할 수가 없다.**

두 가지를 구분한다
  · 「✕ 이 소싱처엔 없음」  = 사장님이 없다고 **정함**  → 사전이 다시 못 붙인다
  · 「↩ 자동으로 되돌리기」 = 내 지정을 **거둠**       → 사전에 다시 맡긴다
"""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

SRC = "musinsa"


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
        session.query(SourceAxisAlias).filter(
            SourceAxisAlias.source_key.in_([SRC, "lotteon"])).delete(synchronize_session=False)
        session.query(AxisConfirmation).filter(
            AxisConfirmation.source_key.in_([SRC, "lotteon"])).delete(synchronize_session=False)
        session.commit()

    clean()
    yield session
    clean()
    session.close()


# ── 핵심: 사전이 붙인 것을 거부할 수 있다 ───────────────────────────────

def test_dictionary_match_can_be_rejected(s):
    """사전이 「250 = 250mm」로 붙여도, 없다고 정하면 안 붙는다."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    assert am.match_one(s, source_key=SRC, axis_name="사이즈",
                        our_value="250", source_value="250mm").matched is True
    ax.set_absent(s, source_key=SRC, axis_name="사이즈", our_value="250")
    s.commit()
    assert am.match_one(s, source_key=SRC, axis_name="사이즈",
                        our_value="250", source_value="250mm").matched is False


def test_absent_blocks_every_candidate(s):
    """없다고 정하면 어떤 표기와도 안 붙는다."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="블랙")
    s.commit()
    for v in ("BLACK", "블랙", "BK", "검정"):
        assert am.match_one(s, source_key=SRC, axis_name="색상",
                            our_value="블랙", source_value=v).matched is False


def test_absent_is_per_source(s):
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="블랙")
    s.commit()
    assert am.match_one(s, source_key="lotteon", axis_name="색상",
                        our_value="블랙", source_value="BLACK").matched is True


# ── 되돌리기 — 사전에 다시 맡긴다 ───────────────────────────────────────

def test_reset_gives_it_back_to_the_dictionary(s):
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_absent(s, source_key=SRC, axis_name="사이즈", our_value="250")
    s.commit()
    assert ax.clear_alias(s, SRC, "사이즈", "250") is True
    s.commit()
    assert am.match_one(s, source_key=SRC, axis_name="사이즈",
                        our_value="250", source_value="250mm").matched is True


def test_absent_then_pick_a_value(s):
    """없다고 했다가 다시 고를 수 있다."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="블랙")
    s.commit()
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="블랙", source_value="딥블랙")
    s.commit()
    assert am.match_one(s, source_key=SRC, axis_name="색상",
                        our_value="블랙", source_value="딥블랙").matched is True


# ── 1:1 잠금이 「없음」 때문에 깨지지 않아야 한다 ───────────────────────

def test_two_absents_do_not_conflict(s):
    """여러 값을 「없음」으로 정해도 서로 부딪히지 않는다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="블랙")
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="화이트")
    s.commit()
    rows = ax.list_aliases(s, SRC, "색상")
    assert {r["our_value"]: r["absent"] for r in rows} == {"블랙": True, "화이트": True}


def test_absent_does_not_take_a_source_value(s):
    """「없음」은 소싱처 표기를 차지하지 않는다 — 다른 줄이 그 표기를 쓸 수 있다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="블랙")
    s.commit()
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="검정", source_value="BLACK")   # 충돌 없이 성공해야
    s.commit()
    assert ax.get_map(s, SRC, "색상") == {"검정": "BLACK"}


# ── 확인 도장은 풀린다 ──────────────────────────────────────────────────

def test_setting_absent_releases_the_stamp(s):
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_confirm as ac
    ac.confirm(s, "LT", SRC)
    s.commit()
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="블랙")
    s.commit()
    assert ac.is_confirmed(s, "LT", SRC) is False


# ── 화면 제안에 「없음으로 정함」이 드러나야 한다 ───────────────────────

def test_suggest_marks_absent_rows(s):
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="블랙")
    s.commit()
    out = am.suggest_axis(s, source_key=SRC, axis_name="색상",
                          our_values=["블랙", "화이트"],
                          source_values=["BLACK", "WHITE"])
    by = {r["our_value"]: r for r in out["rows"]}
    assert by["블랙"]["status"] == "absent"
    assert by["블랙"]["source_value"] is None
    assert by["블랙"]["origin"] == "manual"
    assert by["화이트"]["source_value"] == "WHITE"      # 남은 줄은 정상 동작
    assert out["summary"]["absent"] == 1

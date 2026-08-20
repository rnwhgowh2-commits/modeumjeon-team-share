# -*- coding: utf-8 -*-
"""[TEST] 매칭 3단 계단 — 축 값 하나를 소싱처 표기에 붙이는 단일 판정기.

설계: docs/사전점검_옵션URL매핑_설계.md §15-C·§15-D, §16 2단계

3단 계단 (이 순서 고정)
  1. 축 매핑(DB)  — 사장님이 고른 것. 무엇보다 우선한다.
  2. 정규화       — 띄어쓰기·대소문자·-_. 제거. 「다크 네이비」 = 「다크네이비」
  3. 내장 사전    — shared/sku_format 의 색 21종·사이즈 16종

핵심 규칙
  · **애매하면 안 붙인다.** 지금 매트릭스는 부분일치라 「오프화이트」를 「화이트」에 붙여
    남의 색 가격을 보여준다(§15-D). 여기서는 붙이지 않고 사람에게 보낸다.
  · 축 이름은 자유다 — 색 사전·사이즈 사전을 **둘 다** 조회하고, 결과가 갈리면 확인 필요.
  · 우리 값 하나 = 소싱처 값 하나. 후보가 겹치면 자동 확정하지 않는다.
"""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

SRC = "musinsa"


@pytest.fixture
def s():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.multitenancy.models",
        "lemouton.sourcing.axis_alias",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, SessionLocal, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()

    from lemouton.sourcing.axis_alias import SourceAxisAlias
    session = SessionLocal()
    session.query(SourceAxisAlias).filter(
        SourceAxisAlias.source_key == SRC).delete(synchronize_session=False)
    session.commit()
    yield session
    session.query(SourceAxisAlias).filter(
        SourceAxisAlias.source_key == SRC).delete(synchronize_session=False)
    session.commit()
    session.close()


# ══════════════════════════════════════════════════════════════════════
#  §15-D 실측표 — 새 방식이 지금 방식과 정반대로 틀린다
# ══════════════════════════════════════════════════════════════════════

BINDS = [
    ("다크 네이비", "다크네이비", "exact"),   # 띄어쓰기만 다름 → 사전 없이 통과
    ("블랙", "검정", "dict"),                 # 한글 동의어
    ("BLACK", "블랙", "dict"),                # 영문
    ("Dark Navy", "다크네이비", "dict"),      # 영문 + 띄어쓰기
    ("BK", "블랙", "dict"),                   # 약어
]
NOT_BINDS = [
    ("블랙&화이트", "블랙"),        # 복합색 — 사람만 안다
    ("네이비", "다크네이비"),        # 지금은 부분일치로 잘못 붙는 것
    ("오프화이트", "화이트"),        # 〃
    ("블랙 (블랙아웃솔)", "블랙"),   # 〃
    ("딥네이비", "다크네이비"),      # 사전에 없음
]


@pytest.mark.parametrize("src_val,our_val,method", BINDS)
def test_binds(s, src_val, our_val, method):
    from lemouton.sourcing import axis_match as am
    r = am.match_one(s, source_key=SRC, axis_name="색상",
                     our_value=our_val, source_value=src_val)
    assert r.matched is True
    assert r.method == method


@pytest.mark.parametrize("src_val,our_val", NOT_BINDS)
def test_does_not_bind(s, src_val, our_val):
    """애매한 것은 붙이지 않는다 — 남의 색 가격을 보여주지 않기 위해."""
    from lemouton.sourcing import axis_match as am
    r = am.match_one(s, source_key=SRC, axis_name="색상",
                     our_value=our_val, source_value=src_val)
    assert r.matched is False


# ── 사이즈도 같은 판정기로 (축 이름을 몰라도 된다) ──────────────────────

@pytest.mark.parametrize("src_val,our_val", [
    ("250mm", "250"), ("7US", "250"), ("230 mm", "230"),
    ("one size", "FREE"), ("FREE", "FREE"),
])
def test_size_binds_without_knowing_axis_name(s, src_val, our_val):
    from lemouton.sourcing import axis_match as am
    r = am.match_one(s, source_key=SRC, axis_name="아무이름",
                     our_value=our_val, source_value=src_val)
    assert r.matched is True


def test_size_m_not_bound_to_250(s):
    from lemouton.sourcing import axis_match as am
    assert am.match_one(s, source_key=SRC, axis_name="사이즈",
                        our_value="250", source_value="M").matched is False


# ── 1단: 축 매핑(DB)이 무엇보다 우선 ────────────────────────────────────

def test_db_alias_wins_over_dictionary(s):
    """사장님이 「검정 = BK-01」로 정했으면 사전보다 그게 우선이다."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="검정", source_value="BK-01")
    s.commit()
    r = am.match_one(s, source_key=SRC, axis_name="색상",
                     our_value="검정", source_value="BK-01")
    assert (r.matched, r.method) == (True, "db")


def test_db_alias_makes_unknown_value_bind(s):
    """사전이 모르는 표기도 한 번 가르치면 붙는다."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    assert am.match_one(s, source_key=SRC, axis_name="색상",
                        our_value="블랙", source_value="딥블랙").matched is False
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="블랙", source_value="딥블랙")
    s.commit()
    r = am.match_one(s, source_key=SRC, axis_name="색상",
                     our_value="블랙", source_value="딥블랙")
    assert (r.matched, r.method) == (True, "db")


def test_db_alias_is_per_source(s):
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="블랙", source_value="딥블랙")
    s.commit()
    assert am.match_one(s, source_key="lotteon", axis_name="색상",
                        our_value="블랙", source_value="딥블랙").matched is False


# ══════════════════════════════════════════════════════════════════════
#  화면용 — 축 한 줄씩 제안 (1층 드롭다운의 초기 상태)
# ══════════════════════════════════════════════════════════════════════

def test_suggest_marks_auto_review_none(s):
    from lemouton.sourcing import axis_match as am
    out = am.suggest_axis(
        s, source_key=SRC, axis_name="색상",
        our_values=["검정", "화이트", "블랙&화이트", "검증색"],
        source_values=["BLACK", "WHITE", "BLACK & WHITE", "BLACK/WHITE"],
    )
    by = {r["our_value"]: r for r in out["rows"]}
    assert by["검정"]["status"] == "auto" and by["검정"]["source_value"] == "BLACK"
    assert by["화이트"]["status"] == "auto" and by["화이트"]["source_value"] == "WHITE"
    # 사전이 모르는 복합색 → 비워 두고 후보만 (사장님이 고름)
    assert by["블랙&화이트"]["status"] == "none"
    assert by["검증색"]["status"] == "none"
    # 우리가 안 만든 소싱처 표기는 따로 알려준다
    assert set(out["unused_source_values"]) == {"BLACK & WHITE", "BLACK/WHITE"}


def test_suggest_uses_saved_alias_and_reports_origin(s):
    """저장된 것은 'saved' — 수기/자동 구분이 그대로 나온다(시안 v6 파란 「수기」)."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="블랙&화이트", source_value="BLACK/WHITE", origin="manual")
    s.commit()
    out = am.suggest_axis(s, source_key=SRC, axis_name="색상",
                          our_values=["블랙&화이트"],
                          source_values=["BLACK & WHITE", "BLACK/WHITE"])
    row = out["rows"][0]
    assert (row["status"], row["origin"], row["source_value"]) == ("saved", "manual", "BLACK/WHITE")


def test_suggest_does_not_give_one_source_value_to_two_our_values(s):
    """한 소싱처 표기를 둘이 나눠 가질 수 없다 — 재고 이중계상 차단."""
    from lemouton.sourcing import axis_match as am
    out = am.suggest_axis(s, source_key=SRC, axis_name="사이즈",
                          our_values=["240", "250"], source_values=["7US"])
    picked = [r["source_value"] for r in out["rows"] if r["source_value"]]
    assert picked.count("7US") <= 1
    # 둘 다 후보라 자동 확정하지 않는다 → 사람에게 보낸다
    assert all(r["status"] in ("review", "none") for r in out["rows"])


def test_suggest_summary_counts(s):
    from lemouton.sourcing import axis_match as am
    out = am.suggest_axis(s, source_key=SRC, axis_name="색상",
                          our_values=["검정", "화이트", "검증색"],
                          source_values=["BLACK", "WHITE"])
    assert out["summary"] == {"saved": 0, "auto": 2, "review": 0, "none": 1, "absent": 0}


def test_suggest_saved_alias_not_offered_to_others(s):
    """이미 쓰는 표기는 다른 줄 후보에서 빠진다(드롭다운 잠금과 같은 기준)."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match as am
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="검정", source_value="BLACK")
    s.commit()
    out = am.suggest_axis(s, source_key=SRC, axis_name="색상",
                          our_values=["검정", "다크네이비"], source_values=["BLACK"])
    by = {r["our_value"]: r for r in out["rows"]}
    assert by["검정"]["status"] == "saved"
    assert by["다크네이비"]["source_value"] is None
    assert "BLACK" not in by["다크네이비"]["candidates"]


# ── 빈 입력 방어 ────────────────────────────────────────────────────────

def test_empty_inputs_are_safe(s):
    from lemouton.sourcing import axis_match as am
    assert am.match_one(s, source_key=SRC, axis_name="색상",
                        our_value="", source_value="BLACK").matched is False
    assert am.match_one(s, source_key=SRC, axis_name="색상",
                        our_value="검정", source_value="").matched is False
    out = am.suggest_axis(s, source_key=SRC, axis_name="색상",
                          our_values=[], source_values=[])
    assert out["rows"] == [] and out["summary"]["auto"] == 0

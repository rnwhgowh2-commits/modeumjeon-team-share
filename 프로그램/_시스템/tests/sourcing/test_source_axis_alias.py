# -*- coding: utf-8 -*-
"""[TEST] 축 매핑 저장소 — 소싱처별 「우리 축 값 ↔ 소싱처 표기」.

설계: docs/사전점검_옵션URL매핑_설계.md §15 (축 맞추기 확정안)

지키는 규칙:
  · 저장 단위 = **소싱처** (무신사에서 한 번 맞추면 그 소싱처의 다른 상품에서도 자동)
  · 우리 값 하나 = 소싱처 값 하나 (1:1) — 두 우리 값이 같은 소싱처 값을 못 쓴다
    (같은 소싱처 옵션이 두 우리 옵션에 붙으면 재고가 두 배로 계산 → 초과 판매)
  · 축 이름은 색상/사이즈 고정이 아니다 — 사장님이 매트릭스에서 지은 이름 그대로(모델·재질…)
  · 되돌리기(clear) 가 한 번에 된다
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
        SourceAxisAlias.source_key.in_([SRC, "lotteon"])).delete(synchronize_session=False)
    session.commit()
    yield session
    session.query(SourceAxisAlias).filter(
        SourceAxisAlias.source_key.in_([SRC, "lotteon"])).delete(synchronize_session=False)
    session.commit()
    session.close()


# ── 저장·조회 ──────────────────────────────────────────────────────────

def test_set_and_get_map(s):
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="화이트", source_value="WHITE")
    s.commit()
    assert ax.get_map(s, SRC, "색상") == {"검정": "BLACK", "화이트": "WHITE"}


def test_axis_name_is_free_text_not_only_color_size(s):
    """축 이름은 고정이 아니다 — 모델·재질도 같은 방식으로 저장된다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="모델",
                 our_value="르무통 클래식", source_value="LEMOUTON CLASSIC")
    ax.set_alias(s, source_key=SRC, axis_name="재질", our_value="스웨이드", source_value="SUEDE")
    s.commit()
    assert ax.get_map(s, SRC, "모델") == {"르무통 클래식": "LEMOUTON CLASSIC"}
    assert ax.get_map(s, SRC, "재질") == {"스웨이드": "SUEDE"}


def test_scope_is_per_source(s):
    """무신사에서 배운 것이 롯데온에 새지 않는다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    s.commit()
    assert ax.get_map(s, "lotteon", "색상") == {}


# ── 1:1 규칙 ───────────────────────────────────────────────────────────

def test_reassign_same_our_value_overwrites(s):
    """같은 우리 값을 다시 고르면 덮어쓴다 (행이 늘지 않는다)."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing.axis_alias import SourceAxisAlias
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    s.commit()
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BK-01")
    s.commit()
    assert ax.get_map(s, SRC, "색상") == {"검정": "BK-01"}
    assert s.query(SourceAxisAlias).filter_by(
        source_key=SRC, axis_name="색상", our_value="검정").count() == 1


def test_same_source_value_cannot_be_used_twice(s):
    """이미 다른 우리 값이 쓰는 소싱처 값은 못 쓴다 — 재고 이중계상 차단."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    s.commit()
    with pytest.raises(ax.AliasConflict) as e:
        ax.set_alias(s, source_key=SRC, axis_name="색상",
                     our_value="다크네이비", source_value="BLACK")
    assert "검정" in str(e.value)      # 누가 쓰고 있는지 알려준다


def test_taken_values_reports_owner(s):
    """드롭다운 잠금 표시용 — 어떤 소싱처 값을 누가 쓰는지."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    s.commit()
    assert ax.taken_values(s, SRC, "색상") == {"BLACK": "검정"}


# ── 되돌리기 ───────────────────────────────────────────────────────────

def test_clear_alias_frees_the_source_value(s):
    """되돌리면 그 소싱처 값이 풀려 다른 우리 값이 쓸 수 있다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    s.commit()
    assert ax.clear_alias(s, SRC, "색상", "검정") is True
    s.commit()
    assert ax.get_map(s, SRC, "색상") == {}
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="다크네이비", source_value="BLACK")
    s.commit()
    assert ax.get_map(s, SRC, "색상") == {"다크네이비": "BLACK"}


def test_clear_missing_returns_false(s):
    from lemouton.sourcing import axis_alias as ax
    assert ax.clear_alias(s, SRC, "색상", "없는값") is False


# ── 역방향 조회 (소싱처 표기 → 우리 값) ─────────────────────────────────

def test_resolve_source_value_to_our_value(s):
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    s.commit()
    assert ax.resolve(s, SRC, "색상", "BLACK") == "검정"
    assert ax.resolve(s, SRC, "색상", "WHITE") is None


def test_resolve_ignores_spacing_and_case(s):
    """소싱처가 표기를 살짝 바꿔도 (대소문자·띄어쓰기) 같은 것으로 본다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상",
                 our_value="다크네이비", source_value="DARK NAVY")
    s.commit()
    assert ax.resolve(s, SRC, "색상", "dark navy") == "다크네이비"
    assert ax.resolve(s, SRC, "색상", "DarkNavy") == "다크네이비"


def test_conflict_check_also_ignores_spacing(s):
    """잠금도 같은 기준으로 — 'BLACK' 을 쓰는데 'black' 을 또 못 쓴다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    s.commit()
    with pytest.raises(ax.AliasConflict):
        ax.set_alias(s, source_key=SRC, axis_name="색상",
                     our_value="다크네이비", source_value=" black ")


# ── 손으로 고친 것 표시 (시안 v6) ───────────────────────────────────────

def test_origin_defaults_to_manual_and_is_kept(s):
    """사장님이 고른 것은 '수기'로 남는다 — 나중에 자동과 구분하기 위해."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="화이트",
                 source_value="WHITE", origin="auto")
    s.commit()
    rows = ax.list_aliases(s, SRC, "색상")
    got = {r["our_value"]: r["origin"] for r in rows}
    assert got == {"검정": "manual", "화이트": "auto"}


# ── 빈 값 방어 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw", [
    {"source_key": "", "axis_name": "색상", "our_value": "검정", "source_value": "BLACK"},
    {"source_key": SRC, "axis_name": "", "our_value": "검정", "source_value": "BLACK"},
    {"source_key": SRC, "axis_name": "색상", "our_value": "", "source_value": "BLACK"},
    {"source_key": SRC, "axis_name": "색상", "our_value": "검정", "source_value": "  "},
])
def test_empty_values_rejected(s, kw):
    from lemouton.sourcing import axis_alias as ax
    with pytest.raises(ValueError):
        ax.set_alias(s, **kw)


# ── 판정 경로 세션 캐시 (2026-08-05 성능) ──────────────────────────────
#
# 🔴 왜: match_one 이 비교 한 번마다 is_absent·resolve 를 각각 쿼리해서,
#   라이브(Supabase 원격) 조립이 옵션 102개 상품에서 **12분** 걸렸다(send job 4
#   실측 713초). 판정 경로는 (소싱처, 축) 쌍당 1쿼리로 끝나야 한다.

def _count_queries(s, fn):
    from sqlalchemy import event
    from shared.db import engine
    n = [0]

    def _cnt(conn, cursor, statement, params, context, executemany):
        n[0] += 1
    event.listen(engine, "before_cursor_execute", _cnt)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _cnt)
    return n[0]


def test_판정경로는_비교횟수에_비례해_쿼리가_늘지_않는다(s):
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="화이트", source_value="WHITE")
    s.commit()
    s.info.pop("_axis_alias_pairs", None)      # 캐시 초기화 후 시작

    def 백번_판정():
        for _ in range(100):
            assert ax.resolve(s, SRC, "색상", "black") == "검정"
            assert ax.is_absent(s, SRC, "색상", "검정") is False
    n = _count_queries(s, 백번_판정)
    # (소싱처, 축) 쌍 1개 = 적재 1쿼리. 100회 반복해도 늘지 않는다.
    assert n <= 2, f"판정 200번에 쿼리 {n}개 — 세션 캐시가 깨졌다(라이브 12분 조립 재발)"


def test_같은_세션에서_고치면_캐시가_아니라_새_값을_읽는다(s):
    """쓰기가 캐시를 안 버리면 「맞춰 놨는데 안 붙는」 유령이 된다."""
    from lemouton.sourcing import axis_alias as ax
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="BLACK")
    assert ax.resolve(s, SRC, "색상", "BLACK") == "검정"     # 캐시에 실림
    ax.set_alias(s, source_key=SRC, axis_name="색상", our_value="검정", source_value="JET")
    assert ax.resolve(s, SRC, "색상", "JET") == "검정"       # 새 표기가 보인다
    assert ax.resolve(s, SRC, "색상", "BLACK") is None       # 옛 표기는 풀렸다
    ax.set_absent(s, source_key=SRC, axis_name="색상", our_value="검정")
    assert ax.is_absent(s, SRC, "색상", "검정") is True      # 없음 처리도 즉시 보인다
    assert ax.resolve(s, SRC, "색상", "JET") is None
    ax.clear_alias(s, SRC, "색상", "검정")
    assert ax.is_absent(s, SRC, "색상", "검정") is False     # 지운 것도 즉시 보인다

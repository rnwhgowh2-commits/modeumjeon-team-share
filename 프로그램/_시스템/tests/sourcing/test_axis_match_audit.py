# -*- coding: utf-8 -*-
"""[TEST] 3단계 착수 전 점검 — 판정기 교체 시 달라질 칸을 뽑아낸다.

설계: docs/사전점검_옵션URL매핑_설계.md §15-D, §16 3단계

이 점검이 하는 말
  lost   : 값이 사라질 칸 — 그동안 부분일치로 남의 색이 붙어 있던 것
  gained : 값이 새로 생길 칸 — BLACK·검정·7US 되찾기
  changed: 값이 바뀔 칸 — 둘 다 붙었는데 서로 다른 소싱처 옵션 (가장 위험)
"""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")


class SO:
    """SourceOption 대역 — 판정에 쓰는 칸만."""

    def __init__(self, color, size, price=109900, stock=1):
        self.color_text = color
        self.size_text = size
        self.current_price = price
        self.current_stock = stock


@pytest.fixture
def s():
    for _m in ("lemouton.sourcing.models", "lemouton.sources.models",
               "lemouton.sourcing.axis_alias"):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, SessionLocal, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()
    session = SessionLocal()
    yield session
    session.close()


# ── 옛 판정이 잘못 붙이던 것 → 새 판정은 안 붙임 (lost) ─────────────────

@pytest.mark.parametrize("src_color,our_color", [
    ("오프화이트", "화이트"),
    ("네이비", "다크네이비"),
    ("블랙&화이트", "블랙"),
])
def test_old_binds_but_new_does_not(s, src_color, our_color):
    from lemouton.sourcing import axis_match_audit as au
    cands = [SO(src_color, "250")]
    assert au.old_match(cands, our_color, "250") is cands[0]
    assert au.new_match(s, source_key="musinsa", cands=cands,
                        opt_color=our_color, opt_size="250") is None


# ── 새 판정이 되찾는 것 (gained) ────────────────────────────────────────

@pytest.mark.parametrize("src_color,our_color", [
    ("BLACK", "블랙"),
    ("블랙", "검정"),
    ("Dark Navy", "다크네이비"),
])
def test_new_binds_what_old_missed(s, src_color, our_color):
    from lemouton.sourcing import axis_match_audit as au
    cands = [SO(src_color, "250")]
    assert au.old_match(cands, our_color, "250") is None
    assert au.new_match(s, source_key="musinsa", cands=cands,
                        opt_color=our_color, opt_size="250") is cands[0]


def test_new_binds_us_size(s):
    from lemouton.sourcing import axis_match_audit as au
    cands = [SO("블랙", "7US")]
    assert au.old_match(cands, "블랙", "250") is None       # 숫자 7 ≠ 250
    assert au.new_match(s, source_key="musinsa", cands=cands,
                        opt_color="블랙", opt_size="250") is cands[0]


# ── 둘 다 같게 붙는 것은 차이로 잡히지 않아야 한다 ──────────────────────

def test_same_result_is_not_a_difference(s):
    from lemouton.sourcing import axis_match_audit as au
    cands = [SO("블랙", "250"), SO("화이트", "250")]
    assert au.old_match(cands, "블랙", "250") is cands[0]
    assert au.new_match(s, source_key="musinsa", cands=cands,
                        opt_color="블랙", opt_size="250") is cands[0]


def test_single_color_url_size_only_still_works(s):
    """단품 URL(색 없음) — 옛/새 모두 사이즈만으로 붙는다."""
    from lemouton.sourcing import axis_match_audit as au
    cands = [SO("", "250")]
    assert au.old_match(cands, "다크네이비", "250") is cands[0]
    assert au.new_match(s, source_key="musinsa", cands=cands,
                        opt_color="다크네이비", opt_size="250") is cands[0]


def test_color_only_source_still_works(s):
    """사이즈를 안 주는 소싱처(색상 전용) — 색만으로 붙는 폴백 유지."""
    from lemouton.sourcing import axis_match_audit as au
    cands = [SO("BLACK", "")]
    assert au.new_match(s, source_key="musinsa", cands=cands,
                        opt_color="블랙", opt_size="250") is cands[0]


# ── 축 매핑(DB)을 가르치면 lost 가 사라진다 ─────────────────────────────

def test_teaching_alias_restores_the_binding(s):
    """「오프화이트 = 화이트」라고 가르치면 다시 붙는다 — 사장님이 되살릴 수 있다."""
    from lemouton.sourcing import axis_alias as ax
    from lemouton.sourcing import axis_match_audit as au
    cands = [SO("오프화이트", "250")]
    assert au.new_match(s, source_key="musinsa", cands=cands,
                        opt_color="화이트", opt_size="250") is None
    ax.set_alias(s, source_key="musinsa", axis_name="색상",
                 our_value="화이트", source_value="오프화이트")
    s.commit()
    try:
        assert au.new_match(s, source_key="musinsa", cands=cands,
                            opt_color="화이트", opt_size="250") is cands[0]
    finally:
        ax.clear_alias(s, "musinsa", "색상", "화이트")
        s.commit()


# ── 전수 비교가 빈 DB 에서도 안전한가 ───────────────────────────────────

def test_compare_all_is_safe_on_empty_db(s):
    from lemouton.sourcing import axis_match_audit as au
    out = au.compare_all(s, limit=5)
    assert out["summary"] == {"lost": 0, "gained": 0, "changed": 0}
    assert out["checked"] == 0

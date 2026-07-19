"""등급 설정 저장소 — 사장님이 화면에서 고친 값이 남아야 한다.

설계서 §4: "모든 수치는 제안값. 최종은 사장님이 화면에서 설정."
지금까지 GradeConfig 는 코드 기본값뿐이었다 — 고칠 데가 없었다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lemouton.sources.crawl_grade import GRADE_NAMES
from lemouton.sources.grade_config_store import (
    get_grade_config, reset_grade_config, save_grade_config,
)
from shared.db import Base


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


# ── 기본값 ──────────────────────────────────────────────────────

def test_저장한_적_없으면_코드_기본값(db):
    cfg = get_grade_config(db)
    assert cfg.ceiling_per_day == pytest.approx(2.0)     # 사장님 결정 4-A
    assert cfg.floor_per_day == pytest.approx(1 / 3)     # 사장님 결정 3-A
    assert len(cfg.boundaries) == len(GRADE_NAMES) - 1


def test_기본값을_읽어도_행을_만들지_않는다(db):
    """읽기만 했는데 DB 에 쓰면 '사장님이 정한 값'과 '기본값'을 구분 못 하게 된다."""
    from lemouton.sources.grade_config_store import GradeConfigRow
    get_grade_config(db)
    assert db.query(GradeConfigRow).count() == 0


# ── 저장·복원 ───────────────────────────────────────────────────

def test_저장한_값이_그대로_돌아온다(db):
    save_grade_config(db, ceiling_per_day=6.0, floor_per_day=1 / 7)
    db.flush()
    cfg = get_grade_config(db)
    assert cfg.ceiling_per_day == pytest.approx(6.0)
    assert cfg.floor_per_day == pytest.approx(1 / 7)


def test_경계값도_저장된다(db):
    save_grade_config(db, boundaries=(150.0, 80.0, 40.0, 20.0, 5.0))
    db.flush()
    assert get_grade_config(db).boundaries == (150.0, 80.0, 40.0, 20.0, 5.0)


def test_계수도_저장된다(db):
    save_grade_config(db, coefficients=(4.0, 3.0, 2.0, 1.0, 0.5, 0.25))
    db.flush()
    assert get_grade_config(db).coefficients[0] == pytest.approx(4.0)


def test_일부만_바꾸면_나머지는_그대로(db):
    save_grade_config(db, ceiling_per_day=6.0)
    db.flush()
    cfg = get_grade_config(db)
    assert cfg.ceiling_per_day == pytest.approx(6.0)
    assert cfg.floor_per_day == pytest.approx(1 / 3), "안 건드린 값이 기본값 그대로여야 한다"


def test_두_번_저장해도_행은_하나(db):
    from lemouton.sources.grade_config_store import GradeConfigRow
    save_grade_config(db, ceiling_per_day=3.0)
    db.flush()
    save_grade_config(db, ceiling_per_day=4.0)
    db.flush()
    assert db.query(GradeConfigRow).count() == 1
    assert get_grade_config(db).ceiling_per_day == pytest.approx(4.0)


# ── 🔴 잘못된 값은 저장 자체를 막는다 ───────────────────────────

def test_하한이_상한보다_크면_저장_거부(db):
    """저장되고 나서 읽을 때 터지면 화면이 통째로 죽는다 — 들어올 때 막는다."""
    with pytest.raises(ValueError):
        save_grade_config(db, ceiling_per_day=0.5, floor_per_day=2.0)


def test_경계값이_내림차순이_아니면_거부(db):
    with pytest.raises(ValueError):
        save_grade_config(db, boundaries=(100.0, 200.0, 33.0, 14.0, 3.0))


def test_경계값_개수가_틀리면_거부(db):
    with pytest.raises(ValueError):
        save_grade_config(db, boundaries=(100.0, 33.0))


def test_거부된_저장은_DB를_아예_안_건드린다(db):
    """검증이 **쓰기 전에** 끝나므로 rollback 조차 필요 없다.

    (GradeConfig 를 먼저 만들어 보고, 통과한 뒤에야 행을 손댄다.)
    """
    save_grade_config(db, ceiling_per_day=6.0)
    db.commit()
    with pytest.raises(ValueError):
        save_grade_config(db, boundaries=(1.0, 2.0, 3.0, 4.0, 5.0))
    # rollback 없이 바로 읽어도 멀쩡하다
    assert get_grade_config(db).ceiling_per_day == pytest.approx(6.0)


# ── 되돌리기 ────────────────────────────────────────────────────

def test_기본값으로_되돌릴_수_있다(db):
    save_grade_config(db, ceiling_per_day=9.0)
    db.flush()
    reset_grade_config(db)
    db.flush()
    assert get_grade_config(db).ceiling_per_day == pytest.approx(2.0)


def test_되돌리기는_저장한_적_없어도_안전(db):
    reset_grade_config(db)
    assert get_grade_config(db).ceiling_per_day == pytest.approx(2.0)

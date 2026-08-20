"""크롤 변동 주기 등급 — 강도(%)·평균주기·등급·제안계수.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md
사장님 확정 예시: "30일동안 5번 변동 → 30일 기준 1회 변동 시 평균 6일" (= 강도 16.7%)
"""
import pytest

from lemouton.sources.crawl_grade import (
    GRADE_NAMES,
    GradeConfig,
    average_period_days,
    classify,
    intensity_pct,
    per_day_text,
    proposed_per_day,
    raw_per_day,
    summarize,
    union_is_consistent,
)


# ── 강도 · 평균주기 ──────────────────────────────────────────────

def test_사장님_예시_30일_5회는_평균6일_강도16_7퍼센트():
    assert average_period_days(5, 30) == pytest.approx(6.0)
    assert intensity_pct(5, 30) == pytest.approx(16.667, abs=0.01)


def test_하루_1회가_100퍼센트():
    assert intensity_pct(30, 30) == pytest.approx(100.0)
    assert intensity_pct(1, 1) == pytest.approx(100.0)
    assert average_period_days(30, 30) == pytest.approx(1.0)


def test_하루_3회면_300퍼센트_주기는_3분의1일():
    assert intensity_pct(90, 30) == pytest.approx(300.0)
    assert average_period_days(90, 30) == pytest.approx(1 / 3)


def test_변동이_없으면_강도0이고_평균주기는_None():
    assert intensity_pct(0, 30) == 0.0
    assert average_period_days(0, 30) is None


def test_기간이_0이하면_거부():
    with pytest.raises(ValueError):
        intensity_pct(5, 0)
    with pytest.raises(ValueError):
        average_period_days(5, -1)


def test_음수_변동횟수는_거부():
    with pytest.raises(ValueError):
        intensity_pct(-1, 30)


# ── 등급 분류 ───────────────────────────────────────────────────

@pytest.mark.parametrize("pct,grade", [
    (500.0, 0),   # 하루 2회 이상
    (200.0, 0),   # 경계 포함
    (199.9, 1),   # 하루 1회
    (100.0, 1),
    (99.9, 2),    # 2~3일에 1회
    (33.0, 2),
    (32.9, 3),    # 주간급
    (14.0, 3),
    (13.9, 4),    # 월간급
    (3.0, 4),
    (2.9, 4),     # 0 초과면 월간급
    (0.0, 5),     # 변동 없음
])
def test_등급_경계값(pct, grade):
    assert classify(pct) == grade


def test_등급_이름은_6개():
    assert len(GRADE_NAMES) == 6
    assert GRADE_NAMES[0] == "하루 2회 이상"
    assert GRADE_NAMES[5] == "변동 없음"


def test_아주_작은_양수도_변동없음이_아니라_월간급():
    """30일에 1회(3.3%)는 월간급. 0 과 구분해야 '한 번도 안 바뀜'이 정확해진다."""
    assert classify(intensity_pct(1, 30)) == 4
    assert classify(intensity_pct(0, 30)) == 5


# ── 제안 계수 (하루 N회) ─────────────────────────────────────────

def test_상한_하루2회가_적용된다():
    """사장님 결정 4-A: 상한 하루 2회. 제안이 3회여도 2회로 깎인다."""
    assert raw_per_day(0) == pytest.approx(3.0)
    assert proposed_per_day(0) == pytest.approx(2.0)


def test_상위_두_등급은_상한때문에_같은_계수로_수렴하지만_등급은_유지된다():
    """설계서 §3-1: 계수는 같아져도 등급은 나눠 둔다(상한을 나중에 올릴 때 필요)."""
    assert proposed_per_day(0) == proposed_per_day(1) == pytest.approx(2.0)
    assert classify(500.0) != classify(150.0)


def test_하한_3일1회가_적용된다():
    """사장님 결정 3-A: 변동 없어도 3일에 1회는 돈다."""
    assert proposed_per_day(5) == pytest.approx(1 / 3)
    assert proposed_per_day(4) == pytest.approx(1 / 3)


def test_중간_등급은_그대로():
    assert proposed_per_day(2) == pytest.approx(1.0)
    assert proposed_per_day(3) == pytest.approx(0.5)


def test_사장님이_상한_하한을_바꿀_수_있다():
    """설계서 §4: 모든 수치는 제안값. 최종은 사장님이 설정."""
    cfg = GradeConfig(ceiling_per_day=6.0, floor_per_day=1 / 7)
    assert proposed_per_day(0, cfg) == pytest.approx(3.0)   # 상한이 높아 안 깎임
    assert proposed_per_day(5, cfg) == pytest.approx(1 / 7)  # 하한이 7일 1회


def test_사장님이_등급_경계를_바꿀_수_있다():
    cfg = GradeConfig(boundaries=(100.0, 50.0, 25.0, 10.0, 1.0))
    assert classify(150.0, cfg) == 0   # 기본값이면 1등급인데 경계가 낮아져 0등급
    assert classify(2.0, cfg) == 4


def test_경계값은_내림차순이어야_한다():
    with pytest.raises(ValueError):
        GradeConfig(boundaries=(100.0, 200.0, 33.0, 14.0, 3.0))


def test_경계값은_5개여야_한다():
    with pytest.raises(ValueError):
        GradeConfig(boundaries=(100.0, 33.0))


def test_하한이_상한보다_크면_거부():
    with pytest.raises(ValueError):
        GradeConfig(ceiling_per_day=0.5, floor_per_day=2.0)


# ── 사람이 읽는 표기 ─────────────────────────────────────────────

@pytest.mark.parametrize("per_day,text", [
    (2.0, "2회/일"),
    (1.0, "1회/일"),
    (0.5, "2일 1회"),
    (1 / 3, "3일 1회"),
    (1 / 7, "7일 1회"),
])
def test_계수_표기(per_day, text):
    assert per_day_text(per_day) == text


# ── 합집합 불변식 ───────────────────────────────────────────────

def test_합집합은_최댓값이상_합계이하():
    """설계서 §2: max(축별) ≤ 합집합 ≤ Σ(축별).

    같은 크롤 회차에 둘이 같이 바뀌면 합집합은 1회로 센다 → 합계보다 작다.
    어느 축이든 바뀐 날은 합집합에도 잡힌다 → 최댓값보다 크거나 같다.
    """
    axis = {"sp": 5, "bf": 2, "sa": 20, "sm": 8}
    assert union_is_consistent(axis, 20)   # = max
    assert union_is_consistent(axis, 25)   # 중간
    assert union_is_consistent(axis, 35)   # = sum
    assert not union_is_consistent(axis, 19)   # max 미만 — 있을 수 없음
    assert not union_is_consistent(axis, 36)   # sum 초과 — 있을 수 없음


def test_변동이_전혀_없으면_합집합도_0():
    assert union_is_consistent({"sp": 0, "bf": 0, "sa": 0, "sm": 0}, 0)
    assert not union_is_consistent({"sp": 0, "bf": 0, "sa": 0, "sm": 0}, 1)


# ── 요약 ────────────────────────────────────────────────────────

def test_요약은_합집합으로_등급을_매긴다():
    """설계서 §2: 크롤 계수의 기준축은 합집합. 축별은 화면·업로드 게이트용."""
    out = summarize(
        counts_by_axis={"sp": 5, "bf": 1, "sa": 60, "sm": 20},
        union_count=62,
        window_days=30,
    )
    assert out["grade"] == classify(intensity_pct(62, 30))
    assert out["intensity_pct"] == pytest.approx(intensity_pct(62, 30))
    assert out["average_period_days"] == pytest.approx(30 / 62)
    assert out["proposed_per_day"] == pytest.approx(2.0)      # 206% → 상한
    assert out["raw_per_day"] == pytest.approx(3.0)
    assert out["capped"] is True                              # 상한에 걸렸음을 표시


def test_요약에_축별_강도가_같이_담긴다():
    out = summarize(
        counts_by_axis={"sp": 5, "bf": 1, "sa": 60, "sm": 20},
        union_count=62,
        window_days=30,
    )
    assert out["axes"]["sp"]["intensity_pct"] == pytest.approx(intensity_pct(5, 30))
    assert out["axes"]["sm"]["average_period_days"] == pytest.approx(1.5)


def test_요약은_불일치하는_합집합을_거부한다():
    """조용한 실패 금지 — 데이터가 모순이면 계산해서 넘기지 말고 터뜨린다."""
    with pytest.raises(ValueError):
        summarize(counts_by_axis={"sp": 5, "sa": 20}, union_count=3, window_days=30)


def test_상한에_안_걸리면_capped는_False():
    out = summarize(counts_by_axis={"sp": 5}, union_count=5, window_days=30)
    assert out["capped"] is False
    assert out["floored"] is False


def test_하한에_걸리면_floored가_True():
    out = summarize(counts_by_axis={"sp": 0}, union_count=0, window_days=30)
    assert out["grade"] == 5
    assert out["floored"] is True
    assert out["proposed_per_day"] == pytest.approx(1 / 3)

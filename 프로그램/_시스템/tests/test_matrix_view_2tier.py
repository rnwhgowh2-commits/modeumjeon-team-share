"""회귀 방지 가드 — '매트릭스 보기'(압축 팝업) 표면노출가 + 최종매입가 2단 표기.

배경: 2026-06-22 cb8710bc 가 팝업을 '복원'하면서 2단 표기(표면 취소선 + 최종 파랑)를
통째로 누락 → 셀이 한 줄(검정)로만 보이는 사고가 있었다(fb1f985d 에서 재복원).
이 테스트는 템플릿이 다시 재작성되더라도 핵심 표기/안정화 장치가 사라지면
즉시 빨갛게 실패시켜 같은 회귀를 막는다.

화면(UI)은 전혀 건드리지 않는 순수 구조 가드.
"""
from pathlib import Path

import pytest

TPL = (
    Path(__file__).resolve().parents[1]
    / "webapp" / "templates" / "bundles" / "_matrix_v3.html"
)


def _text() -> str:
    return TPL.read_text(encoding="utf-8")


def test_template_exists():
    assert TPL.exists(), f"매트릭스 템플릿을 찾을 수 없음: {TPL}"


def test_two_tier_markup_present():
    """표면(취소선)·최종(파랑) 2단 셀 마크업이 존재해야 한다."""
    t = _text()
    assert "cmtx-surf" in t, "표면노출가 셀 클래스(cmtx-surf) 누락 — 2단 표기 회귀"
    assert "cmtx-final" in t, "최종매입가 셀 클래스(cmtx-final) 누락 — 2단 표기 회귀"


def test_two_tier_is_conditional_on_benefit():
    """혜택으로 최종 < 표면일 때만 2단(같으면 최종만 — 중복·모순 방지) 조건이 살아 있어야."""
    t = _text()
    assert "< surf" in t, "2단 표기 조건(price < surf)이 사라짐"


def test_legend_labels_present():
    """범례에 '표면노출가'/'최종매입가' 라벨이 있어야 한다."""
    t = _text()
    assert "표면노출가" in t, "범례 '표면노출가' 라벨 누락"
    assert "최종매입가" in t, "범례 '최종매입가' 라벨 누락"


def test_popup_open_ensures_benefits_loaded():
    """팝업 열 때 혜택 로드 보장 장치(__cmtxEnsureBreakdowns)가 정의+호출돼야 한다.

    이게 빠지면 혜택 캐시가 비어 있는 타이밍에 팝업을 열 때 표면가로 폴백 →
    최종==표면 → 2단이 한 줄로 둔갑한다(화면이 들쭉날쭉).
    """
    t = _text()
    assert t.count("__cmtxEnsureBreakdowns") >= 2, (
        "__cmtxEnsureBreakdowns 정의/호출이 빠짐 — 혜택 로드 타이밍에 따라 2단이 사라질 수 있음"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

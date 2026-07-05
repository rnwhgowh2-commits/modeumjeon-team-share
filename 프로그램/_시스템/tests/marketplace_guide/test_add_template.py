# -*- coding: utf-8 -*-
"""add.html — 2탭·4단계·마켓목록·프롬프트 생성 훅 검증."""
import pathlib

from webapp.routes import marketplace_guide as mg

TPL = pathlib.Path(mg.__file__).parents[1] / "templates" / "marketplace_guide"


def _add():
    return (TPL / "add.html").read_text(encoding="utf-8")


def test_two_tabs():
    html = _add()
    assert "신규 판매처 추가" in html
    assert "기존 마켓 연동 업데이트" in html


def test_four_steps_left_rail():
    html = _add()
    for label in ["마켓", "인증·계정", "지원 동작", "프롬프트"]:
        assert label in html
    assert "ma-rail" in html          # 좌측 세로 레일 클래스


def test_support_actions_three():
    html = _add()
    for a in ["신규 상품 등록", "기존 상품 연동", "가격·재고 업데이트"]:
        assert a in html


def test_market_list_injected():
    html = _add()
    assert "{% for m in coming %}" in html   # coming_soon 마켓 목록 루프


def test_prompt_generator_present():
    html = _add()
    assert "genPrompt" in html               # 프롬프트 생성 함수
    assert "복사" in html                     # 복사 버튼
    assert "docs/markets/_schema.yaml" in html  # 프롬프트가 실제 정본(스키마)을 가리킴
    assert "coupang.yaml" in html                # 참고 프로파일 명시
    assert "100% 검증 전" in html             # 무결성 규칙 문구
    assert "_새-마켓-추가-가이드.md" in html   # 자기충분 정본 가이드를 먼저 읽게 지목
    assert "코드 배선" in html                 # yaml만 쓰지 말고 코드까지 배선하라는 지시
    assert "추측 금지" in html                 # 문서·키 없으면 요청, 지어내지 말 것


def test_design_tokens():
    html = _add()
    assert "Pretendard" in html
    assert "#191F28" in html

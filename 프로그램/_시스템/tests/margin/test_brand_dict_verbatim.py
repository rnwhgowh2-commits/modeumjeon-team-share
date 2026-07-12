# -*- coding: utf-8 -*-
"""brand_dict 무수정 이식 검증 — 함수 존재 + 동작 + 원본과 바이트 동치(_DEFAULT_PATH 줄 제외)."""
import pathlib

import pytest

from lemouton.margin import brand_dict as B

ORIGINAL = pathlib.Path(r"C:\dev\대량등록 마진계산기\modules\brand_dict.py")


def test_public_api_present():
    for name in ("load_brand_dict", "match_brand", "get_map",
                 "reload_brand_dict", "save_brand_dict"):
        assert hasattr(B, name), name


def test_load_brand_dict_reads_repo_json():
    """포트의 기본 경로(레포 내 brand_dict.json)가 실제로 로드돼야 한다."""
    m = B.load_brand_dict()
    assert isinstance(m, dict) and m, "brand_dict.json 로드 실패(빈 dict)"
    assert m.get("NIKE") == "나이키"


def test_match_brand_latin_word_boundary():
    # 라틴 키워드는 단어경계 정확매칭 → 'LEE' 가 'SLEEVELESS' 에 매칭 안 됨.
    bmap = {"LEE": "리"}
    assert B.match_brand("LEE 데님 팬츠", bmap) == "리"
    assert B.match_brand("SLEEVELESS TOP", bmap) == ""


def test_match_brand_hangul_substring_and_longest_first():
    bmap = {"빈폴": "빈폴", "빈폴키즈": "빈폴키즈"}
    # 긴 키 우선 → '빈폴키즈' 가 '빈폴' 보다 먼저 매칭.
    assert B.match_brand("빈폴키즈 자켓", bmap) == "빈폴키즈"
    assert B.match_brand("빈폴 코트", bmap) == "빈폴"


def test_match_brand_no_match_returns_empty():
    assert B.match_brand("무명 상품", {"NIKE": "나이키"}) == ""


def test_source_is_verbatim_except_data_path_line():
    """원본과의 diff 가 _DEFAULT_PATH 한 줄뿐이어야 한다(데이터파일 위치 = 유일 허용 적응).

    원본은 개발자 PC 에만 있는 단독앱이라 CI·팀원 PC 에서는 skip 된다.
    (skip 이 아니라 FileNotFoundError 로 '에러' 나면 스위트 전체가 빨개진다.)
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    ported = pathlib.Path(B.__file__).read_text(encoding="utf-8").splitlines()
    original = ORIGINAL.read_text(encoding="utf-8").splitlines()

    def strip(lines):
        # 유일 허용 적응 = 데이터파일 경로(_DEFAULT_PATH):
        #   원본: <app_root>/brand_dict.json (dirname(dirname(__file__)))
        #   포트: <module_dir>/brand_dict.json (dirname(__file__))
        return [ln for ln in lines if "_DEFAULT_PATH" not in ln]

    assert strip(ported) == strip(original), \
        "brand_dict 본문이 원본과 다릅니다 — 무수정 이식 규칙 위반"


def test_original_path_guard_is_skippable():
    """원본 경로가 없는 PC(CI·팀원)에서 FileNotFoundError 로 '에러' 나면 안 된다."""
    import inspect
    src = inspect.getsource(test_source_is_verbatim_except_data_path_line)
    assert "ORIGINAL.exists()" in src, "원본 부재 시 skip 가드가 없습니다"

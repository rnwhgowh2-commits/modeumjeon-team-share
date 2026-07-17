# -*- coding: utf-8 -*-
"""컴파일러 공통 경계 유틸 (스스·쿠팡 두 컴파일러가 공유).

options.py 가 두 옵션 빌더를 공통 헬퍼 위에 올린 것과 같은 구조 — 컴파일러도
자유형 JSON 경계(저장된 options_json·images_json·notice_json, 폼/엑셀 붙여넣기
숫자)를 여기 한곳에서 방어한다. 그래야 쿠팡 컴파일러(Task 7)가 같은 세 버그를
복사하지 않고 이 하드닝을 상속한다.

방어 대상(코드리뷰가 스스 컴파일러에서 잡은 3종):
  1. 손상된 JSON 이 default 로 뭉개져 '옵션 없는 단일 SKU' 로 조용히 등록되던 것
     → loads_json 이 '비었음' 과 '깨졌음' 을 구분한다.
  2. int('75,800')·int('75800.0') 가 500 을 내던 것
     → coerce_int 가 options._num(콤마·소수·bool·nan 방어)을 재사용한다.
  3. (이미지 원소 타입검사는 마켓별 — 스스는 CDN 호스트, 쿠팡은 공개 URL — 각
     컴파일러가 처리한다. 여기선 공용 강제만 둔다.)
"""
# [2026-07-18] 대량등록 Phase 1A Task 6 후속 — 경계 하드닝 공용화

import json

# _num 은 options.py 의 module-private 헬퍼지만, 이 자유형 숫자 경계의 정본 강제기다
# (콤마·'3.0'·float·bool·nan 전부 방어). 다시 구현하면 오히려 중복이라 그대로 재사용한다.
from lemouton.registration.options import _num, OptionValueInvalid


class CompileError(ValueError):
    """드래프트를 마켓 payload 로 만들 수 없음. 조용한 폴백 금지.

    스스·쿠팡 두 컴파일러가 공유하는 단일 예외 — 상위(서비스·라우트)가 이 하나만
    잡으면 된다.
    """


def loads_json(raw, default, *, what: str):
    """저장된 JSON 문자열 → 파이썬 객체. '비었음' 과 '깨졌음' 을 구분한다.

    비었으면(None·빈 문자열) default 를 돌려준다 — 정당한 미입력이다.
    하지만 **내용은 있는데 깨진 JSON** 은 default 로 뭉개지 않고 CompileError 를
    던진다. options_json 이 잘려 저장된 드래프트가 default([])로 넘어가면 옵션이
    통째로 사라진 채 '성공' 으로 등록되는 조용한 실패가 되기 때문이다
    (options.py::_normalize 가 크게 실패시키려던 바로 그 손상이, _loads 가 먼저
    삼켜버려 _normalize 에 닿지도 못했다).

    Args:
        what: 오류 메시지에 쓸 필드 이름(옵션/이미지/고시).

    Raises:
        CompileError: raw 가 비어있지 않은데 JSON 으로 못 읽음.
    """
    if raw is None or raw == '':
        return default
    if not isinstance(raw, str):
        # 이미 파싱된 객체(list/dict)를 그대로 넘긴 경우는 통과.
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise CompileError(
            f'저장된 데이터가 손상됐습니다({what}) — 다시 저장해 주세요.') from e


def coerce_int(raw, field: str):
    """자유형 입력(폼·엑셀 붙여넣기) → int|None. '75,800'·'75800.0'·75800.0 모두 처리.

    int('75,800')·int('75800.0') 는 값이 멀쩡한데도 ValueError 를 던져(주의:
    int(75800.0) 은 되지만 int('75800.0') 은 안 된다) 그대로 500 이 된다.
    options._num 이 이미 이 경계의 정본 강제기(콤마·소수·bool·nan 방어)이므로
    재사용하고, 실패만 CompileError 로 바꿔 컴파일러 경계에서 잡히게 한다.

    Returns:
        int, 또는 미입력(None·빈칸)이면 None.

    Raises:
        CompileError: 숫자로 읽을 수 없는 값.
    """
    try:
        return _num(raw, field)
    except OptionValueInvalid as e:
        raise CompileError(str(e)) from e


def require_category(category_code, *, what: str = '카테고리 코드'):
    """카테고리 코드가 비면 CompileError. 값 형식(str/int)은 각 컴파일러가 정한다.

    (스스=leafCategoryId 문자열, 쿠팡=displayCategoryCode 정수 — 형식은 다르지만
    '없으면 막는다' 는 규칙은 공통이다.)
    """
    if not category_code:
        raise CompileError(f'{what}가 필요합니다.')
    return category_code

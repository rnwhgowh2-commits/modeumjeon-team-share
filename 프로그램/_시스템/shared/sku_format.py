"""shared/sku_format.py — SKU·바코드·품번 컬럼 규칙 (단일 진실 원천).

[2026-05-28] Phase 1-4 — 모음전·재고관리 양쪽 경로에서 동일 함수 호출.

사용자 룰 (확정):
  - SKU       : 'SKU-' + 영숫자 대문자 8자 (한글 X). 비었으면 자동.
  - 바코드     : EAN-13 (200 prefix + 9자리 + 체크섬). 비었으면 자동.
  - 품번       : 영숫자+하이픈+언더스코어만 (한글 X / SKU 형식 X). 빈 값 = '-'.

이 모듈을 import 하지 않고 자체 헬퍼를 다시 만들지 말 것.
"""
from __future__ import annotations

import re
import secrets
import string


# ============ SKU ============

SKU_RE = re.compile(r'^SKU-[A-Z0-9]{8}$')


def is_valid_sku(s: str | None) -> bool:
    """SKU-XXX 형식 검증."""
    if not s:
        return False
    return bool(SKU_RE.match(s))


def gen_sku(existing: set[str] | None = None) -> str:
    """SKU-XXX 자동 생성. existing 받으면 중복 회피."""
    pool = existing if existing is not None else set()
    while True:
        suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits)
                         for _ in range(8))
        sku = f'SKU-{suffix}'
        if sku not in pool:
            pool.add(sku)
            return sku


# ============ 바코드 (EAN-13) ============

def gen_barcode() -> str:
    """EAN-13 자동 생성. 200 prefix (내부용) + 9자리 + 체크섬."""
    digits = '200' + ''.join(secrets.choice(string.digits) for _ in range(9))
    chk = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits))
    return digits + str((10 - chk % 10) % 10)


def is_valid_barcode(s: str | None) -> bool:
    """EAN-13 형식 + 체크섬 검증."""
    if not s or len(s) != 13 or not s.isdigit():
        return False
    body, chk = s[:12], int(s[12])
    expect = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body)) % 10) % 10
    return chk == expect


# ============ 품번 ============

ARTICLE_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def is_valid_article_no(s: str | None) -> bool:
    """영숫자+하이픈+언더스코어. 한글·SKU 형식 X."""
    if not s:
        return False
    if not ARTICLE_RE.match(s):
        return False
    if s.startswith('SKU-'):
        return False
    return True


def clean_article_no(s: str | None) -> str:
    """입력값 → 유효 품번 또는 '-' (사용자 룰 fallback)."""
    if not s:
        return '-'
    s = s.strip()
    if not s or not is_valid_article_no(s):
        return '-'
    return s[:64]


# ============ 한글 검사 (보조) ============

def has_korean(s: str | None) -> bool:
    """문자열에 한글 (가-힣) 포함 여부."""
    if not s:
        return False
    return any('가' <= ch <= '힣' for ch in s)


# ════════════════════════════════════════════════════════════
#  [2026-05-29] 컬럼 규칙 강제 — 사용자 캡처 표 그대로 (10개)
#  단일 진실 원천: 모든 입력 경로 (items 추가/수정·박스히어로·일괄 등록) 가 호출.
# ════════════════════════════════════════════════════════════


def clean_brand(s: str | None) -> str:
    """브랜드 — 단일 단어, 한글 허용, 100자, 미상 fallback."""
    if not s:
        return '미상'
    s = ' '.join(s.split())  # 공백 정리
    if not s:
        return '미상'
    return s[:100]


def clean_category(s: str | None) -> str:
    """카테고리 — 단어, 한글 허용, 100자, 빈 값 허용."""
    if not s:
        return ''
    return ' '.join(s.split())[:100]


def clean_model_name(s: str | None) -> str | None:
    """제품명·모델명 — 자유 텍스트, 한글 허용, 255자, 필수.

    None 반환 = 미입력 (호출처에서 필수 체크 후 사용자에게 에러).
    빈 문자열은 None 으로 정규화.
    """
    if not s or not s.strip():
        return None
    return s.strip()[:255]


def clean_color(s: str | None) -> str:
    """색상 — 단일 색상, 한글 허용, 64자, 'ONE' fallback."""
    if not s or not s.strip():
        return 'ONE'
    return s.strip()[:64]


def clean_size(s: str | None) -> str:
    """사이즈 — 숫자 또는 FREE, 한글 허용, 64자, 'FREE' fallback."""
    if not s or not s.strip():
        return 'FREE'
    return s.strip()[:64]


def clean_avg_price(s) -> int:
    """평균매입가 — 정수(원), 0 허용. 비숫자 → 0."""
    if s is None or s == '':
        return 0
    try:
        v = int(float(str(s).replace(',', '').strip()))
        return max(0, v)
    except (ValueError, TypeError):
        return 0


def clean_memo(s: str | None) -> str:
    """메모 — 자유 텍스트, 한글 허용. 1000자 안전 제한 (사용자 명시 X, DB 보호용)."""
    if not s:
        return ''
    return s.strip()[:1000]


# ════════════════════════════════════════════════════════════
#  [2026-05-29] 표기 차이 alias — 자동 매칭용
#  사용자 시안 v3: "메이트↔Mate", "스카이블루↔Sky Blue↔SB", "240↔7US"
# ════════════════════════════════════════════════════════════


# 색상·모델명 alias (소문자 normalize 후 매칭)
COLOR_ALIASES: dict[str, set[str]] = {
    # 한글 ↔ 영어 ↔ 약어
    '블랙':       {'black', 'bk', 'blk', '검정', '흑'},
    '화이트':     {'white', 'wh', 'wt', '흰', '백'},
    '그레이':     {'gray', 'grey', 'gy', '회색', '회'},
    '네이비':     {'navy', 'nv'},
    '다크네이비': {'darknavy', 'dnv', 'dn'},
    '스카이블루': {'skyblue', 'sb'},
    '라이트블루': {'lightblue', 'lb'},
    '아이보리':   {'ivory', 'iv'},
    '크림':       {'cream', 'cr'},
    '크림핑크':   {'creampink', 'cp'},
    '베이지':     {'beige', 'bg'},
    '브라운':     {'brown', 'br'},
    '레드':       {'red', 'rd', '빨강', '빨간'},
    '오렌지':     {'orange', 'or'},
    '옐로우':     {'yellow', 'yl', '노랑', '노란'},
    '그린':       {'green', 'gr', '초록'},
    '올리브그린': {'olivegreen', 'olive', 'og'},
    '핑크':       {'pink', 'pk', '분홍'},
    '퍼플':       {'purple', 'pp', '보라'},
    'ONE':        {'one', 'default', '기본', 'all'},
}


# 사이즈 alias — KR (mm) ↔ US (남성 운동화 기준)
SIZE_ALIASES: dict[str, set[str]] = {
    '220': {'4us', '4', 'us4', '220mm'},
    '225': {'4.5us', '4.5', 'us4.5', '225mm'},
    '230': {'5us', '5', 'us5', '230mm'},
    '235': {'5.5us', '5.5', 'us5.5', '235mm'},
    '240': {'6us', '6', 'us6', '7us', '7', '240mm'},  # 한국 240 ≈ US 6 (여성 7)
    '245': {'6.5us', '6.5', '7.5us', '7.5', '245mm'},
    '250': {'7us', '7', '8us', '8', '250mm'},
    '255': {'7.5us', '7.5', '8.5us', '8.5', '255mm'},
    '260': {'8us', '8', '9us', '9', '260mm'},
    '265': {'8.5us', '8.5', '9.5us', '9.5', '265mm'},
    '270': {'9us', '9', '10us', '10', '270mm'},
    '275': {'9.5us', '9.5', '10.5us', '10.5', '275mm'},
    '280': {'10us', '10', '11us', '11', '280mm'},
    '285': {'10.5us', '10.5', '11.5us', '11.5', '285mm'},
    '290': {'11us', '11', '12us', '12', '290mm'},
    'FREE': {'free', 'onesize', 'os', 'f', '균일'},
}


def normalize_label(text: str | None) -> str:
    """색상·사이즈·모델명 normalize — alias 매칭의 키.

    소문자화 + 공백·하이픈·언더바·점 제거. 한글 유지.
    """
    if not text:
        return ''
    t = str(text).strip().lower()
    for ch in (' ', '_', '-', '.'):
        t = t.replace(ch, '')
    return t


# ────────────────────────────────────────────────────────────
# [perf 2026-05-29] 별칭 매칭 O(1)화 — 동작 보존
#   기존: color_matches/size_matches 호출마다 ALIASES 사전 전체를
#         재-normalize (호출당 ~100 normalize_label) → 모달 후보매칭
#         B×I=9만회에서 6초+. 워커 점유 → 전체 적체.
#   개선: 모듈 로드 시 1회만 "정규화형 → 소속 canonical 그룹 집합" 역인덱스
#         구축. 매칭 = dict 조회 + 집합 교집합 = O(1). 결과 100% 동일.
#   주의: SIZE_ALIASES 는 한 별칭이 여러 그룹에 속함(예 '7us' ∈ {240,250}).
#         그래서 그룹 '집합'을 저장하고 교집합으로 판정 → 기존 for-loop
#         (na·nb 가 같은 그룹에 동시 존재?) 와 의미 동일.
# ────────────────────────────────────────────────────────────


def _build_alias_index(alias_dict: dict[str, set[str]]) -> dict[str, set[str]]:
    """정규화형(normalize_label) → 소속 canonical key 집합 역인덱스."""
    index: dict[str, set[str]] = {}
    for canonical, aliases in alias_dict.items():
        forms = {normalize_label(canonical)}
        forms |= {normalize_label(x) for x in aliases}
        for f in forms:
            if not f:
                continue
            index.setdefault(f, set()).add(canonical)
    return index


_COLOR_INDEX = _build_alias_index(COLOR_ALIASES)
_SIZE_INDEX = _build_alias_index(SIZE_ALIASES)


def _alias_match(index: dict[str, set[str]], a: str | None, b: str | None) -> bool:
    na, nb = normalize_label(a), normalize_label(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ga = index.get(na)
    gb = index.get(nb)
    return bool(ga and gb and (ga & gb))


def color_matches(a: str | None, b: str | None) -> bool:
    """두 색상 표기가 같은 의미인지 (alias 사전 반영). O(1)."""
    return _alias_match(_COLOR_INDEX, a, b)


def size_matches(a: str | None, b: str | None) -> bool:
    """두 사이즈 표기가 같은 의미인지 (KR mm ↔ US 환산 반영). O(1)."""
    return _alias_match(_SIZE_INDEX, a, b)


def color_groups(s: str | None) -> set[str]:
    """색상 정규화형이 속한 canonical 그룹 집합 (사전계산 매칭용)."""
    return _COLOR_INDEX.get(normalize_label(s), set())


def size_groups(s: str | None) -> set[str]:
    """사이즈 정규화형이 속한 canonical 그룹 집합 (사전계산 매칭용)."""
    return _SIZE_INDEX.get(normalize_label(s), set())

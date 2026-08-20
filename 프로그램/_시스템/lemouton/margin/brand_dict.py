"""브랜드 정확매칭 사전 로더 + 매칭.

매칭 규칙:
- 라틴(영문·숫자·공백) 키워드: 단어경계(\\b...\\b) 정확매칭 → 'LEE' 가 'SLEEVELESS' 에 매칭 안 됨.
- 그 외(한글) 키워드: 부분문자열 매칭 (한글 브랜드명은 우연 매칭 위험 낮음).
- 키워드는 긴 것부터 검사 (부분 브랜드명 우선순위).
"""
from __future__ import annotations

import json
import os
import re

_BUNDLED_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "brand_dict.json")
_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "brand_dict.json")


def _seed_if_needed():
    """영구 저장 경로(볼륨)에 번들 기본 사전을 병합한다.
    - 볼륨 파일이 없으면 번들 기본값으로 생성.
    - 있으면 번들의 '누락된 키워드'만 추가하고, 볼륨에 이미 있는 값은 유지(볼륨 우선).
    → git 에 커밋한 기본 브랜드가 재배포 시 프로덕션 볼륨에도 자동 반영되고, 사용자가 볼륨에서 바꾼 값은 보존된다."""
    if _DEFAULT_PATH == _BUNDLED_PATH:
        return
    try:
        with open(_BUNDLED_PATH, encoding="utf-8") as f:
            bundled = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    existing = {}
    if os.path.exists(_DEFAULT_PATH):
        try:
            with open(_DEFAULT_PATH, encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            existing = {}
    merged = {**bundled, **existing}  # 볼륨(사용자) 값 우선, 번들이 누락분만 채움
    if merged != existing:
        try:
            d = os.path.dirname(_DEFAULT_PATH)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(_DEFAULT_PATH, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError:
            pass


def load_brand_dict(path: str | None = None) -> dict:
    if path is None:
        _seed_if_needed()
    path = path or _DEFAULT_PATH
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _is_latin(key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9 ]+", key))


_CACHED_MAP = None


def get_map(path: str | None = None) -> dict:
    """캐시된 브랜드 사전 반환 (없으면 로드). extract_brand 가 이걸 사용.

    주의: 반환된 dict 를 직접 수정하지 말 것(캐시 오염) — 변경은 save_brand_dict 사용.
    """
    global _CACHED_MAP
    if _CACHED_MAP is None:
        _CACHED_MAP = load_brand_dict(path)
    return _CACHED_MAP


def reload_brand_dict(path: str | None = None) -> dict:
    """디스크에서 다시 읽어 캐시 갱신."""
    global _CACHED_MAP
    _CACHED_MAP = load_brand_dict(path)
    return _CACHED_MAP


def save_brand_dict(mapping: dict, path: str | None = None) -> None:
    """사전을 JSON 으로 저장하고 캐시 갱신."""
    global _CACHED_MAP
    path = path or _DEFAULT_PATH
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
    _CACHED_MAP = dict(mapping)


def match_brand(product_name: str, brand_map: dict) -> str:
    """상품명에서 사전 브랜드를 정확매칭. 없으면 '' (미확정)."""
    if not product_name:
        return ""
    s = str(product_name)
    s_upper = s.upper()
    for key in sorted((k for k in brand_map if k), key=len, reverse=True):
        if _is_latin(key):
            if re.search(rf"\b{re.escape(key.upper())}\b", s_upper):
                return brand_map[key]
        else:
            if key in s:
                return brand_map[key]
    return ""

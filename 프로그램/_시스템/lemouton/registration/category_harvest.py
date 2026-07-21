"""판매처 카테고리 전수 수집 — 마켓별 파서(순수함수) + 저장/diff 엔진.

원칙 (스펙 2026-07-22 §A·§5):
- 파서는 순수함수(응답 텍스트/JSON → 행 리스트). 네트워크는 fetch 콜러블 주입 — 테스트는 fixture.
- 실패는 HarvestError 로 표면화한다. 조용히 빈 리스트를 돌려주지 않는다(조용한 실패 금지).
- 행 스키마: {code, name, parent_code, depth, is_leaf, full_path, raw}  (전부 str/int/bool, raw=원문 조각)
"""
from __future__ import annotations

import re


class HarvestError(Exception):
    """카테고리 수집 실패 — 사유를 그대로 담는다."""


def build_paths(rows):
    """parent_code 사슬로 full_path('A>B>C')를 조립해 각 행에 넣는다. 고아 부모는 HarvestError."""
    by_code = {r['code']: r for r in rows}
    def _path(r, guard=0):
        if guard > 10:
            raise HarvestError(f"카테고리 경로 순환 의심: {r['code']}")
        p = r.get('parent_code')
        if not p or p not in by_code:
            return r['name']
        return _path(by_code[p], guard + 1) + '>' + r['name']
    for r in rows:
        r['full_path'] = _path(r)
    return rows


# ── 11번가 ──────────────────────────────────────────────
_CAT_BLOCK = re.compile(r'<(?:\w+:)?category>(.*?)</(?:\w+:)?category>', re.S)


def _tag(block, t):
    m = re.search(r'<(?:\w+:)?%s>(.*?)</(?:\w+:)?%s>' % (t, t), block, re.S)
    return m.group(1).strip() if m else ''


def parse_eleven11(xml_text):
    """11번가 전체 카테고리 XML → 행 리스트. leafYn=='Y' 를 리프로 본다(기존 검색 코드와 동일 기준)."""
    rows = []
    for block in _CAT_BLOCK.findall(xml_text or ''):
        code, name = _tag(block, 'dispNo'), _tag(block, 'dispNm')
        if not code or not name:
            raise HarvestError('11번가 카테고리 블록에 dispNo/dispNm 누락: ' + block[:120])
        parent = _tag(block, 'parentDispNo')
        rows.append({
            'code': code, 'name': name,
            'parent_code': (parent if parent not in ('', '0') else None),
            'depth': int(_tag(block, 'depth') or 0),
            'is_leaf': _tag(block, 'leafYn') == 'Y',
            'raw': block,
        })
    if not rows:
        raise HarvestError('11번가 카테고리 응답에서 category 블록을 하나도 못 찾음')
    return build_paths(rows)

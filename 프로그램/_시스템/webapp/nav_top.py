# -*- coding: utf-8 -*-
"""상단 탭(애플식) 구조 — 사이드바 레이아웃을 그대로 옮겨 쓴다.

 단일 진실 원천 = data/sidebar_layout.json (사이드바가 이미 쓰는 그 파일).
  메뉴를 여기서 다시 적지 않는다. 여기서 새로 적으면 사장님이 사이드바를
  드래그로 바꿨을 때 상단 탭만 옛날 것으로 남아 「같은 프로그램에 메뉴가 두 벌」이 된다.

  standalone 첫 항목(홈) = 로고가 대신한다 (애플도 로고가 곧 홈).
  stages                 = 상위 탭
  stage.items            = 펼침 메뉴 안의 항목

열 나누기
  애플의 펼침 메뉴는 열마다 제목이 있다(쇼핑하기 / 빠른 링크 / 특별 할인 쇼핑하기).
  우리 저장본에는 「열」이라는 개념이 없다 — 없는 제목을 지어내면 사이드바와
  어긋나므로, 진짜로 댈 수 있는 제목만 붙인다.
    · 「자주 쓰는 것」 열 = data/nav_favorites.json 에 적힌 것 (제목 있음)
    · 그다음 열        = 스테이지 이름을 제목으로 (항목이 많으면 제목 없이 이어짐)
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

# 한 열에 담는 최대 항목 수. 애플 「스토어」 펼침의 가장 긴 열이 8개였다.
열당_최대 = 6

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FAV_PATH = os.path.join(_HERE, 'data', 'nav_favorites.json')


def _favorites() -> Dict[str, List[str]]:
    """스테이지 id → 「자주 쓰는 것」 항목 id 목록.

    sidebar_layout.json 에 얹지 않고 파일을 나눈 이유 — 사이드바 드래그 저장이
    자기가 모르는 키를 지울 수 있고, 그러면 조용히 사라진다.
    파일이 없거나 깨져도 상단 탭은 그대로 떠야 한다(즐겨찾기 열만 빠진다).
    """
    try:
        with open(_FAV_PATH, encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for sid, ids in (raw.get('stages') or {}).items():
        if isinstance(ids, list):
            out[str(sid)] = [str(i) for i in ids]
    return out


def _열나누기(items: List[dict], 제목: str) -> List[dict]:
    """항목 목록을 열로 나눈다. 첫 열만 제목을 달고 나머지는 이어지는 열."""
    cols = []
    for i in range(0, len(items), 열당_최대):
        cols.append({'title': 제목 if i == 0 else '', 'items': items[i:i + 열당_최대]})
    return cols


def build(layout: Dict[str, Any]) -> Dict[str, Any]:
    """사이드바 레이아웃 → 상단 탭 구조.

    반환:
      home    = 로고가 가리킬 곳 (없으면 None)
      tabs    = [{id, name, emoji, icon, icon_color, active_keys, item_count, columns:[{title, items}]}]
      loose   = 스테이지에 안 속한 나머지 독립 항목 (홈 제외) — 오른쪽에 둔다

    「지금 어느 탭을 보고 있는가」는 여기서 정하지 않는다 — active 는 라우트 인자가 아니라
    화면마다 render_template 으로 넘기는 값이라 이 시점에 알 수 없다. 대신 탭이 가진
    active_key 목록(active_keys)을 실어 보내고 판정은 템플릿에서 한다.
    """
    layout = layout or {}
    stand = list(layout.get('standalone') or [])
    home = stand[0] if stand else None
    loose = stand[1:]

    fav = _favorites()
    tabs: List[Dict[str, Any]] = []
    for st in layout.get('stages') or []:
        items = list(st.get('items') or [])
        by_id = {it.get('id'): it for it in items}

        cols: List[Dict[str, Any]] = []
        고른 = [by_id[i] for i in fav.get(st.get('id'), []) if i in by_id]
        if 고른:
            cols.append({'title': '자주 쓰는 것', 'fav': True, 'items': 고른})
        cols += _열나누기(items, st.get('name') or '')

        tabs.append({
            'id': st.get('id'),
            'name': st.get('name') or '',
            'emoji': st.get('emoji') or '',
            'icon': st.get('icon') or '',
            'icon_color': st.get('icon_color') or '',
            'columns': cols,
            'item_count': len(items),
            # 사이드바와 같은 active_key 를 그대로 실어 보낸다 (판정은 템플릿에서)
            # 이름을 keys 로 두면 안 된다 — 템플릿에서 t.keys 가 dict 의 메서드로 잡힌다
            'active_keys': [it.get('active_key') for it in items if it.get('active_key')],
        })

    return {'home': home, 'tabs': tabs, 'loose': loose}

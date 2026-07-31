# -*- coding: utf-8 -*-
"""디자인 모드 단일 원천.

★ current = 안전망. 이 모드에서는 tokens.css 의 어떤 규칙도 화면에 걸리지 않는다.
  화면에 ds 클래스를 붙이지 않기 때문이다. 새 디자인이 망가져도 여기로 돌리면
  예전 화면 그대로 돌아온다.

모드를 추가·삭제할 때 고칠 곳은 이 파일 하나다(템플릿·CSS 는 이 값을 따라간다).
"""
from __future__ import annotations

# 값 → (화면에 보일 이름, 설명, 어두운 화면인가)
#
# ★ 왼쪽 값(current/mono/layer/light)은 절대 바꾸지 않는다.
#   사람마다 고른 취향이 users.design_mode 에 이 값으로 저장돼 있어서,
#   값을 바꾸면 저장된 취향이 전부 「기존 타입」으로 날아간다.
#   보이는 이름만 바꾸면 된다 — 화면 세 곳(사이드바·상단탭·내 계정)이
#   전부 이 표를 읽어 그리므로 여기 하나만 고치면 다 따라온다.
MODES = {
    'current': ('기존 타입',   '지금까지 쓰던 디자인 그대로',            False),
    'mono':    ('검정A 타입',  '화면 전체가 검정 한 판',                 True),
    'layer':   ('검정B 타입',  '바탕 → 카드 → 표 머리가 한 단계씩 밝게', True),
    'light':   ('화이트 타입', '흰 바탕에 가로 카드 요약',               False),
}
DEFAULT_MODE = 'current'


def normalize(mode) -> str:
    """모르는 값이 오면 안전망(current)으로 떨어뜨린다."""
    if not isinstance(mode, str):
        return DEFAULT_MODE
    m = mode.strip()
    return m if m in MODES else DEFAULT_MODE


def body_class(mode) -> str:
    """화면 바깥 상자에 붙일 클래스. current 는 빈 문자열(= 아무것도 안 붙임)."""
    m = normalize(mode)
    if m == DEFAULT_MODE:
        return ''
    parts = ['ds']
    if MODES[m][2]:          # 어두운 화면인가
        parts.append('ds-dark')
    parts.append('ds-' + m)
    return ' '.join(parts)

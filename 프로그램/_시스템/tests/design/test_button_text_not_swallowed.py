# -*- coding: utf-8 -*-
"""색 판 위 버튼 글자가 전역 `색 물려받기` 규칙에 먹히지 않는지 고정.

【무슨 사고였나 — 2026-08-07 렌더 실측(로컬, 60화면 훑기)】
홈 화면의 파란 단추 「+ 신규 모음전」·「+ 신규 모음전 등록」의 글자가
흰색이 아니라 어두운 본문색으로 나와 대비가 각각 3.02 · **1.00** 이었다
(1.00 = 판과 글자의 밝기가 같다 = 사실상 안 보인다).

【범인】
단추 규칙은 `color:#fff` 를 제대로 적고 있었다. 그런데 전역 규칙
`tokens.css` 의 `.ds a{color:inherit}` 가 **선택자 힘이 더 세다**:
    .ds a       → (0,1,1)
    .x-btn-pri  → (0,1,0)
그래서 흰 글자가 덮이고 부모의 어두운 글자를 물려받았다.
**링크(<a>)로 만든 색 단추는 전부 같은 위험을 진다** — 클래스에 흰 글자를
적어 놨다고 안심하면 안 된다.

【고침】
전역 규칙을 손대면 전 화면에 번지므로, 단추 쪽 선택자 힘을 올렸다
(`.ds a.x-btn-pri` → (0,2,1)).

※ 이 파일은 원문 대조만 한다(CI 에 브라우저가 없다). 실제 대비 측정은
  `scripts/contrast_audit_live.py` 가 한다 — 서버를 띄우고 화면을 훑으며
  진한 의미색 판 위 글자의 대비를 전수로 잰다.
"""
from __future__ import annotations

import re
from pathlib import Path

WEBAPP = Path(__file__).resolve().parents[2] / 'webapp'


def _읽기(상대경로: str) -> str:
    return (WEBAPP / 상대경로).read_text(encoding='utf-8')


def test_전역_링크_색물려받기_규칙이_아직_있다():
    """이 검사의 전제. 사라졌다면 아래 보정이 필요 없어졌는지 다시 봐야 한다."""
    css = _읽기('static/tokens.css')
    assert re.search(r'\.ds\s+a\s*\{[^}]*color\s*:\s*inherit', css), (
        'tokens.css 의 `.ds a{color:inherit}` 가 사라졌다 — '
        '단추 글자 보정이 아직 필요한지 다시 확인할 것')


def test_홈_파란단추는_전역규칙보다_센_선택자로_흰글자를_지킨다():
    html = _읽기('templates/home.html')
    m = re.search(r'([^\n{]*\.x-btn-pri[^\n{]*)\{([^}]*color\s*:\s*#fff[^}]*)\}', html)
    assert m, '홈 파란 단추(.x-btn-pri)의 흰 글자 규칙이 사라졌다'
    선택자 = m.group(1)
    assert re.search(r'a\.x-btn-pri', 선택자), (
        '`.x-btn-pri` 만으로는 전역 `.ds a{color:inherit}` 를 못 이긴다 — '
        '글자가 어두워져 파란 판에 묻힌다(실측 대비 1.00). '
        '`.ds a.x-btn-pri` 처럼 <a> 를 포함한 선택자를 함께 적을 것')


def test_홈_파란단추_배경은_흰글자용_토큰이다():
    """`--바탕-{색}` 은 **흰 글자를 얹는 진한 배경**이다(tokens.css 주석).

    연한 판(`--연한-*`)에 흰 글자를 얹으면 반대로 글자가 날아간다.
    """
    html = _읽기('templates/home.html')
    m = re.search(r'\.x-btn-pri[^{]*\{([^}]*)\}', html)
    assert m, '홈 파란 단추 규칙이 사라졌다'
    본문 = m.group(1)
    assert '--바탕-파랑' in 본문, '흰 글자를 얹는 자리이므로 배경은 --바탕-파랑 이어야 한다'
    assert '--연한-' not in 본문, '연한 판에 흰 글자를 얹으면 글자가 날아간다'

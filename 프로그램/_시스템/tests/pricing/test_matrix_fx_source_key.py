# -*- coding: utf-8 -*-
"""매트릭스 fx(계산식) 팝업이 **문자 소싱처 키**를 잃지 않아야 한다.

사장님 화면 실측(2026-07-23): 현대H몰·롯데아이몰 fx 제목이 「source NaN」,
표면가=최종매입가(혜택 0건)로 나옴 — 셀에 보이는 금액과도 다름.

원인: 프론트가 `parseInt(td.dataset.cellSrc, 10)` 로 소싱처 id 를 정수화한다.
카탈로그 소싱처는 'key:hmall' 이라 **NaN** 이 되고, 그 NaN 이 그대로 서버로 가
어떤 템플릿·오버라이드에도 안 걸려 '혜택 없음'으로 계산됐다(조용한 오답).
숫자 소싱처만 맞아떨어져 그동안 안 드러난 것.
"""
from __future__ import annotations

import io
import os
import re

_TPL = os.path.join(os.path.dirname(__file__), "..", "..",
                    "webapp", "templates", "bundles", "_matrix_v3.html")


def _src() -> str:
    return io.open(os.path.normpath(_TPL), encoding="utf-8").read()


def test_fx_는_소싱처키를_정수화하지_않는다():
    """parseInt(...cellSrc...) 가 하나라도 남아 있으면 카탈로그 소싱처가 NaN 이 된다."""
    hits = re.findall(r"parseInt\(\s*\w*\.?dataset\.cellSrc[^)]*\)", _src())
    assert hits == [], f"cellSrc 정수화 잔존: {hits}"


def test_소싱처_비교는_문자열로_한다():
    """id 가 숫자·문자 혼재라 === 비교는 타입이 갈린다 — String() 정규화 필요."""
    s = _src()
    assert "_srcEq(" in s, "소싱처 id 비교 헬퍼(_srcEq)가 있어야 한다"
    assert "String(a) === String(b)" in s or "String(a)===String(b)" in s


def test_소싱처_이름_조회도_문자열_비교():
    """getSrcName 이 === 로만 찾으면 'key:hmall' 이 이름을 못 찾아 'source …' 로 샌다."""
    s = _src()
    m = re.search(r"function getSrcName\(id\)\s*\{(.+?)\n  \}", s, re.S)
    assert m, "getSrcName 을 찾지 못함"
    assert "_srcEq(" in m.group(1)

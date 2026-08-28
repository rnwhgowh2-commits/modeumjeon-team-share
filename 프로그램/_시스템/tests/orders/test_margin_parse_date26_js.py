# -*- coding: utf-8 -*-
"""마진계산기(margin_embed.html) 날짜 필터 — 배선 고정(Node 하네스를 pytest 전수 실행에 물린다).

⚠️ 문자열 검사로는 못 잡는다(코드는 늘 「있다」). 그래서 실체는 `tests/js/*.mjs` 로,
   템플릿의 **진짜 원문**(parseDate26)을 떼어 Node 에서 돌리고 실제 파싱 결과를 만들어 본다.
   마지막에 **뮤테이션**으로 RED 를 실증한다. 이 파일은 그것을 pytest 에 물려 주는 껍데기다
   (선례: test_order_status_js.py).
"""
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path(__file__).resolve().parents[1] / 'js'
PARSE_DATE26 = JS / 'test_margin_parse_date26.mjs'
DOWNLOAD_PAYLOAD = JS / 'test_margin_download_payload.mjs'

_NO_NODE = shutil.which('node') is None
_SKIP = pytest.mark.skipif(
    _NO_NODE,
    reason='node 가 없어 배선 고정을 돌리지 못했습니다 '
           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')


def test_배선_고정_파일이_실제로_있다():
    """node 가 없어 스킵되더라도 파일이 증발한 것은 알아야 한다."""
    assert PARSE_DATE26.exists(), PARSE_DATE26
    assert DOWNLOAD_PAYLOAD.exists(), DOWNLOAD_PAYLOAD


@_SKIP
def test_parseDate26이_모음전_API_주문일_형식을_읽는다():
    """2026-08-24 실측 버그 회귀 방지 — 'YYYY-MM-DD HH:MM:SS' 못 읽어 날짜 필터가
    전부 무시되던 것(dateFrom/dateTo 를 바꿔도 매칭 건수·일별/월별 표가 그대로였다)."""
    r = subprocess.run(['node', str(PARSE_DATE26)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, f'배선 고정 실패:\n{r.stdout}\n{r.stderr}'


@_SKIP
def test_엑셀_다운로드_payload가_UI_내부_키를_안_흘린다():
    """2026-08-24 실측 버그 회귀 방지 — 엑셀 다운로드가 화면 날짜필터·제외·편집을 무시하고
    항상 DB 저장분(전체기간)만 내려받던 것. 프론트가 payload 로 화면 데이터를 실어 보내도록
    고쳤고, 그 과정에서 UI 내부 키(_idx 등)가 열로 새지 않는지 확인한다."""
    r = subprocess.run(['node', str(DOWNLOAD_PAYLOAD)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, f'배선 고정 실패:\n{r.stdout}\n{r.stderr}'

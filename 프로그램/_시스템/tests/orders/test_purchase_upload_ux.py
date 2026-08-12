# -*- coding: utf-8 -*-
"""「매입가」 열 필터 버그 + 더망고 매입 엑셀 올리기 자리·결과 재설계(2안).

🔴 2026-08-06 사장님 라이브 신고 — 「매입가」 열 ▼ 필터를 열면 **「(빈값) 462」 하나뿐**.
   실제로는 200건에 값이 있었다.
   원인: 매입가는 화면 전용 칸(`_pp_purchase`)이라 행(preview.json)에 값이 없고,
        값은 별도 조회(`ppMap`)에만 있는데 `filterKey()` 가 `r['_pp_purchase']` 를 봤다.

🔴 같은 사건의 근본 원인 — 올리는 도구가 표 위 **접힌 한 줄**이라 사장님이 못 찾으셨다.
   확정 시안(2안): 「매입가 미입력」 탭을 고르면 큼직하게 펼쳐지고, 저장이 끝나면
   끌어놓기 자리는 접히고 요약 한 줄만 남는다.

⚠️ 문자열 검사로는 못 잡는다(코드는 늘 「있다」). 그래서 실체는 `tests/js/*.mjs` 로,
   템플릿의 **진짜 원문**을 떼어 Node 에서 돌리고 실제로 필터 목록을 만들고 파일을
   올려 본다. 둘 다 마지막에 **뮤테이션**(옛 코드로 되돌림)으로 RED 를 실증한다.
   이 파일은 그것을 pytest 전수 실행에 물려 주는 껍데기다.
"""
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path(__file__).resolve().parents[1] / 'js'
FILTER = JS / 'test_orders_purchase_filter.mjs'
UPLOAD = JS / 'test_orders_purchase_upload_ux.mjs'
# 노션 주문관리 b-3 — 실마진 열(정산예정금 − 매입가)의 「추정 딱지·매입가 없음」 규율.
MARGIN = JS / 'test_orders_margin_cell.mjs'
# 노션 주문관리 ⑥ — 「정산예정금」 27·28번 열에도 근거 딱지(여태 숫자만 찍혔다).
SETTLE_MONEY = JS / 'test_orders_settle_money_cell.mjs'

_NO_NODE = shutil.which('node') is None
_SKIP = pytest.mark.skipif(
    _NO_NODE,
    reason='node 가 없어 배선 고정을 돌리지 못했습니다 '
           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')


@pytest.mark.parametrize('p', [FILTER, UPLOAD, MARGIN, SETTLE_MONEY],
                         ids=['filter', 'upload_ux', 'margin_cell', 'settle_money'])
def test_배선_고정_파일이_실제로_있다(p):
    """node 가 없어 스킵되더라도 파일이 증발한 것은 알아야 한다."""
    assert p.exists(), p


def _run(p):
    r = subprocess.run(['node', str(p)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, f'배선 고정 실패({p.name}):\n{r.stdout}\n{r.stderr}'


@_SKIP
def test_매입가_열_필터가_ppMap_의_진짜_값을_본다():
    """「(빈값) 462」 하나로 뭉개지지 않고 값 있음(출처별)/값 없음으로 갈린다."""
    _run(FILTER)


@_SKIP
def test_올리기_자리는_미입력_탭에서_펼쳐지고_저장_뒤_접힌다():
    """2안 배치 + 저장 후 dropzone 접힘 + 요약 한 줄 + 문제 있는 것만 펼치기."""
    _run(UPLOAD)


@_SKIP
def test_실마진_칸이_재료의_출처를_숨기지_않는다():
    """매입가 없으면 0 으로 계산하지 않고 「매입가 없음」 · 정산 추정이면 「추정」 딱지."""
    _run(MARGIN)


@_SKIP
def test_정산예정금_두_칸도_근거를_말한다():
    """노션 ⑥ — 27·28번 열이 `MONEY_COLS` 로 떨어져 숫자만 찍히던 것.

    실마진 칸엔 「추정」이 붙는데 그 **재료인 정산액**은 실측처럼 검게 보였다 —
    한 화면 안에서 말이 어긋났다. 딱지 규칙은 실마진 칸과 같은 원천(SETTLE_SRC)을 쓴다.
    """
    _run(SETTLE_MONEY)

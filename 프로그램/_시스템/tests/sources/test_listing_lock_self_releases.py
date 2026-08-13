# -*- coding: utf-8 -*-
"""훑기 잠금은 **스스로 풀린다** — 영영 쥐고 있으면 수집이 통째로 멈춘다.

🔴🔴 왜 (2026-08-13 라이브)
   새 필터를 걸어도 **「한 번도 실행되지 않음」**인 채로 수십 분이 지났다.
   확장은 살아 있었고(다른 청에는 답했다) 서버도 0.3초에 목록을 줬는데,
   **훑기만** 안 돌았다. 어딘가에서 죽은 회차가 `_listingBusy` 를 쥔 채였다.

   `finally` 로 풀도록 돼 있어도 그 사이 서비스워커가 죽었다 되살아나는 등
   **빠져나가는 길이 있다.** 그러면 잠금은 영영 안 풀린다.

★ 「한 번에 하나」는 지켜야 한다(겹치면 탭이 쌓인다). 대신 **너무 오래 쥐고
  있으면 걸린 것으로 보고 놓아 준다.** 정산 회차가 같은 함정에 빠져 30분 감시를
  단 것과 같은 처방이다(0.7.72).

★★ 배운 것 — **「한 번에 하나」 잠금에는 반드시 시한이 있어야 한다.**
   시한 없는 잠금은 언젠가 그 기능을 통째로 멈춘다.
"""
from __future__ import annotations

import re
from pathlib import Path

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _src() -> str:
    return BG.read_text(encoding='utf-8')


def _poll() -> str:
    m = re.search(r'async function moumListingPollOnce\(\) \{.*?\n  _listingBusy = true;',
                  _src(), re.S)
    assert m, '훑기 폴링 함수를 못 찾았습니다.'
    return m.group(0)


def test_잠금을_언제_잡았는지_기록한다():
    src = _src()
    assert '_listingBusyAt' in src, (
        '잠금을 언제 잡았는지 안 남깁니다 — 걸렸는지 판단할 근거가 없습니다.'
    )
    assert re.search(r'_listingBusy = true;\s*\n\s*_listingBusyAt = Date\.now\(\);', src), (
        '잠금을 잡을 때 시각을 안 찍습니다.'
    )


def test_오래_쥐고_있으면_풀어_준다():
    """🔴 이 파일의 핵심 — 이게 없으면 수집이 통째로 멈춘 채 아무 말도 없다."""
    body = _poll()
    assert re.search(r'_listingBusy && \(Date\.now\(\) - _listingBusyAt\) > _LISTING_BUSY_MAX_MS',
                     body), (
        '잠금에 시한이 없습니다 — 한 번 걸리면 영영 안 풀립니다.'
    )
    assert re.search(r'_listingBusy = false;', body), '풀어 주지 않습니다.'


def test_한_번에_하나는_그대로_지킨다():
    """시한을 달았다고 겹쳐 돌게 하면 탭이 쌓여 크롬이 죽는다."""
    body = _poll()
    assert re.search(r'if \(_listingBusy\) return;', body), (
        '「한 번에 하나」 잠금이 사라졌습니다 — 겹치면 탭이 쌓입니다.'
    )


def test_시한이_넉넉하다():
    """60쪽 걷기 + 건너뛰기를 담고도 남아야 한다 — 짧으면 멀쩡한 회차를 끊는다."""
    src = _src()
    m = re.search(r'_LISTING_BUSY_MAX_MS = (\d+) \* (\d+) \* (\d+)', src)
    assert m, '시한 상수를 못 찾았습니다.'
    ms = int(m.group(1)) * int(m.group(2)) * int(m.group(3))
    assert ms >= 20 * 60 * 1000, f'시한 {ms}ms 는 짧습니다 — 멀쩡한 회차를 끊습니다.'


def test_풀_때_말을_남긴다():
    """조용히 풀면 「왜 갑자기 다시 도나」를 아무도 모른다."""
    body = _poll()
    assert 'console.warn' in body, '잠금을 풀 때 아무 말도 안 남깁니다.'

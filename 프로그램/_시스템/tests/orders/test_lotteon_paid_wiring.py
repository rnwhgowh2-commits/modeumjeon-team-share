# -*- coding: utf-8 -*-
"""롯데온 입금내역 — 창구·크롤·단추가 **끝까지 이어져 있나**.

🔴 왜 이 시험이 있나 (2026-08-13 라이브 실측)
   롯데온만 「이미 받았다」가 **0건**이고 받는 날이 1,175건 **전부 추정**이었다
   (쿠팡 1,711 · 스스 1,758 · 11번가 733 은 실값).
   원인은 셋 다 있는데 **가운데 한 칸이 비어 있었던 것**:
     ① 서버 창구  POST /api/margin/lotteon-paid        … 있음
     ② 확장 크롤  handleLotteonPaidCrawl()             … 있음
     ③ 확장 메시지 등록 `lotteon.paid.crawl`            … **없음** ← 여기
     ④ 화면 단추                                        … **없음** ← 여기
   에러도 안 나고 화면도 멀쩡했다. 그냥 **아무도 안 불렀다.**

🔴 그래서 「함수가 있나」가 아니라 **「부르는 데가 있나」**를 본다.
   함수만 검사하면 이 사고를 그대로 다시 통과시킨다.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BG = ROOT / "extension" / "moum-crawler" / "background.js"
TPL = ROOT / "webapp" / "templates" / "orders" / "index.html"
API = ROOT / "webapp" / "routes" / "api_margin.py"

MSG = "lotteon.paid.crawl"


@pytest.fixture(scope="module")
def bg():
    return BG.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tpl():
    return TPL.read_text(encoding="utf-8")


def test_확장에_크롤_함수가_있다(bg):
    assert "async function handleLotteonPaidCrawl(" in bg


def test_확장이_그_명령을_실제로_받는다(bg):
    """🔴 이게 빠져 있었다 — 함수는 있는데 부를 방법이 없었다."""
    assert f'type === "{MSG}"' in bg, (
        f"확장이 `{MSG}` 메시지를 등록하지 않았다 — 화면에서 부를 방법이 없다")
    # 등록만 해 놓고 다른 함수를 부르면 소용없다.
    i = bg.index(f'type === "{MSG}"')
    assert "handleLotteonPaidCrawl(" in bg[i:i + 400], (
        "등록은 됐는데 롯데온 지급내역 크롤을 안 부른다")


def test_화면에_그_명령을_부르는_단추가_있다(tpl):
    """🔴 이것도 빠져 있었다 — 사장님이 누를 자리가 없었다."""
    assert "spn-lo-btn" in tpl, "정산예정금액 탭에 롯데온 입금내역 단추가 없다"
    assert f"'{MSG}'" in tpl, f"단추가 `{MSG}` 를 안 부른다"


def _js_block(tpl: str) -> str:
    """단추의 **동작부**(JS)만 떼어 온다.

    🔴 HTML 자리와 JS 자리가 900줄 넘게 떨어져 있다 — 처음 나오는 자리에서 잘라 보면
      동작부를 못 보고 「없다」로 오판한다(이 시험을 쓰다 실제로 겪었다).
    """
    i = tpl.index("$('#spn-lo-btn')")
    return tpl[i:i + 4000]


def test_단추가_인증된_페이지에서_서버로_넣는다(tpl):
    """확장 SW 의 fetch 는 mou-m 인증 쿠키를 안 실어 0건이 된다(겪은 함정).

    그래서 **화면이** `/api/margin/lotteon-paid` 로 넣어야 한다.
    """
    blk = _js_block(tpl)
    assert "/api/margin/lotteon-paid" in blk
    assert "credentials:'include'" in blk.replace(" ", ""), (
        "인증 쿠키를 안 실으면 저장이 조용히 0건이 된다")


def test_서버_창구가_살아_있다():
    src = API.read_text(encoding="utf-8")
    assert '"/lotteon-paid"' in src and "def lotteon_paid_ingest" in src


def test_버린_행수를_화면이_말한다(tpl):
    """조용히 삼키면 크롤이 멈춘 걸 아무도 모른다 — 서버가 주는 skipped 를 그대로 적는다."""
    blk = _js_block(tpl)
    assert "skipped" in blk


def test_옛_확장이면_무엇을_하면_되는지_말한다(tpl):
    """「모르는 명령」은 확장이 옛 판이라는 뜻 — 로그인 문제로 오해하면 엉뚱한 데를 고친다."""
    blk = _js_block(tpl)
    assert "unknown type" in blk and "새로 고친" in blk

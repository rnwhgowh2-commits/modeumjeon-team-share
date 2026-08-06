# -*- coding: utf-8 -*-
"""판매상태 판정은 **정본(lemouton/catalog/status.unify_status)** 하나로.

🔴 [2026-08-06 실측] 쿠팡 후보 조회가 300개를 훑고 0건이었다. 카탈로그에는 같은 계정에
   판매중지 4,621건이 있다. 원인 — 내가 「중지/중단/정지」 라는 낱말로 손수 걸렀는데,
   쿠팡의 실제 statusName 은 **부분승인완료 · 승인반려 · 상품삭제** 다.

   같은 표가 이미 `lemouton/catalog/status.py` 에 있었다(라이브 실측 근거까지 달려서).
   손으로 만든 판정은 마켓이 낱말을 바꾸면 조용히 0건이 된다 — 정본을 쓴다.

   ★ 더 위험한 쪽: `on_sale()` 이 같은 낱말표를 썼다. 판매중지 상품을 「판매중」으로
     오판하면 시험이 거부되고(안전), 반대로 판매중 상품을 「판매중지」로 오판하면
     **진짜 팔리는 상품을 건드린다**(위험). 정본은 모르는 값을 'unknown' 으로 남긴다.
"""
from __future__ import annotations

import pytest

from lemouton.uploader.roundtrip.sale_status import is_on_sale, is_stopped


# ── 쿠팡 — 실측 statusName 은 한글 ───────────────────────────────────────────
@pytest.mark.parametrize("raw", ["부분승인완료", "승인반려", "상품삭제"])
def test_쿠팡_판매중지_상태를_알아본다(raw):
    assert is_stopped("coupang", raw) is True
    assert is_on_sale("coupang", raw) is False


def test_쿠팡_승인완료는_판매중이다():
    assert is_on_sale("coupang", "승인완료") is True
    assert is_stopped("coupang", "승인완료") is False


@pytest.mark.parametrize("raw", ["임시저장", "심사중", "승인대기중"])
def test_쿠팡_대기상태는_판매중도_판매중지도_아니다(raw):
    """대기 상품은 건드리면 심사 흐름이 꼬인다 — 시험 대상에서 빼야 한다."""
    assert is_stopped("coupang", raw) is False
    assert is_on_sale("coupang", raw) is False


# ── 다른 마켓도 같은 정본으로 ────────────────────────────────────────────────
def test_스마트스토어():
    assert is_stopped("smartstore", "SUSPENSION") is True
    assert is_on_sale("smartstore", "SALE") is True
    assert is_stopped("smartstore", "OUTOFSTOCK") is False   # 품절은 판매중지 아님


def test_롯데온():
    assert is_stopped("lotteon", "STP") is True
    assert is_on_sale("lotteon", "SALE") is True


def test_옥션_G마켓():
    assert is_stopped("auction", "21") is True
    assert is_on_sale("gmarket", "11") is True


# ── 모르는 값 — 안전 쪽으로 ──────────────────────────────────────────────────
def test_모르는_상태는_판매중지로_보지_않는다():
    """모르는 값을 판매중지로 보면 **진짜 팔리는 상품**을 건드린다."""
    assert is_stopped("coupang", "새로운상태") is False
    assert is_stopped("smartstore", None) is False


def test_모르는_상태는_판매중으로도_단정하지_않는다():
    assert is_on_sale("coupang", "새로운상태") is False


def test_모르는_마켓도_터지지_않는다():
    assert is_stopped("없는마켓", "뭐든") is False
    assert is_on_sale("없는마켓", "뭐든") is False

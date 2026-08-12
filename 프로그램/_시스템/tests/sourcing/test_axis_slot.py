# -*- coding: utf-8 -*-
"""축 이름 → 색상/사이즈 칸 배정 (2026-08-12 · 노션 「모델모음전」).

왜 이 시험이 있나
  사장님이 모델모음전 축 순서를 **모델·색상·사이즈**로 확정하셨다.
  예전 규칙(「몇 번째 축인가」)대로면 `color_code` 에 **모델명**이 들어간다.
  그 칸은 마켓 전송·재고·마진이 다 읽으므로, 틀려도 아무도 안 알려 준다.
  → 여기서 못 박는다. 이 시험이 깨지면 돈이 틀어진 것이다.

  동시에 **기존 데이터의 동작이 안 바뀌는 것**도 같이 못 박는다.
  이름을 못 알아보는 옛 매트릭스(단계1·단계2 등)는 오늘 그대로 위치로 정해야 한다.
"""
import pytest

from lemouton.sourcing.axis_slot import (
    is_model_axis, legacy_pair, semantic_slots, storage_slots,
)


# ── 저장(storage) — 옛 칸을 어디에 채우나 ─────────────────────────────────

def test_색상_사이즈는_오늘_그대로다():
    assert storage_slots(['색상', '사이즈']) == ['color', 'size']


def test_모델을_1축에_둬도_색상칸에_모델명이_안_들어간다():
    """🔴 이 시험이 이 파일의 존재 이유다."""
    assert storage_slots(['모델', '색상', '사이즈']) == [None, 'color', 'size']
    color, size = legacy_pair(['모델', '색상', '사이즈'], ['메이트', '블랙', '265'])
    assert color == '블랙', '색상 칸에 모델명이 들어갔다 — 마켓 전송이 틀어진다'
    assert size == '265'


def test_모델_색상_2축이면_색상이_색상칸을_가져간다():
    color, size = legacy_pair(['모델', '색상'], ['메이트', '블랙'])
    assert color == '블랙'
    assert size == '메이트'          # 남은 자리 — 비워 두면 격자가 한 칸으로 뭉개진다


def test_모델만_있는_1축은_칸이_비지_않는다():
    """자리를 비우면 모든 옵션의 (색,사이즈)가 같아져 격자가 무너진다."""
    color, size = legacy_pair(['모델'], ['메이트'])
    assert color == '메이트'
    assert size == ''


def test_이름을_못_알아보면_오늘_그대로_위치로():
    assert storage_slots(['단계1', '단계2']) == ['color', 'size']
    assert legacy_pair(['단계1', '단계2'], ['블랙', '265']) == ('블랙', '265')


def test_축이름을_아예_안_주면_오늘_그대로():
    """이름 바꾸기 경로가 이름을 못 받아도 두 칸이 비면 안 된다."""
    assert legacy_pair(None, ['블랙', '265']) == ('블랙', '265')
    assert legacy_pair([], ['블랙']) == ('블랙', '')


@pytest.mark.parametrize('name', ['색상', '색', '컬러', 'color', ' 색상 ', 'COLOR'])
def test_색상_별칭들(name):
    assert storage_slots([name, '사이즈']) == ['color', 'size']


# ── 대조(semantic) — 소싱처의 어느 값과 짝인가 ─────────────────────────────

def test_모델_축은_소싱처에_짝이_없다():
    assert semantic_slots(['모델', '색상', '사이즈']) == [None, 'color', 'size']
    assert is_model_axis('모델명') is True
    assert is_model_axis('색상') is False


def test_대조도_옛_데이터는_오늘_그대로():
    assert semantic_slots(['단계1', '단계2']) == ['color', 'size']
    assert semantic_slots(['색상', '사이즈']) == ['color', 'size']


def test_한_자리에_두_축이_들어가지_않는다():
    """겹치면 가격·재고가 두 배로 잡힌다 — 어느 규칙에서도 금지."""
    for names in (['색상', '컬러'], ['재질', '색상'], ['모델', '색상', '사이즈'],
                  ['색상', '사이즈', '재질']):
        for slots in (storage_slots(names), semantic_slots(names)):
            got = [x for x in slots if x]
            assert len(got) == len(set(got)), f'{names} → {slots} 에서 자리가 겹쳤다'


# ── 읽기 경로도 같은 규칙을 쓴다 (2026-08-12 · 전수 감사에서 잡힌 구멍) ──────
#   저장·축맞추기 화면만 이름 기준으로 고치고 **매트릭스 읽기 경로를 빠뜨렸다.**
#   그 값은 `match_source_option` 으로 흘러가 어느 소싱처 가격·재고를 붙일지 정한다 —
#   틀리면 남의 색 가격이 붙는다. 규칙이 한 곳뿐인지 여기서 지킨다.

def _names(monkeypatch, names):
    from lemouton.sourcing import axis_match_audit as A

    class _R:
        def __init__(self, n):
            self.axis_name = n
    return A._axis_names(None, 'ANY', rows=[_R(n) for n in names])


def test_읽기경로도_모델을_색상으로_안_읽는다(monkeypatch):
    """🔴 모델·색상·사이즈로 짜면 색은 「색상」 사전에서 찾아야 한다."""
    assert _names(monkeypatch, ['모델', '색상', '사이즈']) == ('색상', '사이즈')


def test_읽기경로_색상사이즈는_오늘_그대로(monkeypatch):
    assert _names(monkeypatch, ['색상', '사이즈']) == ('색상', '사이즈')


def test_읽기경로_옛이름은_오늘_그대로(monkeypatch):
    """이름을 못 알아보는 옛 매트릭스는 동작이 바뀌면 안 된다."""
    assert _names(monkeypatch, ['단계1', '단계2']) == ('단계1', '단계2')


def test_읽기경로_한축이면_사이즈는_기본값(monkeypatch):
    assert _names(monkeypatch, ['색상']) == ('색상', '사이즈')
    assert _names(monkeypatch, []) == ('색상', '사이즈')

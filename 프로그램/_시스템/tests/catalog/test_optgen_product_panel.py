# -*- coding: utf-8 -*-
"""「모음전 상품 생성」 탭 왼쪽 판(「어디까지 왔나」) — 0인 줄을 늘어놓지 않는다.

이 파일이 지키는 것 (2026-08-14 검수 지적 3)

  🔴 **개수가 0인 위상 줄은 판에 안 그린다.**
     예전 이 자리의 「상품 만듦」 줄이 지키던 관례를 되살린 것이다. 없는 상태를
     0으로 늘어놓으면 판이 「고를 수 있는 것」이 아니라 용어 사전이 된다 —
     눌러도 0줄이다. 특히 「상품 생성에 사용됨 0」은 사장님 확정(그 옵션함은
     **옵션 생성 목록**에서 뺀다)과 겹쳐 읽혀 「여기선 쓴다는 건가」로 헷갈린다.
     라벨 자체는 남긴다 — 상품 생성 탭은 다른 목록이라 그 줄이 실제로 생긴다.

시험을 쓰면서 지킨 것
  · 🔴 **판에 실릴 줄을 손으로 심는다.** 라이브 자료에 기대면 위상 셋이 다 0이 아닐
    때가 많아, 「0이면 안 그린다」를 **한 번도 안 보고** 초록불이 된다.
    그래서 목록을 만드는 함수를 바꿔치기해 「ready 만 1, 나머지 0」을 만든다.
  · 「없어야 한다」와 「있어야 한다」를 **항상 같이** 본다. 없는 것만 보면 판이
    통째로 안 그려져도 초록불이다.
"""
import re

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _판(html: str) -> dict:
    """왼쪽 판에 실제로 그려진 줄 — {보이는 글자: 숫자}."""
    return {글: int(수) for 글, 수 in re.findall(
        r'<div class="stg-row[^"]*" data-s="[^"]*">\s*'
        r'<span class="lb">([^<]+)</span><span class="n">(\d+)</span>', html)}


def test_개수가_0인_위상_줄은_판에_안_그린다(client, monkeypatch):
    """🔴 「상품 생성에 사용됨 0」 같은 줄이 늘 떠 있으면, 눌러도 0줄인 칸이 된다.

    판에 실릴 줄을 **한 개(준비 완료)만** 두고 나머지 위상을 0으로 만든 뒤,
    0인 줄이 화면에서 사라지는지 본다.
    """
    from lemouton.matrix.readiness import (PHASE_DRAFT, PHASE_LABEL, PHASE_READY,
                                           PHASE_USED)
    import webapp.routes.optgen as og

    한줄 = [{'id': 1, 'no': 'U-TEST-1', 'name': '판시험함', 'kind': 'origin',
            'box': True, 'brand': '르무통', 'options': 2, 'code': 'U-TEST-1',
            'phase': PHASE_READY, 'missing': []}]
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: 한줄)

    판 = _판(client.get('/optgen/?tab=product').get_data(as_text=True))

    # 헛돔 방지 — 판이 통째로 안 그려졌으면 「없다」는 검사는 전부 통과한다.
    assert 판.get(PHASE_LABEL[PHASE_READY]) == 1, (
        f'심은 줄이 판에 안 잡혔다 — 시험이 헛돈다: {판}')
    for p in (PHASE_DRAFT, PHASE_USED):
        assert PHASE_LABEL[p] not in 판, (
            f'개수가 0인데 「{PHASE_LABEL[p]}」 줄을 그린다 — 눌러도 0줄인 칸이다')


def test_개수가_있으면_그_위상_줄은_판에_뜬다(client, monkeypatch):
    """반대쪽 자물쇠 — 「0이면 숨긴다」를 「아예 안 그린다」로 잘못 고치면 여기서 걸린다.

    상품 생성 탭은 옵션 생성 목록과 **다른 목록**이라, 상품에 쓴 옵션함도 여기엔
    그대로 뜬다. 라벨을 없애 버리면 그 줄이 판 어디에도 안 잡혀 합이 갈린다.
    """
    from lemouton.matrix.readiness import PHASE_LABEL, PHASE_READY, PHASE_USED
    import webapp.routes.optgen as og

    두줄 = [{'id': 1, 'no': 'U-TEST-1', 'name': '준비된함', 'kind': 'origin',
            'box': True, 'brand': '르무통', 'options': 2, 'code': 'U-TEST-1',
            'phase': PHASE_READY, 'missing': []},
           {'id': 2, 'no': 'U-TEST-2', 'name': '다쓴함', 'kind': 'origin',
            'box': True, 'brand': '르무통', 'options': 2, 'code': 'U-TEST-2',
            'phase': PHASE_USED, 'missing': []}]
    monkeypatch.setattr(og, '_matrices', lambda s, *a, **k: 두줄)

    판 = _판(client.get('/optgen/?tab=product').get_data(as_text=True))
    assert 판.get(PHASE_LABEL[PHASE_READY]) == 1, f'준비 완료 줄이 안 뜬다: {판}'
    assert 판.get(PHASE_LABEL[PHASE_USED]) == 1, (
        f'상품 생성 탭에서는 「{PHASE_LABEL[PHASE_USED]}」 줄이 떠야 한다: {판}')

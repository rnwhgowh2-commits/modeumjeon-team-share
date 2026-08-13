# -*- coding: utf-8 -*-
"""상품명 「정책 / 비정책」 — 죽어 있던 칸을 살린다 (인수인계 C1).

■ 무엇이 죽어 있었나 (실측)
    `Model.naver_product_name_override` · `coupang_product_name_override`
      읽는 곳 3 (registration/coupang.py:106 · registration/smartstore.py:85 · formatter)
      **쓰는 곳 0** — 적을 화면이 없어 **늘 비어 있었다.**
    즉 「마켓마다 다른 상품명」은 코드로는 되는데 **아무도 못 쓰는** 기능이었다.

■ 사장님 확정 (2026-08-13)
    쿠폰과 **같은 모양**(A2 미끄럼 스위치)으로. 「비정책」일 때만 이 상품에서 고친다.
    「상품명, 추가이미지, 상세페이지 등도 정책에서 벗어나서 특정 가공만 변경 가능」

■ 🔴 이 시험이 지키는 것
  1. 비웠을 때 **정책 이름으로 되돌아간다** — 빈 글자를 마켓에 보내면 상품명이 사라진다.
  2. 마켓마다 **따로** 간다 — 쿠팡만 바꿨는데 스스까지 바뀌면 안 된다.
  3. 마켓 한도(쿠팡 100자 등)를 **넘으면 보내기 전에** 사람 말로 막는다.
"""
import pytest

from tests.catalog.test_bundles_tower import client, world   # noqa: F401


def _get(client, code):
    return client.get(f'/bundles/api/tower/{code}/markets').get_json()


def test_처음엔_정책_이름을_따른다(client, world):
    j = _get(client, world['code'])
    cp = next(m for m in j['markets'] if m['market'] == 'coupang')
    assert cp['name_own'] is False
    assert cp['name_override'] in (None, '')


def test_비정책으로_이_상품만_이름을_준다(client, world):
    from lemouton.sourcing.models import Model
    from shared.db import SessionLocal
    r = client.post(f"/api/bundles/{world['code']}/name-override",
                    json={'market': 'coupang', 'value': '르무통 메이트 [단독]'})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    s = SessionLocal()
    try:
        m = s.get(Model, world['code'])
        assert m.coupang_product_name_override == '르무통 메이트 [단독]'
        assert m.naver_product_name_override in (None, ''), \
            '쿠팡만 바꿨는데 스마트스토어까지 바뀌었다'
    finally:
        s.close()
    cp = next(x for x in _get(client, world['code'])['markets']
              if x['market'] == 'coupang')
    assert cp['name_own'] is True
    assert cp['name_override'] == '르무통 메이트 [단독]'


def test_비우면_정책_이름으로_되돌아간다(client, world):
    """🔴 빈 글자를 그대로 보내면 마켓에서 상품명이 사라진다 — None 으로 지운다."""
    from lemouton.sourcing.models import Model
    from shared.db import SessionLocal
    client.post(f"/api/bundles/{world['code']}/name-override",
                json={'market': 'coupang', 'value': '아무 이름'})
    r = client.post(f"/api/bundles/{world['code']}/name-override",
                    json={'market': 'coupang', 'value': ''})
    assert r.get_json()['ok'] is True
    s = SessionLocal()
    try:
        assert s.get(Model, world['code']).coupang_product_name_override is None, \
            '빈 글자가 그대로 남았다 — 마켓에 빈 상품명이 나간다'
    finally:
        s.close()


def test_마켓_한도를_넘으면_보내기_전에_막는다(client, world):
    """마켓이 「유효하지 않습니다」만 뱉기 전에 우리가 사람 말로 말한다."""
    from lemouton.registration.market_limits import name_max_len
    cap = name_max_len('coupang')
    if not cap:
        pytest.skip('쿠팡 상품명 한도가 아직 확정 안 됨')
    r = client.post(f"/api/bundles/{world['code']}/name-override",
                    json={'market': 'coupang', 'value': '가' * (cap + 1)})
    assert r.status_code == 400
    assert str(cap) in r.get_json()['message']


def test_모르는_마켓은_안_받는다(client, world):
    """🔴 상품명 덮어쓰기 칸이 있는 마켓은 쿠팡·스마트스토어 둘뿐이다."""
    r = client.post(f"/api/bundles/{world['code']}/name-override",
                    json={'market': 'lotteon', 'value': '이름'})
    assert r.status_code == 400
    assert '쿠팡' in r.get_json()['message'] or '스마트스토어' in r.get_json()['message']


def test_스마트스토어도_따로_간다(client, world):
    from lemouton.sourcing.models import Model
    from shared.db import SessionLocal
    client.post(f"/api/bundles/{world['code']}/name-override",
                json={'market': 'smartstore', 'value': '스스용 이름'})
    s = SessionLocal()
    try:
        m = s.get(Model, world['code'])
        assert m.naver_product_name_override == '스스용 이름'
    finally:
        s.close()
    ss = next(x for x in _get(client, world['code'])['markets']
              if x['market'] == 'smartstore')
    assert ss['name_own'] is True

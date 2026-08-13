# -*- coding: utf-8 -*-
"""「팔 때」 탭의 쿠폰 칸 — 상태(C4) + 「정책/비정책」 스위치(A2).

■ 사장님 확정
    C4 : 「할인·쿠폰」 칸은 **값이 같으면 한 줄, 다를 때만 두 줄**.
         윗줄 = 쿠팡에 지금 **실제로 걸린** 값 / 아랫줄 = 우리가 **걸려는** 값·상태
    A2 : 「정책 / 비정책」 **미끄럼 스위치**. 비정책일 때만 이 상품에서 고친다.

■ 🔴 이 시험이 지키는 것
  1. **「대기 중」과 「걸림」이 절대 같아 보이면 안 된다.** 넣기만 하고 안 걸린 것을
     걸린 줄 알면 사장님이 할인이 나가는 줄 알고 판다.
  2. **실제 값과 걸려는 값이 다르면 화면이 그 차이를 말한다.** 같으면 굳이 두 줄 안 만든다.
  3. 쿠폰 칸은 **쿠팡 줄에만** — 다른 마켓엔 쿠폰이라는 게 없다.
  4. ⏰ **다음날 0시부터**를 화면이 말한다(쿠팡은 오늘 못 켠다).
"""
import io
import re

import pytest

# 상품 1개 + 옵션 4개 + 마켓 등록이 있는 세계 — 옆 파일이 이미 만들어 둔 것을 그대로 쓴다.
from tests.catalog.test_bundles_tower import client, world   # noqa: F401

TPL = 'webapp/templates/bundles/tower.html'


@pytest.fixture(scope='module')
def src():
    return io.open(TPL, encoding='utf-8').read()


@pytest.fixture(scope='module')
def t4(src):
    m = re.search(r'function renderT4\(j\)\{(.*?)\n\}', src, re.S)
    assert m, 'renderT4 를 못 찾았습니다'
    return m.group(1)


# ── ① 서버가 쿠폰 상태를 준다 ────────────────────────────────

def test_markets_API가_쿠폰_상태를_준다(client, world):
    """화면이 「대기 중 / 걸림 / 실패」를 가르려면 서버가 그 상태를 줘야 한다."""
    r = client.get(f"/bundles/api/tower/{world['code']}/markets")
    assert r.status_code == 200
    j = r.get_json()
    cp = next(m for m in j['markets'] if m['market'] == 'coupang')
    assert 'coupon_state' in cp, '쿠폰 상태를 안 줍니다'
    assert cp['coupon_state'] in ('none', 'queued', 'applied', 'failed')
    assert 'coupon_want' in cp, '걸려는 값을 안 줍니다'
    assert 'coupon_own' in cp, '「정책/비정책」을 안 줍니다'


def test_쿠팡이_아닌_마켓엔_쿠폰_칸이_없다(client, world):
    """🔴 쿠폰은 쿠팡만이다 — 다른 마켓에 주면 화면이 없는 기능을 광고한다."""
    j = client.get(f"/bundles/api/tower/{world['code']}/markets").get_json()
    for m in j['markets']:
        if m['market'] == 'coupang':
            continue
        assert 'coupon_state' not in m, f"{m['market']} 에 쿠폰 상태가 붙었습니다"


# ── ② C4 — 같으면 한 줄, 다를 때만 두 줄 ────────────────────

def test_C4_두_줄은_값이_다를_때만(t4):
    """🔴 늘 두 줄로 만들면 표가 쓸데없이 복잡해지고, 늘 한 줄이면 어긋남을 못 본다."""
    assert 'couponCell' in t4, '쿠폰 칸을 만드는 자리가 없습니다'
    m = re.search(r'function couponCell\(m\)\{(.*?)\n\}', open(TPL, encoding='utf-8').read(), re.S)
    assert m, 'couponCell() 이 없습니다'
    body = m.group(1)
    assert 'same' in body or '===' in body, \
        '실제 값과 걸려는 값이 같은지 안 봅니다 — 늘 두 줄이 됩니다'


def test_상태마다_다른_말을_쓴다():
    """「대기 중」과 「걸림」이 같은 글자면 안 걸린 걸 걸린 줄 안다."""
    s = io.open(TPL, encoding='utf-8').read()
    m = re.search(r'function couponCell\(m\)\{(.*?)\n\}', s, re.S)
    body = m.group(1)
    for word in ('대기 중', '걸림', '실패'):
        assert word in body, f'상태 「{word}」 를 화면이 말하지 않습니다'


def test_다음날_0시부터를_말한다():
    """⏰ 쿠팡 쿠폰은 오늘 못 켠다 — 화면이 그 사실을 말해야 한다."""
    s = io.open(TPL, encoding='utf-8').read()
    assert '0시' in s, '「다음날 0시부터」를 화면이 안 말합니다'


# ── ③ A2 — 정책/비정책 미끄럼 스위치 ────────────────────────

def test_A2_스위치가_있다(src):
    assert 'cpn-sw' in src, '「정책/비정책」 스위치가 없습니다'
    assert '비정책' in src and '정책' in src


def test_비정책일_때만_고칠_수_있다(src):
    """🔴 정책일 때 입력칸이 열려 있으면, 고쳐도 안 먹거나 조용히 정책을 벗어난다."""
    m = re.search(r'function couponPanel\(m\)\{(.*?)\n\}', src, re.S)
    assert m, 'couponPanel() 이 없습니다'
    body = m.group(1)
    assert 'disabled' in body, '정책일 때 입력칸을 안 잠급니다'


def test_스위치와_단추가_서버에_보낸다(src):
    """화면만 바뀌고 서버에 안 가면 새로 고치는 순간 되돌아간다."""
    assert '/coupang-coupon/override' in src, '스위치가 서버에 안 보냅니다'
    assert '/coupang-coupon' in src, '「쿠폰 걸기」가 서버에 안 보냅니다'


# ── ④ 서버 — 스위치를 실제로 저장한다 ───────────────────────

@pytest.fixture
def cp_channel(world):
    """그 상품에 쿠팡 구성·채널을 하나 만들어 둔다.

    🔴 이게 없으면 「아직 쿠팡에 연동된 구성이 없습니다」에서 먼저 막힌다 —
      그건 맞는 동작이라, 값 규칙을 재려면 채널이 있어야 한다.
    """
    from shared.db import SessionLocal
    from lemouton.sets.models import ProductSet, SetChannel
    s = SessionLocal()
    try:
        ps = ProductSet(model_code=world['code'], name='기본구성')
        s.add(ps)
        s.flush()
        ch = SetChannel(set_id=ps.id, market='coupang', account_key='세소쿠팡',
                        market_product_id='157', status='linked', api_fields={})
        s.add(ch)
        s.commit()
        return ch.id
    finally:
        s.close()


def test_override_창구가_저장한다(client, world, cp_channel):
    from lemouton.policy import coupon_service as CS
    from lemouton.sets.models import SetChannel
    from shared.db import SessionLocal
    r = client.post(f"/api/bundles/{world['code']}/coupang-coupon/override",
                    json={'mode': 'own', 'value': 250})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert r.get_json()['ok'] is True
    s = SessionLocal()
    try:
        ch = s.get(SetChannel, cp_channel)
        assert CS.override_of(ch) == {'mode': 'own', 'value': 250}
    finally:
        s.close()


def test_정책으로_되돌리면_값도_지운다(client, world, cp_channel):
    """🔴 값이 남아 있으면 다음에 「비정책」으로 켤 때 옛 값이 되살아난다."""
    from lemouton.policy import coupon_service as CS
    from lemouton.sets.models import SetChannel
    from shared.db import SessionLocal
    client.post(f"/api/bundles/{world['code']}/coupang-coupon/override",
                json={'mode': 'own', 'value': 250})
    r = client.post(f"/api/bundles/{world['code']}/coupang-coupon/override",
                    json={'mode': 'policy', 'value': 250})
    assert r.get_json()['ok'] is True
    s = SessionLocal()
    try:
        assert CS.override_of(s.get(SetChannel, cp_channel)) == \
            {'mode': 'policy', 'value': None}
    finally:
        s.close()


def test_10원_단위가_아니면_사람_말로_막는다(client, world, cp_channel):
    r = client.post(f"/api/bundles/{world['code']}/coupang-coupon/override",
                    json={'mode': 'own', 'value': 255})
    assert r.status_code == 400
    assert '10원' in r.get_json()['message']


def test_비정책이면_화면이_그렇게_말한다(client, world, cp_channel):
    """스위치를 돌린 뒤 표가 「이 상품만」이라고 말해야 한다."""
    client.post(f"/api/bundles/{world['code']}/coupang-coupon/override",
                json={'mode': 'own', 'value': 250})
    j = client.get(f"/bundles/api/tower/{world['code']}/markets").get_json()
    cp = next(m for m in j['markets'] if m['market'] == 'coupang')
    assert cp['coupon_own'] is True
    assert cp['coupon_want'] == 250, '이 상품만의 값이 화면에 안 옵니다'

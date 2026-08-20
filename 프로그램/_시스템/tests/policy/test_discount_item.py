# -*- coding: utf-8 -*-
"""정책 판매가 안 「즉시할인」 — 확정 D1(안전장치 안)·E2(노란 띠)·B1(옆 미리보기).

사장님 확정(2026-08-06): 「B1 으로 했으면 좋겠고, 이걸 판매가 부분에 합치면 될듯해.
굳이 구분할필요 없어보여.」

지도 전수정독으로 확인된 사실만 배선한다 —
  스스 = 상품 수정에 즉시할인 필드가 있고 우리 전송 코드도 이미 있다
  쿠팡 = 쿠폰을 만들어 옵션에 붙인다 · ⏰ 다음날 0시부터
  나머지 4마켓 = 자리 못 찾음 → 안 보낸다(날조 금지)
"""
import pytest

from lemouton.policy.discount import (SUPPORTED, discount_of, exposed_price)


# ── 항목표(단일 진실 원천)에 들어갔나 ────────────────────────────────────
def test_판매가_항목_안에_있다():
    """별도 항목을 만들지 않는다 — 사장님 확정."""
    from lemouton.registration.process_rule_schema import all_schemas
    price = next(s for s in all_schemas() if s['key'] == 'price')
    keys = [f['key'] for f in price['fields']]
    assert 'discount_unit' in keys and 'discount_value' in keys
    # 정상가와 나란히 있어야 한다(둘은 다른 것 — 대체 관계 아님)
    assert 'normal_price' in keys


def test_별도_항목은_안_만든다():
    from lemouton.policy.fields import EXTRA_ITEMS
    keys = [it.get('key') for it in EXTRA_ITEMS]
    # ⚠️ '_site_discount'(G마켓·롯데온 지원할인)는 **다른 항목**이다 — 겹쳐 보지 않는다
    assert '_discount' not in keys and '_immediate_discount' not in keys


# ── 값 → 보낼 모양 ──────────────────────────────────────────────────────
def test_정액_정률_모양이_나온다():
    assert discount_of({'price': {'discount_value': 1400}}) == {
        'value': 1400, 'unitType': 'WON'}
    assert discount_of({'price': {'discount_value': 10,
                                  'discount_unit': 'PERCENT'}}) == {
        'value': 10, 'unitType': 'PERCENT'}


@pytest.mark.parametrize('rules', [
    {}, {'price': {}}, {'price': {'discount_value': 0}},
    {'price': {'discount_value': None}}, {'price': {'discount_value': '없음'}},
    {'price': {'discount_value': 5, 'discount_unit': 'YEN'}},   # 모르는 방식
    {'price': {'discount_value': 100, 'discount_unit': 'PERCENT'}},  # 100%=공짜
])
def test_없거나_이상하면_안_보낸다(rules):
    """0 을 보내면 「0원 할인」이라는 뜻이 된다. 모르는 방식은 추측 금지."""
    assert discount_of(rules) is None


def test_고객가_계산은_한_곳에서만():
    assert exposed_price(128900, {'value': 1400, 'unitType': 'WON'}) == 127500
    assert exposed_price(10000, {'value': 10, 'unitType': 'PERCENT'}) == 9000
    assert exposed_price(1000, {'value': 5000, 'unitType': 'WON'}) == 0  # 바닥 0
    assert exposed_price(1000, None) == 1000
    assert exposed_price(None, {'value': 100, 'unitType': 'WON'}) is None


def test_보낼_수_있는_마켓만():
    assert set(SUPPORTED) == {'smartstore', 'coupang'}


# ── 쿠팡 쿠폰 — 지도 스펙 그대로 ────────────────────────────────────────
class FakeCoupang:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []
        self._cfg = {'vendor_id': 'A9TEST'}

    def request(self, method, path, body=None, query=''):
        self.calls.append((method, path, body))
        return {'code': 200, 'data': {'success': self.ok, 'content': {
            'requestedId': '123543582159745830895', 'success': self.ok}}}


def test_쿠팡_쿠폰_만들기_요청_모양():
    from shared.platforms.coupang import promotions as P
    c = FakeCoupang()
    rid = P.create_coupon(c, 'A9TEST', contract_id=316716, name='모음전 즉시할인',
                          unit='WON', value=1400, end_at='2026-12-31 23:59:59')
    assert rid == '123543582159745830895'
    method, path, body = c.calls[0]
    assert method == 'POST' and path.endswith('/vendors/A9TEST/coupon')
    assert body['type'] == 'PRICE' and body['discount'] == 1400
    assert body['contractId'] == 316716
    # ⏰ 오늘이 아니라 내일 0시로 나가야 한다(쿠팡이 오늘을 안 받는다)
    assert body['startAt'].endswith(' 00:00:00')


def test_쿠팡_정률은_RATE_로():
    from shared.platforms.coupang import promotions as P
    c = FakeCoupang()
    P.create_coupon(c, 'A9TEST', contract_id=1, name='n', unit='PERCENT',
                    value=10, end_at='2026-12-31 23:59:59')
    assert c.calls[0][2]['type'] == 'RATE'


def test_쿠팡_모르는_방식이면_안_만든다():
    from shared.platforms.coupang import promotions as P
    c = FakeCoupang()
    with pytest.raises(P.CoupangCouponError):
        P.create_coupon(c, 'A9TEST', contract_id=1, name='n', unit='YEN',
                        value=10, end_at='2026-12-31 23:59:59')
    assert c.calls == [], '거부했는데 마켓을 불렀다'


def test_쿠팡_계약ID_없으면_안_만든다():
    from shared.platforms.coupang import promotions as P
    with pytest.raises(P.CoupangCouponError):
        P.create_coupon(FakeCoupang(), 'A9TEST', contract_id=None, name='n',
                        unit='WON', value=100, end_at='2026-12-31 23:59:59')


def test_쿠팡_옵션_1만개_넘으면_나눠_부른다():
    from shared.platforms.coupang import promotions as P
    c = FakeCoupang()
    rids = P.add_items(c, 'A9TEST', 68, list(range(1, 25_001)))
    assert len(c.calls) == 3 and len(rids) == 3
    assert len(c.calls[0][2]['vendorItems']) == P.MAX_ITEMS_PER_CALL


def test_쿠팡_접수실패는_숨기지_않는다():
    from shared.platforms.coupang import promotions as P
    with pytest.raises(P.CoupangCouponError):
        P.create_coupon(FakeCoupang(ok=False), 'A9TEST', contract_id=1, name='n',
                        unit='WON', value=100, end_at='2026-12-31 23:59:59')


def test_쿠팡_vendor_id_는_설정주머니에서():
    """속성으로 읽으면 전 계정이 「없음」이 된다(2026-08-05 실사고)."""
    from shared.platforms.coupang import promotions as P
    assert P.vendor_id_of(FakeCoupang()) == 'A9TEST'
    assert P.vendor_id_of(object()) is None


def test_쿠팡_처리결과는_실패건수까지_본다():
    from shared.platforms.coupang import promotions as P

    class C(FakeCoupang):
        def request(self, method, path, body=None, query=''):
            return {'data': {'content': {'couponId': 778, 'status': 'DONE',
                                         'total': 3, 'succeeded': 2, 'failed': 1,
                                         'failedVendorItems': [999]}}}
    r = P.check_request(C(), 'A9TEST', 1)
    assert r['done'] is True and r['failed'] == 1 and r['failed_items'] == [999]


# ── 화면 ────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _detail(client, market):
    from shared.db import SessionLocal
    from lemouton.policy.models import MarketPolicy
    s = SessionLocal()
    try:
        p = MarketPolicy(name='즉시할인 검사 정책')
        s.add(p); s.commit()
        pid = p.id
    finally:
        s.close()
    html = client.get(f'/policies/{pid}?m={market}').get_data(as_text=True)
    return html, pid


def test_화면_판매가_안전장치_안에_있다(client):
    """확정 D1 — 「가격 안전장치」 묶음 안, 끝자리·정상가 다음."""
    html, _ = _detail(client, 'smartstore')
    assert 'pf-disc' in html
    i_guard = html.index('pf-guard')
    i_size = html.index('data-k="size_unify"')
    i_disc = html.index('data-k="discount_value"')
    assert i_guard < i_size < i_disc, '안전장치 묶음 안, 사이즈 통일 다음이어야 한다'


def test_화면_쿠팡탭에만_내일_안내(client):
    """확정 E2 — 쿠팡만 노란 띠. 다른 마켓엔 없는 제약을 붙이면 거짓말이다."""
    cp, _ = _detail(client, 'coupang')
    ss, _ = _detail(client, 'smartstore')
    assert '다음날 0시부터' in cp
    assert '다음날 0시부터' not in ss


def test_화면_미리보기가_배선돼_있다(client):
    """확정 B1 — 입력칸 옆에서 바로. 칸만 있고 배선이 없으면 영영 빈칸이다."""
    html, _ = _detail(client, 'smartstore')
    assert 'pf-disc-prev' in html and 'discPaint' in html
    # 🔴 값을 화면에서 새로 계산하지 않는다 — 서버 계산 결과를 그대로 쓴다
    assert 'discBase' in html


def test_화면_정상가와_구분해_적혀_있다(client):
    html, _ = _detail(client, 'smartstore')
    assert '할인 전 표시가' in html          # 정상가 설명(원래 있던 것)
    assert '고객에게 보이는 값만 깎습니다' in html   # 즉시할인 설명(새것)


def test_화면_못보여주는_이유를_그대로_적는다(client):
    """🔴 라이브 실측(2026-08-06)에서 잡음 —

    마진율이 비어 계산이 막혔는데도 「위 계산해 보기를 먼저 누르면」이 남아 있었다.
    사장님은 이미 눌렀는데 안 눌렀다고 말하는 화면 = 사실과 다른 안내.
    """
    html, _ = _detail(client, 'smartstore')
    assert 'discWhyNot' in html, '못 보여주는 이유를 담을 자리가 없다'
    # 계산이 막히는 두 갈래(!j.ok · 옵션 0개) 모두에서 이유를 넘겨야 한다
    assert html.count('discWhyNot =') >= 3
    assert '미리 보여드릴 수 없습니다 — ' in html


# ── 마켓이 알려준 금액 규칙 (라이브 실측 2026-08-06) ─────────────────────
def test_스스는_10원_단위만_받는다():
    """🔴 실측 — 12,345원을 보내니 마켓이 거부했다:
    「기본할인 항목은 10원 단위로 입력해 주세요」.
    안 걸러 주면 사장님은 「유효하지 않습니다」만 보고 이유를 모른다."""
    from lemouton.policy.discount import problem_for
    bad = problem_for('smartstore', {'value': 12345, 'unitType': 'WON'})
    assert bad and '10원 단위' in bad and '12,340' in bad
    assert problem_for('smartstore', {'value': 12340, 'unitType': 'WON'}) is None


def test_쿠팡은_10원_단위_100원_이상():
    from lemouton.policy.discount import problem_for
    assert '10원 단위' in problem_for('coupang', {'value': 105, 'unitType': 'WON'})
    assert '100원 이상' in problem_for('coupang', {'value': 50, 'unitType': 'WON'})
    assert problem_for('coupang', {'value': 1400, 'unitType': 'WON'}) is None


def test_정률은_단위규칙을_지어내지_않는다():
    """실측 근거가 없는 규칙은 만들지 않는다."""
    from lemouton.policy.discount import problem_for
    assert problem_for('smartstore', {'value': 13, 'unitType': 'PERCENT'}) is None


def test_못_보내는_마켓은_그렇게_말한다():
    from lemouton.policy.discount import problem_for, UNSUPPORTED_NOTE
    assert problem_for('lotteon', {'value': 1000, 'unitType': 'WON'}) == UNSUPPORTED_NOTE
    assert problem_for('smartstore', None) is None


def test_화면_못보내는_마켓은_안_나간다고_말한다(client):
    """🔴 검증(2026-08-06)에서 발견 — 롯데온·11번가·옥션·G마켓 탭도
    「고객에게 보이는 값만 깎습니다」라고 말하고 있었다. 안 나가는데 깎이는 줄 안다.
    화면이 사실과 달라선 안 된다."""
    # ⚠️ 클래스 **이름**으로 세면 <style> 안 정의까지 세어 늘 「있음」이 된다
    #   (2026-08-06 브라우저 확인에서도 같은 함정을 밟았다) → 렌더된 요소로 본다.
    RENDERED = 'class="pf-disc-off"'
    for mk in ('lotteon', 'eleven11', 'auction', 'gmarket'):
        html, _ = _detail(client, mk)
        assert RENDERED in html, f'{mk}: 안 나간다는 안내가 없다'
        assert '마켓으로 나가지 않습니다' in html
        assert '고객에게 보이는 값만 깎습니다' not in html, f'{mk}: 깎인다고 말하고 있다'
    for mk in ('smartstore', 'coupang'):
        html, _ = _detail(client, mk)
        assert RENDERED not in html, f'{mk}: 나가는 마켓인데 못 나간다고 한다'
        assert '고객에게 보이는 값만 깎습니다' in html

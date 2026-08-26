# -*- coding: utf-8 -*-
"""즉시할인을 옥션·G마켓에도 건다 (Phase 8).

■ 지도 전수정독 실측 (2026-08-26 · consult-market-map 게이트)
  옥션·G마켓의 즉시할인은 **별도 API 가 아니라 등록 payload 안**에 있다::

      addtionalInfo.sellerDiscount = {
        isUse: bool,
        iac|gmkt: {type: 0사용안함|1정액|2정률, priceOrRate1, startDate, endDate}
      }

  제약(문서 원문): 정액 **최소 100원·10원 단위** · 정률 **판매가 대비 70%까지**
  롯데ON 「판매자할인 저장」(apiNo=122)은 지도에 **[off]·상세 미접수** → **확인 불가**.

🔴 이 파일이 막는 사고 — 전부 **금전 직결**이다
  ① 옥션(iac)/G마켓(gmkt) 키를 **바꿔 넣어 다른 사이트에 할인이 걸리는** 것.
  ② 마켓이 못 받을 값(70% 초과·100원 미만)을 조용히 깎거나 반올림해 보내는 것.
  ③ 안 정했는데 기본값을 지어 넣어 **사장님이 정한 적 없는 할인**이 걸리는 것.
  ④ 자리를 못 찾은 마켓에 비슷해 보이는 칸으로 끼워 넣는 것.
"""
import pytest

from lemouton.policy import discount as DC
from lemouton.registration import process_apply as PA


class _Draft:
    def __init__(self, **kw):
        self.name = kw.pop('name', '르무통 원피스')
        self.brand = kw.pop('brand', '르무통')
        self.source_site = ''
        self.source_category_path = ''
        self.options_json = '[]'
        self.notice_json = '{}'
        for k, v in kw.items():
            setattr(self, k, v)


def _적용(market, unit='PERCENT', value=10):
    return PA.apply_rules(
        _Draft(), {'price': {'discount_unit': unit, 'discount_value': value}},
        market=market)


def _사유(skipped):
    got = [s for s in skipped if s.get('code') == 'DISCOUNT_NOT_SENT']
    return got[0].get('reason') if got else None


# ── 옥션/G마켓 키를 안 바꿔 넣는가 ────────────────────────────────────────

def test_옥션은_iac_로_나간다():
    """🔴 gmkt 로 넣으면 **G마켓에 할인이 걸린다** — 엉뚱한 사이트가 손해를 본다.

    ★ [2026-08-26 라이브 실데이터로 확정] 문서만 믿지 않고 실제 상품으로 확인했다.
      `/api/live-send-test/product-list` 로 라이브 상품 10건을 읽으니
      **옥션 상품 5건은 `iac` 에만**, **G마켓 상품 5건은 `gmkt` 에만** 값이 있었다
      (`sellStatus`·`siteGoodsNo` 둘 다 같은 모양). 반대쪽은 전부 null.
      즉 옥션=iac · G마켓=gmkt 가 라이브 데이터로 증명됐다.
    """
    got = DC.esm_seller_discount('auction', {'value': 10, 'unitType': 'PERCENT'})
    assert set(got) == {'isUse', 'iac'}
    assert got['isUse'] is True
    assert got['iac']['type'] == 2, '정률 = 2 (지도 원문)'
    assert got['iac']['priceOrRate1'] == 10


def test_G마켓은_gmkt_로_나간다():
    got = DC.esm_seller_discount('gmarket', {'value': 5000, 'unitType': 'WON'})
    assert set(got) == {'isUse', 'gmkt'}
    assert got['gmkt']['type'] == 1, '정액 = 1 (지도 원문)'
    assert got['gmkt']['priceOrRate1'] == 5000


def test_기간을_안_주면_날짜_칸을_안_넣는다():
    """🔴 오늘 날짜를 지어 넣으면 사장님이 정한 적 없는 기간이 걸린다."""
    got = DC.esm_seller_discount('auction', {'value': 10, 'unitType': 'PERCENT'})
    assert 'startDate' not in got['iac']
    assert 'endDate' not in got['iac']


def test_기간을_주면_그대로_싣는다():
    got = DC.esm_seller_discount('gmarket', {'value': 10, 'unitType': 'PERCENT'},
                                 start='2026-09-01', end='2026-09-30')
    assert got['gmkt']['startDate'] == '2026-09-01'
    assert got['gmkt']['endDate'] == '2026-09-30'


def test_할인이_없으면_조각도_없다():
    assert DC.esm_seller_discount('auction', None) is None


def test_ESM_아닌_마켓엔_안_만든다():
    for mk in ('smartstore', 'coupang', 'eleven11', 'lotteon'):
        assert DC.esm_seller_discount(mk, {'value': 10, 'unitType': 'PERCENT'}) is None


# ── 마켓이 못 받을 값을 조용히 안 보낸다 ─────────────────────────────────

def test_정률_70퍼센트_초과는_막는다():
    """🔴 지도 원문: 「정률 설정시 : 판매가대비 70%까지 허용」."""
    사유 = DC.problem_for('auction', {'value': 80, 'unitType': 'PERCENT'})
    assert 사유 and '70%' in 사유
    assert DC.esm_seller_discount('auction',
                                  {'value': 80, 'unitType': 'PERCENT'}) is None


def test_정률_70퍼센트_까지는_통과한다():
    assert DC.problem_for('gmarket', {'value': 70, 'unitType': 'PERCENT'}) is None


def test_정액_100원_미만은_막는다():
    """🔴 지도 원문: 「정액 설정시 : 최소 100원 이상」."""
    사유 = DC.problem_for('auction', {'value': 50, 'unitType': 'WON'})
    assert 사유 and '100원' in 사유


def test_정액_10원_단위가_아니면_막는다():
    사유 = DC.problem_for('gmarket', {'value': 555, 'unitType': 'WON'})
    assert 사유 and '10원 단위' in 사유


def test_안내에_조사가_맞다():
    """「옥션는」처럼 읽히면 사장님이 바로 어색해한다."""
    assert '옥션은' in DC.problem_for('auction', {'value': 50, 'unitType': 'WON'})
    assert 'G마켓은' in DC.problem_for('gmarket', {'value': 50, 'unitType': 'WON'})
    assert '스마트스토어는' in DC.problem_for('smartstore',
                                        {'value': 15, 'unitType': 'WON'})


# ── 가공 사본에 실리나 ────────────────────────────────────────────────────

def test_옥션_가공_사본에_실린다():
    view, applied, _ = _적용('auction')
    assert getattr(view, 'seller_discount')['iac']['priceOrRate1'] == 10
    assert any('옥션' in (a.get('note') or '') for a in applied)


def test_자리를_못_찾은_마켓은_사유를_남긴다():
    """🔴 조용히 안 보내면 사장님은 「걸었는데 왜 안 되지」가 된다."""
    for mk in ('eleven11', 'lotteon'):
        view, _, skipped = _적용(mk)
        assert getattr(view, 'seller_discount', None) is None
        assert '못 찾았습니다' in (_사유(skipped) or '')


def test_못_받을_값이면_사유를_남기고_안_싣는다():
    view, _, skipped = _적용('auction', unit='PERCENT', value=80)
    assert getattr(view, 'seller_discount', None) is None
    assert '70%' in (_사유(skipped) or '')


def test_할인을_안_정하면_아무_일도_안_한다():
    """🔴 기본값을 지어 넣으면 사장님이 정한 적 없는 할인이 걸린다."""
    view, applied, skipped = PA.apply_rules(
        _Draft(), {'price': {}}, market='auction')
    assert getattr(view, 'seller_discount', None) is None
    assert _사유(skipped) is None


# ── 실제 payload 까지 이어지나 ────────────────────────────────────────────

def _payload(**kw):
    from shared.platforms.esm.products import build_esm_register_payload
    공통 = dict(market='auction', goods_name='X', cat_code='1', site_cat_code='2',
              site_type=1, price=10000, stock=1, place_no=1, dispatch_policy_no=1,
              return_addr_no='1', delivery_company_no=1, official_notice_no=1,
              official_notice_details=[], image_url='http://x/a.jpg',
              detail_html='<p>x</p>')
    공통.update(kw)
    return build_esm_register_payload(**공통)


def test_payload_에_sellerDiscount_가_들어간다():
    p = _payload(seller_discount={'isUse': True, 'iac': {'type': 2, 'priceOrRate1': 10}})
    assert p['addtionalInfo']['sellerDiscount']['iac']['priceOrRate1'] == 10


def test_안_정하면_payload_에_칸이_없다():
    """🔴 지금까지 안 보내던 칸이다 — 갑자기 보내면 그게 변경이다."""
    assert 'sellerDiscount' not in _payload()['addtionalInfo']


def test_사이트부담_할인은_안_건드린다():
    """siteDiscount(마켓이 부담)는 별개다 — 판매자할인과 섞으면 안 된다."""
    p = _payload(seller_discount={'isUse': True, 'iac': {'type': 1, 'priceOrRate1': 500}})
    assert p['addtionalInfo']['siteDiscount'] == {'gmkt': False, 'iac': False}


def test_조립기와_전송이_실제로_넘긴다():
    """🔴 이 다리가 없으면 판정을 아무리 잘해도 마켓엔 안 나간다."""
    import pathlib
    뿌리 = pathlib.Path(__file__).resolve().parents[2]
    조립 = (뿌리 / 'lemouton' / 'registration' / 'compile_more.py').read_text(
        encoding='utf-8')
    전송 = (뿌리 / 'lemouton' / 'registration' / 'send_more.py').read_text(
        encoding='utf-8')
    assert "spec['seller_discount'] = _sd" in 조립
    assert "seller_discount=spec.get('seller_discount')" in 전송


def test_롯데온은_확인_불가라_안_보낸다():
    """지도에 [off]·상세 미접수 — 지어내지 않는다."""
    assert 'lotteon' not in DC.SUPPORTED


# ── 화면이 정본과 같은 말을 하나 ──────────────────────────────────────────

import os  # noqa: E402

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)

    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass

    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


def _화면(client, market):
    pid = client.post('/api/policies', json={'name': 'P'}).get_json()['id']
    r = client.get(f'/policies/{pid}?m={market}')
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_옥션_화면이_안_나간다고_말하지_않는다(client):
    """🔴 예전엔 목록이 화면에 박혀 있어 「스마트스토어·쿠팡뿐」이라 했다.

    이제 옥션에도 나가는데 화면이 「안 나간다」고 하면, 사장님은 걸어 두고도
    안 걸린 줄 안다.
    """
    html = _화면(client, 'auction')
    assert '보낼 자리를 아직 못 찾았습니다' not in html


def test_11번가_화면은_안_나간다고_말한다(client):
    """자리를 못 찾은 마켓은 그대로 말해야 한다 — 조용히 넘기면 안 된다."""
    html = _화면(client, 'eleven11')
    assert '보낼 자리를 아직 못 찾았습니다' in html


def test_나가는_마켓_목록을_손으로_안_박았다():
    """🔴 화면에 목록을 박아 두면 정본이 늘어도 옛말을 한다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'webapp' / 'templates' / 'policy' / 'detail.html').read_text(
        encoding='utf-8')
    assert "market in ('smartstore', 'coupang')" not in 소스
    assert 'discount_sends' in 소스


def test_드라이런_라우트가_새_칸을_넘긴다():
    """🔴 실전송 테스트 화면은 `arm` 없이 부르면 **등록 없이 payload 만** 돌려준다.

    고객에게 아무것도 안 보이는 상태로 「무엇이 나가는지」를 실서버에서 확인하는
    유일한 길이다. 새 칸을 안 넘기면 즉시할인·가격비교가 실리는지 볼 수 없다.
    """
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'webapp' / 'routes' / 'live_send_test.py').read_text(encoding='utf-8')
    assert 'seller_discount=p.get("seller_discount")' in 소스
    assert 'pcs_use=p.get("pcs_use")' in 소스

# -*- coding: utf-8 -*-
"""마켓 전송 목록 — 한 줄 = 구성(벌) · 소싱처는 여럿.

사장님 확정 ① — 마켓에 올라가는 실제 단위가 구성이다.
🔴 더망고와 다른 점: 우리는 **구성 하나가 소싱처 여럿**을 문다.
"""
import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault('DISABLE_AUTH', '1')

from shared.db import Base                       # noqa: E402
# ★ 표를 만들기 **전에** 모델을 등록해야 한다 — listing 은 안에서 늦게 부르기 때문에
#   여기서 안 불러 두면 create_all 이 send_jobs·send_job_rows 를 안 만든다.
from lemouton.send import models as _send_models  # noqa: E402,F401
from lemouton.send import listing as L           # noqa: E402


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


def _model(s, code, name, crawled=None, box=False, brand='르무통'):
    from lemouton.sourcing.models import Model
    m = Model(model_code=code, model_name_raw=name, model_name_display=name,
              brand=brand, display_no='U-' + code, is_option_box=box,
              last_crawled_at=crawled)
    s.add(m)
    s.flush()
    return m


def _set(s, code, name):
    from lemouton.sets.models import ProductSet
    ps = ProductSet(model_code=code, name=name)
    s.add(ps)
    s.flush()
    return ps


def _src(s, code, key, url):
    from lemouton.sourcing.models import BundleSourceUrl
    s.add(BundleSourceUrl(model_code=code, source_key=key, url=url))
    s.flush()


def _policy(s, name):
    from lemouton.policy.service import create_policy
    p = create_policy(s, name=name)
    s.flush()
    return p


def _change(s, set_id, market, field, at):
    """소싱처·마켓 어느 한쪽에서 가격·재고가 바뀐 이력 한 줄."""
    from lemouton.sets.models import ChannelChangeEvent
    s.add(ChannelChangeEvent(set_id=set_id, market=market, canonical_sku='SKU',
                             field=field, source='source', at=at))
    s.flush()


def _channel_opt(s, set_id, market, sku, mkt_stock):
    """판매처 채널에 옵션 하나를 붙이고 그 마켓이 알려준 재고를 심는다."""
    from lemouton.sets.models import SetChannel, SetChannelOption
    ch = SetChannel(set_id=set_id, market=market, account_key='default')
    s.add(ch)
    s.flush()
    s.add(SetChannelOption(channel_id=ch.id, canonical_sku=sku, status='matched',
                           mkt_stock=mkt_stock))
    s.flush()
    return ch


# ── 한 줄 = 구성 ────────────────────────────────────────────────────────

def test_같은_상품이라도_구성마다_한_줄이다(s):
    """「단품」과 「2벌 묶음」은 마켓에 따로 올라간다 — 따로 보여야 한다."""
    _model(s, 'M1', '탑텐 탱크')
    _set(s, 'M1', '단품')
    _set(s, 'M1', '2벌 묶음')
    got = L.rows(s)
    assert got['total'] == 2
    assert sorted(r['set_name'] for r in got['rows']) == ['2벌 묶음', '단품']
    assert {r['name'] for r in got['rows']} == {'탑텐 탱크'}


def test_옵션함은_목록에_안_나온다(s):
    """아직 안 파는 묶음이라 보낼 대상이 아니다."""
    _model(s, 'BOX', '옵션함', box=True)
    _set(s, 'BOX', '단품')
    assert L.rows(s)['total'] == 0


# ── 소싱처가 여럿 ───────────────────────────────────────────────────────

def test_구성_한_줄에_소싱처가_여럿_실린다(s):
    _model(s, 'M1', '나이키 반팔')
    _set(s, 'M1', '단품')
    _src(s, 'M1', 'musinsa', 'https://a')
    _src(s, 'M1', 'ssf', 'https://b')
    _src(s, 'M1', 'ssg', 'https://c')
    r = L.rows(s)['rows'][0]
    assert r['sources'] == ['musinsa', 'ssf', 'ssg']


def test_같은_소싱처에_URL이_여럿이어도_한_번만_센다(s):
    _model(s, 'M1', '나이키 반팔')
    _set(s, 'M1', '단품')
    _src(s, 'M1', 'musinsa', 'https://a')
    _src(s, 'M1', 'musinsa', 'https://b')
    assert L.rows(s)['rows'][0]['sources'] == ['musinsa']


def test_지금_사오는_곳은_지어내지_않는다(s):
    """🔴 최저가 픽이 아직 미배선이다 — 아무 곳이나 「사오는 곳」이라 하면 거짓이다."""
    _model(s, 'M1', '나이키 반팔')
    _set(s, 'M1', '단품')
    _src(s, 'M1', 'musinsa', 'https://a')
    assert L.rows(s)['rows'][0]['buy_source'] is None


def test_소싱처로_거르면_그것을_문_구성만_나온다(s):
    _model(s, 'M1', 'A')
    _set(s, 'M1', '단품')
    _src(s, 'M1', 'musinsa', 'https://a')
    _model(s, 'M2', 'B')
    _set(s, 'M2', '단품')
    _src(s, 'M2', 'ssg', 'https://b')
    got = L.rows(s, sources=['musinsa'])
    assert [r['name'] for r in got['rows']] == ['A']


# ── 정책 ────────────────────────────────────────────────────────────────

def test_정책_안_붙은_것만_고를_수_있다(s):
    from lemouton.policy.models import SetPolicyLink
    _model(s, 'M1', '붙음')
    a = _set(s, 'M1', '단품')
    _model(s, 'M2', '안붙음')
    _set(s, 'M2', '단품')
    p = _policy(s, '정책A')
    s.add(SetPolicyLink(set_id=a.id, policy_id=p.id))
    s.flush()
    got = L.rows(s, policy='none')
    assert [r['name'] for r in got['rows']] == ['안붙음']
    assert got['rows'][0]['policy'] is None
    got2 = L.rows(s, policy='has')
    assert [r['name'] for r in got2['rows']] == ['붙음']
    assert got2['rows'][0]['policy'] == '정책A'


def test_구성_정책이_상품_정책을_이긴다(s):
    from lemouton.policy.models import BundlePolicyLink, SetPolicyLink
    _model(s, 'M1', 'A')
    ps = _set(s, 'M1', '단품')
    상품, 구성 = _policy(s, '상품쪽'), _policy(s, '구성쪽')
    s.add(BundlePolicyLink(model_code='M1', policy_id=상품.id))
    s.add(SetPolicyLink(set_id=ps.id, policy_id=구성.id))
    s.flush()
    r = L.rows(s)['rows'][0]
    assert r['policy'] == '구성쪽' and r['policy_from'] == 'set'


def test_지운_정책은_없는_것으로_본다(s):
    from lemouton.policy.models import SetPolicyLink
    _model(s, 'M1', 'A')
    ps = _set(s, 'M1', '단품')
    p = _policy(s, '지운정책')
    p.deleted_at = datetime(2026, 8, 1)
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    assert L.rows(s)['rows'][0]['policy'] is None


# ── 마켓 등록 · 전송 ────────────────────────────────────────────────────

def test_마켓_미등록만_고를_수_있다(s):
    """행마다 실린 「등록됨」 마켓별 상품번호 — 2026-08-19 unlisted_only/registered_only 로 이관."""
    from lemouton.sets.models import SetChannel
    _model(s, 'M1', '등록됨')
    a = _set(s, 'M1', '단품')
    _model(s, 'M2', '미등록')
    _set(s, 'M2', '단품')
    s.add(SetChannel(set_id=a.id, market='coupang', account_key='default',
                     market_product_id='CP123'))
    s.flush()
    assert [r['name'] for r in L.rows(s, unlisted_only=True)['rows']] == ['미등록']
    got = L.rows(s, registered_only=True)['rows'][0]
    assert got['listed'] == {'coupang': 'CP123'}


def test_미판매중만_고를_수_있다(s):
    """빨리 올리려고 계획 중인 것만 — 사장님 3번 확정 (a)."""
    from lemouton.sets.models import SetChannel
    _model(s, 'M1', '미등록')
    _set(s, 'M1', '단품')
    _model(s, 'M2', '등록됨')
    b = _set(s, 'M2', '단품')
    s.add(SetChannel(set_id=b.id, market='coupang', account_key='default',
                     market_product_id='CP1'))
    s.flush()
    assert [r['name'] for r in L.rows(s, unlisted_only=True)['rows']] == ['미등록']


def test_등록된것만_고를_수_있다(s):
    """계속 주시·관리하려고 — 판매처 1개라도 등록된 것."""
    from lemouton.sets.models import SetChannel
    _model(s, 'M1', '미등록')
    _set(s, 'M1', '단품')
    _model(s, 'M2', '등록됨')
    b = _set(s, 'M2', '단품')
    s.add(SetChannel(set_id=b.id, market='coupang', account_key='default',
                     market_product_id='CP1'))
    s.flush()
    assert [r['name'] for r in L.rows(s, registered_only=True)['rows']] == ['등록됨']


def test_계정으로_거르면_그_계정에_등록된_구성만_나온다(s):
    """판매처 「전체 > 계정」 — 4-D 확정. 마켓이 아니라 계정 단위로 좁힌다."""
    from lemouton.sets.models import SetChannel
    _model(s, 'M1', '본계정것')
    a = _set(s, 'M1', '단품')
    s.add(SetChannel(set_id=a.id, market='smartstore', account_key='ss_main',
                     market_product_id='SS1'))
    _model(s, 'M2', '서브계정것')
    b = _set(s, 'M2', '단품')
    s.add(SetChannel(set_id=b.id, market='smartstore', account_key='ss_sub1',
                     market_product_id='SS2'))
    s.flush()
    got = L.rows(s, accounts=['ss_main'])
    assert [r['name'] for r in got['rows']] == ['본계정것']


def test_미판매중_등록됨_둘다_안_고르면_전체가_나온다(s):
    from lemouton.sets.models import SetChannel
    _model(s, 'M1', '미등록')
    _set(s, 'M1', '단품')
    _model(s, 'M2', '등록됨')
    b = _set(s, 'M2', '단품')
    s.add(SetChannel(set_id=b.id, market='coupang', account_key='default',
                     market_product_id='CP1'))
    s.flush()
    assert L.rows(s)['total'] == 2


def test_보낸_적_있으면_마켓별_시각이_실린다(s):
    from lemouton.send import service as SS
    from lemouton.send.models import KIND_OK
    _model(s, 'M1', 'A')
    ps = _set(s, 'M1', '단품')
    job = SS.start_job(s)
    SS.record(s, job=job, market='coupang', kind=KIND_OK, set_id=ps.id)
    s.flush()
    assert 'coupang' in L.rows(s)['rows'][0]['sent']


# ── 검색 · 날짜 ─────────────────────────────────────────────────────────

def test_상품명으로_찾는다(s):
    _model(s, 'M1', '탑텐 탱크')
    _set(s, 'M1', '단품')
    _model(s, 'M2', '나이키 반팔')
    _set(s, 'M2', '단품')
    assert [r['name'] for r in L.rows(s, keyword='탑텐')['rows']] == ['탑텐 탱크']


def test_브랜드로_찾는다(s):
    _model(s, 'M1', '탱크', brand='탑텐')
    _set(s, 'M1', '단품')
    _model(s, 'M2', '반팔', brand='나이키')
    _set(s, 'M2', '단품')
    got = L.rows(s, search_in='brand', keyword='탑텐')
    assert [r['name'] for r in got['rows']] == ['탱크']


def test_구성_이름으로도_찾힌다(s):
    """「2벌 묶음」으로 찾을 수 있어야 한다 — 구성이 한 줄이니까."""
    _model(s, 'M1', '탑텐 탱크')
    _set(s, 'M1', '단품')
    _set(s, 'M1', '2벌 묶음')
    got = L.rows(s, keyword='2벌')
    assert [r['set_name'] for r in got['rows']] == ['2벌 묶음']


def test_계정_목록은_마켓별로_묶여_활성_계정만_나온다(s):
    from lemouton.sourcing.models_v2 import UploadAccount
    s.add(UploadAccount(account_key='ss_main', display_name='스마트스토어 본계정',
                        market='smartstore', env_prefix='SMARTSTORE_MAIN'))
    s.add(UploadAccount(account_key='ss_sub1', display_name='스마트스토어 서브1',
                        market='smartstore', env_prefix='SMARTSTORE_2'))
    s.add(UploadAccount(account_key='ss_off', display_name='꺼둔계정',
                        market='smartstore', env_prefix='SMARTSTORE_3', is_active=False))
    s.add(UploadAccount(account_key='cp_main', display_name='쿠팡 본계정',
                        market='coupang', env_prefix='COUPANG_MAIN'))
    s.flush()
    got = L.account_options(s)
    assert [k for k, _ in got['smartstore']] == ['ss_main', 'ss_sub1']
    assert got['coupang'] == [('cp_main', '쿠팡 본계정')]


def test_상품_자동완성_두_글자_미만이면_안_찾는다(s):
    _model(s, 'M1', '탑텐 탱크', brand='탑텐')
    _set(s, 'M1', '단품')
    got = L.suggest_products(s, '탑')
    assert got['rows'] == [] and got['reason']


def test_상품_자동완성_브랜드와_상품명을_구분해_보여준다(s):
    _model(s, 'M1', '탑텐 탱크', brand='탑텐')
    _set(s, 'M1', '단품')
    got = L.suggest_products(s, '탑텐')
    kinds = {r['kind'] for r in got['rows']}
    assert 'brand' in kinds and 'name' in kinds


def test_상품_자동완성_옵션함은_안_나온다(s):
    _model(s, 'M1', '탑텐 옵션함', brand='탑텐', box=True)
    got = L.suggest_products(s, '탑텐')
    assert got['rows'] == []


def test_정책_자동완성_이름으로_찾는다(s):
    _policy(s, '탑텐 20%할인')
    _policy(s, '나이키 정가')
    got = L.suggest_policies(s, '탑텐')
    assert [r['name'] for r in got['rows']] == ['탑텐 20%할인']


def test_정책_자동완성_지운_정책은_안_나온다(s):
    p = _policy(s, '탑텐 지운정책')
    p.deleted_at = datetime(2026, 8, 1)
    s.flush()
    assert L.suggest_policies(s, '탑텐')['rows'] == []


def test_수집날로_거른다(s):
    _model(s, 'M1', '어제것', crawled=datetime(2026, 8, 1, 10))
    _set(s, 'M1', '단품')
    _model(s, 'M2', '오늘것', crawled=datetime(2026, 8, 2, 10))
    _set(s, 'M2', '단품')
    got = L.rows(s, date_basis='crawl', date_from='2026-08-02', date_to='2026-08-02')
    assert [r['name'] for r in got['rows']] == ['오늘것']


def test_날짜_기준을_안_고르면_안_거른다(s):
    """사장님 확정 ④ — 날짜는 골라쓰는 것이지 늘 걸리는 게 아니다."""
    _model(s, 'M1', 'A', crawled=datetime(2026, 1, 1))
    _set(s, 'M1', '단품')
    assert L.rows(s, date_from='2026-08-02', date_to='2026-08-02')['total'] == 1


# ── 재고상태 (판매처 기준 — 사장님 2026-08-19 지시로 소싱처에서 이동) ──────

def test_재고있음만_고를_수_있다(s):
    _model(s, 'M1', '재고있음')
    a = _set(s, 'M1', '단품')
    _channel_opt(s, a.id, 'coupang', 'SKU1', mkt_stock=5)
    _model(s, 'M2', '품절')
    b = _set(s, 'M2', '단품')
    _channel_opt(s, b.id, 'coupang', 'SKU2', mkt_stock=0)
    got = L.rows(s, stock_status='instock')
    assert [r['name'] for r in got['rows']] == ['재고있음']


def test_품절만_고를_수_있다(s):
    _model(s, 'M1', '재고있음')
    a = _set(s, 'M1', '단품')
    _channel_opt(s, a.id, 'coupang', 'SKU1', mkt_stock=5)
    _model(s, 'M2', '품절')
    b = _set(s, 'M2', '단품')
    _channel_opt(s, b.id, 'coupang', 'SKU2', mkt_stock=0)
    got = L.rows(s, stock_status='soldout')
    assert [r['name'] for r in got['rows']] == ['품절']


def test_옵션_하나라도_재고있으면_재고있음으로_본다(s):
    """구성 하나에 옵션(색·사이즈)이 여럿 — 하나라도 살아있으면 재고 있음."""
    from lemouton.sets.models import SetChannelOption
    _model(s, 'M1', '섞임')
    a = _set(s, 'M1', '단품')
    ch = _channel_opt(s, a.id, 'coupang', 'SKU1', mkt_stock=0)
    s.add(SetChannelOption(channel_id=ch.id, canonical_sku='SKU2', status='matched', mkt_stock=3))
    s.flush()
    assert [r['name'] for r in L.rows(s, stock_status='instock')['rows']] == ['섞임']
    assert L.rows(s, stock_status='soldout')['total'] == 0


def test_마켓이_한번도_재고를_안_알려준_구성은_재고_품절_어디에도_안_걸린다(s):
    """지어내지 않는다 — 「모른다」와 「없다」는 다르다."""
    _model(s, 'M1', '확인안됨')
    _set(s, 'M1', '단품')
    assert L.rows(s, stock_status='instock')['total'] == 0
    assert L.rows(s, stock_status='soldout')['total'] == 0
    assert L.rows(s)['total'] == 1


# ── 가격·재고 변동 — 정렬과 기간 필터 둘 다(사장님 확정 "c") ─────────────

def test_변동일로_거른다(s):
    _model(s, 'M1', '어제바뀜')
    a = _set(s, 'M1', '단품')
    _change(s, a.id, 'coupang', 'stock', datetime(2026, 8, 1, 10))
    _model(s, 'M2', '오늘바뀜')
    b = _set(s, 'M2', '단품')
    _change(s, b.id, 'coupang', 'price', datetime(2026, 8, 2, 10))
    got = L.rows(s, date_basis='changed', date_from='2026-08-02', date_to='2026-08-02')
    assert [r['name'] for r in got['rows']] == ['오늘바뀜']


def test_변동일_기준을_안_고르면_안_거른다(s):
    _model(s, 'M1', 'A')
    _set(s, 'M1', '단품')
    assert L.rows(s, date_from='2026-08-02', date_to='2026-08-02')['total'] == 1


def test_변동일_최신순으로_정렬한다(s):
    _model(s, 'M1', '오래전')
    a = _set(s, 'M1', '단품')
    _change(s, a.id, 'coupang', 'stock', datetime(2026, 8, 1, 10))
    _model(s, 'M2', '최근')
    b = _set(s, 'M2', '단품')
    _change(s, b.id, 'coupang', 'price', datetime(2026, 8, 5, 10))
    got = L.rows(s, sort='changed')
    assert [r['name'] for r in got['rows']] == ['최근', '오래전']


def test_변동_없는_구성은_정렬시_맨_뒤로_밀린다(s):
    _model(s, 'M1', '변동없음')
    _set(s, 'M1', '단품')
    _model(s, 'M2', '변동있음')
    b = _set(s, 'M2', '단품')
    _change(s, b.id, 'coupang', 'stock', datetime(2026, 8, 1))
    got = L.rows(s, sort='changed')
    assert [r['name'] for r in got['rows']] == ['변동있음', '변동없음']

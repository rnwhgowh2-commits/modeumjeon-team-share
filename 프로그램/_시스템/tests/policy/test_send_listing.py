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


def _model(s, code, name, crawled=None, box=False):
    from lemouton.sourcing.models import Model
    m = Model(model_code=code, model_name_raw=name, model_name_display=name,
              brand='르무통', display_no='U-' + code, is_option_box=box,
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
    from lemouton.sets.models import SetChannel
    _model(s, 'M1', '등록됨')
    a = _set(s, 'M1', '단품')
    _model(s, 'M2', '미등록')
    _set(s, 'M2', '단품')
    s.add(SetChannel(set_id=a.id, market='coupang', account_key='default',
                     market_product_id='CP123'))
    s.flush()
    assert [r['name'] for r in L.rows(s, listed='no')['rows']] == ['미등록']
    got = L.rows(s, listed='yes')['rows'][0]
    assert got['listed'] == {'coupang': 'CP123'}


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


def test_구성_이름으로도_찾힌다(s):
    """「2벌 묶음」으로 찾을 수 있어야 한다 — 구성이 한 줄이니까."""
    _model(s, 'M1', '탑텐 탱크')
    _set(s, 'M1', '단품')
    _set(s, 'M1', '2벌 묶음')
    got = L.rows(s, keyword='2벌')
    assert [r['set_name'] for r in got['rows']] == ['2벌 묶음']


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


# ── 상품수집&전송 화면 개편 (2026-08) — 브랜드·정책ID·소싱처 URL ──────────

def test_브랜드가_실린다(s):
    _model(s, 'M1', '나이키 반팔')          # _model 은 brand='르무통' 고정
    _set(s, 'M1', '단품')
    assert L.rows(s)['rows'][0]['brand'] == '르무통'


def test_정책_아이디가_실린다_정책_편집_링크용(s):
    from lemouton.policy.models import SetPolicyLink
    _model(s, 'M1', 'A')
    ps = _set(s, 'M1', '단품')
    p = _policy(s, '정책A')
    s.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
    s.flush()
    r = L.rows(s)['rows'][0]
    assert r['policy_id'] == p.id


def test_정책_없으면_아이디도_없다(s):
    _model(s, 'M1', 'A')
    _set(s, 'M1', '단품')
    assert L.rows(s)['rows'][0]['policy_id'] is None


def test_소싱처_URL_상세가_실린다_바로가기용(s):
    _model(s, 'M1', '나이키 반팔')
    _set(s, 'M1', '단품')
    _src(s, 'M1', 'musinsa', 'https://musinsa.com/a')
    r = L.rows(s)['rows'][0]
    assert r['source_detail']['musinsa'] == [{'url': 'https://musinsa.com/a', 'label': ''}]


def test_같은_소싱처_URL_여러개는_전부_실린다(s):
    """sources 는 한 번만 세지만(칩용), source_detail 은 URL 전부(호버카드용) — 서로 다른 목적."""
    _model(s, 'M1', '나이키 반팔')
    _set(s, 'M1', '단품')
    _src(s, 'M1', 'musinsa', 'https://a')
    _src(s, 'M1', 'musinsa', 'https://b')
    r = L.rows(s)['rows'][0]
    assert r['sources'] == ['musinsa']
    assert [u['url'] for u in r['source_detail']['musinsa']] == ['https://a', 'https://b']


def test_소싱처_없으면_source_detail도_빈다(s):
    _model(s, 'M1', 'A')
    _set(s, 'M1', '단품')
    assert L.rows(s)['rows'][0]['source_detail'] == {}

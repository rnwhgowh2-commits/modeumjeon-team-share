# -*- coding: utf-8 -*-
"""구성에 안 걸린 **낱개 크롤 대상**도 확장이 가져갈 수 있어야 한다.

━━ 왜 필요한가 (라이브에서 드러남) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-08-07 — 검색필터가 찾은 주소 30개를 크롤 대기에 넣었는데, 크롤이 그날 아침
**4바퀴를 도는 동안 하나도 안 긁혔다.**

원인 = 확장이 받는 목록은 `due_bundle_codes` 다. 그건 due 인 `SourceProduct.url` 을
**`BundleSourceUrl`(모음전 구성에 등록된 URL)과 맞춰** 그 모음전 코드만 돌려준다.
검색필터가 넣은 낱개 주소는 어느 구성에도 안 걸리므로 **영영 목록에 안 들어간다.**
에러도 안 난다 — 그 함수 주석이 스스로 「조용한 누락」이라 부르는 바로 그 모양이다.

━━ 🔴 기존 목록을 건드리지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`due-bundles` 는 모음전 자동화가 쓰는 살아 있는 길이다. 거기에 낱개를 섞으면
「모음전 코드 하나 = 크롤 한 묶음」이라는 전제가 깨진다. **옆에 하나 더** 둔다
(검색필터 훑기 `due-listings` 를 붙였던 것과 같은 방식).
"""
import datetime

import pytest

_MADE = []

URL_LONE = 'https://www.musinsa.com/products/930001'      # 어느 구성에도 안 걸림
URL_IN_BUNDLE = 'https://www.musinsa.com/products/930002'  # 구성에 걸림


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _restore():
    """🔴 전역 설정(crawl_auto_enabled)을 건드리므로 반드시 되돌린다."""
    from shared.db import SessionLocal
    from lemouton.pricing.settings import get_or_init
    s = SessionLocal()
    try:
        was = bool(get_or_init(s).crawl_auto_enabled)
    finally:
        s.close()
    yield
    from lemouton.sources.models import SourceProduct
    from lemouton.sourcing.models import BundleSourceUrl
    s = SessionLocal()
    try:
        get_or_init(s).crawl_auto_enabled = was
        for u in (URL_LONE, URL_IN_BUNDLE):
            for r in s.query(BundleSourceUrl).filter_by(url=u).all():
                s.delete(r)
            for r in s.query(SourceProduct).filter_by(url=u).all():
                s.delete(r)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE.clear()


def _seed(*, crawl_on=True):
    """낱개 1건 + 구성에 걸린 1건. 둘 다 아직 안 긁힌 상태(=due)."""
    from shared.db import SessionLocal
    from lemouton.pricing.settings import get_or_init
    from lemouton.sources import service as SS
    from lemouton.sourcing.models import BundleSourceUrl
    s = SessionLocal()
    try:
        get_or_init(s).crawl_auto_enabled = bool(crawl_on)
        for u in (URL_LONE, URL_IN_BUNDLE):
            sp = SS.upsert_source_product(s, site='musinsa', url=u)
            sp.last_fetched_at = None          # 한 번도 안 긁음 = 지금 긁을 때
        s.add(BundleSourceUrl(model_code='시험_구성_코드', url=URL_IN_BUNDLE,
                              source_key='musinsa'))
        s.commit()
    finally:
        s.close()


def _urls(client):
    d = client.get('/api/crawl/due-urls').get_json()
    return d, {x['url'] for x in (d.get('items') or [])}


def test_구성에_안_걸린_주소가_목록에_나온다(client):
    """🔴 이게 없어서 검색필터가 넣은 30개가 4바퀴 도는 동안 안 긁혔다."""
    _seed()

    d, urls = _urls(client)

    assert d['enabled'] is True, d
    assert URL_LONE in urls, f'낱개 주소가 안 나온다: {urls}'


def test_구성에_걸린_주소는_여기_안_나온다(client):
    """겹치면 같은 상품을 두 경로가 각각 긁는다 — 소싱처를 두 번 두들기는 셈."""
    _seed()

    _d, urls = _urls(client)

    assert URL_IN_BUNDLE not in urls, '구성에 걸린 주소가 낱개 목록에도 나왔다'


def test_크롤이_꺼져_있으면_빈_목록(client):
    """실행/정지 스위치를 이 경로만 무시하면 「껐는데 도는」 상태가 된다."""
    _seed(crawl_on=False)

    d, urls = _urls(client)

    assert d['enabled'] is False, d
    assert urls == set(), urls


def test_이미_긁은_주소는_안_나온다(client):
    """방금 긁은 것을 또 주면 같은 상품만 계속 돈다."""
    from shared.db import SessionLocal
    from lemouton.sources.models import SourceProduct
    _seed()
    s = SessionLocal()
    try:
        sp = s.query(SourceProduct).filter_by(url=URL_LONE).first()
        sp.last_fetched_at = datetime.datetime.utcnow()
        sp.last_status = 'ok'
        s.commit()
    finally:
        s.close()

    _d, urls = _urls(client)

    assert URL_LONE not in urls, '방금 긁은 주소가 또 나왔다'

# -*- coding: utf-8 -*-
"""가공 규칙 **배선** — 사전 점검 · 실제 등록 · 초안 생성이 같은 답을 낸다.

`preflight_rows` docstring 이 못 박아 둔 규율: 「두 화면이 서로 다른 판정을 내놓으면
그게 곧 모순」. 여기가 그 고정이다.

또 하나 — 🔴 브랜드 미확정. 크롤 초안의 브랜드는 구조적으로 자주 빈다
(`draft_from_crawl.py:301-303`). 그대로 두면 「브랜드 미확정 → 정책 미적용 →
조용히 원본 그대로 등록」이 된다. 그 길을 막는다.
"""
# [2026-07-23] M4 가공 규칙 적용 엔진 — 배선
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("LIVE_REGISTER_ARMED", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


ALL_CODES = {
    'smartstore': '50000167', 'coupang': '63955',
    'auction': '00120005002000000000/37500700',
    'gmarket': '00120005002100000000/300006243',
    'eleven11': '1011634', 'lotteon': 'LO2727500650',
}

SRC = 'zzproc_src'


def _complete_body(**over):
    body = {
        'name': '테스트 자켓', 'brand': '테스트브랜드', 'sale_price': 39000,
        'stock_quantity': 7, 'notice_type': 'WEAR',
        'notice': {'material': '면 100%', 'color': '블랙', 'size': 'M / L',
                   'manufacturer': '테스트제조', 'caution': '단독세탁',
                   'warranty_policy': '구매일로부터 1년',
                   'after_service_director': '홍길동 010-1234-5678'},
        'images': ['https://example.com/main.jpg'],
        'detail_html': '<p>상세</p>',
        'delivery_fee': '3000', 'return_fee': '5000',
        'after_service_phone': '010-1234-5678',
        'after_service_guide': '평일 09-18시',
    }
    body.update(over)
    return body


@pytest.fixture()
def bag():
    """이 파일이 심은 행을 되돌린다."""
    kept = {'drafts': [], 'policies': []}
    yield kept
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import ProcessPolicy
    s = SessionLocal()
    try:
        for model, ids in ((ProductDraft, kept['drafts']),
                           (ProcessPolicy, kept['policies'])):
            for rid in ids:
                row = s.query(model).filter_by(id=rid).first()
                if row is not None:
                    s.delete(row)
        s.commit()
    except Exception:      # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _make_policy(bag, *, brand, rules, market=''):
    """정책 1건 + 소싱처 구성 + 규칙들. 정책 id 를 돌려준다."""
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import (
        attach_source, create_policy, set_rule)
    s = SessionLocal()
    try:
        p = create_policy(s, name=f'테스트정책-{brand}-{len(bag["policies"])}')
        attach_source(s, policy_id=p.id, source_key=SRC, brand=brand)
        for key, cfg in rules.items():
            set_rule(s, policy_id=p.id, item_key=key, config=cfg, market=market)
        s.commit()
        bag['policies'].append(p.id)
        return p.id
    finally:
        s.close()


def _make_draft(client, bag, *, source_site=None, **over):
    did = client.post('/bulk/api/drafts',
                      json=_complete_body(**over)).get_json()['draft_id']
    bag['drafts'].append(did)
    if source_site:
        # 수기 생성 라우트는 source_site 를 받지 않는다(크롤 초안만 채우는 칸)
        # — 테스트는 크롤 초안을 흉내 내려는 것이라 여기서 직접 심는다.
        from shared.db import SessionLocal
        from lemouton.registration.models import ProductDraft
        s = SessionLocal()
        try:
            d = s.query(ProductDraft).filter_by(id=did).first()
            d.source_site = source_site
            s.commit()
        finally:
            s.close()
    return did


def _rows(res):
    return {r['market']: r for r in res.get_json()['rows']}


# ── 실제로 적용된다 ─────────────────────────────────────────────────────────

def test_사전_점검이_가공된_상품명을_보여준다(client, bag):
    _make_policy(bag, brand='가공브랜드A',
                 rules={'name': {'token_order': ['brand', 'origin_name'],
                                 'separator': ' ', 'max_len': 100,
                                 'dedupe_words': True}})
    did = _make_draft(client, bag, brand='가공브랜드A', name='숏 패딩',
                      source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    row = _rows(r)['smartstore']
    assert row['process']['name'] == '가공브랜드A 숏 패딩', row['process']
    assert row['process']['applied'], '무엇이 바뀌었는지 로그가 비었습니다'


def test_저장된_상품명은_그대로다(client, bag):
    """가공은 사본에서만 — 사장님이 보는 저장값은 안 바뀐다."""
    _make_policy(bag, brand='가공브랜드B',
                 rules={'name': {'token_order': ['brand', 'origin_name']}})
    did = _make_draft(client, bag, brand='가공브랜드B', name='숏 패딩',
                      source_site=SRC)
    client.post(f'/bulk/api/drafts/{did}/preflight',
                json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    got = client.get(f'/bulk/api/drafts/{did}').get_json()['draft']
    assert got['name'] == '숏 패딩', '저장값이 덮였습니다 — 저장값 불변 위반'


def test_마켓별_규칙이_마켓마다_다르게_적용된다(client, bag):
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import set_rule
    pid = _make_policy(bag, brand='가공브랜드C',
                       rules={'name': {'token_order': ['brand', 'origin_name']}})
    s = SessionLocal()
    try:                                  # 쿠팡만 브랜드를 뒤로
        set_rule(s, policy_id=pid, item_key='name',
                 config={'token_order': ['origin_name', 'brand']}, market='coupang')
        s.commit()
    finally:
        s.close()
    did = _make_draft(client, bag, brand='가공브랜드C', name='숏 패딩',
                      source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore', 'coupang'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    assert rows['smartstore']['process']['name'] == '가공브랜드C 숏 패딩'
    assert rows['coupang']['process']['name'] == '숏 패딩 가공브랜드C'


# ── 🔴 브랜드 미확정 → 보류 + 표면화 ────────────────────────────────────────

def test_브랜드가_비면_가공규칙_보류로_막는다(client, bag):
    """조용히 원본 그대로 등록되면 안 된다 — 「브랜드 필요」로 세운다."""
    _make_policy(bag, brand='가공브랜드D',
                 rules={'name': {'token_order': ['brand', 'origin_name']}})
    did = _make_draft(client, bag, brand='', name='숏 패딩', source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore', 'lotteon'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    for market in ('smartstore', 'lotteon'):
        assert rows[market]['status'] == 'need_brand', rows[market]
        assert '브랜드가 정해지지 않았습니다' in rows[market]['reason']


def test_브랜드를_넣으면_보류가_풀린다(client, bag):
    _make_policy(bag, brand='가공브랜드E',
                 rules={'name': {'token_order': ['brand', 'origin_name']}})
    did = _make_draft(client, bag, brand='', name='숏 패딩', source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    assert _rows(r)['smartstore']['status'] == 'need_brand'

    client.put(f'/bulk/api/drafts/{did}', json={'brand': '가공브랜드E'})
    r2 = client.post(f'/bulk/api/drafts/{did}/preflight',
                     json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    row = _rows(r2)['smartstore']
    assert row['status'] == 'ready', row
    assert row['process']['name'] == '가공브랜드E 숏 패딩'


def test_그_소싱처에_정책이_없으면_브랜드가_비어도_보류하지_않는다(client, bag):
    """정책 미배정은 「브랜드 미확정」이 아니다 — 거짓 경고 금지."""
    did = _make_draft(client, bag, brand='', name='숏 패딩',
                      source_site='zz_no_policy_src')
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    assert _rows(r)['smartstore']['status'] != 'need_brand'


# ── 금지어 ──────────────────────────────────────────────────────────────────

def test_업로드_금지어는_그_마켓만_막는다(client, bag):
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import set_rule
    pid = _make_policy(bag, brand='가공브랜드F',
                       rules={'name': {'token_order': ['origin_name']}})
    s = SessionLocal()
    try:
        set_rule(s, policy_id=pid, item_key='banned_words',
                 config={'collect_banned': [], 'upload_banned': ['병행수입']},
                 market='coupang')
        s.commit()
    finally:
        s.close()
    did = _make_draft(client, bag, brand='가공브랜드F', name='병행수입 숏 패딩',
                      source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore', 'coupang'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    assert rows['coupang']['status'] == 'blocked', rows['coupang']
    assert '병행수입' in rows['coupang']['reason']
    assert rows['smartstore']['status'] == 'ready', rows['smartstore']


# ── 점검 == 등록 (모순 금지) ────────────────────────────────────────────────

def test_점검이_막은_것은_등록도_막는다(client, bag):
    """두 화면이 다른 답을 내면 그게 곧 모순이다."""
    _make_policy(bag, brand='가공브랜드G',
                 rules={'name': {'token_order': ['brand', 'origin_name']}})
    did = _make_draft(client, bag, brand='', name='숏 패딩', source_site=SRC)

    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    assert _rows(r)['smartstore']['status'] == 'need_brand'

    reg = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                      json={'category_code': ALL_CODES['smartstore']}).get_json()
    assert reg['ok'] is False and reg.get('blocked') is True, reg
    assert '브랜드가 정해지지 않았습니다' in (reg.get('reason') or reg.get('error') or '')


def test_등록이_쓰는_상품명은_점검이_보여준_그_이름이다(client, bag, monkeypatch):
    """가공본이 실제로 마켓 payload 에 실린다 — 「점검만 예쁘고 등록은 원본」 금지."""
    _make_policy(bag, brand='가공브랜드H',
                 rules={'name': {'token_order': ['brand', 'origin_name'],
                                 'separator': ' '}})
    did = _make_draft(client, bag, brand='가공브랜드H', name='숏 패딩',
                      source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    shown = _rows(r)['smartstore']['process']['name']
    assert shown == '가공브랜드H 숏 패딩'

    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    sent = {}

    def _fake_send(market, body):
        sent['body'] = body
        return {'originProductNo': '999'}

    s = SessionLocal()
    try:
        register_draft(s, did, 'smartstore',
                       category_code=ALL_CODES['smartstore'], _send=_fake_send,
                       # CDN 재호스팅은 라이브 업로드라 여기서 가짜로 대체한다.
                       _prepare=lambda urls: ['https://shop-phinf.pstatic.net/x.jpg'])
    finally:
        s.close()
    assert sent['body']['originProduct']['name'] == shown, sent['body']


def test_4마켓도_가공된_상품명으로_등록한다(client, bag):
    """MARKETS_MORE 분기가 가공을 건너뛰면 점검(6마켓 전부 가공)과 답이 갈린다."""
    _make_policy(bag, brand='가공브랜드I',
                 rules={'name': {'token_order': ['brand', 'origin_name']}})
    did = _make_draft(client, bag, brand='가공브랜드I', name='숏 패딩',
                      source_site=SRC)
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    sent = {}

    def _fake_send(market, spec):
        sent['spec'] = spec
        return {'product_id': 'A1'}

    s = SessionLocal()
    try:
        register_draft(s, did, 'eleven11', category_code=ALL_CODES['eleven11'],
                       _send=_fake_send)
    finally:
        s.close()
    assert sent['spec']['goods_name'] == '가공브랜드I 숏 패딩', sent['spec']


# ── 마켓별 상한 (확인된 것만) ───────────────────────────────────────────────

def test_쿠팡은_100자로_자르고_옥션은_자르지_않는다(client, bag):
    _make_policy(bag, brand='가공브랜드J',
                 rules={'name': {'token_order': ['origin_name'], 'max_len': 0}})
    did = _make_draft(client, bag, brand='가공브랜드J', name='가' * 200,
                      source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['coupang', 'auction'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    assert len(rows['coupang']['process']['name']) == 100
    assert len(rows['auction']['process']['name']) == 200
    assert any('확인 불가' in c for c in rows['auction']['caveats']), \
        '상한을 확인 못 했다는 사실이 화면에 안 뜹니다'


# ── 초안 생성(from-url) — 수집 금지어는 초안을 아예 만들지 않는다 ───────────

URL_SRC = 'zzproc_url_src'


def _seed_source(url, *, name, site=URL_SRC):
    import json as _j
    from shared.db import SessionLocal
    from lemouton.sources.models import SourceProduct
    s = SessionLocal()
    try:
        sp = SourceProduct(site=site, url=url, product_name=name,
                           last_price=89000, last_stock=5,
                           category_path='신발>스니커즈',
                           images_json=_j.dumps(['https://img/1.jpg']),
                           detail_html='<p>상세</p>')
        s.add(sp)
        s.commit()
        return sp.id
    finally:
        s.close()


def _uniq_url():
    import uuid
    return f'https://example.test/p/{uuid.uuid4().hex[:10]}'


@pytest.fixture()
def url_bag():
    kept = {'sources': [], 'policies': [], 'drafts': []}
    yield kept
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import ProcessPolicy
    from lemouton.sources.models import SourceProduct
    s = SessionLocal()
    try:
        for model, ids in ((ProductDraft, kept['drafts']),
                           (ProcessPolicy, kept['policies']),
                           (SourceProduct, kept['sources'])):
            for rid in ids:
                row = s.query(model).filter_by(id=rid).first()
                if row is not None:
                    s.delete(row)
        s.commit()
    except Exception:      # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _url_policy(url_bag, rules):
    """크롤 초안의 브랜드는 대개 비어 있다 — 브랜드 '' 구성에 정책을 붙인다."""
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import (
        attach_source, create_policy, set_rule)
    s = SessionLocal()
    try:
        p = create_policy(s, name=f'URL정책-{len(url_bag["policies"])}')
        attach_source(s, policy_id=p.id, source_key=URL_SRC, brand='')
        for key, cfg in rules.items():
            set_rule(s, policy_id=p.id, item_key=key, config=cfg)
        s.commit()
        url_bag['policies'].append(p.id)
        return p.id
    finally:
        s.close()


def test_수집_금지어가_있으면_초안을_만들지_않고_사유를_말한다(client, url_bag):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft

    _url_policy(url_bag, {'banned_words': {'collect_banned': ['짝퉁'],
                                           'upload_banned': []}})
    url = _uniq_url()
    url_bag['sources'].append(_seed_source(url, name='짝퉁 스니커즈'))

    r = client.post('/bulk/api/drafts/from-url', json={'url': url})
    body = r.get_json()
    assert body['ok'] is False, body
    assert body['code'] == 'COLLECT_BANNED', body
    assert '짝퉁' in body['error']

    s = SessionLocal()
    try:
        made = s.query(ProductDraft).filter_by(source_url=url).count()
    finally:
        s.close()
    assert made == 0, '수집 금지어에 걸렸는데 초안이 만들어졌습니다'


def test_초안을_만들면서_가공_미리보기를_같이_돌려준다(client, url_bag):
    _url_policy(url_bag, {'name': {'token_order': ['[정품]', 'origin_name'],
                                   'separator': ' '}})
    url = _uniq_url()
    url_bag['sources'].append(_seed_source(url, name='크롤 스니커즈'))

    body = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()
    assert body['ok'] is True, body
    url_bag['drafts'].append(body['draft_id'])
    assert body['process']['name'] == '[정품] 크롤 스니커즈', body['process']

    # ★ 저장값은 원본 그대로 — 미리보기일 뿐이다.
    got = client.get(f"/bulk/api/drafts/{body['draft_id']}").get_json()['draft']
    assert got['name'] == '크롤 스니커즈'


# ══ [2026-07-23 리뷰 I5] 브랜드가 비어도 수집 금지어는 작동한다 ══════════════

def test_브랜드가_비어도_수집_금지어는_초안을_막는다(client, url_bag):
    """수집 금지어는 「소싱처 단위」 게이트다. 브랜드로 정책을 고른 뒤에 읽으면,
    브랜드가 빈 크롤 초안(대부분)에서 게이트가 통째로 꺼져 「이월상품 스니커즈」가
    그대로 초안이 됐다 — 실측된 사고."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import (
        attach_source, create_policy, set_rule)

    # 브랜드가 **지정된** 정책만 있는 소싱처 → 브랜드 빈 초안은 정책을 못 고른다.
    s = SessionLocal()
    try:
        p = create_policy(s, name='URL정책-브랜드지정')
        attach_source(s, policy_id=p.id, source_key=URL_SRC, brand='어떤브랜드')
        set_rule(s, policy_id=p.id, item_key='banned_words',
                 config={'collect_banned': ['이월상품'], 'upload_banned': []})
        s.commit()
        url_bag['policies'].append(p.id)
    finally:
        s.close()

    url = _uniq_url()
    url_bag['sources'].append(_seed_source(url, name='이월상품 스니커즈'))

    body = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()
    assert body['ok'] is False, body
    assert body['code'] == 'COLLECT_BANNED', body

    s = SessionLocal()
    try:
        made = s.query(ProductDraft).filter_by(source_url=url).count()
    finally:
        s.close()
    assert made == 0, '브랜드가 비었다고 수집 금지어 게이트가 꺼졌습니다'


def test_짧은_영단어_금지어가_초안을_지우지_않는다(client, url_bag):
    """리뷰 C1 회귀 — 'Men' 이 'Mentoring Jacket' 을 막으면 카탈로그가 사라진다."""
    _url_policy(url_bag, {'banned_words': {'collect_banned': ['Men'],
                                           'upload_banned': []}})
    url = _uniq_url()
    url_bag['sources'].append(_seed_source(url, name='Mentoring Jacket'))

    body = client.post('/bulk/api/drafts/from-url', json={'url': url}).get_json()
    assert body['ok'] is True, body
    url_bag['drafts'].append(body['draft_id'])


def test_영문_브랜드_상품이_기본_규칙에_막히지_않는다(client, bag):
    """리뷰 C2 회귀 — 「상품명」 항목을 기본값 그대로 저장만 해도 막히던 사고."""
    from lemouton.registration.process_rule_schema import default_config
    _make_policy(bag, brand='NIKE', rules={'name': default_config('name')})
    did = _make_draft(client, bag, brand='NIKE', name='Air Force 1',
                      source_site=SRC)
    r = client.post(f'/bulk/api/drafts/{did}/preflight',
                    json={'markets': ['smartstore', 'coupang', 'auction',
                                      'gmarket', 'eleven11', 'lotteon'],
                          'category_codes': ALL_CODES})
    rows = _rows(r)
    for market, row in rows.items():
        assert row['status'] != 'blocked', (market, row)
        assert row['process']['name'] == 'NIKE Air Force 1', (market, row['process'])

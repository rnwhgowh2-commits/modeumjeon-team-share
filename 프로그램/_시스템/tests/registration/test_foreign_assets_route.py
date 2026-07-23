# -*- coding: utf-8 -*-
"""등록 전 점검에 **타 마켓 브랜딩 이미지**를 실어 보내고, 고른 것만 빼는 라우트.

[2026-07-23 사장님 결정 (나)안]
  자동 제거 ❌ — 점검에서 **보여 주고** 사장님이 「상세에서 빼기」를 눌러야 빠진다.

지키는 것
  ① 4마켓(옥션·G마켓·11번가·롯데온)은 상세 HTML 을 그대로 본문으로 쓴다
     (`compile_more.py:98`) → 그 행에 `foreign_assets` 가 실린다.
  ② 상태는 **막지 않는다** — `ready` 그대로 두고 `caveats` 에 주의만 보탠다.
     (막으면 오탐 하나로 등록이 통째로 멈춘다.)
  ③ 제거 API 는 **준 주소만** 뺀다 — 나머지 사진·글은 그대로 남는다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("LIVE_REGISTER_ARMED", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


BANNER = 'https://nike2094.godohosting.com/products/info/ssg_banner.jpg'
PHOTO = 'https://sitem.ssgcdn.com/58/80/93/item/1000809938058_i1_1200.jpg'
GUIDE = 'https://nike2094.godohosting.com/products/info/new_size/size_shoes_man.jpg'

#: 배너 1 + 상품사진 1 + 안내사진 1 — 실측 SSG 상세의 축소판.
DETAIL = (f'<div><p>상세 설명</p><img src="{BANNER}">'
          f'<img src="{PHOTO}"><img src="{GUIDE}"></div>')

ALL_CODES = {
    'smartstore': '50000167', 'coupang': '63955',
    'auction': '00120005002000000000/37500700',
    'gmarket': '00120005002100000000/300006243',
    'eleven11': '1011634', 'lotteon': 'LO2727500650',
}


def _draft(client, detail_html=DETAIL):
    body = {
        'name': '테스트 자켓', 'brand': '테스트브랜드', 'sale_price': 39000,
        'stock_quantity': 7, 'notice_type': 'WEAR',
        'notice': {
            'material': '면 100%', 'color': '블랙', 'size': 'M / L',
            'manufacturer': '테스트제조', 'caution': '단독세탁',
            'warranty_policy': '구매일로부터 1년',
            'after_service_director': '홍길동 010-1234-5678',
        },
        'images': ['https://example.com/main.jpg'],
        'detail_html': detail_html,
        'delivery_fee': '3000', 'return_fee': '5000',
        'after_service_phone': '010-1234-5678',
        'after_service_guide': '평일 09-18시',
    }
    return client.post('/bulk/api/drafts', json=body).get_json()['draft_id']


def _rows(res):
    return {r['market']: r for r in res.get_json()['rows']}


def _preflight(client, did, markets=None):
    return client.post(f'/bulk/api/drafts/{did}/preflight',
                       json={'markets': markets or list(ALL_CODES),
                             'category_codes': ALL_CODES})


# ── ① 상세를 쓰는 4마켓 행에 실린다 ────────────────────────────────────────────
def test_상세를_쓰는_4마켓에_타마켓_이미지가_실린다(client):
    rows = _rows(_preflight(client, _draft(client)))
    for market in ('auction', 'gmarket', 'eleven11', 'lotteon'):
        fa = rows[market]['foreign_assets']
        assert [h['url'] for h in fa] == [BANNER], (market, fa)
        assert fa[0]['token'] == 'ssg' and fa[0]['where'] == 'img'


def test_상품사진과_안내사진은_섞여_들어오지_않는다(client):
    """오탐이 하나라도 섞이면 사장님이 상품 사진을 지우게 된다."""
    fa = _rows(_preflight(client, _draft(client)))['auction']['foreign_assets']
    urls = [h['url'] for h in fa]
    assert PHOTO not in urls and GUIDE not in urls, urls


def test_상세를_안_쓰는_마켓은_빈_목록이다(client):
    """스스·쿠팡 행에 붙이면 거짓 안내다 — 키는 있고 값은 비어 있어야 한다."""
    rows = _rows(_preflight(client, _draft(client)))
    for market in ('smartstore', 'coupang'):
        assert rows[market]['foreign_assets'] == [], rows[market]


def test_타마켓_이미지가_없으면_빈_목록이고_주의도_안_붙는다(client):
    did = _draft(client, detail_html=f'<div><p>상세</p><img src="{PHOTO}"></div>')
    row = _rows(_preflight(client, did, ['auction']))['auction']
    assert row['foreign_assets'] == []
    assert not any('타 마켓' in c for c in row['caveats']), row['caveats']


# ── ② 막지 않는다 — ready 유지 + 주의만 보탠다 ──────────────────────────────
def test_막지_않는다_ready_는_그대로고_주의만_늘어난다(client):
    """🔴 오탐 하나로 등록이 멈추면 안 된다 — 판단은 사장님이 한다((나)안)."""
    row = _rows(_preflight(client, _draft(client), ['auction']))['auction']
    assert row['status'] == 'ready', row
    joined = ' '.join(row['caveats'])
    assert '타 마켓 이미지가 1개' in joined, row['caveats']
    assert '판매금지' in joined, row['caveats']


# ── ③ 제거 API — 고른 것만 뺀다 ────────────────────────────────────────────
def test_고른_이미지만_빼고_저장한다(client):
    did = _draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/detail/remove-assets',
                    json={'urls': [BANNER]})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['ok'] is True and body['removed'] == 1

    saved = client.get(f'/bulk/api/drafts/{did}').get_json()['draft']['detail_html']
    assert 'ssg_banner.jpg' not in saved
    assert PHOTO in saved and GUIDE in saved and '상세 설명' in saved
    # 다시 점검하면 이제 아무것도 안 잡힌다.
    assert _rows(_preflight(client, did, ['auction']))['auction']['foreign_assets'] == []


def test_없는_주소를_주면_0건이고_상세는_그대로다(client):
    did = _draft(client)
    body = client.post(f'/bulk/api/drafts/{did}/detail/remove-assets',
                       json={'urls': ['https://cdn.example.com/zzz.jpg']}).get_json()
    assert body['removed'] == 0
    saved = client.get(f'/bulk/api/drafts/{did}').get_json()['draft']['detail_html']
    assert BANNER in saved and PHOTO in saved


def test_urls_가_배열이_아니면_400(client):
    did = _draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/detail/remove-assets',
                    json={'urls': BANNER})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_빈_목록이면_400_아무것도_안_지운다(client):
    """실수로 빈 요청이 오면 조용히 성공(0건)하지 말고 무엇이 없는지 말한다."""
    did = _draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/detail/remove-assets', json={'urls': []})
    assert r.status_code == 400
    assert '빼실 이미지' in r.get_json()['error']


def test_없는_드래프트는_404(client):
    r = client.post('/bulk/api/drafts/999999/detail/remove-assets',
                    json={'urls': [BANNER]})
    assert r.status_code == 404


def test_제거는_마켓_API_를_부르지_않는다(client, monkeypatch):
    """상세 손질은 우리 DB 안 일이다 — 네트워크가 끼면 안 된다."""
    def _boom(*a, **kw):
        raise AssertionError('제거가 외부 HTTP 를 불렀습니다 — 절대 금지')

    import requests
    monkeypatch.setattr(requests.Session, 'request', _boom)
    monkeypatch.setattr(requests, 'request', _boom)
    did = _draft(client)
    r = client.post(f'/bulk/api/drafts/{did}/detail/remove-assets',
                    json={'urls': [BANNER]})
    assert r.status_code == 200 and r.get_json()['removed'] == 1

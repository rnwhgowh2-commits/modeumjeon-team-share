# -*- coding: utf-8 -*-
"""드래프트 CRUD·등록 라우트 — Task 8 에서 이관된 라우트 자동 테스트.

drafts.py 라우트는 지금까지 자동 테스트가 없었다. 수기 화면(Task 9)이 이 라우트를
처음 실제로 두드리는 지점이라 여기서 함께 덮는다. 특히 코드리뷰가 지적한
"라우트가 int()로 500 을 낸다"(콤마·비숫자 입력) 를 coerce_int 로 고친 것을 고정한다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    # 이 저장소의 라우트 테스트 관례 (tests/registration/test_bulk_mode.py:6-13)
    monkeypatch.setenv("DISABLE_AUTH", "1")
    # 실등록 게이트는 반드시 꺼진 상태로 테스트한다 (ambient 로 켜져 있으면 실호출).
    monkeypatch.delenv("LIVE_REGISTER_ARMED", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _compilable_draft():
    """스스 컴파일러를 통과하는 완결된 드래프트 body.

    등록 게이트(blocked) 까지 가려면 컴파일이 먼저 성공해야 한다 — CDN 이미지·고시
    필수 7+유형별·A/S 연락처가 모두 있어야 한다.
    """
    return {
        'name': '테스트 자켓',
        'brand': '테스트브랜드',
        'sale_price': 39000,
        'notice_type': 'WEAR',
        'notice': {
            'material': '면 100%',
            'color': '블랙',
            'size': 'M / L',
            'manufacturer': '테스트제조',
            'caution': '단독세탁',
            'warranty_policy': '구매일로부터 1년',
            'after_service_director': '홍길동 010-1234-5678',
        },
        'cdn_images': ['https://shop-phinf.pstatic.net/20260718/test.jpg'],
        'detail_html': '<p>상세</p>',
        'options': [{'color': '블랙', 'size': 'M', 'stock': 10, 'extra_price': 0}],
        'delivery_fee': '3000',
        'return_fee': '5000',
        'after_service_phone': '010-1234-5678',
        'after_service_guide': '평일 09-18시',
    }


# ── POST /bulk/api/drafts ────────────────────────────────────────────────────

def test_create_draft_ok(client):
    r = client.post('/bulk/api/drafts', json={'name': '상품A', 'sale_price': 12000})
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True
    assert isinstance(body['draft_id'], int)


def test_create_draft_missing_name_400(client):
    r = client.post('/bulk/api/drafts', json={'sale_price': 12000})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_create_draft_bad_option_400_not_500(client):
    """재고 자리에 '빨강' 같은 비숫자 → 저장 전에 400 으로 걸러야 한다(500 아님)."""
    r = client.post('/bulk/api/drafts', json={
        'name': '상품B', 'sale_price': 12000,
        'options': [{'color': '빨강', 'size': 'M', 'stock': '빨강'}],
    })
    assert r.status_code == 400, r.get_data(as_text=True)
    assert r.get_json()['ok'] is False


def test_create_draft_bad_number_abc_400_not_500(client):
    """normal_price='abc' → coerce_int 가 CompileError → 400 (bare int() 였다면 500)."""
    r = client.post('/bulk/api/drafts', json={
        'name': '상품C', 'sale_price': 12000, 'normal_price': 'abc',
    })
    assert r.status_code == 400, r.get_data(as_text=True)
    assert r.get_json()['ok'] is False


def test_create_draft_comma_number_succeeds(client):
    """delivery_fee='1,000' → coerce_int 가 콤마를 떼어 1000 → 성공 200 (500·400 아님).

    엑셀·폼 붙여넣기가 콤마 낀 숫자를 보내는 건 정상 입력이다 — 막지 않는다.
    """
    r = client.post('/bulk/api/drafts', json={
        'name': '상품D', 'sale_price': 12000, 'delivery_fee': '1,000',
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['ok'] is True


# ── POST /bulk/api/drafts/<id>/register/<market> ─────────────────────────────

def test_register_gate_off_is_blocked_not_500(client):
    """게이트 미설정 → {'ok':False,'blocked':True} 200 (500 아님)."""
    did = client.post('/bulk/api/drafts', json=_compilable_draft()).get_json()['draft_id']
    r = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                    json={'category_code': '50000167'})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['ok'] is False
    assert body['blocked'] is True


def test_register_bad_market_400(client):
    did = client.post('/bulk/api/drafts', json={'name': '상품E', 'sale_price': 12000}).get_json()['draft_id']
    r = client.post(f'/bulk/api/drafts/{did}/register/11st',
                    json={'category_code': '123'})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_register_missing_id_404(client):
    r = client.post('/bulk/api/drafts/9999999/register/smartstore',
                    json={'category_code': '123'})
    assert r.status_code == 404
    assert r.get_json()['ok'] is False


def test_register_missing_category_400(client):
    did = client.post('/bulk/api/drafts', json={'name': '상품F', 'sale_price': 12000}).get_json()['draft_id']
    r = client.post(f'/bulk/api/drafts/{did}/register/smartstore', json={})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


# ── GET /bulk/api/drafts ─────────────────────────────────────────────────────

def test_list_drafts_returns_created_with_account_key(client):
    """만든 draft 가 목록에 뜨고, 등록 시도한 마켓 행마다 account_key 가 있다."""
    did = client.post('/bulk/api/drafts', json=_compilable_draft()).get_json()['draft_id']
    # 등록(blocked) → market 행이 생긴다
    client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                json={'category_code': '50000167'})
    r = client.get('/bulk/api/drafts')
    assert r.status_code == 200
    rows = r.get_json()['rows']
    mine = next(d for d in rows if d['id'] == did)
    assert mine['name'] == '테스트 자켓'
    assert mine['markets'], '등록 시도한 마켓 행이 있어야 한다'
    for m in mine['markets']:
        assert 'account_key' in m
        assert m['account_key'] == 'default'

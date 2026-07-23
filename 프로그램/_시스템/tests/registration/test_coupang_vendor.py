# -*- coding: utf-8 -*-
"""M4-2 쿠팡 계정정보(vendor) 저장·주입.

문제: compile_coupang 은 vendor 9키를 요구하는데 등록 화면이 아무것도 안 보내
      쿠팡 등록이 100% 실패했다(compile_coupang.py:43 「vendorId 가 필요합니다」).

설계 판단: vendor 값은 **드래프트가 아니라 계정에 매인 고정값**이다(반품지·출고지는
쿠팡 셀러가 Wing 에 등록해 둔 것). 그래서 드래프트마다 입력받지 않고 계정별로 한 번
저장한 뒤 등록·점검 때 자동 주입한다.

★ vendor_id 는 **저장하지 않는다** — 이미 `.env` 의 `{prefix}_VENDOR_ID` 가 단일 원천이다.
  DB 에 또 두면 두 값이 갈리는 날 잘못된 계정으로 등록된다(CLAUDE.md 중복·모순 금지).
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


@pytest.fixture
def session():
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


PREFIX = "COUPANG_TEST_M4"

FULL = {
    "vendor_user_id": "wing_login_id",
    "return_center_code": "1000557004",
    "return_charge_name": "르무통 반품지",
    "return_zip": "42701",
    "return_address": "대구시 달서구 성서공단로",
    "return_address_detail": "235",
    "return_phone": "02-111-1111",
    "outbound_place_code": "1111222",
}


@pytest.fixture(autouse=True)
def _cleanup():
    """테스트가 만든 계정정보 행을 지운다 — 라이브 설정값을 오염시키지 않는다."""
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import CoupangVendorSetting
    s = SessionLocal()
    try:
        (s.query(CoupangVendorSetting)
         .filter(CoupangVendorSetting.env_prefix.like("COUPANG_TEST%")).delete(
             synchronize_session=False))
        s.commit()
    except Exception:      # noqa: BLE001
        s.rollback()
    finally:
        s.close()


# ── 저장소 ──────────────────────────────────────────────────────

def test_app이_계정정보_모델을_import_한다():
    """create_all 은 import 된 모델만 만든다 — 빠뜨리면 저장이 조용히 안 된다."""
    import io
    import os
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = io.open(os.path.join(here, "app.py"), encoding="utf-8").read()
    assert "lemouton.registration.models" in src


def test_저장한_적_없으면_None(session):
    from lemouton.registration import coupang_vendor as CV
    assert CV.get_saved(session, "COUPANG_TEST_NONE") is None


def test_저장_후_그대로_돌아온다(session):
    from lemouton.registration import coupang_vendor as CV
    CV.save_vendor(session, PREFIX, **FULL)
    session.commit()
    got = CV.get_saved(session, PREFIX)
    for k, v in FULL.items():
        assert got[k] == v, k


def test_같은_계정을_두_번_저장해도_행이_하나(session):
    """env_prefix 는 유니크 — 중복 행이 쌓이면 어느 값이 쓰일지 모른다."""
    from lemouton.registration.models import CoupangVendorSetting
    from lemouton.registration import coupang_vendor as CV
    CV.save_vendor(session, PREFIX, **FULL)
    session.commit()
    CV.save_vendor(session, PREFIX, **{**FULL, "return_zip": "06236"})
    session.commit()
    rows = session.query(CoupangVendorSetting).filter_by(env_prefix=PREFIX).all()
    assert len(rows) == 1
    assert rows[0].return_zip == "06236"


def test_보낸_칸만_갱신되고_안_보낸_칸은_남는다(session):
    from lemouton.registration import coupang_vendor as CV
    CV.save_vendor(session, PREFIX, **FULL)
    session.commit()
    CV.save_vendor(session, PREFIX, return_phone="031-999-9999")
    session.commit()
    got = CV.get_saved(session, PREFIX)
    assert got["return_phone"] == "031-999-9999"
    assert got["return_center_code"] == FULL["return_center_code"]   # 안 보낸 칸은 유지


# ── vendor_id 는 .env 에서만 온다 (중복 저장 금지) ─────────────────

def test_vendor_id_는_DB_에_저장되지_않는다():
    """컬럼 자체가 없어야 한다 — 있으면 언젠가 .env 와 갈린다."""
    from lemouton.registration.models import CoupangVendorSetting
    assert "vendor_id" not in CoupangVendorSetting.__table__.columns


def test_vendor_는_env_의_vendor_id_를_합쳐_9키를_만든다(session, monkeypatch):
    from lemouton.registration import coupang_vendor as CV
    CV.save_vendor(session, PREFIX, **FULL)
    session.commit()

    class _C:
        vendor_id = "A00012345"

    monkeypatch.setattr(CV, "_load_credentials", lambda prefix: _C())
    v = CV.build_vendor(session, PREFIX)
    assert v["vendor_id"] == "A00012345"
    for k, val in FULL.items():
        assert v[k] == val


def test_env_에_키가_없으면_vendor_id_가_빈칸이지_날조하지_않는다(session, monkeypatch):
    from lemouton.registration import coupang_vendor as CV
    CV.save_vendor(session, PREFIX, **FULL)
    session.commit()
    monkeypatch.setattr(CV, "_load_credentials", lambda prefix: None)
    v = CV.build_vendor(session, PREFIX)
    assert v["vendor_id"] == ""      # 컴파일러가 「vendorId 가 필요합니다」로 막아준다


def test_저장값이_없으면_build_vendor_는_빈_dict(session, monkeypatch):
    from lemouton.registration import coupang_vendor as CV
    monkeypatch.setattr(CV, "_load_credentials", lambda prefix: None)
    assert CV.build_vendor(session, "COUPANG_TEST_NONE") == {}


# ── 계정 → env_prefix 해석 ───────────────────────────────────────

def test_default_는_활성_쿠팡_계정을_고른다(session):
    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.registration import coupang_vendor as CV
    acct = UploadAccount(account_key="테스트_쿠팡_M4", display_name="테스트 쿠팡",
                         market="coupang", env_prefix=PREFIX, is_active=True)
    session.add(acct)
    session.flush()
    try:
        assert CV.resolve_env_prefix(session, "default") == PREFIX
        assert CV.resolve_env_prefix(session, "테스트_쿠팡_M4") == PREFIX
    finally:
        session.delete(acct)
        session.flush()


def test_계정이_하나도_없으면_전역_기본_접두사(session):
    """계정 표가 비어도 `.env` 의 COUPANG_* 로 등록은 나간다 — 그 접두사를 쓴다."""
    from lemouton.registration import coupang_vendor as CV
    from lemouton.sourcing.models_v2 import UploadAccount
    rows = session.query(UploadAccount).filter_by(market="coupang").all()
    if rows:
        pytest.skip("이 DB 에 쿠팡 계정이 이미 있어 '없을 때' 를 볼 수 없다")
    assert CV.resolve_env_prefix(session, "default") == "COUPANG"


def test_모르는_계정키는_None(session):
    from lemouton.registration import coupang_vendor as CV
    assert CV.resolve_env_prefix(session, "없는계정_XYZ") is None


# ── 수확(쿠팡 조회 API) — 실호출 금지, monkeypatch 로만 ──────────────

_RETURN_CENTERS = {
    "code": 200, "message": "SUCCESS",
    "data": {"content": [{
        "vendorId": "A00012345",
        "returnCenterCode": "1000557004",
        "shippingPlaceName": "32777 R",
        "usable": True,
        "placeAddresses": [{
            "addressType": "JIBUN", "countryCode": "KR",
            "companyContactNumber": "02-111-1111", "phoneNumber2": "000-0000-0000",
            "returnZipCode": "42701", "returnAddress": "대구시 달서구 성서공단로",
            "returnAddressDetail": "235",
        }],
    }], "pagination": {"currentPage": 1, "totalPages": 1,
                       "totalElements": 1, "countPerPage": 10}},
}

_OUTBOUND = {
    "content": [{
        "outboundShippingPlaceCode": 1111222,
        "shippingPlaceName": "상품출고지1",
        "usable": True,
        "placeAddresses": [{"addressType": "JIBUN", "countryCode": "KR",
                            "companyContactNumber": "02-1234-5678",
                            "returnZipCode": "05510",
                            "returnAddress": "서울특별시 송파구 신천동",
                            "returnAddressDetail": "7-30"}],
    }],
    "pagination": {"currentPage": 1, "countPerPage": 1, "totalPages": 1, "totalElements": 1},
}


class _FakeClient:
    """쿠팡 클라이언트 대역 — 호출된 (method, path, query) 를 기록한다."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def request(self, method, path, query="", body=None):
        self.calls.append((method, path, query))
        for frag, ans in self.answers.items():
            if frag in path:
                return ans
        raise AssertionError(f"예상 못 한 호출: {path}")


def test_반품지_목록을_9키_후보로_바꾼다():
    from shared.platforms.coupang import logistics as L
    c = _FakeClient({"returnShippingCenters": _RETURN_CENTERS})
    rows = L.list_return_centers("A00012345", client=c)
    assert len(rows) == 1
    r = rows[0]
    assert r["return_center_code"] == "1000557004"
    assert r["return_charge_name"] == "32777 R"      # shippingPlaceName = 반품지'명'
    assert r["return_zip"] == "42701"
    assert r["return_address"] == "대구시 달서구 성서공단로"
    assert r["return_address_detail"] == "235"
    assert r["return_phone"] == "02-111-1111"        # companyContactNumber
    # vendorId 는 경로 파라미터로 들어간다
    assert "A00012345" in c.calls[0][1]


def test_출고지_목록을_코드_이름으로_바꾼다():
    from shared.platforms.coupang import logistics as L
    c = _FakeClient({"shipping-place/outbound": _OUTBOUND})
    rows = L.list_outbound_places(client=c)
    assert rows == [{"outbound_place_code": "1111222", "name": "상품출고지1", "usable": True}]


def test_반품지_주소가_없어도_터지지_않고_빈칸(monkeypatch):
    """placeAddresses 가 비어 오는 계정이 있다 — 0 이나 추측으로 채우지 않는다."""
    from shared.platforms.coupang import logistics as L
    payload = {"data": {"content": [{"returnCenterCode": "1", "shippingPlaceName": "N",
                                     "placeAddresses": []}]}}
    rows = L.list_return_centers("A0", client=_FakeClient({"returnShippingCenters": payload}))
    assert rows[0]["return_zip"] == ""
    assert rows[0]["return_address"] == ""


def test_사용불가_반품지는_표시는_하되_usable_False로_구분():
    from shared.platforms.coupang import logistics as L
    payload = {"data": {"content": [{"returnCenterCode": "1", "shippingPlaceName": "옛 반품지",
                                     "usable": False, "placeAddresses": []}]}}
    rows = L.list_return_centers("A0", client=_FakeClient({"returnShippingCenters": payload}))
    assert rows[0]["usable"] is False


# ── 라우트 ──────────────────────────────────────────────────────

def test_계정정보_조회_라우트(client):
    j = client.get('/bulk/api/settings/coupang-vendor').get_json()
    assert j['ok'] is True
    assert isinstance(j['accounts'], list)
    # 9키가 무엇인지 화면이 알 수 있어야 한다
    assert 'return_center_code' in j['keys']
    assert 'vendor_id' not in j['keys']       # .env 소관 — 화면에서 못 고친다


def test_계정정보_저장_라우트(client):
    r = client.post('/bulk/api/settings/coupang-vendor',
                    json={'env_prefix': PREFIX, **FULL})
    j = r.get_json()
    assert j['ok'] is True, j
    got = client.get('/bulk/api/settings/coupang-vendor').get_json()
    row = [a for a in got['accounts'] if a['env_prefix'] == PREFIX]
    assert row and row[0]['saved']['return_zip'] == FULL['return_zip']


def test_계정_없이_저장하면_거부(client):
    j = client.post('/bulk/api/settings/coupang-vendor', json={**FULL}).get_json()
    assert j['ok'] is False
    assert 'env_prefix' in j['error'] or '계정' in j['error']


def test_불러오기_라우트가_후보를_돌려준다(client, monkeypatch):
    """「쿠팡에서 불러오기」 — 사장님이 9칸을 손으로 적지 않게 한다."""
    import webapp.routes.bulk.settings_tab as ST
    monkeypatch.setattr(ST, '_coupang_client_for', lambda prefix: _FakeClient({
        'returnShippingCenters': _RETURN_CENTERS, 'shipping-place/outbound': _OUTBOUND}))
    monkeypatch.setattr(ST, '_vendor_id_for', lambda prefix: 'A00012345')
    j = client.post('/bulk/api/settings/coupang-vendor/fetch',
                    json={'env_prefix': PREFIX}).get_json()
    assert j['ok'] is True, j
    assert j['vendor_id'] == 'A00012345'
    assert j['return_centers'][0]['return_center_code'] == '1000557004'
    assert j['outbound_places'][0]['outbound_place_code'] == '1111222'


def test_불러오기가_실패하면_사유를_그대로_말한다(client, monkeypatch):
    """조용한 성공 금지 — 키가 없거나 권한이 없으면 그 사실이 화면에 나와야 한다."""
    import webapp.routes.bulk.settings_tab as ST

    def _boom(prefix):
        raise RuntimeError('키가 없습니다')

    monkeypatch.setattr(ST, '_vendor_id_for', _boom)
    j = client.post('/bulk/api/settings/coupang-vendor/fetch',
                    json={'env_prefix': PREFIX}).get_json()
    assert j['ok'] is False
    assert '키가 없습니다' in j['error']


# ── 주입 (등록·사전점검) ─────────────────────────────────────────

def _draft(client, **over):
    body = {'name': '쿠팡 주입 시험 상품', 'sale_price': 39000, 'stock_quantity': 5,
            'images': ['https://img.example.com/a.jpg'], 'detail_html': '<p>상세</p>'}
    body.update(over)
    return client.post('/bulk/api/drafts', json=body).get_json()['draft_id']


def _coupang_row(res):
    return [r for r in res.get_json()['rows'] if r['market'] == 'coupang'][0]


def test_사전점검_저장값이_없으면_먼저_저장하라고_안내(client, monkeypatch):
    import lemouton.registration.coupang_vendor as CV
    monkeypatch.setattr(CV, 'resolve_env_prefix', lambda s, k: 'COUPANG_TEST_NONE')
    monkeypatch.setattr(CV, '_load_credentials', lambda prefix: None)
    did = _draft(client)
    row = _coupang_row(client.post(f'/bulk/api/drafts/{did}/preflight',
                                   json={'markets': ['coupang'],
                                         'category_codes': {'coupang': '63955'}}))
    assert row['status'] == 'missing'
    assert '계정정보' in row['reason']


def test_사전점검_저장값이_있으면_ready_이고_caveat_이_사라진다(client, session, monkeypatch):
    """저장돼 있는데도 「화면이 안 보냄」 caveat 을 계속 띄우면 거짓 안내다."""
    import lemouton.registration.coupang_vendor as CV
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        CV.save_vendor(s, PREFIX, **FULL)
        s.commit()
    finally:
        s.close()

    class _C:
        vendor_id = "A00012345"

    monkeypatch.setattr(CV, 'resolve_env_prefix', lambda s, k: PREFIX)
    monkeypatch.setattr(CV, '_load_credentials', lambda prefix: _C())

    did = _draft(client)
    row = _coupang_row(client.post(f'/bulk/api/drafts/{did}/preflight',
                                   json={'markets': ['coupang'],
                                         'category_codes': {'coupang': '63955'}}))
    assert row['status'] == 'ready', row['reason']
    joined = ' '.join(row['caveats'])
    assert '보내지 않아' not in joined      # 옛 caveat 이 남아 있으면 안 된다


def test_사전점검_body_vendor_가_오면_그게_우선(client, monkeypatch):
    """기존 계약 유지 — 화면이 직접 보내면 저장값을 덮는다."""
    import lemouton.registration.coupang_vendor as CV
    monkeypatch.setattr(CV, 'resolve_env_prefix', lambda s, k: 'COUPANG_TEST_NONE')
    monkeypatch.setattr(CV, '_load_credentials', lambda prefix: None)
    did = _draft(client)
    row = _coupang_row(client.post(f'/bulk/api/drafts/{did}/preflight',
                                   json={'markets': ['coupang'],
                                         'category_codes': {'coupang': '63955'},
                                         'vendor': {'vendor_id': 'A00099999', **FULL}}))
    assert row['status'] == 'ready', row['reason']


def test_등록_라우트가_저장값을_주입한다(client, monkeypatch):
    """등록 화면이 vendor 를 안 보내도 계정 저장값으로 컴파일이 통과해야 한다.

    ★ 게이트(LIVE_REGISTER_ARMED)는 꺼진 채로 둔다 — 통과 증거는 「컴파일 실패가
      아니라 게이트에 막혔다」는 것이다(마켓 호출 0).
    """
    import lemouton.registration.coupang_vendor as CV
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        CV.save_vendor(s, PREFIX, **FULL)
        s.commit()
    finally:
        s.close()

    class _C:
        vendor_id = "A00012345"

    monkeypatch.setattr(CV, 'resolve_env_prefix', lambda s, k: PREFIX)
    monkeypatch.setattr(CV, '_load_credentials', lambda prefix: _C())

    did = _draft(client)
    j = client.post(f'/bulk/api/drafts/{did}/register/coupang',
                    json={'category_code': '63955'}).get_json()
    assert j['ok'] is False
    assert j.get('blocked') is True                 # 게이트에 막힘 = 컴파일 통과
    assert 'vendorId' not in (j.get('error') or '')  # vendorId 누락으로 죽지 않았다


def test_등록_저장값이_없으면_계정정보를_저장하라고_말한다(client, monkeypatch):
    import lemouton.registration.coupang_vendor as CV
    monkeypatch.setattr(CV, 'resolve_env_prefix', lambda s, k: 'COUPANG_TEST_NONE')
    monkeypatch.setattr(CV, '_load_credentials', lambda prefix: None)
    did = _draft(client)
    j = client.post(f'/bulk/api/drafts/{did}/register/coupang',
                    json={'category_code': '63955'}).get_json()
    assert j['ok'] is False
    assert '계정정보' in (j.get('error') or '')


# ── 화면 ────────────────────────────────────────────────────────

def test_설정_탭에_쿠팡_계정정보_카드가_있다(client):
    html = client.get('/bulk/?tab=settings').get_data(as_text=True)
    assert 'cpv-root' in html
    assert '쿠팡 계정정보' in html


# ══ 「default 계정」 정의 통일 (2026-07-23 리뷰 I1·I2) ══════════════════════
#  전에는 세 곳이 서로 다른 계정을 가리켰다 —
#    ① 설정 카드 기본선택: accounts[0] (비활성도 포함)
#    ② resolve_env_prefix: 첫 **활성** 계정
#    ③ 실제 전송 클라이언트: 무접두사 COUPANG_ACCESS_KEY
#  계정이 2개 이상이면 「payload 는 A 계정, 서명은 B 계정」이 난다 = 남의 반품지로 등록.

def test_설정_조회가_지금_등록에_쓰이는_계정을_알려준다(client):
    """화면이 기본 선택·배지를 이 값 하나로 그린다 — accounts[0] 추측 금지."""
    from shared.db import SessionLocal
    from lemouton.registration import coupang_vendor as CV
    j = client.get('/bulk/api/settings/coupang-vendor').get_json()
    assert j['ok'] is True
    s = SessionLocal()
    try:
        assert j['active_env_prefix'] == CV.resolve_env_prefix(s, 'default')
    finally:
        s.close()


def test_등록에_쓰이는_계정만_in_use_로_표시된다(client):
    j = client.get('/bulk/api/settings/coupang-vendor').get_json()
    active = j['active_env_prefix']
    for a in j['accounts']:
        assert a['in_use'] is (a['env_prefix'] == active), a['env_prefix']
    assert sum(1 for a in j['accounts'] if a['in_use']) <= 1


def test_비활성_계정은_등록에_안_쓰인다고_표시(client, session):
    """비활성 계정을 목록에서 지우면 저장값이 사라진 것처럼 보인다 — 표시로 구분한다."""
    from lemouton.sourcing.models_v2 import UploadAccount
    from shared.db import SessionLocal
    s = SessionLocal()
    acct = UploadAccount(account_key="테스트_쿠팡_M4_OFF", display_name="꺼진 쿠팡",
                         market="coupang", env_prefix="COUPANG_TEST_OFF", is_active=False)
    s.add(acct)
    s.commit()
    try:
        j = client.get('/bulk/api/settings/coupang-vendor').get_json()
        row = [a for a in j['accounts'] if a['env_prefix'] == 'COUPANG_TEST_OFF'][0]
        assert row['in_use'] is False
        assert row['is_active'] is False
    finally:
        s.delete(s.get(UploadAccount, acct.id))
        s.commit()
        s.close()


def test_비어_있는_칸_이름을_화면에_돌려준다(client):
    """부분 저장이면 「무엇이 비었는지」를 이름으로 말해야 한다(리뷰 C1)."""
    client.post('/bulk/api/settings/coupang-vendor',
                json={'env_prefix': PREFIX, 'vendor_user_id': 'wing_only'})
    j = client.get('/bulk/api/settings/coupang-vendor').get_json()
    row = [a for a in j['accounts'] if a['env_prefix'] == PREFIX][0]
    assert row['complete'] is False
    assert '반품지 코드' in row['missing']
    assert '출고지 코드' in row['missing']


def test_전부_저장하면_complete_이고_missing_이_비어_있다(client):
    client.post('/bulk/api/settings/coupang-vendor', json={'env_prefix': PREFIX, **FULL})
    j = client.get('/bulk/api/settings/coupang-vendor').get_json()
    row = [a for a in j['accounts'] if a['env_prefix'] == PREFIX][0]
    assert row['complete'] is True
    assert row['missing'] == []


def test_부분저장이면_사전점검이_ready_가_아니라_빈칸_이름을_댄다(client, monkeypatch):
    """예전엔 vendor_user_id 한 칸만 저장해도 ready·caveat 없음이었다."""
    import lemouton.registration.coupang_vendor as CV
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        CV.save_vendor(s, PREFIX, vendor_user_id='wing_only')
        s.commit()
    finally:
        s.close()

    class _C:
        vendor_id = "A00012345"

    monkeypatch.setattr(CV, 'resolve_env_prefix', lambda s, k: PREFIX)
    monkeypatch.setattr(CV, '_load_credentials', lambda prefix: _C())

    did = _draft(client)
    row = _coupang_row(client.post(f'/bulk/api/drafts/{did}/preflight',
                                   json={'markets': ['coupang'],
                                         'category_codes': {'coupang': '63955'}}))
    assert row['status'] == 'missing', row
    assert '반품지 주소' in row['reason']
    assert '출고지 코드' in row['reason']


# ── payload 계정 ≠ 전송 계정이면 등록을 막는다 (리뷰 I2) ────────────────────

def test_전송계정과_payload_판매자ID가_다르면_전송_전에_막는다(monkeypatch):
    """서명은 B 계정, payload 는 A 계정 — 남의 셀러 반품지로 등록되는 경로."""
    from lemouton.registration import service as SV
    from shared.platforms import COUPANG
    monkeypatch.setitem(COUPANG, 'vendor_id', 'A00099999')
    with pytest.raises(Exception) as e:
        SV._send_live('coupang', {'vendorId': 'A00012345'})
    assert '계정' in str(e.value)


def test_전송계정의_판매자ID를_모르면_막는다(monkeypatch):
    from lemouton.registration import service as SV
    from shared.platforms import COUPANG
    monkeypatch.setitem(COUPANG, 'vendor_id', '')
    with pytest.raises(Exception) as e:
        SV._send_live('coupang', {'vendorId': 'A00012345'})
    assert '계정' in str(e.value)


def test_같은_판매자ID면_그대로_전송한다(monkeypatch):
    from lemouton.registration import service as SV
    from shared.platforms import COUPANG
    import shared.platforms.coupang.products as P
    monkeypatch.setitem(COUPANG, 'vendor_id', 'A00012345')
    monkeypatch.setattr(P, 'create_product', lambda payload: 777)
    assert SV._send_live('coupang', {'vendorId': 'A00012345'}) == {'data': 777}


# ── 「불러오기」 클라이언트 폴백 제거 (리뷰 I4) ──────────────────────────────

def test_계정_클라이언트를_못_만들면_기본계정으로_눙치지_않는다(monkeypatch):
    """폴백하면 **남의 계정 키로 서명해** 다른 셀러의 출고지를 보여주게 된다."""
    import webapp.routes.bulk.settings_tab as ST
    import lemouton.uploader.market_fetch as MF
    monkeypatch.setattr(MF, '_coupang_client', lambda prefix: None)
    with pytest.raises(Exception):
        ST._coupang_client_for('COUPANG_TEST_M4')


# ── 「불러오기」 응답 경합 (리뷰 I3) ─────────────────────────────────────────

def test_불러오기가_계정_전환_경합을_버린다(client):
    """늦게 온 A 계정 응답이 B 폼에 그려지면 **A 반품지가 B 계정으로 저장**된다."""
    html = client.get('/bulk/?tab=settings').get_data(as_text=True)
    assert 'forPrefix' in html, '요청 시점 계정을 캡처하지 않는다'
    assert 'fetching' in html, 'fetch 중 select 를 잠그지 않는다'


# ══ 조회 경로·구현체 단일화 (2026-07-23 리뷰 M2·M3) ═════════════════════════

def test_조회_경로는_v2_providers_로_고정된다():
    """지도의 example_endpoint 는 `/v5/providers/…` 로 적혀 있다(쿠팡 문서 자체의 불일치).

    서명은 **path** 로 만들어지므로 그 오타를 따라가면 인증이 깨진다 — 다른 쿠팡 API 도
    전부 `/v2/providers/` 다. 채택을 테스트로 못 박는다.
    """
    from shared.platforms.coupang import logistics as L
    assert L.RETURN_CENTERS_PATH.startswith('/v2/providers/')
    assert L.OUTBOUND_PLACES_PATH.startswith('/v2/providers/')
    assert '/v5/providers/' not in L.RETURN_CENTERS_PATH

    c = _FakeClient({'returnShippingCenters': _RETURN_CENTERS})
    L.list_return_centers('A00012345', client=c)
    assert c.calls[0][1].startswith('/v2/providers/')      # 실제로 그 path 로 부른다


def test_반품지_출고지_구현체는_logistics_하나뿐이다():
    """shipping.py 의 두 번째 구현체는 없는 설정키를 읽어 KeyError 로 죽는 죽은 코드였다.

    두 벌이면 나중에 죽은 쪽을 고쳐 놓고 「고쳤는데 안 바뀐다」가 난다.
    """
    from shared.platforms.coupang import shipping
    assert not hasattr(shipping, 'list_return_centers')
    assert not hasattr(shipping, 'list_outbound_places')
    # 실제로 쓰이는 택배사 코드표는 그대로 남아 있어야 한다(invoice_send.py 가 쓴다).
    assert shipping.DELIVERY_COMPANY_CODES['CJ대한통운'] == 'CJGLS'

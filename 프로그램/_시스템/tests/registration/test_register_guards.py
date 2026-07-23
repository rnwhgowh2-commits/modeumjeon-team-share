# -*- coding: utf-8 -*-
"""[2026-07-23 코드리뷰 C1·C2·I2·I1] 등록 경로의 「같은 상품 두 번 올리기」 차단 4종.

이 파일이 고정하는 것 (전부 돈이 걸린 경로다):

  C1 이미 등록된 마켓은 **다시 부르지 않는다.**
     정상 워크플로가 그대로 사고였다 — 6마켓 중 3개 성공·3개 값부족 → 사장님이 빠진
     값을 채우고 「다시 점검」 → 6개가 전부 `ready` 로 나오고 화면이 **미리 체크**까지
     해 준다 → 한 번 누르면 이미 팔리고 있는 3개가 또 올라간다. 장부(ProductDraftMarket)
     에 `status='ok'` + 상품번호가 있으면 그게 「이미 올라가 있다」의 증거다.

  C2 회수된 좀비 스레드는 **다음 마켓을 부르지 않는다.**
     스테일 회수(새 POST)로 job_id 가 바뀌면 옛 스레드의 상태 쓰기는 거부된다. 그런데
     그 거부를 무시하고 계속 돌면 '쓰기만' 막히고 '마켓 호출'은 계속돼, 두 스레드가
     같은 드래프트를 같은 마켓에 동시에 올린다. 쓰기 거부 = 중단 신호다.

  I2 전송 중 끊긴 것을 **「실패」라고 단정하지 않는다.**
     요청이 소켓을 떠난 뒤 끊기면 마켓에는 상품이 만들어져 있을 수 있다(유령 상품).
     죽은 스레드 경로와 **같은 문구·같은 확인 수단**으로 「확인 필요」라고 말한다.

  I1 「마켓에서 확인」이 **있는 유령을 「없다」고 답하지 않는다.**
     롯데온 목록은 1페이지 100행인데 카탈로그는 13,883건이다 — 조회기간 없이 1페이지만
     보고 「0건」이라 답하면 그게 거짓 답이고, 그 답을 믿고 다시 누르면 곧 중복 등록이다.

★ 실등록은 절대 하지 않는다 — LIVE_REGISTER_ARMED 는 꺼둔 채, 마켓 호출 계층
  (register_draft·_send)은 전부 monkeypatch 로만 다룬다.
"""
import datetime
import json
import threading
import time

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('LIVE_REGISTER_ARMED', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


ALL_CODES = {
    'smartstore': '50000167', 'coupang': '63955',
    'auction': '00120005002000000000/37500700',
    'gmarket': '00120005002100000000/300006243',
    'eleven11': '1011634', 'lotteon': 'LO2727500650',
}

#: 쿠팡 계정정보 9키가 **전부** 찬 값 (test_register_many_route.py 와 같은 재료).
_FULL_VENDOR = {
    'vendor_id': 'A00123456', 'vendor_user_id': 'wing_login',
    'return_center_code': '1000557004', 'return_charge_name': '르무통 반품지',
    'return_zip': '06236', 'return_address': '서울시 강남구',
    'return_address_detail': '1층', 'return_phone': '02-111-1111',
    'outbound_place_code': '1111222',
}

_MADE = []      # 이 파일이 만든 draft_id — 실행상태·장부 행을 정확히 이것만 지운다.


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        ProductDraftRegisterRun, ProductDraftMarket)
    s = SessionLocal()
    try:
        for did in _MADE:
            for row in s.query(ProductDraftRegisterRun).filter_by(draft_id=did).all():
                s.delete(row)
            for row in s.query(ProductDraftMarket).filter_by(draft_id=did).all():
                s.delete(row)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE.clear()


def _complete(client, **over):
    """6마켓 예비 컴파일을 통과하는 완결 드래프트 1건."""
    body = {
        'name': '테스트 자켓(중복차단)', 'brand': '테스트브랜드', 'sale_price': 39000,
        'stock_quantity': 7,
        'notice_type': 'WEAR',
        'notice': {
            'material': '면 100%', 'color': '블랙', 'size': 'M / L',
            'manufacturer': '테스트제조', 'caution': '단독세탁',
            'warranty_policy': '구매일로부터 1년',
            'after_service_director': '홍길동 010-1234-5678',
        },
        'images': ['https://example.com/main.jpg'],
        'detail_html': '<p>상세</p>',
        'delivery_fee': '3000', 'return_fee': '5000',
        'after_service_phone': '010-1234-5678',
        'after_service_guide': '평일 09-18시',
    }
    body.update(over)
    did = client.post('/bulk/api/drafts', json=body).get_json()['draft_id']
    _MADE.append(did)
    return did


def _seed_ledger(did, market, *, status='ok', pid='SS-1234', account_key='default'):
    """장부(ProductDraftMarket)에 등록 결과 1행을 심는다 = 「이미 올라가 있다」의 증거."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket
    s = SessionLocal()
    try:
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market=market, account_key=account_key).first())
        if row is None:
            row = ProductDraftMarket(draft_id=did, market=market,
                                     account_key=account_key)
            s.add(row)
        row.status = status
        row.market_product_id = pid
        s.commit()
    finally:
        s.close()


def _ledger_rows(did):
    """장부(ProductDraftMarket) 를 (마켓, 계정키, 상태) 로 — 「어느 계정으로 적혔나」 증명용."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket
    s = SessionLocal()
    try:
        rows = (s.query(ProductDraftMarket).filter_by(draft_id=did)
                .order_by(ProductDraftMarket.id).all())
        return [(r.market, r.account_key, r.status) for r in rows]
    finally:
        s.close()


@pytest.fixture
def accounts():
    """업로드 계정을 심는다(순서 = 첫 활성 계정 판정 순서) → 끝나면 지운다.

    ★ 이 fixture 가 있어야 「default = 첫 활성 계정」이라는 **전송 계층의 해석 규칙**을
      테스트가 그대로 재현할 수 있다(send_more._env_prefix 와 같은 규칙).
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    made = []

    def _add(market, keys):
        s = SessionLocal()
        try:
            for k in keys:
                s.add(UploadAccount(account_key=k, display_name=k, market=market,
                                    env_prefix=f'{market.upper()}_{k.upper()}',
                                    is_active=True))
                made.append(k)
            s.commit()
        finally:
            s.close()

    yield _add

    s = SessionLocal()
    try:
        for k in made:
            row = s.query(UploadAccount).filter_by(account_key=k).first()
            if row is not None:
                s.delete(row)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _set_ledger_error(did, market, code, message, account_key='default'):
    """장부 행의 error_code/error_message 를 심는다(문구 분기의 재료)."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket
    s = SessionLocal()
    try:
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market=market, account_key=account_key).first())
        row.error_code, row.error_message = code, message
        s.commit()
    finally:
        s.close()


def _status(client, did):
    return client.get(f'/bulk/api/drafts/{did}/register/status').get_json()


def _wait_until(cond, timeout=8.0, step=0.05):
    waited = 0.0
    while not cond() and waited < timeout:
        time.sleep(step)
        waited += step
    return cond()


def _run_row(did):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        return s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
    finally:
        s.close()


def _spy_register(monkeypatch, gate=None, ledger=None):
    """register_draft 를 기록기로 갈아끼운다 → 어느 마켓에 호출이 나갔는지 증명용.

    ledger: {market: (status, error_code, error_message)} 를 주면 진짜 register_draft
        처럼 장부 행까지 남긴다(결과행의 error_code 는 장부에서 읽어 온다).
    """
    calls = []

    def fake(session, draft_id, market, *, category_code, vendor=None,
             account_key='default', **kw):
        calls.append(market)
        if gate and market == gate['market']:
            gate['entered'].set()
            gate['release'].wait(timeout=8)
        led = (ledger or {}).get(market)
        if led is not None:
            from lemouton.registration.models import ProductDraftMarket
            row = (session.query(ProductDraftMarket)
                   .filter_by(draft_id=draft_id, market=market,
                              account_key=account_key).first())
            if row is None:
                row = ProductDraftMarket(draft_id=draft_id, market=market,
                                         account_key=account_key)
                session.add(row)
            row.status, row.error_code, row.error_message = led[0], led[1], led[2]
            # 4번째 항목 = 아는 상품번호(PARTIAL 처럼 상품이 만들어진 실패).
            if len(led) > 3:
                row.market_product_id = led[3]
            session.commit()
            return {'ok': False, 'market_product_id': (led[3] if len(led) > 3 else None),
                    'error': led[2]}
        # 성공도 진짜 register_draft 처럼 **장부에 남긴다** — 어느 계정 키로 적히는지가
        # C-1(별칭 구멍)의 증거라, 여기서 안 적으면 그 증거를 볼 수 없다.
        from lemouton.registration.models import ProductDraftMarket
        row = (session.query(ProductDraftMarket)
               .filter_by(draft_id=draft_id, market=market,
                          account_key=account_key).first())
        if row is None:
            row = ProductDraftMarket(draft_id=draft_id, market=market,
                                     account_key=account_key)
            session.add(row)
        row.status, row.market_product_id = 'ok', f'{market}-PID'
        session.commit()
        return {'ok': True, 'market_product_id': f'{market}-PID',
                'error': None, 'excluded': []}

    import webapp.routes.bulk.drafts as D
    monkeypatch.setattr(D, 'register_draft', fake)
    return calls


# ══════════════════════════════════════════════════════════════════════════
#  C1 — 이미 등록된 마켓을 또 부르지 않는다
# ══════════════════════════════════════════════════════════════════════════

def test_이미_등록된_마켓은_점검이_registered로_잠근다(client):
    """★ 화면이 미리 체크해 주는 그 자리를 막는 고정.

    `ready` 로 돌려주면 화면은 체크박스를 켠 채 준다 — 한 번 누르면 이미 팔리는
    상품이 또 올라간다. 상태 자체가 달라야(=registered) 잠기고 체크가 꺼진다.
    """
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    body = client.post(f'/bulk/api/drafts/{did}/preflight',
                       json={'markets': ['smartstore', 'eleven11'],
                             'category_codes': ALL_CODES}).get_json()
    rows = {r['market']: r for r in body['rows']}
    assert rows['smartstore']['status'] == 'registered', rows['smartstore']
    assert rows['smartstore']['market_product_id'] == 'SS-777'
    assert '이미 등록' in rows['smartstore']['reason']
    assert 'SS-777' in rows['smartstore']['reason']       # 상품번호를 그대로 보여준다
    assert rows['eleven11']['status'] == 'ready'          # 나머지 마켓은 그대로


def test_이미_등록된_마켓에는_등록_호출이_0회다(client, monkeypatch):
    """★ 서버 가드 — 누가 markets 를 직접 POST 해도 버텨야 한다(화면은 그 다음)."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore', 'eleven11'],
                          'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])

    assert calls == ['eleven11'], calls        # 스스는 부르지 않았다
    rows = {x['market']: x for x in _status(client, did)['rows']}
    assert rows['smartstore']['status'] == 'already'
    assert rows['smartstore']['market_product_id'] == 'SS-777'
    assert rows['smartstore']['error_code'] == 'ALREADY_REGISTERED'
    assert rows['eleven11']['status'] == 'ok'
    assert _status(client, did)['summary']['already'] == 1


def test_다시_올리기를_켜야만_다시_부른다(client, monkeypatch):
    """다시 올려야 하는 경우의 **명시적 opt-in** — 기본은 꺼져 있다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    # 점검부터 ready 로 풀린다(화면이 체크할 수 있게).
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['smartstore'], 'category_codes': ALL_CODES,
                            'reregister': ['smartstore']}).get_json()
    assert pre['rows'][0]['status'] == 'ready', pre['rows'][0]

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES,
                          'reregister': ['smartstore']})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['smartstore'], calls


def test_다시_올리기는_켠_마켓에만_적용된다(client, monkeypatch):
    """opt-in 은 마켓 단위다 — 하나 켰다고 나머지까지 풀리면 그게 사고다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')
    _seed_ledger(did, 'eleven11', pid='11-888')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore', 'eleven11'],
                          'category_codes': ALL_CODES,
                          'reregister': ['eleven11']})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['eleven11'], calls
    rows = {x['market']: x for x in _status(client, did)['rows']}
    assert rows['smartstore']['status'] == 'already'


def test_실패한_장부행은_잠그지_않는다(client, monkeypatch):
    """실패 뒤 재시도는 막지 않는다 — 막는 근거는 「성공 + 상품번호」뿐이다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', status='failed', pid=None)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['smartstore'], calls


def test_진짜_다른_계정이면_다른_상품이다(client, monkeypatch, accounts):
    """장부 키는 (드래프트, 마켓, **물리 계정**) 이다 — A계정 등록이 B계정 등록을 막으면 안 된다.

    ★ 「다른 계정」의 근거는 **타이핑한 글자**가 아니라 실제로 전송될 계정이다
      (아래 별칭 테스트가 그 차이를 고정한다).
    """
    accounts('lotteon', ['acctA', 'acctB'])
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'lotteon', pid='LO-111', account_key='acctA')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES,
                          'account_keys': {'lotteon': 'acctB'}})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['lotteon'], calls


# ── C-1 [2026-07-23 재리뷰] 「default」 별칭으로 가드가 비켜가던 구멍 ──────────
#
# 장부 키는 사장님이 **타이핑한 글자**였는데, 실제 전송 대상은 send_more._env_prefix 가
# 해석한 **첫 활성 계정**이었다. 같은 물리 계정인데 키 문자열이 달라 가드가 못 걸었다:
#   ① 계정칸에 'acctA'(=첫 활성) 를 넣고 등록 → 장부 ('lotteon','acctA')=ok
#   ② 새로고침하면 화면 상태(regPanel.keys)가 비어 계정칸이 빈칸 → 서버는 'default' 로
#      조회 → 히트 없음 → ready + 미리 체크 → 한 번 누르면 **같은 계정에 또** 올라간다.
# 그래서 장부에 쓰고 읽을 때 account_key 를 **해석된 물리 계정**으로 정규화한다.

def test_계정칸을_비워도_같은_계정이면_막힌다(client, monkeypatch, accounts):
    """★ 재현 ②방향 — 명시(acctA)로 등록해 두고 빈칸(=default)으로 다시 누르는 동선."""
    accounts('lotteon', ['acctA', 'acctB'])          # acctA 가 첫 활성
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'lotteon', pid='LO-111', account_key='acctA')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES})
    assert r.status_code == 202                       # account_keys 없음 = 계정칸 빈칸
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == [], f'빈칸(default)이 같은 계정을 비켜갔다 — {calls}'
    row = _status(client, did)['rows'][0]
    assert row['status'] == 'already'
    assert row['market_product_id'] == 'LO-111'


def test_계정칸을_비우고_등록했어도_명시하면_막힌다(client, monkeypatch, accounts):
    """★ 재현 ①의 반대 방향 — 빈칸으로 등록해 두고 그 계정을 명시해 다시 누르는 동선."""
    accounts('lotteon', ['acctA', 'acctB'])
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'lotteon', pid='LO-111', account_key='default')   # 옛 장부 행

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES,
                          'account_keys': {'lotteon': 'acctA'}})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == [], f"옛 'default' 장부 행을 놓쳤다 — {calls}"


def test_장부에는_해석된_계정으로_적는다(client, monkeypatch, accounts):
    """기록과 전송이 같은 계정을 가리켜야 한다 — 빈칸으로 등록해도 장부엔 실계정이 남는다."""
    accounts('lotteon', ['acctA', 'acctB'])
    _spy_register(monkeypatch)
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    row = _status(client, did)['rows'][0]
    assert row['account_key'] == 'acctA', row      # 'default' 가 아니라 실제 계정
    assert _ledger_rows(did) == [('lotteon', 'acctA', 'ok')], _ledger_rows(did)


def test_계정이_하나도_없으면_default_그대로다(client, monkeypatch):
    """계정 표가 비면 전송은 전역 기본 클라이언트로 나간다 — 그때의 이름은 'default' 다.
    없는 계정 이름을 지어내면 그게 거짓 장부다."""
    _spy_register(monkeypatch)
    did = _complete(client)
    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert _ledger_rows(did) == [('eleven11', 'default', 'ok')], _ledger_rows(did)


def test_단수_라우트도_이미_등록된_마켓을_다시_부르지_않는다(client, monkeypatch):
    """가드는 판정기(_register_one)에 있다 — 단수·복수 라우트가 같은 답을 낸다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    body = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                       json={'category_code': ALL_CODES['smartstore']}).get_json()
    assert calls == [], calls
    assert body['ok'] is False
    assert body['already'] is True
    assert body['market_product_id'] == 'SS-777'

    # opt-in 하면 그때만 부른다.
    client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                json={'category_code': ALL_CODES['smartstore'], 'reregister': True})
    assert calls == ['smartstore'], calls


# ══════════════════════════════════════════════════════════════════════════
#  C2 — 회수된 좀비 스레드는 다음 마켓을 부르지 않는다
# ══════════════════════════════════════════════════════════════════════════

def _steal_run(did, new_job='newjob'):
    """스테일 회수를 흉내낸다 — 새 POST 가 이 드래프트의 실행을 가져간 상태."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        row = s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
        row.job_id = new_job
        row.done_count = 0
        row.result_json = None
        s.commit()
    finally:
        s.close()


def test_회수된_옛_스레드는_다음_마켓을_부르지_않는다(client, monkeypatch):
    """★ C2 의 핵심 — 쓰기만 막고 호출은 계속하면 두 스레드가 같은 마켓에 동시 등록한다.

    상태 쓰기 거부(job_id 불일치)는 「너는 더 이상 이 실행의 주인이 아니다」는 뜻이다.
    다음 마켓을 부르기 전에 멈춰야 한다.
    """
    gate = {'market': 'smartstore', 'entered': threading.Event(),
            'release': threading.Event()}
    calls = _spy_register(monkeypatch, gate=gate)
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore', 'eleven11', 'lotteon'],
                          'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert gate['entered'].wait(timeout=8)

    _steal_run(did)                 # 그 사이 새 POST 가 실행을 회수했다
    gate['release'].set()

    # 옛 스레드가 살아 있었다면 수십 ms 안에 두 번째 마켓을 부른다.
    grew = _wait_until(lambda: len(calls) >= 2, timeout=1.5)
    assert grew is False, f'회수된 옛 스레드가 마켓을 더 불렀다 — {calls}'
    assert calls == ['smartstore'], calls

    # 새 실행의 상태를 덮어쓰지도 않았다.
    row = _run_row(did)
    assert row.job_id == 'newjob'
    assert (row.done_count or 0) == 0
    assert row.result_json is None
    assert row.finished_at is None, '남의 실행을 끝났다고 표시했다'


# ══════════════════════════════════════════════════════════════════════════
#  I2 — 전송이 끊긴 것을 「실패」라고 단정하지 않는다
# ══════════════════════════════════════════════════════════════════════════

def test_service는_전송예외를_CALL로_남긴다(client, monkeypatch):
    """이 아래 매핑이 기대는 계약 — 전송 중 예외는 장부에 error_code='CALL' 로 남는다."""
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)

    def boom(market, spec):
        raise RuntimeError('ReadTimeout — 응답을 받지 못했습니다')

    s = SessionLocal()
    try:
        r = register_draft(s, did, 'eleven11',
                           category_code=ALL_CODES['eleven11'], _send=boom)
        assert r['ok'] is False
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='eleven11',
                          account_key='default').first())
        assert row.error_code == 'CALL', row.error_code
    finally:
        s.close()


def test_전송이_끊긴_결과는_실패가_아니라_확인필요다(client, monkeypatch):
    """★ 요청이 소켓을 떠난 뒤 끊기면 상품은 올라가 있을 수 있다(유령 상품).

    죽은 스레드 경로와 **같은 문구**로 말하고, 확인 수단(lookup)까지 같이 준다.
    """
    calls = _spy_register(monkeypatch, ledger={
        'lotteon': ('failed', 'CALL', 'ReadTimeout — 응답을 받지 못했습니다')})
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['lotteon']

    body = _status(client, did)
    row = body['rows'][0]
    assert row['status'] == 'unknown', row
    assert row['error_code'] == 'CALL'
    assert row['lookup_supported'] is True            # 롯데온은 이름으로 찾을 수 있다
    assert '올라갔는지 모릅니다' in (row['error'] or ''), row
    assert 'ReadTimeout' in (row['error'] or ''), '전송 오류 원문을 버렸다'
    for banned in ('실패했습니다', '성공했습니다', '등록되었습니다'):
        assert banned not in (row['error'] or ''), row
    assert '마켓에서 상품 존재 확인 필요' in row['notes']
    assert body['summary']['unknown'] == 1
    assert body['summary']['failed'] == 0, '거짓 실패가 요약에 잡혔다'


def test_전송끊김이_아닌_실패는_그대로_실패다(client, monkeypatch):
    """우리 쪽에서 확정된 실패(컴파일 등)는 **부르기도 전에** 끝난 일이다.

    [3차리뷰 중요①] NO_PRODUCT_ID 는 더 이상 이 부류가 아니다 — 응답은 왔으니
    상품이 만들어졌을 수 있어 「확인 필요」다(그 고정은 아래 별도 테스트).
    """
    calls = _spy_register(monkeypatch, ledger={
        'eleven11': ('failed', 'COMPILE', '필수값이 비었습니다: 상세설명')})
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['eleven11']
    row = _status(client, did)['rows'][0]
    assert row['status'] == 'failed', row
    assert row['error_code'] == 'COMPILE'


# ══════════════════════════════════════════════════════════════════════════
#  I1 — 「마켓에서 확인」이 있는 유령을 「없다」고 답하지 않는다
#
#  롯데온 상품 목록 조회는 **1페이지 100행**이 상한이고, 이 계정 카탈로그는
#  dataCount 13,883 이다(지도 실측). 조회기간 없이 1페이지만 훑고 「0건」이라 답하면
#  실제로 올라간 유령을 「없다」고 말하는 것이다 — 사장님이 그걸 믿고 다시 누르면
#  그게 곧 중복 등록(C1 이 막으려는 바로 그 사고)이다.
#
#  지도 근거(marketplace_api_map.json · lotteon.product.list):
#    POST /v1/openapi/product/v1/product/list
#    필수 regStrtDttm·regEndDttm(YYYYMMDDHHMMSS 14자리) · pageNo(1부터) · rowsPerPage(MAX 100)
#
#  ★ 라이브 롯데온을 부르지 않는다 — list_products 를 monkeypatch 로 고정한다.
# ══════════════════════════════════════════════════════════════════════════

def _fake_lotteon(monkeypatch, pages):
    """롯데온 상품목록을 페이지별로 되돌려주는 가짜 — 호출 인자를 그대로 기록한다."""
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.lotteon.products as LP
    import webapp.routes.bulk.drafts as D

    seen = []
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'LOTTEON_MAIN')
    monkeypatch.setattr(MF, '_lotteon_client', lambda envp: object())

    def fake_list(*, client=None, page_no=1, rows_per_page=100,
                  reg_start=None, reg_end=None, **kw):
        seen.append({'page_no': page_no, 'rows_per_page': rows_per_page,
                     'reg_start': reg_start, 'reg_end': reg_end})
        if callable(pages):
            return pages(page_no)
        return pages[page_no - 1] if page_no <= len(pages) else []

    monkeypatch.setattr(LP, 'list_products', fake_list)
    return seen


def _filler(n, page):
    return [{'spdNo': f'LO{page}{i:03d}', 'spdNm': f'다른 상품 {page}-{i}'} for i in range(n)]


def test_롯데온_유령확인은_뒤_페이지에_있어도_찾는다(client, monkeypatch):
    """★ 1페이지(100행)만 보고 「0건」이라 답하던 거짓말을 막는 고정.

    카탈로그가 13,883건인데 100행만 훑으면, 방금 올라간 유령은 거의 언제나 못 본다.
    """
    seen = _fake_lotteon(monkeypatch, [
        _filler(100, 1),
        _filler(99, 2) + [{'spdNo': 'LO2729045338', 'spdNm': '유령확인 자켓 블랙'}],
        [],
    ])
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['ok'] is True
    assert [c['page_no'] for c in seen][:2] == [1, 2], seen   # 페이지를 넘겼다
    assert body['count'] == 1, body
    assert body['rows'][0]['code'] == 'LO2729045338'
    assert body['complete'] is True                            # 찾았으면 답이 확정이다


def test_롯데온_조회는_등록직후_구간을_KST_14자리로_준다(client, monkeypatch):
    """지도 실측: regStrtDttm/regEndDttm 은 **14자리**(8자리면 INVALID_INPUT).
    등록은 방금 일어난 일이라 최근 구간만 본다 — 1년치를 훑으면 상한에 먼저 걸린다.

    ★★ [재리뷰 I-A] 시간대를 **KST 로 못 박는다.** 라이브 컨테이너는 TZ 설정이 없어
      UTC 로 돈다 — naive `datetime.now()` 를 쓰면 창이 9시간 과거로 밀려
      [KST now-33h, KST now-9h] 가 되고, 방금 올라간 유령은 **언제나 창 밖**이다.
      (테스트도 같은 naive now() 로 비교하면 이 버그를 못 잡는다 — 그래서 KST 로 비교한다.)
    """
    seen = _fake_lotteon(monkeypatch, [[]])
    did = _complete(client, name='유령확인 자켓')
    client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon')

    call = seen[0]
    assert len(call['reg_start']) == 14 and call['reg_start'].isdigit(), call
    assert len(call['reg_end']) == 14 and call['reg_end'].isdigit(), call
    kst = datetime.timezone(datetime.timedelta(hours=9))
    now_kst = datetime.datetime.now(kst).replace(tzinfo=None)
    end = datetime.datetime.strptime(call['reg_end'], '%Y%m%d%H%M%S')
    start = datetime.datetime.strptime(call['reg_start'], '%Y%m%d%H%M%S')
    # 끝은 '지금'(KST)이어야 한다 — UTC 로 계산했다면 9시간 어긋나 여기서 걸린다.
    assert abs((now_kst - end).total_seconds()) < 300, (call, now_kst)
    import webapp.routes.bulk.drafts as D
    assert (end - start) == datetime.timedelta(days=D.LOOKUP_RECENT_DAYS), call
    assert call['rows_per_page'] == 100                        # 롯데온 상한


def test_상한에_걸리면_없다가_아니라_못_다_봤다로_답한다(client, monkeypatch):
    """무한 루프를 막는 상한은 필요하다 — 다만 상한에 걸린 사실을 숨기면 그게 거짓말이다."""
    import webapp.routes.bulk.drafts as D
    seen = _fake_lotteon(monkeypatch, lambda page: _filler(100, page))
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['ok'] is True
    assert body['count'] == 0
    assert len(seen) == D.LOOKUP_MAX_PAGES, seen               # 상한에서 멈춘다
    assert body['complete'] is False, '못 다 본 것을 다 봤다고 답했다'
    assert body['scanned'] == D.LOOKUP_MAX_PAGES * 100
    assert '확인한 범위' in body['note'], body['note']
    for banned in ('올라가지 않았습니다', '등록되지 않았습니다'):
        assert banned not in body['note'], body['note']


def test_끝까지_봤어도_확인한_범위_안에는_없다고만_말한다(client, monkeypatch):
    """0건은 「안 올라갔다」의 증명이 아니다 — 마켓 색인이 늦을 수 있다."""
    _fake_lotteon(monkeypatch, [_filler(7, 1)])
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['count'] == 0
    assert body['complete'] is True
    assert body['scanned'] == 7
    assert '확인한 범위' in body['note'], body['note']
    assert '판매자센터' in body['note'], body['note']           # 사람이 확인할 곳을 알려준다


def test_훑은_범위를_응답에_싣는다(client, monkeypatch):
    """「0건」이 「없다」인지 「거기까진 못 봤다」인지 구분할 근거를 화면에 준다."""
    _fake_lotteon(monkeypatch, [_filler(100, 1), _filler(5, 2)])
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['scanned'] == 105
    assert body['pages'] == 2
    assert '105' in body['scope'] and '2' in body['scope'], body['scope']


def test_11번가는_이름검색이라_훑은_범위가_검색결과다(client, monkeypatch):
    """마켓마다 확인 수단이 다르다 — 무엇으로 확인했는지를 그대로 말한다."""
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.eleven11.products as P11
    import webapp.routes.bulk.drafts as D

    did = _complete(client, name='유령확인 자켓')
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'ELEVEN11')
    monkeypatch.setattr(MF, '_eleven11_client', lambda envp: object())
    monkeypatch.setattr(P11, 'search_products',
                        lambda **kw: [{'prdNo': '777', 'prdNm': '유령확인 자켓'}])

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=eleven11').get_json()
    assert body['ok'] is True and body['count'] == 1
    assert body['scanned'] == 1
    assert '상품명' in body['scope'], body['scope']


# ══════════════════════════════════════════════════════════════════════════
#  C-2 [재리뷰] 실제로 만들어진 상품이 장부에 failed 로만 남으면 다음 클릭이 중복이다
#
#  가장 유령이 잘 생기는 경로가 하필 가드가 못 보던 경로였다:
#    send_more._register_esm — 상품은 이미 생성(goodsNo 확보)됐는데 옵션 부착이 실패해
#    판매중지로 회수한 뒤 예외 → service 가 status='failed'·상품번호 None 으로 적는다
#    → C1 가드 조건(status=='ok' and pid)에 안 걸린다 → 「다시 점검」하면 ready + 미리
#    체크로 돌아온다 → 한 번 누르면 같은 상품이 또 올라간다.
#
#  판정 근거를 장부에 두기로 한 이상 **장부가 불확실을 표현할 수 있어야** 가드가 성립한다.
#  → 장부 status='uncertain' 신설. 「등록됨」이 아니라 **「확인 전까지 잠금」**.
# ══════════════════════════════════════════════════════════════════════════

def test_상품번호를_아는_실패는_장부에_그_번호를_남긴다(client):
    """★ 옵션 부착 실패(ESM) — 상품은 만들어졌고 우리는 그 번호를 안다. 버리면 안 된다."""
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    from lemouton.registration.send_more import PartialRegisterError
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)

    def boom(market, spec):
        raise PartialRegisterError(
            'auction 상품(A12345)은 등록됐지만 옵션 부착에 실패했습니다 / '
            '상품은 판매중지로 내려두었습니다', product_id='A12345')

    s = SessionLocal()
    try:
        r = register_draft(s, did, 'auction',
                           category_code=ALL_CODES['auction'], _send=boom)
        assert r['ok'] is False
        assert r['market_product_id'] == 'A12345', '아는 상품번호를 결과에서 버렸다'
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='auction', account_key='default').first())
        assert row.market_product_id == 'A12345', '아는 상품번호를 장부에서 버렸다'
        assert row.status == 'uncertain', row.status
        assert row.error_code == 'PARTIAL'
    finally:
        s.close()


def test_불확실_장부행은_다음_점검에서_잠근다(client, monkeypatch):
    """★ C-2 의 핵심 — 결과표를 닫고 「다시 점검」해도 ready 로 돌아오면 안 된다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid='A12345')

    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['auction'], 'category_codes': ALL_CODES}).get_json()
    row = pre['rows'][0]
    assert row['status'] == 'uncertain', row      # registered 와 **다른** 상태
    assert row['market_product_id'] == 'A12345'
    assert '확인' in row['reason'], row['reason']

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['auction'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == [], f'불확실 장부행을 두고 마켓을 또 불렀다 — {calls}'
    out = _status(client, did)['rows'][0]
    assert out['status'] == 'uncertain'
    assert '마켓에서 상품 존재 확인 필요' in out['notes']


def test_상품번호를_모르는_불확실도_잠근다(client, monkeypatch):
    """전송 뒤 끊김(CALL)은 상품번호를 모른다 — 그래도 「확인 전까지」 잠근다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'lotteon', status='uncertain', pid=None)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == [], calls


def test_불확실도_다시_올리기로_풀린다(client, monkeypatch):
    """확인해 보니 안 올라갔더라 — 그때 사장님이 직접 푸는 문이 있어야 한다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid='A12345')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['auction'], 'category_codes': ALL_CODES,
                          'reregister': ['auction']})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['auction'], calls


def test_전송끊김은_장부에도_불확실로_남는다(client):
    """[I2 보강] 결과표만 unknown 이고 장부가 failed 면, 다음 점검이 ready 로 돌아온다."""
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)

    def boom(market, spec):
        raise RuntimeError('ReadTimeout — 응답을 받지 못했습니다')

    s = SessionLocal()
    try:
        register_draft(s, did, 'eleven11',
                       category_code=ALL_CODES['eleven11'], _send=boom)
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='eleven11', account_key='default').first())
        assert row.error_code == 'CALL'
        assert row.status == 'uncertain', row.status
    finally:
        s.close()


def test_상품관리_목록이_불확실을_실패로_뭉개지_않는다(client):
    """모순 금지 — 장부가 '불확실'인데 화면이 '실패'라고 하면 두 답이 갈린다."""
    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid='A12345')
    _seed_ledger(did, 'lotteon', status='failed', pid=None)

    body = client.get('/bulk/api/products').get_json()
    row = next(r for r in body['rows'] if r['id'] == did)
    assert row['failed'] == 1, row              # 실패는 롯데온 1건뿐
    assert row['uncertain'] == 1, row           # 불확실은 따로 센다
    assert body['counts'].get('uncertain', 0) >= 1


# ══════════════════════════════════════════════════════════════════════════
#  I-B [재리뷰] 「보내기 전 확정 실패」를 「올라갔는지 모른다」로 말하면 안 된다
#
#  거짓 실패를 없애다 **거짓 불확실**을 만들었다. 계정 없음·선행자원 없음·출고지 미등록·
#  본보기 조회 실패는 전부 **요청이 나가기 전** 확정 실패인데 「연결이 끊겼습니다 —
#  올라갔는지 모릅니다」로 떴다. 확인 수단도 없다.
#  ★ 「확인 필요」가 상시로 뜨면 진짜 유령 경고가 묻힌다 — 그게 이 절의 존재 이유다.
# ══════════════════════════════════════════════════════════════════════════

def test_보내기_전_실패는_확정_실패다(client):
    """PrereqError = 선행자원 수확 실패(상품 미생성) — 마켓에 아무것도 안 갔다."""
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    from lemouton.registration.models import ProductDraftMarket
    from lemouton.registration.send_more import PrereqError

    did = _complete(client)

    def boom(market, spec):
        raise PrereqError('11번가 출고지/반품지 주소를 못 얻었습니다 — 셀러오피스에서 확인해 주세요.')

    s = SessionLocal()
    try:
        r = register_draft(s, did, 'eleven11',
                           category_code=ALL_CODES['eleven11'], _send=boom)
        assert r['ok'] is False
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='eleven11', account_key='default').first())
        assert row.error_code == 'PREREQ', row.error_code
        assert row.status == 'failed', row.status      # 불확실이 아니다
    finally:
        s.close()


def test_보내기_전_실패는_화면에도_실패로_뜬다(client, monkeypatch):
    """확인할 수단도 없는 「확인 필요」를 띄우면 진짜 경고가 묻힌다."""
    calls = _spy_register(monkeypatch, ledger={
        'eleven11': ('failed', 'PREREQ', '11번가 출고지/반품지 주소를 못 얻었습니다')})
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['eleven11']
    body = _status(client, did)
    row = body['rows'][0]
    assert row['status'] == 'failed', row
    assert '올라갔는지 모릅니다' not in (row['error'] or ''), row
    assert body['summary']['unknown'] == 0


def test_쿠팡_계정불일치는_보내기_전_실패다(client):
    """payload 계정 != 전송 계정 — 호출 전에 막은 것이라 상품이 생겼을 리 없다."""
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft, CoupangAccountMismatch
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)

    def boom(market, body):
        raise CoupangAccountMismatch('등록 내용은 판매자 A 인데 실제 전송 계정은 B 입니다')

    s = SessionLocal()
    try:
        register_draft(s, did, 'coupang', category_code='63955',
                       vendor=_FULL_VENDOR, _send=boom)
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='coupang', account_key='default').first())
        assert row.error_code == 'PREREQ', row.error_code
        assert row.status == 'failed'
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════════════════
#  I-F [재리뷰] 「다시 올리기」가 이전 상품번호를 지운다
# ══════════════════════════════════════════════════════════════════════════

def test_다시_올리면_이전_상품번호를_원문에_남긴다(client):
    """지웠다고 믿고 다시 올렸는데 실제로 남아 있었으면 둘 다 살아 있다 —
    이전 번호를 잃으면 되돌릴 방법이 없다."""
    import json as _json
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)
    _seed_ledger(did, 'eleven11', pid='11-OLD')

    s = SessionLocal()
    try:
        register_draft(s, did, 'eleven11', category_code=ALL_CODES['eleven11'],
                       _send=lambda m, spec: {'product_id': '11-NEW', 'raw': {'ok': 1}})
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='eleven11', account_key='default').first())
        assert row.market_product_id == '11-NEW'
        saved = _json.loads(row.raw_json)
        assert saved['previous_market_product_id'] == '11-OLD', saved
        assert saved['raw'] == {'ok': 1}, saved     # 마켓 원문도 그대로 남는다
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════════════════
#  3차리뷰 — 「불확실은 장부에 남긴다」 규약을 **우회할 수 없게** 만든 것의 고정
#
#  진단: 치명 3건이 같은 뿌리였다. 규약이 복수 라우트의 정상 경로 한 갈래에만 배선돼
#  있어서, ①단수 라우트 ②이번 목록 밖 마켓 ③문구층이 그 밖에 있었다.
#  수정: 「죽은 실행을 회수했다」를 아는 유일한 지점(_claim_register_run)이 **그 트랜잭션
#  안에서 직접** 장부에 uncertain 을 남긴다 → 호출자가 무엇을 하든 규약이 지켜진다.
# ══════════════════════════════════════════════════════════════════════════

def _seed_dead_run(did, *, market, markets=None, account_key=None, minutes_ago=30,
                   running=True, error=None):
    """스레드가 그 마켓 처리 도중 죽은 상태 그대로.

    죽음의 두 모양을 **둘 다** 만들 수 있어야 한다(4차리뷰 중요①):
      ① running=True + 진행률 멈춤        (워커째 사망)
      ② running=False + error 남음         (예상 밖 예외로 끝남 — current_market 은 남는다)
    예전 헬퍼는 ①만 만들어서 ②의 구멍을 못 잡았다.
    """
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    old = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes_ago)
    s = SessionLocal()
    try:
        row = s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
        if row is None:
            row = ProductDraftRegisterRun(draft_id=did)
            s.add(row)
        row.job_id = 'deadjob'
        row.running = running
        row.started_at = old
        row.progress_at = old
        row.finished_at = None if running else old
        row.error = error
        row.current_market = market
        row.current_account_key = account_key
        row.markets_json = json.dumps(markets or [market])
        row.done_count = 0
        row.total_count = len(markets or [market])
        row.result_json = None
        s.commit()
    finally:
        s.close()


def test_치명1_스테일_회수_뒤_단수_등록도_그_마켓을_안_부른다(client, monkeypatch):
    """★ 재현된 사고: 복수 등록이 롯데온 호출 중 워커 사망 → 5분 뒤 **단수** 롯데온 등록
    → 옛 스레드는 아직 장부를 안 썼으니 가드 통과 → 롯데온에 상품 2개.

    단수 라우트는 `taken` 을 안 넘겨 회수 특례를 통째로 비켜갔다. 이제 회수 자체가
    장부에 남으므로 **호출자를 가리지 않는다.**
    """
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_dead_run(did, market='lotteon')

    body = client.post(f'/bulk/api/drafts/{did}/register/lotteon',
                       json={'category_code': ALL_CODES['lotteon']}).get_json()
    assert calls == [], f'회수 직후 단수 등록이 그 마켓을 또 불렀다 — {calls}'
    assert body['ok'] is False and body.get('uncertain') is True, body
    assert _ledger_rows(did) == [('lotteon', 'default', 'uncertain')], _ledger_rows(did)


def test_치명2_회수한_마켓이_이번_목록_밖이어도_장부에_남는다(client, monkeypatch):
    """★ 가장 현실적인 동선: 6마켓 등록이 롯데온에서 죽음 → 화면이 「롯데온 확인 필요」
    → **화면 말대로** 롯데온을 빼고 나머지만 재등록 → 예전엔 그 순간 불확실이 증발하고
    다음 점검에 초록·미리체크로 부활했다(= 화면이 시킨 대로 했더니 사고).
    """
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_dead_run(did, market='lotteon', markets=['lotteon', 'eleven11'])

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['eleven11'],       # 롯데온을 뺐다
                          'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['eleven11'], calls

    led = dict(((m, st) for m, _a, st in _ledger_rows(did)))
    assert led.get('lotteon') == 'uncertain', _ledger_rows(did)

    # 그 뒤 점검에서도 롯데온은 잠긴 채다(초록·미리체크로 부활하지 않는다).
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['lotteon'], 'category_codes': ALL_CODES}).get_json()
    assert pre['rows'][0]['status'] == 'uncertain', pre['rows'][0]


def test_회수한_마켓의_계정을_그대로_잠근다(client, monkeypatch, accounts):
    """장부 키는 (드래프트×마켓×계정) — 계정을 모른 채 남기면 그 계정 재등록이 안 잠긴다."""
    accounts('lotteon', ['acctA', 'acctB'])
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_dead_run(did, market='lotteon', account_key='acctB')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES,
                          'account_keys': {'lotteon': 'acctB'}})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == [], f'죽은 실행이 쓰던 그 계정으로 또 불렀다 — {calls}'
    assert ('lotteon', 'acctB', 'uncertain') in _ledger_rows(did), _ledger_rows(did)


def test_치명3_상품이_만들어진_실패에는_모릅니다를_쓰지_않는다(client, monkeypatch):
    """★ 상품번호를 찍어 놓고 「생겼는지 모릅니다」는 한 문장 안에서 자기모순이다.

    그 말을 들은 사람은 「못 찾겠으면 다시 올리자」로 간다 — 코드층에서 세운 방어를
    사람층에서 되돌리는 문구다.
    """
    calls = _spy_register(monkeypatch, ledger={
        'auction': ('uncertain', 'PARTIAL',
                    'auction 상품(A12345)은 등록됐지만 옵션 부착에 실패했습니다',
                    'A12345')})
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['auction'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['auction']

    row = _status(client, did)['rows'][0]
    assert row['status'] == 'unknown', row
    msg = row['error'] or ''
    assert '상품이 만들어졌습니다' in msg, msg
    assert 'A12345' in msg, msg
    for banned in ('모릅니다', '올라갔는지'):
        assert banned not in msg, f'확정 사실에 「{banned}」를 썼다 — {msg}'
    # 확인할 곳도 마켓별로 알려준다(옥션은 이름 조회 API 가 없어 버튼이 없다).
    assert 'ESM플러스' in msg, msg

    # 다음 점검 문구도 같은 규약(자기모순 금지).
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['auction'], 'category_codes': ALL_CODES}).get_json()
    reason = pre['rows'][0]['reason']
    assert '상품이 만들어졌습니다' in reason and 'A12345' in reason, reason
    assert '모릅니다' not in reason, reason


def test_상품번호를_모르는_불확실에는_모릅니다가_맞다(client, monkeypatch):
    """반대로 **정말 모르는** 경우까지 「만들어졌습니다」로 말하면 그게 거짓이다."""
    did = _complete(client)
    _seed_ledger(did, 'lotteon', status='uncertain', pid=None)
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['lotteon'], 'category_codes': ALL_CODES}).get_json()
    reason = pre['rows'][0]['reason']
    assert '아직 모릅니다' in reason, reason
    assert '만들어졌습니다' not in reason, reason


def test_중요1_상품ID를_못_받은_것은_확인_필요다(client, monkeypatch):
    """마켓이 응답은 줬는데 우리가 ID 를 못 찾은 경우 — 상품은 있는데 우리만 모를 수 있다."""
    calls = _spy_register(monkeypatch, ledger={
        'eleven11': ('uncertain', 'NO_PRODUCT_ID',
                     '마켓이 상품ID 를 주지 않았습니다 — 올라갔는지 모릅니다')})
    did = _complete(client)
    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    row = _status(client, did)['rows'][0]
    assert row['status'] == 'unknown', row
    assert row['lookup_supported'] is True

    # 그리고 장부가 잠갔으니 다시 눌러도 안 나간다.
    calls.clear()
    r2 = client.post(f'/bulk/api/drafts/{did}/register',
                     json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    assert r2.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == [], calls


def test_중요2_다시올리기_재실패에도_이전_상품번호가_남는다(client):
    """불확실(A) → 다시 올리기 → 새 상품 B 생성 후 또 실패. A 를 잃으면 옥션에 살아 있는
    A 를 영영 못 찾는다(I-F 의 취지를 정반대로 뒤집던 자리)."""
    import json as _json
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    from lemouton.registration.send_more import PartialRegisterError
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid='A-OLD')

    def boom(market, spec):
        raise PartialRegisterError('옵션 부착 실패', product_id='A-NEW')

    s = SessionLocal()
    try:
        register_draft(s, did, 'auction', category_code=ALL_CODES['auction'], _send=boom)
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='auction', account_key='default').first())
        assert row.market_product_id == 'A-NEW'
        saved = _json.loads(row.raw_json)
        assert saved['previous_market_product_id'] == 'A-OLD', saved
    finally:
        s.close()


def test_중요3_확인했더니_있더라를_장부에_넣을_수_있다(client, monkeypatch):
    """★ 이게 없으면 uncertain 은 **영구 교착**이다 — 유일한 행동이 「다시 올리기 =
    중복 감수」가 된다. 정직한 결말이 표현 불가능한 상태 기계는 만들지 않는다.

    옥션은 이름으로 찾는 조회 API 가 없어(LOOKUP_MARKETS 밖) 사람이 셀러센터에서 본
    번호를 그대로 믿는다 — 대신 그 사실을 응답 문구에 적는다(4차리뷰 중요③).
    """
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid=None)

    r = client.post(f'/bulk/api/drafts/{did}/market-confirm',
                    json={'market': 'auction', 'market_product_id': 'A999'})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['ok'] is True and body['verified'] is False
    assert '대조 없이' in body['note'], body['note']   # 안 한 검증을 했다고 말하지 않는다

    assert ('auction', 'default', 'ok') in _ledger_rows(did), _ledger_rows(did)
    # 이제 「이미 등록됨」으로 잠긴다(확인 필요 ⚠ 가 아니라).
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['auction'], 'category_codes': ALL_CODES}).get_json()
    assert pre['rows'][0]['status'] == 'registered', pre['rows'][0]
    assert pre['rows'][0]['market_product_id'] == 'A999'
    # 상품관리 목록에서도 「확인 필요」가 아니라 등록됨이다(모순 금지).
    prod = client.get('/bulk/api/products').get_json()
    mine = next(x for x in prod['rows'] if x['id'] == did)
    assert mine['uncertain'] == 0 and mine['registered'] == 1, mine
    assert calls == [], '확정은 조회·기록만 한다 — 등록을 부르지 않는다'


def _stub_lotteon_hits(monkeypatch, codes):
    """롯데온 조회를 그 번호들만 돌려주도록 고정(라이브 호출 없음)."""
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.lotteon.products as LP
    import webapp.routes.bulk.drafts as D
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'LOTTEON_MAIN')
    monkeypatch.setattr(MF, '_lotteon_client', lambda envp: object())
    rows = [{'spdNo': c, 'spdNm': '테스트 자켓(중복차단)'} for c in codes]
    monkeypatch.setattr(LP, 'list_products',
                        lambda **kw: rows if kw.get('page_no', 1) == 1 else [])


def test_중요3_조회되는_마켓은_서버가_번호를_대조한다(client, monkeypatch):
    """11번가·롯데온은 조회 API 가 이미 있다 — 공짜로 막을 수 있는 자리는 막는다."""
    did = _complete(client)
    _seed_ledger(did, 'lotteon', status='uncertain', pid=None)
    _stub_lotteon_hits(monkeypatch, ['LO999'])

    r = client.post(f'/bulk/api/drafts/{did}/market-confirm',
                    json={'market': 'lotteon', 'market_product_id': 'LO999'})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['verified'] is True
    assert ('lotteon', 'default', 'ok') in _ledger_rows(did), _ledger_rows(did)


def test_중요3_마켓에_없는_번호는_확정되지_않는다(client, monkeypatch):
    """틀린 번호를 확정하면 가격·재고 자동갱신이 **남의 상품**으로 나간다(금전 사고)."""
    did = _complete(client)
    _seed_ledger(did, 'lotteon', status='uncertain', pid=None)
    _stub_lotteon_hits(monkeypatch, ['LO111'])          # 다른 번호만 있다

    r = client.post(f'/bulk/api/drafts/{did}/market-confirm',
                    json={'market': 'lotteon', 'market_product_id': 'LO999'})
    assert r.status_code == 400, r.get_data(as_text=True)
    assert 'LO999' in r.get_json()['error']
    # 장부는 그대로 잠긴 채다(확정되지 않았다).
    assert ('lotteon', 'default', 'uncertain') in _ledger_rows(did), _ledger_rows(did)


def test_중요3_조회가_실패하면_확정하지_않는다(client, monkeypatch):
    """「확인 못 했는데 확정」은 폴백이다 — 잠시 뒤 다시 누르면 된다."""
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.lotteon.products as LP
    import webapp.routes.bulk.drafts as D

    did = _complete(client)
    _seed_ledger(did, 'lotteon', status='uncertain', pid=None)
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'LOTTEON_MAIN')
    monkeypatch.setattr(MF, '_lotteon_client', lambda envp: object())

    def boom(**kw):
        raise RuntimeError('롯데온 HTTP 500')

    monkeypatch.setattr(LP, 'list_products', boom)
    r = client.post(f'/bulk/api/drafts/{did}/market-confirm',
                    json={'market': 'lotteon', 'market_product_id': 'LO999'})
    assert r.status_code == 502, r.get_data(as_text=True)
    assert ('lotteon', 'default', 'uncertain') in _ledger_rows(did)


def test_중요4_등록이_도는_중에는_확정이_409(client, monkeypatch):
    """잡이 그 마켓을 처리하는 중에 확정이 끼어들면 장부의 주인이 둘이 된다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun

    did = _complete(client)
    now = datetime.datetime.utcnow()
    s = SessionLocal()
    try:
        s.add(ProductDraftRegisterRun(draft_id=did, job_id='livejob', running=True,
                                      started_at=now, progress_at=now,
                                      current_market='auction',
                                      markets_json=json.dumps(['auction']),
                                      total_count=1))
        s.commit()
    finally:
        s.close()

    r = client.post(f'/bulk/api/drafts/{did}/market-confirm',
                    json={'market': 'auction', 'market_product_id': 'A999'})
    assert r.status_code == 409, r.get_data(as_text=True)
    assert _ledger_rows(did) == [], _ledger_rows(did)


# ── 4차리뷰 치명② 회수(판매중지) 결과를 단정하지 않는다 ────────────────────

def test_치명2_판매중지_실패를_내려두었다고_말하지_않는다(client):
    """★ 회수는 실패할 수 있다(등록 직후 2~3분은 수정 불가 — 실측). 그걸 「내려두었습니다」로
    말하면 사장님이 안심하고 안 내려간다 → 옵션 없는 상품이 계속 판매중이다."""
    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid='A12345')
    _set_ledger_error(did, 'auction', 'PARTIAL',
                      'auction 상품(A12345)은 등록됐지만 옵션 부착에 실패했습니다: 400 / '
                      '⚠️판매중지 실패 — 셀러센터에서 직접 내려주세요(등록 직후 2~3분은 수정 불가)')

    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['auction'], 'category_codes': ALL_CODES}).get_json()
    reason = pre['rows'][0]['reason']
    assert '판매중지에는' in reason and '실패' in reason, reason
    assert '직접 내려주세요' in reason, reason
    assert '판매중지로 내려두었습니다' not in reason, f'거짓 성공 — {reason}'


def test_치명2_판매중지_성공은_그대로_말한다(client):
    """반대로 성공했는데 「실패했을 수 있다」고 하면 그것도 거짓이다."""
    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid='A12345')
    _set_ledger_error(did, 'auction', 'PARTIAL',
                      'auction 상품(A12345)은 등록됐지만 옵션 부착에 실패했습니다: 400 / '
                      '상품은 판매중지로 내려두었습니다')

    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['auction'], 'category_codes': ALL_CODES}).get_json()
    reason = pre['rows'][0]['reason']
    assert '판매중지로 내려두었습니다' in reason, reason
    assert '실패' not in reason.split('옵션 부착만 실패했고')[-1], reason


def test_치명2_회수_결과를_모르면_모른다고_말한다(client):
    """원문에 아무 표식이 없으면 성공도 실패도 단정하지 않는다."""
    did = _complete(client)
    _seed_ledger(did, 'auction', status='uncertain', pid='A12345')
    _set_ledger_error(did, 'auction', 'PARTIAL', '옵션 부착 실패')

    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['auction'], 'category_codes': ALL_CODES}).get_json()
    reason = pre['rows'][0]['reason']
    assert '확인하지 못했습니다' in reason, reason


# ── 4차리뷰 중요① 죽음 판정이 한 벌이다 ────────────────────────────────────

def test_중요1_예외로_끝난_실행도_죽음으로_본다(client, monkeypatch):
    """★ `_register_job` 예외 핸들러는 running=False 로 내리면서 current_market 은 일부러
    남긴다(유령을 찾는 단서). 그 상태가 폴링엔 「죽음」인데 잠금엔 「죽음 아님」이었다 —
    같은 화면이 서로 다른 말을 했다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_dead_run(did, market='lotteon', markets=['lotteon', 'eleven11'],
                   running=False, error='등록 중 예상 밖 오류 — RuntimeError()')

    # ① 폴링과 ② 점검이 같은 말을 한다.
    body = _status(client, did)
    assert body['uncertain'] and body['uncertain']['market'] == 'lotteon', body
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['lotteon'], 'category_codes': ALL_CODES}).get_json()
    assert pre['rows'][0]['status'] == 'uncertain', pre['rows'][0]

    # ③ 회수(새 POST)가 그 사실을 장부에 굳힌다.
    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['eleven11'], calls
    led = dict(((m, st) for m, _a, st in _ledger_rows(did)))
    assert led.get('lotteon') == 'uncertain', _ledger_rows(did)


# ── 4차리뷰 중요② 「호출을 시도한 뒤」의 예외는 실패로 단정하지 않는다 ──────

def test_중요2_전송_뒤_예외는_실패가_아니라_확인_필요다(client):
    """마켓 호출이 나간 뒤 우리 쪽에서 터지면(커밋 실패 등) 상품은 만들어져 있을 수 있다."""
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft, RegisterUnknown

    did = _complete(client)
    sent = []

    def send_then_break(market, spec):
        sent.append(market)
        return {'product_id': 'LO777', 'raw': BrokenRaw()}

    class BrokenRaw:
        def __repr__(self):
            raise RuntimeError('원문 직렬화 중 터짐')

    s = SessionLocal()
    try:
        try:
            register_draft(s, did, 'lotteon', category_code=ALL_CODES['lotteon'],
                           _send=send_then_break)
        except RegisterUnknown:
            pass                       # 예외 자체는 여기까지 오면 된다
    finally:
        s.close()
    assert sent == ['lotteon']


def test_중요2_라우트가_전송뒤_예외를_확인필요로_표시한다(client, monkeypatch):
    """화면에 「실패」로 뜨면 다음 점검이 ready 로 내줘 같은 상품이 두 개가 된다."""
    import webapp.routes.bulk.drafts as D
    from lemouton.registration.service import RegisterUnknown

    did = _complete(client)

    def boom(session, draft_id, market, **kw):
        raise RegisterUnknown('마켓 호출 뒤 기록 중 오류')

    monkeypatch.setattr(D, 'register_draft', boom)
    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    row = _status(client, did)['rows'][0]
    assert row['status'] == 'unknown', row
    assert '올라갔는지 모릅니다' in (row['error'] or ''), row
    # 장부에도 남아 다음 점검이 잠근다.
    assert ('lotteon', 'default', 'uncertain') in _ledger_rows(did), _ledger_rows(did)


def test_확정은_상품번호_없이는_안_된다(client):
    """성공의 유일한 증거는 마켓이 준 상품번호다 — 번호 없이 「등록됨」으로 바꾸지 않는다."""
    did = _complete(client)
    _seed_ledger(did, 'lotteon', status='uncertain', pid=None)
    r = client.post(f'/bulk/api/drafts/{did}/market-confirm',
                    json={'market': 'lotteon'})
    assert r.status_code == 400
    assert '상품번호' in r.get_json()['error']


def test_중요5_크롤_재적재는_상품번호_없는_불확실도_잠근다(client):
    """「모른다」는 「없다」가 아니다 — 유령이 있을지 모르는 초안을 크롤 값으로 덮으면
    그 뒤 등록에서 같은 상품이 둘이 된다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration import draft_from_crawl as DFC

    did = _complete(client)
    _seed_ledger(did, 'lotteon', status='uncertain', pid=None)   # 번호 없음
    s = SessionLocal()
    try:
        draft = s.query(ProductDraft).filter_by(id=did).first()
        rows = DFC.registered_market_rows(s, draft)
        assert [r.market for r in rows] == ['lotteon'], rows
    finally:
        s.close()


def test_중요4_스레드가_죽은_직후에도_점검이_초록으로_안_뜬다(client):
    """★ 회수(새 POST) 전이라도 점검과 결과표가 **같은 말**을 해야 한다.

    예전엔 그 창에서 위쪽 점검이 ready(초록·미리체크), 아래쪽 결과표가 「확인 필요」였다.
    사장님이 위를 믿고 한 번 누르면 그게 중복이다.
    """
    did = _complete(client)
    _seed_dead_run(did, market='lotteon', markets=['lotteon', 'eleven11'])

    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['lotteon', 'eleven11'],
                            'category_codes': ALL_CODES}).get_json()
    rows = {r['market']: r for r in pre['rows']}
    assert rows['lotteon']['status'] == 'uncertain', rows['lotteon']
    assert rows['eleven11']['status'] == 'ready'      # 손댄 적 없는 마켓은 그대로

    # 폴링(결과표)도 같은 답이다 — 두 화면이 갈리지 않는다.
    body = _status(client, did)
    assert body['uncertain'] and body['uncertain']['market'] == 'lotteon'
    # ★ 읽기만 했다 — 장부에 굳히지 않는다(회수될 때 굳는다).
    assert _ledger_rows(did) == [], _ledger_rows(did)


def test_살아있는_실행은_점검을_잠그지_않는다(client):
    """멀쩡히 도는 실행까지 잠그면 정상 등록이 「확인 필요」로 막힌다(거짓 잠금)."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    did = _complete(client)
    now = datetime.datetime.utcnow()
    s = SessionLocal()
    try:
        s.add(ProductDraftRegisterRun(draft_id=did, job_id='livejob', running=True,
                                      started_at=now, progress_at=now,
                                      current_market='lotteon',
                                      markets_json=json.dumps(['lotteon']),
                                      total_count=1))
        s.commit()
    finally:
        s.close()
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['lotteon'], 'category_codes': ALL_CODES}).get_json()
    assert pre['rows'][0]['status'] == 'ready', pre['rows'][0]

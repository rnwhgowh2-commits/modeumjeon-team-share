# -*- coding: utf-8 -*-
"""폰 크롤 리모컨 API — 상태 조회 / 자동 on-off / 지금 한 바퀴.

크롤 자체는 로컬 PC 원칙 그대로다. 서버는 '할 일' 표시만 바꾼다.
"""
import pytest

ADMIN_EMAIL = 'remote-admin@test.local'
MEMBER_EMAIL = 'remote-member@test.local'


# flask_app 픽스처는 tests/mobile/conftest.py 에 있다(세 파일이 쓴다).


@pytest.fixture
def users(flask_app):
    """admin·member 를 하나씩 둔다 — 리모컨이 admin 전용이라 필요하다.

    DISABLE_AUTH=1 은 '첫 admin'으로 자동 로그인한다. 그 사람이 없으면 익명이라
    리모컨이 로그인 화면으로 튕겨 시험이 통째로 무너진다(권한 문제로 오인하기 쉽다).
    flask_app 뒤에 와야 한다 — 테이블은 create_app 의 init_db 가 만든다.
    """
    from shared.db import SessionLocal
    from webapp.auth.models import User
    s = SessionLocal()
    try:
        out = {}
        for email, role in ((ADMIN_EMAIL, 'admin'), (MEMBER_EMAIL, 'member')):
            u = s.query(User).filter(User.email == email).first()
            if u is None:
                # 비밀번호는 안 쓴다 — 로그인은 DISABLE_AUTH 자동 로그인이 해 준다.
                u = User(email=email, name=role, password_hash='x',
                         role=role, is_active=True)
                s.add(u)
                s.flush()
            u.is_active = True          # 앞 시험이 감춰 뒀을 수 있다(member_client)
            out[role] = u.id
        s.commit()
        return out
    finally:
        s.close()


@pytest.fixture
def client(flask_app, users):
    """admin 으로 로그인된 클라이언트 (DISABLE_AUTH 가 첫 admin 을 집는다)."""
    return flask_app.test_client()


@pytest.fixture
def member_client(flask_app, users):
    """member 로 로그인된 클라이언트.

    ★ 세션을 손으로 심으면 안 된다 — flask_login 의 session_protection="strong"
      (webapp/auth/__init__.py) 이 `_id` 가 안 맞는 세션을 **통째로 비워** 버리고,
      그러면 DISABLE_AUTH 가 다시 admin 으로 로그인시킨다. 실측으로 확인했다:
      403 을 기대한 자리에 200 이 오는데, 원인이 권한이 아니라 세션이라 헛짚기 쉽다.
      (Flask 2.3+ 의 session_transaction 은 요청 컨텍스트 밖에서 yield 해서
       올바른 `_id` 를 계산해 넣는 것도 불가능하다.)

    그래서 앱 **자신의** 로그인 경로를 탄다: DISABLE_AUTH 는 '첫 admin, 없으면 첫
    활성 사용자'를 집으므로, member 말고 전부 잠시 비활성으로 두면 member 로
    로그인된다. 끝나면 되돌린다.
    """
    # 🔴 이 fixture 는 **모든 사용자를 잠시 비활성**으로 만든다. 진짜 DB 면 안 돈다.
    #    (사유·원리는 conftest.require_sqlite 의 주석에 한 번만 적어 뒀다.)
    from tests.mobile.conftest import require_sqlite
    require_sqlite()

    from shared.db import SessionLocal
    from webapp.auth.models import User
    hidden = []
    s = SessionLocal()
    try:
        for u in s.query(User).filter(User.is_active.is_(True)).all():
            if u.id != users['member']:
                u.is_active = False
                hidden.append(u.id)
        s.commit()
    finally:
        s.close()

    try:
        c = flask_app.test_client()
        c.get('/mobile/')       # 게이트 없는 화면으로 세션만 만든다
        with c.session_transaction() as sess:
            assert sess.get('_user_id') == str(users['member']), \
                f"member 로 로그인이 안 됐다(_user_id={sess.get('_user_id')!r}) — 권한이 아니라 로그인 문제다"
        yield c
    finally:
        # ★ try 안에 둔다 — 위 assert 가 깨지면 감춘 사용자가 그대로 남아
        #   뒤 시험들이 엉뚱한 이유로 무너진다.
        s = SessionLocal()
        try:
            for uid in hidden:
                u = s.get(User, uid)
                if u is not None:
                    u.is_active = True
            s.commit()
        finally:
            s.close()


def test_상태를_물으면_필요한_칸이_다_온다(client, users):
    r = client.get('/mobile/crawl/api/status')
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    for key in ('pc', 'auto_enabled', 'waiting', 'laps_today',
                'stats_ok', 'last_lap_today_at', 'last_lap_seconds_ago'):
        assert key in d, f'{key} 칸이 없다'
    assert 'online' in d['pc']


def test_퍼센트는_지어내지_않는다(client, users):
    """분모·분자의 단위가 달라 정확한 퍼센트를 낼 수 없다 — 아예 안 준다."""
    d = client.get('/mobile/crawl/api/status').get_json()
    assert 'percent' not in d


def test_통계를_못_읽으면_0이_아니라_모름이다(client, users, monkeypatch):
    """0 을 주면 '진짜 0바퀴'와 '조회 실패'가 화면에서 구분이 안 된다 — 그것도 지어낸 숫자다."""
    from lemouton.sources import crawl_schedule

    def _boom(*a, **kw):
        raise RuntimeError('통계 조회 실패(가정)')

    monkeypatch.setattr(crawl_schedule, 'lap_stats', _boom)
    r = client.get('/mobile/crawl/api/status')
    assert r.status_code == 200, '통계가 죽어도 리모컨은 떠야 한다'
    d = r.get_json()
    assert d['stats_ok'] is False
    assert d['laps_today'] is None, '못 읽었는데 0 을 지어냈다'


def test_마지막_바퀴는_초_단위로도_준다(client, users):
    """at 은 오프셋 없는 naive UTC 라 폰 JS 가 9시간 이르게 읽는다 — 화면은 초를 쓴다.

    바퀴 기록이 없으면 이 칸이 늘 None 이라 계산이 틀려도 안 드러난다. 한 건 넣고 본다.
    completed_at 을 '지금'으로 넣으므로 KST 자정 경계에 걸릴 일이 없다.
    """
    import datetime as _dt
    from shared.db import SessionLocal
    from lemouton.sources.models import CrawlLapRun

    s = SessionLocal()
    run_id = None
    try:
        # 저장 모양은 naive UTC (라우트가 재는 시계와 같아야 한다)
        now_utc = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
        run = CrawlLapRun(completed_at=now_utc)
        s.add(run)
        s.commit()
        run_id = run.id

        d = client.get('/mobile/crawl/api/status').get_json()
        assert d['stats_ok'] is True
        assert d['last_lap_today_at'], '바퀴를 넣었는데 시각이 비었다'
        ago = d['last_lap_seconds_ago']
        assert isinstance(ago, int), f'초가 숫자가 아니다: {ago!r}'
        assert 0 <= ago < 120, f'방금 넣은 바퀴인데 {ago}초 전이라고 한다(시간대 계산 오류)'
    finally:
        if run_id is not None:
            s.query(CrawlLapRun).filter(CrawlLapRun.id == run_id).delete()
            s.commit()
        s.close()


def test_상태는_캐시하면_안_된다(client, users):
    """옛 답이 재사용되면 꺼진 PC 가 켜진 것으로 보인다."""
    r = client.get('/mobile/crawl/api/status')
    assert 'no-store' in (r.headers.get('Cache-Control') or '')


def test_자동크롤을_켜고_끌_수_있다(client, users):
    r = client.post('/mobile/crawl/api/auto', json={'enabled': True})
    assert r.status_code == 200 and r.get_json()['auto_enabled'] is True
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is True

    r = client.post('/mobile/crawl/api/auto', json={'enabled': False})
    assert r.get_json()['auto_enabled'] is False
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is False


def test_enabled_가_없으면_400(client, users):
    r = client.post('/mobile/crawl/api/auto', json={})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_문자열_false_는_켜기로_둔갑하면_안_된다(client, users):
    """bool('false') 는 True 다 — 통과시키면 '끈다'가 조용히 '켠다'가 된다."""
    client.post('/mobile/crawl/api/auto', json={'enabled': False})
    r = client.post('/mobile/crawl/api/auto', json={'enabled': 'false'})
    assert r.status_code == 400, "문자열 'false' 를 받아줬다"
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is False, \
        "거절해 놓고 설정은 바뀌었다"


def test_한_바퀴를_시키면_자동크롤도_같이_켜진다(client, users):
    """꺼져 있으면 서버가 할 일 목록을 비워버려 PC 가 아무것도 안 집어간다."""
    client.post('/mobile/crawl/api/auto', json={'enabled': False})
    r = client.post('/mobile/crawl/api/run-lap', json={})
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    assert d['auto_enabled'] is True
    # 응답의 auto_enabled 는 붙박이 값이라 그것만 보면 아무것도 안 지킨다.
    # 진짜로 켜졌는지는 저장된 설정을 되물어야 안다.
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is True, \
        '응답만 True 고 실제 설정은 안 켜졌다'


def test_한_바퀴는_가짜_완료기록을_남기지_않는다(client, users):
    """start_new_lap(record=True) 면 돌지도 않은 바퀴가 '완료'로 박힌다."""
    before = client.get('/mobile/crawl/api/status').get_json()['laps_today']
    assert before is not None, '통계가 죽어 있으면 None==None 으로 헛통과한다'
    client.post('/mobile/crawl/api/run-lap', json={})
    after = client.get('/mobile/crawl/api/status').get_json()['laps_today']
    assert after == before, '누르기만 했는데 바퀴 수가 늘었다'


# ── 권한 ──────────────────────────────────────────────────────────────────
#  같은 설정을 바꾸는 PC 경로(POST /api/automation/save)가 admin 전용이다
#  (webapp/routes/settings.py 의 blueprint 게이트). 폰만 열려 있으면 member 가
#  전 팀의 크롤을 끄거나 전 소싱처를 즉시 크롤 대상으로 되돌릴 수 있다 = 돈 문제.

def test_member_는_리모컨을_못_쓴다(member_client):
    for method, path in (('get', '/mobile/crawl/api/status'),
                         ('post', '/mobile/crawl/api/auto'),
                         ('post', '/mobile/crawl/api/run-lap'),
                         ('get', '/mobile/crawl/')):
        r = (member_client.get(path) if method == 'get'
             else member_client.post(path, json={'enabled': True}))
        assert r.status_code == 403, f'{method.upper()} {path} 가 {r.status_code} 로 통과했다'
        # ★ 화면(crawl.html)의 askServer 가 '거부'를 알아보는 근거가 **이것**이다:
        #   거부는 JSON 이 아니라 HTML 로 온다. 나중에 누가 JSON 에러 핸들러를 달면
        #   그 갈래가 죽은 코드가 되는데, 상태코드만 보면 여기선 안 걸린다.
        assert 'application/json' not in (r.headers.get('Content-Type') or ''), \
            f'{method.upper()} {path} 거부가 JSON 으로 온다 — 화면의 forbidden 갈래가 죽는다'


def test_member_가_눌러도_설정은_안_바뀐다(member_client):
    """403 만 보고 끝내면 '막았다고 믿었는데 값은 바뀌어 있는' 경우를 놓친다."""
    from shared.db import SessionLocal
    from lemouton.pricing.settings import get_automation, save_automation

    s = SessionLocal()
    try:
        save_automation(s, {'crawl_auto_enabled': False})   # 꺼 둔 상태에서 시작
        s.commit()
    finally:
        s.close()

    member_client.post('/mobile/crawl/api/auto', json={'enabled': True})
    member_client.post('/mobile/crawl/api/run-lap', json={})

    s = SessionLocal()
    try:
        assert bool(get_automation(s).get('crawl_auto_enabled')) is False, \
            'member 가 막혔는데도 자동 크롤이 켜졌다'
    finally:
        s.close()

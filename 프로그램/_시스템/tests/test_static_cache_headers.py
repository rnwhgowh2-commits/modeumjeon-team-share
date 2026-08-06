# -*- coding: utf-8 -*-
"""정적파일(CSS/JS) 캐시 헤더 — 프로그램 전체 체감속도의 최대 병목이던 부분.

라이브에서 실측한 증상 (2026-08-06):
  · 화면 조작 가능(domInteractive) 2,931ms  ↔  서버 응답(TTFB) 은 400ms 뿐
  · CSS/JS 한 개가 최대 250초 대기, 탭 이동 시 36개 중 3개만 캐시 재사용
  · 응답 헤더: `Vary: Cookie` + `cf-cache-status: BYPASS`

원인: 응답에 `Vary: Cookie` 가 붙으면
  ① Cloudflare 가 캐시를 포기해(BYPASS) CSS/JS 25개가 전부 원본 서버까지 온다
  ② 원본 워커는 2개뿐이라 무거운 조회 뒤에 정적파일이 줄 선다
  ③ 브라우저도 캐시를 못 써서 매번 304 재검증 왕복을 한다

여기서 지키는 약속:
  - /static/* 응답에 Cookie 흔적(Vary: Cookie, Set-Cookie)이 없다
  - ?v=<수정시각> 이 붙은 URL 은 immutable (브라우저가 재검증조차 안 함)
  - 버전 없는 URL(서비스워커가 부르는 sw.js·manifest.json)은 불변 처리에서 제외

이 시험이 깨지면 = 위 250초 대기가 되돌아온 것이다. 헤더를 되돌리지 말 것.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_정적파일에_쿠키_흔적이_없다(client):
    """Vary: Cookie 나 Set-Cookie 가 있으면 Cloudflare 가 캐시를 포기한다."""
    resp = client.get('/static/toss.css?v=123456')
    assert resp.status_code == 200

    vary = resp.headers.get('Vary', '')
    assert 'cookie' not in vary.lower(), f"Vary 에 Cookie 가 남아있다: {vary!r}"
    assert 'Set-Cookie' not in resp.headers, "정적파일에 Set-Cookie 가 붙으면 CDN 캐시 불가"


def test_버전붙은_URL은_불변으로_캐시된다(client):
    """?v=<mtime> 이 있으면 내용이 바뀔 때 URL 도 바뀌므로 영구 캐시가 안전하다."""
    resp = client.get('/static/toss.css?v=123456')
    cc = resp.headers.get('Cache-Control', '')

    assert 'immutable' in cc, f"immutable 이 없으면 브라우저가 매번 재검증한다: {cc!r}"
    assert 'max-age=31536000' in cc, f"장기 캐시가 아니다: {cc!r}"


def test_버전없는_URL은_불변이_아니다(client):
    """서비스워커가 /static/sw.js 를 버전 없이 부른다 — 1년 고정되면 갱신이 막힌다."""
    resp = client.get('/static/sw.js')
    cc = resp.headers.get('Cache-Control', '')

    assert 'immutable' not in cc, f"sw.js 가 불변이면 앱 갱신이 영구히 막힌다: {cc!r}"


def test_버전이_있어도_sw_js는_불변이_아니다(client):
    """?v= 가 어쩌다 붙어도 서비스워커·manifest 는 예외로 둔다."""
    for path in ('/static/sw.js?v=123456', '/static/manifest.json?v=123456'):
        cc = client.get(path).headers.get('Cache-Control', '')
        assert 'immutable' not in cc, f"{path} 가 불변이면 안 된다: {cc!r}"


def test_일반_화면은_영향받지_않는다(client):
    """정적파일 규칙이 동적 페이지의 세션·캐시 동작을 건드리면 안 된다."""
    resp = client.get('/')
    cc = resp.headers.get('Cache-Control', '')
    assert 'immutable' not in cc, f"화면 HTML 이 불변이면 내용 갱신이 막힌다: {cc!r}"


@pytest.mark.parametrize('qs', ['nov=1', 'rev=2', 'version=3', 'sv=1'])
def test_v가_아닌_비슷한_이름은_불변이_아니다(client, qs):
    """이름이 정확히 'v' 인 것만 인정 — 문자열로 'v=' 를 찾으면 ?nov=1 도 걸린다.

    한 번 1년 불변으로 나가면 되돌릴 방법이 없다(브라우저가 다시 안 물어봄).
    """
    cc = client.get(f'/static/toss.css?{qs}').headers.get('Cache-Control', '')
    assert 'immutable' not in cc, f"?{qs} 는 버전이 아닌데 1년 고정됐다: {cc!r}"


def test_v가_여러_값_중에_있어도_인정한다(client):
    """?foo=1&v=123 처럼 뒤에 붙어도 버전으로 본다."""
    cc = client.get('/static/toss.css?foo=1&v=123456').headers.get('Cache-Control', '')
    assert 'immutable' in cc, f"버전이 있는데 불변이 아니다: {cc!r}"


def test_세션이_Cookie축을_붙여도_벗겨진다(monkeypatch):
    """진짜 원인 재현 — Flask 는 세션을 건드리면 응답에 Vary: Cookie 를 붙인다.

    그 일은 after_request 가 전부 끝난 **뒤**에 벌어지므로, after_request 에서 지우면
    다시 붙어서 안 지워진다. 그래서 WSGI 바깥층에서 지운다. 이 시험이 그걸 못 박는다.
    """
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True

    # 라이브에서 세션·Flask-Login 이 실제로 만들어내던 헤더를 그대로 흉내낸다
    @flask_app.after_request
    def _세션처럼_Cookie축을_붙인다(resp):
        resp.headers['Vary'] = 'Cookie'
        resp.headers['Set-Cookie'] = 'session=abc; Path=/'
        return resp

    resp = flask_app.test_client().get('/static/toss.css?v=123456')

    assert 'cookie' not in resp.headers.get('Vary', '').lower()
    assert 'Set-Cookie' not in resp.headers
    assert 'immutable' in resp.headers.get('Cache-Control', '')


def test_gzip_캐시가_같은_내용을_돌려준다(client):
    """압축 결과를 메모리에 재사용한다 — 두 번째 요청도 내용이 같아야 한다."""
    headers = {'Accept-Encoding': 'gzip'}
    first = client.get('/static/toss.css?v=123456', headers=headers)
    second = client.get('/static/toss.css?v=123456', headers=headers)

    assert first.data == second.data, "캐시된 압축본이 원본과 다르다"
    assert first.headers.get('Content-Encoding') == 'gzip'
    assert second.headers.get('Content-Encoding') == 'gzip'

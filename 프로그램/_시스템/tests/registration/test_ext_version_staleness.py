# -*- coding: utf-8 -*-
"""화면이 **「확장이 낡았는지」를 스스로 말한다.**

🔴 왜 (2026-08-13 사장님이 겪음)
   화면은 「확장 0.7.94」라고만 보여 줬다. 그게 **낡은 판인지 최신인지**를 알 방법이
   없어서, 사장님이 `chrome://extensions` 에서 ↻ 를 눌러도 아무 일이 없는
   **헛걸음**을 했다(그때 로드 폴더가 이미 최신과 같아 누를 것이 없었다).

   판 번호를 보여 주는 것만으로는 부족하다 — **견줄 상대**가 있어야 뜻이 생긴다.

★ 같으면 아무 말도 안 한다. **늘 뜨는 경고는 아무 말도 안 하는 것과 같다.**
"""
import json
from pathlib import Path

import pytest

SYS = Path(__file__).resolve().parents[2]
MANIFEST = SYS / 'extension' / 'moum-crawler' / 'manifest.json'
COLLECT = SYS / 'webapp' / 'templates' / 'bulk' / 'partials' / '_collect.html'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_서버가_최신_확장판을_안다():
    from webapp.routes.bulk.search_filters import expected_ext_version
    got = expected_ext_version()
    want = json.loads(MANIFEST.read_text(encoding='utf-8'))['version']
    assert got == want, (
        f'서버가 아는 확장 판({got})이 manifest({want})와 다릅니다 — '
        '경로가 틀리면 화면이 늘 「새 판 있음」이라 하거나 영영 아무 말도 안 합니다.'
    )


def test_목록에_최신_확장판이_실려_나간다(client):
    """🔴 **심어 놓고 본다.** 대상이 없으면 건너뛰기로 통과해 아무것도 안 본다."""
    made = client.post('/bulk/api/search-filters', json=dict(
        source_key='musinsa',
        listing_url='https://www.musinsa.com/search/goods?keyword=판번호시험'))
    assert made.status_code == 200, made.get_data(as_text=True)
    fid = made.get_json()['filter']['id']
    try:
        r = client.get('/bulk/api/search-filters')
        assert r.status_code == 200, r.get_data(as_text=True)
        rows = [x for x in (r.get_json().get('filters') or []) if x['id'] == fid]
        assert rows, '방금 만든 필터가 목록에 없습니다.'
        want = json.loads(MANIFEST.read_text(encoding='utf-8'))['version']
        assert rows[0].get('ext_version_expected') == want, (
            '목록에 최신 확장 판이 안 실립니다 — 화면이 견줄 상대가 없습니다.'
        )
    finally:
        from shared.db import SessionLocal
        from lemouton.registration.models import SearchFilter
        s = SessionLocal()
        try:
            row = s.query(SearchFilter).filter_by(id=fid).first()
            if row is not None:
                s.delete(row)
                s.commit()
        finally:
            s.close()


def test_화면이_낡았을_때만_알려_준다():
    """🔴 늘 뜨면 아무도 안 본다 — **낡았을 때만** 말해야 한다.

    ⚠️ 예전 이 시험은 화면에 `'!== f.last_ext_version'` 이라는 **글자가 있는지**를
       봤다. 그래서 「글자로 견주기」라는 틀린 방식을 시험이 못 박아 버렸고,
       확장이 서버보다 새 판일 때 뜨는 거짓 경보를 영영 못 잡았다.
       → 이제 판정은 서버가 하고(`ext_version_outdated`), 화면은 그 답만 읽는다.
    """
    html = COLLECT.read_text(encoding='utf-8')
    assert 'ext_version_outdated' in html, (
        '화면이 서버 판정을 안 읽습니다 — 화면에서 글자로 견주면 0.8.03 이 '
        '0.8.02 보다 낡은 것이 됩니다.'
    )
    assert '!== f.last_ext_version' not in html, (
        '아직 화면에서 글자로 견줍니다 — 판 번호는 숫자로 견줘야 합니다.'
    )
    assert '새 판' in html, '무엇을 해야 하는지 사람 말로 안 알려 줍니다.'


# ── 🔴 2026-08-13 라이브에서 실제로 본 두 장면 ────────────────────────────
#   ① 화면: 「확장 0.8.03 · 새 판 0.8.02 있음」 — 켜져 있는 것이 **더 새 판**인데
#      사장님더러 ↻ 를 누르라고 했다(누를 것이 없는 헛걸음).
#   ② 서버: main 의 manifest 는 0.8.03 이고 배포도 성공했는데 라이브 API 는
#      계속 0.8.02 를 「최신」이라 답했다 — 캐시에 만료가 없어서다.
#   ★ 둘 다 「경고가 틀리게 뜬다」는 같은 고장이다. 늘 틀리게 뜨는 경고는
#     사장님이 곧 무시하게 되고, 그러면 **진짜 낡았을 때도 안 보인다.**

@pytest.mark.parametrize('loaded,expected,want,왜', [
    ('0.8.02', '0.8.03', True,  '진짜 낡았다 — 이때는 말해 줘야 한다'),
    ('0.8.03', '0.8.02', False, '켜져 있는 쪽이 더 새 판 — 라이브에서 본 거짓 경보'),
    ('0.8.03', '0.8.03', False, '같다 — 아무 말도 안 한다'),
    ('0.8.9',  '0.8.10', True,  '9 < 10 — 글자로 견주면 거꾸로 나온다'),
    ('0.8.10', '0.8.9',  False, '10 > 9 — 글자로 견주면 거짓 경보가 난다'),
    (None,     '0.8.03', False, '한 번도 안 돌아 모른다 — 모르면 겁주지 않는다'),
    ('0.8.03', None,     False, 'manifest 를 못 읽었다 — 모르면 겁주지 않는다'),
])
def test_낡았을_때만_참이다(loaded, expected, want, 왜):
    from webapp.routes.bulk.search_filters import ext_version_outdated
    got = ext_version_outdated(loaded, expected)
    assert got is want, f'{왜} — 켜진판={loaded} 저장소={expected} 답={got}'


def test_목록에_낡음_판정이_실려_나간다(client):
    """🔴 심어 놓고 본다 — 대상이 없으면 아무것도 안 보고 통과한다."""
    made = client.post('/bulk/api/search-filters', json=dict(
        source_key='musinsa',
        listing_url='https://www.musinsa.com/search/goods?keyword=낡음판정시험'))
    assert made.status_code == 200, made.get_data(as_text=True)
    fid = made.get_json()['filter']['id']
    try:
        r = client.get('/bulk/api/search-filters')
        rows = [x for x in (r.get_json().get('filters') or []) if x['id'] == fid]
        assert rows, '방금 만든 필터가 목록에 없습니다.'
        assert 'ext_version_outdated' in rows[0], (
            '목록에 낡음 판정이 없습니다 — 화면이 스스로 견주게 되면 또 틀립니다.'
        )
        assert rows[0]['ext_version_outdated'] is False, (
            '한 번도 안 돌아 `last_ext_version` 이 없는 새 필터인데 「낡았다」고 '
            '합니다 — 모르는 것을 낡았다고 하면 안 됩니다.'
        )
    finally:
        from shared.db import SessionLocal
        from lemouton.registration.models import SearchFilter
        s = SessionLocal()
        try:
            row = s.query(SearchFilter).filter_by(id=fid).first()
            if row is not None:
                s.delete(row)
                s.commit()
        finally:
            s.close()


def test_manifest_가_바뀌면_다시_읽는다(tmp_path, monkeypatch):
    """🔴 라이브 실측 — 배포로 manifest 가 0.8.03 이 됐는데도 서버는 계속
       0.8.02 를 「최신」이라 답했다(워커 6개 전부). 캐시에 **만료가 없어서**다.

    ★ 「한 번 읽고 영원히 기억한다」는 배포가 있는 곳에선 거짓말이 된다.
    """
    import webapp.routes.bulk.search_filters as SF

    p = tmp_path / 'manifest.json'
    p.write_text(json.dumps({'version': '1.0.0'}), encoding='utf-8')
    monkeypatch.setattr(SF, '_manifest_path', lambda: p)
    SF._EXT_VER_CACHE.clear()

    assert SF.expected_ext_version() == '1.0.0'

    p.write_text(json.dumps({'version': '1.0.1'}), encoding='utf-8')
    import os
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns + 10 ** 9, st.st_mtime_ns + 10 ** 9))

    assert SF.expected_ext_version() == '1.0.1', (
        '파일이 바뀌었는데 옛 값을 그대로 말합니다 — 배포한 뒤에도 사장님 화면엔 '
        '옛 판 번호가 「최신」이라 뜹니다.'
    )


def test_확장_판_세_곳이_같다():
    """🔴 manifest·본체·화면쪽이 어긋나면 판정이 통째로 틀어진다."""
    import re
    want = json.loads(MANIFEST.read_text(encoding='utf-8'))['version']
    bg = (SYS / 'extension' / 'moum-crawler' / 'background.js').read_text(encoding='utf-8')
    cm = (SYS / 'extension' / 'moum-crawler' / 'content_mou.js').read_text(encoding='utf-8')
    m1 = re.search(r'MOUM_EXT_VERSION = "([0-9.]+)"', bg)
    m2 = re.search(r'EXT_VERSION = "([0-9.]+)"', cm)
    assert m1 and m1.group(1) == want, f'background.js={m1 and m1.group(1)} / manifest={want}'
    assert m2 and m2.group(1) == want, f'content_mou.js={m2 and m2.group(1)} / manifest={want}'

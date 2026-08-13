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


def test_화면이_다를_때만_알려_준다():
    """🔴 늘 뜨면 아무도 안 본다 — 다를 때만 말해야 한다."""
    html = COLLECT.read_text(encoding='utf-8')
    assert 'ext_version_expected' in html, '화면이 최신 판을 안 읽습니다.'
    assert '!== f.last_ext_version' in html, (
        '같은지 다른지를 안 봅니다 — 늘 뜨거나 영영 안 뜹니다.'
    )
    assert '새 판' in html, '무엇을 해야 하는지 사람 말로 안 알려 줍니다.'


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

# -*- coding: utf-8 -*-
"""카테고리 잇기 화면·창구 (Phase 7-2b).

🔴 이 파일이 막는 사고
  ① 창구는 되는데 화면에 없어 사장님은 「안 된다」고 느끼는 것.
  ② 없는 정규 카테고리를 가리켜 화면엔 이어진 것처럼 보이는데 안 먹는 것.
  ③ 점수만으로 저절로 이어지는 길이 생기는 것(사장님 확정 — 자동 확정 안 함).
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)

    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass

    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


def _정규(client, path):
    from lemouton.policy.normalized_category import NormalizedCategory
    s = client._Session()
    try:
        row = NormalizedCategory(path=path, depth=path.count('>'))
        s.add(row)
        s.commit()
        return row.id
    finally:
        s.close()


def _보류(client, source_id='musinsa', source_path='여성의류>원피스', **kw):
    from lemouton.policy.normalized_category import SourceCategoryLink
    s = client._Session()
    try:
        row = SourceCategoryLink(source_id=source_id, source_path=source_path, **kw)
        s.add(row)
        s.commit()
        return row.id
    finally:
        s.close()


# ── 창구 ──────────────────────────────────────────────────────────────────

def test_보류함이_안_이은_것만_준다(client):
    nid = _정규(client, '여성>원피스')
    _보류(client, source_path='이었음', normalized_category_id=nid)
    _보류(client, source_path='아직')
    j = client.get('/api/category-pending').get_json()
    assert [x['source_path'] for x in j['items']] == ['아직']


def test_이으면_보류함에서_빠진다(client):
    nid = _정규(client, '여성>원피스')
    lid = _보류(client)
    r = client.post(f'/api/category-pending/{lid}',
                    json={'normalized_category_id': nid})
    assert r.status_code == 200
    assert client.get('/api/category-pending').get_json()['items'] == []


def test_다시_보류함으로_되돌린다(client):
    nid = _정규(client, '여성>원피스')
    lid = _보류(client)
    client.post(f'/api/category-pending/{lid}', json={'normalized_category_id': nid})
    client.post(f'/api/category-pending/{lid}', json={'normalized_category_id': None})
    assert len(client.get('/api/category-pending').get_json()['items']) == 1


def test_없는_정규_카테고리는_못_가리킨다(client):
    """🔴 화면엔 이어진 것처럼 보이는데 실제로는 안 먹는다."""
    lid = _보류(client)
    r = client.post(f'/api/category-pending/{lid}',
                    json={'normalized_category_id': 99999})
    assert r.status_code == 400


def test_없는_줄이면_404(client):
    r = client.post('/api/category-pending/99999', json={'normalized_category_id': 1})
    assert r.status_code == 404


def test_정규_카테고리를_검색한다(client):
    _정규(client, '여성>원피스')
    _정규(client, '남성>코트')
    j = client.get('/api/normalized-categories?q=원피스').get_json()
    assert [x['path'] for x in j['items']] == ['여성>원피스']


def test_깨진_후보값이_있어도_안_터진다(client):
    """조용히 쓰지 않는다 — 「후보 없음」처럼 다룬다."""
    _보류(client, candidates_json='{이건 JSON 이 아니다')
    j = client.get('/api/category-pending').get_json()
    assert j['ok'] is True
    assert j['items'][0]['candidates'] == []


# ── 화면 ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def html(client):
    r = client.get('/policies/categories')
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_화면이_뜬다(html):
    assert '카테고리 잇기' in html
    assert 'id="clrows"' in html


def test_왜_두_번_잇는지_화면이_말한다(html):
    """안 말하면 「왜 두 번 잇지」가 된다."""
    assert '정규 카테고리' in html
    assert '6마켓이 한꺼번에' in html


def test_자동_확정_안_한다고_화면이_말한다(html):
    """🔴 사장님 확정 — 점수가 높아도 사람이 눌러야 한다."""
    assert '저절로 이어지지 않습니다' in html


def test_창구를_실제로_부른다(html):
    assert '/api/category-pending' in html
    assert '/api/normalized-categories' in html


def test_씨앗_붓기_단추가_있다(html):
    assert 'id="clboot"' in html
    assert '/api/normalized-categories/bootstrap' in html

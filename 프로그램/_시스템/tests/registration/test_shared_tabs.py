# -*- coding: utf-8 -*-
"""⑤주문관리 · ⑥CS관리 · ⑦통계 — 기존 화면을 그대로 쓴다(중복 제작 금지).

설계서 §3-2 확정 원칙: "주문·CS·마진계산기 = 데이터는 한 곳에만."
사장님 확정: "CS탭은 모음전탭 그대로 적용하면 돼."
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_여덟_탭이_모두_등록되어_있다():
    """설계서 §3-2 의 8탭. 여기 없으면 화면에 아예 안 뜬다."""
    from webapp.routes.bulk import SUBTABS
    keys = [t['key'] for t in SUBTABS]
    for k in ('collect', 'process', 'send', 'manual', 'orders', 'cs', 'stats', 'settings'):
        assert k in keys, f"{k} 탭이 SUBTABS 에 없다"


def test_수집_가공_전송_순서가_지켜진다():
    from webapp.routes.bulk import SUBTABS
    keys = [t['key'] for t in SUBTABS]
    assert keys.index('collect') < keys.index('process') < keys.index('send')


@pytest.mark.parametrize("tab", ["orders", "cs", "stats"])
def test_공유_탭이_열린다(client, tab):
    assert client.get(f'/bulk/?tab={tab}').status_code == 200


@pytest.mark.parametrize("tab,href", [
    ("orders", "/orders/?tab=list"),
    ("cs", "/orders/?tab=cs"),
    ("stats", "/orders/?tab=margin"),
])
def test_기존_화면으로_가는_링크가_있다(client, tab, href):
    """다시 그리지 않고 잇는다 — 링크가 없으면 막다른 화면이 된다."""
    assert href in client.get(f'/bulk/?tab={tab}').get_data(as_text=True)


def test_왜_다시_안_그리는지_화면이_설명한다(client):
    """빈 것처럼 보이면 '왜 아무것도 없냐'가 된다 — 이유를 적어둔다."""
    html = client.get('/bulk/?tab=orders').get_data(as_text=True)
    assert '한 곳에만' in html


def test_주문탭은_등록경로로_갈라본다고_안내한다(client):
    """저장소를 안 나누는 대신 필터로 가른다는 게 설계 핵심이다."""
    assert '등록경로' in client.get('/bulk/?tab=orders').get_data(as_text=True)


def test_열여덟_탭_전부_200(client):
    from webapp.routes.bulk import SUBTABS
    for t in SUBTABS:
        r = client.get(f"/bulk/?tab={t['key']}")
        assert r.status_code == 200, f"{t['key']} 탭이 {r.status_code}"


def test_기존_주문화면은_그대로다(client):
    """대량등록 탭을 붙이다가 라이브 주문 화면을 깨뜨리지 않았는지."""
    for t in ('list', 'cs', 'margin', 'inspect'):
        assert client.get(f'/orders/?tab={t}').status_code == 200, f"/orders?tab={t}"

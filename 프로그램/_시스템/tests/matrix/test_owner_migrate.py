# -*- coding: utf-8 -*-
"""옵션 주인 이관 — 새 주인 칸 채우기(백필).

이관을 두 걸음으로 나눈다.
  2a (여기) — 옵션에 `matrix_option_id` 칸을 만들고 **채우기만** 한다.
              읽는 곳이 아직 없으므로 화면·크롤·전송은 하나도 안 바뀐다.
              → 기준 지문이 **그대로여야 한다**. 이게 이 단계의 안전 보증이다.
  2b (다음) — 읽는 곳을 새 칸으로 옮기고, `model_code` 를 비워도 되게 푼다.

🔴 되돌릴 수 있어야 한다 — 옛 칸(`model_code`)을 지우지 않는다.
"""
import pytest

from lemouton.matrix.owner_migrate import plan_backfill


class _Opt:
    def __init__(self, sku, model_code, matrix_option_id=None):
        self.canonical_sku = sku
        self.model_code = model_code
        self.matrix_option_id = matrix_option_id


def _origins():
    """model_code → 원본 매트릭스 id"""
    return {'르무통_메이트': 11, '르무통_레츠': 12}


def test_아직_안_붙은_옵션에만_새_주인을_붙인다():
    opts = [_Opt('SKU-A', '르무통_메이트'),
            _Opt('SKU-B', '르무통_메이트', matrix_option_id=11),
            _Opt('SKU-C', '르무통_레츠')]
    todo, skipped, missing = plan_backfill(opts, _origins())
    assert todo == [('SKU-A', 11), ('SKU-C', 12)]
    assert skipped == 1
    assert missing == []


def test_두_번_돌려도_아무_일_없다():
    """백필은 여러 번 불린다 — 두 번째부터는 붙일 게 없어야 한다."""
    opts = [_Opt('SKU-A', '르무통_메이트', matrix_option_id=11)]
    todo, skipped, missing = plan_backfill(opts, _origins())
    assert todo == []
    assert skipped == 1


def test_원본_매트릭스가_없는_모델은_조용히_넘기지_않는다():
    """🔴 조용히 건너뛰면 그 옵션만 주인이 없는 채 남아 나중에 전송에서 빠진다."""
    opts = [_Opt('SKU-Z', '어디에도_없는_모델')]
    todo, skipped, missing = plan_backfill(opts, _origins())
    assert todo == []
    assert missing == ['어디에도_없는_모델']


def test_이미_붙어_있는데_다른_주인이면_고치지_않고_알린다():
    """멋대로 갈아끼우면 사장님이 손으로 옮겨둔 것을 덮어쓴다."""
    opts = [_Opt('SKU-A', '르무통_메이트', matrix_option_id=99)]
    todo, skipped, missing = plan_backfill(opts, _origins())
    assert todo == []
    assert skipped == 1


def test_옵션에_새_칸이_실제로_있다():
    """모델에 칸이 없으면 백필이 조용히 아무것도 안 한다."""
    from lemouton.sourcing.models import Option
    assert hasattr(Option, 'matrix_option_id')


def test_새_칸은_비어_있어도_된다():
    """🔴 처음엔 전부 비어 있다. NOT NULL 이면 배포하는 순간 저장이 다 막힌다."""
    from lemouton.sourcing.models import Option
    assert Option.__table__.c.matrix_option_id.nullable is True


def test_옛_칸을_지우지_않는다():
    """되돌릴 수 있어야 한다."""
    from lemouton.sourcing.models import Option
    assert 'model_code' in Option.__table__.c


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_붙이기_창구가_지문을_지킨다(client):
    """🔴 이 걸음의 안전 보증 — 붙여도 기준 지문은 그대로여야 한다."""
    before = client.get('/api/admin/option-owner/snapshot').get_json()
    r = client.post('/api/admin/option-owner/backfill?all=1')
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j['ok'] is True
    assert j['unchanged'] is True
    after = client.get('/api/admin/option-owner/snapshot').get_json()
    assert before['overall'] == after['overall']


def test_두_번_불러도_새로_붙는_게_없다(client):
    client.post('/api/admin/option-owner/backfill?all=1')
    j = client.post('/api/admin/option-owner/backfill?all=1').get_json()
    assert j['attached'] == 0

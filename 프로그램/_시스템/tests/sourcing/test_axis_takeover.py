# -*- coding: utf-8 -*-
"""축 맞추기 「이미 쓰고 있다」에서 막히지 않는다 (2026-08-12 · 노션 옵션 c).

사장님 원문 — 「이미 한번 생성하고 취소했을떄, 다시 재매칭하려하니 이미 쓰고 있다고함.」

원인 (조사 확정)
  `source_axis_aliases` 는 **소싱처 전역 사전**이라 매트릭스에 매이지 않는다.
  매트릭스를 지워도 행이 남고(`optgen.api_delete_option_box` 는 models.model_code FK 를
  가진 표만 훑는데 이 표엔 그 FK 가 없다), 남은 행이 소싱처 표기를 붙잡는다.
  그런데 화면은 **지금 매트릭스의 축 값 줄만** 그리므로 그 유령은 화면에 안 나타나
  **놓아줄 방법이 없다** — 「먼저 그 줄에서 놓아야 합니다」가 가리킬 줄이 없다.

여기서 못 박는 것
  · 충돌하면 **누가 붙잡고 있고 그게 유령인지**를 응답이 말한다
  · `takeover:true` 로 빼앗을 수 있다
  · 빼앗아도 **1:1 은 그대로** — 재고 이중계상 방지라는 원래 목적이 안 깨진다
"""
import json

import pytest


@pytest.fixture
def client():
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


SRC = 'musinsa'
AXIS = '색상'


@pytest.fixture(autouse=True)
def _clean():
    """시험끼리 사전을 물려주지 않는다 — 이 표는 소싱처 전역이라 남으면 다음 시험이 샌다."""
    def wipe():
        from shared.db import SessionLocal
        from lemouton.sourcing.axis_alias import SourceAxisAlias
        from lemouton.sourcing.models import BundleOptionStep, Model
        s = SessionLocal()
        try:
            s.query(SourceAxisAlias).filter_by(source_key=SRC, axis_name=AXIS).delete()
            s.query(BundleOptionStep).filter_by(model_code='U-USER-1').delete()
            s.query(Model).filter_by(model_code='U-USER-1').delete()
            s.commit()
        finally:
            s.close()
    wipe()
    yield
    wipe()


def _set(client, our, src, takeover=False):
    return client.post('/api/bundles/ANY/axis-mapping', json={
        'source_key': SRC, 'axis_name': AXIS,
        'our_value': our, 'source_value': src, 'takeover': takeover})


def _aliases():
    from shared.db import SessionLocal
    from lemouton.sourcing import axis_alias as ax
    s = SessionLocal()
    try:
        return ax.list_aliases(s, SRC, AXIS)
    finally:
        s.close()


def test_유령이_붙잡고_있으면_그렇다고_말한다(client):
    """지워진 매트릭스가 남긴 행 — 어느 축 설계에도 안 쓰이는 값."""
    assert _set(client, '없어진검정', 'BLACK').status_code == 200
    r = _set(client, '검정', 'BLACK')
    assert r.status_code == 409
    c = r.get_json()['conflict']
    assert c['holder'] == '없어진검정'
    assert c['ghost'] is True, '아무도 안 쓰는데 유령이 아니라고 했다'
    assert c['holder_used_by'] == []


def test_빼앗아_오면_맞춰지고_1대1이_지켜진다(client):
    assert _set(client, '없어진검정', 'BLACK').status_code == 200
    r = _set(client, '검정', 'BLACK', takeover=True)
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j['ok'] and j['took_from'] == '없어진검정'

    rows = [a for a in _aliases() if a['source_value'] == 'BLACK']
    assert len(rows) == 1, f'같은 표기를 둘이 쓰면 재고가 두 배로 잡힌다: {rows}'
    assert rows[0]['our_value'] == '검정'


def test_쓰이는_중이면_어디서_쓰는지_알려준다(client):
    """유령이 아니면 빼앗기 전에 무엇을 잃는지 보여야 한다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import BundleOptionStep, Model

    s = SessionLocal()
    try:
        s.add(Model(model_code='U-USER-1', model_name_raw='쓰는 묶음',
                    model_name_display='쓰는 묶음', brand='르무통'))
        s.flush()
        s.add(BundleOptionStep(model_code='U-USER-1', step_no=1, axis_name=AXIS,
                               values_json=json.dumps(['진짜검정'], ensure_ascii=False)))
        s.commit()
    finally:
        s.close()

    assert _set(client, '진짜검정', 'BLACK').status_code == 200
    r = _set(client, '검정', 'BLACK')
    assert r.status_code == 409
    c = r.get_json()['conflict']
    assert c['ghost'] is False
    assert 'U-USER-1' in c['holder_used_by']


def test_안_빼앗으면_원래_주인이_그대로다(client):
    assert _set(client, '없어진검정', 'BLACK').status_code == 200
    _set(client, '검정', 'BLACK')                      # takeover 없이 → 409
    rows = [a for a in _aliases() if a['source_value'] == 'BLACK']
    assert len(rows) == 1 and rows[0]['our_value'] == '없어진검정'

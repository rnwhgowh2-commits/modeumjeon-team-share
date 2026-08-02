# -*- coding: utf-8 -*-
"""모음전 삭제 — 라이브에서 FK 위반으로 막히던 것.

🔴 라이브 실측 2026-08-02: 모음전 삭제 →
   `ForeignKeyViolation: ... violates foreign key constraint
    "matrix_options_model_code_fkey" on table "matrix_options"`.

원인은 옵션 삭제·이름변경과 같다 — **지울 표 목록을 손으로 적어서 뒤처졌다.**
model_code 를 가리키는 표 10곳 중 5곳만 지우고 있었다
(matrix_options·product_sets·set_products·bundle_matrix_links·bundle_policy_links 누락).

로컬 SQLite 는 FK 를 느슨하게 봐서 그냥 통과한다 → 지도 검사를 따로 둔다.
"""
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_모음전을_가리키는_표가_전부_삭제_대상에_들어간다():
    """손으로 적으면 뒤처진다 — 실제로 5곳이 빠져 있었다."""
    from lemouton.sourcing.fk_map import model_child_columns
    from shared.db import Base

    declared = {
        (t.name, c.name)
        for t in Base.metadata.sorted_tables
        for c in t.columns
        for fk in c.foreign_keys
        if fk.target_fullname == 'models.model_code' and t.name != 'options'
    }
    assert declared, 'FK 선언을 하나도 못 찾음'
    missing = declared - set(model_child_columns())
    assert not missing, f'삭제 대상에서 빠진 표: {sorted(missing)}'


def test_모음전을_지우면_딸린_행도_같이_사라진다(client):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option, BundleSourceUrl

    code = f'모음전삭제시험_{uuid.uuid4().hex[:8]}'
    sku = f'{code}-블랙-250'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=code, brand='르무통'))
        s.flush()
        s.add(Option(canonical_sku=sku, boxhero_sku=sku, model_code=code,
                     color_code='블랙', size_code='250'))
        s.add(BundleSourceUrl(model_code=code, source_key='lemouton',
                              url='https://example.com/del'))
        s.commit()
    finally:
        s.close()

    r = client.post(f'/api/bundles/{code}/delete')
    assert r.status_code == 200, r.get_data(as_text=True)

    s = SessionLocal()
    try:
        assert s.get(Model, code) is None, '모음전이 안 지워졌다'
        assert s.get(Option, sku) is None, '옵션이 남았다'
        assert s.query(BundleSourceUrl).filter_by(model_code=code).count() == 0
    finally:
        s.close()

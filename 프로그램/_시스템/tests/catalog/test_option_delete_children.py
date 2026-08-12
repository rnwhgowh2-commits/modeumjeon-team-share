# -*- coding: utf-8 -*-
"""옵션 1개 지우기 — 라이브(PostgreSQL)에서 항상 500 이던 것.

🔴 이 저장소의 재발 패턴: **로컬 SQLite 는 FK 를 느슨하게 봐서 삭제 결함이 그냥 통과**하고,
   라이브 PostgreSQL 만 거부한다. 그래서 여기서는 두 가지를 따로 못 박는다.

   ① SQLite 전용 문(PRAGMA)을 라우트가 들고 있으면 안 된다.
      PostgreSQL 에는 PRAGMA 가 없어 문법 오류 → 트랜잭션 abort → 뒤 문이 전부 실패한다.
      (실측 2026-08-02: 라이브에서 옵션 6개 삭제 시도 → 6건 모두 internal_error)
   ② 지울 자식 표 목록을 **손으로 적지 않는다**. 실제로 4개 표가 빠져 있었고
      그중 둘(matrix_option_members·set_options)은 ondelete 가 없어 삭제를 막는다.
"""
import pathlib


import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_옵션_삭제_경로에_SQLite_전용_PRAGMA_가_없다():
    """① PostgreSQL 에서 문법 오류를 내는 문이 라우트에 남아 있으면 안 된다.

    실제로 실행되는 문자열만 본다 (주석·설명글의 'PRAGMA' 글자는 무해).
    """
    import ast

    from webapp.routes import api as api_mod
    tree = ast.parse(pathlib.Path(api_mod.__file__).read_text(encoding='utf-8'))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == 'options_delete'), None)
    assert fn is not None, 'options_delete 를 찾지 못함'

    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    literals = [n.value for stmt in body for n in ast.walk(stmt)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    offenders = [v for v in literals if 'PRAGMA' in v.upper()]
    assert not offenders, (
        f'options_delete 가 SQLite 전용 문을 보내고 있다: {offenders} — '
        'PostgreSQL 라이브에서 트랜잭션이 깨진다'
    )


def test_FK_를_건_표는_전부_정리_대상에_들어간다():
    """② 목록을 손으로 적으면 뒤처진다 — metadata 에서 뽑았는지 확인."""
    from webapp.routes.api import _option_child_columns
    from shared.db import Base

    declared = {
        (t.name, c.name)
        for t in Base.metadata.sorted_tables
        for c in t.columns
        for fk in c.foreign_keys
        if fk.target_fullname == 'options.canonical_sku'
    }
    assert declared, 'FK 선언을 하나도 못 찾음 — 모델 import 가 빠졌는지 확인'
    missing = declared - set(_option_child_columns())
    assert not missing, f'정리 대상에서 빠진 표: {sorted(missing)}'


def test_옵션을_지우면_자식_행도_같이_사라진다(client):
    """실제 삭제 — 자식 행이 붙어 있어도 200 이고, 자식도 같이 지워진다."""
    import uuid
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option, OptionInventoryLink

    code = f'옵션삭제시험_{uuid.uuid4().hex[:8]}'
    sku = f'SKU-{uuid.uuid4().hex[:8].upper()}'
    other = f'SKU-{uuid.uuid4().hex[:8].upper()}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=code, brand='르무통'))
        s.flush()
        s.add(Option(canonical_sku=sku, model_code=code,
                     color_code='블랙', size_code='250'))
        s.add(Option(canonical_sku=other, model_code=code,
                     color_code='화이트', size_code='250'))
        s.flush()
        # 자식 행 — 예전 목록에 없던 표(option_inventory_links)로 일부러 건다
        s.add(OptionInventoryLink(bundle_option_sku=sku, inventory_option_sku=other))
        s.commit()
    finally:
        s.close()

    r = client.post(f'/api/bundles/{code}/options/{sku}/delete')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['ok'] is True

    s = SessionLocal()
    try:
        assert s.get(Option, sku) is None, '옵션이 안 지워졌다'
        assert s.get(Option, other) is not None, '남의 옵션까지 지웠다'
        left = (s.query(OptionInventoryLink)
                .filter(OptionInventoryLink.bundle_option_sku == sku).count())
        assert left == 0, '자식 행(option_inventory_links)이 남았다'
    finally:
        s.close()


def test_없는_옵션은_404_고_500_이_아니다(client):
    r = client.post('/api/bundles/없는모음전/options/SKU-NOPE0000/delete')
    assert r.status_code == 404, r.get_data(as_text=True)


# ── [2026-08-13 감사 후속] 재고 이력이 지도에 없어 유령으로 남던 것 ──────────
def test_옵션을_가리키는_비FK_칸도_지도에_있다():
    """🔴 `option_canonical_sku` 는 이름이 옵션을 가리키는데 FK 가 아니라 지도에 안 잡혔다.

    지우기·이름변경이 **같은 지도**를 보므로, 빠지면 낱개 옵션을 지울 때 재고 이력이
    유령으로 남고(같은 SKU 가 다시 발급되면 없던 재고가 되살아난다),
    이름을 바꾸면 이력이 옛 SKU 에 남아 끊긴다.
    묶음 지우기(optgen._purge_option_traces)는 이미 치우고 있었다 — 경로마다 규칙이 달랐다.
    """
    from lemouton.sourcing.fk_map import option_child_columns
    have = set(option_child_columns())
    for t in ('inventory_txs', 'inventory_safety_stock',
              'inventory_count_sheet_items', 'item_attribute_values'):
        assert (t, 'option_canonical_sku') in have, f'{t} 가 지도에 없다 — 고아가 남는다'


def test_남의_열쇠는_지도에_넣지_않는다():
    """🔴 이름이 `canonical_sku` 라고 다 옵션이 아니다 — 넣으면 **남의 데이터를 지운다.**

    inventory_products·sourcing_options 는 자기 자신의 열쇠다.
    """
    from lemouton.sourcing.fk_map import option_child_columns
    have = set(option_child_columns())
    for t in ('inventory_products', 'sourcing_options', 'options'):
        assert (t, 'canonical_sku') not in have, f'{t} 는 자기 열쇠다 — 지우면 안 된다'

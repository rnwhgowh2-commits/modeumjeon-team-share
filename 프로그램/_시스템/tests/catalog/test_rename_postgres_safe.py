# -*- coding: utf-8 -*-
"""이름·코드 변경 — 라이브(PostgreSQL)에서 실패하던 것.

옵션 삭제(PR#672)와 같은 부류다. 두 겹이 아니라 **세 겹**이었다.

  ① SQLite 전용 `PRAGMA` 를 그대로 보냈다 → PG 는 문법 오류 → 트랜잭션 abort.
  ② PRAGMA 를 걷어내도 **PK 를 제자리에서 바꾸는 방식 자체가 PG 에선 불가능**하다.
     자식이 옛 값을 가리키는 동안 부모 PK 를 UPDATE 하면 FK 위반이다.
     → 새 행 만들기 → 자식 옮기기 → 옛 행 지우기 순서라야 성립한다.
  ③ 옮길 표 목록이 손으로 적혀 있어 절반 넘게 빠져 있었다
     (model_code 를 가리키는 표 10곳 중 3곳만 갱신).

🔴 로컬 SQLite 는 FK 를 느슨하게 봐서 ①②③ 전부 그냥 통과한다. 그래서 정적 가드와
   지도 검사를 따로 둔다.
"""
import ast
import pathlib
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _executed_strings(path: pathlib.Path, func_name: str) -> list[str]:
    """함수 본문에서 **실제로 실행되는** 문자열 상수만 (docstring 제외)."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    assert fn is not None, f'{func_name} 를 찾지 못함'
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    return [n.value for stmt in body for n in ast.walk(stmt)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_옵션_코드_변경에_SQLite_전용_PRAGMA_가_없다():
    from webapp.routes import api as api_mod
    bad = [v for v in _executed_strings(pathlib.Path(api_mod.__file__), 'options_rename')
           if 'PRAGMA' in v.upper()]
    assert not bad, f'options_rename 이 SQLite 전용 문을 보낸다: {bad}'


def test_모음전_코드_변경에_SQLite_전용_PRAGMA_가_없다():
    from lemouton.sourcing import rename as rn
    bad = [v for v in _executed_strings(pathlib.Path(rn.__file__), 'rename_model_code')
           if 'PRAGMA' in v.upper()]
    assert not bad, f'rename_model_code 가 SQLite 전용 문을 보낸다: {bad}'


def test_모음전을_가리키는_표가_전부_옮김_대상에_들어간다():
    """③ 손으로 적으면 뒤처진다 — 10곳 중 3곳만 갱신하던 것이 이 결함이었다."""
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
    assert not missing, f'옮김 대상에서 빠진 표: {sorted(missing)}'


def _mk_bundle(colors=('블랙',), sizes=('250',)):
    """모음전 1개 + 옵션 + 자식 행을 만든다."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import (
        Model, Option, OptionInventoryLink, BundleSourceUrl,
    )
    code = f'이름변경시험_{uuid.uuid4().hex[:8]}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=code, brand='르무통'))
        s.flush()
        skus = []
        for c in colors:
            for z in sizes:
                sku = f'{code}-{c}-{z}'
                s.add(Option(canonical_sku=sku, boxhero_sku=sku, model_code=code,
                             color_code=c, size_code=z))
                skus.append(sku)
        s.flush()
        # 자식 행 — 옛 목록에 없던 표로 일부러 건다
        s.add(OptionInventoryLink(bundle_option_sku=skus[0],
                                  inventory_option_sku=skus[0]))
        s.add(BundleSourceUrl(model_code=code, source_key='lemouton',
                              url='https://example.com/x'))
        s.commit()
        return code, skus
    finally:
        s.close()


def test_옵션_코드를_바꾸면_자식도_따라간다(client):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option, OptionInventoryLink

    code, skus = _mk_bundle()
    old = skus[0]
    r = client.post(f'/api/bundles/{code}/options/{old}/rename',
                    json={'new_color': '화이트', 'new_size': '260'})
    assert r.status_code == 200, r.get_data(as_text=True)
    new = r.get_json()['new_sku']

    s = SessionLocal()
    try:
        assert s.get(Option, old) is None, '옛 옵션이 남았다'
        moved = s.get(Option, new)
        assert moved is not None, '새 옵션이 안 만들어졌다'
        assert (moved.color_code, moved.size_code) == ('화이트', '260')
        assert moved.boxhero_sku == new, '자체 SKU = 박스히어로 SKU 규칙이 깨졌다'
        assert s.query(OptionInventoryLink).filter(
            OptionInventoryLink.bundle_option_sku == old).count() == 0
        assert s.query(OptionInventoryLink).filter(
            OptionInventoryLink.bundle_option_sku == new).count() == 1, '자식이 안 따라왔다'
    finally:
        s.close()


def test_모음전_코드를_바꾸면_옵션과_자식이_전부_따라간다(client):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import (
        Model, Option, OptionInventoryLink, BundleSourceUrl,
    )

    code, skus = _mk_bundle(colors=('블랙', '화이트'), sizes=('250', '260'))
    new_code = f'바뀐코드_{uuid.uuid4().hex[:8]}'
    r = client.post(f'/api/bundles/{code}/rename', json={'new_code': new_code})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['options_updated'] == 4

    s = SessionLocal()
    try:
        assert s.get(Model, code) is None, '옛 모음전이 남았다'
        assert s.get(Model, new_code) is not None, '새 모음전이 없다'
        assert s.query(Option).filter_by(model_code=code).count() == 0
        assert s.query(Option).filter_by(model_code=new_code).count() == 4
        # 옛 목록에 없던 표들도 따라와야 한다
        assert s.query(BundleSourceUrl).filter_by(model_code=code).count() == 0, \
            'bundle_source_urls 가 안 따라왔다 (옛 목록 누락분)'
        assert s.query(BundleSourceUrl).filter_by(model_code=new_code).count() == 1
        assert s.query(OptionInventoryLink).filter(
            OptionInventoryLink.bundle_option_sku == skus[0]).count() == 0
        assert s.query(OptionInventoryLink).filter(
            OptionInventoryLink.bundle_option_sku.like(f'{new_code}-%')).count() == 1
    finally:
        s.close()


def test_이미_있는_코드로는_못_바꾼다(client):
    code_a, _ = _mk_bundle()
    code_b, _ = _mk_bundle()
    r = client.post(f'/api/bundles/{code_a}/rename', json={'new_code': code_b})
    assert r.status_code == 409, r.get_data(as_text=True)

# -*- coding: utf-8 -*-
"""`/optgen/api/box/<code>/detail-card` — [2026-08-19] 「SKU 연결상태」·「소싱처」
호버 카드가 같이 쓰는 창구.

이 파일이 지키는 것
  ① 옵션(SKU) 마다 브랜드·모델·색상·사이즈가 실린다 — 원본 지시의 "필수" 다섯.
  ② 사이즈 축이 없는(색상만인) 묶음은 사이즈가 「free」다 — "1개면 free" 지시.
  ③ 소싱처 URL 목록이 실리고, 없는 묶음이면 빈 목록이지 에러가 아니다.
  ④ 없는 묶음은 404 + 한국어 사유.
  ⑤ 모델명은 `box()`(옵션함 상세 페이지)와 **같은 값**이어야 한다 — 같은 사실은
     한 곳(`model_name_of`)에서만 계산해서, 상세 페이지와 목록 호버가 안 갈린다.
"""
import json
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _옵션함(code, name, *, 축, 옵션, 주소=(), brand='르무통'):
    from shared.db import SessionLocal
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import BundleOptionStep, BundleSourceUrl, Model, Option

    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=name, model_name_display=name,
                    brand=brand, is_option_box=True))
        mo = MatrixOption(kind=KIND_ORIGIN, model_code=code, name=name, display_no=code)
        s.add(mo)
        s.flush()
        for i, (axis_name, values) in enumerate(축, start=1):
            s.add(BundleOptionStep(model_code=code, step_no=i, axis_name=axis_name,
                                   values_json=json.dumps(values, ensure_ascii=False)))
        for sku, combo in 옵션:
            rest = [v for (an, _v), v in zip(축, combo) if an != '모델']
            s.add(Option(canonical_sku=sku, model_code=code, matrix_option_id=mo.id,
                         display_no=f'{code}-{sku[-2:]}',
                         color_code=(rest[0] if len(rest) > 0 else ''),
                         color_display=(rest[0] if len(rest) > 0 else ''),
                         size_code=(rest[1] if len(rest) > 1 else ''),
                         size_display=(rest[1] if len(rest) > 1 else ''),
                         axis_values_json=json.dumps(combo, ensure_ascii=False), brand=brand))
        for i, (src, url) in enumerate(주소):
            s.add(BundleSourceUrl(model_code=code, source_key=src, url=url,
                                  label=None, url_type='단품', sort_order=i))
        s.commit()
    finally:
        s.close()
    return code


def _지우기(code):
    from shared.db import SessionLocal
    from lemouton.matrix.models import MatrixOption
    from lemouton.sourcing.models import BundleOptionStep, BundleSourceUrl, Model, Option
    s = SessionLocal()
    try:
        s.rollback()
        for 표, 칸 in ((BundleSourceUrl, BundleSourceUrl.model_code),
                      (BundleOptionStep, BundleOptionStep.model_code),
                      (Option, Option.model_code), (MatrixOption, MatrixOption.model_code)):
            s.query(표).filter(칸 == code).delete(synchronize_session=False)
        s.query(Model).filter(Model.model_code == code).delete(synchronize_session=False)
        s.commit()
    finally:
        s.close()


def test_옵션마다_필수_다섯_값이_실린다(client):
    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-DC{tag}'
    try:
        _옵션함(code, f'상세카드{tag}', 축=[('색상', ['블랙']), ('사이즈', ['250'])],
               옵션=[(f'SKU-DC{tag}00', ['블랙', '250'])], brand='나이키')
        r = client.get(f'/optgen/api/box/{code}/detail-card')
        assert r.status_code == 200, r.get_data(as_text=True)
        j = r.get_json()
        assert j['ok'] is True
        assert len(j['options']) == 1
        o = j['options'][0]
        assert o['sku'] == f'SKU-DC{tag}00'
        assert o['brand'] == '나이키'
        assert o['color'] == '블랙'
        assert o['size'] == '250'
    finally:
        _지우기(code)


def test_사이즈_축이_없으면_free다(client):
    """🔴 원본 지시 "사이즈(1개면 free)" — 색상만 있는 묶음엔 사이즈 축 자체가 없다."""
    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-DCF{tag}'
    try:
        _옵션함(code, f'프리사이즈{tag}', 축=[('색상', ['블랙'])],
               옵션=[(f'SKU-DCF{tag}00', ['블랙'])])
        r = client.get(f'/optgen/api/box/{code}/detail-card')
        assert r.get_json()['options'][0]['size'] == 'free'
    finally:
        _지우기(code)


def test_모델명은_box_상세페이지와_같은_값이다(client):
    """🔴 같은 사실은 한 곳(model_name_of)에서만 — 상세 페이지·목록 호버가 갈리면 안 된다."""
    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-DCM{tag}'
    try:
        _옵션함(code, f'모델비교{tag}', 축=[('모델', ['메이트']), ('색상', ['블랙'])],
               옵션=[(f'SKU-DCM{tag}00', ['메이트', '블랙'])])
        카드 = client.get(f'/optgen/api/box/{code}/detail-card').get_json()
        상세 = client.get(f'/optgen/box/{code}').get_data(as_text=True)
        모델명 = 카드['options'][0]['model']
        assert 모델명, 'model_name_of 가 빈 값을 냈다'
        assert 모델명 in 상세, f'호버 카드 모델명({모델명!r})이 상세 페이지에 없다 — 원천이 갈렸다'
    finally:
        _지우기(code)


def test_소싱처_URL_목록이_실린다(client):
    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-DCS{tag}'
    try:
        _옵션함(code, f'주소목록{tag}', 축=[('색상', ['블랙'])],
               옵션=[(f'SKU-DCS{tag}00', ['블랙'])],
               주소=[('musinsa', 'https://musinsa.example.com/a'),
                    ('lotteon', 'https://lotteon.example.com/b')])
        j = client.get(f'/optgen/api/box/{code}/detail-card').get_json()
        assert len(j['sources']) == 2
        assert {u['url'] for u in j['sources']} == {
            'https://musinsa.example.com/a', 'https://lotteon.example.com/b'}
    finally:
        _지우기(code)


def test_소싱처가_없으면_빈_목록이지_에러가_아니다(client):
    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-DCE{tag}'
    try:
        _옵션함(code, f'주소없음{tag}', 축=[('색상', ['블랙'])],
               옵션=[(f'SKU-DCE{tag}00', ['블랙'])])
        j = client.get(f'/optgen/api/box/{code}/detail-card').get_json()
        assert j['ok'] is True
        assert j['sources'] == []
    finally:
        _지우기(code)


def test_없는_묶음은_404다(client):
    r = client.get('/optgen/api/box/U19700101-000000/detail-card')
    assert r.status_code == 404
    err = r.get_json()['error']
    assert any('가' <= ch <= '힣' for ch in err), '사유가 한국어가 아니다'

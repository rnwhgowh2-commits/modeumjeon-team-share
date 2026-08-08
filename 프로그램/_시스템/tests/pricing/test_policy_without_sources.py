# -*- coding: utf-8 -*-
"""정책은 붙었는데 소싱처 주소가 하나도 없는 상품 — 편집 화면이 터지면 안 된다.

2026-08-08 라이브 실측: 상품 91개 중 **딱 1개**(`르무통_르무통_메이트_스니커즈_test`)
에서 편집 화면이 「internal_error」 알림을 띄웠다. 그 상품만 남달랐던 점 =
**소싱처 연결 0줄인데 정책이 붙어 있음**(다른 90개는 둘 중 하나가 없음).
"""
import uuid

import pytest


@pytest.fixture
def 정책만_붙은상품():
    from shared.db import SessionLocal
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:6]
    code = f'정책만_{tag}'
    s = SessionLocal()
    pol = None
    try:
        s.add(Model(model_code=code, model_name_raw=code,
                    model_name_display=code, brand='르무통'))
        for i, (색, 사이즈) in enumerate((('블랙', '230'), ('블랙', '240'),
                                          ('그레이', '230'))):
            s.add(Option(canonical_sku=f'SKU_{tag}_{i}', model_code=code,
                         color_code=색, size_code=사이즈))
        pol = MarketPolicy(name=f'정책_{tag}')
        s.add(pol)
        s.flush()
        s.add(BundlePolicyLink(model_code=code, policy_id=pol.id))
        s.commit()
        yield code
    finally:
        s.query(BundlePolicyLink).filter(
            BundlePolicyLink.model_code == code).delete(synchronize_session=False)
        if pol is not None:
            s.query(MarketPolicy).filter(
                MarketPolicy.id == pol.id).delete(synchronize_session=False)
        s.query(Option).filter(Option.model_code == code).delete(synchronize_session=False)
        s.query(Model).filter(Model.model_code == code).delete(synchronize_session=False)
        s.commit()
        s.close()


def test_소싱처가_없어도_옵션표가_터지지_않는다(정책만_붙은상품):
    """🔴 터지면 편집 화면이 「internal_error」 알림만 띄우고 아무것도 못 하게 된다."""
    from webapp.routes.api_pricing import _option_matrix_data

    d = _option_matrix_data(정책만_붙은상품)
    assert d.get('ok'), f'옵션표를 못 만든다: {d}'
    assert len(d.get('options') or []) == 3, \
        f'심은 옵션 3개가 안 나온다 — 시험이 헛돈다: {d.get("options")}'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_옵션표가_터지면_까닭을_말한다(client, monkeypatch):
    """🔴 터지는 것보다 **왜 터졌는지 안 말하는 것**이 더 나쁘다.

    2026-08-08 라이브: 상품 91개 중 1개가 여기서 500 을 냈는데 화면엔
    「internal_error」 다섯 글자뿐이고 서버에도 아무것도 안 남아 못 고쳤다.
    """
    from webapp.routes import api_pricing as P

    def 터뜨리기(*a, **k):
        raise ValueError('일부러 터뜨림')

    monkeypatch.setattr(P, '_option_matrix_data', 터뜨리기)
    r = client.get('/api/bundles/아무거나/option-matrix')
    assert r.status_code == 500
    글 = r.get_json().get('error') or ''
    assert 'internal_error' != 글, '빈 「internal_error」 로만 답하면 아무도 못 고친다'
    assert 'ValueError' in 글 and '일부러 터뜨림' in 글, \
        f'무엇이 왜 터졌는지 안 나온다: {글!r}'

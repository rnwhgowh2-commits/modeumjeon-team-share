# -*- coding: utf-8 -*-
"""「판매처 관리」 등록 설정 화면 — 서버만 되고 화면엔 안 나오는 일을 막는다.

이 프로젝트에서 반복적으로 났던 사고: API 는 되는데 화면에 버튼·칸이 없어
사장님은 「안 된다」고 느끼고, 코드만 본 사람은 「됐다」고 보고한다.
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


def _account(client, market='lotteon', key='르무통_롯데'):
    from lemouton.sourcing.models_v2 import UploadAccount
    s = client._Session()
    try:
        acc = UploadAccount(account_key=f'{key}_{market}', display_name=key,
                            market=market, env_prefix=f'{key}_{market}'.upper())
        s.add(acc)
        s.commit()
        return acc.id
    finally:
        s.close()


def _html(client):
    r = client.get('/accounts/upload')
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_계정_줄에_설정_버튼이_보인다(client):
    _account(client)
    html = _html(client)
    assert 'openAccountSettings(' in html
    assert '> 설정<' in html or '설정</button>' in html


def test_설정_창이_화면에_있다(client):
    _account(client)
    html = _html(client)
    assert 'as-modal-bg' in html
    assert '등록 설정' in html


def test_저장_단추가_있다(client):
    _account(client)
    html = _html(client)
    assert 'submitAccountSettings()' in html


def test_안_정함과_0원_구분을_화면이_안내한다(client):
    """🔴 사장님이 이 구분을 모르면 빈 칸과 0 을 헷갈린다."""
    _account(client)
    html = _html(client)
    assert '안 정함' in html
    assert '0원' in html


def test_쿠팡은_출고지를_여기서_안_만든다고_안내한다(client):
    """이미 「쿠팡 계정정보」가 갖고 있다 — 두 벌이면 어느 쪽이 나갔는지 못 쫓는다."""
    _account(client, market='coupang', key='르무통_쿠팡')
    html = _html(client)
    assert '쿠팡 계정정보' in html


def test_재고_기본값_칸은_안_그린다(client):
    """🔴 「재고는 소싱처 실제 재고로만」 — 기본값 칸을 두면 없는 재고를 판다.

    ★ 이름이 나오는지가 아니라 **입력칸이 그려지는지**를 본다.
      주석으로 「일부러 안 그린다」고 적어 둔 것까지 걸리면 거짓 경보가 되고,
      그 경보 때문에 진짜 문제를 놓친다(2026-08-24 실제로 걸렸다).
    """
    _account(client)
    html = _html(client)
    assert 'data-as-key="stock_default"' not in html
    assert 'data-as-key="stockQuantity"' not in html
    # 화면이 그리는 칸 목록에도 없어야 한다
    assert "'stock_default'" not in html.split('AS_COL_ORDER')[1].split(']')[0]


def test_기존_키_버튼이_그대로_있다(client):
    """회귀 — 설정 버튼을 더하면서 기존 버튼을 밀어내지 않았나."""
    _account(client)
    html = _html(client)
    assert 'openSecretsModal(' in html


def test_모든_마켓_전용칸에_한글이름이_있다(client):
    """🔴 [2026-08-24 실화면에서 잡음] 서버는 칸을 내려보내는데 화면엔 영어가 떴다.

    `reviewMonthPhotoPoint` 같은 칸 4개가 이름 없이 그대로 나왔다. 시험 59건이
    전부 통과했는데도 그랬다 — **눈으로 봐야만** 걸리는 종류였다.
    그래서 「칸을 늘리면 이름도 같이 늘어난다」를 여기서 잠근다.
    """
    import re

    from lemouton.policy.account_settings import MARKET_EXTRA_KEYS

    html = _html(client)
    블록 = html.split('const AS_EXTRA_LABEL')[1].split('};')[0]
    이름있는칸 = set(re.findall(r"(\w+)\s*:\s*'", 블록))

    빠진칸 = {}
    for 마켓, 칸들 in MARKET_EXTRA_KEYS.items():
        모자란것 = sorted(set(칸들) - 이름있는칸)
        if 모자란것:
            빠진칸[마켓] = 모자란것
    assert not 빠진칸, f'한글 이름이 없어 화면에 영어로 뜨는 칸: {빠진칸}'

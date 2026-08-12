# -*- coding: utf-8 -*-
"""정책 생성 화면 「필수」 표시 + 「실제로 나가는가」 표시.

이 표가 지키는 것은 하나다 — **모르는 것을 「필수 아님」으로 말하지 않는다.**
빈칸을 안 채워도 된다고 잘못 안내하면, 사장님이 그대로 올렸다가 마켓이 거부한다.
그건 화면이 거짓말을 한 것이다.
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')

from lemouton.policy.fields import MARKET_KEYS, items_for       # noqa: E402
from lemouton.policy import required as R                        # noqa: E402


# ── 표 자체 ────────────────────────────────────────────────────────────

def test_모든_마켓_모든_항목이_판정을_가진다():
    """빠진 칸이 하나도 없어야 한다 — 빠지면 화면이 아무 말도 못 한다."""
    for mk in MARKET_KEYS:
        for it in items_for(mk):
            st, ev, note = R.status_of(mk, it['key'])
            assert st in (R.REQUIRED, R.CONDITIONAL, R.OPTIONAL, R.UNKNOWN), (mk, it['key'])
            # 근거든 사유든 **뭐라도 말이 있어야** 한다. 빈 배지는 근거 없는 단정이다.
            assert (ev or note), f'{mk}.{it["key"]} 에 근거도 사유도 없다'


def test_모르는_칸은_필수아님이_아니라_확인불가():
    """표에 없는 조합을 「선택」으로 돌려주면 그게 곧 거짓 안내다."""
    st, ev, note = R.status_of('smartstore', '_아직_없는_항목')
    assert st == R.UNKNOWN
    assert '찾지 못했' in note

    st2, _, note2 = R.status_of('없는마켓', 'name')
    assert st2 == R.UNKNOWN
    assert note2


@pytest.mark.parametrize('item_key', ['name', 'price', 'options', 'images', 'detail',
                                      'shipping', 'notice', 'brand', 'origin', 'kc', 'tags'])
def test_롯데온은_확인불가_그리고_이유를_말한다(item_key):
    """롯데온 등록 문서는 요약본이다. 「필수 아님」으로 읽히면 안 된다."""
    st, _, note = R.status_of('lotteon', item_key)
    assert st == R.UNKNOWN, f'롯데온 {item_key} 를 단정하고 있다'
    assert '확인 불가' in note or '요약본' in note


def test_롯데온_카테고리만은_필수로_확인됐다():
    """요약본에도 별표가 붙은 칸은 있다 — 그건 근거가 있으니 필수로 말한다."""
    st, ev, _ = R.status_of('lotteon', 'category')
    assert st == R.REQUIRED
    assert 'scatNo' in ev


def test_근거는_지도_원문을_그대로_담는다():
    """요약하면 어디까지가 마켓 말인지 사라진다."""
    _, ev, _ = R.status_of('eleven11', 'name')
    assert '요청.prdNm' in ev and '[필수]' in ev
    _, ev2, _ = R.status_of('coupang', 'name')
    assert 'sellerProductName' in ev2


def test_십일번가만_브랜드가_필수다():
    """6마켓 중 브랜드를 요구하는 곳은 11번가뿐 — 실등록 코드도 그렇게 막는다."""
    assert R.status_of('eleven11', 'brand')[0] == R.REQUIRED
    for mk in ('smartstore', 'coupang', 'auction', 'gmarket'):
        assert R.status_of(mk, 'brand')[0] != R.REQUIRED, mk


def test_실등록과_어긋나는_칸은_어긋난다고_적혀_있다():
    """문서만 보고 「필수」라고 하면 우리 실등록 실적과 모순된다.

    · 스스 배송 — deliveryFee 는 [필수] 지만 선택 묶음(deliveryInfo) 안이고,
      우리 두 등록 경로 모두 그 묶음을 안 보낸다 → 조건부.
    · 스스 옵션 — 평면 재고로도 등록된다 → 조건부.
    · 11번가 KC — 문서는 [필수] 인데 우리 XML 은 안 보내고도 통과했다 → 사실을 병기.
    """
    assert R.status_of('smartstore', 'shipping')[0] == R.CONDITIONAL
    assert R.status_of('smartstore', 'options')[0] == R.CONDITIONAL
    st, _, note = R.status_of('eleven11', 'kc')
    assert st == R.REQUIRED
    assert '실등록은 이 칸 없이 통과' in note


def test_옥션도_사이트부담_지원할인이_필수다():
    """지도·실코드 둘 다 옥션(iac)을 필수로 보낸다.

    `fields.EXTRA_ITEMS` 의 `_site_discount` 는 only=['gmarket','lotteon'] 이라
    **옥션 탭에 이 항목이 안 뜬다.** 표는 먼저 사실을 말해 둔다.
    """
    st, ev, _ = R.status_of('auction', '_site_discount')
    assert st == R.REQUIRED
    assert 'iac' in ev


# ── 배선 진단 ──────────────────────────────────────────────────────────

def test_지금_밖으로_나가는_항목은_판매가와_배송뿐():
    assert R.wiring_of('price')[0] == R.WIRED
    assert R.wiring_of('shipping')[0] == R.WIRED
    for k in ('name', 'category', 'options', 'images', 'detail', 'notice',
              'brand', 'origin', 'kc', 'banned_words', 'tags'):
        st, note = R.wiring_of(k)
        assert st == R.STORED_ONLY, k
        assert '저장만' in note


def test_요약은_필수인데_안_정한_항목을_센다():
    keys = [it['key'] for it in items_for('smartstore')]
    got = R.summary_for('smartstore', keys, values={'price': {'x': 1}})
    assert got['required'] >= 1
    assert 'price' not in got['missing']        # 정했으니 빠져야 한다
    assert 'name' in got['missing']             # 안 정했으니 남아야 한다
    assert got['stored_only'] >= 1


# ── 화면 ───────────────────────────────────────────────────────────────

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


def _정책하나(client):
    from lemouton.policy.service import create_policy
    s = client._Session()
    try:
        p = create_policy(s, name='테스트 정책')
        s.commit()
        return p.id
    finally:
        s.close()


def test_화면에_필수_배지가_뜬다(client):
    pid = _정책하나(client)
    html = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert '필수' in html
    assert 'req must' in html            # 배지가 실제로 그려졌나


def test_화면이_전송_안_되는_항목을_말한다(client):
    """13항목을 다 채워도 지금 나가는 건 둘뿐 — 화면이 그 사실을 말해야 한다."""
    pid = _정책하나(client)
    html = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert '판매가' in html and '배송' in html
    assert '저장만 됩니다' in html or '저장만' in html
    assert 'wire on' in html             # 「전송됨」 초록 배지


def test_롯데온_화면은_확인불가라고_말한다(client):
    pid = _정책하나(client)
    html = client.get(f'/policies/{pid}?m=lotteon').get_data(as_text=True)
    assert '확인 불가' in html
    assert 'req unk' in html


def test_마켓공통_탭에는_필수배지가_안_뜬다(client):
    """「마켓 공통」은 마켓이 아니다 — 어느 마켓 기준인지 정해지지 않았다."""
    pid = _정책하나(client)
    html = client.get(f'/policies/{pid}?m=common').get_data(as_text=True)
    assert 'req must' not in html
    assert 'req unk' not in html


# ── [2026-08-12] 엑셀 대조로 추가한 항목의 「필수」 근거 ──────────────────────
#   사장님 질문 — 「필수면 이전 코드에도 필수표시 해두라고 되어있었지?」
#   그렇다. 판정 근거는 **마켓 상품등록 API 원문 하나뿐**이고, 근거를 못 찾으면
#   「필수 아님」이 아니라 「확인 불가」로 둔다. 새 항목도 같은 규칙을 따른다.

def test_새_항목도_근거_없이_필수라고_하지_않는다():
    from lemouton.policy import required as R
    from lemouton.policy.fields import MARKET_KEYS
    for key in ('listing', 'price_compare', 'ids'):
        for mk in MARKET_KEYS:
            state, evidence, note = R.status_of(mk, key)
            if state == R.REQUIRED:
                assert evidence.strip(), f'{mk}/{key} — 필수라면서 근거가 비었다'


def test_롯데온은_확인_불가로_남긴다():
    """지도가 요약본이라 「없다」고 단정하면 안 채우고 올렸다가 거부당한다."""
    from lemouton.policy import required as R
    for key in ('listing', 'price_compare', 'ids'):
        state, _e, note = R.status_of('lotteon', key)
        assert state == R.UNKNOWN, f'롯데온 {key} 를 단정했다: {state}'
        assert '요약본' in note


def test_쿠팡_가격비교는_칸_자체가_없다고_적어_둔다():
    """사장님 엑셀에도 X 로 적혀 있다 — 「선택」과 「칸 없음」은 다르다."""
    from lemouton.policy import required as R
    state, evidence, _n = R.status_of('coupang', 'price_compare')
    assert state == R.OPTIONAL
    assert '없습니다' in evidence


def test_11번가_모델번호는_조건부다():
    """필수 표기는 없지만 빈칸을 안 받아 「없음」이라고 적어야 한다."""
    from lemouton.policy import required as R
    state, evidence, note = R.status_of('eleven11', 'ids')
    assert state == R.CONDITIONAL
    assert '없음' in evidence


def test_쿠팡_병행수입과_11번가_판매방식은_필수다():
    from lemouton.policy import required as R
    assert R.status_of('coupang', '_parallel_import')[0] == R.REQUIRED
    assert R.status_of('eleven11', '_sell_method')[0] == R.REQUIRED

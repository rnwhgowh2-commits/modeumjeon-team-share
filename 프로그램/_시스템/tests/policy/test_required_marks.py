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

def test_아직_안_나가는_항목은_저장만이라고_말한다():
    """[2026-08-12 정정] 이 시험은 **틀린 사실을 지키고 있었다.**

    옛 이름이 `…판매가와_배송뿐` 이었고 상품명·옵션·상세설명을 「저장만」이라고
    못 박아 뒀다. 그런데 그 사이 `to_payload → apply_rules → as_draft` 배선이 생겨
    그 셋은 **실제로 마켓 초안에 실려 나가고 있었다.** 시험이 옛 사실을 잠가 두는
    바람에 화면도 계속 「저장만」이라고 말했다 — 사장님이 「어차피 안 나간다」고
    읽고 안 채웠으면 그대로 나갔을 값이다.

    🔴 그래서 지금은 **안 나가는 것만** 여기서 지키고, 나가는 것은 아래
      `test_초안으로_옮겨지는_칸은_전송됨이라고_적혀_있다` 가 **as_draft 원본을 읽어**
      판정한다. 사람이 손으로 적은 목록끼리 대조하면 또 같이 낡는다.
    """
    # [2026-08-13 2단계] 원산지는 이제 초안까지 간다 → 여기서 뺐다.
    #   🔴 사실이 바뀌면 시험도 같이 옮긴다 — 안 옮기면 시험이 옛 사실을 잠근다.
    for k in ('category', 'images', 'notice', 'kc', 'tags'):
        st, note = R.wiring_of(k)
        assert st == R.STORED_ONLY, k
        assert note.strip(), k


def test_원산지와_배송비는_이제_나간다():
    """[2026-08-13 2단계] 정책값이 초안까지 간다 — 전에는 상품 칸 기본값이 나갔다."""
    assert R.wiring_of('origin')[0] == R.WIRED
    assert R.wiring_of('shipping')[0] == R.WIRED
    assert '반품' in R.wiring_of('shipping')[1], '반품비도 나간다는 사실이 빠졌다'


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
    """항목을 다 채워도 아직 안 나가는 것이 있다 — 화면이 그 사실을 말해야 한다.

    [2026-08-12] 전에는 화면 글자 「저장만」을 그대로 찾았는데, 그러면 **문구를
    고치는 순간 시험이 깨진다**(뜻은 그대로인데도). 지금은 「안 나가는 게 있다」는
    뜻이 화면에 있는지와, 나가는 항목에 초록 배지가 붙는지를 본다.
    🔴 「나가는 것은 판매가와 배송비뿐」 같은 **목록을 화면 글자에 박아 두지 않는다** —
      배선이 늘면 그 문장이 곧 거짓말이 된다(실제로 그렇게 됐다).
    """
    pid = _정책하나(client)
    html = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert '아직 마켓으로 나가지 않습니다' in html
    assert 'wire on' in html             # 「전송됨」 초록 배지
    assert '배송비뿐입니다' not in html, '옛 문구가 남아 있다 — 지금은 사실이 아니다'


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


# ── [2026-08-12] 「전송됨/저장만」 표시가 사실인가 ────────────────────────────
#   🔴 이 표는 실제로 틀어져 있었다. 판매가·배송비 둘만 「전송됨」이라 적혀 있었는데,
#     그 사이 배선이 생겨 상품명·브랜드·옵션·상세설명도 나가고 있었다.
#     사장님이 「어차피 안 나간다」고 읽고 안 채웠으면 그대로 마켓에 나갔을 값이다.
#   판정 근거 = `send/as_draft.upsert` 가 사본에서 **실제로 옮겨 담는 칸**.

def _as_draft_copied_fields() -> set:
    """as_draft 가 `getattr(view, …)` 로 옮겨 담는 초안 칸 이름."""
    import re
    from pathlib import Path
    src = Path('lemouton/send/as_draft.py').read_text(encoding='utf-8')
    return set(re.findall(r'd\.(\w+)\s*=\s*getattr\(view', src))


#: 초안 칸 → 그 칸을 만드는 정책 항목
_FIELD_TO_ITEM = {
    'name': 'name',
    'brand': 'brand',
    'options_json': 'options',
    'detail_html': 'detail',
}


def test_초안으로_옮겨지는_칸은_전송됨이라고_적혀_있다():
    from lemouton.policy import required as R
    copied = _as_draft_copied_fields()
    assert copied, 'as_draft 에서 옮겨 담는 칸을 하나도 못 읽었다 — 시험이 헛돈다'
    for field in copied:
        item = _FIELD_TO_ITEM.get(field)
        assert item, f'초안 칸 「{field}」 가 새로 생겼다 — 어느 정책 항목인지 정하고 이 표에 넣어라'
        state, note = R.wiring_of(item)
        assert state == R.WIRED, \
            f'「{item}」 은 실제로 마켓 초안에 실리는데 화면은 「{state}」 라고 말한다'
        assert note.strip()


def test_판매가와_배송비도_전송됨이다():
    """가격 엔진이 읽는다 — 초안 칸과는 다른 경로라 따로 지킨다."""
    from lemouton.policy import required as R
    assert R.wiring_of('price')[0] == R.WIRED
    assert R.wiring_of('shipping')[0] == R.WIRED


def test_이미지는_반쪽만_먹는다고_정직하게_말한다():
    """[2026-08-13] 이미지 규칙은 **반쪽만** 작동한다 — 그렇게 정확히 말해야 한다.

    · 「제외 브랜드」·「사진 없음」은 지금도 전송을 막는다(실제 작동).
    · 그런데 「몇 장 올릴지」는 안 먹는다 — 초안이 옵션 사진을 다시 모아 쓴다.
    🔴 그냥 「전송됨」이라 하면 몇 장 규칙도 먹는 줄 알고, 그냥 「저장만」이라 하면
      제외 브랜드가 안 먹는 줄 안다. 둘 다 거짓이라 문구가 반쪽을 다 말해야 한다.
    """
    from lemouton.policy import required as R
    state, note = R.wiring_of('images')
    assert state == R.STORED_ONLY
    assert '막습니다' in note, '막는 기능이 있다는 사실이 빠졌다'
    assert '몇 장' in note, '몇 장 규칙은 안 먹는다는 사실이 빠졌다'


def test_아직_안_나가는_항목은_그대로_저장만이다():
    from lemouton.policy import required as R
    for key in ('notice', 'kc', 'tags', 'category', 'price_compare', 'ids'):
        assert R.wiring_of(key)[0] == R.STORED_ONLY, \
            f'「{key}」 를 나간다고 적었는데 읽는 코드가 있는지 확인하라'


def test_판매방식_통관은_이제_나간다():
    """[2026-08-13] 「저장만」 이었는데 사실이 아니게 됐다.

    🔴 이 시험은 원래 `listing` 을 STORED_ONLY 로 **잠가 두고** 있었다. 그 사이
      초안 칸이 생기고 5마켓 배선이 붙었는데도 통과했다 — 통과하는 시험이
      「예전에 참이던 것」을 잠가 둘 수 있다. 이제 반대로 잠근다.
    """
    from lemouton.policy import required as R
    state, note = R.wiring_of('listing')
    assert state == R.WIRED
    assert '과세구분' in note and '미성년자' in note and '제조사' in note
    assert '옥션·G마켓에는 제조사 칸이 없습니다' in note, \
        '어느 마켓에 안 나가는지를 뭉개면 「전부 나간다」로 읽힌다'


def test_자동_가격_조정은_반쪽만_나간다고_말한다():
    """🔴 그냥 「전송됨」이면 마진율 계산도 먹는 줄 알고, 그냥 「저장만」이면
      직접 입력도 안 먹는 줄 안다. 둘 다 거짓이라 문구가 반쪽을 다 말해야 한다."""
    from lemouton.policy import required as R
    state, note = R.wiring_of('_auto_pricing')
    assert state == R.STORED_ONLY
    assert '직접 입력' in note and '나갑니다' in note
    assert '마진율' in note and '아직 안 나갑니다' in note

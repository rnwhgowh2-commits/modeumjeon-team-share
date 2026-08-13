# -*- coding: utf-8 -*-
"""정책에서 정한 등록값이 **담길 칸**이 초안에 있는가.

지금까지 이 값들은 갈 곳이 없어 마켓에 안 나갔다. 화면이 「못 보냈습니다」라고
말해 주기는 했지만, 말만 해서는 상품이 제대로 안 올라간다.

🔴 [2026-08-13 사장님 확정]
   · 과세구분 = **과세**가 기본. 「영세」는 수출·외화획득 거래용이라 우리에겐 해당 없음 → **선택지에서 뺀다.**
     (쿠팡·옥션·G마켓엔 영세를 보낼 칸 자체가 없어, 남겨 두면 「고쳤는데 왜 안 먹지」가 된다)
   · 상품상태 = **무조건 새상품** → 고를 것이 아니므로 정책 항목에서 빼고 「정해져 나가는 값」으로 옮긴다.
   · 판매기간 = **마켓마다 가장 긴 것으로 알아서** → 같은 이유로 정책 항목에서 뺀다.
"""
from lemouton.registration.models import ProductDraft
from lemouton.registration.process_rule_schema import SCHEMAS


COLS = set(ProductDraft.__table__.columns.keys())


def _fields(item):
    return {f.key: f for f in SCHEMAS[item].fields}


# ── 담을 칸 ────────────────────────────────────────────────────────────────

def test_새로_담을_칸이_초안에_있다():
    """🔴 칸이 없으면 값을 만들어도 갈 곳이 없다 — 그게 지금까지의 상태였다."""
    for c in ('tax_type', 'manufacturer', 'model_no', 'barcode', 'search_tags'):
        assert c in COLS, f'초안에 「{c}」 칸이 없다'


def test_새_칸은_비어_있어도_된다():
    """🔴 NOT NULL 로 만들면 옛 초안 수백 건이 마이그레이션에서 터진다."""
    for c in ('tax_type', 'manufacturer', 'model_no', 'barcode', 'search_tags'):
        assert ProductDraft.__table__.columns[c].nullable, f'{c} 가 필수 칸이다'


def test_과세구분_기본값은_과세다():
    """사장님 확정 — 기본은 과세. 기본값이 없으면 마켓마다 제멋대로 잡는다."""
    assert ProductDraft.__table__.columns['tax_type'].default.arg == '과세'


# ── 정책 선택지 (사장님 확정 반영) ─────────────────────────────────────────

def test_영세는_고를_수_없다():
    """🔴 쿠팡·옥션·G마켓엔 영세를 보낼 칸이 없다 — 고르게 두면 조용히 다른 값이 나간다."""
    got = _fields('listing')['tax_type'].choices
    assert '영세' not in got, f'영세가 아직 선택지에 있다: {got}'
    assert set(got) == {'과세', '면세'}, got


def test_상품상태와_판매기간은_정책에서_뺐다():
    """고를 것이 하나뿐인 칸을 남기면 사장님이 바꿀 수 있다고 오해한다.

    대신 「정해져 나가는 값」 표에 올려 **무엇이 나가는지는 보이게** 한다.
    """
    keys = set(_fields('listing'))
    assert 'product_condition' not in keys, '상품상태가 아직 고를 수 있는 칸이다'
    assert 'sale_period' not in keys, '판매기간이 아직 고를 수 있는 칸이다'


def test_뺀_값은_정해져_나가는_값_표에_있다():
    """🔴 빼기만 하고 안 보여주면 「어디 갔지」가 된다 — 뺀 만큼 드러내야 한다."""
    from lemouton.policy import fixed_sends as FS
    labels = {r['label'] for r in FS.for_market('coupang')['rows']}
    assert '상품상태' in labels, '상품상태가 어디에도 안 보인다'
    assert '상품 판매기간' in labels

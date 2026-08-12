# -*- coding: utf-8 -*-
"""[2026-08-12] 배송비도 수수료를 뗀다 — 마켓이 준 배송비 정산 실값을 쓴다.

🔴 사장님이 준 쿠팡 정산 엑셀(MSF_PAYMENT_REVENUE_DETAIL) 실물 대조로 확정.
   배송료 행 **124건 전부** `4,000 → 수수료 132 → 정산 3,868` (3.30%). 예외 0건.

그런데 `_finalize_rows` 는 이렇게 했다:
    정산예정금(배송비포함) = 정산예정금액 + **고객배송비 전액**
→ 배송비 붙는 주문마다 정확히 **+132원 과대**. 「받을 돈」이 상시 부풀어 있었다.

★ 고치는 방향 (`project_coupang_shipping_fee_not_deducted` 메모의 경고 그대로)
  · 요율(3.3%)을 **박지 않는다** — 마켓·계정마다 다를 수 있다.
    마켓이 준 **배송비 정산 실값**(`_ship_settle`)이 있으면 그걸 쓰고, 없으면 종전대로
    고객배송비 전액(추정)을 쓴다. 모르는 값을 지어내지 않는다.
  · M열(정산예정금액)에는 **넣지 않는다.** 예전에 스스에서 M 에 배송비 정산을 더했다가
    `_finalize` 가 고객배송비를 또 더해 **이중 계상** 사고가 났다(2026-08-07, 2,910원 과다).
    별도 키로 두고 N열에서만 쓴다.
  · 배송건당 1회 — `_shipkey` 로 이미 정규화되는 고객배송비와 **같은 규칙**을 탄다.
    안 그러면 다품 주문에서 배송비 정산이 줄 수만큼 곱해진다.
"""
from lemouton.markets.order_export import _finalize_rows


def _row(**kw):
    base = {'판매처': '쿠팡', '주문일': '2026-07-01', '단가': 128900, '수량': 1,
            '배송비': 4000, '정산예정금액': 113924, '실결제금액': 132900,
            '주문상태': '배송완료'}
    base.update(kw)
    return base


def test_배송비_정산_실값이_있으면_그걸_쓴다():
    """쿠팡 실측 주문 1100194049219 — 상품 113,924 + 배송비 3,868 = 117,792."""
    rows = [_row(_ship_settle=3868)]
    _finalize_rows(rows)
    assert rows[0]['정산예정금(배송비포함)'] == 113924 + 3868, \
        '마켓이 준 배송비 정산 실값(3,868)을 안 쓰고 고객배송비(4,000)를 더했다'


def test_실값이_없으면_종전대로_고객배송비_전액():
    """모르는 값을 지어내지 않는다 — 요율을 박아 추정하지 말 것."""
    rows = [_row()]
    _finalize_rows(rows)
    assert rows[0]['정산예정금(배송비포함)'] == 113924 + 4000


def test_배송비_없는_주문은_그대로():
    rows = [_row(배송비=0, _ship_settle=None)]
    _finalize_rows(rows)
    assert rows[0]['정산예정금(배송비포함)'] == 113924


def test_다품_주문이면_배송건당_한_번만_더한다():
    """🔴 줄마다 더하면 배송비 정산이 줄 수만큼 곱해진다(고객배송비와 같은 함정)."""
    rows = [_row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=100000),
            _row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=50000)]
    _finalize_rows(rows)
    assert rows[0]['정산예정금(배송비포함)'] == 100000 + 3868
    assert rows[1]['정산예정금(배송비포함)'] == 50000, \
        '같은 배송건인데 배송비 정산을 두 번 더했다'


def test_M열은_안_건드린다():
    """정산예정금액(M)에 배송비를 섞으면 N 이 또 더해 이중 계상된다(2026-08-07 사고)."""
    rows = [_row(_ship_settle=3868)]
    _finalize_rows(rows)
    assert rows[0]['정산예정금액'] == 113924


def test_수수료율은_상품분_기준_그대로():
    """배송비 정산을 N 에 넣어도 수수료율(= (실결제−M)/실결제)은 안 흔들려야 한다.

    예전에 M 에 배송비를 섞었다가 수수료율이 1.32% 로 찍힌 사고가 있었다.
    """
    rows = [_row(_ship_settle=3868)]
    _finalize_rows(rows)
    assert rows[0]['수수료율'] == f"{round((132900 - 113924) / 132900 * 100, 2)}%"


def test_저장분을_다시_읽어도_유지된다():
    """🔴 이 시험이 이 파일에서 제일 중요하다.

    저장분(`order_store`)은 행을 통째로 담고, 다시 읽을 때 `_finalize_rows` 가
    **또 돈다**(order_export.py:3651). 그래서 여기서 `_ship_settle` 을 지워 버리면
    저장분엔 안 남고, 다음 조회에서 고객배송비로 **되돌아간다** — 고친 보람이 사라진다.
    값은 남기되 **두 번 더해지지도 않아야** 한다(멱등).
    """
    rows = [_row(_ship_settle=3868)]
    _finalize_rows(rows)
    first = rows[0]['정산예정금(배송비포함)']
    assert rows[0].get('_ship_settle') == 3868, \
        '저장분에 안 남는다 — 다시 읽으면 고객배송비로 되돌아간다'
    _finalize_rows(rows)                       # 저장분 재조회 흉내
    assert rows[0]['정산예정금(배송비포함)'] == first, '두 번 돌리니 값이 달라졌다'


def test_다품_주문은_재실행해도_한_번만():
    """배송건을 안 맡는 줄에서는 값을 지워야 재실행이 멱등하다.

    `_shipkey` 는 첫 실행에서 사라지므로, 두 번째 실행 땐 중복 판정이 안 된다.
    그때 두 줄 다 `_ship_settle` 을 갖고 있으면 배송비 정산이 두 번 더해진다.
    """
    rows = [_row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=100000),
            _row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=50000)]
    _finalize_rows(rows)
    _finalize_rows(rows)                       # 저장분 재조회 흉내
    assert rows[0]['정산예정금(배송비포함)'] == 100000 + 3868
    assert rows[1]['정산예정금(배송비포함)'] == 50000
    assert rows[1].get('_ship_settle') == 0, \
        '배송건을 안 맡는 줄은 0 을 **명시 대입**해야 한다 — pop 하면 저장분 병합에서 옛 값이 살아남는다'


def test_저장분_병합에서_배송건_담당이_바뀌어도_한_번만():
    """🔴 반증으로 잡힌 구멍 — pop 이면 여기서 배송비가 두 번 더해진다.

    `order_store._merge_row` 는 **새 payload 에 없는 키를 지우지 못한다.** 그래서
    앞 조회에서 A가 배송건을 맡아 저장됐는데 다음 조회에서 B가 맡으면,
    A에는 옛 값이 남고 B는 새 값을 받아 **두 줄 다** 값을 갖게 된다.
    (스스는 변경순, 쿠팡은 박스 상태별 창이라 줄 순서가 실제로 바뀐다)
    → 안 맡는 줄에 **0 을 명시 대입**해야 병합이 그 0 을 덮어써 준다.
    """
    def merge(old, new):                       # order_store._merge_row 흉내
        out = dict(old)
        out.update({k: v for k, v in new.items() if v not in (None, '')})
        return out

    a = _row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=100000)
    b = _row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=50000)
    _finalize_rows([a, b])                     # 1차: A가 담당
    saved_a, saved_b = dict(a), dict(b)

    a2 = _row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=100000)
    b2 = _row(_shipkey=('coupang', 'O1'), _ship_settle=3868, 정산예정금액=50000)
    _finalize_rows([b2, a2])                   # 2차: 순서가 뒤바뀌어 B가 담당
    ma, mb = merge(saved_a, a2), merge(saved_b, b2)
    _finalize_rows([ma, mb])                   # 저장분 재계산

    총합 = ma['정산예정금(배송비포함)'] + mb['정산예정금(배송비포함)']
    assert 총합 == 100000 + 50000 + 3868, f'배송비 정산이 두 번 더해졌다: {총합}'

# -*- coding: utf-8 -*-
"""[2026-08-13 사장님 확정] 쿠팡 쿠폰 자동화 배선 — 만들고 · 붙이고 · 안 되면 올리고 · 실패하면 회수.

■ 사장님 확정
    · 연결 방식 = **c** (정책 자동 + 단추 둘 다)
    · 기본값 = **100원**
    · 100원이 거부되면 = **a** 「10원씩 올려 재시도」
    · 상한 = **300원까지만** (2026-08-13 확정). 넘으면 멈추고 다음 값을 말한다.
    · 쿠폰 기간 = **최대로** + 자동연장

■ 🔴 라이브에서 이미 데인 것 (커밋 `6d4164d9` · 2026-08-06 다른 세션 실측)
    · 만들기·붙이기는 **접수만** 한다(비동기). `requestedId` 로 확인해야 결과를 안다.
    · **FAIL/ERROR 도 「끝」이다.** `done` 만 보고 돌면 실패를 성공으로 보고한다
      (앞 세션이 실제로 그렇게 보고했다).
    · 안 붙었으면 만든 쿠폰을 **그 자리에서 도로 내린다** — 안 그러면 윙에 빈 쿠폰이 쌓인다.
    · 내리기는 `PUT … action=expire` — 빼면 500.
    · 실측 거부: 128,900원에 100원(0.07%) → `[CIE06] 할인이 너무 작거나 너무 큽니다`
                 같은 상품 1,400원(1.09%) → 통과

■ 🔴 [CIE06] 과 [CIR08] 은 **다른 병이다**
    CIE06 = 금액이 작다   → 10원 올리면 낫는다
    CIR08 = 이미 다른 쿠폰에 물렸다 → 금액을 올려도 영영 안 낫는다
    섞으면 300원까지 헛되이 올리며 쿠폰을 20개 만들었다 지운다.

■ 🔴 쿠폰 기간의 「최대」는 우리가 정하는 게 아니다
    쿠팡 생성 API 실제 에러: 「계약의 유효기간 안에 쿠폰이 존재해야 한다」
    → 최대 = **그 계정 계약서(contractId)의 종료일**. 계약서 목록 조회로 읽는다.
      자유계약(NON_CONTRACT_BASED)은 2999년까지도 있다.
    지어내지 않는다 — 계약서를 못 읽으면 쿠폰을 **만들지 않는다**.
"""
import datetime as _dt

import pytest

from lemouton.policy.coupon_apply import (
    RETRY_MAX_WON, RETRY_STEP_WON, apply_coupon,
)

_NOW = _dt.datetime(2026, 8, 13, 15, 0, 0)
_PRICE = 128900

_CIE06 = '[CIE06] 이 프로모션을 적용하면 일부 옵션 ID에 대해 할인이 너무 작거나 너무 큽니다.'
_CIR08 = '[CIR08] 해당 옵션은 이미 다른 쿠폰(89450797)에 발행되어져 있습니다.'


class _Fake:
    """쿠팡 클라이언트 흉내. `request(method, path, body=None, query='')`.

    ok_at   : 이 금액 **이상**이어야 붙는다(그 밑은 [CIE06]) — 라이브 거부를 흉내낸다.
    taken   : 이미 다른 쿠폰이 쓰는 옵션([CIR08]) — 금액을 올려도 안 낫는다.
    """

    CONTRACTS = [
        {'contractId': 9962, 'sellerId': 'A00012345', 'type': 'CONTRACT_BASED',
         'start': '2026-01-01 00:00:00', 'end': '2026-12-31 23:59:59'},
    ]

    #: ⚠️ 실클라이언트는 vendor_id 를 **속성이 아니라 설정 주머니**에 둔다
    #:   (`promotions.vendor_id_of` · 2026-08-05 실사고). 흉내도 같은 자리에 둔다 —
    #:   속성으로 두면 시험만 통과하고 라이브에선 전 계정이 「없음」이 된다.
    _cfg = {'vendor_id': 'A00012345'}

    def __init__(self, ok_at=100, taken=(), contracts=None, attach_status='DONE'):
        self.ok_at = ok_at
        self.taken = {str(t) for t in taken}
        self.contracts = self.CONTRACTS if contracts is None else contracts
        self.attach_status = attach_status
        self.created = []          # [(coupon_id, value, start_at, end_at)]
        self.expired = []          # [coupon_id]
        self.attached = []         # [(coupon_id, [ids])]
        self._seq = 0
        self._pending = {}         # requestedId -> 결과 content

    # ── 도우미 ───────────────────────────────────────────────
    def _next(self, prefix):
        self._seq += 1
        return f'{prefix}{self._seq}'

    @staticmethod
    def _ok(content):
        return {'code': 200, 'message': 'OK',
                'data': {'success': True, 'content': content}}

    # ── 라우팅 ───────────────────────────────────────────────
    def request(self, method, path, body=None, query=''):
        if path.endswith('/contract/list'):
            return self._ok(list(self.contracts))

        if method == 'POST' and path.endswith('/coupon'):
            cid = int(self._next('99')) + 1000
            rid = self._next('R')
            self.created.append((cid, int(body['discount']),
                                 body['startAt'], body['endAt']))
            self._pending[rid] = {'couponId': cid, 'status': 'DONE',
                                  'total': 1, 'succeeded': 1, 'failed': 0}
            return self._ok({'requestedId': rid, 'success': True})

        if method == 'POST' and path.endswith('/items'):
            cid = int(path.split('/coupons/')[1].split('/')[0])
            ids = [str(v) for v in body['vendorItems']]
            value = next(v for c, v, _s, _e in self.created if c == cid)
            self.attached.append((cid, ids))
            failed = []
            for v in ids:
                if v in self.taken:
                    failed.append({'vendorItemId': int(v), 'reason': _CIR08})
                elif value < self.ok_at:
                    failed.append({'vendorItemId': int(v), 'reason': _CIE06})
            rid = self._next('R')
            self._pending[rid] = {
                'couponId': cid, 'status': self.attach_status,
                'total': len(ids), 'succeeded': len(ids) - len(failed),
                'failed': len(failed), 'failedVendorItems': failed}
            return self._ok({'requestedId': rid, 'success': True})

        if method == 'GET' and '/requested/' in path:
            return self._ok(self._pending[path.rsplit('/', 1)[1]])

        if method == 'PUT' and '/coupons/' in path:
            assert query == 'action=expire', \
                '내리기에 action=expire 를 안 붙였다 — 라이브에서 500 이 난다'
            self.expired.append(int(path.rsplit('/', 1)[1]))
            return self._ok({'requestedId': self._next('R'), 'success': True})

        raise AssertionError(f'시험이 모르는 호출: {method} {path} {query}')


def _run(client, **kw):
    kw.setdefault('vendor_id', 'A00012345')
    kw.setdefault('name', '모음전 즉시할인')
    kw.setdefault('vendor_item_ids', [111, 222])
    kw.setdefault('sale_price', _PRICE)
    kw.setdefault('now', _NOW)
    kw.setdefault('sleep', lambda _s: None)
    return apply_coupon(client, **kw)


# ── 기본 동작 ─────────────────────────────────────────────────

def test_기본값_100원으로_한_번에_되면_더_안_올린다():
    """싼 상품은 100원도 통과한다 — 되는데 올리면 그만큼 손해다."""
    c = _Fake(ok_at=100)
    r = _run(c)
    assert r['ok'] is True
    assert r['value'] == 100
    assert len(c.created) == 1, '한 번에 됐는데 쿠폰을 여러 개 만들었다'
    assert c.expired == [], '성공한 쿠폰을 내려 버렸다'
    assert sorted(r['attached']) == ['111', '222']


def test_시작은_내일_0시_끝은_계약서_종료일():
    """⏰ 쿠팡은 **다음날 0시**부터만 켤 수 있다. 끝은 계약서가 정한 **최대**."""
    c = _Fake(ok_at=100)
    r = _run(c)
    assert r['starts_at'] == '2026-08-14 00:00:00'
    assert r['ends_at'] == '2026-12-31 23:59:59', \
        '계약서 종료일(=최대)이 아니라 딴 날짜를 썼다'
    assert r['contract_id'] == 9962
    _cid, _v, start, end = c.created[0]
    assert (start, end) == ('2026-08-14 00:00:00', '2026-12-31 23:59:59')


def test_계약서를_못_읽으면_쿠폰을_안_만든다():
    """🔴 계약ID를 지어내면 엉뚱한 계약에 쿠폰이 걸린다 — 만들지 않는다."""
    c = _Fake(contracts=[])
    r = _run(c)
    assert r['ok'] is False
    assert c.created == [], '계약서가 없는데 쿠폰을 만들었다'
    assert '계약' in r['message']


def test_기간이_지난_계약서는_안_쓴다():
    """끝난 계약으로 만들면 쿠팡이 「계약의 유효기간 안에」라며 거부한다."""
    c = _Fake(contracts=[{'contractId': 1, 'type': 'CONTRACT_BASED',
                          'start': '2020-01-01 00:00:00',
                          'end': '2020-12-31 23:59:59'}])
    r = _run(c)
    assert r['ok'] is False
    assert c.created == []


def test_계약서가_여럿이면_가장_늦게_끝나는_것_최대():
    """사장님 「최대는?」 → 지금 유효한 계약 중 **가장 늦게 끝나는** 것을 쓴다."""
    c = _Fake(contracts=[
        {'contractId': 1, 'type': 'CONTRACT_BASED',
         'start': '2026-01-01 00:00:00', 'end': '2026-09-30 23:59:59'},
        {'contractId': 15, 'type': 'NON_CONTRACT_BASED',
         'start': '2026-01-01 00:00:00', 'end': '2999-12-31 23:59:59'},
    ])
    r = _run(c)
    assert r['contract_id'] == 15
    assert r['ends_at'] == '2999-12-31 23:59:59'


# ── 거부되면 10원씩 올려 재시도 (사장님 확정 a) ───────────────

def test_거부되면_10원씩_올려_재시도한다():
    """100 → 110 → 120 → 130 에서 붙었다. 실측 [CIE06] 그대로 흉내."""
    c = _Fake(ok_at=130)
    r = _run(c)
    assert r['ok'] is True
    assert r['value'] == 130
    assert [a['value'] for a in r['attempts']] == [100, 110, 120, 130]
    assert [a['ok'] for a in r['attempts']] == [False, False, False, True]
    assert RETRY_STEP_WON == 10


def test_실패한_쿠폰은_그자리에서_도로_내린다():
    """🔴 안 붙은 쿠폰을 남기면 윙에 **빈 쿠폰이 쌓인다**(라이브에서 겪음)."""
    c = _Fake(ok_at=130)
    _run(c)
    실패쿠폰 = [cid for cid, v, _s, _e in c.created if v < 130]
    assert 실패쿠폰, '시험이 헛돈다 — 실패한 쿠폰이 없다'
    assert sorted(c.expired) == sorted(실패쿠폰), \
        '안 붙은 쿠폰을 안 내렸다 — 윙에 빈 쿠폰이 쌓인다'
    assert c.created[-1][0] not in c.expired, '성공한 쿠폰까지 내렸다'


def test_300원까지만_올리고_멈춘다():
    """사장님 확정 상한 300원. 무한 재시도 금지 — 멈추고 **다음 값을 말한다**."""
    c = _Fake(ok_at=100000)                       # 영영 안 붙는다
    r = _run(c)
    assert RETRY_MAX_WON == 300
    assert r['ok'] is False
    assert [a['value'] for a in r['attempts']] == list(range(100, 301, 10))
    assert '300' in r['message'], f'어디까지 해 봤는지 안 말한다: {r["message"]}'
    assert '310' in r['message'], f'다음 값을 안 말한다: {r["message"]}'
    assert sorted(c.expired) == sorted(cid for cid, *_ in c.created), \
        '상한에 걸려 멈출 때 만든 쿠폰을 다 안 내렸다'


def test_정책이_준_값이_있으면_거기서_시작한다():
    """정책에 즉시할인이 적혀 있으면 기본값 100원이 아니라 **그 값**부터."""
    c = _Fake(ok_at=1000)
    r = _run(c, discount={'value': 1000, 'unitType': 'WON'})
    assert r['ok'] is True
    assert [a['value'] for a in r['attempts']] == [1000]


def test_시작값이_이미_상한을_넘으면_올리지_않고_한_번만():
    """상한 300원은 **자동 인상의 한계**지 사장님이 적은 값의 한계가 아니다."""
    c = _Fake(ok_at=5000)
    r = _run(c, discount={'value': 5000, 'unitType': 'WON'})
    assert r['ok'] is True
    assert [a['value'] for a in r['attempts']] == [5000]


# ── [CIR08] 은 금액 문제가 아니다 ─────────────────────────────

def test_이미_다른_쿠폰에_물린_옵션은_금액을_안_올린다():
    """🔴 [CIR08] 은 금액을 올려도 영영 안 낫는다 — 300원까지 헛되이 올리면 안 된다."""
    c = _Fake(ok_at=100, taken=['222'])
    r = _run(c)
    assert [a['value'] for a in r['attempts']] == [100], \
        '금액과 무관한 실패인데 10원씩 올렸다'
    assert r['ok'] is True, '붙은 옵션이 있는데 통째로 실패로 봤다'
    assert r['attached'] == ['111']
    assert [f['vendorItemId'] for f in r['failed_items']] == [222]
    assert '222' in r['message'] and 'CIR08' in r['message'], \
        f'못 붙은 옵션을 조용히 넘겼다: {r["message"]}'
    assert c.expired == [], '일부라도 붙었으면 쿠폰을 내리면 안 된다'


def test_전부_다른_쿠폰에_물렸으면_쿠폰을_회수한다():
    c = _Fake(ok_at=100, taken=['111', '222'])
    r = _run(c)
    assert r['ok'] is False
    assert c.expired == [c.created[0][0]], '아무것도 안 붙었는데 쿠폰을 남겼다'


# ── FAIL/ERROR 도 「끝」이다 ──────────────────────────────────

@pytest.mark.parametrize('status', ['FAIL', 'FAILED', 'ERROR'])
def test_FAIL_도_끝으로_보고_성공이라_말하지_않는다(status):
    """🔴 앞 세션이 `done` 만 보고 **실패를 성공이라고 보고**했다(2026-08-06)."""
    c = _Fake(ok_at=100, attach_status=status)
    r = _run(c)
    assert r['ok'] is False, 'FAIL 인데 성공이라고 했다'
    assert c.expired == [c.created[0][0]]


def test_영영_안_끝나면_기다리다_멈춘다():
    """접수만 되고 결과가 안 나오는 경우 — 무한 대기 금지."""
    class _Stuck(_Fake):
        def request(self, method, path, body=None, query=''):
            r = _Fake.request(self, method, path, body=body, query=query)
            if method == 'GET' and '/requested/' in path:
                r['data']['content']['status'] = 'PROGRESS'
            return r

    c = _Stuck(ok_at=100)
    r = _run(c, poll_times=3)
    assert r['ok'] is False
    assert '확인' in r['message'] or '아직' in r['message']


# ── 안전장치 ─────────────────────────────────────────────────

def test_붙일_옵션이_없으면_쿠폰을_만들지_않는다():
    """🔴 옵션이 없는데 쿠폰부터 만들면 반드시 빈 쿠폰이 된다."""
    c = _Fake(ok_at=100)
    r = _run(c, vendor_item_ids=[])
    assert r['ok'] is False
    assert c.created == []


def test_10원_단위가_아니면_보내기_전에_막는다():
    """마켓이 「유효하지 않습니다」만 뱉기 전에 우리가 사람 말로 말한다."""
    c = _Fake(ok_at=100)
    r = _run(c, discount={'value': 105, 'unitType': 'WON'})
    assert r['ok'] is False
    assert c.created == []
    assert '10원' in r['message']


def test_정률은_올리지_않는다():
    """🔴 %는 10원씩 올린다는 말이 성립하지 않는다 — 한 번만 해 보고 끝낸다."""
    c = _Fake(ok_at=100000)
    r = _run(c, discount={'value': 5, 'unitType': 'PERCENT'})
    assert len(r['attempts']) == 1, '정률인데 10원씩 올렸다'


def test_모든_시도가_기록에_남는다():
    """사장님 「몇 번 만에 얼마로 성공했는지 남겨야 다음 상품에 배운다」."""
    c = _Fake(ok_at=130)
    r = _run(c)
    assert len(r['attempts']) == 4
    for a in r['attempts']:
        assert set(a) >= {'value', 'ok', 'reason', 'coupon_id'}
    assert r['attempts'][0]['reason'] and 'CIE06' in r['attempts'][0]['reason']
    assert r['tried'] == 4 and r['value'] == 130

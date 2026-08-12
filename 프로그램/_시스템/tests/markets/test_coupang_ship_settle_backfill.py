# -*- coding: utf-8 -*-
"""저장분에도 배송비 정산 실값이 실려야 한다 — 안 그러면 고침이 라이브에 안 나타난다.

🔴 2026-08-13 라이브 실측으로 드러난 **고침의 빠진 반쪽**:
   `order_export` 는 고쳤는데 화면은 그대로 4,000 을 보여줬다.
     라이브 1100194049219 → 상품정산 113,924 · 배송비정산 **4,000** · 총 **117,924**
                            (바른 값: 3,868 · 117,792)
   원인 — 화면·마진계산기·정산탭이 읽는 것은 **저장분**인데, 저장분을 갱신하는
   정산 스윕(`refresh_settlement_coupang`)이 `_coupang_settle_map` 의 **배송비 맵을
   받아서 버리고 있었다**(`imap, _deliv, dmap = ...`). 빌더를 고쳐도 이미 저장된
   주문은 영영 옛 값이다 — 에러도 없이.

🔴 배송건당 1회 규약: 저장분은 배송건 첫 행에만 `배송비`가 남아 있다(나머지는 0).
   그래서 **배송비가 0 인 행엔 배송비 정산도 0** 이어야 한다. 안 그러면 다품 주문에서
   배송비 정산이 줄 수만큼 더해진다.
"""
import datetime as dt

import pytest

from lemouton.markets import order_ingest as OI


class _Row:
    """MarketOrderLine 대역."""

    def __init__(self, row):
        self.market = "coupang"
        self.row = row
        self.last_seen_at = None


class _Sess:
    def __init__(self, lines):
        self._lines = lines
        self.committed = False

    def query(self, *a):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._lines

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _line(oid="OID1", vid="V1", ship=4000, settle=113924, src="real"):
    return _Row({"오픈마켓주문번호": oid, "_pd_market_option_id": vid,
                 "판매처": "쿠팡", "주문일": "2026-07-20 10:00:00",
                 "단가": 128900, "수량": 1, "배송비": ship,
                 "정산예정금액": settle, "_settle_source": src,
                 "정산예정금(배송비포함)": settle + ship})


@pytest.fixture
def patched(monkeypatch):
    """정산 조회 대역 — 상품 113,924 + 배송비 3,868."""
    monkeypatch.setattr(
        "lemouton.markets.order_export._coupang_settle_map",
        lambda since, until, cli: ({("OID1", "V1"): 113924},
                                   {"OID1": 3868},
                                   {"OID1": {"정산예정일": "2026-08-14"}}))
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda mk: [("대표", object())])
    monkeypatch.setattr(
        "shared.platforms.coupang.settlements.fetch_settlement_histories",
        lambda ym, client=None: [])


def test_저장분에_배송비_실값이_실린다(patched):
    ln = _line()
    st = OI.refresh_settlement_coupang(session=_Sess([ln]))
    assert ln.row["_ship_settle"] == 3868
    assert ln.row["정산예정금(배송비포함)"] == 117792     # 113,924 + 3,868
    assert ln.row["정산예정금액"] == 113924               # M열 불변
    assert ln.row["배송비"] == 4000                       # 고객이 낸 배송비도 불변
    assert st["updated"] >= 1


def test_배송비_0인_행엔_0을_실어_중복가산을_막는다(patched):
    """다품 주문의 둘째 행부터는 저장분 배송비가 0 이다 — 거기에 3,868 을 얹으면
    한 주문에서 배송비 정산이 줄 수만큼 더해진다."""
    second = _line(ship=0, settle=50000)
    OI.refresh_settlement_coupang(session=_Sess([second]))
    assert second.row["_ship_settle"] == 0
    assert second.row["정산예정금(배송비포함)"] == 50000


def test_정산조회에_없는_주문은_안_건드린다(patched):
    """없는 값을 0 으로 채우지 않는다 — 「모른다」와 「0원」은 다르다."""
    other = _line(oid="OTHER")
    before = dict(other.row)
    OI.refresh_settlement_coupang(session=_Sess([other]))
    assert "_ship_settle" not in other.row
    assert other.row["정산예정금(배송비포함)"] == before["정산예정금(배송비포함)"]


def test_이미_같은_값이면_다시_안_쓴다(patched):
    """무의미한 쓰기 방지 규약을 깨지 않는다(스윕이 매번 전 행을 더럽히면 안 된다)."""
    ln = _line()
    ln.row["_ship_settle"] = 3868
    ln.row["정산예정금(배송비포함)"] = 117792
    ln.row["정산예정일"] = "2026-08-14"
    st = OI.refresh_settlement_coupang(session=_Sess([ln]))
    assert st["updated"] == 0


def test_클레임_행은_건드리지_않는다(patched):
    clm = _line()
    clm.row["_kind"] = "change"
    OI.refresh_settlement_coupang(session=_Sess([clm]))
    assert "_ship_settle" not in clm.row

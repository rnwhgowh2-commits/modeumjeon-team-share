"""구조 프로브 — 판정 로직과 개인정보 비유출을 fake client 로 검증.

이 프로브의 출력은 적재 업서트 키를 정하는 근거가 된다. 판정이 틀리면
「키로 적합」이라고 잘못 말해 주문이 덮어씌워진다. 그래서 겹침/공란 판정을 못 박는다.
"""
from __future__ import annotations

import pytest

from lemouton.markets import shape_probe as S


class _FakeEsm:
    def __init__(self, orders):
        self.orders = orders

    def request_orders(self, body):
        # 상태 5종 루프 중 첫 상태에만 데이터를 준다(중복 계상 방지)
        if body.get("orderStatus") != 1:
            return {"Data": {"RequestOrders": []}}
        return {"Data": {"RequestOrders": self.orders}}


def test_ESM_OrderNo가_안겹치면_라인단위로_판정():
    c = _FakeEsm([{"OrderNo": "A1"}, {"OrderNo": "A2"}])
    r = S.shape("auction", days=7, client=c)
    assert r["최대_OrderNo당_행수"] == 1
    assert "라인단위" in r["판정"]


def test_ESM_OrderNo가_겹치면_주문단위로_경고():
    """겹치면 현행 OrderNo dedupe 가 2번째 라인을 버린다 = 주문 소실."""
    c = _FakeEsm([{"OrderNo": "A1"}, {"OrderNo": "A1"}, {"OrderNo": "A2"}])
    r = S.shape("auction", days=7, client=c)
    assert r["최대_OrderNo당_행수"] == 2
    assert r["다행_그룹수"] == 1
    assert "🔴" in r["판정"]


def test_표본이_0건이면_판정불가라고_말한다():
    """0건을 '안전'으로 읽으면 근거 없이 키를 확정하게 된다."""
    r = S.shape("auction", days=7, client=_FakeEsm([]))
    assert "판정 불가" in r["판정"]


class _FakeLotteon:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def request(self, method, path, body=None, **kw):
        self.calls += 1
        return {"data": self.rows if self.calls == 1 else []}


def test_롯데온_odNo_odSeq_조합이_유일하면_키로_적합():
    c = _FakeLotteon([{"odNo": "1", "odSeq": "1"}, {"odNo": "1", "odSeq": "2"}])
    r = S.shape("lotteon", days=1, client=c)
    assert r["그룹수"] == 1 and r["odNo+odSeq_조합수"] == 2
    assert "키로 적합" in r["판정"]


def test_롯데온_odSeq_공란을_센다():
    c = _FakeLotteon([{"odNo": "1", "odSeq": ""}, {"odNo": "1", "odSeq": ""}])
    r = S.shape("lotteon", days=1, client=c)
    assert r["odSeq_공란_행수"] == 2
    assert "🔴" in r["판정"]


class _FakeCoupang:
    _cfg = {"vendor_id": "A1"}

    def __init__(self, boxes):
        self.boxes, self.calls = boxes, 0

    def request(self, method, path, query=None, **kw):
        self.calls += 1
        return {"code": 200, "data": self.boxes if self.calls == 1 else []}


def test_쿠팡_한주문이_여러박스로_갈리면_경고():
    boxes = [{"orderId": "O1", "shipmentBoxId": "B1", "orderItems": [{"vendorItemId": "V1"}]},
             {"orderId": "O1", "shipmentBoxId": "B2", "orderItems": [{"vendorItemId": "V2"}]}]
    r = S.shape("coupang", days=30, client=_FakeCoupang(boxes))
    assert "있음" in r["orderId_다중박스_여부"]
    assert r["shipmentBoxId+vendorItemId_조합수"] == 2
    assert "키로 적합" in r["판정"]


def test_쿠팡_vendorItemId_공란을_센다():
    boxes = [{"orderId": "O1", "shipmentBoxId": "B1",
              "orderItems": [{"vendorItemId": ""}, {"vendorItemId": ""}]}]
    r = S.shape("coupang", days=30, client=_FakeCoupang(boxes))
    assert r["vendorItemId_공란수"] == 2
    assert "🔴" in r["판정"]


class _FakeEleven:
    def __init__(self, xml):
        self.xml = xml

    def request(self, method, path, body=None):
        return self.xml


def test_11번가_ordPrdSeq_있으면_키확정_가능하다고_알린다():
    xml = ("<orders><order><ordNo>1</ordNo><ordPrdSeq>2</ordPrdSeq></order></orders>")
    r = S.shape("eleven11", days=7, client=_FakeEleven(xml))
    assert r["취소요청"]["ordPrdSeq_존재"] is True
    assert "키 확정" in r["취소요청"]["판정"]


def test_11번가_행이_0건이면_판정불가():
    r = S.shape("eleven11", days=7, client=_FakeEleven("<orders></orders>"))
    assert r["취소요청"]["행수"] == 0
    assert "판정 불가" in r["취소요청"]["판정"]


class _FakeSmartstore:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def request(self, method, path, query=None, **kw):
        self.calls += 1
        return {"data": {"lastChangeStatuses": self.rows if self.calls == 1 else []}}


def test_스스_productOrderId_고유하면_키로_적합():
    c = _FakeSmartstore([{"productOrderId": "P1"}, {"productOrderId": "P2"}])
    r = S.shape("smartstore", days=1, client=c)
    assert r["판정"].startswith("productOrderId")


def test_스스_productOrderId_공란이면_경고():
    c = _FakeSmartstore([{"productOrderId": ""}, {"productOrderId": ""}])
    r = S.shape("smartstore", days=1, client=c)
    assert r["productOrderId_공란수"] == 2
    assert "🔴" in r["판정"]


# ── 개인정보 비유출 ─────────────────────────────────────────────
def test_구매자정보_값이_결과에_섞이지_않는다():
    """필드'명'은 나가도 되지만 값은 절대 안 된다. 이게 새면 조사 도구가 유출 경로가 된다."""
    boxes = [{"orderId": "O1", "shipmentBoxId": "B1", "receiver": "홍길동",
              "receiverPhone": "010-1234-5678", "addr": "서울시 어딘가 101동",
              "orderItems": [{"vendorItemId": "V1", "buyerName": "김철수"}]}]
    blob = repr(S.shape("coupang", days=30, client=_FakeCoupang(boxes)))
    for secret in ("홍길동", "010-1234-5678", "서울시", "김철수", "O1", "B1", "V1"):
        assert secret not in blob, f"값 유출: {secret}"
    # 필드명은 구조 파악에 필요하므로 남아야 한다
    assert "receiver" in blob and "vendorItemId" in blob


def test_지원하지_않는_마켓은_명확히_거절():
    with pytest.raises(ValueError, match="지원하지 않는 마켓"):
        S.shape("shopmine", client=object())


def test_클라이언트_없으면_에러를_돌려준다():
    assert "클라이언트 없음" in S.shape("coupang", client=None)["error"]

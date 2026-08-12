# -*- coding: utf-8 -*-
"""왕복 실전송 검증 하네스 — 안전 규칙이 진짜 지켜지는지.

이 테스트들이 막는 사고는 하나같이 **원복 실패 = 마켓에 시험값이 그대로 남는 것**이다.
가짜 마켓(FakeMarket)은 진짜 마켓처럼 **쓴 값을 보관하고 되읽기로 돌려준다** —
그래야 「보냈다고 주장하는 것」이 아니라 「마켓이 실제로 갖고 있는 것」을 검사할 수 있다.
"""
from __future__ import annotations

import pytest

from lemouton.uploader.roundtrip.runner import run_roundtrip
from lemouton.uploader.roundtrip.snapshot import Snapshot


# ── 가짜 마켓 — 쓴 값을 보관하고 되읽기로 돌려준다 ────────────────────────────
class FakeMarket:
    """진짜 마켓의 최소 모형. 상태를 갖는다(= 되읽기가 의미를 가진다)."""

    def __init__(self, *, name="원래이름", sale_price=10000, stock=3,
                 detail_html="<p>원래상세</p>", image_urls=("http://cdn/a.jpg",),
                 on_sale=False):
        self.state = {
            "name": name, "sale_price": sale_price, "stock": stock,
            "detail_html": detail_html, "image_urls": tuple(image_urls),
        }
        self.on_sale = on_sale
        self.writes = []          # 전송 이력 — 순서 검사용
        self.fail_on_write = None  # 이 번째 전송에서 예외 (1-based)

    def snapshot(self) -> Snapshot:
        s = self.state
        return Snapshot(
            market="fake", product_id="P1",
            name=s["name"], detail_html=s["detail_html"],
            image_urls=s["image_urls"], sale_price=s["sale_price"],
            options=(("OPT1", s["stock"], 0),), raw=dict(s),
        )

    def apply(self, changes: dict) -> None:
        self.writes.append(dict(changes))
        if self.fail_on_write == len(self.writes):
            raise RuntimeError("마켓 전송 실패(시험)")
        for k, v in changes.items():
            if k == "stock":
                self.state["stock"] = v
            else:
                self.state[k] = v


class RecordingJournal:
    """저널 대역 — 언제 쓰였는지, 무엇이 쓰였는지 기록."""

    def __init__(self, *, fail=False):
        self.entries = []
        self.closed = None
        self.fail = fail
        self.path = "(시험)"

    def write(self, snap: Snapshot) -> None:
        if self.fail:
            raise OSError("저널 쓰기 실패(시험)")
        self.entries.append(snap)

    def close(self, ok: bool, note: str = "") -> None:
        self.closed = (ok, note)


AXES = ("sale_price", "stock", "name", "detail_html", "image_urls")


TEST_IMAGE = "http://cdn/roundtrip-test.png"


def _run(mkt, journal=None, axes=AXES, **kw):
    journal = journal or RecordingJournal()
    kw.setdefault("image_url_fn", lambda: TEST_IMAGE)
    return run_roundtrip(
        snapshot_fn=mkt.snapshot, apply_fn=mkt.apply,
        journal=journal, axes=axes,
        on_sale_fn=lambda: mkt.on_sale, **kw), journal


# ── 규칙 2: 저널 먼저 ────────────────────────────────────────────────────────
def test_저널을_못_쓰면_전송하지_않는다():
    """저널(원복 보험)이 안 남는데 전송하면, 죽었을 때 손복구 근거가 없다."""
    mkt = FakeMarket()
    journal = RecordingJournal(fail=True)

    report, _ = _run(mkt, journal)

    assert mkt.writes == [], "저널 실패인데 마켓에 전송이 나갔다"
    assert report.ok is False
    assert "저널" in (report.refusal or "")


def test_저널은_전송보다_먼저_쓰인다():
    mkt = FakeMarket()
    report, journal = _run(mkt)

    assert len(journal.entries) == 1
    assert journal.entries[0].name == "원래이름", "저널에 담긴 건 '변경 전' 값이어야 한다"
    assert report.ok is True


# ── 규칙 3: 원복은 finally ───────────────────────────────────────────────────
def test_되읽기_검증이_실패해도_원복은_돈다():
    """마켓이 값을 안 받아줘 검증이 깨져도, 시험값을 남긴 채 끝내면 안 된다."""
    mkt = FakeMarket()

    def apply_ignoring_name(changes):
        mkt.writes.append(dict(changes))
        for k, v in changes.items():
            if k == "name":
                continue          # 마켓이 상품명만 조용히 무시
            mkt.state["stock" if k == "stock" else k] = v

    journal = RecordingJournal()
    report = run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=apply_ignoring_name,
                           journal=journal, axes=AXES, on_sale_fn=lambda: False,
                           image_url_fn=lambda: TEST_IMAGE)

    assert report.ok is False, "상품명이 안 바뀌었는데 통과로 봤다"
    assert report.reverted is True
    assert mkt.state["sale_price"] == 10000, "원복이 안 됐다"
    assert mkt.state["stock"] == 3


def test_전송_중_예외가_나도_원복은_돈다():
    mkt = FakeMarket()
    mkt.fail_on_write = 1     # 첫 전송(=시험값)에서 터진다

    report, _ = _run(mkt)

    assert report.ok is False
    assert report.reverted is True
    assert mkt.state == {"name": "원래이름", "sale_price": 10000, "stock": 3,
                         "detail_html": "<p>원래상세</p>",
                         "image_urls": ("http://cdn/a.jpg",)}


# ── 규칙 1: 원복값은 마켓이 준 값 ────────────────────────────────────────────
def test_원복값은_마켓이_실제로_준_값이다():
    """'우리가 보내려던 값'으로 원복하면, 마켓이 우리 뜻과 다르게 갖고 있던 걸 덮어쓴다."""
    mkt = FakeMarket(sale_price=12345)   # 우리 DB 가 어떻든 마켓의 진짜 값

    report, journal = _run(mkt)

    revert = mkt.writes[-1]
    assert revert["sale_price"] == 12345
    assert journal.entries[0].sale_price == 12345
    assert report.ok is True


# ── 규칙 6: 판매중 상품 거부 ─────────────────────────────────────────────────
def test_판매중인_상품은_거부한다():
    mkt = FakeMarket(on_sale=True)

    report, _ = _run(mkt)

    assert mkt.writes == [], "판매중 상품에 전송이 나갔다"
    assert report.ok is False
    assert "판매중" in (report.refusal or "")


# ── 규칙 4: 원복 실패는 시끄럽게 ─────────────────────────────────────────────
def test_원복이_실패하면_크게_알린다():
    mkt = FakeMarket()
    mkt.fail_on_write = 2     # 2번째 전송 = 원복에서 터진다

    report, journal = _run(mkt)

    assert report.ok is False
    assert report.reverted is False
    assert report.revert_error, "원복 실패 사유가 비어 있다"
    assert report.journal_path, "손복구용 저널 경로가 없다"
    assert journal.closed == (False, report.revert_error) or journal.closed[0] is False


# ── 축별 결과 ────────────────────────────────────────────────────────────────
def test_다섯_축_모두_바뀌고_모두_되돌아온다():
    mkt = FakeMarket()

    report, _ = _run(mkt)

    assert report.ok is True
    assert {a.axis for a in report.axes} == set(AXES)
    for a in report.axes:
        assert a.changed_ok, f"{a.axis} 가 안 바뀌었다"
        assert a.restored_ok, f"{a.axis} 가 안 돌아왔다"
    assert mkt.state["name"] == "원래이름"
    assert mkt.state["sale_price"] == 10000


def test_올릴_이미지가_없으면_이미지축은_확인불가다():
    """시험용 이미지를 CDN 에 못 올렸으면, 가짜 URL 을 지어내 보내면 안 된다."""
    mkt = FakeMarket()
    journal = RecordingJournal()

    report = run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=mkt.apply,
                           journal=journal, axes=AXES, on_sale_fn=lambda: False,
                           image_url_fn=None)

    img = next(a for a in report.axes if a.axis == "image_urls")
    assert img.changed_ok is None
    assert "확인불가" in img.note
    for changes in mkt.writes:
        assert "image_urls" not in changes, "없는 이미지를 보냈다"
    assert report.ok is True


def test_마켓이_못_주는_축은_확인불가로_남기고_건드리지_않는다():
    """None = '그 마켓이 안 줌'. 0·빈문자로 채우면 조용히 틀린 값이 전송된다."""
    mkt = FakeMarket()
    mkt.state["detail_html"] = None      # 이 마켓은 상세를 안 준다

    def snap_without_detail():
        s = mkt.snapshot()
        return Snapshot(market=s.market, product_id=s.product_id, name=s.name,
                        detail_html=None, image_urls=s.image_urls,
                        sale_price=s.sale_price, options=s.options,
                        raw=s.raw, missing=("detail_html",))

    journal = RecordingJournal()
    report = run_roundtrip(snapshot_fn=snap_without_detail, apply_fn=mkt.apply,
                           journal=journal, axes=AXES, on_sale_fn=lambda: False,
                           image_url_fn=lambda: TEST_IMAGE)

    detail = next(a for a in report.axes if a.axis == "detail_html")
    assert detail.changed_ok is None, "확인불가를 참·거짓으로 단정했다"
    assert "확인불가" in detail.note
    for changes in mkt.writes:
        assert "detail_html" not in changes, "못 읽는 축을 전송했다(원복 불가)"
    assert report.ok is True, "확인불가는 실패가 아니다 — 다른 축은 통과해야 한다"


# ── 시험값 폭 — 사장님 확정(2026-08-07): 가격 +100원 · 재고 +1 ────────────────
def test_가격은_100원만_올린다():
    """폭이 작을수록 사고가 나도 피해가 작다. 원복 실패 시 남는 차이도 100원이다."""
    mkt = FakeMarket(sale_price=51700)

    report, _ = _run(mkt, axes=("sale_price",))

    p = next(a for a in report.axes if a.axis == "sale_price")
    assert p.sent == 51800, f"100원만 올려야 한다: {p.sent}"


def test_재고는_1개만_늘린다():
    """고정값(7)로 덮으면 원래 재고가 큰 상품에서 재고가 확 줄어 오버셀 위험."""
    mkt = FakeMarket(stock=430)

    report, _ = _run(mkt, axes=("stock",))

    s = next(a for a in report.axes if a.axis == "stock")
    assert s.sent == 431, f"1개만 늘려야 한다: {s.sent}"


def test_재고가_0이어도_1개로_올린다():
    mkt = FakeMarket(stock=0)

    report, _ = _run(mkt, axes=("stock",))

    assert next(a for a in report.axes if a.axis == "stock").sent == 1


# ── 판매중 상품 — 명시적으로 켤 때만 ─────────────────────────────────────────
def test_판매중_상품은_명시적으로_켜야_시험한다():
    """사장님이 「판매중 상품으로 하자」고 확정하면 켤 수 있어야 한다.
    다만 기본은 계속 거부 — 실수로 팔리는 상품을 건드리면 안 된다."""
    mkt = FakeMarket(on_sale=True)

    report, _ = _run(mkt, allow_on_sale=True)

    assert report.refusal is None, "명시적으로 켰는데 거부했다"
    assert report.ok is True


def test_안_켜면_판매중_상품은_그대로_거부한다():
    mkt = FakeMarket(on_sale=True)

    report, _ = _run(mkt)

    assert mkt.writes == []
    assert "판매중" in (report.refusal or "")

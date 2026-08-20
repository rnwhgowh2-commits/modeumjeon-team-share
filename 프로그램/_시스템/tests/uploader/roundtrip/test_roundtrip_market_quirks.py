# -*- coding: utf-8 -*-
"""라이브 1차 실행(2026-08-06)에서 실측으로 드러난 마켓 성질 3가지.

전부 「전송은 됐는데 우리가 못 알아본」 부류다 — 조용히 실패로 보고하면
멀쩡한 배선을 뜯게 된다.

1. 네이버는 상세 HTML 을 **검열**한다. `<p data-roundtrip="1">시험</p>` 을 보내면
   `<!-- Not Allowed Attribute Filtered ( data-roundtrip="1") --><p>시험</p>` 로 돌아온다.
   → 「글자 그대로 같은가」로 보면 상세는 영원히 실패다.
2. 시험 이미지 업로드가 실패했는데 **왜 실패했는지가 보고서에 없었다**(로그에만).
3. 옵션 없는 단일상품은 재고가 `optionCombinations` 가 아니라
   `originProduct.stockQuantity` 에 있다 — 옵션만 보면 「재고 확인불가」가 된다.
"""
from __future__ import annotations

import copy

from lemouton.uploader.roundtrip.markets.smartstore import make_smartstore_ops
from lemouton.uploader.roundtrip.runner import run_roundtrip
from lemouton.uploader.roundtrip.snapshot import Snapshot


class RecordingJournal:
    path = "(시험)"

    def __init__(self):
        self.entries, self.closed = [], None

    def write(self, snap):
        self.entries.append(snap)

    def close(self, ok, note=""):
        self.closed = (ok, note)


# ── 1. 상세 HTML 검열 내성 ───────────────────────────────────────────────────
class SanitizingMarket:
    """네이버처럼 모르는 속성을 주석으로 바꿔치우는 마켓."""

    def __init__(self):
        self.state = {"name": "이름", "sale_price": 1000, "stock": 3,
                      "detail_html": "<p>원래</p>", "image_urls": ("http://cdn/a.jpg",)}

    def snapshot(self):
        s = self.state
        return Snapshot(market="fake", product_id="P", name=s["name"],
                        detail_html=s["detail_html"], image_urls=s["image_urls"],
                        sale_price=s["sale_price"],
                        options=(("O1", s["stock"], 0),), raw=dict(s))

    def apply(self, changes):
        for k, v in changes.items():
            if k == "detail_html":
                # 속성을 통째로 주석으로 바꿔치운다(네이버 실제 동작)
                v = str(v).replace(' data-roundtrip="1"',
                                   '"/><!-- Not Allowed Attribute Filtered -->')
            self.state["stock" if k == "stock" else k] = v


def test_마켓이_상세HTML을_검열해도_바뀐_것을_알아본다():
    mkt = SanitizingMarket()
    journal = RecordingJournal()

    report = run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=mkt.apply,
                           journal=journal, axes=("detail_html",),
                           on_sale_fn=lambda: False)

    detail = report.axes[0]
    assert detail.changed_ok is True, \
        "마켓이 HTML 을 손봤다고 「안 바뀌었다」로 보면 안 된다"
    assert detail.restored_ok is True
    assert mkt.state["detail_html"] == "<p>원래</p>", "원복이 안 됐다"


def test_상세가_정말로_안_바뀌면_실패로_잡는다():
    """검열 내성이 「무조건 통과」가 되면 진짜 실패를 놓친다."""
    mkt = SanitizingMarket()

    def apply_ignoring_detail(changes):
        for k, v in changes.items():
            if k == "detail_html":
                continue
            mkt.state["stock" if k == "stock" else k] = v

    report = run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=apply_ignoring_detail,
                           journal=RecordingJournal(), axes=("detail_html",),
                           on_sale_fn=lambda: False)

    assert report.axes[0].changed_ok is False


# ── 2. 이미지 업로드 실패 사유 표면화 ────────────────────────────────────────
def test_시험이미지_업로드가_실패하면_사유를_보고서에_담는다():
    """「확인불가」만 있고 왜인지가 없으면 사장님이 원인을 못 찾는다."""
    mkt = SanitizingMarket()

    def boom():
        raise RuntimeError("CDN 이 415 를 줬습니다")

    report = run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=mkt.apply,
                           journal=RecordingJournal(), axes=("image_urls",),
                           on_sale_fn=lambda: False, image_url_fn=boom)

    img = report.axes[0]
    assert img.changed_ok is None
    assert "CDN 이 415 를 줬습니다" in img.note, f"실패 사유가 없다: {img.note!r}"


# ── 3. 옵션 없는 단일상품의 재고 ─────────────────────────────────────────────
def _single_product(stock=5):
    return {"originProduct": {
        "name": "단일상품", "salePrice": 1000, "statusType": "SUSPENSION",
        "stockQuantity": stock, "detailContent": "<p>d</p>",
        "images": {"representativeImage": {"url": "http://cdn/a.jpg"}},
        "detailAttribute": {"optionInfo": {}},      # 옵션 없음
    }}


class SingleProductClient:
    def __init__(self):
        self.product = _single_product()
        self.puts = []

    def request(self, method, path, body=None, **kw):
        if method == "GET":
            return copy.deepcopy(self.product)
        if method == "PUT":
            self.puts.append(copy.deepcopy(body))
            self.product = copy.deepcopy(body)
            return {"originProductNo": 1}
        raise AssertionError(method)


def test_옵션이_없는_상품은_상품재고를_읽는다():
    ops = make_smartstore_ops(1, client=SingleProductClient())

    s = ops.snapshot()

    assert s.value_of("stock") == 5, "옵션이 없다고 재고를 확인불가로 두면 안 된다"
    assert "stock" not in s.missing


def test_옵션이_없는_상품은_상품재고에_쓴다():
    cli = SingleProductClient()
    ops = make_smartstore_ops(1, client=cli)

    ops.apply({"stock": 7})

    assert cli.puts[-1]["originProduct"]["stockQuantity"] == 7
    assert ops.snapshot().value_of("stock") == 7


# ── 4. 승인 후 반영되는 축 — 「안 바뀜」과 「승인 대기」를 가른다 ─────────────
def test_승인이_필요한_축은_안_바뀌어도_실패로_적지_않는다():
    """쿠팡 상품명·상세·이미지는 승인 후 반영이라 보낸 직후엔 옛 값이다.
    그걸 「실패」로 적으면 거짓 보고다 — 「보냈고, 승인 후 반영」으로 적는다."""
    mkt = SanitizingMarket()

    def apply_pending(changes):
        # 마켓이 접수는 하되 조회에는 아직 안 보여준다(승인 대기)
        for k, v in changes.items():
            if k == "name":
                continue
            mkt.state["stock" if k == "stock" else k] = v

    report = run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=apply_pending,
                           journal=RecordingJournal(), axes=("name",),
                           on_sale_fn=lambda: False,
                           approval_axes=("name",))

    nm = report.axes[0]
    assert nm.changed_ok is None, "승인 대기를 실패로 단정했다"
    assert "승인" in nm.note
    assert report.ok is True, "승인 대기는 실패가 아니다"


def test_승인축이_아니면_안_바뀐_것은_그대로_실패다():
    """승인 예외가 아무 축에나 적용되면 진짜 실패를 놓친다."""
    mkt = SanitizingMarket()

    def apply_ignoring_name(changes):
        for k, v in changes.items():
            if k == "name":
                continue
            mkt.state["stock" if k == "stock" else k] = v

    report = run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=apply_ignoring_name,
                           journal=RecordingJournal(), axes=("name",),
                           on_sale_fn=lambda: False,
                           approval_axes=("detail_html",))

    assert report.axes[0].changed_ok is False
    assert report.ok is False


def test_승인축도_원복은_반드시_보낸다():
    """승인 대기라고 원복을 건너뛰면, 승인 나는 순간 시험값이 라이브에 뜬다."""
    mkt = SanitizingMarket()
    sent = []

    def apply_recording(changes):
        sent.append(dict(changes))
        for k, v in changes.items():
            if k == "name":
                continue
            mkt.state["stock" if k == "stock" else k] = v

    run_roundtrip(snapshot_fn=mkt.snapshot, apply_fn=apply_recording,
                  journal=RecordingJournal(), axes=("name",),
                  on_sale_fn=lambda: False, approval_axes=("name",))

    assert len(sent) == 2, "원복 전송이 없다"
    assert sent[-1]["name"] == "이름", "원복이 원래값이 아니다"


# ── 5. 반영이 지연되는 축 — 즉시 되읽기로 판정하면 안 된다 ───────────────────
def test_반영이_늦는_축은_잠깐_기다렸다_다시_읽는다():
    """🔴 [2026-08-07 라이브] 쿠팡 재고는 **반영이 지연**된다.
       10 → 11 을 보내고 즉시 읽으면 아직 10. 원복(10) 뒤에 읽으니 11 이었다.
       (몇 초 뒤 다시 읽으니 10 — 원복은 제대로 됐다)

       한 번 읽고 「안 바뀜/원복 실패」로 단정하면 거짓 보고가 된다.
       못 맞으면 잠깐 기다렸다 한 번 더 읽는다.
    """
    calls = {"n": 0}
    state = {"stock": 3}

    def snapshot_fn():
        calls["n"] += 1
        # 3번째 읽기부터 반영된다(지연 흉내)
        val = state["stock"] if calls["n"] >= 3 else 3
        return Snapshot(market="fake", product_id="P", name="이름",
                        detail_html="<p>d</p>", image_urls=("http://cdn/a.jpg",),
                        sale_price=1000, options=(("O1", val, 0),), raw={})

    def apply_fn(changes):
        state.update(changes)

    report = run_roundtrip(snapshot_fn=snapshot_fn, apply_fn=apply_fn,
                           journal=RecordingJournal(), axes=("stock",),
                           on_sale_fn=lambda: False, recheck_sleep=0)

    st = report.axes[0]
    assert st.changed_ok is True, f"지연 반영을 「안 바뀜」으로 단정했다: {st.note}"


def test_다시_읽어도_안_맞으면_그대로_실패다():
    """재확인이 「무조건 통과」가 되면 진짜 실패를 놓친다."""
    state = {"stock": 3}

    def snapshot_fn():
        return Snapshot(market="fake", product_id="P", name="이름",
                        detail_html="<p>d</p>", image_urls=("http://cdn/a.jpg",),
                        sale_price=1000, options=(("O1", 3, 0),), raw={})

    report = run_roundtrip(snapshot_fn=snapshot_fn, apply_fn=lambda c: None,
                           journal=RecordingJournal(), axes=("stock",),
                           on_sale_fn=lambda: False, recheck_sleep=0)

    assert report.axes[0].changed_ok is False

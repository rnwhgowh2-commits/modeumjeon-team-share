# -*- coding: utf-8 -*-
"""이행 판단 ② — 「값이 바뀌는 상품」만 확인 요청 (노션 ⑤).

사장님 확정(2026-08-13): 「변경값」 = **그 상품의 가격·재고가 바뀐 것**.
🔴 그 신호를 새로 만들지 않는다 — 크롤이 이미 남긴다(`no_change_streak`:
   가격·재고가 바뀌면 0, 그대로면 +1). 새 신호를 만들면 원천이 둘로 갈린다.
🔴 표식만 찍고 여기서 긁지 않는다 — 크롤은 사장님 PC 확장 몫이다.
"""
import datetime as dt

import pytest

from lemouton.orders import fulfillment as FF


class _SP:
    def __init__(self, pid, url="https://x/1", weight=1, streak=0):
        self.id = pid
        self.url = url
        self.crawl_weight = weight
        self.no_change_streak = streak
        self.deleted_at = None
        self.recheck_requested_at = None


class _Sess:
    """세션 대역 — `request_recheck` 이 부르는 질의만 흉내낸다."""

    def __init__(self, sps, models=("M1",), sp_ids=None):
        self._sps = sps
        self._models = list(models)
        self._sp_ids = sp_ids if sp_ids is not None else [p.id for p in sps]
        self._mode = None

    def query(self, *cols):
        col = cols[0]
        name = getattr(col, "key", None) or getattr(col, "__name__", "")
        self._mode = str(name)
        return self

    def filter(self, *a, **k):
        return self

    def distinct(self):
        return self

    def all(self):
        if self._mode == "model_code":
            return [(m,) for m in self._models]
        if self._mode == "source_product_id":
            return [(i,) for i in self._sp_ids]
        return list(self._sps)


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr("lemouton.claims.service.claim_type_of", lambda r: None)
    monkeypatch.setattr(
        "lemouton.orders.price_diff.resolve_targets_verbose",
        lambda s, rows: {i: {"sku": f"SKU{i}"} for i, _ in enumerate(rows)})


def _rows(n=2):
    return [{"오픈마켓주문번호": f"O{i}"} for i in range(n)]


def test_값이_바뀐_상품만_요청한다(patched):
    """streak 0 = 마지막 크롤에서 가격·재고가 바뀐 상품 → 다시 긁는다."""
    changed, stable = _SP(1, streak=0), _SP(2, streak=3)
    out = FF.request_recheck(_Sess([changed, stable]), _rows(), now=dt.datetime(2026, 8, 13))
    assert out["요청"] == 1
    assert out["값이_안_바뀌는_상품"] == 1
    assert changed.recheck_requested_at == dt.datetime(2026, 8, 13)
    assert stable.recheck_requested_at is None      # 저장된 크롤값 그대로 쓴다


def test_소싱처_URL_없으면_안_긁는다(patched):
    """사장님: 「해당 주문건에 소싱처 url 있는것만 긁으면 돼」."""
    no_url = _SP(1, url="", streak=0)
    out = FF.request_recheck(_Sess([no_url]), _rows())
    assert out["요청"] == 0 and out["소싱처URL_없음"] == 1
    assert no_url.recheck_requested_at is None


def test_크롤제외_상품은_뒤집지_않는다(patched):
    """계수 0 = 「이 URL 은 안 긁는다」 — 사장님이 정한 뜻이다."""
    excluded = _SP(1, weight=0, streak=0)
    out = FF.request_recheck(_Sess([excluded]), _rows())
    assert out["요청"] == 0 and out["크롤제외"] == 1
    assert excluded.recheck_requested_at is None


def test_빈_주문이면_아무것도_안_한다(patched):
    assert FF.request_recheck(_Sess([]), [])["요청"] == 0


def test_왜_적게_골랐는지를_말한다(patched):
    """숫자만 주면 「왜 1건뿐이지?」에 답할 수 없다 — 사유별로 센다."""
    out = FF.request_recheck(
        _Sess([_SP(1, streak=0), _SP(2, streak=5), _SP(3, url=""), _SP(4, weight=0)]),
        _rows())
    assert out["요청"] == 1
    assert out["값이_안_바뀌는_상품"] == 1
    assert out["소싱처URL_없음"] == 1
    assert out["크롤제외"] == 1

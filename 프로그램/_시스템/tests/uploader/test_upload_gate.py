# -*- coding: utf-8 -*-
"""[TEST] Phase 1B M3-1 — 업로드 게이트 판정 + 역마진 가드 + 크롤 실패 처리.

여기서 검증하는 사고 시나리오:
  · "재고 5→3이라 스킵" 하다가 같이 바뀐 가격을 못 올려 역마진이 되는 것
  · 크롤 실패를 '변동 없음'으로 세서 크롤 주기가 잘못 늘어나는 것
  · 스킵했는데 사유가 안 남아 '조용한 실패'와 구분이 안 되는 것
  · 역마진 가드가 품절 반영까지 막아 오버셀을 만드는 것
"""
import pytest

from lemouton.uploader.upload_gate import (
    GateDecision, STOCK_UNKNOWN, decide_upload,
)


def _d(**kw) -> GateDecision:
    """직전 스냅샷 기본값 = 가격 10,000원 / 재고 5개."""
    base = dict(prev_price=10000, prev_stock=5, new_price=10000, new_stock=5)
    base.update(kw)
    return decide_upload(**base)


class TestPriceWinsOverStock:
    """가격 변동이면 재고 조건과 무관하게 항상 올린다."""

    def test_price_change_with_plenty_stock_still_uploads(self):
        """★핵심 회귀: 재고 5→3(스킵 구간)인데 가격도 바뀌었다 → 반드시 업로드."""
        d = _d(new_price=11000, new_stock=3)
        assert d.should_upload is True
        assert d.priority == "P0"
        assert d.reason_code == "price_change"
        assert d.price_changed is True

    def test_price_change_with_untouched_plenty_stock(self):
        d = _d(new_price=9000, new_stock=5)
        assert d.should_upload is True
        assert d.priority == "P0"

    def test_price_change_beats_plenty_to_plenty_10_to_3(self):
        d = _d(prev_stock=10, new_price=12000, new_stock=3)
        assert d.should_upload is True
        assert d.reason_code == "price_change"


class TestStockRules:
    """가격 무변동 + 재고만 변동일 때의 규약."""

    def test_in_stock_to_sold_out_is_p0(self):
        d = _d(prev_stock=5, new_stock=0)
        assert d.should_upload is True
        assert d.priority == "P0"
        assert d.reason_code == "sold_out"

    def test_plenty_to_low_is_p1(self):
        """≥3 → ≤2 = 품절임박."""
        d = _d(prev_stock=5, new_stock=2)
        assert d.should_upload is True
        assert d.priority == "P1"
        assert d.reason_code == "low_stock"

    def test_restock_is_p1(self):
        d = _d(prev_stock=0, new_stock=4)
        assert d.should_upload is True
        assert d.priority == "P1"
        assert d.reason_code == "restock"

    @pytest.mark.parametrize("prev,new", [(5, 3), (3, 4), (10, 3)])
    def test_plenty_to_plenty_skipped(self, prev, new):
        """둘 다 3개 이상 = 판매에 영향 없음 → 스킵(P0 지연 방지)."""
        d = _d(prev_stock=prev, new_stock=new)
        assert d.should_upload is False
        assert d.priority == "P2"
        assert d.reason_code == "plenty_to_plenty"

    @pytest.mark.parametrize("prev,new", [(1, 2), (2, 1)])
    def test_change_inside_low_band_uploads(self, prev, new):
        """≤2 구간 안의 변동은 오차 하나가 오버셀이라 올린다."""
        d = _d(prev_stock=prev, new_stock=new)
        assert d.should_upload is True
        assert d.priority == "P1"
        assert d.reason_code == "low_stock_band"

    def test_no_change_at_all_is_skipped(self):
        d = _d(prev_price=10000, prev_stock=5, new_price=10000, new_stock=5)
        assert d.should_upload is False
        assert d.priority == "P2"
        assert d.reason_code == "no_change"
        assert d.counts_as_no_change is True

    def test_sold_out_to_sold_out_not_reuploaded(self):
        """이미 올려둔 품절을 다시 올리는 건 큐 낭비다."""
        d = _d(prev_stock=0, new_stock=0)
        assert d.should_upload is False
        assert d.reason_code == "no_change"

    def test_999_counts_as_plenty(self):
        """999 = '있음'(집 관례). 넉넉 구간으로 다룬다."""
        d = _d(prev_stock=999, new_stock=999)
        assert d.should_upload is False
        d2 = _d(prev_stock=999, new_stock=0)
        assert d2.reason_code == "sold_out"


class TestFirstUpload:
    def test_no_previous_snapshot_uploads(self):
        d = decide_upload(prev_price=None, prev_stock=None,
                          new_price=10000, new_stock=5)
        assert d.should_upload is True
        assert d.priority == "P0"
        assert d.reason_code == "first_upload"

    def test_previous_stock_unknown_resyncs(self):
        """직전 재고가 '확인불가'였으면 기준선이 없다 → 현재 값으로 맞춘다."""
        d = _d(prev_stock=STOCK_UNKNOWN, new_stock=5)
        assert d.should_upload is True
        assert d.reason_code == "prev_stock_unknown"


class TestCrawlFailure:
    """폴백 금지 — 못 가져왔으면 '확인불가'로 두고 기존 값을 유지한다."""

    def test_both_unknown_keeps_existing_and_is_not_no_change(self):
        d = _d(new_price=None, new_stock=None)
        assert d.should_upload is False
        assert d.reason_code == "crawl_failed"
        # ★실패를 안정으로 오독하면 크롤 계수가 잘못 내려간다.
        assert d.counts_as_no_change is False
        assert d.price_changed is False and d.stock_changed is False

    def test_stock_unknown_sentinel_minus_one(self):
        d = _d(new_stock=STOCK_UNKNOWN)
        assert d.should_upload is False
        assert d.reason_code == "stock_unknown"
        assert d.stock_known is False
        assert d.counts_as_no_change is False

    def test_price_unknown_but_stock_sold_out_still_uploads(self):
        """가격을 못 읽어도 품절은 내려야 한다 — 가격 축만 기존 유지."""
        d = _d(new_price=None, new_stock=0)
        assert d.should_upload is True
        assert d.reason_code == "sold_out"
        assert d.price_known is False
        assert any("가격 확인불가" in w for w in d.warnings)

    def test_unknown_price_is_never_counted_as_price_change(self):
        d = _d(new_price=None, new_stock=2)
        assert d.price_changed is False
        assert d.price_known is False

    def test_zero_price_is_a_value_not_a_failure(self):
        """0원은 실제 값이다. None(실패)과 구분된다."""
        d = _d(prev_price=10000, new_price=0)
        assert d.price_known is True
        assert d.price_changed is True
        assert d.reason_code == "price_change"


class TestMarginGuard:
    """기준은 마진율이 아니라 마진금액(원). 미만이면 보류 + 판매중지 후보."""

    def test_below_min_margin_is_held_with_warning(self):
        d = _d(new_price=11000, margin_amount=300, min_margin_amount=1000)
        assert d.should_upload is False
        assert d.held_for_margin is True
        assert d.needs_sale_stop is True
        assert d.reason_code == "margin_below_min"
        assert any("역마진 경고" in w for w in d.warnings)

    def test_at_threshold_passes(self):
        """'미만'이 기준 — 같으면 통과."""
        d = _d(new_price=11000, margin_amount=1000, min_margin_amount=1000)
        assert d.should_upload is True
        assert d.held_for_margin is False

    def test_default_threshold_zero_blocks_only_negative(self):
        assert _d(new_price=11000, margin_amount=0).should_upload is True
        assert _d(new_price=11000, margin_amount=-1).should_upload is False

    def test_unknown_margin_does_not_block(self):
        """모르는 값을 '미달'로 단정해 P0 를 막지 않는다."""
        d = _d(new_price=11000, margin_amount=None, min_margin_amount=5000)
        assert d.should_upload is True
        assert d.held_for_margin is False

    def test_sold_out_upload_never_blocked_by_margin(self):
        """★품절 반영은 '파는 행위'가 아니라 '멈추는 행위'. 막으면 오버셀을 만든다."""
        d = _d(prev_stock=5, new_stock=0, margin_amount=-9999, min_margin_amount=1000)
        assert d.should_upload is True
        assert d.reason_code == "sold_out"
        assert d.needs_sale_stop is True

    def test_skip_is_not_turned_into_hold(self):
        """이미 스킵인 건은 마진 가드가 건드리지 않는다(사유가 바뀌면 안 됨)."""
        d = _d(prev_stock=5, new_stock=3, margin_amount=-500, min_margin_amount=1000)
        assert d.should_upload is False
        assert d.reason_code == "plenty_to_plenty"
        assert d.held_for_margin is False


class TestReasonIsAlwaysRecorded:
    """스킵도 '왜'를 말해야 한다 — 조용한 실패로 오인 방지."""

    @pytest.mark.parametrize("kw", [
        dict(new_stock=3),                              # plenty_to_plenty
        dict(),                                         # no_change
        dict(new_price=None, new_stock=None),           # crawl_failed
        dict(new_stock=STOCK_UNKNOWN),                  # stock_unknown
        dict(new_price=11000, margin_amount=-1),        # margin_below_min
    ])
    def test_every_skip_has_code_and_sentence(self, kw):
        d = _d(**kw)
        assert d.should_upload is False
        assert d.skipped is True
        assert d.reason_code, "스킵 사유 코드가 비었다"
        assert len(d.reason) > 5, "사람이 읽을 사유가 비었다"
        assert d.priority in ("P0", "P1", "P2")

    def test_to_dict_action_labels(self):
        assert _d(new_stock=3).to_dict()["action"] == "skip"
        assert _d(new_price=11000).to_dict()["action"] == "upload"
        assert _d(new_price=11000, margin_amount=-1).to_dict()["action"] == "hold"

    def test_to_dict_is_json_safe(self):
        import json
        json.dumps(_d(new_price=11000).to_dict(), ensure_ascii=False)

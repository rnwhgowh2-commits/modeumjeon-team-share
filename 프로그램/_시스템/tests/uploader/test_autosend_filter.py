# -*- coding: utf-8 -*-
"""[TEST] 변동 종류 토글 필터 — 소싱처 가격/재고 변동만 골라 보낸다.

자동화 설정의 토글을 실제 전송에 연결한다(전엔 저장만 되고 미배선).
  · autosend_on_price  : 가격이 바뀐 것만
  · autosend_on_stock  : 재고가 바뀐 것 중, 임계 이하(autosend_stock_threshold)만
  · 사입 토글(autosend_on_purchase) 은 소스 구분이 페이로드에 없어 이번 범위 밖.
"""
from lemouton.uploader.orchestrator import autosend_keep


def _auto(price=True, stock=True, thr=4):
    return {"autosend_on_price": price, "autosend_on_stock": stock,
            "autosend_stock_threshold": thr}


class TestAutosendFilter:
    def test_price_change_kept_when_price_on(self):
        assert autosend_keep(1000, 1200, 5, 5, _auto()) is True

    def test_price_change_dropped_when_price_off(self):
        assert autosend_keep(1000, 1200, 5, 5, _auto(price=False)) is False

    def test_stock_change_kept_when_below_threshold(self):
        """재고가 임계(4) 이하로 바뀌면 보냄."""
        assert autosend_keep(1000, 1000, 10, 3, _auto()) is True

    def test_stock_change_dropped_when_above_threshold(self):
        """재고 변동이라도 임계 초과면 안 보냄(임박분만)."""
        assert autosend_keep(1000, 1000, 3, 50, _auto()) is False

    def test_stock_change_dropped_when_stock_off(self):
        assert autosend_keep(1000, 1000, 10, 2, _auto(stock=False)) is False

    def test_both_changed_kept_if_either_qualifies(self):
        """가격도 재고도 바뀜 — 가격 토글만 켜도 보냄(API는 둘 다 실어 감)."""
        assert autosend_keep(1000, 1200, 3, 99, _auto(stock=False)) is True

    def test_no_change_not_kept(self):
        assert autosend_keep(1000, 1000, 5, 5, _auto()) is False

    def test_all_off_never_sends(self):
        assert autosend_keep(1000, 1200, 10, 1, _auto(price=False, stock=False)) is False

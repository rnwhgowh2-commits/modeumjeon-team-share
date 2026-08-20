# -*- coding: utf-8 -*-
"""ESM 옵션 실구조 대응 — 2026-07-21 라이브 recommended-options 응답 기준.

라이브 실측(옥션 6390698993)에서 옵션 구조가 우리 가정과 달랐다:
  · 옵션 식별자 = **optSeq**(예 27303973382). manageCode 는 null, recommendedOptNo 없음,
    recommendedOptValueNo 는 0(무용). → 우리 _option_id_of 가 optSeq 를 몰라 옵션을 못 찾고
    재고 읽기·쓰기가 통째로 실패했다(오버셀 근본).
  · 품절은 **isSoldOutSite:{gmkt,iac}** 사이트별. top-level isSoldOut 도 있지만, 한 사이트만
    내릴 때 top-level 을 건드리면 양쪽이 다 내려간다.
  · 노출도 isDisplaySite:{gmkt,iac}, 수량은 qty:{iac,gmkt}.
"""
from __future__ import annotations

import pytest

from shared.platforms.esm import inventory as INV
from shared.platforms.esm.inventory import _option_id_of


def _real_details():
    """라이브 응답 구조를 그대로 옮긴 옵션 2개(S, M)."""
    return [
        {"recommendedOptValueNo": 0,
         "recommendedOptValue": {"koreanText": "S"},
         "optSeq": 27303973382, "isSoldOut": False,
         "isSoldOutSite": {"gmkt": False, "iac": False}, "isDisplay": True,
         "isDisplaySite": {"gmkt": False, "iac": True},
         "qty": {"iac": 10, "gmkt": 99999}, "manageCode": None,
         "addAmntSite": {"gmkt": 0.0, "iac": 0.0}},
        {"recommendedOptValueNo": 0,
         "recommendedOptValue": {"koreanText": "M"},
         "optSeq": 27303973383, "isSoldOut": False,
         "isSoldOutSite": {"gmkt": False, "iac": False}, "isDisplay": True,
         "isDisplaySite": {"gmkt": False, "iac": True},
         "qty": {"iac": 10, "gmkt": 99999}, "manageCode": None,
         "addAmntSite": {"gmkt": 0.0, "iac": 0.0}},
    ]


class _FakeClient:
    def __init__(self, details, put_resp=None):
        self._details = details
        self._put_resp = put_resp or {"resultCode": 0}
        self.calls = []
        self._cfg = {"paths": {"options": "/item/v1/goods/{goodsNo}/recommended-options"}}

    def request(self, *, method, path, body=None, **kw):
        self.calls.append({"method": method, "path": path, "body": body})
        # GET 은 실제 봉투 구조({type,isStockManage,independent:{details}}) 를 준다.
        if method == "GET":
            return {"type": 1, "isStockManage": True,
                    "independent": {"details": self._details, "recommendedOptNo": 976}}
        return self._put_resp


def _put_details(cli):
    # PUT 은 GET 봉투 통째로({independent:{details}}) 되돌린다 → 그 안 details 를 꺼낸다.
    body = [c for c in cli.calls if c["method"] == "PUT"][0]["body"]
    return body["independent"]["details"]


def _put_has_envelope(cli):
    body = [c for c in cli.calls if c["method"] == "PUT"][0]["body"]
    return "type" in body and "independent" in body


def _by_seq(details, seq):
    return next(d for d in details if str(d.get("optSeq")) == str(seq))


class TestOptSeqIsIdentifier:
    def test_option_id_of_reads_optSeq(self):
        assert _option_id_of(_real_details()[0]) == "27303973382"

    def test_update_matches_by_optSeq(self):
        cli = _FakeClient(_real_details())
        ok = INV.update_stock("6390698993", "auction", "27303973382", 7, client=cli)
        assert ok is True
        sent = _by_seq(_put_details(cli), 27303973382)
        assert sent["qty"]["iac"] == 7          # 옥션 재고만 변경
        assert sent["qty"]["gmkt"] == 99999     # G마켓은 보존

    def test_put_sends_full_envelope_not_bare_details(self):
        """PUT 은 GET 봉투 통째로 — {"details":...} 만 보내면 400(type 필수)."""
        cli = _FakeClient(_real_details())
        INV.update_stock("6390698993", "auction", "27303973382", 7, client=cli)
        assert _put_has_envelope(cli)

    def test_unknown_optSeq_fails_not_silent(self):
        cli = _FakeClient(_real_details())
        assert INV.update_stock("6390698993", "auction", "99999999", 7, client=cli) is False
        assert not [c for c in cli.calls if c["method"] == "PUT"]


class TestPerSiteSoldOut:
    """한 사이트만 품절 — isSoldOutSite[site] 만 건드리고 반대편은 보존."""

    def test_zero_stock_sets_site_soldout_only(self):
        cli = _FakeClient(_real_details())
        INV.update_stock("6390698993", "auction", "27303973382", 0, client=cli)
        sent = _by_seq(_put_details(cli), 27303973382)
        assert sent["isSoldOutSite"]["iac"] is True     # 옥션만 품절
        assert sent["isSoldOutSite"]["gmkt"] is False    # G마켓 보존
        assert sent["qty"]["iac"] != 0                    # qty 0 금지(규격)

    def test_restock_clears_site_soldout(self):
        det = _real_details()
        _by_seq(det, 27303973382)["isSoldOutSite"] = {"gmkt": False, "iac": True}
        cli = _FakeClient(det)
        INV.update_stock("6390698993", "auction", "27303973382", 15, client=cli)
        sent = _by_seq(_put_details(cli), 27303973382)
        assert sent["isSoldOutSite"]["iac"] is False
        assert sent["qty"]["iac"] == 15

    def test_all_soldout_on_that_site_refused(self):
        # 옥션에서 S 는 이미 품절, 마지막 판매가능 M 을 품절시키면 옥션 전멸 → 거부.
        det = _real_details()
        _by_seq(det, 27303973382)["isSoldOutSite"] = {"gmkt": False, "iac": True}
        cli = _FakeClient(det)
        with pytest.raises(ValueError) as e:
            INV.update_stock("6390698993", "auction", "27303973383", 0, client=cli)
        assert "판매중지" in str(e.value)
        assert not [c for c in cli.calls if c["method"] == "PUT"]

    def test_other_site_soldout_does_not_block(self):
        # G마켓이 전멸이어도 옥션 업데이트는 막지 않는다(사이트별 독립).
        det = _real_details()
        for d in det:
            d["isSoldOutSite"] = {"gmkt": True, "iac": False}
        cli = _FakeClient(det)
        assert INV.update_stock("6390698993", "auction", "27303973382", 5, client=cli) is True

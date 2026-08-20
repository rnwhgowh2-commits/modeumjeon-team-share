# -*- coding: utf-8 -*-
"""[TEST] 쿠팡 매출내역(revenue-history) — 계정별 vendorId 사용.

멀티계정에서 vendorId 는 계정 클라이언트 config 에 주입된다. 전역 COUPANG["vendor_id"] 는
UI 저장 키가 COUPANG_MAIN_* 접두라 비어있어, 전역을 쓰면 HTTP 400(vendorId null)→정산 전멸
→estimated 조용히 폴백(오차). 라이브 진단(_probe_cp_revmap)에서 7계정 전부 이 400 확인 후 수정.
"""
from shared.platforms.coupang.settlements import fetch_revenue_page


class _FakeClient:
    def __init__(self, cfg):
        self._cfg = cfg
        self.query = None

    def request(self, method, path, query=""):
        self.query = query
        return {"data": [], "hasNext": False}


def test_uses_account_vendor_id_from_client_cfg():
    fake = _FakeClient({"vendor_id": "A00099999"})
    fetch_revenue_page("2026-06-01", "2026-06-30", client=fake)
    assert "vendorId=A00099999" in fake.query          # 계정 vendor_id 사용
    assert "vendorId=&" not in fake.query               # null 아님(400 방지)


def test_falls_back_to_env_when_cfg_missing(monkeypatch):
    monkeypatch.setenv("COUPANG_VENDOR_ID", "A00011111")
    fake = _FakeClient({})                              # config 에 vendor_id 없음
    fetch_revenue_page("2026-06-01", "2026-06-30", client=fake)
    assert "vendorId=A00011111" in fake.query          # 전역 env 폴백

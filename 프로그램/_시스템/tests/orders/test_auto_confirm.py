# -*- coding: utf-8 -*-
"""[TEST] 자동전환 — 「결제완료 → 배송준비중」 마켓·계정별 ON/OFF + 드라이런 안전.

핵심 검증:
  · 결제완료/신규만 대상, 준비중·배송·취소는 제외 (완료라는 글자에 결제'완료'가 안 걸림).
  · 설정은 계정 leaf 단위 · 마켓/전체 스위치는 파생.
  · LIVE 스위치 OFF 면 live=true 로 눌러도 실제 전환 없이 드라이런(집계만) — 외부호출 0.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.orders import auto_confirm as ac


@pytest.fixture
def session():
    from lemouton.sourcing.models_v2 import (AutoConfirmSetting, AutoConfirmConfig,
                                             AutoConfirmLog)
    eng = create_engine("sqlite:///:memory:")
    for m in (AutoConfirmSetting, AutoConfirmConfig, AutoConfirmLog):
        m.__table__.create(eng)
    s = sessionmaker(bind=eng, autoflush=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def accounts(monkeypatch):
    """활성 계정을 고정 — 쿠팡 2계정, 롯데온 1계정."""
    mapping = {
        "coupang": [("_MAIN", "브랜드위시"), ("_2", "브랜드다임")],
        "lotteon": [("_MAIN", "르무통")],
        "smartstore": [], "eleven11": [],
    }
    monkeypatch.setattr(ac._oe, "_active_accounts", lambda m: mapping.get(m, []))
    monkeypatch.setattr(ac._oe, "_account_alias", lambda m: "대표 계정")
    return mapping


class TestTargetLogic:
    @pytest.mark.parametrize("status,expected", [
        ("결제완료", True), ("신규주문", True), ("신규", True),
        ("배송준비중", False), ("상품준비중", False), ("배송완료", False),
        ("구매확정", False), ("취소요청", False), ("반품완료", False),
    ])
    def test_only_paid_orders_are_targets(self, status, expected):
        assert ac.is_confirm_target(status) is expected


class TestSettings:
    def test_default_all_off(self, session, accounts):
        tree = ac.list_settings(session)
        cp = next(m for m in tree["markets"] if m["market"] == "coupang")
        assert cp["total"] == 2 and cp["enabled_count"] == 0
        assert all(a["enabled"] is False for a in cp["accounts"])
        # 자동 실행은 기본 꺼짐 · 이력 비어 있음
        assert tree["auto"]["enabled"] is False and tree["logs"] == []

    def test_emergency_disable_env_forces_dryrun(self, session, accounts, monkeypatch):
        monkeypatch.setenv("MOUM_CONFIRM_DISABLED", "1")
        assert ac.live_confirm_enabled() is False
        assert ac.list_settings(session)["live"] is False

    def test_set_account_then_reflected(self, session, accounts):
        ac.set_account(session, "coupang", "브랜드위시", True)
        cp = next(m for m in ac.list_settings(session)["markets"] if m["market"] == "coupang")
        got = {a["alias"]: a["enabled"] for a in cp["accounts"]}
        assert got == {"브랜드위시": True, "브랜드다임": False}
        assert cp["enabled_count"] == 1

    def test_set_market_toggles_all_accounts(self, session, accounts):
        n = ac.set_market(session, "coupang", True)
        assert n == 2
        cp = next(m for m in ac.list_settings(session)["markets"] if m["market"] == "coupang")
        assert cp["enabled_count"] == 2

    def test_set_all(self, session, accounts):
        ac.set_all(session, True)
        leaves = set(ac.enabled_leaves(session))
        # 계정이 등록된 마켓은 그 계정들, 미등록 마켓은 '대표 계정' 폴백 leaf.
        assert {("coupang", "브랜드위시"), ("coupang", "브랜드다임"),
                ("lotteon", "르무통")} <= leaves

    def test_set_all_scoped_to_given_markets(self, session, accounts):
        ac.set_all(session, True, markets=["coupang"])
        assert set(ac.enabled_leaves(session)) == {
            ("coupang", "브랜드위시"), ("coupang", "브랜드다임")}

    def test_alias_suffix_normalized(self, session, accounts):
        # 주문행 별칭이 '브랜드위시(쿠팡)' 로 와도 설정 '브랜드위시' 와 같은 것으로 취급
        ac.set_account(session, "coupang", "브랜드위시(쿠팡)", True)
        assert ("coupang", "브랜드위시") in ac.enabled_leaves(session)

    def test_unsupported_market_rejected(self, session, accounts):
        with pytest.raises(ValueError):
            ac.set_account(session, "gmarket", "x", True)


class TestRunDryRun:
    def _stub_orders(self, monkeypatch):
        rows = {
            "coupang": [
                {"판매처": "쿠팡", "쇼핑몰별칭": "브랜드위시", "주문상태": "결제완료", "오픈마켓주문번호": "C1"},
                {"판매처": "쿠팡", "쇼핑몰별칭": "브랜드위시", "주문상태": "신규주문", "오픈마켓주문번호": "C2"},
                {"판매처": "쿠팡", "쇼핑몰별칭": "브랜드위시", "주문상태": "배송준비중", "오픈마켓주문번호": "C3"},
                {"판매처": "쿠팡", "쇼핑몰별칭": "브랜드다임", "주문상태": "결제완료", "오픈마켓주문번호": "C4"},
            ],
            "lotteon": [
                {"판매처": "롯데온", "쇼핑몰별칭": "르무통", "주문상태": "결제완료", "오픈마켓주문번호": "L1"},
            ],
        }
        monkeypatch.setattr(ac._oe, "combined_order_rows",
                            lambda mks, **kw: rows.get(mks[0], []))

    def test_dryrun_counts_only_enabled_and_paid(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch)
        ac.set_account(session, "coupang", "브랜드위시", True)   # 브랜드다임·롯데온은 OFF
        res = ac.run(session, live=False)
        assert res["live"] is False
        # 브랜드위시의 결제완료+신규 2건만 (배송준비중 제외, 다른 계정 제외)
        assert res["total"] == 2
        leaf = res["by"][0]
        assert leaf["result"] == "dryrun" and leaf["count"] == 2

    def test_live_requested_but_gate_off_stays_dryrun(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch)
        monkeypatch.setattr(ac, "live_confirm_enabled", lambda: False)   # 게이트 OFF
        ac.set_all(session, True)
        res = ac.run(session, live=True)
        assert res["live"] is False                       # 강등됨
        assert all(b["result"] == "dryrun" for b in res["by"])
        # 실전환이 아니므로 이력(last_run)이 남지 않아야
        from lemouton.sourcing.models_v2 import AutoConfirmSetting
        assert all(r.last_run_at is None for r in session.query(AutoConfirmSetting).all())

    def _live_on(self, monkeypatch):
        monkeypatch.setattr(ac, "live_confirm_enabled", lambda: True)
        monkeypatch.setattr(ac, "_client_for", lambda m, a: object())   # 더미 클라(None 아님)

    def test_live_coupang_sent_and_records_history(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch); self._live_on(monkeypatch)
        calls = {}
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets",
                            lambda market, targets, client: calls.__setitem__(market, len(targets)))
        monkeypatch.setattr(ac, "_readback_moved", lambda market, targets, client: len(targets))
        ac.set_account(session, "coupang", "브랜드위시", True)
        res = ac.run(session, live=True)
        assert res["live"] is True
        leaf = res["by"][0]
        assert leaf["result"] == "sent" and leaf["count"] == 2   # C1 결제완료 + C2 신규주문
        assert calls["coupang"] == 2
        from lemouton.sourcing.models_v2 import AutoConfirmSetting
        row = session.get(AutoConfirmSetting, {"market": "coupang", "account_alias": "브랜드위시"})
        assert row.last_run_at is not None and row.last_run_count == 2

    def test_live_readback_zero_is_failed_no_false_success(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch); self._live_on(monkeypatch)
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets", lambda *a, **k: None)
        monkeypatch.setattr(ac, "_readback_moved", lambda *a, **k: 0)    # 안 움직임(스펙 틀림 시)
        ac.set_account(session, "coupang", "브랜드위시", True)
        res = ac.run(session, live=True)
        assert res["by"][0]["result"] == "failed" and res["total"] == 0
        from lemouton.sourcing.models_v2 import AutoConfirmSetting
        row = session.get(AutoConfirmSetting, {"market": "coupang", "account_alias": "브랜드위시"})
        assert row.last_run_at is None    # 거짓 성공 이력 안 남김

    def test_live_eleven11_now_supported(self, session, accounts, monkeypatch):
        # 11번가 발주처리(reqpackaging) 배선됨 — 더는 unsupported 아님.
        rows = {"eleven11": [{"판매처": "11번가", "쇼핑몰별칭": "대표 계정", "주문상태": "결제완료",
                              "오픈마켓주문번호": "E1",
                              "_send_ids": {"ord_no": "E1", "ord_prd_seq": "1", "dlv_no": "D9"}}]}
        monkeypatch.setattr(ac._oe, "combined_order_rows", lambda mks, **kw: rows.get(mks[0], []))
        self._live_on(monkeypatch)
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets", lambda *a, **k: None)
        monkeypatch.setattr(ac, "_readback_moved", lambda *a, **k: 1)
        ac.set_account(session, "eleven11", "대표 계정", True)
        res = ac.run(session, live=True)
        assert res["by"][0]["result"] == "sent" and res["total"] == 1

    def test_limit_caps_attempted(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch); self._live_on(monkeypatch)
        seen = {}
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets",
                            lambda market, targets, client: seen.__setitem__(market, len(targets)))
        monkeypatch.setattr(ac, "_readback_moved", lambda market, targets, client: len(targets))
        ac.set_account(session, "coupang", "브랜드위시", True)
        res = ac.run(session, live=True, limit=1)
        assert seen["coupang"] == 1 and res["by"][0]["attempted"] == 1

    def test_order_nos_targets_only_approved(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch); self._live_on(monkeypatch)
        seen = {}
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets",
                            lambda market, targets, client:
                            seen.__setitem__(market, [t["오픈마켓주문번호"] for t in targets]))
        monkeypatch.setattr(ac, "_readback_moved", lambda market, targets, client: len(targets))
        ac.set_account(session, "coupang", "브랜드위시", True)
        # 브랜드위시 결제완료는 C1·C2 지만, 승인은 C2 만
        res = ac.run(session, live=True, order_nos=["C2"])
        assert seen["coupang"] == ["C2"]          # C1 은 안 넘김
        assert res["by"][0]["count"] == 1

    def test_smartstore_verified_by_confirm_set_not_status(self, session, accounts, monkeypatch):
        # 스스는 발주확인해도 상태(결제완료)가 안 바뀐다 → 되읽기 대신 confirm 확정집합으로 검증.
        rows = {"smartstore": [{"판매처": "스마트스토어", "쇼핑몰별칭": "대표 계정",
                                "주문상태": "결제완료", "오픈마켓주문번호": "S1"}]}
        monkeypatch.setattr(ac._oe, "combined_order_rows", lambda mks, **kw: rows.get(mks[0], []))
        self._live_on(monkeypatch)
        # confirm_targets 가 확정집합 반환 / 되읽기는 0 을 주도록(안 쓰여야 함)
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets",
                            lambda market, targets, client: {"S1"})
        monkeypatch.setattr(ac, "_readback_moved", lambda *a, **k: 0)
        ac.set_account(session, "smartstore", "대표 계정", True)
        res = ac.run(session, live=True)
        assert res["by"][0]["result"] == "sent" and res["by"][0]["count"] == 1

    def test_run_records_history_log(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch); self._live_on(monkeypatch)
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets", lambda *a, **k: None)
        monkeypatch.setattr(ac, "_readback_moved", lambda market, targets, client: len(targets))
        ac.set_account(session, "coupang", "브랜드위시", True)
        ac.run(session, live=True, source="auto")
        logs = ac.recent_logs(session)
        assert logs and logs[0]["market"] == "coupang" and logs[0]["source"] == "auto"
        assert logs[0]["count"] == 2 and logs[0]["result"] == "sent"

    def test_no_enabled_returns_note(self, session, accounts, monkeypatch):
        self._stub_orders(monkeypatch)
        res = ac.run(session, live=False)
        assert res["total"] == 0 and "note" in res


class TestAutoConfigAndTick:
    def test_config_defaults_and_set(self, session):
        cfg = ac.get_config(session)
        assert cfg.enabled is False and cfg.interval_minutes == 5
        ac.set_config(session, enabled=True, interval_minutes=7)
        cfg2 = ac.get_config(session)
        assert cfg2.enabled is True and cfg2.interval_minutes == 7

    def test_interval_clamped(self, session):
        ac.set_config(session, interval_minutes=9999)
        assert ac.get_config(session).interval_minutes == 180
        ac.set_config(session, interval_minutes=0)
        assert ac.get_config(session).interval_minutes == 180  # 0 무시 → 이전값 유지

    def test_tick_noop_when_auto_off(self, session, accounts):
        assert ac.tick(session)["ran"] is False

    def test_tick_runs_when_on_and_interval_elapsed(self, session, accounts, monkeypatch):
        # 자동 ON, 대상 계정 켬, 주문 스텁 + confirm 성공
        rows = {"coupang": [{"판매처": "쿠팡", "쇼핑몰별칭": "브랜드위시",
                             "주문상태": "결제완료", "오픈마켓주문번호": "C1"}]}
        monkeypatch.setattr(ac._oe, "combined_order_rows", lambda mks, **kw: rows.get(mks[0], []))
        monkeypatch.setattr(ac, "_client_for", lambda m, a: object())
        monkeypatch.setattr("lemouton.orders.confirm_api.confirm_targets", lambda *a, **k: None)
        monkeypatch.setattr(ac, "_readback_moved", lambda *a, **k: 1)
        ac.set_account(session, "coupang", "브랜드위시", True)
        ac.set_config(session, enabled=True, interval_minutes=5)
        r1 = ac.tick(session)
        assert r1["ran"] is True and r1["total"] == 1
        # 방금 돌았으니 간격 전 재틱은 no-op(멀티워커 중복 방지)
        assert ac.tick(session)["ran"] is False


# ── 옥션·G마켓(ESM) 주문확인 배선 (2026-07-21) ──────────────────────────────

class _EsmCheckClient:
    def __init__(self, fail_nos=()):
        self.calls, self.fail_nos = [], set(str(x) for x in fail_nos)

    def post(self, path, body, **kw):
        self.calls.append(path)
        no = path.rsplit("/", 1)[-1]
        if no in self.fail_nos:
            return {"ResultCode": 2000, "Message": "이미 처리된 주문"}
        return {"ResultCode": 0}


def test_esm_주문확인은_건별로_부르고_성공집합을_돌려준다():
    from lemouton.orders import confirm_api as capi
    cli = _EsmCheckClient()
    got = capi.confirm_targets("auction",
                               [{"오픈마켓주문번호": "111"}, {"오픈마켓주문번호": "222"}], cli)
    assert got == {"111", "222"}
    assert cli.calls == ["/shipping/v1/Order/OrderCheck/111",
                         "/shipping/v1/Order/OrderCheck/222"]


def test_esm_일부실패는_성공분을_살린다():
    """전체 예외로 뭉개면 성공한 전환까지 실패로 보인다 — 건별 집계."""
    from lemouton.orders import confirm_api as capi
    got = capi.confirm_targets("gmarket",
                               [{"오픈마켓주문번호": "111"}, {"오픈마켓주문번호": "222"}],
                               _EsmCheckClient(fail_nos=["222"]))
    assert got == {"111"}


def test_esm_전건실패는_사유와_함께_예외():
    from lemouton.orders import confirm_api as capi
    import pytest as _pt
    with _pt.raises(RuntimeError, match="이미 처리된 주문"):
        capi.confirm_targets("auction", [{"오픈마켓주문번호": "222"}],
                             _EsmCheckClient(fail_nos=["222"]))

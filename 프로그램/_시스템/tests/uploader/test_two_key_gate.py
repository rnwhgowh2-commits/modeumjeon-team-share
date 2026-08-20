# -*- coding: utf-8 -*-
"""[TEST] 가격·재고 실전송 = 두 겹 잠금.

서버 열쇠(MOUM_LIVE_UPLOAD env) + 화면 열쇠(autosend_mode='real')가
**둘 다** 켜져야 실제로 나간다. 하나라도 꺼지면 드라이런.
금전 사고 위험이 큰 무인 자동전송이라, 한 겹은 항상 서버(재배포)에 둔다.
"""
import lemouton.uploader.runtime as rt


class _FakeSession:
    pass


def _patch_ui(monkeypatch, mode):
    monkeypatch.setattr("lemouton.pricing.settings.get_automation",
                        lambda s: {"autosend_mode": mode})


class TestTwoKeyGate:
    def test_both_off_is_dryrun(self, monkeypatch):
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        _patch_ui(monkeypatch, "preview")
        assert rt.real_upload_armed(_FakeSession()) is False

    def test_server_on_ui_preview_is_dryrun(self, monkeypatch):
        """서버만 열려 있고 화면이 미리보기면 안 나간다(화면 열쇠 필요)."""
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")
        _patch_ui(monkeypatch, "preview")
        assert rt.real_upload_armed(_FakeSession()) is False

    def test_ui_real_server_locked_is_dryrun(self, monkeypatch):
        """화면만 실제전송이고 서버가 잠겨 있으면 안 나간다(서버 열쇠 필요)."""
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        _patch_ui(monkeypatch, "real")
        assert rt.real_upload_armed(_FakeSession()) is False

    def test_both_on_is_armed(self, monkeypatch):
        """둘 다 켜져야만 실제 전송."""
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")
        _patch_ui(monkeypatch, "real")
        assert rt.real_upload_armed(_FakeSession()) is True

    def test_settings_read_failure_is_safe_dryrun(self, monkeypatch):
        """설정을 못 읽으면 안전하게 미전송(터지지 않음)."""
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")
        def boom(s): raise RuntimeError("db down")
        monkeypatch.setattr("lemouton.pricing.settings.get_automation", boom)
        assert rt.real_upload_armed(_FakeSession()) is False

import pytest


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_success_maps_fields(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResponse(200, {
            "market_type": "coupang",
            "account_label": "본계정",
            "fields": {"accessKey": "AK", "secretKey": "SK", "vendorId": "V1"},
        })

    monkeypatch.setattr(mod.requests, "get", fake_get)

    result = mod.get_market_account("coupang")

    assert result.market_type == "coupang"
    assert result.account_label == "본계정"
    assert result.fields == {"accessKey": "AK", "secretKey": "SK", "vendorId": "V1"}
    assert captured["url"] == "https://samba-wave.example.com/api/v1/internal/accounts/credentials"
    assert captured["params"] == {"market_type": "coupang"}
    assert captured["headers"] == {"X-Internal-Token": "tok123"}


def test_missing_url_raises(monkeypatch):
    monkeypatch.delenv("SAMBA_WAVE_URL", raising=False)
    monkeypatch.delenv("SAMBA_WAVE_INTERNAL_TOKEN", raising=False)
    from shared.market_accounts.client import get_market_account, MarketAccountUnavailable

    with pytest.raises(MarketAccountUnavailable, match="SAMBA_WAVE_URL"):
        get_market_account("coupang")


def test_missing_token_raises(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.delenv("SAMBA_WAVE_INTERNAL_TOKEN", raising=False)
    from shared.market_accounts.client import get_market_account, MarketAccountUnavailable

    with pytest.raises(MarketAccountUnavailable, match="SAMBA_WAVE_INTERNAL_TOKEN"):
        get_market_account("coupang")

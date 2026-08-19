import pytest


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

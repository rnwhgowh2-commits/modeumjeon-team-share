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


def test_404_raises_unavailable(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    monkeypatch.setattr(
        mod.requests, "get",
        lambda *a, **kw: _FakeResponse(404, {"detail": "계정을 찾을 수 없습니다"}),
    )

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="찾을 수 없습니다"):
        mod.get_market_account("coupang")


def test_5xx_raises_unavailable(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    monkeypatch.setattr(
        mod.requests, "get",
        lambda *a, **kw: _FakeResponse(500, {}),
    )

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="500"):
        mod.get_market_account("coupang")


def test_connection_error_raises_unavailable(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    def raise_conn_error(*a, **kw):
        raise mod.requests.exceptions.ConnectionError("연결 거부")

    monkeypatch.setattr(mod.requests, "get", raise_conn_error)

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="연결 실패") as exc_info:
        mod.get_market_account("coupang")
    # 설계서 "원 예외 원인 보존" 요구사항 — match="연결 실패" 만으론 {e} 를
    # f-string 에서 빼먹거나 from e 를 지워도 통과한다(뮤테이션으로 확인됨).
    assert "연결 거부" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, mod.requests.exceptions.ConnectionError)


def test_timeout_raises_unavailable(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    def raise_timeout(*a, **kw):
        raise mod.requests.exceptions.Timeout("10s 초과")

    monkeypatch.setattr(mod.requests, "get", raise_timeout)

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="연결 실패") as exc_info:
        mod.get_market_account("coupang")
    assert "10s 초과" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, mod.requests.exceptions.Timeout)


def test_whitespace_only_url_raises_missing_config(monkeypatch):
    """공백뿐 SAMBA_WAVE_URL 은 "설정 없음"으로 취급 — 잘못된 요청을 실제로 보내
    "연결 실패"라는 헷갈리는 메시지로 둔갑시키지 않는다(app.py 와 동일 원칙)."""
    monkeypatch.setenv("SAMBA_WAVE_URL", "   ")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    def fail_if_called(*a, **kw):
        raise AssertionError("공백뿐 URL 로 실제 요청이 나가면 안 됨")

    monkeypatch.setattr(mod.requests, "get", fail_if_called)

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="SAMBA_WAVE_URL"):
        mod.get_market_account("coupang")


def test_account_label_passed_as_param(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _FakeResponse(200, {
            "market_type": "coupang", "account_label": "부계정",
            "fields": {},
        })

    monkeypatch.setattr(mod.requests, "get", fake_get)

    mod.get_market_account("coupang", account_label="부계정")
    assert captured["params"] == {"market_type": "coupang", "account_label": "부계정"}

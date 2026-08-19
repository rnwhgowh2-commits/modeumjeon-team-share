# samba-wave 판매처 계정 브리지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `shared/market_accounts/client.py`가 samba-wave의 내부 계정 API를 실제로 호출하도록 구현하고, 대량등록 모드 링크를 설정값이 있을 때만 samba-wave URL로 전환한다.

**Architecture:** `get_market_account()`는 `requests`로 `GET {SAMBA_WAVE_URL}/api/v1/internal/accounts/credentials`를 호출해 `MarketAccountCredential`을 돌려주거나 `MarketAccountUnavailable`을 던진다. 설정 누락·404·네트워크 실패 모두 폴백 없이 예외로 통일한다. `_modeswitch.html`의 대량등록 링크는 `app.py`의 기존 전역 context processor에 `samba_wave_url`(환경변수, 없으면 None) 키를 추가해 제어한다.

**Tech Stack:** Python 3, Flask, `requests`, `pytest`, `monkeypatch`

작업 위치: `C:/dev/_wt_sambawave` (모든 경로는 `프로그램/_시스템/`가 루트)

설계서: `docs/superpowers/specs/2026-08-19-samba-wave-account-bridge-design.md`

---

### Task 1: 환경변수 미설정 시 예외

**Files:**
- Modify: `shared/market_accounts/client.py`
- Test: `tests/market_accounts/test_client.py` (신규)

- [ ] **Step 1: 테스트 디렉터리 생성**

```bash
mkdir -p tests/market_accounts && touch tests/market_accounts/__init__.py
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/market_accounts/test_client.py`:
```python
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
```

- [ ] **Step 3: 실패 확인**

Run: `pytest tests/market_accounts/test_client.py -v`
Expected: FAIL — `NotImplementedError` (현재 스텁이 바로 이걸 던짐)

- [ ] **Step 4: 최소 구현**

`shared/market_accounts/client.py`의 `get_market_account` 함수 전체를 아래로 교체(위쪽 dataclass·예외 클래스는 그대로 유지):

```python
def get_market_account(
    market_type: str,
    *,
    account_label: Optional[str] = None,
) -> MarketAccountCredential:
    """market_type 에 해당하는 활성 판매처 계정 1개를 가져온다.

    account_label 없으면 is_default=true 계정. 여러 계정 중 어느 것도 default 가
    아니면 MarketAccountUnavailable — 자동으로 아무거나 고르지 않는다(추측 금지).

    실패(연결 불가·계정 없음)를 삼키지 않는다 — 호출자가 결정하게 예외를 그대로 던진다.
    폴백 가격/폴백 계정 없음 — [[feedback_no_fallback_price_on_match_fail]] 과 같은 원칙.
    """
    import logging
    import os
    import time

    import requests

    logger = logging.getLogger(__name__)

    base_url = os.environ.get("SAMBA_WAVE_URL", "").rstrip("/")
    if not base_url:
        raise MarketAccountUnavailable(
            "samba-wave 연동 미설정 — SAMBA_WAVE_URL 환경변수가 없습니다"
        )
    token = os.environ.get("SAMBA_WAVE_INTERNAL_TOKEN", "")
    if not token:
        raise MarketAccountUnavailable(
            "samba-wave 연동 미설정 — SAMBA_WAVE_INTERNAL_TOKEN 환경변수가 없습니다"
        )

    params = {"market_type": market_type}
    if account_label:
        params["account_label"] = account_label

    started = time.monotonic()
    try:
        resp = requests.get(
            f"{base_url}/api/v1/internal/accounts/credentials",
            params=params,
            headers={"X-Internal-Token": token},
            timeout=10,
        )
    except requests.RequestException as e:
        logger.warning(
            "[market_accounts] %s 조회 실패(연결) %.2fs: %s",
            market_type, time.monotonic() - started, e,
        )
        raise MarketAccountUnavailable(
            f"samba-wave 연결 실패 (market_type={market_type}): {e}"
        ) from e

    elapsed = time.monotonic() - started

    if resp.status_code == 404:
        logger.info(
            "[market_accounts] %s 계정 없음 %.2fs (account_label=%s)",
            market_type, elapsed, account_label,
        )
        raise MarketAccountUnavailable(
            f"'{market_type}' 활성 판매처 계정을 찾을 수 없습니다"
            + (f" (account_label={account_label})" if account_label else " (기본 계정 없음)")
        )

    if resp.status_code != 200:
        logger.warning(
            "[market_accounts] %s 조회 실패(status=%s) %.2fs",
            market_type, resp.status_code, elapsed,
        )
        raise MarketAccountUnavailable(
            f"samba-wave 응답 오류 (market_type={market_type}, status={resp.status_code})"
        )

    data = resp.json()
    logger.info("[market_accounts] %s 조회 성공 %.2fs", market_type, elapsed)
    return MarketAccountCredential(
        market_type=data["market_type"],
        account_label=data["account_label"],
        fields=data["fields"],
    )
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/market_accounts/test_client.py -v`
Expected: `test_missing_url_raises` PASS, `test_missing_token_raises` PASS

- [ ] **Step 6: Commit**

```bash
git add shared/market_accounts/client.py tests/market_accounts/
git commit -m "feat(계정브리지): 환경변수 미설정 시 명시적 예외"
```

---

### Task 2: 정상 조회 — 200 응답 매핑

**Files:**
- Test: `tests/market_accounts/test_client.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/market_accounts/test_client.py`에 추가:
```python
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
```

주의: `monkeypatch.setattr(mod.requests, "get", fake_get)`가 동작하려면 `client.py`
안에서 `import requests`가 함수 최상단이 아니라 **모듈 최상단**에 있어야 한다
(함수 내부 import면 매번 새로 바인딩되어 monkeypatch 가 안 먹는다).

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/market_accounts/test_client.py::test_success_maps_fields -v`
Expected: FAIL — `AttributeError: module 'shared.market_accounts.client' has no attribute 'requests'` (아직 모듈 최상단 import 아님)

- [ ] **Step 3: import 위치 수정**

`shared/market_accounts/client.py` 최상단 (`from __future__ import annotations` 바로 아래)에 추가:
```python
import logging
import os
import time

import requests
```
그리고 `get_market_account` 함수 안의 `import logging`/`import os`/`import time`/`import requests` 4줄과 `logger = logging.getLogger(__name__)` 줄은 함수 밖(모듈 최상단, import들 바로 아래)으로 옮긴다:
```python
logger = logging.getLogger(__name__)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/market_accounts/test_client.py -v`
Expected: 지금까지 만든 3개 테스트 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add shared/market_accounts/client.py tests/market_accounts/test_client.py
git commit -m "feat(계정브리지): 정상 조회 200 응답 필드 매핑 + 테스트 가능한 import 위치"
```

---

### Task 3: 404 및 그 외 오류 상태코드

**Files:**
- Test: `tests/market_accounts/test_client.py`

- [ ] **Step 1: 실패하는 테스트 작성**

추가:
```python
def test_404_raises_unavailable(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    monkeypatch.setattr(
        mod.requests, "get",
        lambda *a, **kw: _FakeResponse(404, {"detail": "계정을 찾을 수 없습니다"}),
    )

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="coupang"):
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
```

- [ ] **Step 2: 확인**

Run: `pytest tests/market_accounts/test_client.py -v`
Expected: 이미 Task 1 구현에 404/비-200 처리가 들어있으므로 **이번엔 바로 PASS** — RED 없이 GREEN이면 그대로 다음 단계(이미 만족하는 요구사항을 테스트로 고정하는 것도 유효한 스텝).

- [ ] **Step 3: Commit**

```bash
git add tests/market_accounts/test_client.py
git commit -m "test(계정브리지): 404·5xx 응답 회귀 고정"
```

---

### Task 4: 네트워크 실패 (연결 불가·타임아웃)

**Files:**
- Test: `tests/market_accounts/test_client.py`

- [ ] **Step 1: 실패하는 테스트 작성**

추가:
```python
def test_connection_error_raises_unavailable(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    def raise_conn_error(*a, **kw):
        raise mod.requests.exceptions.ConnectionError("연결 거부")

    monkeypatch.setattr(mod.requests, "get", raise_conn_error)

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="연결 실패"):
        mod.get_market_account("coupang")


def test_timeout_raises_unavailable(monkeypatch):
    monkeypatch.setenv("SAMBA_WAVE_URL", "https://samba-wave.example.com")
    monkeypatch.setenv("SAMBA_WAVE_INTERNAL_TOKEN", "tok123")

    import shared.market_accounts.client as mod

    def raise_timeout(*a, **kw):
        raise mod.requests.exceptions.Timeout("10s 초과")

    monkeypatch.setattr(mod.requests, "get", raise_timeout)

    from shared.market_accounts.client import MarketAccountUnavailable
    with pytest.raises(MarketAccountUnavailable, match="연결 실패"):
        mod.get_market_account("coupang")
```

- [ ] **Step 2: 확인**

Run: `pytest tests/market_accounts/test_client.py -v`
Expected: `requests.exceptions.ConnectionError`/`Timeout` 모두 `requests.RequestException`의
서브클래스라 Task 1 구현의 `except requests.RequestException` 이 이미 잡는다 — PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/market_accounts/test_client.py
git commit -m "test(계정브리지): 연결실패·타임아웃 회귀 고정"
```

---

### Task 5: account_label 쿼리파라미터 반영

**Files:**
- Test: `tests/market_accounts/test_client.py`

- [ ] **Step 1: 실패하는 테스트 작성**

추가:
```python
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
```

- [ ] **Step 2: 확인**

Run: `pytest tests/market_accounts/test_client.py -v`
Expected: Task 1 구현이 이미 `account_label` 있으면 params 에 넣으므로 PASS.

- [ ] **Step 3: 전체 회귀 실행**

Run: `pytest tests/market_accounts/ -v`
Expected: 8개 테스트 전부 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/market_accounts/test_client.py
git commit -m "test(계정브리지): account_label 쿼리파라미터 회귀 고정"
```

---

### Task 6: 대량등록 링크 — 설정값 게이팅

**Files:**
- Modify: `app.py:368-374` (기존 `_inject_brand_color_overrides` 바로 아래에 추가)
- Modify: `webapp/templates/partials/_modeswitch.html:11`
- Test: `tests/test_samba_wave_modeswitch.py` (신규)

**주의(계획 자체 점검에서 발견)**: `app.py`의 `create_app()`은 실제 DB(Supabase) 연결을
요구한다(`tests/uploader/test_preview_parity.py` 참조 — `OperationalError` 시 skip 처리).
이 테스트는 템플릿 렌더링만 확인하면 되므로 `create_app()`을 부르지 않고, 순수
Jinja2 `Environment`로 템플릿 파일 하나만 렌더링해 DB 의존을 없앤다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_samba_wave_modeswitch.py`:
```python
import pathlib

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = (
    pathlib.Path(__file__).parent.parent / "webapp" / "templates"
)

_ICONS = {
    "bundles": {"emoji": "📦", "color": None},
    "inventory": {"emoji": "🏬", "color": None},
    "bulk": {"emoji": "🚀", "color": None},
}


def _render(samba_wave_url):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("partials/_modeswitch.html")
    return template.render(
        active_app="bulk",
        sidebar_mode_icons=_ICONS,
        samba_wave_url=samba_wave_url,
    )


def test_modeswitch_link_defaults_to_bulk():
    html = _render(samba_wave_url=None)
    assert 'href="/bulk/"' in html


def test_modeswitch_link_uses_samba_wave_url_when_set():
    html = _render(samba_wave_url="https://samba-wave.example.com")
    assert 'href="https://samba-wave.example.com"' in html
    assert 'href="/bulk/"' not in html
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_samba_wave_modeswitch.py -v`
Expected: FAIL — 템플릿에 `samba_wave_url` 을 참조하는 부분이 아직 없어(현재는 `href="/bulk/"`
고정) 두 번째 테스트만 실패. 첫 번째 테스트는 이미 통과할 수 있음(현재 동작이 곧 원하는
기본값이므로) — 그래도 정상, 두 번째 테스트의 FAIL 로 이 스텝의 목적(RED 확인)은 달성됨.

- [ ] **Step 3: context processor 추가**

`app.py`의 `_inject_brand_color_overrides` (약 368행) 바로 아래에 추가:
```python
    # 대량등록 모드 → samba-wave 로 전환하는 스위치. 값 없으면(기본) 기존 /bulk/ 그대로 —
    # samba-wave 실배포 전까지 라이브 동작 무변화.
    @app.context_processor
    def _inject_samba_wave_url():
        return {'samba_wave_url': os.environ.get('SAMBA_WAVE_URL') or None}
```

- [ ] **Step 4: 템플릿 수정**

`webapp/templates/partials/_modeswitch.html` 11행:
```html
  <a href="/bulk/" class="sb-mode {% if active_app == 'bulk' %}on{% endif %}">
```
→
```html
  <a href="{{ samba_wave_url or '/bulk/' }}" class="sb-mode {% if active_app == 'bulk' %}on{% endif %}">
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_samba_wave_modeswitch.py -v`
Expected: 둘 다 PASS

- [ ] **Step 6: 전체 회귀 확인**

Run: `pytest tests/ -v -x --timeout=120` (전체 스위트 — `app.py` 변경이 다른 라우트
초기화를 깨지 않았는지 확인. DB 미연결로 skip 되는 테스트는 정상, 새로운 FAIL 이
없는지만 본다)

- [ ] **Step 7: Commit**

```bash
git add app.py webapp/templates/partials/_modeswitch.html tests/test_samba_wave_modeswitch.py
git commit -m "feat(대량등록): 설정값 있을 때만 samba-wave 링크로 전환 (기본 동작 무변화)"
```

---

### Task 7: 브라우저 실시연 (ai-workflow STEP 7b 의무)

**Files:** 없음 — 검증만

- [ ] **Step 1: 로컬 서버 기동**

Run: `python app.py` (또는 프로젝트 기존 실행 스크립트)

- [ ] **Step 2: 설정 없는 기본 상태 확인**

브라우저로 `/` 접속 → 대량등록 아이콘 hover/클릭 → `/bulk/`로 이동하는지 (기존과 동일) 확인.

- [ ] **Step 3: 설정값 넣고 재기동**

`SAMBA_WAVE_URL=https://example.com python app.py` 로 재기동 → `/` 접속 → 대량등록
링크가 `https://example.com`을 가리키는지 (페이지 소스 또는 hover 상태표시줄로) 확인.

- [ ] **Step 4: 원복**

환경변수 없이 재기동해 원래 상태로 되돌려놓기.

---

## Self-Review 결과 (계획 작성자가 직접 확인)

- **스펙 커버리지**: 설계서의 "포함" 3항목(client.py 실구현/테스트, modeswitch 게이팅) 모두 Task 1~7에 매핑됨. "제외" 항목(5플랫폼 연결, 실배포값)은 의도적으로 태스크 없음.
- **플레이스홀더 스캔**: 없음 — 모든 스텝에 실제 코드/명령 포함.
- **타입 일관성**: `MarketAccountCredential(market_type, account_label, fields)` 필드명이 Task 1 구현·Task 2~5 테스트에서 동일하게 사용됨. `MarketAccountUnavailable`도 전 태스크 동일.
- **실제로 잡아서 고친 것 2건** (초안 그대로 뒀으면 Task 6 착수 시 막혔을 것):
  1. Task 6 원래 초안은 `app.py`의 `create_app()`을 테스트에서 직접 호출했는데,
     `tests/uploader/test_preview_parity.py`를 보니 `create_app()`은 실제 Supabase 연결을
     요구한다(`OperationalError` 시 skip). 템플릿 렌더링만 확인하면 되는 테스트가 DB에
     묶이는 건 과함 → 순수 Jinja2 `Environment`로 템플릿만 떼어 렌더링하도록 교체.
  2. Task 6 원래 초안이 회귀 확인 명령으로 `pytest tests/design/`을 지목했는데, 이
     워크트리(main 기준)엔 `tests/design/` 자체가 없음(그 파일은 아직 안 머지된
     `feature/design-unify` 브랜치에만 있음) → 전체 스위트(`pytest tests/`)로 교체.

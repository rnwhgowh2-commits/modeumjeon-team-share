# SSF샵 로그인 셋업

## 🎯 로그인 필요한가?

**기본은 비로그인** — sale_price·옵션·재고는 비로그인 페이지에서도 정상 추출.

다만 **기프트포인트** / **포인트 적립** 같은 멤버십 한정 항목은 로그인 시에만 노출되는 경우 있음 (확인 필요). 운영 시 검토 후 셋업 가능.

## 📦 인증 메커니즘

| 방식 | 위치 | 용도 |
|---|---|---|
| **비로그인 (default)** | — | sale_price, 옵션, 재고 |
| **profile_dir** (선택) | `_시스템/data/profiles/ssf_{계정}/` | 멤버십 한정 혜택 노출 시 |

## 👤 현재 등록된 SSF 계정

`_시스템/data/profiles/` 안:
- `ssf_dudqls123` — Playwright 영구 프로필
- `ssf_wjsdlrqo00_naver_com` — Playwright 영구 프로필

`_시스템/data/auth/` storage_state JSON: (현재 없음 — Playwright 프로필 위주)

## 🛡️ Anti-bot (curl_cffi)

```python
from curl_cffi import requests as cffi_requests

cffi_requests.get(
    url,
    impersonate="chrome120",        # Cloudflare 통과
    timeout=30,
)
```

→ 일반 `requests` 시 Cloudflare 차단 가능. `curl_cffi` 가 표준.

## ⚠️ 주의

- ❌ Playwright 프로필 git commit 금지 (`.gitignore` 의 `data/profiles/` 포함됨)
- ⚠️ 멤버십 한정 혜택은 일반 비로그인 페이지에 노출되지 않을 수 있음 — 정확한 가격 산정 시 로그인 모드 검토

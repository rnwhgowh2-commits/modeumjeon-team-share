# 스스 르무통 로그인 셋업

## 🎯 로그인 필요한가?

**아니오 — 비로그인 크롤이 기본.** 네이버 브랜드스토어는 회원가 영역이 없으므로 비로그인 GET 만으로 모든 가격·옵션·재고 데이터 추출 가능.

다만 호스트 선택이 중요:
- ❌ `smartstore.naver.com/{seller}/products/{id}` 비로그인 GET → `nidlogin.login` 강제 리디렉트
- ✅ `brand.naver.com/{seller}/products/{id}` 비로그인 GET → 200 OK + inline JSON

→ `_normalize_url()` 가 자동으로 smartstore → brand 호스트 swap.

## 📦 인증 메커니즘

| 방식 | 위치 | 용도 |
|---|---|---|
| **비로그인 (default)** | — | 모든 운영 크롤 |
| ~~로그인~~ | — | 미지원 (SKU 단위 재고에는 인증 commerce API 가 필요하지만 WAF 차단으로 비실용) |

## 🛡️ Anti-bot (curl_cffi)

```python
from curl_cffi import requests as cffi_requests

cffi_requests.get(
    url,
    impersonate="chrome120",        # TLS fingerprint = Chrome 120
    timeout=30,
    allow_redirects=True,
)
```

- 일반 `requests` 사용 시 → 429 / WAF 페이지 / 비로그인 페이지 반환
- `curl_cffi` + `chrome120` impersonate → 200 OK + 정상 HTML

## ⚠️ 주의

- 네이버 측 rate limit 추정 — 짧은 시간 다수 호출 시 429 가능. 운영 시 적당한 간격 유지
- inline state JSON 구조 변경 시 (Next.js 업데이트) 즉시 크롤 실패 → `_extract_preloaded_state` 가 None 반환 → 빈 결과 (호출자가 fail-fast)
- SKU 단위 재고 정확도 한계 (모든 옵션 stock=1 매핑) — 필요 시 별도 task 로 Playwright 옵션 클릭 자동화

# samba-wave 판매처 계정 브리지 — 설계

2026-08-19 · branch `feature/samba-wave-integration`

## 배경

대량등록 탭을 samba-wave(완전 독립 시스템)로 대체하기로 했다. 유일한 공유 지점은
판매처 계정(쿠팡·11번가 등 로그인/API 자격증명) — samba-wave 의 스키마가 표준이고
모음전이 따라간다. 상세 배경은 [`docs/CONTEXT.md`](../../../../../docs/CONTEXT.md),
[`docs/ARCHITECTURE_FIRST_DRAFT.md`](../../../../../docs/ARCHITECTURE_FIRST_DRAFT.md),
[`docs/interfaces.md`](../../../../../docs/interfaces.md) 참조 (메인 저장소 docs/).

## 이번 사이클 범위

samba-wave 가 아직 배포 전(실제 URL 없음)이라, **라이브 동작을 바꾸지 않으면서** 배포되는
순간 바로 켜지는 형태로 좁혔다.

**포함:**
1. `shared/market_accounts/client.py` — `get_market_account()` 실제 구현
2. 유닛 테스트 (HTTP 호출 mock)
3. `_modeswitch.html` 대량등록 링크 — 설정값 있을 때만 samba-wave URL로 (없으면 기존 `/bulk/` 그대로)

**제외 (다음 사이클):**
- 5개 플랫폼 클라이언트(coupang·eleven11·esm·lotteon·smartstore)가 실제로 이 브리지를
  쓰도록 바꾸는 것 — samba-wave 실배포·엔드포인트 생존 확인 후. 지금 바꾸면 실제 마켓 API
  호출이 존재하지 않는 주소로 나갈 위험(매출 직결이라 보류)
- `SAMBA_WAVE_URL`·`SAMBA_WAVE_INTERNAL_TOKEN` 실제 값 채우기 — 배포 후 운영자가 직접

## 컴포넌트

### `shared/market_accounts/client.py`

```
get_market_account(market_type, *, account_label=None)
  1. SAMBA_WAVE_URL, SAMBA_WAVE_INTERNAL_TOKEN 환경변수 읽기
     → 둘 중 하나라도 없으면 즉시 MarketAccountUnavailable
       ("samba-wave 연동 미설정 — SAMBA_WAVE_URL/SAMBA_WAVE_INTERNAL_TOKEN 필요")
  2. requests.get(f"{base}/api/v1/internal/accounts/credentials",
                   params={market_type, account_label(선택)},
                   headers={"X-Internal-Token": token}, timeout=10)
  3. 200 → MarketAccountCredential(...) 반환
     404 → MarketAccountUnavailable(계정 없음, 서버 메시지 그대로 포함)
     그 외(타임아웃·5xx·연결실패) → MarketAccountUnavailable(원인 포함) — 폴백 없이 그대로 예외
  4. 성공/실패 모두 logger 로 남김 (market_type, 소요시간, 결과)
```

기존 `shared/platforms/smartstore/token_store.py` 의 파일락 방식은 여기선 안 씀 —
이 함수는 매 호출 원격 조회고, 로컬 캐시는 다음 사이클(플랫폼 클라이언트 연결 시)에
필요하면 그때 추가. 지금은 "제대로 조회하고 실패는 숨기지 않는다"만 확실히 한다.

### `_modeswitch.html`

```html
<a href="{{ samba_wave_url or '/bulk/' }}" ...>
```
`_modeswitch.html`은 3개 사이드바가 공유하는 단일 원천이라 `/bulk/*` 전용
`inject_bulk_nav`가 아니라 `app.py`의 기존 전역 `@app.context_processor`(39·368행
부근에 이미 있음 — 그중 적절한 쪽에 키 추가)에서 `os.environ.get("SAMBA_WAVE_URL")`로
`samba_wave_url`을 주입(없으면 None → 기존 동작). 새 컬럼·마이그레이션 없음 — 환경변수 하나.

## 에러 처리

- 계정 없음/연동 미설정/네트워크 실패 → 전부 `MarketAccountUnavailable` 하나로 통일해
  호출자가 한 곳에서 처리. 메시지에 원인 구분은 남기되(로그·예외 메시지), 폴백 계정으로
  조용히 대체하지 않는다 — [[feedback_no_fallback_price_on_match_fail]] 원칙과 동일.
- 현재 호출자가 없으므로(플랫폼 연결은 다음 사이클) 이번엔 "예외가 잘 던져지는지"까지만
  테스트하고, "호출자가 예외를 어떻게 다루는지"는 다음 사이클에서 함께 설계.

## 테스트

- `tests/shared/test_market_accounts_client.py` (신규)
  - 환경변수 미설정 → `MarketAccountUnavailable` (SAMBA_WAVE_URL 없음 메시지)
  - 200 응답 → `MarketAccountCredential` 필드 정확히 매핑
  - 404 → `MarketAccountUnavailable`
  - 타임아웃/연결실패(mock) → `MarketAccountUnavailable`, 원 예외 원인 보존
  - `account_label` 지정 시 쿼리파라미터에 반영되는지

## 안 하는 것 (명시)

- 로컬 캐싱 — 원격 실패 시 재시도/캐시는 플랫폼 클라이언트 연결 시점에 실사용 패턴 보고 설계
- `SAMBA_WAVE_URL` 값 자체를 채우는 것 — 배포 정보라 사람이 함
- 5개 플랫폼 클라이언트 변경 — 위 범위 참조

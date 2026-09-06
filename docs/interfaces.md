# 판매처 계정 브리지 — 인터페이스

STEP 2c 산출물. 시그니처만 확정, 구현은 STEP 7.

## 모음전 쪽 (구현 예정 위치: `shared/market_accounts/client.py`)

```python
@dataclass(frozen=True)
class MarketAccountCredential:
    market_type: str
    account_label: str
    fields: dict[str, Any]   # samba-wave credentials.py 의 *_creds() 출력 그대로

class MarketAccountUnavailable(Exception): ...

def get_market_account(
    market_type: str,
    *, account_label: Optional[str] = None,
) -> MarketAccountCredential:
    """실패를 삼키지 않는다 — 계정 없음/연결 실패는 예외로."""
```

기존 `shared/platforms/__init__.py` 의 `PLATFORM_CONFIG`(환경변수 읽기)를 이 함수 호출로
교체. 5개 플랫폼 클라이언트(`coupang`·`eleven11`·`esm`·`lotteon`·`smartstore`)의
시그니처는 안 바뀐다 — 값을 어디서 받아오는지만 바뀐다.

## samba-wave 쪽 — 구현 완료 (커밋됨, 미푸시)

위치: `C:/dev/samba-wave` (clone, branch `feat/moum-account-credentials-internal-api`),
커밋 `ce93ebde0`. fork(`rnwhgowh2-commits/samba-wave`)로 push 는 아직 안 함 — 승인 후.

기존 `/accounts`, `/accounts/{id}` 등은 **화면 표시용이라 `api_secret`·oauth 토큰이
마스킹**되어 나온다(`mask_model_secrets`). 모음전은 실제로 마켓 API를 호출해야 해서
마스킹 안 된 값이 필요 — 그래서 새 창구를 분리했다.

```
GET {SAMBA_WAVE_URL}/api/v1/internal/accounts/credentials?market_type={market_type}&account_label={선택}
(tenant_id 파라미터 없음 — 자유 입력으로 열어두면 다른 테넌트 계정을 긁어낼 수
있어서. 대신 서버 배포시 BG_WORKER_TENANT_ID 환경변수로 정한 "이 API가 대신할
테넌트"만 조회 — ai_tools.py 의 bg_worker 라우터가 이미 쓰는 것과 동일한 기존
패턴 재사용. account_label 지정 분기·미지정(기본계정) 분기 둘 다 이 테넌트로
scoped — 2026-08-19 최종점검(Workflow 리뷰)에서 account_label 분기가 테넌트
필터 없이 조회하던 critical 결함을 잡아 고침)
Header: X-Internal-Token: <samba-wave 에 이미 있는 cs_internal_token 재사용 — 새로 안 만듦>

200 → { "market_type": "coupang", "account_label": "...", "fields": {...} }
      (fields 는 domain/samba/account/credentials.py 의 build_creds() 출력 그대로)
404 → 활성 계정 없음(또는 account_label 불일치, 또는 명시 기본계정이 없어서 —
      "최근 활성 계정으로 추측"은 안 함)
403 → X-Internal-Token 불일치
503 → 토큰 자체가 설정 안 됨(운영 세팅 누락)
```

**아직 미해결 (다음 사이클)**: 모음전은 11번가를 "eleven11"로, samba-wave 는
"11st"로 부른다(그 외 마켓도 이름이 다를 수 있음) — 5개 플랫폼 클라이언트를 이
브리지에 연결할 때 이름 변환이 반드시 필요. 지금은 호출부가 없어 안 드러난
상태(`shared/market_accounts/client.py` 의 `MarketAccountCredential.market_type`
주석 참조 — 워크트리 `C:/dev/_wt_sambawave`, 아직 main 미병합).

인증은 samba-wave 가 이미 쓰고 있는 `/internal/cs/*`·`/internal/balju/*` 와 **동일한
토큰을 재사용**한다(`cs_internal.py`의 `_require_internal_token`) — 새 비밀값을 안 만들어도
됨. 조회 로직도 새로 안 짬 — `SambaAccountService.find_default_for()`(기본계정 우선,
없으면 최근 활성) + `build_creds()` 그대로 사용.

**남은 것**:
- `C:/dev/samba-wave` 에서 `npm run dev:backend` 로 실제 기동 확인 (지금 세션은 의존성
  미설치라 문법 검사만 함)
- fork 로 push + PR 여부 — 사용자 승인 필요
- 모음전 쪽 환경변수에 `cs_internal_token` 값(운영에 이미 있는 값)과 samba-wave 배포
  URL을 넣어야 실제로 호출 가능 — 배포 확정 후

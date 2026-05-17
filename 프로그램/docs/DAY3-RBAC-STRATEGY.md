# Day 3 — 역할 기반 접근 제어 (RBAC) 전략

> 작성: Day 0 ~ Day 2 작업 직후 — 컷오버 전 사용자 검토 필요.
> 적용 시점: 사용자가 admin-only 분류 승인 후 일괄 적용.

---

## 🎯 권한 모델 (확정)

| 역할 | 권한 |
|---|---|
| **admin** | 모든 기능 + 사용자 관리 + 시스템 설정 + 시크릿·API 키 |
| **member** | 일반 운영 (재고·모음전·발주·소싱·업로드) |
| **(비로그인)** | `/auth/login`, `/health`, `/static/*` 만 접근 가능 |

→ before_request 게이트 (webapp/auth/__init__.py) 가 비로그인 차단. member/admin 구분은 라우트별 `@admin_required` 데코레이터.

---

## 🔐 admin 전용으로 분류 제안

### 즉시 admin-only (시크릿 노출 위험)
- `webapp/routes/accounts.py` — **소싱처/마켓 계정 + API 키 + 비밀번호**
  - `GET /accounts/*` 조회는 admin
  - `POST /accounts/*` 변경은 admin
  - 이유: smartstore client secret, coupang access key 등 노출 위험
- `webapp/routes/settings.py` — **시스템 설정 + .env 노출 영역**
  - admin only
- `webapp/routes/source_registry.py` — **소싱처 등록·삭제**
  - admin only (member 는 등록된 소싱처 조회만 가능하게 분리 필요 시 추후)

### admin-only (운영 위험)
- `webapp/routes/queue_dlq.py` — **데드레터 큐 조작**
  - admin only (잘못 건드리면 데이터 손상)
- `webapp/routes/trash.py` — **휴지통 영구 삭제**
  - admin only (복구 불가 작업)
- `KILL_*` 환경변수 토글 라우트 (있다면) — admin only

### member 가능 (일반 운영)
- `webapp/routes/inventory/` — 재고 입출고·조정·실사
- `webapp/routes/bundles.py` — 모음전 관리
- `webapp/routes/orders.py` — 발주·판매·반품 (PO/SO/RO)
- `webapp/routes/sources.py` — 소싱 상품 조회·등록 (계정 자체는 admin)
- `webapp/routes/templates_page.py` — 색상/사이즈 템플릿 (변경 영향 작음)
- `webapp/routes/market_upload.py` — 마켓 업로드 트리거
- `webapp/routes/home.py` — 홈/대시보드
- `webapp/routes/track.py` — 가격 추적

### 회색지대 (사용자 결정 필요)
- `webapp/routes/api_pricing.py` — 가격 정책 수정
  - 후보: admin (가격 = 매출 영향)
  - 또는: member (일상 운영)
- `webapp/routes/api_inventory_link.py` — 박스히어로 연동
  - 후보: admin (시스템 연동 설정)
  - 또는: member (재고 매핑은 운영)
- `webapp/routes/api_benefits.py` — 혜택·쿠폰 정책
  - 후보: admin

---

## 🛠 적용 방법 (admin 분류 확정 후)

### Step 1: admin-only 라우트 파일 상단에 데코레이터 일괄 추가

```python
# 예: webapp/routes/accounts.py 상단에
from webapp.auth.permissions import admin_required

# 모든 view 함수에 추가
@bp.route("/accounts")
@admin_required   # ← 추가
def accounts_list():
    ...
```

### Step 2: Blueprint 전체에 적용 (간단)

```python
# webapp/routes/accounts.py
bp = Blueprint("accounts", __name__)

@bp.before_request
def _admin_only():
    from webapp.auth.permissions import is_team_share_mode
    if not is_team_share_mode():
        return  # 기존 모드 통과
    from flask_login import current_user
    if not current_user.is_authenticated or not current_user.is_admin:
        from flask import abort
        abort(403)
```

→ Step 2 가 더 간결. Blueprint 단위로 잠그면 누락 없음.

### Step 3: UI 보호 (admin 메뉴 노출 제어)

```html
<!-- 템플릿에서 -->
{% if current_user.is_authenticated and current_user.is_admin %}
  <a href="/accounts">계정 관리</a>
  <a href="/settings">설정</a>
  <a href="/auth/users">팀원 관리</a>
{% endif %}
```

---

## ⚠️ 적용 전 사용자 확인 필요

1. **회색지대 3개 라우트** (pricing, inventory_link, benefits) — admin/member 어느 쪽?
2. **member 의 소싱 데이터 조회 범위** — 모든 소싱처 데이터? 본인이 등록한 것만? (지금은 "팀 전체 공유" 정책 → 모두 조회 가능, 변경만 admin)
3. **admin 1명 운영 시나리오** — 너 혼자 admin 이고 팀원 1~2명 member. 이 가정 맞아?

위 3개 답 받으면 Day 3-2 일괄 적용 (Step 2 방식 권장).

---

## 📋 sanity check — before_request 게이트 동작 확인

Day 2 검증에서 이미 다음 확인됨:
- ✅ 비로그인 시 / → /auth/login 으로 리다이렉트
- ✅ `/static/*`, `/health`, `/auth/login` 은 인증 없이 접근 가능
- ✅ `/api/*` 는 401 JSON 반환 (HTML redirect 아님)

→ Day 3 admin 분류 적용 후 추가 검증:
- member 계정으로 `/accounts` 접근 → 403
- admin 계정으로 `/accounts` 접근 → 200

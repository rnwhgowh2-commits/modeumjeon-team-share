# 동기화 상태 (sync-status.md)

> 기존 → 신규 단방향 미러 상태 기록.
> 동기화 실행 시마다 자동 append.
> 사용자가 매일 아침 토스트 알림과 함께 확인.

---

## 📊 현재 상태

- **Day 0 (2026-05-13)**: 초기 복사 완료. 두 시스템 100% 동일 (제외 목록 제외).
- **마지막 동기화**: 2026-05-13 22:51 (수동, robocopy 초기 복사)
- **divergence**: 0 (Day 0 기준)

## ⚙️ 동기화 환경

- **Source (기존)**: `C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템\`
- **Target (신규)**: `C:\dev\모음전 프로젝트\_시스템\`
- **방향**: Source → Target (단방향)
- **자동 실행**: Windows 작업 스케줄러, 매일 04:00, `모음전_팀공유_동기화`
- **수동 실행**: Claude 에게 "동기화" 명령 → `python sync.py`

## 📝 동기화 로그

### 2026-05-13 22:51 — Day 0 초기 복사 (robocopy)
- **방식**: 1회성 초기 복사 (robocopy, /E /MT:8)
- **결과**:
  - 디렉토리 2,378 (복사 2,351, 스킵 27)
  - 파일 16,094 (복사 16,022, 스킵 68, 실패 4)
  - 총 2.71 GB
  - 소요 시간 1분 5초
- **실패 4건**: Chromium 락 파일 (SingletonLock 등) — 브라우저 재실행 시 재생성됨, 무영향
- **스킵 68건**: `.sync-ignore` 매칭 (`.venv/`, `__pycache__/`, `*.db`, `logs/`, 데모 엑셀, 디버그 산출물)
- **포함**: 코드 전체, `data/auth/` (로그인 쿠키), `data/profiles/` (Playwright 세션 2.7GB), 운영 JSON 설정

### (이후 sync.py 자동/수동 실행 로그가 여기에 append 됨)

### 2026-05-13 22:56~22:57 — sync.py 작업 스케줄러 검증 (2회 트리거)
- 22:56:45 — 변경 없음 (테스트 1차)
- 22:57:49 — upd 2 (운영 중 자연 발생 파일 — sidebar_layout.json 등)
- 결론: 작업 스케줄러 + sync.py 정상 동작

### 2026-05-14 — Day 1 작업 동기화
- **17:39:20** — Day 1 패치 반영 (config.py + shared/db.py + requirements.txt + app.py): upd 3
- **17:43:44** — Day 2~4 작업 후 점검: 변경 없음

### 2026-05-14 23:15 — Day 3 동기화
- audit/service.py: actor 자동 채움 (_default_actor)
- 8 라우트 admin 게이트: accounts/settings/source_registry/queue_dlq/trash/api_pricing/api_inventory_link/api_benefits
- 회귀: 기존 모드 295 routes 그대로, /accounts 200 OK, actor=system
- 신규 모드: member→admin 라우트=403, admin→200, audit actor 자동 채움 OK

### Day 1~4 변경 요약
| 분류 | 파일 | 위치 |
|---|---|---|
| 백워드 호환 패치 | `config.py` | 기존 → 동기화 → 신규 |
| 백워드 호환 패치 | `shared/db.py` (PRAGMA → inspect) | 기존 → 동기화 → 신규 |
| 백워드 호환 패치 | `requirements.txt` (psycopg2 + Flask-Login + Flask-WTF + email-validator + gunicorn) | 기존 → 동기화 → 신규 |
| 백워드 호환 패치 | `app.py` (env-gated 인증 초기화) | 기존 → 동기화 → 신규 |
| 신규 전용 | `webapp/auth/*` (5 파일) | 신규만 — .sync-ignore 보호 |
| 신규 전용 | `webapp/templates/auth/*` (6 파일) | 신규만 — .sync-ignore 보호 |
| 신규 전용 | `scripts/create_admin.py` | 신규만 — .sync-ignore 보호 |
| 신규 전용 | `_시스템/Dockerfile`, `.dockerignore`, `fly.toml` | 신규만 — .sync-ignore 보호 |
| 신규 전용 | `migrations/sqlite_to_supabase.py` | 신규 루트 (sync 무관 — _시스템 밖) |
| 신규 전용 | `docs/DAY3-RBAC-STRATEGY.md`, `docs/DAY3-AUDIT-STRATEGY.md`, `docs/DEPLOY.md` | 신규 루트 (sync 무관) |
| 신규 .env | `_시스템/.env` (DATABASE_URL/ENVIRONMENT 추가) | 신규만 — .sync-ignore 보호 |


---

## 🚨 발견 시 대응

### Schema 변경 감지
- sync.py 가 `lemouton/**/models*.py` 또는 `webapp/**/models*.py` 변경 감지 시 alert
- 대응: 신규 폴더에서 다음 1줄 실행
  ```
  cd "C:\dev\모음전 프로젝트\_시스템"
  flask db migrate -m "auto: model changes from sync"
  flask db upgrade
  ```
- (Supabase 연결 후 적용)

### 충돌 감지 (신규 전용 파일을 기존도 수정)
- sync.py 가 `.sync-ignore` 매칭 파일의 기존-쪽 수정 감지 시 alert
- 대응: 룰 위반이므로 기존-쪽 수정 사항 검토 후 신규에만 적용 또는 룰 재정의

## 📅 향후 계획

- **Day 1**: Supabase 가입 + DB 이전 + `config.py` 의 `DATABASE_URL` 수정
- **Day 2**: Flask-Login + `users` 테이블 + 로그인 화면
- **Day 3**: 모든 라우트 `@login_required` + admin/member 권한 분리
- **Day 4**: Fly.io 배포 + 무료 도메인 (`yourapp.fly.dev`) + 팀원 2명 계정 발급
- **Day 5+**: 팀 실사용 검증 → 컷오버

# 배포 가이드 — Fly.io + Supabase

> 모음전 팀공유 시스템 (Day 4) — 무료 인프라로 24시간 운영.
> 사용자 액션 필요: Supabase 가입 (Day 1) + Fly.io 가입 + flyctl 설치.

---

## 🏗 아키텍처

```
[팀원 브라우저]
     ↓ HTTPS
[Fly.io VM (Tokyo)]
   ├─ Flask + Gunicorn
   ├─ docker container (Python 3.14 slim)
   └─ 256MB RAM, shared CPU (무료)
     ↓ PostgreSQL connection
[Supabase (Seoul)]
   └─ PostgreSQL 500MB (무료)

[너의 PC (Plan A 하이브리드)]
   └─ Playwright 크롤러 (기존 그대로 유지)
        ↓ Supabase 에 결과 푸시
```

---

## 1️⃣ 사전 준비

### 가) flyctl 설치 (Windows)

PowerShell 관리자 권한:
```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

설치 후 PATH 추가됨. 새 셸에서:
```powershell
fly version
```

### 나) Fly.io 계정

```powershell
fly auth signup     # 이메일 가입 (또는 GitHub 로그인)
# 또는
fly auth login      # 기존 계정 로그인
```

⚠️ Fly.io 는 가입 시 신용카드 등록 필요 (무료 한도 초과 방지용). 무료 한도 내 사용 시 청구 없음.

### 다) Supabase URL 확보 (Day 1 완료 전제)

`.env` 의 DATABASE_URL 활성화 + connection string 입력 완료.

---

## 2️⃣ 첫 배포

### Step 1: 앱 생성 (deploy 는 아직)

```powershell
cd "C:\dev\모음전 프로젝트\_시스템"
fly launch --name modeumjeon-team-share --region nrt --no-deploy
```

- 앱 이름은 `fly.toml` 에 적힌 거 그대로. 중복 시 다른 이름 시도.
- **"Would you like to overwrite fly.toml?"** 물으면 **n** (현재 파일 유지).
- DB 자동 생성 거절 (Supabase 사용).

### Step 2: 시크릿 등록

`.env` 의 모든 변수를 Fly.io secrets 로 옮김.

```powershell
# DB
fly secrets set DATABASE_URL='postgresql://postgres.xxxxx:PASSWORD@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres'

# Flask
fly secrets set FLASK_SECRET_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(48))")"
fly secrets set ENVIRONMENT='team-share-dev'

# 마켓·소싱처 시크릿 (.env 에 있는 값 그대로)
fly secrets set SMARTSTORE_MAIN_CLIENT_ID='...'
fly secrets set SMARTSTORE_MAIN_CLIENT_SECRET='...'
fly secrets set COUPANG_MAIN_ACCESS_KEY='...'
fly secrets set COUPANG_MAIN_SECRET_KEY='...'
fly secrets set COUPANG_MAIN_VENDOR_ID='...'
# ... (필요한 만큼 추가)
```

### Step 3: 배포

```powershell
fly deploy
```

이미지 빌드 (5~10분) → upload → 헬스체크 → 라이브.

### Step 4: 도메인 확인

```powershell
fly info
```

`hostname` 줄에 표시되는 `modeumjeon-team-share.fly.dev` 가 무료 도메인. 즉시 사용 가능.

### Step 5: 초기 admin 생성

```powershell
# 로컬에서 (Supabase 에 직접 연결)
cd "C:\dev\모음전 프로젝트\_시스템"
python scripts/create_admin.py --email you@company.com --name "관리자"
# 비번 prompt
```

---

## 3️⃣ 배포 후 검증

### 가) 헬스체크
```powershell
fly status
fly checks list   # 헬스체크 결과
```

### 나) 로그
```powershell
fly logs           # 실시간
fly logs -n        # 마지막 100줄
```

### 다) 실접속
브라우저로 `https://modeumjeon-team-share.fly.dev/auth/login` → 로그인 → 메인 페이지 진입 확인.

글로벌 룰 §3 — `/ui-verify` 또는 `/qa` 로 실접속 전수 검증.

---

## 4️⃣ 업데이트 (코드 변경 후)

```powershell
cd "C:\dev\모음전 프로젝트\_시스템"
fly deploy
```

---

## 5️⃣ 운영 명령어

| 작업 | 명령 |
|---|---|
| 상태 보기 | `fly status` |
| 로그 보기 | `fly logs` |
| SSH 접속 | `fly ssh console` |
| 시크릿 추가 | `fly secrets set KEY=VALUE` |
| 시크릿 목록 | `fly secrets list` |
| 머신 재시작 | `fly machine restart <machine_id>` |
| 스케일링 (메모리 ↑) | `fly scale memory 512` |
| 비용 확인 | `fly dashboard` (웹) |
| 앱 삭제 | `fly apps destroy modeumjeon-team-share` |

---

## ⚠️ 메모리 부족 시 (256MB → 512MB)

증상: 첫 요청 OOM, 자동 재시작 반복.

해결:
```powershell
fly scale memory 512
```

512MB 부터는 무료 한도 초과로 월 ~$2 청구. 5명 팀 5분 사용 / 하루 8시간 기준 충분.

---

## 🛡 보안 체크리스트

- [ ] `FLASK_SECRET_KEY` 는 secrets.token_urlsafe(48) 로 강력하게
- [ ] Supabase DB password 는 강력하게 (Day 1 셋업 시 메모)
- [ ] Fly.io `.env` 파일 commit 안 함 (`.dockerignore` 등록 완료)
- [ ] HTTPS 자동 (`force_https = true` 설정됨)
- [ ] X-Frame-Options 등 보안 헤더 자동 (app.py 의 `_apply_security_headers`)
- [ ] 비밀번호 bcrypt rounds=12 (강력)
- [ ] admin/member 권한 분리 (Day 3 적용 후)
- [ ] 화이트리스트 외 모든 라우트 로그인 필수 (`webapp/auth/__init__.py`)

---

## 📞 트러블슈팅

### DB 연결 실패
```
sqlalchemy.exc.OperationalError: connection to server timeout
```
→ Supabase URL 확인. **Session pooler** 가 아닌 **Transaction pooler** 일 경우 SQLAlchemy 호환성 문제. fly.toml 에 명시된 대로 Session pooler 사용.

### Cold start 너무 느림
```
fly.toml 에서 min_machines_running = 1 로 변경
```
머신 1개 항상 ON. 무료 한도 안 (3 머신까지 가능).

### Playwright 크롤러가 안 됨
→ Fly.io 에 Playwright 빠져 있음 (Plan A 하이브리드). 크롤러는 너의 PC 에서 계속 실행. 데이터는 Supabase 로 푸시.

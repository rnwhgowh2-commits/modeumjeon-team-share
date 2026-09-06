# 모음전 — Fly.io 배포 가이드

> 끝선 = Fly.io 배포. 배포 = **Supabase(DB) + Fly.io(서버)**.
> cycle 20260521 · 대상: 신규 프로젝트 `프로그램/_시스템/`

---

## 0. 배포 인프라 — 이미 준비됨 ✅

새로 만들 게 없습니다. 다음이 이미 존재·정상:

| 파일 | 상태 |
|---|---|
| `Dockerfile` | ✅ Python 3.14-slim · gunicorn · 비-root · 8080 |
| `fly.toml` | ✅ app `modeumjeon-team-share` · region nrt(도쿄) · `/health` 체크 |
| `.dockerignore` | ✅ DB·로그·.env·sync 제외 |
| `config.py` | ✅ `DATABASE_URL` env 우선 → Supabase 연결 |
| `requirements.txt` | ✅ gunicorn · psycopg2-binary 포함 |

→ 코드 쪽 배포 준비는 끝. **남은 건 사용자 계정 작업뿐.**

---

## ⚠️ 사용자가 직접 해야 하는 것 (Claude 가 대신 불가)

Supabase·Fly 는 **사장님 계정**이라 로그인·생성을 제가 못 합니다. 아래는 사장님이 실행합니다 (명령은 제가 정확히 드림).

---

## 1. Supabase — 팀 공유 DB 만들기

1. https://supabase.com 가입 → **New project**
   - Name: `modeumjeon` / Region: **Northeast Asia (Seoul 또는 Tokyo)** / DB 비밀번호 설정 (메모)
2. 생성 후 → **Project Settings → Database → Connection string → URI** 복사
   - 형식: `postgresql://postgres:[비밀번호]@db.[ref].supabase.co:5432/postgres`
3. SSL 필요 시 끝에 `?sslmode=require` 추가.
   → 이 문자열이 **`DATABASE_URL`** 입니다.

## 2. Fly.io — 서버 준비

```powershell
# (1) flyctl 설치 — PowerShell
iwr https://fly.io/install.ps1 -useb | iex

# (2) 로그인 (계정 없으면 가입)
fly auth login

# (3) 앱 — fly.toml 의 modeumjeon-team-share. 아직 없으면 생성:
fly apps create modeumjeon-team-share
```

## 3. 비밀값 주입 + 배포

`프로그램/_시스템/` 폴더에서 실행:

```powershell
# 비밀값 — DATABASE_URL 은 1번에서 복사한 것
fly secrets set `
  DATABASE_URL="postgresql://postgres:...@db.xxx.supabase.co:5432/postgres" `
  FLASK_SECRET_KEY="(임의의 긴 랜덤 문자열)" `
  ENVIRONMENT="team-share-dev"

# 배포
fly deploy
```

> **중요** — `ENVIRONMENT=team-share-dev` 를 꼭 설정. 이게 있어야 빈 Supabase DB 에 `create_all` 이 모든 테이블을 만듭니다 (app.py 가 이 값으로 전체 모델을 등록).

## 4. 확인

```powershell
fly open            # 브라우저로 열림
fly logs            # 로그 확인
```

- `https://modeumjeon-team-share.fly.dev/health` 가 정상 응답이면 배포 성공.
- 첫 접속 시 `create_all` 이 Supabase 에 스키마 생성 (자동).

---

## 배포 전 체크리스트

- [ ] 6개 기능 구현 완료 (Phase 1~6 — `docs/PLAN.md`)
- [ ] Supabase 프로젝트 생성 + `DATABASE_URL` 확보
- [ ] `fly auth login` 완료
- [ ] `fly secrets set` (DATABASE_URL · FLASK_SECRET_KEY · ENVIRONMENT)
- [ ] `fly deploy` → `/health` 정상

> 크롤러(Playwright)는 Docker 이미지에 미포함 — 사용자 PC 에 유지 (Plan A 하이브리드). 배포된 서버는 웹앱·DB만.

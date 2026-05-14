# CLAUDE.md — 모음전 프로젝트 (팀 공유 신규)

> **계층**: 프로젝트 (글로벌 `~/.claude/CLAUDE.md` 보다 우선)
> **책임**: 본 프로젝트 도메인 룰 + 단방향 미러 룰
> **상위 의존**: 글로벌 CLAUDE.md (보편 6원칙)
> **자매 프로젝트**: 기존 시스템 (`C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템\`)

---

## 🎯 본 프로젝트 정의

- **목적**: 기존 단일유저 SQLite 시스템 → 팀 공유 (현재 2명, 향후 5명) 가능한 멀티유저 시스템으로 전환
- **데이터 모델**: 팀 전체가 같은 데이터 공유 (per-user 분리 ❌)
- **권한**: admin / member 2단계
- **배포**: 무료 (Fly.io + Supabase 예정)
- **개발 방식**: 병렬 (기존 무중단 운영 + 신규 점진 구축 → 컷오버)

## 🔄 단방향 미러 룰 (절대 준수)

```
[기존]  → 변경 → [신규]  ✅ (사용자 "동기화" 명령 또는 매일 04:00 자동)
[기존]  ← 차단 ← [신규]  ❌ (영원히)
```

### 룰
1. **기존 시스템 코드 변경 → 신규에도 반영** (sync.py 가 수행)
2. **신규 시스템 변경 → 기존에 절대 반영 금지** (코드·DB 모두)
3. **신규 전용 파일** (auth, deploy, Supabase 관련) 은 `.sync-ignore` 에 명시 → 동기화 시 자동 보호

### 사용자 명령
- "동기화" / "sync" / "기존 → 신규 동기화" → Claude 가 `python sync.py` 실행
- 매일 04:00 → Windows 작업 스케줄러가 `python sync.py --scheduled` 자동 실행

### Claude 가 신규에서 작업 시 주의
- 기존 폴더 절대 수정 금지 (read-only)
- 신규 전용 파일 만들면 즉시 `.sync-ignore` 에 추가
- DB 스키마 변경 시 Alembic 마이그레이션 생성 (Supabase 적용용)

## 🚫 비-신규-전용 변경은 기존에 먼저

비-신규-전용 (= 비즈니스 로직, 모델, 라우트, 크롤러) 변경이 필요하면:
1. 먼저 기존 시스템에 변경
2. `python sync.py` 또는 매일 04:00 자동 동기화로 신규에 반영
3. 신규에서 직접 비즈니스 로직 수정 ❌

이유: divergence 방지. 신규에서 먼저 고치면 기존이 뒤처지고, 그 뒤 기존 → 신규 동기화 시 신규 변경이 덮어쓰여짐.

## 📋 동기화 대상·예외

### 동기화됨 (기존 → 신규)
- `lemouton/` (도메인 모델·서비스)
- `webapp/` (라우트·템플릿·정적 자원)
- `shared/` (DB·플랫폼·notifier)
- `scheduler/`, `scripts/`, `tests/`
- `app.py`, `requirements.txt`

### 동기화 안 됨 (`.sync-ignore` 참조)
- 캐시·로그·DB 파일
- 테스트 엑셀
- Playwright 프로필 (Day 0 초기 복사엔 포함, daily 에선 제외)
- 신규 전용 파일 (auth/, Dockerfile, fly.toml 등 — Day 1+ 작성)

### 부분 동기화 (line-level)
- `config.py` — `DATABASE_URL`, `SUPABASE_URL` 등 신규 전용 라인 보존
- `requirements.txt` — `Flask-Login`, `psycopg2`, `gunicorn` 등 신규 전용 패키지 보존

## 🌐 인프라 (예정)

- **DB**: Supabase PostgreSQL (무료 티어, 500MB)
- **호스팅**: Fly.io 무료 (Flask 웹앱)
- **크롤러**: 기존 사용자 PC 유지 (Plan A 하이브리드)
- **알림**: 토스트 알림 (당분간) → Telegram 봇 (나중)

## ✅ 검증

- 기존 시스템 무결성: 본 프로젝트 작업으로 기존 폴더 mtime 변경 0건이어야 함
- 동기화 로그: `sync.log` 매일 append
- 상태 추적: `docs/sync-status.md` 매 동기화 후 업데이트

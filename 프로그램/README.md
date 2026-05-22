# 모음전 팀공유 시스템

> Flask + Supabase PostgreSQL + Fly.io. 팀 다중 사용자 재고·모음전·소싱·발주 관리.

🌐 **라이브**: https://modeumjeon-team-share.fly.dev

---

## 🏗 아키텍처

```
[팀원 브라우저]
     ↓ HTTPS
[Fly.io VM (도쿄)]                    
   ├─ Flask + Gunicorn (Python 3.14)
   ├─ Flask-Login (bcrypt)
   └─ admin / member 권한 분리
     ↓
[Supabase PostgreSQL (도쿄)]
   └─ 56 테이블, 무료 500MB
     ↑
[사용자 PC (Plan A 하이브리드)]
   └─ Playwright 크롤러 (24/7)
        → Supabase 에 결과 푸시
```

---

## 📁 폴더 구조

```
모음전 프로젝트/
├── _시스템/                    # Flask 앱 본체
│   ├── app.py                 # 진입점
│   ├── config.py              # 환경설정 (DATABASE_URL env-aware)
│   ├── Dockerfile             # Fly.io 빌드
│   ├── fly.toml               # Fly.io 배포 설정
│   ├── requirements.txt
│   ├── lemouton/              # 도메인 모델·서비스
│   │   ├── audit/             # 변경 이력 (actor 자동 채움)
│   │   ├── auth/              # 소싱처 자동 로그인 (Playwright)
│   │   ├── inventory/         # 재고관리 모델
│   │   ├── multitenancy/      # 계정 멀티테넌시
│   │   ├── pricing/           # 가격 정책
│   │   ├── sources/           # 소싱처 데이터
│   │   ├── sourcing/          # 소싱 크롤러
│   │   ├── templates/         # 색상/사이즈 템플릿
│   │   └── uploader/          # 마켓 업로드
│   ├── shared/                # 공유 인프라
│   │   ├── db.py              # SQLAlchemy (dialect-agnostic)
│   │   └── platforms/         # 무신사·SSF·쿠팡·스마트스토어
│   ├── webapp/                # Flask 라우트·템플릿
│   │   ├── auth/              # 팀공유 인증 (Flask-Login)
│   │   ├── routes/            # 비즈니스 라우트 (admin/member 게이트)
│   │   ├── static/            # 디자인 토큰 (toss.css)
│   │   └── templates/
│   ├── scheduler/             # 백그라운드 작업
│   ├── scripts/               # CLI 유틸 (create_admin.py 등)
│   └── tests/
├── migrations/                # SQLite → Supabase 1회성
├── docs/                      # 설계 문서
│   ├── DEPLOY.md
│   ├── DAY3-RBAC-STRATEGY.md
│   └── DAY3-AUDIT-STRATEGY.md
├── CLAUDE.md                  # AI 에이전트 룰
└── README.md
```

---

## 🚀 로컬 실행 (개발자용)

```powershell
cd _시스템
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# .env 파일 만들기 (시크릿)
# DATABASE_URL=postgresql://...
# FLASK_SECRET_KEY=...
# ENVIRONMENT=team-share-dev

python app.py
# → http://127.0.0.1:5052
```

---

## ☁️ 배포

자세한 가이드: [docs/DEPLOY.md](docs/DEPLOY.md)

```powershell
cd _시스템
flyctl deploy
```

---

## 🔑 환경변수

| 변수 | 설명 | 예시 |
|---|---|---|
| `DATABASE_URL` | Supabase PostgreSQL | `postgresql://postgres.xxx:PWD@aws-...` |
| `ENVIRONMENT` | 모드 분리 (`team-share-dev` 시 인증 활성) | `team-share-dev` |
| `FLASK_SECRET_KEY` | 세션 암호화 | `secrets.token_urlsafe(48)` |
| `SMARTSTORE_*` | 스마트스토어 API | (생략) |
| `COUPANG_*` | 쿠팡 API | (생략) |

⚠️ `.env` 파일은 절대 commit X (`.gitignore` 등록됨).

---

## 🛡 보안

- bcrypt 비번 해싱 (rounds=12)
- Flask-Login 세션 (`session_protection = strong`)
- HTTPS 자동 (Fly.io + Let's Encrypt)
- 보안 헤더 (X-Frame-Options, X-Content-Type-Options, ...)
- admin / member 권한 분리
- 화이트리스트 외 모든 라우트 로그인 필수

---

## 👥 팀원 추가

admin 계정으로:
1. 로그인 → `/auth/users/invite`
2. 이메일·이름·임시비번·역할 입력
3. 팀원에게 임시비번 안전하게 전달
4. 팀원 첫 로그인 후 `/auth/change-password` 권장

---

## 📊 시스템 상태

- **Day 0-4 완료**: 인프라·인증·권한·배포 (2026-05-13 ~ 2026-05-15)
- **컷오버 완료**: 기존 시스템 폐기, 신규 단독 운영 (2026-05-22)

---

## 🤝 개발 컨벤션

- 글로벌 룰: `CLAUDE.md` 참조
- 변경은 모두 audit_log 에 자동 기록 (actor = 로그인 사용자 이메일)

---

## 📞 운영

| 작업 | 명령 |
|---|---|
| 로그 보기 | `fly logs` |
| 머신 상태 | `fly status` |
| 시크릿 추가 | `fly secrets set KEY=VALUE` |
| SSH 접속 | `fly ssh console` |
| 재배포 | `cd _시스템 && fly deploy` |
| 첫 admin 생성 | `python scripts/create_admin.py --email X --name Y` |

---

## 라이선스

Private — 모음전 팀 내부 사용 한정.

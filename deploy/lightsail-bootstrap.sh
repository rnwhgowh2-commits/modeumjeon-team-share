#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# AWS Lightsail 서버 1회 셋업 — Docker 설치 + 앱 환경변수 파일 생성
# ════════════════════════════════════════════════════════════
# 사용법 (인스턴스 SSH 접속 후 1회):
#   curl -fsSL https://raw.githubusercontent.com/rnwhgowh2-commits/modeumjeon-team-share/main/deploy/lightsail-bootstrap.sh | bash
#   그 다음 ~/app.env 를 실제 키 값으로 채운다 (아래 안내).
# ════════════════════════════════════════════════════════════
set -e

echo "[1/3] Docker 설치"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker ubuntu
  echo "  → Docker 설치 완료 (그룹 적용 위해 재로그인 1회 필요)"
else
  echo "  → Docker 이미 설치됨"
fi

echo "[2/3] app.env 템플릿 생성 (없을 때만)"
if [ ! -f /home/ubuntu/app.env ]; then
  cat > /home/ubuntu/app.env <<'ENVEOF'
# ── 모음전 앱 환경변수 — 실제 값으로 채우세요 (현재 Fly secrets 와 동일) ──
ENVIRONMENT=team-share-dev
FLASK_SECRET_KEY=__채우기__
DATABASE_URL=__Supabase_postgresql_URL__

# Cloudflare R2 (이미지)
R2_ACCOUNT_ID=__채우기__
R2_ACCESS_KEY_ID=__채우기__
R2_SECRET_ACCESS_KEY=__채우기__
R2_BUCKET=modeumjeon-images
R2_PUBLIC_BASE_URL=__채우기__

# 스마트스토어 커머스 API
SMARTSTORE_MAIN_CLIENT_ID=__채우기__
SMARTSTORE_MAIN_CLIENT_SECRET=__채우기__

# 쿠팡 WING API
COUPANG_MAIN_ACCESS_KEY=__채우기__
COUPANG_MAIN_SECRET_KEY=__채우기__
COUPANG_MAIN_VENDOR_ID=__채우기__
ENVEOF
  chmod 600 /home/ubuntu/app.env
  echo "  → /home/ubuntu/app.env 생성. 'nano ~/app.env' 로 값을 채우세요."
else
  echo "  → app.env 이미 존재 (보존)"
fi

echo "[3/3] 방화벽 확인 — Lightsail 콘솔에서 80(HTTP) 포트 열려있는지 확인"
echo ""
echo "✅ 셋업 완료. 다음:"
echo "   1) nano ~/app.env  → 실제 키 값 입력 후 저장"
echo "   2) GitHub Actions 에서 'AWS Lightsail 자동배포' 1회 수동 실행 → 배포 확인"

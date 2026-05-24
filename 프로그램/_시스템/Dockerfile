# ============================================================
# 모음전 팀공유 — Dockerfile (Fly.io 무료 티어 256MB 최적화)
# ============================================================
# Python 3.14 slim + Playwright 미포함 (크롤러는 사용자 PC 에 유지 — Plan A 하이브리드)
# 빌드: docker build -t modeumjeon .
# 로컬: docker run -p 8080:8080 --env-file .env modeumjeon
# 배포: fly deploy
# ============================================================

FROM python:3.14-slim

# 시스템 패키지 — psycopg2 빌드 의존성 (binary 휠 있어 보통 불필요하나 안전망)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements 먼저 (캐시 활용)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# [2026-05-24] cache busting — Depot/Docker layer cache 무력화
ARG CACHEBUST=20260524_2230
RUN echo "cachebust=${CACHEBUST}"

# 코드 복사
COPY . .

# 비-root 사용자 (보안)
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8080

# Gunicorn — Flask 앱 진입점 = app:create_app()
# 워커 2개 × 스레드 4개 = 동시 요청 처리 8개. --preload 로 모델 import 메모리
# 공유 → 두 워커 추가 메모리 ~50-100MB (1GB 머신 안 충분).
# --worker-tmp-dir /dev/shm: 워커 heartbeat 파일을 tmpfs(메모리)에 → 디스크 IO
# 제거. 컨테이너 환경 best practice. /dev/shm 은 기본 64MB.
# --max-requests 1000 + jitter 100: 워커가 1000±100 요청 처리 후 재시작 →
# 메모리 누수 누적 방지 (안정성↑, 속도 직접 영향 없음).
# 타임아웃 60초 (크롤러 대시보드 등 무거운 요청 대비)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--threads", "4", \
     "--worker-tmp-dir", "/dev/shm", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--preload", \
     "app:create_app()"]

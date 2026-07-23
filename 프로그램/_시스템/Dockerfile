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
ARG CACHEBUST=20260524_2300_VERIFY
RUN echo "cachebust=${CACHEBUST}"

# 코드 복사
COPY . .

# [2026-05-24] BUILD-TIME VERIFY — 우리 fix 가 image 에 들어갔는지 명시 확인
# brandPx 가 없으면 빌드 실패 (cache 사용해서 옛 코드 들어간 케이스 잡음)
RUN echo '--- base.html 진단 ---' && \
    wc -l /app/webapp/templates/base.html && \
    grep -c "option_url_modal" /app/webapp/templates/base.html && \
    grep "script src" /app/webapp/templates/base.html | tail -3 && \
    echo '--- end ---'

# [2026-05-27] Fly Volume mount 대비 — /app/data 의 git 기본 파일을 별도 위치로 백업
#   런타임에 volume 마운트하면 /app/data 가 빈 volume 으로 가려짐 → entrypoint 가 빈 경우만 시드
RUN mkdir -p /app/data_initial && cp -rT /app/data /app/data_initial 2>/dev/null || true

# entrypoint 스크립트 — Fly Volume 의 lost+found 때문에 "빈 디렉토리" 체크 불가능
#   cp -n (no-clobber) 로 destination 에 없는 파일만 복사 — 사용자 데이터 안 덮어씀, 빠진 default 만 채움
RUN echo '#!/bin/sh' > /app/entrypoint.sh && \
    echo 'set -e' >> /app/entrypoint.sh && \
    echo '# /app/data_initial 의 default 중 destination 에 없는 것만 복사 (사용자 데이터 보존)' >> /app/entrypoint.sh && \
    echo 'if [ -d /app/data_initial ]; then' >> /app/entrypoint.sh && \
    echo '  echo "[entrypoint] /app/data_initial → /app/data 시드 (no-clobber)"' >> /app/entrypoint.sh && \
    echo '  cp -rn /app/data_initial/. /app/data/ 2>/dev/null || true' >> /app/entrypoint.sh && \
    echo 'fi' >> /app/entrypoint.sh && \
    echo 'exec "$@"' >> /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# 비-root 사용자 (보안)
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]

# Gunicorn — Flask 앱 진입점 = app:create_app()
# [perf 2026-05-29] 워커 3 × 스레드 6 = 동시 요청 처리 18개 (기존 2×4=8).
#   배경: 무거운 요청 1개가 워커를 점유하면 다른 사용자/탭 요청이 줄서서 적체
#         (라이브 전수조사에서 재현 — 무거운 요청 시 전체 20초+ 먹통).
#   근본 원인(옵션조합 모달 6초 CPU)은 이번 커밋에서 제거했고, 여기서는 동시성
#   여유를 보강해 잔여 적체를 완화. --preload 로 코드 메모리 공유(fork COW) →
#   워커 1개 추가 메모리 ~25-50MB, 1GB 머신 내 충분.
#   ⚠️ CPU 는 shared-cpu-1x(1코어)라 CPU-bound 병렬은 워커 수만큼만. 더 필요하면
#      fly.toml [[vm]] size 를 shared-cpu-2x 로 (비용 발생 — 사용자 승인 필요).
# --worker-tmp-dir /dev/shm: 워커 heartbeat 파일을 tmpfs(메모리)에 → 디스크 IO 제거.
# --max-requests 1000 + jitter 100: 워커 1000±100 요청 후 재시작 → 메모리 누수 방지.
# 타임아웃 180초 — 60초였을 때 마진 분석이 늘 502 로 죽었다(2026-07-23 실측:
#   6마켓 한 요청 = 61.7초, 그중 옥션 58.1초·G마켓 46.5초. 60초를 넘기면 gunicorn 이
#   워커를 죽여 응답이 JSON 이 아니게 되고, 화면엔 "서버 오류"만 뜬다).
#   ⚠️ 이건 안전망일 뿐 해법이 아니다 — 앞단 Cloudflare 가 100초에서 끊으므로
#      180초를 실제로 쓸 수 있는 게 아니다. 진짜 해법은 요청을 짧게 쪼개는 것
#      (마진 분석 = 저장분만 읽기 / 최신 수집은 마켓별 run-sync 로 나눠 호출).
#   동시 처리 여력: 3워커 × 6스레드 = 18 → 긴 요청 하나가 화면 전체를 막지 않는다.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "3", \
     "--threads", "6", \
     "--worker-tmp-dir", "/dev/shm", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--timeout", "180", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--preload", \
     "app:create_app()"]

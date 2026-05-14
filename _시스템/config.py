"""
르무통 재고 업데이트 — 환경변수 / 기본 설정 로드.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env", override=True)


class Config:
    HOST = os.environ.get("FLASK_HOST", "127.0.0.1")
    PORT = int(os.environ.get("FLASK_PORT", "5052"))
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-not-secure")

    DB_PATH = PROJECT_ROOT / os.environ.get("LEMOUTON_DB_PATH", "data/lemouton.db")
    # DATABASE_URL 환경변수 우선 (PostgreSQL / Supabase 등) — 없으면 SQLite 폴백 (백워드 호환).
    # 신규 팀공유 프로젝트 (C:\dev\모음전 프로젝트\) 에서는 .env 에 DATABASE_URL=postgresql://... 설정.
    DB_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}"

    LOG_DIR = PROJECT_ROOT / "logs"


Config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
Config.LOG_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────
# 소싱처 로그인 세션 + 크롤러 설정
# ──────────────────────────────────────────────────────────────
SOURCING_AUTH = {
    "auth_dir": str(PROJECT_ROOT / "data" / "auth"),
    "crawl_timeout_ms": 25000,
    "csr_wait_ms": 5000,
    "dropdown_interval_ms": 200,
    "stock_cap": 10,
    "login_urls": {
        # 무신사: /auth/login → 자동 리디렉트 → member.one.musinsa.com/login (정상)
        "무신사":     "https://www.musinsa.com/auth/login",
        # SSF: 2026 리뉴얼 후 /public/member/login
        "SSF샵":      "https://www.ssfshop.com/public/member/login",
        "르무통":     "https://lemouton.co.kr/member/login.html",
    },
    "login_path_patterns": ["/login", "/auth", "/signin"],
    "manual_login_wait_sec": 300,

    # 무신사 회원가 산정 룰 — 2026-05-05 사용자 확정 정책 (musinsa_playwright._crawl 참조)
    # 누적식 5단계:
    #   sale_price
    #     - 등급할인 (활성 시 화면값)
    #     - 상품쿠폰
    #     - 선할인 (정책: 0, 항상 "구매적립" 라디오 선택)
    #     - 적립금사용 (정책: 0, 이중차감 방지)
    #   = base1
    #     - 후기적립 500원 (항목 있을 때 고정)
    #   = base2
    #     - 등급적립 = base2 × LV별 % (활성 시)
    #     - 구매 추가 적립 (활성 시 화면값)
    #   = base3
    #     - 무신사머니 적립 = base3 × LV별 % (기본+프로모션 합계)
    #   = ★ 매입가 (계층 2)
    #
    # 정책상 무시 항목:
    #   - 결제수단 즉시할인 (토스페이/카드 등 — 일관성 X)
    #   - 결제수단 적립 (무신사 삼성카드 등 — 무신사머니 적립만 사용)
    "musinsa_rules": {
        # 모두 deprecated (호환성 유지) — 신규 누적식이 우선
        "card_cashback_rate":     0.0273,   # 미사용 (LV별 무신사머니 % 매 크롤 추출)
        "include_card_discount":  False,    # 미사용 (정책: 결제수단 무시)
        "include_point_use":      False,    # 미사용 (정책: 적립금사용 0)
        # 신규 정책 명시
        "review_reward_fixed":    500,      # 후기적립 항목 있을 때 고정 차감 (일반 후기)
        "purchase_radio_default": "purchase_reward",  # 항상 "구매적립" 선택 가정
    },
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

Path(SOURCING_AUTH["auth_dir"]).mkdir(parents=True, exist_ok=True)

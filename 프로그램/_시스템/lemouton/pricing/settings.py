"""[B] 글로벌 설정 — 단일 row 테이블."""
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, ForeignKey
from datetime import datetime, timezone

from shared.db import Base


# DEFAULT 값 — 사용자 결정 기반 (spec §2)
_DEFAULTS = {
    "boxhero_purchase_price_default": 95000,
    "boxhero_ss_price_default": 115900,
    "boxhero_coupang_price_default": 128900,
    "external_ss_price_default": 128900,
    "external_coupang_price_default": 128900,
    "coupang_winner_premium_price": 149000,
    "guardrail_lower": 99000,
    "guardrail_upper": 120000,
    "delivery_fee": 3000,
    "ss_fee_rate": 0.06,
    "coupang_fee_rate": 0.1155,
    "external_ss_margin_mode": "rate",
    "external_ss_margin_value": 0.0945,
    "external_coupang_margin_mode": "rate",
    "external_coupang_margin_value": 0.1242,
    "rounding_unit": 100,
    "crawl_interval_hours": 6,
    "dryrun_warnings_threshold": 5,
    "dryrun_avg_price_change_pct": 30.0,
    # [자동화 설정] 크롤 자동 주기 + 판매처 자동 전송
    "crawl_auto_enabled": False,
    "crawl_interval_minutes": 0,
    "autosend_mode": "preview",          # preview | real
    "autosend_on_purchase": True,
    "autosend_on_stock": True,
    "autosend_stock_threshold": 4,
    "autosend_on_price": True,
    # [2026-07-19 Phase 1B M3-1] 역마진 가드 최소 마진 — **율(%)이 아니라 금액(원)**.
    # 기본 0 = "1원이라도 남으면 올린다" → 오늘 동작과 완전히 동일(도입 영향 0).
    "min_margin_amount": 0,
}


class GlobalSettings(Base):
    """단일 row 테이블. id=1 고정."""
    __tablename__ = "global_settings"

    id = Column(Integer, primary_key=True, default=1)

    boxhero_purchase_price_default = Column(Integer, default=95000, nullable=False)
    boxhero_ss_price_default = Column(Integer, default=115900, nullable=False)
    boxhero_coupang_price_default = Column(Integer, default=128900, nullable=False)
    external_ss_price_default = Column(Integer, default=128900, nullable=False)
    external_coupang_price_default = Column(Integer, default=128900, nullable=False)
    coupang_winner_premium_price = Column(Integer, default=149000, nullable=False)
    guardrail_lower = Column(Integer, default=99000, nullable=False)
    guardrail_upper = Column(Integer, default=120000, nullable=False)
    delivery_fee = Column(Integer, default=3000, nullable=False)
    ss_fee_rate = Column(Float, default=0.06, nullable=False)
    coupang_fee_rate = Column(Float, default=0.1155, nullable=False)
    external_ss_margin_mode = Column(String(16), default="rate", nullable=False)
    external_ss_margin_value = Column(Float, default=0.0945, nullable=False)
    external_coupang_margin_mode = Column(String(16), default="rate", nullable=False)
    external_coupang_margin_value = Column(Float, default=0.1242, nullable=False)
    rounding_unit = Column(Integer, default=100, nullable=False)
    crawl_interval_hours = Column(Integer, default=6, nullable=False)
    dryrun_warnings_threshold = Column(Integer, default=5, nullable=False)
    dryrun_avg_price_change_pct = Column(Float, default=30.0, nullable=False)
    # [자동화 설정]
    crawl_auto_enabled = Column(Boolean, default=False, nullable=False)
    crawl_interval_minutes = Column(Integer, default=0, nullable=False)
    autosend_mode = Column(String(8), default="preview", nullable=False)
    autosend_on_purchase = Column(Boolean, default=True, nullable=False)
    autosend_on_stock = Column(Boolean, default=True, nullable=False)
    autosend_stock_threshold = Column(Integer, default=4, nullable=False)
    autosend_on_price = Column(Boolean, default=True, nullable=False)
    # [역마진 가드 — Phase 1B M3-1]
    # 마진율(%)이 아니라 마진금액(원)이 기준이다(사용자 확정). 이 값 미만이면
    # 업로드하지 않고 '판매중지 후보'로 표시한다. 전역 1개로 시작 —
    # 마켓별/상품별 예외가 필요해지면 그때 분리한다(지금 나누면 같은 숫자가
    # 여러 곳에 복제돼 한 곳만 고치는 사고가 난다).
    # ※ 기존 테이블에는 create_all 이 컬럼을 못 붙인다 →
    #   shared/db.py::_apply_lightweight_migrations() 에 ADD COLUMN 등록 필수.
    min_margin_amount = Column(Integer, default=0, nullable=False)

    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {col.name: getattr(self, col.name)
                for col in self.__table__.columns
                if col.name not in ("id", "updated_at")}


def get_or_init(session) -> GlobalSettings:
    """싱글톤 row 가져오기. 없으면 default로 생성."""
    s = session.get(GlobalSettings, 1)
    if s is None:
        s = GlobalSettings(id=1, **_DEFAULTS)
        session.add(s)
    return s


def get_settings(session) -> GlobalSettings | None:
    return session.get(GlobalSettings, 1)


def save_settings(session) -> None:
    """이미 변경된 객체를 flush. session.commit은 호출자가."""
    session.flush()


# ── 계정(API)별 업로드 속도 (P4b) = 업로드 속도 정본 ─────────────────────────
# (구 P4 마켓 per_minute 정책 MarketUploadPolicy 는 폐기 — 이 계정 단위로 흡수.
#  마켓 처리량은 lemouton/uploader/throttle.py 의 market_hourly_total 파생값.)
_ACCOUNT_DEFAULT_SECONDS = 6   # 1개당 6초 = 시간당 600개


class AccountUploadPolicy(Base):
    """판매 계정(API)별 업로드 속도. account_id = market_accounts.id."""
    __tablename__ = "account_upload_policies"

    account_id = Column(Integer, ForeignKey("market_accounts.id"), primary_key=True)
    seconds_per_item = Column(Integer, default=_ACCOUNT_DEFAULT_SECONDS, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)


def _active_accounts(session):
    from lemouton.multitenancy.models import MarketAccount
    return (session.query(MarketAccount)
            .filter(MarketAccount.is_active.is_(True))
            .filter(MarketAccount.deleted_at.is_(None))
            .all())


def get_account_policies(session) -> list:
    """활성 계정별 속도 정책. 없으면 기본 시드. per_hour 파생 포함."""
    for acc in _active_accounts(session):
        if session.get(AccountUploadPolicy, acc.id) is None:
            session.add(AccountUploadPolicy(account_id=acc.id,
                        seconds_per_item=_ACCOUNT_DEFAULT_SECONDS, enabled=True))
    session.flush()
    out = []
    for acc in _active_accounts(session):
        p = session.get(AccountUploadPolicy, acc.id)
        sec = max(1, int(p.seconds_per_item))
        out.append({"account_id": acc.id, "market": acc.market,
                    "account_name": acc.account_name,
                    "seconds_per_item": sec, "enabled": p.enabled,
                    "per_hour": 3600 // sec})
    return out


def set_account_policy(session, account_id: int, *, seconds_per_item=None,
                       enabled=None) -> dict:
    """전달된 항목만 갱신. seconds ≥ 1 클램프. 호출자가 commit."""
    p = session.get(AccountUploadPolicy, account_id)
    if p is None:
        p = AccountUploadPolicy(account_id=account_id,
                                seconds_per_item=_ACCOUNT_DEFAULT_SECONDS, enabled=True)
        session.add(p)
    if seconds_per_item is not None:
        p.seconds_per_item = max(1, int(seconds_per_item))
    if enabled is not None:
        p.enabled = bool(enabled)
    session.flush()
    sec = max(1, int(p.seconds_per_item))
    return {"seconds_per_item": sec, "enabled": p.enabled, "per_hour": 3600 // sec}


# ── 자동화 설정 (크롤 자동 주기 + 판매처 자동 전송) ──────────────────────────
_AUTOMATION_KEYS = (
    "crawl_auto_enabled", "crawl_interval_hours", "crawl_interval_minutes",
    "autosend_mode", "autosend_on_purchase", "autosend_on_stock",
    "autosend_stock_threshold", "autosend_on_price",
)


def get_automation(session) -> dict:
    """자동화 설정 값 dict (팀 공유 단일 설정)."""
    s = get_or_init(session)
    return {k: getattr(s, k) for k in _AUTOMATION_KEYS}


def save_automation(session, data: dict) -> dict:
    """전달된 항목만 갱신·검증(분 0~59·음수 방지·mode 화이트리스트). 호출자가 commit."""
    s = get_or_init(session)
    if "crawl_auto_enabled" in data:
        s.crawl_auto_enabled = bool(data["crawl_auto_enabled"])
    if "crawl_interval_hours" in data:
        s.crawl_interval_hours = max(0, int(data["crawl_interval_hours"]))
    if "crawl_interval_minutes" in data:
        s.crawl_interval_minutes = max(0, min(59, int(data["crawl_interval_minutes"])))
    if "autosend_mode" in data:
        s.autosend_mode = "real" if data["autosend_mode"] == "real" else "preview"
    if "autosend_on_purchase" in data:
        s.autosend_on_purchase = bool(data["autosend_on_purchase"])
    if "autosend_on_stock" in data:
        s.autosend_on_stock = bool(data["autosend_on_stock"])
    if "autosend_stock_threshold" in data:
        s.autosend_stock_threshold = max(0, int(data["autosend_stock_threshold"]))
    if "autosend_on_price" in data:
        s.autosend_on_price = bool(data["autosend_on_price"])
    session.flush()
    return get_automation(session)


# ── 역마진 가드 (Phase 1B M3-1) ─────────────────────────────────────────────

def get_min_margin_amount(session) -> int:
    """업로드 최소 마진금액(원). 팀 공유 단일 설정.

    컬럼이 아직 없는 DB(경량 마이그레이션 전)에서도 0 으로 안전하게 떨어진다.
    """
    s = get_or_init(session)
    try:
        return int(getattr(s, "min_margin_amount", 0) or 0)
    except (TypeError, ValueError):
        return 0


def save_min_margin_amount(session, value) -> int:
    """최소 마진금액 저장. 호출자가 commit.

    잘못된 입력을 0 으로 조용히 뭉개지 않는다 — 그러면 가드가 꺼진 줄 모르고
    역마진 상품이 그대로 나간다. 숫자로 못 읽으면 ValueError 로 표면화한다.
    음수는 허용한다("최대 N원까지는 손해 봐도 올린다" 는 사용자의 유효한 선택).
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"최소 마진금액은 정수(원)여야 합니다: {value!r}")
    s = get_or_init(session)
    s.min_margin_amount = v
    session.flush()
    return v

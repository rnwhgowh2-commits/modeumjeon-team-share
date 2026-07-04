"""[B] 글로벌 설정 — 단일 row 테이블."""
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime
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


# ── 마켓별 업로드 속도 정책 (P4) ────────────────────────────────────────────
_MARKET_DEFAULTS = {
    "coupang": {"per_minute": 10, "enabled": True},
    "smartstore": {"per_minute": 10, "enabled": True},
}


class MarketUploadPolicy(Base):
    """마켓별 업로드 속도 정책. market = 마켓 키(coupang/smartstore …)."""
    __tablename__ = "market_upload_policies"

    market = Column(String(32), primary_key=True)
    per_minute = Column(Integer, default=10, nullable=False)  # 분당 상한
    enabled = Column(Boolean, default=True, nullable=False)


def get_market_policies(session) -> dict:
    """마켓별 정책 dict. 알려진 마켓(coupang/smartstore)은 없으면 기본값 시드."""
    for mk, d in _MARKET_DEFAULTS.items():
        row = session.get(MarketUploadPolicy, mk)
        if row is None:
            session.add(MarketUploadPolicy(market=mk, per_minute=d["per_minute"],
                                           enabled=d["enabled"]))
    session.flush()
    rows = session.query(MarketUploadPolicy).all()
    return {r.market: {"per_minute": r.per_minute, "enabled": r.enabled} for r in rows}


def set_market_policy(session, market: str, *, per_minute: int | None = None,
                      enabled: bool | None = None) -> dict:
    """전달된 항목만 갱신. per_minute 음수 → 0. 호출자가 commit."""
    row = session.get(MarketUploadPolicy, market)
    if row is None:
        d = _MARKET_DEFAULTS.get(market, {"per_minute": 10, "enabled": True})
        row = MarketUploadPolicy(market=market, per_minute=d["per_minute"],
                                 enabled=d["enabled"])
        session.add(row)
    if per_minute is not None:
        row.per_minute = max(0, int(per_minute))
    if enabled is not None:
        row.enabled = bool(enabled)
    session.flush()
    return {"per_minute": row.per_minute, "enabled": row.enabled}


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

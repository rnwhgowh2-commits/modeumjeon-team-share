"""[B] 글로벌 설정 — 단일 row 테이블."""
from sqlalchemy import Column, Integer, Float, String, DateTime
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

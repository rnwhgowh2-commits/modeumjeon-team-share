"""market_registrations CRUD."""
from sqlalchemy.orm import Session
from .models import MarketRegistration


def upsert_registration(session: Session, *,
                        canonical_sku: str, market: str, **kwargs) -> MarketRegistration:
    existing = session.get(MarketRegistration, (canonical_sku, market))
    if existing is None:
        r = MarketRegistration(canonical_sku=canonical_sku, market=market, **kwargs)
        session.add(r)
        return r
    for k, v in kwargs.items():
        if v is not None:
            setattr(existing, k, v)
    return existing


def get_registration(session: Session, canonical_sku: str, market: str
                     ) -> MarketRegistration | None:
    return session.get(MarketRegistration, (canonical_sku, market))


def list_by_market(session: Session, market: str) -> list[MarketRegistration]:
    return list(session.query(MarketRegistration).filter_by(market=market).all())

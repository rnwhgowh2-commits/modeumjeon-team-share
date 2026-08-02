# -*- coding: utf-8 -*-
"""마켓별 수수료 기준 — **코드가 아니라 데이터.**

사장님 확정 2026-08-02:
  「11번가는 기본 11% 설정하고, 1년 이내 계정 체크버튼 만들어줘. 체크하면 8% 되도록.
   다만, 우리 마켓 정책 언제든 변경될 수 있으니 기본값과 체크하면 X% 이런것들도
   수기로 조정가능하도록 해줘.」

→ 요율을 코드에 박아 두면 마켓이 정책을 바꿀 때마다 개발자를 불러야 한다.
  표를 DB 로 옮기고 화면에서 고치게 한다. 코드의 값은 **처음 한 번 심는 씨앗**일 뿐이다.

마켓마다 담는 것:
  · `base_pct`   기본 요율(%)
  · `alt_label`  조건 이름 — 비어 있으면 그 마켓엔 체크박스가 안 뜬다
  · `alt_pct`    그 조건일 때의 요율(%)

🔴 **계산이 쓰는 값은 언제나 정책에 저장된 숫자 하나다.** 여기 표는 화면 칸을
  채워 주는 「기준」일 뿐 — 체크박스는 칸의 숫자를 바꿔 놓을 뿐, 계산 때 다시
  판단하지 않는다. 그래야 사장님이 화면에서 본 숫자가 그대로 쓰인다.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import Column, Float, String

from shared.db import Base

_log = logging.getLogger(__name__)


class MarketFeeDefault(Base):
    """마켓 하나의 수수료 기준. 화면에서 고친다."""
    __tablename__ = 'market_fee_defaults'

    market = Column(String(20), primary_key=True)
    base_pct = Column(Float, nullable=False)
    alt_label = Column(String(60))          # 비면 체크박스 없음
    alt_pct = Column(Float)


#: 처음 한 번 심는 씨앗 — 사장님이 불러준 값 (2026-08-02).
#:   🔴 여기 고쳐도 **이미 심긴 행은 안 바뀐다.** 화면에서 고치는 것이 정상 경로다.
SEED: dict[str, dict] = {
    'smartstore': {'base_pct': 6.0,   'alt_label': '', 'alt_pct': None},
    'coupang':    {'base_pct': 11.55, 'alt_label': '', 'alt_pct': None},
    'lotteon':    {'base_pct': 18.0,  'alt_label': '', 'alt_pct': None},
    # 1년 지나면 11% 로 오른다 — 기본을 11 로 두고, 신규 계정만 체크해서 8 로 내린다.
    'eleven11':   {'base_pct': 11.0,  'alt_label': '1년 이내 계정', 'alt_pct': 8.0},
    'auction':    {'base_pct': 15.0,  'alt_label': '', 'alt_pct': None},
    'gmarket':    {'base_pct': 15.0,  'alt_label': '', 'alt_pct': None},
}

#: 마켓마다 「제휴 2% 포함」 같은 사실을 덧붙인다(요율이 아니라 설명이라 표에 안 넣는다).
NOTES: dict[str, str] = {
    'lotteon': '제휴 2% 포함된 값입니다',
    'auction': '제휴 2% 포함된 값입니다',
    'gmarket': '제휴 2% 포함된 값입니다',
}

# 매 페이지 렌더·매 옵션 계산에서 불리므로 캐시한다. 저장하면 바로 비운다.
_cache: dict | None = None
_lock = threading.Lock()


def invalidate() -> None:
    """저장 뒤 호출 — 다음 조회에서 다시 읽는다."""
    global _cache
    with _lock:
        _cache = None


def _seed_if_missing(session) -> None:
    have = {m for (m,) in session.query(MarketFeeDefault.market).all()}
    added = 0
    for market, row in SEED.items():
        if market in have:
            continue
        session.add(MarketFeeDefault(market=market, **row))
        added += 1
    if added:
        session.flush()
        _log.info('[fee-defaults] 씨앗 %s개 심음', added)


def load(session=None) -> dict:
    """{market: {base_pct, alt_label, alt_pct}} — 없으면 씨앗을 심고 돌려준다.

    session 이 없으면 스스로 연다(계산 경로가 세션을 안 들고 다닌다).
    🔴 읽다 실패해도 계산이 멈추면 안 된다 — 그때는 코드의 씨앗을 그대로 쓴다.
    """
    global _cache
    if _cache is not None:
        return _cache
    own = session is None
    try:
        if own:
            from shared.db import SessionLocal
            session = SessionLocal()
        _seed_if_missing(session)
        out = {r.market: {'base_pct': float(r.base_pct),
                          'alt_label': r.alt_label or '',
                          'alt_pct': None if r.alt_pct is None else float(r.alt_pct)}
               for r in session.query(MarketFeeDefault).all()}
        if own:
            session.commit()
    except Exception:                                    # noqa: BLE001
        _log.exception('[fee-defaults] 조회 실패 — 코드 씨앗으로 계산을 이어간다')
        if own and session is not None:
            session.rollback()
        return {m: dict(v) for m, v in SEED.items()}
    finally:
        if own and session is not None:
            session.close()
    # 표에 없는 마켓(나중에 추가된 것)은 씨앗으로 메운다
    for m, v in SEED.items():
        out.setdefault(m, dict(v))
    with _lock:
        _cache = out
    return out


def pretty(pct):
    """화면 표기 — 6.0 → 6 · 11.55 → 11.55.

    「6.0%」로 보이면 소수 자리가 뜻이 있는 값처럼 읽힌다. 진짜 소수(11.55)는 남긴다.
    """
    if pct is None:
        return None
    f = float(pct)
    return int(f) if f.is_integer() else round(f, 4)


def base_pct(market: str) -> float | None:
    """그 마켓 기본 요율(%). 모르는 마켓이면 None."""
    return (load().get(market) or {}).get('base_pct')


def save(session, market: str, *, base_pct: float,
         alt_label: str = '', alt_pct=None) -> dict:
    """한 마켓의 기준을 고친다.

    🔴 기본 요율에 0 이나 음수를 넣지 못하게 막는다 — 수수료 0% 로 계산되면
      판매가가 실제보다 싸게 나가 그대로 손해가 된다. 100 이상도 막는다
      (수수료 + 마진이 100% 를 넘으면 성립하는 판매가가 없다).
    """
    if market not in SEED:
        raise ValueError(f'모르는 마켓이에요: {market}')
    if not isinstance(base_pct, (int, float)) or isinstance(base_pct, bool):
        raise ValueError('기본 요율은 숫자여야 해요')
    if not (0 < float(base_pct) < 100):
        raise ValueError('기본 요율은 0 보다 크고 100 보다 작아야 해요')
    label = (alt_label or '').strip()
    if label:
        if alt_pct is None or isinstance(alt_pct, bool) or \
                not isinstance(alt_pct, (int, float)) or not (0 < float(alt_pct) < 100):
            raise ValueError(f'「{label}」 일 때의 요율을 0~100 사이로 넣어 주세요')
        alt = float(alt_pct)
    else:
        alt = None                       # 조건 이름이 없으면 조건 요율도 지운다

    row = session.get(MarketFeeDefault, market)
    if row is None:
        row = MarketFeeDefault(market=market, base_pct=float(base_pct))
        session.add(row)
    row.base_pct = float(base_pct)
    row.alt_label = label
    row.alt_pct = alt
    session.flush()
    invalidate()
    return {'market': market, 'base_pct': row.base_pct,
            'alt_label': row.alt_label, 'alt_pct': row.alt_pct}

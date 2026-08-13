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

#: 가격비교(제휴) 2% 가 **기본 요율에 이미 들어 있나** — True / False / None(모름).
#:
#: 🔴 [2026-08-13] 사장님 「우리는 항상 켠다」. 그래서 정책의 「가격비교 수수료 가산」
#:   칸(기본 2%)을 계산에 **또 더하면 이중 계상**이 된다 — 수수료가 2%p 과대라
#:   판매가가 그만큼 비싸게 나가고, 팔리지 않는 손해가 난다.
#:
#: · True  이미 포함 → 더하지 않는다 (위 NOTES 와 같은 사실. 표가 원천이다)
#: · False 그 마켓엔 개념 자체가 없다 (쿠팡 등록 API 에 칸이 없다)
#: · None  **모른다** — 근거 있는 문서를 못 찾았다. 지어내지 않는다.
#:
#: 🔴 11번가 11%(1년 이내 8%)에 가격비교 몫이 포함인지 확인된 문서가 없다.
#:   정해지면 여기 True/False 를 적는 게 아니라 **요율 숫자 자체를 고친다** —
#:   「계산이 쓰는 값은 언제나 정책에 저장된 숫자 하나」(이 파일 맨 위 원칙).
AFFILIATE_IN_BASE: dict[str, bool | None] = {
    'smartstore': True,    # 6% = 결제 + 매출연동 항목 합 — 연동 몫이 이미 들어 있다
    'coupang': False,      # 등록 API 에 가격비교 개념 자체가 없다(사장님 엑셀도 X)
    'lotteon': True,
    'eleven11': None,      # 🔴 모름 — 사장님 확인 필요
    'auction': True,
    'gmarket': True,
}


def affiliate_note(market: str) -> str:
    """가격비교 2% 를 이 마켓에서 더해도 되나 — **사람 말로** 답한다.

    🔴 조용히 True/False 만 돌려주면 화면이 이유를 못 보여 준다.
      「왜 안 더하나」를 사장님이 읽을 수 있어야 한다.
    """
    got = AFFILIATE_IN_BASE.get(market)
    if got is True:
        return ('이 마켓 기본 수수료율에 가격비교(제휴) 2% 가 **이미 포함**되어 '
                '있습니다 — 여기서 또 더하면 이중으로 빠집니다.')
    if got is False:
        return '이 마켓은 가격비교 노출이라는 개념 자체가 없어 아무 일도 안 합니다.'
    return ('이 마켓 요율에 가격비교 2% 가 포함인지 **아직 확인하지 못했습니다** — '
            '확인되면 수수료율 숫자 자체를 고칩니다(여기서 따로 더하지 않습니다).')

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

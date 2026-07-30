"""shared/display_no.py — 표시번호(사람이 보는 번호) 단일 진실 원천.

사장님 확정 (2026-07-30):

    [접두] + [생성일 8자리] + '-' + [순번 6자리]

    M      모음전 상품(모상품번호)      M20260730-000001
    U      원본 매트릭스 옵션           U20260730-000001
    P      파생 매트릭스 옵션           P20260730-000001
    영문2  소싱처 — 상품은 순번 앞자리 1, 옵션은 0
             MU20260730-100001  무신사 **상품**
             MU20260730-000001  무신사 **옵션**
    DS/DU  대량등록(상품셋트 / 단위상품) — 자리만 예약. 접두가 D 로 시작하면 대량등록.

🔴 개별 옵션번호는 기존 `canonical_sku`(SKU-XXXXXXXX)를 그대로 쓴다.
   마켓 전송·크롤·주문매칭이 그 열쇠로 돌고 **252개 파일 1,715곳**에서 참조한다.
   여기서 만드는 표시번호는 그 옆에 새로 붙이는 칸이지 **열쇠가 아니다**.

🔴 이 모듈을 거치지 않고 번호를 직접 만들지 말 것.
   (기존 SKU·바코드·품번 규칙은 shared/sku_format.py — 그쪽도 같은 원칙)

순번은 `display_no_seq` 한 행을 잠그고 예약한다. 워커가 3개라 max()+1 로 뽑으면
같은 번호가 두 번 난다.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import Column, Integer, String
from sqlalchemy.exc import IntegrityError

from shared.db import Base

# ── 소싱처 접두 (사장님 확정) ───────────────────────────────────────────────
PREFIX_BY_SITE: dict[str, str] = {
    'lemouton':    'LE',   # 르무통 공홈
    'musinsa':     'MU',   # 무신사
    'ssf':         'SF',   # SSF샵
    'lotteimall':  'LI',   # 롯데아이몰
    'lotteon':     'LO',   # 롯데온
    'ssg':         'SG',   # SSG
    'hmall':       'HM',   # H몰(현대)
    'ss_lemouton': 'SS',   # 스마트스토어 르무통
}

# 계층 접두
PREFIX_BUNDLE_PRODUCT = 'M'   # 모음전 상품(모상품)
PREFIX_MATRIX_ORIGIN  = 'U'   # 원본 매트릭스 옵션 (O 는 숫자 0 과 헷갈려 U 로 확정)
PREFIX_MATRIX_DERIVED = 'P'   # 파생 매트릭스 옵션
PREFIX_BULK_SET       = 'DS'  # 대량등록 상품셋트
PREFIX_BULK_UNIT      = 'DU'  # 대량등록 단위상품

# 순번 앞자리로 상품/옵션을 가른다 — 같은 소싱처 접두를 공유하기 때문.
BAND_OPTION = 0
BAND_PRODUCT = 1
_BAND_SIZE = 100_000          # 한 구간 최대 99,999개

DISPLAY_NO_RE = re.compile(r'^[A-Z]{1,2}\d{8}-\d{6}$')


def prefix_for_site(site: str | None) -> str | None:
    """소싱처 site 키 → 영문 2자 접두. 모르는 소싱처면 None(번호 안 붙임)."""
    if not site:
        return None
    return PREFIX_BY_SITE.get(str(site).strip())


def format_no(prefix: str, seq: int, *, band: int = 0, on: date | None = None) -> str:
    """번호 1개 조립. seq 는 1부터. band 가 순번 앞자리가 된다.

    format_no('M', 1)                       → 'M20260730-000001'
    format_no('MU', 1, band=BAND_PRODUCT)   → 'MU20260730-100001'
    """
    if seq < 1 or seq >= _BAND_SIZE:
        raise ValueError(
            f'순번이 범위를 벗어났다: {seq} (1~{_BAND_SIZE - 1}). '
            f'자리수를 늘려야 한다 — 임의로 잘라 쓰면 번호가 겹친다.')
    ymd = (on or date.today()).strftime('%Y%m%d')
    return f'{prefix}{ymd}-{band * _BAND_SIZE + seq:06d}'


def is_valid(s: str | None) -> bool:
    return bool(s) and bool(DISPLAY_NO_RE.match(s))


def is_bulk(s: str | None) -> bool:
    """대량등록 번호인가 — 접두가 D 로 시작한다."""
    return bool(s) and s.startswith('D')


# ── 순번 예약 ──────────────────────────────────────────────────────────────

class DisplaySeq(Base):
    """표시번호 순번 보관. scope 1행을 잠그고 예약해 워커 간 중복을 막는다."""
    __tablename__ = 'display_no_seq'

    scope = Column(String(16), primary_key=True)      # 'M' · 'U' · 'MU:1' · 'MU:0'
    last_seq = Column(Integer, nullable=False, default=0)


def _scope(prefix: str, band: int | None) -> str:
    return prefix if band is None else f'{prefix}:{band}'


def reserve(session, prefix: str, *, band: int | None = None, count: int = 1) -> int:
    """순번 count 개를 예약하고 **첫 번호**를 돌려준다.

    같은 행을 잠그므로 워커가 여럿이어도 겹치지 않는다.
    커밋은 호출한 쪽 책임 — 예약과 실제 부여가 한 트랜잭션이어야 번호가 새지 않는다.
    """
    if count < 1:
        raise ValueError('count 는 1 이상')
    scope = _scope(prefix, band)
    row = session.get(DisplaySeq, scope, with_for_update=True)
    if row is None:
        try:
            with session.begin_nested():
                session.add(DisplaySeq(scope=scope, last_seq=0))
        except IntegrityError:
            pass                                   # 다른 워커가 먼저 만들었다
        row = session.get(DisplaySeq, scope, with_for_update=True)
    start = (row.last_seq or 0) + 1
    row.last_seq = (row.last_seq or 0) + count
    session.flush()
    return start


def issue(session, prefix: str, *, band: int | None = None,
          count: int = 1, on: date | None = None) -> list[str]:
    """번호 count 개를 발급한다. 순번 예약 + 조립을 한 번에."""
    start = reserve(session, prefix, band=band, count=count)
    b = 0 if band is None else band
    return [format_no(prefix, start + i, band=b, on=on) for i in range(count)]


def issue_one(session, prefix: str, *, band: int | None = None,
              on: date | None = None) -> str:
    return issue(session, prefix, band=band, count=1, on=on)[0]

# -*- coding: utf-8 -*-
"""쿠팡 브랜드 판별 창구 — 캐시(`BrandRegistryCache`)를 낀 조회 한 곳.

왜 캐시를 끼우나: 쿠팡 클라이언트는 초당 5요청 토큰버킷이다
(`shared/platforms/coupang/client.py`). 대량등록에서 브랜드마다 동기 조회하면 등록
전체가 그 속도에 묶인다. 브랜드↔brandId·소명여부는 자주 바뀌지 않으므로 표에 쌓는다.

🔴 이 파일이 지키는 것
  ① **「모른다」와 「아니다」를 가른다.** `uid_required=None` 은 판정 불가이지
     「소명 필요 없음(False)」이 아니다. 캐시에서 읽을 때도 None 을 그대로 내린다.
  ② **판정만 캐시에 굳힌다.** 쿠팡이 「그런 브랜드 없다」고 답한 것은 판정이라 남기지만,
     401·네트워크 실패·code!=SUCCESS 는 **덮지 않는다**. 일시적 장애를 matched=False 로
     굳히면 그 브랜드가 max_age_days 동안 「판정 불가」로 얼어붙는다.
  ③ **지어내지 않는다.** 캐시에도 없고 물어볼 수도 없으면 `None` 을 돌려준다.
     그럴듯한 기본값(자유판매·brandId 빈 문자열)으로 때우지 않는다.

캐시 키는 **손대지 않은 브랜드 문자열**(양끝 공백만 제거)이다. 비교 키(normalize)로
합치지 않는 이유 — 「A B」와 「AB」가 정말 다른 브랜드일 수 있어서다. 쿠팡 쪽 표기 차이를
흡수하는 정규화는 `brands.search_brand` 의 **정확일치 비교**에서만 한다.

커밋은 **호출자 몫**이다. 여기서 commit 하면 호출자 트랜잭션 한가운데서 남의 미완성
변경까지 확정된다(`prepare_compile_draft` 처럼 한 세션으로 여러 일을 하는 자리가 있다).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError

from lemouton.policy.models import BrandRegistryCache
from shared.platforms.coupang import brands as BR


logger = logging.getLogger(__name__)


#: 기본 만료. 브랜드 소명 정책은 마켓이 계속 늘리므로 무기한 캐시는 위험하다.
DEFAULT_MAX_AGE_DAYS = 30


def _utcnow():
    return datetime.now(timezone.utc)


def _as_utc(dt):
    """DB 가 돌려준 시각을 UTC aware 로 맞춘다.

    🔴 SQLite·PostgreSQL 둘 다 `DateTime`(timezone 없음) 칸을 **naive** 로 돌려준다.
      `_utcnow()`(aware)와 그냥 빼면 TypeError 로 터진다 — 우리가 쓰는 값은 전부
      `models._utcnow` 가 넣은 UTC 라 naive 면 UTC 로 읽는다.
    """
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_fresh(row, max_age_days) -> bool:
    if row is None:
        return False
    if max_age_days is None:
        return True                      # 만료 없음 (호출자가 명시적으로 끈 경우)
    ts = _as_utc(getattr(row, 'checked_at', None))
    if ts is None:
        return False                     # 언제 판정했는지 모르면 신선하다고 못 한다
    return (_utcnow() - ts) <= timedelta(days=float(max_age_days))


def _from_row(row, *, stale: bool) -> dict:
    """캐시 행을 반환 모양으로.

    🔴 `allowed_uid_types` 는 **None(모름)** 이다 — 표에 그 칸이 없다. `[]`(=허용 타입
      없음)로 내리면 「모름」이 판정처럼 읽힌다. 필요하면 client 를 주입해 다시 묻는다.
    """
    return {
        'brand': row.brand,
        'brand_id': row.coupang_brand_id or None,
        'uid_required': row.uid_required,        # None 그대로 — False 로 바꾸지 않는다
        'allowed_uid_types': None,
        'matched': bool(row.matched),
        'checked_at': row.checked_at,
        'from_cache': True,
        'stale': stale,
    }


def _upsert(session, row, name: str, got: dict):
    """판별 결과를 캐시에 쓴다. 없으면 만들고, 있으면 갱신한다.

    🔴 `brand` 는 UNIQUE 인데 등록은 배경 스레드로 돈다
      (`webapp/routes/bulk/drafts.py` 의 등록 잡). 같은 브랜드를 두 스레드가 동시에
      처음 조회하면 나중 쪽 flush 가 UNIQUE 로 터지고, 잡히지 않으면 세션이 abort 돼
      **그 상품 등록이 통째로 죽는다.** savepoint 로 격리하고 먼저 들어온 행을 갱신한다
      (`lemouton/sources/service.py` 의 옵션 upsert 와 같은 방식).
    """
    if row is None:
        row = BrandRegistryCache(brand=name)
        try:
            # 🔴 `add` 는 savepoint **안**에서 한다. 밖에서 add 하면 `begin_nested()` 가
            #   savepoint 를 걸기 **전에** 그 pending INSERT 를 흘려 보내서, UNIQUE 로
            #   터졌을 때 바깥 트랜잭션이 통째로 죽는다(savepoint 가 아무것도 못 막는다).
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            logger.info("브랜드 캐시 동시 삽입 — 먼저 들어온 행을 갱신한다 brand=%s", name)
            # savepoint 롤백이 pending 객체를 이미 떼어내는 경우가 있다 — 남아 있을 때만
            #   떼어낸다(안 떼면 다음 flush 가 같은 INSERT 를 또 시도한다).
            if row in session:
                session.expunge(row)
            row = (session.query(BrandRegistryCache)
                   .filter(BrandRegistryCache.brand == name)
                   .one())

    row.coupang_brand_id = got.get('brand_id')
    row.uid_required = got.get('uid_required')   # None(모름) 을 그대로 저장한다
    row.matched = bool(got.get('matched'))
    row.checked_at = _utcnow()
    session.flush()
    return row


def lookup(
    session,
    brand,
    client: Optional[object] = None,
    max_age_days: Optional[int] = DEFAULT_MAX_AGE_DAYS,
) -> Optional[dict]:
    """브랜드 하나의 쿠팡 판별 결과를 돌려준다.

    Args:
        session: SQLAlchemy 세션 (커밋은 호출자 몫)
        brand: 브랜드 문자열
        client: 쿠팡 클라이언트. **None 이면 API 를 부르지 않고 캐시만 본다.**
        max_age_days: 이보다 오래된 캐시는 다시 묻는다. None 이면 만료 없음.

    Returns:
        dict 또는 **None**(캐시에도 없고 물어보지도 못했다 — 지어내지 않는다)
        {
          'brand', 'brand_id', 'uid_required'(🔴 None=모름), 'allowed_uid_types',
          'matched', 'checked_at', 'from_cache', 'stale'
        }
    """
    name = str(brand or '').strip()
    if not name:
        # 브랜드가 없으면 판정 대상 자체가 없다. 빈 이름으로 쿠팡을 부르면 400 이다.
        return None

    row = (session.query(BrandRegistryCache)
           .filter(BrandRegistryCache.brand == name)
           .one_or_none())

    if _is_fresh(row, max_age_days):
        return _from_row(row, stale=False)

    if client is None:
        # 캐시만 본다. 오래된 행은 「오래됐다」를 숨기지 않고 그대로 알린다.
        return None if row is None else _from_row(row, stale=True)

    got = BR.search_brand(name, client=client)

    if not got.get('answered'):
        # 🔴 쿠팡이 답을 못 줬다 — 캐시를 덮지 않는다.
        logger.warning("브랜드 판별 실패(답 없음) brand=%s — 캐시를 덮지 않는다", name)
        return None if row is None else _from_row(row, stale=True)

    row = _upsert(session, row, name, got)
    return {
        'brand': name,
        'brand_id': got.get('brand_id'),
        'uid_required': got.get('uid_required'),
        'allowed_uid_types': got.get('allowed_uid_types'),
        'matched': bool(got.get('matched')),
        'checked_at': row.checked_at,
        'from_cache': False,
        'stale': False,
    }

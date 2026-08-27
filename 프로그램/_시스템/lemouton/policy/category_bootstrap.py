# -*- coding: utf-8 -*-
"""정규 카테고리에 **씨앗 붓기** + 기존 매핑 옮기기 (2026-08-25 Phase 7-2a).

■ 씨앗은 어디서 오나 — 마켓 우선순위 캐스케이드 (삼바와 같은 방식)
  정규 카테고리 트리를 맨손으로 만들 수는 없다. **가장 정돈된 마켓 트리를 바닥으로
  깔고**, 그 다음 마켓에서 **없는 가지만** 더한다(롱테일).

      롯데온 → 쿠팡 → 11번가 → 스마트스토어 → G마켓 → 옥션

  (삼바 순서에서 우리에게 없는 롯데아이몰만 뺐다.)

  🔴 한 번 부은 뒤에는 마켓 트리를 **실시간으로 따라가지 않는다**. 마켓이 분류를
    개편해도 이 트리는 자동으로 안 바뀐다 — 자동으로 따라가면 어제 이어 둔 상품이
    오늘 다른 분류로 조용히 옮겨 간다.

■ 기존 매핑을 잃지 않는다
  지금까지 사장님이 손으로 확정한 `CategoryMapRow`(소싱처→마켓 직접 매핑)를
  2단 구조로 옮긴다. **확정된 것만** 옮긴다 — 제안은 제안일 뿐이라 옮기면
  「사장님이 확정한 것」으로 둔갑한다.

■ 🔴 이 파일은 표를 채우기만 한다. 전송 경로는 아직 새 표를 안 본다(Phase 7-2c).
"""
from __future__ import annotations

import logging

from lemouton.policy.normalized_category import (
    MAPPED, MarketCategoryLink, NormalizedCategory, SourceCategoryLink,
)

logger = logging.getLogger(__name__)

#: 씨앗을 붓는 순서 — 앞쪽이 바닥, 뒤쪽은 없는 가지만 더한다.
#: 🔴 순서를 바꾸면 트리 모양이 통째로 달라진다. 바꾸려면 사장님 확정이 필요하다.
CASCADE = ('lotteon', 'coupang', 'eleven11', 'smartstore', 'gmarket', 'auction')


def _split(path: str) -> list:
    """'여성>원피스>미니' → ['여성', '여성>원피스', '여성>원피스>미니'] (조상 포함)."""
    조각 = [p.strip() for p in str(path or '').split('>') if p.strip()]
    return ['>'.join(조각[:i + 1]) for i in range(len(조각))]


def ensure_path(session, path: str, *, source_market=None, _cache=None):
    """그 경로의 정규 카테고리를 만들어(또는 찾아) 돌려준다. 조상도 같이 만든다.

    🔴 이미 있으면 **안 건드린다** — 나중에 부은 마켓이 먼저 부은 마켓의 유래를
      덮으면 「이 가지가 어디서 왔나」를 못 쫓는다.

    Args:
        _cache: `{경로: row}` 를 미리 채워 넘기면 **조상마다 SELECT 를 안 한다.**
            🔴 마켓 트리는 수만 줄일 수 있다. 줄마다 조상 깊이만큼 SELECT 를 날리면
              씨앗 붓기 한 번이 몇 분씩 걸려 화면이 멎는다(2026-08-26에 고침).
    """
    마지막 = None
    부모 = None
    for i, 조상 in enumerate(_split(path)):
        row = _cache.get(조상) if _cache is not None else None
        if row is None:
            row = session.query(NormalizedCategory).filter_by(path=조상).first()
        if row is None:
            row = NormalizedCategory(
                path=조상, parent_id=(부모.id if 부모 else None), depth=i,
                source_market=source_market)
            session.add(row)
            session.flush()
        if _cache is not None:
            _cache[조상] = row
        부모 = row
        마지막 = row
    return 마지막


def bootstrap(session, *, markets=None, limit_per_market=None) -> dict:
    """마켓 트리에서 정규 카테고리 씨앗을 붓는다. `{market: 새로 만든 칸 수}`.

    🔴 **멱등하다** — 두 번 불러도 같은 경로를 두 번 만들지 않는다.
    """
    from lemouton.registration.models import MarketCategory

    # 🔴 있는 경로를 **한 번에** 읽어 둔다. 예전에는 줄마다 전체 개수를 두 번 세고
    #   조상마다 SELECT 를 날려서, 마켓 트리가 커지면 씨앗 붓기 한 번에 몇 분씩
    #   걸려 화면이 멎었다(2026-08-26 고침).
    캐시 = {r.path: r for r in session.query(NormalizedCategory).all()}
    결과 = {}
    for mk in (markets or CASCADE):
        q = (session.query(MarketCategory)
             .filter(MarketCategory.market == mk)
             .order_by(MarketCategory.depth, MarketCategory.id))
        if limit_per_market:
            q = q.limit(limit_per_market)
        전 = len(캐시)
        for row in q.all():
            경로 = (row.full_path or '').strip()
            if not 경로:
                continue
            ensure_path(session, 경로, source_market=mk, _cache=캐시)
        결과[mk] = len(캐시) - 전
        logger.info('정규 카테고리 씨앗 — %s 에서 %s칸 새로 만듦', mk, 결과[mk])
    session.flush()
    return 결과


def migrate_confirmed(session) -> dict:
    """확정된 `CategoryMapRow` 를 2단 구조로 옮긴다.

    🔴 **확정된 것만** 옮긴다. 제안까지 옮기면 「사장님이 확정한 것」으로 둔갑한다.
    🔴 한 소싱처 경로는 정규 카테고리 **하나**만 가리킬 수 있다. 여러 마켓에 서로
      다르게 이어 둔 경우, `CASCADE` 에서 **앞선 마켓**의 것을 쓴다(우선순위 규칙).

    Returns:
        {'sources': 새 소싱처 연결 수, 'markets': 새 마켓 연결 수, 'skipped': 건너뜀}
    """
    from lemouton.registration.models import CategoryMapRow

    rows = (session.query(CategoryMapRow)
            .filter(CategoryMapRow.status == 'confirmed').all())
    순위 = {mk: i for i, mk in enumerate(CASCADE)}
    # 소싱처 경로마다 **우선순위가 가장 높은 마켓**의 행을 고른다.
    대표 = {}
    for r in rows:
        키 = (r.source_id, r.source_path)
        기존 = 대표.get(키)
        if 기존 is None or 순위.get(r.market, 99) < 순위.get(기존.market, 99):
            대표[키] = r

    새소싱, 새마켓, 건너뜀 = 0, 0, 0
    for (source_id, source_path), r in 대표.items():
        경로 = (r.market_cat_path or '').strip()
        if not 경로:
            # 🔴 마켓 경로를 모르면 정규 카테고리를 만들 수 없다. 지어내지 않는다.
            건너뜀 += 1
            continue
        정규 = ensure_path(session, 경로, source_market=r.market)
        있나 = (session.query(SourceCategoryLink)
                .filter_by(source_id=source_id, source_path=source_path).first())
        if 있나 is None:
            session.add(SourceCategoryLink(
                source_id=source_id, source_path=source_path,
                normalized_category_id=정규.id))
            새소싱 += 1
        elif 있나.normalized_category_id is None:
            있나.normalized_category_id = 정규.id
            새소싱 += 1

    # 마켓 연결은 **모든 확정 행**에서 거둔다 — 소싱처 대표와 무관하다.
    for r in rows:
        경로 = (r.market_cat_path or '').strip()
        if not 경로 or not (r.market_cat_code or '').strip():
            continue
        정규 = ensure_path(session, 경로, source_market=r.market)
        있나 = (session.query(MarketCategoryLink)
                .filter_by(normalized_category_id=정규.id, market=r.market).first())
        if 있나 is None:
            session.add(MarketCategoryLink(
                normalized_category_id=정규.id, market=r.market,
                market_cat_code=r.market_cat_code, market_cat_path=경로,
                status=MAPPED))
            새마켓 += 1

    session.flush()
    logger.info('기존 매핑 옮김 — 소싱처 %s · 마켓 %s · 건너뜀 %s',
                새소싱, 새마켓, 건너뜀)
    return {'sources': 새소싱, 'markets': 새마켓, 'skipped': 건너뜀}


def pending(session, *, source_id=None, limit=200) -> list:
    """보류함 — **아직 안 이은** 소싱처 카테고리들.

    🔴 별도 표가 아니다. `normalized_category_id` 가 비어 있는 행이 곧 보류함이다.
    """
    q = (session.query(SourceCategoryLink)
         .filter(SourceCategoryLink.normalized_category_id.is_(None)))
    if source_id:
        q = q.filter(SourceCategoryLink.source_id == source_id)
    return q.order_by(SourceCategoryLink.source_id,
                      SourceCategoryLink.source_path).limit(limit).all()

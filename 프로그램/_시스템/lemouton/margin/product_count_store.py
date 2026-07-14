# -*- coding: utf-8 -*-
"""계층 분석 등록수 저장/조회 — 팀 공유 단일 row.

원본(대량등록 마진계산기)은 단일 사용자 product_counts.json({경로키: 등록수}) 파일이었다.
팀 공유 앱에서는 이를 DB 한 행(ProductCountConfig, id=1)으로 승격한다: 멀티유저가 같은
등록수를 보고, 파일이 아니라 DB 에 영속한다(재배포·컨테이너 교체에도 유지). CardKeywordConfig
와 동일 패턴(시드는 불필요 — 빈 dict 시작).
"""
from typing import Optional

from lemouton.margin.models import ProductCountConfig

_CONFIG_ID = 1


def _row(session) -> Optional[ProductCountConfig]:
    return session.get(ProductCountConfig, _CONFIG_ID)


def get_counts(session) -> dict:
    """{경로키: 등록수} 전체 조회. 행 없으면 빈 dict(원본 load_product_counts 계약)."""
    row = _row(session)
    return dict(row.counts) if row and row.counts else {}


def set_count(session, key: str, count: int, delete: bool = False) -> dict:
    """경로키 하나의 등록수 저장/삭제. 갱신된 전체 dict 반환(원본 POST 계약).

    시드 삽입 경쟁: 최초 사용 시 동시 요청 둘이 모두 "행 없음"을 보고 각자 id=1 을
    INSERT 하면 하나가 PK 충돌로 500 난다. IntegrityError 를 잡아 rollback 후 이미
    생긴 행을 다시 읽어 그 위에 적용한다(멱등).
    """
    from sqlalchemy.exc import IntegrityError

    row = _row(session)
    if row is None:
        row = ProductCountConfig(id=_CONFIG_ID, counts={})
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            row = _row(session)
            if row is None:
                raise

    data = dict(row.counts or {})
    if delete:
        data.pop(key, None)
    else:
        data[key] = int(count)
    # JSON 컬럼은 in-place 변경을 감지 못하므로 새 dict 를 재대입한다.
    row.counts = data
    session.commit()
    return data

"""소싱처 카테고리 사전(source_categories) 적재 — 크롤이 본 경로를 축적한다.

크롤 한 번에 상품 하나의 경로가 하나 들어온다. 처음 보는 경로면 행을 만들고,
이미 있으면 product_count 만 올린다(그 경로로 몇 개나 크롤됐는지가 맵핑 우선순위 근거).
빈 경로는 저장하지 않는다 — 파싱 실패를 '카테고리 없음'으로 둔갑시키지 않기 위해서다.
"""
from __future__ import annotations

from lemouton.registration.models import SourceCategory


def normalize_path(raw):
    """'  신발 > 스니커즈 ' → '신발>스니커즈'. 빈 조각 제거. 못 쓸 값이면 ''."""
    parts = [p.strip() for p in str(raw or '').split('>')]
    return '>'.join([p for p in parts if p])


def ingest_path(session, source_id, raw_path, now):
    """반환 True=새 경로 추가 / False=기존 갱신 또는 무시. commit 은 호출자 몫."""
    path = normalize_path(raw_path)
    if not path or not source_id:
        return False
    row = (session.query(SourceCategory)
           .filter_by(source_id=str(source_id), path=path).first())
    if row is None:
        parts = path.split('>')
        session.add(SourceCategory(
            source_id=str(source_id), path=path, leaf_name=parts[-1],
            depth=len(parts), product_count=1, first_seen_at=now, last_seen_at=now))
        return True
    row.product_count = (row.product_count or 0) + 1
    row.last_seen_at = now
    return False

# -*- coding: utf-8 -*-
"""마진 분석 세션 저장/조회/정리.

결과는 gzip(JSON) 으로 DB LargeBinary 에. 원본 엑셀은 R2.
최근 KEEP_RECENT 건만 보관 — 초과분은 R2 오브젝트까지 함께 삭제한다.

R2 삭제 실패 시 정책: DB 정리를 막지 않는다.
  고아 DB 행 = 목록에 계속 남고 prune 카운트를 오염시켜 무한 증식 → 치명적.
  고아 R2 오브젝트 = 잠깐 남는 엑셀 파일(gzip 아님, 원본), 낭비일 뿐 정합성 무해.
  → 둘 중 R2 고아가 덜 나쁘다. 그러니 R2 실패는 로그만 남기고 DB 는 계속 정리한다.
"""
import gzip
import json
import logging
from typing import Optional

from lemouton.margin.models import MarginAnalysis

logger = logging.getLogger(__name__)

KEEP_RECENT = 20


def _delete_object(key: str) -> None:
    """R2 삭제 seam — 테스트에서 monkeypatch. 실패 처리는 호출부(delete/_prune)가 감싼다."""
    from shared import storage
    storage.delete_object(key)


def _delete_object_safe(key: Optional[str]) -> None:
    """R2 삭제를 감싸 — key 가 없으면 무시, 실패해도 삼키고 로그만.
    try/except 는 반드시 호출부(seam 바깥)에 둔다: 테스트가 _delete_object 자체를
    raise 하도록 monkeypatch 하므로, seam 안에 넣으면 실패 주입이 관측되지 않는다."""
    if not key:
        return
    try:
        _delete_object(key)
    except Exception:
        logger.warning("R2 오브젝트 삭제 실패 (고아 오브젝트 잔류) key=%s", key, exc_info=True)


def _pack(payload: dict) -> bytes:
    # allow_nan=False: NaN/Infinity 가 blob 에 섞이면 나중에 브라우저 JSON.parse 가
    #   조용히 깨진다. 생산자 회귀를 저장 시점에 큰 소리로 실패시킨다.
    return gzip.compress(
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _unpack(blob: bytes) -> dict:
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def save(session, *, payload, period_from, period_to,
         buy_file_key, buy_filename,
         markets_fetched, markets_failed, counts,
         created_by,
         shopmine_file_key=None, shopmine_filename=None) -> MarginAnalysis:
    """분석 1건 저장 후 KEEP_RECENT 초과분 정리. 저장된 레코드를 반환."""
    row = MarginAnalysis(
        created_by=created_by,
        period_from=period_from, period_to=period_to,
        buy_file_key=buy_file_key, buy_filename=buy_filename,
        shopmine_file_key=shopmine_file_key, shopmine_filename=shopmine_filename,
        markets_fetched=markets_fetched, markets_failed=markets_failed,
        counts=counts,
        result_blob=_pack(payload),
    )
    session.add(row)
    session.commit()
    _prune(session)
    return row


def get(session, analysis_id: int) -> Optional[MarginAnalysis]:
    """레코드 반환 — 없으면 None."""
    return session.get(MarginAnalysis, analysis_id)


def load(session, analysis_id: int) -> dict:
    """저장된 결과(payload dict) 반환 — 없으면 LookupError."""
    row = get(session, analysis_id)
    if row is None:
        raise LookupError(f"margin_analysis {analysis_id} not found")
    return _unpack(row.result_blob)


def list_recent(session, limit: int = KEEP_RECENT) -> list:
    """최근순(id DESC) 레코드 목록."""
    return (session.query(MarginAnalysis)
            .order_by(MarginAnalysis.id.desc())
            .limit(limit)
            .all())


def delete(session, analysis_id: int) -> None:
    """레코드 + R2 오브젝트(buy/shopmine) 삭제. 없으면 no-op.
    R2 삭제가 실패해도 DB 행은 지운다 (모듈 docstring 정책)."""
    row = get(session, analysis_id)
    if row is None:
        return
    _delete_object_safe(row.buy_file_key)
    _delete_object_safe(row.shopmine_file_key)
    session.delete(row)
    session.commit()


def _prune(session) -> None:
    """KEEP_RECENT 초과분(오래된 것부터) 삭제 — R2 오브젝트도 함께. save 끝에서 호출."""
    stale = (session.query(MarginAnalysis)
             .order_by(MarginAnalysis.id.desc())
             .offset(KEEP_RECENT)
             .all())
    if not stale:
        return
    for row in stale:
        _delete_object_safe(row.buy_file_key)
        _delete_object_safe(row.shopmine_file_key)
        session.delete(row)
    session.commit()

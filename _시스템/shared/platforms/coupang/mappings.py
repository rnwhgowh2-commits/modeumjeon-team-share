# -*- coding: utf-8 -*-
"""
쿠팡 매핑 DB — 소싱처↔쿠팡 옵션 매핑 저장소 (SQLite)

책임:
- (소싱처명, 소싱처상품ID, 소싱처옵션키, 쿠팡채널) → vendorItemId 매핑
- 채널(MARKETPLACE / ROCKET_GROWTH) 분리 저장
- 상태 기반 동기화 대상 조회 (auto / linked / readonly)
- 마지막 동기화 결과(last_price, last_quantity, last_synced_at) 기록

비책임:
- API 호출 (client.py / prices.py / inventory.py 에서 처리)
- 가격 계산 (price_engine.py)
- 비즈니스 검증 (validator.py)
"""
from __future__ import annotations

import sqlite3
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from shared.platforms import COUPANG


# ── 상수 ───────────────────────────────
MAPPING_STATE_AUTO     = "auto"       # 자동 생성 (신규 등록 상품)
MAPPING_STATE_LINKED   = "linked"     # 기존 상품을 수동 매핑 (동기화 대상)
MAPPING_STATE_READONLY = "readonly"   # 읽기 전용 (건들지 않음)

CHANNEL_MARKETPLACE    = "MARKETPLACE"
CHANNEL_ROCKET_GROWTH  = "ROCKET_GROWTH"


# ── 레코드 ─────────────────────────────
@dataclass
class MappingRecord:
    source_name: str
    source_product_id: str
    source_option_key: str
    coupang_seller_product_id: int
    coupang_seller_product_item_id: int
    coupang_vendor_item_id: int
    coupang_channel: str = CHANNEL_MARKETPLACE
    state: str = MAPPING_STATE_LINKED
    last_price: Optional[int] = None
    last_quantity: Optional[int] = None
    last_synced_at: Optional[str] = None
    source_purchase_price: Optional[int] = None   # 소싱처 계층1 확정매입가 (마진 계산 기준)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── 저장소 ─────────────────────────────
class MappingStore:
    """SQLite 기반 매핑 저장소."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS coupang_mappings (
        id                             INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name                    TEXT    NOT NULL,
        source_product_id              TEXT    NOT NULL,
        source_option_key              TEXT    NOT NULL,
        coupang_seller_product_id      INTEGER NOT NULL,
        coupang_seller_product_item_id INTEGER NOT NULL,
        coupang_vendor_item_id         INTEGER NOT NULL,
        coupang_channel                TEXT    NOT NULL DEFAULT 'MARKETPLACE',
        state                          TEXT    NOT NULL DEFAULT 'linked',
        last_price                     INTEGER,
        last_quantity                  INTEGER,
        last_synced_at                 TEXT,
        source_purchase_price          INTEGER,
        created_at                     TEXT    NOT NULL,
        updated_at                     TEXT    NOT NULL,
        UNIQUE(source_name, source_product_id, source_option_key, coupang_channel)
    );
    CREATE INDEX IF NOT EXISTS idx_coupang_mappings_vendor_item
        ON coupang_mappings(coupang_vendor_item_id);
    CREATE INDEX IF NOT EXISTS idx_coupang_mappings_state_channel
        ON coupang_mappings(state, coupang_channel);
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or COUPANG.get("mapping_db_path")
        if not self.db_path:
            raise ValueError("mapping_db_path 미설정 (config.COUPANG.mapping_db_path 확인)")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_schema()

    # ── 연결/스키마 ──
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(self._SCHEMA)
            # 기존 DB 에 source_purchase_price 컬럼이 없을 수 있음 → 안전하게 추가
            cur = conn.execute("PRAGMA table_info(coupang_mappings)")
            cols = {row[1] for row in cur.fetchall()}
            if "source_purchase_price" not in cols:
                conn.execute(
                    "ALTER TABLE coupang_mappings ADD COLUMN source_purchase_price INTEGER"
                )

    # ── 유틸 ──
    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MappingRecord:
        return MappingRecord(
            source_name=row["source_name"],
            source_product_id=row["source_product_id"],
            source_option_key=row["source_option_key"],
            coupang_seller_product_id=row["coupang_seller_product_id"],
            coupang_seller_product_item_id=row["coupang_seller_product_item_id"],
            coupang_vendor_item_id=row["coupang_vendor_item_id"],
            coupang_channel=row["coupang_channel"],
            state=row["state"],
            last_price=row["last_price"],
            last_quantity=row["last_quantity"],
            last_synced_at=row["last_synced_at"],
            source_purchase_price=(row["source_purchase_price"]
                                   if "source_purchase_price" in row.keys() else None),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ── CRUD ──
    def upsert(self, rec: MappingRecord) -> None:
        """UNIQUE 키 충돌 시 업데이트. 없으면 insert."""
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coupang_mappings (
                    source_name, source_product_id, source_option_key,
                    coupang_seller_product_id, coupang_seller_product_item_id,
                    coupang_vendor_item_id, coupang_channel, state,
                    last_price, last_quantity, last_synced_at,
                    source_purchase_price,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name, source_product_id, source_option_key, coupang_channel)
                DO UPDATE SET
                    coupang_seller_product_id      = excluded.coupang_seller_product_id,
                    coupang_seller_product_item_id = excluded.coupang_seller_product_item_id,
                    coupang_vendor_item_id         = excluded.coupang_vendor_item_id,
                    state                          = excluded.state,
                    last_price                     = COALESCE(excluded.last_price, last_price),
                    last_quantity                  = COALESCE(excluded.last_quantity, last_quantity),
                    last_synced_at                 = COALESCE(excluded.last_synced_at, last_synced_at),
                    source_purchase_price          = COALESCE(excluded.source_purchase_price, source_purchase_price),
                    updated_at                     = excluded.updated_at
                """,
                (
                    rec.source_name,
                    rec.source_product_id,
                    rec.source_option_key,
                    rec.coupang_seller_product_id,
                    rec.coupang_seller_product_item_id,
                    rec.coupang_vendor_item_id,
                    rec.coupang_channel,
                    rec.state,
                    rec.last_price,
                    rec.last_quantity,
                    rec.last_synced_at,
                    rec.source_purchase_price,
                    rec.created_at or now,
                    now,
                ),
            )

    def get_by_source(
        self,
        source_name: str,
        source_product_id: str,
        source_option_key: str,
        coupang_channel: str = CHANNEL_MARKETPLACE,
    ) -> Optional[MappingRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM coupang_mappings
                WHERE source_name = ? AND source_product_id = ?
                  AND source_option_key = ? AND coupang_channel = ?
                """,
                (source_name, source_product_id, source_option_key, coupang_channel),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_vendor_item_id(self, vendor_item_id: int) -> Optional[MappingRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM coupang_mappings WHERE coupang_vendor_item_id = ?",
                (vendor_item_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_active_for_sync(
        self, channel: str = CHANNEL_MARKETPLACE
    ) -> List[MappingRecord]:
        """state in (auto, linked) 인 레코드만 반환."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coupang_mappings
                WHERE coupang_channel = ?
                  AND state IN (?, ?)
                ORDER BY updated_at DESC
                """,
                (channel, MAPPING_STATE_AUTO, MAPPING_STATE_LINKED),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def record_sync_result(
        self,
        coupang_vendor_item_id: int,
        last_price: Optional[int] = None,
        last_quantity: Optional[int] = None,
    ) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE coupang_mappings
                SET last_price    = COALESCE(?, last_price),
                    last_quantity = COALESCE(?, last_quantity),
                    last_synced_at = ?,
                    updated_at    = ?
                WHERE coupang_vendor_item_id = ?
                """,
                (last_price, last_quantity, now, now, coupang_vendor_item_id),
            )

    def count(self) -> int:
        with self._connect() as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM coupang_mappings").fetchone()
        return int(n)

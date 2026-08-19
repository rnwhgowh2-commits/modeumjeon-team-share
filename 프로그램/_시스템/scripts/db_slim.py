# -*- coding: utf-8 -*-
"""DB 용량 줄이기 — 재보고, 지우고, 실제로 반납까지.

🔴 먼저 읽을 것 — `--apply` 는 지금 **쓸모가 없다** (2026-08-19 라이브 실측)

  이 도구는 「범인은 price_track_history」라는 전제로 만들어졌다. **그 전제가 틀렸다.**
  라이브에서 실제로 재보니 price_track_history 는 상위 15위 안에도 없다(1MB 미만).
  `--apply` 를 돌려도 1MB 도 못 줄이고 VACUUM FULL 배타 잠금만 걸린다. 돌리지 말 것.

  라이브 718MB 의 실제 구성 (2026-08-19):
      market_products        409 MB / 439,118 줄   ← 57%. 마켓 상품 캐시(진짜 데이터)
      crawl_deltas            78 MB / 243,434 줄
      source_price_history    47 MB / 341,835 줄   ← 진짜 가격 이력은 이 이름이다
      market_categories       32 MB /  59,048 줄
      order_rows_cache        28 MB /     838 줄   ← 줄당 34KB
      margin_analyses         20 MB /      20 줄   ← 줄당 1MB
  쉬운 것(crawl_deltas·source_price_history·margin_analyses·order_rows_cache)을 다 합쳐도
  약 173MB → 545MB. 무료 한도 500MB 를 못 넘어선다. 상품 캐시를 어디까지 남길지는
  사람이 정할 문제라 자동 정리로 풀 수 없다. **사장님 결정 = 안 건드림(Pro 유지).**

이 도구가 지금도 쓸모 있는 것
  1) 재기   : 어느 표가 얼마나 먹는지 (읽기만 — 안전). ★이것만 쓰면 된다
  2) 미리보기: 지우면 얼마나 줄지 (안 지움)
  3) 지우기 : 값이 안 바뀐 '중복 줄' 만 지운다 — 다만 대상 표가 위 이유로 무의미
  4) 반납   : 지운 공간을 실제로 돌려준다 (이걸 안 하면 표시 용량이 안 줄어든다)

  → 나중에 정말 줄여야 할 때는 `--apply` 의 대상 표부터 다시 정하고 시작할 것.

쓰는 법
    python scripts/db_slim.py            # 재기만 (안전)
    python scripts/db_slim.py --preview  # 얼마나 줄지 미리보기
    python scripts/db_slim.py --apply    # 실제로 지우고 반납
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text            # noqa: E402
from shared.db import engine           # noqa: E402

TOP_N = 15


def q(conn, sql, **kw):
    return conn.execute(text(sql), kw).fetchall()


def measure(conn):
    print('=== 표별 용량 (큰 순서) ===')
    rows = q(conn, """
        SELECT c.relname AS 표,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS 크기,
               pg_total_relation_size(c.oid) AS bytes,
               COALESCE(s.n_live_tup, 0) AS 줄수
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE c.relkind = 'r' AND n.nspname = 'public'
        ORDER BY pg_total_relation_size(c.oid) DESC
        LIMIT :n
    """, n=TOP_N)
    total = 0
    for r in rows:
        print('  %-34s %10s  %12s 줄' % (r[0], r[1], f'{r[3]:,}'))
        total += r[2]
    print('  %-34s %10.1f MB (상위 %d개 합)' % ('', total / 1024 / 1024, len(rows)))
    db = q(conn, "SELECT pg_size_pretty(pg_database_size(current_database()))")[0][0]
    print('\n  데이터베이스 전체:', db)
    return rows


def preview(conn):
    print('\n=== 가격 이력 — 지울 수 있는 중복 줄 ===')
    try:
        r = q(conn, """
            WITH ordered AS (
                SELECT id, canonical_sku, source, price, stock, captured_at,
                       LAG(price) OVER w AS prev_price,
                       LAG(stock) OVER w AS prev_stock
                FROM price_track_history
                WINDOW w AS (PARTITION BY canonical_sku, source ORDER BY captured_at)
            )
            SELECT count(*) FILTER (WHERE prev_price IS NOT DISTINCT FROM price
                                      AND prev_stock IS NOT DISTINCT FROM stock) AS 중복,
                   count(*) AS 전체
            FROM ordered
        """)[0]
    except Exception as e:
        print('  못 셈:', str(e).split('\n')[0][:110]); return None
    dup, all_ = r[0], r[1]
    keep = all_ - dup
    print('  전체 %s 줄 · 값이 안 바뀐 중복 %s 줄 (%.1f%%)' %
          (f'{all_:,}', f'{dup:,}', (dup / all_ * 100) if all_ else 0))
    print('  남길 줄(값이 바뀐 시점): %s 줄' % f'{keep:,}')
    print('  → 화면의 가격 추이 그래프는 그대로 보인다 (변화 시점만 필요하므로)')
    return dup, all_, keep


def apply(conn):
    print('\n=== 지우고 반납 ===')
    n = conn.execute(text("""
        DELETE FROM price_track_history p
        USING (
            SELECT id FROM (
                SELECT id,
                       LAG(price) OVER w AS pp,
                       LAG(stock) OVER w AS ps,
                       price, stock
                FROM price_track_history
                WINDOW w AS (PARTITION BY canonical_sku, source ORDER BY captured_at)
            ) t
            WHERE t.pp IS NOT DISTINCT FROM t.price
              AND t.ps IS NOT DISTINCT FROM t.stock
        ) d
        WHERE p.id = d.id
    """)).rowcount
    # 이 연결은 AUTOCOMMIT — 위 DELETE 는 이미 확정됐다.
    #   전에는 여기서 conn.commit() 과 'COMMIT' 을 또 걸었는데, 진행 중인 트랜잭션이
    #   없어서 경고만 나고 아무 일도 안 했다. VACUUM 은 트랜잭션 안에서 못 돌기 때문에
    #   AUTOCOMMIT 이 필수고, 그래서 커밋을 따로 걸 이유도 없다.
    print('  지운 줄: %s' % f'{n:,}')
    if n == 0:
        print('  지운 게 없어 공간 반납은 건너뛴다')
        return 0

    before = q(conn, "SELECT pg_size_pretty(pg_total_relation_size('price_track_history'))")[0][0]
    # 🔴 지우기만 하면 표시 용량이 안 줄어든다 — 실제로 반납해야 한다.
    #    VACUUM FULL 은 그 표에 **배타 잠금**을 건다(그동안 그 표를 읽는 화면은 기다린다).
    conn.exec_driver_sql('VACUUM FULL price_track_history')
    after = q(conn, "SELECT pg_size_pretty(pg_total_relation_size('price_track_history'))")[0][0]
    print('  공간 반납 완료 — price_track_history %s → %s' % (before, after))
    return n


def main():
    mode = 'measure'
    if '--apply' in sys.argv:
        mode = 'apply'
    elif '--preview' in sys.argv:
        mode = 'preview'

    with engine.connect() as conn:
        if engine.dialect.name != 'postgresql':
            print('PostgreSQL 이 아닙니다 (지금:', engine.dialect.name, ') — 라이브 DB 로 실행하세요')
            return 1
        measure(conn)
        if mode in ('preview', 'apply'):
            r = preview(conn)
            if mode == 'apply':
                if not r or r[0] == 0:
                    print('\n지울 중복이 없습니다.'); return 0
                print('\n지웁니다 …')
                # AUTOCOMMIT 은 연결을 열 때 걸어야 한다 — VACUUM 은 트랜잭션 안에서 못 돈다.
                with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as c2:
                    apply(c2)
                with engine.connect() as c3:
                    print()
                    measure(c3)
        else:
            print('\n(지우려면  --preview  로 먼저 확인하고  --apply)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

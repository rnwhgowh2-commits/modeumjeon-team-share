# -*- coding: utf-8 -*-
"""DB 용량 줄이기 — 재보고, 지우고, 실제로 반납까지.

배경 (2026-08-19)
  Supabase 무료 한도를 넘겨 프로젝트가 멈췄다.
  범인은 price_track_history — 크롤할 때마다 값이 그대로여도 한 줄씩 쌓였고
  크롤이 60초 간격 연속 모드라 하루 수천 줄이 늘었다.
  (앞으로 안 쌓이게 하는 건 bulk_crawl.save_crawl_to_track 에서 이미 고침)

이 도구가 하는 일
  1) 재기   : 어느 표가 얼마나 먹는지 (읽기만 — 안전)
  2) 미리보기: 지우면 얼마나 줄지 (안 지움)
  3) 지우기 : 값이 안 바뀐 '중복 줄' 만 지운다. 값이 바뀐 시점은 전부 남긴다
              → 화면의 가격 추이 그래프는 똑같이 보인다
  4) 반납   : 지운 공간을 실제로 돌려준다 (이걸 안 하면 표시 용량이 안 줄어든다)

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
        SELECT relname AS 표,
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
    conn.commit()
    print('  지운 줄: %s' % f'{n:,}')
    # 지우기만 하면 표시 용량이 안 줄어든다 — 실제로 반납해야 한다
    conn.execute(text('COMMIT'))
    conn.exec_driver_sql('VACUUM FULL price_track_history')
    print('  공간 반납 완료 (VACUUM FULL)')


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
                with engine.connect() as c2:
                    c2.execution_options(isolation_level='AUTOCOMMIT')
                    apply(c2)
                with engine.connect() as c3:
                    print()
                    measure(c3)
        else:
            print('\n(지우려면  --preview  로 먼저 확인하고  --apply)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

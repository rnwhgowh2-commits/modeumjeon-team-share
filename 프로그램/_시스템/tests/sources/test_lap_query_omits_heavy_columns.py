# -*- coding: utf-8 -*-
"""[TEST] 크롤 대기열·랩 계산은 상품 상세 HTML 을 읽어 오지 않는다.

왜 필요한가 (2026-08-19 실사고 — 수파베이스 조직 잠김):
  2026-07-23 에 `SourceProduct.detail_html`(상품 상세 HTML)·`images_json` 칸이 생겼다.
  그런데 대기열을 세는 `_active_products` 는 `query(SourceProduct).all()` 이라
  **모든 칸을 다 읽는다** → 폴링 한 번에 전 상품의 상세 HTML 이 통째로 DB 밖으로 나갔다.

  확장(moum-crawler)이 1분마다 `/api/crawl/queue`·`/crawl/due-bundles` 를 부르므로
  하루 1,440번. 전송량이 7/22 까지 0에 가까웠다가 **7/23 부터 하루 12~13GB** 로 뛰었고
  무료 한도(월 5GB)의 1,475%(73.8GB)를 써서 조직 전체가 잠겼다.

  🔴 줄 '개수' 로는 절대 안 잡힌다 — 대상은 85건뿐이었다. 터진 건 **줄 크기**다.

이 시험이 지키는 것:
  랩·대기열 계산 경로에서 나가는 SELECT 에 무거운 칸이 실리지 않는다.
  (칸을 지우는 게 아니라 '이 경로에선 안 읽는다' — 필요한 곳에선 그대로 읽힌다)
"""
from sqlalchemy import event

from lemouton.sources.crawl_schedule import (
    lap_progress, next_lap_products, weighted_due_products,
)
from lemouton.sources.models import SourceProduct
import lemouton.sourcing.models as M

# 이 경로가 절대 끌고 오면 안 되는 칸들 — 전부 Text(길이 제한 없음).
HEAVY = ('detail_html', 'images_json', 'last_error_msg',
         'auto_card_discount_json', 'dynamic_benefits_json')


def _seed(db):
    """랩 대상 = 모음전에 걸린 URL 만 → BundleSourceUrl 로 연결해서 심는다."""
    sp = SourceProduct(site='musinsa', url='https://x/a', last_fetched_at=None)
    sp.detail_html = '<div>' + ('상세' * 20000) + '</div>'   # 실제로 무거운 값
    sp.images_json = '["https://x/1.jpg"]'
    db.add(sp)
    db.add(M.BundleSourceUrl(model_code='HEAVY-1', source_key='musinsa',
                             url='https://x/a', sort_order=0))
    db.flush()
    return sp


def _capture(db):
    """이 세션이 실제로 보낸 SQL 문을 모은다."""
    seen = []
    bind = db.get_bind()

    def on_exec(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(bind, 'before_cursor_execute', on_exec)
    return seen, (lambda: event.remove(bind, 'before_cursor_execute', on_exec))


def _heavy_selects(seen):
    """source_products 를 읽으면서 무거운 칸을 같이 끌고 온 SELECT 만."""
    out = []
    for s in seen:
        low = s.lower()
        if 'select' not in low or 'source_products' not in low:
            continue
        hit = [c for c in HEAVY if c in low]
        if hit:
            out.append((hit, ' '.join(s.split())[:160]))
    return out


def test_lap_progress_does_not_read_detail_html(db):
    """링 진행률(자동크롤이 꺼져 있어도 매번 계산된다)이 상세 HTML 을 안 읽는다."""
    _seed(db)
    db.expunge_all()                      # 캐시 말고 실제 조회로 재게 한다
    seen, stop = _capture(db)
    try:
        lap_progress(db)
    finally:
        stop()
    bad = _heavy_selects(seen)
    assert not bad, f'대기열 계산이 무거운 칸을 끌고 왔다: {bad}'


def test_weighted_due_products_does_not_read_detail_html(db):
    """확장이 1분마다 받아 가는 목록 계산도 마찬가지."""
    _seed(db)
    db.expunge_all()
    seen, stop = _capture(db)
    try:
        weighted_due_products(db)
    finally:
        stop()
    bad = _heavy_selects(seen)
    assert not bad, f'대기열 계산이 무거운 칸을 끌고 왔다: {bad}'


def test_next_lap_products_does_not_read_detail_html(db):
    """연속 모드(기준주기 0) 진입점 — 라이브가 실제로 타는 길."""
    _seed(db)
    db.expunge_all()
    seen, stop = _capture(db)
    try:
        next_lap_products(db)
    finally:
        stop()
    bad = _heavy_selects(seen)
    assert not bad, f'대기열 계산이 무거운 칸을 끌고 왔다: {bad}'


def test_new_heavy_column_must_be_registered(db):
    """앞으로 이 표에 무거운 칸이 새로 생기면 여기서 먼저 걸린다 (재발 방지 자물쇠).

    이번 사고가 정확히 이렇게 났다 — 2026-07-23 에 detail_html 이 조용히 늘었고,
    대기열 계산은 「모든 칸」을 읽으니 코드는 한 줄도 안 바뀐 채 전송량만 터졌다.
    새 Text 칸을 추가하는 사람이 이 목록을 같이 보게 만든다.
    """
    from sqlalchemy import Text
    from lemouton.sources.crawl_schedule import _HEAVY_COLS

    # 대기열 계산이 실제로 쓰는 칸 — 여기 있는 건 무거워질 일이 없다(짧은 값).
    USED_BY_QUEUE = {
        'id', 'site', 'url', 'external_product_id', 'product_name',
        'last_fetched_at', 'last_status', 'last_price', 'last_stock',
        'crawl_weight', 'no_change_streak', 'crawl_lap_count', 'slowdown',
        'recheck_requested_at', 'created_at', 'updated_at', 'deleted_at',
    }
    unregistered = [
        c.name for c in SourceProduct.__table__.columns
        if isinstance(c.type, Text)
        and c.name not in _HEAVY_COLS
        and c.name not in USED_BY_QUEUE
    ]
    assert not unregistered, (
        '무거운 칸이 새로 생겼는데 대기열 계산에서 빼지 않았다: %s\n'
        '  → crawl_schedule._HEAVY_COLS 에 추가하세요. '
        '안 그러면 확장 폴링 1분마다 그 칸이 통째로 DB 밖으로 나갑니다.' % unregistered)


def test_returned_products_still_expose_detail_html_when_asked(db):
    """무거운 칸을 '안 읽는' 것이지 '없애는' 게 아니다 — 물어보면 그대로 나온다.

    (이게 없으면 다음 사람이 칸을 지우거나 with_entities 로 바꿔 기능을 깬다)
    """
    sp = _seed(db)
    db.expunge_all()
    got = weighted_due_products(db)
    assert got, '랩 대상이 비었다 — 시험 자료 심기가 틀렸다'
    assert got[0].detail_html == sp.detail_html

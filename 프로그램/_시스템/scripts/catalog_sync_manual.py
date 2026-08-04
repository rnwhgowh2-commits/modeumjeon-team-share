# -*- coding: utf-8 -*-
"""마켓 상품 머리글 훑기 — 수동 1회 (서버 컨테이너 안에서 실행).

왜 이 길인가
  · 웹 단추(`POST /catalog/api/sync`)는 **요청 안에서** 돈다 → Cloudflare 100초·
    gunicorn 타임아웃에 끊기고, 그동안 워커 하나를 점유해 502 가 난다(실사고 기록).
  · 야간 훑기는 새벽에 **무인**으로 돈다 → 처음 도는 것을 아무도 못 본다.
  → 첫 채우기·문제 시 재훑기는 **지켜보면서** 여기서 돌린다.

읽고 쓰는 것
  · 마켓 API 는 **읽기만** 한다(상품 목록 조회). 등록·수정·삭제 안 부른다.
  · 우리 DB 의 `market_products` 만 갱신한다.

환경변수
  ONLY_MARKET   비우면 전체. smartstore/coupang/lotteon/eleven11/auction/gmarket
  ONLY_ACCOUNT  그 마켓의 계정 하나만 (account_key). 비우면 그 마켓 전 계정
  MAX_PAGES     계정당 페이지 상한(기본 800). 시험할 땐 작게 잡아 부담을 줄인다
"""
import os
import sys
import time

sys.path.insert(0, '/app')


def _n(v):
    return f'{v:,}' if isinstance(v, int) else str(v)


def main() -> int:
    market = (os.environ.get('ONLY_MARKET') or '').strip() or None
    account = (os.environ.get('ONLY_ACCOUNT') or '').strip() or None
    try:
        max_pages = int(os.environ.get('MAX_PAGES') or '800')
    except ValueError:
        max_pages = 800

    from shared.db import SessionLocal
    from lemouton.catalog import sync as S
    from lemouton.catalog.models import MarketProduct

    s = SessionLocal()
    try:
        before = s.query(MarketProduct).count()
        accounts = S._active_accounts(s, market)
        if account:
            accounts = [a for a in accounts if a.account_key == account]
        if not accounts:
            print(f'■ 훑을 계정이 없습니다 (market={market} account={account})')
            return 1

        print('=' * 70)
        print(f'■ 훑기 시작 — 계정 {len(accounts)}개 · 페이지 상한 {max_pages}')
        print(f'  지금 저장된 마켓 상품: {_n(before)}건')
        print('=' * 70)

        t0 = time.time()
        rows = []
        for a in accounts:
            t1 = time.time()
            try:
                client = S._client_for(a.market, a.env_prefix)
                r = S.sync_account(s, a.market, a.account_key, client=client,
                                   max_pages=max_pages,
                                   vendor_id=getattr(client, 'vendor_id', None))
            except Exception as e:                      # noqa: BLE001
                r = {'ok': False, 'saved': 0, 'pages': 0, 'missing': 0,
                     'truncated': False, 'error': str(e)[:200]}
            sec = time.time() - t1
            rows.append((a.market, a.account_key, r, sec))
            mark = '○' if r.get('ok') else '✕'
            print(f'{mark} {a.market:11} | {a.account_key:18} | '
                  f'저장 {_n(r.get("saved", 0)):>8} | 쪽 {r.get("pages", 0):>5} | '
                  f'사라짐 {r.get("missing", 0):>5} | {sec:6.1f}초'
                  + ('  ⚠️상한에 걸림(더 있음)' if r.get('truncated') else '')
                  + (f'  ⚠️{r.get("error")}' if r.get('error') else ''))

        after = s.query(MarketProduct).count()
        total_sec = time.time() - t0
        ok = sum(1 for _m, _a, r, _s in rows if r.get('ok'))
        saved = sum(r.get('saved', 0) for _m, _a, r, _s in rows)
        pages = sum(r.get('pages', 0) for _m, _a, r, _s in rows)

        print('=' * 70)
        print(f'■ 끝 — 성공 {ok}/{len(rows)} · 저장 {_n(saved)} · '
              f'호출 약 {_n(pages)}회 · {total_sec / 60:.1f}분')
        print(f'  마켓 상품: {_n(before)} → {_n(after)}건 (+{_n(after - before)})')
        if rows:
            slow = max(rows, key=lambda x: x[3])
            print(f'  가장 오래 걸린 계정: {slow[1]} {slow[3]:.1f}초')
        # 36계정 전체를 가늠할 수 있게 — 지어내지 않고 이번 실측으로만 환산한다.
        if pages:
            print(f'  쪽당 평균 {total_sec / pages:.2f}초 '
                  f'→ 이 속도면 1,000쪽에 {total_sec / pages * 1000 / 60:.0f}분')
        return 0 if ok == len(rows) else 1
    finally:
        s.close()


if __name__ == '__main__':
    sys.exit(main())

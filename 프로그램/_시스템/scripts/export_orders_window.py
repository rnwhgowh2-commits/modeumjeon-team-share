# -*- coding: utf-8 -*-
"""적재분(order_store) 기간 추출 — 전 컬럼 jsonl.gz 덤프.

용도(2026-07-22 사장님): 샵마인 3개월 정답지의 각 열을 우리 API 수집분이 전부
갖고 있는지 전 열 대조하기 위한 원자료 추출. 라이브 서버를 거치지 않고
GitHub Actions(DATABASE_URL 시크릿)에서 실행해 아티팩트로 받는다.

사용: python scripts/export_orders_window.py 2026-04-15 2026-07-21 out.jsonl.gz
"""
import gzip
import io
import json
import sys


def main() -> int:
    since, until, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    from lemouton.markets import order_store
    rows = order_store.load(since=since, until=until, include_claims=True)
    n = 0
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            n += 1
    # 정직 요약 — 행수·마켓 분포를 stdout 으로(아티팩트가 비었는데 성공처럼 보이는 것 방지)
    from collections import Counter
    mk = Counter(str(r.get("판매처") or "?") for r in rows)
    kinds = Counter("claim" if r.get("_kind") == "change" else "order" for r in rows)
    print(json.dumps({"rows": n, "markets": dict(mk), "kinds": dict(kinds),
                      "since": since, "until": until}, ensure_ascii=False))
    if n == 0:
        print("::error::추출 0행 — DATABASE_URL 대상 DB 확인 필요", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(main())

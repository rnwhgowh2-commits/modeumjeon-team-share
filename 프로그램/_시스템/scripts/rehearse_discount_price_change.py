# -*- coding: utf-8 -*-
"""판매자 부담 할인 반영 **리허설** — 아무것도 바꾸지 않고 「무엇이 어떻게 될지」만 본다.

🔴 이 스크립트는 **읽기 전용**이다. DB 를 고치지도, 마켓에 아무것도 보내지 않는다.

같은 표를 **화면에서도** 봅니다: `/policies/discount-rehearsal`
(사장님은 그쪽이 편합니다 — 터미널이 필요 없습니다.)

무엇을 보여 주나
  · 할인을 걸어 둔 **가공정책**이 무엇이고, 거기 붙은 상품이 몇 개인지
  · 그 상품들의 **표시 판매가**가 얼마에서 얼마로 오르는지
  · 고객이 내는 값 (전체 할인을 뺀 값)
  · **역마진 가드에 새로 걸리는** 조합이 있는지

  python scripts/rehearse_discount_price_change.py
  python scripts/rehearse_discount_price_change.py --min-margin 1000

DB 가 안 붙으면(로컬 자격증명 만료) **라이브 서버 안에서** 돌린다.
배포는 AWS Lightsail 의 `modeumjeon` 도커 컨테이너다(Fly 아님)::

  ssh ubuntu@<LIGHTSAIL_HOST>
  sudo docker exec modeumjeon python scripts/rehearse_discount_price_change.py

🔴 계산은 `lemouton/policy/discount_rehearsal.rehearse` **한 곳에서만** 한다 —
  여기서 다시 쓰면 터미널 표와 화면 표가 갈리고, 그러면 승인이 무의미해진다.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 윈도 콘솔은 cp949 라 이모지에서 터진다 — 보고서가 인코딩 때문에 죽으면 안 된다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                            # noqa: BLE001
        pass

부담말 = {"seller": "판매자", "market": "마켓", "split": "반반"}


def _fmt(n) -> str:
    return "—" if n is None else f"{int(n):,}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-margin", type=int, default=0, help="역마진 기준(원)")
    args = ap.parse_args()

    from lemouton.policy.discount_rehearsal import rehearse

    try:
        from shared.db import SessionLocal
        session = SessionLocal()
    except Exception as e:                       # noqa: BLE001
        print(f"🔴 DB 에 못 붙었습니다: {e}")
        print("   라이브 서버 안에서 돌리세요:")
        print("   sudo docker exec modeumjeon python "
              "scripts/rehearse_discount_price_change.py")
        return 2

    with session as s:
        try:
            r = rehearse(s, min_margin=args.min_margin)
        except Exception as e:                   # noqa: BLE001
            print(f"🔴 정책을 못 읽었습니다: {e}")
            return 2

    print(f"■ 정책 {r['policies_total']}개 중 "
          f"**할인을 걸어 둔 것 {r['policies_with_discount']}건**")
    print()

    if not r["rows"]:
        print("할인을 걸어 둔 정책이 없습니다 — 지금 이 변경으로 바뀌는 판매가는 "
              "**한 건도 없습니다.**")
        print("   (할인은 「가공정책 → 판매가 → 즉시할인」 칸에서 겁니다.)")
        for e in r["errors"][:10]:
            print("   -", e)
        return 0

    print(f"{'정책':14}{'마켓':11}{'할인':8}{'부담':8}{'상품':>6}{'매입':>9}"
          f"{'표시 전':>10}{'표시 후':>10}{'고객 후':>10}"
          f"{'마진 전':>10}{'마진 후':>10}")
    for row in r["rows"]:
        표 = "  🔴새로걸림" if row["newly_held"] else ""
        print(f"{str(row['policy'])[:13]:14}{row['market']:11}{row['discount']:8}"
              f"{부담말.get(row['burden'], row['burden']):8}"
              f"{_fmt(row['products']):>6}{_fmt(row['purchase']):>9}"
              f"{_fmt(row['price_before']):>10}{_fmt(row['price_after']):>10}"
              f"{_fmt(row['customer_after']):>10}"
              f"{_fmt(row['margin_before']):>10}{_fmt(row['margin_after']):>10}{표}")

    print()
    print(f"■ 판매가가 바뀌는 상품 연결 {r['products_affected']:,}건")
    print(f"■ 고치기 전 **적자**였던 줄: {r['loss_before']} / {len(r['rows'])}")
    print(f"■ 역마진 가드에 **새로** 걸리는 조합: {r['newly_held']}건 "
          f"(기준 {r['min_margin']:,}원)")
    if r["newly_held"]:
        print("   판매가를 올린 뒤에도 기준 미달이라 전송이 보류됩니다.")
    if r["errors"]:
        print()
        print(f"⚠️ 못 잰 조합 {len(r['errors'])}건:")
        for e in r["errors"][:10]:
            print("   -", e)
    print()
    print("🔴 이 표를 사장님이 승인하기 전에는 마켓에 아무것도 올리지 않습니다.")
    print("   같은 표를 화면에서도 봅니다: /policies/discount-rehearsal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

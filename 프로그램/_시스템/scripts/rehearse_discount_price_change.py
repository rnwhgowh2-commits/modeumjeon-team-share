# -*- coding: utf-8 -*-
"""판매자 부담 할인 반영 **리허설** — 아무것도 바꾸지 않고 「무엇이 어떻게 될지」만 본다.

🔴 이 스크립트는 **읽기 전용**이다. DB 를 고치지도, 마켓에 아무것도 보내지 않는다.

무엇을 보여 주나
  · 할인을 걸어 둔 **가공정책**이 무엇이고, 거기 붙은 상품이 몇 개인지
  · 그 상품들의 **표시 판매가**가 얼마에서 얼마로 오르는지
  · 고객이 내는 값은 그대로인지 (할인 뒤 값 = 원래 판매가)
  · **역마진 가드에 새로 걸리는** 조합이 있는지

왜 필요한가 — 판매자 부담 할인만큼 판매가를 올려 잡으면 대상 상품의 **표시 판매가가
오른다.** 고객이 내는 값은 그대로지만, 마켓 화면의 숫자가 바뀌는 것은 사실이다.
사장님이 이 목록을 보고 승인하기 전에는 마켓에 아무것도 올리지 않는다.

  python scripts/rehearse_discount_price_change.py
  python scripts/rehearse_discount_price_change.py --min-margin 1000

DB 가 안 붙으면(로컬 자격증명 만료) 라이브에서 돌린다::

  fly ssh console -C "python scripts/rehearse_discount_price_change.py"
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

#: 매입가는 정책에 없다 — 폭을 보여 주려고 대표값 몇 개로 잰다.
샘플_매입가 = (10000, 50000, 200000)


def _fmt(n) -> str:
    return "—" if n is None else f"{int(n):,}"


def _policies_with_discount(session):
    """할인을 실제로 걸어 둔 (정책, 마켓, 판매가설정) 만 골라 낸다."""
    from lemouton.policy.fields import MARKET_KEYS
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import values_for

    out = []
    폴리시 = [p for p in session.query(MarketPolicy).all() if p.deleted_at is None]
    for p in 폴리시:
        for mk in MARKET_KEYS:
            price = ((values_for(session, p.id, mk) or {}).get("price") or {})
            try:
                값 = int(price.get("discount_value") or 0)
            except (TypeError, ValueError):
                값 = 0
            if 값 > 0:
                out.append((p, mk, price))
    return out, len(폴리시)


def _붙은_상품수(session, policy_id: int) -> int:
    from lemouton.policy.models import BundlePolicyLink, SetPolicyLink
    n = session.query(BundlePolicyLink).filter(
        BundlePolicyLink.policy_id == policy_id).count()
    n += session.query(SetPolicyLink).filter(
        SetPolicyLink.policy_id == policy_id).count()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-margin", type=int, default=0, help="역마진 기준(원)")
    args = ap.parse_args()

    from lemouton.policy.as_template import PREFIX_TO_MARKET, policy_as_template
    from lemouton.pricing.unified import compute_market_price, compute_sale_price_unified
    from lemouton.policy.discount import exposed_price
    from lemouton.uploader.reconcile import compute_margin_amount

    MARKET_TO_PREFIX = {v: k for k, v in PREFIX_TO_MARKET.items()}

    try:
        from shared.db import SessionLocal
    except Exception as e:                       # noqa: BLE001
        print(f"🔴 DB 모듈을 못 불렀습니다: {e}")
        return 2

    rows, errs = [], []
    try:
        session = SessionLocal()
    except Exception as e:                       # noqa: BLE001
        print(f"🔴 DB 에 못 붙었습니다: {e}")
        print("   라이브에서 돌리세요: fly ssh console -C "
              '"python scripts/rehearse_discount_price_change.py"')
        return 2

    with session as s:
        try:
            대상, 전체정책수 = _policies_with_discount(s)
        except Exception as e:                   # noqa: BLE001
            print(f"🔴 정책을 못 읽었습니다: {e}")
            return 2

        print(f"■ 정책 {전체정책수}개 중 **할인을 걸어 둔 것 {len(대상)}건**\n")
        if not 대상:
            print("할인을 걸어 둔 정책이 없습니다 — 지금 이 변경으로 바뀌는 판매가는 "
                  "**한 건도 없습니다.**")
            print("   (할인은 「가공정책 → 판매가 → 즉시할인」 칸에서 겁니다.)")
            return 0

        for p, mk, price in 대상:
            prefix = MARKET_TO_PREFIX.get(mk)
            if not prefix:
                errs.append(f"{p.name} / {mk}: 가격 엔진이 모르는 마켓")
                continue
            상품수 = _붙은_상품수(s, p.id)
            tpl = policy_as_template(s, p.id)
            if tpl is None:
                errs.append(f"{p.name} / {mk}: 판매가를 하나도 안 정한 정책")
                continue
            단위 = str(price.get("discount_unit") or "WON").upper()
            값 = int(price.get("discount_value") or 0)
            부담 = str(price.get("discount_burden") or "seller")
            할인 = {"value": 값, "unitType": 단위}

            for 매입 in 샘플_매입가:
                try:
                    후 = compute_market_price(tpl, prefix, "sourcing", 매입)
                except Exception as e:           # noqa: BLE001
                    errs.append(f"{p.name} / {mk} / {매입}: {e}")
                    continue
                고객_후 = 후.breakdown.get("exposed_price", 후.final_price)
                마진_후 = compute_margin_amount(후, 매입)

                # 고치기 전 = 할인을 모르는 상태 (엔진에 할인을 안 넘긴 계산)
                pol_전 = compute_sale_price_unified(
                    매입,
                    margin_rate=getattr(tpl, f"{prefix}_rate_sourcing", None) or 0,
                    fee_rate=getattr(tpl, f"{prefix}_fee_rate", None) or 0,
                    shipping_fee=getattr(tpl, f"{prefix}_delivery_fee", 0) or 0,
                    rounding_unit=getattr(tpl, "rounding_unit", 100) or 100,
                    mode=str(getattr(tpl, f"{prefix}_mode_sourcing", "rate") or "rate"),
                    margin_amount=getattr(tpl, f"{prefix}_amount_sourcing", 0) or 0,
                    fixed_price=getattr(tpl, f"{prefix}_external_sale_price", 0) or 0)
                고객_전 = exposed_price(pol_전.final_price, 할인)
                수수료 = float(getattr(tpl, f"{prefix}_fee_rate", None) or 0)
                마진_전 = int(round(고객_전 * (1 - 수수료))) - 매입

                rows.append({
                    "정책": p.name, "마켓": mk, "상품수": 상품수, "매입": 매입,
                    "할인": f"{값}{'%' if 단위 == 'PERCENT' else '원'}({부담})",
                    "표시_전": pol_전.final_price, "표시_후": 후.final_price,
                    "고객_전": 고객_전, "고객_후": 고객_후,
                    "마진_전": 마진_전, "마진_후": 마진_후,
                    "새로걸림": (마진_전 >= args.min_margin and 마진_후 is not None
                                 and 마진_후 < args.min_margin),
                })

    if not rows:
        print("잴 수 있는 조합이 없습니다.")
        for e in errs[:10]:
            print("   -", e)
        return 0

    print(f"{'정책':14}{'마켓':11}{'할인':15}{'상품':>5}{'매입':>9}"
          f"{'표시 전':>10}{'표시 후':>10}{'고객 전':>10}{'고객 후':>10}"
          f"{'마진 전':>10}{'마진 후':>10}")
    for r in rows:
        표 = "  🔴새로걸림" if r["새로걸림"] else ""
        print(f"{str(r['정책'])[:13]:14}{r['마켓']:11}{r['할인'][:14]:15}"
              f"{r['상품수']:>5}{_fmt(r['매입']):>9}"
              f"{_fmt(r['표시_전']):>10}{_fmt(r['표시_후']):>10}"
              f"{_fmt(r['고객_전']):>10}{_fmt(r['고객_후']):>10}"
              f"{_fmt(r['마진_전']):>10}{_fmt(r['마진_후']):>10}{표}")

    영향상품 = sum({(r["정책"], r["마켓"]): r["상품수"] for r in rows}.values())
    걸림 = [r for r in rows if r["새로걸림"]]
    손해 = [r for r in rows if r["마진_전"] < 0]
    print(f"\n■ 판매가가 바뀌는 상품 연결 {영향상품}건 "
          f"(정책×마켓 {len({(r['정책'], r['마켓']) for r in rows})}조합)")
    print(f"■ 고치기 전 **적자**였던 조합: {len(손해)}건 / {len(rows)}")
    print(f"■ 역마진 가드에 **새로** 걸리는 조합: {len(걸림)}건 "
          f"(기준 {args.min_margin:,}원)")
    if 걸림:
        print("   판매가를 올린 뒤에도 기준 미달이라 전송이 보류됩니다.")
    if errs:
        print(f"\n⚠️ 못 잰 조합 {len(errs)}건:")
        for e in errs[:10]:
            print("   -", e)
    print("\n🔴 이 표를 사장님이 승인하기 전에는 마켓에 아무것도 올리지 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""가격 템플릿 → 정책 이관 **모의 대조** — 지금 있는 템플릿 전부를 검사한다.

읽기만 하고 아무것도 저장하지 않는다(임시 메모리 DB 에서 옮겨 보고 값만 비교).
쓰는 법:  python scripts/policy_price_parity.py
"""
import os
import sys

# scripts/ 에서 바로 돌려도 프로그램 뿌리를 찾게 한다
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from shared.db import Base, SessionLocal
from lemouton.policy import models as _pm            # noqa: F401 — 테이블 등록
from lemouton.policy.migrate_from_template import compare_prices, migrate_template
from lemouton.templates.models import PriceTemplate


def main() -> int:
    live = SessionLocal()
    try:
        tpls = list(live.scalars(select(PriceTemplate).order_by(PriceTemplate.id)))
        print(f'가격 템플릿 {len(tpls)}개를 검사합니다.\n')
        if not tpls:
            print('템플릿이 없습니다 — 검사할 것이 없습니다.')
            return 0
        rows = [{c.name: getattr(t, c.name) for c in PriceTemplate.__table__.columns}
                for t in tpls]
    finally:
        live.close()

    # 임시 DB — 라이브에는 한 글자도 쓰지 않는다
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    bad_total = 0
    try:
        for row in rows:
            t = PriceTemplate(**row)
            s.add(t)
            s.flush()
            got = migrate_template(s, tpl=t)
            res = compare_prices(s, tpl=t, policy_id=got['policy_id'])
            mark = 'OK ' if res['ok'] else 'X  '
            print(f"{mark} 「{t.name}」 — {res['checked']}가지 대조 · 다른 곳 {len(res['rows'])}")
            for r in res['rows'][:8]:
                print(f"      {r['market']:9s} {r['side']:8s} 매입가 {r['purchase']:>7,} : "
                      f"{r['template']} → {r['policy']}")
            bad_total += len(res['rows'])
    finally:
        s.close()

    print()
    if bad_total:
        print(f'다른 곳 {bad_total}군데 — **전환하면 안 됩니다.**')
        return 1
    print('전부 같습니다 — 이관해도 가격이 한 원도 안 바뀝니다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""정책에 흩어진 배송·A/S 값을 2층(계정 설정)으로 되채운다.

실행:
    python scripts/migrate_policy_to_account_settings.py            # 미리보기(기본)
    python scripts/migrate_policy_to_account_settings.py --apply    # 실제 저장

🔴 세 가지를 지킨다:
  ① 원본 `market_policy_values` 를 **지우지 않는다** — 되돌릴 수 있어야 한다.
  ② 기본이 **미리보기** — 무엇이 바뀔지 먼저 보여준다.
  ③ 계정에 이미 값이 있으면 **덮어쓰지 않는다** — 사장님이 손으로 넣은 값이 이긴다.
  ④ 그 마켓 계정이 없으면 **건너뛴다** — 아무 계정에나 붙이면 남의 셀러 반품지로
    등록되는 금전 사고가 난다(`registration/service.py` 가 같은 이유로 막고 있다).
"""
from __future__ import annotations

import sys
from pathlib import Path

# ★ 이 파일을 `python scripts/...py` 로 직접 돌리면 `프로그램/_시스템` 이 sys.path 에
#   없어서 `ModuleNotFoundError: No module named 'lemouton'` 로 죽는다. pytest 는 경로를
#   알아서 잡아 주기 때문에 시험만으로는 안 드러난다(2026-08-24 실행해 보고 잡음).
#   저장소의 다른 스크립트(`scripts/_audit_remeasure_dump.py` 등)와 같은 방식으로 맞춘다.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lemouton.policy.models import MarketAccountSetting, MarketPolicyValue  # noqa: E402
from lemouton.sourcing.models_v2 import UploadAccount  # noqa: E402

#: 정책 항목 키 → 계정 설정 컬럼 이름
_MAP = {
    'shipping.as_phone': 'as_phone',
    'shipping.as_guide': 'as_message',
    'shipping.return_fee': 'return_fee',
    'shipping.exchange_fee': 'exchange_fee',
    'shipping.jeju_extra': 'jeju_fee',
    'shipping.island_extra': 'island_fee',
    'shipping.courier': 'courier',          # extra 로 간다(공통 컬럼 아님)
}
_INT_COLUMNS = {'return_fee', 'exchange_fee', 'jeju_fee', 'island_fee'}
_COLUMN_NAMES = {'as_phone', 'as_message', 'return_fee', 'exchange_fee',
                 'jeju_fee', 'island_fee'}


def migrate(session, dry_run: bool = True) -> list[dict]:
    """되채움. ``dry_run=True`` 면 계획만 돌려주고 아무것도 저장하지 않는다."""
    rows = (session.query(MarketPolicyValue)
            .filter(MarketPolicyValue.field_key.in_(list(_MAP)))
            .all())

    # 마켓 → 그 마켓의 활성 계정 (여러 개면 되채우지 않는다 — 어느 계정 값인지 모른다)
    by_market: dict[str, list[UploadAccount]] = {}
    for acc in session.query(UploadAccount).filter_by(is_active=True).all():
        by_market.setdefault(acc.market, []).append(acc)

    plan: dict[int, dict] = {}
    for r in rows:
        accs = by_market.get(r.market) or []
        if len(accs) != 1:
            continue   # 계정이 없거나 여럿 — 건너뛴다(§④)
        acc = accs[0]
        col = _MAP[r.field_key]
        entry = plan.setdefault(acc.id, {'upload_account_id': acc.id,
                                         'market': r.market, 'values': {}})
        entry['values'][col] = r.value

    out = list(plan.values())
    if dry_run:
        return out

    for entry in out:
        s = (session.query(MarketAccountSetting)
             .filter_by(upload_account_id=entry['upload_account_id'])
             .one_or_none())
        if s is None:
            s = MarketAccountSetting(upload_account_id=entry['upload_account_id'])
            session.add(s)
            session.flush()
        extra = dict(s.extra or {})
        for col, raw in entry['values'].items():
            if col in _COLUMN_NAMES:
                # 🔴 「이미 정한 값」의 기준은 **None 이 아닌 것** 하나뿐이다
                #   (2026-08-24 사장님 확정). 예전 조건 `not in (None, '', 0)` 은
                #   사장님이 **0원(무료 반품)** 이나 **빈 A/S 안내**로 정해 둔 것을
                #   「안 정했다」고 보고 정책 값으로 덮어써 버렸다 — 금전 사고다.
                if getattr(s, col) is not None:
                    continue   # 이미 정한 값은 안 덮는다(§③)
                setattr(s, col, int(raw or 0) if col in _INT_COLUMNS else (raw or ''))
            else:
                if col in extra:
                    continue
                extra[col] = raw
        s.extra = extra   # JSON 칸은 새 dict 를 통째로 대입해야 SQLAlchemy 가 안다
    session.commit()
    return out


def main() -> int:
    from shared.db import SessionLocal

    apply = '--apply' in sys.argv
    s = SessionLocal()
    try:
        plan = migrate(s, dry_run=not apply)
    finally:
        s.close()

    if not plan:
        print('되채울 값이 없습니다.')
        return 0
    print(('실제 저장' if apply else '미리보기') + f' — 계정 {len(plan)}개')
    for e in plan:
        print(f"  계정 {e['upload_account_id']} ({e['market']}): {e['values']}")
    if not apply:
        print('\n실제로 저장하려면 --apply 를 붙여 다시 실행하세요.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

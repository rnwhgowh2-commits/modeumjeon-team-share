"""기존 혜택 행의 apply_mode 백필 (category→apply_mode). 멱등."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.db import SessionLocal
from lemouton.sourcing.models import SourceBenefitTemplate, OptionBenefitOverride


def _mode(cat, name, btype):
    c = (cat or '').strip()
    if c == '결제': return 'payment'
    if c == '캐시백': return 'cashback'
    if c in ('정액', '정률'): return 'deduct'
    if '적립' in (name or ''): return 'accrue'
    return 'deduct'


def run():
    s = SessionLocal()
    try:
        n = 0
        for Model in (SourceBenefitTemplate, OptionBenefitOverride):
            for row in s.query(Model).filter(Model.apply_mode.is_(None)).all():
                row.apply_mode = _mode(row.category, row.benefit_name, row.benefit_type)
                n += 1
        s.commit()
        print(f"backfilled apply_mode: {n} rows")
    finally:
        s.close()


if __name__ == '__main__':
    run()

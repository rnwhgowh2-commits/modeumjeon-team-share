# -*- coding: utf-8 -*-
"""정책 배송값 → 2층 계정 설정 되채움.

🔴 이 파일이 지키는 것:
  ① **원본을 지우지 않는다** — 되채움이 틀렸으면 되돌려야 한다.
  ② **dry-run 이 기본** — 실행하면 무엇이 바뀔지 먼저 보여준다.
  ③ 계정에 이미 값이 있으면 **덮어쓰지 않는다**(사장님이 손으로 넣은 값이 이긴다).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import MarketAccountSetting, MarketPolicy, MarketPolicyValue
from lemouton.sourcing.models_v2 import UploadAccount
from scripts.migrate_policy_to_account_settings import migrate


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _setup(db):
    acc = UploadAccount(account_key='르무통_쿠팡', display_name='르무통 쿠팡',
                        market='coupang', env_prefix='COUPANG_MAIN')
    db.add(acc)
    p = MarketPolicy(name='봄 신상')
    db.add(p)
    db.commit()
    db.add_all([
        MarketPolicyValue(policy_id=p.id, market='coupang',
                          field_key='shipping.as_phone', value='0507-1234-5678'),
        MarketPolicyValue(policy_id=p.id, market='coupang',
                          field_key='shipping.return_fee', value='5000'),
    ])
    db.commit()
    return acc, p


def test_드라이런은_아무것도_안_바꾼다(db):
    acc, _ = _setup(db)
    plan = migrate(db, dry_run=True)

    assert len(plan) == 1
    assert plan[0]['upload_account_id'] == acc.id
    assert plan[0]['values']['as_phone'] == '0507-1234-5678'
    assert db.query(MarketAccountSetting).count() == 0   # 저장 안 됨


def test_실행하면_계정_설정이_생긴다(db):
    acc, _ = _setup(db)
    migrate(db, dry_run=False)

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.as_phone == '0507-1234-5678'
    assert got.return_fee == 5000


def test_원본_정책값을_지우지_않는다(db):
    acc, p = _setup(db)
    migrate(db, dry_run=False)

    남은_값 = db.query(MarketPolicyValue).filter_by(policy_id=p.id).count()
    assert 남은_값 == 2   # 🔴 되돌릴 수 있어야 한다


def test_계정에_이미_값이_있으면_덮어쓰지_않는다(db):
    acc, _ = _setup(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, as_phone='0507-9999-9999'))
    db.commit()

    migrate(db, dry_run=False)

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.as_phone == '0507-9999-9999'   # 손으로 넣은 값이 이긴다


def test_그_마켓_계정이_없으면_건너뛴다(db):
    """🔴 계정이 없는 마켓 값을 아무 계정에나 붙이면 **남의 셀러 반품지**로 등록된다."""
    p = MarketPolicy(name='계정 없는 정책')
    db.add(p)
    db.commit()
    db.add(MarketPolicyValue(policy_id=p.id, market='lotteon',
                             field_key='shipping.as_phone', value='0507-1'))
    db.commit()

    plan = migrate(db, dry_run=True)
    assert plan == []


def test_사장님이_0원이라_정한_값을_덮지_않는다(db):
    """🔴 [2026-08-24] 예전 조건 `not in (None, '', 0)` 이 만들던 금전 사고.

    반품비를 **0원(무료 반품)** 으로 정해 둔 계정에 옛 정책의 5,000원이 덮여
    쓰이면, 사장님이 무료로 걸어 둔 반품이 유료로 바뀐다.
    """
    acc, _ = _setup(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, return_fee=0))
    db.commit()

    migrate(db, dry_run=False)

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.return_fee == 0          # 0 은 「정한 값」이라 그대로 남는다


def test_안_정한_칸만_채운다(db):
    acc, _ = _setup(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, as_phone='0507-9999-9999'))
    db.commit()

    migrate(db, dry_run=False)

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.as_phone == '0507-9999-9999'   # 정해 둔 값 — 안 덮음
    assert got.return_fee == 5000             # 안 정했던 칸 — 정책 값으로 채움


def test_스크립트를_직접_실행해도_돈다():
    """🔴 [2026-08-24] pytest 로는 통과하는데 **실제로 돌리면 죽던** 결함.

    `python scripts/migrate_policy_to_account_settings.py` 로 직접 실행하면
    `프로그램/_시스템` 이 sys.path 에 없어 `No module named 'lemouton'` 로 죽었다.
    pytest 는 경로를 알아서 잡아 주기 때문에 시험만으로는 영영 안 드러난다 —
    그래서 여기서 **진짜 하위 프로세스로** 돌려 확인한다.
    """
    import os
    import subprocess
    import sys as _sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]          # 프로그램/_시스템
    script = root / 'scripts' / 'migrate_policy_to_account_settings.py'
    # ★ 이 스크립트는 한글을 찍는다. Windows 기본 인코딩(cp949)으로 읽으면 읽기 스레드가
    #   터져 stdout 이 None 이 된다 — 스크립트 잘못이 아니라 **읽는 쪽** 문제다.
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([_sys.executable, str(script)], cwd=str(root),
                       capture_output=True, text=True, timeout=300,
                       encoding='utf-8', errors='replace', env=env)

    assert r.returncode == 0, f"직접 실행이 실패했다:\n{r.stderr[-800:]}"
    assert 'ModuleNotFoundError' not in r.stderr
    # --apply 없이 돌렸으므로 저장은 안 되고 안내만 나와야 한다
    assert ('되채울 값이 없습니다' in r.stdout) or ('미리보기' in r.stdout)

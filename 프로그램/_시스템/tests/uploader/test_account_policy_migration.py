"""속도 정책 표의 주인 갈아끼우기 (market_accounts → upload_accounts).

★ 이 마이그레이션이 안 돌면 라이브에서 **계정 30개 전부 저장 실패**한다.
  PostgreSQL 이 옛 FK 를 강제하기 때문이다 (SQLite 는 기본적으로 안 막아서
  개발기에서는 멀쩡해 보인다 — 그래서 테스트로 잡는다).
"""
from sqlalchemy import create_engine, inspect, text

from shared.db import _repoint_account_upload_policies

# 옛 스키마 — account_id 가 market_accounts.id 를 가리킨다
_OLD = """
CREATE TABLE market_accounts (id INTEGER PRIMARY KEY, market VARCHAR(20));
CREATE TABLE account_upload_policies (
    account_id INTEGER PRIMARY KEY REFERENCES market_accounts(id),
    seconds_per_item INTEGER NOT NULL DEFAULT 6,
    window_seconds INTEGER, max_count INTEGER,
    enabled BOOLEAN NOT NULL DEFAULT 1
);
"""


def _old_db(rows=0):
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        for stmt in _OLD.strip().split(";"):
            if stmt.strip():
                c.execute(text(stmt))
        for i in range(rows):
            c.execute(text("INSERT INTO market_accounts (id, market) VALUES "
                           f"({i + 1}, 'coupang')"))
            c.execute(text("INSERT INTO account_upload_policies (account_id) VALUES "
                           f"({i + 1})"))
    return eng


def test_옛_FK_를_찾아서_갈아엎는다():
    eng = _old_db()
    assert _repoint_account_upload_policies(eng) is True
    assert 'account_upload_policies' not in set(inspect(eng).get_table_names())


def test_옛_행이_있어도_지운다():
    """★ 남겨두면 더 위험하다 — market_accounts.id 3번의 속도가
    upload_accounts.id 3번(전혀 다른 계정)에 조용히 붙는다."""
    eng = _old_db(rows=3)
    assert _repoint_account_upload_policies(eng) is True


def test_두번_돌려도_안전하다():
    eng = _old_db()
    _repoint_account_upload_policies(eng)
    assert _repoint_account_upload_policies(eng) is False


def test_이미_새_스키마면_안_건드린다():
    """새 표를 만든 뒤 재부팅해도 사장님이 정한 속도가 날아가면 안 된다."""
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE upload_accounts (id INTEGER PRIMARY KEY)"))
        c.execute(text("CREATE TABLE account_upload_policies ("
                       "account_id INTEGER PRIMARY KEY REFERENCES upload_accounts(id),"
                       "seconds_per_item INTEGER NOT NULL DEFAULT 6)"))
        c.execute(text("INSERT INTO upload_accounts (id) VALUES (1)"))
        c.execute(text("INSERT INTO account_upload_policies "
                       "(account_id, seconds_per_item) VALUES (1, 99)"))
    assert _repoint_account_upload_policies(eng) is False
    with eng.begin() as c:
        assert c.execute(text("SELECT seconds_per_item FROM account_upload_policies"
                              )).scalar() == 99


def test_표가_없으면_아무것도_안_한다():
    assert _repoint_account_upload_policies(create_engine("sqlite://")) is False


def test_새_모델의_FK_가_upload_accounts_를_가리킨다():
    """모델 정의 자체가 옛 표로 되돌아가는 걸 막는다."""
    from lemouton.pricing.settings import AccountUploadPolicy
    fks = list(AccountUploadPolicy.__table__.c.account_id.foreign_keys)
    assert [fk.column.table.name for fk in fks] == ["upload_accounts"]

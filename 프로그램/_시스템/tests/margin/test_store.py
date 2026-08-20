# -*- coding: utf-8 -*-
"""store — gzip 왕복 + 20건 보관 정리 + R2 삭제."""
import datetime as _dt

import pytest

from lemouton.margin import store as S


@pytest.fixture
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared.db import Base
    import lemouton.margin.models  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["margin_analyses"]])
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


def _payload(n=3):
    return {"matched": [{"마켓주문번호": str(i)} for i in range(n)],
            "summary": {"총순마진": 1000 * n}}


def _save(session, **kw):
    base = dict(payload=_payload(), period_from=_dt.date(2026, 7, 1),
                period_to=_dt.date(2026, 7, 8), buy_file_key="k",
                buy_filename="b.xls", markets_fetched=["coupang"],
                markets_failed=[], counts={"matched": 3}, created_by=None)
    base.update(kw)
    return S.save(session, **base)


def test_roundtrip_gzip(session):
    a = _save(session, created_by="tester")
    loaded = S.load(session, a.id)
    assert loaded["summary"]["총순마진"] == 3000
    assert len(loaded["matched"]) == 3


def test_blob_is_compressed(session):
    import json
    big = {"matched": [{"x": "y" * 200} for _ in range(500)]}
    a = _save(session, payload=big)
    raw = len(json.dumps(big, ensure_ascii=False).encode("utf-8"))
    assert len(a.result_blob) < raw / 5


def test_korean_survives_roundtrip(session):
    a = _save(session, payload={"summary": {"마켓": "스마트스토어", "총순마진": -50000}})
    assert S.load(session, a.id)["summary"]["마켓"] == "스마트스토어"


def test_pack_rejects_nan():
    """NaN 페이로드는 저장 시점에 큰 소리로 실패해야 한다 — 저장된 blob 이
    나중에 브라우저 JSON.parse 를 조용히 깨뜨리는 것보다 낫다."""
    with pytest.raises(ValueError):
        S._pack({"summary": {"총순마진": float("nan")}})


def test_list_recent_newest_first(session):
    for i in range(3):
        _save(session, buy_file_key=f"k{i}", counts={"matched": i})
    rows = S.list_recent(session)
    assert [r.counts["matched"] for r in rows] == [2, 1, 0]


def test_load_missing_raises(session):
    with pytest.raises(LookupError):
        S.load(session, 9999)


def test_prune_keeps_20_and_deletes_r2(session, monkeypatch):
    deleted = []
    monkeypatch.setattr(S, "_delete_object", lambda key: deleted.append(key))
    for i in range(23):
        _save(session, buy_file_key=f"key-{i}")
    assert len(S.list_recent(session, limit=100)) == 20
    assert deleted == ["key-0", "key-1", "key-2"]


def test_delete_removes_row_and_objects(session, monkeypatch):
    deleted = []
    monkeypatch.setattr(S, "_delete_object", lambda key: deleted.append(key))
    a = _save(session, buy_file_key="bk", shopmine_file_key="sk",
              shopmine_filename="s.xls")
    S.delete(session, a.id)
    assert deleted == ["bk", "sk"]
    assert S.list_recent(session) == []


def test_delete_missing_is_noop(session):
    S.delete(session, 9999)   # 던지지 않는다


def test_r2_failure_does_not_block_db_cleanup(session, monkeypatch):
    """R2 삭제가 실패해도 DB 정리는 진행한다 — 고아 레코드가 쌓이면 안 된다."""
    def _boom(key):
        raise RuntimeError("R2 down")
    monkeypatch.setattr(S, "_delete_object", _boom)
    a = _save(session, buy_file_key="bk")
    S.delete(session, a.id)
    assert S.list_recent(session) == []

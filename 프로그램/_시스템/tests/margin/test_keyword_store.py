# -*- coding: utf-8 -*-
"""card_keyword_store — 팀 공유 카드 키워드 설정 (단일 row) 저장/조회/시드.

원본은 단일 사용자 card_keywords.json 이었으나, 팀 공유 앱에서는 DB 한 행으로
승격한다 (멀티유저가 같은 설정을 본다). 표가 비면 lemouton/margin/card_keywords_seed.json
으로 시드한다 (원본 기본값과 동일 = 페이지 내장 폴백과 일치).
"""
import pytest


@pytest.fixture
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared.db import Base
    import lemouton.margin.models  # noqa: F401  # 테이블 등록

    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables["card_keyword_config"]])
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    yield s, Session
    s.close()


def test_get_config_seeds_from_json_when_empty(session):
    s, _ = session
    from lemouton.margin import keyword_store as KS
    cfg = KS.get_config(s)
    assert isinstance(cfg, dict)
    assert isinstance(cfg.get("cards"), dict)
    # 원본 시드의 대표 카드가 있어야 한다
    assert "confirmed_blackspot" in cfg["cards"]
    assert cfg["cards"]["confirmed_blackspot"]["memo"] == ["블랙"]
    # 다른 top-level 키(_comment, version)도 시드에서 그대로 보존
    assert "version" in cfg


def test_save_config_roundtrip(session):
    s, _ = session
    from lemouton.margin import keyword_store as KS
    KS.get_config(s)  # 시드
    new = {"version": 9, "cards": {"x": {"memo": ["hi"], "label": "X"}}}
    KS.save_config(s, new)
    got = KS.get_config(s)
    assert got["cards"] == {"x": {"memo": ["hi"], "label": "X"}}
    assert got["version"] == 9


def test_replace_single_card_leaves_others_intact(session):
    s, _ = session
    from lemouton.margin import keyword_store as KS
    cfg = KS.get_config(s)
    other_before = dict(cfg["cards"]["memo_settled"])
    cfg["cards"]["confirmed_blackspot"] = {"memo": ["새키워드"], "label": "L"}
    KS.save_config(s, cfg)
    got = KS.get_config(s)
    assert got["cards"]["confirmed_blackspot"]["memo"] == ["새키워드"]
    assert got["cards"]["memo_settled"] == other_before


def test_team_shared_persists_across_sessions(session):
    """새 세션(새 커넥션)이 저장값을 본다 — per-request 메모리가 아니라 DB 임을 증명."""
    s, Session = session
    from lemouton.margin import keyword_store as KS
    KS.get_config(s)
    KS.save_config(s, {"version": 42, "cards": {"z": {"label": "Z"}}})

    s2 = Session()
    try:
        got = KS.get_config(s2)
        assert got["version"] == 42
        assert list(got["cards"].keys()) == ["z"]
    finally:
        s2.close()


def test_seed_insert_is_idempotent_under_race(session, monkeypatch):
    """동시 최초 요청 둘이 각자 id=1 을 INSERT 해도 500 나지 않는다.

    다른 요청이 먼저 시드해 둔 상태에서, '행 없음'(stale)을 본 이 세션이
    INSERT 를 시도해 IntegrityError → rollback → 기존 행 재읽기로 복구하는지 검증.
    """
    s, Session = session
    from lemouton.margin import keyword_store as KS
    from lemouton.margin.models import CardKeywordConfig

    # 다른 요청이 먼저 시드한 상태 (행이 이미 DB 에 존재).
    pre = Session()
    try:
        pre.add(CardKeywordConfig(id=1, config={"cards": {"seeded": {"label": "S"}}}))
        pre.commit()
    finally:
        pre.close()

    # 이 세션은 '행 없음'을 봤다고 가정 → 첫 _row 만 None → INSERT 충돌 유도.
    real_row = KS._row
    calls = {"n": 0}

    def stale_first(sess):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_row(sess)

    monkeypatch.setattr(KS, "_row", stale_first)

    cfg = KS.get_config(s)  # 500 나면 안 된다
    assert cfg["cards"] == {"seeded": {"label": "S"}}
    assert calls["n"] >= 2  # 충돌 후 재읽기까지 갔다


def test_seed_matches_page_builtin_fallback(session):
    """시드가 페이지 내장 폴백(_getCardKeywords)의 대표 카드들과 일치해야 한다."""
    s, _ = session
    from lemouton.margin import keyword_store as KS
    cards = KS.get_config(s)["cards"]
    assert cards["memo_settled"]["memo"] == ["입금", "철회"]
    assert cards["tracking_failed"]["mg"] == ["송장전송실패"]
    assert cards["pending"]["mg"] == ["배송대기중"]

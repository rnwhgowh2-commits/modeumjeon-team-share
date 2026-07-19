# -*- coding: utf-8 -*-
"""가공정책 — 여러 소싱처 URL 을 묶어 여러 마켓으로 내보내는 규칙 묶음.

설계서: 2026-07-17-신규상품등록-가공템플릿-design.md §7 / 시안 13 Ⅲ-E안
사장님 확정: "세트 → 가공정책(URL별). 가공정책 기준은 URL. 여러 소싱처 URL 을 넣을 수 있고,
              여러 판매처 마켓에 올릴 수 있음."
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lemouton.registration.process_policy import (
    ITEM_KEYS,
    PolicyConflict,
    attach_market,
    attach_source,
    create_policy,
    detach_source,
    policy_for_source,
    rules_for,
    set_rule,
    unassigned_sources,
)
from shared.db import Base


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


# ── 정책 만들기 ─────────────────────────────────────────────────

def test_정책을_만든다(db):
    p = create_policy(db, name="나이키 스니커즈 기본")
    assert p.id
    assert p.name == "나이키 스니커즈 기본"


def test_이름이_비면_거부(db):
    with pytest.raises(ValueError):
        create_policy(db, name="   ")


def test_같은_이름_정책은_거부(db):
    """이름이 겹치면 화면에서 어느 것인지 못 고른다."""
    create_policy(db, name="나이키")
    db.flush()
    with pytest.raises(ValueError):
        create_policy(db, name="나이키")


# ── 소싱처 URL 붙이기 ───────────────────────────────────────────

def test_정책에_소싱처_구성을_붙인다(db):
    p = create_policy(db, name="A")
    attach_source(db, policy_id=p.id, source_key="musinsa", brand="나이키",
                  url="https://musinsa.com/search?keyword=nike")
    db.flush()
    assert policy_for_source(db, source_key="musinsa", brand="나이키").id == p.id


def test_한_정책에_여러_소싱처를_붙일_수_있다(db):
    p = create_policy(db, name="A")
    attach_source(db, policy_id=p.id, source_key="musinsa", brand="나이키")
    attach_source(db, policy_id=p.id, source_key="ssg", brand="나이키")
    db.flush()
    assert policy_for_source(db, source_key="ssg", brand="나이키").id == p.id


# ── 🔴 한 구성은 한 정책에만 (중복·모순 금지) ────────────────────

def test_같은_구성을_두_정책에_붙이면_거부(db):
    """이 프로젝트 최상위 원칙 — 중복·모순 금지.

    한 구성이 두 정책에 속하면 「이 URL 은 어느 규칙을 따르나」가 모호해지고,
    가공 결과가 실행 순서에 따라 달라진다. 조용히 덮어쓰지 않고 막는다.
    """
    a = create_policy(db, name="A")
    b = create_policy(db, name="B")
    attach_source(db, policy_id=a.id, source_key="musinsa", brand="나이키")
    db.flush()
    with pytest.raises(PolicyConflict) as e:
        attach_source(db, policy_id=b.id, source_key="musinsa", brand="나이키")
    assert "A" in str(e.value), "어느 정책과 부딪히는지 이름을 알려줘야 한다"


def test_같은_정책에_같은_구성을_또_붙이면_조용히_넘어간다(db):
    """멱등 — 같은 정책이면 중복이 아니라 '이미 되어 있음'이다."""
    a = create_policy(db, name="A")
    attach_source(db, policy_id=a.id, source_key="musinsa", brand="나이키")
    db.flush()
    attach_source(db, policy_id=a.id, source_key="musinsa", brand="나이키")
    db.flush()
    assert policy_for_source(db, source_key="musinsa", brand="나이키").id == a.id


def test_떼면_다른_정책에_붙일_수_있다(db):
    a = create_policy(db, name="A")
    b = create_policy(db, name="B")
    attach_source(db, policy_id=a.id, source_key="musinsa", brand="나이키")
    db.flush()
    detach_source(db, source_key="musinsa", brand="나이키")
    db.flush()
    attach_source(db, policy_id=b.id, source_key="musinsa", brand="나이키")
    db.flush()
    assert policy_for_source(db, source_key="musinsa", brand="나이키").id == b.id


def test_브랜드가_다르면_다른_구성이다(db):
    a = create_policy(db, name="A")
    b = create_policy(db, name="B")
    attach_source(db, policy_id=a.id, source_key="musinsa", brand="나이키")
    attach_source(db, policy_id=b.id, source_key="musinsa", brand="아디다스")
    db.flush()
    assert policy_for_source(db, source_key="musinsa", brand="아디다스").id == b.id


# ── 🔴 정책 없는 구성 찾기 (E안의 존재 이유) ─────────────────────

def test_정책이_안_붙은_구성을_찾아낸다(db):
    """시안 13 Ⅲ-E안 — 크롤은 되는데 어디에도 안 올라가는 URL 을 잡는다.

    정책 중심 화면에서는 이 누락이 안 보인다. 그래서 URL 을 주인공으로 놓는다.
    """
    a = create_policy(db, name="A")
    attach_source(db, policy_id=a.id, source_key="musinsa", brand="나이키")
    db.flush()

    crawled = [("musinsa", "나이키"), ("musinsa", "아디다스"), ("ssg", "뉴발란스")]
    out = unassigned_sources(db, crawled)
    assert ("musinsa", "아디다스") in out
    assert ("ssg", "뉴발란스") in out
    assert ("musinsa", "나이키") not in out


def test_전부_붙어_있으면_빈_목록(db):
    a = create_policy(db, name="A")
    attach_source(db, policy_id=a.id, source_key="musinsa", brand="나이키")
    db.flush()
    assert unassigned_sources(db, [("musinsa", "나이키")]) == []


def test_크롤된_게_없으면_빈_목록(db):
    assert unassigned_sources(db, []) == []


# ── 마켓 붙이기 ─────────────────────────────────────────────────

def test_정책에_여러_마켓을_붙인다(db):
    p = create_policy(db, name="A")
    attach_market(db, policy_id=p.id, market="smartstore", account_key="acc1")
    attach_market(db, policy_id=p.id, market="coupang", account_key="acc1")
    db.flush()
    assert {m.market for m in p.markets} == {"smartstore", "coupang"}


def test_같은_마켓_같은_계정은_한_번만(db):
    p = create_policy(db, name="A")
    attach_market(db, policy_id=p.id, market="smartstore", account_key="acc1")
    db.flush()
    attach_market(db, policy_id=p.id, market="smartstore", account_key="acc1")
    db.flush()
    assert len(p.markets) == 1


def test_같은_마켓이라도_계정이_다르면_따로(db):
    """다계정 운영이므로 계정까지 봐야 한다."""
    p = create_policy(db, name="A")
    attach_market(db, policy_id=p.id, market="smartstore", account_key="acc1")
    attach_market(db, policy_id=p.id, market="smartstore", account_key="acc2")
    db.flush()
    assert len(p.markets) == 2


# ── 13항목 규칙 ─────────────────────────────────────────────────

def test_항목은_13개(db):
    assert len(ITEM_KEYS) == 13
    assert "name" in ITEM_KEYS
    assert "banned_words" in ITEM_KEYS


def test_규칙을_저장한다(db):
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name",
             config={"replace": [["화이트 블랙", "팬다"]], "max_len": 100})
    db.flush()
    r = next(x for x in p.rules if x.item_key == "name")
    assert r.config["max_len"] == 100


def test_같은_항목을_다시_저장하면_덮어쓴다(db):
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 100})
    db.flush()
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 50})
    db.flush()
    rules = [x for x in p.rules if x.item_key == "name"]
    assert len(rules) == 1
    assert rules[0].config["max_len"] == 50


# ── 🔴 마켓마다 다른 규칙 (사장님 확정 1-2) ────────────────────────

def test_공통_규칙이_모든_마켓에_적용된다(db):
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 100})
    db.flush()
    assert rules_for(db, policy_id=p.id, market="smartstore")["name"]["max_len"] == 100
    assert rules_for(db, policy_id=p.id, market="coupang")["name"]["max_len"] == 100


def test_마켓별_규칙이_공통을_덮어쓴다(db):
    """설계서 §7-12 「세트 단위 = 소싱처 × 마켓 조합마다」.

    「스스는 상품명 100자, 쿠팡은 50자」가 이 구조로 표현된다.
    """
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 100})
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 50}, market="coupang")
    db.flush()
    assert rules_for(db, policy_id=p.id, market="smartstore")["name"]["max_len"] == 100
    assert rules_for(db, policy_id=p.id, market="coupang")["name"]["max_len"] == 50


def test_덮어쓰기는_항목_단위다(db):
    """마켓별로 한 항목만 달라도 나머지는 공통을 그대로 쓴다."""
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 100})
    set_rule(db, policy_id=p.id, item_key="price", config={"margin_rate": 0.25})
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 50}, market="coupang")
    db.flush()
    r = rules_for(db, policy_id=p.id, market="coupang")
    assert r["name"]["max_len"] == 50            # 덮어씀
    assert r["price"]["margin_rate"] == 0.25     # 공통 그대로


def test_마켓_안_주면_공통만_돌려준다(db):
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 100})
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 50}, market="coupang")
    db.flush()
    assert rules_for(db, policy_id=p.id)["name"]["max_len"] == 100


def test_같은_마켓_같은_항목은_한_행(db):
    from lemouton.registration.process_policy import ProcessRule
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 100}, market="coupang")
    db.flush()
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 70}, market="coupang")
    db.flush()
    rows = db.query(ProcessRule).filter_by(policy_id=p.id, market="coupang",
                                           item_key="name").all()
    assert len(rows) == 1
    assert rows[0].config["max_len"] == 70


def test_공통과_마켓별은_다른_행이다(db):
    from lemouton.registration.process_policy import ProcessRule
    p = create_policy(db, name="A")
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 100})
    set_rule(db, policy_id=p.id, item_key="name", config={"max_len": 50}, market="coupang")
    db.flush()
    assert db.query(ProcessRule).filter_by(policy_id=p.id, item_key="name").count() == 2


def test_모르는_항목은_거부(db):
    """오타로 만든 규칙이 조용히 저장되면 '왜 안 먹지'가 된다."""
    p = create_policy(db, name="A")
    with pytest.raises(ValueError):
        set_rule(db, policy_id=p.id, item_key="nmae", config={})


# ── 🔴 테이블이 실제로 만들어지는지 ─────────────────────────────

def test_app이_가공정책_모델을_import_한다():
    """create_all 은 **import 된 모델만** 만든다 — 빠뜨리면 테이블이 조용히 안 생긴다.

    app.py 주석에 이미 같은 사고 이력이 적혀 있다(크롤 통계 테이블이 한동안 안 생겼음).
    에러도 안 나고 화면만 비므로, import 누락을 테스트로 못박는다.
    """
    import io
    import os
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = io.open(os.path.join(here, "app.py"), encoding="utf-8").read()
    assert "lemouton.registration.process_policy" in src, (
        "app.py 에 process_policy import 가 없습니다 — 라이브에서 테이블이 안 생깁니다")


def test_create_all이_4테이블을_만든다():
    from sqlalchemy import create_engine, inspect

    import lemouton.registration.process_policy  # noqa: F401
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    names = set(inspect(eng).get_table_names())
    for t in ("process_policies", "process_policy_sources",
              "process_policy_markets", "process_rules"):
        assert t in names, f"{t} 테이블이 안 만들어졌습니다"

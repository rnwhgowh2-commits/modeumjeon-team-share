# -*- coding: utf-8 -*-
"""소싱처 단일 명부 통합 — SourcingSource 확장·seed·동적 라벨 단위 테스트.

spec: docs/superpowers/specs/2026-06-30-소싱처-단일명부-통합-design.md
"""
import os

import pytest


@pytest.fixture
def roster_db(monkeypatch):
    """SourcingSource 테이블이 있는 격리 DB. 각 테스트 전 빌트인 행 정리."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    for _m in ("lemouton.sourcing.models", "lemouton.sourcing.models_pricing"):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, SessionLocal, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()      # 기존 테이블에 신규 컬럼(is_builtin·crawl_guide) 보강
    from lemouton.sourcing.models import SourcingSource
    s = SessionLocal()
    try:
        s.query(SourcingSource).delete()
        s.commit()
    finally:
        s.close()
    yield
    s = SessionLocal()
    try:
        s.query(SourcingSource).delete()
        s.commit()
    finally:
        s.close()


def test_sourcingsource_has_new_columns():
    from lemouton.sourcing.models import SourcingSource
    cols = SourcingSource.__table__.columns.keys()
    assert "is_builtin" in cols and "crawl_guide" in cols


def test_seed_builtins_idempotent(roster_db):
    from lemouton.sourcing.source_registry import seed_builtins, SOURCES
    from lemouton.sourcing.models import SourcingSource
    from shared.db import SessionLocal
    seed_builtins()
    seed_builtins()  # 두 번 호출해도 중복 없어야
    s = SessionLocal()
    try:
        rows = s.query(SourcingSource).filter_by(is_builtin=True).all()
        keys = [r.source_key for r in rows]
    finally:
        s.close()
    assert len(keys) == len(set(keys))                  # 중복 없음
    assert {x["key"] for x in SOURCES}.issubset(set(keys))


def test_get_labels_reflects_renamed_builtin(roster_db):
    from lemouton.sourcing.source_registry import seed_builtins, get_labels
    from lemouton.sourcing.models import SourcingSource
    from shared.db import SessionLocal
    seed_builtins()
    s = SessionLocal()
    try:
        r = s.query(SourcingSource).filter_by(source_key="lemouton").first()
        r.label = "르무통TEST"
        s.commit()
    finally:
        s.close()
    assert get_labels().get("lemouton") == "르무통TEST"   # 이름 껍데기 수정 반영


def test_get_all_sources_no_duplicate_builtin(roster_db):
    from lemouton.sourcing.source_registry import seed_builtins, get_all_sources
    seed_builtins()
    keys = [s["key"] for s in get_all_sources()]
    assert len(keys) == len(set(keys))                  # 빌트인 중복 없음


def test_api_source_label_reflects_rename(roster_db):
    """api._source_label 이 명부 rename 을 반영(하드코딩 아님)."""
    from lemouton.sourcing.source_registry import seed_builtins
    from lemouton.sourcing.models import SourcingSource
    from shared.db import SessionLocal
    seed_builtins()
    s = SessionLocal()
    try:
        r = s.query(SourcingSource).filter_by(source_key="musinsa").first()
        r.label = "무신사RENAMED"
        s.commit()
    finally:
        s.close()
    from webapp.routes.api import _source_label
    assert _source_label("musinsa") == "무신사RENAMED"


def test_sidebar_hides_opcenter_and_dict():
    """[2026-06-30] 운영센터·소싱처 사전 둘 다 사이드바에서 제거(가이드로 통합)."""
    from webapp.routes.api_sidebar import _default_layout, _has_item_id
    layout = _default_layout()
    assert _has_item_id(layout, "i_sources") is False      # 운영센터 제거
    assert _has_item_id(layout, "i_src_dict") is False     # 소싱처 사전 제거(통합)
    assert _has_item_id(layout, "i_crawl_guide") is True   # 크롤링 가이드 유지


# ─────────────────────────────────────────────────────────────
# roster 서비스 (Phase 2) — 이름 껍데기·로고·삭제 가드·가이드
# ─────────────────────────────────────────────────────────────

def test_roster_rename_keeps_key(roster_db):
    from lemouton.sourcing import roster
    roster.seed_if_needed()
    roster.rename("hmall_x", "현대백화점") if False else None
    roster.add("hmall_x", "현대H몰", "hmall.com")
    roster.rename("hmall_x", "현대백화점")
    g = roster.get("hmall_x")
    assert g["label"] == "현대백화점" and g["key"] == "hmall_x"   # 키 불변


def test_roster_builtin_delete_blocked(roster_db):
    from lemouton.sourcing import roster
    import pytest as _pt
    roster.seed_if_needed()
    with _pt.raises(ValueError):
        roster.delete("lemouton")                                 # 빌트인 삭제 차단


def test_roster_custom_delete_ok_when_unused(roster_db):
    from lemouton.sourcing import roster
    roster.add("tmpsrc", "임시", "tmp.example")
    roster.delete("tmpsrc")                                       # 참조 0 → 삭제 OK
    assert roster.get("tmpsrc") is None


def test_roster_set_active_hide(roster_db):
    from lemouton.sourcing import roster
    roster.add("hidesrc", "숨길소싱처", "hide.example")
    roster.set_active("hidesrc", False)
    # is_active=False 면 get_all_sources(활성만) 에서 빠짐
    assert roster.get("hidesrc") is None


def test_roster_guide_roundtrip(roster_db):
    from lemouton.sourcing import roster
    import lemouton.sourcing.crawl_guide as cg
    roster.add("gsrc", "가이드소싱처", "g.example")
    g = cg.empty_skeleton()
    g["sample_urls"] = [{"url": "https://g.example/p/1", "is_lead": True}]
    roster.set_guide("gsrc", g)
    back = roster.get_guide("gsrc")
    assert back["sample_urls"][0]["url"] == "https://g.example/p/1"


# ─────────────────────────────────────────────────────────────
# 가이드 인라인 관리 엔드포인트 (사전 통합) — /sourcing-guide/api/source/<key>
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def sg_client(roster_db):
    from flask import Flask
    from webapp.routes import sourcing_guide as sg
    app = Flask(__name__)
    app.register_blueprint(sg.bp)
    app.config.update(TESTING=True)
    return app.test_client()


def test_guide_rename_reflects_in_labels(sg_client):
    from lemouton.sourcing import roster
    from lemouton.sourcing.source_registry import get_labels
    roster.add('shopx', '쇼핑몰', 'shopx.example')
    r = sg_client.put('/sourcing-guide/api/source/shopx', json={'name': '쇼핑몰RENAMED'})
    assert r.get_json()['ok'] is True
    assert get_labels().get('shopx') == '쇼핑몰RENAMED'


def test_guide_builtin_delete_blocked(sg_client):
    r = sg_client.delete('/sourcing-guide/api/source/lemouton')
    assert r.status_code == 400 and r.get_json()['ok'] is False


def test_guide_hide_toggle(sg_client):
    from lemouton.sourcing import roster
    roster.add('hidesrc', '숨길소싱처', 'hide.example')
    r = sg_client.put('/sourcing-guide/api/source/hidesrc', json={'is_active': False})
    assert r.get_json()['ok'] is True
    assert roster.get('hidesrc') is None        # 비활성→활성 목록에서 빠짐


def test_guide_custom_delete(sg_client):
    from lemouton.sourcing import roster
    roster.add('tmpsrc', '임시', 'tmp.example')
    r = sg_client.delete('/sourcing-guide/api/source/tmpsrc')
    assert r.get_json()['ok'] is True
    assert roster.get('tmpsrc') is None


def test_guide_logo_from_url(sg_client):
    from lemouton.sourcing import roster
    roster.add('logosrc', '로고소싱처', 'old.example')
    r = sg_client.put('/sourcing-guide/api/source/logosrc', json={'logo_url': 'https://www.new.example/p/1'})
    assert r.get_json()['ok'] is True
    g = roster.get('logosrc')
    assert 'new.example/favicon.ico' in (g.get('favicon_url') or '')


# ─────────────────────────────────────────────────────────────
# 가이드 이관 (Phase 4 T9) — SourceRegistry.crawl_guide → SourcingSource
# ─────────────────────────────────────────────────────────────

def test_migrate_guides_from_registry(roster_db):
    from lemouton.sourcing import roster
    from lemouton.sourcing.models_pricing import SourceRegistry
    from lemouton.sourcing.models import SourcingSource
    from shared.db import SessionLocal
    import lemouton.sourcing.crawl_guide as cg
    roster.seed_if_needed()
    # 도메인 매칭용 SourceRegistry 행(르무통) — 비어있지 않은 가이드
    g = cg.empty_skeleton()
    g["fields"]["title"]["status"] = "ok"
    s = SessionLocal()
    try:
        s.query(SourceRegistry).filter(SourceRegistry.main_url.like("%lemouton%")).delete(synchronize_session=False)
        s.add(SourceRegistry(name="르무통 공홈", main_url="https://lemouton.co.kr", crawl_guide=cg.dumps(g)))
        s.commit()
    finally:
        s.close()
    n = roster.migrate_guides_from_registry()
    assert n >= 1
    back = roster.get_guide("lemouton")
    assert back["fields"]["title"]["status"] == "ok"
    # 멱등: 2회차는 target 이미 있어 복사 0
    assert roster.migrate_guides_from_registry() == 0


def test_seed_includes_catalog_adapter_sources(roster_db):
    """[2026-06-30 fix] hmall·lotteimall(카탈로그 크롤지원)도 명부에 seed — 사전 누락 방지."""
    from lemouton.sourcing.source_registry import seed_builtins, get_labels
    from lemouton.sourcing import roster
    seed_builtins()
    keys = {x["key"] for x in roster.list_all()}
    assert "hmall" in keys and "lotteimall" in keys     # 카탈로그 크롤지원 포함
    assert get_labels().get("hmall") == "현대H몰"

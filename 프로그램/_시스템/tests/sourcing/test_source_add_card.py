import json
import os

import pytest

from lemouton.sourcing import crawl_guide as cg
from shared.db import SessionLocal
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing.models import SourcingSource

# webapp/templates 절대 경로 — tests/sourcing/ 에서 ../../webapp/templates
_TMPL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "webapp", "templates")
)


# ─────────────────────────────────────────────────────────────────
#  Task 2 — 신규 소싱처 생성 API  /sourcing-guide/api/add-source
# ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    """sourcing_guide 블루프린트만 띄운 테스트 클라이언트. ENVIRONMENT=test 로 admin 게이트 우회.
    로컬 SQLite 에 테이블이 없는 워크트리 환경을 위해 Base.metadata.create_all() 선행."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    # 모든 모델을 먼저 등록해야 create_all() 이 테이블을 생성한다
    for _m in (
        "lemouton.sourcing.models",
        "lemouton.sourcing.models_pricing",
        "lemouton.sources.models",
        "lemouton.templates.models",
        "lemouton.inventory.models",
        "lemouton.mapping.models",
        "webapp.icon_store_model",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()      # [2026-06-30] SourcingSource is_builtin·crawl_guide 보강

    from flask import Flask
    from webapp.routes import sourcing_guide as sg
    app = Flask(__name__, template_folder=_TMPL_DIR)
    app.register_blueprint(sg.bp)
    app.config.update(TESTING=True)
    # base.html / sidebar.html 에서 필요한 컨텍스트 변수 — 테스트 앱에는 context_processor 없으므로
    # 모든 sidebar 변수를 안전한 더미값으로 globals 주입.
    # [2026-07-17] 모드가 늘 때마다 여기 손대지 않도록 _MODE_DEFAULTS 에서 파생.
    # (키 하나라도 빠지면 _modeswitch.html 이 UndefinedError)
    from webapp.routes import _MODE_DEFAULTS
    _dummy_mode_icons = {k: {'emoji': v, 'color': ''} for k, v in _MODE_DEFAULTS.items()}
    app.jinja_env.globals.update(
        sidebar_layout={},
        sidebar_badge_values={'unmapped': 0, 'failed': 0},
        sidebar_mode_icons=_dummy_mode_icons,
        sidebar_unmapped_count=0,
        sidebar_failed_count=0,
        active_app='bundles',  # 실 context_processor 기본값과 동일하게
    )
    return app.test_client()


def _cleanup(name):
    # [2026-06-30 단일명부] 소싱처는 이제 SourcingSource(label) — 양쪽 정리(하위호환).
    from lemouton.sourcing.models import SourcingSource
    s = SessionLocal()
    try:
        for r in s.query(SourcingSource).filter_by(label=name).all():
            s.delete(r)
        for r in s.query(SourcingSource).filter_by(label=name).all():
            s.delete(r)
        s.commit()
    finally:
        s.close()


def _find_src(label):
    """label 로 SourcingSource 1건(테스트 헬퍼)."""
    from lemouton.sourcing.models import SourcingSource
    s = SessionLocal()
    try:
        return s.query(SourcingSource).filter_by(label=label).first()
    finally:
        s.close()


def test_add_source_creates_registry_and_urls(client):
    _cleanup("테스트29")
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "테스트29",
        "urls": ["https://example.com/p/1", "https://example.com/p/2"],
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    s = SessionLocal()
    try:
        row = s.query(SourcingSource).filter_by(label="테스트29").first()
        assert row is not None
        guide = json.loads(row.crawl_guide)
        assert [u["url"] for u in guide["sample_urls"]] == \
            ["https://example.com/p/1", "https://example.com/p/2"]
        assert guide["sample_urls"][0]["is_lead"] is True
    finally:
        s.close()
    _cleanup("테스트29")


def test_add_source_rejects_empty_name(client):
    resp = client.post("/sourcing-guide/api/add-source", json={"name": "", "urls": []})
    assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────
#  Task 1 — update_requested 필드 검증 (기존 테스트)
# ─────────────────────────────────────────────────────────────────

def test_skeleton_has_update_requested_none():
    sk = cg.empty_skeleton()
    assert sk["update_requested"] is None


def test_validate_keeps_update_requested():
    g = cg.empty_skeleton()
    g["update_requested"] = {"at": "2026-06-29T00:00:00+00:00", "note": "재고 둔갑"}
    out = cg.validate_guide(g)
    assert out["update_requested"]["note"] == "재고 둔갑"
    assert out["update_requested"]["at"] == "2026-06-29T00:00:00+00:00"


def test_validate_rejects_bad_update_requested():
    g = cg.empty_skeleton()
    g["update_requested"] = "nope"          # dict 아님 → None 으로 정제
    out = cg.validate_guide(g)
    assert out["update_requested"] is None


def test_validate_caps_note_at_200():
    g = cg.empty_skeleton()
    g["update_requested"] = {"at": "2026-06-29T00:00:00+00:00", "note": "x" * 250}
    out = cg.validate_guide(g)
    assert len(out["update_requested"]["note"]) == 200


def test_validate_update_requested_missing_at_becomes_none():
    g = cg.empty_skeleton()
    g["update_requested"] = {"note": "사유만 있음"}
    out = cg.validate_guide(g)
    assert out["update_requested"]["at"] is None
    assert out["update_requested"]["note"] == "사유만 있음"


def test_add_source_invalid_url_returns_400(client):
    _cleanup("테스트나쁜URL")
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "테스트나쁜URL", "urls": ["not-a-real-url"]})
    assert resp.status_code == 400
    # 잘못된 URL 이면 행이 커밋되지 않아야 함(롤백)
    s = SessionLocal()
    try:
        assert s.query(SourcingSource).filter_by(label="테스트나쁜URL").first() is None
    finally:
        s.close()
    _cleanup("테스트나쁜URL")


def test_add_source_empty_urls_ok(client):
    _cleanup("테스트빈URL")
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "테스트빈URL", "urls": []})
    assert resp.status_code == 200
    assert resp.get_json()["url_count"] == 0
    _cleanup("테스트빈URL")


# ─────────────────────────────────────────────────────────────────
#  Task 3 — URL 편집 + 기존 업데이트 요청 API
# ─────────────────────────────────────────────────────────────────

def _make_source(name, urls):
    # [2026-06-30 단일명부] SourcingSource(label) 로 생성. source_key 자동 고유화.
    from lemouton.sourcing.models import SourcingSource
    import re as _re
    key = _re.sub(r'[^a-z0-9]', '', name.lower()) or 'tsrc'
    s = SessionLocal()
    try:
        base, n = key, 2
        while s.query(SourcingSource).filter_by(source_key=key).first():
            key, n = f"{base}{n}", n + 1
        src = SourcingSource(source_key=key, label=name, domain=key + '.example',
                             is_active=True, is_builtin=False, sort_order=999)
        s.add(src); s.flush()
        g = cg.empty_skeleton()
        g["sample_urls"] = [{"url": u, "is_lead": i == 0} for i, u in enumerate(urls)]
        src.crawl_guide = cg.dumps(g)
        s.commit()
        return src.id
    finally:
        s.close()


def test_save_urls_replaces_list(client):
    _cleanup("테스트URL")
    sid = _make_source("테스트URL", ["https://a.com/1"])
    resp = client.post(f"/sourcing-guide/api/{sid}/save-urls", json={
        "urls": ["https://a.com/2", "https://a.com/3"]})
    assert resp.status_code == 200
    s = SessionLocal()
    try:
        g = json.loads(s.query(SourcingSource).get(sid).crawl_guide)
        assert [u["url"] for u in g["sample_urls"]] == ["https://a.com/2", "https://a.com/3"]
    finally:
        s.close()
    _cleanup("테스트URL")


def test_request_update_sets_flag(client):
    _cleanup("테스트UPD")
    sid = _make_source("테스트UPD", ["https://a.com/1"])
    resp = client.post(f"/sourcing-guide/api/{sid}/request-update", json={"note": "재고 둔갑"})
    assert resp.status_code == 200
    s = SessionLocal()
    try:
        g = json.loads(s.query(SourcingSource).get(sid).crawl_guide)
        assert g["update_requested"]["note"] == "재고 둔갑"
    finally:
        s.close()
    _cleanup("테스트UPD")


# ─────────────────────────────────────────────────────────────────
#  Task 4 — 분석 대기 큐 식별 헬퍼 + API  /sourcing-guide/api/queue
# ─────────────────────────────────────────────────────────────────

def test_queue_lists_pending(client):
    _cleanup("테스트큐")
    sid = _make_source("테스트큐", ["https://a.com/1"])   # 카드 빈 + URL 있음 = 신규 대기
    resp = client.get("/sourcing-guide/api/queue")
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    hit = [it for it in items if it["id"] == sid]
    assert hit and hit[0]["kind"] == "new"
    _cleanup("테스트큐")


# ─────────────────────────────────────────────────────────────────
#  Task 5 — /add 페이지 렌더 스모크 테스트
# ─────────────────────────────────────────────────────────────────

def test_add_page_renders(client):
    resp = client.get("/sourcing-guide/add")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "소싱처 추가" in body
    assert "신규 소싱처 추가" in body
    assert "기존 소싱처 크롤 업데이트" in body


# ─────────────────────────────────────────────────────────────────
#  Task 6 — 전체보기 4번째 카드 + 분석 대기 배지
# ─────────────────────────────────────────────────────────────────

def test_overview_has_add_card(client):
    resp = client.get("/sourcing-guide/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "/sourcing-guide/add" in body
    assert "소싱처 추가·업데이트" in body


def test_overview_shows_pending_badge(client):
    _cleanup("테스트배지")
    _make_source("테스트배지", ["https://a.com/1"])   # 빈 카드 + URL = 분석 대기
    resp = client.get("/sourcing-guide/")
    body = resp.get_data(as_text=True)
    assert "분석 대기" in body
    _cleanup("테스트배지")


# ─────────────────────────────────────────────────────────────────
#  존재검사 게이트 — 도메인 기준 중복 차단 (hmall 중복 교훈)
# ─────────────────────────────────────────────────────────────────

def test_add_source_blocks_builtin_domain(client):
    """빌트인 크롤지원 소싱처(hmall.com)를 신규로 넣으면 409 exists=builtin."""
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "현대몰중복테스트",
        "urls": ["https://www.hmall.com/md/pda/itemPtc?slitmCd=1"],
    })
    assert resp.status_code == 409
    d = resp.get_json()
    assert d["ok"] is False and d["exists"] is True
    assert d["existing"]["kind"] == "builtin" and d["existing"]["key"] == "hmall"
    # 생성 안 됐어야 함
    s = SessionLocal()
    try:
        assert s.query(SourcingSource).filter_by(label="현대몰중복테스트").first() is None
    finally:
        s.close()


def test_add_source_blocks_registered_domain(client):
    """이미 등록된 소싱처와 같은 도메인 URL 이면 409 exists=registered."""
    _cleanup("도메인원본")
    _cleanup("도메인중복")
    client.post("/sourcing-guide/api/add-source", json={
        "name": "도메인원본", "urls": ["https://shop-xyz.example/p/1"]})
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "도메인중복", "urls": ["https://shop-xyz.example/p/2"]})
    assert resp.status_code == 409
    d = resp.get_json()
    assert d["exists"] is True and d["existing"]["kind"] == "registered"
    assert d["existing"]["name"] == "도메인원본"
    _cleanup("도메인원본")
    _cleanup("도메인중복")


def test_add_source_force_bypasses_gate(client):
    """force=True 면 게이트 무시하고 강행 생성."""
    _cleanup("강제추가테스트")
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "강제추가테스트",
        "urls": ["https://www.hmall.com/md/pda/itemPtc?slitmCd=2"], "force": True})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    _cleanup("강제추가테스트")


# ─────────────────────────────────────────────────────────────────
#  중복 정리 — merge-into (빈 카드만 안전 병합·삭제)
# ─────────────────────────────────────────────────────────────────

def test_merge_into_moves_urls_and_deletes_blank(client):
    _cleanup("병합타겟"); _cleanup("병합중복")
    client.post("/sourcing-guide/api/add-source", json={
        "name": "병합타겟", "urls": ["https://m-xyz.example/a"], "force": True})
    client.post("/sourcing-guide/api/add-source", json={
        "name": "병합중복", "urls": ["https://m-xyz.example/b"], "force": True})
    s = SessionLocal()
    try:
        tgt = s.query(SourcingSource).filter_by(label="병합타겟").first()
        dup = s.query(SourcingSource).filter_by(label="병합중복").first()
        tid, did = tgt.id, dup.id
    finally:
        s.close()
    resp = client.post(f"/sourcing-guide/api/{did}/merge-into/{tid}")
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    s = SessionLocal()
    try:
        assert s.query(SourcingSource).get(did) is None          # 중복 삭제됨
        guide = cg.loads(s.query(SourcingSource).get(tid).crawl_guide)
        urls = {u["url"] for u in guide["sample_urls"]}
        assert urls == {"https://m-xyz.example/a", "https://m-xyz.example/b"}
    finally:
        s.close()
    _cleanup("병합타겟")


def test_merge_into_refuses_nonblank_source(client):
    """크롤 정의가 있는 소싱처는 안전상 병합 거부."""
    _cleanup("병합타겟2"); _cleanup("정의있음")
    client.post("/sourcing-guide/api/add-source", json={
        "name": "병합타겟2", "urls": ["https://t2.example/a"], "force": True})
    client.post("/sourcing-guide/api/add-source", json={
        "name": "정의있음", "urls": ["https://t2.example/b"], "force": True})
    s = SessionLocal()
    try:
        tgt = s.query(SourcingSource).filter_by(label="병합타겟2").first()
        nb = s.query(SourcingSource).filter_by(label="정의있음").first()
        # 정의있음 카드를 non-blank 로 만듦(thumbnail status=ok)
        g = cg.loads(nb.crawl_guide)
        g["fields"]["thumbnail"]["status"] = "ok"
        nb.crawl_guide = cg.dumps(g)
        s.commit()
        tid, nid = tgt.id, nb.id
    finally:
        s.close()
    resp = client.post(f"/sourcing-guide/api/{nid}/merge-into/{tid}")
    assert resp.status_code == 400
    s = SessionLocal()
    try:
        assert s.query(SourcingSource).get(nid) is not None       # 삭제 안 됨
    finally:
        s.close()
    _cleanup("병합타겟2"); _cleanup("정의있음")

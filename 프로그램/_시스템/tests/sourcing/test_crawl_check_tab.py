import os

import pytest

# webapp/templates 절대 경로 — tests/sourcing/ 에서 ../../webapp/templates
_TMPL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "webapp", "templates")
)


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


def test_crawl_check_kinds_and_prompts(client):
    """검사 종류 세그먼트(재고/가격/재고+가격) + 세 프롬프트 본문이 있는지."""
    r = client.get("/sourcing-guide/crawl-check")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    # 검사 종류 세그먼트 (탭 없앤 통합 — 종류 선택기)
    assert "재고 정합성" in body
    assert "가격 정합성" in body
    assert "재고+가격" in body
    # 재고 프롬프트
    assert "재고 정합성 조사를 시작한다" in body
    assert "품절둔갑" in body
    assert "999·센티넬" in body
    assert "귀책" in body
    assert "/data-guide" in body
    assert "InventoryTx" in body
    # 가격 프롬프트 (3층·증상)
    assert "가격 정합성 조사를 시작한다" in body
    assert "표면노출가" in body
    assert "언더프라이싱" in body
    assert "셀≠계산식" in body


def test_crawl_check_stock_prompt_self_sufficient(client):
    """재고 프롬프트 자기충분성 보강 — 클린 세션이 프롬프트만으로 끝낼 수 있게:
    ① 프로그램 저장값·URL 을 어디서 읽는지(매트릭스 API) ② 크롤을 Claude 가 로컬 PC
    브라우저로 직접 돌린다 ③ 정본 가이드 경로 정확 ④ 먼저 origin/main 최신에서."""
    r = client.get("/sourcing-guide/crawl-check")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    # ① 대상 불러오기 — 매트릭스 API (로그인 불필요) 를 명시
    assert "option-matrix" in body
    # ② 크롤 = 사용자 로컬 PC 브라우저를 Claude 가 직접 구동 (서버/CLI 크롤 아님)
    assert "로컬 PC" in body
    assert "Claude-in-Chrome" in body or "로그인된 크롬" in body
    # 최신화 전 다음 단계 금지 (오래된 값 대조 = 품절둔갑) — 무결성 가드
    assert "최신화 전" in body or "완료 신호" in body
    # ③ 정본 가이드 경로 정확 (stale orphan docs/ 가 아닌 캐노니컬 경로)
    assert "프로그램/_시스템/docs/크롤링-가이드.md" in body
    # ④ 먼저 origin/main 최신에서 작업 — 파일 읽기 전 반드시 전환(단순 조회여도), stale orphan 경고
    assert "git fetch origin main" in body
    assert "파일 읽기 전 반드시" in body
    assert "stale orphan" in body


def test_crawl_check_price_prompt_self_sufficient(client):
    """가격 프롬프트 보강 — 클린 세션이 프롬프트만으로:
    ① 최종매입가·계산식은 매트릭스가 아니라 별도 브레이크다운 API 라는 것 ② purchase_final_price
    는 옵션 템플릿값(대조 금지) ③ 혜택 층 없는 소싱처 존재 를 알 수 있게."""
    r = client.get("/sourcing-guide/crawl-check")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    # 최종매입가·계산식 = 별도 브레이크다운 API (매트릭스 아님)
    assert "/api/source-benefits/breakdown/" in body
    # purchase_final_price 는 템플릿값이지 소싱처 최종매입가 아님 (혼동 금지)
    assert "purchase_final_price" in body and "템플릿" in body
    # 혜택 층 없는 소싱처 경고
    assert "혜택 층 없는 소싱처" in body


def test_crawl_check_both_prompt_chunked_execution(client):
    """재고+가격 = 한 프롬프트지만 '나눠서 실행'(소싱처 1개씩·단계 1개씩) 지시."""
    r = client.get("/sourcing-guide/crawl-check")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "반드시 나눠서" in body
    assert "소싱처 1개씩" in body
    # 재고+가격도 최종매입가는 별도 breakdown API 로
    assert body.count("/api/source-benefits/breakdown/") >= 2
    # 게이트 = 엑셀 파일 형식이 아니라 '재고 판정·집계 완료' (하드 .xlsx 게이트 완화)
    assert "재고 판정·집계 완료" in body
    assert "재고 엑셀까지 마친" not in body


def test_crawl_check_scope_selector_present(client):
    """검사 범위 선택(모음전+소싱처 + 전체 선택) UI + 대상 주입 지점."""
    r = client.get("/sourcing-guide/crawl-check")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "무슨 검사를 할까요" in body                   # 종류 선택 안내
    assert "/api/bundles/with-sources" in body          # 모음전+소싱처 목록 로드
    assert "프롬프트 만들기" in body
    assert "전체 선택" in body                            # 전체 선택
    assert 'id="ccTargetStock"' in body
    assert 'id="ccTargetPrice"' in body
    assert 'id="ccTargetBoth"' in body


def test_crawl_check_both_sequential(client):
    """재고+가격 = 순차 지시(재고 먼저 → 가격, 동시 금지)."""
    r = client.get("/sourcing-guide/crawl-check")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "반드시 순서대로" in body
    assert "[1단계] 재고" in body and "[2단계] 가격" in body
    assert "동시 진행 금지" in body


def test_crawl_check_bare_sets_sameorigin(client):
    r = client.get("/sourcing-guide/crawl-check?bare=1")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_overview_has_crawl_check_card(client):
    r = client.get("/sourcing-guide/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'data-guide-modal="/sourcing-guide/crawl-check?bare=1"' in body
    assert "크롤링 검사" in body

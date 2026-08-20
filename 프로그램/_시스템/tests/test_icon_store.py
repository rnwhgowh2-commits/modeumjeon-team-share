"""[TEST] icon_store 영속화 회귀 테스트 — DB(BrandColorOverride) 기반.

버그(원래): 모드 전환 아이콘 변경이 새로고침 후 되돌아감(인메모리 stub).
수정 이력: ① data/icon_overrides.json 파일 영속화 → ② v34.11 DB(BrandColorOverride,
  Supabase/SQLite) 영속화로 재리팩터(Fly.io 멀티 인스턴스 휘발 방지).
이 테스트는 ②(현재 구현)에 맞춰 DB 기준으로 갱신. (구 버전은 사라진 _STORE_PATH
  JSON 파일을 monkeypatch 해 stale·에러였음.)
검증 행동은 동일: set/get/clear/list 영속.
"""
import os
import pytest

os.environ.setdefault("ENVIRONMENT", "test")

CTX = "test_iconstore"   # 실데이터와 겹치지 않는 전용 컨텍스트


@pytest.fixture
def store():
    import webapp.icon_store_model  # noqa: F401  (BrandColorOverride 테이블 등록)
    from shared.db import Base, engine
    Base.metadata.create_all(engine)
    from webapp import icon_store
    icon_store._invalidate_icons_cache()
    yield icon_store
    # 정리 — 이 테스트가 만든 CTX 행만 제거 + 캐시 무효화
    from shared.db import SessionLocal
    from webapp.icon_store_model import BrandColorOverride
    s = SessionLocal()
    try:
        s.query(BrandColorOverride).filter(
            BrandColorOverride.context == CTX).delete(synchronize_session=False)
        s.commit()
    finally:
        s.close()
    icon_store._invalidate_icons_cache()


def test_set_icon_persists(store):
    """set_icon 후 get_icon 이 저장값 반환 (매 호출 새 세션으로 DB fresh 조회)."""
    store.set_icon(CTX, 'inventory', '🎁', 'default')
    assert store.get_icon(CTX, 'inventory') == {'icon': '🎁', 'color': 'default'}


def test_set_icon_persists_to_db(store):
    """변경이 실제 DB 행으로 기록 — 새 세션 조회로도 유지(서버 재시작 무관)."""
    store.set_icon(CTX, 'bundles', '🛒', 'blue')
    from shared.db import SessionLocal
    from webapp.icon_store_model import BrandColorOverride
    s = SessionLocal()
    try:
        row = (s.query(BrandColorOverride)
               .filter_by(context=CTX, target_id='bundles').one_or_none())
        assert row is not None
        assert row.icon == '🛒' and row.color == 'blue'
    finally:
        s.close()


def test_clear_icon_persists(store):
    """clear_icon(삭제)도 DB 에 반영 — 재조회 시 None."""
    store.set_icon(CTX, 'inventory', '🎁', 'default')
    store.clear_icon(CTX, 'inventory')
    assert store.get_icon(CTX, 'inventory') is None


def test_list_icons_reflects_db(store):
    """list_icons 도 DB 상태 반영 (set_icon 이 TTL 캐시 무효화)."""
    store.set_icon(CTX, 'inventory', '🎁', 'red')
    icons = store.list_icons()
    assert icons.get(CTX, {}).get('inventory') == {'icon': '🎁', 'color': 'red'}


def test_get_icon_missing_returns_none(store):
    """저장값 없으면 None (템플릿이 기본 이모지로 폴백)."""
    assert store.get_icon(CTX, 'inventory') is None

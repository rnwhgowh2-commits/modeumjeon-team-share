"""[TEST] icon_store 영속화 회귀 테스트.

버그: 모드 전환 아이콘(재고관리/모음전) 이모지 변경이 탭 이동(페이지 새로고침)
      후 원래대로 되돌아감.
원인: icon_store 가 인메모리 stub — 변경을 디스크에 저장하지 않아
      서버 재시작·새 요청 시 기본값으로 복귀.
수정: data/icon_overrides.json 으로 atomic 영속화. 매 호출 fresh 로드라
      서버 재시작·멀티워커와 무관하게 항상 디스크 상태를 반영.
"""
import json

import pytest

from webapp import icon_store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """실제 data 파일을 건드리지 않도록 임시 경로로 격리."""
    monkeypatch.setattr(icon_store, '_STORE_PATH', tmp_path / 'icon_overrides.json')
    return icon_store


def test_set_icon_persists(isolated_store):
    """set_icon 후 get_icon 이 저장값을 반환 (매 호출 디스크 fresh 로드)."""
    isolated_store.set_icon('mode', 'inventory', '🎁', 'default')
    assert isolated_store.get_icon('mode', 'inventory') == {'icon': '🎁', 'color': 'default'}


def test_set_icon_writes_file(isolated_store):
    """변경이 실제 JSON 파일로 기록돼 서버 재시작 후에도 유지."""
    isolated_store.set_icon('mode', 'bundles', '🛒', 'blue')
    assert isolated_store._STORE_PATH.exists()
    saved = json.loads(isolated_store._STORE_PATH.read_text(encoding='utf-8'))
    assert saved['mode']['bundles'] == {'icon': '🛒', 'color': 'blue'}


def test_clear_icon_persists(isolated_store):
    """clear_icon(삭제)도 디스크에 반영 — 재시작 후에도 삭제 상태 유지."""
    isolated_store.set_icon('mode', 'inventory', '🎁', 'default')
    isolated_store.clear_icon('mode', 'inventory')
    assert isolated_store.get_icon('mode', 'inventory') is None


def test_list_icons_reflects_disk(isolated_store):
    """list_icons 도 디스크 상태를 반영."""
    isolated_store.set_icon('mode', 'inventory', '🎁', 'red')
    icons = isolated_store.list_icons()
    assert icons.get('mode', {}).get('inventory') == {'icon': '🎁', 'color': 'red'}


def test_get_icon_missing_returns_none(isolated_store):
    """저장값 없으면 None (템플릿이 기본 이모지로 폴백)."""
    assert isolated_store.get_icon('mode', 'inventory') is None

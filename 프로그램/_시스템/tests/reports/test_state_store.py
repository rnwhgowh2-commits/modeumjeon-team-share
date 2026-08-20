# -*- coding: utf-8 -*-
"""배포를 견디는 상태 저장 위치.

라이브(AWS Lightsail)는 배포마다 앱 컨테이너를 새로 만든다. 앱 안 ``data/`` 에
쓴 파일은 배포 즉시 사라지고, 그러면 ① 카카오 갱신 토큰이 날아가 재로그인을
해야 하고 ② 어제 스냅샷이 없어 그날이 「첫 실행」으로 오인돼 보고가 빠진다.
"""
from __future__ import annotations

import importlib
import json

import pytest

from shared import state_store


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MOUM_STATE_DIR", raising=False)
    monkeypatch.delenv("MOUM_SECRETS_ENV", raising=False)
    yield


def test_마운트된_시크릿폴더를_기본으로_쓴다(tmp_path, monkeypatch):
    """MOUM_SECRETS_ENV 는 파일 경로 — 그 부모가 호스트에 마운트된 폴더다."""
    env_file = tmp_path / "mounted" / ".env"
    monkeypatch.setenv("MOUM_SECRETS_ENV", str(env_file))
    assert state_store.state_dir() == tmp_path / "mounted"


def test_명시_지정이_시크릿폴더보다_우선(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_SECRETS_ENV", str(tmp_path / "a" / ".env"))
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path / "b"))
    assert state_store.state_dir() == tmp_path / "b"


def test_폴더가_없으면_만든다(tmp_path, monkeypatch):
    target = tmp_path / "새폴더" / "안쪽"
    monkeypatch.setenv("MOUM_STATE_DIR", str(target))
    assert state_store.state_dir().exists()


def test_아무것도_없으면_임시라고_알린다():
    """라이브에서 True 면 설정이 잘못된 것 — 화면이 경고를 띄운다."""
    assert state_store.is_ephemeral() is True


def test_설정되면_임시가_아니다(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    assert state_store.is_ephemeral() is False


# ──────────────────────────────────────────────────────────────
# 실제로 그 폴더에 쓰는지
# ──────────────────────────────────────────────────────────────
def test_카카오_토큰이_영속폴더에_저장된다(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    kt = importlib.import_module("shared.kakao_token")
    monkeypatch.setattr(kt, "_TOKEN_PATH", None)   # 실경로 로직을 타게

    kt._save({"access_token": "A", "refresh_token": "R"})

    written = tmp_path / "kakao_token.json"
    assert written.exists(), "배포 때 날아가는 자리에 쓰고 있다"
    assert json.loads(written.read_text(encoding="utf-8"))["refresh_token"] == "R"


def test_스냅샷이_영속폴더에_저장된다(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    nt = importlib.import_module("lemouton.reports.notion_todo")
    monkeypatch.setattr(nt, "_SNAPSHOT_PATH", None)

    nt.save_snapshot([{"id": "a", "text": "할일", "checked": False}],
                     sent_date="2026-08-01")

    written = tmp_path / "notion_todo_snapshot.json"
    assert written.exists(), "배포 때 날아가는 자리에 쓰고 있다"
    assert json.loads(written.read_text(encoding="utf-8"))["sent_date"] == "2026-08-01"


def test_배포_시뮬레이션_토큰이_살아남는다(tmp_path, monkeypatch):
    """컨테이너가 갈려도(모듈 재로딩) 마운트 폴더의 토큰은 그대로여야 한다."""
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    kt = importlib.import_module("shared.kakao_token")
    monkeypatch.setattr(kt, "_TOKEN_PATH", None)
    kt._save({"access_token": "A", "refresh_token": "REFRESH-KEEP"})

    # 배포 = 프로세스 교체. 모듈을 새로 읽어들여 흉내낸다.
    kt2 = importlib.reload(kt)
    monkeypatch.setattr(kt2, "_TOKEN_PATH", None)

    assert kt2._load()["refresh_token"] == "REFRESH-KEEP"

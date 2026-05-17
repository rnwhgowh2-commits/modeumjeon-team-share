"""판매처 셀러 포털 ID/PW 저장소.

설계:
  · 단일 JSON 파일 ``data/upload_credentials.json``
  · 구조: ``{env_prefix: {id, pw, login_method}}``
  · API 키(.env)와 별개 — 셀러 포털 브라우저 로그인용 (쿠팡 Wing, 스마트스토어 셀러센터 등)
  · ``.gitignore`` 등록 필수
  · 평문 저장 (단일 머신·단일 사용자)

소싱처와 분리한 이유:
  · 소싱처 = 사이트 키(musinsa, ssf...) 기반
  · 판매처 = env_prefix(COUPANG_MAIN, SMARTSTORE_MAIN...) 기반
  · 스토어 구조가 달라서 분리
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from filelock import FileLock

logger = logging.getLogger(__name__)


def _mask_id(value: Optional[str]) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return value[0] + "***"
    return f"{value[:2]}***{value[-2:]}"


class UploadCredentialsStore:
    """``data/upload_credentials.json`` 읽기/쓰기 — env_prefix 기반."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _load_unlocked(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[upload_creds] 손상 — 빈 dict 반환: %s", e)
            return {}

    def load_all(self) -> dict:
        with FileLock(str(self._lock_path), timeout=5):
            return self._load_unlocked()

    def get(self, env_prefix: str) -> Optional[dict]:
        all_creds = self.load_all()
        return all_creds.get(env_prefix)

    def upsert(
        self,
        env_prefix: str,
        id_value: str,
        pw_value: str,
        *,
        login_method: str = "direct",
    ) -> dict:
        if not env_prefix or not env_prefix.strip():
            raise ValueError("env_prefix 비어있음")
        if not id_value or not id_value.strip():
            raise ValueError("id 비어있음")
        if not pw_value or not pw_value.strip():
            raise ValueError("pw 비어있음")

        with FileLock(str(self._lock_path), timeout=5):
            all_creds = self._load_unlocked()
            all_creds[env_prefix] = {
                "id": id_value.strip(),
                "pw": pw_value.strip(),
                "login_method": login_method,
            }
            self._atomic_write(all_creds)

        logger.info("[upload_creds] upsert — %s id=%s", env_prefix, _mask_id(id_value))
        return {
            "env_prefix": env_prefix,
            "id_masked": _mask_id(id_value),
            "login_method": login_method,
        }

    def remove(self, env_prefix: str) -> bool:
        with FileLock(str(self._lock_path), timeout=5):
            all_creds = self._load_unlocked()
            if env_prefix in all_creds:
                del all_creds[env_prefix]
                self._atomic_write(all_creds)
                return True
            return False

    def list_summary(self) -> list[dict]:
        all_creds = self.load_all()
        rows = []
        for env_prefix, creds in all_creds.items():
            pw = creds.get("pw") or ""
            rows.append({
                "env_prefix": env_prefix,
                "id_masked": _mask_id(creds.get("id")),
                "login_method": creds.get("login_method", "direct"),
                "has_pw": bool(pw),
                "pw_length": len(pw),
            })
        return rows

    def _atomic_write(self, data: dict) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".upload_creds.tmp.",
            suffix=".json",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, self.path)


def default_store() -> UploadCredentialsStore:
    project_root = Path(__file__).resolve().parents[2]
    return UploadCredentialsStore(project_root / "data" / "upload_credentials.json")

"""소싱처 회원 ID/PW 저장소 — 송장전송기 settings.json 패턴.

설계:
  · 단일 JSON 파일 ``data/sourcing_credentials.json``
  · 구조: ``{source: {account_key: {id, pw}}}``
  · filelock 으로 동시성 보호
  · ``.gitignore`` 등록 (커밋 사고 방지)
  · 비밀번호는 평문 저장 (단일 머신·단일 사용자 — 송장전송기와 동일)
  · 화면 표시는 항상 마스킹 (``id_masked``, pw 는 절대 반환 안 함)

Phase 2-C 활성화 시:
  · ``LoginWizard`` 가 이 파일에서 ID/PW 읽음 → Playwright headless=False 로 자동 로그인 시도
  · 봇 탐지 시 사용자 직접 입력 모드로 전환
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


class SourcingCredentialsStore:
    """``data/sourcing_credentials.json`` 읽기/쓰기 — 단일 진실 원천."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _load_unlocked(self) -> dict:
        """잠금 없이 파일 읽기 — 내부 호출 (lock 보유 중일 때) 전용."""
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[sourcing_creds] 손상 — 빈 dict 반환: %s", e)
            return {}

    def load_all(self) -> dict:
        """전체 자격증명 딕셔너리 반환 — 파일 없으면 빈 dict."""
        with FileLock(str(self._lock_path), timeout=5):
            return self._load_unlocked()

    def get(self, source: str, account_key: str = "default") -> Optional[dict]:
        """단일 자격증명 반환 — 없으면 None."""
        all_creds = self.load_all()
        return all_creds.get(source, {}).get(account_key)

    def upsert(
        self,
        source: str,
        account_key: str,
        id_value: str,
        pw_value: str,
        *,
        login_method: str = "direct",
    ) -> dict:
        """단일 자격증명 추가/갱신.

        Args:
            source: "musinsa" | "ssf" | "lemouton" 등
            account_key: "default" 또는 사용자 정의
            id_value: 회원 ID (이메일/아이디)
            pw_value: 비밀번호 (평문 저장)
            login_method: "direct" (자동) | "manual" (사용자 직접 로그인)

        Returns:
            저장된 자격증명 (마스킹된 형태)

        Raises:
            ValueError: 빈 값 거부
        """
        if not source or not source.strip():
            raise ValueError("source 비어있음")
        if not account_key:
            account_key = "default"
        if not id_value or not id_value.strip():
            raise ValueError("id 비어있음")
        if not pw_value or not pw_value.strip():
            raise ValueError("pw 비어있음")

        with FileLock(str(self._lock_path), timeout=5):
            all_creds = self._load_unlocked()
            all_creds.setdefault(source, {})[account_key] = {
                "id": id_value.strip(),
                "pw": pw_value.strip(),
                "login_method": login_method,
            }
            self._atomic_write(all_creds)

        logger.info(
            "[sourcing_creds] upsert — %s/%s id=%s",
            source, account_key, _mask_id(id_value),
        )
        return {
            "source": source,
            "account_key": account_key,
            "id_masked": _mask_id(id_value),
            "login_method": login_method,
        }

    def remove(self, source: str, account_key: str = "default") -> bool:
        """자격증명 삭제 — 있었으면 True."""
        with FileLock(str(self._lock_path), timeout=5):
            all_creds = self._load_unlocked()
            if source in all_creds and account_key in all_creds[source]:
                del all_creds[source][account_key]
                if not all_creds[source]:
                    del all_creds[source]
                self._atomic_write(all_creds)
                return True
            return False

    def list_summary(self) -> list[dict]:
        """전체 목록 요약 — pw 값 절대 반환 X (자릿수만 노출)."""
        all_creds = self.load_all()
        rows = []
        for source, accounts in all_creds.items():
            for account_key, creds in accounts.items():
                pw = creds.get("pw") or ""
                rows.append({
                    "source": source,
                    "account_key": account_key,
                    "id_masked": _mask_id(creds.get("id")),
                    "login_method": creds.get("login_method", "direct"),
                    "has_pw": bool(pw),
                    "pw_length": len(pw),  # 자릿수만 (값은 절대 노출 X)
                })
        return rows

    def _atomic_write(self, data: dict) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".sourcing_creds.tmp.",
            suffix=".json",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, self.path)


def default_store() -> SourcingCredentialsStore:
    """기본 store — ``data/sourcing_credentials.json``."""
    project_root = Path(__file__).resolve().parents[2]
    return SourcingCredentialsStore(project_root / "data" / "sourcing_credentials.json")

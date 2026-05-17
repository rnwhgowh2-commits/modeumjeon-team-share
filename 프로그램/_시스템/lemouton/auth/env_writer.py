"""`.env` 파일 안전 쓰기 — UI에서 시크릿 입력 시 사용.

설계:
  · 기존 .env 의 다른 키는 모두 보존 (업데이트할 prefix 만 수정)
  · atomic write: tempfile 작성 → os.replace
  · 파일 없으면 새로 생성
  · 빈 값은 거부 (실수 방지)
  · filelock 으로 동시성 보호
  · 저장 후 ``load_dotenv(override=True)`` 호출 → 환경변수 즉시 반영

보안:
  · 입력 값은 마스킹된 형태로만 로그에 남김
  · 검증 실패 시 명확한 에러 (어떤 키가 비었는지)
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Mapping

from filelock import FileLock
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class EnvWriteError(RuntimeError):
    """``.env`` 파일 쓰기 실패."""


def _mask(value: str) -> str:
    """로그용 마스킹 — 앞 3 + ★★★ + 뒤 3."""
    if not value:
        return "<empty>"
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


def update_env_keys(
    env_path: Path,
    keys: Mapping[str, str],
    *,
    require_non_empty: bool = True,
) -> dict[str, str]:
    """``.env`` 의 키들을 업데이트 — 다른 키는 보존.

    Args:
        env_path: ``.env`` 파일 경로 (없으면 생성)
        keys: ``{"SMARTSTORE_MAIN_CLIENT_ID": "value", ...}``
        require_non_empty: True 면 빈 값 거부

    Returns:
        업데이트된 키 → 마스킹 값 매핑

    Raises:
        EnvWriteError: 빈 값 거부 / 쓰기 실패 / 잠금 실패
    """
    if not keys:
        raise EnvWriteError("업데이트할 키가 없습니다")

    if require_non_empty:
        empty = [k for k, v in keys.items() if not v or not v.strip()]
        if empty:
            raise EnvWriteError(f"빈 값 입력 거부: {empty}")

    env_path = Path(env_path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = env_path.with_suffix(env_path.suffix + ".lock")

    masked = {k: _mask(v) for k, v in keys.items()}

    with FileLock(str(lock_path), timeout=5):
        # 1) 기존 라인 읽기
        existing_lines: list[str] = []
        if env_path.exists():
            try:
                existing_lines = env_path.read_text(encoding="utf-8").splitlines()
            except Exception as e:
                raise EnvWriteError(f"기존 .env 읽기 실패: {e}")

        # 2) 라인별 처리: 같은 키 만나면 새 값으로 교체, 없으면 보존
        seen_keys = set()
        new_lines: list[str] = []
        for line in existing_lines:
            stripped = line.strip()
            # 주석 / 빈 줄 보존
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            # KEY=VALUE 파싱
            if "=" in line:
                k = line.split("=", 1)[0].strip()
                if k in keys:
                    seen_keys.add(k)
                    new_lines.append(f"{k}={keys[k]}")
                    continue
            new_lines.append(line)

        # 3) 새 키 추가 (기존 .env 에 없던 키)
        new_keys_to_append = {k: v for k, v in keys.items() if k not in seen_keys}
        if new_keys_to_append:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")  # 보기 좋게 빈 줄
            new_lines.append("# UI에서 추가한 시크릿")
            for k, v in new_keys_to_append.items():
                new_lines.append(f"{k}={v}")

        content = "\n".join(new_lines) + "\n"

        # 4) atomic write — tempfile + os.replace
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=env_path.parent,
                prefix=".env.tmp.",
                delete=False,
            ) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, env_path)
        except Exception as e:
            raise EnvWriteError(f".env 저장 실패: {e}")

        logger.info(
            "[env_writer] %s 업데이트 — %d 키",
            env_path.name,
            len(keys),
        )
        for k, m in masked.items():
            logger.info("  · %s = %s", k, m)

    # 5) 환경변수 즉시 반영 (override=True 가 핵심 — 이미 import된 값도 갱신)
    load_dotenv(env_path, override=True)

    return masked

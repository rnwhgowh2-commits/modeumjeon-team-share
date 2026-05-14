"""DLQ — 실패 호출을 logs/lemouton_dlq.jsonl에 적재 + 사용자 재시도용."""
import json
import os
from datetime import datetime, timezone


def enqueue_dlq(path: str, item: dict) -> None:
    """item에 timestamp 추가 후 jsonl 한 줄 append."""
    payload = dict(item)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def list_dlq(path: str) -> list[dict]:
    """파일 전체 읽어 list 반환. 없으면 빈 리스트."""
    if not os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items

"""R2(S3 호환) 오브젝트 스토리지 어댑터 — "창고 직원".

호출부(업로드 라우트)는 R2를 몰라도 된다. 저장/삭제/URL계산만 시킨다.

가공 seam: put_object(processors=[...]) 의 processors 는 bytes->bytes 함수 목록.
지금은 호출부에서 안 넘기므로 그냥 통과. 미래에 resize/watermark 함수를 끼우면 됨.
"""
import threading
from typing import Callable, List, Optional

import boto3
from botocore.config import Config as BotoConfig

from config import Config

Processor = Callable[[bytes], bytes]

# 확장자 → Content-Type (브라우저가 이미지로 인식하도록)
_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "csv": "text/csv", "txt": "text/plain",
}

_client = None  # 지연 생성 후 모듈 캐시
_client_lock = threading.Lock()


def _get_client():
    """boto3 S3 클라이언트(R2 엔드포인트). 최초 1회 생성 후 재사용. 테스트는 이 함수를 monkeypatch."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = boto3.client(
                    "s3",
                    endpoint_url=f"https://{Config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
                    aws_access_key_id=Config.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,
                    config=BotoConfig(signature_version="s3v4"),
                    region_name="auto",
                )
    return _client


def public_url(key: str) -> str:
    """key의 공개 URL 계산(네트워크 호출 없음)."""
    base = Config.R2_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/{key}"


def put_object(data: bytes, key: str, content_type: str,
               *, processors: Optional[List[Processor]] = None) -> str:
    """processors를 순서대로 통과시킨 뒤 R2에 업로드, 공개 URL 반환."""
    for proc in (processors or []):
        data = proc(data)
    _get_client().put_object(
        Bucket=Config.R2_BUCKET, Key=key, Body=data, ContentType=content_type,
    )
    return public_url(key)


def put_upload(file_storage, key: str,
               *, processors: Optional[List[Processor]] = None) -> str:
    """Flask FileStorage 편의 래퍼 — 확장자로 Content-Type 추론 후 put_object.

    스트림을 항상 선두(seek 0)부터 읽으므로, 호출부가 size 계산 등으로
    위치를 옮겼더라도 안전하다. Content-Type은 key 확장자로 추론하며,
    확장자가 없으면 application/octet-stream 으로 폴백한다.
    """
    file_storage.seek(0)
    data = file_storage.read()
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
    return put_object(data, key, content_type, processors=processors)


def delete_object(key: str) -> None:
    """R2에서 key 삭제(존재하지 않아도 에러 없음)."""
    _get_client().delete_object(Bucket=Config.R2_BUCKET, Key=key)

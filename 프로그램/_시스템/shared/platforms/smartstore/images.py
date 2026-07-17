# -*- coding: utf-8 -*-
"""스마트스토어 상품 이미지 업로드 → 네이버 CDN URL.

스스는 shop-phinf.pstatic.net CDN URL 만 상품 등록에 받는다(외부 URL 거부).
쿠팡은 공개 URL(R2 등)을 그대로 받으므로 이 단계가 필요 없다.

공식 규격 출처 (2026-07-17 확인):
  https://github.com/commerce-api-naver/commerce-api/discussions/117
  POST /v1/product-images/upload (multipart/form-data) → {images: [{url}]}
  · 폼 이름은 여러 장이어도 전부 'imageFiles'
  · 본문 Content-Type 은 '저장된 실제 포맷' 의 MIME (확장자 아님)
  · 1 호출당 최대 10장, 합계 10MB 미만, JPEG/GIF/PNG/BMP 만
  · ★ 스토어 계정당 동시 1건 — 이전 응답 전에 또 부르면 '이전 요청이 진행중입니다.'
"""
import logging
import threading

logger = logging.getLogger(__name__)

# 공식: 여러 장이어도 name 어트리뷰트는 전부 동일해야 한다.
_MULTIPART_FIELD = 'imageFiles'
_MAX_FILES = 10
_MAX_TOTAL_BYTES = 10 ** 7   # 10MB '미만'

# 매직 넘버 → MIME. imghdr 는 Python 3.13 에서 제거돼 쓸 수 없고, 확장자·mimetypes 는
# 공식 규격('저장된 실제 포맷 기준')에 어긋난다 → 바이트를 직접 본다.
_MAGIC = (
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
    (b'BM', 'image/bmp'),
)

# ★ 공식: 이미지 업로드는 스토어 계정당 동시 1건만 허용된다. 프로세스 안에서 병렬
# 호출이 나가지 않도록 직렬화한다. (여러 프로세스·기기가 같은 계정을 동시에 쓰면
# 이 락으로는 못 막는다 — 그때는 마켓이 '이전 요청이 진행중입니다.' 로 거절한다.)
_upload_lock = threading.Lock()


class ImageUploadError(RuntimeError):
    """이미지 업로드 실패. 조용히 빈 목록을 반환하지 않는다."""


def _sniff_mime(blob: bytes) -> str:
    """저장된 실제 포맷의 MIME. 지원 4종이 아니면 예외."""
    for magic, mime in _MAGIC:
        if blob.startswith(magic):
            return mime
    raise ImageUploadError(
        f'지원하지 않는 이미지 형식입니다 — JPEG·GIF·PNG·BMP 만 됩니다. '
        f'(앞 8바이트: {blob[:8]!r})')


def upload_images(blobs: list, *, client=None) -> list:
    """이미지 바이트 목록 → CDN URL 목록 (순서 보존).

    Raises:
        ImageUploadError: 입력 없음 / 10장 초과 / 10MB 이상 / 미지원 포맷 /
                          응답에 images 없음 / 장수 불일치
    """
    if not blobs:
        raise ImageUploadError('업로드할 이미지가 없습니다.')
    if len(blobs) > _MAX_FILES:
        raise ImageUploadError(
            f'한 번에 최대 {_MAX_FILES}장입니다 — {len(blobs)}장을 받았습니다.')
    total = sum(len(b) for b in blobs)
    if total >= _MAX_TOTAL_BYTES:
        raise ImageUploadError(
            f'이미지 합계가 10MB 미만이어야 합니다 — {total:,} bytes 입니다.')

    # MIME 은 전송 전에 전부 판정한다 (한 장이라도 미지원이면 아예 호출하지 않는다).
    files = [
        (_MULTIPART_FIELD, (f'image_{i}', blob, _sniff_mime(blob)))
        for i, blob in enumerate(blobs)
    ]

    if client is None:
        from shared.platforms.smartstore.client import SmartStoreClient
        client = SmartStoreClient()

    # ★ 계정당 동시 1건 — 직렬화 (공식 제약)
    with _upload_lock:
        resp = client.request_multipart('POST', client.path_for('upload_images'), files)

    images = (resp or {}).get('images')
    if not isinstance(images, list) or not images:
        raise ImageUploadError(f'업로드 응답에 images 가 없습니다: {resp!r}')

    urls = [im.get('url') for im in images if isinstance(im, dict) and im.get('url')]
    if len(urls) != len(blobs):
        raise ImageUploadError(
            f'이미지 {len(blobs)}장을 올렸는데 URL 을 {len(urls)}개만 받았습니다 — '
            f'일부가 조용히 누락됐습니다. 응답: {resp!r}')
    return urls

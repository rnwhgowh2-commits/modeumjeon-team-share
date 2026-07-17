# -*- coding: utf-8 -*-
"""폼이 준 공개 이미지 URL → 네이버 CDN URL (스스 등록 전 재호스팅).

스스는 상품 등록에 shop-phinf.pstatic.net CDN URL 만 받는다(외부 URL 거부). 폼은
소싱처 이미지 URL(공개 URL)을 받으므로, 등록 직전에 그 URL 들의 바이트를 내려받아
upload_images() 로 네이버 CDN 에 올리고 CDN URL 을 얻는다.

★ 이 과정은 전부 라이브 호출이다:
  · 공개 URL fetch (외부 서버)
  · upload_images (네이버 — 계정당 동시 1건 제약, 최대 10장, 합계 10MB)
따라서 반드시 LIVE 게이트 뒤에서만 부른다(service.register_draft 가 그렇게 배선).

쿠팡은 공개 URL 을 그대로 받으므로 이 모듈이 필요 없다.

⚠️ SSRF: 사용자가 준 URL 을 서버가 fetch 한다. 팀 내부 도구라 임의 URL 을 허용하되,
   http/https 만 받고(파일·gopher 등 스킴 차단) 실패는 조용히 넘기지 않고 예외로 올린다.
   외부 노출 도구가 되면 호스트 allowlist 를 붙일 것.
"""
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT = 20
_ALLOWED_SCHEMES = ('http', 'https')
# 한 장 상한. upload_images 의 합계 10MB 캡은 fetch '뒤' 에 적용되므로, 거대한 URL 이
# 메모리를 터뜨리기 전에 fetch 단계에서 먼저 막는다(스트리밍 중 초과 시 중단).
_MAX_FETCH_BYTES = 10 ** 7


class ImagePrepError(RuntimeError):
    """이미지 재호스팅 실패. 조용한 폴백 금지 — 실패하면 등록을 막는다."""


def _default_fetch(url: str) -> bytes:
    """공개 URL → 바이트. http/https 만, 20초 타임아웃."""
    import requests
    scheme = (urlparse(url).scheme or '').lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ImagePrepError(f'이미지 URL 스킴이 http/https 가 아닙니다: {url!r}')
    try:
        resp = requests.get(url, timeout=_FETCH_TIMEOUT, stream=True)
    except requests.RequestException as e:
        raise ImagePrepError(f'이미지를 내려받지 못했습니다({url}): {e}') from e
    with resp:
        if resp.status_code >= 400:
            raise ImagePrepError(
                f'이미지 URL 이 HTTP {resp.status_code} 를 반환했습니다: {url}')
        # Content-Length 로 사전 차단(있으면). 없거나 거짓이어도 아래 스트리밍이 캡을 지킨다.
        clen = resp.headers.get('Content-Length')
        if clen and clen.isdigit() and int(clen) >= _MAX_FETCH_BYTES:
            raise ImagePrepError(
                f'이미지가 너무 큽니다({int(clen):,} bytes ≥ 10MB): {url}')
        chunks, total = [], 0
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total >= _MAX_FETCH_BYTES:
                raise ImagePrepError(f'이미지가 너무 큽니다(10MB 이상): {url}')
            chunks.append(chunk)
    data = b''.join(chunks)
    if not data:
        raise ImagePrepError(f'이미지가 비어 있습니다(0 bytes): {url}')
    return data


def prepare_cdn_images(image_urls, *, _fetch=None, _upload=None) -> list:
    """공개 이미지 URL 목록 → 네이버 CDN URL 목록 (순서 보존).

    Args:
        image_urls: 폼이 준 공개 URL 리스트 (images_json 에서 온 것).
        _fetch: URL→bytes 주입점 (테스트). 기본 = _default_fetch (라이브 fetch).
        _upload: bytes[]→CDN url[] 주입점 (테스트). 기본 = upload_images (라이브).

    Raises:
        ImagePrepError: URL 없음 / fetch 실패 / 업로드 실패.
    """
    urls = [u for u in (image_urls or []) if isinstance(u, str) and u.strip()]
    if not urls:
        raise ImagePrepError('업로드할 이미지 URL 이 없습니다.')

    fetch = _fetch or _default_fetch
    blobs = [fetch(u.strip()) for u in urls]   # 실패하면 여기서 ImagePrepError 로 즉시 중단

    upload = _upload
    if upload is None:
        from shared.platforms.smartstore.images import upload_images, ImageUploadError
        try:
            return upload_images(blobs)
        except ImageUploadError as e:
            # 업로드 실패(장수불일치·미지원포맷·10MB 초과 등)를 조용히 넘기지 않는다.
            raise ImagePrepError(f'네이버 CDN 업로드 실패: {e}') from e
    return upload(blobs)

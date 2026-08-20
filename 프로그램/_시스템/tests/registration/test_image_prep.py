# -*- coding: utf-8 -*-
"""이미지 재호스팅 — fetch·upload 주입으로 순수 검증 (라이브 호출 없음)."""
import pytest

from lemouton.registration.image_prep import prepare_cdn_images, ImagePrepError


def test_order_preserved_url_to_cdn():
    """공개 URL 순서 그대로 CDN URL 이 나온다."""
    fetched = []
    def fake_fetch(u):
        fetched.append(u)
        return b'\xff\xd8\xff' + u.encode()   # 가짜 JPEG 바이트
    def fake_upload(blobs):
        return [f'https://shop-phinf.pstatic.net/{i}.jpg' for i in range(len(blobs))]

    urls = ['https://src/a.jpg', 'https://src/b.jpg', 'https://src/c.jpg']
    out = prepare_cdn_images(urls, _fetch=fake_fetch, _upload=fake_upload)
    assert fetched == urls, '입력 순서대로 fetch'
    assert len(out) == 3
    assert all('shop-phinf.pstatic.net' in u for u in out)


def test_empty_input_raises():
    with pytest.raises(ImagePrepError) as e:
        prepare_cdn_images([], _fetch=lambda u: b'x', _upload=lambda b: [])
    assert '이미지 URL' in str(e.value)


def test_blank_and_none_urls_filtered_then_empty_raises():
    """빈 문자열·None·공백은 걸러지고, 남는 게 없으면 실패."""
    with pytest.raises(ImagePrepError):
        prepare_cdn_images(['', '   ', None], _fetch=lambda u: b'x', _upload=lambda b: [])


def test_fetch_failure_propagates_not_swallowed():
    """한 장이라도 못 받으면 조용히 넘기지 말고 즉시 실패 (폴백 금지)."""
    def bad_fetch(u):
        raise ImagePrepError(f'다운로드 실패: {u}')
    with pytest.raises(ImagePrepError) as e:
        prepare_cdn_images(['https://src/a.jpg'], _fetch=bad_fetch, _upload=lambda b: ['x'])
    assert '다운로드 실패' in str(e.value)


def test_non_http_scheme_rejected_by_default_fetch():
    """SSRF 방어 — file:// 같은 스킴은 기본 fetch 가 거부한다 (upload 안 붙여 fetch 만 탐)."""
    # _upload 는 주입해 라이브 업로드를 막고, _fetch 는 기본값(=_default_fetch)로 둔다.
    with pytest.raises(ImagePrepError) as e:
        prepare_cdn_images(['file:///etc/passwd'], _upload=lambda b: ['x'])
    assert '스킴' in str(e.value)


def test_upload_receives_fetched_bytes():
    """fetch 가 준 바이트가 그대로 upload 로 넘어간다 (중간 변형 없음)."""
    captured = {}
    def fake_upload(blobs):
        captured['blobs'] = blobs
        return ['https://shop-phinf.pstatic.net/x.jpg']
    prepare_cdn_images(['https://src/a.jpg'],
                       _fetch=lambda u: b'\x89PNG\r\n\x1a\nDATA', _upload=fake_upload)
    assert captured['blobs'] == [b'\x89PNG\r\n\x1a\nDATA']

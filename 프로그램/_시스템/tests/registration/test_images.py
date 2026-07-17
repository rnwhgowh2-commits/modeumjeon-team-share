# -*- coding: utf-8 -*-
"""스스 이미지 업로드 — 네트워크는 가짜 클라이언트로 대체."""
import pytest

from shared.platforms.smartstore.images import upload_images, ImageUploadError


class FakeClient:
    """request_multipart 만 흉내내는 가짜 클라이언트."""
    def __init__(self, resp=None, raise_exc=None):
        self.resp = resp or {}
        self.raise_exc = raise_exc
        self.calls = []

    def path_for(self, name):
        assert name == 'upload_images'
        return '/v1/product-images/upload'

    def request_multipart(self, method, path, files):
        self.calls.append({'method': method, 'path': path, 'files': files})
        if self.raise_exc:
            raise self.raise_exc
        return self.resp


JPEG = b'\xff\xd8\xff' + b'x' * 20
PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 20
GIF = b'GIF89a' + b'x' * 20
BMP = b'BM' + b'x' * 20


def test_upload_returns_cdn_urls():
    c = FakeClient(resp={'images': [{'url': 'https://shop-phinf.pstatic.net/a.jpg'},
                                    {'url': 'https://shop-phinf.pstatic.net/b.jpg'}]})
    urls = upload_images([JPEG, PNG], client=c)
    assert urls == ['https://shop-phinf.pstatic.net/a.jpg',
                    'https://shop-phinf.pstatic.net/b.jpg']
    assert c.calls[0]['method'] == 'POST'
    assert c.calls[0]['path'] == '/v1/product-images/upload'
    assert len(c.calls[0]['files']) == 2


def test_all_parts_use_the_same_field_name():
    """공식: 여러 장이어도 name 은 전부 'imageFiles' (Discussion #117)."""
    c = FakeClient(resp={'images': [{'url': 'https://shop-phinf.pstatic.net/a.jpg'},
                                    {'url': 'https://shop-phinf.pstatic.net/b.jpg'}]})
    upload_images([JPEG, PNG], client=c)
    assert [f[0] for f in c.calls[0]['files']] == ['imageFiles', 'imageFiles']


def test_mime_comes_from_actual_bytes_not_filename():
    """공식: MIME 은 확장자가 아니라 저장된 실제 포맷 기준.

    .jpg 인데 데이터가 PNG 면 image/png 를 보내야 한다 (Discussion #117).
    """
    c = FakeClient(resp={'images': [{'url': 'https://shop-phinf.pstatic.net/a.jpg'},
                                    {'url': 'https://shop-phinf.pstatic.net/b.jpg'},
                                    {'url': 'https://shop-phinf.pstatic.net/c.jpg'},
                                    {'url': 'https://shop-phinf.pstatic.net/d.jpg'}]})
    upload_images([JPEG, PNG, GIF, BMP], client=c)
    mimes = [f[1][2] for f in c.calls[0]['files']]
    assert mimes == ['image/jpeg', 'image/png', 'image/gif', 'image/bmp']


def test_unsupported_format_raises():
    """JPEG·GIF·PNG·BMP 4종만. WEBP 등은 거부 (조용히 보내면 마켓이 400)."""
    with pytest.raises(ImageUploadError) as e:
        upload_images([b'RIFF____WEBPVP8 ' + b'x' * 20], client=FakeClient())
    assert 'JPEG' in str(e.value)


def test_over_ten_files_raises():
    """공식: 1 호출당 최대 10장."""
    with pytest.raises(ImageUploadError) as e:
        upload_images([JPEG] * 11, client=FakeClient())
    assert '10' in str(e.value)


def test_over_size_limit_raises():
    """공식: 합계 10MB(10^7 bytes) 미만."""
    big = b'\xff\xd8\xff' + b'x' * (5 * 10 ** 6)
    with pytest.raises(ImageUploadError) as e:
        upload_images([big, big], client=FakeClient())
    assert '10MB' in str(e.value) or '10,000,000' in str(e.value)


def test_empty_input_raises():
    with pytest.raises(ImageUploadError) as e:
        upload_images([], client=FakeClient())
    assert '이미지' in str(e.value)


def test_response_without_images_raises_not_returns_empty():
    """응답에 images 가 없으면 조용히 빈 목록을 주지 말고 실패한다."""
    c = FakeClient(resp={'code': 'SOMETHING'})
    with pytest.raises(ImageUploadError) as e:
        upload_images([JPEG], client=c)
    assert 'images' in str(e.value)


def test_count_mismatch_raises():
    """올린 장수와 받은 URL 수가 다르면 실패 — 조용한 누락 금지."""
    c = FakeClient(resp={'images': [{'url': 'https://shop-phinf.pstatic.net/a.jpg'}]})
    with pytest.raises(ImageUploadError) as e:
        upload_images([JPEG, PNG], client=c)
    assert '2' in str(e.value) and '1' in str(e.value)

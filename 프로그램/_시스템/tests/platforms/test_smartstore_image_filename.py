# -*- coding: utf-8 -*-
"""스마트스토어 이미지 업로드 — 파일명에 **확장자**가 있어야 한다.

🔴 라이브 실측(2026-08-06) — 네이버가 400 으로 거부했다:
    {"code":"BAD_REQUEST","message":"이미지 업로드중 오류가 발생하였습니다.",
     "invalidInputs":[{"name":"imageFiles[0]","type":"PhotoInfraUpload.extension",
       "message":"JPEG, JPG, GIF, PNG, BMP 파일만 업로드가 가능합니다."}]}

    MIME 은 image/png 로 맞게 보냈는데도 거부됐다 — 네이버는 **파일명의 확장자**를 본다.
    우리 코드는 파일명을 `image_0` 로 만들고 있었다(확장자 없음).

이 경로는 상품 등록(`registration/image_prep.prepare_cdn_images`)도 같이 쓴다 —
시험만의 문제가 아니라 **등록 시 이미지가 안 올라가는 문제**였다.
"""
from __future__ import annotations

import pytest

from shared.platforms.smartstore.images import ImageUploadError, upload_images

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
_JPG = b"\xff\xd8\xff" + b"\x00" * 40
_GIF = b"GIF89a" + b"\x00" * 40
_BMP = b"BM" + b"\x00" * 40


class CaptureClient:
    def __init__(self, n=1):
        self.files = None
        self._n = n

    def path_for(self, key):
        return "/external/v1/product-images/upload"

    def request_multipart(self, method, path, files):
        self.files = files
        return {"images": [{"url": f"https://shop-phinf.pstatic.net/{i}.png"}
                           for i in range(len(files))]}


def _names(cli):
    # files = [(field, (filename, blob, mime)), ...]
    return [tup[1][0] for tup in cli.files]


def test_PNG_은_png_확장자로_보낸다():
    cli = CaptureClient()

    upload_images([_PNG], client=cli)

    assert _names(cli)[0].lower().endswith(".png"), _names(cli)


@pytest.mark.parametrize("blob,ext", [
    (_PNG, ".png"), (_JPG, ".jpg"), (_GIF, ".gif"), (_BMP, ".bmp"),
])
def test_포맷마다_맞는_확장자를_붙인다(blob, ext):
    cli = CaptureClient()

    upload_images([blob], client=cli)

    assert _names(cli)[0].lower().endswith(ext)


def test_확장자는_바이트로_판정한다_남이_준_이름을_믿지_않는다():
    """PNG 바이트인데 .jpg 로 부르면 네이버가 거부한다 — 실제 포맷이 기준."""
    cli = CaptureClient()

    upload_images([_PNG], client=cli)

    assert not _names(cli)[0].lower().endswith(".jpg")


def test_여러_장이면_이름이_겹치지_않는다():
    cli = CaptureClient()

    upload_images([_PNG, _JPG], client=cli)

    assert len(set(_names(cli))) == 2


def test_지원하지_않는_포맷은_그대로_거부한다():
    with pytest.raises(ImageUploadError):
        upload_images([b"NOTANIMAGE" + b"\x00" * 40], client=CaptureClient())

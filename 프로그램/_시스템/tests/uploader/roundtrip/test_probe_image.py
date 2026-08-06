# -*- coding: utf-8 -*-
"""시험용 이미지 — 파일을 직접 만들어 마켓 CDN 에 올린다.

왜 만들어서 올리나:
    이미지 축을 왕복하려면 「지금 안 쓰는, 확실히 다른」 이미지 URL 이 필요하다.
    남의 이미지 URL 을 빌려 쓰면 그 URL 이 죽었을 때 원인을 못 가린다. 그래서
    글자가 박힌 PNG 를 그 자리에서 만들어 올린다 — 마켓 화면에서 눈으로도 구별된다.

절대 안 되는 것: 올리지 못했는데 그럴듯한 URL 을 지어내는 것(원복 불가).
"""
from __future__ import annotations

import struct

import pytest

from lemouton.uploader.roundtrip.probe_image import (
    ProbeImageError, make_probe_png, upload_probe_image,
)


def _png_size(blob: bytes):
    """PNG IHDR 에서 가로·세로를 읽는다(외부 라이브러리 없이)."""
    assert blob[:8] == b"\x89PNG\r\n\x1a\n", "PNG 시그니처가 아니다"
    w, h = struct.unpack(">II", blob[16:24])
    return w, h


def test_진짜_PNG_파일을_만든다():
    blob = make_probe_png()

    assert _png_size(blob) == (640, 640)
    assert len(blob) > 100


def test_크기를_지정할_수_있다():
    assert _png_size(make_probe_png(size=(320, 320))) == (320, 320)


def test_부를_때마다_다른_그림이_나온다():
    """같은 바이트면 마켓이 「같은 이미지」로 보고 URL 을 재사용할 수 있다."""
    a = make_probe_png(text="A")
    b = make_probe_png(text="B")

    assert a != b


def test_올린_URL_을_그대로_돌려준다():
    calls = {}

    def fake_upload(blobs, **kw):
        calls["n"] = len(blobs)
        return ["https://shop-phinf.pstatic.net/probe.png"]

    url = upload_probe_image(_upload=fake_upload)

    assert url == "https://shop-phinf.pstatic.net/probe.png"
    assert calls["n"] == 1


def test_업로드가_빈_결과면_주소를_지어내지_않는다():
    with pytest.raises(ProbeImageError):
        upload_probe_image(_upload=lambda blobs, **kw: [])


def test_업로드가_터지면_삼키지_않는다():
    def boom(blobs, **kw):
        raise RuntimeError("CDN 거부")

    with pytest.raises(ProbeImageError):
        upload_probe_image(_upload=boom)

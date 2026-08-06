# -*- coding: utf-8 -*-
"""시험 이미지를 **어디에 올리나** — 마켓마다 받는 주소가 다르다.

  · 스마트스토어: 네이버 CDN(shop-phinf.pstatic.net) URL 만 받는다. 외부 URL 은 거부.
  · 옥션·G마켓·쿠팡·롯데온: 공개 URL 을 그대로 받는다 → 우리 R2 에 올려 그 주소를 쓴다.

어느 쪽이든 **못 올렸으면 주소를 지어내지 않는다** — 가짜 주소를 보내면 상품 사진이
깨지고, 원복할 원래 주소는 이미 덮인 뒤다.
"""
from __future__ import annotations

import pytest

from lemouton.uploader.roundtrip.probe_image import (
    ProbeImageError, upload_probe_image_public,
)


def test_공개저장소에_올린_주소를_돌려준다():
    got = {}

    def fake_put(data, key, content_type, **kw):
        got["key"] = key
        got["type"] = content_type
        got["size"] = len(data)
        return "https://cdn.example.com/" + key

    url = upload_probe_image_public(_put=fake_put)

    assert url == "https://cdn.example.com/" + got["key"]
    assert got["type"] == "image/png"
    assert got["size"] > 100


def test_올린_파일은_PNG_다():
    blobs = {}

    def fake_put(data, key, content_type, **kw):
        blobs["data"] = data
        return "https://cdn.example.com/x.png"

    upload_probe_image_public(_put=fake_put)

    assert blobs["data"][:8] == b"\x89PNG\r\n\x1a\n"


def test_회차마다_다른_키를_쓴다():
    keys = []

    def fake_put(data, key, content_type, **kw):
        keys.append(key)
        return "https://cdn.example.com/" + key

    upload_probe_image_public(_put=fake_put, tag="a")
    upload_probe_image_public(_put=fake_put, tag="b")

    assert keys[0] != keys[1], "같은 주소면 마켓이 「안 바뀌었다」로 볼 수 있다"


def test_올리기가_터지면_주소를_지어내지_않는다():
    def boom(data, key, content_type, **kw):
        raise RuntimeError("R2 거부")

    with pytest.raises(ProbeImageError, match="R2 거부"):
        upload_probe_image_public(_put=boom)


def test_빈_주소를_돌려받으면_실패로_본다():
    with pytest.raises(ProbeImageError):
        upload_probe_image_public(_put=lambda data, key, content_type, **kw: "")

# -*- coding: utf-8 -*-
"""시험용 이미지 — 파일을 그 자리에서 만들어 마켓 CDN 에 올린다.

**왜 만들어 올리나**
    이미지 축을 왕복하려면 「지금 안 쓰는, 확실히 다른」 이미지가 필요하다. 남의 URL 을
    빌려 쓰면 그게 죽었을 때 우리 전송이 실패한 건지 남의 이미지가 죽은 건지 못 가린다.
    그래서 눈에 확 띄는 격자 무늬 PNG 를 만들어 올린다 — 마켓 화면에서 사람이 봐도
    「이건 시험 이미지구나」 알 수 있다.

**왜 Pillow 를 안 쓰나**
    requirements.txt 에 Pillow 가 없다. 시험 하나 하자고 라이브 서버 의존성을 늘리지
    않는다. PNG 는 zlib + struct 만으로 충분히 만들 수 있다(표준 라이브러리).

**절대 안 되는 것**
    업로드에 실패했는데 그럴듯한 CDN 주소를 지어내는 것 — 그 주소로 상품을 바꾸면
    이미지가 깨지고, 원복할 「원래 주소」는 이미 덮인 뒤다.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from datetime import datetime

_SIG = b"\x89PNG\r\n\x1a\n"


class ProbeImageError(RuntimeError):
    """시험 이미지 준비 실패. 조용한 폴백 금지 — 실패하면 이미지 축을 건너뛴다."""


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _colors(seed: str):
    """글자에서 색 두 개를 뽑는다 — 부를 때마다 다른 그림이 되게."""
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    fg = (h[0] | 0x60, h[1] | 0x60, h[2] | 0x60)      # 너무 어둡지 않게
    bg = (255 - fg[0], 255 - fg[1], 255 - fg[2])
    return fg, bg


def make_probe_png(*, text: str | None = None, size=(640, 640)) -> bytes:
    """시험용 PNG 바이트. 격자 + 대각선 띠 — 실제 상품 사진과 헷갈릴 수 없는 무늬."""
    w, h = int(size[0]), int(size[1])
    if w <= 0 or h <= 0:
        raise ProbeImageError(f"이미지 크기가 잘못됐습니다: {size!r}")
    label = text if text is not None else datetime.now().strftime("%Y%m%d%H%M%S%f")
    fg, bg = _colors(label)
    cell = max(w // 8, 1)

    rows = bytearray()
    for y in range(h):
        rows.append(0)                       # 필터 타입 0(None)
        band = abs((y - (h - 1) // 2))       # 대각선 대신 가로 띠(계산 단순·시각 강함)
        for x in range(w):
            checker = ((x // cell) + (y // cell)) % 2 == 0
            on_band = band < h // 12 or abs(x - y) < w // 40
            c = fg if (checker ^ on_band) else bg
            rows.extend(c)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8bit truecolor
    meta = b"Comment\x00" + f"moum roundtrip probe {label}".encode("utf-8", "replace")
    return (_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"tEXt", meta)
            + _chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + _chunk(b"IEND", b""))


def upload_probe_image_public(*, tag: str = "", text: str | None = None,
                              size=(640, 640), _put=None) -> str:
    """시험 PNG 1장을 **우리 공개 저장소(R2)** 에 올리고 그 URL 을 돌려준다.

    옥션·G마켓·쿠팡·롯데온은 공개 URL 을 그대로 받는다(네이버만 자기 CDN 만 받는다).

    Raises:
        ProbeImageError: 업로드 실패·빈 주소. **주소를 지어내지 않는다.**
    """
    label = text if text is not None else datetime.now().strftime("%Y%m%d%H%M%S%f")
    blob = make_probe_png(text=f"{tag}{label}", size=size)
    # 회차마다 다른 키 — 같은 주소면 마켓이 「안 바뀌었다」로 볼 수 있다.
    key = f"roundtrip/probe_{tag or 'x'}_{label}.png"

    put = _put
    if put is None:
        from shared.storage import put_object
        put = put_object

    try:
        url = put(blob, key, "image/png")
    except Exception as e:  # noqa: BLE001
        raise ProbeImageError(f"시험 이미지 저장 실패: {type(e).__name__}: {e}") from e

    url = str(url or "").strip()
    if not url:
        raise ProbeImageError("시험 이미지 저장 결과 주소가 비어 있습니다 — "
                              "주소를 지어내지 않고 이미지 축을 건너뜁니다.")
    return url


def upload_probe_image(*, client=None, text: str | None = None,
                       size=(640, 640), _upload=None) -> str:
    """시험 PNG 1장을 네이버 CDN 에 올리고 그 URL 을 돌려준다.

    Raises:
        ProbeImageError: 업로드 실패·빈 결과. **주소를 지어내지 않는다.**
    """
    blob = make_probe_png(text=text, size=size)

    upload = _upload
    if upload is None:
        from shared.platforms.smartstore.images import upload_images
        upload = upload_images

    try:
        urls = upload([blob], client=client)
    except Exception as e:  # noqa: BLE001
        raise ProbeImageError(f"시험 이미지 업로드 실패: {type(e).__name__}: {e}") from e

    urls = [str(u).strip() for u in (urls or []) if str(u or "").strip()]
    if not urls:
        raise ProbeImageError("시험 이미지 업로드 결과가 비어 있습니다 — "
                              "주소를 지어내지 않고 이미지 축을 건너뜁니다.")
    return urls[0]

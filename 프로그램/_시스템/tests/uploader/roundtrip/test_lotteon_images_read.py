# -*- coding: utf-8 -*-
"""롯데온 이미지는 **읽을 수 있었는데 우리가 엉뚱한 이름으로 찾고 있었다**.

[2026-08-12 라이브] 롯데온 상세조회는 필드를 150개나 준다. 그 안에 이미지가 있다:
    itmLst[].itmImgLst[].origImgFileNm      ← 단품(itm)별 이미지
그런데 어댑터는 상품 최상위에서 `imgLst` / `pdImgLst` / `images` 를 찾고 있었고,
그런 열쇠가 없으니 「이 마켓은 이미지를 안 준다(확인불가)」로 굳어 있었다.

🔴 「마켓이 안 준다」고 적기 전에 응답 열쇠를 전수로 봐야 한다.
   (feedback_field_arrives_but_code_drops_it — 오는데 우리가 버리는 경우)

⚠️ 읽기만 고친다. **쓰기는 아직 못 한다** — 롯데온 상품수정은 「등록과 동일 스키마」라
   일부만 보내면 나머지가 지워질 위험이 있고, 그 스펙(apiNo=90)을 아직 못 구했다.
   되돌릴 자신이 없는 축은 시험 대상에서 계속 뺀다.
"""
from __future__ import annotations

import copy

from lemouton.uploader.roundtrip.markets.lotteon import make_lotteon_ops

_DETAIL = {
    "spdNo": "S1", "spdNm": "매장정품 닥스 메쉬 중절모", "slStatCd": "SALE",
    "itmLst": [{
        "sitmNo": "I1", "slPrc": 163500, "stkQty": 10, "stkMgtYn": "Y",
        "itmImgLst": [
            {"epsrTypCd": "01", "origImgFileNm": "https://img.lotteon.com/a.jpg",
             "rprtImgYn": "Y"},
            {"epsrTypCd": "02", "origImgFileNm": "https://img.lotteon.com/b.jpg",
             "rprtImgYn": "N"},
        ],
    }],
}


class FakeLotteon:
    def __init__(self, detail=None):
        self.detail = copy.deepcopy(detail if detail is not None else _DETAIL)
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "T1", "lrtr_no": "",
                     "paths": {"detail": "/detail",
                               "price_change": "/price", "stock_change": "/stock"}}

    def request(self, *, method, path, body=None, **kw):
        if path == "/detail":
            return {"returnCode": "0000", "data": copy.deepcopy(self.detail)}
        return {"returnCode": "0000", "data": [{"resultCode": "0000", "sitmNo": "I1"}]}


def test_단품_안의_이미지를_읽는다():
    s = make_lotteon_ops("S1", client=FakeLotteon()).snapshot()

    assert s.image_urls == ("https://img.lotteon.com/a.jpg",
                            "https://img.lotteon.com/b.jpg"), \
        f"이미지를 못 읽었다: {s.image_urls}"


def test_대표이미지가_맨_앞에_온다():
    """rprtImgYn='Y' 가 대표다. 순서가 뒤바뀌면 원복했는데 대표가 달라진다."""
    d = copy.deepcopy(_DETAIL)
    d["itmLst"][0]["itmImgLst"] = [
        {"origImgFileNm": "https://img/보조.jpg", "rprtImgYn": "N"},
        {"origImgFileNm": "https://img/대표.jpg", "rprtImgYn": "Y"},
    ]

    s = make_lotteon_ops("S1", client=FakeLotteon(d)).snapshot()

    assert s.image_urls[0] == "https://img/대표.jpg", f"대표가 앞이 아니다: {s.image_urls}"


def test_이미지가_없으면_지어내지_않는다():
    d = copy.deepcopy(_DETAIL)
    d["itmLst"][0]["itmImgLst"] = []

    s = make_lotteon_ops("S1", client=FakeLotteon(d)).snapshot()

    assert s.image_urls is None
    assert "image_urls" in s.missing


def test_읽히더라도_시험_대상에서는_계속_뺀다():
    """🔴 되돌릴 자신이 없는 축은 안 건드린다.

    롯데온 상품수정은 「등록과 동일 스키마」라 일부만 보내면 나머지가 지워질 수 있다.
    그 스펙을 못 구한 동안은 **읽기만** 하고 쓰기는 안 한다.
    """
    s = make_lotteon_ops("S1", client=FakeLotteon()).snapshot()

    for axis in ("name", "detail_html", "image_urls"):
        assert axis in s.missing, f"{axis} 를 시험 대상으로 잡았다"


def test_상세는_여전히_확인불가다():
    """150개 필드 어디에도 상세 HTML 이 없다 — 없는 걸 있는 척 하지 않는다."""
    s = make_lotteon_ops("S1", client=FakeLotteon()).snapshot()

    assert s.detail_html is None

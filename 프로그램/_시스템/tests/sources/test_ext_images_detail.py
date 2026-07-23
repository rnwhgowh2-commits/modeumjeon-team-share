# -*- coding: utf-8 -*-
"""[M4-5] 확장 경로 소싱처(무신사·롯데온)도 상품 사진·상세설명을 실어 보내는지.

배경 — 소싱처 8곳 중 6곳은 **서버 파서**(`lemouton/sourcing/crawlers/*.py::parse_html`)가
이미 이미지·상세를 뽑는다(M4-4). 남은 **무신사·롯데온 2곳은 추출이 크롬 확장
(`extension/moum-crawler/background.js`) 안**에 있어 아직 사진이 0장이었다.
6마켓 전부 대표 이미지가 필수고 4마켓(옥션·G마켓·11번가·롯데온)은 상세도 필수라,
이 둘이 비어 있으면 그 상품은 **등록 자체가 막힌다**.

관문(여기가 끊기면 「조용한 실패」) —
  ① 확장 추출기가 값을 읽고
  ② `crawlItemInTabBG` BG_JS 분기가 결과에 싣고
  ③ `toItemBG` 가 `/api/sources/crawl-result` 로 보내야
  서버 `webapp/routes/api_pricing.py::save_crawl_result` 가 받아
  `SourceProduct.images_json` · `detail_html` 에 넣는다(status=='ok' + 무스톰프 게이트).
  ★ `BENEFIT_PASSTHROUGH` 에는 **넣지 않는다** — 그 배열은 혜택 화이트리스트라
    거기 넣으면 `dynamic_benefits_json` 에 중복 저장된다(전용 컬럼이 진실 원천).

fixture 는 전부 **2026-07-23 라이브 실측 원본**이다(지어낸 마크업 아님):
  · `musinsa_goods_api.json`   = `goods-detail.musinsa.com/api2/goods/4800825` 응답에서
                                 우리가 쓰는 노드만 남긴 것(값은 원문 그대로)
  · `lotteon_product.html`     = `www.lotteon.com/p/product/LO2158462914` SSR 원문
  · `lotteon_base_multi.json`  = `pbf.lotteon.com/.../base/pd/PD59900747` 응답(사진 2장 상품)
  · `lotteon_detail_file.html` = 위 상품의 상세 파일 원문(16,238바이트)
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from lemouton.sourcing.crawlers.base import build_image_urls, sanitize_detail_html

FIX = pathlib.Path(__file__).parent / "fixtures"
_EXT = pathlib.Path(__file__).resolve().parents[2] / "extension" / "moum-crawler"

# 확장 안 공통 헬퍼 블록 — 파이썬 테스트가 통째로 떠서 node 로 돌린다(코드 복제 금지).
_HELPERS_START = "// ==== M4IMG-HELPERS-START ===="
_HELPERS_END = "// ==== M4IMG-HELPERS-END ===="


def _bg() -> str:
    return (_EXT / "background.js").read_text(encoding="utf-8")


def _fixture_text(name: str) -> str:
    p = FIX / name
    if not p.exists():
        pytest.skip(f"fixture 없음: {name}")
    return p.read_text(encoding="utf-8")


def _fixture_json(name: str):
    return json.loads(_fixture_text(name))


# ─────────────────────────────────────────────────────────────
# node 하네스 — **배포되는 background.js 원본**을 그대로 실행한다.
#   tests/js/*.js 처럼 로직을 베껴 두면 확장이 바뀌어도 테스트는 초록불이라
#   '테스트는 통과하는데 실물은 틀린' 상태가 된다. 여기서는 베끼지 않는다.
# ─────────────────────────────────────────────────────────────
def _helpers_source() -> str:
    bg = _bg()
    i, j = bg.find(_HELPERS_START), bg.find(_HELPERS_END)
    assert i >= 0 and j > i, (
        "background.js 에 M4IMG 헬퍼 블록 표식이 없다 — 확장 이미지/상세 배관이 빠졌다")
    return bg[i:j]


def _run_js(expr: str, payload):
    """헬퍼 블록 + `expr` 을 node 로 실행하고 결과(JSON)를 돌려준다."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음 — 확장 헬퍼 행위 검증 건너뜀")
    script = (_helpers_source()
              + "\nconst IN = JSON.parse(process.argv[2]);\n"
              + f"console.log(JSON.stringify({expr}));\n")
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "run.js"
        f.write_text(script, encoding="utf-8")
        out = subprocess.run([node, str(f), json.dumps(payload, ensure_ascii=False)],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, f"node 실행 실패: {out.stderr[:400]}"
    return json.loads(out.stdout.strip())


# ═════════════════════════════════════════════════════════════
# 무신사 — 이미지·상세는 **이미 부르고 있는** api2/goods/{id} 응답 안에 있다
#   (추가 HTTP 호출 0 — 표면가·카테고리와 같은 응답)
# ═════════════════════════════════════════════════════════════
def _musinsa_goods():
    return _fixture_json("musinsa_goods_api.json")["data"]


def test_무신사_이미지는_대표_썸네일과_추가컷을_절대URL로_만든다():
    """[실측 근거 — 추측 아님] 2026-07-23.

    · PDP 의 `og:image` = `https://image.msscdn.net` + `thumbnailImageUrl` **문자열 일치**
      (`https://image.msscdn.net/images/goods_img/20250218/4800825/4800825_17401126635997_500.jpg`)
    · 추가컷 = `goodsImages[].imageUrl`(`/images/prd_img/…`)
    · HEAD 3건 전부 `200 image/jpeg` (78,690B / 113,001B / 106,203B)
    """
    got = _run_js("musinsaImageUrlsBG(IN)", _musinsa_goods())
    assert got == [
        'https://image.msscdn.net/images/goods_img/20250218/4800825/'
        '4800825_17401126635997_500.jpg',
        'https://image.msscdn.net/images/prd_img/20250218/4800825/'
        'detail_4800825_17401126843126_500.jpg',
        'https://image.msscdn.net/images/prd_img/20250218/4800825/'
        'detail_4800825_17401126983997_500.jpg',
    ]


def test_무신사_이미지_렌디션을_큰판으로_치환하지_않는다():
    """[추측 금지 핀] `_500` 을 떼거나 `_1200` 으로 바꾸면 **404** 다(2026-07-23 HEAD 실측).

    치환했다면 마켓에 깨진 대표사진이 올라갔을 것이다 — API 가 준 주소만 쓴다.
    """
    got = _run_js("musinsaImageUrlsBG(IN)", _musinsa_goods())
    assert all(u.endswith("_500.jpg") for u in got)


def test_무신사_이미지_없는_응답이면_빈리스트이고_예외를_던지지_않는다():
    assert _run_js("musinsaImageUrlsBG(IN)", {}) == []
    assert _run_js("musinsaImageUrlsBG(IN)", None) == []
    assert _run_js("musinsaImageUrlsBG(IN)", {"goodsImages": [{"imageUrl": ""}]}) == []


def test_무신사_상세는_goodsContents_원문이다():
    got = _run_js("musinsaDetailHtmlBG(IN)", _musinsa_goods())
    assert got.count("<img") == 18
    assert 'https://ai.esmplus.com/oozootech/Lemouton/202606/mate/1.jpg' in got


def test_무신사_상세가_없으면_빈문자열이다():
    assert _run_js("musinsaDetailHtmlBG(IN)", {}) == ""
    assert _run_js("musinsaDetailHtmlBG(IN)", {"goodsContents": "   "}) == ""


def test_무신사_상세는_서버_관문을_통과해도_상품사진이_살아남는다():
    """확장이 보낸 값은 서버 수신 경계에서 `sanitize_detail_html` 로 재정제된다.

    거기서 전부 걸러지면 '보냈는데 안 남는' 조용한 실패다 — 그 자리를 핀으로 막는다.
    """
    raw = _run_js("musinsaDetailHtmlBG(IN)", _musinsa_goods())
    got = sanitize_detail_html(raw, "https://www.musinsa.com/products/4800825")
    assert got.count("<img") == 18
    assert "<script" not in got and "href" not in got


def test_무신사_이미지는_서버_관문을_통과한다():
    """`build_image_urls` 의 비상품 필터(아이콘·로고·1px)에 걸리면 0장이 된다."""
    srcs = _run_js("musinsaImageUrlsBG(IN)", _musinsa_goods())
    assert build_image_urls(srcs, "https://www.musinsa.com/products/4800825") == srcs


# ═════════════════════════════════════════════════════════════
# 롯데온 — 사진은 JSON-LD 1순위 · base API 폴백, 상세는 별도 파일(SW fetch)
# ═════════════════════════════════════════════════════════════
def _lotteon_ld_images():
    """PDP SSR 의 JSON-LD `Product.image` — 확장 추출기가 페이지에서 읽는 값."""
    html = _fixture_text("lotteon_product.html")
    m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
    assert m, "fixture 전제 변경 — JSON-LD 블록이 사라졌다"
    blocks = json.loads(m.group(1))
    for o in (blocks if isinstance(blocks, list) else [blocks]):
        if isinstance(o, dict) and o.get("@type") == "Product":
            return o.get("image")
    raise AssertionError("JSON-LD 에 Product 가 없다")


def test_롯데온_이미지는_JSONLD_Product_image_가_1순위다():
    """실측(2026-07-23, LO2158462914): JSON-LD 가 **절대 URL** 을 그대로 준다.

    같은 상품 base API 의 `imgRteNm`+`imgFileNm` 조립 결과와 **문자열이 같다**
    (`/itemimage/20260629190936/LO/21/58/46/29/14/_2/15/84/62/91/5/…_1.jpg`).
    두 원천이 일치하므로 조립 규칙이 아니라 **읽은 값**을 먼저 쓴다(추측 최소화).
    """
    got = _run_js("lotteonImageUrlsBG(IN, null)", _lotteon_ld_images())
    assert got == ['https://contents.lotteon.com/itemimage/20260629190936/LO/21/58/46/29/14/'
                   '_2/15/84/62/91/5/LO2158462914_2158462915_1.jpg']


def test_롯데온_JSONLD_가_없으면_base_API_이미지목록으로_조립한다():
    """[조립 근거 — 추측 아님] 2026-07-23 실측.

    · `PD59900747` 은 SSR JSON-LD 에 `image` 키가 **아예 없다**(실측) → 폴백이 필요하다.
    · 조립 = `https://contents.lotteon.com/itemimage` + `imgRteNm` + `imgFileNm`
    · HEAD 실측: 이 상품 2장 + 다른 상품 1장 = **3/3 모두 `200 image/jpeg`**
      (30,946B / 34,577B / 189,603B)
    """
    base = _fixture_json("lotteon_base_multi.json")["data"]
    got = _run_js("lotteonImageUrlsBG(null, IN)", base)
    assert got == [
        'https://contents.lotteon.com/itemimage/20260615120801/LE/12/20/81/72/93/'
        '_1/32/53/62/47/8/LE1220817293_1325362478_1.jpg',
        'https://contents.lotteon.com/itemimage/20260615120801/LE/12/20/81/72/93/'
        '_1/32/53/62/47/8/LE1220817293_1325362478_2.jpg',
    ]


def test_롯데온_이미지_원천이_둘다_없으면_빈리스트다():
    assert _run_js("lotteonImageUrlsBG(null, null)", {}) == []
    assert _run_js("lotteonImageUrlsBG([], IN)", {"imgInfo": {"imageList": []}}) == []
    # 조각이 반쪽이면 지어내지 않는다(없는 주소 금지)
    assert _run_js("lotteonImageUrlsBG(null, IN)",
                   {"imgInfo": {"imageList": [{"imgRteNm": "/a/b/"}]}}) == []


def test_롯데온_상세파일_주소는_base_API_descInfo_로_조립한다():
    """[탐색 실측 2026-07-23] `descInfo.epnJsn` 의 `DSCRP` 항목이 상세설명 파일이다.

    후보 6개를 HEAD 로 두들겨 `…/itemdesc/…`·`…/desc/…` 등은 **403**,
    `https://contents.lotteon.com/itemdetail` + `dtlFileRteNm` + `dtlFileNm` 만 **200 HTML**
    (1,424B · 16,238B, 서로 다른 상품 2건). 그 하나만 쓴다.
    """
    base = _fixture_json("lotteon_base_multi.json")["data"]
    got = _run_js("lotteonDetailUrlBG(IN)", base)
    assert got == ('https://contents.lotteon.com/itemdetail/LE/12/20/81/72/93/'
                   'DSCRP_LE1220817293')


def test_롯데온_상세파일_주소는_AS안내가_아니라_상품설명이다():
    """`epnJsn` 에는 `AS_CNTS`(A/S 이용설명)도 같이 온다 — 그걸 상세로 올리면 오등록이다."""
    got = _run_js("lotteonDetailUrlBG(IN)", {"descInfo": {"epnJsn": [
        {"pdEpnTypCd": "AS_CNTS", "dtlFileRteNm": "/LO/1/", "dtlFileNm": "AS_CNTS_X"},
        {"pdEpnTypCd": "DSCRP", "dtlFileRteNm": "/LO/1/", "dtlFileNm": "DSCRP_X"},
    ]}})
    assert got.endswith("/DSCRP_X")


def test_롯데온_상세파일_주소를_못만들면_빈문자열이다():
    assert _run_js("lotteonDetailUrlBG(IN)", {}) == ""
    assert _run_js("lotteonDetailUrlBG(IN)", None) == ""
    assert _run_js("lotteonDetailUrlBG(IN)", {"descInfo": {"epnJsn": [
        {"pdEpnTypCd": "DSCRP", "dtlFileNm": "DSCRP_X"}]}}) == ""


def test_롯데온_상세파일_내용은_서버_관문을_통과한다():
    """fixture = 그 주소에서 받은 원문 그대로(16,238바이트 · 이미지 3장)."""
    got = sanitize_detail_html(_fixture_text("lotteon_detail_file.html"),
                               "https://www.lotteon.com/p/product/PD59900747")
    assert got.count("<img") == 3
    assert "static.wixstatic.com" in got
    assert "<script" not in got and "href" not in got


def test_롯데온_이미지는_서버_관문을_통과한다():
    srcs = _run_js("lotteonImageUrlsBG(IN, null)", _lotteon_ld_images())
    assert build_image_urls(srcs, "https://www.lotteon.com/p/product/LO2158462914") == srcs


# ═════════════════════════════════════════════════════════════
# 공통 절대화기 — 상대경로·프로토콜상대·중복·상한
# ═════════════════════════════════════════════════════════════
def test_절대화기_프로토콜상대와_상대경로를_처리하고_중복을_지운다():
    got = _run_js('absImageUrlsBG(IN, "https://image.msscdn.net")',
                  ["//cdn.x.com/a.jpg", "/images/b.jpg", "https://y.com/c.jpg",
                   "/images/b.jpg"])
    assert got == ["https://cdn.x.com/a.jpg",
                   "https://image.msscdn.net/images/b.jpg",
                   "https://y.com/c.jpg"]


def test_절대화기_기준호스트_없는_상대경로는_지어내지_않는다():
    assert _run_js('absImageUrlsBG(IN, "")', ["/images/b.jpg"]) == []


def test_절대화기_placeholder_와_빈값은_버린다():
    assert _run_js('absImageUrlsBG(IN, "https://h")',
                   ["", "   ", None, "data:image/gif;base64,R0lGODlh"]) == []


def test_절대화기_상한을_넘기지_않는다():
    """서버 `build_image_urls` 상한(20장)과 같은 값 — 확장이 더 보내 봐야 잘린다."""
    got = _run_js('absImageUrlsBG(IN, "https://h")',
                  [f"/p{i}.jpg" for i in range(30)])
    assert len(got) == 20


# ═════════════════════════════════════════════════════════════
# 확장 배관 정적 핀 — 여기가 끊기면 수집해도 「조용히 유실」된다
# ═════════════════════════════════════════════════════════════
def test_확장_toItemBG_가_이미지와_상세를_crawl_result_로_실어보낸다():
    m = re.search(r"function toItemBG\(x\) \{(.*?)\n\}", _bg(), re.S)
    assert m, "background.js 에 toItemBG 정의가 없음"
    body = m.group(1)
    assert "image_urls" in body, (
        "toItemBG 가 image_urls 를 안 보낸다 — 확장이 수집해도 서버에 도달 못 한다")
    assert "detail_html" in body, (
        "toItemBG 가 detail_html 을 안 보낸다 — 확장이 수집해도 서버에 도달 못 한다")


def test_확장_BG_JS_결과조립_분기가_이미지와_상세를_싣는다():
    """무신사·롯데온은 `crawlItemInTabBG` 의 BG_JS 분기에서 결과가 만들어진다."""
    bg = _bg()
    i = bg.find("if (BG_JS_SOURCES.indexOf(sk) >= 0) {")
    assert i > 0, "BG_JS 분기를 찾지 못했다"
    seg = bg[i:i + 4000]
    assert "image_urls:" in seg, "BG_JS 분기가 image_urls 를 결과에 안 싣는다"
    assert "detail_html:" in seg, "BG_JS 분기가 detail_html 을 결과에 안 싣는다"


def test_확장_창없이_무신사_어댑터도_이미지와_상세를_싣는다():
    """`fetchMusinsaAdapter`(창 없는 fast-lane)만 빠지면 그 경로 상품이 조용히 빈다."""
    m = re.search(r"async function fetchMusinsaAdapter\(item\) \{(.*?)\n\}\n", _bg(), re.S)
    assert m, "fetchMusinsaAdapter 정의가 없음"
    body = m.group(1)
    assert "musinsaImageUrlsBG" in body and "musinsaDetailHtmlBG" in body, (
        "창없이 무신사 경로가 이미지·상세를 안 싣는다")


def test_확장_이미지상세는_혜택_화이트리스트에_넣지_않는다():
    """🔴 `BENEFIT_PASSTHROUGH` 에 넣으면 `dynamic_benefits_json` 에 **중복 저장**된다.

    전용 컬럼(`source_products.images_json`·`detail_html`)이 이미 진실 원천이다
    (중복·모순 금지). category_path 와 같은 이유로 명시 필드로만 통과시킨다.
    """
    m = re.search(r"const BENEFIT_PASSTHROUGH = \[(.*?)\];", _bg(), re.S)
    assert m, "BENEFIT_PASSTHROUGH 배열을 찾지 못했다"
    arr = m.group(1)
    assert "image_urls" not in arr and "detail_html" not in arr


def test_확장_롯데온_상세는_서비스워커가_받아온다():
    """🔴 `contents.lotteon.com` 응답에 CORS 헤더가 없다(2026-07-23 실측).

    페이지(MAIN world) 안에서 fetch 하면 브라우저가 막는다 → **호스트 권한이 있는
    서비스워커**가 받아야 한다. 추출기는 주소만 알려 주고, 실제 수신은 BG 몫이다.
    """
    bg = _bg()
    assert "async function fetchDetailFileBG(" in bg, (
        "서비스워커 상세 수신기(fetchDetailFileBG)가 없다")
    i = bg.find("if (BG_JS_SOURCES.indexOf(sk) >= 0) {")
    seg = bg[i:i + 4000]
    assert "fetchDetailFileBG(" in seg, "BG_JS 분기가 롯데온 상세 파일을 안 받아온다"


def test_확장_추출기가_이미지_상세_원천을_결과에_담는다():
    """추출기(페이지 주입 함수)는 **원문 조각**만 넘기고 조립은 BG 가 한다.

    같은 규칙을 두 벌 쓰지 않기 위해서다 — 조립 규칙의 단일 원천은 헬퍼 블록.
    """
    bg = _bg()
    mus = re.search(r"async function musinsaExtractor\(\) \{(.*?)\n\}\n", bg, re.S)
    lot = re.search(r"async function lotteonExtractor\(\) \{(.*?)\n\}\n", bg, re.S)
    assert mus and lot, "추출기 정의를 찾지 못했다"
    assert "musinsa_goods:" in mus.group(1), "무신사 추출기가 이미지·상세 원천을 안 넘긴다"
    assert "lotteon_ld_images:" in lot.group(1), "롯데온 추출기가 JSON-LD 이미지를 안 넘긴다"
    assert "lotteon_base:" in lot.group(1), "롯데온 추출기가 base 응답(폴백 원천)을 안 넘긴다"


def test_확장_사진이_한장도_없으면_경고를_남긴다():
    """조용한 실패 금지 — 0장이면 6마켓 등록이 통째로 막히는데 아무 말이 없으면 안 된다."""
    bg = _bg()
    i = bg.find("if (BG_JS_SOURCES.indexOf(sk) >= 0) {")
    seg = bg[i:i + 4000]
    assert "m4img" in seg, "이미지 0장 경고 흔적(m4img)이 없다"


def test_확장_버전이_manifest_와_background_에서_같다():
    """상습 불일치 이력 — 두 값이 어긋나면 로드 버전 진단이 거짓말을 한다."""
    manifest_v = json.loads((_EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
    m = re.search(r'const MOUM_EXT_VERSION = "([\d.]+)"', _bg())
    assert m, "background.js 에 MOUM_EXT_VERSION 상수가 없음"
    assert m.group(1) == manifest_v
    assert manifest_v >= "0.7.63", "이미지·상세 배관이 들어간 새 버전으로 올라가야 재로드가 확인된다"

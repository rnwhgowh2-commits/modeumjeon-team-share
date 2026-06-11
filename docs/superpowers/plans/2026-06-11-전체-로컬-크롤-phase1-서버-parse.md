# 전체 로컬 크롤 — Phase 1: 서버 `parse_html` + `/api/sources/parse` 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4개 비로그인 소싱처(르무통·SSF·SSG·스스르무통) 크롤러에 "이미 받은 HTML을 파싱"하는 `parse_html(html, url)` 메서드를 추가하고, 그 HTML을 받아 구조화 결과를 돌려주는 `POST /api/sources/parse` 엔드포인트를 만든다. (확장이 로컬 창에서 긁은 HTML을 서버 기존 파서로 추출 — 설계 A안의 서버 측 토대.)

**Architecture:** 각 크롤러의 `fetch(url)` 는 내부적으로 `html = self._fetch_html(url)` 후 파싱한다. 이 "파싱 부분"을 `parse_html(html, url) -> CrawlResult` 로 분리하고, `fetch` 는 `parse_html(self._fetch_html(url), url)` 로 재정의한다(동작 불변, 리팩터). 신규 엔드포인트는 `build_crawlers()[source_key].parse_html(html, url)` 를 호출해 직렬화한다.

**Tech Stack:** Python 3.14 · Flask · BeautifulSoup(lxml) · pytest · 기존 `lemouton/sourcing/crawlers/*`

**범위:** 본 계획은 Phase 1(서버 토대)만. 독립적으로 테스트·배포 가능(확장 없이 저장된 HTML 픽스처로 검증). 후속: Phase 2(확장 창·HTML 수집 v0.4.0) / Phase 3(처리량 컨트롤러) / Phase 4(대시보드 로그) / Phase 5(소싱처별 라이브 검증) — 각각 별도 계획.

**설계 문서:** `docs/superpowers/specs/2026-06-11-전체-로컬-크롤-적응형-동시성-design.md` (§3.1, §3.2, §7)

---

## 파일 구조

| 파일 | 역할 | 변경 |
|---|---|---|
| `lemouton/sourcing/crawlers/ssf.py` | SSF 크롤러 | `parse_html` 추가, `fetch` 재배선 |
| `lemouton/sourcing/crawlers/lemouton.py` | 르무통 공홈 크롤러 | 〃 |
| `lemouton/sourcing/crawlers/ssg.py` | SSG 크롤러 | 〃 |
| `lemouton/sourcing/crawlers/ss_lemouton.py` | 스스르무통 크롤러 | 〃 |
| `webapp/routes/api_sources_parse.py` | 신규 `POST /api/sources/parse` | 생성 |
| `app.py` | 블루프린트 등록 | 1줄 추가 |
| `tests/sourcing/fixtures/*.html` | 4개 소싱처 샘플 HTML | 생성 |
| `tests/sourcing/test_parse_html.py` | parse_html·parity 테스트 | 생성 |
| `tests/sourcing/test_parse_endpoint.py` | 엔드포인트 테스트 | 생성 |

**공통 리팩터 패턴(4개 크롤러 동일):**
크롤러에서 `html = self._fetch_html(url)`(또는 동등) 직후의 **순수 파싱 코드**를 `parse_html(self, html, product_url) -> CrawlResult` 로 옮긴다. 기존 fetch 진입 메서드는 `return self.parse_html(self._fetch_html(product_url), product_url)` 로 바꾼다. `_parse_*` 헬퍼는 그대로 둔다(재사용). 다색 자동발견(SSF의 GRG 등)은 `fetch` 에만 남기고 `parse_html` 은 **단일 페이지**만 처리(확장이 URL별로 창을 열어줌).

---

## Task 1: HTML 픽스처 캡처 + 테스트 하니스

**Files:**
- Create: `tests/sourcing/fixtures/ssf_sample.html`, `lemouton_sample.html`, `ssg_sample.html`, `ss_lemouton_sample.html`
- Create: `tests/sourcing/conftest.py` (픽스처 로더)

- [ ] **Step 1: 각 소싱처 대표 URL 의 raw HTML 저장 스크립트 작성·실행**

`tests/sourcing/_capture_fixtures.py`:
```python
"""대표 URL 의 raw HTML 을 픽스처로 저장(1회). 실행: python tests/sourcing/_capture_fixtures.py"""
import os, pathlib
from lemouton.sourcing.crawlers import build_crawlers
FIX = pathlib.Path(__file__).parent / "fixtures"
FIX.mkdir(exist_ok=True)
SAMPLES = {
    "ssf": "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good",
    "lemouton": "<르무통 공홈 대표 상품 URL>",   # 실행자: 소싱처 사전/등록 URL 에서 채움
    "ssg": "<SSG 대표 URL>",
    "ss_lemouton": "<스스르무통 대표 URL>",
}
crawlers = build_crawlers()
for key, url in SAMPLES.items():
    html = crawlers[key]._fetch_html(url)        # 크롤러의 네트워크 메서드 재사용
    (FIX / f"{key}_sample.html").write_text(html, encoding="utf-8")
    print(key, len(html), "bytes")
```
> 대표 URL 은 `source-registry`/등록 URL 에서 가져온다. `_fetch_html` 명칭이 다른 크롤러는 그 크롤러의 네트워크 메서드명으로 교체.

Run: `python tests/sourcing/_capture_fixtures.py`
Expected: 4개 `*_sample.html` 생성(각 수십 KB).

- [ ] **Step 2: conftest 픽스처 로더 작성**

`tests/sourcing/conftest.py`:
```python
import pathlib, pytest
FIX = pathlib.Path(__file__).parent / "fixtures"
@pytest.fixture
def html_of():
    def _load(key): return (FIX / f"{key}_sample.html").read_text(encoding="utf-8")
    return _load
```

- [ ] **Step 3: Commit**
```bash
git add tests/sourcing/fixtures tests/sourcing/conftest.py tests/sourcing/_capture_fixtures.py
git commit -m "test(sourcing): 4개 소싱처 HTML 픽스처 + 로더"
```

---

## Task 2: SSF `parse_html` 분리 (리팩터 템플릿)

**Files:**
- Modify: `lemouton/sourcing/crawlers/ssf.py` (`_fetch_one_page` → `parse_html` 분리)
- Test: `tests/sourcing/test_parse_html.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/sourcing/test_parse_html.py`:
```python
from lemouton.sourcing.crawlers import build_crawlers

def test_ssf_parse_html_from_fixture(html_of):
    c = build_crawlers()["ssf"]
    res = c.parse_html(html_of("ssf"), "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good")
    assert res.source == "ssf"
    assert res.product_name_raw           # 상품명 추출됨
    assert len(res.options) > 0           # 옵션 1개 이상
    assert all(o["price"] > 0 for o in res.options)   # 가격 양수
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/sourcing/test_parse_html.py::test_ssf_parse_html_from_fixture -v`
Expected: FAIL — `AttributeError: 'SsfCrawler' object has no attribute 'parse_html'`

- [ ] **Step 3: `_fetch_one_page` 를 `parse_html` 로 분리**

`ssf.py` 의 `_fetch_one_page(self, product_url)` 본문에서 `html = self._fetch_html(product_url)` **다음 줄부터 끝까지**(soup 생성·`_parse_*`·options 조립·`return CrawlResult(...)`)를 그대로 새 메서드로 옮긴다:
```python
def parse_html(self, html: str, product_url: str) -> CrawlResult:
    product_id = _extract_product_id(product_url)
    soup = BeautifulSoup(html, "lxml")
    # ↓ 기존 _fetch_one_page 의 파싱·조립 코드 그대로 (soup 생성 이후 전부)
    ...
    return CrawlResult(source="ssf", product_url=product_url, ...)

def _fetch_one_page(self, product_url: str) -> CrawlResult:
    html = self._fetch_html(product_url)
    return self.parse_html(html, product_url)
```
> `fetch` 의 다색 GRG 자동발견 로직은 건드리지 않는다(그대로 `_fetch_one_page` 호출). 동작 불변.

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/sourcing/test_parse_html.py::test_ssf_parse_html_from_fixture -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add lemouton/sourcing/crawlers/ssf.py tests/sourcing/test_parse_html.py
git commit -m "refactor(ssf): parse_html(html,url) 분리 — fetch 동작 불변"
```

---

## Task 3: 르무통 공홈 `parse_html` 분리

**Files:**
- Modify: `lemouton/sourcing/crawlers/lemouton.py`
- Test: `tests/sourcing/test_parse_html.py` (테스트 추가)

- [ ] **Step 1: 실패 테스트 추가**
```python
def test_lemouton_parse_html_from_fixture(html_of):
    c = build_crawlers()["lemouton"]
    res = c.parse_html(html_of("lemouton"), "<르무통 대표 URL>")
    assert res.source == "lemouton"
    assert res.product_name_raw and len(res.options) > 0
    assert all(o["price"] > 0 for o in res.options)
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/sourcing/test_parse_html.py::test_lemouton_parse_html_from_fixture -v` → FAIL(no attribute)

- [ ] **Step 3: 구현** — `lemouton.py` 에서 `fetch` 내부의 `html = self._fetch_html(url)`(또는 동등 네트워크 호출) **이후 파싱·조립 전체**를 `parse_html(self, html, product_url) -> CrawlResult` 로 분리. `fetch` 는 `return self.parse_html(self._fetch_html(product_url), product_url)`. `_parse_*` 헬퍼 재사용, `CrawlResult(source="lemouton", ...)`.
> 실행자: 이 파일을 열어 네트워크 호출 라인을 식별 → 그 아래 파싱부를 옮긴다. Playwright 기반(`lemouton_playwright.py`)이면 `page.content()` 로 받은 html 을 같은 `parse_html` 에 넘기도록 한다.

- [ ] **Step 4: 통과 확인** — Run 위 테스트 → PASS

- [ ] **Step 5: Commit** — `git commit -m "refactor(lemouton): parse_html 분리"`

---

## Task 4: SSG `parse_html` 분리

**Files:** Modify `lemouton/sourcing/crawlers/ssg.py` · Test `tests/sourcing/test_parse_html.py`

- [ ] **Step 1: 실패 테스트 추가**
```python
def test_ssg_parse_html_from_fixture(html_of):
    c = build_crawlers()["ssg"]
    res = c.parse_html(html_of("ssg"), "<SSG 대표 URL>")
    assert res.source == "ssg" and res.product_name_raw and len(res.options) > 0
    assert all(o["price"] > 0 for o in res.options)
```
- [ ] **Step 2: 실패 확인** — FAIL(no attribute)
- [ ] **Step 3: 구현** — Task 3 과 동일 패턴으로 `ssg.py` 의 fetch 파싱부를 `parse_html(html, url)` 로 분리, `fetch` 재배선, `CrawlResult(source="ssg", ...)`.
- [ ] **Step 4: 통과 확인** — PASS
- [ ] **Step 5: Commit** — `git commit -m "refactor(ssg): parse_html 분리"`

---

## Task 5: 스스르무통 `parse_html` 분리

**Files:** Modify `lemouton/sourcing/crawlers/ss_lemouton.py` · Test `tests/sourcing/test_parse_html.py`

- [ ] **Step 1: 실패 테스트 추가**
```python
def test_ss_lemouton_parse_html_from_fixture(html_of):
    c = build_crawlers()["ss_lemouton"]
    res = c.parse_html(html_of("ss_lemouton"), "<스스르무통 대표 URL>")
    assert res.source == "ss_lemouton" and res.product_name_raw and len(res.options) > 0
    assert all(o["price"] > 0 for o in res.options)
```
- [ ] **Step 2: 실패 확인** — FAIL(no attribute)
- [ ] **Step 3: 구현** — 동일 패턴으로 `ss_lemouton.py` 분리, `CrawlResult(source="ss_lemouton", ...)`.
- [ ] **Step 4: 통과 확인** — PASS
- [ ] **Step 5: Commit** — `git commit -m "refactor(ss_lemouton): parse_html 분리"`

---

## Task 6: `POST /api/sources/parse` 엔드포인트

**Files:**
- Create: `webapp/routes/api_sources_parse.py`
- Modify: `app.py` (블루프린트 등록)
- Test: `tests/sourcing/test_parse_endpoint.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/sourcing/test_parse_endpoint.py`:
```python
import os, json, pytest
os.environ.setdefault("ENVIRONMENT", "test")  # admin 게이트 우회

@pytest.fixture
def client():
    from app import create_app
    app = create_app(); app.config.update(TESTING=True)
    return app.test_client()

def test_parse_endpoint_ssf(client, html_of):
    r = client.post("/api/sources/parse", json={
        "source_key": "ssf",
        "url": "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good",
        "html": html_of("ssf"),
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["source"] == "ssf"
    assert len(d["options"]) > 0 and all(o["price"] > 0 for o in d["options"])

def test_parse_endpoint_unknown_source(client):
    r = client.post("/api/sources/parse", json={"source_key": "nope", "url": "x", "html": "<html></html>"})
    assert r.status_code == 400
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/sourcing/test_parse_endpoint.py -v`
Expected: FAIL — 404 (route 없음)

- [ ] **Step 3: 엔드포인트 구현**

`webapp/routes/api_sources_parse.py`:
```python
"""POST /api/sources/parse — 로컬 확장이 창에서 긁은 HTML 을 서버 기존 파서로 추출.

설계 A안: 무신사·롯데온은 확장 JS 가 직접 추출하고, 르무통·SSF·SSG·스스르무통은
이 엔드포인트가 crawlers[source_key].parse_html(html,url) 로 구조화한다.
"""
from __future__ import annotations
import os
from dataclasses import asdict
from flask import Blueprint, jsonify, request

bp = Blueprint("api_sources_parse", __name__, url_prefix="/api")

_PARSE_SOURCES = {"lemouton", "ssf", "ssg", "ss_lemouton"}


@bp.before_request
def _admin_only():
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.post("/sources/parse")
def parse_source_html():
    body = request.get_json(silent=True) or {}
    source_key = body.get("source_key")
    url = body.get("url")
    html = body.get("html")
    if source_key not in _PARSE_SOURCES:
        return jsonify(ok=False, error="bad_source",
                       message=f"parse 지원 소싱처 아님: {source_key}"), 400
    if not isinstance(url, str) or not isinstance(html, str) or not html.strip():
        return jsonify(ok=False, error="bad_input", message="url·html 필요"), 400
    from lemouton.sourcing.crawlers import build_crawlers
    crawler = build_crawlers().get(source_key)
    if crawler is None or not hasattr(crawler, "parse_html"):
        return jsonify(ok=False, error="no_parser"), 400
    try:
        res = crawler.parse_html(html, url)
    except Exception as e:  # 파싱 실패 — 셀렉터 불일치 등
        return jsonify(ok=False, error="parse_failed", message=str(e)[:200]), 200
    out = asdict(res)
    return jsonify(ok=True, **out)
```

- [ ] **Step 4: 블루프린트 등록**

`app.py` 에서 다른 블루프린트 등록부 근처에 추가:
```python
from webapp.routes.api_sources_parse import bp as api_sources_parse_bp
app.register_blueprint(api_sources_parse_bp)
```
> 등록 위치: `app.py` 의 `register_blueprint` 들이 모인 곳(다른 api_* 등록 라인 옆). 정확 라인은 실행자가 grep `register_blueprint` 로 확인.

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/sourcing/test_parse_endpoint.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**
```bash
git add webapp/routes/api_sources_parse.py app.py tests/sourcing/test_parse_endpoint.py
git commit -m "feat(sources): POST /api/sources/parse — HTML→기존 파서 구조화"
```

---

## Task 7: 정확도 패리티 게이트 (설계 §7)

**Files:** Test `tests/sourcing/test_parse_parity.py`

목적: `parse_html(fetch_html(url), url)` == `fetch(url)`(단일 페이지) 임을 보장 → "HTML 경로"가 "기존 fetch 경로"와 같은 가격·옵션을 낸다.

- [ ] **Step 1: 패리티 테스트 작성**

`tests/sourcing/test_parse_parity.py`:
```python
import pytest
from lemouton.sourcing.crawlers import build_crawlers

# 단일 페이지 파서가 있는 소싱처 + 대표 URL
CASES = {
    "ssf": "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good",
    "lemouton": "<르무통 대표 URL>",
    "ssg": "<SSG 대표 URL>",
    "ss_lemouton": "<스스르무통 대표 URL>",
}

@pytest.mark.parametrize("key,url", list(CASES.items()))
def test_parse_html_matches_single_page_fetch(key, url):
    c = build_crawlers()[key]
    html = c._fetch_html(url)                 # 네트워크 메서드명은 크롤러별 확인
    via_html = c.parse_html(html, url)
    via_fetch = c._fetch_one_page(url) if hasattr(c, "_fetch_one_page") else c.parse_html(c._fetch_html(url), url)
    # 핵심 필드 동일성 (옵션 가격/사이즈 집합)
    def key_set(r):
        return sorted((o["size_text"], o["price"], o["stock"]) for o in r.options)
    assert via_html.product_name_raw == via_fetch.product_name_raw
    assert key_set(via_html) == key_set(via_fetch)
```
> 라이브 네트워크 테스트라 CI 에선 `@pytest.mark.network` 로 분리 가능. 로컬 실검증용.

- [ ] **Step 2: 실행·확인**

Run: `pytest tests/sourcing/test_parse_parity.py -v`
Expected: PASS (4 소싱처). 실패 시 → 렌더/raw 차이 분석(설계 §9), 파서 보정 후 재실행.

- [ ] **Step 3: Commit**
```bash
git add tests/sourcing/test_parse_parity.py
git commit -m "test(sources): parse_html == fetch 단일페이지 패리티 게이트"
```

---

## Self-Review 결과

- **Spec 커버리지(§3.1·§3.2 서버 측):** Task 2~5 = crawlers `parse_html`, Task 6 = `/api/sources/parse`, Task 7 = §7 정확도 게이트(서버 측). ✅ (확장·컨트롤러·로그·라이브 검증은 Phase 2~5)
- **Placeholder:** `<...대표 URL>` 는 실행자가 등록 URL 에서 채우는 **데이터 값**(코드 placeholder 아님) — Task 1 에서 출처 명시. 크롤러별 네트워크 메서드명 차이는 "grep/열어 확인" 으로 명시.
- **타입 일관성:** `parse_html(self, html, product_url) -> CrawlResult` 시그니처 전 태스크 동일. 엔드포인트는 `asdict(CrawlResult)` 직렬화로 필드 일치.

---

## 실행 핸드오프

다음 단계는 이 계획을 task 단위로 구현하는 것. 실행 방식은 사용자가 선택(서브에이전트 / 인라인). Phase 1 완료 후 Phase 2 계획 작성.

# -*- coding: utf-8 -*-
"""[2026-07-23 리뷰지적 I2·M2] 서버→소싱처 **상세 보강 접속**의 킬스위치.

배경 — 상세가 페이지에 아예 없는 두 소싱처는 서버가 공개 문서 하나를 더 받아 채운다
(SSG iframe · 현대H몰 `item-dtl`). 그런데 기존 킬스위치
`server_crawl_gate.server_crawl_enabled()`(기본 OFF)를 **둘 다 안 지켰다**.

특히 SSG 는 「공개 API 1회 GET」이 아니라 **impersonate 세션**(curl_cffi chrome120 ·
홈 워밍업 · sleep 1.2)이고 `DEFAULT_TIMEOUT=30` 이 Flask 핫패스에서 **동기**로 돈다.
SSG·현대H몰이 서버 IP 를 조이면 **배포 없이** 끌 수 있어야 한다.

→ `server_detail_fetch_enabled()` 신설. **기본 ON**(오늘 라이브 동작 유지) ·
  `MOUM_SERVER_DETAIL_FETCH=0` 이면 OFF. 크롤 자체를 켜는 `MOUM_SERVER_CRAWL` 과는
  **다른 손잡이**다(이건 '상세 한 장 더 받기'만 끈다).

M2 — 현대H몰 상세 API 호출이 `status == 'ok'` 밖에 있어 **실패건에도 외부 호출**이
  나갔다. 실패는 보통 WAF·차단인데 거기에 요청을 한 번 더 얹는 꼴이라 더 조인다.
"""
import os

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M                        # noqa: E402
from lemouton.sources.service import upsert_source_product   # noqa: E402
from shared.db import Base                                   # noqa: E402

HMALL_URL = "https://www.hmall.com/md/pda/itemPtc?slitmCd=2225894478"


# ═════════════════════════════════════════════════════════════════
# 1) 손잡이 자체 — 기본 ON, `0` 이면 OFF
# ═════════════════════════════════════════════════════════════════
def test_상세보강_기본값은_켜짐이다(monkeypatch):
    """오늘 라이브가 이걸로 상세를 채우고 있다 — 기본 OFF 로 바꾸면 등록이 막힌다."""
    from lemouton.sourcing import server_crawl_gate as G

    monkeypatch.delenv("MOUM_SERVER_DETAIL_FETCH", raising=False)
    assert G.server_detail_fetch_enabled() is True


def test_상세보강은_env_0_으로_배포없이_끈다(monkeypatch):
    from lemouton.sourcing import server_crawl_gate as G

    monkeypatch.setenv("MOUM_SERVER_DETAIL_FETCH", "0")
    assert G.server_detail_fetch_enabled() is False
    monkeypatch.setenv("MOUM_SERVER_DETAIL_FETCH", "1")
    assert G.server_detail_fetch_enabled() is True


def test_크롤킬스위치와_상세보강킬스위치는_다른_손잡이다(monkeypatch):
    """`MOUM_SERVER_CRAWL`(기본 OFF)을 켜고 끄는 게 상세 보강을 좌우하면 안 된다."""
    from lemouton.sourcing import server_crawl_gate as G

    monkeypatch.delenv("MOUM_SERVER_DETAIL_FETCH", raising=False)
    monkeypatch.delenv("MOUM_SERVER_CRAWL", raising=False)
    assert G.server_crawl_enabled() is False
    assert G.server_detail_fetch_enabled() is True


# ═════════════════════════════════════════════════════════════════
# 2) SSG — parse 경로의 iframe GET
# ═════════════════════════════════════════════════════════════════
def _ssg_fixture() -> str:
    import pathlib
    p = (pathlib.Path(__file__).resolve().parents[1]
         / "sources" / "fixtures" / "ssg_product.html")
    if not p.exists():
        pytest.skip("fixture 없음: ssg_product.html")
    return p.read_text(encoding="utf-8")


SSG_URL = ("https://www.ssg.com/item/itemView.ssg?itemId=1000809938058"
           "&siteNo=6009&salestrNo=6009")


def _post_ssg_parse(monkeypatch, *, flag):
    """/api/sources/parse 를 한 번 호출하고 SSG iframe GET 이 나갔는지 돌려준다."""
    import webapp.routes.api_sources_parse as _mod
    from lemouton.sourcing.crawlers import ssg as _ssg

    calls: list = []

    def _spy(url, html, *a, **kw):
        calls.append(url)
        return "<div>상세</div>"

    monkeypatch.setattr(_ssg, "fetch_detail_html", _spy)
    if flag is None:
        monkeypatch.delenv("MOUM_SERVER_DETAIL_FETCH", raising=False)
    else:
        monkeypatch.setenv("MOUM_SERVER_DETAIL_FETCH", flag)

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        r = app.test_client().post("/api/sources/parse", json={
            "source_key": "ssg", "url": SSG_URL, "html": _ssg_fixture()})
    assert r.status_code == 200, r.get_data(as_text=True)
    return calls


def test_SSG_상세보강은_기본값에서는_그대로_나간다(monkeypatch):
    """회귀 핀 — 게이트를 단다고 오늘 되던 게 꺼지면 안 된다."""
    assert _post_ssg_parse(monkeypatch, flag=None), "기본값인데 SSG 상세 보강이 안 나갔다"


def test_SSG_상세보강은_킬스위치가_꺼지면_접속하지_않는다(monkeypatch):
    """🔴 impersonate 세션(chrome120·홈 워밍업·sleep 1.2)이 Flask 핫패스에서 동기로 돈다.

    SSG 가 서버 IP 를 조이면 **배포 없이** 끌 수 있어야 한다.
    """
    assert _post_ssg_parse(monkeypatch, flag="0") == [], \
        "킬스위치를 껐는데도 서버가 SSG 에 접속했다"


# ═════════════════════════════════════════════════════════════════
# 3) 현대H몰 — crawl-result 경로의 item-dtl GET
# ═════════════════════════════════════════════════════════════════
@pytest.fixture
def hmall_eng():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    seed = Session(eng)
    seed.add(M.Model(model_code="HM", model_name_raw="H몰테스트"))
    seed.commit()
    upsert_source_product(seed, site="hmall", url=HMALL_URL)
    seed.commit()
    seed.close()
    return eng


def _post_hmall(monkeypatch, hmall_eng, *, flag=None, status="ok"):
    """crawl-result 를 한 번 호출하고 item-dtl GET 이 나갔는지 돌려준다."""
    import webapp.routes.api_pricing as _mod
    from lemouton.sourcing.crawlers import hmall as _h

    calls: list = []
    monkeypatch.setattr(_h, "fetch_combo_persize_options", lambda *a, **kw: [])
    monkeypatch.setattr(_h, "fetch_detail_html",
                        lambda url, *a, **kw: (calls.append(url), "<div>상세</div>")[1])
    if flag is None:
        monkeypatch.delenv("MOUM_SERVER_DETAIL_FETCH", raising=False)
    else:
        monkeypatch.setenv("MOUM_SERVER_DETAIL_FETCH", flag)

    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    item = {"url": HMALL_URL, "price": 126900, "stock": 3, "status": status,
            "product_name": "현대H몰 상품"}
    if status != "ok":
        item["price"] = None
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(hmall_eng)):
        r = app.test_client().post("/api/sources/crawl-result", json={"items": [item]})
    assert r.status_code == 200, r.get_data(as_text=True)
    return calls


def test_현대H몰_상세보강은_기본값에서는_그대로_나간다(monkeypatch, hmall_eng):
    assert _post_hmall(monkeypatch, hmall_eng), "기본값인데 현대H몰 상세 보강이 안 나갔다"


def test_현대H몰_상세보강은_킬스위치가_꺼지면_접속하지_않는다(monkeypatch, hmall_eng):
    assert _post_hmall(monkeypatch, hmall_eng, flag="0") == [], \
        "킬스위치를 껐는데도 서버가 현대H몰에 접속했다"


def test_현대H몰_상세보강은_실패건에는_아예_나가지_않는다(monkeypatch, hmall_eng):
    """🟠 [리뷰지적 M2] 실패(status != 'ok')는 보통 WAF·차단이다.

    거기에 외부 요청을 한 번 더 얹으면 더 조인다. 게다가 실패건의 상세는 어차피
    수신 게이트(`test_images_detail_receive_gate`)가 저장을 막는다 = 순수 낭비.
    """
    assert _post_hmall(monkeypatch, hmall_eng, status="error") == [], \
        "실패 크롤인데 서버가 현대H몰에 상세를 받으러 갔다"

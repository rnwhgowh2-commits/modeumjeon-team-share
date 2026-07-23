"""POST /api/sources/parse — 로컬 확장이 창에서 긁은 HTML 을 서버 기존 파서로 추출.

설계 A안: 무신사·롯데온은 확장 JS 가 직접 추출하고, 르무통·SSF·SSG·스스르무통은
이 엔드포인트가 crawlers[source_key].parse_html(html,url) 로 구조화한다.
"""
from __future__ import annotations
import logging
import os
from dataclasses import asdict
from flask import Blueprint, jsonify, request

from shared.db import SessionLocal  # 모듈 레벨 — 옵션 영속 헬퍼가 사용(테스트 패치 지점)

bp = Blueprint("api_sources_parse", __name__, url_prefix="/api")

_PARSE_SOURCES = {"lemouton", "ssf", "ssg", "ss_lemouton", "hmall", "lotteimall"}


@bp.before_request
def _admin_only():
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.errorhandler(Exception)
def _always_json_error(e):
    """[2026-06-28 O13] 이 blueprint(/api/sources/*) 는 확장이 r.json() 으로 받으므로
    예외가 HTML 에러페이지로 새면 클라가 SyntaxError 로 조용히 터진다(전체크롤 일부 건 실패).
    → 미처리 예외도 항상 JSON 으로 표면화. app 전역 핸들러 아님(이 blueprint 한정, 부작용 없음).
    (인프라 502/504 프록시 HTML 은 Flask 밖이라 못 잡음 — 클라 ext_bridge fetchJson 가드가 보완.)"""
    from werkzeug.exceptions import HTTPException
    code = e.code if isinstance(e, HTTPException) else 500
    return jsonify(ok=False, error="server_error", detail=str(e)[:200]), code


@bp.post("/sources/parse")
def parse_source_html():
    body = request.get_json(silent=True) or {}
    source_key = body.get("source_key")
    url = body.get("url")
    html = body.get("html")
    # 스스 per-SKU 재고 맵("색상||사이즈"→수량) — 확장이 n/v2 API 로 수집해 동봉(선택).
    sku_stock = body.get("sku_stock") if isinstance(body.get("sku_stock"), dict) else None
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
        # [2026-06-20 money-safe] SSG 딜페이지(dealItemView) — 자동 '대표상품' 크롤 금지.
        #   딜 페이지 itemView 링크에 SSG 광고 캐러셀(data-advert) 상품이 섞여 '첫 itemView'가
        #   무관한 광고상품(예: 여성 와이드 바지)일 수 있음 → 엉뚱한 가격/재고(금전 위험).
        #   딜은 모델 선택(resolve_deal_models)으로 단일 itemView URL 을 지정해 크롤해야 한다.
        if source_key == "ssg" and "uitemObjArr.push" not in html:
            # 딜 HTML 직접 파싱(옵션 없음=정직한 '데이터 없음'). 대표상품 자동선택 폐기.
            res = crawler.parse_html(html, url)
        elif source_key == "ss_lemouton" and sku_stock:
            # ss_lemouton 만 sku_stock 을 받아 옵션별 재고 교정. 타 파서는 (html,url) 시그니처.
            res = crawler.parse_html(html, url, sku_stock=sku_stock)
        else:
            res = crawler.parse_html(html, url)
    except Exception as e:
        return jsonify(ok=False, error="parse_failed", message=str(e)[:200]), 200
    payload = asdict(res)
    # [2026-07-23 M3] 소싱처 카테고리 경로(빵부스러기) 사전 적재. 적재 실패가
    #   파싱 응답을 죽이면 안 된다 — best-effort(try/except + 로그 한 줄).
    try:
        _ingest_source_category(source_key, payload.get("category_path"))
    except Exception:
        logging.getLogger(__name__).warning(
            "[cat3] 카테고리 적재 실패 source=%s url=%s", source_key, url)
    # ★ 2026-06-22 — navGrab(SSF·SSG·르무통·스스) 동적 혜택 서버측 저장.
    #   서버 크롤러가 옵션에 채운 동적 키(멤버십포인트·기프트포인트·SSG MONEY·상품쿠폰 등)를
    #   여기서 SourceProduct.dynamic_benefits_json 에 직접 저장한다(확장이 그 키를 드롭해
    #   라이브에서 비어 있던 사고 수정). 무신사·롯데온은 직읽기 경로(별도)라 여기 안 옴.
    try:
        _save_navgrab_dynamic_benefits(source_key, url, payload.get("options") or [])
    except Exception:
        pass  # 저장 실패해도 파싱 결과 반환은 유지(가격/재고는 crawl-result 가 별도 저장)
    # ★ 2026-06-26 — 색·사이즈별 SourceOption 을 서버측에서 '생성' 영속.
    #   배경: 확장 저장경로(ext_bridge→crawl-result)는 options[] 를 전송하지 않고,
    #   백엔드 _persist_option_stocks 도 '기존' SO 만 갱신(생성 안 함) → 신규 등록 URL 은
    #   옵션행이 0개라 매트릭스가 상품 last_stock(전 사이즈 합계)으로 균일 폴백
    #   (예: 르무통 올리브그린 전 사이즈 53개, 실제 품절인 265 도 '53·있음' 둔갑).
    #   여기 parse 가 실 per-사이즈 재고를 이미 손에 쥐고 있으므로(option_stock_data),
    #   서버사이드 _ingest 와 동일하게 옵션행을 생성(upsert)+단품 색스코프+stale prune.
    try:
        _persist_navgrab_option_stocks(source_key, url, payload.get("options") or [])
    except Exception:
        pass  # best-effort — 실패해도 파싱 결과 반환·crawl-result 저장은 유지
    # [2026-07-11] 상품명 치유 — 확장 저장 경로는 product_name 을 갱신하지 않아
    #   옛 파서가 박은 '메인메뉴'가 영영 남았다(라이브 실측). parse 는 매 크롤마다
    #   불리고 정확한 og:title(product_name_raw)을 쥐고 있으므로 여기서 URL+site 매칭 상품에 치유.
    try:
        _heal_product_name(source_key, url, payload.get("product_name_raw"))
    except Exception:
        pass  # best-effort
    return jsonify(ok=True, **payload)


def _ingest_source_category(source_key: str, category_path) -> None:
    """parse 결과의 카테고리 경로를 소싱처 카테고리 사전(source_categories)에 적재.

    빈 경로는 ingest_path 가 알아서 거른다(파싱 실패를 '카테고리 없음'으로 둔갑 금지).
    """
    if not category_path:
        return
    import datetime as _dt
    from lemouton.registration.source_category_ingest import ingest_path
    s = SessionLocal()
    try:
        ingest_path(s, source_key, category_path, now=_dt.datetime.now(_dt.timezone.utc))
        s.commit()
    finally:
        s.close()


def _persist_navgrab_option_stocks(source_key: str, url: str, options: list) -> None:
    """parse 결과 options 의 색·사이즈별 실재고/실가격을 SourceOption 에 영속(생성 포함).

    서버사이드 _ingest(service.py)와 동일 규칙:
      - upsert_source_option 으로 (색,사이즈) 행 생성·갱신(없으면 INSERT)
      - 단품(url_type='단품') SP 는 등록색 스코프(형제색 오염 차단)
      - 이번 크롤에 없는 옛 (색,사이즈) 조합은 soft-delete(stale prune) — 재크롤 무결성
      - 재고/가격 폴백 금지: 파서가 준 값(품절 0 포함) 그대로. 폴백·추정 없음.
    """
    if not isinstance(options, list) or not options:
        return
    from lemouton.sources.service import (
        upsert_source_product, persist_crawled_options)
    s = SessionLocal()
    try:
        sp = upsert_source_product(s, site=source_key, url=url)
        s.flush()
        persist_crawled_options(s, source_product=sp, options=options)
        s.commit()
    finally:
        s.close()


def _heal_product_name(source_key: str, url: str, new_name) -> None:
    """URL+site 매칭 SourceProduct 의 상품명을 치유(비었/내비쓰레기 → 정확한 이름)."""
    from lemouton.sources.service import normalize_url, apply_name_heal
    from lemouton.sources.models import SourceProduct
    from shared.db import SessionLocal
    if not (new_name and str(new_name).strip()):
        return
    s = SessionLocal()
    try:
        target = normalize_url(url)
        sp = next((p for p in s.query(SourceProduct)
                   .filter(SourceProduct.deleted_at.is_(None)).all()
                   if p.url and normalize_url(p.url) == target
                   and getattr(p, "site", None) == source_key), None)
        if sp is not None and apply_name_heal(sp, new_name):
            s.commit()
    finally:
        s.close()


def _save_navgrab_dynamic_benefits(source_key: str, url: str, options: list) -> None:
    """parse 결과 options 의 동적 혜택을 (url + site=source_key) 매칭 SourceProduct 에 저장.

    ★ site 일치 필수 — 같은 URL 이 여러 SourceProduct(site 다름; 예: 'lemouton'·'ssf')에
      걸려 있어, site 를 안 가리면 엉뚱한 상품에 저장돼 compute_breakdown(site=해당소싱처)이
      못 읽는다(라이브 SSF 멤버십포인트 미반영 실증·수정). source_key 와 site 일치 상품에만 저장.
    """
    from lemouton.pricing.benefit_parse import extract_dynamic_benefits_from_options
    from lemouton.sources.service import normalize_url
    from lemouton.sources.models import SourceProduct
    from shared.db import SessionLocal
    import json as _json
    dyn = extract_dynamic_benefits_from_options(options)
    s = SessionLocal()
    try:
        target = normalize_url(url)
        sp = next((p for p in s.query(SourceProduct)
                   .filter(SourceProduct.deleted_at.is_(None)).all()
                   if p.url and normalize_url(p.url) == target
                   and getattr(p, "site", None) == source_key), None)
        if sp is None:
            return  # site 일치 상품 없음 — 잘못된 site 에 저장하지 않음
        sp.dynamic_benefits_json = _json.dumps(dyn, ensure_ascii=False) if dyn else None
        s.commit()
    finally:
        s.close()


@bp.post("/sources/resolve-deal-models")
def resolve_deal_models_ep():
    """[2026-06-19 모델매핑] 멀티모델 딜 URL → 묶인 모델 목록 + 우리 모델 자동매칭.

    body: {url, target_model?} — target_model(예: "메이트") 주면 자동매칭 결과 동봉.
    Returns: {ok, is_multi, models:[{item_id,name,url}], matched, ambiguous}
    """
    body = request.get_json(silent=True) or {}
    url = body.get("url")
    target = (body.get("target_model") or "").strip()
    html_in = body.get("html")  # [2026-06-21] 브라우저(한국 IP)가 받은 딜 HTML — 서버 fetch 불안정 회피
    if not isinstance(url, str) or not url.strip():
        return jsonify(ok=False, error="url 필요"), 400
    from lemouton.sourcing.crawlers import build_crawlers
    from lemouton.sourcing.crawlers.ssg import resolve_deal_models, match_deal_model
    crawler = build_crawlers().get("ssg")
    if crawler is None or not hasattr(crawler, "_fetch_html"):
        return jsonify(ok=False, error="ssg 크롤러 없음"), 400
    # 딜 HTML — 브라우저가 보낸 게 있으면 그걸 우선(서버 도쿄 IP fetch 가 간헐적으로 단일상품
    #   HTML 을 반환해 '모델 선택 불필요' 오판하던 문제 회피). 없으면 서버 fetch.
    url_is_deal = 'dealitemview' in url.lower()
    if isinstance(html_in, str) and len(html_in) > 1000:
        html = html_in
    else:
        try:
            html = crawler._fetch_html(url)
        except Exception as e:
            return jsonify(ok=False, error=f"딜 페이지 로드 실패: {str(e)[:120]}"), 200
    # 단일상품(딜 URL 아님) + uitemObj 존재 → 모델 선택 불필요.
    #   ★ 딜(dealItemView) URL 이면 uitemObj 유무와 무관하게 항상 모델 링크를 해석한다
    #   (딜 페이지에 대표상품 uitemObj 가 끼어 있어도 단일상품으로 오판하지 않게).
    if (not url_is_deal) and "uitemObjArr.push" in html:
        return jsonify(ok=True, is_multi=False, models=[], matched=None, ambiguous=False)
    try:
        models = resolve_deal_models(url, html, fetch_html=crawler._fetch_html,
                                     parse_html=crawler.parse_html)
    except Exception as e:
        return jsonify(ok=False, error=f"딜 모델 해석 실패: {str(e)[:120]}"), 200
    if not models:
        # 묶인 모델 링크를 못 찾음 = 단일상품으로 취급(매핑 불필요)
        return jsonify(ok=True, is_multi=False, models=[], matched=None, ambiguous=False)
    matched, ambiguous = match_deal_model(models, target) if target else (None, False)
    return jsonify(ok=True, is_multi=True, models=models, matched=matched, ambiguous=ambiguous)

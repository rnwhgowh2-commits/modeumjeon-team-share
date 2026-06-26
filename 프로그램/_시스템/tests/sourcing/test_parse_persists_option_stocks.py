# -*- coding: utf-8 -*-
"""[TEST] /api/sources/parse 가 색·사이즈별 SourceOption 을 '생성'해 영속.

배경(르무통 올리브그린 265 재고 둔갑, 2026-06-26):
  신규 등록 URL 을 확장으로 크롤하면 위젯엔 '완료'가 떠도 매트릭스가 올리브그린
  전 사이즈를 균일 53개(=상품 재고 합계)로 표시하고, 실제 품절인 265 도 '53개·있음'
  으로 둔갑했다.

  근본원인(2중 누락):
   1) 확장 저장경로(ext_bridge→crawl-result)가 옵션 배열(options[])을 전송 안 함.
   2) 백엔드 _persist_option_stocks 는 '기존' SourceOption 만 갱신, 생성 안 함
      → 신규 URL 은 옵션행 0개 → per-사이즈 재고가 DB 에 안 남음
      → 매트릭스가 상품 last_stock(합계 53)을 전 사이즈에 균일 폴백.

  수정: 서버 파싱 단계(/api/sources/parse)가 서버사이드 _ingest 와 동일하게
  색·사이즈별 SourceOption 을 upsert(생성 포함) + 단품 색 스코프 + stale prune.
  파서는 이미 실재고(265=0)를 손에 쥐고 있으므로 거기서 영속하면 확장/재설치 불필요.

이 테스트가 'parse 가 옵션행을 생성·영속'을 영구 잠근다.
"""
import os
import pytest
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

import lemouton.sourcing.models as M
from lemouton.sources.models import SourceProduct, SourceOption
from shared.db import Base

URL = "https://www.lemouton.co.kr/product/detail.html?product_no=122"

# 라이브 올리브그린 실재고 (curl 로 확인) — 265 만 품절(0)
OLIVE = [
    {"color_text": "올리브그린", "size_text": f"{sz}mm", "stock": st, "price": 116900}
    for sz, st in [
        (220, 1), (225, 2), (230, 5), (235, 4), (240, 5), (245, 2), (250, 4),
        (255, 2), (260, 2), (265, 0), (270, 7), (275, 1), (280, 9), (290, 9),
    ]
]


def _make_db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    from sqlalchemy import text
    s.execute(text("PRAGMA foreign_keys=ON"))
    return s, eng


def _seed(s):
    s.add(M.Model(model_code="LT", model_name_raw="르무통메이트"))
    for sz in (220, 265, 270):
        s.add(M.Option(canonical_sku=f"LT-올리브그린-{sz}", model_code="LT",
                       color_code="올리브그린", size_code=str(sz), is_active=True))
    s.commit()  # FK 부모(Model/Option) 먼저 커밋
    bsu = M.BundleSourceUrl(model_code="LT", source_key="lemouton",
                            url=URL, sort_order=0, url_type="단품")
    s.add(bsu)
    s.flush()
    # 단품 URL = 그 색 전 사이즈에 연결 (매트릭스 컬럼 + _resolve_reg_color 색 스코프용)
    for sz in (220, 265, 270):
        s.add(M.OptionSourceUrlLink(option_canonical_sku=f"LT-올리브그린-{sz}",
                                    bundle_source_url_id=bsu.id))
    s.commit()
    return bsu


def _persist(s, eng, options):
    """SessionLocal 을 테스트 세션 팩토리로 패치하고 헬퍼 실행."""
    import webapp.routes.api_sources_parse as _mod
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        _mod._persist_navgrab_option_stocks("lemouton", URL, options)


def _so(eng, size):
    q = Session(eng)
    try:
        return (q.query(SourceOption)
                .join(SourceProduct, SourceOption.source_product_id == SourceProduct.id)
                .filter(SourceProduct.url.like("%product_no=122%"),
                        SourceOption.size_text == f"{size}mm",
                        SourceOption.deleted_at.is_(None)).first())
    finally:
        q.close()


def test_creates_persize_sourceoptions_with_real_stock():
    """신규 URL: 옵션행 0개 → 색·사이즈별 SourceOption 생성, 265=품절(0)."""
    s, eng = _make_db()
    _seed(s)
    # 사전: SourceOption 없음
    assert Session(eng).query(SourceOption).count() == 0

    _persist(s, eng, OLIVE)

    # SourceProduct + 14개 SourceOption 생성
    assert Session(eng).query(SourceProduct).filter(
        SourceProduct.url.like("%product_no=122%")).count() == 1
    assert Session(eng).query(SourceOption).filter(
        SourceOption.deleted_at.is_(None)).count() == 14

    # ★ 핵심: 265 는 품절(0), 270 은 7 — 균일 53 이 아니라 실 per-사이즈
    assert _so(eng, 265).current_stock == 0, "265 품절이 반영 안 됨"
    assert _so(eng, 270).current_stock == 7
    assert _so(eng, 230).current_stock == 5


def test_corrects_uniform_fallback_and_prunes_stale():
    """기존 잘못된 균일행(53) → 실재고로 교정 + 이번 크롤에 없는 조합 prune."""
    s, eng = _make_db()
    bsu = _seed(s)
    # 잘못된 사전상태: 모든 사이즈 current_stock=53 (상품총합 폴백 둔갑) + 안 파는 295 사이즈
    sp = SourceProduct(site="lemouton", url=URL)
    s.add(sp); s.flush()
    for sz in (265, 270, 295):
        s.add(SourceOption(source_product_id=sp.id, color_text="올리브그린",
                           size_text=f"{sz}mm", current_stock=53, current_price=116900))
    s.commit()

    _persist(s, eng, OLIVE)

    assert _so(eng, 265).current_stock == 0, "균일 53 → 품절 0 교정 실패"
    assert _so(eng, 270).current_stock == 7
    # 295 = 이번 크롤에 없음 → soft-delete(prune)
    assert _so(eng, 295) is None, "안 파는 295 사이즈가 prune 안 됨"


def test_matrix_shows_persize_not_uniform():
    """end-to-end: 영속 후 매트릭스가 265=품절, 270=실수량 (균일 53 아님)."""
    s, eng = _make_db()
    _seed(s)
    # 매트릭스 소싱처 컬럼용 SourceRegistry(lemouton 도메인)
    from lemouton.sourcing.models_pricing import SourceRegistry
    s.add(SourceRegistry(name="르무통 공홈", main_url="https://www.lemouton.co.kr", sort_order=0))
    s.commit()

    _persist(s, eng, OLIVE)

    from webapp.routes.api_pricing import _option_matrix_data
    import webapp.routes.api_pricing as _mod
    with patch.object(_mod, "SessionLocal", return_value=Session(eng)):
        result = _option_matrix_data("LT")
    assert result.get("ok"), result

    def _olive_lemouton_stock(sku):
        o = next((x for x in result["options"] if x.get("sku") == sku), None)
        assert o, f"{sku} 없음"
        e = next((src for src in o.get("sources", [])
                  if src.get("source_key") == "lemouton"), None)
        assert e, f"{sku} lemouton 소싱처 항목 없음: {o.get('sources')}"
        return e.get("crawled_stock")

    assert _olive_lemouton_stock("LT-올리브그린-265") == 0, "매트릭스 265 가 품절(0) 아님"
    assert _olive_lemouton_stock("LT-올리브그린-270") == 7, "매트릭스 270 이 실수량(7) 아님"

# -*- coding: utf-8 -*-
"""검증 화면 ②③ 자동 채움 — DB 조회 계층 테스트.

이 테스트가 지키는 것:
  · 크롤 데이터가 없으면 폴백·추정 없이 None + 사유 (→ 확인불가)
  · URL 저장소가 분열돼 있어도(legacy / 현행) SKU 를 찾아낸다
  · 카탈로그 소싱처(롯데아이몰·현대H몰)는 'key:<source_key>' 합성 source_id
  · ★ 롯데아이몰 사고 재현 — 표면가가 갈리면 '크롤 파싱 문제'로 지목되는가
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.sourcing.models          # noqa: F401  FK 타겟 등록
import lemouton.sourcing.models_pricing  # noqa: F401
import lemouton.templates.models         # noqa: F401
import lemouton.sources.models           # noqa: F401
import lemouton.multitenancy.models      # noqa: F401
import lemouton.pricing.settings         # noqa: F401

from lemouton.sourcing import price_verify_service as pvs
from lemouton.sourcing import price_verify as pv
from lemouton.sources.models import SourceProduct
from lemouton.sourcing.models import BundleSourceUrl, OptionSourceUrlLink
from lemouton.sourcing.models_pricing import SourceRegistry, OptionSourceUrl

# 롯데아이몰 라이브 실측 (르무통 메이트 메리노울 운동화)
URL = "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559417201"
SURFACE = 116900   # ★ 정답 — 카드 미적용 22% 할인가
MAXPRICE = 108720  # ✗ 최대할인가(카드 청구할인 포함) — 표면가가 아니다


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _seed_product(db, *, site="lotteimall", url=URL, last_price=SURFACE):
    sp = SourceProduct(site=site, url=url, last_price=last_price,
                       last_status="ok", product_name="메리노울 운동화")
    db.add(sp)
    db.commit()
    return sp


class TestFindSourceProduct:
    def test_없으면_None(self, db):
        assert pvs.find_source_product(db, "lotteimall", URL) is None

    def test_찾는다(self, db):
        sp = _seed_product(db)
        assert pvs.find_source_product(db, "lotteimall", URL).id == sp.id

    def test_추적파라미터_붙어도_정규화_매칭(self, db):
        _seed_product(db)
        got = pvs.find_source_product(db, "lotteimall", URL + "&NaPm=abc123")
        assert got is not None, "추적 파라미터 때문에 못 찾으면 안 된다"

    def test_소싱처가_다르면_못찾는다(self, db):
        _seed_product(db)
        assert pvs.find_source_product(db, "hmall", URL) is None

    def test_삭제된_상품은_제외(self, db):
        from datetime import datetime, timezone
        sp = _seed_product(db)
        sp.deleted_at = datetime.now(timezone.utc)
        db.commit()
        assert pvs.find_source_product(db, "lotteimall", URL) is None


class TestFindSku:
    def test_없으면_None(self, db):
        assert pvs.find_sku(db, "lotteimall", URL) is None

    def test_현행경로_BundleSourceUrl로_찾는다(self, db):
        bsu = BundleSourceUrl(model_code="MTN-001", source_key="lotteimall", url=URL)
        db.add(bsu)
        db.flush()
        db.add(OptionSourceUrlLink(bundle_source_url_id=bsu.id,
                                   option_canonical_sku="MTN-001-BLK-250"))
        db.commit()
        assert pvs.find_sku(db, "lotteimall", URL) == "MTN-001-BLK-250"

    def test_legacy경로_OptionSourceUrl로도_찾는다(self, db):
        db.add(OptionSourceUrl(canonical_sku="MTN-001-BLK-260", source_id=1,
                               product_url=URL))
        db.commit()
        assert pvs.find_sku(db, "lotteimall", URL) == "MTN-001-BLK-260"

    def test_다른소싱처의_같은URL은_안잡힌다(self, db):
        bsu = BundleSourceUrl(model_code="MTN-001", source_key="hmall", url=URL)
        db.add(bsu)
        db.flush()
        db.add(OptionSourceUrlLink(bundle_source_url_id=bsu.id,
                                   option_canonical_sku="X"))
        db.commit()
        assert pvs.find_sku(db, "lotteimall", URL) is None


class TestResolveSourceId:
    def test_카탈로그_소싱처는_합성문자열(self, db):
        # 롯데아이몰·현대H몰은 SourceRegistry 에 행이 없다 → 'key:' 접두
        assert pvs.resolve_source_id(db, "lotteimall") == "key:lotteimall"
        assert pvs.resolve_source_id(db, "hmall") == "key:hmall"

    def test_레지스트리에_있으면_정수id(self, db):
        r = SourceRegistry(name="무신사", main_url="https://musinsa.com")
        db.add(r)
        db.commit()
        assert pvs.resolve_source_id(db, "musinsa") == r.id

    def test_레지스트리에_없으면_합성문자열_폴백(self, db):
        assert pvs.resolve_source_id(db, "musinsa") == "key:musinsa"


class TestCollect:
    def test_크롤데이터_없으면_전부_None_과_사유(self, db):
        got = pvs.collect(db, "lotteimall", URL)
        assert got["ours_surface_price"] is None
        assert got["computed_final_price"] is None
        assert got["computed_steps"] is None
        assert "크롤 데이터가" in got["compute_error"]

    def test_표면가_없으면_계산_안하고_사유(self, db):
        _seed_product(db, last_price=None)
        got = pvs.collect(db, "lotteimall", URL)
        assert got["ours_surface_price"] is None
        assert got["computed_steps"] is None
        assert "표면가가 없습니다" in got["compute_error"]

    def test_SKU_연결없으면_표면가는_주되_계산은_확인불가(self, db):
        _seed_product(db)
        got = pvs.collect(db, "lotteimall", URL)
        assert got["ours_surface_price"] == SURFACE, "② 는 줄 수 있어야 한다"
        assert got["computed_steps"] is None
        assert "옵션(SKU)" in got["compute_error"]

    def test_동적혜택_원문을_그대로_노출(self, db):
        sp = _seed_product(db)
        sp.dynamic_benefits_json = '{"point_rewards": 2000}'
        db.commit()
        got = pvs.collect(db, "lotteimall", URL)
        assert got["dynamic_benefits"] == {"point_rewards": 2000}

    def test_깨진_JSON은_None_으로_삼키되_표면가는_유지(self, db):
        sp = _seed_product(db)
        sp.dynamic_benefits_json = "{깨진"
        db.commit()
        got = pvs.collect(db, "lotteimall", URL)
        assert got["dynamic_benefits"] is None
        assert got["ours_surface_price"] == SURFACE


class TestLotteimallIncidentReplay:
    """★ 이번 사고 재현 — 표면가 자리에 카드할인 먹은 값이 들어간 경우."""

    def test_최대할인가를_표면가로_집으면_크롤파싱_문제로_지목된다(self, db):
        # 크롤이 잘못 집은 상태: 표면가 자리에 최대할인가(카드 포함)가 들어있다
        _seed_product(db, last_price=MAXPRICE)
        got = pvs.collect(db, "lotteimall", URL)

        # 사장님이 실제 페이지에서 본 값 = 116,900 (카드 미적용 할인가)
        res = pv.judge(human_surface=SURFACE,
                       ours_surface=got["ours_surface_price"],
                       human_benefits=[], engine_steps=got["computed_steps"])

        assert res["verdict"] == pv.VERDICT_MISMATCH
        assert pv.LAYER_CRAWL in res["diverged_layers"], "크롤 파싱 문제로 지목돼야 한다"
        assert "크롤 파싱" in res["summary"]
        # 차이 = 카드 청구할인액만큼 (−8,180)
        assert res["layers"][pv.LAYER_CRAWL]["diff"] == MAXPRICE - SURFACE == -8180

    def test_제대로_집었으면_표면가층은_일치(self, db):
        _seed_product(db, last_price=SURFACE)
        got = pvs.collect(db, "lotteimall", URL)
        res = pv.judge(human_surface=SURFACE,
                       ours_surface=got["ours_surface_price"],
                       human_benefits=[], engine_steps=got["computed_steps"])
        assert res["layers"][pv.LAYER_CRAWL]["verdict"] == pv.VERDICT_MATCH
        # 단, 혜택 미입력 + 계산 불가 → 전체는 확인불가 (일치로 승격 금지)
        assert res["verdict"] == pv.VERDICT_UNKNOWN

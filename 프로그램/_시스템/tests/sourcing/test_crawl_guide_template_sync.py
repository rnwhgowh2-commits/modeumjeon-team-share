"""크롤가이드 혜택 '값' → 소싱처 기본셋팅(SourceBenefitTemplate) 연결 검증 (2026-06-13).

sync_templates_from_crawl_guide:
  - 값 입력된 혜택만 반영 / 빈값·옵션(개월) 제외
  - rate(정률·적립%) 는 %→소수 변환(15→0.15), amount(정액·고정액) 그대로
  - apply → apply_mode 1:1, status planned → enabled=False
  - 이름 기준 upsert: 기존 행 update(태그 보존) / 없는 행 insert / 크롤가이드에 없는 템플릿 삭제 안 함
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

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

from lemouton.sourcing.models import (
    SourceBenefitTemplate, OptionBenefitOverride, Model, Option,
)
from webapp.routes.api_benefits import (
    sync_templates_from_crawl_guide, snapshot_bundle_from_templates,
)


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _guide(benefits):
    return {"pricing": {"benefits": benefits}}


def _tpls(s, source_id=7):
    return {t.benefit_name: t for t in
            s.query(SourceBenefitTemplate).filter_by(source_id=source_id).all()}


def test_value_set_only_and_unit_conversion(db):
    g = _guide([
        {"name": "할인 혜택", "apply": "preapplied", "status": "always",
         "method": "정률(%)", "value": 15},               # rate 15 → 0.15
        {"name": "신규 쿠폰", "apply": "deduct", "status": "conditional",
         "method": "정액(원)", "value": 5000},             # amount 5000 → 5000
        {"name": "OK캐시백", "apply": "cashback", "status": "always",
         "method": "적립(%→원)", "value": 10},             # 적립% → rate 0.10
        {"name": "고정 적립", "apply": "accrue", "status": "always",
         "method": "고정액", "value": 633},                # 고정액 → amount 633
        {"name": "등급 할인", "apply": "preapplied", "status": "always",
         "method": "정률(%)"},                              # 값 없음 → 스킵
        {"name": "무이자 할부", "apply": "payment", "status": "always",
         "method": "옵션(개월)", "value": 10},              # 개월 → 스킵
        {"name": "예정 혜택", "apply": "deduct", "status": "planned",
         "method": "정액(원)", "value": 1000},              # planned → enabled False
    ])
    n = sync_templates_from_crawl_guide(db, 7, g)
    db.commit()
    assert n == 5  # 값있고 개월 아닌 것 5개 (등급할인·무이자할부 제외)
    t = _tpls(db)
    assert set(t) == {"할인 혜택", "신규 쿠폰", "OK캐시백", "고정 적립", "예정 혜택"}
    assert (t["할인 혜택"].benefit_type, t["할인 혜택"].value) == ("rate", 0.15)
    assert (t["신규 쿠폰"].benefit_type, t["신규 쿠폰"].value) == ("amount", 5000)
    assert (t["OK캐시백"].benefit_type, t["OK캐시백"].value) == ("rate", 0.10)
    assert (t["고정 적립"].benefit_type, t["고정 적립"].value) == ("amount", 633)
    assert t["할인 혜택"].apply_mode == "preapplied"
    assert t["OK캐시백"].apply_mode == "cashback"
    assert t["예정 혜택"].enabled is False
    assert t["신규 쿠폰"].enabled is True


def test_upsert_preserves_existing_and_no_delete(db):
    # 운영센터에서 만든 기존 템플릿 2개 (태그 세팅됨)
    db.add(SourceBenefitTemplate(
        source_id=7, benefit_name="할인 혜택", benefit_type="rate", value=0.05,
        category="정률", apply_mode="preapplied", pay_method=None, channel="normal",
        enabled=True, sort_order=0))
    db.add(SourceBenefitTemplate(
        source_id=7, benefit_name="운영센터 전용", benefit_type="amount", value=2000,
        category="정액", apply_mode="deduct", pay_method="affiliate_card",
        enabled=True, sort_order=1))
    db.commit()

    g = _guide([
        {"name": "할인 혜택", "apply": "preapplied", "status": "always",
         "method": "정률(%)", "value": 20},   # 기존 행 update: 0.05 → 0.20
    ])
    sync_templates_from_crawl_guide(db, 7, g)
    db.commit()
    t = _tpls(db)
    # 크롤가이드에 없는 '운영센터 전용' 은 삭제되지 않음
    assert "운영센터 전용" in t
    assert t["운영센터 전용"].value == 2000
    # 기존 '할인 혜택' update 됨 + 태그(pay_method/channel) 보존
    assert t["할인 혜택"].value == 0.20
    assert t["할인 혜택"].channel == "normal"


def test_end_to_end_value_reaches_bundle_override(db):
    """크롤가이드 값(15%) → 템플릿(0.15) → 모음전 옵션 override(0.15) 전 구간."""
    db.add(Model(model_code="TST", model_name_raw="테스트"))
    db.add(Option(canonical_sku="TST-블랙-260", model_code="TST",
                  color_code="블랙", size_code="260"))
    db.commit()

    g = _guide([
        {"name": "할인 혜택", "apply": "preapplied", "status": "always",
         "method": "정률(%)", "value": 15},
        {"name": "신규 쿠폰", "apply": "deduct", "status": "always",
         "method": "정액(원)", "value": 5000},
    ])
    sync_templates_from_crawl_guide(db, 7, g)        # → 템플릿 2개
    snapshot_bundle_from_templates(db, "TST", source_ids=[7])  # → 모음전 옵션에 복제
    db.commit()

    ov = {o.benefit_name: o for o in
          db.query(OptionBenefitOverride)
          .filter_by(canonical_sku="TST-블랙-260", source_id=7).all()}
    assert (ov["할인 혜택"].benefit_type, ov["할인 혜택"].value) == ("rate", 0.15)
    assert (ov["신규 쿠폰"].benefit_type, ov["신규 쿠폰"].value) == ("amount", 5000)
    assert ov["할인 혜택"].apply_mode == "preapplied"

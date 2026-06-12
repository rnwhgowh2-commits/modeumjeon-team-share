# -*- coding: utf-8 -*-
"""[TEST] _dedup_merge — (model,color,size) 중복 옵션 안전 병합 (2026-06-13).

핵심: 잉여행에 매핑이 '있어도' 데이터 손실 없이 보존행으로 이전 후 삭제.
  - 보존행이 없는 매핑 → 보존행으로 이전(move)
  - 보존행이 이미 가진 매핑 → 중복제거(delete)
  - 시장ID(naver 등) 잉여행에만 있으면 보존행으로 복사(등록 손실 방지)
  - dry_run=True 면 아무것도 안 바꿈
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENVIRONMENT", "test")

_M = "ZZ_MERGE_TEST"


@pytest.fixture
def session():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.multitenancy.models",
        "lemouton.audit.models", "lemouton.mapping.models",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _opt(M, sku, active=True, naver=None):
    return M.Option(canonical_sku=sku, model_code=_M, color_code="스카이블루",
                    size_code="220", is_active=active, naver_option_id=naver)


def test_merge_moves_mappings_and_deletes_redundant(session):
    import lemouton.sourcing.models as M
    s = session
    from webapp.routes.bundles import _dedup_merge
    # keeper(활성), 잉여(비활성)지만 잉여에 URL 매핑 + 시장ID 있음
    s.add(_opt(M, "keep", active=True, naver=None))
    s.add(_opt(M, "dupe", active=False, naver="NV-999"))
    # 잉여행에만 있는 URL 매핑(이전돼야 함) + 보존행이 이미 가진 매핑(중복제거돼야 함)
    s.add(M.OptionSourceUrlLink(option_canonical_sku="dupe", bundle_source_url_id=1))
    s.add(M.OptionSourceUrlLink(option_canonical_sku="dupe", bundle_source_url_id=2))
    s.add(M.OptionSourceUrlLink(option_canonical_sku="keep", bundle_source_url_id=2))
    s.commit()

    # 1) dry-run — 변경 없음
    rep = _dedup_merge(s, dry_run=True)
    assert rep["deleted"] == 1 and rep["url_moved"] == 1 and rep["url_deduped"] == 1
    assert s.query(M.Option).filter_by(model_code=_M).count() == 2  # 안 지워짐

    # 2) 실제 병합
    rep = _dedup_merge(s, dry_run=False)
    assert rep["deleted"] == 1 and rep["ids_copied"] == 1
    # 잉여행 삭제됨, 보존행만 남음
    remaining = s.query(M.Option).filter_by(model_code=_M).all()
    assert len(remaining) == 1 and remaining[0].canonical_sku == "keep"
    # 시장ID 보존행으로 복사됨(등록 손실 없음)
    assert remaining[0].naver_option_id == "NV-999"
    # URL 매핑: bundle 1은 keep 으로 이전, bundle 2는 중복제거(keep 1개만)
    keep_urls = {l.bundle_source_url_id for l in
                 s.query(M.OptionSourceUrlLink).filter_by(option_canonical_sku="keep").all()}
    assert keep_urls == {1, 2}
    # dupe 의 매핑은 모두 사라짐
    assert s.query(M.OptionSourceUrlLink).filter_by(option_canonical_sku="dupe").count() == 0


def test_no_dupes_noop(session):
    import lemouton.sourcing.models as M
    s = session
    from webapp.routes.bundles import _dedup_merge
    s.add(_opt(M, "solo", active=True))
    s.commit()
    rep = _dedup_merge(s, dry_run=False)
    assert rep["groups"] == 0 and rep["deleted"] == 0
    assert s.query(M.Option).filter_by(model_code=_M).count() == 1

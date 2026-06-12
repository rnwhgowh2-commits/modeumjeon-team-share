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


def test_merge_reassigns_blocking_fk_option_source_links(session):
    """라이브 실패 재현: 잉여행이 option_source_links(비-CASCADE FK)에 참조되면
       삭제가 FK로 막혔었음 → 보존행으로 이전 후 삭제(손실 없음)."""
    import lemouton.sourcing.models as M
    import lemouton.sources.models as SM
    s = session
    from webapp.routes.bundles import _dedup_merge
    s.add(_opt(M, "keep", active=True))
    s.add(_opt(M, "dupe", active=False))
    sp = SM.SourceProduct(site="ssf", url="https://x/y")
    s.add(sp)
    s.flush()
    so = SM.SourceOption(source_product_id=sp.id, color_text="스카이블루", size_text="220")
    s.add(so)
    s.flush()
    # 잉여행에 크롤매핑(option_source_links) — 이게 라이브에서 삭제를 막았다
    s.add(SM.OptionSourceLink(canonical_sku="dupe", source_option_id=so.id))
    s.commit()

    rep = _dedup_merge(s, dry_run=False)
    assert rep["deleted"] == 1
    assert s.query(M.Option).filter_by(model_code=_M).count() == 1
    # 크롤매핑이 keeper 로 이전됨(손실·FK위반 없음)
    link = s.query(SM.OptionSourceLink).filter_by(source_option_id=so.id).first()
    assert link is not None and link.canonical_sku == "keep"


def test_no_dupes_noop(session):
    import lemouton.sourcing.models as M
    s = session
    from webapp.routes.bundles import _dedup_merge
    s.add(_opt(M, "solo", active=True))
    s.commit()
    rep = _dedup_merge(s, dry_run=False)
    assert rep["groups"] == 0 and rep["deleted"] == 0
    assert s.query(M.Option).filter_by(model_code=_M).count() == 1


def test_endpoint_merge_creates_unique_index_blocking_future_dupes(monkeypatch):
    """병합 실행 후 UNIQUE 인덱스 생성 → 이후 같은 (model,color,size) 삽입 차단."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.exc import IntegrityError
    for _m in ("lemouton.sourcing.models", "lemouton.sources.models",
               "lemouton.templates.models", "lemouton.inventory.models"):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base
    import lemouton.sourcing.models as M
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng)
    s = TS()
    s.add(_opt(M, "keep", active=True))
    s.add(_opt(M, "dupe", active=False))
    s.commit()
    s.close()

    import webapp.routes.bundles as B
    monkeypatch.setattr(B, "SessionLocal", TS)
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(B.bp)
    d = app.test_client().post("/api/admin/options/merge-dupes",
                               json={"dry_run": False}).get_json()
    assert d["ok"] and d["deleted"] == 1
    assert d["unique_index"].startswith("ok")

    # 이제 같은 (model,color,size) 삽입 시도 → UNIQUE 인덱스가 차단
    s2 = TS()
    s2.add(_opt(M, "new-dupe", active=True))
    with pytest.raises(IntegrityError):
        s2.commit()
    s2.rollback()
    s2.close()

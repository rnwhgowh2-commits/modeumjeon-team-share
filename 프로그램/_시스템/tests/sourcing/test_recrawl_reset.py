"""[TEST] 재크롤 리셋 — save_crawl_result 가 이번 크롤에 없는 옛 옵션을 soft-delete.

배경(integrity_recrawl_reset): upsert 만 하던 시절엔 한 번 긁힌 (색·사이즈) 조합이
다음 크롤에서 사라져도 옛 가격·재고가 남아 그 값으로 판매되는 오발주(손실)가 가능.
정책: 성공 크롤(옵션 ≥1)에서만, 이번 결과에 없는 조합은 soft-delete. 빈 결과(크롤
실패 추정)면 옛 데이터 보존(잘못 prune 방지).
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

from lemouton.sources.models import SourceProduct, SourceOption
from lemouton.sources.service import upsert_source_product, save_crawl_result
from lemouton.sourcing.crawlers.base import CrawlResult


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _cr(opts):
    return CrawlResult(source="lemouton", product_url="https://lemouton.co.kr/x",
                       product_name_raw="메이트", options=opts)


def _opt(color, size, price, stock):
    return {"color_text": color, "size_text": size, "sale_price": price,
            "price": price, "stock": stock, "option_id": f"130|{color}|{size}"}


def _active(db, sp):
    return (db.query(SourceOption)
            .filter_by(source_product_id=sp.id, deleted_at=None).all())


def test_recrawl_prunes_disappeared_combo(db):
    sp = upsert_source_product(db, site="lemouton",
                               url="https://lemouton.co.kr/product/detail.html?product_no=130")
    db.commit()
    # 1차 크롤: 크림핑크 240·245 두 조합
    r1 = save_crawl_result(db, source_product=sp, crawl_result=_cr([
        _opt("크림핑크", "240mm", 116900, 3),
        _opt("크림핑크", "245mm", 116900, 8),
    ]))
    db.commit()
    assert r1["options_inserted"] == 2
    assert r1["options_pruned"] == 0
    assert len(_active(db, sp)) == 2

    # 2차 크롤: 245mm 가 사라짐(미판매·삭제) → 240mm 만 옴
    r2 = save_crawl_result(db, source_product=sp, crawl_result=_cr([
        _opt("크림핑크", "240mm", 116900, 2),
    ]))
    db.commit()
    assert r2["options_pruned"] == 1          # 245mm soft-delete
    active = _active(db, sp)
    assert len(active) == 1
    assert active[0].size_text == "240mm"
    assert active[0].current_stock == 2       # 갱신값 반영
    # 245mm 는 soft-delete 됨(완전 삭제 아님, deleted_at set)
    gone = (db.query(SourceOption)
            .filter_by(source_product_id=sp.id, size_text="245mm").first())
    assert gone is not None and gone.deleted_at is not None


def test_empty_crawl_does_not_prune(db):
    sp = upsert_source_product(db, site="lemouton",
                               url="https://lemouton.co.kr/product/detail.html?product_no=131")
    db.commit()
    save_crawl_result(db, source_product=sp, crawl_result=_cr([_opt("블랙", "250mm", 100, 5)]))
    db.commit()
    assert len(_active(db, sp)) == 1
    # 빈 결과(크롤 실패 추정) → prune 금지, 옛 데이터 보존
    r = save_crawl_result(db, source_product=sp, crawl_result=_cr([]))
    db.commit()
    assert r["options_pruned"] == 0
    assert len(_active(db, sp)) == 1


def test_recrawl_all_present_no_prune(db):
    sp = upsert_source_product(db, site="lemouton",
                               url="https://lemouton.co.kr/product/detail.html?product_no=132")
    db.commit()
    save_crawl_result(db, source_product=sp, crawl_result=_cr([
        _opt("그레이", "260mm", 100, 1), _opt("그레이", "265mm", 100, 0),
    ]))
    db.commit()
    # 같은 두 조합 재크롤(품절 포함) → prune 0, 모두 유지(품절도 0으로 보존)
    r = save_crawl_result(db, source_product=sp, crawl_result=_cr([
        _opt("그레이", "260mm", 100, 2), _opt("그레이", "265mm", 100, 0),
    ]))
    db.commit()
    assert r["options_pruned"] == 0
    assert len(_active(db, sp)) == 2

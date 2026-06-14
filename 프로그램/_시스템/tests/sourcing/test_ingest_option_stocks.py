"""[TEST] 확장 options[] 의 사이즈별 재고 → SourceOption.current_stock 반영.

배경(2026-06-14 라이브 진단): 무신사 회원가 크롤은 확장이 사이즈별 재고를 정확히
계산(240=2·245=4·235=품절)해도, ext_bridge/서버가 상품 레벨 stock(999)만 저장해
전 사이즈가 '재고있음'으로 둔갑(오발주 손실)했다. _ingest_option_stocks 가 options[]
의 per-option stock 을 (색·사이즈 매칭) SourceOption.current_stock 에 교정한다.
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
from lemouton.sources.service import upsert_source_product, upsert_source_option
from webapp.routes.api_pricing import _ingest_option_stocks, _prune_stale_option_sizes


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _opt(s, spid, color, size, stock):
    return upsert_source_option(s, source_product_id=spid, color_text=color,
                                size_text=size, current_stock=stock)


def _stocks(s, sp):
    return {so.size_text: so.current_stock
            for so in s.query(SourceOption).filter_by(source_product_id=sp.id).all()}


def test_per_size_stock_applied(db):
    sp = upsert_source_product(db, site="musinsa",
                               url="https://www.musinsa.com/products/4046672")
    db.commit()
    # 기존: 전 사이즈 999(충분 둔갑)
    _opt(db, sp.id, "크림핑크", "240mm", 999)
    _opt(db, sp.id, "크림핑크", "245mm", 999)
    _opt(db, sp.id, "크림핑크", "235mm", 999)
    db.commit()
    # 확장 options: 색 '크림 핑크'(공백) — 정규화 매칭, size 는 mm 없는 문자열
    n = _ingest_option_stocks(db, sp.id, [
        {"color": "크림 핑크", "size": "240", "stock": 2},
        {"color": "크림 핑크", "size": "245", "stock": 4},
        {"color": "크림 핑크", "size": "235", "stock": 0},   # 품절
    ])
    db.commit()
    assert n == 3
    got = _stocks(db, sp)
    assert got["240mm"] == 2
    assert got["245mm"] == 4
    assert got["235mm"] == 0     # 품절 반영


def test_color_disambiguation(db):
    """같은 사이즈 다른 색 — 색+사이즈 정밀 매칭으로 해당 색만 갱신."""
    sp = upsert_source_product(db, site="musinsa",
                               url="https://www.musinsa.com/products/4046672b")
    db.commit()
    _opt(db, sp.id, "크림핑크", "240mm", 999)
    _opt(db, sp.id, "블랙", "240mm", 999)
    db.commit()
    n = _ingest_option_stocks(db, sp.id, [{"color": "크림 핑크", "size": "240", "stock": 2}])
    db.commit()
    rows = {so.color_text: so.current_stock
            for so in db.query(SourceOption).filter_by(source_product_id=sp.id).all()}
    assert n == 1
    assert rows["크림핑크"] == 2
    assert rows["블랙"] == 999    # 블랙은 안 건드림


def test_single_color_size_only_match(db):
    """단일색 상품 — 색이 비어도 사이즈 단일 매칭."""
    sp = upsert_source_product(db, site="musinsa",
                               url="https://www.musinsa.com/products/4800825")
    db.commit()
    _opt(db, sp.id, "크림핑크", "240", 999)
    db.commit()
    n = _ingest_option_stocks(db, sp.id, [{"color": "", "size": "240", "stock": 2}])
    db.commit()
    assert n == 1
    assert db.query(SourceOption).filter_by(source_product_id=sp.id).first().current_stock == 2


def test_parse_html_key_format(db):
    """서버 parse_html 포맷(color_text/size_text) 도 수용 (전체크롤 비무신사 경로)."""
    sp = upsert_source_product(db, site="ssf",
                               url="https://www.ssfshop.com/LEMOUTON/GRG1/good")
    db.commit()
    _opt(db, sp.id, "크림핑크", "240mm", 999)
    _opt(db, sp.id, "크림핑크", "235mm", 999)
    db.commit()
    n = _ingest_option_stocks(db, sp.id, [
        {"color_text": "크림핑크", "size_text": "240mm", "stock": 7},
        {"color_text": "크림핑크", "size_text": "235mm", "stock": 0},
    ])
    db.commit()
    assert n == 2
    got = _stocks(db, sp)
    assert got["240mm"] == 7
    assert got["235mm"] == 0


def test_single_color_updates_all_by_size(db):
    """단일색 상품(color='')인데 옛 다색 행이 섞여도 사이즈로 전부 갱신 (#65 4800825 잔여)."""
    sp = upsert_source_product(db, site="musinsa",
                               url="https://www.musinsa.com/products/4800825")
    db.commit()
    # 옛 크롤이 잘못 다색으로 저장 (크림핑크 240 + 블랙 240) — 둘 다 999
    _opt(db, sp.id, "크림핑크", "240", 999)
    _opt(db, sp.id, "블랙", "240", 999)
    db.commit()
    # 단일색 크롤: color='' (단일 드롭다운)
    n = _ingest_option_stocks(db, sp.id, [{"color": "", "size": "240", "stock": 2}])
    db.commit()
    rows = {so.color_text: so.current_stock
            for so in db.query(SourceOption).filter_by(source_product_id=sp.id).all()}
    assert n == 2                        # 그 사이즈 전부 갱신
    assert rows["크림핑크"] == 2 and rows["블랙"] == 2


def test_prune_removes_stale_sizes(db):
    """이번 크롤에 없는 사이즈는 soft-delete (SSF 235=6993 잔존 제거)."""
    sp = upsert_source_product(db, site="ssf",
                               url="https://www.ssfshop.com/LEMOUTON/GRG9/good")
    db.commit()
    _opt(db, sp.id, "크림핑크", "235", 6993)   # 옛 미판매 사이즈 잔존
    _opt(db, sp.id, "크림핑크", "240", 999)
    db.commit()
    pruned = _prune_stale_option_sizes(db, sp.id, [{"color": "", "size": "240", "stock": 5}])
    db.commit()
    assert pruned == 1
    active = {so.size_text for so in db.query(SourceOption)
              .filter_by(source_product_id=sp.id, deleted_at=None).all()}
    assert "235" not in active            # 235 prune됨
    assert "240" in active


def test_creates_when_no_existing_options(db):
    """[2026-06-14] per-size SourceOption 이 없던 소싱처(롯데온)는 upsert 로 생성.

    롯데온은 늘 상품레벨 stock(999) 하나만 저장 → SourceOption 이 없어 update-only
    _ingest 가 아무 행도 못 고치고 매트릭스가 999 폴백(한정수량 둔갑)했다. 이제 들어온
    사이즈별 재고로 행을 생성해 옵션단위로 읽히게 한다.
    """
    sp = upsert_source_product(db, site="lotteon",
                               url="https://www.lotteon.com/p/product/LO2158462485")
    db.commit()
    # 기존 SourceOption 전혀 없음(롯데온 상품레벨만)
    assert db.query(SourceOption).filter_by(source_product_id=sp.id).count() == 0
    n = _ingest_option_stocks(db, sp.id, [
        {"color": "블랙", "size": "220", "stock": 10},
        {"color": "블랙", "size": "255", "stock": 9},    # 한정수량
        {"color": "블랙", "size": "240", "stock": 999},  # 충분
    ])
    db.commit()
    assert n == 3
    got = {so.size_text: so.current_stock
           for so in db.query(SourceOption).filter_by(source_product_id=sp.id).all()}
    assert got["220"] == 10
    assert got["255"] == 9      # 둔갑 안 됨(999 아님)
    assert got["240"] == 999
    # 색은 블랙으로 생성(다른 색 행에 새지 않음)
    colors = {so.color_text for so in db.query(SourceOption).filter_by(source_product_id=sp.id).all()}
    assert colors == {"블랙"}


def test_empty_or_bad_options_noop(db):
    sp = upsert_source_product(db, site="musinsa", url="https://www.musinsa.com/products/9")
    db.commit()
    _opt(db, sp.id, "크림핑크", "240mm", 999)
    db.commit()
    assert _ingest_option_stocks(db, sp.id, None) == 0
    assert _ingest_option_stocks(db, sp.id, []) == 0
    # stock None 인 옵션은 건너뜀(덮어쓰기 금지)
    assert _ingest_option_stocks(db, sp.id, [{"color": "크림핑크", "size": "240", "stock": None}]) == 0
    assert db.query(SourceOption).filter_by(source_product_id=sp.id).first().current_stock == 999

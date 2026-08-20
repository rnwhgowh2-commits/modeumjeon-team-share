# -*- coding: utf-8 -*-
"""[TEST] 크롤이 상품명을 '갱신'한다 — 옛 파서가 저장한 나비게이션 쓰레기(「메인메뉴」) 치유.

배경(라이브 실측 2026-07-11):
  르무통 공홈 첫 상품의 이름이 「메인메뉴」로 떴다. 진짜 상품 페이지인데
  옛 파서(og:title 우선 도입 전, 2026-06-21 이전)가 PC 페이지 첫 h2 '메인메뉴'(내비)를
  상품명으로 저장한 뒤, save_crawl_result 가 `and not source_product.product_name`
  가드 때문에 '비어 있을 때만' 채워서 영원히 안 바뀌었다. 파서는 고쳤는데 DB 가 stale.

  수정: 새로 파싱한 이름이 있고, 현재 이름이 비었거나 '내비 쓰레기'면 갱신한다.
  (정상 저장된 좋은 이름은 덮지 않는다 — fill-if-blank + heal-junk.)
"""
from dataclasses import dataclass, field

from lemouton.sources.models import SourceProduct
from lemouton.sources.service import save_crawl_result


@dataclass
class _CR:
    source: str = "lemouton"
    product_url: str = "https://www.lemouton.co.kr/product/detail.html?product_no=1"
    product_name_raw: str = ""
    options: list = field(default_factory=list)
    brand: str = ""
    discount_info: str = ""
    fetched_at: str = None


def _sp(db, name):
    sp = SourceProduct(site="lemouton",
                       url="https://www.lemouton.co.kr/product/detail.html?product_no=1",
                       product_name=name)
    db.add(sp); db.flush()
    return sp


def test_junk_name_is_replaced_by_fresh_parse(db):
    """★「메인메뉴」가 저장돼 있으면, 크롤이 준 진짜 이름으로 갱신된다."""
    sp = _sp(db, "메인메뉴")
    save_crawl_result(db, source_product=sp,
                      crawl_result=_CR(product_name_raw="르무통 메이트 발 편한 메리노울 운동화"))
    assert sp.product_name == "르무통 메이트 발 편한 메리노울 운동화"


def test_blank_name_is_filled(db):
    """비어 있으면 채운다 (기존 동작 유지)."""
    sp = _sp(db, "")
    save_crawl_result(db, source_product=sp, crawl_result=_CR(product_name_raw="르무통 메이트"))
    assert sp.product_name == "르무통 메이트"


def test_good_name_is_not_overwritten(db):
    """정상 이름은 덮지 않는다 (파서 폴백이 더 나쁜 값을 줘도 보호)."""
    sp = _sp(db, "르무통 메이트 발 편한 메리노울 운동화")
    save_crawl_result(db, source_product=sp, crawl_result=_CR(product_name_raw="메인메뉴"))
    assert sp.product_name == "르무통 메이트 발 편한 메리노울 운동화"


def test_junk_not_replaced_by_junk(db):
    """새 이름도 쓰레기면 그대로 둔다 (쓰레기→쓰레기 방지)."""
    sp = _sp(db, "메인메뉴")
    save_crawl_result(db, source_product=sp, crawl_result=_CR(product_name_raw="메인메뉴"))
    assert sp.product_name == "메인메뉴"

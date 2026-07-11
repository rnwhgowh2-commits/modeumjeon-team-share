# -*- coding: utf-8 -*-
"""[TEST] 상품명 치유 순수 함수 — 확장 크롤 경로(parse)에서도 재사용.

「메인메뉴」가 안 고쳐지던 진짜 이유(라이브 2026-07-11): 확장이 쓰는 저장 경로는
service.save_crawl_result 가 아니라 api_sources_parse(/api/sources/parse)다. 파서는
정확한 og:title 이름을 이미 손에 쥐고 있으므로, 그 경로에서도 같은 치유 로직을 쓴다.
로직을 한 곳(service.apply_name_heal)에 두고 양쪽이 부른다.
"""
from lemouton.sources.models import SourceProduct
from lemouton.sources.service import apply_name_heal


def _sp(db, name):
    sp = SourceProduct(site="lemouton", url="https://www.lemouton.co.kr/product/detail.html?product_no=219",
                       product_name=name)
    db.add(sp); db.flush()
    return sp


def test_heals_junk(db):
    sp = _sp(db, "메인메뉴")
    assert apply_name_heal(sp, "르무통 클래식2 발 편한 메리노울 운동화") is True
    assert sp.product_name == "르무통 클래식2 발 편한 메리노울 운동화"


def test_fills_blank(db):
    sp = _sp(db, "")
    assert apply_name_heal(sp, "르무통 메이트") is True
    assert sp.product_name == "르무통 메이트"


def test_protects_good_name(db):
    sp = _sp(db, "르무통 클래식2 발 편한 메리노울 운동화")
    assert apply_name_heal(sp, "메인메뉴") is False
    assert sp.product_name == "르무통 클래식2 발 편한 메리노울 운동화"


def test_ignores_junk_new_name(db):
    sp = _sp(db, "메인메뉴")
    assert apply_name_heal(sp, "메인메뉴") is False
    assert sp.product_name == "메인메뉴"


def test_ignores_empty_new_name(db):
    sp = _sp(db, "메인메뉴")
    assert apply_name_heal(sp, "") is False
    assert apply_name_heal(sp, None) is False

"""크롤 실패에 소싱처·브랜드·옵션(색/사이즈)·url_type 표기 (항목 5).

B 아코디언(소싱처>브랜드>옵션/url)이 읽을 4계층 데이터를 list_crawl_failures 가 준다.
"""
from lemouton.sources.failure_classify import list_crawl_failures
from lemouton.sources.models import SourceProduct, SourceOption
import lemouton.sourcing.models as M


def _fail(db, *, site, url, err, model_code, brand, url_type, opts):
    sp = SourceProduct(site=site, url=url, last_status="error", last_error_msg=err)
    db.add(sp); db.flush()
    if db.query(M.Model).filter_by(model_code=model_code).first() is None:
        db.add(M.Model(model_code=model_code, model_name_raw=model_code, brand=brand))
    db.add(M.BundleSourceUrl(model_code=model_code, source_key=site, url=url,
                             sort_order=0, url_type=url_type))
    for (c, s) in opts:
        db.add(SourceOption(source_product_id=sp.id, color_text=c, size_text=s))
    db.flush()
    return sp


def _find(groups, spid):
    for g in groups:
        for it in g["items"]:
            if it["source_product_id"] == spid:
                return it
    return None


def test_failure_item_has_brand_site_label_option_scope(db):
    sp = _fail(db, site="musinsa", url="https://m.com/p/1", err="옵션 없음",
               model_code="MM", brand="르무통", url_type="단품",
               opts=[("블랙", "265"), ("블랙", "270")])
    it = _find(list_crawl_failures(db), sp.id)
    assert it is not None
    assert it["brand"] == "르무통"
    assert it["site"] == "musinsa"
    assert it["url_type"] == "단품"
    assert it["option_scope"] == "블랙 · 265~270"   # 단일 색 · 사이즈 범위


def test_option_scope_multi_color(db):
    sp = _fail(db, site="ssf", url="https://s.com/p/2", err="타임아웃",
               model_code="SS", brand="르무통", url_type="색상모음전",
               opts=[("블랙", "260"), ("아이보리", "260")])
    it = _find(list_crawl_failures(db), sp.id)
    assert it["option_scope"] == "블랙 외 1색"


def test_failure_without_options_falls_back_to_urltype(db):
    sp = _fail(db, site="hmall", url="https://h.com/g/3", err="옵션 가격 없음",
               model_code="HH", brand="르무통", url_type="색상모음전", opts=[])
    it = _find(list_crawl_failures(db), sp.id)
    assert it["option_scope"] == "색상모음전"       # 옵션 없으면 url_type 폴백
    assert it["brand"] == "르무통"

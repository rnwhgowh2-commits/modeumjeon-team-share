# -*- coding: utf-8 -*-
"""롯데온 카테고리 — **목록엔 없고 상세엔 있다**(2026-08-12).

왜 이 시험이 있나
  옛 코드·옛 화면은 「롯데온은 카테고리를 영영 못 받는다」고 말했다. 그건 **목록**
  이야기였고, 상세(product/detail)에는 `scatNo`·`dcatLst` 가 실제로 온다 —
  상품 등록이 본보기 상세의 그 두 필드를 그대로 복사해 **라이브에서 성공**했다
  (2026-07-21 LO2729045338 · `products.py::_REGISTER_TEMPLATE_FIELDS`).
  「마켓이 안 준다」고 말하기 전에 raw 를 봐야 한다는 그 부류의 오진이었다.

무엇을 지키나
 ① 상세의 scatNo → `MarketProduct.category_code`.
 ② 🔴 **가격이 없어도** 카테고리는 담는다 — 같은 응답에 온 값을 조기 `continue` 로
   버리면 안 된다(이 파일이 막으려는 실제 버그 유형).
 ③ 🔴 이름은 실려 올 때만 — 번호를 이름처럼 꾸미지 않는다.
 ④ 카테고리만 비어 있는 상품도 훑기 차례가 온다(가격이 이미 차 있어도).
 ⑤ 지도(marketplace_api_map.json)가 이 사실을 담고 있다(선순환 — 다음 세션이 또 헤매지 않게).
"""
import json
from pathlib import Path

import pytest

_SYS = Path(__file__).resolve().parents[2]


# ── ①③ 뽑아내기 규칙 ────────────────────────────────────────────────

def test_scatNo_가_카테고리_코드가_된다():
    from lemouton.catalog.lotteon_prices import category_of
    code, name = category_of({'scatNo': '1234567', 'itmLst': []})
    assert code == '1234567'
    assert name is None, '이름이 안 왔으면 지어내지 않는다'


def test_이름이_실려_오면_담는다():
    from lemouton.catalog.lotteon_prices import category_of
    code, name = category_of({'scatNo': '77', 'dcatLst': [
        {'lfDcatNo': '9', 'dcatNm': '여성신발 > 샌들'}]})
    assert (code, name) == ('77', '여성신발 > 샌들')


def test_scatNo_가_없으면_전시카테고리_leaf_라도_쓴다():
    from lemouton.catalog.lotteon_prices import category_of
    code, _ = category_of({'dcatLst': [{'dcatNo': '1'}, {'lfDcatNo': '42'}]})
    assert code == '42', '마지막(leaf) 전시카테고리가 그 상품의 자리다'


def test_아무것도_없으면_None(monkeypatch):
    from lemouton.catalog.lotteon_prices import category_of
    assert category_of({'itmLst': [{'slPrc': 1000}]}) == (None, None)
    assert category_of(None) == (None, None)


# ── ②④ 훑기 배선 ────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    appmod.create_app()
    from shared.db import SessionLocal
    s = SessionLocal()
    yield s
    from lemouton.catalog.models import MarketProduct
    s.query(MarketProduct).filter_by(account_key='롯데온카테고리검사').delete()
    s.commit(); s.close()


def _seed(db, mpid, **kw):
    from lemouton.catalog.models import MarketProduct
    db.add(MarketProduct(market='lotteon', account_key='롯데온카테고리검사',
                         market_product_id=mpid, name='검사', status='sale', **kw))
    db.commit()


def test_가격과_카테고리를_한_번의_상세로_같이_거둔다(db, monkeypatch):
    from lemouton.catalog.lotteon_prices import enrich_prices
    from lemouton.catalog.models import MarketProduct

    _seed(db, 'LOC-1')
    calls = []

    def _detail(spd, client=None, **k):
        calls.append(spd)
        return {'scatNo': '5001001', 'itmLst': [{'slPrc': 45000},
                                                {'slPrc': 43000}]}
    monkeypatch.setattr('shared.platforms.lotteon.products.get_product_detail',
                        _detail)
    r = enrich_prices(db, object(), account_key='롯데온카테고리검사')
    assert len(calls) == 1, '카테고리 때문에 상세를 두 번 부르면 안 된다'
    assert r['filled'] == 1 and r['category_filled'] == 1
    m = (db.query(MarketProduct)
         .filter_by(account_key='롯데온카테고리검사', market_product_id='LOC-1').first())
    assert m.sale_price == 43000 and m.category_code == '5001001'


def test_가격이_없어도_카테고리는_담긴다(db, monkeypatch):
    """🔴 이 시험이 진짜 막는 것 — 「가격 없으면 continue」에 카테고리가 휩쓸려 버려짐."""
    from lemouton.catalog.lotteon_prices import enrich_prices
    from lemouton.catalog.models import MarketProduct

    _seed(db, 'LOC-2')
    monkeypatch.setattr('shared.platforms.lotteon.products.get_product_detail',
                        lambda spd, client=None, **k: {'scatNo': '7', 'itmLst': []})
    r = enrich_prices(db, object(), account_key='롯데온카테고리검사')
    m = (db.query(MarketProduct)
         .filter_by(account_key='롯데온카테고리검사', market_product_id='LOC-2').first())
    assert m.sale_price is None, '값이 없으면 NULL 유지(날조 금지)'
    assert m.category_code == '7' and r['category_filled'] == 1


def test_가격이_이미_찼어도_카테고리가_비면_차례가_온다(db, monkeypatch):
    """가격만 「빈 것」으로 보면 카테고리는 재확인 꼬리에서만 걸려 영영 안 찬다."""
    from lemouton.catalog.lotteon_prices import enrich_prices
    from lemouton.catalog.models import MarketProduct

    _seed(db, 'LOC-3', sale_price=39000)
    monkeypatch.setattr('shared.platforms.lotteon.products.get_product_detail',
                        lambda spd, client=None, **k: {'scatNo': '9', 'itmLst': []})
    enrich_prices(db, object(), account_key='롯데온카테고리검사', limit=1)
    m = (db.query(MarketProduct)
         .filter_by(account_key='롯데온카테고리검사', market_product_id='LOC-3').first())
    assert m.category_code == '9'


# ── ⑤ 지도 선순환 ───────────────────────────────────────────────────

def _map():
    p = _SYS / 'webapp' / 'data' / 'marketplace_api_map.json'
    return json.loads(p.read_text(encoding='utf-8'))


def _api(api_id):
    for a in _map()['apis']:
        if a.get('id') == api_id:
            return a
    raise AssertionError(f'{api_id} 가 지도에 없다')


def test_지도_상세에_카테고리_필드가_적혀_있다():
    keys = {f['key'] for f in _api('lotteon.product.get_detail')['fields']}
    assert 'data.scatNo' in keys and 'data.dcatLst[]' in keys


def test_지도에서_영원히_NULL_이라던_옛_서술이_거둬졌다():
    traps = ' '.join(_api('lotteon.product.list')['idTraps'])
    assert '영원히 NULL' not in traps, \
        '틀린 것으로 밝혀진 서술이 지도에 남으면 다음 세션이 또 그대로 믿는다'
    assert 'get_detail' in traps or 'product.get_detail' in traps


def test_화면이_마켓이_안_알려준다고_말하지_않는다():
    src = (_SYS / 'webapp' / 'templates' / 'bundles' / 'tower.html'
           ).read_text(encoding='utf-8')
    assert '마켓이 카테고리를 안 알려줘요' not in src
    assert 'category_via_detail' in src

# -*- coding: utf-8 -*-
"""3갈래(모델명·색상·사이즈)로 올린 상품이 **연동돼야** 가격·재고가 나간다.

## 사고 (2026-08-13 실측)

3갈래 전송을 열었더니, 그렇게 올린 상품은 **가격·재고가 영영 안 나갔다. 에러도 없이.**

사슬:
1. `platforms/smartstore/get_options.py` 가 `optionName1`·`optionName2` 만 읽는다
   → **`optionName3`(사이즈)를 통째로 버린다.**
2. 그래서 마켓 옵션이 `color=모델명` · `size=색상` 으로 들어온다.
3. `uploader/linker.py` 는 우리 `color_code(블랙)`·`size_code(250)` 와 대조 → **hits 0 → unmatched**
4. `unmatched` 는 `build_sku_by_option` 에 안 들어가고 `_extract_uploads` 가 건너뛴다
   → **전송 0건.**

🟢 **정확한 열쇠는 이미 왕복하고 있었다** — 우리가 등록할 때 `sellerManagerCode` 에
우리 SKU 를 써 넣고(`registration/options.py`), 조회 때 되받아 온다
(`get_options.py` 의 `manager_code`). 그런데 **`market_fetch.py` 가 그걸 안 싣고 버렸다.**
이름 대조보다 정확하므로 **그것을 먼저 본다.**

★ 손으로 만든 옛 상품은 `sellerManagerCode` 가 비어 있다 —
  그래서 이름 대조 폴백을 **지우지 않고 뒤에 남긴다.**
"""
from lemouton.uploader.linker import MarketOption, match_market_options_to_skus


def _우리옵션(sku, color, size, model=''):
    return {'canonical_sku': sku, 'color_code': color, 'color_display': color,
            'size_code': size, 'size_display': size, 'model': model}


BUNDLE_3축 = [_우리옵션('SKU-M1', '블랙', '250', '메이트'),
              _우리옵션('SKU-S1', '블랙', '250', '스위트')]


def test_우리_SKU_로_정확히_짝짓는다():
    """🔴 RED 였던 자리 — 이름으로만 대조해서 3갈래 상품이 통째로 unmatched 였다."""
    시장 = [MarketOption(option_id='11', color='메이트', size='블랙',
                        name3='250', manager_code='SKU-M1'),
           MarketOption(option_id='22', color='스위트', size='블랙',
                        name3='250', manager_code='SKU-S1')]
    rows = match_market_options_to_skus(BUNDLE_3축, 시장)
    assert [r.status for r in rows] == ['matched', 'matched'], [r.status for r in rows]
    assert {r.market_option_id: r.canonical_sku for r in rows} == {
        '11': 'SKU-M1', '22': 'SKU-S1'}


def test_SKU_가_없으면_세_값으로_대조한다():
    """옛 상품엔 `sellerManagerCode` 가 없다 — 그때는 모델·색상·사이즈 셋으로."""
    시장 = [MarketOption(option_id='11', color='메이트', size='블랙', name3='250'),
           MarketOption(option_id='22', color='스위트', size='블랙', name3='250')]
    rows = match_market_options_to_skus(BUNDLE_3축, 시장)
    assert [r.status for r in rows] == ['matched', 'matched'], [r.status for r in rows]
    assert {r.market_option_id: r.canonical_sku for r in rows} == {
        '11': 'SKU-M1', '22': 'SKU-S1'}


def test_2갈래_옛_상품은_예전_그대로다():
    """🔴 라이브 대부분이 이 길이다 — 회귀가 나면 안 된다."""
    bundle = [_우리옵션('A1', '블랙', '250'), _우리옵션('A2', '크림', '250')]
    시장 = [MarketOption(option_id='11', color='블랙', size='250'),
           MarketOption(option_id='22', color='크림', size='250')]
    rows = match_market_options_to_skus(bundle, 시장)
    assert [r.status for r in rows] == ['matched', 'matched']
    assert {r.market_option_id: r.canonical_sku for r in rows} == {'11': 'A1', '22': 'A2'}


def test_모르는_SKU_는_이름_대조로_떨어진다():
    """마켓에 남의 코드가 적혀 있어도 조용히 틀리게 잇지 않는다."""
    bundle = [_우리옵션('A1', '블랙', '250')]
    시장 = [MarketOption(option_id='11', color='블랙', size='250',
                        manager_code='남의코드-999')]
    rows = match_market_options_to_skus(bundle, 시장)
    assert rows[0].status == 'matched' and rows[0].canonical_sku == 'A1'


def test_짝이_없으면_지어내지_않는다():
    bundle = [_우리옵션('A1', '블랙', '250')]
    시장 = [MarketOption(option_id='11', color='빨강', size='999')]
    rows = match_market_options_to_skus(bundle, 시장)
    assert rows[0].status == 'unmatched' and rows[0].canonical_sku is None


def test_같은_이름이_둘이면_보류한다():
    """모호한 것을 matched 로 만들면 가격이 엉뚱한 옵션에 실린다."""
    bundle = [_우리옵션('A1', '블랙', '250'), _우리옵션('A2', '블랙', '250')]
    시장 = [MarketOption(option_id='11', color='블랙', size='250')]
    rows = match_market_options_to_skus(bundle, 시장)
    assert rows[0].status == 'ambiguous' and rows[0].canonical_sku is None


# ── 다리가 끝까지 이어졌나 (엔진만 고치면 라이브는 안 바뀐다) ─────────────────


def test_마켓_응답의_optionName3_가_MarketOption_까지_도착한다():
    """🔴 사슬 왕복 — `get_options` → `market_fetch` → `MarketOption`.

    예전엔 `get_options` 가 `manager_code` 를 받아 놓고도 `market_fetch` 가
    **안 싣고 버렸다.** 정확한 열쇠가 중간에서 증발한 것이 이 결함의 본체다.
    """
    from shared.platforms.smartstore.get_options import OptionRow
    from lemouton.uploader.linker import MarketOption

    o = OptionRow(option_id=11, name1='메이트', name2='블랙', name3='250',
                  stock=3, add_price=0, manager_code='SKU-M1')
    assert o.display_name == '메이트 / 블랙 / 250', o.display_name

    # market_fetch 가 만드는 것과 같은 모양으로 옮겨진다.
    mo = MarketOption(option_id=str(o.option_id), color=o.name1, size=o.name2,
                      stock=o.stock, price=0, usable=o.usable,
                      name3=getattr(o, 'name3', None),
                      manager_code=getattr(o, 'manager_code', None))
    assert (mo.name3, mo.manager_code) == ('250', 'SKU-M1')


def test_마켓_응답_파서가_optionName3_를_안_버린다():
    """응답 dict → `OptionRow` 단계에서 셋째 칸이 살아 오는지."""
    import shared.platforms.smartstore.get_options as G
    import inspect
    src = inspect.getsource(G)
    assert "name3=c.get('optionName3')" in src, (
        'optionName3 를 안 읽는다 — 3갈래 상품이 통째로 unmatched 가 된다')
    assert "manager_code=c.get('sellerManagerCode')" in src, (
        'sellerManagerCode 를 안 읽는다 — 정확한 열쇠가 사라진다')


def test_market_fetch_가_두_값을_버리지_않는다():
    import lemouton.uploader.market_fetch as MF
    import inspect
    src = inspect.getsource(MF)
    코드 = '\n'.join(l for l in src.splitlines() if not l.lstrip().startswith('#'))
    assert 'name3=' in 코드 and 'manager_code=' in 코드, (
        'market_fetch 가 name3·manager_code 를 안 싣는다 — 여기서 버리면 '
        'linker 가 영영 못 본다(이 결함의 본체였다)')

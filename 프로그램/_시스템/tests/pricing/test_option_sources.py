# -*- coding: utf-8 -*-
"""소싱처 픽 · 재고 해석 = 화면과 마켓 전송이 **같은 한 곳**을 본다.

이 판정이 갈리면 화면은 「품절·A소싱처」인데 전송은 「있음·B소싱처」로 나간다.
이 저장소가 반복해서 겪은 원천 분열의 형태 그대로다.
"""
from lemouton.sourcing import option_sources as OS


def cell(**kw):
    d = {'site': 'ssg', 'crawled_price': 10000, 'crawled_stock': 5,
         'last_status': 'ok'}
    d.update(kw)
    return d


# ── 원천이 하나인가 ─────────────────────────────────────────────────────

def test_라우트가_쓰는_함수와_같은_물건이다():
    from webapp.routes import api_pricing as AP
    assert AP._effective_stock_status is OS.effective_stock_status
    assert AP._pick_cheapest_buyable is OS.pick_cheapest_buyable


# ── 재고 해석 ───────────────────────────────────────────────────────────

def test_소싱처가_안_파는_조합은_품절이다():
    """match_failed + 크롤 성공 = 목록에 없음 = 미판매. 오버셀 방향이 아니다."""
    assert OS.effective_stock_status(
        cell(match_failed=True, last_status='ok')) == 'not_sold'


def test_크롤_실패면_품절로_단정하지_않는다():
    """목록이 최신이 아니라 「없다」고 말할 근거가 없다."""
    for st in ('error', None, 'pending'):
        assert OS.effective_stock_status(
            cell(match_failed=True, last_status=st)) == 'uncollected'


def test_셀_재고_미수집은_확인_불가다():
    assert OS.effective_stock_status(
        cell(stock_uncollected=True, last_status='ok')) == 'uncollected'


def test_재고_해석을_네_칸에_붙인다():
    srcs = [cell(crawled_stock=0), cell(crawled_stock=7)]
    OS.decorate_stock(srcs)
    assert srcs[0]['stock_label'] == '품절' and srcs[0]['stock_out'] is True
    assert srcs[1]['stock_qty'] == 7 and srcs[1]['stock_state'] == 'limited'


# ── 어디서 사오나 ───────────────────────────────────────────────────────

def test_품절_아닌_최저가를_고른다():
    a = cell(site='ssg', crawled_price=12000)
    b = cell(site='musinsa', crawled_price=9000)
    srcs = [a, b]
    OS.decorate_stock(srcs)
    assert OS.pick_cheapest_buyable(srcs) is b


def test_품절인_곳은_원가로_안_잡힌다():
    """싸도 못 사는 곳이면 원가가 아니다."""
    싼데품절 = cell(site='ssg', crawled_price=5000, crawled_stock=0)
    비싼데있음 = cell(site='musinsa', crawled_price=9000, crawled_stock=3)
    srcs = [싼데품절, 비싼데있음]
    OS.decorate_stock(srcs)
    assert OS.pick_cheapest_buyable(srcs) is 비싼데있음


def test_전부_품절이면_실가격이라도_후보로_쓴다():
    """품절은 「실가격은 받았다」 — 가격 자체는 유효하다."""
    a = cell(crawled_price=5000, crawled_stock=0)
    b = cell(crawled_price=9000, crawled_stock=0)
    srcs = [a, b]
    OS.decorate_stock(srcs)
    assert OS.pick_cheapest_buyable(srcs) is a


def test_크롤_실패한_곳의_옛_가격은_끝까지_배제한다():
    """🔴 stale 가격이 원가로 잡히면 잘못된 판매가가 나간다."""
    stale = cell(crawled_price=1000, last_status='error')
    assert OS.pick_cheapest_buyable([stale]) is None


def test_최저가_기준은_최종매입가다():
    """표면가가 싼 곳이 혜택 반영 후엔 더 비쌀 수 있다 — 실제로 내는 돈이 원가."""
    표면싼곳 = cell(crawled_price=10000, final_purchase_price=9500)
    표면비싼곳 = cell(crawled_price=11000, final_purchase_price=8000)
    srcs = [표면싼곳, 표면비싼곳]
    OS.decorate_stock(srcs)
    assert OS.pick_cheapest_buyable(srcs) is 표면비싼곳


# ── 마켓에 보내도 되나 ──────────────────────────────────────────────────

def test_소싱처가_없으면_막는다():
    ok, qty, why, picked = OS.sendable_for_option([])
    assert ok is False and picked is None and '소싱처가 없습니다' in why


def test_살_수_있는_곳이_없으면_막는다():
    ok, _, why, _ = OS.sendable_for_option([cell(last_status='error')])
    assert ok is False and '옛 가격으로 올리지 않습니다' in why


def test_고른_곳의_재고가_불명이면_막는다():
    """🔴 -1 = 크롤은 됐는데 신호를 못 읽음. 있다고 단정하면 오버셀이다."""
    ok, qty, why, picked = OS.sendable_for_option(
        [cell(site='musinsa', crawled_stock=-1)])
    assert ok is False and qty is None
    assert picked is not None and '확인' in why


def test_품절이면_0을_보낸다():
    """0 은 확인된 값이다 — 안 보내면 마켓에 옛 재고가 남는다."""
    ok, qty, why, _ = OS.sendable_for_option([cell(crawled_stock=0)])
    assert ok is True and qty == 0


def test_보낼_때도_화면과_같은_곳을_고른다():
    """화면이 「무신사에서 3개」라고 하면 전송도 그래야 한다."""
    a = cell(site='ssg', crawled_price=12000, crawled_stock=9)
    b = cell(site='musinsa', crawled_price=9000, crawled_stock=3)
    srcs = [a, b]
    OS.decorate_stock(srcs)
    화면이_고른_곳 = OS.pick_cheapest_buyable(srcs)
    ok, qty, _, 전송이_고른_곳 = OS.sendable_for_option([dict(a), dict(b)])
    assert ok is True and qty == 3
    assert 전송이_고른_곳['site'] == 화면이_고른_곳['site']

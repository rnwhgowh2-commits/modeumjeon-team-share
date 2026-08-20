# -*- coding: utf-8 -*-
"""D-1 매트릭스 폰 화면(/mobile/matrix) — 검색 → 옵션 카드(소싱처별 가격·재고).

사장님 확정(2026-08-04, 「모음전 폰 화면 일괄 시안 v1.html」 fD1): 검색 상자 하나 →
결과는 옵션 카드. 카드 = 상품·옵션 제목 + SKU + 소싱처별 줄(이름 · 가격(tabular
오른쪽) · 재고 배지: 재고 N 초록 / 품절 빨강 / 확인불가 노랑). **시안=코드**.

무엇을 지키나
    ① 화면이 열리고(200) 시안 구조(검색 상자·카드 부품 클래스)가 있다.
    ② 메뉴 등록 — PHONE_NATIVE_ROWS 에 실렸다(역방향 관문은 형제 시험이 지킨다).
    ③ 검색은 **배선**이다 — DB 를 실제로 읽는다. 서로 다른 두 검색어가 서로 다른
       답을 내야 한다(하드코딩 결과면 여기서 잡힌다).
    ④ 🔴 재고 의미 보존(이 프로젝트 1원칙) — 모르면 **확인불가**(있음으로 둔갑 금지),
       0=품절, 999 센티넬=「재고 있음」(개수 아님). 배지는 **서버가 판정**해 내려보내고
       폰 JS 는 그대로 그린다(같은 판정 두 곳 금지). 원천 의미는
       lemouton/sourcing/guide_url_result._stock_label 과 부류가 같아야 한다(대조 시험).
    ⑤ 가격 — 최종매입가(final) 우선, 없으면 표면가(surface, 종류를 밝힌다),
       둘 다 없으면 None → 폰은 '-'(폴백 가격 발명 금지).

★ '낱말이 어딘가 있나'로 검사하지 않는다(형제 화면에서 네 번 헛통과한 함정) —
  API 는 JSON 값 자체를, 템플릿은 그 줄·규칙 본문을 정규식으로 못 박는다.
"""
import re
from pathlib import Path

import pytest

# flask_app 픽스처는 tests/mobile/conftest.py 에 있다.

_TPL = Path(__file__).resolve().parents[2] / 'webapp' / 'templates' / 'mobile' / 'matrix.html'

_SKU_A = 'SKU-MMX-A0001'
_SKU_B = 'SKU-MMX-B0001'


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _tpl_src() -> str:
    assert _TPL.exists(), f'템플릿이 없다: {_TPL}'
    return _TPL.read_text(encoding='utf-8')


def _matrix_html(client):
    """화면 HTML — 200 이 아니면 여기서 세운다(빈 본문 헛통과 방지)."""
    r = client.get('/mobile/matrix')
    assert r.status_code == 200, \
        f'매트릭스 폰 화면이 안 열린다(status={r.status_code}) — 아래 시험은 의미가 없다'
    return r.get_data(as_text=True)


# ════════════════════════════════════════════════════════════
#  준비물 — 모델·옵션·소싱처(가격·재고 세 갈래)를 임시 SQLite 에 심는다
# ════════════════════════════════════════════════════════════

@pytest.fixture
def seeded(flask_app):
    """옵션 2개 + 소싱처 3갈래(재고 6 / 품절 0 / 미크롤 None).

    🔴 데이터를 **만드는** 픽스처다 — 진짜 DB(PostgreSQL)면 안 돈다.
    """
    from tests.mobile.conftest import require_sqlite
    require_sqlite()

    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import Model, Option
    from shared.db import SessionLocal

    s = SessionLocal()
    made = {'skus': [], 'sp': [], 'so': [], 'link': []}
    try:
        if not s.query(Model).filter_by(model_code='MMX-A').first():
            s.add(Model(model_code='MMX-A', model_name_raw='르무통 컴포트 니트',
                        model_name_display='르무통 컴포트 니트'))
            s.add(Model(model_code='MMX-B', model_name_raw='르무통 클래식 로퍼',
                        model_name_display='르무통 클래식 로퍼'))
        for sku, mc, color, size in ((_SKU_A, 'MMX-A', '블랙', 'M'),
                                     (_SKU_B, 'MMX-B', '브라운', '260')):
            if not s.get(Option, sku):
                s.add(Option(canonical_sku=sku, model_code=mc,
                             color_code=color, size_code=size, is_active=True))
                made['skus'].append(sku)
        s.flush()

        def _src(site, url, price, stock, sku):
            sp = SourceProduct(site=site, url=url, last_status='ok')
            s.add(sp); s.flush()
            so = SourceOption(source_product_id=sp.id, color_text='블랙',
                              size_text='M', current_price=price,
                              current_stock=stock)
            s.add(so); s.flush()
            lk = OptionSourceLink(canonical_sku=sku, source_option_id=so.id)
            s.add(lk); s.flush()
            made['sp'].append(sp.id); made['so'].append(so.id); made['link'].append(lk.id)

        if made['skus']:
            _src('lemouton', 'https://t.example/a1', 22000, 6, _SKU_A)   # 재고 6
            _src('musinsa', 'https://t.example/a2', 23500, 0, _SKU_A)    # 품절
            _src('ssf', 'https://t.example/a3', None, None, _SKU_A)      # 미크롤 → 확인불가
            # 혜택 계산이 **확실히 불가능한** 소싱처(pricing_source_id 없음) —
            #   final=None 보장(tests/matrix/test_rows_final_purchase_price.py 와 같은 근거).
            _src('unknown_site', 'https://t.example/a4', 33000, 2, _SKU_A)
        s.commit()
        yield
    finally:
        try:
            for lid in made['link']:
                s.query(OptionSourceLink).filter_by(id=lid).delete()
            for soid in made['so']:
                s.query(SourceOption).filter_by(id=soid).delete()
            for spid in made['sp']:
                s.query(SourceProduct).filter_by(id=spid).delete()
            for sku in made['skus']:
                s.query(Option).filter_by(canonical_sku=sku).delete()
            s.commit()
        finally:
            s.close()


# ════════════════════════════════════════════════════════════
#  ① 화면 · ② 메뉴
# ════════════════════════════════════════════════════════════

def test_화면이_뜨고_시안_구조가_있다(client):
    """fD1 구조 — 검색 상자 + 카드 그릇. 부품 클래스는 시안 이름 그대로다."""
    html = _matrix_html(client)
    assert re.search(r'<input[^>]*id="mm-q"', html), '검색 입력 상자(mm-q)가 없다'
    assert 'id="mm-cards"' in html, '결과 카드 그릇(mm-cards)이 없다'
    # 시안 부품 클래스가 CSS 규칙으로 실재한다(낱말이 아니라 규칙 본문).
    src = _tpl_src()
    for cls, needle in (('.card', 'border-radius'), ('.row', 'display:flex'),
                        ('.num', 'tabular-nums'), ('.bg', 'border-radius')):
        m = re.search(re.escape(cls) + r'[^{]*\{([^}]*)\}', src)
        assert m, f'시안 부품 {cls} 규칙이 없다'
        assert needle.split(':')[0] in m.group(1), f'{cls} 규칙에 {needle} 이 없다'
    # 배지 3색 — 시안 이름 그대로(g-grn/g-red/g-amb).
    for cls in ('.g-grn', '.g-red', '.g-amb'):
        assert re.search(re.escape(cls) + r'\s*\{[^}]*background', src), \
            f'재고 배지 색 {cls} 규칙이 없다'


def test_메뉴_목록에_실렸다():
    from webapp.routes.mobile_shell import PHONE_NATIVE_ROWS
    rows = [it for it in PHONE_NATIVE_ROWS if it['url'] == '/mobile/matrix']
    assert rows, '/mobile/matrix 가 PHONE_NATIVE_ROWS 에 없다 — 메뉴에서 못 들어간다'
    # PC /matrix 는 권한 게이트가 없다(모든 팀원이 본다) — 폰도 같아야 한다.
    assert not rows[0].get('admin_only'), 'PC 매트릭스는 안 잠겨 있는데 폰만 잠갔다'


# ════════════════════════════════════════════════════════════
#  ③ 검색 배선
# ════════════════════════════════════════════════════════════

def test_두_글자_미만_검색은_거절한다(client):
    r = client.get('/mobile/matrix/api/search?q=니')
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_검색이_DB를_실제로_읽는다(client, seeded):
    """서로 다른 두 검색어 → 서로 다른 답(하드코딩 결과 차단)."""
    j1 = client.get('/mobile/matrix/api/search?q=컴포트 니트').get_json()
    j2 = client.get('/mobile/matrix/api/search?q=클래식 로퍼').get_json()
    assert j1['ok'] and j2['ok']
    skus1 = {it['sku'] for it in j1['items']}
    skus2 = {it['sku'] for it in j2['items']}
    assert _SKU_A in skus1 and _SKU_A not in skus2
    assert _SKU_B in skus2 and _SKU_B not in skus1


def test_옵션_낱말로도_찾는다(client, seeded):
    """「니트 블랙 M」 — 상품명+색+사이즈 낱말 전부 맞는 옵션만(시안 예시 그대로)."""
    j = client.get('/mobile/matrix/api/search?q=니트 블랙 M').get_json()
    assert j['ok']
    skus = {it['sku'] for it in j['items']}
    assert _SKU_A in skus
    assert _SKU_B not in skus, '낱말이 하나도 안 맞는 옵션이 결과에 섞였다'


# ════════════════════════════════════════════════════════════
#  ④ 재고 의미 보존 — 서버 판정 · 확인불가 둔갑 금지
# ════════════════════════════════════════════════════════════

def test_소싱처_줄_배지를_서버가_판정해_내려보낸다(client, seeded):
    j = client.get('/mobile/matrix/api/search?q=컴포트 니트').get_json()
    card = next(it for it in j['items'] if it['sku'] == _SKU_A)
    assert len(card['sources']) == 4, '소싱처 4갈래가 다 안 실렸다'

    stock6 = next(x for x in card['sources'] if x['surface'] == 22000)
    oos = next(x for x in card['sources'] if x['surface'] == 23500)
    unknown = next(x for x in card['sources'] if x['surface'] is None)

    assert stock6['badge'] == {'kind': 'ok', 'label': '재고 6'}
    assert oos['badge'] == {'kind': 'oos', 'label': '품절'}
    # 🔴 1원칙 — 모르면 「확인불가」. '재고 있음' 으로 바꾸면 이 두 줄이 잡는다.
    assert unknown['badge']['kind'] == 'unknown'
    assert unknown['badge']['label'] == '확인불가'
    assert unknown['price'] is None, '크롤 안 된 소싱처에 가격을 지어냈다'


def test_재고_판정_규칙이_정본과_같은_부류다():
    """서버 배지 판정 ↔ guide_url_result._stock_label(정본) 전 구간 대조.

    두 함수가 다른 답을 내기 시작하면(센티넬 변경 등) 여기서 갈라진 값이 잡힌다.
    """
    from lemouton.sourcing.guide_url_result import _stock_label
    from webapp.routes.mobile_matrix import _stock_badge

    category_of = {'품절': 'oos', '확인 불가': 'unknown', '재고 있음': 'ok'}
    for v in (None, -1, 0, 1, 3, 7, 998, 999, 1500, 'abc'):
        canon = _stock_label(v)
        badge = _stock_badge(v)
        want_kind = category_of.get(canon, 'ok')   # 'N개' → ok
        assert badge['kind'] == want_kind, \
            f'재고 {v!r}: 정본은 {canon!r} 인데 폰 배지는 {badge!r} — 판정이 갈라졌다'

    assert _stock_badge(999)['label'] == '재고 있음', '999 는 개수가 아니라 센티넬이다'
    assert _stock_badge(5)['label'] == '재고 5'
    assert _stock_badge(None)['label'] == '확인불가'
    assert _stock_badge(-1)['label'] == '확인불가'


def test_폰_JS_는_재고를_다시_판정하지_않는다():
    """🔴 같은 판정 두 곳 금지 — 배지 글자·판정은 서버 값 그대로 그린다.

    템플릿 스크립트에 '품절'·'확인불가'·'재고 있음' 판정 갈래가 생기면 서버와
    폰이 다른 답을 낼 수 있다(이 저장소가 내내 싸운 두-원천 drift).
    """
    src = _tpl_src()
    m = re.search(r'{%\s*block extra_script\s*%}(.*?){%\s*endblock\s*%}', src, re.S)
    assert m, 'extra_script 블록이 없다'
    js = m.group(1)
    for word in ('품절', '확인불가', '재고 있음'):
        assert word not in js, \
            f'폰 JS 가 {word!r} 를 직접 판정한다 — 서버 badge.label 을 그대로 써야 한다'
    assert 'badge' in js, '서버 badge 를 그리는 코드가 없다'


# ════════════════════════════════════════════════════════════
#  ⑤ 가격 — final 우선 · 종류 표시 · 없으면 '-'
# ════════════════════════════════════════════════════════════

def test_가격은_종류를_밝히고_없으면_None(client, seeded):
    j = client.get('/mobile/matrix/api/search?q=컴포트 니트').get_json()
    card = next(it for it in j['items'] if it['sku'] == _SKU_A)
    surf_only = next(x for x in card['sources'] if x['surface'] == 33000)
    priced = next(x for x in card['sources'] if x['surface'] == 22000)
    unknown = next(x for x in card['sources'] if x['surface'] is None)

    # 혜택 계산이 불가능한 소싱처 → final=None → 표면가로 **종류를 밝히고** 표시
    #   (표면가를 최종가인 척 내보내면 memory: project_crawl_log_vs_final_price 재발)
    assert surf_only['final'] is None
    assert surf_only['price'] == 33000 and surf_only['price_kind'] == 'surface'
    # final 이 계산된 소싱처 → 규칙은 final 우선(PC 「최저」 판정과 같은 규칙)
    assert priced['price'] == (priced['final'] or priced['surface'])
    if priced['final'] is not None:
        assert priced['price_kind'] == 'final'
    # 아무 값도 없으면 지어내지 않는다
    assert unknown['price'] is None and unknown['price_kind'] is None


def test_폰은_가격_없으면_빼기표를_그린다():
    """render 갈래 — price 가 null 이면 '-'(0·빈칸·폴백 금지)."""
    src = _tpl_src()
    m = re.search(r"price\s*==\s*null\s*\?\s*'-'", src)
    assert m, "가격 없음 → '-' 갈래가 폰 JS 에 없다"

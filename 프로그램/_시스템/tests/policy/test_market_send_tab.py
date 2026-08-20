# -*- coding: utf-8 -*-
"""「자동화」 분류 → 「상품수집&전송」 + 하위탭 2개.

🔴 이 파일이 지키는 것 — **하위탭 원천이 두 곳**이라는 사실.
   화면 가로탭(`market_send.SUBTABS`)만 고치면 상단 메뉴는 옛것으로 남는다.
   optgen 하위탭 때 실제로 그렇게 됐다(사장님이 라이브에서 잡음).
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')

from webapp.routes import api_sidebar as SB          # noqa: E402
from webapp.routes.market_send import SUBTABS         # noqa: E402


def _stage(layout, sid):
    return next((s for s in layout['stages'] if s['id'] == sid), None)


# ── 두 원천이 같은 것을 말하는가 ────────────────────────────────────────

def test_상단메뉴와_화면_가로탭이_같은_순서다():
    """한쪽만 고치면 메뉴가 옛것으로 남는다 — 그 사고를 여기서 막는다."""
    메뉴_주소 = [SB._ITEM_DEFS[i]['url'] for i in SB._SEND2]
    화면_주소 = [t['url'] for t in SUBTABS]
    assert 메뉴_주소 == 화면_주소, f'메뉴 {메뉴_주소} vs 화면 {화면_주소}'


def test_기본_레이아웃에_하위탭_2개가_들어있다():
    st = _stage(SB._default_layout(), 's_auto')
    assert st is not None
    assert st['name'] == SB._SEND_STAGE_NAME == '상품수집&전송'
    assert [i['id'] for i in st['items']] == ['i_market_send', 'i_automation']


def test_자동화_이름은_저장본을_이긴다():
    """라이브에 저장된 옛 이름(「수집·전송 자동화」)이 이기면 개명이 안 보인다."""
    assert 'i_automation' in SB._FORCE_RENAME
    got = SB._item('i_automation', {'name': '수집·전송 자동화', 'emoji': '🌀'})
    assert got['name'] == '자동화'


# ── 저장본 갈아끼우기 ──────────────────────────────────────────────────

def test_옛_저장본을_갈아끼운다():
    old = {'standalone': [], 'stages': [
        {'id': 's_auto', 'emoji': '⚙️', 'name': '자동화', 'color': '#8B5CF6',
         'items': [{'id': 'i_automation', 'emoji': '⚙️', 'name': '수집·전송 자동화'}]}]}
    assert SB._migrate_send2(old) is True
    st = _stage(old, 's_auto')
    assert st['name'] == SB._SEND_STAGE_NAME == '상품수집&전송'
    assert [i['id'] for i in st['items']] == ['i_market_send', 'i_automation']


def test_두_번_돌려도_안전하다():
    old = {'standalone': [], 'stages': [
        {'id': 's_auto', 'emoji': '⚙️', 'name': '자동화', 'color': '#8B5CF6',
         'items': [{'id': 'i_automation', 'emoji': '⚙️', 'name': '수집·전송 자동화'}]}]}
    SB._migrate_send2(old)
    assert SB._migrate_send2(old) is False        # 두 번째는 아무것도 안 한다
    ids = [i['id'] for i in _stage(old, 's_auto')['items']]
    assert ids == ['i_market_send', 'i_automation'], '중복으로 들어갔다'


def test_s_auto_가_없는_저장본도_받는다():
    """옛 레이아웃엔 분류째로 없을 수 있다 — 그때도 만들어 넣어야 한다."""
    old = {'standalone': [], 'stages': [{'id': 's_etc', 'name': '기타', 'items': []}]}
    assert SB._migrate_send2(old) is True
    assert _stage(old, 's_auto') is not None


# ── 화면 ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 🔴 `/automation` 은 `ENVIRONMENT=team-share-dev` 일 때 **관리자 전용**이 된다
    #   (settings.py 의 before_request). 다른 스위트가 그 값을 환경에 남기면 이 검사가
    #   로그인 화면으로 튕겨 「혼자 돌리면 통과, 같이 돌리면 실패」가 된다 — 실측으로 걸렸다.
    #   여기서 지워 **돌리는 순서와 무관하게** 같은 답이 나오게 한다.
    monkeypatch.delenv('ENVIRONMENT', raising=False)
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)
    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass
    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


def test_마켓전송_화면이_열린다(client):
    r = client.get('/market-send')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '상품수집&amp;전송' in html
    assert 'ms-tab' in html


def test_두_화면_모두_하위탭_2개를_보여준다(client):
    """옆 탭으로 오갈 수 없으면 하위탭이 아니라 그냥 딴 화면이다."""
    for url in ('/market-send', '/automation'):
        html = client.get(url).get_data(as_text=True)
        assert html.count('class="ms-tab') >= 2, f'{url} 에 하위탭이 없다'
        assert '/market-send' in html and '/automation' in html, url


def test_필터가_전부_펼쳐져_있다(client):
    """A안 확정 — 더망고처럼 필터를 접지 않고 다 보여준다."""
    html = client.get('/market-send').get_data(as_text=True)
    for 있어야 in ('소싱처 수집날', '마켓 전송날',      # ④ 날짜 골라쓰기
                  '정책 안 붙은 것만',                 # ③ 우리에게만 있는 안전 필터
                  '아직 미등록만',                     # ③ 마켓 등록 여부
                  '보낼 마켓'):
        assert 있어야 in html, 있어야


def test_전송_버튼이_있고_재고_경고를_같이_말한다(client):
    """재고를 못 읽은 구성은 **그 구성만** 안 나간다 — 그 사실을 미리 말한다."""
    html = client.get('/market-send').get_data(as_text=True)
    assert 'id="btnSend"' in html
    assert 'disabled>긁기' not in html          # 이제 눌린다
    assert '그 구성은 보내지 않습니다' in html
    assert '오버셀' in html


def test_실시간_로그_자리가_있다(client):
    """사장님 확정 — 「전송은 실시간으로 보여지게」."""
    html = client.get('/market-send').get_data(as_text=True)
    assert 'id="lgBox"' in html
    assert '/api/market-send/start' in html
    assert '/api/market-send/jobs/' in html
    # 🔴 마켓이 한 말과 우리 말을 화면에서도 갈라 놓는다
    assert '← 마켓 원문' in html
    assert '마켓이 한 말' in html


def test_목록은_구성_기준_칸을_가진다(client):
    """한 줄 = 구성(벌) — 사장님 확정 ①. 소싱처는 여럿일 수 있다."""
    html = client.get('/market-send').get_data(as_text=True)
    assert '/api/market-send/rows' in html          # 목록을 실제로 불러온다
    assert '하나라도 물고 있으면' in html            # 소싱처 복합 안내


def test_자동화_화면은_그대로_돈다(client):
    """탭을 얹었다고 원래 기능이 깨지면 안 된다."""
    html = client.get('/automation').get_data(as_text=True)
    assert '자동화 설정' in html
    assert 'au-root' in html


def test_소싱처_긁기는_내_PC_크롬에_맡긴다(client):
    """🔴 크롤=로컬 PC 원칙 — 서버는 소싱처를 못 긁는다.

    확장이 없으면 **그 사실을 말하고 체크를 막는다.** 조용히 건너뛰면
    옛 값이 그대로 마켓에 나간다.
    """
    html = client.get('/market-send').get_data(as_text=True)
    assert 'id="fCrawl"' in html
    assert 'MoumExt' in html and 'enqueueCrawl' in html
    assert '크롬 확장이 꺼져 있어 긁을 수 없습니다' in html


def test_긁기와_보내기가_따로_있다(client):
    """사장님 확정 ② — 둘 다 둔다(더망고의 「업데이트 항목」 자리)."""
    html = client.get('/market-send').get_data(as_text=True)
    assert '① 소싱처에서 다시 긁기' in html
    assert '② 보낼 마켓' in html


# ── [2026-08-06 사장님 지시] 「상품 마켓 전송」 → 「상품수집&전송」 개명 ──────────
#   🔴 이 분류 이름은 **저장본(sidebar_layout.json)에도 박혀 있다.** 코드 상수만 고치면
#      라이브 화면은 옛 이름 그대로다(i_policies·optgen 하위탭 때 반복된 자리).

def test_옛_저장본의_분류_이름도_개명된다():
    """저장본에 옛 이름이 남아 있어도 새 이름으로 올라와야 한다."""
    saved = {'standalone': [], 'stages': [
        {'id': 's_auto', 'emoji': '📤', 'name': '상품 마켓 전송', 'color': '#8B5CF6',
         'items': [{'id': 'i_market_send'}, {'id': 'i_automation'}]}]}
    assert SB._migrate_send_rename(saved) is True
    assert _stage(saved, 's_auto')['name'] == '상품수집&전송'
    assert SB._migrate_send_rename(saved) is False      # 두 번째는 아무것도 안 한다


def test_옛_마이그레이션은_개명을_못_한다():
    """왜 마이그레이션을 새로 만들었나 — `_migrate_send2` 는 **이미 끝난 것**이라 안 돈다.

    이 검사가 빨간불이 되면 개명 마이그레이션은 지워도 된다는 뜻이다.
    """
    saved = {'standalone': [], 'stages': [
        {'id': 's_auto', 'emoji': '📤', 'name': '상품 마켓 전송', 'color': '#8B5CF6',
         'items': [{'id': 'i_market_send'}, {'id': 'i_automation'}]}]}
    assert SB._migrate_send2(saved) is False            # 손도 안 댄다
    assert _stage(saved, 's_auto')['name'] == '상품 마켓 전송'


def test_로더가_개명을_실제로_돌려서_저장한다(tmp_path, monkeypatch):
    """상수만 고치고 로더에 안 물리면 라이브는 안 바뀐다 — 배선까지 못 박는다."""
    import json
    path = tmp_path / 'sidebar_layout.json'
    layout = SB._default_layout()
    for st in layout['stages']:
        if st['id'] == 's_auto':
            st['name'] = '상품 마켓 전송'               # 라이브에 저장돼 있던 옛 이름
    path.write_text(json.dumps(layout, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(SB, 'LAYOUT_PATH', path)
    monkeypatch.setattr(SB, '_layout_cache', {'mtime': 0.0, 'data': None})
    got = SB._load()

    assert _stage(got, 's_auto')['name'] == '상품수집&전송'
    on_disk = json.loads(path.read_text(encoding='utf-8'))
    assert next(s for s in on_disk['stages'] if s['id'] == 's_auto')['name'] == '상품수집&전송', \
        '저장본을 다시 안 써서, 다음 배포 때 옛 이름이 되살아난다'


def test_옛_이름이_화면_템플릿에_안_남았다():
    """전수 grep — 화면(템플릿) 어디에도 옛 이름이 남으면 안 된다.

    ★코드 주석은 뺀다 — 「왜 또 바꿨나」를 적어 두는 건 남겨야 할 기록이다.
      여기서 막는 건 **사장님 눈에 보이는 글자**다.
    """
    from pathlib import Path
    tpl = Path(SB.__file__).resolve().parents[1] / 'templates'
    남은 = [str(p.relative_to(tpl)) for p in tpl.rglob('*.html')
           if '상품 마켓 전송' in p.read_text(encoding='utf-8', errors='ignore')]
    assert 남은 == [], f'화면에 옛 이름이 남아 있다: {남은}'


def test_두_화면_어디에도_옛_이름이_안_뜬다(client):
    """실제로 그려진 HTML 로 확인 — 상수·저장본·템플릿 중 하나만 어긋나도 여기서 잡힌다."""
    for url in ('/market-send', '/automation'):
        html = client.get(url).get_data(as_text=True)
        assert '상품 마켓 전송' not in html, url
        assert '상품수집&amp;전송' in html, url        # 상단 메뉴 분류 이름


# ── 칸별 호버카드 — 옵션별·소싱처별 가격·재고 이력 (2026-08 개편) ──────────

def _seed_history(session, *, model_code='M1', sku='SKU1', color='화이트', size='250'):
    from datetime import datetime
    from lemouton.sourcing.models import Model, Option
    from lemouton.sets.models import ProductSet, SetProduct, SetOption
    from lemouton.templates.models import PriceTrackHistory
    m = Model(model_code=model_code, model_name_raw='나이키 반팔', model_name_display='나이키 반팔',
              brand='나이키', display_no='M20260101-000001')
    session.add(m)
    o = Option(canonical_sku=sku, model_code=model_code, color_code=color, color_display=color,
               size_code=size, size_display=size)
    session.add(o)
    ps = ProductSet(model_code=model_code, name='단품')
    session.add(ps)
    session.flush()
    sp = SetProduct(set_id=ps.id, model_code=model_code)
    session.add(sp)
    session.flush()
    session.add(SetOption(set_product_id=sp.id, canonical_sku=sku))
    session.add(PriceTrackHistory(canonical_sku=sku, source='musinsa',
                                  price=38900, stock=11,
                                  captured_at=datetime(2026, 8, 19, 9, 0)))
    session.add(PriceTrackHistory(canonical_sku=sku, source='musinsa',
                                  price=38900, stock=12,
                                  captured_at=datetime(2026, 8, 20, 9, 0)))
    session.flush()
    return ps.id


def test_호버카드_이력_API가_옵션당_소싱처별_최근_2줄을_돌려준다(client):
    sess = client._Session()
    try:
        set_id = _seed_history(sess)
        sess.commit()
    finally:
        sess.close()
    r = client.get(f'/api/market-send/rows/{set_id}/history')
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    assert len(d['skus']) == 1
    sk = d['skus'][0]
    assert sk['color'] == '화이트' and sk['size'] == '250'
    musinsa = sk['sources']['musinsa']
    assert musinsa['current_stock'] == 12 and musinsa['current_price'] == 38900
    assert len(musinsa['history']) == 2        # 최근 2줄만 — 전체 이력은 price-chart 몫


def test_이력_없는_옵션은_카드에서_빠진다(client):
    """빈 줄을 늘어놓지 않는다 — listing.py 의 「지어내지 않는다」와 같은 원칙."""
    from lemouton.sourcing.models import Model, Option
    from lemouton.sets.models import ProductSet, SetProduct, SetOption
    sess = client._Session()
    try:
        sess.add(Model(model_code='M2', model_name_raw='이력없음', display_no='M-2'))
        sess.add(Option(canonical_sku='SKU2', model_code='M2', color_code='블랙', size_code='250'))
        ps = ProductSet(model_code='M2', name='단품')
        sess.add(ps)
        sess.flush()
        sp = SetProduct(set_id=ps.id, model_code='M2')
        sess.add(sp)
        sess.flush()
        sess.add(SetOption(set_product_id=sp.id, canonical_sku='SKU2'))
        sess.commit()
        set_id = ps.id
    finally:
        sess.close()
    d = client.get(f'/api/market-send/rows/{set_id}/history').get_json()
    assert d['skus'] == []


def test_소싱처가_둘이면_한_숫자로_뭉개지_않고_둘_다_나온다(client):
    """🔴 listing.py 의 buy_source=None 원칙과 같다 — 「지금 사오는 곳」을 안 정했다."""
    from datetime import datetime
    from lemouton.sourcing.models import Model, Option
    from lemouton.sets.models import ProductSet, SetProduct, SetOption
    from lemouton.templates.models import PriceTrackHistory
    sess = client._Session()
    try:
        sess.add(Model(model_code='M3', model_name_raw='복수소싱', display_no='M-3'))
        sess.add(Option(canonical_sku='SKU3', model_code='M3', color_code='화이트', size_code='250'))
        ps = ProductSet(model_code='M3', name='단품')
        sess.add(ps)
        sess.flush()
        sp = SetProduct(set_id=ps.id, model_code='M3')
        sess.add(sp)
        sess.flush()
        sess.add(SetOption(set_product_id=sp.id, canonical_sku='SKU3'))
        sess.add(PriceTrackHistory(canonical_sku='SKU3', source='musinsa', price=38900, stock=10,
                                   captured_at=datetime(2026, 8, 20, 9, 0)))
        sess.add(PriceTrackHistory(canonical_sku='SKU3', source='ssf', price=39900, stock=3,
                                   captured_at=datetime(2026, 8, 20, 9, 0)))
        sess.commit()
        set_id = ps.id
    finally:
        sess.close()
    d = client.get(f'/api/market-send/rows/{set_id}/history').get_json()
    srcs = d['skus'][0]['sources']
    assert set(srcs.keys()) == {'musinsa', 'ssf'}
    assert srcs['musinsa']['current_price'] == 38900
    assert srcs['ssf']['current_price'] == 39900


# ── 판매처 수집 칸 호버카드 — 옵션별·마켓별 판매가·예상마진 (2026-08 개편 ⑦) ──

def _seed_market_channel(session, *, model_code='MM1', sku='MSKU1', color='화이트', size='250'):
    from lemouton.sourcing.models import Model, Option
    from lemouton.sets.models import ProductSet, SetProduct, SetOption, SetChannel, SetChannelOption
    session.add(Model(model_code=model_code, model_name_raw='마켓상품', display_no='M-MM1'))
    session.add(Option(canonical_sku=sku, model_code=model_code, color_code=color, size_code=size))
    ps = ProductSet(model_code=model_code, name='단품')
    session.add(ps)
    session.flush()
    sp = SetProduct(set_id=ps.id, model_code=model_code)
    session.add(sp)
    session.flush()
    session.add(SetOption(set_product_id=sp.id, canonical_sku=sku))
    ch = SetChannel(set_id=ps.id, market='smartstore')
    session.add(ch)
    session.flush()
    from datetime import datetime
    session.add(SetChannelOption(channel_id=ch.id, canonical_sku=sku, status='matched',
                                 mkt_price=49000, mkt_stock=7,
                                 mkt_fetched_at=datetime(2026, 8, 19, 13, 0)))
    session.flush()
    return ps.id, ch.id


def test_판매처_수집_API가_옵션당_마켓별_판매가_재고를_돌려준다(client):
    sess = client._Session()
    try:
        set_id, _ = _seed_market_channel(sess)
        sess.commit()
    finally:
        sess.close()
    r = client.get(f'/api/market-send/rows/{set_id}/margin')
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    assert len(d['skus']) == 1
    sk = d['skus'][0]
    assert sk['color'] == '화이트' and sk['size'] == '250'
    ss = sk['markets']['smartstore']
    assert ss['price'] == 49000 and ss['stock'] == 7
    assert ss['fetched_at'] == '08-19 13:00'


def test_매입가를_모르면_마진을_지어내지_않고_사유를_남긴다(client):
    """🔴 소싱 크롤 데이터가 없어 최종매입가를 못 구하는 흔한 경우 — margin 은 None, 사유는 있어야 한다."""
    sess = client._Session()
    try:
        set_id, _ = _seed_market_channel(sess)
        sess.commit()
    finally:
        sess.close()
    d = client.get(f'/api/market-send/rows/{set_id}/margin').get_json()
    ss = d['skus'][0]['markets']['smartstore']
    assert ss['margin'] is None
    assert ss['margin_reason']       # 빈 문자열이 아니라 실제 사유가 있어야 한다


def test_마켓_데이터가_없는_옵션은_카드에서_빠진다(client):
    """빈 줄을 늘어놓지 않는다 — history 엔드포인트와 같은 원칙."""
    from lemouton.sourcing.models import Model, Option
    from lemouton.sets.models import ProductSet, SetProduct, SetOption
    sess = client._Session()
    try:
        sess.add(Model(model_code='MM2', model_name_raw='마켓데이터없음', display_no='M-MM2'))
        sess.add(Option(canonical_sku='MSKU2', model_code='MM2', color_code='블랙', size_code='250'))
        ps = ProductSet(model_code='MM2', name='단품')
        sess.add(ps)
        sess.flush()
        sp = SetProduct(set_id=ps.id, model_code='MM2')
        sess.add(sp)
        sess.flush()
        sess.add(SetOption(set_product_id=sp.id, canonical_sku='MSKU2'))
        sess.commit()
        set_id = ps.id
    finally:
        sess.close()
    d = client.get(f'/api/market-send/rows/{set_id}/margin').get_json()
    assert d['skus'] == []


def test_마켓이_둘이면_한_숫자로_뭉개지_않고_둘_다_나온다(client):
    from datetime import datetime
    from lemouton.sourcing.models import Model, Option
    from lemouton.sets.models import ProductSet, SetProduct, SetOption, SetChannel, SetChannelOption
    sess = client._Session()
    try:
        sess.add(Model(model_code='MM3', model_name_raw='복수마켓', display_no='M-MM3'))
        sess.add(Option(canonical_sku='MSKU3', model_code='MM3', color_code='화이트', size_code='250'))
        ps = ProductSet(model_code='MM3', name='단품')
        sess.add(ps)
        sess.flush()
        sp = SetProduct(set_id=ps.id, model_code='MM3')
        sess.add(sp)
        sess.flush()
        sess.add(SetOption(set_product_id=sp.id, canonical_sku='MSKU3'))
        ch1 = SetChannel(set_id=ps.id, market='smartstore')
        ch2 = SetChannel(set_id=ps.id, market='coupang')
        sess.add_all([ch1, ch2])
        sess.flush()
        sess.add(SetChannelOption(channel_id=ch1.id, canonical_sku='MSKU3', status='matched',
                                  mkt_price=49000, mkt_stock=7,
                                  mkt_fetched_at=datetime(2026, 8, 19, 13, 0)))
        sess.add(SetChannelOption(channel_id=ch2.id, canonical_sku='MSKU3', status='matched',
                                  mkt_price=51000, mkt_stock=2,
                                  mkt_fetched_at=datetime(2026, 8, 19, 13, 0)))
        sess.commit()
        set_id = ps.id
    finally:
        sess.close()
    d = client.get(f'/api/market-send/rows/{set_id}/margin').get_json()
    mk = d['skus'][0]['markets']
    assert set(mk.keys()) == {'smartstore', 'coupang'}
    assert mk['smartstore']['price'] == 49000
    assert mk['coupang']['price'] == 51000


def test_최근_가격_변동이_같이_실린다(client):
    from datetime import datetime
    from lemouton.sets.models import ChannelChangeEvent
    sess = client._Session()
    try:
        set_id, _ = _seed_market_channel(sess)
        sess.add(ChannelChangeEvent(set_id=set_id, market='smartstore', canonical_sku='MSKU1',
                                    field='price', source='market',
                                    prev_value=45000, next_value=49000,
                                    at=datetime(2026, 8, 19, 13, 0)))
        sess.commit()
    finally:
        sess.close()
    d = client.get(f'/api/market-send/rows/{set_id}/margin').get_json()
    ss = d['skus'][0]['markets']['smartstore']
    assert ss['prev_price'] == 45000

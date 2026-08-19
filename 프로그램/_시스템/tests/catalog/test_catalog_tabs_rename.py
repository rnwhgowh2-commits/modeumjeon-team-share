# -*- coding: utf-8 -*-
"""[2026-08-12 노션] 상품관리 하위탭 — 「모음전」 떼기 + 순서 뒤집기.

노션 「무재고 모음전 솔루션 개발현황 > 프로그램 개선사항 > 상품관리」:
  a. 이름변경 : 모음전 상품관리 / 모음전 옵션관리 → 모음전 삭제할것. 상품관리 / 옵션관리
  b. 순서변경 : 옵션 변경 / 상품 변경
사장님 확정(2026-08-12): 순서 = 옵션관리 → 상품관리 → 실마켓 상품 현황.
  「마켓 상품 현황」도 「실마켓 상품 현황」으로 같이 개명.

★ 왜 시험이 이렇게 많나 — 이 프로젝트가 **같은 자리에서 네 번** 넘어졌다.
  `_ITEM_DEFS`(코드 상수)만 고치면 화면은 안 바뀐다. 서버가 읽는 건 저장본
  (`data/sidebar_layout.json`)이고, `get_layout_for_template()` 은 저장본에
  **이미 있는** 항목을 `_item()` 을 안 거치고 그대로 통과시킨다 →
  `_FORCE_RENAME` 도 안 닿는다. (i_policies · i_automation · s_auto 때 반복)
  그래서 상수·마이그레이션·로더 배선·렌더 결과를 **따로따로** 못 박는다.
"""
import json

import pytest

from webapp.routes import api_sidebar as SB


def _stage(out, sid):
    for st in out.get('stages', []):
        if st.get('id') == sid:
            return st
    return None


def _ids(out, sid):
    return [it.get('id') for it in (_stage(out, sid) or {}).get('items', [])]


def _names(out, sid):
    return [it.get('name') for it in (_stage(out, sid) or {}).get('items', [])]


# ── ① 상수 ────────────────────────────────────────────────────

def test_이름에서_모음전이_빠졌다():
    assert SB._ITEM_DEFS['i_bundles']['name'] == '상품관리'
    assert SB._ITEM_DEFS['i_matrix']['name'] == '옵션관리'
    assert SB._ITEM_DEFS['i_catalog']['name'] == '실마켓 상품 현황'


def test_개명_대상에_그대로_들어_있다():
    """사장님이 손으로 고쳐둔 이름이 있어도 새 이름이 이겨야 한다."""
    for iid in ('i_bundles', 'i_matrix', 'i_catalog'):
        assert iid in SB._FORCE_RENAME


def test_스펙_순서가_옵션_먼저다():
    """만드는 순서(옵션 → 상품)와 같게. 노션 b항."""
    spec = {s[0]: s for s in SB._STAGE_SPEC}
    assert spec['s_catalog'][4] == ['i_matrix', 'i_bundles', 'i_catalog']


def test_주소와_활성키는_안_건드린다():
    """이름만 바꾼다 — url·active_key 를 건드리면 모바일 메뉴·강조표시가 깨진다."""
    assert SB._ITEM_DEFS['i_bundles']['url'] == '/bundles'
    assert SB._ITEM_DEFS['i_matrix']['url'] == '/matrix'
    assert SB._ITEM_DEFS['i_catalog']['url'] == '/catalog/'
    assert SB._ITEM_DEFS['i_bundles']['active_key'] == 'bundles'
    assert SB._ITEM_DEFS['i_matrix']['active_key'] == 'matrix'
    assert SB._ITEM_DEFS['i_catalog']['active_key'] == 'catalog'


# ── ② 저장본 마이그레이션 ─────────────────────────────────────

def _live_saved():
    """개명 전 라이브 저장본을 그대로 흉내낸다(data/sidebar_layout.json 기준)."""
    return {
        'version': 1, 'schema': 8, 'standalone': [],
        'stages': [
            {'id': 's_catalog', 'emoji': '📦', 'name': '상품 관리', 'color': '#06B6D4',
             'items': [
                 {'id': 'i_bundles', 'emoji': '📋', 'name': '모음전 상품관리',
                  'url': '/bundles', 'active_key': 'bundles'},
                 {'id': 'i_matrix', 'emoji': '🧱', 'name': '모음전 옵션관리',
                  'url': '/matrix', 'active_key': 'matrix'},
                 {'id': 'i_catalog', 'emoji': '📦', 'name': '마켓 상품 현황',
                  'url': '/catalog/', 'active_key': 'catalog'},
             ]},
        ],
    }


def test_저장본_이름이_갈아끼워진다():
    layout = _live_saved()
    assert SB._migrate_catalog_rename(layout) is True
    assert _names(layout, 's_catalog') == ['상품관리', '옵션관리', '실마켓 상품 현황']


def test_개명은_어긋나면_다시_고치고_맞으면_안_건드린다():
    """개명은 **늘** 다시 걸어야 한다 — 저장본이 어긋나도 스스로 낫게."""
    layout = _live_saved()
    assert SB._migrate_catalog_rename(layout) is True
    assert SB._migrate_catalog_rename(layout) is False, '매 요청마다 저장을 유발한다'
    # 나중에 누가 옛 이름으로 되돌려 놓아도 다음 로드에 낫는다
    _stage(layout, 's_catalog')['items'][0]['name'] = '모음전 상품관리'
    assert SB._migrate_catalog_rename(layout) is True


def test_저장본_순서가_옵션_먼저로_바뀐다():
    """🔴 `get_layout_for_template()` 은 이미 있는 항목의 순서를 안 건드린다
    (「사장님이 드래그로 둔 자리가 곧 의도다」). 그래서 스펙만 고치면 순서는
    영영 안 바뀐다 — 저장본을 여기서 한 번 갈아끼워야 한다."""
    layout = _live_saved()
    assert SB._migrate_catalog_order(layout) is True
    assert _ids(layout, 's_catalog') == ['i_matrix', 'i_bundles', 'i_catalog']
    assert layout['schema'] == SB._SCHEMA


def test_재정렬은_한_번만_하고_그_뒤_드래그를_존중한다():
    """🔴 이 시험이 이 파일에서 제일 중요하다.

    「스펙 순서와 다르면 고친다」로 짜면, 사장님이 드래그로 순서를 바꾼 순간
    다음 요청에 되돌아간다 — 드래그가 아예 안 먹는 것처럼 보인다.
    1회 표시(schema)로만 「의도된 재정렬」과 「드래그 존중」이 양립한다.
    """
    layout = _live_saved()
    SB._migrate_catalog_order(layout)
    st = _stage(layout, 's_catalog')

    # 사장님이 도로 상품관리를 위로 끌어다 놓았다
    st['items'] = [st['items'][1], st['items'][0], st['items'][2]]
    assert SB._migrate_catalog_order(layout) is False, '드래그로 둔 자리를 또 뒤집었다'
    assert _ids(layout, 's_catalog') == ['i_bundles', 'i_matrix', 'i_catalog']


def test_상품관리_분류가_없는_저장본에도_안_터진다():
    layout = {'version': 1, 'schema': 8, 'standalone': [], 'stages': []}
    assert SB._migrate_catalog_rename(layout) is False
    # 분류가 없어도 표시는 남긴다 — 안 남기면 매 요청마다 다시 돈다
    assert SB._migrate_catalog_order(layout) is True
    assert layout['schema'] == SB._SCHEMA
    assert SB._migrate_catalog_order(layout) is False


def test_항목이_일부만_있어도_있는_것만_고친다():
    """옛 저장본엔 i_catalog 하나만 있던 시절도 있다."""
    layout = {'version': 1, 'schema': 8, 'standalone': [], 'stages': [
        {'id': 's_catalog', 'name': '상품 관리', 'items': [
            {'id': 'i_catalog', 'name': '마켓 상품 현황', 'url': '/catalog/'},
        ]},
    ]}
    assert SB._migrate_catalog_rename(layout) is True
    assert _names(layout, 's_catalog') == ['실마켓 상품 현황']


def test_모르는_항목은_스펙_뒤에_그대로_남는다():
    """사장님이 상품관리 분류에 직접 끌어다 놓은 딴 메뉴를 잃어버리면 안 된다."""
    layout = _live_saved()
    _stage(layout, 's_catalog')['items'].append(
        {'id': 'i_inventory', 'name': '재고관리', 'url': '/inventory/'})
    SB._migrate_catalog_order(layout)
    assert _ids(layout, 's_catalog') == ['i_matrix', 'i_bundles', 'i_catalog',
                                         'i_inventory']


def test_기본값의_세대가_최신이다():
    """기본값이 옛 세대면 새 볼륨이 뜨자마자 재정렬이 또 돌아 쓸데없이 저장한다."""
    assert SB._default_layout()['schema'] == SB._SCHEMA


def test_드래그_저장이_세대표시를_잃지_않는다():
    """저장 API 가 schema 를 안 채우면, 드래그로 둔 순서가 다음 로드에 되돌아간다."""
    import inspect
    src = inspect.getsource(SB.api_put_layout)
    assert "setdefault('schema'" in src


# ── ③ 로더 배선 ───────────────────────────────────────────────

def test_로더가_개명과_재정렬을_실제로_돌려서_저장한다(tmp_path, monkeypatch):
    """상수만 고치고 `_load()` 에 안 물리면 라이브는 안 바뀐다 — 배선까지 못 박는다.

    (`test_market_send_tab.py` 의 같은 이름 시험과 같은 자리·같은 이유)
    """
    path = tmp_path / 'sidebar_layout.json'
    layout = _live_saved()
    path.write_text(json.dumps(layout, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(SB, 'LAYOUT_PATH', path)
    monkeypatch.setattr(SB, '_layout_cache', {'mtime': 0.0, 'data': None})
    got = SB._load()

    assert _names(got, 's_catalog') == ['옵션관리', '상품관리', '실마켓 상품 현황']
    on_disk = json.loads(path.read_text(encoding='utf-8'))
    assert _names(on_disk, 's_catalog') == ['옵션관리', '상품관리', '실마켓 상품 현황'], \
        '저장본을 다시 안 써서, 다음 배포 때 옛 이름이 되살아난다'
    assert _ids(on_disk, 's_catalog') == ['i_matrix', 'i_bundles', 'i_catalog']
    assert on_disk['schema'] == SB._SCHEMA


# ── ④ 렌더 결과 ───────────────────────────────────────────────

def test_화면에는_새_이름_새_순서로_뜬다(monkeypatch):
    """상수·저장본·렌더 필터 중 하나만 어긋나도 여기서 잡힌다."""
    layout = _live_saved()
    SB._migrate_catalog_rename(layout)
    SB._migrate_catalog_order(layout)
    monkeypatch.setattr(SB, '_load', lambda: layout)
    out = SB.get_layout_for_template()
    assert _names(out, 's_catalog') == ['옵션관리', '상품관리', '실마켓 상품 현황']
    assert _ids(out, 's_catalog') == ['i_matrix', 'i_bundles', 'i_catalog']


def test_옛_이름이_화면_템플릿에_안_남았다():
    """전수 grep — 사장님 눈에 보이는 글자에서 옛 이름을 없앤다.

    ★코드 주석·도크스트링은 뺀다(왜 바꿨나는 남겨야 할 기록). 여기서 막는 건 화면.

    🔴 이 시험은 **두 낱말만** 세다가 「매트릭스 옵션」 5곳을 놓친 채로 초록불이었다
      (2026-08-12). 개명은 세 개인데 감시는 두 개였다 —
      **개명 하나당 금지 낱말 하나**를 여기 같이 넣어야 한다.

    🔴 「매트릭스」 하나로 세면 안 된다 — 「옵션 매트릭스」(상품관리 안의 가격 격자)·
      「매핑 매트릭스」는 **딴 것**이라 살아 있어야 한다. 옛 탭 이름인
      **「매트릭스 옵션」이라는 구절 그대로**만 막는다.
    """
    import re
    from pathlib import Path
    tpl = Path(SB.__file__).resolve().parents[1] / 'templates'
    금지 = [
        ('모음전 상품관리', None),
        ('모음전 옵션관리', None),
        ('매트릭스 옵션', None),          # 옛 탭·옛 개체 이름 (지금은 옵션관리 / 옵션 묶음)
        ('마켓 상품 현황', r'(?<!실)마켓 상품 현황'),   # 「실마켓 상품 현황」은 새 이름이라 통과
    ]
    남은 = []
    for p in tpl.rglob('*.html'):
        txt = p.read_text(encoding='utf-8', errors='ignore')
        for 옛, 패턴 in 금지:
            found = re.search(패턴, txt) if 패턴 else (옛 in txt)
            if found:
                남은.append(f'{p.relative_to(tpl)} :: {옛}')
    assert 남은 == [], f'화면에 옛 이름이 남아 있다: {남은}'


def test_옛_이름이_화면에_넘기는_파이썬_글자에도_안_남았다():
    """🔴 템플릿만 훑으면 못 잡는다 — 라우트가 **글자를 만들어 템플릿에 넘긴다**.

    `matrix.py` · `optgen.py` 가 404 화면에 `requested_code='매트릭스 옵션'` 을
    넘겨서, 템플릿엔 옛 이름이 한 글자도 없는데 **화면엔 뜬다**.
    그래서 템플릿 grep 이 통과하는 채로 깨져 있었다.

    🔴 줄 단위로 낱말을 세면 안 된다 — 도크스트링·주석까지 걸려서
      「왜 바꿨나」 기록을 지워야 통과하는 시험이 된다.
      그래서 **파이썬 문법으로 읽어**, 화면으로 나가는 인자(`render_template(...)`·
      `flash(...)`)에 박힌 글자만 본다. 설명글은 손대지 않는다.
    """
    import ast
    from pathlib import Path
    화면함수 = {'render_template', 'render_template_string', 'flash'}
    뿌리 = Path(SB.__file__).resolve().parents[1]        # webapp/
    남은 = []
    for p in sorted(뿌리.rglob('*.py')):
        tree = ast.parse(p.read_text(encoding='utf-8', errors='ignore'), str(p))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            이름 = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, 'id', '')
            if 이름 not in 화면함수:
                continue
            글자들 = [(None, a) for a in node.args]
            글자들 += [(kw.arg, kw.value) for kw in node.keywords]
            for 인자, v in 글자들:
                if (isinstance(v, ast.Constant) and isinstance(v.value, str)
                        and '매트릭스 옵션' in v.value):
                    남은.append(f'{p.relative_to(뿌리)}:{v.lineno} '
                                f'{이름}({인자 or "위치인자"}=)')
    assert 남은 == [], f'라우트가 옛 이름을 화면으로 넘긴다: {남은}'


# ── ⑤ 404 화면 — 이름표가 값과 맞아야 한다 ────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_없는_옵션묶음_404가_모음전_코드라고_안_한다(client):
    """🔴 `모음전 코드: 매트릭스 옵션` 이라고 떴다 — 값도 옛 이름이고, 이름표도 틀렸다.

    넘긴 값은 **옵션 묶음 번호**(mo_id)인데 이름표는 「모음전 코드」였다.
    사장님이 그 번호를 모음전 코드로 알고 찾으면 영영 못 찾는다.
    """
    html = client.get('/matrix/99887766').get_data(as_text=True)
    assert html.count('99887766') >= 1, '무엇을 찾다 실패했는지 안 알려준다'
    assert '옵션 묶음 번호' in html, f'번호에 맞는 이름표가 없다'
    assert '매트릭스 옵션' not in html
    assert '모음전 코드' not in html, '옵션 묶음 번호를 모음전 코드라고 부른다'


def test_없는_상품생성_조립대_404도_같다(client):
    """같은 404를 옵션생성 탭에서도 쓴다 — 한 곳만 고치면 다른 곳이 남는다."""
    html = client.get('/optgen/product/99887766').get_data(as_text=True)
    assert html.count('99887766') >= 1
    assert '옵션 묶음 번호' in html
    assert '매트릭스 옵션' not in html
    assert '모음전 코드' not in html


def test_없는_정책_404도_모음전_코드라고_안_한다(client):
    """`requested_code='정책'` — 정책 번호를 「모음전 코드」 자리에 넣고 있었다."""
    html = client.get('/policies/99887766').get_data(as_text=True)
    assert html.count('99887766') >= 1
    assert '정책 번호' in html
    assert '모음전 코드' not in html


def test_404_제목이_못_찾은_것과_같은_말이다(client):
    """정책 404가 「**옵션**을 찾을 수 없습니다」라고 떴다 — 화면 하나를 넷이 나눠 쓴다.

    정책을 찾다 실패했는데 옵션을 못 찾았다고 하면 사장님이 딴 데를 뒤진다.
    """
    html = client.get('/policies/99887766').get_data(as_text=True)
    assert '정책을 찾을 수 없습니다' in html
    assert '옵션을 찾을 수 없습니다' not in html


def test_옵션_404는_그대로_옵션이라고_한다(client):
    """제목을 바꾸다가 **맞던 것까지** 바꾸면 안 된다."""
    html = client.get('/matrix/99887766').get_data(as_text=True)
    assert '옵션을 찾을 수 없습니다' in html


def test_진짜_모음전_코드는_그대로_모음전_코드로_뜬다(client):
    """이름표를 손보다가 **맞던 것까지 바꾸면** 안 된다 — 여기가 그 자물쇠다."""
    html = client.get('/bundles/NOPE-CODE-1/option/NOPE-SKU-1').get_data(as_text=True)
    assert '모음전 코드' in html and 'NOPE-CODE-1' in html
    assert '옵션 SKU' in html and 'NOPE-SKU-1' in html

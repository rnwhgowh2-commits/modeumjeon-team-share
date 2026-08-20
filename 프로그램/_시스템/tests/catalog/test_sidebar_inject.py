# -*- coding: utf-8 -*-
"""사이드바 메뉴가 **라이브에 실제로 뜨는지** 지키는 테스트.

★ [2026-07-24 라이브에서 발견] data/sidebar_layout.json 만 고쳤더니 라이브 사이드바에
  메뉴가 **아예 안 떴다**. 서버는 사장님이 드래그로 바꾼 저장본을 쓰기 때문.
  사장님이 URL 을 직접 치지 않으면 이 화면에 들어갈 수 없었다.

★ [2026-07-30] 노션 8분류 재편. 항목마다 있던 「없으면 주입」 상수 7종을 _STAGE_SPEC
  하나로 합쳤다(그 갈림이 위 사고의 원인). 그래서 이 테스트도 특정 항목이 아니라
  **스펙 전체**가 라이브에 도달하는지를 지킨다.
"""
from webapp.routes import api_sidebar as SB


def _customized():
    """사장님이 드래그로 만져 상품관리·재고관리가 없는 저장본을 흉내낸다."""
    return {
        'version': 1, 'schema': 8, 'standalone': [],
        'stages': [
            {'id': 's_collect', 'name': '상품수집·생성', 'items': [
                {'id': 'i_bundles', 'name': '모음전 구성', 'url': '/bundles'},
            ]},
            {'id': 's_order', 'name': '주문 관리', 'items': [
                {'id': 'i_orders', 'name': '주문 내역', 'url': '/orders/?tab=list'},
                {'id': 'i_cs', 'name': 'CS', 'url': '/orders/?tab=cs'},
            ]},
        ],
    }


def _items(out, stage_id):
    for st in out.get('stages', []):
        if st.get('id') == stage_id:
            return st.get('items', [])
    return []


def _all_ids(out):
    return {it.get('id') for st in out.get('stages', []) for it in st.get('items', [])}


def test_저장본에_없는_스펙_항목은_전부_주입된다(monkeypatch):
    """하나라도 빠지면 사장님이 그 화면에 들어갈 방법이 없다."""
    monkeypatch.setattr(SB, '_load', _customized)
    got = _all_ids(SB.get_layout_for_template())
    expected = {i for _s, _e, _n, _c, ids in SB._STAGE_SPEC for i in ids}
    missing = expected - got
    assert not missing, f'사이드바에 안 뜨는 메뉴: {missing}'


def test_스테이지가_통째로_없어도_만들어진다(monkeypatch):
    """저장본에 없던 새 분류(상품 관리·재고관리 등)도 화면에 생겨야 한다."""
    monkeypatch.setattr(SB, '_load', _customized)
    out = SB.get_layout_for_template()
    catalog = _items(out, 's_catalog')
    assert [i for i in catalog if i['id'] == 'i_catalog'], '상품 관리 분류가 안 생겼다'
    assert _items(out, 's_inventory'), '재고관리 분류가 안 생겼다'


def test_주입된_항목은_주소와_이름이_스펙대로다(monkeypatch):
    monkeypatch.setattr(SB, '_load', _customized)
    got = [i for i in _items(SB.get_layout_for_template(), 's_catalog')
           if i['id'] == 'i_catalog']
    assert got[0]['url'] == '/catalog/'
    # [2026-08-01] 상품관리가 3탭으로 갈리면서 이 항목은 「마켓에 올라간 상품」 전용이 됐다.
    # [2026-08-12] 「모음전」을 떼면서 옆 탭이 「상품관리」가 됐다 → 「실」을 붙여 가른다.
    assert got[0]['name'] == '실마켓 상품 현황'


def test_이미_있으면_두_번_넣지_않고_자리도_안_옮긴다(monkeypatch):
    """사장님이 옮겨둔 자리를 덮어쓰거나 중복으로 늘리면 안 된다."""
    lay = _customized()
    lay['stages'][1]['items'].append(
        {'id': 'i_ship', 'name': '송장 작업', 'url': '/orders/?tab=ship'})
    monkeypatch.setattr(SB, '_load', lambda: lay)
    order = _items(SB.get_layout_for_template(), 's_order')
    assert len([i for i in order if i['id'] == 'i_ship']) == 1
    assert [i['id'] for i in order][:3] == ['i_orders', 'i_cs', 'i_ship'], \
        '사장님이 둔 순서를 바꿔버렸다'


def test_없앤_항목은_화면에_안_나온다(monkeypatch):
    """가격·재고 추적·신규 상품 등록·미맵핑 큐 등 — 저장본에 남아 있어도 걸러야 한다."""
    lay = _customized()
    lay['stages'][0]['items'] += [
        {'id': 'i_track', 'name': '가격·재고 추적', 'url': '/track'},
        {'id': 'i_queue', 'name': '미맵핑 큐', 'url': '/queue'},
        {'id': 'i_register', 'name': '신규 상품 등록', 'url': '/orders/?tab=register'},
    ]
    monkeypatch.setattr(SB, '_load', lambda: lay)
    got = _all_ids(SB.get_layout_for_template())
    assert not (got & SB._REMOVED_IDS), f'없앤 메뉴가 아직 보인다: {got & SB._REMOVED_IDS}'


def test_스테이지가_없어도_터지지_않는다(monkeypatch):
    """사장님이 그룹을 다 지웠을 수도 있다 — 그래도 앱이 떠야 한다."""
    monkeypatch.setattr(SB, '_load', lambda: {'version': 1, 'standalone': [], 'stages': []})
    out = SB.get_layout_for_template()
    assert isinstance(out.get('stages'), list) and out['stages']


def test_8분류_재편은_두_번_해도_같다(monkeypatch):
    """마이그레이션이 매 요청마다 저장을 유발하면 안 된다(idempotent)."""
    old = {'version': 1, 'standalone': [], 'stages': [
        {'id': 's_sell', 'name': '판매', 'items': [
            {'id': 'i_orders', 'name': '주문 내역', 'url': '/orders/?tab=list'},
            {'id': 'i_track', 'name': '가격·재고 추적', 'url': '/track'},
        ]},
    ]}
    assert SB._migrate_to_8groups(old) is True
    before = [(st['id'], [i['id'] for i in st['items']]) for st in old['stages']]
    assert SB._migrate_to_8groups(old) is False, '두 번째 호출에서 또 바꿨다'
    after = [(st['id'], [i['id'] for i in st['items']]) for st in old['stages']]
    assert before == after
    ids = {i for _s, items in after for i in items}
    assert 'i_track' not in ids, '없앤 항목이 저장본에 남았다'


def test_재편은_사장님이_고친_이름을_살린다():
    """이모지·이름을 바꿔둔 항목은 그대로 — 단 「템플릿」은 확정 개명(강제 개명 대상).

    [2026-08-12] 노션 「b-1. 가격 정책 → 옵션 맵핑 템플릿」 반영.
    """
    lay = {'version': 1, 'standalone': [], 'stages': [
        {'id': 's_sell', 'name': '판매', 'items': [
            {'id': 'i_orders', 'emoji': '🧾', 'name': '주문서', 'url': '/orders/?tab=list'},
            {'id': 'i_templates', 'emoji': '📄', 'name': '템플릿', 'url': '/templates'},
        ]},
    ]}
    SB._migrate_to_8groups(lay)
    flat = {i['id']: i for st in lay['stages'] for i in st['items']}
    assert flat['i_orders']['name'] == '주문서' and flat['i_orders']['emoji'] == '🧾'
    assert flat['i_templates']['name'] == '옵션 맵핑 템플릿'


def test_정산예정금액_메뉴는_주문분류에_한번만_추가된다():
    """[2026-08-06] i_settle_plan — 저장본 마이그레이션(idempotent). 🔴 스펙만 고치면
    라이브에 안 나오는 함정(_migrate_notion_report 선례)의 재발 방지 케이스."""
    lay = {'version': 1, 'standalone': [], 'stages': [
        {'id': 's_order', 'name': '주문 관리', 'items': [
            {'id': 'i_orders', 'name': '주문 내역', 'url': '/orders/?tab=list'}]},
    ]}
    assert SB._migrate_settle_plan(lay) is True
    ids = [i['id'] for i in lay['stages'][0]['items']]
    assert ids[-1] == 'i_settle_plan'
    assert SB._migrate_settle_plan(lay) is False, '두 번째 호출에서 또 바꿨다'


# ── [2026-08-12] 노션 「상품가공 > b-2. 기타 상위탭 아래로 옮기기」 ──────────────

def _옮기기_전_저장본() -> dict:
    """i_templates 가 아직 「상품 가공」에 있는 저장본 (라이브가 이 모양이다)."""
    return {'version': 1, 'standalone': [], 'stages': [
        {'id': 's_process', 'name': '상품 가공', 'items': [
            {'id': 'i_policies', 'name': '정책 생성', 'url': '/policies'},
            {'id': 'i_policy_apply', 'name': '상품 정책 적용', 'url': '/policies/apply'},
            {'id': 'i_templates', 'emoji': '💲', 'name': '가격 정책', 'url': '/templates'},
        ]},
        {'id': 's_etc', 'name': '기타', 'items': [
            {'id': 'i_trash', 'name': '휴지통·변경 이력', 'url': '/trash'},
        ]},
    ]}


def test_옵션맵핑템플릿이_기타로_옮겨진다():
    """🔴 스펙(_STAGE_SPEC)만 고치면 **안 옮겨진다** — 저장본에 이미 있는 항목은
    주입 로직이 「빠진 것」으로 안 잡기 때문. 저장본을 갈아끼우는지 확인한다."""
    lay = _옮기기_전_저장본()
    assert SB._migrate_templates_to_etc(lay) is True

    process = next(st for st in lay['stages'] if st['id'] == 's_process')
    etc = next(st for st in lay['stages'] if st['id'] == 's_etc')
    assert [i['id'] for i in process['items']] == ['i_policies', 'i_policy_apply'], \
        '상품 가공에 그대로 남았다'
    assert etc['items'][0]['id'] == 'i_templates', '기타 맨 앞에 안 왔다'


def test_옮기면서_새_이름으로_바뀐다():
    """i_templates 는 강제 개명 대상 — 저장본의 옛 이름이 이기면 안 된다."""
    lay = _옮기기_전_저장본()
    SB._migrate_templates_to_etc(lay)
    etc = next(st for st in lay['stages'] if st['id'] == 's_etc')
    moved = etc['items'][0]
    assert moved['name'] == '옵션 맵핑 템플릿', f"옛 이름이 남았다: {moved['name']}"
    assert moved['url'] == '/templates'


def test_옮기기는_두_번_해도_같다():
    """매 요청마다 저장을 유발하면 안 된다(idempotent).

    🔴 「이미 했나」 판정을 존재 여부로 하면 옮기기 전에도 True 라 **한 번도 안 돈다**.
       목적지(s_etc)에 있나로 판정해야 한다."""
    lay = _옮기기_전_저장본()
    assert SB._migrate_templates_to_etc(lay) is True
    before = [(st['id'], [i['id'] for i in st['items']]) for st in lay['stages']]
    assert SB._migrate_templates_to_etc(lay) is False, '두 번째 호출에서 또 바꿨다'
    after = [(st['id'], [i['id'] for i in st['items']]) for st in lay['stages']]
    assert before == after


def test_오른쪽_바로가기에_있어도_거두어_옮긴다():
    """사장님이 드래그로 standalone 에 빼 뒀을 수도 있다 — 거기서도 뽑아온다."""
    lay = {'version': 1,
           'standalone': [{'id': 'i_templates', 'name': '가격 정책', 'url': '/templates'}],
           'stages': [{'id': 's_etc', 'name': '기타', 'items': []}]}
    assert SB._migrate_templates_to_etc(lay) is True
    assert lay['standalone'] == [], '바로가기에 그대로 남았다'
    assert [i['id'] for i in lay['stages'][0]['items']] == ['i_templates']


def test_같은_메뉴가_두_번_생기지_않는다():
    """옮기기 뒤에도 id 는 유일해야 한다 — 중복이면 저장 검증(_validate)이 400 을 낸다."""
    lay = _옮기기_전_저장본()
    SB._migrate_templates_to_etc(lay)
    ids = [i['id'] for st in lay['stages'] for i in st['items']]
    ids += [i['id'] for i in lay['standalone']]
    assert len(ids) == len(set(ids)), f'겹친 메뉴가 있다: {ids}'


def test_정산예정금액_주문분류_없는_저장본은_바로가기로라도_노출():
    lay = {'version': 1, 'standalone': [], 'stages': []}
    assert SB._migrate_settle_plan(lay) is True
    assert lay['standalone'][-1]['id'] == 'i_settle_plan'

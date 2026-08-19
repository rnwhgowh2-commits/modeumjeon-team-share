# -*- coding: utf-8 -*-
"""옵션함 목록 표 — [2026-08-19 칼럼 재구성] 새 일곱 칸 + 오른쪽 판(축소판) 이 그려지는지.

정본은 사용자가 준 「옵션 매트릭스 패널 목록 칼럼 구성 변경」 체크리스트 4번 항목.

이 파일이 지키는 것
  ① 표 머리가 **일곱 칸**이다(고르기·「···」 자리는 값 칸이 아니다).
     번호·이름·브랜드·모델명을 한 칸(옵션 매트릭스)으로 묶고, 옵션축·소싱처를
     표로 올리면서 칸 수 자체는 예전(4안) 그대로 일곱이 됐다 — 우연이 아니라
     「일곱 칸이 한눈에」가 원래 확정이었고 이번엔 **무엇을 담을지만** 바뀐 것이다.
  ② 오른쪽 판은 **표에 없는 것만** 남는다(미완료 사유). 모델명·축 구성·소싱처는
     표로 옮겨졌으니 판에서 지웠다 — 같은 값을 두 곳에 다르게 보여주는 게 더
     헷갈린다는 사용자 확정(A안)에 따른 것이다.
  ③ 🔴 상태 이름·색은 `readiness.PHASE_LABEL`·`PHASE_CLS`·`PHASE_ICON` 에서만 온다.
     화면이 글자를 또 적으면 한쪽만 고쳤을 때 같은 옵션함이 화면마다 다른 이름이 된다.
  ④ 🔴 미완료 줄은 **왜 미완료인지**를 같이 말한다. 사유가 없으면 상태 표시가
     「안 됐다」고만 하고 손볼 곳을 안 알려 준다.
  ⑤ 🔴 소싱처 칸이 옛 「맵핑」(SKU↔소싱처 URL 연결 완료율)을 흡수했다 — 숫자
     칸에서는 안 보이고 호버 카드 첫 줄에서만 보인다(칸 자체를 두 번 두지 않는다).
  ⑥ 🔴 매트릭스가 없는 줄에 원본·파생을 **지어내지 않는다**(모른다 ≠ 아니다).

여기서 **안 보는 것** (다른 파일이 이미 본다 — 같은 사실을 두 곳에 안 적는다)
  · 「미구성」 딱지·「상품 생성에 사용됨」 글자가 없는지 → `test_optgen_direct_panel.py`
  · SKU 연결상태·소싱처 호버 카드의 실제 내용 → `test_optgen_direct_detail_card.py`
  · 「···」 메뉴가 안 잘리는지 · 가로 스크롤 규격 → `tests/design/test_optgen_menu_not_clipped.py`
  · 라이브 분량에서 문서가 가로로 구르는지 → `tests/design/test_optgen_4an_width.py`
    (그건 글자를 세서는 못 잡는다 — 진짜 브라우저로 재야 한다)
"""
import uuid

import pytest
from bs4 import BeautifulSoup

# 표본 심는 도구는 형제 시험 것을 그대로 쓴다 — 두 벌이 되면 언젠가 갈린다.
from tests.catalog.test_optgen_direct_panel import (  # noqa: F401
    _글자만, _옵션함, _지우기, _화면코드, client,
)


# ═══════════════════════════════════════════════════════════════════════════
#  표본 — 화면이 갈라지는 다섯 갈래를 모두 심는다
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def 표본():
    """준비완료 · 맵핑 덜 됨 · 주소 없음 · 모델 모음전 · 매트릭스 없는 줄."""
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:8].upper()
    코드 = {
        '준비완료': f'U-4RDY{tag}',
        '덜맵핑': f'U-4MAP{tag}',
        '주소없음': f'U-4URL{tag}',
        '모델함': f'U-4MDL{tag}',
        '매트릭스없음': f'U-4NOM{tag}',
    }
    s = SessionLocal()
    try:
        축둘 = [('색상', ['블랙', '화이트']), ('사이즈', ['250'])]
        옵션둘 = [('블랙', '250'), ('화이트', '250')]
        _옵션함(s, 코드['준비완료'], f'다갖춘함{tag}', 옵션=옵션둘, 축=축둘,
               주소=1, 다이음=True, 번호=f'U-NO-RDY{tag}')
        _옵션함(s, 코드['덜맵핑'], f'맵핑덜된함{tag}', 옵션=옵션둘, 축=축둘,
               주소=1, 다이음=False, 번호=f'U-NO-MAP{tag}')
        _옵션함(s, 코드['주소없음'], f'주소없는함{tag}', 옵션=옵션둘, 축=축둘,
               주소=0, 번호=f'U-NO-URL{tag}')
        _옵션함(s, 코드['모델함'], f'모델모음함{tag}', 옵션=옵션둘,
               축=[('모델', ['메이트', '스위트']), ('색상', ['블랙'])],
               주소=1, 다이음=True, 번호=f'U-NO-MDL{tag}')
        # 🔴 매트릭스를 **안 만든** 줄 — 재고관리로 들어온 물건이 이 꼴이다.
        #    `_옵션함` 은 늘 매트릭스를 만들므로 이 줄만 손으로 심는다.
        s.add(Model(model_code=코드['매트릭스없음'], model_name_raw=f'매트릭스없는함{tag}',
                    model_name_display=f'매트릭스없는함{tag}', brand='르무통',
                    is_option_box=True))
        s.add(Option(canonical_sku=f'SKU-{코드["매트릭스없음"]}-0',
                     model_code=코드['매트릭스없음'], color_code='블랙', size_code='250'))
        s.commit()
        yield {'tag': tag, '코드': 코드,
               '이름': {k: (f'다갖춘함{tag}' if k == '준비완료' else
                           f'맵핑덜된함{tag}' if k == '덜맵핑' else
                           f'주소없는함{tag}' if k == '주소없음' else
                           f'모델모음함{tag}' if k == '모델함' else
                           f'매트릭스없는함{tag}') for k in 코드}}
    finally:
        _지우기(s, list(코드.values()))
        s.close()


def _수프(client, 주소='/optgen/?tab=direct'):
    return BeautifulSoup(client.get(주소).get_data(as_text=True), 'html.parser')


def _표(수프):
    표 = 수프.select_one('table.og-tb4')
    assert 표 is not None, '4안 표(.og-tb4)가 화면에 없다'
    return 표


def _줄(수프, code):
    줄 = 수프.select_one(f'tr.og-row[data-href$="/optgen/box/{code}"]')
    assert 줄 is not None, f'심은 표본 줄이 화면에 없다 — 시험이 헛돈다: {code}'
    return 줄


def _판(수프, code):
    판 = 수프.select_one(f'#og-side-bank .og-sd[data-code="{code}"]')
    assert 판 is not None, f'그 줄의 판 내용이 화면에 없다: {code}'
    return 판


# 칸 순서(고정) — pick·NO·옵션매트릭스·모음전구성·옵션축·SKU연결상태·소싱처·상태·actions.
# 이 화면 시험 전부가 이 자리를 쓰므로 **여기 한 곳만** 고치면 되게 모아 둔다.
_매트릭스칸, _구성칸, _축칸, _SKU칸, _소싱처칸, _상태칸_i = 2, 3, 4, 5, 6, -2


def _상태칸(수프, code):
    return _줄(수프, code).select('td')[_상태칸_i]


# ═══════════════════════════════════════════════════════════════════════════
#  ① 일곱 칸
# ═══════════════════════════════════════════════════════════════════════════

def test_표_머리가_일곱_칸이다(client, 표본):
    """🔴 [2026-08-19] 번호·이름·브랜드·모델명을 한 칸으로 묶고 옵션축·소싱처를
    표로 올렸다 — 칸을 합친 만큼 늘어, 다시 **일곱 칸**(예전 4안과 같은 수)이다."""
    머리 = [th.get_text(strip=True) for th in _표(_수프(client)).select('thead th')]
    # 맨 앞(고르기)과 맨 뒤(ⓘ·「···」)는 값 칸이 아니라 빈 머리다.
    assert 머리[0] == '' and 머리[-1] == '', f'앞뒤 조작 칸이 사라졌다: {머리}'
    assert 머리[1:-1] == ['NO', '옵션 매트릭스', '모음전 구성', '옵션축',
                          'SKU 연결상태', '소싱처', '상태'], 머리


def test_모든_줄의_칸_수가_머리와_같다(client, 표본):
    """칸 수가 어긋나면 값이 옆 칸으로 밀려 **다른 뜻**으로 읽힌다."""
    표 = _표(_수프(client))
    칸수 = len(표.select('thead th'))
    줄들 = 표.select('tbody tr.og-row')
    assert len(줄들) >= 4, f'표본이 화면에 없다 — 시험이 헛돈다({len(줄들)}줄)'
    for tr in 줄들:
        assert len(tr.find_all('td', recursive=False)) == 칸수, (
            f'칸 수가 머리({칸수})와 다르다: {tr.get("data-name")}')


def test_NO_는_보이는_순서대로_매겨진다(client, 표본):
    """🔴 매트릭스 번호(U…)와는 다른 것 — 지금 화면에서 몇 번째 줄인지일 뿐이다."""
    줄들 = _표(_수프(client)).select('tbody tr.og-row')
    보인번호 = [int(tr.select('td')[1].get_text(strip=True)) for tr in 줄들]
    assert 보인번호 == list(range(1, len(줄들) + 1)), f'NO 가 1부터 순서대로가 아니다: {보인번호}'


# ═══════════════════════════════════════════════════════════════════════════
#  ② 오른쪽 판 — 표로 옮긴 값은 뺀다(A안)
# ═══════════════════════════════════════════════════════════════════════════

def test_오른쪽_판이_있다(client, 표본):
    수프 = _수프(client)
    assert 수프.select_one('#og-side') is not None, '오른쪽 판이 없다'
    본문 = 수프.select_one('#og-side-b')
    assert 본문 is not None and 'ⓘ' in 본문.get_text(), (
        '판을 어떻게 여는지 화면이 안 알려 준다')


def test_미완료_사유는_판에_그대로_있다(client, 표본):
    """🔴 [2026-08-19 A안] 표로 옮긴 값(모델명·축 구성·소싱처)은 판에서 뺐지만,
    표에 자리가 없는 미완료 사유는 그대로 판에 남아야 한다."""
    수프 = _수프(client)
    글 = _판(수프, 표본['코드']['주소없음']).get_text(' ', strip=True)
    assert '소싱처 URL 없음' in 글, f'미완료 사유가 판에서 사라졌다: {글}'
    # 판을 여는 단추가 그 줄에 실제로 있어야 한다 — 값만 있고 여는 길이 없으면 헛것이다.
    단추 = _줄(수프, 표본['코드']['모델함']).select_one('.og-i')
    assert 단추 is not None and 단추['data-code'] == 표본['코드']['모델함']


def test_판을_여는_배선이_화면에_있다(client, 표본):
    """🔴 값이 실려 있어도 **옮겨 붙이는 코드**가 없으면 판은 영영 안 뜬다.

    글자만 세는 검사는 그 조용한 실패를 못 잡는다 — 배선의 세 마디를 같이 본다.
    """
    본문 = client.get('/optgen/?tab=direct').get_data(as_text=True)
    코드 = '\n'.join(l for l in 본문.splitlines() if not l.lstrip().startswith('//'))
    assert "querySelectorAll('.og-i')" in 코드, 'ⓘ 단추에 아무것도 안 걸었다'
    assert 'og곳간[code]' in 코드, '판에 넣을 값을 곳간에서 안 꺼낸다'
    assert 'e.stopPropagation()' in 코드, (
        'ⓘ 가 줄 클릭까지 같이 일으킨다 — 판을 열려다 다음 화면으로 넘어간다')
    assert ".og-more, .og-menu, .og-pick, .og-i" in 코드, (
        '줄 클릭에서 ⓘ 를 안 뺐다 — 판을 열려다 다음 화면으로 넘어간다')


def test_모델명_축구성_소싱처는_판에서_빠지고_표에만_있다(client, 표본):
    """🔴 [2026-08-19 A안] 같은 값을 두 곳에 그리면 한쪽만 고쳐졌을 때 화면이
    서로 다른 말을 한다 — 표로 옮긴 값은 판에서 지웠다."""
    수프 = _수프(client)
    판글 = _판(수프, 표본['코드']['모델함']).get_text(' ', strip=True)
    assert '메이트' not in 판글, f'모델명이 판에 남아 있다(표와 중복): {판글}'
    assert '모델 × 색상' not in 판글, f'축 구성이 판에 남아 있다(표와 중복): {판글}'

    표줄 = _줄(수프, 표본['코드']['모델함'])
    assert '메이트' in 표줄.select('td')[_매트릭스칸].get_text(' ', strip=True), (
        '모델명이 표(옵션 매트릭스 칸)에 없다')
    assert '모델' in 표줄.select('td')[_축칸].get_text(' ', strip=True), (
        '축 구성이 표(옵션축 칸)에 없다')


# ═══════════════════════════════════════════════════════════════════════════
#  ③ 상태 — 이름·색의 원천은 하나
# ═══════════════════════════════════════════════════════════════════════════

def test_상태_이름과_색이_readiness_에서만_온다(client, 표본):
    """🔴 [2026-08-19 디자인 통일] 딱지(`.og-badge`)가 아니라 `.ds-st`(아이콘+색 글자)다."""
    from lemouton.matrix.readiness import (PHASE_CLS, PHASE_LABEL, PHASE_DRAFT,
                                           PHASE_READY)
    수프 = _수프(client)
    본 = {'준비완료': PHASE_READY, '주소없음': PHASE_DRAFT}
    for 열쇠, 위상 in 본.items():
        배지 = _상태칸(수프, 표본['코드'][열쇠]).select_one('.ds-st')
        assert 배지 is not None, f'{열쇠} 줄에 상태 표시가 없다'
        assert 배지.get_text(strip=True) == PHASE_LABEL[위상], (
            f'{열쇠} 상태 글자가 정본과 다르다: {배지.get_text(strip=True)}')
        assert f'ds-st--{PHASE_CLS[위상]}' in 배지['class'], (
            f'{열쇠} 상태 색이 정본과 다르다: {배지["class"]}')
    # 🔴 화면이 그 글자를 **또 적어 두지** 않았는지 — 그리는 코드에서 확인한다.
    #    주석은 걷어낸다(`_화면코드`). 안 그러면 「이 글자를 여기 적으면 안 된다」고
    #    적어 둔 설명 자체에 걸려 없는 결함에 빨간불이 뜬다 — 실제로 한 번 걸렸다.
    코드 = _화면코드('webapp/templates/optgen/index.html')
    for 라벨 in PHASE_LABEL.values():
        assert 라벨 not in 코드, f'화면이 상태 이름을 또 적어 뒀다: {라벨}'


# ═══════════════════════════════════════════════════════════════════════════
#  ④ 미완료 사유
# ═══════════════════════════════════════════════════════════════════════════

def test_미완료_줄은_왜_미완료인지_말한다(client, 표본):
    """🔴 사유가 없으면 상태 표시가 손볼 곳을 안 알려 준다 — 그것만으로는 쓸모가 없다."""
    수프 = _수프(client)
    code = 표본['코드']['주소없음']
    배지 = _상태칸(수프, code).select_one('.ds-st')
    assert '소싱처 URL 없음' in (배지.get('title') or ''), (
        f'상태 표시가 사유를 안 알려 준다: {배지.get("title")!r}')
    # 마우스를 안 올려도 보이도록 판에도 글자로 남는다.
    판글 = _판(수프, code).get_text(' ', strip=True)
    assert '소싱처 URL 없음' in 판글, f'판에 미완료 사유가 없다: {판글}'


def test_다_갖춘_줄에는_사유를_안_붙인다(client, 표본):
    """할 일이 없는 줄에 「아직 안 된 것」이 붙으면 없는 일감을 만든다."""
    수프 = _수프(client)
    code = 표본['코드']['준비완료']
    assert not _상태칸(수프, code).select_one('.ds-st').get('title')
    assert '아직 안 된 것' not in _판(수프, code).get_text(' ', strip=True)


# ═══════════════════════════════════════════════════════════════════════════
#  ⑤ 소싱처 — 옛 「맵핑」을 흡수. 숫자는 곳 수, 판정 불가는 「—」
# ═══════════════════════════════════════════════════════════════════════════

def test_소싱처_칸은_곳_수와_주소_수를_보여준다(client, 표본):
    수프 = _수프(client)
    칸 = _줄(수프, 표본['코드']['준비완료']).select('td')[_소싱처칸]
    호버 = 칸.select_one('.ub4-hov')
    assert 호버 is not None, '소싱처 호버 트리거가 없다'
    assert '1곳' in 호버.get_text(strip=True) and '1개' in 호버.get_text(strip=True)
    # 옛 맵핑(SKU↔소싱처 연결 완료율)은 이 칸의 자료 속성으로 흡수돼 있다 —
    # 숫자 칸엔 안 보이고 호버(별도 시험)에서만 보인다.
    assert 호버['data-map-skus-done'] == '2' and 호버['data-map-skus'] == '2'


def test_판정_불가는_대시로_적고_0으로_안_적는다(client, 표본):
    """🔴 주소가 0개면 「이었나」는 **모른다**다. 0/2 로 적으면 「안 이었다」로 단정하는 것이다."""
    칸 = _줄(_수프(client), 표본['코드']['주소없음']).select('td')[_소싱처칸]
    assert 칸.get_text(strip=True) == '—', f'모르는 것을 숫자로 적었다: {칸}'
    assert '판정할 수 없습니다' in (칸.select_one('.og-dash').get('title') or ''), (
        '왜 못 재는지 안 알려 준다')


# ═══════════════════════════════════════════════════════════════════════════
#  ⑥ 옵션 매트릭스 칸 — 번호·갈래는 없는 사실을 지어내지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_옵션매트릭스_칸에_번호와_갈래가_있다(client, 표본):
    칸 = _줄(_수프(client), 표본['코드']['준비완료']).select('td')[_매트릭스칸]
    assert f'U-NO-RDY{표본["tag"]}' in 칸.get_text(' ', strip=True)
    assert 칸.select_one('.og-kind').get_text(strip=True) == '원본'


def test_매트릭스가_없으면_원본_파생을_안_지어낸다(client, 표본):
    """🔴 「원본이 아니다 = 파생」으로 뭉개면 화면이 없는 사실을 말한다."""
    수프 = _수프(client)
    칸 = _줄(수프, 표본['코드']['매트릭스없음']).select('td')[_매트릭스칸]
    assert 칸.select_one('.og-kind') is None, f'없는 갈래를 지어냈다: {칸}'
    # 대신 창고 번호라도 보여 주고, 왜 다른지 말한다 — 빈칸으로 두지 않는다.
    assert 칸.get_text(strip=True), '번호 칸이 통째로 비었다'
    assert '매트릭스 번호가 없습니다' in str(칸)


# ═══════════════════════════════════════════════════════════════════════════
#  모음전 구성 · 옵션축 · SKU 연결상태
# ═══════════════════════════════════════════════════════════════════════════

def test_모음전_구성과_SKU_연결상태가_칸에_있다(client, 표본):
    수프 = _수프(client)
    준비 = _줄(수프, 표본['코드']['준비완료']).select('td')
    assert 준비[_구성칸].get_text(strip=True) == '색상 모음전'
    assert '2' in 준비[_SKU칸].get_text(strip=True)
    모델 = _줄(수프, 표본['코드']['모델함']).select('td')
    assert 모델[_구성칸].get_text(strip=True) == '모델 모음전'


def test_안_정한_모음전_구성은_대시로_적는다(client, 표본):
    """축이 없어 종류를 못 정한 줄 — 빈칸으로 두면 「없다」인지 「못 봤다」인지 모른다."""
    칸 = _줄(_수프(client), 표본['코드']['매트릭스없음']).select('td')[_구성칸]
    assert 칸.get_text(strip=True) == '—'
    assert '안 정했습니다' in str(칸)


def test_옵션축_칸에_축_이름과_값_개수가_있다(client, 표본):
    """🔴 [2026-08-19] 「모델 2개 × 색상 1개」처럼 축마다 값 개수가 같이 보여야 한다."""
    칸 = _줄(_수프(client), 표본['코드']['모델함']).select('td')[_축칸]
    글 = 칸.get_text(strip=True)
    assert '모델 2개' in 글 and '색상 1개' in 글, f'축별 개수가 안 보인다: {글}'


def test_축이_없으면_옵션축_칸도_대시다(client, 표본):
    칸 = _줄(_수프(client), 표본['코드']['매트릭스없음']).select('td')[_축칸]
    assert 칸.get_text(strip=True) == '—'

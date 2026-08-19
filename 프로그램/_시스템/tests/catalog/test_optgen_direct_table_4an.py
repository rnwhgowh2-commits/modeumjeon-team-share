# -*- coding: utf-8 -*-
"""옵션함 목록 표 — 사장님 확정 **4안**(일곱 칸 + 오른쪽 판) 이 화면에 그려지는지.

정본은 시안 `_시안_임시/optgen_direct_배치_5안.html` 의 5번째 탭이다.

이 파일이 지키는 것
  ① 표 머리가 **일곱 칸**이다(고르기·「···」 자리는 값 칸이 아니다).
     칸이 슬그머니 늘거나 줄면 사장님이 고르신 배치가 아닌 게 된다.
  ② 오른쪽 판이 있고, **줄마다 그 줄 값이 실려 있다.**
     판이 비면 표에서 뺀 값(모델명·축 구성·소싱처·미완료 사유)을 볼 곳이 사라진다.
  ③ 🔴 상태 이름·색은 `readiness.PHASE_LABEL`·`PHASE_CLS` 에서만 온다.
     화면이 글자를 또 적으면 한쪽만 고쳤을 때 같은 옵션함이 화면마다 다른 이름이 된다.
  ④ 🔴 미완료 줄은 **왜 미완료인지**를 같이 말한다. 사유가 없으면 배지가
     「안 됐다」고만 하고 손볼 곳을 안 알려 준다.
  ⑤ 🔴 맵핑은 분수로, **판정 불가는 「—」**. 0/0 을 완료로도 미완료로도 안 쓴다.
  ⑥ 🔴 매트릭스가 없는 줄에 원본·파생을 **지어내지 않는다**(모른다 ≠ 아니다).

여기서 **안 보는 것** (다른 파일이 이미 본다 — 같은 사실을 두 곳에 안 적는다)
  · 「미구성」 딱지·「상품 생성에 사용됨」 글자가 없는지 → `test_optgen_direct_panel.py`
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


# ═══════════════════════════════════════════════════════════════════════════
#  ① 일곱 칸
# ═══════════════════════════════════════════════════════════════════════════

def test_표_머리가_여덟_칸이다(client, 표본):
    """🔴 [2026-08-19] 「SKU 정보 상태」 열이 늘어 **여덟 칸**이 됐다 — 늘거나 줄면 다른 배치가 된다."""
    머리 = [th.get_text(strip=True) for th in _표(_수프(client)).select('thead th')]
    # 맨 앞(고르기)과 맨 뒤(ⓘ·「···」)는 값 칸이 아니라 빈 머리다.
    assert 머리[0] == '' and 머리[-1] == '', f'앞뒤 조작 칸이 사라졌다: {머리}'
    assert 머리[1:-1] == ['옵션 매트릭스 번호', '옵션 매트릭스 이름', '브랜드',
                          '모음전 구성', 'SKU 구성수', '맵핑', '상태',
                          'SKU 정보 상태'], 머리


def test_모든_줄의_칸_수가_머리와_같다(client, 표본):
    """칸 수가 어긋나면 값이 옆 칸으로 밀려 **다른 뜻**으로 읽힌다."""
    표 = _표(_수프(client))
    칸수 = len(표.select('thead th'))
    줄들 = 표.select('tbody tr.og-row')
    assert len(줄들) >= 4, f'표본이 화면에 없다 — 시험이 헛돈다({len(줄들)}줄)'
    for tr in 줄들:
        assert len(tr.find_all('td', recursive=False)) == 칸수, (
            f'칸 수가 머리({칸수})와 다르다: {tr.get("data-name")}')


# ═══════════════════════════════════════════════════════════════════════════
#  ② 오른쪽 판
# ═══════════════════════════════════════════════════════════════════════════

def test_오른쪽_판이_있다(client, 표본):
    수프 = _수프(client)
    assert 수프.select_one('#og-side') is not None, '오른쪽 판이 없다'
    본문 = 수프.select_one('#og-side-b')
    assert 본문 is not None and 'ⓘ' in 본문.get_text(), (
        '판을 어떻게 여는지 화면이 안 알려 준다')


def test_줄을_고르면_판에_뜰_값이_줄마다_실려_있다(client, 표본):
    """🔴 표에서 뺀 값 넷(모델명·축 구성·소싱처와 주소 수·미완료 사유)이 판에 있어야 한다.

    없으면 「표를 줄였다」가 아니라 **값을 잃었다**가 된다.
    """
    수프 = _수프(client)
    글 = _판(수프, 표본['코드']['모델함']).get_text(' ', strip=True)
    assert '메이트 · 스위트' in 글, f'모델명이 판에 없다: {글}'
    assert '모델 × 색상' in 글, f'축 구성이 판에 없다: {글}'
    assert '주소 1개' in 글 and '주소 모두 1개' in 글, f'소싱처·주소 수가 판에 없다: {글}'
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


def test_판에_들어가는_값은_표에_다시_안_적는다(client, 표본):
    """같은 값을 두 곳에 그리면 한쪽만 고쳐졌을 때 화면이 서로 다른 말을 한다."""
    줄 = _줄(_수프(client), 표본['코드']['모델함']).get_text(' ', strip=True)
    assert '메이트' not in 줄, f'모델명이 표에도 적혀 있다: {줄}'
    assert '모델 × 색상' not in 줄, f'축 구성이 표에도 적혀 있다: {줄}'


# ═══════════════════════════════════════════════════════════════════════════
#  ③ 상태 — 이름·색의 원천은 하나
# ═══════════════════════════════════════════════════════════════════════════

def _상태칸(수프, code):
    """🔴 [2026-08-19] 「SKU 정보 상태」 열이 뒤에 늘어 상태 칸은 이제 `[-3]`이다.

    또 열이 느는 날 이 함수 한 곳만 고치면 되게, 자리를 여기 한 곳에 모아 둔다
    (`_맵핑칸`과 같은 이유).
    """
    return _줄(수프, code).select('td')[-3]


def test_상태_이름과_색이_readiness_에서만_온다(client, 표본):
    from lemouton.matrix.readiness import (PHASE_CLS, PHASE_LABEL, PHASE_DRAFT,
                                           PHASE_READY)
    수프 = _수프(client)
    본 = {'준비완료': PHASE_READY, '주소없음': PHASE_DRAFT}
    for 열쇠, 위상 in 본.items():
        배지 = _상태칸(수프, 표본['코드'][열쇠]).select_one('.og-badge')
        assert 배지 is not None, f'{열쇠} 줄에 상태 배지가 없다'
        assert 배지.get_text(strip=True) == PHASE_LABEL[위상], (
            f'{열쇠} 상태 글자가 정본과 다르다: {배지.get_text(strip=True)}')
        assert PHASE_CLS[위상] in 배지['class'], (
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
    """🔴 사유가 없으면 배지가 손볼 곳을 안 알려 준다 — 배지만으로는 쓸모가 없다."""
    수프 = _수프(client)
    code = 표본['코드']['주소없음']
    배지 = _상태칸(수프, code).select_one('.og-badge')
    assert '소싱처 URL 없음' in (배지.get('title') or ''), (
        f'상태 배지가 사유를 안 알려 준다: {배지.get("title")!r}')
    # 마우스를 안 올려도 보이도록 판에도 글자로 남는다.
    판글 = _판(수프, code).get_text(' ', strip=True)
    assert '소싱처 URL 없음' in 판글, f'판에 미완료 사유가 없다: {판글}'


def test_다_갖춘_줄에는_사유를_안_붙인다(client, 표본):
    """할 일이 없는 줄에 「아직 안 된 것」이 붙으면 없는 일감을 만든다."""
    수프 = _수프(client)
    code = 표본['코드']['준비완료']
    assert not _상태칸(수프, code).select_one('.og-badge').get('title')
    assert '아직 안 된 것' not in _판(수프, code).get_text(' ', strip=True)


# ═══════════════════════════════════════════════════════════════════════════
#  ⑤ 맵핑 — 분수 · 판정 불가는 「—」
# ═══════════════════════════════════════════════════════════════════════════

def _맵핑칸(수프, code):
    # 🔴 [2026-08-19] 「SKU 정보 상태」 열이 뒤에 늘어 맵핑 칸은 이제 `[-4]`이다.
    return _줄(수프, code).select('td')[-4]


def test_맵핑은_분수로_보인다(client, 표본):
    수프 = _수프(client)
    assert _맵핑칸(수프, 표본['코드']['준비완료']).get_text(strip=True) == '2/2'
    assert _맵핑칸(수프, 표본['코드']['덜맵핑']).get_text(strip=True) == '0/2'


def test_판정_불가는_대시로_적고_0으로_안_적는다(client, 표본):
    """🔴 주소가 0개면 「이었나」는 **모른다**다. 0/2 로 적으면 「안 이었다」로 단정하는 것이다."""
    칸 = _맵핑칸(_수프(client), 표본['코드']['주소없음'])
    assert 칸.get_text(strip=True) == '—', f'모르는 것을 숫자로 적었다: {칸}'
    assert '판정할 수 없습니다' in (칸.select_one('.og-dash').get('title') or ''), (
        '왜 못 재는지 안 알려 준다')


# ═══════════════════════════════════════════════════════════════════════════
#  ⑥ 번호·갈래 — 없는 사실을 지어내지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_번호는_매트릭스_번호를_보여_준다(client, 표본):
    칸 = _줄(_수프(client), 표본['코드']['준비완료']).select('td')[1]
    assert f'U-NO-RDY{표본["tag"]}' in 칸.get_text(' ', strip=True)
    assert 칸.select_one('.og-kind').get_text(strip=True) == '원본'


def test_매트릭스가_없으면_원본_파생을_안_지어낸다(client, 표본):
    """🔴 「원본이 아니다 = 파생」으로 뭉개면 화면이 없는 사실을 말한다."""
    수프 = _수프(client)
    칸 = _줄(수프, 표본['코드']['매트릭스없음']).select('td')[1]
    assert 칸.select_one('.og-kind') is None, f'없는 갈래를 지어냈다: {칸}'
    # 대신 창고 번호라도 보여 주고, 왜 다른지 말한다 — 빈칸으로 두지 않는다.
    assert 칸.get_text(strip=True), '번호 칸이 통째로 비었다'
    assert '매트릭스 번호가 없습니다' in str(칸)


# ═══════════════════════════════════════════════════════════════════════════
#  모음전 구성 · SKU 구성수
# ═══════════════════════════════════════════════════════════════════════════

def test_모음전_구성과_SKU_수가_칸에_있다(client, 표본):
    수프 = _수프(client)
    준비 = _줄(수프, 표본['코드']['준비완료']).select('td')
    assert 준비[4].get_text(strip=True) == '색상 모음전'
    assert 준비[5].get_text(strip=True) == '2개'
    모델 = _줄(수프, 표본['코드']['모델함']).select('td')
    assert 모델[4].get_text(strip=True) == '모델 모음전'


def test_안_정한_모음전_구성은_대시로_적는다(client, 표본):
    """축이 없어 종류를 못 정한 줄 — 빈칸으로 두면 「없다」인지 「못 봤다」인지 모른다."""
    칸 = _줄(_수프(client), 표본['코드']['매트릭스없음']).select('td')[4]
    assert 칸.get_text(strip=True) == '—'
    assert '안 정했습니다' in str(칸)

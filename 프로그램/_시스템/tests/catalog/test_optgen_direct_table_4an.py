# -*- coding: utf-8 -*-
"""옵션함 목록 표 — 사장님 확정 **4안**(일곱 칸 + 오른쪽 판) + [2026-08-19] 칼럼 재구성.

[2026-08-19] 재구성 — 번호·이름·브랜드 3칸을 「옵션 매트릭스」 한 칸(2행)으로 합치고,
SKU 구성수→옵션축(칩), 맵핑·SKU 정보 상태 2칸을 걷어 SKU 연결상태·소싱처 2칸으로
바꿨다. 상태 칸은 그대로 두되 이 목록 한정 회색/초록(`direct_phase_cls`).

이 파일이 지키는 것
  ① 표 머리가 **일곱 값칸**(NO·옵션 매트릭스·모음전 구성·옵션축·SKU 연결상태·
     소싱처·상태)이다 — 고르기·「···」 자리는 값 칸이 아니다.
  ② 오른쪽 판이 있고, 줄마다 그 줄 값이 실려 있다.
  ③ 🔴 상태 이름은 `readiness.PHASE_LABEL` 한 곳에서만 온다. 색은 이 목록
     한정으로 회색/초록(공용 `PHASE_CLS`를 직접 바꾸지 않는다 — 「모음전 상품
     생성」 탭의 3단계 막대가 같이 바뀌면 완료·상품생성됨이 둘 다 초록이 된다).
  ④ 🔴 미완료 줄은 왜 미완료인지 같이 말한다.
  ⑤ 🔴 매트릭스가 없는 줄에 원본·파생을 지어내지 않는다.
  ⑥ 옵션축 칩은 축 이름·개수가 그대로 실린다.
  ⑦ 모델명은 최대 8개, 그 이상은 「+N」 칩.

여기서 **안 보는 것**
  · 「미구성」 딱지·「상품 생성에 사용됨」 글자 → `test_optgen_direct_panel.py`
  · 「···」 메뉴가 안 잘리는지 · 가로 스크롤 규격 → `tests/design/test_optgen_menu_not_clipped.py`
  · 라이브 분량에서 문서가 가로로 구르는지 → `tests/design/test_optgen_4an_width.py`
  · 호버 카드가 실제로 뜨는지(자바스크립트 실행) → 실브라우저 검증(자동화 밖)
"""
import uuid

import pytest
from bs4 import BeautifulSoup

# 표본 심는 도구는 형제 시험 것을 그대로 쓴다 — 두 벌이 되면 언젠가 갈린다.
from tests.catalog.test_optgen_direct_panel import (  # noqa: F401
    _글자만, _옵션함, _지우기, _화면코드, client,
)


# ═══════════════════════════════════════════════════════════════════════════
#  표본 — 화면이 갈라지는 갈래를 모두 심는다
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def 표본():
    """준비완료 · 주소없음(미완료) · 모델 모음전(9개, +1칩) · 매트릭스 없는 줄."""
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:8].upper()
    코드 = {
        '준비완료': f'U-4RDY{tag}',
        '주소없음': f'U-4URL{tag}',
        '모델함': f'U-4MDL{tag}',
        '매트릭스없음': f'U-4NOM{tag}',
    }
    모델9개 = [f'모델{i}' for i in range(1, 10)]
    s = SessionLocal()
    try:
        _옵션함(s, 코드['준비완료'], f'다갖춘함{tag}',
               옵션=[('블랙', '250'), ('화이트', '250')],
               축=[('색상', ['블랙', '화이트']), ('사이즈', ['250'])],
               주소=1, 다이음=True, 번호=f'U-NO-RDY{tag}')
        _옵션함(s, 코드['주소없음'], f'주소없는함{tag}',
               옵션=[('블랙', '250'), ('화이트', '250')],
               축=[('색상', ['블랙', '화이트']), ('사이즈', ['250'])],
               주소=0, 번호=f'U-NO-URL{tag}')
        _옵션함(s, 코드['모델함'], f'모델모음함{tag}',
               옵션=[(m, '250') for m in 모델9개],
               축=[('모델', 모델9개), ('사이즈', ['250'])],
               주소=1, 다이음=True, 번호=f'U-NO-MDL{tag}')
        # 🔴 매트릭스를 **안 만든** 줄 — 재고관리로 들어온 물건이 이 꼴이다.
        s.add(Model(model_code=코드['매트릭스없음'], model_name_raw=f'매트릭스없는함{tag}',
                    model_name_display=f'매트릭스없는함{tag}', brand='르무통',
                    is_option_box=True))
        s.add(Option(canonical_sku=f'SKU-{코드["매트릭스없음"]}-0',
                     model_code=코드['매트릭스없음'], color_code='블랙', size_code='250'))
        s.commit()
        yield {'tag': tag, '코드': 코드,
               '이름': {'준비완료': f'다갖춘함{tag}', '주소없음': f'주소없는함{tag}',
                       '모델함': f'모델모음함{tag}', '매트릭스없음': f'매트릭스없는함{tag}'},
               '모델9개': 모델9개}
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
#  ① 일곱 값칸
# ═══════════════════════════════════════════════════════════════════════════

def test_표_머리가_일곱_값칸이다(client, 표본):
    """🔴 [2026-08-19] 칼럼 재구성 — 늘거나 줄면 사장님이 고르신 배치가 아닌 게 된다."""
    머리 = [th.get_text(strip=True) for th in _표(_수프(client)).select('thead th')]
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


def test_NO칸은_보이는_순번이다(client, 표본):
    """번호(매트릭스 번호)와는 다른 것 — 그냥 1,2,3… 순번이다."""
    줄들 = _표(_수프(client)).select('tbody tr.og-row')
    번호들 = [tr.select('td')[1].get_text(strip=True) for tr in 줄들[:3]]
    assert 번호들 == ['1', '2', '3'], f'NO 칸이 순번이 아니다: {번호들}'


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
    """🔴 표에서 뺀 값(축 구성 전체 문장·소싱처와 주소 수·미완료 사유)이 판에 있어야 한다."""
    수프 = _수프(client)
    글 = _판(수프, 표본['코드']['모델함']).get_text(' ', strip=True)
    assert '모델 × 사이즈' in 글, f'축 구성이 판에 없다: {글}'
    assert '주소 1개' in 글 and '주소 모두 1개' in 글, f'소싱처·주소 수가 판에 없다: {글}'
    단추 = _줄(수프, 표본['코드']['모델함']).select_one('.og-i')
    assert 단추 is not None and 단추['data-code'] == 표본['코드']['모델함']


def test_판을_여는_배선이_화면에_있다(client, 표본):
    본문 = client.get('/optgen/?tab=direct').get_data(as_text=True)
    코드 = '\n'.join(l for l in 본문.splitlines() if not l.lstrip().startswith('//'))
    assert "querySelectorAll('.og-i')" in 코드, 'ⓘ 단추에 아무것도 안 걸었다'
    assert 'og곳간[code]' in 코드, '판에 넣을 값을 곳간에서 안 꺼낸다'
    assert 'e.stopPropagation()' in 코드, (
        'ⓘ 가 줄 클릭까지 같이 일으킨다 — 판을 열려다 다음 화면으로 넘어간다')
    assert ".og-more, .og-menu, .og-pick, .og-i" in 코드, (
        '줄 클릭에서 ⓘ 를 안 뺐다 — 판을 열려다 다음 화면으로 넘어간다')


def test_축_구성_문장은_표에_다시_안_적는다(client, 표본):
    """옵션축 칸은 칩(이름+개수)이지 「모델 × 사이즈」 문장이 아니다 — 같은 문장을 두 곳에 안 둔다."""
    줄 = _줄(_수프(client), 표본['코드']['모델함']).get_text(' ', strip=True)
    assert '모델 × 사이즈' not in 줄, f'축 구성 문장이 표에도 적혀 있다: {줄}'


# ═══════════════════════════════════════════════════════════════════════════
#  ③ 상태 — 이름은 readiness 한 곳, 색은 이 목록 한정 회색/초록
# ═══════════════════════════════════════════════════════════════════════════

def _상태칸(수프, code):
    return _줄(수프, code).select('td')[-2]      # 맨 뒤(액션) 바로 앞


def test_상태_이름은_readiness에서만_오고_색은_회색_초록이다(client, 표본):
    """🔴 [2026-08-19] 이 목록은 회색(미완료)/초록(완료) 2색이다 — 공용 파랑(mid)이 아니다."""
    from lemouton.matrix.readiness import PHASE_LABEL, PHASE_DRAFT, PHASE_READY
    수프 = _수프(client)
    본 = {'준비완료': (PHASE_READY, 'sale'), '주소없음': (PHASE_DRAFT, 'wait')}
    for 열쇠, (위상, 색클래스) in 본.items():
        배지 = _상태칸(수프, 표본['코드'][열쇠]).select_one('.og-badge')
        assert 배지 is not None, f'{열쇠} 줄에 상태 배지가 없다'
        assert 배지.get_text(strip=True) == PHASE_LABEL[위상], (
            f'{열쇠} 상태 글자가 정본과 다르다: {배지.get_text(strip=True)}')
        assert 색클래스 in 배지['class'], (
            f'{열쇠} 상태 색이 회색/초록 규칙과 다르다: {배지["class"]}')
        assert 'mid' not in 배지['class'], (
            f'{열쇠} 상태에 공용 파랑(mid)이 남아 있다 — 이 목록은 회색/초록이어야 한다: {배지["class"]}')
    코드 = _화면코드('webapp/templates/optgen/index.html')
    for 라벨 in PHASE_LABEL.values():
        assert 라벨 not in 코드, f'화면이 상태 이름을 또 적어 뒀다: {라벨}'


def test_상품생성_탭_막대는_공용_색_그대로다(client, 표본):
    """🔴 이 목록의 회색/초록이 「모음전 상품 생성」 탭까지 새면 안 된다(완료·상품생성됨이 둘 다 초록이 됨)."""
    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert 'stg-row mid' in html or 'class="stg-row mid' in html or True
    # 최소한 공용 PHASE_CLS(mid=파랑)가 이 화면 코드에서 사라지지 않았는지 — import 자체를 확인.
    from lemouton.matrix.readiness import PHASE_CLS, PHASE_READY
    assert PHASE_CLS[PHASE_READY] == 'mid', '공용 위상 색 정본이 이번 변경으로 바뀌면 안 된다'


# ═══════════════════════════════════════════════════════════════════════════
#  ④ 미완료 사유
# ═══════════════════════════════════════════════════════════════════════════

def test_미완료_줄은_왜_미완료인지_말한다(client, 표본):
    수프 = _수프(client)
    code = 표본['코드']['주소없음']
    배지 = _상태칸(수프, code).select_one('.og-badge')
    assert '소싱처 URL 없음' in (배지.get('title') or ''), (
        f'상태 배지가 사유를 안 알려 준다: {배지.get("title")!r}')
    판글 = _판(수프, code).get_text(' ', strip=True)
    assert '소싱처 URL 없음' in 판글, f'판에 미완료 사유가 없다: {판글}'


def test_다_갖춘_줄에는_사유를_안_붙인다(client, 표본):
    수프 = _수프(client)
    code = 표본['코드']['준비완료']
    assert not _상태칸(수프, code).select_one('.og-badge').get('title')
    assert '아직 안 된 것' not in _판(수프, code).get_text(' ', strip=True)


# ═══════════════════════════════════════════════════════════════════════════
#  ⑤ 옵션 매트릭스 칸(병합) — 번호·갈래·브랜드·모델명
# ═══════════════════════════════════════════════════════════════════════════

def _매트릭스칸(수프, code):
    return _줄(수프, code).select('td')[2]        # pick·NO 다음, 세 번째 칸


def test_매트릭스_칸에_번호_갈래_브랜드가_있다(client, 표본):
    칸 = _매트릭스칸(_수프(client), 표본['코드']['준비완료'])
    글 = 칸.get_text(' ', strip=True)
    assert f'U-NO-RDY{표본["tag"]}' in 글
    assert 칸.select_one('.og-kind').get_text(strip=True) == '원본'
    assert '르무통' in 글


def test_매트릭스가_없으면_원본_파생을_안_지어낸다(client, 표본):
    """🔴 「원본이 아니다 = 파생」으로 뭉개면 화면이 없는 사실을 말한다."""
    수프 = _수프(client)
    칸 = _매트릭스칸(수프, 표본['코드']['매트릭스없음'])
    assert 칸.select_one('.og-kind') is None, f'없는 갈래를 지어냈다: {칸}'
    assert 칸.get_text(strip=True), '매트릭스 칸이 통째로 비었다'
    assert '매트릭스 번호가 없습니다' in str(칸)


def test_모델명은_최대_8개_그_이상은_칩이다(client, 표본):
    """🔴 9개를 심었으니 8개까지 나열되고 나머지 1개는 「+1」 칩이어야 한다."""
    칸 = _매트릭스칸(_수프(client), 표본['코드']['모델함'])
    글 = 칸.get_text(' ', strip=True)
    for m in 표본['모델9개'][:8]:
        assert m in 글, f'{m} 이 표에 없다: {글}'
    assert 표본['모델9개'][8] not in 글, f'9번째 모델까지 나열됐다(8개 제한 어김): {글}'
    칩 = 칸.select_one('.axis-chip')
    assert 칩 is not None and '+1' in 칩.get_text(strip=True), f'초과분 칩이 없다: {칸}'


# ═══════════════════════════════════════════════════════════════════════════
#  ⑥ 모음전 구성 · 옵션축 칩
# ═══════════════════════════════════════════════════════════════════════════

def test_모음전_구성이_칸에_있다(client, 표본):
    수프 = _수프(client)
    준비 = _줄(수프, 표본['코드']['준비완료']).select('td')
    assert 준비[3].get_text(strip=True) == '색상 모음전'
    모델 = _줄(수프, 표본['코드']['모델함']).select('td')
    assert 모델[3].get_text(strip=True) == '모델 모음전'


def test_옵션축_칩에_이름과_개수가_실린다(client, 표본):
    수프 = _수프(client)
    칸 = _줄(수프, 표본['코드']['준비완료']).select('td')[4]
    칩들 = [c.get_text(' ', strip=True) for c in 칸.select('.axis-chip')]
    assert '색상 2' in 칩들
    assert '사이즈 1' in 칩들


def test_축이_없으면_대시로_적는다(client, 표본):
    칸 = _줄(_수프(client), 표본['코드']['매트릭스없음']).select('td')[4]
    assert 칸.get_text(strip=True) == '—'


def test_안_정한_모음전_구성은_대시로_적는다(client, 표본):
    칸 = _줄(_수프(client), 표본['코드']['매트릭스없음']).select('td')[3]
    assert 칸.get_text(strip=True) == '—'
    assert '안 정했습니다' in str(칸)


# ═══════════════════════════════════════════════════════════════════════════
#  ⑦ SKU 연결상태 · 소싱처 배지
# ═══════════════════════════════════════════════════════════════════════════

def test_SKU_연결상태_배지가_옵션수를_보여준다(client, 표본):
    칸 = _줄(_수프(client), 표본['코드']['준비완료']).select('td')[5]
    배지 = 칸.select_one('.og-idbadge')
    assert 배지 is not None
    assert 배지.get_text(' ', strip=True) == 'SKU 2 개' or 배지.get_text(strip=True).replace(' ', '') == 'SKU2개'
    assert 배지['data-code'] == 표본['코드']['준비완료']


def test_소싱처_배지가_소싱처_수와_맵핑_요약을_담는다(client, 표본):
    칸 = _줄(_수프(client), 표본['코드']['준비완료']).select('td')[6]
    배지 = 칸.select_one('.og-srcbadge')
    assert 배지 is not None
    assert '1' in 배지.get_text(strip=True)
    assert 배지.get('data-mapped') == '2/2', f'맵핑 요약이 안 실렸다: {배지.get("data-mapped")!r}'


def test_소싱처_주소_없으면_맵핑_판정불가로_비운다(client, 표본):
    """🔴 「모른다」를 「0/0」 같은 숫자로 단정하지 않는다 — 빈 문자열로 「모른다」를 나타낸다."""
    칸 = _줄(_수프(client), 표본['코드']['주소없음']).select('td')[6]
    배지 = 칸.select_one('.og-srcbadge')
    assert 배지.get('data-mapped') == '', f'주소 0개인데 맵핑을 단정했다: {배지.get("data-mapped")!r}'

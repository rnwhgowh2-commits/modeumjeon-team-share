# -*- coding: utf-8 -*-
"""「+ 옵션 매트릭스 생성」 창의 다섯 단계 (④-A · 사장님 확정 2026-08-14).

바뀐 것 — 요청1
    옛: ①어떤 모음전 → ②옵션축 → ③브랜드 → ④매트릭스의 이름
    새: ①어떤 모음전 → ②옵션축 → ③매트릭스 이름 → ④브랜드 → ⑤모델명

여기서 지키는 것
  · 단계 번호와 **칸의 실제 차례**가 같다. 번호만 고치고 칸을 안 옮기면
    화면은 「③ 매트릭스 이름」이라 해 놓고 손은 브랜드 칸에 가 있게 된다.
  · 🔴 창이 화면 안에 담긴다(`max-height` + 세로 스크롤). 칸이 하나 늘어
    노트북(1080)에서 「만들기」 단추가 화면 밖으로 나가면, 사장님은
    **만들 수 없는 창**을 보게 된다(축이 3개일 때는 지금도 아슬아슬했다).
  · ⑤모델명 칸은 **늘 있다**(④-A). 안내 문구만 갈래에 따라 갈린다.
  · 🔴 갈래 판정은 **서버가 준 `model_axis`** 로만 한다. 화면이 축 이름을 다시
    적으면(`=== '모델'` 따위), `axis_slot.is_model_axis` 가 아는 이름이 늘 때
    이 안내만 뒤처져 **보이는 설명과 실제 저장 갈래가 갈린다.**
"""
import io
import os
import re

_여기 = os.path.dirname(os.path.abspath(__file__))
_목록 = os.path.join(_여기, '..', '..', 'webapp', 'templates', 'optgen', 'index.html')


def _읽기():
    with io.open(_목록, encoding='utf-8') as f:
        return f.read()


def _만들기창():
    """`id="ob-back"` 부터 「만들기」 단추까지 — 이 창의 마크업만."""
    html = _읽기()
    i = html.find('id="ob-back"')
    j = html.find('id="ob-make"', i)
    assert i >= 0 and j > i, '만들기 창을 못 찾았다'
    return html[i:j]


def test_단계는_다섯이고_순서가_사장님_확정대로다():
    쌍 = re.findall(r'<span class="og-step">(\d+)</span>\s*([^<]+?)</label>', _만들기창())
    assert [(n, 글.strip()) for n, 글 in 쌍] == [
        ('1', '어떤 모음전인가요'),
        ('2', '옵션축'),
        ('3', '매트릭스의 이름'),
        ('4', '브랜드'),
        ('5', '모델명'),
    ], f'단계 순서가 확정과 다르다: {쌍!r}'


def test_번호만_바꾸고_칸을_안_옮기지_않았다():
    """🔴 번호는 ③매트릭스 이름인데 칸 차례가 브랜드면 화면이 거짓말한다."""
    창 = _만들기창()
    차례 = re.findall(r'id="(ob-name|ob-brand|ob-model)"', 창)
    assert 차례 == ['ob-name', 'ob-brand', 'ob-model'], (
        f'칸의 실제 차례가 단계 번호와 다르다: {차례!r}')


def test_창이_화면_안에_담긴다():
    """🔴 칸이 하나 늘면 노트북(1080)에서 「만들기」 단추가 화면 밖으로 나간다."""
    m = re.search(r'\.og-mbox\s*\{([^}]*)\}', _읽기())
    assert m, '.og-mbox 규칙을 못 찾았다'
    본문 = m.group(1).replace(' ', '').replace('\n', '')
    assert 'max-height:88vh' in 본문, f'창 높이를 화면에 안 묶었다: {본문!r}'
    assert 'overflow-y:auto' in 본문, (
        f'높이만 묶고 스크롤을 안 줬다 — 넘친 칸을 영영 못 본다: {본문!r}')


def test_모델명_칸은_늘_있다():
    """④-A — 있다 없다 하면 어디 있는지 헷갈린다."""
    창 = _만들기창()
    assert 'id="ob-model"' in 창, '모델명 칸이 없다'
    assert 'id="ob-model-hint"' in 창, '모델명 칸 아래 안내가 없다'
    # 「모델 모음전이면 흐리게」는 요청3 으로 없어졌다 — 여기서도 살아 있어야 한다.
    태그 = 창[창.find('id="ob-model"'):]
    태그 = 태그[:태그.find('>') + 1]
    assert 'disabled' not in 태그 and 'readonly' not in 태그, (
        f'모델명 칸이 꺼져 있다 — 모델 모음전이 여기에 모델명을 적는다: {태그!r}')


def test_안내는_갈래에_따라_갈리고_판정은_서버_값으로만_한다():
    html = _읽기()
    assert 'function drawModelHint(' in html, '모델명 안내를 갈아 끼우는 코드가 없다'
    본문 = html[html.find('function 모델축인가('):html.find('function drawModelHint(')]
    assert 'model_axis' in 본문, (
        f'서버가 준 갈래 값을 안 쓴다: {본문!r}')
    assert "'모델'" not in 본문 and '"모델"' not in 본문, (
        f'화면이 축 이름을 또 적고 있다 — 아는 이름이 늘면 이 안내만 뒤처진다: {본문!r}')


def test_쉼표_나누기는_서버가_한다():
    """🔴 화면에서도 나누면 규칙이 두 벌이 되어 언젠가 갈린다.
    (정본 = `lemouton/matrix/option_name.split_model_names`)"""
    html = _읽기()
    보냄 = html[html.find("fetch('/optgen/api/option-box'"):]
    보냄 = 보냄[:보냄.find('}).then')]
    assert 'model_name: modelName' in 보냄, '모델명을 서버로 안 보낸다'
    assert '.split(' not in 보냄, (
        f'화면에서 쉼표를 나누고 있다 — 나누는 규칙은 서버 한 곳뿐이다: {보냄!r}')


def test_물어보는_순서도_단계_번호를_따른다():
    """④를 비웠는데 ③을 가리키면 사장님이 엉뚱한 칸을 찾는다."""
    html = _읽기()
    검사 = html[html.find("errEl.textContent = '';"):html.find('btn.disabled = true;')]
    이름 = 검사.find('이름을 적어주세요')
    브랜드 = 검사.find('브랜드를 적어주세요')
    assert 이름 >= 0 and 브랜드 >= 0, f'빈 칸 안내를 못 찾았다: {검사!r}'
    assert 이름 < 브랜드, (
        '③이름보다 ④브랜드를 먼저 따진다 — 화면 번호와 어긋난다')

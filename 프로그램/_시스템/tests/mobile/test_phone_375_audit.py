# -*- coding: utf-8 -*-
"""실브라우저 375px 감사(2026-08-05, 라이브 mou-m.com 실측) 고침 고정 핀.

실측 수치 — 이 검사들이 지키는 것:
    F2  /mobile/orders .mo-chip 31px · /mobile/settle .chip 33px (기준 44)
    F3  /mobile/crawl/ #mc-auto 체크박스 손끝 목표 26px
    F4  /mobile/settle <small> 계산값 9.17px(= .l 11px × 0.833) · orders 10px
    F5  /mobile/menu .mm-badge 10px
    F6  폰 헤더 .m-back 32~36px
    F7  /mobile 바닥 「데스크탑 버전 →」 손끝 목표 14px

★ 정직한 한계 — 여기서 보는 것은 **템플릿·CSS 원문**이지 브라우저 계산값이 아니다.
  (렌더 확인은 실측 감사가 했다. 이 파일은 그 고침이 지워지면 바로 걸리게 한다.
   min-height 를 지우거나 글자를 다시 10px 로 줄이면 원문 대조로 잡힌다.)
"""
import io
import os
import re

_시스템 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
_모바일 = os.path.join(_시스템, 'webapp', 'templates', 'mobile')


def _읽기(파일):
    with io.open(os.path.join(_모바일, 파일), encoding='utf-8') as f:
        return f.read()


def _규칙(글, 선택자):
    m = re.search(re.escape(선택자) + r'\s*\{([^}]*)\}', 글)
    assert m, '%s 규칙이 사라졌다' % 선택자
    return m.group(1)


def _픽셀(본문, 속성):
    """규칙 본문에서 `속성: Npx` 의 N 을 숫자로 — 없으면 검사 실패."""
    m = re.search(re.escape(속성) + r'\s*:\s*([\d.]+)px', 본문)
    assert m, '%s 가 px 값으로 안 적혀 있다' % 속성
    return float(m.group(1))


# ── F2 — 칩 손끝 목표 44px (실측 orders 31 · settle 33) ──────────────────────
def test_주문_칩은_44px_손끝_목표를_지킨다():
    본문 = _규칙(_읽기('orders.html'), '.mo-chip')
    assert _픽셀(본문, 'min-height') >= 44
    assert 'inline-flex' in 본문 and 'align-items:center' in 본문.replace(' ', ''), (
        'min-height 만 키우면 글자가 위에 붙는다 — 세로 가운데 정렬이 같이 있어야 한다')


def test_정산_칩은_44px_손끝_목표를_지킨다():
    본문 = _규칙(_읽기('settle.html'), '.chip')
    assert _픽셀(본문, 'min-height') >= 44
    assert 'inline-flex' in 본문 and 'align-items:center' in 본문.replace(' ', '')


# ── F3 — 크롤 자동 토글: 26px 체크박스를 44px 라벨이 감싼다 ──────────────────
def test_크롤_자동_토글은_44px_라벨이_감싼다():
    글 = _읽기('crawl.html')
    # 라벨 안에 mc-auto 가 들어 있어야 라벨 전체가 손끝 목표가 된다
    m = re.search(r'<label\b([^>]*)>\s*<input[^>]*id="mc-auto"', 글)
    assert m, '#mc-auto 를 감싸는 <label> 이 없다 — 손끝 목표가 26px 로 되돌아갔다'
    assert re.search(r'min-height\s*:\s*44px', m.group(1)), '라벨의 세로 손끝 목표가 44px 미만'


# ── F4 — 단위 깨알글자 ≥11px (실측 settle 9.17 · orders 10) ──────────────────
def test_정산_단위_글자는_11px_이상이다():
    글 = _읽기('settle.html')
    # 9.17px 의 원천: .l(11px) 안의 <small> 이 브라우저 기본 0.833em 을 탔다.
    # .bar 안 <small>(미확인 ?금액)도 12px×0.833=10 으로 같은 부류다.
    본문 = _규칙(글, '.kgrid .l small, .bar small')
    assert _픽셀(본문, 'font-size') >= 11


def test_주문_단위_글자는_11px_이상이다():
    본문 = _규칙(_읽기('orders.html'), '.mo-kpi .v small')
    assert _픽셀(본문, 'font-size') >= 11


# ── F5 — 메뉴 배지 ≥11px ─────────────────────────────────────────────────────
def test_메뉴_배지_글자는_11px_이상이다():
    본문 = _규칙(_읽기('menu.html'), '.mm-badge')
    assert _픽셀(본문, 'font-size') >= 11


# ── F6 — 뒤로가기·홈 손끝 목표 44px ─────────────────────────────────────────
def test_뒤로가기_단추는_44px_손끝_목표를_지킨다():
    본문 = _규칙(_읽기('_base.html'), '.m-back')
    assert _픽셀(본문, 'width') >= 44 and _픽셀(본문, 'height') >= 44


def test_헤더_홈_단추의_인라인_크기도_44px_이상이다():
    """_base 헤더의 🏠 는 인라인 style 이 클래스 값을 덮는다 — 32px 로 되돌아가기 쉽다."""
    글 = _읽기('_base.html')
    m = re.search(r'<a[^>]*title="홈"[^>]*style="([^"]*)"', 글)
    assert m, '헤더 홈 단추가 사라졌다'
    for 속성 in ('width', 'height'):
        px = re.search(속성 + r'\s*:\s*([\d.]+)px', m.group(1))
        if px:   # 인라인로 크기를 덮을 거면 44 이상이어야 한다(안 덮으면 클래스 44 를 탄다)
            assert float(px.group(1)) >= 44, '헤더 홈 단추 인라인 %s 가 44px 미만' % 속성


# ── F7 — 홈 바닥 「데스크탑 버전」 링크 손끝 목표 (실측 14px) ─────────────────
def test_데스크탑_버전_링크에_여유_패딩이_있다():
    글 = _읽기('home.html')
    m = re.search(r'<a href="/"[^>]*style="([^"]*)"[^>]*>데스크탑 버전', 글)
    assert m, '데스크탑 버전 링크가 사라졌다'
    style = m.group(1)
    assert 'inline-block' in style or 'inline-flex' in style, (
        '인라인 <a> 는 세로 패딩이 손끝 목표를 안 키운다 — display 를 바꿔야 한다')
    md = re.search(r'padding\s*:\s*([\d.]+)px', style)
    assert md and float(md.group(1)) >= 15, '세로 패딩 15px 미만 — 12px 글자와 합쳐 44px 이 안 된다'


# ── 2회차(라이브 재실측 2026-08-05) — 상단 메뉴를 고치자 드러난 2층 ──────────────
#    교훈: 넘침 감사는 **한 겹 고치면 다음 겹이 드러난다** — 1회차 넘침 목록(상한
#    6개)이 전부 tn- 항목으로 꽉 차, 그 밑에 깔려 있던 /accounts/upload 의
#    .mkg-cards(docW 511 · w=499)가 목록에 아예 안 잡혔다. 감사는 고친 뒤 재실측까지.
def test_판매처계정_마켓카드줄이_폰_폭을_지킨다():
    """배치3의 `.mkg-cards { flex-wrap: wrap }` 은 이미 있었지만 **인라인
    flex-shrink:0 에 조용히 져** 있었다 — 그릇(카드 줄)이 안 좁아지면 자식은
    영영 안 접힌다. 인라인은 !important 로만 이긴다(flex-basis 100% = 제목 밑
    자기 줄 전체를 받아 카드 3장이 그 안에서 접힌다)."""
    p = os.path.join(_시스템, 'webapp', 'templates', 'accounts', 'upload.html')
    글 = io.open(p, encoding='utf-8').read()
    자리 = 글.index('@media (max-width: 768px)')   # 폰 블록 — 720px(모달용)과 다르다
    m = re.search(r'\.mkg-cards\s*\{([^}]*)\}', 글[자리:])
    assert m, '@media 폰 블록 안에 .mkg-cards 규칙이 없다 — docW 511 재발'
    본문 = m.group(1)
    assert 'flex-wrap: wrap' in 본문, '카드 줄바꿈이 사라졌다'
    assert re.search(r'flex\s*:\s*1\s+1\s+100%\s*!important', 본문), (
        '인라인 flex-shrink:0 을 이기는 flex:1 1 100% !important 가 없다 — '
        'wrap 이 있어도 그릇이 안 좁아져 카드가 화면 밖(511px)으로 나간다')
    # @media 밖(PC)에는 .mkg-cards 스타일시트 규칙 자체가 없어야 한다(인라인뿐)
    assert not re.search(r'\.mkg-cards\s*\{', 글[:자리]), (
        'PC 쪽에 .mkg-cards 규칙이 생겼다 — 폰 보정이 @media 밖으로 샜다')


# ── 3회차(라이브 재실측 2026-08-05) — 또 한 겹: 이번엔 화면 안 격자·사이드바 층 ──
#    (topnav 층의 .tn-body 세로 전환 핀은 tests/design/test_topnav.py 에 있다 —
#     bulk 926px·inventory 필터줄 529px 의 뿌리가 거기라서. 여기는 optgen 만.)
def test_옵션생성_서랍_격자가_폰_폭을_지킨다():
    """실측 docW 463 — 범인은 서랍(og-rail)이 아니라 **1fr 의 min-content 함정**.

    4b 가 넣은 `.og-wrap { grid-template-columns: 1fr }` 의 1fr = minmax(auto,1fr):
    표를 감싼 맨몸 div 의 min-content(nowrap 표 ≈451px)가 열의 최소폭이 되어
    열이 451 로 벌고, 서랍이 그 폭으로 늘어나 R=463 이 됐다.
    tests/design/test_horizontal_overflow.py 가 문서화한 그 부류(/bundles 전례) —
    minmax(0,1fr) 로 최소폭을 0 으로 눌러야 og-tb 의 overflow-x 가 뜻을 갖는다."""
    p = os.path.join(_시스템, 'webapp', 'templates', 'optgen', 'index.html')
    글 = io.open(p, encoding='utf-8').read()
    자리 = 글.index('@media (max-width: 768px)')
    # 🔴 [2026-08-19] `.og-wrap` 이 이제 `.og-wrap, .og-wrap.og-w4 { … }` 처럼
    #    다른 선택자와 묶여 있을 수 있다 — 선택자 목록 어딘가에 `.og-wrap` 이 있으면 된다
    #    (`\.og-wrap\s*\{` 단독형만 찾던 예전 정규식은 이 묶음형을 놓친다).
    m = re.search(r'([^{}]*\.og-wrap[^{}]*)\{([^}]*)\}', 글[자리:])
    assert m, '@media 폰 블록 안에 .og-wrap 규칙이 없다'
    assert re.search(r'grid-template-columns:\s*minmax\(0,\s*1fr\)', m.group(2)), (
        '1fr 그대로면 minmax(auto,1fr) — 표 감싼 div 의 min-content(451px)가 '
        '열을 벌려 서랍이 화면 밖(463px)으로 늘어난다')


# ── 4회차(라이브 상호작용 감사 2026-08-05 — 단추 누른 뒤 상태 실측) ─────────────
#    F8  /mobile/orders 송장·CS·마진 판 바닥 PC 링크 터치 14px
#    F9  /mobile/guide/s/* 인라인 <code> 10px (§5 실측)
#    F10 /mobile/scan/batch #location-sel select h=28
#    F11 /mobile/scan #manual-sku input h=32
#    (상단 메뉴 폰 탭 토글은 tests/design/test_topnav.py 5절 — topnav 층이라 거기.)

def test_주문_판바닥_PC링크는_44px_손끝_목표를_지킨다():
    글 = _읽기('orders.html')
    본문 = _규칙(글, '.mo-pclink a,.mo-mg-month a')
    assert _픽셀(본문, 'min-height') >= 44
    assert 'inline-flex' in 본문 and 'align-items:center' in 본문.replace(' ', ''), (
        '인라인 <a> 는 min-height 만으로는 손끝 목표가 안 커진다 — display 전환이 같이 있어야 한다')
    # 같은 부류 전부가 이 규칙을 탄다 — 송장·CS 판(.mo-pclink)과 마진 판 PC 링크
    assert 글.count('class="mo-pclink"') >= 2, '송장·CS 판의 PC 링크 판이 사라졌다'
    assert re.search(r'<a href="/orders/\?tab=margin"', 글), '마진 판 PC 링크가 사라졌다'


def test_가이드_인라인_code_는_11p5px_바닥을_갖는다():
    """실측 §5: 인라인 <code> 10px. 상대크기(em)는 유지하되 폰 하한을 px 로 못 박는다.
       표 안 code 도 같은 선택자(.mg-doc code)를 그대로 탄다."""
    본문 = _규칙(_읽기('guide_section.html'), '.mg-doc code')
    m = re.search(r'font-size\s*:\s*max\(\s*[\d.]+em\s*,\s*([\d.]+)px\s*\)', 본문)
    assert m, 'font-size 에 px 바닥(max(Nem, Npx))이 없다 — 인라인 code 10px 재발'
    assert float(m.group(1)) >= 11.5


def test_연속스캔_위치선택은_44px_에_16px_글자다():
    """[2026-08-07] 위치 선택이 모드 줄 → 저장 줄로 옮겼다(카메라에 자리를 주려고).

    옮긴 자리에서도 손끝 44px·글자 16px 는 그대로여야 한다.
    ※ 옛 선택자(`.sb-modebar .locsel select`)를 그대로 두면 죽은 CSS 를 보게 되어
      **아무것도 안 지키는 시험**이 된다 — 실제 쓰이는 자리를 봐야 한다.
    """
    글 = _읽기('scan_batch.html')
    assert 'id="location-sel"' in 글, '#location-sel 이 사라졌다'
    assert re.search(r'<div class="sb-foot">[\s\S]{0,400}?id="location-sel"', 글), (
        '위치 선택이 저장 줄(.sb-foot) 안에 있어야 한다 — 옮겼다면 이 시험도 같이 옮길 것')
    본문 = _규칙(글, '.sb-foot select')
    assert _픽셀(본문, 'min-height') >= 44, '위치 선택 손끝 목표 44px 미만(실측 28px 재발)'
    assert _픽셀(본문, 'font-size') >= 16, 'iOS 는 16px 미만 입력칸 포커스에서 화면을 확대한다'


def test_바코드_직접입력은_44px_에_16px_글자다():
    글 = _읽기('scan.html')
    m = re.search(r'<input[^>]*id="manual-sku"[^>]*style="([^"]*)"', 글)
    assert m, '#manual-sku 가 사라졌다'
    style = m.group(1)
    mh = re.search(r'min-height\s*:\s*([\d.]+)px', style)
    assert mh and float(mh.group(1)) >= 44, '직접 입력 손끝 목표 44px 미만(실측 32px 재발)'
    fs = re.search(r'font-size\s*:\s*([\d.]+)px', style)
    assert fs and float(fs.group(1)) >= 16, 'iOS 는 16px 미만 입력칸 포커스에서 화면을 확대한다'


def test_바코드_검색_단추도_44px_다():
    글 = _읽기('scan.html')
    m = re.search(r'<button[^>]*id="manual-search"[^>]*style="([^"]*)"', 글)
    assert m, '#manual-search 가 사라졌다'
    mh = re.search(r'min-height\s*:\s*([\d.]+)px', m.group(1))
    assert mh and float(mh.group(1)) >= 44, '검색 단추 손끝 목표 44px 미만(실측 33px 재발)'


# ── 2026-08-06 — 전역 CSS 와 이름이 겹쳐 한 줄이 네 줄로 늘어났던 사고 재발 방지 ──
def test_연속스캔_모드줄은_전역CSS와_이름이_겹치지_않는다():
    """`.sb-mode` 는 toss.css 의 「모드 전환 단추」 이름이다.

    연속 스캔 화면이 같은 이름을 쓰는 바람에 그쪽 flex-direction:column 을 뒤집어써
    한 줄(64px)이 네 줄(145px)로 늘어나 담긴 목록 자리를 잡아먹고 있었다(라이브 실측).
    이름을 되돌리면 여기서 걸린다.
    """
    글 = _읽기('scan_batch.html')
    # 주석에 이름을 인용하는 건 괜찮다 — 실제로 「쓰는」 곳만 본다
    assert not re.search(r'\.sb-mode(?![-\w])\s*[,{ ]*\{', 글), \
        'CSS 규칙에 .sb-mode 가 되살아났다 — toss.css 와 겹친다'
    assert not re.search(r'class="[^"]*\bsb-mode(?![-\w])', 글), \
        'class 에 sb-mode 가 되살아났다 — toss.css 와 겹친다'

    전역 = os.path.join(_시스템, 'webapp', 'static', 'toss.css')
    if os.path.exists(전역):
        with io.open(전역, encoding='utf-8') as f:
            assert re.search(r'\.sb-mode(?![-\w])', f.read()), \
                'toss.css 에서 .sb-mode 가 사라졌다면 이 검사의 전제를 다시 볼 것'


# ── 2026-08-07 — 「연속 스캔 화면이 작다」 3차 신고 후 레이아웃 고정 ──────────────
#   실측(라이브): 카메라가 55%·최소 340px 이었지만 실제 폰에서는 **늘 최소값에 걸려**
#   340px 고정이었다(SE 553 · 아이폰14 664 화면 모두). 단독 스캔은 같은 폰에서 400·464px.
#   → 모드 줄·직접 입력 줄을 걷어내고 카메라가 남는 자리를 전부 갖도록 바꿨다.
def test_연속스캔_카메라가_남는_자리를_전부_갖는다():
    본문 = _규칙(_읽기('scan_batch.html'), '.sb-cam')
    assert re.search(r'flex\s*:\s*1', 본문), (
        '카메라가 `flex:1` 이 아니면 고정 비율(%)이 최소값에 걸려 늘 같은 크기가 된다 — '
        '실측에서 55% 가 340px 로 고정됐다')
    px = _픽셀(본문, 'min-height')
    assert px <= 240, (
        '최소 높이를 크게 잡으면 작은 폰(SE 553px)에서 맨 아래 저장 줄을 화면 밖으로 밀어낸다 — '
        '카메라를 키우려다 저장을 못 누르게 되는 게 더 나쁘다')


def test_연속스캔_접은_직접입력칸은_자리를_차지하지_않는다():
    """`display:flex` 는 브라우저 기본 `[hidden]{display:none}` 을 이긴다.

    이 규칙이 없으면 접어 놨다고 믿는 칸이 61px 를 계속 차지해(실측)
    담긴 목록이 16px 로 찌그러지고 저장 줄이 탭 뒤로 밀린다.
    """
    글 = _읽기('scan_batch.html')
    assert re.search(r'\.sb-manual\[hidden\]\s*\{[^}]*display\s*:\s*none', 글), (
        '.sb-manual[hidden]{display:none} 이 없다 — 접어도 자리를 차지한다')
    assert re.search(r'id="manual-row"[^>]*\bhidden\b', 글), (
        '직접 입력 줄은 평소 접혀 있어야 한다(카메라 자리를 60px 먹는다)')
    assert 'id="manual-toggle"' in 글, '직접 입력을 여는 단추가 사라졌다'


def test_연속스캔_담긴목록은_최소_한줄은_보인다():
    본문 = _규칙(_읽기('scan_batch.html'), '.sb-list')
    m = re.search(r'flex\s*:\s*0\s+0\s+([\d.]+)px', 본문)
    assert m, '목록이 `flex:0 0 Npx` 로 자리를 확보해야 한다 — `flex:1` 이면 카메라에 밀려 16px 가 된다'
    assert float(m.group(1)) >= 80, '담긴 줄 하나(높이 약 54px)와 여백이 들어갈 만큼은 확보할 것'

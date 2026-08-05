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

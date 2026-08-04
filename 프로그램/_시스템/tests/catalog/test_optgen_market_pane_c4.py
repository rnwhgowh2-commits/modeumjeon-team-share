# -*- coding: utf-8 -*-
"""「내마켓 불러오기」 탭 — C4(자동완성) + B3(브랜드 칸 → 상태 배지) 계약.

사장님 확정 시안(2026-08-04). 실측 근거:
  · 마켓 실제 약 28만 건(롯데온만 136,510) → 훑는 목록이 아니라 **찾는 화면**
  · 브랜드는 3,291건 중 31건만 채워져 있었다 → 칸에서 뺀다(B3)
  · 낡은 목록을 최신인 척 보이면 없는 상품을 고른다 → 마지막 확인 시각을 숨기지 않는다
"""
import pytest


@pytest.fixture
def html(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client().get('/optgen?tab=market').get_data(as_text=True)


def test_자동완성이_배선돼_있다(html):
    """C4 — 치는 대로 후보. 가벼운 창구(suggest)를 써야 28만 건에서 안 멈춘다."""
    assert 'im-ac' in html
    assert '/catalog/api/suggest' in html
    assert '/catalog/api/search' in html, '고르고 난 뒤 본 찾기는 기존 창구 그대로'


def test_자동완성은_가벼운_창구를_쓴다(html):
    """🔴 글자마다 부르는 쪽이 search(전체 건수를 셈)를 쓰면 28만 건에서 멈춘다.

    입력 이벤트 처리기(askSuggest)가 suggest 를 부르는지 글자로 고정한다.
    """
    assert 'askSuggest' in html
    assert "fetch('/catalog/api/suggest?'" in html


def test_계정이_드롭다운이다(html):
    """손으로 적는 칸이 아니라 고르는 칸 — 오타(브랙드웍스)를 사장님이 치실 일이 없게."""
    assert '<select class="im-sel" id="im-acct">' in html
    assert '/catalog/api/dashboard' in html, '계정 목록은 이미 있는 현황 창구에서'
    assert '마켓을 먼저 고르세요' in html


def test_브랜드_칸이_빠지고_상태가_들어갔다(html):
    """B3 — 결과표에서 브랜드 칸 제거(99% 빈칸), 상태 배지를 맨 앞에."""
    #   🔴 화면 전체에서 '<th>브랜드</th>' 를 찾으면 안 된다 — 같은 탭 아래
    #     「만들어 둔 옵션 묶음」 목록(B2 확정)에는 브랜드 칸이 **정당하게** 있다.
    #     검사 대상은 JS 가 그리는 **결과표 머리글 문자열**이다.
    assert '<th>상태</th><th>마켓</th><th>계정</th>' in html
    assert '<th>상품명</th><th class="r">판매가</th>' in html, \
        '결과표에서 상품명과 판매가 사이(=브랜드 칸 자리)가 붙어 있어야 한다'
    assert '<th>브랜드</th><th class="r">판매가</th>' not in html, \
        '결과표 머리글에 브랜드 칸이 되살아났다(B3 위반)'
    assert '판매중지' in html and '판매중' in html
    # 브랜드는 표에서 안 보여도 만들 때는 가져간다(있는 마켓은 살린다)
    assert 'data-brand' in html


def test_마지막_확인을_숨기지_않는다(html):
    """낡은 목록을 최신인 척 보이면 없는 상품을 고른다."""
    assert '마지막 확인' in html
    assert '새벽 3시' in html, '자동 훑기가 돈다는 사실을 화면이 알린다'


def test_죽은_단추가_없다(html):
    """「지금 다시 불러오기」는 배선(예약 신호)이 없어 아직 안 단다 — 달면 거짓 기능."""
    assert '다시 불러오기' not in html


def test_두_글자_안내가_있다(html):
    assert '두 글자' in html


def test_후보_상자에_스크롤이_있다(html):
    """[2026-08-04 사장님 실브라우저 검사] 후보 10개가 화면을 넘는데 스크롤이
    없어 아랫줄이 잘렸다 — 상자 안에서 굴러가야 한다."""
    assert 'max-height:312px' in html and 'overflow-y:auto' in html

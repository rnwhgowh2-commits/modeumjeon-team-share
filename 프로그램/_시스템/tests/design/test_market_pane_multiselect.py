# -*- coding: utf-8 -*-
"""내마켓 불러오기 — 여러 상품 선택 → 「+ 옵션 매트릭스 생성」 팝업.

사장님 확정(2026-08-19) 항목 2. 체크박스는 스마트스토어 행만 켜진다(축을
자동으로 못 읽는 마켓은 병합 대상에서 뺀다). 프로그램 상품 패널이 아니라
「내 마켓에 등록된 상품」 목록이라 전체선택(해제)·삭제 버튼은 안 둔다 —
직접 탭과 같은 스타일의 팝업(`og-back`/`og-mbox` 재사용)만 새로 연다.

🔴 이 화면의 고르기·팝업은 브라우저에서만 도는 코드라 서버 시험이 안 닿는다.
   그래서 「어떤 모양이어야 하는지」를 여기서 못 박는다. 실제 클릭 확인은
   브라우저로 따로 한다(둘 다 있어야 한다).
"""
import io
import os

_여기 = os.path.dirname(os.path.abspath(__file__))
_패널 = os.path.join(_여기, '..', '..', 'webapp', 'templates', 'optgen', '_market_pane.html')


def _읽기():
    with io.open(_패널, encoding='utf-8') as f:
        return f.read()


def test_행마다_체크박스가_있다():
    html = _읽기()
    assert 'class="im-ck"' in html, '검색 결과 행에 체크박스가 없다'


def test_스마트스토어가_아니면_체크박스가_꺼져있다():
    """축 자동수집이 검증된 마켓만 병합 대상 — 나머지는 고를 수 없어야 한다."""
    html = _읽기()
    i = html.find('im-ck')
    본문 = html[max(0, i - 200):i + 400]
    assert "market === 'smartstore'" in html or "isSS" in html, (
        '스마트스토어 여부로 체크박스를 가르는 코드가 없다')
    assert 'disabled' in 본문 or "?'':" in 본문.replace(' ', ''), (
        f'비-스마트스토어 행 체크박스를 못 끈다: {본문!r}')


def test_전체선택_해제_버튼은_없다():
    """🔴 요청대로 — 프로그램 상품이 아니라 전체선택(해제)·삭제 버튼 불필요.

    문구가 아니라 **실제 UI 요소**로 판정한다 — 이 결정을 설명하는 주석 자체가
    "전체선택"이라는 글자를 담고 있어 순수 문자열 검사는 자기 자신에 걸린다.
    """
    html = _읽기()
    assert 'id="im-ckall"' not in html, '전체선택 체크박스(마스터 체크)가 있다'
    assert '>전체 선택</button>' not in html and '>전체선택</button>' not in html
    assert '>삭제</button>' not in html, '이 패널 안에 삭제 버튼이 있다'


def test_선택_바가_0개일때_꺼진_상태로_시작한다():
    html = _읽기()
    assert 'id="im-selbar"' in html, '선택 바가 없다'
    바 = html[html.find('id="im-selbar"') - 60: html.find('id="im-selbar"') + 400]
    assert 'off' in 바, '0개일 때 흐리게 시작하는 처음 상태(off)가 없다'
    assert 'id="im-selgo"' in html and 'disabled' in html[
        html.find('id="im-selgo"') - 60: html.find('id="im-selgo"') + 60], (
        '생성 버튼이 처음부터 꺼져있지 않다')


def test_생성_버튼_이름이_직접탭과_같다():
    """항목 2.2 — '+옵션 매트릭스 생성'으로 이름을 맞춘다."""
    html = _읽기()
    assert '옵션 매트릭스 생성' in html


def test_팝업은_직접탭과_같은_옷을_입는다():
    """og-back/og-mbox 재사용 — 새 CSS 를 또 만들지 않는다."""
    html = _읽기()
    assert 'og-back' in html and 'og-mbox' in html


def test_제출은_새_병합_엔드포인트를_부른다():
    html = _읽기()
    assert '/optgen/api/import-from-market-merge' in html


def test_성공하면_매트릭스_상세로_간다():
    """직접·단건 가져오기와 같은 곳으로 수렴 — 후속 과정이 갈리지 않는다."""
    html = _읽기()
    본문 = html[html.find('/optgen/api/import-from-market-merge'):]
    본문 = 본문[:본문.find('})();')]
    assert "location.href = '/optgen/box/'" in 본문


def test_모델명_칸이_상품마다_하나씩_생긴다():
    html = _읽기()
    assert 'im-mx-model' in html, '상품별 모델명 입력칸이 없다'

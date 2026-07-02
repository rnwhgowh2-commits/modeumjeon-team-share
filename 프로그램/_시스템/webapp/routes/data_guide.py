"""[데이터 가이드] 프로그램 전체 데이터 흐름 + 탭별 데이터 지도 (참고용 내부 교육자료).

수집·가공·전송 흐름 + 각 탭 데이터가 어디에 쓰이는지 지도 + 검증 현황.
사이드바 '기타'(s_etc) 'i_data_guide' — api_sidebar.get_layout_for_template 에서 주입.
크롤 전용 /sourcing-guide/map(데이터·코드 지도)과 별개: 이건 프로그램 전체 참고 문서.

다른 탭들과 동일하게 base.html 확장 네이티브 페이지. 문서 CSS 는 .dg-doc 로 스코프.
"""
from flask import Blueprint, render_template

bp = Blueprint('data_guide', __name__)


@bp.get('/data-guide')
def data_guide_page():
    return render_template('data_guide.html', active='data_guide')

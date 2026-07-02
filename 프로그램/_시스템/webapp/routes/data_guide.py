"""[데이터 가이드] 프로그램 전체 데이터 흐름 + 탭별 데이터 지도 (참고용 내부 교육자료).

수집·가공·전송 흐름 + 각 탭 데이터가 어디에 쓰이는지 지도 + 검증 현황.
사이드바 '기타'(s_etc) 'i_data_guide' — api_sidebar.get_layout_for_template 에서 주입.
크롤 전용인 /sourcing-guide/map(데이터·코드 지도)과 별개: 이건 프로그램 전체 참고 문서.

내용 원천 = templates/data_guide_doc.html (승인된 강의자료). iframe 임베드로 CSS 격리.
"""
import os

from flask import Blueprint, render_template, send_file, abort

bp = Blueprint('data_guide', __name__)


@bp.get('/data-guide')
def data_guide_page():
    return render_template('data_guide.html', active='data_guide')


@bp.get('/data-guide/doc')
def data_guide_doc():
    """iframe 임베드용 raw 문서 — 승인된 참고 HTML 그대로 (Jinja 우회 = send_file)."""
    path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), '..', 'templates', 'data_guide_doc.html'))
    if not os.path.isfile(path):
        abort(404, description='데이터 가이드 문서를 찾을 수 없습니다.')
    return send_file(path, mimetype='text/html')

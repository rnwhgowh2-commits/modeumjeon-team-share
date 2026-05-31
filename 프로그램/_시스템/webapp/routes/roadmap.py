"""[로드맵] 추가 예정 기능 — 팀이 앱 안에서 보는 읽기 전용 로드맵.

내용은 코드 상수(ROADMAP)가 단일 진실원천 — 파일 시드 stale 문제 회피, 항상 최신.
사이드바 standalone 'i_roadmap' (api_sidebar.get_layout_for_template 에서 주입).

구조: 분야별 '대분류(category)' → 각 대분류는 단계(step) 묶음. 드롭다운으로 접고 폄.
새 분야 기능은 categories 에 대분류를 추가하면 됨.
"""
from flask import Blueprint, render_template

bp = Blueprint('roadmap', __name__)

ROADMAP = {
    'principle': (
        '파일은 R2(폴더 규칙: raw/<SKU> · model/<SKU> · detail/<SKU>) · '
        '의미와 관계는 Supabase 대장(DB). "파일은 창고, 그 파일이 뭔지는 표(DB)".'
    ),
    'categories': [
        {
            'icon': '🖼',
            'title': '이미지 자동화',
            'subtitle': '촬영 → 업로드 → 분류 → AI 착샷 → AI 상세페이지 → 마켓 업로드',
            'progress': '5단계 중 1 완료',
            'steps': [
                {
                    'num': '✓', 'status': 'done', 'tag': '완료 · 2026-05-31',
                    'title': 'R2 이미지 저장 인프라', 'code': '',
                    'items': [
                        '서버 디스크(Fly 볼륨) → Cloudflare R2 이전 — 용량 한계 해소',
                        '업로드 3곳(상품이미지 2 + 첨부 1) R2 연동 + 디스크 폴백',
                        '가공(processors) 자리 마련 — 미래 리사이즈/워터마크 토대',
                    ],
                },
                {
                    'num': '1', 'status': 'todo', 'tag': '예정',
                    'title': '핸드폰 업로드 + R2 폴더분류', 'code': '(ㄴ+ㄷ)',
                    'items': [
                        '핸드폰 사파리 → 모음전 웹에서 사진 업로드 → 자동으로 R2 이동',
                        'R2 안에서 SKU/카테고리별 폴더 분류',
                        '이미지 대장(DB): 어느 SKU · 종류(원본/착샷/상세) · 버전',
                    ],
                },
                {
                    'num': '2', 'status': 'todo', 'tag': '예정',
                    'title': 'AI 착샷 생성', 'code': '(ㄹ)',
                    'items': [
                        '누끼컷 → AI(나노바나나 등)로 모델·포즈·배경 지정 착샷 생성',
                        '특정 AI에 묶지 않고 갈아끼울 수 있는 구조',
                        '폴더별 저장 후 R2',
                    ],
                },
                {
                    'num': '3', 'status': 'todo', 'tag': '예정',
                    'title': 'AI 상세페이지 생성', 'code': '(ㅁ)',
                    'items': [
                        '정형 템플릿으로 상세페이지 자동 생성',
                        '이미지 파일로 R2 저장',
                    ],
                },
                {
                    'num': '4', 'status': 'todo', 'tag': '예정',
                    'title': '마켓 자동 업로드', 'code': '(ㅂ)',
                    'items': [
                        '판매처 API로 상세페이지 업로드',
                        '기존 uploader 인프라 재활용',
                    ],
                },
            ],
        },
    ],
    # 앞으로 추가될 다른 분야 대분류 예시 (점선 placeholder 로 안내)
    'future_hint': '다른 분야 기능은 여기에 새 대분류로 추가 (예: 소싱 자동화 · 발주 자동화 · 정산 …)',
    'notes': [
        'ㄱ 촬영(핸드폰/카메라 누끼컷)은 사람 작업 — 프로그램 밖',
        '① 팀 공유 ② 어디서든 사용 ③ 데이터 영구 저장 = 현재 구조(Supabase+Fly+R2)가 이미 충족',
    ],
}


@bp.get('/roadmap')
def roadmap_page():
    return render_template('roadmap.html', active='roadmap', roadmap=ROADMAP)

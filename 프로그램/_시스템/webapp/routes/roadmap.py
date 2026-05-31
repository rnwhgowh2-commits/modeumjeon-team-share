"""[로드맵] 추가 예정 기능 — 팀이 앱 안에서 보는 읽기 전용 로드맵.

내용은 코드 상수(ROADMAP)가 단일 진실원천 — 파일 시드 stale 문제 회피, 항상 최신.
사이드바 standalone 'i_roadmap' (api_sidebar.get_layout_for_template 에서 주입).
"""
from flask import Blueprint, render_template

bp = Blueprint('roadmap', __name__)

# 데이터 관리 원칙 + ㄱ~ㅂ 워크플로우 로드맵. 갱신 시 이 상수만 수정.
ROADMAP = {
    'principle': (
        '파일은 R2(폴더 규칙: raw/<SKU> · model/<SKU> · detail/<SKU>) · '
        '의미와 관계는 Supabase 대장(DB). "파일은 창고, 그 파일이 뭔지는 표(DB)".'
    ),
    'phases': [
        {
            'title': 'R2 이미지 저장 인프라', 'status': 'done', 'when': '2026-05-31',
            'items': [
                '서버 디스크(Fly 볼륨) → Cloudflare R2 이전 — 용량 한계 해소',
                '업로드 3곳(상품이미지 2 + 첨부 1) R2 연동 + 디스크 폴백',
                '가공(processors) 자리 마련 — 미래 리사이즈/워터마크가 끼워질 토대',
            ],
        },
        {
            'title': '1순위 · 핸드폰 업로드 + R2 폴더분류 (ㄴ+ㄷ)', 'status': 'todo', 'when': '',
            'items': [
                '핸드폰 사파리 → 모음전 웹에서 사진 업로드 → 자동으로 R2 이동',
                'R2 안에서 SKU/카테고리별 폴더 분류',
                '이미지 대장(DB): 어느 SKU · 종류(원본/착샷/상세) · 버전 기록',
            ],
        },
        {
            'title': '2순위 · AI 착샷 생성 (ㄹ)', 'status': 'todo', 'when': '',
            'items': [
                '누끼컷 → AI(나노바나나 등)로 모델·포즈·배경 지정 착샷 생성',
                '특정 AI에 묶지 않고 갈아끼울 수 있는 구조',
                '폴더별 저장 후 R2',
            ],
        },
        {
            'title': '3순위 · AI 상세페이지 생성 (ㅁ)', 'status': 'todo', 'when': '',
            'items': [
                '정형 템플릿으로 상세페이지 자동 생성',
                '이미지 파일로 R2 저장',
            ],
        },
        {
            'title': '4순위 · 마켓 자동 업로드 (ㅂ)', 'status': 'todo', 'when': '',
            'items': [
                '판매처 API로 상세페이지 업로드',
                '기존 uploader 인프라 재활용',
            ],
        },
    ],
    'notes': [
        'ㄱ 촬영(핸드폰/카메라 누끼컷)은 사람 작업 — 프로그램 밖',
        'AI(ㄹ·ㅁ)는 모델이 자주 바뀜 → 갈아끼울 수 있게 설계',
        '① 팀 공유 ② 어디서든 사용 ③ 데이터 영구 저장 = 현재 구조(Supabase+Fly+R2)가 이미 충족',
    ],
}


@bp.get('/roadmap')
def roadmap_page():
    return render_template('roadmap.html', active='roadmap', roadmap=ROADMAP)

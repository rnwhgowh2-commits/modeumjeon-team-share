"""마켓 업로드 설정 페이지 — v6 Phase 4 (2026-05-07).

M2 레이아웃: 좌측 마켓 sub-nav (앱 로고 + 상태) + 우측 설정 폼.
현재 마켓 데이터는 정적 placeholder. Phase 5 에서 DB MarketUploadConfig 모델 도입 예정.
"""
from flask import Blueprint, render_template, request, jsonify

bp = Blueprint('market_upload', __name__)


# === 8 marketplaces — 실 브랜드 컬러 + 핸드폰 앱 아이콘 스타일 ===
MARKETS = [
    {
        'key': 'musinsa', 'nm': '무신사', 'logo_text': 'M', 'logo_class': 'ai-musinsa',
        'status': 'done', 'progress': 100,
        'category': '남성 > 아우터 > 코트 (무신사 카테 ID 105001)',
        'name_prefix': '[르무통] 레츠 브라운 코트',
        'margin': '35%', 'shipping': '무료배송',
        'option_map': 'S → S, M → M, L → L, XL → XL',
        'image_ratio': '4:5',
        'fee_rate': 10,
    },
    {
        'key': 'ssf', 'nm': 'SSF샵', 'logo_text': 'SSF', 'logo_class': 'ai-ssf',
        'status': 'done', 'progress': 100,
        'category': 'WOMEN > OUTER > COAT (SSF 카테 230410)',
        'name_prefix': '[르무통] 레츠 브라운 코트',
        'margin': '32%', 'shipping': '5만원 이상 무료',
        'option_map': 'S → 90, M → 95, L → 100, XL → 105',
        'image_ratio': '1:1',
        'fee_rate': 12,
    },
    {
        'key': 'cm29', 'nm': '29CM', 'logo_text': '29CM', 'logo_class': 'ai-29cm',
        'status': 'in_progress', 'progress': 50,
        'category': '여성 > 아우터 > 코트 (29CM 카테 200340)',
        'name_prefix': '[르무통] 레츠 브라운 코트',
        'margin': '38%', 'shipping': '무료배송 (조건 없음)',
        'option_map': 'S → S, M → M, L → L, XL → XL',
        'image_ratio': '4:5',
        'fee_rate': 12,
    },
    {
        'key': 'wconcept', 'nm': 'W컨셉', 'logo_text': 'W', 'logo_class': 'ai-wconcept',
        'status': 'pending', 'progress': 0,
        'category': '— 미설정', 'name_prefix': '— 미설정',
        'margin': '— 미설정', 'shipping': '— 미설정',
        'option_map': '— 미설정', 'image_ratio': '4:5',
        'fee_rate': 11,
    },
    {
        'key': 'lotte', 'nm': '롯데홈쇼핑', 'logo_text': '롯데', 'logo_class': 'ai-lotte',
        'status': 'pending', 'progress': 0,
        'category': '— 미설정', 'name_prefix': '— 미설정',
        'margin': '— 미설정', 'shipping': '— 미설정',
        'option_map': '— 미설정', 'image_ratio': '1:1',
        'fee_rate': 15,
    },
    {
        'key': 'cafe24', 'nm': '카페24', 'logo_text': 'C24', 'logo_class': 'ai-cafe24',
        'status': 'done', 'progress': 100,
        'category': '쇼핑몰 직배송 (자사몰)',
        'name_prefix': '레츠 브라운 코트',
        'margin': '50%', 'shipping': '5만원 이상 무료',
        'option_map': 'S, M, L, XL (옵션 동일)',
        'image_ratio': '1:1',
        'fee_rate': 0,
    },
    {
        'key': 'smartstore', 'nm': '스마트스토어', 'logo_text': 'N', 'logo_class': 'ai-smartstore',
        'status': 'pending', 'progress': 0,
        'category': '— 미설정', 'name_prefix': '— 미설정',
        'margin': '— 미설정', 'shipping': '— 미설정',
        'option_map': '— 미설정', 'image_ratio': '1:1',
        'fee_rate': 5,
    },
    {
        'key': 'coupang', 'nm': '쿠팡', 'logo_text': '쿠팡', 'logo_class': 'ai-coupang',
        'status': 'pending', 'progress': 0,
        'category': '— 미설정', 'name_prefix': '— 미설정',
        'margin': '— 미설정', 'shipping': '— 미설정',
        'option_map': '— 미설정', 'image_ratio': '1:1',
        'fee_rate': 13,
    },
]


@bp.route('/market-upload-config')
def index():
    """마켓별 업로드 설정 — 좌측 sub-nav + 우측 설정 폼."""
    active_key = request.args.get('m', 'cm29')
    active = next((m for m in MARKETS if m['key'] == active_key), MARKETS[0])
    done_count = sum(1 for m in MARKETS if m['status'] == 'done')
    return render_template(
        'market_upload/index.html',
        active='market_upload',
        markets=MARKETS,
        active_market=active,
        done_count=done_count,
        total_count=len(MARKETS),
    )

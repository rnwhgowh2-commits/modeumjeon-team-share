"""[E] 옵션 맵핑 템플릿 화면 — 색상 / 사이즈 (2개 sub-tab).

색상 템플릿 패널은 색상 사전(ColorDict) + 색상 템플릿(ColorTemplate) 통합 뷰.
사이즈도 동일 패턴 (SizeSuggestionRule + SizeTemplate).

[2026-08-12] 노션 「상품가공 > 하위탭 b-1·b-3」 — 화면 이름이 「가격 정책」에서
  「옵션 맵핑 템플릿」이 되고 가격 판이 빠졌다. 그래서 여기서 `PriceTemplate` 을
  더 이상 조회하지 않는다.
  [중요] 모델·API·가격 엔진은 **그대로 살아 있다**(사장님 확정 「화면에서만 빼기」).
     정책(MarketPolicy)은 가격 템플릿을 대체한 게 아니라 「정책이 못 채운 칸이
     되돌아갈 자리」다 — `lemouton/policy/as_template.py` 의 fallback.
     가격 템플릿을 만들고 고치는 입구는 모음전 상세(`/policies/product/<코드>`)와
     `/inventory/data/price-templates` 에 그대로 남아 있다.
"""
import json

from flask import Blueprint, jsonify, render_template

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, ColorDict
from lemouton.templates.models import (
    ColorTemplate, SizeTemplate,
    ColorSuggestionRule, SizeSuggestionRule,
)

bp = Blueprint('templates_page', __name__)


def _count_apply(s, attr_name, tpl_id):
    return s.query(Model).filter(getattr(Model, attr_name) == tpl_id).count()


def _templates_context(s) -> dict:
    """색상·사이즈 사전 + 템플릿 한 벌 — 화면(/templates)과 옵션 조합 창의

    「 템플릿 참고」 드로어가 같이 쓴다. 두 벌로 나누면 반드시 갈린다.
    """
    color_tpls = s.query(ColorTemplate).order_by(ColorTemplate.id).all()
    size_tpls = s.query(SizeTemplate).order_by(SizeTemplate.id).all()
    color_dict = s.query(ColorDict).order_by(ColorDict.color_code).all()
    color_rules = s.query(ColorSuggestionRule).order_by(ColorSuggestionRule.standard_code).all()
    size_rules = s.query(SizeSuggestionRule).order_by(SizeSuggestionRule.category, SizeSuggestionRule.standard_size).all()

    color_view = [
        {
            'tpl': t,
            'apply_count': _count_apply(s, 'color_template_id', t.id),
        }
        for t in color_tpls
    ]
    size_view = [
        {
            'tpl': t,
            'apply_count': _count_apply(s, 'size_template_id', t.id),
        }
        for t in size_tpls
    ]
    return {
        'color_view': color_view, 'size_view': size_view,
        'color_dict': color_dict, 'color_rules': color_rules, 'size_rules': size_rules,
    }


@bp.route('/templates')
def index():
    s = SessionLocal()
    try:
        ctx = _templates_context(s)
    finally:
        s.close()
    return render_template(
        'templates_page/index.html',
        active='templates',
        **ctx,
    )


@bp.get('/templates/api/data')
def api_data():
    """색상·사이즈 사전 + 템플릿을 JSON 으로 — 옵션 조합 창의 「 템플릿 참고」 드로어가 연다.

    `/templates` 화면과 같은 자료(`_templates_context`)를 그대로 읽는다.
    """
    s = SessionLocal()
    try:
        ctx = _templates_context(s)
        out = {
            'ok': True,
            'color': {
                'dict': [{'code': c.color_code, 'variants': json.loads(c.variants_json or '[]')}
                         for c in ctx['color_dict']],
                'templates': [{'id': v['tpl'].id, 'name': v['tpl'].name,
                               'codes': json.loads(v['tpl'].color_codes_json or '[]'),
                               'apply_count': v['apply_count']}
                              for v in ctx['color_view']],
            },
            'size': {
                'rules': [{'category': r.category, 'standard_size': r.standard_size,
                           'suggested_variant': r.suggested_variant}
                          for r in ctx['size_rules']],
                'templates': [{'id': v['tpl'].id, 'name': v['tpl'].name,
                               'category': v['tpl'].category,
                               'codes': json.loads(v['tpl'].size_codes_json or '[]'),
                               'apply_count': v['apply_count']}
                              for v in ctx['size_view']],
            },
        }
    finally:
        s.close()
    return jsonify(out)

"""[E] 템플릿 화면 — 가격 / 색상 / 사이즈 (3개 sub-tab).

색상 템플릿 패널은 색상 사전(ColorDict) + 색상 템플릿(ColorTemplate) 통합 뷰.
사이즈도 동일 패턴 (SizeSuggestionRule + SizeTemplate).
"""
from flask import Blueprint, render_template

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, ColorDict
from lemouton.templates.models import (
    PriceTemplate, ColorTemplate, SizeTemplate,
    ColorSuggestionRule, SizeSuggestionRule,
)

bp = Blueprint('templates_page', __name__)


def _count_apply(s, attr_name, tpl_id):
    return s.query(Model).filter(getattr(Model, attr_name) == tpl_id).count()


@bp.route('/templates')
def index():
    s = SessionLocal()
    try:
        price_tpls = s.query(PriceTemplate).order_by(PriceTemplate.id).all()
        color_tpls = s.query(ColorTemplate).order_by(ColorTemplate.id).all()
        size_tpls = s.query(SizeTemplate).order_by(SizeTemplate.id).all()
        color_dict = s.query(ColorDict).order_by(ColorDict.color_code).all()
        color_rules = s.query(ColorSuggestionRule).order_by(ColorSuggestionRule.standard_code).all()
        size_rules = s.query(SizeSuggestionRule).order_by(SizeSuggestionRule.category, SizeSuggestionRule.standard_size).all()

        price_view = [
            {
                'tpl': t,
                'apply_count': _count_apply(s, 'price_template_id', t.id),
            }
            for t in price_tpls
        ]
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
    finally:
        s.close()
    return render_template(
        'templates_page/index.html',
        active='templates',
        price_view=price_view,
        color_view=color_view,
        size_view=size_view,
        color_dict=color_dict,
        color_rules=color_rules,
        size_rules=size_rules,
    )

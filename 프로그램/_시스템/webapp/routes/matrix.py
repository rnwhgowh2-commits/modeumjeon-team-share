"""매트릭스 옵션 화면 — 목록 · 상세(격자에서 골라 파생 만들기) · 파생 상세.

시안 확정 (2026-07-30 사장님):
  · 격자에서 찍어 담기(V2) — 색상 줄 머리·사이즈 칸 머리를 누르면 통째로, 다시 누르면 풀림
  · 칸에 마우스를 올리면 표 형태 정보창(H3) — 옵션번호·브랜드 품번·소싱처별 관리번호·
    매입가·바로가기. 최저가에 「최저」 표시
  · 파생은 위쪽 띠 + 「원본으로 가기」(E1). 소싱처 URL·사입품번은 원본에서만 고친다

규칙은 lemouton/matrix/service.py 가 단일 진실 원천. 여기는 화면에 실어 나를 뿐이다.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint('matrix', __name__)

_SITE_LABEL = {
    'lemouton': '르무통 공홈', 'musinsa': '무신사', 'ssf': 'SSF샵',
    'lotteimall': '롯데아이몰', 'lotteon': '롯데온', 'ssg': 'SSG',
    'hmall': 'H몰', 'ss_lemouton': '스마트스토어 르무통',
}


def _rows_for(session, skus: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """격자에 필요한 옵션 정보 + 색상·사이즈 축.

    반환 rows: {sku, color, size, article_no, stock, sources:[{site,label,no,price,url}],
                min_price, src_count}
    """
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import Model, Option
    if not skus:
        return [], [], []
    opts = (session.query(Option).filter(Option.canonical_sku.in_(skus)).all())
    arts = dict(session.query(Model.model_code, Model.article_no).all())

    by_sku: dict[str, list[dict]] = {}
    for sku, site, url, no, price, stock in (
            session.query(OptionSourceLink.canonical_sku, SourceProduct.site,
                          SourceProduct.url, SourceOption.display_no,
                          SourceOption.current_price, SourceOption.current_stock)
            .join(SourceOption, SourceOption.source_product_id == SourceProduct.id)
            .join(OptionSourceLink, OptionSourceLink.source_option_id == SourceOption.id)
            .filter(OptionSourceLink.canonical_sku.in_(skus)).all()):
        by_sku.setdefault(sku, []).append({
            'site': site, 'label': _SITE_LABEL.get(site, site),
            'no': no, 'price': price, 'stock': stock, 'url': url})

    rows, colors, sizes = [], [], []
    for o in opts:
        srcs = sorted(by_sku.get(o.canonical_sku, []), key=lambda x: x['label'])
        prices = [x['price'] for x in srcs if x['price']]
        stocks = [x['stock'] for x in srcs if x['stock'] is not None and x['stock'] >= 0]
        if o.color_code not in colors:
            colors.append(o.color_code)
        if o.size_code not in sizes:
            sizes.append(o.size_code)
        rows.append({
            'sku': o.canonical_sku, 'color': o.color_code, 'size': o.size_code,
            'article_no': arts.get(o.model_code) or '',
            # 재고는 소싱처가 알려준 값 중 가장 큰 것 — 모르면 None(0 으로 지어내지 않는다)
            'stock': max(stocks) if stocks else None,
            'sources': srcs, 'src_count': len(srcs),
            'min_price': min(prices) if prices else None,
        })

    def _size_key(v):
        try:
            return (0, int(v))
        except (TypeError, ValueError):
            return (1, str(v))
    sizes.sort(key=_size_key)
    return rows, colors, sizes


@bp.route('/matrix')
def matrix_index():
    """매트릭스 옵션 목록 — 원본과 파생."""
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.matrix.service import member_skus
    s = SessionLocal()
    try:
        q = (s.query(MatrixOption).filter(MatrixOption.deleted_at.is_(None))
             .order_by(MatrixOption.kind.desc(), MatrixOption.created_at.desc()))
        kw = (request.args.get('q') or '').strip()
        items = []
        for mo in q.all():
            if kw and kw.lower() not in ((mo.name or '') + ' ' + (mo.display_no or '')
                                         + ' ' + (mo.model_code or '')).lower():
                continue
            items.append({
                'id': mo.id, 'no': mo.display_no, 'name': mo.name,
                'kind': mo.kind, 'is_origin': mo.kind == KIND_ORIGIN,
                'model_code': mo.model_code,
                'count': len(member_skus(s, mo)),
                'created_at': mo.created_at,
            })
    finally:
        s.close()
    return render_template('matrix/index.html', active='matrix', items=items,
                           kw=request.args.get('q') or '')


@bp.route('/matrix/<int:mo_id>')
def matrix_detail(mo_id: int):
    """원본이면 격자에서 골라 파생 만들기, 파생이면 담긴 옵션 + 원본으로 가기."""
    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.service import derived_of, edit_target, member_skus
    s = SessionLocal()
    try:
        mo = s.get(MatrixOption, mo_id)
        if mo is None or mo.deleted_at is not None:
            return render_template('errors/option_not_found.html', active='matrix',
                                   requested_code='매트릭스 옵션',
                                   requested_sku=str(mo_id)), 404
        skus = member_skus(s, mo)
        rows, colors, sizes = _rows_for(s, skus)
        gate = edit_target(s, mo)
        ctx = {
            'mo': {'id': mo.id, 'no': mo.display_no, 'name': mo.name,
                   'kind': mo.kind, 'model_code': mo.model_code},
            'rows': rows, 'colors': colors, 'sizes': sizes,
            'editable': gate['editable'], 'lock_reason': gate['reason'],
            'origin': ({'id': gate['origin'].id, 'no': gate['origin'].display_no,
                        'name': gate['origin'].name} if gate['origin'] else None),
            'derived': [{'id': d.id, 'no': d.display_no, 'name': d.name,
                         'count': len(member_skus(s, d))} for d in derived_of(s, mo)]
                       if gate['editable'] else [],
        }
    finally:
        s.close()
    return render_template('matrix/detail.html', active='matrix', **ctx)


@bp.post('/api/matrix/derived')
def create_derived_api():
    """파생 매트릭스 만들기 — {origin_id, name, skus:[...]}"""
    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.service import MatrixError, create_derived
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        org = s.get(MatrixOption, int(p.get('origin_id') or 0))
        if org is None:
            return jsonify({'ok': False, 'error': '원본을 찾을 수 없어요.'}), 404
        mo = create_derived(s, origin=org, name=p.get('name') or '',
                            skus=list(p.get('skus') or []))
        s.commit()
        return jsonify({'ok': True, 'id': mo.id, 'no': mo.display_no, 'name': mo.name})
    except MatrixError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        _log.exception('[matrix] 파생 생성 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()

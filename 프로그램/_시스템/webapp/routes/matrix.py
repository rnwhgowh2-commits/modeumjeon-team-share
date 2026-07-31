"""매트릭스 옵션 화면 — 목록 · 상세(격자에서 골라 파생 만들기) · 파생 상세.

시안 확정 (2026-07-30 사장님):
  · 격자에서 찍어 담기(V2) — 색상 줄 머리·사이즈 칸 머리를 누르면 통째로, 다시 누르면 풀림
  · 칸에 마우스를 올리면 표 형태 정보창(H3) — 옵션번호·브랜드 품번·소싱처별 관리번호·
    표면가·최종매입가·바로가기. 실제로 내는 돈(최종매입가)이 가장 싼 곳에 「최저」 표시
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


def _attach_final(session, by_sku: dict) -> None:
    """소싱처 칸마다 최종매입가를 주입한다 — 계산은 **하지 않고 불러 쓴다**.

    단일 진실 원천 = `api_pricing._attach_final_purchase` → `compute_breakdown`.
    여기서 다시 만들면 같은 값이 두 곳에서 갈린다(가격이 갈리면 곧 금전 손실).

    실패해도 화면은 뜬다 — 대신 최종매입가는 None(「—」) 으로 남긴다.
    표면가로 메우지 않는다(feedback_no_fallback_price_on_match_fail).
    """
    if not by_sku:
        return
    try:
        from webapp.routes.api_pricing import _attach_final_purchase
        _attach_final_purchase(session, by_sku)
    except Exception:      # noqa: BLE001
        _log.exception('[matrix] 최종매입가 주입 실패 — 표면가만 표시한다')
    for srcs in by_sku.values():
        for d in srcs:
            d.setdefault('final_purchase_price', None)


def _rows_for(session, skus: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """격자에 필요한 옵션 정보 + 색상·사이즈 축.

    반환 rows: {sku, color, size, article_no, stock,
                sources:[{site,label,no,surface,final,stock,url}],
                min_surface, min_final, src_count}

    🔴 가격은 **두 값을 나눠서** 준다.
       surface = 표면노출가 (소싱처 페이지에 크게 적힌 값)
       final   = 최종매입가 (혜택을 차례로 뺀, 우리가 실제로 내는 값)
       2026-07-31 이전엔 표면가 하나를 「매입가」라고 내보내서, 혜택이 큰 소싱처일수록
       실제보다 비싸 보였고 「최저」도 엉뚱한 소싱처를 가리켰다
       (memory: project_crawl_log_vs_final_price).
    """
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import Model, Option
    from lemouton.sourcing.source_ids import pricing_source_id
    if not skus:
        return [], [], []
    opts = (session.query(Option).filter(Option.canonical_sku.in_(skus)).all())
    arts = dict(session.query(Model.model_code, Model.article_no).all())

    by_sku: dict[str, list[dict]] = {}
    for sku, sp_id, site, url, no, price, stock in (
            session.query(OptionSourceLink.canonical_sku, SourceProduct.id,
                          SourceProduct.site, SourceProduct.url,
                          SourceOption.display_no,
                          SourceOption.current_price, SourceOption.current_stock)
            .join(SourceOption, SourceOption.source_product_id == SourceProduct.id)
            .join(OptionSourceLink, OptionSourceLink.source_option_id == SourceOption.id)
            .filter(OptionSourceLink.canonical_sku.in_(skus)).all()):
        by_sku.setdefault(sku, []).append({
            'site': site, 'label': _SITE_LABEL.get(site, site),
            'no': no, 'surface': price, 'stock': stock, 'url': url,
            # 아래 3개는 _attach_final_purchase 가 읽는 이름 그대로 (api_pricing 과 같은 계약).
            #   화면에 실어 보내기 전에 다시 걷어낸다.
            'crawled_price': price, 'source_id': pricing_source_id(site),
            'source_product_id': sp_id})
    _attach_final(session, by_sku)

    rows, colors, sizes = [], [], []
    for o in opts:
        srcs = sorted(by_sku.get(o.canonical_sku, []), key=lambda x: x['label'])
        for x in srcs:
            x['final'] = x.pop('final_purchase_price', None)
            for k in ('crawled_price', 'source_id', 'source_product_id'):
                x.pop(k, None)
        surfaces = [x['surface'] for x in srcs if x['surface']]
        finals = [x['final'] for x in srcs if x['final']]
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
            'min_surface': min(surfaces) if surfaces else None,
            'min_final': min(finals) if finals else None,
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


@bp.get('/api/matrix/price-history')
def price_history_api():
    """옵션 하나의 가격·재고 이력 — 노션 ④「X축 시간, Y축 가격, 소싱처별」.

    query: ?sku=SKU-XXXX &days=30
    응답: {ok, days, points:{소싱처라벨: [{t, price, stock, changed}]}, total, note}

    🔴 표면가 기준이다(혜택 차감 전). 최종매입가는 혜택 템플릿이 바뀌면 과거 시점
      값도 달라져 「그때 얼마였나」의 답이 못 된다 — 화면이 그 사실을 밝힌다.
    """
    from lemouton.sources import price_history as ph
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    sku = (request.args.get('sku') or '').strip()
    try:
        days = max(1, min(180, int(request.args.get('days') or 30)))
    except (TypeError, ValueError):
        days = 30
    if not sku:
        return jsonify({'ok': False, 'error': '옵션을 지정해 주세요.'}), 400
    s = SessionLocal()
    try:
        # 이 옵션이 걸린 소싱처 상품들 + 그 소싱처가 쓰는 색상·사이즈 표기
        links = (s.query(SourceProduct.id, SourceProduct.site,
                         SourceOption.color_text, SourceOption.size_text)
                 .join(SourceOption, SourceOption.source_product_id == SourceProduct.id)
                 .join(OptionSourceLink,
                       OptionSourceLink.source_option_id == SourceOption.id)
                 .filter(OptionSourceLink.canonical_sku == sku).all())
        points = {}
        for sp_id, site, color, size in links:
            label = _SITE_LABEL.get(site, site)
            for p in ph.series_for(s, source_product_ids=[sp_id],
                                   color=color, size=size, days=days):
                points.setdefault(label, []).append(
                    {'t': p['captured_at'], 'price': p['surface_price'],
                     'stock': p['stock'], 'changed': p['changed']})
        total = sum(len(v) for v in points.values())
    except Exception as e:      # noqa: BLE001
        _log.exception('[matrix] 가격 이력 조회 실패 sku=%s', sku)
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()
    return jsonify({
        'ok': True, 'days': days, 'points': points, 'total': total,
        # 「값이 아직 없다」와 「기능이 없다」는 다른 말이다 — 그대로 적는다.
        'note': ('가격 이력은 이제부터 모읍니다 — 아직 쌓인 값이 없어요. '
                 '크롤이 돌면 채워집니다(값이 바뀌면 그때마다, 안 바뀌면 하루 2번).'
                 if not total else
                 '소싱처 화면에 적힌 값(표면가) 기준이에요 — 혜택을 빼기 전 금액입니다.'),
    })


@bp.post('/api/matrix/build-bundle')
def build_bundle_api():
    """이 매트릭스의 옵션으로 새 모음전 상품 만들기 —
    {matrix_id, name, brand, category, skus?}"""
    from lemouton.matrix.build_service import create_bundle_from_matrix
    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.service import MatrixError
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        mx = s.get(MatrixOption, int(p.get('matrix_id') or 0))
        if mx is None:
            return jsonify({'ok': False, 'error': '묶음을 찾을 수 없어요.'}), 404
        m, made = create_bundle_from_matrix(
            s, matrix=mx, name=p.get('name') or '', brand=p.get('brand') or '',
            category=p.get('category') or '', model_code=p.get('model_code') or '',
            skus=list(p.get('skus') or []) or None)
        s.commit()
        return jsonify({'ok': True, 'model_code': m.model_code,
                        'no': m.display_no, 'options': made})
    except MatrixError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        _log.exception('[matrix] 상품 만들기 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


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

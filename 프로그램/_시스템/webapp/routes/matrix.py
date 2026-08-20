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
from urllib.parse import quote

from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint('matrix', __name__)

# 소싱처 한글 이름표는 lemouton/sources/site_labels.py 하나뿐이다 —
#   여기 또 적어 두면 한쪽만 고쳐져 화면마다 다른 이름이 뜬다(실제로 그랬다).
from lemouton.sources.site_labels import SITE_LABEL as _SITE_LABEL


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

    [중요] 가격은 **두 값을 나눠서** 준다.
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


def _index_stats(session, matrices) -> dict[int, dict]:
    """목록 열 집계 — 매트릭스별 담긴 상품 · 마켓 등록 · 소싱처 연결 · 재고 신호 · 최근 확인.

    [2026-08-05 A안] 매트릭스마다 쿼리를 돌리면 목록이 N+1 로 터진다 —
    원본(모델 소유)과 파생(멤버 명시) 두 갈래를 각각 **그룹 쿼리 몇 개**로 끝낸다.

    [중요] 마켓 등록의 정본 = MarketRegistration(market_product_id 있는 행).
       SetChannel·계정별 기록과 3벌 공존하는데, 옵션함 삭제 가드(optgen.py)가
       읽는 것과 같은 원천을 읽어야 화면끼리 안 갈린다.
    [중요] 품절 = 「그 옵션의 연결 소싱처 중 재고를 아는 곳이 있고, 아는 값이 전부 0」.
       모르는 것(None)은 품절이 아니라 「확인 불가」 — 여기 안 센다(무결성 원칙 1).
    [중요] 소싱처 연결은 **URL 단위 합집합** — 옵션 매칭(OptionSourceLink)이 아직 없어도
       모델에 붙인 주소(BundleSourceUrl)가 있으면 「연결됨」이다. 라이브 실측에서
       옵션 매칭만 세면 거의 전부 「—」로 뭉개져 실태와 달랐다(2026-08-05).
    """
    from sqlalchemy import func
    from lemouton.matrix.models import KIND_ORIGIN, BundleMatrixLink, MatrixOptionMember
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import BundleSourceUrl, Option
    from lemouton.uploader.models import MarketRegistration

    stats: dict[int, dict] = {
        mo.id: {'products': 0, 'markets': [], 'src': 0, 'src_fail': 0,
                'soldout': 0, 'seen': None, 'colors': 0, 'sizes': 0, 'active': 0,
                'skus': [], 'colorv': set(), 'sizev': set(), 'prodnames': [],
                '_urls': {}}
        for mo in matrices}
    origin_mid = {mo.model_code: mo.id for mo in matrices
                  if mo.kind == KIND_ORIGIN and mo.model_code}
    derived_ids = [mo.id for mo in matrices if mo.kind != KIND_ORIGIN]
    # 매트릭스 → 모델 (파생은 원본의 모델) — URL 은 모델에 붙는다
    origin_by_id = {mo.id: mo for mo in matrices if mo.kind == KIND_ORIGIN}
    mid_model = {}
    for mo in matrices:
        if mo.kind == KIND_ORIGIN:
            mid_model[mo.id] = mo.model_code
        elif mo.origin_id and mo.origin_id in origin_by_id:
            mid_model[mo.id] = origin_by_id[mo.origin_id].model_code

    # ── 담긴 상품 (이 묶음에서 만들어 간 상품 — 수 + 이름은 검색에 쓴다) ──
    from lemouton.sourcing.models import Model as _Model
    for mid, nm_disp, nm_raw in (
            session.query(BundleMatrixLink.matrix_option_id,
                          _Model.model_name_display, _Model.model_name_raw)
            .join(_Model, _Model.model_code == BundleMatrixLink.model_code).all()):
        if mid in stats:
            stats[mid]['products'] += 1
            stats[mid]['prodnames'].append(nm_disp or nm_raw or '')

    # 두 갈래 공통 — (매트릭스 key 식) 을 받아 sku 단위 집계를 채운다
    def _fill(key_col, base_join, key_to_mid):
        # 축·켜짐 + 검색용 값(SKU·색상·사이즈) — 집계 대신 원시 줄로 받아 한 번에 만든다
        for key, sku, color, size, active in (
                base_join(session.query(
                    key_col, Option.canonical_sku, Option.color_code,
                    Option.size_code, Option.is_active)).all()):
            mid = key_to_mid(key)
            if mid not in stats:
                continue
            st = stats[mid]
            st['skus'].append(sku)
            if active:
                st['active'] += 1
            if color:
                st['colorv'].add(color)
            if size:
                st['sizev'].add(size)
        for st in stats.values():
            st['colors'] = len(st['colorv'])
            st['sizes'] = len(st['sizev'])
        # 마켓 등록
        for key, market in (
                base_join(session.query(key_col, MarketRegistration.market))
                .join(MarketRegistration,
                      MarketRegistration.canonical_sku == Option.canonical_sku)
                .filter(MarketRegistration.market_product_id.isnot(None))
                .distinct().all()):
            mid = key_to_mid(key)
            if mid in stats and market not in stats[mid]['markets']:
                stats[mid]['markets'].append(market)
        # 소싱처 연결 — 옵션 매칭이 있는 소싱처 상품 (URL 로 모은다)
        for key, url, status, fetched in (
                base_join(session.query(key_col, SourceProduct.url,
                                        SourceProduct.last_status,
                                        SourceProduct.last_fetched_at))
                .join(OptionSourceLink,
                      OptionSourceLink.canonical_sku == Option.canonical_sku)
                .join(SourceOption, SourceOption.id == OptionSourceLink.source_option_id)
                .join(SourceProduct, SourceProduct.id == SourceOption.source_product_id)
                .distinct().all()):
            mid = key_to_mid(key)
            if mid in stats and url:
                stats[mid]['_urls'][url] = (status, fetched)
        # 품절 — 옵션별 「아는 재고의 최댓값」이 0 인 것만 (None 은 세지 않는다)
        for key, _sku, mx in (
                base_join(session.query(key_col, Option.canonical_sku,
                                        func.max(SourceOption.current_stock)))
                .join(OptionSourceLink,
                      OptionSourceLink.canonical_sku == Option.canonical_sku)
                .join(SourceOption, SourceOption.id == OptionSourceLink.source_option_id)
                .filter(SourceOption.current_stock.isnot(None))
                .group_by(key_col, Option.canonical_sku).all()):
            mid = key_to_mid(key)
            if mid in stats and mx == 0:
                stats[mid]['soldout'] += 1

    if origin_mid:
        _fill(Option.model_code,
              lambda q: q.filter(Option.model_code.in_(origin_mid)),
              lambda code: origin_mid.get(code))
    if derived_ids:
        _fill(MatrixOptionMember.matrix_option_id,
              lambda q: q.join(Option, Option.canonical_sku
                               == MatrixOptionMember.canonical_sku)
                         .filter(MatrixOptionMember.matrix_option_id.in_(derived_ids)),
              lambda mid: mid)

    # ── 모델에 붙인 주소(BundleSourceUrl)도 「연결된 소싱처」다 ──
    codes = {c for c in mid_model.values() if c}
    if codes:
        by_model: dict[str, list[str]] = {}
        for code, url in (session.query(BundleSourceUrl.model_code, BundleSourceUrl.url)
                          .filter(BundleSourceUrl.model_code.in_(codes)).distinct().all()):
            by_model.setdefault(code, []).append(url)
        all_urls = {u for us in by_model.values() for u in us}
        # 그 주소로 크롤된 기록이 있으면 상태·시각을 읽는다 (없으면 아직 안 돈 주소)
        meta = {url: (st, ft) for url, st, ft in
                (session.query(SourceProduct.url, SourceProduct.last_status,
                               SourceProduct.last_fetched_at)
                 .filter(SourceProduct.url.in_(all_urls)).all())} if all_urls else {}
        for mid, code in mid_model.items():
            for url in by_model.get(code, []):
                stats[mid]['_urls'].setdefault(url, meta.get(url, (None, None)))

    # URL 합집합 → 열 값 확정
    for st in stats.values():
        urls = st.pop('_urls')
        st['src'] = len(urls)
        st['src_fail'] = sum(1 for s_, _ in urls.values() if s_ in ('error', 'timeout'))
        fetched = [f for _, f in urls.values() if f]
        st['seen'] = max(fetched) if fetched else None
    return stats


@bp.route('/matrix')
def matrix_index():
    """매트릭스 옵션 목록. [2026-08-06 최종안] 사이드바 3구획 · 전체 검색 · 숨김 통합.

    검색은 이름·번호·모델코드에 더해 **브랜드·옵션번호(SKU)·색상·사이즈·담긴 상품명**
    까지 한 칸에서 된다(사장님 요청). 같은 검색 글자를 화면(즉시 거르기)과 서버(Enter)가
    같이 쓰도록 blob 으로 내려보낸다 — 두 곳의 기준이 갈리면 「Enter 치니 달라져요」가 된다.
    """
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.policy.fields import MARKET_LABEL
    from lemouton.sourcing.models import Model
    s = SessionLocal()
    try:
        q = (s.query(MatrixOption).filter(MatrixOption.deleted_at.is_(None))
             .order_by(MatrixOption.kind.desc(), MatrixOption.created_at.desc()))
        kw = (request.args.get('q') or '').strip().lower()
        matrices = q.all()
        stats = _index_stats(s, matrices)
        brands = dict(s.query(Model.model_code, Model.brand).all())
        items = []
        for mo in matrices:
            st = stats.get(mo.id, {})
            brand = brands.get(mo.model_code) or ''
            blob = ' '.join(filter(None, [
                mo.name or '', mo.display_no or '', mo.model_code or '', brand,
                *sorted(st.get('colorv', ())), *sorted(st.get('sizev', ())),
                *st.get('prodnames', ()), *st.get('skus', ())]))
            if kw and kw not in blob.lower():
                continue
            count = len(st.get('skus', ()))
            items.append({
                'id': mo.id, 'no': mo.display_no, 'name': mo.name,
                'kind': mo.kind, 'is_origin': mo.kind == KIND_ORIGIN,
                'model_code': mo.model_code, 'count': count,
                'brand': brand, 'blob': blob,
                # 숨김 = 재고 단독(단독_) + 빈 묶음(옵션 0) — 사장님 확정: 평소 볼 일 없음
                'hid': bool((mo.model_code or '').startswith('단독_') or count == 0),
                'products': st.get('products', 0),
                'markets': [{'key': m, 'label': MARKET_LABEL.get(m, m)}
                            for m in sorted(st.get('markets', []))],
                'src': st.get('src', 0), 'src_fail': st.get('src_fail', 0),
                'soldout': st.get('soldout', 0),
                'warn': bool(st.get('soldout', 0) or st.get('src_fail', 0)),
                'active': st.get('active', 0),
                'colors': st.get('colors', 0), 'sizes': st.get('sizes', 0),
                'seen': st.get('seen'),
            })
        _attach_stage_matrix(s, items)
    finally:
        s.close()
    from webapp.routes.bundles_tower import STAGES, STAGE_CLS, STAGE_LABEL_MATRIX
    # 🔴 판 숫자는 **화면에 실제로 보이는 것**만 센다.
    #    숨긴 묶음(단독_·빈 묶음)은 기본으로 안 보이는데 같이 세면
    #    「아직 상품 생성 안 함 89」라 해놓고 눌러도 3개만 나온다(라이브 실측).
    #    「숨긴 묶음 보기」를 켜면 화면 JS 가 숫자를 다시 센다.
    보임 = [i for i in items if not i.get('hid')]
    counts = {'all': len(보임), 'all_with_hidden': len(items)}
    for st in STAGES:
        counts['s%d' % st] = sum(1 for i in 보임 if i.get('stage') == st)
        counts['h%d' % st] = sum(1 for i in items if i.get('stage') == st)
    counts['none'] = sum(1 for i in 보임 if not i.get('stage'))
    counts['hnone'] = sum(1 for i in items if not i.get('stage'))
    return render_template('matrix/index.html', active='matrix', items=items,
                           kw=request.args.get('q') or '',
                           stages=STAGES, stage_label=STAGE_LABEL_MATRIX,
                           stage_cls=STAGE_CLS, stage_counts=counts)


def _attach_stage_matrix(session, items):
    """묶음마다 「어디까지 왔나」 4가지 상태 — 상품관리와 **같은 판정·같은 말**.

    묶음에 상품이 아직 없으면(옵션함이거나 model_code 없음) 상태 없음(=아직 상품 안 만듦).
    """
    from webapp.routes.bundles_tower import stages_for
    from lemouton.sourcing.models import Model

    codes = [i['model_code'] for i in items if i.get('model_code')]
    if not codes:
        return
    boxes = {c for (c,) in session.query(Model.model_code)
             .filter(Model.model_code.in_(codes),
                     Model.is_option_box.is_(True)).all()}
    got = stages_for(session, [c for c in codes if c not in boxes])
    for i in items:
        c = i.get('model_code')
        i['stage'] = got.get(c) if (c and c not in boxes) else None


def _attach_model(session, mo, rows) -> list[str]:
    """줄마다 **모델명**을 붙이고, 격자에 쓸 모델 목록을 돌려준다.

    [중요] [2026-08-12 노션 상품 c-2 옆에서 드러난 것 · 사장님 B2 확정]
       격자는 색상 × 사이즈 두 축만 그린다. 그래서 모델모음전(3축)은
       「메이트 블랙 250」과 「데일리 블랙 250」이 **같은 칸 하나에 겹쳤다**
       (실측: 옵션 3개 → 격자 2칸). 모델을 격자 위 탭으로 갈라 준다.

    모델이 없고 따로 적어 둔 모델명도 없는 묶음은 빈 목록 — 화면이 오늘 그대로 그린다.

    [중요] [2026-08-13] 여기는 **모델명을 알면서 빈 값을 내놓던 유일한 자리**였다.
       `model_name_of('', …)` 로 매트릭스 이름을 일부러 빈 문자열로 넘겼기 때문에,
       축 값을 못 믿는 옛 옵션(`len(vals) != len(names)`)은 모델명이 '' 이 되고
       격자에서 **조용히 사라졌다**(그 칸을 그리는 열쇠가 없어진다).
       그런데 그 옵션도 마켓에는 매트릭스 이름을 모델명으로 달고 나간다
       (`policy/to_payload._options_json`). 화면과 나가는 값이 달랐던 것이다.
       → 진짜 이름을 넘긴다. 「보는 것 = 나가는 것」.

    [중요] 넘기는 이름은 `mo.name`(매트릭스 이름)이 **아니라 모델(Model) 이름**이다.
       전송·대조가 모두 모델 이름을 쓰기 때문이다(to_payload·set_link_service·
       optgen box 셋 다 `model_name_display or model_name_raw or model_code`).
       파생 매트릭스도 옵션의 주인은 원본의 모델이라 같은 행을 본다.
       여기만 다른 이름을 쓰면 화면과 마켓이 또 갈린다.
    """
    from lemouton.matrix.option_name import model_name_of
    from lemouton.sourcing.models import BundleOptionStep, Model, Option

    origin_code = mo.model_code
    if origin_code is None:                       # 파생 — 원본에서 축을 읽는다
        from lemouton.matrix.service import origin_of
        org = origin_of(session, mo)
        origin_code = org.model_code if org else None
    axis_names = ([a for (a,) in session.query(BundleOptionStep.axis_name)
                   .filter_by(model_code=origin_code)
                   .order_by(BundleOptionStep.step_no).all()]
                  if origin_code else [])
    m = session.get(Model, origin_code) if origin_code else None
    origin_name = ((m.model_name_display or m.model_name_raw or m.model_code)
                   if m is not None else (mo.name or ''))
    bundle_model_name = m.bundle_model_name if m is not None else None

    from lemouton.sourcing.axis_slot import is_model_axis
    # 모델 축도 없고 따로 적어 둔 모델명도 없으면 — 오늘 그대로(모델명 없음).
    #   🔴 「축이 없다」만으로 걸러내면, 색상모음전에 모델명을 적어 둔 묶음이
    #      화면에서만 모델명을 잃는다. 조건을 둘 다 없을 때로 좁힌다.
    if not any(is_model_axis(a) for a in axis_names) and not (
            bundle_model_name or '').strip():
        for r in rows:
            r['model'] = ''
        return []

    skus = [r['sku'] for r in rows]
    opts = {o.canonical_sku: o for o in session.query(Option)
            .filter(Option.canonical_sku.in_(skus)).all()} if skus else {}
    models: list[str] = []
    for r in rows:
        o = opts.get(r['sku'])
        nm = (model_name_of(origin_name, o, axis_names,
                            bundle_model_name=bundle_model_name)
              if o is not None else '')
        r['model'] = nm
        if nm and nm not in models:
            models.append(nm)
    return models


def _made_from(session, mo, rows) -> list[dict]:
    """이 묶음으로 **이미 만든 상품**들 — 그때 넣은 값과 담은 칸까지.

    [중요] [2026-08-12 노션 상품 b-1] 조립대가 `BundleMatrixLink` 를 아예 안 봐서,
       상품을 만든 묶음을 열어도 **백지**로 떴다(라이브 실측: U…000189 는
       「상품 만듦」 배지인데 이름·브랜드·카테고리가 전부 빈 칸).
       목록 화면은 이미 보고 있었는데(optgen._attach_made) 조립대만 못 봤다.

    [중요] 「그때 담은 옵션」은 **(색상, 사이즈) 대조로 되짚는다 — 추정이다.**
       상품을 만들 때 옵션을 **복제**하면서 어느 원본에서 왔는지 안 남겼기 때문이다
       (build_service 는 copied_count 숫자만 남긴다). 복제는 color_code/size_code 를
       그대로 옮기고 격자도 (색상,사이즈)를 유일 키로 전제하므로 이 대조가 성립한다.
       화면은 이것을 「담은 조합」이라고 말한다 — 옵션번호라고 말하면 거짓이 된다.
    """
    from lemouton.matrix.models import BundleMatrixLink
    from lemouton.sourcing.models import Model, Option

    links = (session.query(BundleMatrixLink.model_code, BundleMatrixLink.created_at)
             .filter(BundleMatrixLink.matrix_option_id == mo.id)
             .order_by(BundleMatrixLink.created_at.desc()).all())
    if not links:
        return []
    codes = [c for c, _ts in links]
    models = {m.model_code: m for m in
              session.query(Model).filter(Model.model_code.in_(codes)).all()}
    # [2026-08-12 노션 상품 c-1] 정책이 붙었나 — 바로가기 목적지가 갈린다.
    #   붙었으면 그 상품의 정책·가격을 보러(`/policies/product/<code>`),
    #   안 붙었으면 붙이러(`/policies/apply?model=<code>`). 「없는데 보러 가기」는
    #   눌러도 볼 게 없는 헛걸음이다.
    from lemouton.policy.models import BundlePolicyLink
    has_policy = {c for (c,) in session.query(BundlePolicyLink.model_code)
                  .filter(BundlePolicyLink.model_code.in_(codes)).all()}
    # 상품이 가진 (색상, 사이즈) → 이 묶음 격자의 같은 칸
    sku_by_axis = {(r['color'], r['size']): r['sku'] for r in rows}
    out = []
    for code, _ts in links:
        m = models.get(code)
        if m is None:
            continue                      # 상품이 지워졌으면 조용히 건너뛴다
        picked = []
        for c, z in session.query(Option.color_code, Option.size_code) \
                .filter(Option.model_code == code).all():
            sku = sku_by_axis.get((c, z))
            if sku and sku not in picked:
                picked.append(sku)
        out.append({
            'code': code, 'no': m.display_no,
            'name': m.model_name_display or m.model_name_raw or code,
            'brand': m.brand or '', 'category': m.category or '',
            'picked': picked,
            'policy_url': (f'/policies/product/{quote(code)}' if code in has_policy
                           else f'/policies/apply?model={quote(code)}'),
            'policy_label': ('정책·가격 보기' if code in has_policy
                             else '정책 붙이러 가기'),
        })
    return out


def detail_context(mo_id: int):
    """상세 화면 재료 — 없거나 지워졌으면 None.

    [2026-08-06] 조립대 승격(설계서 §4)으로 이 재료를 두 화면이 나눠 쓴다:
    · `/matrix/<id>` (상품관리 > 모음전 옵션관리) — **보기 전용**
    · `/optgen/product/<id>` (옵션생성&상품생성 하위탭③) — 조립대(상품 만들기)
    화면을 복제하지 않고 재료 함수를 공유한다 — 두 벌이 되면 반드시 갈린다.
    """
    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.service import derived_of, edit_target, member_skus
    s = SessionLocal()
    try:
        mo = s.get(MatrixOption, mo_id)
        if mo is None or mo.deleted_at is not None:
            return None
        skus = member_skus(s, mo)
        rows, colors, sizes = _rows_for(s, skus)
        gate = edit_target(s, mo)
        return {
            'mo': {'id': mo.id, 'no': mo.display_no, 'name': mo.name,
                   'kind': mo.kind, 'model_code': mo.model_code},
            'rows': rows, 'colors': colors, 'sizes': sizes,
            'models': _attach_model(s, mo, rows),
            'made': _made_from(s, mo, rows),
            'editable': gate['editable'], 'lock_reason': gate['reason'],
            'origin': ({'id': gate['origin'].id, 'no': gate['origin'].display_no,
                        'name': gate['origin'].name} if gate['origin'] else None),
            'derived': [{'id': d.id, 'no': d.display_no, 'name': d.name,
                         'count': len(member_skus(s, d))} for d in derived_of(s, mo)]
                       if gate['editable'] else [],
        }
    finally:
        s.close()


@bp.route('/matrix/<int:mo_id>')
def matrix_detail(mo_id: int):
    """모음전 옵션관리 상세 — **보기 전용** (설계서 §4 확정).

    상품 만들기(조립대)는 「옵션생성 & 상품생성 > 모음전 상품 생성」
    (`/optgen/product/<id>`)에 있다 — 관리 탭은 확인, 작업은 생성 탭.
    """
    ctx = detail_context(mo_id)
    if ctx is None:
        # 🔴 종전엔 「모음전 코드: 매트릭스 옵션」으로 떴다 — 이름표도 값도 틀렸다.
        #   여기서 못 찾은 것은 **옵션 묶음 번호**(mo_id) 하나뿐이다.
        return render_template('errors/option_not_found.html', active='matrix',
                               requested_code='',
                               sku_label='옵션 묶음 번호',
                               requested_sku=str(mo_id)), 404
    return render_template('matrix/detail.html', active='matrix',
                           assembly=False, detail_base='/matrix/', **ctx)


@bp.get('/api/matrix/<int:mo_id>/panel')
def matrix_panel_api(mo_id: int):
    """[2026-08-05 A안] 오른쪽 미끄럼판 — 요약 · 연결 관계 · 소싱처 · 이력.

    목록에서 행을 누르면 이 API 하나로 4탭을 다 채운다.
    가격은 _rows_for(→ api_pricing 의 최종매입가 계산)를 **불러 쓴다** — 재구현 금지.
    """
    import json as _json
    from sqlalchemy import func
    from lemouton.matrix.models import (
        KIND_ORIGIN, BundleMatrixLink, MatrixOption,
    )
    from lemouton.matrix.service import derived_of, member_skus, origin_of
    from lemouton.policy.fields import MARKET_LABEL
    from lemouton.sources.models import SourceProduct
    from lemouton.sourcing.models import BundleRun, Model, Option
    from lemouton.uploader.models import MarketRegistration

    s = SessionLocal()
    try:
        mo = s.get(MatrixOption, mo_id)
        if mo is None or mo.deleted_at is not None:
            return jsonify({'ok': False, 'error': '묶음을 찾을 수 없어요.'}), 404
        origin = origin_of(s, mo)
        model = s.get(Model, origin.model_code) if (origin and origin.model_code) else None
        skus = member_skus(s, mo)
        rows, colors, sizes = _rows_for(s, skus)
        active = dict(s.query(Option.canonical_sku, Option.is_active)
                      .filter(Option.canonical_sku.in_(skus)).all()) if skus else {}

        # ── 요약: 축 격자 (칸 숫자 = 연결 소싱처 수 · 꺼진 옵션은 흐리게) ──
        by_key = {(r['color'], r['size']): r for r in rows}
        # [2026-08-06 사장님 요청] 칸에 소싱처 수만 두지 않고 **최종매입가·재고**까지 같이.
        #   final 은 계산해 온 값을 그대로 실어 보낸다(표면가로 메우지 않음).
        def _best_label(r) -> str | None:
            """그 값이 **어느 소싱처에서 나온 것인지**. 최저 최종매입가 기준,
            최종매입가를 모르면 표면가 기준(소싱처 탭의 「최저」 판정과 같은 규칙)."""
            pay = [(x['final'] or x['surface'], x['label']) for x in r['sources']
                   if (x['final'] or x['surface'])]
            return min(pay)[1] if pay else None

        grid = [{'color': c, 'cells': [
                    ({'sku': r['sku'], 'n': r['src_count'],
                      'final': r['min_final'], 'surface': r['min_surface'],
                      'stock': r['stock'], 'best': _best_label(r),
                      'active': bool(active.get(r['sku'], True))}
                     if (r := by_key.get((c, z))) else None)
                    for z in sizes]} for c in colors]

        # ── 연결 관계: 원본 → 파생들 → 만들어 간 상품들 → 상품별 마켓 등록 ──
        def _products_of(mid: int) -> list[dict]:
            out = []
            for link, m in (s.query(BundleMatrixLink, Model)
                            .join(Model, Model.model_code == BundleMatrixLink.model_code)
                            .filter(BundleMatrixLink.matrix_option_id == mid)
                            .order_by(BundleMatrixLink.created_at.desc()).all()):
                # 이 상품의 마켓 등록 — 정본 = MarketRegistration(market_product_id 있는 행)
                marks = [{'key': mk, 'label': MARKET_LABEL.get(mk, mk), 'n': n}
                         for mk, n in
                         (s.query(MarketRegistration.market, func.count())
                          .join(Option, Option.canonical_sku
                                == MarketRegistration.canonical_sku)
                          .filter(Option.model_code == m.model_code,
                                  MarketRegistration.market_product_id.isnot(None))
                          .group_by(MarketRegistration.market).all())]
                out.append({'model_code': m.model_code, 'no': m.display_no,
                            'name': (m.model_name_display or m.model_name_raw
                                     or m.model_code),
                            'copied': link.copied_count, 'markets': marks})
            return out

        tree = {
            'origin': ({'id': origin.id, 'no': origin.display_no, 'name': origin.name,
                        'here': origin.id == mo.id} if origin else None),
            'derived': [{'id': d.id, 'no': d.display_no, 'name': d.name,
                         'count': len(member_skus(s, d)), 'here': d.id == mo.id,
                         'products': _products_of(d.id)}
                        for d in (derived_of(s, origin) if origin else [])],
            'products': _products_of(origin.id) if origin else [],
        }

        # ── 소싱처: URL 단위로 합쳐 보여준다 ──
        # 옵션 매칭이 있으면 매칭 수·최저가, 없어도 모델에 붙인 주소(BundleSourceUrl)는
        # 「주소만(매칭 0)」으로 보인다 — 주소가 있는데 「—」로 뭉개면 실태와 다르다.
        from lemouton.sourcing.models import BundleSourceUrl
        agg: dict[str, dict] = {}
        for r in rows:
            for x in r['sources']:
                a = agg.setdefault(x['url'] or x['label'], {
                    'label': x['label'], 'url': x['url'], 'matched': 0,
                    'surface': None, 'final': None, 'stocks': []})
                a['matched'] += 1
                for k in ('surface', 'final'):
                    if x[k] and (a[k] is None or x[k] < a[k]):
                        a[k] = x[k]
                if x['stock'] is not None:
                    a['stocks'].append(x['stock'])
        burls = (s.query(BundleSourceUrl)
                 .filter(BundleSourceUrl.model_code == origin.model_code).all()
                 if origin and origin.model_code else [])
        for b in burls:
            agg.setdefault(b.url, {
                'label': _SITE_LABEL.get(b.source_key, b.source_key)
                         + (f' · {b.label}' if b.label else ''),
                'url': b.url, 'matched': 0, 'surface': None, 'final': None,
                'stocks': []})
        meta, sp_row = {}, {}
        urls = [u for u in agg if u and u.startswith('http')]
        if urls:
            for sp in (s.query(SourceProduct)
                       .filter(SourceProduct.url.in_(urls)).all()):
                meta[sp.url] = {'status': sp.last_status,
                                'fetched': (sp.last_fetched_at.isoformat()
                                            if sp.last_fetched_at else None)}
                sp_row[sp.url] = sp
        sources = []
        for url, a in sorted(agg.items(), key=lambda kv: kv[1]['label']):
            stocks = a.pop('stocks')
            sp = sp_row.get(url)
            # 재고: 아는 값이 하나라도 >0 → 있음 / 아는 값 전부 0 → 품절 / 모름 → 확인 불가.
            # 옵션 매칭이 없으면 크롤이 그 주소에서 읽은 값(SourceProduct)으로 대신 본다.
            if stocks:
                a['stock'] = '있음' if any(v > 0 for v in stocks) else '품절'
            elif sp is not None and sp.last_stock is not None:
                a['stock'] = '있음' if sp.last_stock > 0 else '품절'
            else:
                a['stock'] = None
            if a['surface'] is None and sp is not None:
                a['surface'] = sp.last_price
            a['total'] = len(skus)
            a.update(meta.get(url, {'status': None, 'fetched': None}))
            sources.append(a)

        # ── 이력: 이 묶음(원본 모델)의 최근 실행 기록 ──
        runs = []
        if origin and origin.model_code:
            for r in (s.query(BundleRun).filter(BundleRun.model_code == origin.model_code)
                      .order_by(BundleRun.started_at.desc()).limit(8).all()):
                note = ''
                try:
                    d = _json.loads(r.details_json or '{}')
                    srcs = d.get('sources') or {}
                    ok = sum(1 for v in srcs.values() if v.get('ok'))
                    if srcs:
                        note = f'소싱처 {ok}/{len(srcs)} 성공'
                except Exception:      # noqa: BLE001
                    pass
                runs.append({'phase': r.phase, 'status': r.status, 'note': note,
                             'at': r.started_at.isoformat() if r.started_at else None})

        return jsonify({'ok': True, 'summary': {
            'id': mo.id, 'no': mo.display_no, 'name': mo.name, 'kind': mo.kind,
            'model_code': mo.model_code or (origin.model_code if origin else None),
            'brand': model.brand if model else None,
            'category': model.category if model else None,
            'count': len(skus), 'active': sum(1 for v in active.values() if v),
            'sizes': sizes, 'grid': grid,
            'origin': ({'id': origin.id, 'no': origin.display_no}
                       if origin and origin.id != mo.id else None),
            'editable': mo.kind == KIND_ORIGIN,
        }, 'tree': tree, 'sources': sources, 'runs': runs})
    except Exception as e:      # noqa: BLE001
        _log.exception('[matrix] 미끄럼판 조회 실패 id=%s', mo_id)
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.get('/api/matrix/price-history')
def price_history_api():
    """옵션 하나의 가격·재고 이력 — 노션 ④「X축 시간, Y축 가격, 소싱처별」.

    query: ?sku=SKU-XXXX &days=30
    응답: {ok, days, points:{소싱처라벨: [{t, price, stock, changed}]}, total, note}

    [중요] 표면가 기준이다(혜택 차감 전). 최종매입가는 혜택 템플릿이 바뀌면 과거 시점
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


@bp.get('/api/matrix/product-info')
def product_info_api():
    """노션 ④ 상품 관리 —「적용된 정책 보기」+「카테고리 맵핑 보기」.

    query: ?model=<model_code>
    응답: {ok, policy:{...}|None, category:{sources:[...], rows:[...]}}

    [중요] 값을 지어내지 않는다. 정책이 안 붙었으면 None, 맵핑이 없으면 빈 목록이고
      화면이 「아직 없다」고 말한다.
    """
    from lemouton.policy.fields import MARKET_LABEL, MARKETS
    from lemouton.policy.service import policy_of, readiness, values_for
    from lemouton.registration.models import CategoryMapRow
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import Option
    code = (request.args.get('model') or '').strip()
    if not code:
        return jsonify({'ok': False, 'error': '상품을 지정해 주세요.'}), 400
    s = SessionLocal()
    try:
        # ── 적용된 정책 (노션 「정책명 > 적용된 정책 항목」) ──
        pol = policy_of(s, code)
        policy = None
        if pol is not None:
            rd = readiness(s, pol.id)
            policy = {
                'id': pol.id, 'name': pol.name, 'is_default': bool(pol.is_default),
                'markets': [{
                    'market': mk, 'label': MARKET_LABEL.get(mk, mk),
                    'filled': rd[mk]['filled'], 'total': rd[mk]['total'],
                    'price_ready': rd[mk]['price_ready'],
                    # 무엇을 정했는지 — 항목 이름만(값은 정책 화면에서 본다)
                    'items': sorted(values_for(s, pol.id, mk).keys()),
                } for mk, _ in MARKETS],
            }

        # ── 카테고리 맵핑 (노션 「소싱처 카테고리 ↔ 판매처별 등록된 카테고리」) ──
        skus = [o.canonical_sku for o in
                s.query(Option).filter(Option.model_code == code).all()]
        src, seen = [], set()
        if skus:
            for site, path in (s.query(SourceProduct.site, SourceProduct.category_path)
                               .join(SourceOption,
                                     SourceOption.source_product_id == SourceProduct.id)
                               .join(OptionSourceLink,
                                     OptionSourceLink.source_option_id == SourceOption.id)
                               .filter(OptionSourceLink.canonical_sku.in_(skus))
                               .distinct().all()):
                if path and (site, path) not in seen:
                    seen.add((site, path))
                    src.append({'site': site, 'label': _SITE_LABEL.get(site, site),
                                'path': path})
        rows = []
        for x in src:
            for r in (s.query(CategoryMapRow)
                      .filter(CategoryMapRow.source_id == x['site'],
                              CategoryMapRow.source_path == x['path']).all()):
                rows.append({'source': x['label'], 'source_path': x['path'],
                             'market': r.market, 'code': r.market_cat_code,
                             'path': r.market_cat_path, 'status': r.status})
    except Exception as e:      # noqa: BLE001
        _log.exception('[matrix] 상품 정보 조회 실패 model=%s', code)
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()
    return jsonify({'ok': True, 'policy': policy,
                    'category': {'sources': src, 'rows': rows}})


@bp.post('/api/matrix/build-bundle')
def build_bundle_api():
    """이 매트릭스의 옵션으로 새 모음전 상품 만들기 —
    {matrix_id, name, brand, category, skus?}

    [2026-08-12 노션 상품 c-2] `matrix_ids` 로 **여러 묶음을 한 상품**으로도 만든다.
    옛 `matrix_id` 는 그대로 받는다 — 조립대 화면이 그걸 보낸다.
    """
    from lemouton.matrix.build_service import create_bundle_from_matrix
    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.service import MatrixError
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        ids = [int(x) for x in (p.get('matrix_ids') or []) if str(x).strip().isdigit()]
        if not ids and p.get('matrix_id'):
            ids = [int(p.get('matrix_id') or 0)]
        mats = [s.get(MatrixOption, i) for i in ids]
        if not ids or any(m is None for m in mats):
            return jsonify({'ok': False, 'error': '묶음을 찾을 수 없어요.'}), 404
        skipped: list = []
        m, made = create_bundle_from_matrix(
            s, matrices=mats, name=p.get('name') or '', brand=p.get('brand') or '',
            category=p.get('category') or '', model_code=p.get('model_code') or '',
            skus=list(p.get('skus') or []) or None, skipped_out=skipped)
        s.commit()
        return jsonify({'ok': True, 'model_code': m.model_code,
                        'no': m.display_no, 'options': made,
                        # 겹쳐서 한 번만 담은 조합 — 조용히 버리지 않는다.
                        'skipped': skipped})
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

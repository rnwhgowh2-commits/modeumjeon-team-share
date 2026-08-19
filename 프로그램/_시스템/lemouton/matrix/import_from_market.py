# -*- coding: utf-8 -*-
"""내마켓 불러오기 — 마켓 상품에서 옵션함이 **태어난다** (사장님 확정 흐름).

「맞추기」가 아니라 「생성」이다: 우리 쪽이 비어 있는 상태에서 마켓의 색상·사이즈가
그대로 우리 축이 되고, 옵션이 1:1 로 태어난다. 그래서 매칭 실패라는 게 없다 —
태어나면서 **그 마켓의 상품번호·옵션번호가 저절로 기록**된다.

🔴 이 기록이 이 기능의 본체다. 안 남기면 나중에 정책을 씌워 전송할 때 프로그램이
   「처음 올리는 상품」으로 알고, **이미 팔던 그 마켓에 같은 상품을 하나 더** 올린다
   (send/runner.py — 마켓 상품번호가 있으면 갱신, 없으면 신규).
   지금은 옵션 단위(MarketRegistration)와 묶음 단위(MarketProductGroup.model_code)에
   남긴다. 상품(구성) 단위(SetChannel)는 상품 생성 단계에서 이 기록을 읽어 잇는다.

지금은 **스마트스토어만** — 다른 마켓은 축 모양(1축 조합값 등)이 달라 마켓마다
따로 검증해야 한다. 검증 없이 열면 엉뚱한 축이 태어난다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 아직 이 흐름을 검증한 마켓. 하나씩 실측으로 넓힌다 — 미검증 마켓을 열지 않는다.
SUPPORTED_MARKETS = ('smartstore',)


def _fetch_one(session, *, market: str, account_key: str,
               market_product_id: str, fetcher=None) -> dict:
    """마켓 상품 1건을 읽어 축 재료로 정리한다 — DB 에 아무것도 쓰지 않는다.

    단건 가져오기(`import_market_product`)와 여러 개 병합 가져오기
    (`import_market_products_merged`)가 공유하는 검증+조회 앞부분.
    실패하면 ValueError — 호출자는 이 단계에서 아무것도 안 만들었으니
    되돌릴 것도 없다(all-or-nothing 이 저절로 지켜진다).
    """
    from lemouton.catalog.models import MarketProduct
    from lemouton.sourcing.models_v2 import UploadAccount

    market = (market or '').strip()
    if market not in SUPPORTED_MARKETS:
        raise ValueError(f'아직 {market or "?"} 는 축까지 못 가져옵니다 — '
                         f'지금은 스마트스토어만 됩니다.')
    pid = str(market_product_id or '').strip()
    if not pid:
        raise ValueError('마켓 상품번호가 비어 있습니다.')

    # 캐시 행 — 이름·브랜드의 원천 + 「이미 가져옴」 표시 대상.
    mp = (session.query(MarketProduct)
          .filter_by(market=market, market_product_id=pid)
          .filter(MarketProduct.deleted_at.is_(None))
          .order_by(MarketProduct.id.desc()).first())
    if mp is not None and mp.group_id is not None:
        raise ValueError('이미 가져온 상품입니다 — 같은 상품을 두 번 가져오면 '
                         '옵션 묶음이 둘로 갈립니다.')

    # 계정 키 → env_prefix (시크릿은 .env 에만 있다).
    acc = (session.query(UploadAccount)
           .filter_by(market=market, account_key=(account_key or '').strip(),
                      is_active=True).first())
    if acc is None:
        raise ValueError(f'모르는 계정입니다: {account_key!r}')

    if fetcher is None:
        from lemouton.uploader.market_fetch import fetch_market_options as fetcher
    fr = fetcher(market, pid, env_prefix=acc.env_prefix)
    if not fr.success:
        raise ValueError(f'마켓에서 옵션을 못 읽었습니다 — {fr.error}')
    if not fr.options:
        raise ValueError('마켓 상품에 옵션이 없습니다 — '
                         '「직접 만들기」로 색상·사이즈를 짜 주세요.')

    # ── 마켓 옵션 → 축 (색상·사이즈) ──────────────────────────────────
    #   값은 마켓이 준 그대로 쓴다 — 다듬으면(BLACK→블랙) 어느 옵션이 어느
    #   마켓 옵션에서 왔는지 흐려진다. 이름 정리는 만들고 나서 기존 개명 기능으로.
    colors: list[str] = []
    sizes: list[str] = []
    combos: list[list[str]] = []
    by_combo: dict[tuple, str] = {}      # (색,사이즈) → 마켓 옵션번호
    skipped, dup = [], []
    for o in fr.options:
        c = (o.color or '').strip()
        z = (o.size or '').strip()
        if not c and not z:
            skipped.append(str(o.option_id))          # 축이 아예 없는 옵션 — 못 만든다
            continue
        key = (c, z)
        if key in by_combo:
            dup.append(str(o.option_id))              # 같은 조합 두 벌 — 첫 것만
            continue
        by_combo[key] = str(o.option_id)
        if c and c not in colors:
            colors.append(c)
        if z and z not in sizes:
            sizes.append(z)
        combos.append([v for v in (c, z) if v])
    if not combos:
        raise ValueError('색상·사이즈가 있는 옵션이 하나도 없습니다.')

    name = (mp.name if mp is not None else None) or (fr.product_name or '').strip()
    if not name:
        raise ValueError('상품 이름을 못 읽었습니다 — 이름 없이 만들 수 없습니다.')
    brand = ((mp.brand if mp is not None else None) or '').strip()

    return {'market': market, 'pid': pid, 'mp': mp, 'acc': acc,
           'name': name, 'brand': brand, 'colors': colors, 'sizes': sizes,
           'combos': combos, 'by_combo': by_combo, 'skipped': skipped, 'dup': dup}


def _combo_key(vals: list[str], colors: set[str]) -> tuple:
    """옵션의 축 값(모델명 뺀 나머지) → `by_combo` 열쇠 `(색,사이즈)`.

    1축뿐이면 그 값이 색상 소속인지 사이즈 소속인지 `colors` 집합으로 가른다
    (마켓이 색상만 준 상품과 사이즈만 준 상품을 구별하는 유일한 단서).
    """
    if len(vals) >= 2:
        return (vals[0], vals[1])
    if len(vals) == 1:
        return (vals[0], '') if vals[0] in colors else ('', vals[0])
    return ('', '')


def import_market_product(session, *, market: str, account_key: str,
                          market_product_id: str, fetcher=None) -> dict:
    """마켓 상품 1건 → 옵션함 + 옵션들 + 마켓 연결 기록.

    fetcher: (market, product_id, env_prefix=) -> FetchResult. 테스트는 가짜 주입.
    실패하면 ValueError — **아무것도 만들지 않는다**(반쪽짜리 옵션함 금지).
    커밋은 호출자(라우트) 몫이다.
    """
    from lemouton.catalog.models import MarketProductGroup
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    from lemouton.sourcing.option_combo import option_axis_values
    from lemouton.sourcing.option_service import create_combination_options
    from lemouton.uploader.repository import upsert_registration

    got = _fetch_one(session, market=market, account_key=account_key,
                     market_product_id=market_product_id, fetcher=fetcher)
    market, pid, mp = got['market'], got['pid'], got['mp']
    name, brand = got['name'], got['brand']
    colors, sizes, combos, by_combo = got['colors'], got['sizes'], got['combos'], got['by_combo']

    steps = []
    if colors:
        steps.append({'axis_name': '색상', 'values': colors})
    if sizes:
        steps.append({'axis_name': '사이즈', 'values': sizes})

    # ── 옵션함 생성 + 조합 그대로 옵션 생성 ──────────────────────────
    #   🔴 selected=combos — 전체 조합(cartesian)이 아니라 **마켓에 실제로 있는
    #     조합만** 만든다. 마켓에 베이지 230 이 없는데 우리가 만들면, 소싱처만
    #     붙이면 팔리는 것처럼 보이는 유령 조합이 된다.
    memo = f'불러온 곳: {market} {pid} ({got["acc"].account_key})'
    # band=1 — 「직접」 생성(band 없음)과 순번 앞자리로 갈린다. 품번체계(자리수)는
    #   그대로고 scope 만 'U:1' 로 완전히 새로 시작해 기존 번호와 절대 안 겹친다.
    box = create_option_box(session, name=name,
                            brand=(brand or '르무통'), memo=memo, band=1)
    create_combination_options(session, box.model_code, steps, selected=combos)
    session.flush()

    # ── 태어난 옵션 ↔ 마켓 옵션번호 — 1:1 기록 ───────────────────────
    color_set = set(colors)
    linked = 0
    for opt in session.query(Option).filter_by(model_code=box.model_code).all():
        key = _combo_key(option_axis_values(opt), color_set)
        moid = by_combo.get(key)
        if moid is None:
            logger.warning('[내마켓] %s 옵션 %s 에 짝 마켓옵션이 없음(예상 밖)',
                           box.model_code, key)
            continue
        upsert_registration(session, canonical_sku=opt.canonical_sku,
                            market=market, market_product_id=pid,
                            market_option_id=moid, status='linked')
        linked += 1

    # ── 「이미 가져옴」 표시 — 캐시 행에 묶음을 붙인다 ────────────────
    #   groups.create_group 은 안에서 commit 을 해 되돌리기가 끊긴다 → 직접 만든다.
    if mp is not None:
        g = MarketProductGroup(name=name, brand=(brand or None),
                               model_code=box.model_code)
        session.add(g)
        session.flush()
        mp.group_id = g.id

    return {'code': box.model_code, 'name': name,
            'options': len(combos), 'linked': linked,
            'colors': len(colors), 'sizes': len(sizes),
            'skipped': got['skipped'], 'dup': got['dup']}


def import_market_products_merged(session, *, items: list[dict], name: str,
                                  brand: str, fetcher=None) -> dict:
    """마켓 상품 여러 개 → **「모델」 축 매트릭스 1개**로 합쳐 태어난다.

    사장님 확정(2026-08-19): 상품마다 매트릭스를 따로 만들지 않고, 상품마다
    「모델」 축 값 하나씩을 받는 매트릭스 1개로 합친다. 단건 가져오기와 같은
    원칙 — 실패하면 아무것도 안 만든다, 마켓 상품번호·옵션번호를 빠짐없이 기록,
    이미 가져온 상품은 다시 못 담는다.

    Args:
        items: `[{'market','account_key','market_product_id','model_name'}, …]`.
            `model_name` 은 이 상품이 「모델」 축에서 받을 값 — 화면에서
            상품명으로 미리 채워 주고 사장님이 고칠 수 있게 한다.
        name, brand: 매트릭스 이름·브랜드 — 사장님이 팝업에서 확인/수정한 값을
            그대로 받는다(개별 상품의 캐시 이름·브랜드가 아니라).

    🔴 상품마다 옵션 구성(색상·사이즈 있고 없음)이 다르면 격자가 어긋나므로
       합치지 않고 거절한다 — 조용히 빈 칸으로 채우면 「있는 척」이 된다.
    """
    from lemouton.catalog.models import MarketProductGroup
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    from lemouton.sourcing.option_combo import option_axis_values
    from lemouton.sourcing.option_service import create_combination_options
    from lemouton.uploader.repository import upsert_registration

    items = items or []
    if not items:
        raise ValueError('상품을 하나도 고르지 않았습니다.')

    # ① 모델명부터 확인 — 네트워크를 타기 전에 빨리 걸러낸다.
    model_names: list[str] = []
    for it in items:
        mn = ((it or {}).get('model_name') or '').strip()
        if not mn:
            raise ValueError('모델명이 빈 상품이 있습니다 — 모델마다 이름을 적어주세요.')
        model_names.append(mn)
    if len(model_names) != len(set(model_names)):
        raise ValueError('모델명이 서로 겹칩니다 — 상품마다 다른 이름을 적어주세요.')

    # ② 상품마다 읽는다(순서대로, 실패하면 그 자리에서 멈춘다 — 아직 아무것도 안 썼다).
    results = [_fetch_one(session, market=it.get('market') or '',
                          account_key=it.get('account_key') or '',
                          market_product_id=it.get('market_product_id') or '',
                          fetcher=fetcher)
              for it in items]

    # ③ 축 구성이 상품마다 같은지 — 다르면 격자가 어긋난다.
    shapes = {(bool(r['colors']), bool(r['sizes'])) for r in results}
    if len(shapes) > 1:
        raise ValueError('상품마다 옵션 구성이 서로 달라 하나로 합칠 수 없습니다 — '
                         '색상·사이즈 구성이 같은 상품끼리만 함께 고르세요.')
    has_color, has_size = next(iter(shapes))

    # ④ 합친 축 — 모델(필수) + 색상(있으면) + 사이즈(있으면). 값은 첫 등장 순서.
    steps = [{'axis_name': '모델', 'values': model_names}]
    if has_color:
        merged_colors: list[str] = []
        for r in results:
            merged_colors += [c for c in r['colors'] if c not in merged_colors]
        steps.append({'axis_name': '색상', 'values': merged_colors})
    if has_size:
        merged_sizes: list[str] = []
        for r in results:
            merged_sizes += [z for z in r['sizes'] if z not in merged_sizes]
        steps.append({'axis_name': '사이즈', 'values': merged_sizes})

    # ⑤ 선택 조합 — 상품별 실제 조합 앞에 그 상품의 모델명을 붙인다.
    selected: list[list[str]] = []
    for mn, r in zip(model_names, results):
        for combo in r['combos']:
            selected.append([mn] + combo)

    memo = '불러온 곳: ' + ', '.join(
        f'{r["market"]} {r["pid"]}({mn})' for mn, r in zip(model_names, results))
    box = create_option_box(session, name=name, brand=(brand or '르무통'),
                            memo=memo, band=1)
    create_combination_options(session, box.model_code, steps, selected=selected)
    session.flush()

    # ⑥ 태어난 옵션 ↔ 마켓 옵션번호 — 모델명으로 어느 상품 소속인지 가린다.
    by_model = {mn: r for mn, r in zip(model_names, results)}
    linked = 0
    for opt in session.query(Option).filter_by(model_code=box.model_code).all():
        vals = option_axis_values(opt)
        mn, rest = (vals[0], vals[1:]) if vals else (None, [])
        r = by_model.get(mn)
        if r is None:
            logger.warning('[내마켓·병합] %s 옵션이 모르는 모델명 %r', box.model_code, mn)
            continue
        key = _combo_key(rest, set(r['colors']))
        moid = r['by_combo'].get(key)
        if moid is None:
            logger.warning('[내마켓·병합] %s 옵션 %s 에 짝 마켓옵션이 없음(예상 밖)',
                           box.model_code, vals)
            continue
        upsert_registration(session, canonical_sku=opt.canonical_sku,
                            market=r['market'], market_product_id=r['pid'],
                            market_option_id=moid, status='linked')
        linked += 1

    # ⑦ 「이미 가져옴」 표시 — N개 상품 전부 같은 그룹으로.
    g = MarketProductGroup(name=name, brand=(brand or None), model_code=box.model_code)
    session.add(g)
    session.flush()
    for r in results:
        if r['mp'] is not None:
            r['mp'].group_id = g.id

    return {'ok': True, 'code': box.model_code, 'name': name,
           'options': len(selected), 'linked': linked, 'models': model_names}

# -*- coding: utf-8 -*-
"""마켓 전송 목록 — **한 줄 = 구성(벌)**.

설계서: docs/superpowers/specs/2026-08-02-상품-마켓전송-탭-design.md §4-2
사장님 확정 ① — 마켓에 올라가는 실제 단위가 구성이다(구성 하나 = 마켓 상품 하나).
상품 단위로 묶으면 「한 상품에 여러 정책」일 때 어느 벌이 안 나갔는지 못 말한다.

━━ 🔴 더망고와 다른 점 — 소싱처가 복합이다 ━━━━━━━━━━━━━━━━━━━━
  더망고는 `MUSINSA.com` 하나가 한 줄이다. 우리는 **구성 하나가 소싱처 여럿**을 물고,
  그중 최저가 한 곳에서 사온다. 그래서 「몇 곳에서 보는지」와 「지금 어디서 사오는지」가
  다른 정보다.

  🔴 **「지금 사오는 곳」은 아직 안 채운다.** 그걸 알려면 옵션별 소싱처 재고·가격을
    읽어 최저가를 골라야 하는데(`option_sources.pick_cheapest_buyable`), 그 조립부가
    아직 `api_pricing` 라우트 안에 있다. 지어내면 화면이 거짓말을 한다 —
    `buy_source=None` 으로 두고 화면이 「아직 모름」이라고 말하게 한다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_

#: 날짜를 어느 기준으로 거를까 (사장님 확정 ④ — 골라쓰기)
#  'changed' — 2026-08-19 추가: 가격·재고가 실제로 바뀐 날(소싱처·마켓 어느 쪽이든)
DATE_BASIS = [('crawl', '소싱처 수집날'), ('sent', '마켓 전송날'),
              ('changed', '가격·재고 변동일')]

#: 정렬 기준. '' = 기존 그대로(수집일 최신순), 'changed' = 가격·재고 변동 최신순.
SORT_OPTIONS = [('', '수집일 최신순'), ('changed', '가격·재고 변동 최신순')]

#: 정책 필터 (사장님 확정 ③)
POLICY_FILTER = [('', '정책 ― 전체'), ('none', '정책 안 붙은 것만'),
                 ('has', '정책 붙은 것만')]

#: 마켓 등록 여부 — 2026-08-19 사장님 지시로 독립된 두 조건으로 분리(3번 확정 (a)).
#  「미판매중」= 빨리 올릴 계획인 것 / 「등록됨」= 계속 주시·관리할 것. 각각 따로 켠다.

#: 검색할 칸 — 'brand' 2026-08-19 추가(상품 기준 자동완성 3종 중 하나).
SEARCH_IN = [('name', '상품명·모델명'), ('brand', '브랜드'),
            ('code', '모음전 번호'), ('mpid', '마켓 상품번호')]


def _parse_day(s):
    try:
        return datetime.strptime(str(s)[:10], '%Y-%m-%d')
    except (TypeError, ValueError):
        return None


def source_keys_by_model(session, model_codes: list[str]) -> dict[str, list[str]]:
    """모음전별 소싱처 키들 — 구성이 물고 있는 곳 전부.

    ★ 소싱처는 **모음전(model_code)** 에 붙는다(구성이 아니라). 같은 모음전의
      구성들은 같은 소싱처를 본다 — 「단품」이든 「2벌 묶음」이든 사오는 데는 같다.
    """
    from lemouton.sourcing.models import BundleSourceUrl
    if not model_codes:
        return {}
    out: dict[str, list[str]] = {}
    rows = (session.query(BundleSourceUrl.model_code, BundleSourceUrl.source_key)
            .filter(BundleSourceUrl.model_code.in_(model_codes)).all())
    for code, key in rows:
        if not key:
            continue
        lst = out.setdefault(code, [])
        if key not in lst:              # 같은 소싱처에 URL 여러 개면 한 번만
            lst.append(key)
    return {k: sorted(v) for k, v in out.items()}


def source_urls_by_model(session, model_codes: list[str]) -> dict[str, dict[str, list[dict]]]:
    """모음전별 · 소싱처별 실제 URL 목록 — 호버카드 「바로가기」용.

    {model_code: {source_key: [{url, label}, ...]}}. 여러 URL 이면 sort_order 순.
    """
    from lemouton.sourcing.models import BundleSourceUrl
    if not model_codes:
        return {}
    out: dict[str, dict[str, list[dict]]] = {}
    rows = (session.query(BundleSourceUrl)
            .filter(BundleSourceUrl.model_code.in_(model_codes))
            .order_by(BundleSourceUrl.model_code, BundleSourceUrl.source_key,
                      BundleSourceUrl.sort_order).all())
    for r in rows:
        if not r.source_key:
            continue
        out.setdefault(r.model_code, {}).setdefault(r.source_key, []).append(
            {'url': r.url, 'label': r.label or ''})
    return out


def market_product_ids(session, set_ids: list[int]) -> dict[int, dict]:
    """구성별 마켓 상품번호 — `{set_id: {market: 상품번호}}`. 등록된 것만."""
    from lemouton.sets.models import SetChannel
    if not set_ids:
        return {}
    out: dict[int, dict] = {}
    for c in (session.query(SetChannel)
              .filter(SetChannel.set_id.in_(set_ids)).all()):
        if c.market_product_id:
            out.setdefault(c.set_id, {})[c.market] = c.market_product_id
    return out


def _changed_at_subquery(session):
    """구성별 「가격·재고가 마지막으로 바뀐 시각」 — `set_id, at` 두 칸짜리 서브쿼리.

    `ChannelChangeEvent` 는 값이 실제로 달라졌을 때만 쌓인다(change_service.record_change).
    소싱처·마켓 어느 쪽에서 바뀌었든 field 가 'stock'|'price' 인 것 중 최신 시각.
    """
    from lemouton.sets.models import ChannelChangeEvent as CCE
    return (session.query(CCE.set_id.label('set_id'), func.max(CCE.at).label('at'))
            .filter(CCE.field.in_(('stock', 'price')))
            .group_by(CCE.set_id).subquery())


def market_collected_at(session, set_ids: list[int]):
    """구성별 **판매처에서 값을 마지막으로 긁어온 때** — 「판매처 수집」 칸.

    `SetChannelOption.mkt_fetched_at` 최댓값(여러 마켓·옵션 중 가장 최근).
    「마켓 전송」(우리가 보낸 때)과는 다른 정보 — 이건 마켓 쪽 값을 우리가 읽어온 때다.

    Returns: `{set_id: datetime}`
    """
    from lemouton.sets.models import SetChannel, SetChannelOption
    if not set_ids:
        return {}
    rows = (session.query(SetChannel.set_id, func.max(SetChannelOption.mkt_fetched_at))
            .join(SetChannelOption, SetChannelOption.channel_id == SetChannel.id)
            .filter(SetChannel.set_id.in_(set_ids),
                    SetChannelOption.mkt_fetched_at.isnot(None))
            .group_by(SetChannel.set_id).all())
    return {sid: at for sid, at in rows if at is not None}


def rows(session, *, page: int = 1, per_page: int = 50,
         date_basis: str = '', date_from='', date_to='',
         policy: str = '', sources: list[str] | None = None,
         search_in: str = 'name', keyword: str = '',
         stock_status: str = '', sort: str = '',
         unlisted_only: bool = False, registered_only: bool = False,
         accounts: list[str] | None = None) -> dict:
    """필터 → 목록 한 쪽. `{total, page, per_page, rows: [...]}`.

    한 줄:
        {set_id, model_code, display_no, name, brand, set_name, options,
         sources: [소싱처키…], source_detail: {소싱처키: [{url,label}…]},
         buy_source: None,
         policy: 이름|None, policy_id: int|None, policy_from: 'set'|'model'|None,
         crawled_at, sent: {market: 시각}, listed: {market: 상품번호},
         market_collected_at: 판매처에서 값을 마지막으로 긁어온 때|None}
    """
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy, SetPolicyLink
    from lemouton.sets.models import ProductSet, SetOption, SetProduct
    from lemouton.sourcing.models import BundleSourceUrl, Model
    from lemouton.send.models import SendJobRow, KIND_OK

    q = (session.query(ProductSet, Model)
         .join(Model, Model.model_code == ProductSet.model_code)
         # 옵션함(아직 안 파는 묶음)은 보낼 대상이 아니다.
         .filter(or_(Model.is_option_box.is_(False), Model.is_option_box.is_(None))))

    # ── 이름·번호 검색 ──────────────────────────────────────────────
    kw = (keyword or '').strip()
    if kw:
        if search_in == 'code':
            q = q.filter(or_(Model.model_code.ilike(f'%{kw}%'),
                             Model.display_no.ilike(f'%{kw}%')))
        elif search_in == 'mpid':
            from lemouton.sets.models import SetChannel
            hit = {r[0] for r in session.query(SetChannel.set_id)
                   .filter(SetChannel.market_product_id.ilike(f'%{kw}%')).all()}
            q = q.filter(ProductSet.id.in_(hit or [-1]))
        elif search_in == 'brand':
            q = q.filter(Model.brand.ilike(f'%{kw}%'))
        else:
            q = q.filter(or_(Model.model_name_display.ilike(f'%{kw}%'),
                             Model.model_name_raw.ilike(f'%{kw}%'),
                             ProductSet.name.ilike(f'%{kw}%')))

    # ── 소싱처 (하나라도 물고 있으면) ────────────────────────────────
    picked = [s for s in (sources or []) if s]
    if picked:
        codes = {r[0] for r in session.query(BundleSourceUrl.model_code)
                 .filter(BundleSourceUrl.source_key.in_(picked)).all()}
        q = q.filter(ProductSet.model_code.in_(codes or ['']))

    # ── 정책 붙음 여부 ──────────────────────────────────────────────
    if policy in ('none', 'has'):
        set_linked = {r[0] for r in session.query(SetPolicyLink.set_id).all()}
        model_linked = {r[0] for r in session.query(BundlePolicyLink.model_code).all()}
        if policy == 'has':
            q = q.filter(or_(ProductSet.id.in_(set_linked or [-1]),
                             ProductSet.model_code.in_(model_linked or [''])))
        else:
            q = (q.filter(~ProductSet.id.in_(set_linked or [-1]))
                  .filter(~ProductSet.model_code.in_(model_linked or [''])))

    # ── 재고상태 (판매처 기준 — 마켓이 알려준 실제 재고, 지어내지 않는다) ──
    #   확인 안 된 구성(마켓이 재고를 한 번도 안 알려줌)은 재고·품절 어디에도
    #   안 걸린다 — 「모른다」와 「없다」는 다르다.
    if stock_status in ('instock', 'soldout'):
        from lemouton.sets.models import SetChannel, SetChannelOption
        checked = (session.query(SetChannel.set_id)
                   .join(SetChannelOption, SetChannelOption.channel_id == SetChannel.id)
                   .filter(SetChannelOption.mkt_stock.isnot(None)))
        instock_ids = {r[0] for r in checked.filter(SetChannelOption.mkt_stock > 0).all()}
        if stock_status == 'instock':
            q = q.filter(ProductSet.id.in_(instock_ids or [-1]))
        else:
            checked_ids = {r[0] for r in checked.all()}
            q = q.filter(ProductSet.id.in_((checked_ids - instock_ids) or [-1]))

    # ── 판매처 계정(전체>계정, 4-D 확정) — 읽기 전용 필터. 실제 전송 시 어느
    #   계정 자격증명으로 나가는지는 별도(계정별 전송 배선, 게이트 통과 후) ──
    picked_accts = [a for a in (accounts or []) if a]
    if picked_accts:
        from lemouton.sets.models import SetChannel
        hit = {r[0] for r in session.query(SetChannel.set_id)
               .filter(SetChannel.account_key.in_(picked_accts)).all()}
        q = q.filter(ProductSet.id.in_(hit or [-1]))

    # ── 마켓 등록 여부 — 독립된 두 조건, 둘 다 켜면 사실상 전체(교집합 아님) ──
    if unlisted_only or registered_only:
        from lemouton.sets.models import SetChannel
        reg = {r[0] for r in session.query(SetChannel.set_id)
               .filter(SetChannel.market_product_id.isnot(None)).all()}
        if unlisted_only and not registered_only:
            q = q.filter(~ProductSet.id.in_(reg or [-1]))
        elif registered_only and not unlisted_only:
            q = q.filter(ProductSet.id.in_(reg or [-1]))

    # ── 날짜 (사장님 확정 ④ — 어느 날짜인지 골라쓰기) ─────────────────
    d1, d2 = _parse_day(date_from), _parse_day(date_to)
    if date_basis == 'crawl' and (d1 or d2):
        if d1:
            q = q.filter(Model.last_crawled_at >= d1)
        if d2:
            q = q.filter(Model.last_crawled_at < d2.replace(hour=23, minute=59, second=59))
    elif date_basis == 'sent' and (d1 or d2):
        sub = session.query(SendJobRow.set_id).filter(SendJobRow.kind == KIND_OK)
        if d1:
            sub = sub.filter(SendJobRow.created_at >= d1)
        if d2:
            sub = sub.filter(SendJobRow.created_at
                             < d2.replace(hour=23, minute=59, second=59))
        q = q.filter(ProductSet.id.in_({r[0] for r in sub.all() if r[0]} or [-1]))
    elif date_basis == 'changed' and (d1 or d2):
        chg = _changed_at_subquery(session)
        sub = session.query(chg.c.set_id)
        if d1:
            sub = sub.filter(chg.c.at >= d1)
        if d2:
            sub = sub.filter(chg.c.at < d2.replace(hour=23, minute=59, second=59))
        q = q.filter(ProductSet.id.in_({r[0] for r in sub.all() if r[0]} or [-1]))

    total = q.count()
    page = max(1, int(page or 1))
    per = max(1, min(int(per_page or 50), 200))
    if sort == 'changed':
        chg = _changed_at_subquery(session)
        got = (q.outerjoin(chg, chg.c.set_id == ProductSet.id)
               .order_by(chg.c.at.desc().nullslast(), ProductSet.id.desc())
               .offset((page - 1) * per).limit(per).all())
    else:
        got = (q.order_by(Model.last_crawled_at.desc().nullslast(), ProductSet.id.desc())
               .offset((page - 1) * per).limit(per).all())

    set_ids = [ps.id for ps, _ in got]
    codes = list({ps.model_code for ps, _ in got})

    # ── 곁들여 읽을 것들 (N+1 방지 — 한 번씩만) ──────────────────────
    src_map = source_keys_by_model(session, codes)
    src_url_map = source_urls_by_model(session, codes)
    listed_map = market_product_ids(session, set_ids)
    from lemouton.send.service import last_sent_at
    sent_map = last_sent_at(session, set_ids=set_ids)
    mkt_collected_map = market_collected_at(session, set_ids)

    opt_cnt = dict(session.query(SetProduct.set_id, func.count(SetOption.id))
                   .join(SetOption, SetOption.set_product_id == SetProduct.id)
                   .filter(SetProduct.set_id.in_(set_ids or [-1]))
                   .group_by(SetProduct.set_id).all())

    set_pol = {r.set_id: r.policy_id for r in session.query(SetPolicyLink)
               .filter(SetPolicyLink.set_id.in_(set_ids or [-1])).all()}
    model_pol = {r.model_code: r.policy_id for r in session.query(BundlePolicyLink)
                 .filter(BundlePolicyLink.model_code.in_(codes or [''])).all()}
    pol_ids = set(set_pol.values()) | set(model_pol.values())
    pol_name = {p.id: p.name for p in session.query(MarketPolicy)
                .filter(MarketPolicy.id.in_(pol_ids or [-1]),
                        MarketPolicy.deleted_at.is_(None)).all()}

    out = []
    for ps, m in got:
        pid, origin = set_pol.get(ps.id), 'set'
        if pid is None or pid not in pol_name:
            pid, origin = model_pol.get(ps.model_code), 'model'
        if pid not in pol_name:
            pid, origin = None, None
        out.append({
            'set_id': ps.id, 'model_code': ps.model_code,
            'display_no': m.display_no or ps.model_code,
            'name': m.model_name_display or m.model_name_raw or ps.model_code,
            'brand': m.brand or '',
            'set_name': ps.name or '단품',
            'options': int(opt_cnt.get(ps.id) or 0),
            'sources': src_map.get(ps.model_code, []),
            'source_detail': src_url_map.get(ps.model_code, {}),
            # 🔴 「지금 사오는 곳」은 옵션별 최저가 픽이 있어야 안다 — 아직 미배선.
            #   지어내지 않고 None. 화면이 「아직 모름」이라고 말한다.
            'buy_source': None,
            'policy': pol_name.get(pid), 'policy_id': pid, 'policy_from': origin,
            'crawled_at': m.last_crawled_at,
            'sent': sent_map.get(ps.id, {}),
            'listed': listed_map.get(ps.id, {}),
            'market_collected_at': mkt_collected_map.get(ps.id),
        })
    return {'total': total, 'page': page, 'per_page': per, 'rows': out}


def source_options(session) -> list[tuple[str, str]]:
    """필터에 뿌릴 소싱처 목록 — **실제로 붙어 있는 것만**.

    쓰지도 않는 소싱처를 늘어놓으면 고를 게 많아 보이기만 한다.
    """
    from lemouton.sourcing.models import BundleSourceUrl
    keys = sorted({r[0] for r in session.query(BundleSourceUrl.source_key)
                   .distinct().all() if r[0]})
    # 사람이 읽는 이름은 소싱처 명부에 있다. 없으면 키를 그대로 보여준다 —
    # 지어낸 이름을 붙이면 사장님이 화면에서 못 찾는다.
    names = {}
    try:
        from lemouton.sourcing.source_registry import SourcingSource
        for r in session.query(SourcingSource).all():
            k = getattr(r, 'key', None) or getattr(r, 'source_key', None)
            if k:
                names[k] = getattr(r, 'name', None) or k
    except Exception:                       # noqa: BLE001 — 명부 없는 옛 DB
        pass
    return [(k, names.get(k, k)) for k in keys]


#: 자동완성 한 번에 돌려줄 최대 건수 — `catalog/search.py:SUGGEST_LIMIT` 과 같은 규칙.
SUGGEST_LIMIT = 10


def _escape_like(v: str) -> str:
    """LIKE 특수문자를 글자로 바꾼다 — `%` 를 그대로 넘기면 전체가 걸린다."""
    return v.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def suggest_products(session, q: str, *, limit: int = SUGGEST_LIMIT) -> dict:
    """상품 기준 자동완성 — 브랜드·상품명(모델명 포함) 뒤섞어 찾고 종류를 표시한다.

    ★ catalog/search.py:suggest() 와 같은 규칙 — 2글자 미만은 안 찾고, 전체
      건수는 안 센다(글자마다 부르므로 가볍게).
    🔴 「모델명」은 별도 칸이 없다 — `Model.model_name_display` 가 이미 그 값이다.
      없는 칸을 지어내지 않고 'name' 한 종류로 합친다.
    """
    from lemouton.sets.models import ProductSet
    from lemouton.sourcing.models import Model
    qq = (q or '').strip()
    if len(qq) < 2:
        return {'rows': [], 'q': qq, 'reason': '두 글자 이상 적어주세요'}
    limit = max(1, min(int(limit or SUGGEST_LIMIT), 25))
    like = f'%{_escape_like(qq)}%'

    base = (session.query(Model)
            .filter(or_(Model.is_option_box.is_(False), Model.is_option_box.is_(None))))
    out = []
    for m in (base.filter(Model.brand.ilike(like, escape='\\'))
              .order_by(Model.model_code).limit(limit).all()):
        out.append({'kind': 'brand', 'value': m.brand, 'model_code': m.model_code,
                    'display_no': m.display_no or m.model_code})
    for m in (base.filter(or_(Model.model_name_display.ilike(like, escape='\\'),
                              Model.model_name_raw.ilike(like, escape='\\')))
              .order_by(Model.model_code).limit(limit).all()):
        out.append({'kind': 'name',
                    'value': m.model_name_display or m.model_name_raw,
                    'model_code': m.model_code,
                    'display_no': m.display_no or m.model_code})
    return {'rows': out[:limit], 'q': qq, 'reason': ''}


def suggest_policies(session, q: str, *, limit: int = SUGGEST_LIMIT) -> dict:
    """판매처 기준 정책 이름 자동완성 — 지운 정책은 안 나온다."""
    from lemouton.policy.models import MarketPolicy
    qq = (q or '').strip()
    if len(qq) < 2:
        return {'rows': [], 'q': qq, 'reason': '두 글자 이상 적어주세요'}
    limit = max(1, min(int(limit or SUGGEST_LIMIT), 25))
    like = f'%{_escape_like(qq)}%'
    rows = (session.query(MarketPolicy)
            .filter(MarketPolicy.deleted_at.is_(None),
                    or_(MarketPolicy.name.ilike(like, escape='\\'),
                       MarketPolicy.brand.ilike(like, escape='\\')))
            .order_by(MarketPolicy.id.desc()).limit(limit).all())
    return {'rows': [{'id': p.id, 'name': p.name, 'brand': p.brand} for p in rows],
           'q': qq, 'reason': ''}


def account_options(session) -> dict[str, list[tuple[str, str]]]:
    """필터에 뿌릴 판매처 계정 목록 — `{market: [(account_key, display_name), ...]}`.

    2026-08-19 「판매처 전체 > 계정」 4-D 확정 — **꺼둔 계정은 안 보인다**
    (`_env_prefix` 의 실전송 후보 선정과 같은 기준: `is_active=True`).
    """
    from lemouton.sourcing.models_v2 import UploadAccount
    out: dict[str, list[tuple[str, str]]] = {}
    for a in (session.query(UploadAccount)
              .filter(UploadAccount.is_active.is_(True))
              .order_by(UploadAccount.market, UploadAccount.id).all()):
        out.setdefault(a.market, []).append((a.account_key, a.display_name))
    return out

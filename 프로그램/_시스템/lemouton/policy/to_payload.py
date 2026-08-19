# -*- coding: utf-8 -*-
"""배선 — 정책 13항목을 **구성(벌)에 실제로 적용**한다.

설계서: docs/superpowers/specs/2026-08-02-상품-마켓전송-탭-design.md §2

━━ 왜 이 파일이 있나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PR#678 이 진단한 그림 — 정책 항목 중 **밖으로 나가는 것은 판매가·배송비뿐**이고
  나머지는 저장만 됐다(읽는 코드가 0곳). 여기가 그 끊긴 자리를 잇는다.
  [2026-08-12] 이 파일 덕분에 상품명·브랜드·옵션·상세설명이 실제로 나가게 됐는데,
  화면 표시(`policy/required.py:WIRING`)는 옛 진단 그대로 「저장만」이라 말하고
  있었다 — 그 표를 실측으로 정정했다.

━━ 🔴 가공 엔진을 다시 만들지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━
  13항목을 실제로 적용하는 엔진은 이미 있다 —
  `lemouton/registration/process_apply.py:apply_rules()`. 대량등록이 쓰며 라이브에서
  검증됐다. 그게 받는 `rules` 는 `{item_key: config}` 인데, 정책 화면의
  `policy.service.values_for()` 가 **정확히 같은 모양**을 돌려준다(항목 정의를
  `process_rule_schema` 한 곳에서 같이 쓰기 때문).

  그래서 이 파일이 하는 일은 딱 둘이다:
    ① 이 구성에 적용될 **정책 하나**를 정한다 (되받기 사슬)
    ② 구성을 엔진이 읽을 수 있는 **모양**으로 보여준다 (`SetProcessView`)
  가공 자체는 엔진에 맡긴다. 여기서 다시 구현하면 두 화면이 다른 결과를 낸다.

━━ 🔴 판매가와 나머지 항목이 **같은 정책**을 따라야 한다 ━━━━━━━━━━━
  `as_template.policy_template_for_set` 은 「구성에 정책이 붙었는데 **판매가를 안
  정했으면** 상품 정책으로 되받기」를 한다. 가격만 볼 때는 옳다.
  하지만 그 규칙을 그대로 쓰면, 상품명은 구성 정책을 따르고 판매가는 상품 정책을
  따르는 **뒤섞인 상품**이 나간다. 그래서 여기서는 정책을 **먼저 하나로 정하고**,
  그 정책으로 가격 껍데기까지 만든다(:func:`price_template_for`).
"""
from __future__ import annotations

import json

from lemouton.policy.fields import MARKET_KEYS
from lemouton.policy.models import BundlePolicyLink, MarketPolicy, SetPolicyLink


class PayloadError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패 사유."""


# ── ① 이 구성에 적용될 정책 하나 ─────────────────────────────────────────

def resolve_policy(session, *, set_id: int):
    """구성 하나에 적용될 정책. 없으면 None.

    되받기 사슬 (위가 이긴다)::

        구성 정책(SetPolicyLink) → 상품 정책(BundlePolicyLink) → 없음

    🔴 `as_template` 의 사슬과 **한 군데 다르다** — 거기서는 「구성 정책이 판매가를
      안 정했으면 상품 정책으로」 한 단계 더 되받는다. 여기서는 되받지 않는다.
      한 벌은 **한 정책만** 따라야 상품명과 판매가가 뒤섞이지 않는다.
      (그 차이는 `test_to_payload.py` 가 고정해 둔다)

    Returns:
        (MarketPolicy, 어디서 왔나) — 'set' | 'model' | None
    """
    if set_id:
        link = session.get(SetPolicyLink, set_id)
        if link is not None:
            p = session.get(MarketPolicy, link.policy_id)
            if p is not None and p.deleted_at is None:
                return p, 'set'

    from lemouton.sets.models import ProductSet
    ps = session.get(ProductSet, set_id) if set_id else None
    if ps is None:
        return None, None
    link = session.get(BundlePolicyLink, ps.model_code)
    if link is None:
        return None, None
    p = session.get(MarketPolicy, link.policy_id)
    if p is None or p.deleted_at is not None:
        return None, None
    return p, 'model'


def rules_for(session, *, set_id: int, market: str) -> tuple[dict, object, str]:
    """그 구성 × 그 마켓에 **실제로 적용될** 규칙 한 벌.

    Returns:
        (rules, policy, 출처) — 정책이 없으면 ({}, None, None)

    ★ 「마켓 공통」 탭 값은 여기서 자동으로 섞지 않는다. 공통은 **담아두는 자리**이고,
      마켓으로 넣는 것은 사장님이 화면에서 「넣기/불러오기」로 한다
      (`policy/common_sync.py`). 여기서 몰래 섞으면 화면이 보여주는 값과
      실제로 나가는 값이 달라진다.
    """
    if market not in MARKET_KEYS:
        raise PayloadError(f'모르는 마켓입니다: {market} — {MARKET_KEYS} 중에서 골라 주세요.')
    policy, origin = resolve_policy(session, set_id=set_id)
    if policy is None:
        return {}, None, None
    from lemouton.policy.service import values_for
    return values_for(session, policy.id, market), policy, origin


def price_template_for(session, *, set_id: int, fallback=None):
    """그 구성의 **정해진 정책**으로 만든 가격 껍데기.

    🔴 `as_template.policy_template_for_set` 을 쓰지 않는 이유는 이 파일 머리말에
      적어 두었다 — 판매가와 나머지 항목이 다른 정책을 따르면 안 된다.
    """
    from lemouton.policy.as_template import policy_as_template
    policy, _ = resolve_policy(session, set_id=set_id)
    if policy is None:
        return None
    return policy_as_template(session, policy.id, fallback=fallback)


# ── ② 구성을 엔진이 읽을 수 있는 모양으로 ────────────────────────────────
#
# `apply_rules` 가 읽는 칸은 아홉 개뿐이다(실측):
#   name · brand · detail_html · options_json · notice_json ·
#   origin_area_code · delivery_fee · return_fee · source_category_path
# ProductDraft 를 흉내 내되 **읽기 전용**이다 — 쓰면 DB 에 안 남고 사라진다.

class SetProcessView:
    """구성 하나를 드래프트 모양으로 보여주는 읽기 전용 사본.

    `notice_defaults.DraftNoticeView` · `process_apply.DraftProcessView` 와 같은 결.
    """

    __slots__ = ('_v',)

    def __init__(self, values: dict):
        object.__setattr__(self, '_v', dict(values))

    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, '_v')[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        raise AttributeError(
            f'읽기 전용입니다({name}) — 여기에 값을 넣어도 저장되지 않고 사라집니다.')

    def as_dict(self) -> dict:
        return dict(object.__getattribute__(self, '_v'))


#: 재고를 못 읽었다는 표시. 전송 게이트가 이걸 보고 **막는다**.
STOCK_UNREADABLE = 'STOCK_UNREADABLE'
#: (옛 이름 — 3단계에서 「아직 안 붙음」을 뜻했다. 지금은 「못 읽음」이다)
STOCK_NOT_WIRED = STOCK_UNREADABLE


def _stock_by_sku(session, model_code: str) -> dict:
    """모음전의 옵션별 소싱처 재고 — **화면(매트릭스)이 쓰는 그 값 그대로**.

    🔴 재고를 여기서 새로 계산하지 않는다 (프로젝트 최상위 원칙 · 폴백 금지)
      우리 재고는 「있음 / 품절(0) / 확인 불가」 3상태이고, 그 판정은 소싱처 URL별
      원시값 + 마지막 크롤 상태 + 색·사이즈 매칭까지 봐야 나온다. 그걸 다시 짜면
      화면은 「품절」인데 전송은 「있음」으로 나간다.

      `_option_matrix_data(code)` 가 그 조립의 정본이고, **업로드 드라이런이 이미
      같은 방식으로 이 함수를 부른다**(`uploader/preview.py:117` — "표시가=업로드가
      단일 진실 원천(parity)"). 마켓 전송도 그 선례를 그대로 따른다.

      ⚠️ `Option.boxhero_stock_total` 은 **사입(우리 창고) 재고**라 쓰면 안 된다.
        `default=0` 이라 「모름」이 저장되는 순간 0(품절)으로 둔갑한다.

    Returns:
        `{canonical_sku: [소싱처 셀…]}` — 셀에는 이미 `stock_qty·stock_label·
        stock_state` 가 붙어 있다. 못 읽으면 `{}`.
    """
    from webapp.routes.api_pricing import _option_matrix_data
    try:
        md = _option_matrix_data(model_code)
    except Exception:                       # noqa: BLE001
        return {}
    if not md.get('ok'):
        return {}
    return {o['sku']: (o.get('sources') or []) for o in (md.get('options') or [])}


def _options_json(session, set_id: int, stock_by_sku: dict | None = None) -> str:
    """구성에 담긴 옵션들 → 드래프트의 `options_json` 모양.

    재고는 :func:`_stock_by_sku` 가 준 **화면과 같은 값**을 싣는다. 못 읽은 옵션은
    `stock` 키를 **아예 넣지 않는다** — 0 을 넣으면 품절로 나간다.
    """
    from lemouton.sets.models import SetOption, SetProduct
    from lemouton.sourcing.models import Option

    skus = [r[0] for r in
            session.query(SetOption.canonical_sku)
            .join(SetProduct, SetProduct.id == SetOption.set_product_id)
            .filter(SetProduct.set_id == set_id)
            .order_by(SetOption.sort_order, SetOption.id).all()]
    if not skus:
        return '[]'
    rows = (session.query(Option).filter(Option.canonical_sku.in_(skus)).all())
    by_sku = {o.canonical_sku: o for o in rows}
    out = []
    for sku in skus:                       # 구성이 정한 순서를 지킨다
        o = by_sku.get(sku)
        if o is None:
            continue
        cell = {
            'sku': o.canonical_sku,
            'color': o.color_display or o.color_code or '',
            'size': o.size_display or o.size_code or '',
            'image_url': o.image_url or '',
            'active': bool(o.is_active),
        }
        srcs = (stock_by_sku or {}).get(o.canonical_sku)
        if srcs:
            from lemouton.sourcing.option_sources import sendable_for_option
            ok, qty, why, picked = sendable_for_option([dict(x) for x in srcs])
            if ok:
                # 수량 미상(「재고있음」)이면 None — 마켓별 상한은 컴파일러가 정한다.
                cell['stock'] = qty
                cell['buy_source'] = (picked or {}).get('site')
            else:
                cell['stock_blocked'] = why    # 왜 못 보내는지 그대로 실어 보낸다
        # ★ 못 읽었으면 'stock' 키를 **아예 넣지 않는다** — 0 을 넣으면 품절로 나간다.
        out.append(cell)
    return json.dumps(out, ensure_ascii=False)


def set_view(session, *, set_id: int) -> SetProcessView:
    """구성 → 가공 엔진이 읽을 수 있는 사본.

    이름은 **구성 이름이 먼저**다 — 구성이 곧 마켓에 올라가는 한 상품이고,
    「긴팔 2벌 묶음」처럼 상품 이름과 다를 수 있다. 구성 이름이 비면 상품 이름을 쓴다.
    """
    from lemouton.sets.models import ProductSet
    from lemouton.sourcing.models import Model
    # 함수 안에서 부른다 — as_draft 가 이 파일을 되부르므로 맨 위에서 부르면 순환한다.
    from lemouton.send.as_draft import option_images

    ps = session.get(ProductSet, set_id)
    if ps is None:
        raise PayloadError(f'그런 구성이 없습니다: {set_id}')
    m = session.get(Model, ps.model_code)
    model_name = ''
    brand = ''
    category_path = ''
    if m is not None:
        model_name = m.model_name_display or m.model_name_raw or m.model_code
        brand = m.brand or ''
        category_path = m.category or ''

    return SetProcessView({
        'set_id': ps.id,
        'model_code': ps.model_code,
        'name': (ps.name or '').strip() or model_name,
        'brand': brand,
        'detail_html': '',                 # 상세는 아직 구성에 칸이 없다(3단계 범위 밖)
        'options_json': _options_json(session, ps.id,
                                      _stock_by_sku(session, ps.model_code)),
        # 🔴 [2026-08-13] 이 칸이 없어서 **전송이 통째로 막혔다.**
        #   정책에 「이미지」 항목만 저장해 두면, 가공 엔진이 사본에서 사진을 못 찾아
        #   「이미지가 한 장도 없습니다」로 판정하고 막았다(process_apply.py 의
        #   `_apply_images` → NO_IMAGES, blocking=True). 옵션에 사진이 **있는데도**
        #   그랬다 — 사장님이 이미지 규칙을 저장하는 순간 그 상품이 어느 마켓에도
        #   못 나가는 상태였다.
        #   ★ 사진 모으는 방법은 `send/as_draft.option_images` 가 정본이다 —
        #     여기서 다시 만들면 「사본이 본 사진」과 「초안에 실리는 사진」이 갈린다.
        'images_json': json.dumps(option_images(session, ps.id), ensure_ascii=False),
        'notice_json': '{}',
        'origin_area_code': '',
        'delivery_fee': None,
        'return_fee': None,
        'source_category_path': category_path,
    })


# ── ③ 붙이기 ────────────────────────────────────────────────────────────

def build_for_set(session, *, set_id: int, market: str, base_view=None) -> dict:
    """구성 × 마켓 → 가공된 사본 + 무엇이 바뀌었고 무엇이 막혔나.

    Args:
        base_view: :func:`set_view` 결과를 미리 만들어 넘기면 재사용한다.
            🔴 사본 조립(`set_view`)은 **마켓과 무관**한데 그 안의 재고 읽기
            (`_stock_by_sku` → `_option_matrix_data`)가 옵션 102개×소싱처 8곳짜리
            상품에서 수십 초씩 걸린다. 마켓 6곳을 돌 때 6번 다시 만들면 첫 로그
            한 줄이 몇 분씩 늦는다 — **라이브 실측으로 걸린 병목**이다.
            호출자(runner)가 구성당 한 번 만들어 넘긴다. 안 주면 여기서 만든다 —
            답은 같다(process_policy.resolve_rules_for_draft 의 gate 인자와 같은 결).

    Returns:
        {
          'view':     가공된 읽기 전용 사본 (정책이 없으면 원본 사본 그대로)
          'policy':   적용된 정책 (없으면 None)
          'origin':   정책이 어디서 왔나 — 'set' | 'model' | None
          'applied':  [{item, field, label, before, after, note}]
          'skipped':  [{item, field, label, code, reason, blocking}]
          'blocking': [사유…] — **하나라도 있으면 보내면 안 된다**
        }

    🔴 정책이 없으면 **막는다**. 예전 대량등록은 정책이 없으면 「크롤 값이 그대로
      갑니다」라고 알리기만 하고 통과시켰다(초안이라 그게 맞다). 하지만 여기서는
      마켓으로 실제로 나가는 자리라, 정해진 적 없는 값이 나가면 그게 곧 사고다.
    """
    from lemouton.registration import process_apply as PA

    view = base_view if base_view is not None else set_view(session, set_id=set_id)
    rules, policy, origin = rules_for(session, set_id=set_id, market=market)

    if policy is None:
        skip = [{'item': 'name', 'field': '', 'label': '정책',
                 'code': 'NO_POLICY',
                 'reason': '이 구성에 정책이 붙어 있지 않습니다 — 「정책 매칭」에서 '
                           '붙여 주세요. 정책이 없으면 어떤 값으로 올릴지 정해지지 '
                           '않아 보내지 않습니다.',
                 'blocking': True}]
        return {'view': view, 'policy': None, 'origin': None,
                'applied': [], 'skipped': skip,
                'blocking': [s['reason'] for s in skip]}

    if not rules:
        skip = [{'item': 'name', 'field': '', 'label': '정책',
                 'code': 'NO_RULES',
                 'reason': f'정책 「{policy.name}」 에 이 마켓({market})으로 저장된 항목이 '
                           f'하나도 없습니다 — 「정책 생성」에서 채워 주세요.',
                 'blocking': True}]
        return {'view': view, 'policy': policy, 'origin': origin,
                'applied': [], 'skipped': skip,
                'blocking': [s['reason'] for s in skip]}

    # 수집 금지어는 **소싱처 단위 게이트**라 규칙 밖에서 주입받는다(엔진 규약).
    #   구성에는 소싱처가 여럿 붙을 수 있어, 붙은 소싱처 전부의 금지어를 모은다.
    collect = _collect_banned_for_set(session, set_id=set_id)

    out_view, applied, skipped = PA.apply_rules(
        view, rules, market=market, collect_banned_words=collect)

    # 🔴 재고를 못 읽은 옵션이 하나라도 있으면 **보내지 않는다.**
    #   「모름」을 0 으로 보내면 멀쩡한 상품이 품절로 올라가고, 아무 수나 보내면
    #   오버셀이다. 어느 옵션이 왜 막혔는지 사유를 그대로 실어 보낸다.
    skipped = list(skipped) + _stock_gate(out_view)
    return {'view': out_view, 'policy': policy, 'origin': origin,
            'applied': applied, 'skipped': skipped,
            'blocking': PA.blocking_reasons(skipped)}


def _stock_gate(view) -> list:
    """재고를 못 읽은 옵션을 막는 사유들. 다 읽었으면 빈 목록.

    ★ 사유는 옵션 이름과 함께 준다 — 「재고를 못 읽었습니다」만 있으면 어느 옵션을
      봐야 할지 모른다.
    """
    try:
        opts = json.loads(getattr(view, 'options_json', '') or '[]')
    except (TypeError, ValueError):
        opts = []
    if not opts:
        return [{'item': 'options', 'field': 'stock', 'label': '재고',
                 'code': STOCK_UNREADABLE,
                 'reason': '이 구성에 옵션이 하나도 없습니다 — 보낼 것이 없습니다.',
                 'blocking': True}]
    out = []
    for o in opts:
        if 'stock' in o:
            continue                       # 읽었다(0 도 읽은 값이다)
        who = f"{o.get('color') or ''} {o.get('size') or ''}".strip() or o.get('sku')
        why = o.get('stock_blocked') or ('이 옵션에 붙은 소싱처 재고를 읽지 못했습니다.')
        out.append({'item': 'options', 'field': 'stock', 'label': '재고',
                    'code': STOCK_UNREADABLE,
                    'reason': f'옵션 「{who}」 — {why}',
                    'blocking': True})
    return out


def _collect_banned_for_set(session, *, set_id: int) -> list:
    """이 구성이 물고 있는 소싱처들의 **수집 금지어** 합집합.

    ★ 엔진(`apply_rules`)은 수집 금지어가 규칙에 있는데 주입되지 않으면 **막는다**
      (리뷰 I-2 — 게이트가 통째로 꺼진 채 「등록된 금지어가 없습니다」라고 거짓
      안내하던 사고). 그래서 빈 목록이라도 반드시 만들어 넘긴다.
    """
    from lemouton.registration.process_policy import collect_banned_for_source
    from lemouton.sets.models import ProductSet

    ps = session.get(ProductSet, set_id)
    if ps is None:
        return []
    try:
        from lemouton.sourcing.models import BundleSourceUrl
        keys = {r[0] for r in session.query(BundleSourceUrl.source_key)
                .filter(BundleSourceUrl.model_code == ps.model_code).all() if r[0]}
    except Exception:                       # noqa: BLE001 — 표가 없는 옛 DB
        keys = set()
    out = []
    for k in sorted(keys):
        out.extend(w for w, _ in collect_banned_for_source(session, source_key=k))
    return out

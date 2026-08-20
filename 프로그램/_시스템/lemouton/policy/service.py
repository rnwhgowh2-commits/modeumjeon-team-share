"""정책 규칙 — 만들기 · 항목값 저장 · 상품에 붙이기 · 채움 현황.

값은 **항목 하나당 설정 묶음 하나**로 저장한다(`field_key=item_key`, `value=JSON`).
항목 정의는 대량등록 가공 규칙 13항목을 그대로 쓴다 — lemouton/policy/fields.py 주석 참조.

🔴 **저장하지 않은 항목은 「아직 안 정함」이다.**
   화면이 기본값을 보여주더라도, 사장님이 저장하지 않았으면 정해진 것이 아니다.
   `values_for()` 는 저장된 항목만 돌려주고, `readiness()` 가 「가격 아직 못 씀」을 알린다.
   가격 계산에 물리는 것은 「판매가」 항목이 저장된 뒤다(현재 미배선).
"""
from __future__ import annotations

import json

from sqlalchemy import select

from lemouton.policy.fields import (
    COMMON_KEY, MARKET_KEYS, PRICE_REQUIRED_ITEMS, all_item_keys, item_keys_for,
)
from lemouton.policy.models import BundlePolicyLink, MarketPolicy, MarketPolicyValue


class PolicyError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패 사유."""


def create_policy(session, *, name: str = '', memo: str = '', brand: str = '',
                  category: str = '', sourcing: str = '', prefix: str = '') -> MarketPolicy:
    """정책을 만든다. `name` 을 안 적으면 자동으로 조합한다.

    [2026-08-19 사장님 확정] 정책명 = [대량]or[모음전] + 브랜드 + 카테고리 + 소싱처.
    조합할 조각(브랜드·카테고리·소싱처)이 **하나도 없으면** 조합하지 않는다 —
    「[모음전]」 하나만 덩그러니 남는 이름은 뜻이 없어, 그때는 이름을 직접 받는다.
    사용자가 이름을 직접 적었으면 그 이름을 그대로 쓴다(자동 조합이 덮지 않는다).
    """
    name = (name or '').strip()
    brand = (brand or '').strip()
    category = (category or '').strip()
    sourcing = (sourcing or '').strip()
    if not name:
        parts = [p for p in (brand, category, sourcing) if p]
        if parts:
            tag = f'[{prefix.strip()}]' if (prefix or '').strip() else '[모음전]'
            name = tag + ' ' + ' '.join(parts)
    if not name:
        raise PolicyError('정책 이름을 넣어 주세요.')
    dup = session.scalar(select(MarketPolicy).where(
        MarketPolicy.name == name, MarketPolicy.deleted_at.is_(None)))
    if dup is not None:
        raise PolicyError(f'「{name}」 이름의 정책이 이미 있어요.')
    p = MarketPolicy(name=name, memo=(memo or '').strip() or None,
                     brand=brand or None, category=category or None,
                     sourcing=sourcing or None)
    session.add(p)
    session.flush()
    return p


def _check_field_keys(market: str, item_key: str, config: dict) -> None:
    """항목 안의 **칸 이름**까지 검사한다.

    🔴 [2026-08-01] 여기까지 안 보면 오타난 칸이 조용히 저장된다. 저장은 됐는데
      계산에는 안 쓰이니 「왜 안 먹지」로 한참 헤맨다. 판매가 항목이 4칸에서
      15칸으로 늘면서 더 위험해졌다(sourcing_rate ↔ sourcing_ratio).
      대량등록 쪽(process_policy.set_rule)은 원래 이 검사를 하고 있었다.
    """
    if not config:
        return
    from lemouton.policy.fields import COMMON_KEY, items_for
    look = MARKET_KEYS[0] if market == COMMON_KEY else market
    item = next((it for it in items_for(look) if it['key'] == item_key), None)
    if item is None:
        return          # 그 마켓에 없는 항목 — item_key 검사가 이미 통과시킨 경우
    allowed = {f['key'] for f in item['fields']}
    unknown = [k for k in config if k not in allowed]
    if unknown:
        raise PolicyError(
            f"「{item['label']}」에 모르는 칸이 있어요: {', '.join(unknown)} — "
            f"쓸 수 있는 칸: {', '.join(sorted(allowed))}")


def save_item(session, *, policy: MarketPolicy, market: str,
              item_key: str, config: dict) -> None:
    """항목 하나의 설정을 저장한다. config 가 비면 「안 정함」으로 되돌린다."""
    # 「마켓 공통」도 값을 담는 자리다 — 마켓은 아니지만 저장은 여기로 들어온다.
    if market not in MARKET_KEYS and market != COMMON_KEY:
        raise PolicyError(f'모르는 마켓이에요: {market}')
    if item_key not in all_item_keys():
        raise PolicyError(f'모르는 항목이에요: {item_key}')
    _check_field_keys(market, item_key, config)
    row = session.scalar(select(MarketPolicyValue).where(
        MarketPolicyValue.policy_id == policy.id,
        MarketPolicyValue.market == market,
        MarketPolicyValue.field_key == item_key))
    if not config:
        if row is not None:
            session.delete(row)     # 비우면 「안 정함」 — 0 으로 남기지 않는다
        session.flush()
        return
    body = json.dumps(config, ensure_ascii=False)
    if row is None:
        session.add(MarketPolicyValue(policy_id=policy.id, market=market,
                                      field_key=item_key, value=body))
    else:
        row.value = body
        # 화면에서 직접 저장한 값은 「공통에서 받은 값」이 아니다.
        row.from_common_at = None
    session.flush()


def save_values(session, *, policy: MarketPolicy, market: str, values: dict) -> int:
    """여러 항목을 한 번에. {item_key: config dict}. 바뀐 항목 수를 돌려준다."""
    before = values_for(session, policy.id, market)
    for k, cfg in (values or {}).items():
        save_item(session, policy=policy, market=market, item_key=k,
                  config=dict(cfg or {}))
    after = values_for(session, policy.id, market)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return len(changed)


def values_for(session, policy_id: int, market: str) -> dict:
    """저장된 항목만. {item_key: config dict}. 안 정한 항목은 **키 자체가 없다**."""
    out = {}
    for v in session.scalars(select(MarketPolicyValue).where(
            MarketPolicyValue.policy_id == policy_id,
            MarketPolicyValue.market == market)):
        try:
            out[v.field_key] = json.loads(v.value) if v.value else {}
        except (TypeError, ValueError):
            out[v.field_key] = {}       # 깨진 값은 「안 정함」처럼 취급(조용히 쓰지 않는다)
    return out


def readiness(session, policy_id: int, markets: list[str] | None = None) -> dict:
    """마켓별 채움 현황 — {market: {filled, total, price_ready, missing:[...]}}.

    price_ready=False 면 그 마켓 가격 계산에 이 정책을 쓰면 안 된다.

    markets 를 주면 그 마켓만 센다(기본은 전 마켓 — 기존 호출부는 그대로 동작).
      [2026-08-12] 노션 「체크한 것만 가공 활성화」 — 안 켠 마켓까지 세면
      **분모에 영영 안 채울 칸이 남아 100% 가 안 찬다.** 화면이 「할 일이 남았다」고
      계속 말하는데 실제로 할 일은 없는 상태가 된다.
    """
    out = {}
    for mk in (markets if markets is not None else MARKET_KEYS):
        got = values_for(session, policy_id, mk)
        keys = item_keys_for(mk)
        missing = [k for k in PRICE_REQUIRED_ITEMS if not got.get(k)]
        out[mk] = {'filled': len([k for k in keys if got.get(k)]),
                   'total': len(keys),
                   'price_ready': not missing, 'missing': missing}
    return out


def apply_to(session, *, policy: MarketPolicy, model_codes: list[str]) -> int:
    """상품들에 정책을 붙인다(노션 「그룹핑 — 체크 후 적용」). 이미 붙어 있으면 갈아끼운다."""
    codes = [c for c in dict.fromkeys(model_codes or []) if c]
    if not codes:
        raise PolicyError('적용할 상품을 하나도 고르지 않았어요.')
    from lemouton.sourcing.models import Model
    known = set(session.scalars(select(Model.model_code).where(
        Model.model_code.in_(codes))))
    unknown = [c for c in codes if c not in known]
    if unknown:
        raise PolicyError(f'없는 상품이 섞여 있어요: {", ".join(unknown[:5])}')
    cur = {l.model_code: l for l in session.scalars(select(BundlePolicyLink).where(
        BundlePolicyLink.model_code.in_(codes)))}
    for c in codes:
        row = cur.get(c)
        if row is None:
            session.add(BundlePolicyLink(model_code=c, policy_id=policy.id))
        else:
            row.policy_id = policy.id
    session.flush()
    return len(codes)


def policy_of(session, model_code: str) -> MarketPolicy | None:
    link = session.get(BundlePolicyLink, model_code)
    if link is None:
        return None
    p = session.get(MarketPolicy, link.policy_id)
    return p if p is not None and p.deleted_at is None else None


def toggle_default(session, *, policy: MarketPolicy) -> bool:
    """기본정책(여러 번 쓰는 템플릿) 지정을 켜고 끈다.

    [2026-08-19 사장님 확정] 「여러개 템플릿 생성 가능」 — 예전엔 기본 하나만 허용해
    새로 지정하면 이전 것이 풀렸다(대표=1개 제한). 지금은 브랜드·카테고리별로
    여러 개를 동시에 기본정책으로 둘 수 있어, 단순 토글로 바뀐다.
    """
    policy.is_default = 0 if policy.is_default else 1
    session.flush()
    return bool(policy.is_default)


def applied_count(session, policy_id: int) -> int:
    from sqlalchemy import func
    return session.query(func.count()).select_from(BundlePolicyLink).filter(
        BundlePolicyLink.policy_id == policy_id).scalar() or 0


def applied_products_list(session, policy_id: int) -> list[dict]:
    """이 정책이 붙은 상품 **전체** 목록 — 정책 목록 화면 호버 카드용(가볍게 code·name 만).

    `applied_count` 와 같은 원천(`BundlePolicyLink`)만 본다 — 숫자와 목록이
    서로 다른 근거로 갈리면 안 된다(구성별 override 인 SetPolicyLink 는 별개).

    🔴 `applied_products`(아래, #1059 정책 고르기 카드용)와 다른 함수다 —
       그쪽은 카드 여러 장을 한 화면에 띄우느라 `{total, sample(최대 limit개)}`
       로 자른다. 이쪽은 정책 목록 표 한 줄의 호버 카드 하나만 그리므로
       자를 필요가 없어 **전체**를 그대로 돌려준다(정책 하나가 수백 개
       상품에 붙는 극단적 경우는 카드 쪽 스크롤이 대신 감당한다).
    """
    from lemouton.sourcing.models import Model
    rows = session.execute(
        select(Model.model_code, Model.model_name_display, Model.model_name_raw)
        .join(BundlePolicyLink, BundlePolicyLink.model_code == Model.model_code)
        .where(BundlePolicyLink.policy_id == policy_id)
        .order_by(Model.model_name_display, Model.model_name_raw)
    ).all()
    return [{'code': code, 'name': (disp or raw or code)} for code, disp, raw in rows]


# ── 브랜드 분류 (노션 「브랜드별로 정책분류」) ─────────────────────────────

def brand_counts(session) -> list[tuple[str | None, int]]:
    """브랜드별 정책 수. 많은 순 → 이름 순. 브랜드 없는 것은 **맨 뒤**.

    맨 뒤에 두는 이유 — 「브랜드 없음」은 대개 만들다 만 정책이라
    목록 위쪽을 차지하면 진짜 정책이 밀린다.
    """
    from collections import Counter
    c = Counter(p.brand for p in session.scalars(select(MarketPolicy).where(
        MarketPolicy.deleted_at.is_(None))))
    named = sorted(((b, n) for b, n in c.items() if b),
                   key=lambda x: (-x[1], x[0]))
    if None in c:
        named.append((None, c[None]))
    return named


# ── 내보낼 마켓 (노션 「마켓별 토글 활성화」) ──────────────────────────────

def enabled_markets(session, policy: MarketPolicy) -> list[str]:
    """내보낼 마켓. 아직 안 정했으면 **전부 켜진 것**으로 본다.

    🔴 안 정한 것을 「전부 꺼짐」으로 읽으면, 지금까지 잘 나가던 정책이
      이 기능을 붙이는 순간 조용히 멈춘다. 값이 깨져 있을 때도 같은 이유로
      「전부 켜짐」으로 본다 — 읽다 실패했다고 전송을 멈추면 안 된다.
    """
    raw = getattr(policy, 'enabled_markets', None)
    if raw is None:
        return list(MARKET_KEYS)
    try:
        got = json.loads(raw)
    except (TypeError, ValueError):
        return list(MARKET_KEYS)
    if not isinstance(got, list):
        return list(MARKET_KEYS)
    return [m for m in MARKET_KEYS if m in set(got)]


def set_enabled_markets(session, *, policy: MarketPolicy,
                        markets: list[str]) -> list[str]:
    """내보낼 마켓을 정한다. 빈 목록도 받는다(= 아무 데도 안 나감)."""
    picked = [m for m in dict.fromkeys(markets or []) if m]
    unknown = [m for m in picked if m not in MARKET_KEYS]
    if unknown:
        raise PolicyError(f'모르는 마켓이에요: {", ".join(unknown)}')
    ordered = [m for m in MARKET_KEYS if m in set(picked)]
    policy.enabled_markets = json.dumps(ordered, ensure_ascii=False)
    session.flush()
    return ordered


# ── 정책 고르기 카드(#1059) — 마켓별 상태 3단계·적용 상품 목록 ─────────────────

def market_status(session, policy_id: int, markets: list[str] | None = None) -> dict:
    """마켓별 위상 3단계 — {market: 'wait'|'mid'|'sale'}.

    옵션생성 화면의 위상 3종(`lemouton/matrix/readiness.py` — draft/ready/used)과
    같은 이름 체계로 맞춘다(회색·파랑·초록 = wait·mid·sale).
      · wait(작성중) — 이 마켓 가격을 아직 못 쓴다(readiness.price_ready=False)
      · mid(준비됨)  — 가격은 쓸 수 있는데, 이 정책에 붙은 상품이 아직 없다
      · sale(적용됨) — 가격도 되고 붙은 상품도 있다

    markets 를 생략하면 **켠 마켓만** 돌려준다(정책 카드의 「내보낼 마켓」 배지 줄과
    1:1로 맞아야 하기 때문 — 꺼진 마켓까지 섞으면 카드에 뜻 없는 회색 칸이 늘어난다).
    """
    p = session.get(MarketPolicy, policy_id)
    if p is None:
        return {}
    on = markets if markets is not None else enabled_markets(session, p)
    if not on:
        return {}
    rd = readiness(session, policy_id, markets=on)
    applied = applied_count(session, policy_id)
    out = {}
    for mk in on:
        if not rd.get(mk, {}).get('price_ready'):
            out[mk] = 'wait'
        elif applied == 0:
            out[mk] = 'mid'
        else:
            out[mk] = 'sale'
    return out


def applied_products(session, policy_id: int, limit: int = 3) -> dict:
    """이 정책이 붙은 상품 — {'total': 전체개수, 'sample': [{model_code,no,name}…]}.

    🔴 키 이름을 `items` 로 두지 않는다 — Jinja 에서 dict.items 는 딕셔너리 값이
      아니라 파이썬 내장 `.items()` 메서드로 먼저 풀려 화면이 조용히 깨진다.
    sample 은 최근 붙은 순으로 최대 limit 개(호버 카드 대표 목록용). 전체 개수는
    limit 과 무관하게 항상 정확해야 「n개 더보기」 문구가 거짓말을 안 한다.
    """
    from lemouton.sourcing.models import Model
    total = applied_count(session, policy_id)
    if total == 0:
        return {'total': 0, 'sample': []}
    rows = (session.query(Model.model_code, Model.display_no, Model.model_name_display)
            .join(BundlePolicyLink, BundlePolicyLink.model_code == Model.model_code)
            .filter(BundlePolicyLink.policy_id == policy_id)
            .order_by(BundlePolicyLink.applied_at.desc())
            .limit(limit).all())
    sample = [{'model_code': code, 'no': no, 'name': (name or no or code)}
             for code, no, name in rows]
    return {'total': total, 'sample': sample}

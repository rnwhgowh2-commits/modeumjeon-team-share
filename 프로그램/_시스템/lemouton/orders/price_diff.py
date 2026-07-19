"""주문 시점 가격 차이 — 「올릴 때 매입가」 vs 「지금 매입가」 3층 대조 (Phase 1B M4).

사장님 확정 요구: "주문 시점에 가격 차이가 있다면 화면에 전후 가격을 전부 표시".

3층이 각각 어디서 오는지 (전부 **호출만** — 계산식은 이 모듈에 없다):
  1층 올릴 때 매입가 = ``uploader.reconcile.last_confirmed_snapshot`` 이 고른
      PriceSnapshot.final_purchase_price. **실제로 마켓이 받은** 스냅샷만
      (action='upload' AND uploaded_at IS NOT NULL) — 전송 실패한 시도는 기준선이
      되지 못한다.
  2층 주문 걸린 판매가 = 주문 행의 `단가`(개당 판매가). 마켓이 준 실값.
  3층 지금 매입가 = ``api_pricing._option_matrix_data`` 의 대표 소싱처(최저 크롤가)
      → ``api_benefits.compute_breakdown`` 의 final_price.

마진 = ``uploader.reconcile.compute_margin_amount`` (기존 함수 그대로).
      = (판매가 − 배송비) × (1 − 수수료율) − 지금매입가.

★ 폴백 절대 금지 — 세 층 중 하나라도 모르면 그 행은 'unknown'(화면 "확인 불가").
  추정가·0원·평균으로 채우지 않는다. 전/후 두 값을 하나로 뭉개지 않는다.

★ N+1 회피 — 행 단위 쿼리가 하나도 없다:
  · 대상 색인(SetChannel⋈SetChannelOption) 1회
  · Option(색상/사이즈) 1회 IN 쿼리
  · PriceSnapshot 1회 IN 쿼리(파이썬에서 대상별 최신 1건 선별)
  · _option_matrix_data 는 **모델코드당** 1회(행당 아님)
  · _build_breakdown_cache 1회 → compute_breakdown 은 캐시 재사용
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# 주문 행의 `판매처`(한글 라벨) → 내부 마켓 슬러그. order_export._MARKET_KO 의 역방향.
MARKET_SLUG_BY_LABEL = {
    "스마트스토어": "smartstore", "롯데온": "lotteon", "쿠팡": "coupang",
    "11번가": "eleven11", "옥션": "auction", "G마켓": "gmarket",
}

# resolve_market_policy 가 아는 마켓만. 모르는 마켓을 넣으면 조용히 'ss'(6%)로
# 폴백해 **엉뚱한 수수료로 마진을 날조**하므로(unified._PREFIX_MAP), 화이트리스트로 막는다.
# reconcile.PRICED_MARKETS 와 같은 근거.
_FEE_PREFIX = {"smartstore": "ss", "coupang": "coupang"}

# 화면 상태 — 색이 상황을 말한다(시안 C안 범례와 1:1).
STATE_SAME = "same"        # 회색 — 안 바뀜
STATE_LOSS = "loss"        # 빨강 — 올랐고 손해 전환
STATE_WARN = "warn"        # 주황 — 올랐지만 아직 남음
STATE_GAIN = "gain"        # 초록 — 내려서 더 남음
STATE_UNKNOWN = "unknown"  # 회색 — 확인 불가


@dataclass
class RowPriceDiff:
    """주문 한 줄의 가격 전후. 모르는 값은 전부 None (0 아님)."""

    upload_purchase: int | None = None    # 올릴 때 매입가
    current_purchase: int | None = None   # 지금 매입가
    order_sale_price: int | None = None   # 주문 걸린 판매가(단가)
    margin: int | None = None             # 지금 사면 마진
    state: str = STATE_UNKNOWN
    reason: str | None = None             # 확인 불가 사유(사람이 읽는 말)
    canonical_sku: str | None = None      # 진단용


def row_key(r: dict) -> str:
    """주문 행 식별자. 화면(JS)과 서버가 같은 규칙을 쓴다.

    `판매처|오픈마켓주문번호` 만으로는 한 주문에 여러 상품이 든 행을 구분 못 해
    (order_export._row_key 와 같은 이유로) 상품명·옵션까지 붙인다.
    """
    return "|".join([str(r.get("판매처") or ""), str(r.get("오픈마켓주문번호") or ""),
                     str(r.get("상품명") or ""), str(r.get("옵션") or "")])


# ─────────────────────────────────────────────────────────────────────────────
#  1) 주문 행 → canonical_sku  (id 기반 조인만. 이름 추측 금지)
# ─────────────────────────────────────────────────────────────────────────────

def _row_market_ids(r: dict) -> tuple[str | None, list[str]]:
    """행이 들고 있는 (마켓옵션ID, [마켓상품ID…]). 없으면 (None, []).

    order_export 의 각 마켓 파서가 **응답에 실제로 있는 필드만** `_pd_` 키로 보존한다
    (엑셀·화면 열은 ALL_COLUMNS 화이트리스트라 `_pd_` 는 새어나가지 않는다).

    옵션 단위(정확 일치):
      · 쿠팡  vendorItemId → `_pd_market_option_id`
      · 11번가 prdStckNo(주문상품옵션코드) → `_pd_market_option_id`
    상품 단위(옵션은 색·사이즈 텍스트로 좁힘):
      · 롯데온 spdNo → `_lo_spdno`
      · 스마트스토어 productId(채널)·originalProductId(원상품) → `_pd_market_product_id(_alt)`
      · 옥션·G마켓 SiteGoodsNo → `_pd_market_product_id`

    스마트스토어·옥션·G마켓의 **옵션 단위** id 는 응답에서 확인되지 않았다(각 파서 주석 참조).
    추측해서 잇지 않는다 — 못 좁히면 화면은 '확인 불가'로 남는다.
    """
    oid = r.get("_pd_market_option_id") or r.get("_vid")
    pids, seen = [], set()
    for v in (r.get("_pd_market_product_id"), r.get("_pd_market_product_id_alt"),
              r.get("_lo_spdno")):
        s = str(v).strip() if v not in (None, "") else ""
        if s and s not in seen:
            seen.add(s)
            pids.append(s)
    oid = str(oid).strip() if oid not in (None, "") else ""
    return (oid or None, pids)


def _target_index(session):
    """(마켓,마켓옵션ID)→[(sku,계정)] · (마켓,마켓상품ID)→[(sku,계정)] 색인. 쿼리 1회.

    근거 테이블은 reconcile.market_targets_for 와 같은 SetChannel⋈SetChannelOption —
    계정(account_key)까지 들고 있는 유일한 자리다. MarketRegistration 은 PK 가
    (sku,market) 라 같은 마켓의 두 계정을 구분 못 해 쓰지 않는다.
    """
    from lemouton.sets.models import SetChannel, SetChannelOption

    rows = (session.query(SetChannel.market, SetChannel.account_key,
                          SetChannel.market_product_id,
                          SetChannelOption.market_option_id,
                          SetChannelOption.canonical_sku)
            .join(SetChannelOption, SetChannelOption.channel_id == SetChannel.id)
            .filter(SetChannelOption.status == "matched")
            .all())
    by_option, by_product = defaultdict(list), defaultdict(list)
    for market, acct, mpid, moid, sku in rows:
        pair = (sku, acct or "default")
        if moid:
            by_option[(market, str(moid))].append(pair)
        if mpid:
            by_product[(market, str(mpid))].append(pair)
    return by_option, by_product


def _option_axis_index(session, skus):
    """sku → (정규화 색상, 정규화 사이즈, model_code). 쿼리 1회.

    matcher.normalize 를 그대로 쓴다(공백·단위·영한 색상 매핑) — 옵션 매칭 규칙을
    새로 만들지 않는다. uploader.linker 가 마켓 옵션을 sku 에 붙일 때 쓰는 그 함수다.
    """
    from lemouton.mapping.matcher import normalize
    from lemouton.sourcing.models import Option

    if not skus:
        return {}
    out = {}
    for o in (session.query(Option)
              .filter(Option.canonical_sku.in_(list(skus))).all()):
        out[o.canonical_sku] = (normalize(o.color_display or o.color_code or ""),
                                normalize(o.size_display or o.size_code or ""),
                                o.model_code)
    return out


def _resolve_targets(session, rows):
    """행키 → (sku, market, account_key). 못 찾은 행은 아예 안 담는다(추측 금지).

    2단계, **둘 다 유일하게 걸릴 때만** 인정한다(set_link_service._resolve_env_prefix
    의 '정확히 1건일 때만' 규약과 같음). 애매하면 화면에 '확인 불가'가 뜨는 게
    엉뚱한 상품의 가격을 보여주는 것보다 낫다.
      1단계 마켓옵션ID 정확 일치 (쿠팡 vendorItemId · 11번가 prdStckNo)
      2단계 마켓상품ID + 옵션 텍스트의 색상·사이즈 동시 포함
            (롯데온 spdNo · 스마트스토어 productId/originalProductId · 옥션·G마켓 SiteGoodsNo)
    """
    from lemouton.mapping.matcher import normalize

    by_option, by_product = _target_index(session)

    # 2단계 후보 sku 만 모아 Option 을 한 번에 긁는다(행마다 쿼리 금지).
    need = set()
    plan = []      # (key, market, oid, pid)
    for r in rows:
        market = MARKET_SLUG_BY_LABEL.get(str(r.get("판매처") or "").strip())
        if not market:
            continue
        oid, pids = _row_market_ids(r)
        if not oid and not pids:
            continue
        plan.append((row_key(r), market, oid, pids, str(r.get("옵션") or "")))
        for pid in pids:
            for sku, _ in by_product.get((market, pid), []):
                need.add(sku)
    axis = _option_axis_index(session, need)

    out = {}
    for key, market, oid, pids, opt_text in plan:
        hits = by_option.get((market, oid), []) if oid else []
        if len(hits) == 1:
            sku, acct = hits[0]
            out[key] = (sku, market, acct)
            continue
        # 상품ID 후보가 여럿인 이유: 스마트스토어는 주문이 채널상품번호·원상품번호를 둘 다 주고,
        #  연동은 그중 하나로 등록돼 있다. 어느 쪽으로 걸리든 같은 채널을 가리키므로 합집합으로
        #  본다(중복 제거). 합쳐도 2건 이상이면 아래 색·사이즈 텍스트로 좁힌다.
        cands, seen_c = [], set()
        for pid in pids:
            for pair in by_product.get((market, pid), []):
                if pair not in seen_c:
                    seen_c.add(pair)
                    cands.append(pair)
        if not cands:
            continue
        if len(cands) == 1:                     # 단일 옵션 상품 — 텍스트 매칭 불필요
            sku, acct = cands[0]
            out[key] = (sku, market, acct)
            continue
        norm_opt = normalize(opt_text)
        matched = [(sku, acct) for sku, acct in cands
                   if sku in axis
                   and axis[sku][0] and axis[sku][1]
                   and axis[sku][0] in norm_opt and axis[sku][1] in norm_opt]
        if len(matched) == 1:                   # 유일할 때만. ambiguous 는 버린다
            sku, acct = matched[0]
            out[key] = (sku, market, acct)
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  2) 올릴 때 매입가 — 스냅샷 일괄 (last_confirmed_snapshot 과 같은 필터)
# ─────────────────────────────────────────────────────────────────────────────

def _confirmed_snapshots(session, targets):
    """(sku,market,account_key) → PriceSnapshot. 쿼리 1회.

    reconcile.last_confirmed_snapshot 은 단건 전용이라 행마다 부르면 N+1 이 난다.
    **필터 조건과 '최신=id 내림차순 첫 행' 규약을 그대로** 옮겨 일괄로 만든다
    (조건이 갈리면 화면값과 업로드 게이트값이 달라지므로 여기서 바꾸면 안 된다).
    """
    from lemouton.uploader.models import PriceSnapshot

    if not targets:
        return {}
    skus = {t[0] for t in targets}
    rows = (session.query(PriceSnapshot)
            .filter(PriceSnapshot.canonical_sku.in_(list(skus)),
                    PriceSnapshot.action == "upload",
                    PriceSnapshot.uploaded_at.isnot(None))
            .order_by(PriceSnapshot.id.desc())
            .all())
    out = {}
    for sp in rows:                       # id 내림차순 → 대상별 첫 등장이 최신
        k = (sp.canonical_sku, sp.market, sp.account_key or "default")
        if k not in out:
            out[k] = sp
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  3) 지금 매입가 — 대표 소싱처 크롤가 → compute_breakdown (호출만)
# ─────────────────────────────────────────────────────────────────────────────

def _current_purchase(session, skus, matrix_loader=None):
    """sku → 지금 최종매입가. 못 구한 sku 는 **키를 안 만든다**(0 으로 채우지 않음).

    소싱 값은 매트릭스 단일 진실 원천(_option_matrix_data)을 그대로 쓴다 —
    카드·영수증과 같은 값이어야 화면끼리 안 갈린다(sets_api._current_source_value_map
    과 동일 경로·동일 대표 선정: 크롤가 최저).
    """
    from webapp.routes.api_benefits import _build_breakdown_cache, compute_breakdown

    if matrix_loader is None:
        from webapp.routes.api_pricing import _option_matrix_data as matrix_loader

    from lemouton.sourcing.models import Option

    want = set(skus)
    if not want:
        return {}, {}
    items, seen_models = [], set()
    # model_code 별로 1회만 매트릭스를 읽는다(행당 아님).
    model_by_sku = {o.canonical_sku: o.model_code
                    for o in session.query(Option)
                    .filter(Option.canonical_sku.in_(list(want))).all()}
    for mc in set(model_by_sku.values()):
        if mc in seen_models:
            continue
        seen_models.add(mc)
        try:
            data = matrix_loader(mc)
        except Exception:                      # noqa: BLE001
            logger.exception("옵션 매트릭스 조회 실패 model=%s", mc)
            continue
        if not data or not data.get("ok"):
            continue
        for o in (data.get("options") or []):
            if o.get("sku") not in want:
                continue
            cands = [sc for sc in (o.get("sources") or [])
                     if sc.get("source_id") is not None
                     and sc.get("crawled_price") is not None]
            if not cands:
                continue                        # 크롤값 없음 → 확인 불가로 남긴다
            best = min(cands, key=lambda sc: sc["crawled_price"])
            items.append({"sku": o["sku"], "source_id": best["source_id"],
                          "sale_price": best["crawled_price"],
                          "source_product_id": best.get("source_product_id")})

    finals, errors = {}, {}
    if not items:
        return finals, errors
    try:
        cache = _build_breakdown_cache(session, items)   # ★ N+1 제거 — 딱 1회
    except Exception:                                    # noqa: BLE001
        logger.exception("breakdown 캐시 실패 — %d건 확인 불가", len(items))
        return finals, {it["sku"]: "계산 실패" for it in items}
    for it in items:
        try:
            bd = compute_breakdown(session, sku=it["sku"],
                                   source_id=_sid_key(it["source_id"]),
                                   sale_price=float(it["sale_price"]), _cache=cache,
                                   source_product_id=it.get("source_product_id"))
        except Exception:                                # noqa: BLE001
            logger.exception("최종매입가 계산 실패 sku=%s", it["sku"])
            errors[it["sku"]] = "계산 실패"
            continue
        if bd and bd.get("final_price") is not None:
            finals[it["sku"]] = int(bd["final_price"])
        else:
            errors[it["sku"]] = "계산 실패"
    return finals, errors


def _sid_key(v):
    """소싱처 id 정규화 — sets_api._sid_key 와 같은 규약(문자열 카탈로그 키 허용)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


# ─────────────────────────────────────────────────────────────────────────────
#  4) 마진 — 기존 수수료·마진 함수 재사용 (여기서 산식을 만들지 않는다)
# ─────────────────────────────────────────────────────────────────────────────

class _PriceLike:
    """compute_margin_amount 가 읽는 모양(final_price/breakdown)만 맞춘 어댑터.

    마진 산식을 복사하지 않으려고 둔다 — 실제 계산은 reconcile.compute_margin_amount
    한 곳에서만 일어난다(정의가 갈리면 같은 상품 마진이 화면마다 달라진다).
    """

    def __init__(self, final_price, fee_rate, shipping_fee=0):
        self.final_price = final_price
        self.breakdown = {"fee_rate": fee_rate, "shipping_fee": shipping_fee}


def _parse_pct(v):
    """'11.55%' → 0.1155. 못 읽으면 None(0 으로 넘기지 않는다)."""
    if v is None or v == "":
        return None
    try:
        s = str(v).strip().rstrip("%")
        if not s:
            return None
        return float(s) / 100.0
    except (TypeError, ValueError):
        return None


def _fee_rate_for(row, market, tpl):
    """이 주문에 쓸 수수료율(분수). 모르면 None → 마진은 '확인 불가'.

    순서에 근거가 있다:
      1. 주문 행의 `수수료율` — 마켓 정산이 준 **실값**(order_export._finalize_rows
         가 마켓수수료÷총주문금액으로 채움). 추정이 아니므로 최우선.
      2. 없으면 pricing.unified.resolve_market_policy 의 fee_rate — 우리가 가격을
         만들 때 쓴 그 요율. 단 _FEE_PREFIX 에 있는 마켓만: resolve_market_policy 는
         모르는 마켓을 조용히 'ss'(6%)로 폴백해 롯데온·11번가 마진을 날조한다.
      3. 둘 다 없으면 None.
    """
    real = _parse_pct(row.get("수수료율"))
    if real is not None and 0 <= real < 1:
        return real
    prefix = _FEE_PREFIX.get(market)
    if not prefix:
        return None
    from lemouton.pricing.unified import resolve_market_policy
    try:
        return float(resolve_market_policy(tpl, prefix, "sourcing").get("fee_rate"))
    except Exception:                                    # noqa: BLE001
        logger.exception("수수료율 조회 실패 market=%s", market)
        return None


def _price_templates_for(session, skus):
    """sku → PriceTemplate. reconcile._price_template_for 와 같은 경로를 일괄로.

    sku → Option.model_code → Model.price_template_id → PriceTemplate. 쿼리 3회(고정).
    """
    from lemouton.sourcing.models import Model, Option
    from lemouton.templates.models import PriceTemplate

    if not skus:
        return {}
    opts = (session.query(Option.canonical_sku, Option.model_code)
            .filter(Option.canonical_sku.in_(list(skus))).all())
    model_by_sku = dict(opts)
    codes = set(model_by_sku.values())
    if not codes:
        return {}
    tpl_id_by_code = {m.model_code: m.price_template_id
                      for m in session.query(Model)
                      .filter(Model.model_code.in_(list(codes))).all()}
    tpl_ids = {v for v in tpl_id_by_code.values() if v}
    tpl_by_id = {}
    if tpl_ids:
        tpl_by_id = {t.id: t for t in session.query(PriceTemplate)
                     .filter(PriceTemplate.id.in_(list(tpl_ids))).all()}
    return {sku: tpl_by_id.get(tpl_id_by_code.get(mc))
            for sku, mc in model_by_sku.items()}


# ─────────────────────────────────────────────────────────────────────────────
#  5) 조립
# ─────────────────────────────────────────────────────────────────────────────

def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(round(float(str(v).replace(",", ""))))
    except (TypeError, ValueError):
        return None


def _state_of(upload, current, margin):
    if upload is None or current is None:
        return STATE_UNKNOWN
    if int(upload) == int(current):
        return STATE_SAME
    if int(current) > int(upload):
        # 손해 전환은 **마진을 실제로 계산했을 때만** 단정한다. 마진을 모르면
        # '올랐다'까지만 말한다(모르는 걸 손해로 단정하지 않음).
        return STATE_LOSS if (margin is not None and margin < 0) else STATE_WARN
    return STATE_GAIN


def build_price_diffs(session, rows, *, matrix_loader=None) -> dict:
    """주문 행 목록 → {행키: RowPriceDiff dict}. 실패는 전부 '확인 불가'로 남는다."""
    rows = list(rows or [])
    if not rows:
        return {}

    targets = _resolve_targets(session, rows)
    skus = {t[0] for t in targets.values()}
    snaps = _confirmed_snapshots(session, set(targets.values()))
    finals, calc_errors = _current_purchase(session, skus, matrix_loader=matrix_loader)
    tpls = _price_templates_for(session, skus)

    out = {}
    for r in rows:
        key = row_key(r)
        sale = _to_int(r.get("단가"))
        d = RowPriceDiff(order_sale_price=sale)
        tgt = targets.get(key)
        if not tgt:
            d.reason = "이 주문을 우리 옵션(SKU)에 연결하지 못했어요"
            out[key] = asdict(d)
            continue
        sku, market, acct = tgt
        d.canonical_sku = sku
        sp = snaps.get((sku, market, acct))
        if sp is None:
            d.reason = "마켓에 실제로 올라간 가격 기록(스냅샷)이 없어요"
        elif sp.final_purchase_price is not None:
            d.upload_purchase = int(sp.final_purchase_price)
        else:
            d.reason = "올릴 때 매입가가 기록되지 않았어요"

        if sku in finals:
            d.current_purchase = finals[sku]
        else:
            d.reason = d.reason or (calc_errors.get(sku)
                                    or "지금 소싱처 가격을 못 읽었어요")

        if d.current_purchase is not None and sale is not None:
            fee = _fee_rate_for(r, market, tpls.get(sku))
            if fee is not None:
                from lemouton.uploader.reconcile import compute_margin_amount
                d.margin = compute_margin_amount(
                    _PriceLike(sale, fee, _to_int(r.get("배송비")) or 0),
                    d.current_purchase)
        d.state = _state_of(d.upload_purchase, d.current_purchase, d.margin)
        out[key] = asdict(d)
    return out

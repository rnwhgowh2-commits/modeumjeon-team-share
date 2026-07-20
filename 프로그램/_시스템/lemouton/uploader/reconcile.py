# -*- coding: utf-8 -*-
"""[Phase 1B M3-2] 크롤 완료 → 재계산 → 판정 → 전송 → 스냅샷 기록 파이프라인.

M3-1 이 만든 :func:`~lemouton.uploader.upload_gate.decide_upload` (순수 판정) 와
:class:`~lemouton.uploader.models.PriceSnapshot` (이력) 을 **실제 배선**한다.
판정 로직·가격 계산 로직은 여기서 다시 쓰지 않는다 — 전부 호출만 한다.

■ 흐름 (1 소싱처 상품 = 1 회 호출)
    소싱처 크롤 저장 완료
      → 이 SourceProduct 에 걸린 canonical_sku 들 역추적
      → compute_breakdown 으로 **최종매입가** 재계산 (단일 진실 원천)
      → compute_market_price 로 **업로드가** 가공 (표시가=업로드가 단일 진입점)
      → 마진금액 산출 (:func:`compute_margin_amount`)
      → decide_upload(직전 스냅샷 vs 이번 값) → P0/P1/P2
      → P0 부터 순서대로 마켓 전송 (실전송 잠금 통과 시에만)
      → 업로드·스킵·보류 **전부** PriceSnapshot 1행

■ 왜 save_crawl_result 안에 인라인으로 넣지 않았나
    ``save_crawl_result`` / ``persist_crawled_options`` 는 크롤 루프 안에서 URL 하나당
    한 번씩 도는 **저장 전용** 함수이고, 진단 스크립트(scripts/_ssg_verify.py 등)도
    직접 부른다. 여기에 마켓 호출을 인라인으로 박으면
      · 진단 스크립트를 돌리는 것만으로 마켓에 값이 나가고,
      · 마켓 rate limit(계정당 초 간격)을 크롤 루프가 그대로 뒤집어쓰며,
      · 저장 트랜잭션이 마켓 응답을 기다리는 동안 열려 있게 된다.
    그래서 **크롤 저장 뒤에 이어지는 별도 패스**로 뺐다. 호출 지점은
    :func:`reconcile_after_crawl` 하나이고, 크롤 완료 이벤트가 이걸 부른다.

■ 실전송 잠금 (이 프로젝트 불변식)
    :func:`~lemouton.uploader.runtime.real_upload_armed` 두 겹 잠금을 그대로 쓴다
    (서버 열쇠 ``MOUM_LIVE_UPLOAD`` + 화면 열쇠 ``autosend_mode == 'real'``).
    잠겨 있으면 **어댑터를 조회조차 하지 않는다** — 드라이런 어댑터를 태우지도
    않는다. DryRunAdapter 는 success=True 를 돌려주는데, 그걸 성공으로 적으면
    ``uploaded_at`` 이 채워져 "마켓에 올라간 값" 기준선이 오염되고, 나중에 잠금을
    풀었을 때 **한 번도 안 나간 값을 '이미 나갔다'고 판단해 영영 안 보낸다**.
    잠금 상태의 판정 결과는 action='hold' + uploaded_at=NULL 로 남는다(= 아직 안 올림).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import PriceSnapshot
from .upload_gate import decide_upload, GateDecision, STOCK_UNKNOWN

logger = logging.getLogger(__name__)

# P0 가 P1·P2 보다 먼저 나가야 한다 — 게이트가 매긴 우선순위의 정렬 키.
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}

# 가격 정책(마진율·수수료율·배송비)이 PriceTemplate 에 **실제로 정의된** 마켓만.
#   resolve_market_policy 는 모르는 마켓을 조용히 'ss'(스마트스토어) 정책으로
#   떨어뜨린다(unified.py:225 `_PREFIX_MAP.get(..., 'ss')`). 롯데온·11번가·ESM 을
#   그대로 태우면 **스스 수수료율로 계산한 값이 다른 마켓에 올라간다** = 금전 손실.
#   그래서 여기서 명시적으로 좁히고, 나머지는 사유를 적어 스킵한다(조용한 폴백 금지).
PRICED_MARKETS = ("smartstore", "coupang")

# compute_market_price 가 쓰는 마켓 접두 (unified._PREFIX_MAP 과 같은 어휘).
_MARKET_PREFIX = {"smartstore": "ss", "coupang": "coupang"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
#  1) 역추적 — 크롤된 SourceProduct → 이 값이 영향을 주는 canonical_sku 들
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceLink:
    """크롤된 소싱처 옵션 1개 ↔ 우리 SKU 1개의 연결 + 이번에 읽은 값."""

    canonical_sku: str
    source_id: object            # int(source_registry.id) | 'key:<site>' 합성
    source_option_id: int | None
    surface_price: int | None    # 이 옵션의 표면노출가. None = 못 읽음(폴백 금지)
    stock: int | None            # None=미크롤 / -1=확인불가 / 0=품절 / 999=있음
    source_id_exact: bool        # False = 'key:' 합성 → 혜택 템플릿 조회가 안 된다


def source_links_for(session, source_product) -> list[SourceLink]:
    """SourceProduct → 이 상품 크롤값을 쓰는 (sku, 소싱처, 옵션값) 목록.

    집에는 sku→소싱처 방향 헬퍼만 있고(``get_source_data_for_sku``) 역방향이 없어
    여기서 만든다. 기준 테이블은 **실제 FK 가 있는** ``option_source_links``
    (sku ↔ source_options) 다 — URL 문자열 비교보다 정확하다.

    ``source_id`` 는 ``compute_breakdown`` 이 혜택 템플릿(SourceBenefitTemplate)을
    조회하는 키라 정확해야 한다. ``option_source_urls`` 에 같은 URL 행이 있으면
    거기 적힌 정수 id 를 쓰고, 없으면 ``'key:<site>'`` 합성값으로 떨어진다
    (api_benefits._resolve_site_key 가 해석하는 형식). 합성값이면 혜택 템플릿이
    조회되지 않아 **최종매입가가 표면가와 같아진다** — 그래서 조용히 넘기지 않고
    ``source_id_exact=False`` 로 표시해 스냅샷 경고로 표면화한다.
    """
    from lemouton.sources.models import OptionSourceLink, SourceOption
    from lemouton.sourcing.models_pricing import OptionSourceUrl
    from lemouton.sources.service import normalize_url

    rows = (session.query(OptionSourceLink, SourceOption)
            .join(SourceOption, OptionSourceLink.source_option_id == SourceOption.id)
            .filter(SourceOption.source_product_id == source_product.id)
            .filter(SourceOption.deleted_at.is_(None))
            .all())
    if not rows:
        return []

    sp_norm = normalize_url(source_product.url or "")
    skus = sorted({link.canonical_sku for link, _ in rows})
    # sku → 이 소싱처 URL 과 같은 곳을 가리키는 OptionSourceUrl.source_id
    src_id_by_sku: dict[str, int] = {}
    for osu in (session.query(OptionSourceUrl)
                .filter(OptionSourceUrl.canonical_sku.in_(skus)).all()):
        if osu.product_url and normalize_url(osu.product_url) == sp_norm:
            src_id_by_sku.setdefault(osu.canonical_sku, osu.source_id)

    synth = f"key:{source_product.site}" if source_product.site else None
    out: list[SourceLink] = []
    for link, so in rows:
        exact = link.canonical_sku in src_id_by_sku
        out.append(SourceLink(
            canonical_sku=link.canonical_sku,
            source_id=src_id_by_sku.get(link.canonical_sku, synth),
            source_option_id=so.id,
            # 옵션 단위 크롤가. 상품 대표가(last_price = 전 옵션 평균)로 메우지 않는다 —
            # 그건 이 옵션의 값이 아니라 다른 숫자다(폴백 금지).
            surface_price=so.current_price,
            stock=so.current_stock,
            source_id_exact=exact,
        ))
    return out


def unlinked_sku_count(session, source_product) -> int:
    """``option_source_links`` 없이 URL 로만 걸려 있는 sku 수 (진단용).

    SSG 단일상품처럼 옵션별 링크가 안 만들어지는 소싱처가 있다
    (api_benefits.py:566 에 같은 사례가 기록돼 있다). 이런 sku 는 어느
    SourceOption 이 그 sku 인지 알 수 없어 **이번 패스가 건드리지 않는다**.
    상품 대표가로 추측해 올리는 건 폴백 금지 위반이라 하지 않고, 대신 이 수치를
    결과에 실어 "조용히 빠진 게 아니라 셌다"를 남긴다.
    """
    from lemouton.sources.models import OptionSourceLink, SourceOption
    from lemouton.sourcing.models_pricing import OptionSourceUrl
    from lemouton.sources.service import normalize_url

    linked = {link.canonical_sku for link, in
              (session.query(OptionSourceLink.canonical_sku)
               .join(SourceOption, OptionSourceLink.source_option_id == SourceOption.id)
               .filter(SourceOption.source_product_id == source_product.id)
               .filter(SourceOption.deleted_at.is_(None)).all())}
    sp_norm = normalize_url(source_product.url or "")
    n = 0
    for osu in session.query(OptionSourceUrl).all():
        if (osu.product_url and normalize_url(osu.product_url) == sp_norm
                and osu.canonical_sku not in linked):
            n += 1
    return n


# ─────────────────────────────────────────────────────────────────────────────
#  2) 마켓 대상 열거 — sku 가 어느 마켓·계정의 어느 옵션에 올라가 있나
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MarketTarget:
    market: str
    account_key: str
    market_product_id: str | None
    market_option_id: str


def market_targets_for(session, canonical_sku: str) -> list[MarketTarget]:
    """sku → 매칭된 (마켓, 계정, 마켓상품ID, 마켓옵션ID) 목록.

    ``SetChannel ⋈ SetChannelOption`` 이 계정(account_key)까지 들고 있는 유일한
    자리다. ``MarketRegistration`` 은 PK 가 (sku, market) 라 **같은 마켓의 두 계정을
    표현할 수 없어** 다계정(롯데온 7계정 등)에서 기준선을 서로 덮어쓴다 — 그래서
    대상 열거의 근거로 쓰지 않는다.
    ``runtime.build_sku_by_option`` 은 같은 조인을 쓰지만 account_key 와
    market_product_id 를 버리고 방향도 반대라(옵션ID→sku) 여기선 직접 조회한다.

    matched + market_option_id 있는 행만. 폴백 금지 — 못 찾으면 안 올린다.
    """
    from lemouton.sets.models import SetChannel, SetChannelOption

    rows = (session.query(SetChannel, SetChannelOption)
            .join(SetChannelOption, SetChannelOption.channel_id == SetChannel.id)
            .filter(SetChannelOption.canonical_sku == canonical_sku)
            .filter(SetChannelOption.status == "matched")
            .filter(SetChannelOption.market_option_id.isnot(None))
            .all())
    return [MarketTarget(market=ch.market,
                         account_key=ch.account_key or "default",
                         market_product_id=ch.market_product_id,
                         market_option_id=str(opt.market_option_id))
            for ch, opt in rows]


# ─────────────────────────────────────────────────────────────────────────────
#  3) 마진금액 산출 — 게이트의 역마진 가드가 먹는 입력
# ─────────────────────────────────────────────────────────────────────────────

def compute_margin_amount(price_result, final_purchase_price) -> int | None:
    """이 업로드가로 팔았을 때 **수수료 뒤 손에 남는 금액(원)**.

    정의는 새로 만들지 않고 집에 이미 확정돼 있는 것을 그대로 뒤집는다:
    ``compute_sale_price_unified(mode='amount')`` 가 쓰는 사용자 확정 규약
    (unified.py:22-24, 2026-06-02) — "수수료 차감 후 손에 남는 금액 = 마진금액",
    즉 ``판매가 = (원가 + 마진금액) / (1 - 수수료율) + 배송비``.
    이걸 마진금액에 대해 풀면

        마진금액 = (판매가 - 배송비) × (1 - 수수료율) - 원가

    가 된다. 그래서 mode='amount' 로 만든 가격을 이 함수에 넣으면 설정한
    마진금액이 **정확히 되돌아온다**(tests: test_margin_roundtrips_amount_mode).
    수수료 기준을 임의로 '판매가 전액'으로 바꾸면 같은 상품의 마진이 계산 경로마다
    달라져 역마진 가드가 어느 쪽 숫자로 걸린 건지 알 수 없게 된다.

    원가 = **최종매입가**(혜택 다 반영된 실매입가). 모르면 None 을 돌려준다 —
    게이트는 None 을 받으면 가드를 적용하지 않는다(모르는 걸 '미달'로 단정하지 않음).
    """
    if final_purchase_price is None:
        return None
    upload = getattr(price_result, "final_price", None)
    if not upload or int(upload) <= 0:
        return None
    bd = getattr(price_result, "breakdown", None) or {}
    fee_rate = bd.get("fee_rate")
    if fee_rate is None:
        return None
    shipping = int(bd.get("shipping_fee") or 0)
    net = (int(upload) - shipping) * (1.0 - float(fee_rate))
    return int(round(net)) - int(final_purchase_price)


# ─────────────────────────────────────────────────────────────────────────────
#  4) 직전 스냅샷 — "마켓에 실제로 올라가 있는 값"
# ─────────────────────────────────────────────────────────────────────────────

def last_confirmed_snapshot(session, *, canonical_sku, market, account_key):
    """이 대상에 대해 **마켓이 실제로 받은 것이 확인된** 마지막 스냅샷.

    ★ 전송 실패 재시도의 핵심이 이 한 줄이다.
      기준선을 "마지막 스냅샷"이 아니라 "마지막으로 **올라간** 스냅샷"으로 잡는다
      (action='upload' **이면서** uploaded_at 이 채워진 행).

      전송이 실패하면 uploaded_at 을 안 채우므로 그 행은 기준선이 되지 못한다.
      따라서 다음 사이클에 게이트가 보는 prev 는 여전히 **마켓에 실제 올라가 있는
      옛 값**이고, 새 값과 다르니 자연히 다시 변동으로 잡혀 재전송된다.
      재시도를 위한 별도 큐·플래그·재시도 카운터가 필요 없다.

      재고 0→0 스킵이 재시도를 막지 않는 이유도 같다. "0→0" 의 앞 0 은
      *마켓이 받은* 0 이다. 품절 전송이 실패했다면 마켓이 받은 값은 0 이 아니라
      직전에 성공했던 값(예: 5개)이므로 게이트는 5→0 = 품절(P0)로 보고 재전송한다.
      마켓이 진짜 0 을 받은 뒤의 0→0 만 스킵된다 — 이게 정확히 원하는 동작이다.
    """
    return (session.query(PriceSnapshot)
            .filter(PriceSnapshot.canonical_sku == canonical_sku,
                    PriceSnapshot.market == market,
                    PriceSnapshot.account_key == account_key,
                    PriceSnapshot.action == "upload",
                    PriceSnapshot.uploaded_at.isnot(None))
            .order_by(PriceSnapshot.id.desc())
            .first())


def has_pending_failed_send(session, *, canonical_sku, market, account_key) -> bool:
    """마지막 시도가 '보내려 했는데 아직 못 올린' 상태로 남아 있나 (진단·표시용).

    판정에는 쓰지 않는다(위 last_confirmed_snapshot 이 이미 처리한다). 화면에
    "전송 대기/실패 N건" 을 세거나 재시도 대상을 사람에게 보여줄 때 쓴다.
    """
    latest = (session.query(PriceSnapshot)
              .filter(PriceSnapshot.canonical_sku == canonical_sku,
                      PriceSnapshot.market == market,
                      PriceSnapshot.account_key == account_key)
              .order_by(PriceSnapshot.id.desc())
              .first())
    return bool(latest is not None
                and latest.action in ("upload", "hold")
                and latest.uploaded_at is None)


# ─────────────────────────────────────────────────────────────────────────────
#  5) 재계산 — 최종매입가 · 업로드가 · 마진
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Recomputed:
    """한 (sku, 마켓) 조합의 이번 사이클 계산 결과."""

    final_purchase_price: int | None = None
    upload_price: int | None = None
    margin_amount: int | None = None
    steps: list | None = None
    warnings: tuple[str, ...] = ()


def _price_template_for(session, canonical_sku):
    """sku 가 속한 모음전의 PriceTemplate. 없으면 None(정책 기본값으로 계산된다)."""
    from lemouton.sourcing.models import Model, Option
    from lemouton.templates.models import PriceTemplate

    opt = session.query(Option).filter_by(canonical_sku=canonical_sku).first()
    if opt is None:
        return None
    m = session.query(Model).filter_by(model_code=opt.model_code).first()
    if m is None or not m.price_template_id:
        return None
    return session.query(PriceTemplate).filter_by(id=m.price_template_id).first()


def recompute(session, *, link: SourceLink, market: str, tpl,
              source_product_id: int | None = None) -> Recomputed:
    """표면가 → (compute_breakdown) 최종매입가 → (compute_market_price) 업로드가 → 마진.

    두 계산 함수 모두 **호출만** 한다. 계산식은 이 모듈에 없다.
    실패·미상은 전부 None 으로 남긴다 — 추정가·직전값 추측으로 채우지 않는다.
    """
    from webapp.routes.api_benefits import compute_breakdown
    from lemouton.pricing.unified import compute_market_price
    from lemouton.pricing.cost_basis import resolve_cost_basis
    from lemouton.sourcing.models import Option

    warns: list[str] = []
    if link.surface_price is None or int(link.surface_price) <= 0:
        warns.append("표면가 없음(크롤 실패·미크롤) — 가격 축은 기존 값을 유지합니다.")
        return Recomputed(warnings=tuple(warns))

    if not link.source_id_exact:
        warns.append(
            "소싱처 레지스트리 id 미해석('key:' 합성) — 혜택 템플릿이 조회되지 않아 "
            "최종매입가가 표면가와 같을 수 있습니다.")

    final_purchase = None
    steps = None
    try:
        bd = compute_breakdown(
            session, sku=link.canonical_sku, source_id=link.source_id,
            sale_price=float(link.surface_price),
            source_product_id=source_product_id)
        if isinstance(bd, dict):
            final_purchase = bd.get("final_price")
            steps = bd.get("steps")
    except Exception as e:   # noqa: BLE001 — 계산 실패를 성공으로 둔갑시키지 않는다
        logger.warning("[reconcile] compute_breakdown 실패 sku=%s: %s",
                       link.canonical_sku, e)
        warns.append(f"최종매입가 계산 실패 — 가격 축 미변경 ({str(e)[:60]})")
        return Recomputed(warnings=tuple(warns))

    if final_purchase is None or int(final_purchase) <= 0:
        warns.append("최종매입가 0/미상 — 가격 축은 기존 값을 유지합니다(0원 업로드 금지).")
        return Recomputed(steps=steps, warnings=tuple(warns))

    # [2026-07-20] 원가 기준 = 사장님 규칙(옵션별 낮은 쪽). 화면·미리보기와 같은 함수.
    #   이전엔 "sourcing" 하드코딩이라, 화면이 「사입 ✓적용」을 보여줘도 실제로는
    #   100% 소싱가가 올라갔다(조용한 실패). 여기까지 고쳐야 화면=업로드가 성립한다.
    #   후보 사입가는 그 옵션의 **실측** 이동평균(Option.boxhero_avg_purchase_price).
    _opt = (session.query(Option)
            .filter(Option.canonical_sku == link.canonical_sku).first())
    _pur_avg = (_opt.boxhero_avg_purchase_price or 0) if _opt else 0
    try:
        from shared.inventory_stock import get_stock_batch
        _pur_stock = (get_stock_batch(session, [link.canonical_sku]) or {}).get(
            link.canonical_sku, 0)
    except Exception as e:   # noqa: BLE001 — 재고 조회 실패를 사입 있음으로 둔갑시키지 않는다
        logger.warning("[reconcile] 사입 재고 조회 실패 sku=%s: %s", link.canonical_sku, e)
        _pur_stock = 0
        warns.append("사입 재고 조회 실패 — 소싱 기준으로 계산했습니다.")
    basis = resolve_cost_basis(int(final_purchase), _pur_avg, _pur_stock)
    _side = "purchase" if basis.side == "purchase" else "sourcing"
    pr = compute_market_price(tpl, _MARKET_PREFIX[market], _side, int(basis.cost))
    upload_price = pr.final_price
    if not upload_price or int(upload_price) <= 0:
        warns.append("업로드가 0/미상 — 보내지 않습니다(0원 업로드 금지).")
        return Recomputed(final_purchase_price=int(final_purchase), steps=steps,
                          warnings=tuple(warns))
    if pr.guardrail_status in ("below", "above"):
        warns.append(f"가드레일 {pr.guardrail_status} — 업로드가 {upload_price:,}원.")

    return Recomputed(
        final_purchase_price=int(final_purchase),
        upload_price=int(upload_price),
        margin_amount=compute_margin_amount(pr, int(final_purchase)),
        steps=steps,
        warnings=tuple(warns),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  6) 계획 — 판정까지 끝내고 P0 부터 정렬 (전송은 아직 안 함)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlannedUpload:
    link: SourceLink
    target: MarketTarget
    recomputed: Recomputed
    decision: GateDecision
    prev_price: int | None
    prev_stock: int | None

    @property
    def sort_key(self):
        """P0 → P1 → P2. 같은 우선순위 안에서는 sku·마켓 순으로 결정적(deterministic)."""
        return (PRIORITY_RANK.get(self.decision.priority, 99),
                self.link.canonical_sku, self.target.market,
                self.target.account_key)


def plan_uploads(session, *, source_product, min_margin_amount: int) -> list[PlannedUpload]:
    """크롤된 소싱처 상품 1건 → 전송 계획(정렬 완료). 마켓 호출 없음.

    순수 조회·계산만 하므로 테스트에서 마켓 없이 그대로 검증할 수 있다.
    """
    plans: list[PlannedUpload] = []
    tpl_cache: dict[str, object] = {}

    for link in source_links_for(session, source_product):
        if link.canonical_sku not in tpl_cache:
            tpl_cache[link.canonical_sku] = _price_template_for(
                session, link.canonical_sku)
        tpl = tpl_cache[link.canonical_sku]

        for target in market_targets_for(session, link.canonical_sku):
            if target.market not in PRICED_MARKETS:
                # 가격 정책이 없는 마켓 — 스스 정책으로 조용히 계산해 올리면 금전 손실.
                plans.append(PlannedUpload(
                    link=link, target=target,
                    recomputed=Recomputed(warnings=(
                        f"'{target.market}' 는 PriceTemplate 에 가격 정책이 없습니다. "
                        f"스마트스토어 정책으로 대체 계산하지 않고 건너뜁니다.",)),
                    decision=GateDecision(
                        should_upload=False, priority="P2",
                        reason_code="market_no_policy",
                        reason=(f"'{target.market}' 가격 정책 미정의 — 다른 마켓 정책으로 "
                                f"대체 계산하지 않습니다(잘못된 값 전송 방지)."),
                        counts_as_no_change=False),
                    prev_price=None, prev_stock=None))
                continue

            rc = recompute(session, link=link, market=target.market, tpl=tpl,
                           source_product_id=source_product.id)
            prev = last_confirmed_snapshot(
                session, canonical_sku=link.canonical_sku,
                market=target.market, account_key=target.account_key)

            decision = decide_upload(
                prev_price=(prev.upload_price if prev else None),
                prev_stock=(prev.stock if prev else None),
                new_price=rc.upload_price,
                new_stock=link.stock,
                margin_amount=rc.margin_amount,
                min_margin_amount=min_margin_amount,
            )
            plans.append(PlannedUpload(
                link=link, target=target, recomputed=rc, decision=decision,
                prev_price=(prev.upload_price if prev else None),
                prev_stock=(prev.stock if prev else None)))

    plans.sort(key=lambda p: p.sort_key)
    return plans


# ─────────────────────────────────────────────────────────────────────────────
#  7) 실행 — 전송(잠금 통과 시) + 스냅샷 기록
# ─────────────────────────────────────────────────────────────────────────────

def _send_values(plan: PlannedUpload):
    """실제로 마켓에 보낼 (가격, 재고). 못 정하면 (None, None, 사유).

    ★ 게이트는 "올려라"라고 말할 수 있지만 **한쪽 축을 모를 수 있다**.
      예를 들어 첫 업로드(기준선 없음)는 재고만 읽혀도 올리라고 한다. 그때
      가격을 모른 채 어댑터에 ``new_price=None`` 을 넘기면 마켓에 빈 값·0원이
      나가거나 예외가 난다. 반대로 재고 확인불가(-1)를 그대로 보내면 마켓이
      '-1개'를 받는다.

      집 원칙은 "모르는 축은 **기존 값 유지**"다. 여기서 기존 값 = 마켓이 실제로
      들고 있는 값(직전 확정 스냅샷)이다. 그 값을 다시 보내는 건 값을 지어내는
      게 아니라 **마켓의 현재 값을 그대로 두는 것**이라 폴백 금지에 걸리지 않는다.
      기준선조차 없으면 보낼 숫자가 없다 — 추측하지 않고 보류한다.
    """
    price = plan.recomputed.upload_price
    if price is None:
        price = plan.prev_price
    stock = plan.link.stock
    if stock is None or int(stock) <= STOCK_UNKNOWN:
        stock = plan.prev_stock
    if price is None or stock is None:
        missing = "가격" if price is None else "재고"
        return None, None, (
            f"{missing}을 이번에 못 읽었고 마켓에 올라간 기준값도 없어 보낼 숫자가 "
            f"없습니다 — 추측해서 올리지 않습니다.")
    return int(price), int(stock), None


def _record(session, plan: PlannedUpload, *, source_key, action, reason_code,
            reason, extra_warnings=(), uploaded_at=None) -> PriceSnapshot:
    """스냅샷 1행. **업로드·스킵·보류를 가리지 않고 전부** 남긴다.

    아무것도 안 남기면 '조용한 실패'와 구분되지 않는다(M3-1 게이트가 스킵도
    사유와 함께 반환하는 것과 같은 이유).
    """
    warns = list(plan.decision.warnings) + list(plan.recomputed.warnings) \
        + list(extra_warnings)
    snap = PriceSnapshot(
        canonical_sku=plan.link.canonical_sku,
        market=plan.target.market,
        account_key=plan.target.account_key,
        source_key=source_key,
        surface_price=plan.link.surface_price,
        final_purchase_price=plan.recomputed.final_purchase_price,
        upload_price=plan.recomputed.upload_price,
        margin_amount=plan.recomputed.margin_amount,
        stock=plan.link.stock,
        steps_json=plan.recomputed.steps,
        action=action,
        priority=plan.decision.priority,
        reason_code=(reason_code or "")[:32],
        reason=(reason or "")[:200],
        warnings_json=warns or None,
        uploaded_at=uploaded_at,
    )
    session.add(snap)
    return snap


def reconcile_after_crawl(session, *, source_product, adapters=None, pacer=None,
                          armed: bool | None = None,
                          min_margin_amount: int | None = None,
                          cap_config=None,
                          commit: bool = True) -> dict:
    """크롤 완료 1건에 대한 전체 파이프라인. **크롤 저장 직후에 부른다.**

    Args:
        source_product: 방금 크롤 결과가 저장된 SourceProduct.
        adapters: {market: MarketAdapter}. None 이고 잠금이 풀려 있으면
            ``select_adapters(live=True)`` 로 만든다. 테스트는 여기에 목을 넣는다.
        pacer: :class:`~lemouton.uploader.throttle.IntervalPacer`. 전송 직전
            ``pacer.wait(market)`` 로 마켓 rate limit(계정 정본 파생 초 간격)을 지킨다.
            None 이고 잠금이 풀려 있으면 ``build_market_pacer`` 로 만든다.
        armed: 실전송 잠금 상태를 강제(테스트용). None = 실제 잠금을 조회.
        min_margin_amount: 역마진 기준(원). None = 설정에서 조회.
        cap_config: :class:`~lemouton.uploader.daily_cap.CapConfig`.
            상품당 하루 몇 번까지 마켓을 건드릴지. None = 기본(하루 2회).
            ``max_per_day=0`` 으로 주면 **상한 검사를 건너뛴다**(무제한).
        commit: 끝에 commit. False 면 호출자가 트랜잭션을 관리.

    Returns:
        {'armed', 'planned', 'uploaded', 'skipped', 'held', 'failed',
         'capped', 'sold_out_exempt', 'unlinked_skus', 'errors', 'by_priority'}
        · capped — 하루 상한에 걸려 대기시킨 건수(버린 게 아니다)
        · sold_out_exempt — 품절이라 상한을 넘겨 내보낸 건수

    ★ 잠금이 꺼져 있으면 어댑터를 **조회조차 하지 않는다** — 실제 마켓 호출 0.
    """
    from .runtime import real_upload_armed

    if armed is None:
        armed = real_upload_armed(session)
    if min_margin_amount is None:
        from lemouton.pricing.settings import get_min_margin_amount
        min_margin_amount = get_min_margin_amount(session)

    plans = plan_uploads(session, source_product=source_product,
                         min_margin_amount=min_margin_amount)
    source_key = source_product.site

    # ── [M5] P2 스킵 집계 — **업로드 판정** 쪽 숫자만 ───────────────────────
    #   판정을 다시 하지 않는다. 위에서 이미 나온 GateDecision 을 세기만 한다.
    #   ★변동성 통계(관측·변동률)는 여기서 세지 않는다 — 그건 기준선이 소싱처라
    #     CrawlDelta 를 만드는 자리(sources.service._record_crawl_delta)에서 센다.
    #   통계 실패가 업로드를 막을 이유는 없으므로 삼키되, 조용히 넘기지 않고 로그를 남긴다.
    try:
        from lemouton.sources.crawl_change_stats import record_gate_skips
        record_gate_skips(session, source_product=source_product, plans=plans)
    except Exception as e:   # noqa: BLE001
        logger.warning("[reconcile] P2 스킵 집계 실패 sp=%s: %s",
                       getattr(source_product, "id", None), e)

    # 어댑터·페이서는 **잠금이 풀렸을 때만** 준비한다. 꺼져 있을 때 드라이런
    # 어댑터라도 태우면 success=True 가 돌아와 '올렸다'로 기록될 위험이 생긴다.
    if armed and adapters is None:
        from .runtime import select_adapters
        adapters = select_adapters(live=True)
    if armed and pacer is None:
        try:
            from .throttle import build_market_pacer
            pacer = build_market_pacer(session)
        except Exception:   # noqa: BLE001 — 페이싱 준비 실패가 전송을 막을 이유는 없다
            pacer = None

    out = {"armed": bool(armed), "planned": len(plans), "uploaded": 0,
           "skipped": 0, "held": 0, "failed": 0,
           "capped": 0, "sold_out_exempt": 0, "errors": [],
           "by_priority": {"P0": 0, "P1": 0, "P2": 0}}

    for plan in plans:   # 이미 P0 → P1 → P2 로 정렬돼 있다
        d = plan.decision
        out["by_priority"][d.priority] = out["by_priority"].get(d.priority, 0) + 1

        # ── 게이트가 안 보낸다고 했다 → 사유와 함께 기록만 ──────────────────
        if not d.should_upload:
            action = "hold" if d.held_for_margin else "skip"
            _record(session, plan, source_key=source_key, action=action,
                    reason_code=d.reason_code, reason=d.reason)
            out["held" if action == "hold" else "skipped"] += 1
            continue

        # ── 보낼 숫자가 실제로 정해지는가 ──────────────────────────────────
        #   게이트가 "올려라"라고 해도 한쪽 축을 모르면 그 축은 마켓 현재값으로
        #   채운다. 그것도 없으면 보류 — None·-1 을 마켓에 넘기지 않는다.
        send_price, send_stock, missing = _send_values(plan)
        if missing:
            _record(session, plan, source_key=source_key, action="hold",
                    reason_code="send_value_unknown", reason=missing,
                    extra_warnings=(f"게이트 사유: {d.reason}",))
            out["held"] += 1
            continue

        # ── 하루 상한 (2026-07-20 배선) ────────────────────────────────────
        #   사장님 확정: "여유가 되면 바로바로. 다만 너무 많으면 상품별 하루 2회까지."
        #                "품절은 빠르게 무조건 빼야 함."
        #   ★ 막혀도 **버리지 않는다**(hold) — 다음 슬롯에 최신 값으로 나간다.
        #   ★ 잠금 검사보다 **앞**이다: 잠금이 걸린 건 애초에 안 나갔으니
        #     상한을 쓴 적이 없다. 순서를 바꾸면 잠금 해제 직후 상한이
        #     이미 찬 것처럼 보인다.
        if cap_config is None or cap_config.max_per_day > 0:
            try:
                from .daily_cap_service import decide_for_plan
                cap = decide_for_plan(
                    session,
                    canonical_sku=plan.link.canonical_sku,
                    market=plan.target.market,
                    account_key=getattr(plan.target, "account_key", None) or "default",
                    stock=send_stock,
                    config=cap_config,
                )
            except Exception as e:      # noqa: BLE001
                # 상한을 못 세는 것이 전송을 막을 이유는 없다 — 다만 조용히 넘기지 않는다.
                logger.warning("[reconcile] 하루 상한 집계 실패 sku=%s: %s",
                               plan.link.canonical_sku, e)
                cap = None
            if cap is not None and not cap.allowed:
                _record(session, plan, source_key=source_key, action="hold",
                        reason_code=cap.reason_code, reason=cap.reason[:200],
                        extra_warnings=(f"게이트 사유: {d.reason}",))
                out["held"] += 1
                out["capped"] = out.get("capped", 0) + 1
                continue
            if cap is not None and cap.exempt:
                out["sold_out_exempt"] = out.get("sold_out_exempt", 0) + 1

        # ── 실전송 잠금 ────────────────────────────────────────────────────
        #   보낼 값은 정해졌지만 잠금이 걸려 있다. "보낼 뻔했다"를 남기고 끝.
        #   uploaded_at 은 비운다 = 아직 안 올라갔다 → 잠금을 풀면 다음 사이클에 나간다.
        if not armed:
            _record(session, plan, source_key=source_key, action="hold",
                    reason_code="live_send_disarmed",
                    reason=(f"실전송 잠금(MOUM_LIVE_UPLOAD·autosend_mode) — 보내지 "
                            f"않았습니다. 게이트 사유: {d.reason}"),
                    extra_warnings=("실전송 잠금 상태라 마켓을 호출하지 않았습니다.",))
            out["held"] += 1
            continue

        adapter = (adapters or {}).get(plan.target.market)
        if adapter is None:
            # 이진 else 금지 — 다른 마켓 어댑터로 보내면 그 마켓에 값이 나간다.
            _record(session, plan, source_key=source_key, action="hold",
                    reason_code="no_adapter",
                    reason=f"'{plan.target.market}' 어댑터 미등록 — 보내지 않았습니다.")
            out["held"] += 1
            out["errors"].append({"market": plan.target.market,
                                  "canonical_sku": plan.link.canonical_sku,
                                  "error": "어댑터 미등록"})
            continue

        if pacer is not None:
            pacer.wait(plan.target.market)   # 마켓 rate limit (계정 정본 파생)

        # ── 실제 전송. 예외를 삼켜 성공으로 만들지 않는다(거짓 성공 금지). ──
        try:
            result = adapter.update_price_and_stock(
                canonical_sku=plan.link.canonical_sku,
                market_product_id=plan.target.market_product_id,
                market_option_id=plan.target.market_option_id,
                new_price=send_price,
                new_stock=send_stock,
            )
            success = bool(getattr(result, "success", False))
            err = getattr(result, "error", None)
            http = getattr(result, "http_status", None)
        except Exception as e:   # noqa: BLE001
            success, err, http = False, f"{type(e).__name__}: {e}", None
            logger.warning("[reconcile] 전송 예외 sku=%s market=%s: %s",
                           plan.link.canonical_sku, plan.target.market, e)

        if success:
            # 마켓이 성공을 응답했을 때만 uploaded_at 을 채운다.
            # 이 행이 다음 사이클의 "마켓에 올라가 있는 값" 기준선이 된다.
            _record(session, plan, source_key=source_key, action="upload",
                    reason_code=d.reason_code, reason=d.reason,
                    uploaded_at=_utcnow())
            out["uploaded"] += 1
        else:
            # uploaded_at 을 비워 둔다 = 기준선이 되지 않는다 → 다음 사이클 자동 재시도.
            _record(session, plan, source_key=source_key, action="upload",
                    reason_code=d.reason_code, reason=d.reason,
                    extra_warnings=(f"전송 실패 — 아직 마켓에 반영되지 않았습니다: "
                                    f"{str(err)[:100]}",),
                    uploaded_at=None)
            out["failed"] += 1
            out["errors"].append({"market": plan.target.market,
                                  "canonical_sku": plan.link.canonical_sku,
                                  "error": err, "http_status": http})

    try:
        out["unlinked_skus"] = unlinked_sku_count(session, source_product)
    except Exception:   # noqa: BLE001 — 진단 수치라 실패해도 파이프라인은 진행
        out["unlinked_skus"] = None

    if commit:
        session.commit()
    return out

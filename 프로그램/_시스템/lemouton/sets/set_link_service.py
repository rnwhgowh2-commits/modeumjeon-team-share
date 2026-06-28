"""[구성 레이어] 구성별 판매처 연동 실행 — P0 매칭·조회 코어 재사용.

채널(SetChannel)의 마켓 상품번호로 마켓 옵션을 가져와, 구성의 선택 옵션(SetOption→Option
색/사이즈)과 매칭하여 SetChannelOption 에 결과 저장. 마켓에 쓰지 않음(읽기+로컬 저장).
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from lemouton.sourcing.models import Option
from lemouton.sets.models import (
    SetChannel, SetProduct, SetOption, SetChannelOption,
)
from lemouton.uploader.linker import match_market_options_to_skus
from lemouton.uploader.market_fetch import fetch_market_options


def _gather_set_options(session: Session, set_id: int) -> list[dict]:
    """구성의 선택 옵션을 V1 Option 색/사이즈로 풀어 매칭 입력 형태로."""
    skus = [
        row[0] for row in (
            session.query(SetOption.canonical_sku)
            .join(SetProduct, SetOption.set_product_id == SetProduct.id)
            .filter(SetProduct.set_id == set_id)
            .all()
        )
    ]
    if not skus:
        return []
    opts = session.query(Option).filter(Option.canonical_sku.in_(skus)).all()
    return [
        {"canonical_sku": o.canonical_sku, "color_code": o.color_code,
         "color_display": o.color_display, "size_code": o.size_code,
         "size_display": o.size_display}
        for o in opts
    ]


def _resolve_env_prefix(session: Session, market: str, account_key: str):
    """채널의 (market, account_key) → UploadAccount.env_prefix. 없으면 None(전역 기본)."""
    try:
        from lemouton.sourcing.models_v2 import UploadAccount
        a = (session.query(UploadAccount)
             .filter_by(market=market, account_key=account_key).first())
        return a.env_prefix if a else None
    except Exception:  # noqa: BLE001 — 계정 미존재/모델 미로드 시 전역 폴백
        return None


def link_set_channel(session: Session, channel_id: int, *,
                     fetcher=fetch_market_options) -> dict:
    """채널의 마켓 상품과 구성 옵션을 매칭해 SetChannelOption 저장.

    matched(고유)만 market_option_id 채움. 같은 SKU 로 정규화되는 마켓옵션 2+개는
    duplicate 로 1행만 기록(오바인딩 방지, P0 머니세이프티 동일). 마켓에 쓰지 않음.
    """
    empty = {"ok": False, "error": "", "linked": 0, "unmatched": 0,
             "ambiguous": 0, "duplicate": 0}
    ch = session.get(SetChannel, channel_id)
    if ch is None:
        return {**empty, "error": "채널 없음"}
    if not ch.market_product_id:
        return {**empty, "error": "상품번호 미입력"}

    bundle_options = _gather_set_options(session, ch.set_id)
    env_prefix = _resolve_env_prefix(session, ch.market, ch.account_key)
    fr = fetcher(ch.market, ch.market_product_id, env_prefix=env_prefix)
    if not fr.success:
        return {**empty, "error": fr.error or "옵션 조회 실패"}

    rows = match_market_options_to_skus(bundle_options, fr.options)
    dup_skus = {
        sku for sku, n in
        Counter(r.canonical_sku for r in rows if r.status == "matched").items()
        if n > 1
    }

    # 이전 결과 교체(재실행 멱등)
    session.query(SetChannelOption).filter_by(channel_id=channel_id).delete()

    linked = unmatched = ambiguous = duplicate = 0
    seen: set[str] = set()
    for r in rows:
        if r.canonical_sku is None:
            if r.status == "ambiguous":
                ambiguous += 1
            else:
                unmatched += 1
            continue
        if r.canonical_sku in dup_skus:
            if r.canonical_sku not in seen:
                session.add(SetChannelOption(
                    channel_id=channel_id, canonical_sku=r.canonical_sku,
                    market_option_id=None, status="duplicate"))
                seen.add(r.canonical_sku)
                duplicate += 1
            continue
        session.add(SetChannelOption(
            channel_id=channel_id, canonical_sku=r.canonical_sku,
            market_option_id=r.market_option_id, status="matched"))
        linked += 1

    if linked:
        ch.status = "linked"
    session.flush()
    return {"ok": True, "error": None, "product_name": fr.product_name,
            "linked": linked, "unmatched": unmatched,
            "ambiguous": ambiguous, "duplicate": duplicate}

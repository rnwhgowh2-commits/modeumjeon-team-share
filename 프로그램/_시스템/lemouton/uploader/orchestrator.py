"""[D] 메인 오케스트레이터.

흐름:
  1. C 페이로드 → 옵션별 가격·재고 추출
  2. 변동 감지 (skip 최적화)
  3. 드라이런 요약 → 자동 보류 검사
  4. 보류 아니면: 마켓별 어댑터 호출
  5. 결과 → DB market_registrations 업데이트
  6. 실패 → DLQ
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from .changes import detect_change
from .repository import upsert_registration
from .dryrun import compute_dryrun_summary
from .dlq import enqueue_dlq
from .adapters.base import MarketAdapter


def _extract_uploads(c_output: dict, sku_by_option: dict) -> list[dict]:
    """C 페이로드에서 (market, sku, product_id, option_id, price, stock) 리스트 추출."""
    uploads = []
    for model_code, payload in c_output.get("smartstore", {}).items():
        product_id = payload["product_id"]
        base = payload.get("base_price", 0)
        for opt in payload.get("options", []):
            option_id = opt["option_id"]
            sku = sku_by_option.get(("smartstore", option_id))
            if not sku:
                continue
            uploads.append({
                "market": "smartstore",
                "canonical_sku": sku,
                "market_product_id": product_id,
                "market_option_id": option_id,
                "new_price": base + opt.get("add_price", 0),
                "new_stock": opt.get("stock", 0),
            })

    for model_code, payload in c_output.get("coupang", {}).items():
        product_id = payload["product_id"]
        for opt in payload.get("options", []):
            option_id = opt["option_id"]
            sku = sku_by_option.get(("coupang", option_id))
            if not sku:
                continue
            uploads.append({
                "market": "coupang",
                "canonical_sku": sku,
                "market_product_id": product_id,
                "market_option_id": option_id,
                "new_price": opt.get("price", 0),
                "new_stock": opt.get("stock", 0),
            })
    return uploads


def run_uploader(
    session: Session,
    c_output: dict,
    *,
    sku_by_option: dict,
    ss_adapter: MarketAdapter,
    cp_adapter: MarketAdapter,
    dlq_path: str,
    warnings_threshold: int = 5,
    avg_price_change_pct: float = 30.0,
    force: bool = False,
    persist: bool = False,
) -> dict:
    """메인 진입점. force=True면 보류 무시하고 진행.

    persist=True 면 종료 시 session.commit() 으로 MarketRegistration(변동감지 기준선)을
    영속한다. 이게 없으면 SessionLocal(autocommit=False)에서 등록이 롤백돼 detect_change 가
    매번 '이전 없음'=변동으로 판정 → 라이브에서 안 바뀐 옵션도 매 사이클 재전송(#12).
    dry-run(persist=False)은 커밋하지 않아 '미전송분'이 '전송됨' 기준선으로 오염되지 않는다.
    """
    uploads = _extract_uploads(c_output, sku_by_option)

    # 변동 감지
    actionable = []
    skipped = 0
    diff_for_dryrun = []
    for u in uploads:
        change = detect_change(
            session,
            canonical_sku=u["canonical_sku"], market=u["market"],
            new_price=u["new_price"], new_stock=u["new_stock"],
        )
        if not change.has_change:
            skipped += 1
            continue
        actionable.append(u)
        diff_for_dryrun.append({
            "market": u["market"],
            "old_price": change.old_price, "new_price": change.new_price,
            "old_stock": change.old_stock, "new_stock": change.new_stock,
        })

    # 드라이런
    summary = compute_dryrun_summary(
        diff_for_dryrun, c_output.get("alerts", []),
        warnings_threshold, avg_price_change_pct,
    )
    if summary.should_hold and not force:
        return {
            "uploaded": 0, "skipped": skipped, "failed": 0,
            "held": True, "hold_reason": summary.hold_reason,
            "summary": summary,
        }

    # 호출
    uploaded = 0
    failed = 0
    now = datetime.now(timezone.utc)
    for u in actionable:
        adapter = ss_adapter if u["market"] == "smartstore" else cp_adapter
        result = adapter.update_price_and_stock(
            canonical_sku=u["canonical_sku"],
            market_product_id=u["market_product_id"],
            market_option_id=u["market_option_id"],
            new_price=u["new_price"], new_stock=u["new_stock"],
        )
        if result.success:
            upsert_registration(
                session,
                canonical_sku=u["canonical_sku"], market=u["market"],
                market_product_id=u["market_product_id"],
                market_option_id=u["market_option_id"],
                last_synced_price=u["new_price"],
                last_synced_stock=u["new_stock"],
                status="ok",
                last_attempt_at=now,
                last_success_at=now,
                sync_error=None,
            )
            uploaded += 1
        else:
            upsert_registration(
                session,
                canonical_sku=u["canonical_sku"], market=u["market"],
                market_product_id=u["market_product_id"],
                market_option_id=u["market_option_id"],
                status="failed",
                last_attempt_at=now,
                sync_error=result.error,
                sync_attempts=1,  # 실제 재시도 로직은 어댑터에서 처리
            )
            enqueue_dlq(dlq_path, {
                "market": u["market"],
                "canonical_sku": u["canonical_sku"],
                "request_payload": {
                    "market_product_id": u["market_product_id"],
                    "market_option_id": u["market_option_id"],
                    "new_price": u["new_price"],
                    "new_stock": u["new_stock"],
                },
                "error": result.error,
                "http_status": result.http_status,
                "attempts": 1,
            })
            failed += 1

    if persist:
        session.commit()   # #12 — 변동감지 기준선(MarketRegistration) 영속
    return {
        "uploaded": uploaded, "skipped": skipped, "failed": failed,
        "held": False, "hold_reason": "",
        "summary": summary,
    }

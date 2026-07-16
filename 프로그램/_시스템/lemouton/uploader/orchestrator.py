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


def autosend_keep(old_price, new_price, old_stock, new_stock, automation: dict) -> bool:
    """자동화 설정 토글에 따라 이 변동을 실제로 보낼지 판정.

    · 가격이 바뀌었고 autosend_on_price → 보냄
    · 재고가 바뀌었고 autosend_on_stock 이며 새 재고가 임계(autosend_stock_threshold) 이하 → 보냄
    한 항목이 가격·재고 둘 다 바뀌면 어느 한쪽만 조건 맞아도 보낸다(API가 둘 다 실어 감).
    사입 토글은 소스 구분이 페이로드에 없어 여기서 다루지 않는다(별도 작업).
    """
    price_changed = old_price != new_price
    stock_changed = old_stock != new_stock
    if price_changed and automation.get("autosend_on_price"):
        return True
    if stock_changed and automation.get("autosend_on_stock"):
        try:
            thr = int(automation.get("autosend_stock_threshold") or 0)
        except (TypeError, ValueError):
            thr = 0
        if int(new_stock) <= thr:
            return True
    return False


# 전송 대상 마켓 정본 — _extract_uploads 가 라우팅하는 6마켓과 동일 순서.
UPLOAD_MARKETS = ("smartstore", "coupang", "lotteon", "eleven11", "auction", "gmarket")


def has_uploadable_payload(c_output: dict | None) -> bool:
    """C 페이로드에 전송 대상 마켓이 하나라도 비어있지 않게 있으면 True.

    옛 게이트(스마트스토어·쿠팡만 검사)가 롯데온/ESM 단독 변동을 드롭하던 결함 수정.
    alerts 만 있는 dict 는 전송 대상이 아니므로 False.
    """
    if not c_output:
        return False
    return any(c_output.get(m) for m in UPLOAD_MARKETS)


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

    # 롯데온 — formatter 가 "lotteon" 페이로드를 방출하면 자동으로 포함된다.
    #   (현재 formatter 는 미방출 — 신규등록/모델매핑 배선 시 활성. 배선 순서 무관하게
    #    여기서 먼저 읽도록 두어, 페이로드가 생기는 순간 라우팅 누락이 없게 한다.)
    for model_code, payload in c_output.get("lotteon", {}).items():
        product_id = payload["product_id"]
        for opt in payload.get("options", []):
            option_id = opt["option_id"]
            sku = sku_by_option.get(("lotteon", option_id))
            if not sku:
                continue
            uploads.append({
                "market": "lotteon",
                "canonical_sku": sku,
                "market_product_id": product_id,
                "market_option_id": option_id,
                "new_price": opt.get("price", 0),
                "new_stock": opt.get("stock", 0),
            })

    # 11번가 — 롯데온과 동일. formatter 가 "eleven11" 페이로드를 방출하면 자동 포함.
    #   (현재 formatter 는 미방출 — DB 매핑컬럼 eleven11_product_id/option_id 신설 = 나중.
    #    여기서 먼저 읽도록 두어 라우팅 누락 방지. 없으면 .get() 이 {} 라 무해.)
    for model_code, payload in c_output.get("eleven11", {}).items():
        product_id = payload["product_id"]
        for opt in payload.get("options", []):
            option_id = opt["option_id"]
            sku = sku_by_option.get(("eleven11", option_id))
            if not sku:
                continue
            uploads.append({
                "market": "eleven11",
                "canonical_sku": sku,
                "market_product_id": product_id,
                "market_option_id": option_id,
                "new_price": opt.get("price", 0),
                "new_stock": opt.get("stock", 0),
            })

    # 옥션·G마켓(ESM 2.0) — 롯데온과 동일. formatter 가 방출하면 자동 포함.
    #   market_product_id=goodsNo, market_option_id=옵션 manageCode.
    #   미매핑(auction_product_id NULL) 모델은 build 가 None → 방출 0(안전).
    for _mkt in ("auction", "gmarket"):
        for model_code, payload in c_output.get(_mkt, {}).items():
            product_id = payload["product_id"]
            for opt in payload.get("options", []):
                option_id = opt["option_id"]
                sku = sku_by_option.get((_mkt, option_id))
                if not sku:
                    continue
                uploads.append({
                    "market": _mkt,
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
    adapters: dict[str, MarketAdapter],
    dlq_path: str,
    warnings_threshold: int = 5,
    avg_price_change_pct: float = 30.0,
    force: bool = False,
    persist: bool = False,
    pacer=None,
    automation: dict | None = None,
) -> dict:
    """메인 진입점. force=True면 드라이런 보류(자동 hold)와 변동감지 스킵을 둘 다 우회한다.

    force 는 '변동감지 보류'만 우회할 뿐 어댑터 게이트(서버키·price_guard)는 못 우회한다.
    직접 값 지정 전송(scoped_send.run_explicit)에서 '현재값과 같아도 반드시 전송'을 위해 쓴다.

    persist=True 면 종료 시 session.commit() 으로 MarketRegistration(변동감지 기준선)을
    영속한다. 이게 없으면 SessionLocal(autocommit=False)에서 등록이 롤백돼 detect_change 가
    매번 '이전 없음'=변동으로 판정 → 라이브에서 안 바뀐 옵션도 매 사이클 재전송(#12).
    dry-run(persist=False)은 커밋하지 않아 '미전송분'이 '전송됨' 기준선으로 오염되지 않는다.

    pacer 를 주면(:class:`lemouton.uploader.throttle.IntervalPacer`) 전송 직전마다
    ``pacer.wait(market)`` 로 계정 정본에서 파생한 '1개당 최소 초 간격'을 강제한다 —
    업로드 속도 정본은 계정(API) 단위 하나다. None 이면 페이싱 없이 현행대로 동작.
    """
    uploads = _extract_uploads(c_output, sku_by_option)

    # 변동 감지 + (설정 있으면) 변동 종류 토글 필터 + 미리보기 집계
    actionable = []
    skipped = 0
    filtered_out = 0
    diff_for_dryrun = []
    preview: dict[str, dict] = {}   # market → {건수, 가격, 재고}
    for u in uploads:
        change = detect_change(
            session,
            canonical_sku=u["canonical_sku"], market=u["market"],
            new_price=u["new_price"], new_stock=u["new_stock"],
        )
        # force=True 는 변동감지 보류만 우회한다 — 명시값 전송(직접 값 지정 테스트)에서
        #   '현재값과 같아도 반드시 전송'을 보장하기 위해 has_change 스킵도 건너뛴다.
        #   (스케줄러·기본 경로는 force=False 라 현행 동작 완전 보존.)
        if not change.has_change and not force:
            skipped += 1
            continue
        # 변동 종류 토글(소싱처 가격/재고) — automation 주면 필터. 없으면 현행대로 전량.
        if automation is not None and not autosend_keep(
                change.old_price, change.new_price,
                change.old_stock, change.new_stock, automation):
            filtered_out += 1
            continue
        actionable.append(u)
        diff_for_dryrun.append({
            "market": u["market"],
            "old_price": change.old_price, "new_price": change.new_price,
            "old_stock": change.old_stock, "new_stock": change.new_stock,
        })
        pv = preview.setdefault(u["market"], {"count": 0, "price": 0, "stock": 0})
        pv["count"] += 1
        if change.old_price != change.new_price:
            pv["price"] += 1
        if change.old_stock != change.new_stock:
            pv["stock"] += 1

    # 드라이런
    summary = compute_dryrun_summary(
        diff_for_dryrun, c_output.get("alerts", []),
        warnings_threshold, avg_price_change_pct,
    )
    if summary.should_hold and not force:
        return {
            "uploaded": 0, "skipped": skipped, "failed": 0,
            "filtered_out": filtered_out, "preview": preview,
            "held": True, "hold_reason": summary.hold_reason,
            "summary": summary,
        }

    # 호출
    uploaded = 0
    failed = 0
    errors: list[dict] = []   # 실패 상세(마켓·sku·이유) — 반환에 담아 UI/진단에 표면화
    now = datetime.now(timezone.utc)
    for u in actionable:
        if pacer is not None:
            pacer.wait(u["market"])   # 계정 정본 파생 '1개당 최소 초 간격'
        # 마켓별 어댑터 dict 조회. 이진 else 금지 —
        #   등록 안 된 마켓 행을 임의의 어댑터로 보내면 그 마켓 API 로 가격·재고가 나가
        #   금전 손실이 된다(예: lotteon 행이 쿠팡 API 로). 없으면 실패로 표면화.
        adapter = adapters.get(u["market"])
        if adapter is None:
            failed += 1
            upsert_registration(
                session,
                canonical_sku=u["canonical_sku"], market=u["market"],
                market_product_id=u["market_product_id"],
                market_option_id=u["market_option_id"],
                status="failed",
                last_attempt_at=now,
                sync_error=f"어댑터 미등록 마켓: {u['market']} (select_adapters 확인)",
                sync_attempts=1,
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
                "error": f"no adapter for market {u['market']}",
                "http_status": None,
                "attempts": 1,
            })
            errors.append({"market": u["market"], "canonical_sku": u["canonical_sku"],
                           "error": f"어댑터 미등록 마켓: {u['market']}", "http_status": None})
            continue
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
            errors.append({"market": u["market"], "canonical_sku": u["canonical_sku"],
                           "error": result.error, "http_status": result.http_status})
            failed += 1

    if persist:
        session.commit()   # #12 — 변동감지 기준선(MarketRegistration) 영속
    return {
        "uploaded": uploaded, "skipped": skipped, "failed": failed,
        "filtered_out": filtered_out, "preview": preview,
        "held": False, "hold_reason": "",
        "summary": summary,
        "errors": errors[:20],
    }

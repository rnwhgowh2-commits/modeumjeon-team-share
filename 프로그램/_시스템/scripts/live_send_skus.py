# -*- coding: utf-8 -*-
"""스코프 원샷 실전송 도구 — 지정 SKU만 1회 전송(연속 스케줄러와 분리).

실전송 조건(3중): --live + --i-understand-live-send + 서버키 MOUM_LIVE_UPLOAD ON.
기본 드라이런. price_guard·DLQ·정직한 성공판정은 run_uploader 재사용으로 보존.
"""
from __future__ import annotations


def resolve_send_mode(*, want_live: bool, confirmed: bool, server_key_on: bool):
    """(use_real: bool, refusal_reason: str|None). real 은 3조건 모두 참일 때만."""
    if not want_live:
        return False, None
    if not confirmed:
        return False, "실전송하려면 --i-understand-live-send 확인 플래그가 필요합니다(드라이런으로 실행)."
    if not server_key_on:
        return False, "서버키 MOUM_LIVE_UPLOAD 가 꺼져 있습니다. 배포 env 설정·재배포(사용자) 후 재시도(드라이런으로 실행)."
    return True, None


import argparse
import os


def _server_key_on() -> bool:
    from lemouton.uploader.runtime import live_upload_enabled
    return live_upload_enabled()


def run(skus, *, want_live: bool, confirmed: bool, force: bool = False) -> dict:
    """스코프 원샷 전송. use_real 이면 실어댑터, 아니면 드라이런. 결과 dict 반환."""
    from shared.db import SessionLocal
    from lemouton.uploader.runtime import select_adapters, build_sku_by_option
    from lemouton.uploader.orchestrator import run_uploader
    from scripts.verify_pipeline_dryrun import build_c_output

    use_real, refusal = resolve_send_mode(
        want_live=want_live, confirmed=confirmed, server_key_on=_server_key_on())
    session = SessionLocal()
    try:
        c_output = build_c_output(session, only_skus=list(skus))
        sku_by_option = build_sku_by_option(session)
        adapters = select_adapters(live=use_real)
        dlq_path = os.path.join(os.path.dirname(__file__), "..", "data", "uploader_dlq.jsonl")
        result = run_uploader(
            session, c_output,
            sku_by_option=sku_by_option, adapters=adapters, dlq_path=dlq_path,
            force=force, persist=use_real, automation=None,
        )
    finally:
        session.close()
    return {"use_real": use_real, "refusal": refusal, "skus": list(skus), "result": result}


def main() -> None:
    ap = argparse.ArgumentParser(description="스코프 원샷 실전송(지정 SKU만).")
    ap.add_argument("--skus", required=True, help="쉼표구분 canonical_sku 목록")
    ap.add_argument("--live", action="store_true", help="실제 전송 시도(기본 드라이런)")
    ap.add_argument("--i-understand-live-send", dest="confirmed", action="store_true",
                    help="실전송 명시 확인(--live 와 함께여야 real)")
    ap.add_argument("--force", action="store_true", help="드라이런 보류(hold) 무시")
    args = ap.parse_args()
    skus = [s.strip() for s in args.skus.split(",") if s.strip()]

    out = run(skus, want_live=args.live, confirmed=args.confirmed, force=args.force)
    mode = "★실전송(LIVE)" if out["use_real"] else "드라이런(preview)"
    print(f"모드: {mode} · 대상 SKU {len(out['skus'])}개: {', '.join(out['skus'])}")
    if out["refusal"]:
        print(f"⚠️ 실전송 거부 → 드라이런으로 실행: {out['refusal']}")
    r = out["result"]
    if r.get("held"):
        print(f"⏸ 보류(hold): {r.get('hold_reason')} — 확인 후 --force 로 재시도")
    print(f"결과: 전송 {r.get('uploaded', 0)} · 스킵 {r.get('skipped', 0)} · 실패 {r.get('failed', 0)} · 토글제외 {r.get('filtered_out', 0)}")
    for mkt, pv in (r.get("preview") or {}).items():
        print(f"  · {mkt}: 건수 {pv['count']} (가격변동 {pv['price']}, 재고변동 {pv['stock']})")
    if r.get("failed", 0):
        print(f"⚠️ 실패 {r['failed']}건 — DLQ(data/uploader_dlq.jsonl) 확인. 거짓성공 아님(응답코드 판정).")


if __name__ == "__main__":
    main()

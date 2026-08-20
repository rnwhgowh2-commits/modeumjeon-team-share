# -*- coding: utf-8 -*-
"""스코프 원샷 실전송 도구 — 지정 SKU만 1회 전송(연속 스케줄러와 분리).

실전송 조건(3중): --live + --i-understand-live-send + 서버키 MOUM_LIVE_UPLOAD ON.
기본 드라이런. price_guard·DLQ·정직한 성공판정은 run_uploader 재사용으로 보존.
"""
from __future__ import annotations

import argparse

# [2026-07-16] 코어 이관 — resolve_send_mode/run 은 lemouton.uploader.scoped_send 로
#   단일화(라우트·CLI 공용). 여기서는 재노출(re-export)만 유지해 기존 CLI·테스트 보존.
from lemouton.uploader.scoped_send import run, resolve_send_mode  # noqa: F401


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

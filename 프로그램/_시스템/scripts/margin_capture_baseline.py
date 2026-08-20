# -*- coding: utf-8 -*-
r"""골든테스트 1단계 — 옛 마진계산기(READ-ONLY)의 회귀 기준선(baseline) 캡처.

사용법:
    export PYTHONIOENCODING=utf-8
    python scripts/margin_capture_baseline.py 260704
    python scripts/margin_capture_baseline.py 260706

무엇을 하나:
    옛 프로그램 C:\dev\대량등록 마진계산기\app.py 를 in-process 로 import 하고
    test_client() 로 /api/upload(더망고·샵마인 xls) → /api/analyze({}) 를 호출해
    옛 프로그램의 "cycle ① 매칭·집계 결과"를 그대로 뽑아 JSON 으로 저장한다.

왜 라우트 JSON 을 그대로 저장하지 않고 store + _aggregate 를 다시 읽나 (중요):
    /api/analyze 응답(jsonify(agg))은 cycle ②(블랙스팟 분류기, classifier.py)의
    산출물로 오염돼 있다 — 이는 이 포트의 범위가 아니며(과제 명시), 신코드
    (pipeline.run + aggregator.aggregate)가 재현하지 않는 것들이다:
      · summary.card_*  → 라우트가 _compute_card_counts(분류기)로 덮어씀
      · summary.mango_total/mango_with_order_no/mango_with_trace → 라우트 주입
      · agg['unmatched_buy'] → 라우트가 raw 더망고 '매입흔적' 행으로 augment
      · top-level classified / blackspot_summary / missing_order_no → cycle ②
    순수 cycle ① 산출물은 store['matched'] / store['unmatched_buy'] /
    store['unmatched_sell'] 와, 그 matched 를 그대로 넣은 _aggregate(...) 반환값이다.
    이것이 신코드가 1:1 로 재현해야 하는 대상이므로, baseline 은 여기서 뽑는다.
    (라우트를 실제로 호출해 store 를 옛 파이프라인으로 채운 뒤 읽는다 — 경로 충실.)

개인정보 마스킹:
    응답에 고객명이 실린다. {"수령인","수령인명","수취고객명"} 키의 값을 재귀적으로
    "***" 로 치환한 뒤 저장한다. 신코드 출력에도 동일 마스크를 적용해 비교하므로
    마스킹이 차이를 가리지 못한다(테스트에서 대칭 적용).
"""
import gzip
import json
import math
import os
import sys

# ~5MB 초과 baseline 은 gzip 으로 저장(테스트가 .json.gz 를 자동 인식).
GZIP_THRESHOLD = 5 * 1024 * 1024

OLD = r"C:\dev\대량등록 마진계산기"
HERE = os.path.dirname(os.path.abspath(__file__))
SYS = os.path.dirname(HERE)  # 프로그램/_시스템
FIXTURES = os.path.join(SYS, "tests", "margin", "fixtures")

MASK_KEYS = {"수령인", "수령인명", "수취고객명"}


def mask_pii(obj):
    """{수령인,수령인명,수취고객명} 값을 재귀적으로 '***' 로 치환."""
    if isinstance(obj, dict):
        return {
            k: ("***" if k in MASK_KEYS else mask_pii(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask_pii(v) for v in obj]
    return obj


def _jsonable(obj):
    """pandas/numpy 스칼라·NaN 을 JSON 직렬화 가능한 파이썬 기본형으로.

    NaN/NaT/pd.NA → None(=JSON null). 옛 matched 에 숫자칸 NaN 이 있으면
    baseline 에 null 로 남고, 신코드는 NaN→0 로 강제하므로 테스트에서
    null(옛) vs 0(신) 불일치로 표면화된다(과제 5순위 신호).
    """
    import numpy as np
    import pandas as pd

    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return None if math.isnan(f) else f
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    try:
        if obj is pd.NaT or (obj is not None and pd.isna(obj)):
            return None
    except (ValueError, TypeError):
        pass
    return obj


def capture(date: str) -> dict:
    folder = os.path.join(OLD, "데이터", date)
    if not os.path.isdir(folder):
        raise SystemExit(f"데이터 폴더 없음: {folder}")

    mango = shopmine = None
    for fn in os.listdir(folder):
        low = fn.lower()
        if not (low.endswith(".xls") or low.endswith(".xlsx")):
            continue
        if "더망고" in fn:
            mango = os.path.join(folder, fn)
        elif "샵마인" in fn:
            shopmine = os.path.join(folder, fn)
    if not mango or not shopmine:
        raise SystemExit(f"더망고/샵마인 쌍을 찾지 못함: {folder}")

    # ── 옛 앱 in-process import (migrator·app.run 은 __main__ 아래라 미실행) ──
    os.environ["DEPLOY_MODE"] = "server"  # Playwright/Chrome 경로 비활성
    prev_cwd = os.getcwd()
    sys.path.insert(0, OLD)
    os.chdir(OLD)
    try:
        import app as old_app  # noqa: E402

        client = old_app.app.test_client()
        with open(mango, "rb") as f:
            mango_bytes = f.read()
        with open(shopmine, "rb") as f:
            shopmine_bytes = f.read()

        up = client.post(
            "/api/upload",
            data={
                "buy_file": (open(mango, "rb"), os.path.basename(mango)),
                "sell_file": (open(shopmine, "rb"), os.path.basename(shopmine)),
            },
            content_type="multipart/form-data",
        )
        if up.status_code != 200:
            raise SystemExit(f"/api/upload 실패: {up.status_code} {up.data[:400]}")
        up_json = up.get_json()
        if not (up_json.get("buy", {}).get("success") and up_json.get("sell", {}).get("success")):
            raise SystemExit(f"/api/upload 파싱 실패: {up_json}")

        an = client.post("/api/analyze", json={})
        if an.status_code != 200:
            raise SystemExit(f"/api/analyze 실패: {an.status_code} {an.data[:400]}")

        # ── 순수 cycle ① 산출물만 추출 (라우트 오염 제외) ──
        store = old_app.store
        agg = old_app._aggregate(store["matched"], old_app.DEFAULT_PRICE_RANGES)

        buy_missing = store.get("buy_missing_df")
        baseline = {
            "date": date,
            "source_files": {
                "buy": os.path.basename(mango),
                "sell": os.path.basename(shopmine),
            },
            "matched": list(store["matched"] or []),
            "unmatched_buy": list(store["unmatched_buy"] or []),
            "unmatched_sell": list(store["unmatched_sell"] or []),
            "buy_missing": (
                buy_missing.to_dict("records") if buy_missing is not None else []
            ),
            "summary": agg["summary"],
            "market": agg["market"],
            "daily": agg["daily"],
            "monthly": agg["monthly"],
            "brand": agg["brand"],
            "priceRange": agg["priceRange"],
            "product": agg["product"],
            "filters": agg["filters"],
        }
    finally:
        os.chdir(prev_cwd)
        # sys.path 원복 (여러 date 를 한 프로세스에서 돌릴 때 오염 방지)
        try:
            sys.path.remove(OLD)
        except ValueError:
            pass

    return mask_pii(_jsonable(baseline))


def main():
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python scripts/margin_capture_baseline.py <date>  (예: 260704)")
    date = sys.argv[1]
    baseline = capture(date)
    os.makedirs(FIXTURES, exist_ok=True)
    text = json.dumps(baseline, ensure_ascii=False, indent=1)
    raw = text.encode("utf-8")

    plain = os.path.join(FIXTURES, f"{date}_baseline.json")
    gz = plain + ".gz"
    # 재생성 시 반대 포맷 잔재 제거
    for stale in (plain, gz):
        if os.path.exists(stale):
            os.remove(stale)

    if len(raw) > GZIP_THRESHOLD:
        with gzip.open(gz, "wb") as f:
            f.write(raw)
        out, size = gz, os.path.getsize(gz)
        print(f"[OK] {out}  ({size:,} bytes, gzip of {len(raw):,})")
    else:
        with open(plain, "wb") as f:
            f.write(raw)
        out, size = plain, os.path.getsize(plain)
        print(f"[OK] {out}  ({size:,} bytes)")
    print(
        f"  matched={len(baseline['matched'])} "
        f"unmatched_buy={len(baseline['unmatched_buy'])} "
        f"unmatched_sell={len(baseline['unmatched_sell'])} "
        f"buy_missing={len(baseline['buy_missing'])}"
    )
    print(f"  summary.총순마진={baseline['summary'].get('총순마진')}")
    groups = {k: len(baseline[k]) for k in ("market", "daily", "monthly", "brand", "priceRange", "product")}
    print(f"  groups={groups}")


if __name__ == "__main__":
    main()

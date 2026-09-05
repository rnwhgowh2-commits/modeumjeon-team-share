# -*- coding: utf-8 -*-
r"""Build the blackspot-tab `analysisData` for the golden card-number regression.

Used to mirror `webapp/routes/api_margin.analyze()` by substituting the old
integrated-order-management EXCEL for the market API as sell_df (the same
substitution `tests/margin/test_golden_regression.py` used to make), so the
run was offline/deterministic and reproduced the ORIGINAL program's blackspot
screenshot.

⚠️ 2026-09 전 마켓 API 연동 완료로 sell_source 의 구 통합주문관리 엑셀 변환 함수 자체가 삭제됐다.
   이 헬퍼는 옛 데이터 폴더(`data_available()`)가 있는 그 한 대의 개발자 PC 밖에서는
   원래도 전부 skip 이었다 — 그 PC 에서도 이제는 재현 불가이므로 `build_analysis_data()`
   호출 시 명시적으로 실패한다(조용한 실패 금지).
"""
import json
import os

# old program data folder (local only; absent on CI/teammate PCs → callers skip)
from scripts.margin_capture_baseline import OLD

DATA_ROOT = os.path.join(OLD, "데이터")


def source_excel_pair(date):
    """Locate (더망고, 매출) xls/xlsx for a date folder. (None, None) if absent."""
    folder = os.path.join(DATA_ROOT, date)
    if not os.path.isdir(folder):
        return None, None
    mango = shop = None
    for fn in os.listdir(folder):
        low = fn.lower()
        if not (low.endswith(".xls") or low.endswith(".xlsx")):
            continue
        if "더망고" in fn:
            mango = os.path.join(folder, fn)
        elif "샵마인" in fn:
            shop = os.path.join(folder, fn)
    return mango, shop


def data_available(date):
    mango, shop = source_excel_pair(date)
    return bool(mango and shop)


def build_analysis_data(date):
    """Return the full `analysisData` dict the page would receive for `date`.

    2026-09: sell_source's old integrated-order-management excel conversion
    function was deleted (all markets now go through the API). This
    excel-substitution reproduction path can no longer work, even on the one
    dev PC that still has the old data folder — skip instead of silently
    reproducing something else (this helper was already local-PC-only and
    never ran in CI).
    """
    import pytest

    mango, shop = source_excel_pair(date)
    if not (mango and shop):
        raise FileNotFoundError(f"source excel pair missing for {date}")
    pytest.skip(
        f"[{date}] the old integrated-order-management excel conversion "
        "function was removed (2026-09, full market-API migration) — this "
        "golden reproduction path no longer works."
    )


def write_analysis_data(date, path):
    """Build + dump analysisData to `path` (allow_nan=False mirrors store._pack guard)."""
    payload = build_analysis_data(date)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, allow_nan=False)
    return path

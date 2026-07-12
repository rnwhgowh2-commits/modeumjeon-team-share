# -*- coding: utf-8 -*-
r"""Build the blackspot-tab `analysisData` for the golden card-number regression.

Mirrors `webapp/routes/api_margin.analyze()` EXACTLY, but substitutes the 샵마인
EXCEL for the market API as sell_df — the same substitution
`tests/margin/test_golden_regression.py` makes (so the run is offline/deterministic
and reproduces the ORIGINAL program's blackspot screenshot).

We import and reuse the route's real helpers (`_json_normalize`, `_augment_blackspot`)
and the real modules (pipeline / aggregator / buy_parser / sell_source / keyword_store)
— nothing is re-implemented. The only analyze() step skipped is R2 upload + DB save,
which don't touch `analysisData`.
"""
import json
import os

# reuse the route's exact helpers — do NOT re-implement
from webapp.routes.api_margin import _json_normalize, _augment_blackspot
from lemouton.margin import aggregator, pipeline, keyword_store
from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.sell_source import from_shopmine_excel
from lemouton.margin.config import DEFAULT_PRICE_RANGES

# old program data folder (local only; absent on CI/teammate PCs → callers skip)
from scripts.margin_capture_baseline import OLD

DATA_ROOT = os.path.join(OLD, "데이터")


def source_excel_pair(date):
    """Locate (더망고, 샵마인) xls/xlsx for a date folder. (None, None) if absent."""
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
    """Return the full `analysisData` dict the page would receive for `date`."""
    mango, shop = source_excel_pair(date)
    if not (mango and shop):
        raise FileNotFoundError(f"source excel pair missing for {date}")

    with open(mango, "rb") as f:
        buy_df = parse_buy(f.read(), os.path.basename(mango))
    with open(shop, "rb") as f:
        sell_df = from_shopmine_excel(f.read(), os.path.basename(shop))

    # analyze(): pipeline.run(staged.df, sell_df) — no price_ranges (defaults inside)
    out = pipeline.run(buy_df, sell_df)
    agg = aggregator.aggregate(out["matched"], DEFAULT_PRICE_RANGES)
    payload = _json_normalize({**out, **agg})
    # 2b) blackspot classification contract restore (classified / blackspot_summary /
    #     unmatched_buy augment / mango_* counts / missing_order_no)
    _augment_blackspot(payload, buy_df, sell_df, out)
    # inject summary._card_keywords — analyze() reads keyword_store.get_config()["cards"];
    # on a fresh DB that returns the bundled seed (identical to margin_embed.html's
    # _getCardKeywords() built-in fallback). Reuse the module's own seed loader — no DB.
    cards = keyword_store._load_seed().get("cards") or {}
    if cards:
        payload.setdefault("summary", {})["_card_keywords"] = cards
    return payload


def write_analysis_data(date, path):
    """Build + dump analysisData to `path` (allow_nan=False mirrors store._pack guard)."""
    payload = build_analysis_data(date)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, allow_nan=False)
    return path

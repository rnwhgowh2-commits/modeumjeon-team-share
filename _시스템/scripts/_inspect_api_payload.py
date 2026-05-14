# -*- coding: utf-8 -*-
"""Commerce API 응답에서 channelProductNo 추출 위치 확인."""
import sys, io, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

_LOG = Path("data/_inspect_api_payload.log")
_LOG.parent.mkdir(parents=True, exist_ok=True)
log = open(_LOG, "w", encoding="utf-8", buffering=1)
def W(s): log.write(s + "\n"); log.flush()

from shared.platforms.smartstore.get_options import fetch_product_options

result = fetch_product_options(13153051689)
W(f"success: {result.success}")
W(f"origin_product_no: {result.origin_product_no}")
W(f"product_name: {result.product_name}")
W(f"options: {len(result.options)}")
W(f"\n=== raw payload top-level keys ===")
if result.raw:
    for k in result.raw.keys():
        v = result.raw[k]
        if isinstance(v, dict):
            W(f"  {k}: dict — keys={list(v.keys())[:15]}")
        elif isinstance(v, list):
            W(f"  {k}: list[{len(v)}]")
            if v and isinstance(v[0], dict):
                W(f"    [0] keys: {list(v[0].keys())[:20]}")
        else:
            W(f"  {k}: {type(v).__name__} = {str(v)[:80]}")
    W(f"\n=== smartstoreChannelProduct ===")
    sc = result.raw.get('smartstoreChannelProduct') or result.raw.get('smartstoreChannel') or {}
    if sc:
        W(json.dumps({k: str(v)[:80] for k, v in sc.items()}, ensure_ascii=False, indent=2))
    W(f"\n=== channelProducts (if list) ===")
    cps = result.raw.get('channelProducts') or []
    if cps:
        for i, cp in enumerate(cps):
            W(f"  [{i}]: {json.dumps({k: str(v)[:60] for k, v in cp.items() if not isinstance(v, (dict, list))}, ensure_ascii=False)}")
W("\ndone")

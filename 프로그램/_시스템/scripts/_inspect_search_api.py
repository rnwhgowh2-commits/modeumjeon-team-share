# -*- coding: utf-8 -*-
"""Commerce API search 엔드포인트 시도 — channelProductNo 추출."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

_LOG = Path("data/_inspect_search_api.log")
_LOG.parent.mkdir(parents=True, exist_ok=True)
log = open(_LOG, "w", encoding="utf-8", buffering=1)
def W(s): log.write(s + "\n"); log.flush()

from shared.platforms.smartstore.client import SmartStoreClient
client = SmartStoreClient()

# 시도 1: POST /external/v1/products/search
W("=== try1: POST /external/v1/products/search ===")
try:
    # 1b: originProductNo 필터 (정수 array)
    r = client.request("POST", "/external/v1/products/search", body={
        "originProductNos": [13153051689],
        "page": 1, "size": 5,
    })
    if isinstance(r, dict):
        W(f"keys: {list(r.keys())[:10]}")
        W(f"totalElements: {r.get('totalElements')}")
        contents = r.get('contents') or []
        for i, item in enumerate(contents[:3]):
            W(f"\n--- item[{i}] ---")
            W(f"  originProductNo: {item.get('originProductNo')}")
            cps = item.get('channelProducts') or []
            for cp in cps:
                W(f"  channelProductNo: {cp.get('channelProductNo')} (channelServiceType={cp.get('channelServiceType')}, name={(cp.get('name') or '')[:50]})")
    else:
        W(f"non-dict: {type(r).__name__} {str(r)[:200]}")
except Exception as e:
    W(f"err: {type(e).__name__}: {e}")

# 시도 2: GET /external/v1/products/origin-products/{x}/channel-products
W("\n=== try2: GET .../origin-products/{x}/channel-products ===")
try:
    r = client.request("GET", "/external/v1/products/origin-products/13153051689/channel-products")
    if isinstance(r, dict):
        W(f"keys: {list(r.keys())[:10]}")
        W(json.dumps(r, ensure_ascii=False, indent=2)[:800])
    else:
        W(f"non-dict: {type(r).__name__}")
except Exception as e:
    W(f"err: {type(e).__name__}: {e}")

# 시도 3: GET /external/v2/products with query
W("\n=== try3: GET /external/v2/products ===")
try:
    r = client.request("GET", "/external/v2/products?originProductNo=13153051689")
    if isinstance(r, dict):
        W(f"keys: {list(r.keys())[:10]}")
        W(json.dumps(r, ensure_ascii=False, indent=2)[:1500])
except Exception as e:
    W(f"err: {type(e).__name__}: {e}")

W("\ndone")

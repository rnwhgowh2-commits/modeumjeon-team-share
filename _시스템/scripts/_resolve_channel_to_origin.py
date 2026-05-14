# -*- coding: utf-8 -*-
"""스크린샷의 channelProductNo 들에 대한 originProductNo 매핑 조회."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

_LOG = Path("data/_resolve_channel_to_origin.log")
_LOG.parent.mkdir(parents=True, exist_ok=True)
log = open(_LOG, "w", encoding="utf-8", buffering=1)
def W(s): log.write(s + "\n"); log.flush()

# 사용자 캡쳐본의 상품번호 (channelProductNo)
TARGETS = [
    13211486893,
    13211402595,
    13211379418,
    13211350421,
    13211326309,
    13211239655,
    13211211948,
    13200695698,
    13112592707,
]

from shared.platforms.smartstore.client import SmartStoreClient
client = SmartStoreClient()

# 전체 상품 fetch + mapping 추출
all_items = []
page = 1
while True:
    r = client.request("POST", "/external/v1/products/search",
                       body={"page": page, "size": 100})
    contents = r.get("contents") or []
    all_items.extend(contents)
    if r.get("last") or len(contents) < 100:
        break
    page += 1
    if page > 30: break

W(f"전체 fetched: {len(all_items)} items")
W("")
W("=== 매핑 ===")
W(f"{'channelProductNo':>14} | {'originProductNo':>15} | name")
W("-" * 100)

found = {}
for item in all_items:
    origin = int(item.get("originProductNo") or 0)
    cps = item.get("channelProducts") or []
    for cp in cps:
        ch = int(cp.get("channelProductNo") or 0)
        if ch in TARGETS:
            found[ch] = {"origin": origin, "name": cp.get("name") or ""}

for tch in TARGETS:
    if tch in found:
        info = found[tch]
        W(f"{tch:>14} | {info['origin']:>15} | {info['name'][:60]}")
    else:
        W(f"{tch:>14} |        NOT FOUND |")

W("")
W("=== 검증용 URL (사용자가 직접 열어서 상품명 확인) ===")
for tch in TARGETS:
    if tch in found:
        info = found[tch]
        W(f"  https://sell.smartstore.naver.com/#/products/edit/{info['origin']}")
        W(f"    expected name: {info['name'][:60]}")
W("\ndone")

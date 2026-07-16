"""판매처 API 지도 데이터 로더 + 검증기 (무의존, 순수 Python).

단일 진실 원천: webapp/data/marketplace_api_map.json
- validate_map: 스키마 필수키 + 완성게이트(st∈{ok,code}→req·res·fields·success 필수)
  + api id 유일성 + transitions/perMarket 참조무결성.
"""
from __future__ import annotations
import json, os

_PATH = os.path.join(os.path.dirname(__file__), "data", "marketplace_api_map.json")

TOP_KEYS = ["schema_version", "markets", "unifiedStatuses", "transitions", "codes", "apis"]
API_KEYS = ["id","market","fnKey","tabs","category","nm","dir","st",
            "endpoint","req","res","fields","success","idTraps","persistIds","codeRef"]
GATE_STATUSES = {"ok", "code"}

def load_map(path: str = _PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def validate_map(data: dict) -> list[str]:
    errors: list[str] = []
    for k in TOP_KEYS:
        if k not in data:
            errors.append(f"최상위 키 누락: {k}")
    apis = data.get("apis", [])
    seen = set()
    for a in apis:
        aid = a.get("id", "<id없음>")
        if aid in seen:
            errors.append(f"api id 중복: {aid}")
        seen.add(aid)
        for k in API_KEYS:
            if k not in a:
                errors.append(f"api[{aid}] 필드 누락: {k}")
        if a.get("st") in GATE_STATUSES:
            for g in ("req", "res", "fields", "success"):
                if not a.get(g):
                    errors.append(f"완성게이트 위반 api[{aid}]: st={a.get('st')} 인데 {g} 비어있음")
    ids = {a.get("id") for a in apis}
    for t in data.get("transitions", []):
        for mk, ref in (t.get("perMarket") or {}).items():
            if ref != "unsupported" and ref not in ids:
                errors.append(f"transition {t.get('from')}→{t.get('to')} perMarket[{mk}] 참조 없음: {ref}")
    return errors

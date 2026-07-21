"""판매처 API 지도 데이터 로더 + 검증기 (무의존, 순수 Python).

단일 진실 원천: webapp/data/marketplace_api_map.json
- validate_map: 스키마 필수키 + 완성게이트(st∈{ok,code}→req·res·fields·success 필수)
  + api id 유일성 + transitions/perMarket 참조무결성.
"""
from __future__ import annotations
import json, os

_PATH = os.path.join(os.path.dirname(__file__), "data", "marketplace_api_map.json")

TOP_KEYS = ["schema_version", "markets", "unifiedStatuses", "transitions", "codes", "apis", "incidents"]
API_KEYS = ["id","market","fnKey","tabs","category","nm","dir","st",
            "endpoint","req","res","fields","success","idTraps","persistIds","codeRef"]
GATE_STATUSES = {"ok", "code"}

# 과거이력(문제 발생·해결) — 각 항목 필수 키. commit 만 빈 값 허용(커밋 없는 개통·설정 건).
INCIDENT_KEYS = ["id","date","markets","area","title","symptom","cause",
                 "fix","commit","severity","status","lesson"]
# 코드 해결 명확 기록 지침: 아래 필드는 비어있으면 안 됨(조용한 통과 금지).
INCIDENT_NONEMPTY = ["id","date","area","title","symptom","cause","fix","severity","status","lesson"]
INCIDENT_SEVERITIES = {"high", "med", "low"}
INCIDENT_STATUSES = {"resolved", "mitigated", "open"}

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
    market_ids = {m.get("id") for m in data.get("markets", [])}
    for t in data.get("transitions", []):
        for mk, ref in (t.get("perMarket") or {}).items():
            if ref != "unsupported" and ref not in ids:
                errors.append(f"transition {t.get('from')}→{t.get('to')} perMarket[{mk}] 참조 없음: {ref}")

    # 과거이력 검증 — 필수키·비어있음·타입·id중복·enum(조용한 통과 금지)
    seen_inc = set()
    for inc in data.get("incidents", []):
        iid = inc.get("id", "<id없음>")
        if iid in seen_inc:
            errors.append(f"incident id 중복: {iid}")
        seen_inc.add(iid)
        for k in INCIDENT_KEYS:
            if k not in inc:
                errors.append(f"incident[{iid}] 필드 누락: {k}")
        for k in INCIDENT_NONEMPTY:
            if not str(inc.get(k, "")).strip():
                errors.append(f"incident[{iid}] {k} 비어있음(기록 지침 위반: 코드 해결 명확 기록)")
        mks = inc.get("markets")
        if not isinstance(mks, list) or not mks:
            errors.append(f"incident[{iid}] markets 는 비어있지 않은 배열이어야 함")
        else:
            for mk in mks:
                if market_ids and mk not in market_ids:
                    errors.append(f"incident[{iid}] markets 참조 없음: {mk}")
        if inc.get("severity") not in INCIDENT_SEVERITIES:
            errors.append(f"incident[{iid}] severity 값 오류: {inc.get('severity')} (high/med/low)")
        if inc.get("status") not in INCIDENT_STATUSES:
            errors.append(f"incident[{iid}] status 값 오류: {inc.get('status')} (resolved/mitigated/open)")

    # autoConfirm — 주문상태 전환(V1) SOT (구 인라인 TRANS/API_CALLS 이관분)
    ac = data.get("autoConfirm")
    if not isinstance(ac, dict):
        errors.append("autoConfirm 누락(주문상태 전환 SOT)")
    else:
        if not ac.get("markets"):
            errors.append("autoConfirm.markets 비어있음")
        for m in ac.get("markets", []):
            mid = m.get("id", "?")
            if market_ids and mid not in market_ids:
                errors.append(f"autoConfirm.markets 참조 없음: {mid}")
            for k in ("id", "api", "ids", "v"):
                if not m.get(k):
                    errors.append(f"autoConfirm.markets[{mid}] {k} 비어있음")
        for k, call in (ac.get("calls") or {}).items():
            if market_ids and k not in market_ids:
                errors.append(f"autoConfirm.calls 참조 없음: {k}")
            if not call.get("auth") or not call.get("rows"):
                errors.append(f"autoConfirm.calls[{k}] auth/rows 비어있음")
        for c in ac.get("cautions", []):
            if market_ids and c.get("id") not in market_ids:
                errors.append(f"autoConfirm.cautions 참조 없음: {c.get('id')}")
    return errors

# -*- coding: utf-8 -*-
"""마켓 1개 = 마크다운 1장 브리핑(전수정독용).

출처 = 화면(/marketplace-guide/map)과 동일: marketplace_api_map.json(SOT)
+ api_ingest_paths.json(문서 수집법) + docs/markets/<id>.yaml(어댑터 근거, 있으면).
원칙: 날조 금지 — 없는 정보는 '확인불가'로 표기. 폴백 금지.
"""
from __future__ import annotations

import json
import os

_WEBAPP = os.path.dirname(__file__)
_DATA = os.path.join(_WEBAPP, "data")


def _load(name: str) -> dict:
    with open(os.path.join(_DATA, name), encoding="utf-8") as f:
        return json.load(f)


def _repo_root() -> str:
    # webapp → _시스템 → 프로그램 → 저장소 루트
    return os.path.dirname(os.path.dirname(os.path.dirname(_WEBAPP)))


def _yaml_profile(mid: str) -> str | None:
    p = os.path.join(_repo_root(), "docs", "markets", f"{mid}.yaml")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return None


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False, indent=1)


def build_brief(mid: str) -> str | None:
    data = _load("marketplace_api_map.json")
    mk = next((m for m in data.get("markets", []) if m.get("id") == mid), None)
    if mk is None:
        return None
    out: list[str] = []
    add = out.append
    label = mk.get("label", mid)
    add(f"# {label} 개발 브리핑 (자동생성 — 데이터 코드 지도 SOT)")
    add("")
    add("> 출처: marketplace_api_map.json · api_ingest_paths.json · docs/markets/*.yaml — 화면(/marketplace-guide/map)과 같은 원천.")
    add("> 원칙: 날조 금지 — 없는 정보는 '확인불가'.")
    add("")
    add("## 1. 개발환경")
    for k in ("auth", "base_url", "env_prefixes", "concurrency", "rate"):
        v = mk.get(k)
        add(f"- {k}: {v if v not in (None, '', []) else '확인불가'}")
    u = mk.get("upload_limit") or {}
    if u:
        add(f"- 업로드 한도(실측): {u.get('measured', '확인불가')} · 단위={u.get('scope', '?')}"
            f" · 동시={u.get('concurrent', '?')} · 문서한도={u.get('limit_doc', '?')}")
        if u.get("note"):
            add(f"  - {u['note']}")
    add("")
    apis = [a for a in data.get("apis", []) if a.get("market") == mid]
    add(f"## 2. API 카탈로그 — {len(apis)}개 (st: ok=라이브검증 · code=코드있음(검증대기) · off=문서만 · todo=미확인)")
    by_cat: dict[str, list] = {}
    for a in apis:
        by_cat.setdefault(a.get("category") or "기타", []).append(a)
    for cat, items in by_cat.items():
        add(f"### {cat} ({len(items)})")
        for a in items:
            add(f"- [{a.get('st', '?')}] ({a.get('dir', '?')}) **{a.get('nm', '')}** — `{a.get('endpoint', '')}`"
                f"  (id={a.get('id', '')}, tabs={','.join(a.get('tabs') or [])})")
            if a.get("codeRef"):
                add(f"  - 코드: `{a['codeRef']}`")
            if a.get("st") in ("ok", "code"):
                for key in ("req", "res", "fields", "success"):
                    if a.get(key):
                        add(f"  - {key}: {_j(a[key])}")
            for key in ("idTraps", "persistIds"):
                if a.get(key):
                    add(f"  - {key}: {_j(a[key])}")
        add("")
    sc = data.get("settleCalc") or {}
    idx = next((i for i, m in enumerate(sc.get("markets", [])) if m.get("id") == mid), None)
    add("## 3. 정산 계산 (settleCalc)")
    if idx is None:
        add("- 확인불가(이 마켓의 정산 계산 데이터 미접수)")
    else:
        add(f"- 정산 API: {sc['markets'][idx].get('api', '?')}")
        for r in sc.get("rows", []):
            cells = r.get("cells") or []
            c = cells[idx] if idx < len(cells) else {}
            if c.get("c"):
                val = c["c"]
            elif c.get("inc"):
                val = f"{c['inc']} 에 포함" + (f" ({c['n']})" if c.get("n") else "")
            else:
                val = "확인불가"
            add(f"- {r.get('item')} ({r.get('op')}): `{val}`")
        tot = sc.get("total") or []
        if idx < len(tot):
            add(f"- 최종 정산액: `{tot[idx]}`")
    add("")
    ac = data.get("autoConfirm") or {}
    ent = next((m for m in ac.get("markets", []) if m.get("id") == mid), None)
    call = (ac.get("calls") or {}).get(mid)
    add("## 4. 주문상태 전환 (autoConfirm)")
    if not ent and not call:
        add("- 확인불가(미배선 또는 미접수)")
    if ent:
        add(f"- 전환 API: `{ent.get('api')}` · 식별자: {ent.get('ids')} · 검증: {ent.get('v')}")
    if call:
        add(f"- 인증: {call.get('auth')}")
        for r in call.get("rows", []):
            add(f"- {r[0]}: `{r[1]}` — {r[2]}")
        if call.get("note"):
            add(f"- ⚠️ {call['note']}")
    for c in ac.get("cautions", []):
        if c.get("id") == mid:
            add(f"- ⚠️ {c.get('text')}")
    add("")
    add("## 5. 통일 주문상태 전이 (transitions)")
    hit = False
    for t in data.get("transitions", []):
        ref = (t.get("perMarket") or {}).get(mid)
        if ref:
            hit = True
            add(f"- {t.get('from')} → {t.get('to')}: {ref}")
    if not hit:
        add("- 확인불가(이 마켓 참조 없음)")
    add("")
    add("## 6. 공식 문서 수집법 (api_ingest_paths.json)")
    try:
        ing = _load("api_ingest_paths.json")
        row = next((r for r in ing.get("matrix", [])
                    if isinstance(r, list) and r and label in str(r[0])), None)
        if row:
            add(f"- 매트릭스(경로별 뚫림): {row}")
        h = next((x for x in ing.get("hier", []) if label in str(x.get("mk", ""))), None)
        if h:
            add(f"- 채택 경로: {h.get('route', '?')}")
            add(f"- 상위탭: {h.get('top', '?')}")
            add(f"- 카테고리: {h.get('cats', '?')}")
            if h.get("detail"):
                add(f"- 상세: {h['detail']}")
        if not row and not h:
            add("- 확인불가(수집법 데이터에 이 마켓 없음)")
    except OSError:
        add("- 확인불가(api_ingest_paths.json 읽기 실패)")
    add("")
    incs = [i for i in data.get("incidents", []) if mid in (i.get("markets") or [])]
    add(f"## 7. 과거이력 ({len(incs)}건)")
    for i in incs:
        add(f"- [{i.get('date')}·{i.get('severity')}·{i.get('status')}] {i.get('title')}"
            f" — 증상: {i.get('symptom')} / 원인: {i.get('cause')} / 해결: {i.get('fix')} / 교훈: {i.get('lesson')}")
    add("")
    add("## 8. 어댑터 프로파일 (docs/markets/*.yaml — 라이브 코드 근거)")
    y = _yaml_profile(mid)
    if y:
        add("```yaml")
        add(y.rstrip())
        add("```")
    else:
        add("- 확인불가(yaml 없음 — 서버 배포본엔 docs/ 미포함일 수 있음. 로컬 저장소에서 확인)")
    add("")
    wired = sum(1 for a in apis if a.get("st") in ("ok", "code"))
    off = sum(1 for a in apis if a.get("st") == "off")
    todo = sum(1 for a in apis if a.get("st") == "todo")
    add("## 9. 요약 — 배선 현황")
    add(f"- 우리 코드 연결(ok+code): {wired} · 문서만(off): {off} · 미확인(todo): {todo}")
    add("- 빈칸 채우기: 인앱 「📘 API 문서 수집법」 탭(=docs/markets/_API문서수집법.md) 플레이북 순서로 확보 → 이 JSON에 되채움(validate_map 통과).")
    return "\n".join(out)

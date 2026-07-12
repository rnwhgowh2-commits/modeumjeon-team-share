# -*- coding: utf-8 -*-
r"""소싱처 계정 관리 API — `/api/sourcing-sites` + `/api/settings` (GET/POST).

마진 계산기 페이지(`/orders/margin-embed` 의 ⚙️설정 → 소싱처 계정 관리 탭)가
이 리터럴 경로를 호출한다. `/api/margin` 프리픽스가 아니라 최상위 `/api/*` 여야
한다 — 이식된 원본 페이지(renderSourcingAccounts / saveSourcingAccounts)가
그 경로를 하드코딩했기 때문(D1 `api_keywords` 와 동일 패턴).

■ 원본 계약 (C:\dev\대량등록 마진계산기\app.py 1633–1671):
  · GET  /api/sourcing-sites → {<site>: {name, login_methods, login_method_labels}}
  · GET  /api/settings       → {accounts: {<site>: [{id, pw, owner, login_method}]}}
                               (pw 는 마스킹 sentinel '***' 로 대체)
  · POST /api/settings       → body {accounts: {...}}; 들어온 pw 가 '***' 이면
                               기존 저장 pw 를 유지(마스킹을 실제 pw 로 저장 X).

■ 저장소 승격: 원본의 서버측 settings.json(평문 파일) → 모음전 기존 자격증명
  DB(SourcingCredential) via `lemouton.auth.sourcing_credentials.default_store()`.
  파일 평문 저장을 재구현하지 않는다(팀 공유·배포 무관 영속·CLAUDE.md 3대 원칙).

■ list ↔ account_key 매핑 (페이지는 사이트별 계정 LIST, 스토어는 account_key 키):
  · 정렬 규칙: 'default' 키 우선, 나머지 오름차순 → 결정적(deterministic) 순서.
  · POST 시 키 배정: 들어온 리스트의 index i → 현재 저장 순서의 i 번째 기존 키
    재사용, 초과분은 새 안정 키 발급('default' → '_2' → '_3' …, MAIN/_2 패턴).
  · pw 마스킹 보존은 index 가 아닌 **id 일치**로 찾는다(원본은 index 기준이라
    중간 삭제 시 pw 가 엉키는 위험이 있음 → id 매칭이 자격증명 무결성에 안전).
  · 리스트에서 사라진 기존 계정은 스토어에서 remove.

■ owner(담당자) 필드: SourcingCredential 스키마에 컬럼이 없어 영속 불가 →
  GET 은 항상 owner:"" 로 반환(페이지는 acc.owner || '' 로 우아하게 처리).
  ※ id/pw/login_method(핵심 자격증명·로그인 계약)는 100% 영속된다.

■ /api/cookie-status/all · /api/check-sourcing 은 여기 없음(Task E — 로컬 확장
  자동 점검). 페이지는 이미 .catch 로 우아하게 degrade 한다(건드리지 않음).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("api_sourcing_settings", __name__, url_prefix="/api")

# margin_embed.html line 2528: `acc.pw === '***'` — 페이지가 기대하는 마스킹 값과 일치.
PW_MASK = "***"

_LOGIN_METHOD_LABELS = {
    "direct": "직접 로그인",
    "naver": "네이버 로그인",
    "kakao": "카카오 로그인",
    "google": "구글 로그인",
    "manual": "수동 로그인",
}


# ══════════════════════════════════════════════════════════════════
#  소싱처 사이트 레지스트리 (단일 진실 원천 = webapp.routes.accounts.SOURCING_SITES)
# ══════════════════════════════════════════════════════════════════
def _sites_registry() -> dict:
    """모음전 소싱처 사이트 목록 → 원본 /api/sourcing-sites 형태.

    자격증명 DB 를 검증·백킹하는 것과 동일한 목록(accounts.py SOURCING_SITES)을
    재사용해 마진 페이지와 계정 페이지의 소싱처 목록을 일관되게 유지한다.
    login_methods 는 supports_naver 에서 유도(원본이 ssg/lotteon 등에 naver 를
    제공하던 것과 동일). 스토어는 어떤 방식이든 id+pw 를 요구한다.
    """
    from webapp.routes.accounts import SOURCING_SITES
    sites = {}
    for s in SOURCING_SITES:
        methods = ["direct"]
        if s.get("supports_naver"):
            methods.append("naver")
        sites[s["key"]] = {
            "name": s.get("label", s["key"]),
            "login_methods": methods,
            "login_method_labels": {m: _LOGIN_METHOD_LABELS.get(m, m) for m in methods},
        }
    return sites


def _known_source_keys() -> set:
    return set(_sites_registry().keys())


# ══════════════════════════════════════════════════════════════════
#  list ↔ account_key 매핑 헬퍼
# ══════════════════════════════════════════════════════════════════
def _ordered_keys(accounts_map: dict) -> list:
    """저장된 account_key 를 결정적 순서로: 'default' 우선, 나머지 오름차순."""
    return sorted(accounts_map.keys(), key=lambda k: (k != "default", k))


def _mint_key(used: set) -> str:
    """새 안정 account_key 발급 — 'default' → '_2' → '_3' … (MAIN/_2 패턴)."""
    if "default" not in used:
        return "default"
    i = 2
    while f"_{i}" in used:
        i += 1
    return f"_{i}"


# ══════════════════════════════════════════════════════════════════
#  GET /api/sourcing-sites
# ══════════════════════════════════════════════════════════════════
@bp.route("/sourcing-sites", methods=["GET"])
def sourcing_sites():
    """소싱처 목록 및 로그인 방식 조회 (원본 계약 그대로)."""
    return jsonify(_sites_registry())


# ══════════════════════════════════════════════════════════════════
#  GET /api/settings — 비밀번호 마스킹
# ══════════════════════════════════════════════════════════════════
@bp.route("/settings", methods=["GET"])
def get_settings():
    """소싱처 계정 설정 조회 — pw 는 항상 마스킹.

    형태: {"accounts": {<source>: [{id, pw:'***', owner:'', login_method}, ...]}}
    """
    from lemouton.auth.sourcing_credentials import default_store
    allc = default_store().load_all()  # {source: {account_key: {id, pw, login_method}}}
    accounts = {}
    for source, amap in allc.items():
        lst = []
        for key in _ordered_keys(amap):
            creds = amap[key] or {}
            has_pw = bool(creds.get("pw"))
            lst.append({
                "id": creds.get("id", "") or "",
                "pw": PW_MASK if has_pw else "",
                "owner": "",  # DB 스키마 미지원 (report 참조)
                "login_method": creds.get("login_method") or "direct",
            })
        accounts[source] = lst
    return jsonify({"accounts": accounts})


# ══════════════════════════════════════════════════════════════════
#  POST /api/settings — 마스킹 pw 보존 + DB 영속
# ══════════════════════════════════════════════════════════════════
@bp.route("/settings", methods=["POST"])
def save_settings():
    """소싱처 계정 설정 저장.

    · pw == '***' → 기존 저장 pw 유지(id 일치로 조회).
    · 완전 빈 행(id·pw 모두 빈값) → 저장 안 함(no-op, 손실 아님).
    · id 는 있는데 pw 를 결정할 수 없음 → 400(조용한 실패 금지).
    · 리스트에서 사라진 기존 계정 → remove.
    검증을 먼저 전부 통과한 뒤에만 쓰기(부분 저장 방지 = 원자성).
    """
    from lemouton.auth.sourcing_credentials import default_store

    data = request.get_json(silent=True) or {}
    incoming = data.get("accounts")
    if incoming is None:
        incoming = {}
    if not isinstance(incoming, dict):
        return jsonify({"success": False, "error": "accounts 는 dict 여야 합니다."}), 400

    store = default_store()
    known = _known_source_keys()
    current_all = store.load_all()

    upserts = []   # (source, account_key, id, pw, login_method)
    removes = []   # (source, account_key)

    for source, accs in incoming.items():
        if source not in known:
            return jsonify({"success": False,
                            "error": f"지원하지 않는 소싱처: {source}"}), 400
        if not isinstance(accs, list):
            return jsonify({"success": False,
                            "error": f"{source} 계정 목록은 list 여야 합니다."}), 400

        cur = current_all.get(source, {})           # {account_key: {id, pw, login_method}}
        by_id = {(c.get("id") or ""): c for c in cur.values()}
        ordered = _ordered_keys(cur)
        used = set(ordered)

        # id 가 있는 실제 행만(빈 행은 무시 — 저장할 자격증명이 없음)
        real_accs = [a for a in accs if isinstance(a, dict) and (a.get("id") or "").strip()]

        kept_keys = set()
        for i, acc in enumerate(real_accs):
            id_val = (acc.get("id") or "").strip()
            pw_in = acc.get("pw")
            method = (acc.get("login_method") or "direct").strip() or "direct"

            # pw 결정: 마스킹이면 id 일치로 기존 pw 조회(없으면 index 폴백)
            if pw_in == PW_MASK:
                prev = by_id.get(id_val)
                if prev is None and i < len(ordered):
                    prev = cur.get(ordered[i])
                pw_val = (prev or {}).get("pw", "") if prev else ""
                if not pw_val:
                    return jsonify({
                        "success": False,
                        "error": f"{source}/{id_val}: 마스킹된 비밀번호인데 기존 값을 찾을 수 없습니다.",
                    }), 400
            else:
                pw_val = pw_in or ""
                if not pw_val.strip():
                    return jsonify({
                        "success": False,
                        "error": f"{source}/{id_val}: 비밀번호가 비어 있습니다.",
                    }), 400

            # account_key 배정: 기존 순서 index 재사용, 초과분은 새 키 발급
            if i < len(ordered):
                key = ordered[i]
            else:
                key = _mint_key(used)
                used.add(key)
            kept_keys.add(key)
            upserts.append((source, key, id_val, pw_val, method))

        # 리스트에서 사라진 기존 계정 제거
        for key in ordered:
            if key not in kept_keys:
                removes.append((source, key))

    # ── 쓰기 단계 (검증 전부 통과 후) ──
    try:
        for source, key, id_val, pw_val, method in upserts:
            store.upsert(source=source, account_key=key,
                         id_value=id_val, pw_value=pw_val, login_method=method)
        for source, key in removes:
            store.remove(source, key)
    except ValueError as e:
        # 사전 검증을 통과했음에도 스토어가 거부 → 조용히 넘기지 않고 표면화.
        logger.warning("[api_settings] 저장 거부: %s", e)
        return jsonify({"success": False, "error": str(e)}), 400

    return jsonify({"success": True})

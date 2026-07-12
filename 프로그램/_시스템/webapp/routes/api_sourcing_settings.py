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
  · account_key 는 저장된 로그인 세션/쿠키 파일명({source}_{account_key}.json,
    profile_dir(source, account_key))을 이름짓는 **안정 식별자**다. 따라서 위치가
    아니라 **login_id 정체성**으로 키를 배정한다 — 위치 기반이면 중간 삭제·순서
    변경 시 한 회원이 다른 회원의 세션/쿠키·비밀번호를 물려받는 조용한 오계정
    로그인이 발생(Task E 자동 로그인이 이 자격증명에 얹히기 전에 반드시 차단).
  · 들어온 id 가 기존 계정과 일치 → 그 account_key 재사용. 새 id → 새 키 발급
    ('default' → '_2' → '_3' …, MAIN/_2 패턴, 충돌 회피).
  · 마스킹 pw('***')는 id 일치 계정의 기존 pw 만 복원. 일치 없으면 400(위치
    추정 폴백 없음). login_id RENAME = remove-old + add-new(새 키·새 세션).
  · GET 표시 순서만 'default' 우선·나머지 오름차순으로 정렬(표시용, 정체성 무관).
  · 들어온 리스트에 id 가 없는 기존 계정은 스토어에서 remove.

■ owner(담당자) 필드: SourcingCredential 스키마에 컬럼이 없고 SourcingAccount.
  display_name 은 운영센터 라벨로 이미 쓰이므로, 작은 사이드 테이블
  SourcingAccountOwner((source, account_key)→owner)에 영속한다
  (lemouton.margin.sourcing_owner_store). id/pw/login_method/owner 모두 round-trip.

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
    from lemouton.margin import sourcing_owner_store
    allc = default_store().load_all()  # {source: {account_key: {id, pw, login_method}}}
    owners = sourcing_owner_store.load_all()  # {source: {account_key: owner}}
    accounts = {}
    for source, amap in allc.items():
        omap = owners.get(source, {})
        lst = []
        for key in _ordered_keys(amap):
            creds = amap[key] or {}
            has_pw = bool(creds.get("pw"))
            lst.append({
                "id": creds.get("id", "") or "",
                "pw": PW_MASK if has_pw else "",
                "owner": omap.get(key, "") or "",  # 사이드 테이블(SourcingAccountOwner)
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

    account_key 배정은 **login_id 정체성** 기준이다(리스트 위치 아님):
      · 들어온 id 가 기존 저장 계정과 일치 → 그 계정의 기존 account_key 재사용.
        account_key 는 저장된 세션/쿠키 파일명({source}_{account_key}.json,
        profile_dir(source, account_key))을 이름짓는 **안정 식별자**이므로,
        위치 기반 배정은 중간 삭제·순서변경 시 C 가 B 의 세션을 물려받는
        조용한 오계정 로그인을 부른다.
      · 새 id(일치 없음) → 새 안정 키 발급(default → _2/_3, 충돌 회피).
    규칙:
      · pw == '***' 인데 **id 일치 없음** → 400(위치 추정 폴백 금지). login_id
        RENAME 은 곧 remove-old + add-new 이며, 마스킹 pw 는 재입력해야 한다.
      · pw == '***' + id 일치 → 그 계정의 기존 pw 유지.
      · 완전 빈 행(id·pw 모두 빈값) → 저장 안 함(no-op, 손실 아님).
      · id 는 있는데 pw 를 결정할 수 없음 → 400(조용한 실패 금지).
      · 들어온 리스트에 id 가 없는 기존 계정 → remove(+owner 행 제거).
        (세션/쿠키 파일 정리는 Task E 소관 — 여기서 하지 않음.)
      · owner 는 정체성으로 확정된 같은 account_key 에 묶여 절대 드리프트 X.

    ※ 정합성 주의: 이 핸들러는 검증을 먼저 끝낸 뒤 쓰기하지만, 두 스토어
      (자격증명 DB + owner 사이드 테이블)에 걸쳐 각 upsert/set_owner 가 개별
      커밋한다 — **트랜잭션이 아니다**. 검증 실패는 쓰기 전에 400 으로 반환되므로
      정상 경로에선 부분 저장이 없다. 쓰기 도중 예외(예: DB 단절)는 부분 커밋을
      남길 수 있으나 orphan owner 행은 무해하다(GET 은 자격증명 키만 순회하므로
      대응 자격증명이 없는 owner 행은 결코 노출되지 않는다).
    """
    from lemouton.auth.sourcing_credentials import default_store
    from lemouton.margin import sourcing_owner_store

    data = request.get_json(silent=True) or {}
    incoming = data.get("accounts")
    if incoming is None:
        incoming = {}
    if not isinstance(incoming, dict):
        return jsonify({"success": False, "error": "accounts 는 dict 여야 합니다."}), 400

    store = default_store()
    known = _known_source_keys()
    current_all = store.load_all()

    upserts = []   # (source, account_key, id, pw, login_method, owner)
    removes = []   # (source, account_key)

    for source, accs in incoming.items():
        if source not in known:
            return jsonify({"success": False,
                            "error": f"지원하지 않는 소싱처: {source}"}), 400
        if not isinstance(accs, list):
            return jsonify({"success": False,
                            "error": f"{source} 계정 목록은 list 여야 합니다."}), 400

        cur = current_all.get(source, {})           # {account_key: {id, pw, login_method}}
        # login_id → 기존 account_key (정체성 매핑). 세션 파일명이 이 키에 묶인다.
        key_by_id = {(c.get("id") or ""): k for k, c in cur.items()}
        used = set(cur.keys())

        # id 가 있는 실제 행만(빈 행은 무시 — 저장할 자격증명이 없음)
        real_accs = [a for a in accs if isinstance(a, dict) and (a.get("id") or "").strip()]

        kept_keys = set()
        for acc in real_accs:
            id_val = (acc.get("id") or "").strip()
            pw_in = acc.get("pw")
            method = (acc.get("login_method") or "direct").strip() or "direct"
            owner = (acc.get("owner") or "").strip()

            existing_key = key_by_id.get(id_val)   # None 이면 새 id

            # pw 결정: 마스킹이면 반드시 id 일치 계정에서 조회(위치 추정 금지).
            # (PW_MASK '***' 는 예약 sentinel — 사용자는 실제 pw 로 '***' 를 못 쓴다.)
            if pw_in == PW_MASK:
                if existing_key is None:
                    return jsonify({
                        "success": False,
                        "error": f"{source}/{id_val}: 비밀번호를 다시 입력해야 합니다 "
                                 f"— 계정 ID 가 새로 입력되었습니다.",
                    }), 400
                pw_val = (cur.get(existing_key) or {}).get("pw", "")
                if not pw_val:
                    return jsonify({
                        "success": False,
                        "error": f"{source}/{id_val}: 저장된 비밀번호가 없어 마스킹 값을 "
                                 f"복원할 수 없습니다 — 다시 입력해 주세요.",
                    }), 400
            else:
                pw_val = pw_in or ""
                if not pw_val.strip():
                    return jsonify({
                        "success": False,
                        "error": f"{source}/{id_val}: 비밀번호가 비어 있습니다.",
                    }), 400

            # account_key 배정: id 일치면 기존 키 재사용, 새 id 면 새 키 발급.
            if existing_key is not None:
                key = existing_key
            else:
                key = _mint_key(used)
                used.add(key)
            kept_keys.add(key)
            upserts.append((source, key, id_val, pw_val, method, owner))

        # 들어온 리스트에 id 가 없는(= 재사용되지 않은) 기존 계정 제거
        for key in cur.keys():
            if key not in kept_keys:
                removes.append((source, key))

    # ── 쓰기 단계 (검증 전부 통과 후 — 단, 트랜잭션 아님; docstring 참조) ──
    try:
        for source, key, id_val, pw_val, method, owner in upserts:
            store.upsert(source=source, account_key=key,
                         id_value=id_val, pw_value=pw_val, login_method=method)
            sourcing_owner_store.set_owner(source, key, owner)  # 빈 값이면 행 제거
        for source, key in removes:
            store.remove(source, key)
            sourcing_owner_store.remove_owner(source, key)
            # NOTE: 저장된 세션/쿠키 파일({source}_{account_key}) 정리는 Task E 소관.
    except ValueError as e:
        # 사전 검증을 통과했음에도 스토어가 거부 → 조용히 넘기지 않고 표면화.
        logger.warning("[api_settings] 저장 거부: %s", e)
        return jsonify({"success": False, "error": str(e)}), 400

    return jsonify({"success": True})

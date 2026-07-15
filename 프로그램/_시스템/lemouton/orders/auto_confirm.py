"""[자동전환] 「결제완료 → 배송준비중」 마켓·계정별 자동전환 엔진.

사용자 요청(2026-07-15): 각 마켓 「결제완료」 주문을 사람이 일일이 안 넘겨도
자동으로 「배송준비중」으로 넘긴다. 전체 / 마켓별 / 계정별 ON·OFF.

안전 3겹 (CLAUDE.md 🔒 3대 원칙 · 송장 전송과 동일 패턴):
  1. 기본 = 드라이런 — 실제 마켓 상태 변경 없이 "몇 건 넘어갈지"만 집계.
  2. 실전환 = LIVE 스위치(``MOUM_LIVE_CONFIRM``) + 요청 ``live=true`` 둘 다여야.
  3. 마켓별 confirm API 는 **검증된 것만** 실제 호출. 미검증 마켓은 거짓 성공 대신
     명시 실패("아직 실전환 미지원")로 표면화한다 — 조용한 성공 금지.

설정(마켓·계정별 ON/OFF)은 :class:`AutoConfirmSetting` (팀 공유 DB)에
**계정 leaf 단위로만** 저장한다. '전체'·'마켓별' 스위치는 leaf 들의
all-on/some/none 으로 파생 → 마켓/계정 스위치가 서로 다른 값을 갖는 모순을 원천 차단.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import re

from lemouton.markets import order_export as _oe
from lemouton.sourcing.models_v2 import AutoConfirmSetting

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

# 자동전환 대상 마켓 = 주문 조회가 검증된 마켓(엑셀버튼과 동일 집합).
SUPPORTED = set(_oe.SUPPORTED)   # {smartstore, lotteon, coupang, eleven11}

# 슬러그 ↔ 한글 라벨 (order_export 단일 원천 재사용)
MARKET_KO = dict(_oe._MARKET_KO)

# '결제완료(=아직 발송 준비 전)' 주문만 대상. 마켓별 표기가 달라 통일 규칙으로 판정.
#   포함: 결제완료·신규주문·신규 / 제외: 준비중·배송·취소·반품 등(이미 넘어갔거나 대상 아님).
# '완료'(단독) 는 제외어에 넣지 않는다 — '결제완료' 의 완료까지 걸려 대상이 사라진다.
#   이미 넘어간 상태는 준비중·출고·배송·취소·반품·교환·구매확정·수취·정산으로 충분히 걸린다.
_TARGET_RE = re.compile(r"결제\s*완료|신규주문|^신규|발주\s*확인\s*대기")
_EXCLUDE_RE = re.compile(r"준비중|출고|배송|취소|반품|교환|구매확정|수취|정산|발송")


def live_confirm_enabled() -> bool:
    """자동전환 실행 허용 여부 — ``MOUM_LIVE_CONFIRM`` (기본 OFF).

    가격·재고 실전송(``MOUM_LIVE_UPLOAD``)이 켜져 있으면 함께 허용(운영 편의).
    반대는 성립하지 않는다.
    """
    from lemouton.uploader.runtime import live_upload_enabled
    v = (os.environ.get("MOUM_LIVE_CONFIRM", "") or "").strip().lower()
    return v in _TRUTHY or live_upload_enabled()


def is_confirm_target(status_text: str) -> bool:
    """주문상태 문자열이 '결제완료(자동전환 대상)' 인가."""
    s = str(status_text or "")
    if _EXCLUDE_RE.search(s):
        return False
    return bool(_TARGET_RE.search(s))


def norm_alias(v) -> str:
    """계정 표시명 정규화 — 뒤 마켓 표기 괄호 제거(화면·설정·주문행 별칭 정렬)."""
    return re.sub(r"\s*\((?:쿠팡|스마트스토어|스스|롯데온|11번가|옥션|G마켓|지마켓)\)\s*$",
                  "", str(v or "")).strip()


# ──────────────────────────────────────────────────────────────
#  설정 조회·저장
# ──────────────────────────────────────────────────────────────

def _accounts_of(market: str) -> list:
    """그 마켓 활성 계정 표시명 목록(정규화). 없으면 대표 계정 1개로 폴백."""
    accs = _oe._active_accounts(market) or []
    names = [norm_alias(name) for _p, name in accs if name]
    if not names:
        names = [norm_alias(_oe._account_alias(market)) or "대표 계정"]
    # 중복 제거(순서 보존)
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _enabled_map(session) -> dict:
    """저장된 설정 → {(market, alias): row}. 켜진 것만 행이 있는 게 아니라 전부 로드."""
    out = {}
    for row in session.query(AutoConfirmSetting).all():
        out[(row.market, norm_alias(row.account_alias))] = row
    return out


def list_settings(session, markets=None) -> dict:
    """UI 용 설정 트리 — 마켓별 계정 목록 + 켜짐/이력 + LIVE 스위치.

    markets 미지정이면 SUPPORTED 전체. 계정 universe 는 판매처관리(활성 계정)에서.
    """
    mks = [m for m in (markets or sorted(SUPPORTED)) if m in SUPPORTED]
    stored = _enabled_map(session)
    out_markets = []
    for m in mks:
        accts = []
        for alias in _accounts_of(m):
            row = stored.get((m, alias))
            accts.append({
                "alias": alias,
                "enabled": bool(row.enabled) if row else False,
                "last_run_at": row.last_run_at.isoformat() if (row and row.last_run_at) else None,
                "last_run_count": (row.last_run_count if row else 0) or 0,
            })
        on = sum(1 for a in accts if a["enabled"])
        out_markets.append({
            "market": m, "label": MARKET_KO.get(m, m),
            "accounts": accts, "enabled_count": on, "total": len(accts),
        })
    return {"markets": out_markets, "live": live_confirm_enabled()}


def _upsert(session, market: str, alias: str, enabled: bool) -> None:
    alias = norm_alias(alias)
    row = session.get(AutoConfirmSetting, {"market": market, "account_alias": alias})
    if row is None:
        row = AutoConfirmSetting(market=market, account_alias=alias, enabled=enabled)
        session.add(row)
    else:
        row.enabled = enabled


def set_account(session, market: str, alias: str, enabled: bool) -> None:
    """계정 하나 토글."""
    if market not in SUPPORTED:
        raise ValueError(f"지원하지 않는 마켓: {market}")
    _upsert(session, market, alias, bool(enabled))
    session.commit()


def set_market(session, market: str, enabled: bool) -> int:
    """마켓의 모든 활성 계정을 한꺼번에 토글. 바뀐 계정 수 반환."""
    if market not in SUPPORTED:
        raise ValueError(f"지원하지 않는 마켓: {market}")
    n = 0
    for alias in _accounts_of(market):
        _upsert(session, market, alias, bool(enabled))
        n += 1
    session.commit()
    return n


def set_all(session, enabled: bool, markets=None) -> int:
    """전체(모든 마켓·계정) 토글. 바뀐 계정 수 반환."""
    mks = [m for m in (markets or sorted(SUPPORTED)) if m in SUPPORTED]
    n = 0
    for m in mks:
        for alias in _accounts_of(m):
            _upsert(session, m, alias, bool(enabled))
            n += 1
    session.commit()
    return n


def enabled_leaves(session) -> list:
    """켜진 (market, alias) 목록."""
    return [(m, a) for (m, a), row in _enabled_map(session).items()
            if row.enabled and m in SUPPORTED]


# ──────────────────────────────────────────────────────────────
#  실행 (드라이런 기본 · 실전환 게이트)
# ──────────────────────────────────────────────────────────────

def _target_rows_by_leaf(enabled, days: int, warnings: list) -> dict:
    """켜진 leaf 들에 대해 '결제완료' 주문을 조회 → {(market, alias): [rows]}.

    마켓별로 따로 조회(한 마켓 실패가 전체를 막지 않게 · 프론트와 동일 방침).
    """
    markets = sorted({m for m, _a in enabled})
    allow = set(enabled)   # (market, alias) 허용 집합
    out: dict = {}
    for m in markets:
        label = MARKET_KO.get(m, m)
        try:
            rows = _oe.combined_order_rows([m], days=days, use_cache=True,
                                           include_settlement=False)
        except Exception as e:   # noqa: BLE001 — 한 마켓 실패는 사유 남기고 건너뜀
            logger.warning("auto-confirm fetch failed market=%s: %s", m, e)
            warnings.append(f"[{label}] 주문을 불러오지 못해 건너뜀 ({type(e).__name__})")
            continue
        for r in rows:
            if not is_confirm_target(r.get("주문상태")):
                continue
            alias = norm_alias(r.get("쇼핑몰별칭"))
            if (m, alias) not in allow:
                continue
            out.setdefault((m, alias), []).append(r)
    return out


def run(session, *, live: bool = False, days: int = 7) -> dict:
    """자동전환 실행. 기본 드라이런(집계만). live=True + 서버 스위치 ON 이면 실전환 시도.

    반환: {ok, live, total, by:[{market,label,alias,count,result}], warnings}
      result: 'dryrun'(미리보기) | 'unsupported'(실전환 미지원·명시실패) | 'sent' | 'failed'
    """
    is_live = bool(live) and live_confirm_enabled()
    warnings: list = []
    enabled = enabled_leaves(session)
    if not enabled:
        return {"ok": True, "live": is_live, "total": 0, "by": [], "warnings": [],
                "note": "켜진 마켓·계정이 없어요. 먼저 자동전환을 켜세요."}

    by_leaf = _target_rows_by_leaf(enabled, days, warnings)
    by, total = [], 0
    stored = _enabled_map(session)
    for (m, alias) in enabled:
        rows = by_leaf.get((m, alias), [])
        cnt = len(rows)
        total += cnt
        if not is_live:
            result = "dryrun"
        else:
            # 실전환 경로: 마켓별 confirm API 가 검증되면 여기서 호출. 현재는 미검증 →
            # 거짓 성공 금지, 명시 실패로 표면화(LIVE 를 켜도 실제 상태는 안 바뀜).
            result = _confirm_market(m, rows)
            if result == "sent" and cnt:
                row = stored.get((m, alias))
                if row is not None:
                    row.last_run_at = _dt.datetime.now(_dt.timezone.utc)
                    row.last_run_count = cnt
        by.append({"market": m, "label": MARKET_KO.get(m, m), "alias": alias,
                   "count": cnt, "result": result})
    if is_live:
        session.commit()
    return {"ok": True, "live": is_live, "total": total, "by": by, "warnings": warnings}


def _confirm_market(market: str, rows: list) -> str:
    """마켓에 '결제완료→배송준비중' 실전환 요청.

    ⚠️ 마켓별 발주확인/상품준비중 처리 API 는 스펙 검증 후 배선한다. 현재는 미검증이므로
    **거짓 성공 대신 'unsupported'** 를 돌려준다(CLAUDE.md 🔒 — 확인 못한 걸 했다고 하지 않음).
    검증 완료 마켓부터 여기 분기를 채운다.
    """
    # TODO(스펙검증 후): coupang=상품준비중 처리 / smartstore=발주확인(dispatch) /
    #   lotteon=상품준비중 / eleven11=발송처리 준비. 각 실계정 1:1 대조 후 활성화.
    return "unsupported"

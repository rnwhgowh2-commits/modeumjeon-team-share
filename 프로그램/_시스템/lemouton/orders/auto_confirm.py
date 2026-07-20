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
import datetime as _dt2
from lemouton.sourcing.models_v2 import (AutoConfirmSetting, AutoConfirmConfig,
                                         AutoConfirmLog)

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

# 자동전환 대상 마켓 = 주문 조회가 검증된 마켓(엑셀버튼과 동일 집합).
# ★ 상수로 복사하면 안 된다 — 라이브 검증으로 마켓이 열려도 모듈 로드 시점 값에
#   묶여 영영 반영되지 않는다. 호출 시점에 order_export 에 물어본다.
def supported() -> set:
    """자동전환 대상 마켓(라이브 검증 반영). order_export.supported_markets() 단일 원천."""
    return _oe.supported_markets()

# 슬러그 ↔ 한글 라벨 (order_export 단일 원천 재사용)
MARKET_KO = dict(_oe._MARKET_KO)

# '결제완료(=아직 발송 준비 전)' 주문만 대상. 마켓별 표기가 달라 통일 규칙으로 판정.
#   포함: 결제완료·신규주문·신규 / 제외: 준비중·배송·취소·반품 등(이미 넘어갔거나 대상 아님).
# '완료'(단독) 는 제외어에 넣지 않는다 — '결제완료' 의 완료까지 걸려 대상이 사라진다.
#   이미 넘어간 상태는 준비중·출고·배송·취소·반품·교환·구매확정·수취·정산으로 충분히 걸린다.
_TARGET_RE = re.compile(r"결제\s*완료|신규주문|^신규|발주\s*확인\s*대기")
_EXCLUDE_RE = re.compile(r"준비중|출고|배송|취소|반품|교환|구매확정|수취|정산|발송")


def live_confirm_enabled() -> bool:
    """실전환 허용 여부 — 발주확인은 안전한 앞단계라 **화면 확인창이 게이트**다.

    · 수동 「지금 즉시 전환」 = 사용자가 확인창을 눌러 실행(의도적) → 실전환.
    · 자동 실행 = 화면 스위치 ON(config.enabled) 이 arming → 스케줄러가 실전환.
    비상 정지는 환경변수 ``MOUM_CONFIRM_DISABLED`` (설정 시 무조건 미리보기로 강등).
    거짓성공은 되읽기 검증이, 오작동 범위는 계정별 대상 토글이 막는다.
    """
    v = (os.environ.get("MOUM_CONFIRM_DISABLED", "") or "").strip().lower()
    return v not in _TRUTHY


# ──────────────────────────────────────────────────────────────
#  자동 실행 설정(스케줄러) — 단일 row
# ──────────────────────────────────────────────────────────────

def get_config(session) -> AutoConfirmConfig:
    row = session.get(AutoConfirmConfig, 1)
    if row is None:
        row = AutoConfirmConfig(id=1, enabled=False, interval_minutes=5)
        session.add(row)
        session.commit()
    return row


def set_config(session, *, enabled=None, interval_minutes=None) -> AutoConfirmConfig:
    row = get_config(session)
    if enabled is not None:
        row.enabled = bool(enabled)
    if interval_minutes is not None:
        try:
            iv = int(interval_minutes)
            if iv >= 1:                       # 0·음수·형식오류는 무시(이전 값 유지)
                row.interval_minutes = min(180, iv)
        except (TypeError, ValueError):
            pass
    session.commit()
    return row


def next_run_at(cfg) -> str:
    """다음 자동 실행 예정 시각(ISO) — enabled 아니면 None."""
    if not cfg.enabled:
        return None
    base = cfg.last_run_at or _dt.datetime.now(_dt.timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=_dt.timezone.utc)
    return (base + _dt.timedelta(minutes=cfg.interval_minutes)).isoformat()


def recent_logs(session, limit: int = 40) -> list:
    rows = (session.query(AutoConfirmLog)
            .order_by(AutoConfirmLog.ran_at.desc()).limit(limit).all())
    return [{"ran_at": r.ran_at.isoformat() if r.ran_at else None,
             "market": r.market, "label": MARKET_KO.get(r.market, r.market),
             "alias": r.account_alias, "count": r.count,
             "result": r.result, "source": r.source} for r in rows]


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

    markets 미지정이면 supported() 전체. 계정 universe 는 판매처관리(활성 계정)에서.
    """
    _sup = supported()
    mks = [m for m in (markets or sorted(_sup)) if m in _sup]
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
    cfg = get_config(session)
    return {"markets": out_markets, "live": live_confirm_enabled(),
            "auto": {"enabled": bool(cfg.enabled),
                     "interval_minutes": cfg.interval_minutes,
                     "last_run_at": cfg.last_run_at.isoformat() if cfg.last_run_at else None,
                     "next_run_at": next_run_at(cfg)},
            "logs": recent_logs(session, 40)}


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
    if market not in supported():
        raise ValueError(f"지원하지 않는 마켓: {market}")
    _upsert(session, market, alias, bool(enabled))
    session.commit()


def set_market(session, market: str, enabled: bool) -> int:
    """마켓의 모든 활성 계정을 한꺼번에 토글. 바뀐 계정 수 반환."""
    if market not in supported():
        raise ValueError(f"지원하지 않는 마켓: {market}")
    n = 0
    for alias in _accounts_of(market):
        _upsert(session, market, alias, bool(enabled))
        n += 1
    session.commit()
    return n


def set_all(session, enabled: bool, markets=None) -> int:
    """전체(모든 마켓·계정) 토글. 바뀐 계정 수 반환."""
    _sup = supported()
    mks = [m for m in (markets or sorted(_sup)) if m in _sup]
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
            if row.enabled and m in supported()]


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
            # warnings 채널을 넘겨야 계정 일부 실패(IP 미등록 등)에도 부분 결과를 받는다.
            # (안 넘기면 combined_order_rows 가 캐시-경고에서 RuntimeError 로 전체를 막음)
            mkwarns: list = []
            rows = _oe.combined_order_rows([m], days=days, use_cache=True,
                                           include_settlement=False, warnings=mkwarns)
            for w in mkwarns:
                warnings.append(f"[{label}] {w}")
        except Exception as e:   # noqa: BLE001 — 한 마켓 전체 실패만 사유 남기고 건너뜀
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


def run(session, *, live: bool = False, days: int = 7, limit=None,
        order_nos=None, source: str = "manual") -> dict:
    """자동전환 실행. 기본 드라이런(집계만). live=True + 비상정지 아님이면 실전환.

    limit(정수) = 계정별 최대 몇 건만 전환할지(마켓별 실주문 1건 검증용). None=제한 없음.
    order_nos(집합/목록) = 지정 시 그 오픈마켓주문번호만 대상(승인한 주문만 콕 집어 전환).
    source = 'manual'(버튼) | 'auto'(스케줄러) — 이력 기록용.
    반환: {ok, live, total, by:[{market,label,alias,count,attempted,result,error?}], warnings}
      result: 'dryrun'(미리보기) | 'sent'(전환·되읽기확인) | 'partial'(일부만 이동) |
              'failed'(요청·검증 실패) | 'unsupported'(실전환 미배선) | 'skip'(대상 0)
    """
    is_live = bool(live) and live_confirm_enabled()
    warnings: list = []
    enabled = enabled_leaves(session)
    if not enabled:
        return {"ok": True, "live": is_live, "total": 0, "by": [], "warnings": [],
                "note": "켜진 마켓·계정이 없어요. 먼저 자동전환을 켜세요."}

    lim = limit if isinstance(limit, int) and limit > 0 else None
    only = {str(o) for o in order_nos} if order_nos else None
    by_leaf = _target_rows_by_leaf(enabled, days, warnings)
    by, total = [], 0
    stored = _enabled_map(session)
    for (m, alias) in enabled:
        rows = by_leaf.get((m, alias), [])
        if only is not None:   # 승인한 주문번호만 남긴다(콕 집어 전환)
            rows = [r for r in rows if str(r.get("오픈마켓주문번호") or "") in only]
        if not is_live:
            by.append({"market": m, "label": MARKET_KO.get(m, m), "alias": alias,
                       "count": len(rows), "result": "dryrun"})
            total += len(rows)
            continue
        targets = rows[:lim] if lim else rows
        res = _confirm_leaf(m, alias, targets)
        by.append({"market": m, "label": MARKET_KO.get(m, m), "alias": alias,
                   "count": res["moved"], "attempted": len(targets),
                   "result": res["result"], "error": res.get("error")})
        total += res["moved"]
        if res["moved"] > 0:
            row = stored.get((m, alias))
            if row is not None:
                row.last_run_at = _dt.datetime.now(_dt.timezone.utc)
                row.last_run_count = res["moved"]
            # 이력 기록(타임라인) — 실제로 넘긴 것만.
            session.add(AutoConfirmLog(market=m, account_alias=alias,
                                       count=res["moved"], result=res["result"],
                                       source=source))
    if is_live:
        session.commit()
    return {"ok": True, "live": is_live, "total": total, "by": by, "warnings": warnings}


def tick(session) -> dict:
    """스케줄러 1분 틱 — 자동 실행 ON + 간격 지났으면 한 바퀴 실전환.

    ★멀티워커 안전: 간격이 지난 경우에만 last_run_at 을 원자적으로(조건부 UPDATE) 선점한다.
    여러 워커가 동시에 틱을 돌려도 UPDATE 를 성공시킨 1개 워커만 실행(중복 전환 방지).
    반환: {ran: bool, ...}.
    """
    from sqlalchemy import update
    cfg = get_config(session)
    if not cfg.enabled:
        return {"ran": False, "reason": "auto off"}
    now = _dt.datetime.now(_dt.timezone.utc)
    threshold = now - _dt.timedelta(seconds=cfg.interval_minutes * 60 - 5)
    res_upd = session.execute(
        update(AutoConfirmConfig)
        .where(AutoConfirmConfig.id == 1, AutoConfirmConfig.enabled == True)   # noqa: E712
        .where((AutoConfirmConfig.last_run_at.is_(None))
               | (AutoConfirmConfig.last_run_at < threshold))
        .values(last_run_at=now)
        .execution_options(synchronize_session=False))
    session.commit()
    if res_upd.rowcount != 1:   # 다른 워커가 이미 가져갔거나 간격 안 됨
        return {"ran": False, "reason": "interval not elapsed / taken by other worker"}
    res = run(session, live=True, source="auto")
    res["ran"] = True
    logger.info("auto-confirm tick: total=%s by=%s", res.get("total"),
                [(b["market"], b["result"], b["count"]) for b in res.get("by", [])])
    return res


def _client_for(market: str, alias: str):
    """행의 「쇼핑몰별칭」 → 그 계정의 마켓 클라이언트(별칭 정규화 매칭). 없으면 대표 계정."""
    env_prefix = None
    try:
        for prefix, name in (_oe._active_accounts(market) or []):
            if alias and norm_alias(name) == norm_alias(alias):
                env_prefix = prefix
                break
    except Exception:   # noqa: BLE001 — 계정 조회 실패는 대표 계정 폴백
        env_prefix = None
    return _oe._account_client(market, env_prefix)


def _confirm_leaf(market: str, alias: str, targets: list) -> dict:
    """한 계정의 결제완료 주문들을 배송준비중으로 전환 + 되읽기 검증.

    되읽기 검증 = 전환 후 그 마켓을 재조회해 대상 주문이 '결제완료'를 벗어났는지 확인.
    → 스펙이 틀려도 거짓 성공이 아니라 정직한 실패로 표면화(CLAUDE.md 🔒).
    """
    from lemouton.orders import confirm_api as _capi
    if not targets:
        return {"result": "skip", "moved": 0}
    cli = _client_for(market, alias)
    if cli is None:
        return {"result": "failed", "moved": 0, "error": "계정 키 미등록/불량"}
    try:
        confirmed = _capi.confirm_targets(market, targets, cli)
    except _capi.ConfirmUnsupported as e:
        return {"result": "unsupported", "moved": 0, "error": str(e)}
    except Exception as e:   # noqa: BLE001 — 전환 요청 실패는 사유와 함께 표면화
        return {"result": "failed", "moved": 0, "error": f"{type(e).__name__}: {str(e)[:250]}"}
    if confirmed is not None:
        # 마켓 API 가 개별 확정 결과를 준 경우(스스 발주확인) — 상태가 안 바뀌므로 이게 검증 신호.
        want = {str(t.get("오픈마켓주문번호") or "") for t in targets if t.get("오픈마켓주문번호")}
        moved = len(want & {str(c) for c in confirmed})
    else:
        # 상태가 바뀌는 마켓(쿠팡·롯데온) — 전환 후 재조회로 '결제완료'를 벗어났는지 독립 검증.
        moved = _readback_moved(market, targets, cli)
    if moved >= len(targets):
        result = "sent"
    elif moved > 0:
        result = "partial"
    else:
        result = "failed"
    return {"result": result, "moved": moved}


def _readback_moved(market: str, targets: list, client) -> int:
    """전환 후 재조회 — 대상 주문 중 '결제완료'를 벗어난(=이동한) 건수. 확인 실패 시 0."""
    want = {str(t.get("오픈마켓주문번호") or "") for t in targets if t.get("오픈마켓주문번호")}
    if not want:
        return 0
    try:
        rows = _oe.combined_order_rows([market], days=7, use_cache=False,
                                       include_settlement=False, warnings=[])
    except Exception:   # noqa: BLE001 — 재조회 실패 = 확인 불가 → 이동 0(거짓 성공 금지)
        return 0
    still_paid = {str(r.get("오픈마켓주문번호") or "")
                  for r in rows if is_confirm_target(r.get("주문상태"))}
    return sum(1 for o in want if o not in still_paid)

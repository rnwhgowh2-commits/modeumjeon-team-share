# -*- coding: utf-8 -*-
"""⑧ 설정 — 등급 경계·계수·하한·상한을 사장님이 직접 고친다.

설계서: 2026-07-19-크롤주기-변동주기-등급-design.md §4·§4-2
  "모든 수치는 제안값. 최종은 사장님이 화면에서 설정."
"""
from flask import jsonify, request

from shared.db import SessionLocal

from . import bp


def _payload(session):
    from lemouton.sources.crawl_grade import GRADE_NAMES, per_day_text
    from lemouton.sources.grade_config_store import get_grade_config, is_customized

    cfg = get_grade_config(session)
    grades = []
    for i, nm in enumerate(GRADE_NAMES):
        lo = cfg.boundaries[i] if i < len(cfg.boundaries) else 0.0
        hi = cfg.boundaries[i - 1] if i > 0 else None
        raw = cfg.coefficients[i]
        eff = max(cfg.floor_per_day, min(cfg.ceiling_per_day, raw))
        grades.append({
            "index": i, "name": nm,
            "lower_pct": lo, "upper_pct": hi,
            "raw_per_day": raw,
            "effective_per_day": eff,
            "effective_text": per_day_text(eff),
            "capped": eff < raw,
            "floored": raw <= cfg.floor_per_day,
        })
    return {
        "boundaries": list(cfg.boundaries),
        "coefficients": list(cfg.coefficients),
        "ceiling_per_day": cfg.ceiling_per_day,
        "floor_per_day": cfg.floor_per_day,
        "ceiling_text": per_day_text(cfg.ceiling_per_day),
        "floor_text": per_day_text(cfg.floor_per_day),
        "customized": is_customized(session),
        "grades": grades,
    }


@bp.get('/api/settings/grade')
def get_grade_settings():
    s = SessionLocal()
    try:
        return jsonify(_payload(s))
    finally:
        s.close()


@bp.post('/api/settings/grade')
def save_grade_settings():
    """전달된 항목만 갱신. 규칙 위반이면 400 과 사유 — DB 는 안 건드린다."""
    from lemouton.sources.grade_config_store import save_grade_config

    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        save_grade_config(
            s,
            boundaries=body.get('boundaries'),
            coefficients=body.get('coefficients'),
            ceiling_per_day=body.get('ceiling_per_day'),
            floor_per_day=body.get('floor_per_day'),
        )
        s.commit()
        return jsonify({"ok": True, **_payload(s)})
    except (ValueError, TypeError) as e:
        s.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


# ══ 업로드 속도 「X초에 Y개」 (2026-07-20 B) ═══════════════════════════════
#  사장님 확정: "계정별로 X초에 Y개. 마켓별로도 API 전송 고려해 수기 수정 가능."
#  저장 함수는 있었는데 **부르는 곳이 없어** 손으로 고칠 수가 없었다.

def _speed_payload(session) -> dict:
    from lemouton.markets.order_export import account_workers
    from lemouton.pricing.settings import (
        AccountUploadPolicy, MarketUploadPolicy, account_rate_window,
        get_account_policies, get_market_rate, market_effective_rate,
    )
    from lemouton.uploader.market_concurrency import market_info
    from lemouton.uploader.rate_window import text_of

    from .send import MARKET_LABELS, MARKET_ORDER

    pols = get_account_policies(session)
    session.flush()

    by_market: dict = {}
    for p in pols:
        by_market.setdefault(p["market"], []).append(p)

    markets = []
    for m in list(MARKET_ORDER) + sorted(by_market):
        if any(x["market"] == m for x in markets):
            continue
        accs = by_market.get(m, [])
        mk = get_market_rate(session, m)
        eff = market_effective_rate(session, m)
        info = market_info(m)
        markets.append({
            "market": m,
            "label": MARKET_LABELS.get(m, m),
            # 마켓 API 한도 — 비어 있으면 '미확인'
            "market_limit": ({"window_seconds": mk.window_seconds,
                              "max_count": mk.max_count,
                              "text": text_of(mk)} if mk else None),
            # 한도 적용 범위 — 'account'(계정당 천장·계정 수만큼 총량↑) / 'shared'(마켓 전체로 묶임)
            "limit_scope": getattr(
                session.get(MarketUploadPolicy, m), "limit_scope", "shared") or "shared",
            # 실제로 나갈 속도 (계정 합산 ∧ 마켓 한도)
            "effective": {"per_second": round(eff["per_second"], 3),
                          "bound_by": eff["bound_by"]},
            "concurrency_note": info["concurrency_note"],
            "must_be_sequential": info["must_be_sequential"],
            "account_workers": account_workers(m),
            "accounts": [{
                "account_id": a["account_id"],
                "name": a["account_name"],
                "enabled": a["enabled"],
                **(lambda rw: {"window_seconds": rw.window_seconds,
                               "max_count": rw.max_count,
                               "text": text_of(rw)})(
                    account_rate_window(session.get(AccountUploadPolicy,
                                                    a["account_id"]))),
            } for a in accs],
        })
    return {"markets": markets}


@bp.get('/api/settings/speed')
def get_speed_settings():
    s = SessionLocal()
    try:
        d = _speed_payload(s)
        s.commit()      # get_account_policies 가 기본 정책을 시드할 수 있다
        return jsonify(d)
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"error": "speed_load_failed", "detail": str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/settings/speed')
def save_speed_settings():
    """마켓 한도 또는 계정 속도를 「X초에 Y개」로 저장.

    body: {"market": "coupang", "window_seconds": 1, "max_count": 5}
       또는 {"account_id": 3, "window_seconds": 1, "max_count": 2}

    ★ 둘 다 오면 거부한다 — 어느 쪽을 고쳤는지 모호하면 안 된다.
    """
    from lemouton.pricing.settings import set_account_rate, set_market_rate
    from lemouton.sourcing.models_v2 import UploadAccount

    body = request.get_json(silent=True) or {}
    market, acc_id = body.get('market'), body.get('account_id')
    if bool(market) == (acc_id is not None):
        return jsonify({"ok": False,
                        "error": "market 또는 account_id 중 하나만 보내주세요."}), 400

    # ★ 마켓 한도를 **비우면 「미확인」으로 되돌린다.**
    #   이게 없으면 한 번 넣은 숫자를 영영 못 지운다 — 나중에 그 값이
    #   공식 문서에서 확인된 값인 줄 알고 쓰게 된다(추정치 금지 원칙).
    #   계정 속도에는 '미확인'이 없다(항상 기본값이 있음) → 마켓만 허용.
    blank = (body.get('window_seconds') in (None, "")
             or body.get('max_count') in (None, ""))
    if blank and market:
        s = SessionLocal()
        try:
            from lemouton.pricing.settings import clear_market_rate
            clear_market_rate(s, market)
            d = _speed_payload(s)
            s.commit()
            return jsonify({"ok": True, **d})
        except Exception as e:      # noqa: BLE001
            s.rollback()
            return jsonify({"ok": False, "error": str(e)[:300]}), 500
        finally:
            s.close()

    try:
        window = int(body.get('window_seconds'))
        count = int(body.get('max_count'))
    except (TypeError, ValueError):
        return jsonify({"ok": False,
                        "error": "window_seconds·max_count 는 정수여야 합니다."}), 400

    s = SessionLocal()
    try:
        if market:
            set_market_rate(s, market, window_seconds=window, max_count=count,
                            note=body.get('note') or "화면에서 직접 설정")
        else:
            if s.get(UploadAccount, int(acc_id)) is None:
                return jsonify({"ok": False, "error": "계정 없음"}), 404
            set_account_rate(s, int(acc_id), window_seconds=window, max_count=count)
        d = _speed_payload(s)
        s.commit()
        return jsonify({"ok": True, **d})
    except (ValueError, TypeError) as e:
        s.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/settings/grade/reset')
def reset_grade_settings():
    from lemouton.sources.grade_config_store import reset_grade_config

    s = SessionLocal()
    try:
        reset_grade_config(s)
        s.commit()
        return jsonify({"ok": True, **_payload(s)})
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()

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

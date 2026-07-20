# -*- coding: utf-8 -*-
"""① 데이터수집 — 구성(소싱처 × 브랜드)별 변동 주기와 계수 제안.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §6
시안: 바탕화면/모음전 시안 12 — ① 데이터수집 C안(좌우 2단)

★ 여기는 **읽기 전용**이다. 계수를 자동으로 바꾸지 않는다 —
  사장님 결정 5-B: 제안 목록 → 확인 → 적용.
"""
from flask import jsonify, request

from shared.db import SessionLocal

from . import bp


@bp.post('/api/collect/apply')
def collect_apply():
    """계수 제안을 실제 규칙으로 적용 (사장님 결정 5-B: 확인 후 적용).

    dry_run=True(기본)면 **저장하지 않고** 「누르면 무엇이 어떻게 바뀌나」만 돌려준다.
    화면이 경고를 보여주고, 사람이 다시 눌러야 실제로 저장된다.
    """
    from lemouton.sources.grade_apply import apply_plan, brands_by_source, plan_apply

    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        plan = plan_apply(
            source_key=body.get('source_key') or '',
            brand=body.get('brand') or '',
            proposed_weight=body.get('weight'),
            brands_by_source=brands_by_source(s),
        )
        if body.get('dry_run', True):
            return jsonify({"ok": True, "applied": False, **plan.to_dict()})
        saved = apply_plan(s, plan)
        s.commit()
        return jsonify({"ok": True, "applied": True, "saved_weight": saved,
                        **plan.to_dict()})
    except (ValueError, TypeError) as e:
        s.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


@bp.get('/api/collect/grades')
def collect_grades():
    """구성별 등급·제안계수. 대량등록 ① 데이터수집 탭이 읽는다."""
    from lemouton.sources.crawl_grade_service import composition_grades

    try:
        laps = max(1, min(200, int(request.args.get('laps', 10))))
    except (TypeError, ValueError):
        laps = 10
    try:
        window = max(1, min(365, int(request.args.get('days', 30))))
    except (TypeError, ValueError):
        window = 30

    s = SessionLocal()
    try:
        return jsonify(composition_grades(s, laps=laps, window_days=window))
    except Exception as e:      # noqa: BLE001
        # 조용한 빈 화면 금지 — 화면이 '데이터 없음'과 '터짐'을 구분할 수 있어야 한다.
        return jsonify({"error": "grades_failed", "detail": str(e)[:300]}), 500
    finally:
        s.close()

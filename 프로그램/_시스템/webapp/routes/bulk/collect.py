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

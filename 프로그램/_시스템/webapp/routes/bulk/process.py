# -*- coding: utf-8 -*-
"""② 데이터가공 — 가공정책 목록·상세 (E안: URL 이 주인공).

설계서: 2026-07-17-신규상품등록-가공템플릿-design.md §7 · 시안 13 Ⅲ-E안
사장님 확정: "E + 선택하면 상세페이지로 이동하여 편집 + 검색/필터 + 정책 추가 버튼(A안)"

★ E안을 고른 이유 — **정책이 안 붙은 URL 이 눈에 띈다.**
  정책 중심 화면에서는 「크롤은 되는데 어디에도 안 올라가는 URL」이 안 보인다.
"""
from flask import jsonify, render_template, request

from shared.db import SessionLocal

from . import bp


def _crawled_compositions(session):
    """지금 크롤 중인 구성 목록 (소싱처, 브랜드) — 정책 미적용을 가려내는 기준."""
    from lemouton.sources.models import CrawlChangeStat
    rows = (session.query(CrawlChangeStat.source_key, CrawlChangeStat.brand)
            .distinct().all())
    return [(r[0], r[1]) for r in rows if r[0]]


@bp.get('/api/process/policies')
def process_policies():
    """정책 목록 + URL별 매핑 + 미적용 URL. ② 데이터가공 탭이 읽는다."""
    from lemouton.registration.process_policy import (
        ITEM_LABELS, ProcessPolicy, unassigned_sources,
    )

    q = (request.args.get('q') or '').strip().lower()
    only = (request.args.get('only') or '').strip()   # '' | 'unassigned'

    s = SessionLocal()
    try:
        policies = (s.query(ProcessPolicy)
                    .filter(ProcessPolicy.deleted_at.is_(None))
                    .order_by(ProcessPolicy.name.asc()).all())

        # URL(구성) 한 줄 = 화면의 주인공
        rows = []
        for p in policies:
            markets = [{"market": m.market, "account_key": m.account_key}
                       for m in p.markets]
            rule_keys = sorted({r.item_key for r in p.rules})
            for srcrow in p.sources:
                rows.append({
                    "source_key": srcrow.source_key,
                    "brand": srcrow.brand,
                    "url": srcrow.url,
                    "policy_id": p.id,
                    "policy_name": p.name,
                    "markets": markets,
                    "rule_count": len(rule_keys),
                })

        crawled = _crawled_compositions(s)
        for sk, br in unassigned_sources(s, crawled):
            rows.append({
                "source_key": sk, "brand": br, "url": None,
                "policy_id": None, "policy_name": None,
                "markets": [], "rule_count": 0,
            })

        if only == 'unassigned':
            rows = [r for r in rows if r["policy_id"] is None]
        if q:
            rows = [r for r in rows
                    if q in (r["source_key"] or '').lower()
                    or q in (r["brand"] or '').lower()
                    or q in (r["policy_name"] or '').lower()]

        # 정책 없는 것을 맨 위로 — 누락이 먼저 보여야 한다.
        rows.sort(key=lambda r: (r["policy_id"] is not None,
                                 r["source_key"] or '', r["brand"] or ''))

        return jsonify({
            "rows": rows,
            "policies": [{"id": p.id, "name": p.name,
                          "source_count": len(p.sources),
                          "market_count": len(p.markets),
                          "rule_count": len(p.rules)} for p in policies],
            "item_labels": ITEM_LABELS,
            "counts": {
                "total": len(rows),
                "unassigned": sum(1 for r in rows if r["policy_id"] is None),
            },
        })
    except Exception as e:      # noqa: BLE001
        return jsonify({"error": "policies_failed", "detail": str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/process/policies')
def create_process_policy():
    """정책 추가 (A안 버튼)."""
    from lemouton.registration.process_policy import create_policy

    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        p = create_policy(s, name=body.get('name') or '',
                          description=body.get('description') or '')
        s.commit()
        return jsonify({"ok": True, "id": p.id, "name": p.name}), 201
    except ValueError as e:
        s.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


@bp.get('/api/process/schema')
def process_schema():
    """가공 규칙 13항목 스키마 — 화면이 이걸로 폼을 그린다(설계서 §7 정본)."""
    from lemouton.registration.process_rule_schema import all_schemas
    return jsonify({"items": all_schemas()})


@bp.get('/api/process/policies/<int:policy_id>/rules')
def get_policy_rules(policy_id: int):
    """그 마켓에 실제로 적용될 규칙 한 벌 (공통 + 마켓별 덮어쓰기)."""
    from lemouton.registration.process_policy import ProcessPolicy, rules_for
    from lemouton.registration.process_rule_schema import default_config

    market = (request.args.get('market') or '').strip()
    s = SessionLocal()
    try:
        p = s.get(ProcessPolicy, policy_id)
        if not p or p.deleted_at:
            return jsonify({"ok": False, "error": "없는 정책입니다."}), 404
        saved = rules_for(s, policy_id=policy_id, market=market)
        # 저장 안 된 항목은 기본값으로 채워 화면이 늘 13칸을 그리게 한다.
        from lemouton.registration.process_policy import ITEM_KEYS
        merged = {k: (saved.get(k) or default_config(k)) for k in ITEM_KEYS}
        return jsonify({"ok": True, "market": market, "rules": merged,
                        "saved_keys": sorted(saved)})
    finally:
        s.close()


@bp.post('/api/process/policies/<int:policy_id>/rules')
def save_policy_rule(policy_id: int):
    """항목 규칙 저장. market='' 이면 모든 마켓 공통.

    ★ 검사·정리는 서버 :func:`validate_config` **한 벌**이 한다(화면은 안 한다).
      정리하면서 손댄 내용(빈 줄 제거·앞뒤 공백·같은 말 중복)은 `notices` 로 돌려줘
      화면이 그대로 띄운다 — 사장님이 넣은 값을 몰래 고치면 안 되기 때문이다.
    """
    from lemouton.registration.process_policy import set_rule
    from lemouton.registration.process_rule_schema import validate_config

    body = request.get_json(silent=True) or {}
    item_key = (body.get('item_key') or '').strip()
    notices = []
    s = SessionLocal()
    try:
        config = validate_config(item_key, body.get('config') or {}, notices=notices)
        r = set_rule(s, policy_id=policy_id, item_key=item_key, config=config,
                     market=(body.get('market') or '').strip())
        s.commit()
        return jsonify({"ok": True, "item_key": r.item_key, "market": r.market,
                        "config": r.config, "notices": notices})
    except (ValueError, TypeError) as e:
        s.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


@bp.get('/process/policy/<int:policy_id>')
def process_policy_detail(policy_id: int):
    """정책 상세 편집 페이지 — 목록에서 고르면 여기로 온다."""
    from lemouton.registration.process_policy import ITEM_LABELS, ProcessPolicy

    s = SessionLocal()
    try:
        p = s.get(ProcessPolicy, policy_id)
        if not p or p.deleted_at:
            return render_template('bulk/policy_detail.html',
                                   policy=None, item_labels=ITEM_LABELS), 404
        return render_template('bulk/policy_detail.html',
                               policy=p, item_labels=ITEM_LABELS)
    finally:
        s.close()

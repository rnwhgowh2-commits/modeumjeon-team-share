# -*- coding: utf-8 -*-
"""② 데이터가공 — 가공정책 목록·상세 (E안: URL 이 주인공).

설계서: 2026-07-17-신규상품등록-가공템플릿-design.md §7 · 시안 13 Ⅲ-E안
사장님 확정: "E + 선택하면 상세페이지로 이동하여 편집 + 검색/필터 + 정책 추가 버튼(A안)"

★ E안을 고른 이유 — **정책이 안 붙은 URL 이 눈에 띈다.**
  정책 중심 화면에서는 「크롤은 되는데 어디에도 안 올라가는 URL」이 안 보인다.
"""
from flask import jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal

from . import bp


def _crawled_compositions(session):
    """지금 크롤 중인 구성 목록 (소싱처, 브랜드) — 정책 미적용을 가려내는 기준."""
    from lemouton.sources.models import CrawlChangeStat
    rows = (session.query(CrawlChangeStat.source_key, CrawlChangeStat.brand)
            .distinct().all())
    return [(r[0], r[1]) for r in rows if r[0]]


def _live_policy(session, policy_id: int):
    """살아 있는 정책. 없거나 지워졌으면 None.

    🔴 [2026-07-24] 이 검사가 없어서 **없는 정책 id 로도 200 이 나고** 주인 없는
      규칙 행(고아)이 DB 에 남았다. 정책에 무언가를 붙이거나 저장하는 라우트는
      전부 여기를 먼저 지난다 — 판정은 한 곳에서만 한다.
    """
    from lemouton.registration.process_policy import ProcessPolicy
    p = session.get(ProcessPolicy, policy_id)
    if not p or p.deleted_at:
        return None
    return p


def _no_policy():
    return jsonify({"ok": False,
                    "error": "없는 정책입니다 — 지워졌거나 주소가 잘못됐습니다."}), 404


def _label(market: str) -> str:
    """사장님이 읽는 이름 — 안내 문구에 'coupang' 이 아니라 '쿠팡' 이 뜨게."""
    from .send import MARKET_LABELS
    return MARKET_LABELS.get(market, market)


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
            # label = 사장님이 읽는 이름. 상세 화면과 **같은 말**을 쓰려고 서버가 싣는다
            # (목록만 'coupang' 이고 상세는 '쿠팡' 이면 같은 것을 다르게 부르는 셈이다).
            markets = [{"market": m.market, "label": _label(m.market),
                        "account_key": m.account_key}
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


# ── 소싱처 붙이기·떼기 ─────────────────────────────────────────
#   화면이 「아래 빨간 줄을 정책에 붙여주세요」라고 안내하면서 정작 붙이는 수단이
#   없었다. 사장님이 할 수 없는 일을 시키면 안 된다.

@bp.post('/api/process/policies/<int:policy_id>/sources')
def attach_policy_source(policy_id: int):
    """정책에 소싱처 구성(소싱처 × 브랜드)을 붙인다.

    body: `{source_key, brand, url?, confirm_move?}`

    🔴 **한 구성은 한 정책에만** — 이미 다른 정책에 붙어 있으면 **409 + 되묻기**다.
      두 정책을 따르면 가공 결과가 실행 순서에 따라 달라진다. 사장님이
      `confirm_move` 로 「옮기겠다」고 답한 뒤에만 옮기고, 옮겼으면 **어디서
      왔는지**를 응답에 실어 화면이 알린다(조용한 이동 금지).
    """
    from lemouton.registration.process_policy import (
        PolicyConflict, attach_source, move_source,
    )

    body = request.get_json(silent=True) or {}
    source_key = (body.get('source_key') or '').strip()
    brand = (body.get('brand') or '').strip()
    url = (body.get('url') or '').strip()
    confirm = bool(body.get('confirm_move'))

    if not source_key or not brand:
        return jsonify({"ok": False,
                        "error": "소싱처와 브랜드를 둘 다 알려주세요 — "
                                 "가공정책은 「소싱처 × 브랜드」 단위로 붙습니다."}), 400

    s = SessionLocal()
    try:
        p = _live_policy(s, policy_id)
        if p is None:
            return _no_policy()
        moved_from = None
        if confirm:
            _, moved_from = move_source(s, policy_id=policy_id,
                                        source_key=source_key, brand=brand, url=url)
        else:
            try:
                attach_source(s, policy_id=policy_id, source_key=source_key,
                              brand=brand, url=url)
            except PolicyConflict as e:
                s.rollback()
                cur = _current_policy_of(source_key, brand)
                return jsonify({
                    "ok": False, "need_confirm": True,
                    "current_policy": cur,
                    "error": str(e),
                }), 409
        s.commit()
        msg = (f"정책 「{moved_from}」 에서 「{p.name}」 로 옮겼습니다."
               if moved_from else f"정책 「{p.name}」 에 붙였습니다.")
        return jsonify({"ok": True, "policy_id": policy_id, "policy_name": p.name,
                        "moved_from": moved_from, "message": msg})
    except IntegrityError:
        # 같은 구성을 두 사람이 동시에 붙이면 UNIQUE(source_key, brand) 에 걸린다.
        # ★ 이걸 500 으로 흘리면 SQL 원문이 사장님 화면에 뜬다 — 사람 말로 바꾼다.
        s.rollback()
        cur = _current_policy_of(source_key, brand)
        return jsonify({
            "ok": False, "need_confirm": True, "current_policy": cur,
            "error": f"방금 다른 곳에서 이 구성을 정책 "
                     f"「{(cur or {}).get('name', '')}」 에 붙였습니다 — "
                     f"화면을 새로 고친 뒤 다시 해주세요.",
        }), 409
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


def _current_policy_of(source_key: str, brand: str):
    """그 구성이 지금 붙어 있는 정책 {id, name}. 없으면 None.

    ★ 충돌 응답을 만들려고 **새 세션**으로 다시 읽는다 — 충돌이 난 세션은
      rollback 된 뒤라 그 안에서 읽으면 값이 불안정하다.
    """
    from lemouton.registration.process_policy import policy_for_source
    s = SessionLocal()
    try:
        p = policy_for_source(s, source_key=source_key, brand=brand)
        return {"id": p.id, "name": p.name} if p else None
    finally:
        s.close()


@bp.delete('/api/process/sources')
def detach_policy_source():
    """구성을 정책에서 뗀다. body: `{source_key, brand}`.

    구성은 **테이블 전체에서 유일**해서(한 구성 = 한 정책) 정책 id 없이도 특정된다.
    """
    from lemouton.registration.process_policy import detach_source

    body = request.get_json(silent=True) or {}
    source_key = (body.get('source_key') or '').strip()
    brand = (body.get('brand') or '').strip()
    if not source_key or not brand:
        return jsonify({"ok": False, "error": "소싱처와 브랜드를 알려주세요."}), 400

    s = SessionLocal()
    try:
        row = _source_row(s, source_key, brand)
        if row is None:
            return jsonify({"ok": False,
                            "error": f"「{source_key} > {brand}」 은(는) 어느 정책에도 "
                                     f"붙어 있지 않습니다."}), 404
        lost_url = row.url or ''
        was = row.policy.name if row.policy else ''
        detach_source(s, source_key=source_key, brand=brand)
        s.commit()
        msg = (f"「{source_key} > {brand}」 을(를) 정책 「{was}」 에서 뗐습니다 "
               f"— 이제 어디에도 올라가지 않습니다.")
        if lost_url:
            msg += f" 저장돼 있던 주소도 같이 지워졌습니다: {lost_url}"
        return jsonify({"ok": True, "policy_name": was, "url": lost_url,
                        "message": msg})
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


def _source_row(session, source_key: str, brand: str):
    """구성 행 하나 (없으면 None). 뗄 때 **무엇이 사라지는지** 먼저 읽으려고 쓴다."""
    from lemouton.registration.process_policy import ProcessPolicySource
    return (session.query(ProcessPolicySource)
            .filter(ProcessPolicySource.source_key == source_key,
                    ProcessPolicySource.brand == brand).first())


@bp.get('/api/process/sources')
def peek_policy_source():
    """이 구성이 지금 어디에 붙어 있고 **떼면 무엇을 잃는지** — 되묻기 전에 읽는다.

    🔴 [리뷰 중요②] 떼기는 행을 통째로 지운다(URL 포함). 화면이 그걸 모르고 물으면
      「무엇을 잃는지 모르고 예」가 된다. 확인 문구의 내용도 **서버가 쥔 사실 하나**
      에서 나오게 한다 — 화면이 자체 규칙을 세우지 않는다.
    """
    source_key = (request.args.get('source_key') or '').strip()
    brand = (request.args.get('brand') or '').strip()
    if not source_key or not brand:
        return jsonify({"ok": False, "error": "소싱처와 브랜드를 알려주세요."}), 400
    s = SessionLocal()
    try:
        row = _source_row(s, source_key, brand)
        if row is None:
            return jsonify({"ok": False,
                            "error": f"「{source_key} > {brand}」 은(는) 어느 정책에도 "
                                     f"붙어 있지 않습니다."}), 404
        return jsonify({"ok": True, "policy_id": row.policy_id,
                        "policy_name": row.policy.name if row.policy else '',
                        "url": row.url or ''})
    finally:
        s.close()


# ── 마켓 붙이기·떼기 ───────────────────────────────────────────

@bp.post('/api/process/policies/<int:policy_id>/markets')
def attach_policy_market(policy_id: int):
    """정책이 내보낼 판매처 마켓을 붙인다. body: `{market, account_key?}`.

    ★ 우리가 올릴 수 있는 6마켓만 받는다. 모르는 값은 **조용히 저장하지 않고**
      400 + 사유 — 오타로 만든 'coupng' 이 저장되면 「왜 안 올라가지」로 헤맨다.
    """
    from lemouton.registration.process_policy import attach_market
    from lemouton.registration.service import MARKETS

    body = request.get_json(silent=True) or {}
    market = (body.get('market') or '').strip()
    account_key = (body.get('account_key') or '').strip()

    if market not in MARKETS:
        return jsonify({"ok": False,
                        "error": f"모르는 마켓입니다: {market!r} — "
                                 f"쓸 수 있는 마켓: {', '.join(MARKETS)}"}), 400

    s = SessionLocal()
    try:
        p = _live_policy(s, policy_id)
        if p is None:
            return _no_policy()
        attach_market(s, policy_id=policy_id, market=market, account_key=account_key)
        s.commit()
        where = f"{_label(market)}{' · ' + account_key if account_key else ''}"
        return jsonify({"ok": True, "market": market, "account_key": account_key,
                        "message": f"「{where}」 로 내보내도록 붙였습니다."})
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()


@bp.delete('/api/process/policies/<int:policy_id>/markets')
def detach_policy_market(policy_id: int):
    """정책에서 마켓을 뗀다. body: `{market, account_key?}` (계정까지 같아야 뗀다)."""
    from lemouton.registration.process_policy import detach_market
    from lemouton.registration.service import MARKETS

    body = request.get_json(silent=True) or {}
    market = (body.get('market') or '').strip()
    account_key = (body.get('account_key') or '').strip()

    # 붙일 때와 **같은 목록**으로 본다 — 빈 값이면 「「」 은(는)…」 같은 이름 빈 안내가 뜬다.
    if market not in MARKETS:
        return jsonify({"ok": False,
                        "error": f"모르는 마켓입니다: {market!r} — "
                                 f"쓸 수 있는 마켓: {', '.join(MARKETS)}"}), 400

    s = SessionLocal()
    try:
        if _live_policy(s, policy_id) is None:
            return _no_policy()
        if not detach_market(s, policy_id=policy_id, market=market,
                             account_key=account_key):
            return jsonify({"ok": False,
                            "error": f"「{_label(market)}」 은(는) 이 정책에 붙어 있지 "
                                     f"않습니다."}), 404
        s.commit()
        return jsonify({"ok": True,
                        "message": f"「{_label(market)}」 을(를) 뗐습니다 — "
                                   f"이제 이 마켓으로는 안 올라갑니다."})
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
    """그 마켓에 실제로 적용될 규칙 한 벌 (공통 + 마켓별 덮어쓰기).

    ★ `market_saved_keys` = **이 마켓 전용으로 굳어 있는** 항목들.
      덮어쓰기는 항목 단위라, 한 번 마켓 전용으로 저장하면 그 항목은 공통을
      아무리 고쳐도 이 마켓에 안 닿는다. 화면이 배지로 알려 줘야
      「공통 치환표를 고쳤는데 쿠팡만 옛 표로 나간다」를 막는다.
    """
    from lemouton.registration.process_policy import ProcessRule, rules_for
    from lemouton.registration.process_rule_schema import default_config

    market = (request.args.get('market') or '').strip()
    s = SessionLocal()
    try:
        # 「살아 있는 정책인가」 판정은 _live_policy 한 곳 — 손검사 사본을 두지 않는다.
        if _live_policy(s, policy_id) is None:
            return _no_policy()
        saved = rules_for(s, policy_id=policy_id, market=market)
        # 저장 안 된 항목은 기본값으로 채워 화면이 늘 13칸을 그리게 한다.
        from lemouton.registration.process_policy import ITEM_KEYS
        merged = {k: (saved.get(k) or default_config(k)) for k in ITEM_KEYS}
        market_keys = []
        if market:
            market_keys = sorted(
                r.item_key for r in s.query(ProcessRule).filter(
                    ProcessRule.policy_id == policy_id,
                    ProcessRule.market == market).all())
        return jsonify({"ok": True, "market": market, "rules": merged,
                        "saved_keys": sorted(saved),
                        "market_saved_keys": market_keys})
    finally:
        s.close()


@bp.post('/api/process/policies/<int:policy_id>/rules')
def save_policy_rule(policy_id: int):
    """항목 규칙 저장. market='' 이면 모든 마켓 공통.

    ★ 검사·정리는 서버 :func:`validate_config` **한 벌**이 한다(화면은 안 한다).
      정리하면서 손댄 내용(빈 줄 제거·앞뒤 공백·같은 말 중복)은 `notices` 로 돌려줘
      화면이 그대로 띄운다 — 사장님이 넣은 값을 몰래 고치면 안 되기 때문이다.

    🔴 [2026-07-24] **정책 존재 검사가 없었다.** 없는 정책 id 로 불러도 200 이 나고
      주인 없는 규칙 행이 DB 에 남았다(조회는 이미 404 를 내는데 저장만 뚫려 있었다).
      :func:`_live_policy` 로 먼저 막는다.
    """
    from lemouton.registration.process_policy import set_rule
    from lemouton.registration.process_rule_schema import validate_config

    body = request.get_json(silent=True) or {}
    item_key = (body.get('item_key') or '').strip()
    notices = []
    s = SessionLocal()
    try:
        if _live_policy(s, policy_id) is None:
            return _no_policy()
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
    """정책 상세 편집 페이지 — 목록에서 고르면 여기로 온다.

    `market_choices` = 화면의 마켓 드롭다운. **고를 수 있는 값과 서버가 받는 값이
    같은 목록에서 나와야** 「골랐는데 400」이 안 난다(서버 판정은 여전히 서버가 한다).
    """
    from lemouton.registration.process_policy import ITEM_LABELS
    from lemouton.registration.service import MARKETS

    from .send import MARKET_LABELS, MARKET_ORDER

    choices = [{"key": m, "label": MARKET_LABELS.get(m, m)}
               for m in MARKET_ORDER if m in MARKETS]
    s = SessionLocal()
    try:
        p = _live_policy(s, policy_id)      # 판정은 _live_policy 한 곳
        if p is None:
            return render_template('bulk/policy_detail.html', policy=None,
                                   item_labels=ITEM_LABELS,
                                   market_choices=choices,
                                   market_labels=MARKET_LABELS), 404
        return render_template('bulk/policy_detail.html', policy=p,
                               item_labels=ITEM_LABELS,
                               market_choices=choices,
                               market_labels=MARKET_LABELS)
    finally:
        s.close()

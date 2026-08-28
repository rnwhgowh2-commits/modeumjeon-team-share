# -*- coding: utf-8 -*-
"""0층 상품명 규칙 세트 창구 (2026-08-24 Phase 3).

■ 왜 정책 밖에 두나
  규칙 한 벌을 **여러 정책이 참조**한다. 정책이 값을 복사해 갖고 있으면 규칙을
  고쳐도 옛 정책은 옛 값 그대로다 — 삼바가 별도 저장소를 둔 이유가 이것이다.

■ 🔴 미리보기는 **전송과 같은 엔진**(`process_apply.apply_rules`)을 쓴다.
  여기서 다시 조립하면 화면이 「이렇게 나갑니다」라고 해 놓고 실제로 다른 이름이
  나간다. 그러면 사장님은 틀린 걸 확인할 방법이 없다.

■ 이 파일은 `policy.py` 의 블루프린트에 얹힌다 — 화면·주소 체계가 같은 묶음이라
  따로 등록하지 않는다(`policy.py` 맨 끝에서 불러온다).
"""
from __future__ import annotations

import logging

from flask import jsonify, request

from shared.db import SessionLocal
from webapp.routes.policy import bp

_log = logging.getLogger(__name__)


@bp.get('/api/name-rules/tokens')
def api_name_rule_tokens():
    """화면이 단추를 그릴 근거 — **실제로 붙는 조각만** 준다."""
    from lemouton.policy.name_rules import TOKENS
    return jsonify({'ok': True, 'tokens': [dict(t) for t in TOKENS]})


@bp.get('/api/name-rules')
def api_name_rules():
    from lemouton.policy.name_rules import list_rules
    s = SessionLocal()
    try:
        return jsonify({'ok': True, 'rules': [
            {'id': r.id, 'name': r.name,
             'token_order': list(r.token_order or []),
             'replacements': list(r.replacements or []),
             'market_overrides': dict(r.market_overrides or {}),
             'max_len_mode': r.max_len_mode or 'byte'}
            for r in list_rules(s)]})
    finally:
        s.close()


def _read_rule_body(body, *, 기존=None):
    """저장 전 검사. `(값, 오류메시지)` — 오류가 있으면 값은 None."""
    from lemouton.policy.name_rules import normalize_order

    이름 = str(body.get('name', getattr(기존, 'name', '')) or '').strip()
    if not 이름:
        return None, '규칙 이름을 적어 주세요 — 정책에서 고를 때 이 이름으로 찾습니다.'

    if 'token_order' in body:
        순서 = normalize_order(body.get('token_order'))
    else:
        순서 = list(getattr(기존, 'token_order', None) or [])
    # 🔴 빈 조립 순서를 저장하면 이 규칙을 쓰는 정책의 **상품명이 통째로 사라진다.**
    if not 순서:
        return None, ('조립 순서가 비었습니다 — 조각을 하나 이상 넣어 주세요. '
                      '비워 두면 이 규칙을 쓰는 상품의 이름이 통째로 사라집니다.')

    치환 = body.get('replacements', getattr(기존, 'replacements', None))
    치환 = [dict(x) for x in (치환 or []) if isinstance(x, dict)]
    개별 = body.get('market_overrides', getattr(기존, 'market_overrides', None))
    개별 = dict(개별 or {})
    모드 = str(body.get('max_len_mode',
                       getattr(기존, 'max_len_mode', 'byte')) or 'byte')
    if 모드 not in ('byte', 'char', 'both'):
        return None, f'길이 재는 법이 이상합니다: {모드}'
    return ({'name': 이름, 'token_order': 순서, 'replacements': 치환,
             'market_overrides': 개별, 'max_len_mode': 모드}, None)


@bp.post('/api/name-rules')
def api_create_name_rule():
    from lemouton.policy.models import NameRule
    body = request.get_json(silent=True) or {}
    값, 오류 = _read_rule_body(body)
    if 오류:
        return jsonify({'ok': False, 'message': 오류}), 400
    s = SessionLocal()
    try:
        r = NameRule(**값)
        s.add(r)
        s.commit()
        return jsonify({'ok': True, 'id': r.id, 'name': r.name})
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[상품명규칙] 생성 실패')
        return jsonify({'ok': False, 'message': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/name-rules/<int:rid>')
def api_update_name_rule(rid: int):
    from lemouton.policy.models import NameRule
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        r = s.get(NameRule, rid)
        if r is None:
            return jsonify({'ok': False, 'message': '그 규칙이 없어요.'}), 404
        값, 오류 = _read_rule_body(body, 기존=r)
        if 오류:
            return jsonify({'ok': False, 'message': 오류}), 400
        for k, v in 값.items():
            setattr(r, k, v)
        s.commit()
        return jsonify({'ok': True, 'id': r.id})
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[상품명규칙] 수정 실패 rid=%s', rid)
        return jsonify({'ok': False, 'message': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/name-rule')
def api_set_policy_name_rule(pid: int):
    """정책에 규칙을 붙이거나(id) 뗀다(null).

    뗀 상태(NULL)가 정상이다 — 규칙을 안 고른 정책은 지금까지처럼 정책 값을 쓴다.
    """
    from lemouton.policy.models import MarketPolicy, NameRule
    body = request.get_json(silent=True) or {}
    rid = body.get('name_rule_id')
    s = SessionLocal()
    try:
        p = s.get(MarketPolicy, pid)
        if p is None:
            return jsonify({'ok': False, 'message': '그 정책이 없어요.'}), 404
        if rid in (None, '', 0):
            p.name_rule_id = None
        else:
            # 🔴 없는 규칙을 붙이면 화면엔 걸린 것처럼 보이는데 아무것도 안 먹는다.
            if s.get(NameRule, int(rid)) is None:
                return jsonify({'ok': False,
                                'message': '그 규칙이 없어요 — 지워졌을 수 있습니다.'}), 400
            p.name_rule_id = int(rid)
        s.commit()
        return jsonify({'ok': True, 'name_rule_id': p.name_rule_id})
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[상품명규칙] 정책 연결 실패 pid=%s', pid)
        return jsonify({'ok': False, 'message': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


class _NamePreviewDraft:
    """미리보기용 가짜 상품 — `apply_rules` 가 읽는 칸만 흉내 낸다."""

    def __init__(self, sample: dict):
        g = (sample or {}).get
        self.name = str(g('name') or '')
        self.brand = str(g('brand') or '')
        self.article_no = str(g('article_no') or '')
        self.display_no = str(g('display_no') or '')
        self.model_code = str(g('model_code') or '')
        self.source_site = ''
        self.source_category_path = str(g('category_path') or '')
        self.options_json = '[]'
        self.notice_json = '{}'


@bp.post('/api/name-rules/preview')
def api_name_rule_preview():
    """이 조립 순서로 6마켓에 어떤 이름이 나가나 — **아무것도 저장하지 않는다**."""
    from lemouton.policy.fields import MARKETS
    from lemouton.policy.name_rules import normalize_order
    from lemouton.registration import process_apply as PA
    from lemouton.registration.market_limits import name_limit_for

    body = request.get_json(silent=True) or {}
    순서 = normalize_order(body.get('token_order'))
    if not 순서:
        return jsonify({'ok': False,
                        'message': '조립 순서가 비었습니다 — 조각을 하나 이상 '
                                   '넣어 주세요.'}), 400

    cfg = {'token_order': 순서}
    if body.get('replacements'):
        cfg['replacements'] = [dict(x) for x in body['replacements']
                               if isinstance(x, dict)]
    if body.get('separator') is not None:
        cfg['separator'] = body['separator']
    개별 = dict(body.get('market_overrides') or {})
    draft = _NamePreviewDraft(body.get('sample'))

    rows = []
    for mk, label in MARKETS:
        이_마켓 = dict(cfg)
        over = 개별.get(mk)
        if isinstance(over, dict) and over.get('token_order'):
            이_마켓['token_order'] = normalize_order(over['token_order'])
        # 🔴 전송이 쓰는 그 엔진을 그대로 부른다 — 여기서 다시 조립하면 갈린다.
        view, applied, skipped = PA.apply_rules(draft, {'name': 이_마켓}, market=mk)
        이름 = getattr(view, 'name', '') or ''
        lim = name_limit_for(mk)
        rows.append({
            'market': mk, 'label': label, 'name': 이름,
            'chars': len(이름), 'bytes': len(이름.encode('utf-8')),
            'cap_chars': lim['chars'], 'cap_bytes': lim['bytes'],
            'over': any(a.get('field') == 'max_len' for a in (applied or [])),
            'notes': [x.get('message') or x.get('reason') or ''
                      for x in (skipped or []) if not x.get('blocking')],
        })
    return jsonify({'ok': True, 'rows': rows})


# ══ 마켓별 「보낼 계정」 (2026-08-24 Phase 4-3) ═══════════════════════════
#
# 🔴 예전엔 고를 방법이 아예 없어 **늘 'default' 계정으로** 나갔다.
#   `send/runner.py:_register` 가 `preflight_rows` 에 `keys` 를 안 넘겨서,
#   마켓마다 계정이 여러 개여도 전부 기본 계정 하나로 갔다.

@bp.get('/api/policies/<int:pid>/accounts')
def api_policy_accounts(pid: int):
    """그 정책이 고른 계정 + 고를 수 있는 계정 목록."""
    from lemouton.policy import market_accounts as MA
    from lemouton.policy.models import MarketPolicy
    s = SessionLocal()
    try:
        p = s.get(MarketPolicy, pid)
        if p is None:
            return jsonify({'ok': False, 'message': '그 정책이 없어요.'}), 404
        return jsonify({'ok': True, 'chosen': MA.all_for(p),
                        'choices': MA.choices_for(s)})
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/accounts')
def api_set_policy_accounts(pid: int):
    """마켓별 보낼 계정을 정한다. 빈 값이면 「안 고름」(= 기본 계정)."""
    from lemouton.policy import market_accounts as MA
    from lemouton.policy.models import MarketPolicy
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        p = s.get(MarketPolicy, pid)
        if p is None:
            return jsonify({'ok': False, 'message': '그 정책이 없어요.'}), 404
        got = MA.set_accounts(s, policy=p, values=body.get('accounts') or {})
        s.commit()
        return jsonify({'ok': True, 'chosen': got})
    except ValueError as e:
        s.rollback()
        return jsonify({'ok': False, 'message': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정책계정] 저장 실패 pid=%s', pid)
        return jsonify({'ok': False, 'message': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


# ══ 기존 계정에 기본 배송비 채우기 (2026-08-24 사장님 확정) ═══════════════
#
# 왜 단추인가: 기본값 5,000/10,000 은 **새로 만드는 계정에만** 들어간다.
#   이미 있던 계정 33개는 「안 정함」인데, 프로그램이 임의로 채우면 사장님이 정한
#   적 없는 값을 지어내는 셈이라 안 했다. 사장님이 **누르면** 그건 정한 것이다.
#
# 🔴 이미 값이 있는 계정은 안 건드린다. 0원(무료로 정함)도 「정한 값」이다 —
#   덮으면 무료 반품을 유료로 바꿔 버린다.

@bp.post('/accounts/api/settings/fill-default-fees')
def api_fill_default_fees():
    from lemouton.policy.models import DEFAULT_FEES, MarketAccountSetting
    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        기존 = {r.upload_account_id: r
                for r in s.query(MarketAccountSetting).all()}
        채움, 건너뜀 = 0, 0
        for acc in s.query(UploadAccount).all():
            row = 기존.get(acc.id)
            if row is None:
                s.add(MarketAccountSetting(upload_account_id=acc.id, **DEFAULT_FEES))
                채움 += 1
                continue
            바뀜 = False
            for k, v in DEFAULT_FEES.items():
                # 🔴 `is None` 으로 본다 — 0 은 「무료로 정함」이라 덮으면 안 된다.
                if getattr(row, k) is None:
                    setattr(row, k, v)
                    바뀜 = True
            채움 += 1 if 바뀜 else 0
            건너뜀 += 0 if 바뀜 else 1
        s.commit()
        return jsonify({'ok': True, 'filled': 채움, 'skipped': 건너뜀,
                        'message': (f'{채움}개 계정에 기본 배송비를 넣었습니다'
                                    + (f' · {건너뜀}개는 이미 정해져 있어 그대로 뒀습니다.'
                                       if 건너뜀 else '.'))})
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[계정설정] 기본 배송비 채우기 실패')
        return jsonify({'ok': False, 'message': f'넣지 못했어요: {e}'}), 500
    finally:
        s.close()


# ══ 정규 카테고리 — 보류함·잇기 (2026-08-25 Phase 7-2b) ═══════════════════
#
# 🔴 보류함은 **별도 표가 아니다** — 소싱처 카테고리 중 정규 카테고리를 아직 안
#   가리키는 행이다. 별도 표를 두면 원천이 두 벌이 되고, 한쪽에서 이어도 다른 쪽은
#   모른다(이 저장소가 반복해 사고를 낸 형태).
# 🔴 **자동 확정하지 않는다**(사장님 확정). 점수는 고를 거리를 줄 뿐이다.

@bp.get('/api/normalized-categories')
def api_normalized_categories():
    """정규 카테고리 목록 — 잇기 화면이 고를 거리."""
    from lemouton.policy.normalized_category import NormalizedCategory
    q = (request.args.get('q') or '').strip()
    s = SessionLocal()
    try:
        rows = s.query(NormalizedCategory)
        if q:
            rows = rows.filter(NormalizedCategory.path.contains(q))
        rows = rows.order_by(NormalizedCategory.path).limit(200).all()
        return jsonify({'ok': True, 'items': [
            {'id': r.id, 'path': r.path, 'depth': r.depth,
             'source_market': r.source_market} for r in rows]})
    finally:
        s.close()


@bp.get('/api/category-pending')
def api_category_pending():
    """보류함 — 아직 정규 카테고리를 안 가리키는 소싱처 분류들."""
    import json as _json

    from lemouton.policy import category_bootstrap as CB
    s = SessionLocal()
    try:
        rows = CB.pending(s, source_id=(request.args.get('source') or '').strip() or None)
        out = []
        for r in rows:
            후보 = []
            if r.candidates_json:
                try:
                    후보 = _json.loads(r.candidates_json) or []
                except (TypeError, ValueError):
                    후보 = []      # 깨진 값은 「후보 없음」처럼 — 조용히 쓰지 않는다
            out.append({'id': r.id, 'source_id': r.source_id,
                        'source_path': r.source_path,
                        'confidence': r.confidence, 'candidates': 후보})
        return jsonify({'ok': True, 'items': out, 'count': len(out)})
    finally:
        s.close()


@bp.post('/api/category-pending/<int:link_id>')
def api_link_category(link_id: int):
    """소싱처 분류를 정규 카테고리에 잇는다(또는 뗀다).

    🔴 사람이 눌러야 이어진다 — 점수만으로 이어지는 길은 만들지 않는다.
    """
    from lemouton.policy.normalized_category import NormalizedCategory, SourceCategoryLink
    body = request.get_json(silent=True) or {}
    nid = body.get('normalized_category_id')
    s = SessionLocal()
    try:
        row = s.get(SourceCategoryLink, link_id)
        if row is None:
            return jsonify({'ok': False, 'message': '그 줄이 없어요.'}), 404
        if nid in (None, '', 0):
            row.normalized_category_id = None     # 다시 보류함으로
        else:
            # 🔴 없는 정규 카테고리를 가리키면 화면엔 이어진 것처럼 보이는데 안 먹는다.
            if s.get(NormalizedCategory, int(nid)) is None:
                return jsonify({'ok': False,
                                'message': '그 정규 카테고리가 없어요.'}), 400
            row.normalized_category_id = int(nid)
        s.commit()
        return jsonify({'ok': True, 'normalized_category_id': row.normalized_category_id})
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정규카테고리] 잇기 실패 id=%s', link_id)
        return jsonify({'ok': False, 'message': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/normalized-categories/bootstrap')
def api_bootstrap_categories():
    """마켓 트리에서 씨앗을 붓고, 확정된 기존 매핑을 옮긴다. 멱등."""
    from lemouton.policy import category_bootstrap as CB
    s = SessionLocal()
    try:
        씨앗 = CB.bootstrap(s)
        옮김 = CB.migrate_confirmed(s)
        s.commit()
        전체 = sum(씨앗.values())
        return jsonify({'ok': True, 'seeded': 씨앗, 'migrated': 옮김,
                        'message': (f'정규 카테고리 {전체}칸을 새로 만들고, '
                                    f'확정된 매핑 {옮김["sources"]}건을 옮겼습니다'
                                    + (f' · 마켓 경로를 몰라 {옮김["skipped"]}건은 '
                                       f'건너뛰었습니다.' if 옮김['skipped'] else '.'))})
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정규카테고리] 씨앗 붓기 실패')
        return jsonify({'ok': False, 'message': f'하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.route('/policies/categories')
def policy_categories():
    """카테고리 잇기 화면 — 보류함 + 정규 카테고리 고르기."""
    from flask import render_template
    return render_template('policy/categories.html', active='policies')

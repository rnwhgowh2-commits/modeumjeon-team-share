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

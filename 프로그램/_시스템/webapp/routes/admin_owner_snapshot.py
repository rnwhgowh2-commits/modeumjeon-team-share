# -*- coding: utf-8 -*-
"""옵션 주인 이관 — 기준 지문 조회 (읽기 전용).

  GET /api/admin/option-owner/snapshot          전체 지문 + 묶음별 지문
  GET /api/admin/option-owner/snapshot/<code>   한 묶음을 한 줄씩 (달라진 곳 찾을 때)

[주의] **아무것도 고치지 않는다.** 이관(2단계) 전후로 두 번 불러 대조하는 용도다.
   로컬에서는 라이브 DB 에 붙을 수 없어(.env 없음) 이 창구가 유일한 방법이다.

계산은 lemouton/matrix/owner_snapshot.py 가 단일 원천. 여기는 창구일 뿐이다.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint('admin_owner_snapshot', __name__,
               url_prefix='/api/admin/option-owner')


@bp.before_request
def _admin_only():
    if os.environ.get('ENVIRONMENT') != 'team-share-dev':
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.get('/snapshot')
def snapshot():
    from lemouton.matrix.owner_snapshot import collect
    s = SessionLocal()
    try:
        out = collect(s)
    except Exception as e:                              # noqa: BLE001
        _log.exception('[option-owner] 지문 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    _log.info('[option-owner] 지문 %s · %s', out['overall'], out['counts'])
    return jsonify({'ok': True, **out})


@bp.post('/backfill')
def backfill():
    """옵션에 새 주인(원본 매트릭스)을 붙인다. 멱등.

    [중요] **틀리면 스스로 되돌린다.** 붙이기 전후로 기준 지문을 떠서, 하나라도
       달라졌으면 커밋하지 않고 rollback 한 뒤 409 로 어디가 달라졌는지 돌려준다.

    2a 단계라 읽는 곳이 아직 없다 → 지문은 **반드시 같아야 한다.**
    다르면 그건 이 작업이 딴 것까지 건드렸다는 뜻이다.
    """
    from lemouton.matrix.owner_migrate import backfill as do_backfill
    from lemouton.matrix.owner_snapshot import collect, diff
    from lemouton.matrix.service import ensure_all_origins

    limit = request.args.get('limit', type=int) or 1000
    run_all = request.args.get('all') in ('1', 'true', 'yes')

    s = SessionLocal()
    try:
        before = collect(s)

        # 원본 매트릭스가 없는 모델이 있으면 옵션이 주인을 못 찾는다 — 먼저 보장(멱등).
        made = ensure_all_origins(s, limit=None)

        # 🔴 매트릭스에 U… 번호가 없으면 그 아래 옵션 번호를 만들 수 없다.
        #   라이브에서 실제로 막혔다 — 매트릭스 하나가 번호를 못 받아 옵션 89개가
        #   영영 무번호로 남았다. 여기서 번호부터 챙긴다(멱등).
        from lemouton.sourcing.display_no_assign import assign_missing
        assign_missing(s, limit=None)
        s.flush()

        total = {'attached': 0, 'skipped': 0, 'numbered': 0,
                 'missing_origin': [], 'remaining': 0, 'without_number': 0}
        rounds = 0
        while True:
            res = do_backfill(s, limit=limit)
            rounds += 1
            total['attached'] += res['attached']
            total['skipped'] += res['skipped']
            total['numbered'] += res.get('numbered', 0)
            total['missing_origin'] = sorted(
                set(total['missing_origin']) | set(res['missing_origin']))
            total['remaining'] = res['remaining']
            total['without_number'] = res.get('without_number', 0)
            if (not run_all or rounds >= 100
                    or (res['attached'] == 0 and res.get('numbered', 0) == 0)):
                break

        s.flush()
        after = collect(s)
        d = diff(before, after)
        if not d['same']:
            s.rollback()
            _log.error('[option-owner] 지문이 달라져 되돌림: %s', d)
            return jsonify({'ok': False, 'rolled_back': True,
                            'error': '붙이기 전후 지문이 달라졌습니다 — 아무것도 저장하지 않았습니다.',
                            'diff': d}), 409

        s.commit()
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        _log.exception('[option-owner] 백필 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()

    _log.info('[option-owner] 새 주인 %s (원본 %d개 생성) 지문 %s 유지',
              total, made, before['overall'])
    return jsonify({'ok': True, 'origins_created': made, 'rounds': rounds,
                    'fingerprint': before['overall'], 'unchanged': True, **total})


@bp.get('/snapshot/<path:model_code>')
def snapshot_model(model_code: str):
    from lemouton.matrix.owner_snapshot import model_rows
    s = SessionLocal()
    try:
        out = model_rows(s, model_code)
    except Exception as e:                              # noqa: BLE001
        _log.exception('[option-owner] 묶음 상세 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    if not out['options']:
        return jsonify({'ok': False, 'error': f'그런 묶음이 없습니다: {model_code}'}), 404
    return jsonify({'ok': True, **out})


@bp.get('/derived-drift')
def derived_drift():
    """원본에서 만든 상품의 소싱처 연결이 원본과 갈렸는지 본다 (읽기 전용).

    설계서 규칙 3 — 원본에서 고치면 그 옵션을 쓰는 모든 상품에 반영돼야 한다.
    상품을 만들 때 옵션을 **복사**하므로 그냥 두면 갈린다.
    """
    from lemouton.matrix.derived_sync import check
    s = SessionLocal()
    try:
        out = check(s, apply=False)
    except Exception as e:                              # noqa: BLE001
        _log.exception('[derived-sync] 확인 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    return jsonify({'ok': True, **out})


@bp.post('/derived-sync')
def derived_sync():
    """갈린 것을 원본에 맞춘다. 원본이 진실이다.

    [중요] 옵션 자체는 건드리지 않는다 — 소싱처 연결만 맞춘다.
       그래서 기준 지문(옵션·주소)은 그대로여야 하고, 다르면 되돌린다.
    """
    from lemouton.matrix.derived_sync import check
    from lemouton.matrix.owner_snapshot import collect, diff
    s = SessionLocal()
    try:
        before = collect(s)
        out = check(s, apply=True)
        s.flush()
        after = collect(s)
        d = diff(before, after)
        if not d['same']:
            s.rollback()
            _log.error('[derived-sync] 지문이 달라져 되돌림: %s', d)
            return jsonify({'ok': False, 'rolled_back': True,
                            'error': '맞추는 중 지문이 달라졌습니다 — 아무것도 저장하지 않았습니다.',
                            'diff': d}), 409
        s.commit()
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        _log.exception('[derived-sync] 맞추기 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    _log.info('[derived-sync] %s', out)
    return jsonify({'ok': True, 'fingerprint': before['overall'], **out})


@bp.get('/soldout')
def soldout_scan():
    """전수 품절 상품을 찾는다 (읽기 전용 · 알림 안 보냄). 설계서 규칙 9."""
    from lemouton.matrix.soldout_alert import scan
    s = SessionLocal()
    try:
        out = scan(s)
    except Exception as e:                              # noqa: BLE001
        _log.exception('[soldout] 확인 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    return jsonify({'ok': True, 'counts': {
        'checked': out['checked'], 'soldout': len(out['soldout']),
        'new': len(out['new']), 'recovered': len(out['recovered'])}, **out})


@bp.post('/soldout/notify')
def soldout_notify():
    """새로 전수 품절된 상품만 알린다. 이미 알린 것은 다시 안 보낸다.

    [중요] 상품을 내리지 않는다 — 알림만 보낸다(사장님 확정).
    """
    from lemouton.matrix.soldout_alert import notify_new, scan
    s = SessionLocal()
    try:
        out = scan(s)
        sent = notify_new(s, out)
        s.commit()
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        _log.exception('[soldout] 알림 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    _log.info('[soldout] 새 품절 %d건 알림 · 회복 %d건', sent, len(out['recovered']))
    return jsonify({'ok': True, 'sent': sent,
                    'recovered': len(out['recovered']),
                    'soldout_total': len(out['soldout']),
                    'checked': out['checked']})

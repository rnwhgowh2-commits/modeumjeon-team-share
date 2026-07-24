# -*- coding: utf-8 -*-
"""검색·담기·묶기 API.

★ 잘못된 입력을 조용히 무시하지 않는다. 모르는 마켓을 넘겼는데 전체가 나오면
  사장님은 「검색이 됐다」고 믿는다 — ESM 이 정확히 그래서 사고가 났다.
"""
from flask import jsonify, request

from shared.db import SessionLocal

from . import bp

MARKETS = ('smartstore', 'coupang', 'lotteon', 'eleven11', 'auction', 'gmarket')
STATUSES = ('sale', 'soldout', 'stopped', 'waiting', 'unknown')
MAX_IDS = 200


def parse_search_args(args) -> dict:
    """조회 파라미터 검증. 모르는 값은 거절한다."""
    from lemouton.catalog.search import DEFAULT_LIMIT, MAX_LIMIT

    def _g(k):
        return (args.get(k) or '').strip()

    market = _g('market') or None
    if market and market not in MARKETS:
        raise ValueError(f'모르는 마켓입니다: {market}')
    status = _g('status') or None
    if status and status not in STATUSES:
        raise ValueError(f'모르는 상태입니다: {status}')

    raw_picked = _g('picked').lower()
    picked = True if raw_picked == 'true' else (
        False if raw_picked == 'false' else None)

    try:
        limit = int(_g('limit') or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))
    try:
        offset = max(0, int(_g('offset') or 0))
    except (TypeError, ValueError):
        offset = 0

    return {'q': _g('q'), 'market': market,
            'account_key': _g('account_key') or None,
            'status': status, 'picked': picked,
            'limit': limit, 'offset': offset}


def parse_ids(body) -> list:
    """고른 상품 번호 목록. 비었거나 숫자가 아니면 거절한다."""
    raw = (body or {}).get('ids') or []
    if not isinstance(raw, list) or not raw:
        raise ValueError('고른 상품이 없습니다.')
    if len(raw) > MAX_IDS:
        raise ValueError(f'한 번에 {MAX_IDS}개까지만 담을 수 있습니다.')
    out = []
    for v in raw:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            raise ValueError(f'상품 번호는 숫자여야 합니다: {v!r}')
    return out


@bp.get('/api/search')
def api_search():
    """캐시 검색 — 마켓에 묻지 않는다(4곳이 검색을 못 하므로)."""
    from lemouton.catalog.search import search
    try:
        a = parse_search_args(request.args)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    s = SessionLocal()
    try:
        return jsonify(search(s, a['q'], market=a['market'],
                              account_key=a['account_key'], status=a['status'],
                              picked=a['picked'], limit=a['limit'],
                              offset=a['offset']))
    except Exception as e:      # noqa: BLE001
        return jsonify({'error': 'search_failed', 'detail': str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/groups')
def api_create_group():
    """대표를 정해 묶음을 만들고, 함께 고른 것이 있으면 같이 붙인다."""
    from lemouton.catalog import groups as G

    body = request.get_json(silent=True) or {}
    try:
        leader_id = int(body.get('leader_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': '대표 상품을 골라주세요.'}), 400
    s = SessionLocal()
    try:
        g = G.create_group(s, leader_id=leader_id,
                           name=(body.get('name') or '').strip() or None)
        others = [int(i) for i in (body.get('ids') or []) if int(i) != leader_id]
        moved = []
        if others:
            r = G.attach(s, g['id'], others, detail=True)
            moved = r['moved']
            g = G.get_group(s, g['id'])
        return jsonify({'ok': True, 'group': g, 'moved': moved})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/groups/<int:group_id>/attach')
def api_attach(group_id: int):
    from lemouton.catalog import groups as G
    try:
        ids = parse_ids(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    s = SessionLocal()
    try:
        r = G.attach(s, group_id, ids, detail=True)
        return jsonify({'ok': True, 'attached': r['attached'],
                        'moved': r['moved'], 'group': G.get_group(s, group_id)})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/groups/<int:group_id>/detach')
def api_detach(group_id: int):
    from lemouton.catalog import groups as G
    try:
        ids = parse_ids(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    s = SessionLocal()
    try:
        n = G.detach(s, ids)
        return jsonify({'ok': True, 'detached': n,
                        'group': G.get_group(s, group_id)})
    except Exception as e:      # noqa: BLE001
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()


@bp.get('/api/groups')
def api_list_groups():
    """담아둔 모음전 상품 목록."""
    from lemouton.catalog import groups as G
    s = SessionLocal()
    try:
        try:
            limit = int(request.args.get('limit') or 50)
            offset = int(request.args.get('offset') or 0)
        except (TypeError, ValueError):
            limit, offset = 50, 0
        return jsonify(G.list_groups(
            s, q=(request.args.get('q') or '').strip(),
            limit=limit, offset=offset))
    except Exception as e:      # noqa: BLE001
        return jsonify({'error': 'list_failed', 'detail': str(e)[:300]}), 500
    finally:
        s.close()


@bp.get('/api/groups/<int:group_id>')
def api_get_group(group_id: int):
    from lemouton.catalog import groups as G
    s = SessionLocal()
    try:
        g = G.get_group(s, group_id)
        if g is None:
            return jsonify({'error': '없는 묶음입니다.'}), 404
        return jsonify(g)
    except Exception as e:      # noqa: BLE001
        return jsonify({'error': 'get_failed', 'detail': str(e)[:300]}), 500
    finally:
        s.close()


@bp.delete('/api/groups/<int:group_id>')
def api_delete_group(group_id: int):
    """묶음만 지운다 — 상품은 안 지운다(마켓엔 그대로 있다)."""
    from lemouton.catalog import groups as G
    s = SessionLocal()
    try:
        return jsonify({'ok': G.delete_group(s, group_id)})
    except Exception as e:      # noqa: BLE001
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()

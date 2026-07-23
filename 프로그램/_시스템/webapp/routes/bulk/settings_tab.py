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


# ══ 🛒 쿠팡 계정정보 (2026-07-23 M4-2) ═══════════════════════════════════
#  쿠팡 등록은 vendor 9키가 없으면 100% 실패했다(compile_coupang.py:43). 그 값은
#  드래프트가 아니라 **계정에 매인 고정값**이라 여기서 계정별로 한 번 저장하고,
#  등록·사전점검이 자동 주입한다.
#
#  ★ 9칸 중 7칸은 손으로 적지 않는다 — 쿠팡 조회 API 로 수확한다(「불러오기」).
#    지도 근거: coupang.logistics.query-a-list-of-return-locations /
#              coupang.logistics.query-a-shipping-location (둘 다 st=code)
#  ★ 여기 값은 자격증명이 아니라 **주소·코드**라 화면에 그대로 보여도 된다.
#    다만 반품지 전화번호는 개인정보에 가까워 목록에서는 가운데를 가린다
#    (편집 칸에는 그대로 — 안 그러면 저장할 때 마스킹된 값이 그대로 박힌다).


def _mask_phone(v: str) -> str:
    """'02-111-1111' → '02-***-1111'. 가운데만 가려 어느 번호인지는 알아보게 둔다."""
    parts = [p for p in str(v or '').split('-')]
    if len(parts) < 3:
        return v or ''
    return '-'.join([parts[0]] + ['*' * len(p) for p in parts[1:-1]] + [parts[-1]])


def _coupang_accounts(session) -> list:
    """계정정보를 붙일 수 있는 쿠팡 계정 목록 (+ 저장 현황)."""
    from lemouton.registration import coupang_vendor as CV
    from lemouton.sourcing.models_v2 import UploadAccount

    rows = []
    seen = set()
    for a in (session.query(UploadAccount)
              .filter_by(market='coupang').order_by(UploadAccount.id).all()):
        rows.append({'env_prefix': a.env_prefix, 'account_key': a.account_key,
                     'display_name': a.display_name, 'is_active': bool(a.is_active)})
        seen.add(a.env_prefix)

    # 계정 표가 비어도 `.env` 의 COUPANG_* 로 등록은 나간다 — 그 자리를 화면에 남긴다.
    if CV.DEFAULT_ENV_PREFIX not in seen:
        rows.append({'env_prefix': CV.DEFAULT_ENV_PREFIX, 'account_key': 'default',
                     'display_name': '기본 계정 (.env COUPANG_*)', 'is_active': True})
        seen.add(CV.DEFAULT_ENV_PREFIX)

    # ★ 계정 표에 없는 접두사로 저장된 계정정보도 반드시 보여준다. 안 그러면 계정을
    #   지우거나 이름을 바꾼 순간 저장값이 화면에서 사라져 「저장했는데 없다」가 된다
    #   (지워진 게 아니라 안 보이는 것 — 조용한 손실).
    from lemouton.registration.models import CoupangVendorSetting
    for (orphan,) in (session.query(CoupangVendorSetting.env_prefix)
                      .order_by(CoupangVendorSetting.env_prefix).all()):
        if orphan in seen:
            continue
        rows.append({'env_prefix': orphan, 'account_key': None,
                     'display_name': f'{orphan} (계정 목록에 없음)', 'is_active': False})
        seen.add(orphan)

    for r in rows:
        saved = CV.get_saved(session, r['env_prefix'])
        r['saved'] = saved
        r['complete'] = bool(saved) and all(saved.get(k) for k in CV.SAVED_KEYS)
        r['phone_masked'] = _mask_phone(saved['return_phone']) if saved else ''
    return rows


@bp.get('/api/settings/coupang-vendor')
def get_coupang_vendor():
    from lemouton.registration import coupang_vendor as CV

    s = SessionLocal()
    try:
        return jsonify({'ok': True, 'keys': list(CV.SAVED_KEYS),
                        'accounts': _coupang_accounts(s)})
    except Exception as e:      # noqa: BLE001
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/settings/coupang-vendor')
def save_coupang_vendor():
    """계정정보 저장 — 보낸 칸만 갱신(안 보낸 칸은 유지)."""
    from lemouton.registration import coupang_vendor as CV

    body = request.get_json(silent=True) or {}
    prefix = str(body.get('env_prefix') or '').strip()
    if not prefix:
        return jsonify({'ok': False, 'error': 'env_prefix(계정)를 골라 주세요.'}), 400

    fields = {k: body[k] for k in CV.SAVED_KEYS if k in body}
    if not fields:
        return jsonify({'ok': False,
                        'error': f'저장할 칸이 없습니다 — {list(CV.SAVED_KEYS)} 중에서 보내 주세요.'}), 400

    s = SessionLocal()
    try:
        CV.save_vendor(s, prefix, **fields)
        s.commit()
        return jsonify({'ok': True, 'accounts': _coupang_accounts(s)})
    except ValueError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()


def _vendor_id_for(env_prefix: str) -> str:
    """`.env` 의 vendor_id — 없으면 예외(사유를 그대로 화면에 올린다). 테스트 주입점."""
    from lemouton.auth import secrets as S
    c = S.load_credentials(market='coupang', env_prefix=env_prefix)
    return c.vendor_id


def _coupang_client_for(env_prefix: str):
    """계정별 쿠팡 클라이언트. 테스트 주입점 — 실호출은 이 함수를 통해서만."""
    from lemouton.uploader.market_fetch import _coupang_client
    from shared.platforms.coupang.client import CoupangClient
    return _coupang_client(env_prefix) or CoupangClient()


@bp.post('/api/settings/coupang-vendor/fetch')
def fetch_coupang_vendor():
    """「쿠팡에서 불러오기」 — Wing 에 등록해 둔 반품지·출고지를 그대로 가져온다.

    ⚠ 이 라우트는 **쿠팡 조회 API 를 실제로 부른다**(사장님이 버튼을 눌렀을 때만).
      사전점검(preflight)은 여전히 마켓을 한 번도 부르지 않는다 — 서로 다른 계층이다.
      조회 전용이라 쿠팡에 아무것도 쓰지 않는다.
    """
    from shared.platforms.coupang import logistics as L

    body = request.get_json(silent=True) or {}
    prefix = str(body.get('env_prefix') or '').strip()
    if not prefix:
        return jsonify({'ok': False, 'error': 'env_prefix(계정)를 골라 주세요.'}), 400

    try:
        vendor_id = _vendor_id_for(prefix)
        client = _coupang_client_for(prefix)
        centers = L.list_return_centers(vendor_id, client=client)
        places = L.list_outbound_places(client=client)
    except Exception as e:      # noqa: BLE001 — 실패 사유는 뭉개지 않고 그대로 올린다
        return jsonify({'ok': False,
                        'error': f'쿠팡에서 불러오지 못했습니다 — {e}'[:300]}), 200

    return jsonify({'ok': True, 'vendor_id': vendor_id,
                    'return_centers': centers, 'outbound_places': places,
                    # Wing 로그인 ID 는 어느 조회 API 에도 없다 — 직접 넣어야 한다.
                    'note': 'Wing 로그인 ID 는 쿠팡 조회 API 로 알 수 없어 직접 넣으셔야 합니다.'})

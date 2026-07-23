# -*- coding: utf-8 -*-
"""쿠팡 계정정보(vendor) 저장·조회 — compile_coupang 이 요구하는 9키의 공급처.

배경: `compile_coupang(draft, category_code=..., vendor=...)` 은 vendor 9키를 받는데
등록 화면이 아무것도 안 보내 쿠팡 등록이 100% 실패했다(compile_coupang.py:43).

설계: vendor 는 **계정에 매인 고정값**이라 계정별로 한 번 저장하고 등록·사전점검에서
자동 주입한다. 9키의 출처는 두 갈래다 —

  · vendor_id            ← `.env` `{env_prefix}_VENDOR_ID`  (자격증명. DB 사본 금지)
  · 나머지 8키           ← CoupangVendorSetting (이 모듈)

그리고 8키 중 7개는 사장님이 손으로 적을 필요가 없다 — 쿠팡 조회 API 로 수확한다
(shared/platforms/coupang/logistics.py). 지도 근거는 그 모듈 docstring 참조.
"""
from __future__ import annotations

from typing import Optional

from lemouton.registration.models import CoupangVendorSetting

#: 화면·저장이 다루는 칸 (vendor_id 제외 — `.env` 소관).
SAVED_KEYS = (
    'vendor_user_id',
    'return_center_code',
    'return_charge_name',
    'return_zip',
    'return_address',
    'return_address_detail',
    'return_phone',
    'outbound_place_code',
)

#: compile_coupang 이 실제로 읽는 전체 키 — 화면 안내용.
VENDOR_KEYS = ('vendor_id',) + SAVED_KEYS

#: 계정 표가 비어 있을 때 쓰는 전역 기본 접두사.
#: `shared/platforms/__init__.py` 의 COUPANG 기본 설정이 `COUPANG_ACCESS_KEY` 등
#: 접두사 없는 이름을 읽으므로, 그 계정의 계정정보는 이 이름으로 저장한다.
DEFAULT_ENV_PREFIX = 'COUPANG'


def _load_credentials(env_prefix: str):
    """`.env` 자격증명 로드 — 실패하면 None (테스트 주입점이라 모듈 함수로 둔다)."""
    from lemouton.auth import secrets as S
    try:
        return S.load_credentials(market='coupang', env_prefix=env_prefix)
    except Exception:     # noqa: BLE001 — 키 미설정은 '없음'이지 예외로 죽을 일이 아니다
        return None


def resolve_env_prefix(session, account_key: Optional[str]) -> Optional[str]:
    """등록 요청의 account_key → `.env` 접두사.

    · 실제 계정키가 오면 그 UploadAccount 의 env_prefix (없으면 None — 폴백 금지.
      모르는 계정을 기본 계정으로 바꿔치기하면 남의 계정으로 등록된다).
    · 'default'/빈값이면 활성 쿠팡 계정 중 첫 번째. 계정 표가 비었으면 전역 기본.
    """
    from lemouton.sourcing.models_v2 import UploadAccount

    key = (account_key or '').strip()
    if key and key != 'default':
        acct = (session.query(UploadAccount)
                .filter_by(market='coupang', account_key=key).first())
        return acct.env_prefix if acct is not None else None

    acct = (session.query(UploadAccount)
            .filter_by(market='coupang', is_active=True)
            .order_by(UploadAccount.id).first())
    return acct.env_prefix if acct is not None else DEFAULT_ENV_PREFIX


def get_saved(session, env_prefix: str) -> Optional[dict]:
    """저장된 8키 (없으면 None — 빈 dict 로 뭉개면 '저장했다'와 구분이 안 된다)."""
    row = (session.query(CoupangVendorSetting)
           .filter_by(env_prefix=env_prefix).first())
    if row is None:
        return None
    return {k: (getattr(row, k) or '') for k in SAVED_KEYS}


def save_vendor(session, env_prefix: str, **fields) -> CoupangVendorSetting:
    """계정정보 upsert — **보낸 칸만** 갱신한다.

    안 보낸 칸을 ''로 밀면, 「전화번호만 고치려다 반품지 주소가 통째로 사라지는」
    조용한 손실이 난다. commit 은 호출자 몫(라우트가 트랜잭션 주인).
    """
    prefix = (env_prefix or '').strip()
    if not prefix:
        raise ValueError('env_prefix(계정)가 필요합니다.')

    unknown = [k for k in fields if k not in SAVED_KEYS]
    if unknown:
        raise ValueError(f'모르는 칸입니다: {unknown} — {list(SAVED_KEYS)} 중에서만 됩니다.')

    row = (session.query(CoupangVendorSetting)
           .filter_by(env_prefix=prefix).first())
    if row is None:
        row = CoupangVendorSetting(env_prefix=prefix)
        session.add(row)
    for k, v in fields.items():
        if v is None:
            continue                    # 안 보낸 것과 같게 — 기존 값 유지
        setattr(row, k, str(v).strip())
    session.flush()
    return row


def build_vendor(session, env_prefix: Optional[str]) -> dict:
    """compile_coupang 에 그대로 넘길 9키 dict. 저장된 게 없으면 **빈 dict**.

    빈 dict 를 돌려주는 이유: 컴파일러가 「vendorId 가 필요합니다」로 막게 하려는 것.
    여기서 부분값을 지어내면 쿠팡에 반쯤 빈 반품지로 등록이 나간다(폴백 금지).
    """
    if not env_prefix:
        return {}
    saved = get_saved(session, env_prefix)
    if saved is None:
        return {}
    cred = _load_credentials(env_prefix)
    # 키가 아직 안 꽂혀 있으면 vendor_id 는 ''로 둔다 — 날조하지 않는다.
    return {'vendor_id': getattr(cred, 'vendor_id', '') or '', **saved}


def vendor_for_account(session, account_key: Optional[str]) -> dict:
    """account_key 하나로 9키까지 — 등록·사전점검 라우트의 진입점."""
    return build_vendor(session, resolve_env_prefix(session, account_key))

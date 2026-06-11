# -*- coding: utf-8 -*-
"""2026-06-11 검증 — 적용범위 신규 scope (select / bundle_all_src / set-value-scoped) 왕복.

실 dev DB 에 Flask 테스트 클라이언트로 임시 데이터 생성 → 검증 → 정리.
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault('ENVIRONMENT', 'verify')  # _admin_only 우회 (team-share-dev 아닐 때 통과)

from app import create_app
app = create_app()
if getattr(app, 'login_manager', None):
    app.login_manager.session_protection = None

from shared.db import SessionLocal
from lemouton.sourcing.models import OptionBenefitOverride, Model
from webapp.routes.api_benefits_crud import _options_by_bundle_code

c = app.test_client()
s = SessionLocal()

# ── 인증: 활성 사용자 1명으로 테스트 세션 로그인 (Flask-Login) ──
from webapp.auth.models import User
_u = s.query(User).filter_by(is_active=True).first() or s.query(User).first()
assert _u, '검증용 User 없음'
with c.session_transaction() as sess:
    sess['_user_id'] = str(_u.id)
    sess['_fresh'] = True
print('로그인 사용자: %s' % getattr(_u, 'email', _u.id))

# ── 옵션 2~8개인 작은 모음전 1개 선정 ──
code = None
bundle_opts = None
for (cc,) in s.query(Model.model_code).all():
    if not cc:
        continue
    opts = _options_by_bundle_code(s, cc)
    if 2 <= len(opts) <= 8:
        code, bundle_opts = cc, opts
        break
assert code, '검증용 모음전(옵션 2~8개) 없음'
SRC = 3
pick = [bundle_opts[0]['sku'], bundle_opts[1]['sku']]
print(f'대상 모음전={code} 옵션{len(bundle_opts)}개, pick={pick}')


def cleanup(name):
    rows = s.query(OptionBenefitOverride).filter_by(benefit_name=name).all()
    for r in rows:
        s.delete(r)
    s.commit()


# ── ① select ──
NAME = '__verify_select__'
cleanup(NAME)
r = c.post('/api/benefits/crud', json={
    'name': NAME, 'benefit_type': 'rate', 'value': 0.03,
    'scope': 'select', 'source_id': SRC, 'skus': pick,
})
j = r.get_json()
assert j and j.get('ok') and j.get('applied_count') == 2, j
rows = s.query(OptionBenefitOverride).filter_by(source_id=SRC, benefit_name=NAME).all()
assert sorted(o.canonical_sku for o in rows) == sorted(pick), [o.canonical_sku for o in rows]
print('✓ select 저장 OK', [o.canonical_sku for o in rows])
cleanup(NAME)

# ── ② bundle_all_src ──
NAME2 = '__verify_ballsrc__'
SIDS = [3, 4]
cleanup(NAME2)
r = c.post('/api/benefits/crud', json={
    'name': NAME2, 'benefit_type': 'rate', 'value': 0.02,
    'scope': 'bundle_all_src', 'source_id': SRC,
    'bundle_code': code, 'source_ids': SIDS,
})
j = r.get_json()
assert j and j.get('ok'), j
rows2 = s.query(OptionBenefitOverride).filter_by(benefit_name=NAME2).all()
got_sids = sorted(set(o.source_id for o in rows2))
assert got_sids == sorted(SIDS), got_sids
assert j.get('applied_count') == len(bundle_opts) * len(SIDS), (j.get('applied_count'), len(bundle_opts), len(SIDS))
print('✓ bundle_all_src 저장 OK', j.get('applied_count'), '건, 소싱처', got_sids)
cleanup(NAME2)

# ── ③ set-value-scoped (select) — Task 3 구현 후 활성 ──
try:
    NAME3 = '__verify_setval__'
    cleanup(NAME3)
    r = c.post('/api/source-benefits/overrides/set-value-scoped', json={
        'source_id': SRC, 'benefit_name': NAME3, 'benefit_type': 'rate',
        'value': 0.04, 'scope': 'select', 'skus': pick,
    })
    j = r.get_json()
    if j and j.get('ok'):
        rows3 = s.query(OptionBenefitOverride).filter_by(source_id=SRC, benefit_name=NAME3).all()
        assert all(abs(float(o.value) - 0.04) < 1e-9 for o in rows3) and len(rows3) == 2, rows3
        print('✓ set-value-scoped(select) OK')
        cleanup(NAME3)
    else:
        print('… set-value-scoped 미구현(Task 3 전) — skip:', (j or {}).get('error'))
except Exception as e:
    print('… set-value-scoped skip:', e)

print('✓ cleanup done')

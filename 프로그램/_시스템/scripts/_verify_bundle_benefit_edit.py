# -*- coding: utf-8 -*-
"""2026-06-11 검증 — 모음전 한정 혜택값 수정(set-value-bundle) + 초기화(reset-bundle).

실 dev DB에 대해 Flask 테스트 클라이언트로 왕복 검증:
  1) 수정 전 breakdown 기록
  2) set-value-bundle 호출 → 이 모음전 전 옵션에 override 생성, 템플릿 보존
  3) breakdown 재계산 = 새 값 반영 확인
  4) 같은 소싱처의 '다른 모음전 옵션' 은 영향 없음(템플릿 그대로) 확인
  5) reset-bundle 호출 → override 삭제, 원래 계산값 복귀 확인
끝에 잔여 override 0 확인(원상복구).
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from app import create_app
app = create_app()
# 테스트 세션 주입을 위해 strong 보호 완화(검증 전용)
if getattr(app, 'login_manager', None):
    app.login_manager.session_protection = None
from shared.db import SessionLocal
from lemouton.sourcing.models import SourceBenefitTemplate, OptionBenefitOverride, Model
from webapp.routes.api_benefits_crud import _options_by_bundle_code

s = SessionLocal()

# ── 검증용 (source_id, benefit) = 템플릿 중 rate 타입 1개 ──
tpl = (s.query(SourceBenefitTemplate)
       .filter(SourceBenefitTemplate.benefit_type == 'rate')
       .order_by(SourceBenefitTemplate.id).first())
assert tpl, '검증용 rate 템플릿 없음'
SRC = tpl.source_id
NAME = tpl.benefit_name
ORIG_VAL = float(tpl.value)
NEW_VAL = round(ORIG_VAL + 0.0137, 4) if ORIG_VAL < 0.5 else 0.05

# ── 옵션 ≤ 6개인 작은 모음전 2개 선정 (대상 / 비대상) ──
codes = [c[0] for c in s.query(Model.model_code).all() if c[0]]
target_code = other_code = None
target_skus = other_skus = None
for c in codes:
    sk = [o['sku'] for o in _options_by_bundle_code(s, c)]
    if 1 <= len(sk) <= 6:
        if target_code is None:
            target_code, target_skus = c, sk
        elif other_code is None and not (set(sk) & set(target_skus)):
            other_code, other_skus = c, sk
            break
assert target_code, '옵션 1~6개짜리 모음전 없음'
print('검증 대상  : source_id=%s benefit=%r %.4f→%.4f' % (SRC, NAME, ORIG_VAL, NEW_VAL))
print('대상 모음전: %r (%d옵션) %s' % (target_code, len(target_skus), target_skus))
print('비대상모음전: %r' % (other_code,))

OTHER_SKU = (other_skus or [None])[0]
SALE = 100000.0
c = app.test_client()

# ── 인증: 활성 사용자 1명으로 테스트 세션 로그인 (Flask-Login) ──
from webapp.auth.models import User
_u = s.query(User).filter_by(is_active=True).first() or s.query(User).first()
assert _u, '검증용 User 없음'
with c.session_transaction() as sess:
    sess['_user_id'] = str(_u.id)
    sess['_fresh'] = True
print('로그인 사용자: %s' % getattr(_u, 'email', _u.id))

def bd(sku):
    r = c.get('/api/source-benefits/breakdown/%s/%s?sale_price=%s' % (sku, SRC, SALE))
    j = r.get_json()
    val = next((it['value'] for it in j.get('items_used', []) if it['name'] == NAME), None)
    return j.get('final_price'), val

def n_override():
    return (s.query(OptionBenefitOverride)
            .filter(OptionBenefitOverride.source_id == SRC,
                    OptionBenefitOverride.benefit_name == NAME,
                    OptionBenefitOverride.canonical_sku.in_(target_skus)).count())

results = []
def check(label, cond):
    results.append((label, cond))
    print(('  [PASS] ' if cond else '  [FAIL] ') + label)

T0 = target_skus[0]
fp0, v0 = bd(T0)
print('\n수정 전: final=%s, %s값=%s' % (fp0, NAME, v0))
check('수정 전 override 0건', n_override() == 0)

# ── 2) set-value-bundle ──
r = c.post('/api/source-benefits/overrides/set-value-bundle', json={
    'source_id': SRC, 'bundle_code': target_code,
    'benefit_name': NAME, 'benefit_type': 'rate', 'value': NEW_VAL})
print('\nset-value-bundle:', r.get_json())
check('응답 ok', r.get_json().get('ok') is True)
check('override = 대상옵션 수(%d)' % len(target_skus), n_override() == len(target_skus))
s.expire_all()
tpl_after = s.get(SourceBenefitTemplate, tpl.id)
check('소싱처 공통 템플릿 값 보존(%.4f)' % ORIG_VAL, abs(float(tpl_after.value) - ORIG_VAL) < 1e-9)
fp1, v1 = bd(T0)
print('수정 후: final=%s, %s값=%s' % (fp1, NAME, v1))
check('대상 옵션 값 = 새 값(%.4f)' % NEW_VAL, v1 is not None and abs(v1 - NEW_VAL) < 1e-9)
check('대상 옵션 final 변동', fp1 != fp0)

# ── 4) 비대상 모음전 옵션은 그대로(템플릿 값) ──
if OTHER_SKU:
    fpo, vo = bd(OTHER_SKU)
    print('비대상 옵션(%s): final=%s, %s값=%s' % (OTHER_SKU, fpo, NAME, vo))
    check('비대상 모음전 옵션 값 = 원래 템플릿(%.4f)' % ORIG_VAL,
          vo is not None and abs(vo - ORIG_VAL) < 1e-9)

# ── 5) reset-bundle ──
r = c.post('/api/source-benefits/overrides/reset-bundle', json={
    'source_id': SRC, 'bundle_code': target_code, 'benefit_name': NAME})
print('\nreset-bundle:', r.get_json())
check('reset 응답 ok', r.get_json().get('ok') is True)
check('reset 후 override 0건(원상복구)', n_override() == 0)
fp2, v2 = bd(T0)
print('초기화 후: final=%s, %s값=%s' % (fp2, NAME, v2))
check('초기화 후 값 = 원래 템플릿(%.4f)' % ORIG_VAL, v2 is not None and abs(v2 - ORIG_VAL) < 1e-9)
check('초기화 후 final = 수정 전(%s)' % fp0, fp2 == fp0)

s.close()
ok = all(c for _, c in results)
print('\n=== 결과: %d/%d PASS ===' % (sum(1 for _, c in results if c), len(results)))
print('TOTAL:', 'ALL PASS ✅' if ok else 'FAIL ❌')
sys.exit(0 if ok else 1)

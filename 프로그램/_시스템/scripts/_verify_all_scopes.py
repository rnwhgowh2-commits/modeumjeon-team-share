# -*- coding: utf-8 -*-
"""전수 시연 — 5 적용범위 × (추가/수정/삭제) 전부, 대상 수·값·정리까지 검증.

scope: option / select / bundle / bundle_all_src / source
각 scope: ADD(대상수 일치) → EDIT(set-value, 값 반영) → DELETE(잔여 0).
dev DB, production 무수정(테스트 이름·즉시 삭제). bundle_all_src 는 938행 타이밍 포함.
"""
import sys, io, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault('ENVIRONMENT', 'verify')

from app import create_app
app = create_app()
if getattr(app, 'login_manager', None):
    app.login_manager.session_protection = None
c = app.test_client()

from shared.db import SessionLocal
from lemouton.sourcing.models import OptionBenefitOverride, SourceBenefitTemplate, Model
from lemouton.sourcing.models_pricing import SourceRegistry
from webapp.routes.api_benefits_crud import _options_by_bundle_code
from webapp.auth.models import User

s = SessionLocal()
_u = s.query(User).filter_by(is_active=True).first() or s.query(User).first()
with c.session_transaction() as sess:
    sess['_user_id'] = str(_u.id); sess['_fresh'] = True

# 가장 큰 모음전 + 전 소싱처
best_code, best_opts = None, []
for (cc,) in s.query(Model.model_code).all():
    if cc:
        o = _options_by_bundle_code(s, cc)
        if len(o) > len(best_opts):
            best_code, best_opts = cc, o
SKUS = [o['sku'] for o in best_opts]
SRC = [r.id for r in s.query(SourceRegistry).order_by(SourceRegistry.id).all()]
S0 = SRC[0]
print(f'대상 모음전: {best_code}  옵션 {len(SKUS)} · 소싱처 {len(SRC)}\n')

def n_ovr(name):
    return s.query(OptionBenefitOverride).filter_by(benefit_name=name).count()
def n_tpl(name):
    return s.query(SourceBenefitTemplate).filter_by(benefit_name=name).count()
def ovr_val(name):
    r = s.query(OptionBenefitOverride).filter_by(benefit_name=name).first()
    return float(r.value) if r else None
def tpl_val(name):
    r = s.query(SourceBenefitTemplate).filter_by(benefit_name=name).first()
    return float(r.value) if r else None

def cleanup(name):
    s.query(OptionBenefitOverride).filter_by(benefit_name=name).delete(synchronize_session=False)
    s.query(SourceBenefitTemplate).filter_by(benefit_name=name).delete(synchronize_session=False)
    s.commit()

PASS = []
def chk(label, cond):
    PASS.append(cond)
    print(('  [PASS] ' if cond else '  [FAIL] ') + label)

# scope 별 payload 빌더
def payloads(scope, name, value):
    base = {'benefit_type': 'rate', 'value': value, 'source_id': S0, 'benefit_name': name,
            'name': name, 'scope': scope, 'bundle_code': best_code, 'canonical_sku': SKUS[0]}
    if scope == 'select':
        base['skus'] = SKUS[:2]
    if scope == 'bundle_all_src':
        base['source_ids'] = SRC
    return base

EXPECT = {
    'option': 1, 'select': 2, 'bundle': len(SKUS),
    'bundle_all_src': len(SKUS) * len(SRC), 'source': 1,
}

for scope in ['option', 'select', 'bundle', 'bundle_all_src', 'source']:
    name = '__all_' + scope
    cleanup(name)
    p = payloads(scope, name, 0.005)
    exp = EXPECT[scope]
    print(f'── scope = {scope}  (기대 대상 {exp}) ──')

    # ADD
    t0 = time.perf_counter()
    j = c.post('/api/benefits/crud', json=p).get_json()
    add_ms = (time.perf_counter() - t0) * 1000
    real = n_tpl(name) if scope == 'source' else n_ovr(name)
    chk(f'추가 applied_count={j.get("applied_count")} · DB실제={real} (기대 {exp})  [{add_ms:.0f}ms]',
        j.get('ok') and j.get('applied_count') == exp and real == exp)

    # EDIT (set-value-scoped, 값 0.005 → 0.0123)
    pe = payloads(scope, name, 0.0123)
    je = c.post('/api/source-benefits/overrides/set-value-scoped', json=pe).get_json()
    s.expire_all()
    got = tpl_val(name) if scope == 'source' else ovr_val(name)
    chk(f'수정 set-value ok={je.get("ok")} · 값={got} (기대 0.0123)',
        je.get('ok') and got is not None and abs(got - 0.0123) < 1e-9)

    # DELETE (same scope)
    jd = c.post('/api/source-benefits/delete-scoped', json=p).get_json()
    left = (n_tpl(name) + n_ovr(name))
    chk(f'삭제 ok={jd.get("ok")} · 잔여={left}', jd.get('ok') and left == 0)
    cleanup(name)
    print()

print('=' * 40)
print(f'결과: {sum(PASS)}/{len(PASS)} PASS', '✅ ALL PASS' if all(PASS) else '❌ 일부 FAIL')

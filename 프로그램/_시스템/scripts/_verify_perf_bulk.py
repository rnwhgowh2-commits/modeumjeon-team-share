# -*- coding: utf-8 -*-
"""성능 시연 — bundle_all_src 대량 적용(추가/삭제)의 벌크 처리 속도 측정.

dev DB 의 가장 큰 모음전 × 전 소싱처로 (옵션수×소싱처수) 행을 추가/삭제하며
소요 시간(ms)과 건수를 출력. production 무수정(테스트 이름·즉시 삭제).
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
from lemouton.sourcing.models import OptionBenefitOverride, Model
from lemouton.sourcing.models_pricing import SourceRegistry
from webapp.routes.api_benefits_crud import _options_by_bundle_code
from webapp.auth.models import User

s = SessionLocal()
_u = s.query(User).filter_by(is_active=True).first() or s.query(User).first()
with c.session_transaction() as sess:
    sess['_user_id'] = str(_u.id); sess['_fresh'] = True

# 옵션 가장 많은 모음전 찾기
best_code, best_opts = None, []
for (cc,) in s.query(Model.model_code).all():
    if not cc:
        continue
    opts = _options_by_bundle_code(s, cc)
    if len(opts) > len(best_opts):
        best_code, best_opts = cc, opts
src_ids = [r.id for r in s.query(SourceRegistry).order_by(SourceRegistry.id).all()]
N = len(best_opts) * len(src_ids)
print(f'대상: {best_code}  옵션 {len(best_opts)} × 소싱처 {len(src_ids)} = {N} 행')

NAME = '__perf_ballsrc__'
# 정리(이전 잔여)
s.query(OptionBenefitOverride).filter_by(benefit_name=NAME).delete(synchronize_session=False); s.commit()

# ── 추가 (벌크) 시간 측정 ──
t0 = time.perf_counter()
r = c.post('/api/benefits/crud', json={
    'name': NAME, 'benefit_type': 'rate', 'value': 0.005,
    'scope': 'bundle_all_src', 'source_id': src_ids[0],
    'bundle_code': best_code, 'source_ids': src_ids,
})
add_ms = (time.perf_counter() - t0) * 1000
j = r.get_json()
cnt = s.query(OptionBenefitOverride).filter_by(benefit_name=NAME).count()
print(f'✓ 추가  : {add_ms:7.0f} ms   응답 applied_count={j.get("applied_count")}  DB실제={cnt}')

# ── 삭제 (벌크) 시간 측정 ──
t0 = time.perf_counter()
r = c.post('/api/source-benefits/delete-scoped', json={
    'source_id': src_ids[0], 'benefit_name': NAME, 'scope': 'bundle_all_src',
    'bundle_code': best_code, 'source_ids': src_ids,
})
del_ms = (time.perf_counter() - t0) * 1000
j2 = r.get_json()
left = s.query(OptionBenefitOverride).filter_by(benefit_name=NAME).count()
print(f'✓ 삭제  : {del_ms:7.0f} ms   응답 deleted={j2.get("deleted_overrides")}  잔여={left}')

print(f'\n→ {N}행 추가 {add_ms:.0f}ms / 삭제 {del_ms:.0f}ms · 행당 ≈ {add_ms/max(N,1):.2f}ms (벌크 전엔 행당 1왕복)')
print('PASS' if (cnt == N and left == 0) else 'FAIL')

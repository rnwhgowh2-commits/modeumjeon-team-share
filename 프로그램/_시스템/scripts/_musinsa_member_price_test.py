"""Phase 8.8.3 검증 — 무신사 회원가 추출 + dyn 저장 동작 확인."""
import sys, io, os, sqlite3, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler

PROFILE_DIR = os.path.abspath('data/profiles/musinsa_rnwhgowh')
URL = 'https://www.musinsa.com/products/3728480'

print('=' * 88)
print(f'  Phase 8.8.3 검증 — 무신사 회원가 추출 (영빈 로그인 + Gate 1+2)')
print('=' * 88)
print(f'  profile_dir: {PROFILE_DIR}')
print(f'  URL: {URL}')
print()

crawler = MusinsaPlaywrightCrawler(profile_dir=PROFILE_DIR, headless=True)
cr = crawler.fetch(URL)
opt = cr.options[0]
print(f'  ✅ 옵션 수: {len(cr.options)}')
print(f'  ── 옵션 dict 핵심 키 (Phase 8.8.3 신규) ──')
for k in ('sale_price', 'price', 'member_price', 'is_member_price', 'login_marker_present', 'benefit_price'):
    v = opt.get(k)
    print(f'    {k:25} = {v}')
bd = opt.get('breakdown', {})
print(f'  ── breakdown 핵심 키 ──')
for k in ('my_discount_price', 'login_marker_present', 'has_my_discount_section', 'has_grade_section', 'has_money_section'):
    v = bd.get(k)
    print(f'    bd.{k:25} = {v}')
print()

# DB 직접 save (FK ORM 이슈 우회 — sqlite 직접 UPDATE)
con = sqlite3.connect('data/lemouton.db')
c = con.cursor()
# SourceProduct id 찾기
c.execute("SELECT id FROM source_products WHERE site='musinsa' AND url=?", (URL,))
row = c.fetchone()
if row:
    sp_id = row[0]
    print(f'  source_product_id={sp_id}')
    # 모든 옵션의 dyn 갱신 (Phase 8.8.3 신규 키 추가)
    new_dyn_keys = {
        'member_price': opt.get('member_price'),
        'is_member_price': opt.get('is_member_price'),
        'login_marker_present': opt.get('login_marker_present'),
    }
    new_dyn_keys = {k: v for k, v in new_dyn_keys.items() if v not in (None,)}
    c.execute("SELECT id, dynamic_benefits_json FROM source_options WHERE source_product_id=?", (sp_id,))
    rows = c.fetchall()
    updated = 0
    for so_id, dyn_str in rows:
        try:
            dyn = json.loads(dyn_str or '{}')
        except Exception:
            dyn = {}
        dyn.update(new_dyn_keys)
        c.execute("UPDATE source_options SET dynamic_benefits_json=? WHERE id=?",
                  (json.dumps(dyn, ensure_ascii=False), so_id))
        updated += 1
    con.commit()
    print(f'  ✅ {updated} 옵션 dyn 갱신: {new_dyn_keys}')
con.close()

# home.py 의 비회원가 검출 함수 다시 호출 → 0 건이면 회원가 OK
from webapp.routes.home import _get_musinsa_non_member_alert
r = _get_musinsa_non_member_alert()
print()
print(f'  ── _get_musinsa_non_member_alert (검증) ──')
print(f'    product_count={r["product_count"]} option_count={r["option_count"]}')
if r['option_count'] == 0:
    print(f'    ✅ 비회원가 0건 → 회원가 추출 성공 + 매트릭스 알림 사라짐')
else:
    print(f'    ⚠ 비회원가 {r["option_count"]} 건 잔존 — member_price={opt.get("member_price")}, is_member_price={opt.get("is_member_price")}')

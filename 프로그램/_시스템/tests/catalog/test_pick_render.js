// 상품 담기 화면이 실제로 그려지는지 — 함수 하나라도 터지면 화면이 빈다.
// 실행: node tests/catalog/test_pick_render.js
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..',
  'webapp', 'templates', 'catalog', 'partials', '_pick.html');
const html = fs.readFileSync(file, 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

// ── 최소 DOM 흉내 ─────────────────────────────────────────────
const els = {};
function mkEl(id) {
  return {
    id, value: '', textContent: '', _html: '',
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html; },
    querySelectorAll: () => [],
    onclick: null, oninput: null, onchange: null, disabled: false,
  };
}
['pk-list', 'pk-cart', 'pk-msg', 'pk-hint', 'pk-save', 'pk-q',
 'pk-market', 'pk-status', 'pk-cart-hint'].forEach((id) => { els[id] = mkEl(id); });
global.document = { getElementById: (id) => els[id] || mkEl(id) };
global.window = { alert: () => {} };
global.URLSearchParams = URLSearchParams;

let payload = {
  total: 2, limit: 50, offset: 0,
  rows: [
    { id: 1, market: 'lotteon', account_key: '브랜드위시',
      market_product_id: 'LO2727575855', name: '아디다스골프 썬 햇 모자',
      brand: '아디다스', status: 'sale', sale_price: 31900, group_id: null },
    { id: 2, market: 'coupang', account_key: '브랜드마켓쿠팡',
      market_product_id: '16176862782', name: '르무통 스니커즈 운동화',
      brand: '르무통', status: 'stopped', sale_price: null, group_id: 7 },
  ],
};
global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });

eval(script);

function check(label, el, must) {
  const missing = must.filter((m) => !el._html.includes(m));
  if (missing.length) {
    console.error(`[${label}] 화면에 안 나온 것:`, missing);
    console.error('실제:', el._html.slice(0, 400));
    process.exit(1);
  }
  console.log(`  OK ${label} (길이 ${el._html.length})`);
}

setTimeout(() => {
  check('검색 결과', els['pk-list'], [
    '아디다스골프 썬 햇 모자', '31,900원', '롯데온', '판매중',
    '르무통 스니커즈', '쿠팡', '판매중지', '이미 담김',
    '담기',
  ]);
  // 가격이 없으면 0원이 아니라 — 로 (공짜 상품으로 보이면 안 된다)
  if (!els['pk-list']._html.includes('—')) {
    console.error('가격 미상이 — 로 안 나온다'); process.exit(1);
  }
  if (els['pk-cart']._html.indexOf('아직 고른 것이 없습니다') < 0) {
    console.error('빈 담을목록 안내가 없다'); process.exit(1);
  }
  console.log('  OK 담을목록 비어있음');

  // 검색 결과 0건
  payload = { total: 0, rows: [], limit: 50, offset: 0 };
  eval(script);
  setTimeout(() => {
    check('결과 0건', els['pk-list'], ['찾는 상품이 없습니다', '지금 동기화']);
    console.log('OK — 상품 담기 화면 렌더 확인');
  }, 30);
}, 30);

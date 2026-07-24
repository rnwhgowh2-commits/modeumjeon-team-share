// 상품 상세 화면 — 확정 시안 ①(그 자리 펼침·나머지가 얇아짐) + ⑥(마켓마다 카드).
// 실행: node tests/catalog/test_detail_render.js
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..',
  'webapp', 'templates', 'catalog', 'partials', '_detail.html');
const html = fs.readFileSync(file, 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

const els = {};
function mkEl(id) {
  return {
    id, value: '', _html: '',
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html; },
    querySelectorAll: () => [], oninput: null,
  };
}
['dt-root', 'dt-q'].forEach((id) => { els[id] = mkEl(id); });
global.document = { getElementById: (id) => els[id] || mkEl(id) };
global.window = { alert: () => {}, confirm: () => true };
global.URLSearchParams = URLSearchParams;

const GROUPS = {
  total: 2,
  rows: [
    { id: 1, name: '아디다스골프 썬 햇 모자', brand: '아디다스', member_count: 3,
      markets: ['coupang', 'eleven11', 'lotteon'],
      price_min: 31900, price_max: 32900, has_soldout: false, has_stopped: true },
    { id: 2, name: '필라 페이토 샌들', brand: '휠라', member_count: 2,
      markets: ['auction', 'gmarket'],
      price_min: null, price_max: null, has_soldout: true, has_stopped: false },
  ],
};
const DETAIL = {
  id: 1, name: '아디다스골프 썬 햇 모자', brand: '아디다스', member_count: 3,
  markets: ['coupang', 'eleven11', 'lotteon'],
  members: [
    { id: 11, market: 'lotteon', account_key: '브랜드위시',
      market_product_id: 'LO2727575855', site_product_id: null,
      name: '<매장정품> 아디다스골프 썬 햇 모자', status: 'sale',
      sale_price: 31900, synced_at: '2026-07-24T10:34:57' },
    { id: 12, market: 'eleven11', account_key: '브랜드마켓11번가',
      market_product_id: '4821003942', site_product_id: null,
      name: '아디다스골프 HS9658 썬햇', status: 'sale',
      sale_price: 32900, synced_at: '2026-07-24T10:35:02' },
    { id: 13, market: 'coupang', account_key: '브랜드마켓쿠팡',
      market_product_id: '16176862782', site_product_id: null,
      name: '아디다스 골프 썬햇 모자', status: 'stopped',
      sale_price: null, synced_at: null },
  ],
};

let mode = 'list';
global.fetch = (url) => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(
    String(url).includes('/api/groups/') ? DETAIL
      : (mode === 'empty' ? { total: 0, rows: [] } : GROUPS)),
});

eval(script);

function need(label, must, forbid) {
  const h = els['dt-root']._html;
  const missing = must.filter((m) => !h.includes(m));
  if (missing.length) {
    console.error(`[${label}] 화면에 안 나온 것:`, missing);
    console.error('실제:', h.slice(0, 600));
    process.exit(1);
  }
  (forbid || []).forEach((f) => {
    if (h.includes(f)) {
      console.error(`[${label}] 나오면 안 되는 것:`, f); process.exit(1);
    }
  });
  console.log(`  OK ${label} (길이 ${h.length})`);
}

setTimeout(() => {
  // 1) 목록 — 접힘 없이 보통 줄. 가격은 범위로.
  need('목록', ['아디다스골프 썬 햇 모자', '31,900원 ~ 32,900원', '필라 페이토 샌들',
                '가격 미상', '품절 있음', '중지 있음', '펼치기', '롯데온', '옥션']);

  // 2) 펼침 — 하나를 열면 나머지는 얇아지되 **상품명·가격은 남아야** 한다
  const openFns = [];
  els['dt-root'].querySelectorAll = () => openFns;
  // toggle 을 직접 부를 수 없으니 스크립트를 다시 실행하며 openId 를 흉내낸다:
  // 대신 render 결과를 확인하기 위해 fetch 를 태워 detail 을 받은 상태를 만든다.
  eval(script.replace('let openId = null;', 'let openId = 1;')
             .replace('let detail = null;', 'let detail = ' + JSON.stringify(DETAIL) + ';'));
  setTimeout(() => {
    need('펼침 + 마켓 카드', [
      // ⑥ 마켓마다 카드
      '롯데온', '11번가', '쿠팡',
      // ★ 상품명은 안전하게 바꿔 그린다 — 꺾쇠를 그대로 넣으면 화면이 깨진다
      '&lt;매장정품&gt; 아디다스골프 썬 햇 모자',
      '31,900원', '32,900원', 'LO2727575855', '마켓 상품 페이지',
      '이 마켓만 고치기', '다음 단계에서 열립니다',
      '아직 확인 전',            // 확인 시각 없는 카드
      '접기', '이 상품 묶음 풀기',
      // ① 나머지는 얇아지되 상품명·가격은 남는다
      '필라 페이토 샌들', '가격 미상',
    ]);
    const h = els['dt-root']._html;
    if (!h.includes('dt-thin')) {
      console.error('나머지 줄이 얇아지지 않았다'); process.exit(1);
    }
    console.log('  OK 나머지 줄이 얇아짐');

    // 3) 담은 게 없을 때
    mode = 'empty';
    eval(script);
    setTimeout(() => {
      need('담은 것 없음', ['아직 담아둔 상품이 없습니다', '상품 담기']);
      console.log('OK — 상품 상세 화면 렌더 확인');
    }, 30);
  }, 30);
}, 30);

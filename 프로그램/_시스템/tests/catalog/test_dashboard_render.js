// 현황 보기 화면이 실제로 그려지는지 — 함수 하나라도 터지면 화면이 빈다.
// 실행: node tests/catalog/test_dashboard_render.js
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..',
  'webapp', 'templates', 'catalog', 'partials', '_dashboard.html');
const html = fs.readFileSync(file, 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

let rendered = '';
const handlers = [];
const fakeEl = {
  set innerHTML(v) { rendered = v; },
  get innerHTML() { return rendered; },
  querySelectorAll: () => handlers,
};
global.document = { getElementById: () => fakeEl };
global.window = { alert: () => {} };

let payload = {
  markets: [{
    market: 'lotteon', total: 47960,
    accounts: [{ account_key: '브랜드위시', total: 47960, sale: 44102,
                 soldout: 612, stopped: 3246, waiting: 0, unknown: 0,
                 measured_at: '2026-07-24T03:00:00+00:00' }],
  }],
  summary: { total: 47960, sale: 44102, soldout: 612, stopped: 3246,
             waiting: 0, unknown: 0, groups: 3, linked: 7 },
  unknown_total: 0,
};
// ★ 탭이 실제로 scope 를 넘기는지 확인 — 안 넘기면 거짓 기능이다
const fetched = [];
global.fetch = (url) => {
  fetched.push(String(url));
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
};

eval(script);

function check(label, must, forbid) {
  const missing = must.filter((m) => !rendered.includes(m));
  if (missing.length) {
    console.error(`[${label}] 화면에 안 나온 것:`, missing);
    process.exit(1);
  }
  (forbid || []).forEach((f) => {
    if (rendered.includes(f)) {
      console.error(`[${label}] 나오면 안 되는 것이 나왔다:`, f);
      process.exit(1);
    }
  });
  console.log(`  OK ${label} (길이 ${rendered.length})`);
}

setTimeout(() => {
  check('정상', ['브랜드위시', '44,102', '612', '47,960', '롯데온',
                 '지금 동기화', '모음전', '대량등록', '마지막 확인',
                 '마켓에 올라간 상품 전체']);
  if (!fetched.some((u) => u.includes('scope=bundle'))) {
    console.error('탭 구분(scope)을 안 넘긴다 — 탭이 거짓 기능이 된다:', fetched);
    process.exit(1);
  }
  console.log('  OK 탭 구분을 실제로 넘김');
  if (rendered.length < 500) {
    console.error('화면이 거의 비었다 — 길이', rendered.length);
    process.exit(1);
  }

  // 아직 한 번도 안 훑은 상태 — 빈 표를 그려야지 터지면 안 된다
  payload = { markets: [], summary: { total: 0, sale: 0, soldout: 0, stopped: 0,
              waiting: 0, unknown: 0, groups: 0, linked: 0 }, unknown_total: 0 };
  eval(script);
  setTimeout(() => {
    check('아직 안 훑음', ['아직 가져온 상품이 없습니다', '지금 동기화']);

    // ★ 모르는 상태가 있으면 경고가 떠야 한다 — 숨기면 아무도 모른다
    payload = {
      markets: [{ market: 'lotteon', total: 8,
        accounts: [{ account_key: 'A', total: 8, sale: 5, soldout: 0,
                     stopped: 0, waiting: 0, unknown: 3, measured_at: null }] }],
      summary: { total: 8, sale: 5, soldout: 0, stopped: 0, waiting: 0,
                 unknown: 3, groups: 0, linked: 0 },
      unknown_total: 3,
    };
    eval(script);
    setTimeout(() => {
      check('모르는 상태 경고', ['처음 보는 상태가 3개 있습니다', '아직 확인 전']);
      console.log('OK — 현황 화면 렌더 3가지 경우 모두 확인');
    }, 30);
  }, 30);
}, 30);

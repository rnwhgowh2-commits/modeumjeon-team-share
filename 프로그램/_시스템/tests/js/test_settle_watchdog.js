// test_settle_watchdog.js
//  [2026-08-04] 정산 자동 반복 「회차 감시」 — 실사고 고정.
//  걸린 회차(롯데온 페이지 무한 대기 등)가 _settleRunning 을 영영 쥐면, 1분 알람 틱이
//  매번 busy 로 빠져 다음 회차가 1~2시간씩 밀렸다(2026-08-04 실측: 17:10 다음이 19:56).
//  수정 = 30분 상한 감시: 넘기면 강제로 내려놓고(_settleGen 세대표로 옛 회차 무장해제)
//  다음 회차부터 다시 돈다. 옛 회차가 뒤늦게 깨어나도 기록·마감을 못 덮는다(모순 금지).
//
//  ★실제 background.js 의 settle 블록(MOUM_SETTLE_ALARM ~ MOUM_SETTLE_AWAKE_ALARM 직전)을
//    그대로 잘라 vm 에 싣는다 — 로직을 베껴 두면 확장이 바뀌어도 초록불이라 해롭다.
//    가짜 chrome(storage/alarms/tabs)·가짜 시계(Date)만 물린다.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

let pass = 0, fail = 0;
function t(name, fn) {
  return Promise.resolve().then(fn).then(
    () => { console.log('  ✅ ' + name); pass++; },
    (e) => { console.log('  ❌ ' + name + ' — ' + e.message); fail++; });
}

const sys = path.join(__dirname, '..', '..');
const extDir = path.join(sys, 'extension', 'moum-crawler');
const bg = fs.readFileSync(path.join(extDir, 'background.js'), 'utf8');

// ── settle 블록 절취 ──
const start = bg.indexOf('const MOUM_SETTLE_ALARM');
const end = bg.indexOf('const MOUM_SETTLE_AWAKE_ALARM');
assert.ok(start >= 0 && end > start, 'settle 블록 경계를 background.js 에서 찾지 못함');
const slice = bg.slice(start, end);

// ── 가짜 세상 ──
let now = Date.UTC(2026, 7, 4, 9, 0, 0);   // 시계는 우리가 돌린다
class FakeDate extends Date {
  constructor(...a) { if (a.length) super(...a); else super(now); }
  static now() { return now; }
}
const store = {};                 // chrome.storage.local
const removedTabs = [];           // 강제 중단이 닫은 탭
let collectCalls = 0;             // 회차가 계정 수집을 몇 번 시작했나
let collectMode = 'hang';         // 'hang' = 영영 안 끝남 / 'ok' = 정상
let hangResolve = null;           // 걸린 수집을 뒤늦게 깨우는 손잡이

const sandbox = {
  console,
  Date: FakeDate,
  chrome: {
    runtime: { lastError: null },
    storage: { local: {
      get(key, cb) { cb({ [key]: store[key] }); },
      set(obj, cb) { Object.assign(store, obj); if (cb) cb(); },
    } },
    alarms: { create() {}, clear() {}, onAlarm: { addListener() {} } },
    tabs: { remove: async (id) => { removedTabs.push(id); } },
  },
  _mgr: { base: '' },
  _loTabId: 77,
  closeServiceTabIfOwned: async () => {},
  handleLotteonAccountCollect() {
    collectCalls++;
    if (collectMode === 'hang') return new Promise((res) => { hangResolve = res; });
    return Promise.resolve({ ok: true, rows: [{ a: 1 }], collected: 3, orderRows: [], trNo: 'T1' });
  },
  bgFetch: async (url) => ({ json: async () => {
    if (url.indexOf('/accounts/api/crawl-login/accounts') >= 0)
      return { ok: true, accounts: [{ saved: true, env_prefix: 'L1', display_name: '테스트' }] };
    if (url.indexOf('/creds') >= 0) return { ok: true, login_id: 'id', password: 'pw' };
    return { ok: true };
  } }),
};
const ctx = vm.createContext(sandbox);
const run = (code) => vm.runInContext(code, ctx);
const flush = async (n) => { for (let i = 0; i < (n || 20); i++) await new Promise((r) => setTimeout(r, 0)); };

const T0 = now;
const KEY = 'moum_settle_auto';
store[KEY] = { on: true, min: 60, nextAt: 1, base: '', last: null, deepAt: now };  // 마감 지남 → 첫 틱에 돈다

(async () => {
  console.log('정산 자동 반복 — 회차 감시(30분 상한) 동작:');
  vm.runInContext(slice, ctx, { filename: 'settle-slice.js' });

  run('settleTick()'); await flush();
  await t('걸린 회차가 시작됐고, 틱이 먼저 다음 마감을 밀어 뒀다', () => {
    assert.strictEqual(run('_settleRunning'), true, '회차가 안 돌았다');
    assert.strictEqual(collectCalls, 1);
    assert.strictEqual(store[KEY].nextAt, T0 + 3600000, '마감을 안 밀었다');
  });

  now = T0 + 29 * 60000;
  run('settleTick()'); await flush();
  await t('29분 — 상한 전에는 건드리지 않는다(멀쩡한 긴 회차 보호)', () => {
    assert.strictEqual(run('_settleRunning'), true);
    assert.strictEqual(removedTabs.length, 0);
    assert.strictEqual(collectCalls, 1);
  });

  now = T0 + 31 * 60000;
  run('settleTick()'); await flush();
  await t('31분 — 강제로 내려놓는다: 깃발 해제 + 롯데온 탭 닫기', () => {
    assert.strictEqual(run('_settleRunning'), false, '깃발이 안 내려갔다');
    assert.deepStrictEqual(removedTabs, [77], '걸린 탭을 안 닫았다');
  });
  await t('강제 중단을 기록으로 남긴다 — 조용한 복구 금지', () => {
    assert.ok(store[KEY].last && /강제 중단/.test(store[KEY].last.error || ''),
      'last.error 에 강제 중단이 없다: ' + JSON.stringify(store[KEY].last));
  });
  await t('마감(T0+60분) 전이라 새 회차는 아직 안 돈다(중복 방지)', () => {
    assert.strictEqual(collectCalls, 1);
  });

  collectMode = 'ok';
  now = T0 + 61 * 60000;
  run('settleTick()'); await flush(40);
  await t('마감이 오면 새 회차가 정상으로 돌고 성공을 기록한다', () => {
    assert.strictEqual(collectCalls, 2, '새 회차가 안 돌았다');
    assert.strictEqual(run('_settleRunning'), false, '새 회차가 안 끝났다');
    assert.strictEqual(store[KEY].last.ok, 1, '성공 기록이 없다: ' + JSON.stringify(store[KEY].last));
    assert.strictEqual(store[KEY].last.error, '', '성공인데 오류가 남았다');
  });

  const snap = JSON.stringify(store[KEY]);
  hangResolve({ ok: true, rows: [{ a: 1 }], collected: 99, orderRows: [], trNo: 'OLD' });
  await flush(40);
  await t('걸려 있던 옛 회차가 뒤늦게 깨어나도 기록·마감을 못 덮는다(세대표)', () => {
    assert.strictEqual(JSON.stringify(store[KEY]), snap, '옛 회차가 상태를 덮었다');
    assert.strictEqual(run('_settleRunning'), false, '옛 회차가 남의 깃발을 건드렸다');
  });

  // ── 정적 고정 — 버전 3곳 일치(로드버전 진단이 거짓말하면 디버깅이 통째로 샌다) ──
  await t('manifest ↔ background ↔ content_mou 버전이 모두 같다', () => {
    const manifest = JSON.parse(fs.readFileSync(path.join(extDir, 'manifest.json'), 'utf8'));
    const bgV = (bg.match(/const\s+MOUM_EXT_VERSION\s*=\s*["']([^"']+)["']/) || [])[1];
    const cm = fs.readFileSync(path.join(extDir, 'content_mou.js'), 'utf8');
    const cmV = (cm.match(/const\s+MOUM_EXT_VERSION\s*=\s*["']([^"']+)["']/) || [])[1];
    assert.strictEqual(bgV, manifest.version, 'background ≠ manifest');
    assert.strictEqual(cmV, manifest.version, 'content_mou ≠ manifest (0.7.70 드리프트 재발)');
  });

  // ── 정적 고정 — 페이지 연결 감시(굳은 화면 재발 방지) ──
  await t('크롤-로그인 페이지에 연결 감시가 있다(경고 배너 + 새로고침 1회 가드)', () => {
    const page = fs.readFileSync(path.join(sys, 'webapp', 'templates', 'accounts', 'crawl_login.html'), 'utf8');
    assert.ok(page.indexOf('stl-conn-warn') >= 0, '연결 끊김 배너가 사라짐');
    assert.ok(page.indexOf('moum_settle_conn_reloaded') >= 0, '새로고침 1회 가드가 사라짐(무한 새로고침 위험)');
  });

  console.log('\n' + pass + ' 통과 / ' + fail + ' 실패');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

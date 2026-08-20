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
  setInterval, clearInterval,   // 심장박동(20초 storage.get)이 쓴다 — 실타이머라 테스트엔 영향 없음
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
  console.log('정산 자동 반복 — 회차 감시(40분 상한)·실패 재시도·회차 예산 동작:');
  vm.runInContext(slice, ctx, { filename: 'settle-slice.js' });

  run('settleTick()'); await flush();
  await t('걸린 회차가 시작됐고, 틱이 먼저 다음 마감을 밀어 뒀다', () => {
    assert.strictEqual(run('_settleRunning'), true, '회차가 안 돌았다');
    assert.strictEqual(collectCalls, 1);
    assert.strictEqual(store[KEY].nextAt, T0 + 3600000, '마감을 안 밀었다');
  });
  await t('시작 도장(runStartedAt)이 스토리지에 찍혔다 — 도중 사망 부검용', () => {
    assert.ok(store[KEY].runStartedAt > 0, '시작 도장이 없다');
  });
  await t('심장박동이 있다 — 회차 중 20초마다 SW 를 깨워 둔다(30초 침묵 사망 방지)', () => {
    const body = slice.slice(slice.indexOf('async function settleRunOnce'));
    assert.ok(/setInterval\(/.test(body), '심장박동 setInterval 이 없다');
    assert.ok(/clearInterval\(_ka\)/.test(body), '심장박동을 finally 에서 안 끈다(누수)');
  });

  now = T0 + 39 * 60000;
  run('settleTick()'); await flush();
  await t('39분 — 상한 전에는 건드리지 않는다(멀쩡한 긴 회차 보호)', () => {
    assert.strictEqual(run('_settleRunning'), true);
    assert.strictEqual(removedTabs.length, 0);
    assert.strictEqual(collectCalls, 1);
  });

  now = T0 + 41 * 60000;
  run('settleTick()'); await flush();
  await t('41분 — 강제로 내려놓는다: 깃발 해제 + 롯데온 탭 닫기', () => {
    assert.strictEqual(run('_settleRunning'), false, '깃발이 안 내려갔다');
    assert.deepStrictEqual(removedTabs, [77], '걸린 탭을 안 닫았다');
  });
  await t('강제 중단을 기록으로 남긴다 — 조용한 복구 금지', () => {
    assert.ok(store[KEY].last && /강제 중단/.test(store[KEY].last.error || ''),
      'last.error 에 강제 중단이 없다: ' + JSON.stringify(store[KEY].last));
    assert.ok(Array.isArray(store[KEY].hist) && /강제 중단/.test((store[KEY].hist[0]||{}).error||''),
      '이력(hist)에도 강제 중단이 남아야 한다 — 기록과 최근이 같은 사실을 말하게');
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
  await t('정상 완료는 시작 도장을 지운다(끝맺음)', () => {
    assert.strictEqual(store[KEY].runStartedAt, 0, '끝났는데 도장이 남았다');
  });
  await t('회차 이력(hist)이 쌓인다 — 맨 앞이 방금 회차(성공 1), 그 뒤가 강제 중단', () => {
    var h = store[KEY].hist;
    assert.ok(Array.isArray(h) && h.length === 2, 'hist 가 2건이어야 한다: ' + JSON.stringify(h));
    assert.strictEqual(h[0].ok, 1, '맨 앞이 방금 성공 회차가 아니다');
    assert.ok(/강제 중단/.test(h[1].error || ''), '두 번째가 강제 중단 이력이 아니다');
  });

  const snap = JSON.stringify(store[KEY]);
  const removedBefore = removedTabs.length;
  run('_loTabId = 88;');          // 새 회차가 쓰고 있는 탭(옛 회차가 건드리면 안 된다)
  hangResolve({ ok: true, rows: [{ a: 1 }], collected: 99, orderRows: [], trNo: 'OLD' });
  await flush(40);
  await t('걸려 있던 옛 회차가 뒤늦게 깨어나도 기록·마감을 못 덮는다(세대표)', () => {
    assert.strictEqual(JSON.stringify(store[KEY]), snap, '옛 회차가 상태를 덮었다');
    assert.strictEqual(run('_settleRunning'), false, '옛 회차가 남의 깃발을 건드렸다');
  });
  // [2026-08-06 라이브] 「예기치 못한 오류: No tab with id」의 정체 —
  //   끊긴 옛 회차가 뒷정리까지 흘러와 **지금 도는 회차의 롯데온 탭을 닫아** 그 계정을 죽였다.
  await t('옛 회차는 남의 롯데온 탭도 못 닫는다(No tab with id 사고)', () => {
    assert.strictEqual(removedTabs.length, removedBefore,
      '옛 회차가 새 회차의 탭을 닫았다: ' + JSON.stringify(removedTabs));
    assert.strictEqual(run('_loTabId'), 88, '옛 회차가 남의 탭 번호를 지웠다');
  });

  // ══════════════════════════════════════════════════════════════════════
  //  [2026-08-06] 자동 회차만 실패 2~3계정 — 손으로 그 계정만 돌리면 정상이던 사건
  //   근본원인 = 롯데온 전용 백그라운드 탭에 재우기 금지 핀이 없어 크롬이 재웠다.
  //   여기서는 그 사건이 만든 **회차 쪽 방어 3가지**를 고정한다(탭 핀 자체는 아래 별도 블록).
  // ══════════════════════════════════════════════════════════════════════
  {
    // 계정 3개 · 첫 번째만 처음에 실패하고 두 번째 시도에 붙는 세상
    const seen = [];
    let failOnce = new Set(['L1']);
    const ctx2ctl = {
      accounts: [{ saved: true, env_prefix: 'L1', display_name: '가' },
                 { saved: true, env_prefix: 'L2', display_name: '나' },
                 { saved: true, env_prefix: 'L3', display_name: '다' }],
      posted: [],
      tickMs: 0,          // 계정 하나가 잡아먹는 (가짜) 시간
    };
    const sb2 = Object.assign({}, sandbox, {
      _loTabId: null,
      handleLotteonAccountCollect: (p) => {
        const pfx = p.login_id;                     // creds 가 env_prefix 를 그대로 돌려준다
        seen.push(pfx);
        now += ctx2ctl.tickMs;                      // 회차 예산 소모를 흉내
        if (failOnce.has(pfx)) { failOnce.delete(pfx); return Promise.resolve({ ok: false, step: '로그인', error: '로그인 실패' }); }
        if (pfx === 'V1') return Promise.resolve({ ok: false, needs_verify: true, error: '본인인증 필요' });
        return Promise.resolve({ ok: true, rows: [{ a: 1 }], collected: 2, orderRows: [], trNo: 'T-' + pfx });
      },
      bgFetch: async (url, opts) => {
        if (url.indexOf('/accounts/api/crawl-login/accounts') >= 0)
          return { json: async () => ({ ok: true, accounts: ctx2ctl.accounts }) };
        if (url.indexOf('/creds') >= 0) {
          const pfx = decodeURIComponent(url.split('/crawl-login/')[1].split('/')[0]);
          return { json: async () => ({ ok: true, login_id: pfx, password: 'pw' }) };
        }
        if (url.indexOf('lotteon-crawl-run') >= 0) {
          ctx2ctl.posted = JSON.parse(opts.body).runs;
        }
        return { json: async () => ({ ok: true }) };
      },
    });
    const c2 = vm.createContext(sb2);
    vm.runInContext(slice, c2, { filename: 'settle-slice-retry.js' });
    const T2 = now = Date.UTC(2026, 7, 6, 15, 0, 0);
    store[KEY] = { on: true, min: 60, nextAt: 1, base: '', last: null, deepAt: now, hist: [] };
    vm.runInContext('settleTick()', c2); await flush(80);

    await t('실패한 계정을 회차가 **스스로 한 번 더** 돌린다(손으로 다시 누르던 일)', () => {
      assert.deepStrictEqual(seen, ['L1', 'L2', 'L3', 'L1'],
        '1차 3계정 뒤 실패한 L1 만 재시도해야 한다: ' + JSON.stringify(seen));
      assert.strictEqual(store[KEY].last.retried, 1, '재시도 횟수를 안 남겼다');
    });
    await t('재시도로 붙으면 그 계정의 결말은 ok 한 줄뿐 — 실패로도 세지 않는다(모순 금지)', () => {
      assert.strictEqual(store[KEY].last.ok, 3, '3계정 전부 성공이어야 한다: ' + JSON.stringify(store[KEY].last));
      assert.strictEqual(store[KEY].last.fail, 0, '재시도로 붙었는데 실패로 남았다');
      const l1 = ctx2ctl.posted.filter((r) => r.env_prefix === 'L1');
      assert.strictEqual(l1.length, 1, '한 계정이 두 줄로 올라갔다(화면이 성공·실패 둘 다 보게 된다)');
      assert.strictEqual(l1[0].result, 'ok', '마지막 결말이 서버에 안 갔다');
    });

    // ── 본인인증은 무인으로 못 넘긴다 — 재시도로 시간을 태우지 않는다 ──
    seen.length = 0; failOnce = new Set();
    ctx2ctl.accounts = [{ saved: true, env_prefix: 'V1', display_name: '인증' }];
    now = T2 + 61 * 60000;
    vm.runInContext('settleTick()', c2); await flush(80);
    await t('본인인증(verify) 계정은 재시도하지 않는다 — 회차 시간만 태운다', () => {
      assert.deepStrictEqual(seen, ['V1'], '인증 필요 계정을 또 돌렸다: ' + JSON.stringify(seen));
      assert.strictEqual(store[KEY].last.verify, 1);
    });

    // ── 회차 예산(25분) — 다 못 돌면 남은 계정을 「순서가 못 옴」으로 정직히 적는다 ──
    seen.length = 0;
    ctx2ctl.accounts = [{ saved: true, env_prefix: 'A1' }, { saved: true, env_prefix: 'A2' },
                        { saved: true, env_prefix: 'A3' }];
    ctx2ctl.tickMs = 13 * 60000;          // 계정당 13분 → 2계정이면 예산 초과
    const T3 = now = T2 + 122 * 60000;
    vm.runInContext('settleTick()', c2); await flush(80);
    await t('회차 예산을 넘기면 남은 계정을 「순서가 못 옴」으로 기록한다(감시에 끊겨 무기록 되던 것)', () => {
      assert.deepStrictEqual(seen, ['A1', 'A2'], '예산을 넘겼는데도 계속 돌았다: ' + JSON.stringify(seen));
      const a3 = ctx2ctl.posted.find((r) => r.env_prefix === 'A3');
      assert.ok(a3 && /순서가 못 옴/.test(a3.detail || ''),
        '못 돈 계정이 기록에 없다(어느 계정이 왜 빠졌는지 영영 모르게 된다): ' + JSON.stringify(ctx2ctl.posted));
    });
    await t('다음 회차는 굶은 계정부터 출발한다 — 뒷자리가 영영 못 도는 것 방지', () => {
      assert.strictEqual(store[KEY].startPfx, 'A3', 'startPfx 를 안 남겼다');
      seen.length = 0; ctx2ctl.tickMs = 0;
      now = store[KEY].nextAt + 60000;   // 다음 마감 이후(회차가 가짜 시간을 26분 태웠다)
      return Promise.resolve(vm.runInContext('settleTick()', c2)).then(() => flush(80)).then(() => {
        assert.strictEqual(seen[0], 'A3', '굶었던 계정이 맨 앞이 아니다: ' + JSON.stringify(seen));
        assert.strictEqual(store[KEY].startPfx, '', '다 돌았으면 출발점을 비워야 한다');
      });
    });
  }

  // ── 롯데온 전용 탭 — 재우기 금지 핀 + 잠들면 깨우기(이 사건의 근본원인) ──
  {
    const loStart = bg.indexOf('async function _loGetDedicatedTab');
    const loEnd = bg.indexOf('// SW 백업 로그아웃');
    assert.ok(loStart >= 0 && loEnd > loStart, '_loGetDedicatedTab 블록을 못 찾음');
    const pinned = [], reloaded = [];
    let tabState = { id: 5, discarded: true };
    const sb3 = {
      console,
      _LO_LOGIN_URL: 'https://store.lotteon.com/cm/main/login_SO.wsp',
      _loTabId: 5,
      _pinTab: (id) => pinned.push(id),
      waitTabComplete: async () => {},
      chrome: { tabs: {
        get: async (id) => (id === tabState.id ? tabState : null),
        reload: async (id) => { reloaded.push(id); tabState = { id: id, discarded: false }; },
        create: async () => ({ id: 9 }),
      } },
    };
    const c3 = vm.createContext(sb3);
    vm.runInContext(bg.slice(loStart, loEnd), c3, { filename: 'lo-tab-slice.js' });

    await t('잠든(discard) 롯데온 탭은 깨워서 쓴다 — 주입이 영구 대기하던 자리', async () => {
      const tb = await vm.runInContext('_loGetDedicatedTab()', c3);
      assert.deepStrictEqual(reloaded, [5], '잠든 탭을 안 깨웠다(executeScript 가 영영 안 돌아온다)');
      assert.strictEqual(tb.discarded, false, '깨운 뒤 상태를 다시 안 읽었다');
      assert.ok(pinned.indexOf(5) >= 0, '재우기 금지 핀을 다시 안 박았다');
    });
    await t('새로 만든 롯데온 탭에도 재우기 금지 핀을 박는다', async () => {
      pinned.length = 0;
      vm.runInContext('_loTabId = null;', c3);
      const tb = await vm.runInContext('_loGetDedicatedTab()', c3);
      assert.strictEqual(tb.id, 9);
      assert.deepStrictEqual(pinned, [9],
        '핀이 없으면 크롬 메모리 세이버가 이 탭을 재운다 — 2026-08-06 실패 2~3계정의 원인');
    });
  }

  // ── 무한 대기 차단 — **실제로 돌려서** 증명한다(정적 regex 로는 「진짜 안 매달리나」를 못 본다) ──
  //   2026-08-06 라이브 실패 「[이전 계정 로그아웃] 시간초과 — 4분 초과」의 정체 =
  //   잠든 탭에 건 executeScript 가 안 돌아와 계정 예산 240초를 통째로 태운 것.
  {
    const injStart = bg.indexOf('const LO_INJECT_TIMEOUT_MS');
    const injEnd = bg.indexOf('async function handleLotteonAutoLogin');
    assert.ok(injStart >= 0 && injEnd > injStart, '_loInject 블록을 못 찾음');
    const wtStart = bg.indexOf('function withTimeout');
    const wt = bg.slice(wtStart, bg.indexOf('\n}', wtStart) + 2);

    let execCalls = 0, reloads = 0;
    const sb4 = {
      console, Promise, Error, setTimeout, clearTimeout,
      _sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))),
      waitTabComplete: async () => {},
      _loWakeTab: async () => true,
      chrome: {
        scripting: { executeScript: () => { execCalls++; return new Promise(() => {}); } },  // 영영 안 끝남
        tabs: { reload: async () => { reloads++; } },
      },
    };
    const c4 = vm.createContext(sb4);
    vm.runInContext(wt + '\n' + bg.slice(injStart, injEnd), c4, { filename: 'loinject-slice.js' });

    await t('안 돌아오는 주입은 상한에서 끊고 포기한다 — 계정 예산을 통째로 태우지 않는다', async () => {
      const t0 = Date.now();
      let err = null;
      try { await vm.runInContext('_loInject(1, function(){}, [], {tries:2, timeoutMs:1000})', c4); }
      catch (e) { err = e; }
      const took = Date.now() - t0;
      assert.ok(err, '영영 안 끝나는 주입인데 성공으로 돌아왔다');
      assert.ok(/주입 응답 없음/.test(String(err.message)), '무응답을 다른 오류로 뭉갰다: ' + err.message);
      // 2회 × 1초 + 재시도 사이 여유. 부탁한 상한을 부풀리면(예전 하한 5초) 여기서 잡힌다.
      assert.ok(took < 4000, '상한을 안 지켰다(' + took + 'ms) — 이게 4분 초과의 원인이었다');
      assert.strictEqual(execCalls, 2, 'tries 만큼만 시도해야 한다');
      assert.ok(reloads >= 1, '무응답 탭을 새로 안 그렸다(다음 시도도 똑같이 매달린다)');
    });
  }
  await t('페이지 안 수집 XHR 에 timeout 이 있다 — 기본값은 무한이다', () => {
    for (const nm of ['lotteonSettleCrawlInPage', 'lotteonOrdersCrawlInPage']) {
      const s = bg.slice(bg.indexOf('function ' + nm), bg.indexOf('function ' + nm) + 4000);
      assert.ok(/x\.timeout\s*=/.test(s), nm + ' 의 XHR 에 timeout 이 없다(한 번 물리면 영영 안 끝난다)');
      assert.ok(/x\.ontimeout\s*=/.test(s), nm + ' 에 ontimeout 처리가 없다(응답이 영영 안 온다)');
      assert.ok(/_budget/.test(s), nm + ' 에 수집 루프 예산이 없다');
    }
  });

  // ── SW 재기동 부검 — 시작 도장만 남은 회차 = 도중 사망 → 정직하게 기록 ──
  //   (새 컨텍스트 = SW 가 새로 뜬 것. 슬라이스 최상위의 settleLoad().then 부검이 돈다)
  const mkCtx = () => vm.createContext(Object.assign({}, sandbox));
  const T9 = now;
  store[KEY] = { on: true, min: 60, nextAt: T9 + 3600000, base: '',
                 runStartedAt: T9 - 5 * 60000, last: { at: T9 - 65 * 60000, ok: 7, error: '' }, deepAt: T9 };
  vm.runInContext(slice, mkCtx(), { filename: 'settle-slice-restart.js' }); await flush();
  await t('SW 재기동 때 끝맺음 없는 도장이 보이면 「도중 끊김」을 기록한다(증발 금지)', () => {
    assert.ok(/재워 끊김/.test(store[KEY].last.error || ''),
      '도중 사망 기록이 없다: ' + JSON.stringify(store[KEY].last));
    assert.strictEqual(store[KEY].runStartedAt, 0, '도장을 안 지웠다');
    assert.ok(/재워 끊김/.test((store[KEY].hist && store[KEY].hist[0] || {}).error || ''),
      '도중 끊김이 이력(hist)에도 남아야 한다');
  });
  store[KEY] = { on: true, min: 60, nextAt: T9 + 3600000, base: '',
                 runStartedAt: T9 - 5 * 60000, last: { at: T9 - 60000, ok: 7, error: '' }, deepAt: T9 };
  vm.runInContext(slice, mkCtx(), { filename: 'settle-slice-restart2.js' }); await flush();
  await t('끝맺음이 도장보다 나중이면 정상 — 기록은 안 건드리고 도장만 청소', () => {
    assert.strictEqual(store[KEY].last.error, '', '멀쩡한 회차에 오류를 씌웠다');
    assert.strictEqual(store[KEY].last.ok, 7, '성공 기록을 건드렸다');
    assert.strictEqual(store[KEY].runStartedAt, 0, '도장을 안 지웠다');
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
    assert.ok(page.indexOf('회차 도는 중') >= 0,
      '「도는 중」 표시가 사라짐 — 회차 몇 분간 옛 완료 시각만 보여 멈춘 것처럼 읽힌다');
    assert.ok(page.indexOf('확장 있는 PC') >= 0,
      '확장 없는 브라우저의 카드 모순 수정이 사라짐 — 띠는 「성공 7」인데 카드는 「아직 없음」이 된다');
    assert.ok(page.indexOf('histLines') >= 0,
      '기록에 확장 자동 회차 이력 합치기가 사라짐 — 기록이 하루 통째로 비는 모순 재발');
    assert.ok(page.indexOf('dayPrefix') >= 0,
      '최근·다음 날짜 표기(오늘/어제/내일/월일)가 사라짐 — 22:40 이 어느 날인지 모른다');
    assert.ok(page.indexOf('stl-fail-strip') >= 0 && page.indexOf('cl-acc-bad') >= 0,
      '실패 강조(상단 띠·계정 카드 빨강)가 사라짐 — 실패가 작은 배지 하나에 숨는다');
    assert.ok(page.indexOf('cl-onecrawl') >= 0 && /runFullAuto\(false,\s*prefix\)/.test(page),
      '「이 계정만 수집」 단추가 사라짐 — 실패 1건에도 7계정 전체를 돌려야 한다');
  });

  console.log('\n' + pass + ' 통과 / ' + fail + ' 실패');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

// 실행: node 프로그램/_시스템/tests/js/test_reg_panel_confirm.mjs
//        (pytest 에서도 돈다 — tests/registration/test_reg_panel_render.py 가 이 파일을 부른다)
//
// ★★ [2026-07-24 4차리뷰 치명①] **화면에 확정 버튼이 실제로 그려지는지**를 고정한다.
//   지난 리뷰까지 라우트 테스트(POST …/market-confirm)만 있어서, 서버는 6마켓을 받는데
//   화면은 2마켓에만 버튼을 그리던 구멍이 그대로 통과했다. 그 4마켓(스스·쿠팡·옥션·
//   G마켓)에 남는 행동은 「다시 올리기」뿐 = 문구가 사람을 중복 등록 쪽으로 밀었다.
//   하필 상품번호를 콕 집어 주는 PARTIAL 이 옥션·G마켓 전용이라 최악의 조합이었다.
//
// 라이브 접속 없음 — bulk_manual.js 의 실제 렌더 함수를 떼어 Node 에서 돌리고 HTML 만 본다.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__d, '..', '..', 'webapp', 'static', 'bulk_manual.js');
const all = fs.readFileSync(SRC, 'utf8').split('\n');

// 실제 소스에서 필요한 조각만 그대로 떼어 온다(로직을 베끼지 않는다 — 베끼면 소스가
// 바뀌어도 테스트는 초록불이라 아무것도 못 잡는다. tests/js/test_optcost.mjs 와 같은 관례).
function cut(startsWith, endStartsWith) {
  const s = all.findIndex((l) => l.trimStart().startsWith(startsWith));
  const e = all.findIndex((l, i) => i > s && l.trimStart().startsWith(endStartsWith));
  if (s < 0 || e < 0) throw new Error(`조각을 못 찾음: ${startsWith}`);
  return all.slice(s, e).join('\n');
}

const src = [
  cut('const PRE_LABEL', 'function preflightHtml'),
  cut('function regPickRowHtml', '/* 등록 패널 = 사전점검'),
  cut('function regResultHtml', '/* 목록을 새로고침해도'),
].join('\n');

const esc = (x) => String(x == null ? '' : x).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ACCT_MKTS = ['auction', 'gmarket', 'eleven11', 'lotteon'];
// PRE_MARKET 은 떼어 온 소스 안에 이미 있다(중복 선언 금지).
const REG_LABEL = { ok: '등록됨', failed: '실패', blocked: '막힘', skipped: '건너뜀',
                    unknown: '확인 필요', already: '이미 등록됨',
                    uncertain: '확인 필요(안 보냄)' };
const REG_DOT = { ok: 'ok', failed: 'danger', blocked: 'danger', skipped: 'warn',
                  unknown: 'warn', already: 'na', uncertain: 'warn' };
const fn = new Function('esc', 'ACCT_MKTS', 'REG_LABEL', 'REG_DOT',
  `${src}\n return { regPickRowHtml, regResultHtml, PRE_LABEL, PRE_DOT };`);
const { regPickRowHtml, regResultHtml, PRE_LABEL } =
  fn(esc, ACCT_MKTS, REG_LABEL, REG_DOT);

const MARKETS = ['smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'];
const LOOKUP = ['eleven11', 'lotteon'];
const st = { keys: {}, redo: {}, checked: {} };
let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails++; } };

// ── ① 6마켓 전부: 확인 필요 행에 확정 입력칸 + 버튼이 그려진다 ──────────────
for (const m of MARKETS) {
  const row = {
    market: m, status: 'uncertain', reason: '올라갔는지 모릅니다',
    market_product_id: m === 'auction' ? 'A12345' : null,
    lookup_supported: LOOKUP.includes(m),
    confirm_supported: true, caveats: [],
  };
  const html = regPickRowHtml(row, st);
  ok(html.includes(`data-cfm="${m}"`), `${m}: 「이 상품번호로 확정」 버튼이 없다`);
  ok(html.includes(`data-cfm-input="${m}"`), `${m}: 상품번호 입력칸이 없다`);
  ok(html.includes('이 상품번호로 확정'), `${m}: 확정 버튼 문구가 없다`);
  ok(html.includes('data-redo='), `${m}: 다시 올리기 체크박스가 없다`);
  // 조회 API 가 있는 마켓만 조회 버튼(없는 마켓에 가짜 버튼 금지)
  ok(html.includes('data-lookup=') === LOOKUP.includes(m),
     `${m}: 조회 버튼 노출이 LOOKUP_MARKETS 와 다르다`);
  // 잠금 — 체크박스는 꺼진 채 비활성
  ok(html.includes('disabled'), `${m}: 확인 필요인데 체크박스가 잠기지 않았다`);
  ok(!/data-m="[^"]+" checked/.test(html), `${m}: 확인 필요인데 체크가 켜져 있다`);
}

// ── ② 상품번호를 아는 행은 그 번호가 입력칸에 미리 채워진다 ────────────────
{
  const html = regPickRowHtml({
    market: 'auction', status: 'uncertain', reason: '상품이 만들어졌습니다 (상품번호 A12345)',
    market_product_id: 'A12345', lookup_supported: false, confirm_supported: true, caveats: [],
  }, st);
  ok(html.includes('value="A12345"'), '아는 상품번호가 입력칸에 미리 안 채워졌다');
}

// ── ③ 올릴 수 있는 행에는 확정 칸이 없다(엉뚱한 자리에 확정 버튼 금지) ─────
{
  const html = regPickRowHtml({
    market: 'smartstore', status: 'ready', reason: '', caveats: [],
  }, st);
  ok(!html.includes('data-cfm='), 'ready 행에 확정 버튼이 붙었다');
  ok(!html.includes('data-redo='), 'ready 행에 다시 올리기가 붙었다');
}

// ── ④ 이미 등록된 행: 잠기고 체크 꺼짐(초록 아님) ─────────────────────────
{
  const html = regPickRowHtml({
    market: 'lotteon', status: 'registered', reason: '이미 등록돼 있습니다 (상품번호 LO1)',
    market_product_id: 'LO1', caveats: [],
  }, st);
  ok(html.includes('data-redo='), 'registered 행에 다시 올리기가 없다');
  ok(html.includes('disabled'), 'registered 행이 잠기지 않았다');
  ok(PRE_LABEL.registered === '이미 등록됨', 'registered 라벨이 바뀌었다');
}

// ── ⑤ 결과표(등록 직후)에도 6마켓 전부 확정 칸이 나온다 ────────────────────
//    화면이 status 목록 같은 **자체 조건**을 세우면 서버와 갈린다 — 판정은 서버가 준
//    confirm_supported 하나뿐이어야 한다(이번 구멍이 정확히 그 갈림이었다).
for (const m of MARKETS) {
  const body = {
    running: false, pending: [], summary: { unknown: 1 },
    rows: [{ market: m, status: 'unknown', error: '올라갔는지 모릅니다',
             market_product_id: m === 'auction' ? 'A12345' : null,
             lookup_supported: LOOKUP.includes(m), confirm_supported: true,
             notes: [], excluded: [] }],
  };
  const html = regResultHtml(body);
  ok(html.includes(`data-cfm="${m}"`), `결과표 ${m}: 확정 버튼이 없다`);
  ok(html.includes(`data-cfm-input="${m}"`), `결과표 ${m}: 상품번호 입력칸이 없다`);
}

// ── ⑥ 성공한 줄에는 확정 칸이 없다 ─────────────────────────────────────────
{
  const html = regResultHtml({
    running: false, pending: [], summary: {},
    rows: [{ market: 'lotteon', status: 'ok', market_product_id: 'LO1',
             notes: [], excluded: [] }],
  });
  ok(!html.includes('data-cfm='), '이미 성공한 줄에 확정 버튼이 붙었다');
}

if (fails) {
  console.error(`\n실패 ${fails}건`);
  process.exit(1);
}
console.log('✅ 등록 패널 렌더 고정 통과 — 6마켓 전부 확정 경로 있음');

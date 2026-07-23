// 실행: node 프로그램/_시스템/tests/js/test_reg_panel_confirm.mjs
//        (pytest 에서도 돈다 — tests/registration/test_reg_panel_render.py 가 이 파일을 부른다)
//
// ★★ [2026-07-24 4·5차리뷰] **화면이 실제로 그리는 것**을 고정한다.
//   4차: 라우트 테스트(POST …/market-confirm)만 있어서, 서버는 6마켓을 받는데 화면은
//        2마켓에만 확정 버튼을 그리던 구멍이 통과했다.
//   5차: 그마저도 **등록 패널의 두 표**만 고정해서, 목록의 「점검」 버튼으로 들어오는
//        **세 번째 화면**(preflightHtml)이 또 빠졌다. 서버 문구는 세 화면 모두에서
//        「이 상품번호로 확정」을 누르라고 말한다.
//   그래서 이 파일은 **세 화면 전부**를 본다: 점검 패널 / 등록 패널 / 결과표.
//
// 라이브 접속 없음 — bulk_manual.js 의 실제 렌더 함수를 떼어 Node 에서 돌리고 HTML 만 본다.
// ★ 상수(ACCT_MKTS·REG_LABEL·REG_DOT…)도 **소스에서 떼어 온다**(5차 S1) — 베껴 쓰면
//   소스가 바뀌어도 초록불이라 아무것도 못 잡는다(이 파일이 잡으려는 바로 그 버그다).
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__d, '..', '..', 'webapp', 'static', 'bulk_manual.js');
const all = fs.readFileSync(SRC, 'utf8').split('\n');

function cut(startsWith, endStartsWith) {
  const s = all.findIndex((l) => l.trimStart().startsWith(startsWith));
  const e = all.findIndex((l, i) => i > s && l.trimStart().startsWith(endStartsWith));
  if (s < 0 || e < 0) throw new Error(`조각을 못 찾음: ${startsWith}`);   // 이름이 바뀌면 즉사
  return all.slice(s, e).join('\n');
}

const src = [
  cut('const PRE_LABEL', 'function preflightHtml'),                // PRE_LABEL·PRE_DOT·PRE_MARKET
  cut('function confirmBoxHtml', 'async function fillPreflight'),  // 확정칸 + preflightHtml
  cut('const MKTS =', '/* 열려 있는 등록 패널'),                    // ACCT_MKTS·REG_LABEL·REG_DOT
  cut('function regPickRowHtml', '/* 등록 패널 = 사전점검'),
  cut('function regResultHtml', '/* 목록을 새로고침해도'),
].join('\n');

const esc = (x) => String(x == null ? '' : x).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// foreignAssetsHtml 은 이 테스트의 관심 밖(타 마켓 이미지 목록) — 빈 문자열로 둔다.
const foreignAssetsHtml = () => '';
const fn = new Function('esc', 'foreignAssetsHtml',
  `${src}\n return { preflightHtml, regPickRowHtml, regResultHtml, confirmBoxHtml,` +
  ` PRE_LABEL, PRE_DOT, REG_LABEL, REG_DOT };`);
const { preflightHtml, regPickRowHtml, regResultHtml,
        PRE_LABEL, REG_LABEL } = fn(esc, foreignAssetsHtml);

const MARKETS = ['smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'];
const LOOKUP = ['eleven11', 'lotteon'];
const st = { keys: {}, redo: {}, checked: {} };
let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails++; } };

const uncertainRow = (m) => ({
  market: m, status: 'uncertain', reason: '올라갔는지 모릅니다',
  market_product_id: m === 'auction' ? 'A12345' : null,
  lookup_supported: LOOKUP.includes(m), confirm_supported: true, caveats: [],
});

// ── ① 등록 패널: 6마켓 전부 확정칸 ─────────────────────────────────────────
for (const m of MARKETS) {
  const html = regPickRowHtml(uncertainRow(m), st);
  ok(html.includes(`data-cfm="${m}"`), `등록패널 ${m}: 확정 버튼이 없다`);
  ok(html.includes(`data-cfm-input="${m}"`), `등록패널 ${m}: 상품번호 입력칸이 없다`);
  ok(html.includes('data-redo='), `등록패널 ${m}: 다시 올리기 체크박스가 없다`);
  ok(html.includes('data-lookup=') === LOOKUP.includes(m),
     `등록패널 ${m}: 조회 버튼 노출이 LOOKUP_MARKETS 와 다르다`);
  ok(html.includes('disabled'), `등록패널 ${m}: 확인 필요인데 체크박스가 잠기지 않았다`);
  ok(!/data-m="[^"]+" checked/.test(html), `등록패널 ${m}: 확인 필요인데 체크가 켜져 있다`);
}

// ── ② 「점검」 패널(세 번째 화면)도 6마켓 전부 확정칸 ───────────────────────
//    서버 문구가 이 화면에서도 「이 상품번호로 확정」을 누르라고 말한다.
for (const m of MARKETS) {
  const html = preflightHtml(77, [uncertainRow(m)]);
  ok(html.includes(`data-cfm="${m}"`), `점검패널 ${m}: 확정 버튼이 없다`);
  ok(html.includes(`data-cfm-input="${m}"`), `점검패널 ${m}: 상품번호 입력칸이 없다`);
  ok(html.includes('data-cfm-draft="77"'), `점검패널 ${m}: 드래프트 id 가 안 실렸다`);
  ok(html.includes('data-lookup=') === LOOKUP.includes(m),
     `점검패널 ${m}: 조회 버튼 노출이 LOOKUP_MARKETS 와 다르다`);
}
{
  const html = preflightHtml(77, [{ market: 'smartstore', status: 'ready', caveats: [] }]);
  ok(!html.includes('data-cfm='), '점검패널: 올릴 수 있는 줄에 확정 버튼이 붙었다');
}

// ── ③ 결과표도 6마켓 전부 ──────────────────────────────────────────────────
for (const m of MARKETS) {
  const html = regResultHtml({
    running: false, pending: [], summary: { unknown: 1 },
    rows: [{ market: m, status: 'unknown', error: '올라갔는지 모릅니다',
             market_product_id: m === 'auction' ? 'A12345' : null,
             lookup_supported: LOOKUP.includes(m), confirm_supported: true,
             notes: [], excluded: [] }],
  });
  ok(html.includes(`data-cfm="${m}"`), `결과표 ${m}: 확정 버튼이 없다`);
  ok(html.includes(`data-cfm-input="${m}"`), `결과표 ${m}: 상품번호 입력칸이 없다`);
}

// ── ④ 확정칸의 규칙은 **confirm_supported 하나뿐**이다 ─────────────────────
//    [5차 I2] 예전엔 등록 패널이 확정칸을 「다시 올리기」 안에 끼워 넣어, 실제 규칙이
//    `confirm_supported AND status ∈ {registered, uncertain}` 이었다 — 주석·커밋이
//    말하는 규칙과 갈렸다. status 가 그 둘이 아닌 행으로 그 갈림을 잡는다.
for (const status of ['missing', 'blocked', 'need_category']) {
  const r = { market: 'coupang', status, reason: '값이 없습니다',
              confirm_supported: true, caveats: [] };
  ok(regPickRowHtml(r, st).includes('data-cfm="coupang"'),
     `등록패널: status=${status} + confirm_supported 인데 확정칸이 없다(규칙이 둘이다)`);
  ok(preflightHtml(1, [r]).includes('data-cfm="coupang"'),
     `점검패널: status=${status} + confirm_supported 인데 확정칸이 없다`);
}
for (const status of ['uncertain', 'registered', 'ready']) {
  const r = { market: 'coupang', status, reason: '', confirm_supported: false, caveats: [] };
  ok(!regPickRowHtml(r, st).includes('data-cfm='),
     `등록패널: confirm_supported=false 인데 확정칸이 붙었다(status=${status})`);
  ok(!preflightHtml(1, [r]).includes('data-cfm='),
     `점검패널: confirm_supported=false 인데 확정칸이 붙었다(status=${status})`);
}

// ── ⑤ 아는 상품번호는 입력칸에 미리 채운다 / 성공한 줄엔 확정칸 없음 ────────
{
  const html = regPickRowHtml(uncertainRow('auction'), st);
  ok(html.includes('value="A12345"'), '아는 상품번호가 입력칸에 미리 안 채워졌다');
  const done = regResultHtml({
    running: false, pending: [], summary: {},
    rows: [{ market: 'lotteon', status: 'ok', market_product_id: 'LO1',
             notes: [], excluded: [] }],
  });
  ok(!done.includes('data-cfm='), '이미 성공한 줄에 확정 버튼이 붙었다');
}

// ── ⑥ 상태 라벨이 한글이다(장부 상태가 날것으로 새지 않는다) ───────────────
ok(PRE_LABEL.registered === '이미 등록됨', 'registered 라벨이 바뀌었다');
ok(PRE_LABEL.uncertain === '확인 필요', 'uncertain 라벨이 바뀌었다');
ok(REG_LABEL.unknown === '확인 필요', '결과표 unknown 라벨이 바뀌었다');
ok(REG_LABEL.already === '이미 등록됨', '결과표 already 라벨이 바뀌었다');

if (fails) {
  console.error(`\n실패 ${fails}건`);
  process.exit(1);
}
console.log('✅ 화면 렌더 고정 통과 — 점검·등록·결과 세 화면 모두 6마켓 확정 경로 있음');

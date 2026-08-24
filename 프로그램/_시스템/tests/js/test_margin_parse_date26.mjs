// 실행: node 프로그램/_시스템/tests/js/test_margin_parse_date26.mjs
//
// 마진계산기(margin_embed.html) — 날짜 필터가 「초기값 대비 날짜를 바꾸면」 아예 안 먹는 버그.
//
// 🔴 근본 원인 — `parseDate26(s)`는 더망고 엑셀의 옛 표기('26.04.08', 점 구분)만 파싱한다.
//   그런데 모음전 자체 API로 「분석 시작」했을 때의 `주문일` 필드는 실제로
//   '2026-08-23 20:52:02'(대시+시분초) 형식이다 — 점이 없으니 split('.').length !== 3 이라
//   **항상 빈 문자열**을 돌려준다. 그 결과:
//     · autoSetDateRange() 가 dateFrom/dateTo 를 못 채운다(초기값이 빈칸으로 보임)
//     · getFilteredData() 의 `if (d) {...}` 날짜 비교 자체가 실행이 안 돼 필터가 완전 무시된다
//     · daily/monthly/기간평균배너 등 parseDate26 를 쓰는 16곳 전부 같은 증상
//   라이브 재현(2026-08-24): dateFrom=dateTo='2026-08-23'로 필터해도 매칭 1667건(=사실상 전체)
//   그대로 남았고, 일별 탭은 "기간 1일" 배너 밑에 "일별 마진 (23일)" 표가 그대로 떴다
//   (일평균 매출 8,081만원처럼 전체 합계를 1일로 나눠 말도 안 되는 숫자가 나옴).
//
// 이 시험은 실제 원문(진짜 parseDate26)을 template에서 그대로 떼어와 Node 에서 돌린다.
// 마지막 뮤테이션으로 「이 시험이 그 버그를 실제로 잡는지」까지 실증한다(선례: test_orders_margin_cell.mjs).
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'orders', 'margin_embed.html');
const SRC = fs.readFileSync(TPL, 'utf8').replace(/\r\n/g, '\n');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } else { console.log('  ✅', msg); } };

/** `function 이름(...) { … }` 원문을 중괄호 짝으로 떼어 온다. 사라지면 즉사(베껴 쓰기 금지). */
function extract(name, src = SRC) {
  const m = new RegExp('^\\s*function\\s+' + name + '\\s*\\(', 'm').exec(src);
  if (!m) throw new Error(`${name}() 이(가) margin_embed.html 에 없습니다 — 배선이 사라졌습니다`);
  const i = src.indexOf('{', m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j += 1) {
    if (src[j] === '{') depth += 1;
    else if (src[j] === '}') { depth -= 1; if (depth === 0) return src.slice(m.index, j + 1); }
  }
  throw new Error(`${name}() 의 중괄호 짝이 안 맞습니다`);
}

function load(src) {
  // eslint-disable-next-line no-new-func
  const fn = new Function(`${extract('parseDate26', src)}\nreturn parseDate26;`);
  return fn();
}

const parseDate26 = load(SRC);

// ── 실제 라이브 데이터 형식(모음전 API 「분석 시작」 경로) ──
ok(parseDate26('2026-08-23 20:52:02') === '2026-08-23',
   '모음전 API 주문일(대시+시분초) 파싱 — 라이브 실측 형식');
ok(parseDate26('2026-01-05 09:00:00') === '2026-01-05',
   '월/일이 한 자리로 안 깨지는지(0패딩 유지)');
ok(parseDate26('2026-08-23') === '2026-08-23',
   '시분초 없는 순수 ISO 날짜도 파싱');

// ── 레거시 형식(더망고 엑셀 업로드 경로) — 회귀 방지, 계속 지원돼야 한다 ──
ok(parseDate26('26.04.08') === '2026-04-08',
   '레거시 더망고 엑셀 표기(점 구분)는 계속 지원');

// ── 빈 값/이상값 — 날조 금지, 빈 문자열로 ──
ok(parseDate26('') === '', '빈 문자열 입력 → 빈 문자열');
ok(parseDate26(null) === '', 'null 입력 → 빈 문자열(예외 없이)');
ok(parseDate26('알수없음') === '', '날짜로 못 읽는 문자열 → 빈 문자열(지어내지 않음)');

// ══════════════════════════════════════════════════════════════════
// 뮤테이션 — 이 시험이 실제로 그 버그(모음전 API 형식 파싱 실패)를 잡는지 실증
// ══════════════════════════════════════════════════════════════════
const BROKEN = `function parseDate26(s) {
  try {
    var p = String(s).trim().split('.');
    if (p.length === 3) return '20' + p[0] + '-' + p[1] + '-' + p[2];
  } catch(e) {}
  return '';
}`;
const mutated = SRC.replace(extract('parseDate26'), BROKEN);
if (mutated === SRC) throw new Error('뮤테이션이 parseDate26 을 못 바꿨습니다 — 시험이 무효입니다');
const brokenFn = load(mutated);
ok(brokenFn('2026-08-23 20:52:02') === '',
   '[뮤테이션] 옛 코드는 모음전 API 주문일을 못 읽고 빈 문자열을 돌린다 — 이 시험이 그걸 잡는다');

console.log(fails ? `\n❌ 실패 ${fails}건` : '\n✅ 전부 통과');
process.exit(fails ? 1 : 0);

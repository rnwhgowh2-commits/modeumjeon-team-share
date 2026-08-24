// 실행: node 프로그램/_시스템/tests/js/test_margin_download_payload.mjs
//
// 마진계산기(margin_embed.html) — "엑셀 다운로드"가 화면 날짜필터를 무시하던 버그.
//
// 🔴 근본 원인 — 일반 다운로드 버튼(대부분의 탭)이 analysis_id 만 보내 서버가
//   "분석 시작" 시점 DB 저장분(전체기간)을 다시 불러왔다. 화면에서 날짜를 좁히거나
//   행을 제외·수정해도 다운로드에는 전혀 반영 안 되고 매번 전체기간이 나왔다
//   (라이브 실측 2026-08-24: webapp/routes/api_margin.py export_route 가 body 에서
//    excluded_ids·matched 를 아예 안 읽는 것 확인, grep 0건).
//
// 수정 — downloadExcel() 이 화면의 getFilteredData() 결과를 `payload` 로 실어 보내고,
//   서버(export_route)는 payload 가 오면 DB 재조회 없이 그대로 쓴다(백엔드 검증은
//   tests/margin/test_api_margin.py::test_export_with_payload_overrides_stored_analysis).
//   이 파일은 프론트가 payload 를 만들 때 쓰는 `_stripInternalKeys` 헬퍼(UI 내부
//   키 `_idx`·`_excluded` 등이 그대로 엑셀 열로 새지 않게)를 실제 원문으로 검증한다.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'orders', 'margin_embed.html');
const SRC = fs.readFileSync(TPL, 'utf8').replace(/\r\n/g, '\n');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } else { console.log('  ✅', msg); } };

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

function load(name, src = SRC) {
  // eslint-disable-next-line no-new-func
  const fn = new Function(`${extract(name, src)}\nreturn ${name};`);
  return fn();
}

const stripInternalKeys = load('_stripInternalKeys');

const rows = [
  { 주문일: '2026-08-23', 상품명: '코트', 매출: 50000, _idx: 3, _excluded: false, _주문미이행: true },
  { 주문일: '2026-08-24', 상품명: '셔츠', 매출: 30000, _edited: true, _orig_정산예상금액: 1000 },
];
const out = stripInternalKeys(rows);

ok(out.length === 2, '행 개수 보존');
ok(Object.keys(out[0]).sort().join(',') === '매출,상품명,주문일',
   '언더스코어 키(_idx·_excluded·_주문미이행) 전부 제거, 기명 필드만 남음');
ok(Object.keys(out[1]).sort().join(',') === '매출,상품명,주문일',
   '두번째 행도 동일(_edited·_orig_정산예상금액 제거)');
ok(out[0]['주문일'] === '2026-08-23' && out[0]['매출'] === 50000,
   '남은 필드 값은 원본 그대로(변형 없음)');
ok(stripInternalKeys(null) === null && stripInternalKeys(undefined) === undefined,
   '배열이 아니면 그대로 반환(예외 없이) — unmatched_buy/sell 이 빈 배열/undefined 일 수 있음');
ok(JSON.stringify(rows[0]).includes('_idx'),
   '원본 rows 는 변형되지 않음(map 이지 in-place 아님)');

// ── 뮤테이션 — 이 시험이 실제로 「언더스코어 키가 샌다」를 잡는지 실증 ──
const BROKEN = `function _stripInternalKeys(rows) { return rows; }`;
const mutated = SRC.replace(extract('_stripInternalKeys'), BROKEN);
if (mutated === SRC) throw new Error('뮤테이션이 _stripInternalKeys 를 못 바꿨습니다 — 시험이 무효입니다');
const brokenFn = load('_stripInternalKeys', mutated);
ok(Object.keys(brokenFn(rows)[0]).indexOf('_idx') >= 0,
   '[뮤테이션] 아무 것도 안 거르는 옛 코드는 _idx 가 그대로 샌다 — 이 시험이 그걸 잡는다');

console.log(fails ? `\n❌ 실패 ${fails}건` : '\n✅ 전부 통과');
process.exit(fails ? 1 : 0);

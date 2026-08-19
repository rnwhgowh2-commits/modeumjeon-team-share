// 실행: node 프로그램/_시스템/tests/js/test_matrix_grid_model_axis.mjs
//
// 격자 4안 — 모델을 **가로축**으로 (2026-08-13 사장님 확정).
//
// 왜 이 시험이 있나
//   격자는 오래 「색상 × 사이즈」 두 축뿐이었다. 모델모음전(모델·색상·사이즈)에서는
//   모델이 달라도 (색,사이즈)가 같으면 **한 칸에 겹쳐** 옵션이 사라져 보였다
//   (실측: 3축 옵션 3개 → 격자 2칸 · 담은 조합도 2개가 1개로 세어졌다).
//   4안은 가로를 「모델 × 사이즈」로 세워 겹침 자체를 없앤다.
//
//   🔴 이 로직은 **브라우저에서만** 도는 곳이라 파이썬 시험이 못 잡는다.
//      실제 템플릿에서 코드를 떼어 Node 에서 돌린다(test_optcost.mjs 와 같은 방식).
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__d, '..', '..', 'webapp', 'templates', 'matrix', 'detail.html');
const html = fs.readFileSync(SRC, 'utf8');

// ── 템플릿에서 build() 와 열쇠 규칙만 떼어낸다 ────────────────────────
const keyLine = html.match(/const KEY = [^\n]+/);
const buildSrc = html.match(/function build\(\)\{[\s\S]*?\n\}/);
if (!keyLine || !buildSrc) {
  console.error('🔴 KEY 또는 build() 를 못 찾음 — 템플릿 구조가 바뀌었다');
  process.exit(1);
}

// ── 3축 모델모음전 자료 (모델 2 × 색 2 × 사이즈 2, 한 칸은 없음) ──────
const ROWS = [
  { sku: 'S1', model: '메이트', color: '블랙', size: '250', src_count: 1 },
  { sku: 'S2', model: '메이트', color: '블랙', size: '260', src_count: 1 },
  { sku: 'S3', model: '메이트', color: '크림', size: '250', src_count: 2 },
  { sku: 'S4', model: '스위트', color: '블랙', size: '250', src_count: 1 },
  { sku: 'S5', model: '스위트', color: '블랙', size: '260', src_count: 1 },
  { sku: 'S6', model: '스위트', color: '크림', size: '250', src_count: 3 },
];
const COLORS = ['블랙', '크림'];
const SIZES = ['250', '260'];
const MODELS = ['메이트', '스위트'];

// 최소 껍데기 — 실제 화면이 주는 것과 같은 모양
const mx = { innerHTML: '', querySelectorAll: () => [] };
const sel = new Set();
const MADE_SKUS = new Set();
const CANPICK = true;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

let byKey = {};
const KEY = eval('(' + keyLine[0].replace('const KEY = ', '').replace(/;\s*$/, '') + ')');
function reindex() {
  byKey = {};
  ROWS.forEach((r) => (byKey[KEY(r.model, r.color, r.size)] = r));
}
reindex();

// build() 를 그대로 실행 (arm/upd 는 안 쓰는 부분이라 잘라낸다).
// ESM 은 엄격 모드라 eval 안의 함수 선언이 밖으로 안 새 나온다 → 식으로 받아 쓴다.
const body = buildSrc[0].replace(/mx\.querySelectorAll[\s\S]*$/, '}');
const build = eval('(' + body + ')');
build();
const out = mx.innerHTML;

// ── 검사 ──────────────────────────────────────────────────────────────
const checks = [];
const 칸수 = (out.match(/<td /g) || []).length;
checks.push(['모델만 다른 옵션이 안 겹친다 (칸 = 모델2 × 색2 × 사이즈2 = 8)', 칸수 === 8, 칸수]);
checks.push(['모델이 가로 머리줄로 선다 (colspan 묶음 2개)',
  (out.match(/class="mxgrp/g) || []).length === 2]);
checks.push(['모델 이름이 머리줄에 보인다', out.includes('메이트') && out.includes('스위트')]);
checks.push(['색상 칸이 붙박이다 (mxstick)', (out.match(/mxstick/g) || []).length >= 3]);
checks.push(['없는 조합은 회색 칸', (out.match(/class="none"/g) || []).length === 2]);
checks.push(['옵션 6개가 전부 자기 칸을 가진다',
  ROWS.every((r) => out.includes('data-sku="' + r.sku + '"'))]);

// 모델이 하나면 예전 그대로 (색상모음전 회귀 방지)
ROWS.length = 3;
ROWS[0] = { sku: 'A', model: null, color: '블랙', size: '250', src_count: 1 };
ROWS[1] = { sku: 'B', model: null, color: '블랙', size: '260', src_count: 1 };
ROWS[2] = { sku: 'C', model: null, color: '크림', size: '250', src_count: 1 };
MODELS.length = 0;
reindex();
build();
const out2 = mx.innerHTML;
checks.push(['모델 축이 없으면 예전 그대로 (색상＼사이즈)', out2.includes('색상＼사이즈')]);
checks.push(['그때는 모델 묶음 머리줄이 없다', !out2.includes('mxgrp')]);

let bad = 0;
for (const [name, ok, got] of checks) {
  console.log((ok ? '  OK   ' : '  🔴 FAIL ') + name + (ok ? '' : '  (실제: ' + got + ')'));
  if (!ok) bad++;
}
console.log(bad ? `\n${bad}건 실패` : `\n${checks.length}건 전부 통과`);
process.exit(bad ? 1 : 0);

// -*- coding: utf-8 -*-
// 크롤 가이드 §5 에러이력 — 글자에 별표·백틱이 그대로 보이던 것 (2026-08-12 라이브 실측)
//
// 무엇이 문제였나
//   카탈로그(error_catalog.json)의 증상·원인·재발방지 글은 원문(.md)과 **같은 표기**를 쓴다.
//   그런데 보기 화면은 esc() 로 막기만 하고 표기를 안 살려서, 화면에 별 두 개와
//   백틱이 글자 그대로 떴다 — 라이브 실측 18항목 · 19줄.
//
// 여기서 못 박는 것
//   ① `코드` → <code> · **굵게** → <strong> 으로 살아난다
//   ② 🔴 그래도 남의 HTML 은 절대 실행되지 않는다 (막기가 먼저, 표기는 나중)
//   ③ 🔴 진짜 카탈로그 93건을 통과시켜 **화면에 별표가 한 줄도 안 남는다**
//      — 이 검사가 「눈으로 보는 것」이다. 함수만 맞고 데이터가 어긋나면 화면은 그대로 깨진다.
//
// 로직 사본 금지: map.html 의 esc()·rich() 를 **파일에서 잘라** 그대로 돌린다.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  OK  ' + name); pass++; }
  catch (e) { console.log('  FAIL ' + name + ' - ' + e.message); fail++; }
}

const ROOT = path.join(__dirname, '..', '..');
const HTML = fs.readFileSync(
  path.join(ROOT, 'webapp', 'templates', 'sourcing_guide', 'map.html'), 'utf8');

// map.html 에서 함수 하나를 중괄호 균형으로 잘라 온다
function grab(name) {
  const i = HTML.indexOf('function ' + name + '(');
  if (i < 0) throw new Error(name + '() 를 map.html 에서 못 찾았다 — 이름이 바뀌었나?');
  let depth = 0, started = false, j = i;
  for (; j < HTML.length; j++) {
    const c = HTML[j];
    if (c === '{') { depth++; started = true; }
    else if (c === '}') { depth--; if (started && depth === 0) { j++; break; } }
  }
  return HTML.slice(i, j);
}

const api = new Function(grab('esc') + '\n' + grab('rich') +
                         '\nreturn {esc: esc, rich: rich};')();
const rich = api.rich;

// ── ① 표기가 살아난다 ────────────────────────────────────────────────
t('굵게가 굵게로 나온다', () => {
  assert.strictEqual(rich('축을 **모델** 로'), '축을 <strong>모델</strong> 로');
});

t('백틱이 코드 칸으로 나온다', () => {
  assert.strictEqual(rich('`axis_slot.py` 하나'), '<code>axis_slot.py</code> 하나');
});

t('한 줄에 둘 다 있어도 된다', () => {
  assert.strictEqual(rich('**이름**은 `semantic_slots` 가'),
                     '<strong>이름</strong>은 <code>semantic_slots</code> 가');
});

// ── ② 남의 HTML 은 실행되지 않는다 ──────────────────────────────────
t('꺾쇠는 여전히 글자로 막힌다', () => {
  assert.strictEqual(rich('<script>alert(1)</script>'),
                     '&lt;script&gt;alert(1)&lt;/script&gt;');
});

t('굵게 안에 든 태그도 막힌다', () => {
  assert.strictEqual(rich('**<b>x</b>**'), '<strong>&lt;b&gt;x&lt;/b&gt;</strong>');
});

t('앰퍼샌드가 두 번 바뀌지 않는다', () => {
  assert.strictEqual(rich('A & B'), 'A &amp; B');
});

t('본문의 $& 가 삼켜지지 않는다', () => {
  // 치환값을 문자열로 넣으면 $& 가 「찾은 것 전체」로 바뀌어 글이 뒤틀린다
  assert.strictEqual(rich('**$& 그대로**'), '<strong>$&amp; 그대로</strong>');
});

// ── 짝이 안 맞는 표기는 건드리지 않는다 ─────────────────────────────
t('짝 없는 별표는 그대로 둔다', () => {
  assert.strictEqual(rich('별 ** 하나'), '별 ** 하나');
});

t('빈 값도 터지지 않는다', () => {
  assert.strictEqual(rich(null), '');
  assert.strictEqual(rich(undefined), '');
});

// ── ③ 진짜 카탈로그로 — 화면에 별표가 한 줄도 안 남아야 한다 ────────
t('카탈로그 전건에 별표·백틱이 남지 않는다', () => {
  const cat = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'webapp', 'static', 'error_catalog.json'), 'utf8'));
  const items = cat.items || [];
  assert.ok(items.length > 50, '카탈로그가 비었다 — 검사가 헛돈다 (' + items.length + '건)');

  const bad = [];
  items.forEach(e => {
    ['sy', 'cz', 'pv'].forEach(k => {
      const out = rich(e[k]);
      if (/\*\*/.test(out) || /`/.test(out)) bad.push(e.id + '.' + k + ' → ' + out.slice(0, 70));
    });
  });
  assert.deepStrictEqual(bad, [],
    '화면에 표기가 글자로 남는다 (짝이 안 맞는 별표·백틱):\n  ' + bad.join('\n  '));
});

t('실제로 살아나는 항목이 있다 (검사가 헛돌지 않는다)', () => {
  const cat = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'webapp', 'static', 'error_catalog.json'), 'utf8'));
  const n = (cat.items || []).filter(
    e => ['sy', 'cz', 'pv'].some(k => /<strong>|<code>/.test(rich(e[k])))).length;
  assert.ok(n >= 10, '표기가 살아난 항목이 ' + n + '개뿐 — 데이터나 함수가 어긋났다');
});

console.log('\n통과 ' + pass + ' / 실패 ' + fail);
process.exit(fail ? 1 : 0);

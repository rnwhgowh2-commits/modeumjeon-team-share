// 실행: node 프로그램/_시스템/tests/js/test_policy_attach_wiring.mjs
//        (pytest 에서도 돈다 — tests/registration/test_policy_attach_render.py 가 부른다)
//
// ★★ [2026-07-24 리뷰 ⑧] **버튼이 죽었는지**를 잡는다.
//   앞선 테스트는 서버가 뱉은 HTML 문자열만 봐서, 상세 화면의 「떼기」·「+ 마켓 추가」
//   배선을 통째로 끊어 **죽은 버튼**으로 만들어도 전부 초록불이었다.
//   그래서 여기서는 템플릿 안 **실제 소스 조각을 떼어 Node 에서 실행**하고,
//   버튼을 진짜로 눌러 어떤 요청이 나가는지 본다(선례: test_reg_panel_confirm.mjs).
//
// DOM 라이브러리가 없는 저장소라 필요한 만큼만 흉내 낸다(아래 미니 DOM).
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __d = path.dirname(fileURLToPath(import.meta.url));
const TPL = path.join(__d, '..', '..', 'webapp', 'templates', 'bulk');
const DETAIL = fs.readFileSync(path.join(TPL, 'policy_detail.html'), 'utf8');
const LIST = fs.readFileSync(path.join(TPL, 'partials', '_process.html'), 'utf8');

let fails = 0;
const ok = (cond, msg) => { if (!cond) { console.error('❌', msg); fails += 1; } };

/** 두 표시줄 사이의 원문을 떼어 온다. 표시줄이 사라지면 즉사한다(베껴 쓰기 금지). */
function cut(src, startsWith, endStartsWith, what) {
  const all = src.split('\n');
  const s = all.findIndex((l) => l.trimStart().startsWith(startsWith));
  const e = all.findIndex((l, i) => i > s && l.trimStart().startsWith(endStartsWith));
  if (s < 0 || e < 0) throw new Error(`${what} 조각을 못 찾음: ${startsWith}`);
  return all.slice(s, e).join('\n');
}

// ══ 미니 DOM ═══════════════════════════════════════════════════
//   지원: getElementById / querySelector(All) / insertAdjacentHTML / remove /
//         dataset / textContent / className / addEventListener('click') / closest
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

class El {
  constructor(tag, attrs = {}) {
    this.tag = tag;
    this.attrs = attrs;
    this.children = [];
    this.parent = null;
    this.text = '';
    this.listeners = [];
    this.onclick = null;
    this.value = attrs.value || '';
    this.dataset = {};
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith('data-')) {
        this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
      }
    }
  }
  get className() { return this.attrs.class || ''; }
  set className(v) { this.attrs.class = v; }
  get classes() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
  get textContent() {
    return this.text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(v) { this.text = String(v); this.children = []; }
  get innerHTML() { return this._html || ''; }
  set innerHTML(v) { this._html = v; this.children = parseNodes(v, this); }
  append(node) { node.parent = this; this.children.push(node); }
  remove() {
    if (!this.parent) return;
    this.parent.children = this.parent.children.filter((c) => c !== this);
    this.parent = null;
  }
  hasAttribute(n) { return this.attrs[n] !== undefined; }
  removeAttribute(n) { delete this.attrs[n]; }
  focus() { this.removeAttribute('readonly'); }
  addEventListener(type, fn) { if (type === 'click') this.listeners.push(fn); }
  insertAdjacentHTML(pos, html) {
    const nodes = parseNodes(html, pos === 'beforebegin' ? this.parent : this);
    if (pos === 'beforeend') { nodes.forEach((n) => this.append(n)); return; }
    if (pos === 'beforebegin') {
      const p = this.parent;
      const i = p.children.indexOf(this);
      nodes.forEach((n) => { n.parent = p; });
      p.children.splice(i, 0, ...nodes);
      return;
    }
    throw new Error('안 만든 위치: ' + pos);
  }
  matches(sel) {
    if (sel.startsWith('#')) return this.attrs.id === sel.slice(1);
    if (sel.startsWith('[')) return this.hasAttribute(sel.slice(1, -1));
    return sel.split('.').filter(Boolean).every((c) => this.classes.includes(c));
  }
  closest(sel) {
    let n = this;
    while (n) { if (n.matches(sel)) return n; n = n.parent; }
    return null;
  }
  descendants() {
    const out = [];
    const walk = (n) => n.children.forEach((c) => { out.push(c); walk(c); });
    walk(this);
    return out;
  }
  querySelectorAll(sel) {
    const parts = sel.trim().split(/\s+/);
    const last = parts[parts.length - 1];
    return this.descendants().filter((n) => {
      if (!n.matches(last)) return false;
      let p = n.parent;
      for (let i = parts.length - 2; i >= 0; i -= 1) {
        while (p && !p.matches(parts[i])) p = p.parent;
        if (!p) return false;
        p = p.parent;
      }
      return true;
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

/** 아주 작은 HTML 파서 — 이 화면이 만들어 내는 모양(div/span/button)만 다룬다. */
function parseNodes(html, parent) {
  const out = [];
  const stack = [];
  const re = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[a-zA-Z-]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const [, close, tag, attrStr, selfClose, textChunk] = m;
    const cur = stack[stack.length - 1];
    if (textChunk !== undefined) {
      const t = textChunk.replace(/\s+/g, ' ');
      if (cur && t.trim()) cur.text += t;
      continue;
    }
    if (close) { stack.pop(); continue; }
    const attrs = {};
    const ar = /([a-zA-Z-]+)(?:="([^"]*)")?/g;
    let a;
    while ((a = ar.exec(attrStr || '')) !== null) attrs[a[1]] = a[2] === undefined ? '' : a[2];
    const el = new El(tag, attrs);
    if (cur) { el.parent = cur; cur.children.push(el); } else { el.parent = parent; out.push(el); }
    if (!selfClose && !['input', 'br', 'img'].includes(tag)) stack.push(el);
  }
  return out;
}

function makeDoc(root) {
  return {
    root,
    getElementById(id) { return root.querySelectorAll(`#${id}`)[0] || (root.attrs.id === id ? root : null); },
    querySelectorAll(sel) { return root.querySelectorAll(sel); },
    querySelector(sel) { return root.querySelector(sel); },
  };
}

/** 진짜 클릭처럼 — 자기 onclick 을 부르고 조상까지 거슬러 올라간다(위임 배선 확인). */
function click(node) {
  const e = { target: node };
  if (node.onclick) node.onclick(e);
  let n = node;
  while (n) { n.listeners.forEach((fn) => fn(e)); n = n.parent; }
}

const nextTick = () => new Promise((r) => setTimeout(r, 0));

// ══ ① 정책 상세 — 「+ 마켓 추가」·「떼기」가 살아 있나 ═════════
function buildDetailDom() {
  const page = new El('div', { id: 'page' });
  page.innerHTML = `
    <div class="pd-miss" id="pd-nomkt">내보낼 마켓이 없습니다</div>
    <div class="pd-grid" id="pd-grid">
      <div class="pd-card">
        <h3>가져오는 곳 <b id="pd-srccnt">1</b></h3>
        <div id="pd-srcs">
          <div class="pd-line" data-src="musinsa" data-brand="나이키"
               data-url="https://www.musinsa.com/brand/nike">
            <span class="chip src">musinsa &gt; 나이키</span>
            <button class="pd-off" data-off="source">떼기</button>
          </div>
        </div>
        <div class="pd-msg" id="pd-srcmsg"></div>
      </div>
      <div class="pd-card">
        <h3>내보내는 곳 <b id="pd-mktcnt">0</b></h3>
        <div id="pd-mkts"><span class="chip none">아직 없음</span></div>
        <select id="pd-addmkt"></select>
        <input id="pd-addacc" readonly>
        <button id="pd-addbtn">+ 마켓 추가</button>
        <div class="pd-msg" id="pd-mktmsg"></div>
      </div>
    </div>
    <p><span id="pd-subsrc">1</span><span id="pd-submkt">0</span></p>
    <div id="pd-rules">규칙 편집 중인 값(건드리면 안 됨)</div>`;
  return page;
}

function runDetail(opts) {
  const src = cut(DETAIL, '// ── 붙은 소싱처·마켓 손보기', 'function load()', '상세');
  const page = buildDetailDom();
  const document = makeDoc(page);
  const calls = [];
  const asked = [];
  const fetchStub = (url, init) => {
    calls.push({ url, method: (init && init.method) || 'GET',
                 body: init && init.body ? JSON.parse(init.body) : null });
    const j = opts.reply(url, init);
    return Promise.resolve({ status: j.__status || 200, json: () => Promise.resolve(j) });
  };
  const win = { confirm: (m) => { asked.push(m); return opts.confirm !== false; } };
  let loadCalled = 0;
  const fn = new Function(
    'document', 'window', 'fetch', 'esc', 'MARKET_LABELS', 'MARKETS', 'market',
    'POLICY_ID', 'schema', 'renderMarketSelect', 'load',
    `${src}\n return { addMarket, detachSource, detachMarket };`);
  fn(document, win, fetchStub, esc, { coupang: '쿠팡', smartstore: '스마트스토어' },
     opts.markets || [], opts.market || '', 7, {}, () => {}, () => { loadCalled += 1; });
  return { page, document, calls, asked, loadCount: () => loadCalled };
}

// ── ①-1 「+ 마켓 추가」가 죽어 있지 않다 ─────────────────────
{
  const t = runDetail({ reply: () => ({ ok: true, market: 'coupang', account_key: '본계정',
                                        message: '붙였습니다.' }) });
  const btn = t.document.getElementById('pd-addbtn');
  ok(typeof btn.onclick === 'function', '「+ 마켓 추가」 버튼에 배선이 없다(죽은 버튼)');

  t.document.getElementById('pd-addmkt').value = 'coupang';
  t.document.getElementById('pd-addacc').value = '본계정';
  const rulesBefore = t.document.getElementById('pd-rules').textContent;
  click(btn);
  await nextTick();

  ok(t.calls.length === 1, '버튼을 눌렀는데 서버로 아무 요청도 안 갔다');
  ok(t.calls[0].url === '/bulk/api/process/policies/7/markets'
     && t.calls[0].method === 'POST', `엉뚱한 요청: ${JSON.stringify(t.calls[0])}`);
  ok(t.calls[0].body.market === 'coupang' && t.calls[0].body.account_key === '본계정',
     '고른 마켓·계정이 그대로 안 갔다');

  const lines = t.document.querySelectorAll('#pd-mkts .pd-line');
  ok(lines.length === 1, '붙였는데 화면에 줄이 안 생겼다');
  ok(lines[0].dataset.market === 'coupang', '새 줄에 마켓 표시가 없다');
  ok(lines[0].querySelector('.pd-off') !== null, '새 줄에 「떼기」가 없다');
  ok(t.document.getElementById('pd-mktcnt').textContent === '1', '마켓 개수가 안 늘었다');
  ok(t.document.getElementById('pd-nomkt') === null,
     '마켓을 붙였는데 「내보낼 마켓이 없습니다」 경고가 남아 있다');
  ok(t.document.getElementById('pd-mktmsg').textContent.includes('붙였습니다'),
     '결과를 화면에 안 알렸다');

  // 🔴 리뷰 ③ — 저장 안 한 규칙 입력을 조용히 버리면 안 된다
  ok(t.document.getElementById('pd-rules').textContent === rulesBefore,
     '마켓을 붙였더니 규칙 편집 칸이 다시 그려졌다(저장 안 한 입력이 사라진다)');
  ok(t.loadCount() === 0, '마켓을 붙였을 뿐인데 규칙을 통째로 다시 불러왔다');
}

// ── ①-2 마켓 「떼기」가 실제로 요청을 보낸다 ────────────────
{
  const t = runDetail({ markets: ['coupang'],
                        reply: () => ({ ok: true, message: '뗐습니다.' }) });
  t.document.getElementById('pd-mkts').insertAdjacentHTML('beforeend',
    '<div class="pd-line" data-market="coupang" data-acc="본계정">'
    + '<span class="chip mkt">쿠팡 · 본계정</span>'
    + '<button class="pd-off" data-off="market">떼기</button></div>');

  click(t.document.querySelector('#pd-mkts .pd-off'));
  await nextTick();

  ok(t.calls.length === 1 && t.calls[0].method === 'DELETE',
     '마켓 「떼기」 버튼이 죽어 있다(요청이 안 나갔다)');
  ok(t.calls[0].url === '/bulk/api/process/policies/7/markets', '엉뚱한 곳으로 뗐다');
  ok(t.calls[0].body.market === 'coupang' && t.calls[0].body.account_key === '본계정',
     '어느 마켓·계정을 떼는지 안 실렸다(계정이 다르면 다른 줄이다)');
  ok(t.document.querySelectorAll('#pd-mkts .pd-line').length === 0, '줄이 안 사라졌다');
  ok(t.document.getElementById('pd-nomkt') !== null,
     '마켓이 0곳이 됐는데 「어디에도 안 올라갑니다」 경고가 안 돌아왔다');
}

// ── ①-3 소싱처 「떼기」는 **먼저 묻고**, 무엇을 잃는지 말한다 ─
{
  const t = runDetail({ reply: () => ({ ok: true, message: '뗐습니다.' }) });
  click(t.document.querySelector('#pd-srcs .pd-off'));
  await nextTick();

  ok(t.asked.length === 1, '떼기 전에 안 물었다(한 번의 오조작으로 사라진다)');
  ok(t.asked[0].includes('https://www.musinsa.com/brand/nike'),
     '저장된 주소가 같이 지워진다는 사실을 확인 문구가 안 알린다');
  ok(t.calls.length === 1 && t.calls[0].method === 'DELETE'
     && t.calls[0].url === '/bulk/api/process/sources', '소싱처 「떼기」 가 죽어 있다');
  ok(t.calls[0].body.source_key === 'musinsa' && t.calls[0].body.brand === '나이키',
     '어느 구성을 떼는지 안 실렸다');
  ok(t.document.querySelectorAll('#pd-srcs .pd-line').length === 0, '줄이 안 사라졌다');
}

// ── ①-4 「아니오」 면 아무 일도 안 일어난다 ──────────────────
{
  const t = runDetail({ confirm: false, reply: () => ({ ok: true }) });
  click(t.document.querySelector('#pd-srcs .pd-off'));
  await nextTick();
  ok(t.calls.length === 0, '거절했는데도 지우러 갔다');
  ok(t.document.querySelectorAll('#pd-srcs .pd-line').length === 1, '거절했는데 줄이 사라졌다');
  ok(t.document.getElementById('pd-srcmsg').textContent.includes('떼지 않았습니다'),
     '거절한 사실을 화면에 안 알렸다');
}

// ══ ② 목록 화면 — 고르면 저장하고 **다시 그린다** ════════════
function runList(opts) {
  const src = cut(LIST, '/** 결과를 그 줄 옆에 쓴다.', 'function addPolicy(', '목록');
  const calls = [];
  const asked = [];
  const msgs = {};
  let loadCalled = 0;
  const fetchStub = (url, init) => {
    calls.push({ url, method: (init && init.method) || 'GET',
                 body: init && init.body ? JSON.parse(init.body) : null });
    const j = opts.reply(url, init);
    return Promise.resolve({ status: j.__status || 200, json: () => Promise.resolve(j) });
  };
  const root = { querySelectorAll: () => [] };            // 메시지는 msgs 로만 확인
  const win = { confirm: (m) => { asked.push(m); return opts.confirm !== false; } };
  const data = { policies: [{ id: 1, name: '나이키 기본' }, { id: 2, name: '아디다스 기본' }] };
  const fn = new Function('root', 'msgs', 'data', 'window', 'fetch', 'esc', 'load',
    `${src}\n return { pick, detach, attach };`);
  const api = fn(root, msgs, data, win, fetchStub, esc, () => { loadCalled += 1; });
  return { api, calls, asked, msgs, loadCount: () => loadCalled };
}

const fakeSel = (value, extra = {}) => ({
  value, dataset: Object.assign({ src: 'musinsa', brand: '나이키', url: '' }, extra),
});

// ── ②-1 정책을 고르면 붙이고, **목록을 다시 그린다** ────────
{
  const t = runList({ reply: () => ({ ok: true, moved_from: null,
                                      message: '정책 「나이키 기본」 에 붙였습니다.' }) });
  t.api.pick(fakeSel('1'));
  await nextTick();
  ok(t.calls.length === 1 && t.calls[0].method === 'POST'
     && t.calls[0].url === '/bulk/api/process/policies/1/sources',
     '드롭다운을 골랐는데 붙이러 안 갔다');
  ok(t.msgs['musinsa > 나이키'].text.includes('붙였습니다'), '결과를 그 줄에 안 적었다');
  ok(t.loadCount() === 1,
     '저장한 뒤 목록을 다시 안 그린다 — 빨간 줄이 빨간 채로 남는다');
}

// ── ②-2 다른 정책에 있으면 되묻고, 승낙해야 옮긴다 ──────────
{
  let n = 0;
  const t = runList({
    reply: (url, init) => {
      n += 1;
      const body = JSON.parse(init.body);
      if (!body.confirm_move) {
        return { __status: 409, ok: false, need_confirm: true,
                 current_policy: { id: 2, name: '아디다스 기본' },
                 error: '이미 붙어 있습니다.' };
      }
      return { ok: true, moved_from: '아디다스 기본',
               message: '정책 「아디다스 기본」 에서 「나이키 기본」 로 옮겼습니다.' };
    },
  });
  t.api.pick(fakeSel('1'));
  await nextTick();
  await nextTick();
  ok(t.asked.length === 1 && t.asked[0].includes('아디다스 기본')
     && t.asked[0].includes('나이키 기본'), '옮기기 전에 양쪽 정책 이름으로 안 물었다');
  ok(n === 2 && t.calls[1].body.confirm_move === true, '승낙했는데 안 옮겼다');
  ok(t.msgs['musinsa > 나이키'].text.includes('옮겼습니다'), '옮긴 사실을 안 알렸다');
}

// ── ②-3 「정책 없음」은 무엇을 잃는지 묻고 나서 뗀다 ─────────
{
  const t = runList({
    reply: (url, init) => {
      if (!init || !init.method || init.method === 'GET') {
        return { ok: true, policy_id: 2, policy_name: '아디다스 기본',
                 url: 'https://www.musinsa.com/brand/nike' };
      }
      return { ok: true, message: '뗐습니다.' };
    },
  });
  t.api.pick(fakeSel(''));
  await nextTick();
  await nextTick();
  ok(t.asked.length === 1, '떼기 전에 안 물었다');
  ok(t.asked[0].includes('https://www.musinsa.com/brand/nike'),
     '저장된 주소가 같이 지워진다는 사실을 안 알렸다');
  ok(t.calls.length === 2 && t.calls[1].method === 'DELETE', '승낙했는데 안 뗐다');
}

// ── ②-4 떼기를 거절하면 지우러 가지 않는다 ──────────────────
{
  const t = runList({
    confirm: false,
    reply: () => ({ ok: true, policy_id: 2, policy_name: '아디다스 기본', url: '' }),
  });
  t.api.pick(fakeSel(''));
  await nextTick();
  await nextTick();
  ok(!t.calls.some((c) => c.method === 'DELETE'), '거절했는데 지우러 갔다');
  ok(t.msgs['musinsa > 나이키'].text.includes('떼지 않았습니다'), '거절 사실을 안 알렸다');
}

if (fails) { console.error(`\n${fails}건 실패`); process.exit(1); }
console.log('가공정책 붙이기·떼기 배선 — 전부 통과');

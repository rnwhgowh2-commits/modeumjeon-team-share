// background.js — 확장 서비스 워커. 실제 크롤(소싱처 수집)을 담당.
//  v0.4.1(소싱처별 창 재사용): 소싱처 1곳당 보이는 창 1개를 열고(openWin), 그 소싱처의
//   URL들을 그 창에서 차례로 이동(navGrab/navExtract)하며 크롤 → 사용자가 과정을 눈으로 본다.
//   그 소싱처가 끝나면 창을 닫는다(closeWin). URL마다 창을 열었다 닫던 v0.4.0 의 깜빡임 제거.
//   - navGrab : 비로그인 4개(르무통·SSF·SSG·스스르무통) — 창에서 렌더 HTML 만 수집 →
//               서버 /api/sources/parse 가 추출(ext_bridge 가 배선). SPA 안정화 대기 포함.
//   - navExtract : 무신사·롯데온 — 창 안에서 기존 JS 추출기(EXTRACTORS) 실행.
//   (로그인된 브라우저로 직접 긁으므로 무신사 회원가·롯데온 SPA가 그대로 읽힘.)
//   sysinfo: chrome.system.cpu/memory 로 CPU·메모리 사용률 측정(적응형 컨트롤러 보조 신호).
//  결과 저장은 mou-m.com /api/sources/crawl-result (ext_bridge.crawlBundleAll 이 호출).
//  grabHtml/crawl(URL마다 창 생성·즉시 닫기) 핸들러는 하위호환 위해 유지.

const MOUM_EXT_VERSION = "0.4.4";

// cascade 위치 시퀀서 — 창이 여러 개 열려도 서로 어긋나 보임
let _winSeq = 0;

// SPA(르무통·SSG·스스르무통) 가격 DOM 이 로드 완료 후에도 늦게 뜰 수 있어
//  navGrab 은 로드 완료 뒤 추가 안정화 대기 후 outerHTML 을 뜬다(빈 HTML 방지).
const NAVGRAB_SETTLE_MS = 1200;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const type = msg && msg.type;
  if (type === "ping") {
    sendResponse({ pong: true, version: MOUM_EXT_VERSION,
      from: sender && sender.url ? new URL(sender.url).host : null, ts: Date.now() });
    return false;
  }
  if (type === "crawl") {
    handleCrawl(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "grabHtml") {
    handleGrabHtml(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "openWin") {
    handleOpenWin(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "navGrab") {
    handleNavGrab(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "navExtract") {
    handleNavExtract(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "closeWin") {
    handleCloseWin(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  if (type === "sysinfo") {
    handleSysinfo()
      .then((r) => sendResponse(r))
      .catch((_) => sendResponse({ ok: true, cpu: null, mem: null }));
    return true; // async
  }
  sendResponse({ error: "unknown type: " + type });
  return false;
});

// ── 소싱처별 추출 레시피 (페이지 컨텍스트에서 실행될 함수) ──
const EXTRACTORS = { musinsa: musinsaExtractor, lotteon: lotteonExtractor };

async function handleCrawl(payload) {
  const sources = payload.sources || [];
  const results = [];
  for (const s of sources) {
    const base = { source_key: s.source_key, url: s.url };
    try {
      results.push({ ...base, ...(await crawlOne(s)) });
    } catch (e) {
      results.push({ ...base, ok: false, error: String(e && e.message ? e.message : e) });
    }
  }
  return { ok: true, count: results.length, results };
}

async function crawlOne(s) {
  const extractor = EXTRACTORS[s.source_key];
  if (!extractor) return { ok: false, error: "레시피 없음(미구현 소싱처): " + s.source_key };
  // 보이는 새 창으로 열기(focused:false → 사용자 작업 방해 최소화하되 화면엔 보임).
  const win = await chrome.windows.create({ url: s.url, focused: false });
  const tab = win && win.tabs && win.tabs[0];
  if (!tab) { try { await chrome.windows.remove(win.id); } catch (_) {} return { ok: false, error: "창 탭 없음" }; }
  try {
    await waitTabComplete(tab.id, 25000);
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "ISOLATED", func: extractor,
    });
    return (out && out[0] && out[0].result) || { ok: false, error: "추출 결과 없음" };
  } finally {
    try { await chrome.windows.remove(win.id); } catch (_) {}
  }
}

// ── 비로그인 4개용: 보이는 창에서 렌더 HTML 수집(추출은 서버 /api/sources/parse) ──
async function handleGrabHtml(payload) {
  const url = payload.url;
  if (!url) return { ok: false, error: "url 없음" };
  const win = await chrome.windows.create({ url, focused: false });
  const tab = win && win.tabs && win.tabs[0];
  if (!tab) { try { await chrome.windows.remove(win.id); } catch (_) {} return { ok: false, error: "창 탭 없음" }; }
  try {
    await waitTabComplete(tab.id, 25000);
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "ISOLATED",
      func: () => document.documentElement.outerHTML,
    });
    const html = out && out[0] && out[0].result;
    return html ? { ok: true, html } : { ok: false, error: "HTML 수집 실패" };
  } finally {
    try { await chrome.windows.remove(win.id); } catch (_) {}
  }
}

// ════════════════════════════════════════════
//  창 재사용 모델 (v0.4.1) — 소싱처 1곳당 창 1개, URL은 그 창에서 순차 이동
// ════════════════════════════════════════════

// openWin — 보이는 빈 창 1개 생성(focused:true, cascade 위치). 첫 탭 id 확보.
async function handleOpenWin(_payload) {
  const k = _winSeq++ % 6;
  const left = 60 + k * 70;
  const top  = 60 + k * 48;
  const win = await chrome.windows.create({
    url: "about:blank", focused: true, type: "normal",
    left, top, width: 1000, height: 760,
  });
  const tab = win && win.tabs && win.tabs[0];
  if (!win || !tab) {
    if (win && win.id != null) { try { await chrome.windows.remove(win.id); } catch (_) {} }
    return { ok: false, error: "창 생성 실패(탭 없음)" };
  }
  return { ok: true, winId: win.id, tabId: tab.id };
}

// navGrab — 그 탭을 url 로 이동 → 로드 완료 + 안정화 대기 → outerHTML 반환. (창 안 닫음)
async function handleNavGrab(payload) {
  const tabId = payload.tabId, url = payload.url;
  if (tabId == null) return { ok: false, error: "tabId 없음" };
  if (!url) return { ok: false, error: "url 없음" };
  await chrome.tabs.update(tabId, { url });
  await waitTabComplete(tabId, 25000);
  // SPA 가격 DOM 늦게 뜨는 경우 대비 추가 안정화 대기(빈 HTML 방지)
  await new Promise((r) => setTimeout(r, NAVGRAB_SETTLE_MS));
  const out = await chrome.scripting.executeScript({
    target: { tabId: tabId }, world: "ISOLATED",
    func: () => document.documentElement.outerHTML,
  });
  const html = out && out[0] && out[0].result;
  return html ? { ok: true, html } : { ok: false, error: "HTML 수집 실패" };
}

// navExtract — 그 탭을 url 로 이동 → 로드 완료 대기 → 소싱처 추출기 실행. (창 안 닫음)
async function handleNavExtract(payload) {
  const tabId = payload.tabId, url = payload.url, sk = payload.source_key;
  if (tabId == null) return { ok: false, error: "tabId 없음" };
  if (!url) return { ok: false, error: "url 없음" };
  const extractor = EXTRACTORS[sk];
  if (!extractor) return { ok: false, error: "레시피 없음(미구현 소싱처): " + sk };
  await chrome.tabs.update(tabId, { url });
  await waitTabComplete(tabId, 25000);
  const out = await chrome.scripting.executeScript({
    target: { tabId: tabId }, world: "ISOLATED", func: extractor,
  });
  return (out && out[0] && out[0].result) || { ok: false, error: "추출 결과 없음" };
}

// closeWin — 창 닫기. (winId 없거나 이미 닫혔어도 ok)
async function handleCloseWin(payload) {
  const winId = payload.winId;
  if (winId == null) return { ok: true };
  try { await chrome.windows.remove(winId); } catch (_) {}
  return { ok: true };
}

// ── 시스템 신호(보조): CPU/메모리 사용률 0~100. 권한·측정 실패 시 null. ──
//   chrome.system.cpu 의 processors[].usage 는 누적값(kernel+user+idle 틱)이라
//   두 번 샘플(400ms)해 델타로 % 계산. memory 는 (total-available)/total.
async function handleSysinfo() {
  const cpuApi = chrome.system && chrome.system.cpu;
  const memApi = chrome.system && chrome.system.memory;
  if (!cpuApi || !memApi) return { ok: true, cpu: null, mem: null };
  const getCpu = () => new Promise((res) => { try { cpuApi.getInfo((i) => res(i || null)); } catch (_) { res(null); } });
  const getMem = () => new Promise((res) => { try { memApi.getInfo((i) => res(i || null)); } catch (_) { res(null); } });

  let cpu = null;
  try {
    const a = await getCpu();
    await new Promise((r) => setTimeout(r, 400));
    const b = await getCpu();
    if (a && b && a.processors && b.processors && a.processors.length === b.processors.length) {
      let busyDelta = 0, totalDelta = 0;
      for (let i = 0; i < b.processors.length; i++) {
        const ua = a.processors[i].usage, ub = b.processors[i].usage;
        if (!ua || !ub) continue;
        const idle = ub.idle - ua.idle;
        const total = ub.total - ua.total;
        if (total > 0) { busyDelta += (total - idle); totalDelta += total; }
      }
      if (totalDelta > 0) cpu = Math.round(Math.max(0, Math.min(100, (busyDelta / totalDelta) * 100)));
    }
  } catch (_) { cpu = null; }

  let mem = null;
  try {
    const m = await getMem();
    if (m && m.capacity > 0) {
      mem = Math.round(Math.max(0, Math.min(100, ((m.capacity - m.availableCapacity) / m.capacity) * 100)));
    }
  } catch (_) { mem = null; }

  return { ok: true, cpu, mem };
}

function waitTabComplete(tabId, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => { if (!settled) { settled = true; chrome.tabs.onUpdated.removeListener(listener); resolve(); } };
    const to = setTimeout(finish, timeoutMs);
    function listener(id, info) { if (id === tabId && info.status === "complete") { clearTimeout(to); finish(); } }
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId, (t) => { if (t && t.status === "complete") { clearTimeout(to); finish(); } });
  });
}

// ════════════════════════════════════════════
//  무신사 — www.musinsa.com/products/{id}. 옵션·재고=API, 회원가=DOM '나의 할인가'
// ════════════════════════════════════════════
async function musinsaExtractor() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const id = (location.pathname.match(/products\/(\d+)/) || [])[1];
  if (!id) return { ok: false, error: "무신사 product id 추출 실패" };
  const base = "https://goods-detail.musinsa.com/api2/goods/" + id;

  const oj = await fetch(base + "/options", { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
  const basic = (oj.data || {}).basic || [];
  const items = (oj.data || {}).optionItems || [];

  const valueNos = [];
  basic.forEach((g) => (g.optionValues || g.values || []).forEach((v) => { if (v.no != null) valueNos.push(v.no); }));
  const invMap = {};
  let invOk = false;
  try {
    const ij = await fetch(base + "/options/v2/prioritized-inventories", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ optionValueNos: valueNos }),
    }).then((r) => r.json());
    const invArr = (ij && ij.data) || [];
    invArr.forEach((x) => { invMap[x.productVariantId] = x; });
    invOk = invArr.length > 0; // 재고 API 성공+데이터 → true. 전체 실패/빈 응답이면 false.
  } catch (e) { /* invOk=false 유지 → 전체 실패 시 999(재고있음) 금지, 아래서 -1(불명) */ }

  // ★ 2026-06-13 — 표면노출가 = 무신사 구조화 API(goodsPrice.salePrice) 직읽기.
  //   기존: document.body.innerText 정규식으로 '나의 할인가'(회원가)를 price 로 오긁어
  //         표면가 자리에 회원가(예: 110,300)가 들어가 → 이중차감·언더프라이싱 사고. → 폐기.
  //   변경: API 가 표면가(salePrice)·정가(normalPrice)를 숫자로 직접 제공 → 결정적·로그인 불필요.
  //   회원가('나의 할인가')는 참고용 member_price 로만 (계산 base 아님).
  let surface = null, normal = null;
  try {
    const gj = await fetch(base, { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
    const gp = ((gj && (gj.data || gj)) || {}).goodsPrice || {};
    surface = parseInt(gp.salePrice, 10);
    normal = parseInt(gp.normalPrice, 10);
  } catch (e) { /* surface=null → 아래 게이트에서 크롤실패 처리 */ }

  // 회원가('나의 할인가')는 참고용으로만 1회 추출 (price base 아님 — 사고 원인 제거).
  let member = null;
  const mm = document.body.innerText.match(/([\d,]{4,})\s*원\s*나의\s*할인가/);
  if (mm) member = parseInt(mm[1].replace(/,/g, ""), 10);

  // ★ 표면가 검증 게이트 — 통과 못 하면 price=null(크롤실패). 폴백(회원가·정가 등) 일절 금지.
  //   G1 존재: salePrice 양수.  G2 상한: salePrice ≤ normalPrice(정가).
  const surfaceValid = Number.isFinite(surface) && surface > 0
    && (!Number.isFinite(normal) || normal <= 0 || surface <= normal);
  const price = surfaceValid ? surface : null;

  const options = items.map((it) => {
    const code = it.managedCode || "";
    let color = "", size = "";
    if (code.includes("^")) { const p = code.split("^"); color = (p[0] || "").trim(); size = (p[1] || "").trim(); }
    else { size = code.trim(); }
    // S16: 재고 API 전체 실패(invOk=false)인데 이 옵션이 맵에 없으면 999(재고있음) 금지 → -1(불명).
    //   API 성공(invOk=true) happy-path는 기존대로(맵에 있으면 그 값, 없으면 999).
    const inv = invMap[it.no];
    let stock;
    if (inv) stock = inv.outOfStock ? 0 : (inv.remainQuantity == null ? 999 : Math.max(0, inv.remainQuantity));
    else stock = invOk ? 999 : -1;
    return { color, size: size.replace("mm", "").trim(), price, stock };
  });
  const anyStock = options.some((o) => o.stock > 0) || (price != null);

  return {
    ok: !!price,
    price: price,                       // 표면노출가(salePrice) — 검증 통과 시만, 아니면 null
    stock: anyStock ? 999 : 0,          // 재고 있으면 sentinel
    product_name: document.title.split("-")[0].trim().slice(0, 120),
    member_price: member,               // 참고용(회원가, '나의 할인가') — 계산 base 아님
    sale_price: surface, surface_price: surface, normal_price: normal,
    is_logged_in: member != null,
    option_count: options.length, options,
    error: price ? null : "표면가 검증 실패(salePrice 없음/0/정가 초과) — 크롤실패(폴백 금지)",
  };
}

// ════════════════════════════════════════════
//  롯데온 — www.lotteon.com/p/product/LO... (Vue SPA). 혜택가 = DOM '나의 혜택가'
// ════════════════════════════════════════════
async function lotteonExtractor() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // [2026-06-12 버그픽스] 1원 오인 방지:
  //   기존 보조식 `나의 혜택가[^\d]*([\d,]+)` 가 라벨 뒤 첫 숫자를 잡는데, 롯데온은
  //   가격이 라벨 *앞*("119,910원 나의 혜택가")에 있고 뒤엔 "1회 최대 20개 구매"의 "1"이
  //   와서 SPA 렌더 전 순간 "1"을 가격으로 오인 → 1원 저장됨.
  //   대책: ① 숫자 4자리 이상 + '원' 인접만 인정(한 자리/원 없는 숫자 배제)
  //         ② 1000원 미만 거부(MIN)  ③ 유효 가격 렌더될 때까지 폴링.
  const MIN = 1000;
  function pickBenefit(t) {
    // (A) [가격]원 나의 혜택가  — 롯데온 기본 레이아웃(가격이 라벨 앞)
    let m = t.match(/([\d,]{4,})\s*원\s*나의\s*혜택가/);
    if (m) { const v = parseInt(m[1].replace(/,/g, ""), 10); if (v >= MIN) return v; }
    // (B) 혜택가 [가격]원  — 라벨 뒤 가격('원' 인접 필수라 "1회"는 배제됨)
    m = t.match(/혜택가\s*([\d,]{4,})\s*원/);
    if (m) { const v = parseInt(m[1].replace(/,/g, ""), 10); if (v >= MIN) return v; }
    return null;
  }
  function pickSale(t) {
    const m = t.match(/(\d+)%\s*([\d,]{4,})\s*원/);
    if (m) { const v = parseInt(m[2].replace(/,/g, ""), 10); if (v >= MIN) return v; }
    return null;
  }
  let benefit = null, sale = null;
  for (let i = 0; i < 16; i++) {
    const t = document.body.innerText;
    if (benefit == null) benefit = pickBenefit(t);
    if (sale == null) sale = pickSale(t);
    if (benefit != null) break;   // MIN 통과한 유효 혜택가만 종료 조건
    await sleep(500);
  }
  const price = (benefit != null) ? benefit : sale;
  const valid = (price != null && price >= MIN);   // 하한 재확인(방어)
  const soldOut = /품절|일시품절/.test(document.body.innerText) && !valid;
  return {
    ok: valid,
    price: valid ? price : null,
    stock: valid && !soldOut ? 999 : 0,
    product_name: document.title.split(":")[0].trim().slice(0, 120),
    benefit_price: benefit, sale_price: sale,
    error: valid ? null : (soldOut ? "품절" : "가격 추출 실패(렌더 미완/하한 미달)"),
  };
}

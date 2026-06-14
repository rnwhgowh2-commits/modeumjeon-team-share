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

const MOUM_EXT_VERSION = "0.5.1";  // 0.5.0+ = 백그라운드 크롤 엔진(탭 닫아도 지속) 지원

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
  // ── [2026-06-14] 2단계: 백그라운드 오케스트레이터 제어 메시지 ──
  //   크롤 엔진이 이 서비스워커에서 돌아 페이지(탭)를 닫거나 이동해도 지속된다.
  if (type === "crawl.enqueue") {
    sendResponse(mgrEnqueue(msg.payload || {}));
    return false;
  }
  if (type === "crawl.pause")  { sendResponse(mgrPause());  return false; }
  if (type === "crawl.resume") { sendResponse(mgrResume()); return false; }
  if (type === "crawl.stop")   { sendResponse(mgrStop());   return false; }
  if (type === "crawl.cancel") { sendResponse(mgrCancel((msg.payload || {}).code)); return false; }
  if (type === "crawl.getState") { sendResponse(mgrSnapshot()); return false; }
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

// ────────────────────────────────────────────────────────────
//  스스(스마트스토어/브랜드스토어) per-SKU 재고 — 로그인 브라우저 전용.
//  R&D(2026-06-14): inline __PRELOADED_STATE__ 엔 SKU별 재고가 없고(상품 합계만),
//  per-SKU 는 n/v2 옵션조합 API 가 준다. 그 API 는 비브라우저(curl/서버)에서 429 WAF →
//  로그인된 이 브라우저(동일출처+쿠키)에서만 200. 그래서 무신사 inventories 처럼
//  확장이 페이지 컨텍스트에서 직접 호출한다.
//  구조 무관 walker: 응답 어디든 (stockQuantity + optionName1/optionName) 를 가진
//  객체 배열을 찾아 "색상||사이즈"→수량 맵 생성. 실패 시 null(현행 유지=둔갑 안 함)+진단.
// ────────────────────────────────────────────────────────────
function naverSkuStockFetch() {
  return (async () => {
    try {
      const html = document.documentElement.outerHTML;
      const m = html.match(/window\.__PRELOADED_STATE__\s*=\s*([\s\S]+?)<\/script>/);
      if (!m) return { err: "no-state" };
      let raw = m[1].trim();
      if (raw.endsWith(";")) raw = raw.slice(0, -1);
      raw = raw.replace(/(?<![\w"])undefined(?![\w"])/g, "null");
      let state;
      try { state = JSON.parse(raw); } catch (e) { return { err: "state-parse" }; }
      const A = (state.simpleProductForDetailPage && state.simpleProductForDetailPage.A) || {};
      const ch = A.channel || {};
      const cu = ch.channelUid;
      const pno = A.productNo || A.id;
      if (!cu || !pno) return { err: "no-ids" };
      const resp = await fetch(`/n/v2/channels/${cu}/products/${pno}`, {
        credentials: "include", headers: { accept: "application/json" },
      });
      if (!resp.ok) return { err: "http-" + resp.status };
      const j = await resp.json();
      const map = {};
      let combos = 0;
      (function walk(o, d) {
        if (!o || d > 7) return;
        if (Array.isArray(o)) {
          for (const it of o) {
            if (it && typeof it === "object" && "stockQuantity" in it &&
                (("optionName1" in it) || ("optionName" in it))) {
              const c = (it.optionName1 || "").toString().trim();
              const s = (it.optionName2 || it.optionName || "").toString().trim();
              const q = it.stockQuantity;
              const usable = it.usable !== false && it.sellable !== false && it.useYn !== "N";
              if (typeof q === "number") { map[c + "||" + s] = usable ? q : 0; combos++; }
            } else { walk(it, d + 1); }
          }
        } else if (typeof o === "object") {
          for (const k in o) walk(o[k], d + 1);
        }
      })(j, 0);
      if (!combos) return { err: "no-combos", topKeys: Object.keys(j).slice(0, 14) };
      return { map, combos };
    } catch (e) { return { err: String(e).slice(0, 90) }; }
  })();
}

// navGrab — 그 탭을 url 로 이동 → 로드 완료 + 안정화 대기 → outerHTML 반환. (창 안 닫음)
async function handleNavGrab(payload) {
  const tabId = payload.tabId, url = payload.url;
  if (!url) return { ok: false, error: "url 없음" };
  // [2026-06-14] SSF: 옵션 재고(품절임박 N·품절)는 '한국 IP' raw HTML 의 JS문자열에만 존재.
  //   - AWS 서버 curl(도쿄 IP) = 품절임박 숫자 없는 버전
  //   - navGrab 렌더본 = JS문자열 optCd 소진 + 옵션리스트 lazy 렌더(콜드 창서 빈 결과)
  //   → 이 브라우저(한국)에서 raw HTML 을 직접 fetch 해 서버 정규식 파서에 넘긴다(렌더 X).
  if (/ssfshop\.com/.test(url)) {
    try {
      const resp = await fetch(url, { credentials: "include" });
      const raw = await resp.text();
      if (raw && raw.length > 5000) return { ok: true, html: raw };
    } catch (e) { /* 실패 시 아래 렌더 grab 폴백 */ }
  }
  if (tabId == null) return { ok: false, error: "tabId 없음" };
  await chrome.tabs.update(tabId, { url });
  await waitTabComplete(tabId, 25000);
  // SPA 가격 DOM 늦게 뜨는 경우 대비 추가 안정화 대기(빈 HTML 방지)
  await new Promise((r) => setTimeout(r, NAVGRAB_SETTLE_MS));
  const out = await chrome.scripting.executeScript({
    target: { tabId: tabId }, world: "ISOLATED",
    func: () => document.documentElement.outerHTML,
  });
  const html = out && out[0] && out[0].result;
  if (!html) return { ok: false, error: "HTML 수집 실패" };
  // 스스만: per-SKU 재고를 로그인 브라우저 컨텍스트에서 n/v2 API 로 수집(같은 탭).
  let sku_stock = null, sku_diag = null;
  if (/(?:brand|smartstore)\.naver\.com/.test(url)) {
    try {
      const sk = await chrome.scripting.executeScript({
        target: { tabId: tabId }, world: "ISOLATED", func: naverSkuStockFetch,
      });
      const r = sk && sk[0] && sk[0].result;
      if (r && r.map && Object.keys(r.map).length) {
        sku_stock = r.map;
        sku_diag = "ok:" + r.combos;        // 성공: 조합 수
      } else if (r && r.err) {
        sku_diag = "err:" + r.err + (r.topKeys ? "|" + r.topKeys.join(",") : "");
      }
    } catch (e) { sku_diag = "exc:" + String(e).slice(0, 60); }
  }
  // sku_diag: 둔갑 방지 — 실패해도 sku_stock=null(현행 유지). ext_bridge 가 콘솔 로깅.
  return { ok: true, html, sku_stock, sku_diag };
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
    const arr = (ij && ij.data) || [];
    arr.forEach((x) => { invMap[x.productVariantId] = x; });
    invOk = arr.length > 0;   // ★ 재고 데이터 실제 수신 여부 (실패/빈응답이면 false)
  } catch (e) { invOk = false; /* 재고 호출 실패 → 아래서 null(불명), 가격은 진행 */ }

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
    const inv = invMap[it.no] || {};
    // ★ [재고 안전망] 인벤토리 호출 실패(invOk=false) 시 999(충분) 둔갑 금지 → null(불명).
    //   서버 _ingest_option_stocks 가 null 은 스킵 → 옛 좋은 값(예: 2)을 999로 덮어쓰지 않음.
    //   (인벤토리 성공인데 이 variant 만 없는 경우는 기존대로 999=충분 유지.)
    const stock = !invOk ? null
      : (inv.outOfStock ? 0 : (inv.remainQuantity == null ? 999 : Math.max(0, inv.remainQuantity)));
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

  // ── [2026-06-14] 사이즈별 재고 추출 (무신사 일반화) ──────────────
  //   롯데온 옵션 패널 구조(실측):
  //     ul.selectLists > li > div.labelTextWrap > span.caption(사이즈)
  //                                              + span.price(가격)
  //                                              + span.stock("10개 남음" 등 마커)
  //   span.stock 마커:  "N개 남음"/"마지막 N개" = 한정수량(N) · "품절" = 0 · 없음 = 충분(999)
  //   색상: 롯데온은 색상별 별도 listing(모델 LM-06-BK) → title 마지막 토큰 1개.
  //   ※ ul.selectLists 가 2개(PC/모바일 중복) 노출되므로 size 로 dedup.
  function lotteStock(txt) {
    if (!txt) return 999;                                 // 마커 없음 = 충분
    if (/품절|일시품절|sold\s*out/i.test(txt)) return 0;   // 품절
    const m = txt.match(/(\d+)\s*개\s*남음/) || txt.match(/마지막\s*(\d+)\s*개/);
    if (m) return Math.max(0, parseInt(m[1], 10));         // 한정수량(실수량)
    return 999;
  }
  // 색상명: "[르무통]…운동화 블랙 : 롯데ON" → '블랙'
  const titleColor = (document.title.split(":")[0].trim().split(/\s+/).pop()) || "";
  const seenSize = new Set();
  const options = [];
  for (const li of document.querySelectorAll("ul.selectLists > li")) {
    const cap = li.querySelector(".caption");
    if (!cap) continue;
    const size = (cap.textContent || "").replace(/mm/i, "").trim();
    if (!size || seenSize.has(size)) continue;
    seenSize.add(size);
    const stEl = li.querySelector(".stock");
    // li 전체가 비활성/품절 처리된 경우도 0 (방어)
    const liSold = /품절|sold|disable|soldout/i.test((li.className || "").toString())
      || li.getAttribute("aria-disabled") === "true";
    const stock = liSold ? 0 : lotteStock(stEl ? stEl.textContent.trim() : "");
    options.push({ color: "", size, price: valid ? price : null, stock });
  }

  return {
    ok: valid,
    price: valid ? price : null,
    stock: valid && !soldOut ? 999 : 0,
    product_name: document.title.split(":")[0].trim().slice(0, 120),
    benefit_price: benefit, sale_price: sale,
    option_count: options.length, options,
    error: valid ? null : (soldOut ? "품절" : "가격 추출 실패(렌더 미완/하한 미달)"),
  };
}

// ════════════════════════════════════════════════════════════════════
//  [2026-06-14] 2단계 — 백그라운드 크롤 오케스트레이터
//   크롤 엔진(멀티 모음전 큐 + 적응형 동시성 + 일시중지/중지)을 이 서비스워커에서 돌린다.
//   → mou-m.com 탭을 닫거나 다른 페이지로 이동해도 크롤이 계속된다(1단계는 페이지에서 돌아 멈췄음).
//   페이지(ext_bridge)는 enqueue/pause/resume/stop/cancel/getState 메시지만 보내는 얇은 클라이언트.
//   진행 로그는 chrome.tabs.sendMessage 로 열린 mou-m 탭들에 push → content_mou 가 페이지로 중계.
//   가격 안전 로직(하드리셋·finalize·폴백금지·표면→매입 갱신·sku_stock) 전부 보존(ext_bridge 와 동일).
// ════════════════════════════════════════════════════════════════════
const BG_PARSE_SOURCES = ["lemouton", "ssf", "ssg", "ss_lemouton"];
const BG_JS_SOURCES = ["musinsa", "lotteon"];

const _mgr = { queue: [], running: null, paused: false, stopped: false, base: "", _kick: null, view: {} };

function bgMedian(arr) {
  if (!arr.length) return 0;
  const s = arr.slice().sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function bgClamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// ── 진행 로그 → 열린 mou-m 탭들로 push + 스냅샷용 compact view 갱신 ──
const MOUM_TAB_GLOBS = ["https://www.mou-m.com/*", "https://mou-m.com/*", "http://54.116.196.90/*", "https://54.116.196.90/*"];
function bgEmit(detail) {
  detail = detail || {};
  if (detail.ts == null) detail.ts = Date.now();
  try { bgUpdateView(detail); } catch (_) {}
  try {
    chrome.tabs.query({ url: MOUM_TAB_GLOBS }, (tabs) => {
      if (!tabs) return;
      for (const t of tabs) {
        try { chrome.tabs.sendMessage(t.id, { __moumPush: "log", detail }, () => { void chrome.runtime.lastError; }); } catch (_) {}
      }
    });
  } catch (_) {}
}
function bgEmitQueue() {
  const q = [];
  if (_mgr.running) q.push({ code: _mgr.running, status: _mgr.paused ? "pause" : "run" });
  _mgr.queue.forEach((c) => q.push({ code: c, status: "wait" }));
  bgEmit({ type: "queue", queue: q, running: _mgr.running, paused: _mgr.paused });
}

// compact view (재연결 스냅샷용 — 로그 제외, 상태/진행/게이지만)
function vGet(code) { return _mgr.view[code] || (_mgr.view[code] = { label: code, status: "wait", total: 0, done: 0, metrics: {}, sources: {} }); }
function vSrc(v, sk) { return v.sources[sk] || (v.sources[sk] = { status: "wait", done: 0, total: null }); }
function bgUpdateView(d) {
  if (d.type === "queue") return;
  const code = d.bundle; if (!code) return;
  const v = vGet(code); v.label = code;
  if (d.metrics) {
    ["concurrency", "cap", "active", "cpu", "mem", "avgSec"].forEach((k) => { if (d.metrics[k] != null) v.metrics[k] = d.metrics[k]; });
    if (d.metrics.total != null) v.total = d.metrics.total;
    if (d.metrics.done != null) v.done = d.metrics.done;
  }
  switch (d.type) {
    case "start": v.status = "run"; v.finishMsg = ""; break;
    case "window-open": { const s = vSrc(v, d.source); s.status = "run"; s.done = 0; break; }
    case "item-done": { const s = vSrc(v, d.source); s.done = (s.done || 0) + 1; break; }
    case "source-done": { const s = vSrc(v, d.source); s.status = "done"; break; }
    case "bundle-paused": v.status = "pause"; break;
    case "bundle-resumed": v.status = "run"; break;
    case "finish": v.status = d.stopped ? "stop" : "done"; v.finishMsg = d.msg || ""; break;
  }
}

// ── SW 깨우기(보조) — 활성 크롤 중 30s idle 로 잠들지 않게. 크롤 자체의 chrome API 호출이
//   1차 keepalive 이고, alarm 은 조용한 구간 백업. (SW 가 죽으면 in-memory 루프는 사라지므로
//   resume 은 안 하나, 하드리셋+finalize fail-safe 로 잘못된 가격 저장은 없음.)
try {
  chrome.alarms.onAlarm.addListener((a) => { if (a && a.name === "moum-keepalive") { /* wake only */ } });
} catch (_) {}
function bgKeepaliveStart() { try { chrome.alarms.create("moum-keepalive", { periodInMinutes: 0.4 }); } catch (_) {} }
function bgKeepaliveStop() { try { chrome.alarms.clear("moum-keepalive"); } catch (_) {} }

// ── mou-m.com 서버 호출 — 반드시 mou-m 탭 컨텍스트(first-party)에서 실행 ──
//   이유: 서비스워커가 직접 fetch(mou-m) 하면 cross-origin 이라 SameSite=Lax 세션쿠키가
//   안 실려 인증 실패(저장·parse 401) 위험. 그래서 chrome.scripting 으로 mou-m 탭 안에서
//   fetch 를 실행한다(same-origin → 쿠키 확실). 탭이 없으면(사용자가 다 닫음) SW 가
//   백그라운드 mou-m 탭을 1개 띄워 서비스 탭으로 쓰고(_serviceTabOwned), 크롤 끝나면 닫는다.
//   → "탭 닫아도 계속" 을 깨지 않으면서 인증을 보장.
let _serviceTabId = null;
let _serviceTabOwned = false;

async function _isMoumTab(tabId) {
  try { const t = await chrome.tabs.get(tabId); return !!(t && t.url && /:\/\/(www\.)?mou-m\.com|54\.116\.196\.90/.test(t.url)); }
  catch (_) { return false; }
}
async function ensureServiceTab() {
  if (_serviceTabId != null && await _isMoumTab(_serviceTabId)) return _serviceTabId;
  _serviceTabId = null; _serviceTabOwned = false;
  // 이미 열린 mou-m 탭 재사용(사용자 탭이면 닫지 않음)
  const tabs = await chrome.tabs.query({ url: MOUM_TAB_GLOBS });
  if (tabs && tabs.length) { _serviceTabId = tabs[0].id; _serviceTabOwned = false; return _serviceTabId; }
  // 없으면 백그라운드 탭 1개 생성(비활성) → 서비스 탭
  const base = _mgr.base || "https://mou-m.com";
  const t = await chrome.tabs.create({ url: base + "/", active: false });
  if (!t || t.id == null) throw new Error("서비스 탭 생성 실패");
  await waitTabComplete(t.id, 25000);
  _serviceTabId = t.id; _serviceTabOwned = true;
  return _serviceTabId;
}
async function closeServiceTabIfOwned() {
  if (_serviceTabOwned && _serviceTabId != null) { try { await chrome.tabs.remove(_serviceTabId); } catch (_) {} }
  _serviceTabId = null; _serviceTabOwned = false;
}
// mou-m 탭 안에서 실행될 fetch (same-origin, 쿠키 동봉). 상대경로 path 사용.
function _injectedFetch(p, o) {
  return (async () => {
    try {
      const r = await fetch(p, Object.assign({ credentials: "same-origin" }, o || {}));
      const txt = await r.text();
      let j = null; try { j = JSON.parse(txt); } catch (_) {}
      return { ok: r.ok, status: r.status, json: j, text: j ? null : (txt || "").slice(0, 160) };
    } catch (e) { return { ok: false, status: 0, json: null, error: String(e).slice(0, 120) }; }
  })();
}
// fetch Response 유사 객체 반환(.ok/.status/.json()) — 호출부 .then(x=>x.json()) 호환.
async function bgFetch(path, opts) {
  let out = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    let tabId;
    try { tabId = await ensureServiceTab(); }
    catch (e) { return { ok: false, status: 0, json: () => Promise.resolve(null), _err: String(e) }; }
    try {
      const res = await chrome.scripting.executeScript({
        target: { tabId: tabId }, world: "ISOLATED", func: _injectedFetch, args: [path, opts || null],
      });
      out = res && res[0] && res[0].result;
      if (out) break;
    } catch (e) {
      _serviceTabId = null;   // 탭이 닫혔을 수 있음 → 재시도 시 재확보
      if (attempt === 1) return { ok: false, status: 0, json: () => Promise.resolve(null), _err: String(e) };
    }
  }
  out = out || { ok: false, status: 0, json: null };
  return { ok: out.ok, status: out.status, _text: out.text, json: () => Promise.resolve(out.json) };
}

// ── 제어 API (메시지 핸들러가 호출) ──
function mgrEnqueue(payload) {
  payload = payload || {};
  const code = payload.code || null;
  const codes = payload.codes || (code ? [code] : []);
  if (payload.base) _mgr.base = payload.base;
  if (!codes.length) return { ok: false, error: "code 없음" };
  let added = 0;
  for (const c of codes) {
    if (!c || c === _mgr.running || _mgr.queue.indexOf(c) >= 0) continue;
    _mgr.queue.push(c); added++;
  }
  bgEmitQueue();
  if (!_mgr.running) runQueueBG();
  return { ok: true, queued: added, position: _mgr.queue.length };
}
function mgrPause() {
  if (!_mgr.running) return { ok: false, error: "진행 중 아님" };
  if (_mgr.paused) return { ok: true, already: true };
  _mgr.paused = true;
  bgEmit({ type: "bundle-paused", bundle: _mgr.running, level: "warn", msg: "일시중지 — 창 닫는 중 (재개하면 이어서 크롤)" });
  bgEmitQueue();
  return { ok: true };
}
function mgrResume() {
  if (!_mgr.running) return { ok: false, error: "진행 중 아님" };
  if (!_mgr.paused) return { ok: true, already: true };
  _mgr.paused = false;
  bgEmit({ type: "bundle-resumed", bundle: _mgr.running, level: "", msg: "재개 — 이어서 크롤" });
  bgEmitQueue();
  if (_mgr._kick) { try { _mgr._kick(); } catch (_) {} }
  return { ok: true };
}
function mgrStop() {
  if (!_mgr.running && !_mgr.queue.length) return { ok: false, error: "진행 중 아님" };
  _mgr.stopped = true; _mgr.paused = false; _mgr.queue = [];
  bgEmit({ type: "bundle-stopping", bundle: _mgr.running, level: "warn", msg: "중지 — 창 닫고 종료 (긁은 것까지 저장)" });
  if (_mgr._kick) { try { _mgr._kick(); } catch (_) {} }
  bgEmitQueue();
  return { ok: true };
}
function mgrCancel(code) {
  const i = _mgr.queue.indexOf(code);
  if (i >= 0) { _mgr.queue.splice(i, 1); bgEmitQueue(); return { ok: true }; }
  return { ok: false, error: "대기열에 없음" };
}
function mgrSnapshot() {
  return { ok: true, running: _mgr.running, paused: _mgr.paused, stopped: _mgr.stopped,
           queue: _mgr.queue.slice(), view: _mgr.view, base: _mgr.base };
}

// ── 큐 러너 — 모음전을 하나씩 꺼내 순차 크롤. 중지 시 큐 비움. ──
async function runQueueBG() {
  bgKeepaliveStart();
  try {
    while (_mgr.queue.length) {
      if (_mgr.stopped) break;
      const code = _mgr.queue.shift();
      _mgr.running = code; _mgr.paused = false;
      bgEmitQueue();
      try { await crawlBundleAllBG(code); } catch (e) { console.warn("[moum] bundle err", code, e); }
      if (_mgr.stopped) break;
    }
  } finally {
    _mgr.queue = []; _mgr.running = null; _mgr.paused = false; _mgr.stopped = false; _mgr._kick = null;
    bgEmitQueue();
    bgKeepaliveStop();
    await closeServiceTabIfOwned();   // SW 가 띄운 백그라운드 mou-m 탭 정리
  }
}

// ── 1건 처리(창 재사용) — 백그라운드 내부 핸들러 직접 호출(메시지 왕복 없음) ──
async function crawlItemInTabBG(tabId, code, item) {
  const sk = item.source_key, url = item.url;
  if (BG_JS_SOURCES.indexOf(sk) >= 0) {
    const x = await handleNavExtract({ tabId: tabId, url: url, source_key: sk }) || {};
    return {
      url: url, source_key: sk, price: x.price, stock: x.stock, options: x.options,
      status: x.ok ? "ok" : "error", product_name: x.product_name, error: x.error || null,
      is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
    };
  }
  const grab = await handleNavGrab({ tabId: tabId, url: url });
  if (!grab || !grab.ok || !grab.html) {
    return { url: url, source_key: sk, status: "error", error: (grab && grab.error) || "HTML 수집 실패" };
  }
  if (grab.sku_diag) console.log("[moum] sku_stock", sk, url, grab.sku_diag);
  let p;
  try {
    p = await bgFetch("/api/sources/parse", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_key: sk, url: url, html: grab.html, sku_stock: grab.sku_stock || null }),
    }).then((x) => x.json());
  } catch (e) {
    return { url: url, source_key: sk, status: "error", error: "parse 호출 실패: " + e };
  }
  if (!p || !p.ok) {
    return { url: url, source_key: sk, status: "error", error: (p && (p.message || p.error)) || "parse 실패" };
  }
  const opts2 = Array.isArray(p.options) ? p.options : [];
  const priced = opts2.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  let stock = null;
  const stocks = opts2.filter((o) => o && typeof o.stock === "number");
  if (stocks.length) stock = stocks.reduce((sum, o) => sum + Math.max(0, o.stock), 0);
  const ok = price != null;
  return {
    url: url, source_key: sk, price: price, stock: stock,
    options: opts2.map((o) => ({ color: o.color_text, size: o.size_text, stock: o.stock })),
    status: ok ? "ok" : "error", product_name: p.product_name_raw || null,
    error: ok ? null : "옵션 가격 없음",
  };
}

// ── 모음전 1건 전체 크롤(백그라운드판) — ext_bridge.crawlBundleAll 과 동일 로직 ──
async function crawlBundleAllBG(code) {
  _mgr.paused = false;
  const emit = (type, fields) => bgEmit(Object.assign({ type: type, bundle: code }, fields || {}));
  emit("start", { level: "", msg: "전체 로컬 크롤 시작: " + code });
  const ENC = encodeURIComponent(code);
  try { await bgFetch("/api/bundles/" + ENC + "/crawl-reset", { method: "POST" }); } catch (_) {}
  const _finalize = () => bgFetch("/api/bundles/" + ENC + "/crawl-finalize", { method: "POST" }).then((x) => x.json()).catch(() => null);

  const r = await bgFetch("/api/bundles/" + ENC + "/option-matrix").then((x) => x.json());
  const ALL = BG_JS_SOURCES.concat(BG_PARSE_SOURCES);
  const seen = new Set();
  const bySource = {};
  (r.options || []).forEach((o) =>
    (o.sources || []).forEach((s) => {
      if (!s.product_url || ALL.indexOf(s.source_key) < 0) return;
      const key = s.source_key + "|" + s.product_url;
      if (seen.has(key)) return;
      seen.add(key);
      (bySource[s.source_key] = bySource[s.source_key] || []).push({ source_key: s.source_key, url: s.product_url });
    })
  );
  const sourceKeys = Object.keys(bySource);
  const total = sourceKeys.reduce((n, k) => n + bySource[k].length, 0);
  if (!total) { await _finalize(); emit("finish", { level: "warn", msg: "대상 URL 없음" }); return { ok: false, error: "대상 URL 없음" }; }

  let cap = bgClamp(((typeof navigator !== "undefined" && navigator.hardwareConcurrency) || 4) - 1, 1, 5);
  let concurrency = 1;
  emit("concurrency", { level: "", msg: "초기 동시 창 " + concurrency + "/" + cap, metrics: { concurrency, cap, active: 0, total, done: 0 } });

  const pendingSources = sourceKeys.slice();
  const sourceProgress = {};
  const results = [];
  const latencies = [];
  let done = 0;
  let lastSys = { cpu: null, mem: null };
  let cooldown = 0;
  let prevThroughput = 0;
  let active = 0;

  async function runSource(sk) {
    const list = bySource[sk];
    const startIdx = sourceProgress[sk] || 0;
    let winId = null, tabId = null;
    let pausedMid = false;
    try {
      const w = await handleOpenWin({});
      if (!w || !w.ok || w.tabId == null) {
        for (let j = startIdx; j < list.length; j++) { results.push({ url: list[j].url, source_key: sk, status: "error", error: (w && w.error) || "창 생성 실패" }); done++; }
        delete sourceProgress[sk];
        emit("source-done", { source: sk, level: "warn", msg: sk + " 창 생성 실패 — " + (list.length - startIdx) + "건 건너뜀", metrics: { concurrency, cap, active, done, total } });
        return;
      }
      winId = w.winId; tabId = w.tabId;
      emit("window-open", { source: sk, level: "", msg: sk + " 창 시작", metrics: { concurrency, cap, active, done, total } });
      for (let i = startIdx; i < list.length; i++) {
        if (_mgr.stopped) break;
        if (_mgr.paused) { sourceProgress[sk] = i; pausedMid = true; break; }
        const t0 = Date.now();
        let out;
        try { out = await crawlItemInTabBG(tabId, code, list[i]); }
        catch (e) { out = { url: list[i].url, source_key: sk, status: "error", error: String(e && e.message ? e.message : e) }; }
        const sec = (Date.now() - t0) / 1000;
        latencies.push(sec); if (latencies.length > 12) latencies.shift();
        results.push(out); done++; sourceProgress[sk] = i + 1;
        if (cooldown > 0) cooldown--;
        emit("item-done", {
          source: sk, level: out.status === "ok" ? "" : "warn",
          url: (out && out.url) || (list[i] && list[i].url) || null,
          lineId: out.status === "ok" ? (sk + "|" + ((out && out.url) || (list[i] && list[i].url) || "")) : null,
          msg: out.status === "ok"
            ? (sk + " 표면 " + (out.price != null ? out.price.toLocaleString() + "원" : "가격없음") + " (" + sec.toFixed(1) + "s)")
            : (sk + " 실패: " + (out.error || "")),
          metrics: { concurrency, cap, active, done, total, avgSec: +bgMedian(latencies).toFixed(2), cpu: lastSys.cpu, mem: lastSys.mem },
        });
        if (done % 3 === 0) {
          lastSys = await handleSysinfo().then((s) => ({ cpu: s && s.cpu != null ? s.cpu : null, mem: s && s.mem != null ? s.mem : null })).catch(() => ({ cpu: null, mem: null }));
          if (lastSys.cpu != null || lastSys.mem != null) {
            const hot = (lastSys.cpu != null && lastSys.cpu >= 90) || (lastSys.mem != null && lastSys.mem >= 96);
            if (hot) emit("resource", { level: "warn", msg: "자원 높음 — CPU " + lastSys.cpu + "% / MEM " + lastSys.mem + "%", metrics: { concurrency, cap, active, cpu: lastSys.cpu, mem: lastSys.mem } });
          }
        }
      }
    } finally {
      if (winId != null) { try { await handleCloseWin({ winId: winId }); } catch (_) {} }
    }
    if (pausedMid) { pendingSources.unshift(sk); return; }
    if (_mgr.stopped) return;
    delete sourceProgress[sk];
    emit("source-done", { source: sk, level: "done", msg: sk + " 완료 (" + list.length + "건)", metrics: { concurrency, cap, active, done, total } });
  }

  function evaluateConcurrency() {
    if (cooldown > 0) return;
    if (latencies.length < 3) return;
    const med = bgMedian(latencies) || 0.001;
    const throughput = concurrency / med;
    const cpu = lastSys.cpu, mem = lastSys.mem;
    if ((cpu != null && cpu >= 95) || (mem != null && mem >= 98)) {
      if (concurrency > 1) { concurrency--; cooldown = 3; prevThroughput = throughput; emit("concurrency", { level: "down", msg: "자원 한계(CPU≥95·MEM≥98) 강제 −1 → " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
      return;
    }
    const blockUp = (cpu != null && cpu >= 90) || (mem != null && mem >= 96);
    if (throughput > prevThroughput * 1.05) {
      prevThroughput = throughput;
      if (concurrency < cap && !blockUp) { concurrency++; cooldown = 3; emit("concurrency", { level: "up", msg: "처리량 개선 → 창 +1 = " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
      else if (blockUp && concurrency < cap) { emit("resource", { level: "warn", msg: "처리량 여력 있으나 자원 높음(CPU≥90·MEM≥96) → +1 보류", metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
    } else if (throughput < prevThroughput * 0.9 && concurrency > 1) {
      concurrency--; cooldown = 3; prevThroughput = throughput; emit("concurrency", { level: "down", msg: "처리량 하락 → 창 −1 = " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } });
    } else { prevThroughput = Math.max(prevThroughput, throughput); }
  }

  let endReason = "done";
  await new Promise((resolveAll) => {
    let done2 = false; let pollTimer = null;
    function finish(reason) { if (done2) return; done2 = true; endReason = reason; if (pollTimer) clearTimeout(pollTimer); resolveAll(); }
    function schedulePoll() { if (pollTimer) clearTimeout(pollTimer); pollTimer = setTimeout(() => { pollTimer = null; pump(); }, 1200); }
    function pump() {
      if (done2) return;
      if (_mgr.stopped) { if (active === 0) finish("stopped"); else schedulePoll(); return; }
      if (_mgr.paused) { if (active > 0) schedulePoll(); return; }
      evaluateConcurrency();
      while (active < concurrency && pendingSources.length > 0) {
        const sk = pendingSources.shift(); active++;
        runSource(sk).catch((_) => {}).then(() => { active--; pump(); });
      }
      if (active === 0 && pendingSources.length === 0) { finish("done"); return; }
      schedulePoll();
    }
    _mgr._kick = pump;
    pump();
  });
  _mgr._kick = null;

  const items = results.map((x) => ({
    url: x.url, price: x.price, stock: x.stock, options: x.options,
    status: x.status, product_name: x.product_name, error: x.error,
    is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
  }));
  const save = await bgFetch("/api/sources/crawl-result", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
  }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));

  try { await bgFetch("/api/bundles/" + ENC + "/touch-crawled", { method: "POST" }); } catch (_) {}

  try {
    const rr = await bgFetch("/api/bundles/" + ENC + "/option-matrix").then((x) => x.json());
    const repByLine = {};
    (rr.options || []).forEach((o) => (o.sources || []).forEach((s) => {
      const p = s.crawled_price;
      if (!(p > 0) || !s.product_url) return;
      const inStock = (s.crawled_stock == null) || (s.crawled_stock > 0);
      if (!inStock) return;
      const lid = s.source_key + "|" + s.product_url;
      const cur = repByLine[lid];
      if (!cur || p < cur.sale_price) repByLine[lid] = { sku: o.sku, source_id: s.source_id, source_key: s.source_key, url: s.product_url, sale_price: p, lineId: lid };
    }));
    const reps = Object.values(repByLine);
    if (reps.length) {
      const bd = await bgFetch("/api/source-benefits/breakdowns", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: reps.map((r) => ({ sku: r.sku, source_id: r.source_id, sale_price: r.sale_price })) }),
      }).then((x) => x.json()).catch(() => null);
      const bdres = (bd && bd.results) || {};
      reps.forEach((r) => {
        const b = bdres[r.sku + "|" + r.source_id];
        if (!b || b.error || b.final_price == null) return;
        const surf = Math.round(b.sale_price != null ? b.sale_price : r.sale_price);
        const buy = Math.round(b.final_price);
        emit("item-final", { source: r.source_key, level: "done", lineId: r.lineId, url: r.url, surf: surf, buy: buy, msg: r.source_key + " 표면 " + surf.toLocaleString() + "원 → 매입 " + buy.toLocaleString() + "원" });
      });
    }
  } catch (_) {}

  const okCount = results.filter((x) => x.status === "ok").length;
  const finalize = await _finalize();
  const stoppedTxt = endReason === "stopped" ? "중지됨 — " : "완료 — ";
  emit("finish", {
    level: endReason === "stopped" ? "warn" : "done", stopped: endReason === "stopped",
    msg: stoppedTxt + okCount + "/" + results.length + " 성공 · 저장 " + ((save && save.updated) || 0) + "건" + (finalize && finalize.blocked ? " · 판매차단 " + finalize.blocked : ""),
    metrics: { concurrency, cap, active, done, total, cpu: lastSys.cpu, mem: lastSys.mem },
  });
  return { ok: true, crawled: results.length, ok_count: okCount, save, finalize, stopped: endReason === "stopped" };
}

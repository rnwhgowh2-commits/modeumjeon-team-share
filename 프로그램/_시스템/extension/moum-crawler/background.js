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

const MOUM_EXT_VERSION = "0.6.2";  // 0.6.0 = 백그라운드 크롤 상태 영속(chrome.storage.session)+SW 재가동 자동재개. 0.5.x: 백그라운드 엔진·혜택 수집·롯데온 옵션매핑API

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
      // 공통 walker: 객체트리서 (stockQuantity + optionName1/optionName) 배열 찾아 색||사이즈→수량
      function walkFor(root) {
        const map = {}; let combos = 0;
        (function walk(o, d) {
          if (!o || d > 8) return;
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
          } else if (typeof o === "object") { for (const k in o) walk(o[k], d + 1); }
        })(root, 0);
        return { map, combos };
      }
      // [2026-06-15 fix 스스] ① __PRELOADED_STATE__ 직접 훑기 — 드롭다운(품절임박/품절)을 그리는
      //   소스가 state 안에 있다. API(빈응답 다발) 안 거치고 여기서 잡으면 가장 견고.
      const st = walkFor(state);
      if (st.combos) return { map: st.map, combos: st.combos, via: "state" };
      // ② API 폴백 (state 에 옵션조합 없을 때)
      const A = (state.simpleProductForDetailPage && state.simpleProductForDetailPage.A) || {};
      const ch = A.channel || {};
      const cu = ch.channelUid;
      // [2026-06-15 fix] A.productNo(예 5817455588)를 쓰면 /n/v2/.../products/{productNo} 가
      //   HTTP 204(빈 응답) → resp.ok=true라 resp.json() throw → 조용히 999 폴백(silent fail).
      //   channelProductNo(=A.id, URL의 상품번호 5844147017)를 써야 200 + per-SKU 재고가 온다.
      const pno = A.channelProductNo || A.id;   // ⚠️ A.productNo 는 쓰지 말 것(204)
      if (!cu || !pno) return { err: "no-ids:stCombos0" };
      let resp, txt = "";
      try {
        resp = await fetch(`/n/v2/channels/${cu}/products/${pno}`, { credentials: "include", headers: { accept: "application/json" } });
        txt = await resp.text();
      } catch (e) { return { err: "fetch-exc:" + String(e).slice(0, 40) }; }
      if (!resp.ok) return { err: "http-" + resp.status };
      if (!txt || txt.length < 2) return { err: "empty-body:" + (txt ? txt.length : 0) };
      let j; try { j = JSON.parse(txt); } catch (e) { return { err: "api-parse:len" + txt.length }; }
      const ap = walkFor(j);
      if (!ap.combos) return { err: "no-combos", topKeys: Object.keys(j).slice(0, 14) };
      return { map: ap.map, combos: ap.combos, via: "api" };
    } catch (e) { return { err: String(e).slice(0, 90) }; }
  })();
}

// navGrab — 그 탭을 url 로 이동 → 로드 완료 + 안정화 대기 → outerHTML 반환. (창 안 닫음)
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
      // 공통 walker: 객체트리서 (stockQuantity + optionName1/optionName) 배열 찾아 색||사이즈→수량
      function walkFor(root) {
        const map = {}; let combos = 0;
        (function walk(o, d) {
          if (!o || d > 8) return;
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
          } else if (typeof o === "object") { for (const k in o) walk(o[k], d + 1); }
        })(root, 0);
        return { map, combos };
      }
      // [2026-06-15 fix 스스] ① __PRELOADED_STATE__ 직접 훑기 — 드롭다운(품절임박/품절)을 그리는
      //   소스가 state 안에 있다. API(빈응답 다발) 안 거치고 여기서 잡으면 가장 견고.
      const st = walkFor(state);
      if (st.combos) return { map: st.map, combos: st.combos, via: "state" };
      // ② API 폴백 (state 에 옵션조합 없을 때)
      const A = (state.simpleProductForDetailPage && state.simpleProductForDetailPage.A) || {};
      const ch = A.channel || {};
      const cu = ch.channelUid;
      // [2026-06-15 fix] A.productNo(예 5817455588)를 쓰면 /n/v2/.../products/{productNo} 가
      //   HTTP 204(빈 응답) → resp.ok=true라 resp.json() throw → 조용히 999 폴백(silent fail).
      //   channelProductNo(=A.id, URL의 상품번호 5844147017)를 써야 200 + per-SKU 재고가 온다.
      const pno = A.channelProductNo || A.id;   // ⚠️ A.productNo 는 쓰지 말 것(204)
      if (!cu || !pno) return { err: "no-ids:stCombos0" };
      let resp, txt = "";
      try {
        resp = await fetch(`/n/v2/channels/${cu}/products/${pno}`, { credentials: "include", headers: { accept: "application/json" } });
        txt = await resp.text();
      } catch (e) { return { err: "fetch-exc:" + String(e).slice(0, 40) }; }
      if (!resp.ok) return { err: "http-" + resp.status };
      if (!txt || txt.length < 2) return { err: "empty-body:" + (txt ? txt.length : 0) };
      let j; try { j = JSON.parse(txt); } catch (e) { return { err: "api-parse:len" + txt.length }; }
      const ap = walkFor(j);
      if (!ap.combos) return { err: "no-combos", topKeys: Object.keys(j).slice(0, 14) };
      return { map: ap.map, combos: ap.combos, via: "api" };
    } catch (e) { return { err: String(e).slice(0, 90) }; }
  })();
}

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
  const world = (sk === "lotteon") ? "MAIN" : "ISOLATED";
  const out = await chrome.scripting.executeScript({
    target: { tabId: tabId }, world: world, func: extractor,
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

// [2026-06-14 fix F] 유닛당 하드 타임아웃 — 한 소싱처 1건이 행(예: 네이버 봇차단 페이지가
//   never-complete)해도 전체크롤이 영구 정지하지 않게. 정상 무신사 유닛(waitTabComplete 25s
//   + 혜택 아코디언 ~8s)보다 넉넉히 큰 60s. 타임아웃 시 그 유닛만 error 로 표면화하고 진행.
const UNIT_TIMEOUT_MS = 60000;
function withTimeout(promise, ms) {
  return new Promise((resolve) => {
    let settled = false;
    const to = setTimeout(() => { if (!settled) { settled = true; resolve({ __timeout: true }); } }, ms);
    Promise.resolve(promise).then(
      (v) => { if (!settled) { settled = true; clearTimeout(to); resolve(v); } },
      (e) => { if (!settled) { settled = true; clearTimeout(to); resolve({ __error: String(e && e.message ? e.message : e) }); } }
    );
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

  // ★ 2026-06-14 — 현재 페이지(로그인 상태 그대로) 혜택영역 자동 수집 (v0.4.6).
  //   ① 접힌 아코디언('최대 적립' 등)을 펼친다 — innerText 는 숨김=빈값이라 적립내역을
  //      놓침(무신사머니 결제적립 누락 사고). textContent + 펼침으로 빠짐없이.
  //   ② 행(row) 단위 textContent 수집 = 라벨+금액 한 줄(키워드+금액 둘 다 있는 행).
  //   ③ off 신호('등급 할인 불가'/'쿠폰 없음'/'적용 안함')는 금액 없어도 게이트 veto용 포함.
  //   금액은 서버가 라인(matched_lines)에서 추출 — 별도 키 계약 불필요. (실브라우저 3상태 검증)
  async function collectBenefitLines() {
    try {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const norm = () => (document.body.textContent || "").replace(/\s+/g, " ");
      // 적립 내역(접힌 '최대 적립')이 렌더됐는지 검증식 — 이게 보일 때까지 펼침 재시도.
      const hasAccrual = () => /후기 적립\s*[\d,]+\s*원|포인트 10% 적립\s*[\d,]+|등급 적립\([^)]*\)\s*[\d,]+/.test(norm());
      // ★ 크롤 새 창은 React 하이드레이션 전이라 1회 클릭이 자주 실패 → '펼쳐질 때까지' 재시도
      //   (최대 ~8초). 검증식 통과하면 즉시 종료. (실패해도 아래서 있는 만큼 수집)
      for (let i = 0; i < 16 && !hasAccrual(); i++) {
        [...document.querySelectorAll("body *")].forEach((el) => {
          if (el.childElementCount > 4) return;
          const t = (el.textContent || "").replace(/\s+/g, " ").trim();
          if (/최대 적립|나의 할인가/.test(t) && t.length < 40) { try { el.click(); } catch (_) {} }
        });
        await sleep(500);
      }
      const KW = /(쿠폰|적립|할인|머니|혜택|등급|페이|즉시|삼성|토스|카카오|후기|결제)/;
      // 값: 금액(원) 또는 율(%).  부재신호: 없음/불가/적용안함/품절/사용불가 등(혜택이 '없다'는 상태).
      const AMT = /([\-+]?\s*[\d,]{2,}\s*원|\d+(\.\d+)?\s*%)/;
      const ABS = /(없음|불가|불가능|사용\s*불가|적용\s*안함|미적용|품절|해당\s*없음)/;
      const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "svg", "path"]);
      const rows = [];
      // ★ 완전수집: 혜택 키워드가 있고 (값이 있거나 || '없음/불가' 부재신호가 있으면) 한 줄로 담는다.
      //   '없으면 없다'까지 인지하도록 부재 라인도 포함 — 서버 게이트가 exclude(없음/불가)로 off 판정.
      document.querySelectorAll("body *").forEach((el) => {
        if (SKIP.has(el.tagName) || el.childElementCount > 6) return;
        const t = (el.textContent || "").replace(/\s+/g, " ").trim();
        if (!t || t.length > 90) return;
        if (/\{|\}|props|pageProps/.test(t)) return; // SPA JSON 잔재 배제
        if (!KW.test(t)) return;
        if (!AMT.test(t) && !ABS.test(t)) return;   // 값도 부재신호도 없으면 의미 없음 → 제외
        rows.push(t);
      });
      // 부재신호 단독 잎(키워드+없음/불가만, 값 없는 짧은 라벨)도 빠짐없이 — 게이트 veto 재료.
      document.querySelectorAll("body *").forEach((el) => {
        if (el.childElementCount !== 0) return;
        const t = (el.textContent || "").replace(/\s+/g, " ").trim();
        if (!t || t.length > 40) return;
        if (KW.test(t) && ABS.test(t)) rows.push(t);
      });
      const uniq = [...new Set(rows)].sort((a, b) => a.length - b.length);
      const kept = [];
      uniq.forEach((t) => { if (!kept.some((k) => k.includes(t))) kept.push(t); });
      return kept;
    } catch (e) {
      return null; // 수집 실패 — benefits_ok=false 로 표면화
    }
  }
  const _benLines = await collectBenefitLines();

  return {
    ok: !!price,
    price: price,                       // 표면노출가(salePrice) — 검증 통과 시만, 아니면 null
    stock: anyStock ? 999 : 0,          // 재고 있으면 sentinel
    product_name: document.title.split("-")[0].trim().slice(0, 120),
    member_price: member,               // 참고용(회원가, '나의 할인가') — 계산 base 아님
    sale_price: surface, surface_price: surface, normal_price: normal,
    is_logged_in: member != null,
    benefits_ok: Array.isArray(_benLines) && _benLines.length > 0,
    benefit_lines: Array.isArray(_benLines) ? _benLines : [],
    benefit_amounts: {},
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

  // ── [2026-06-15 fix 롯데온 v3] 옵션매핑 API 직읽기 (범용·fail-safe, 라이브 ★FIN 검증) ──
  //   롯데온 플랫폼 표준 API 한 번 fetch → 전 옵션조합 재고 즉시(클릭/색순회/렌더대기 전부 폐기).
  //     URL: pbf.lotteon.com/product/v2/detail/option/mapping/{spdNo}/{sitmNo}  (쿼리 없이 경로만 200, ★URL검증)
  //     data.optionInfo.optionList = 옵션 축들(각 {label,value}) — 축 이름 안 고정(범용: 색상/사이즈/기타 N축)
  //     data.optionInfo.optionMappingInfo["{축1value}_{축2value}…"] = {stkQty, sitmNoSlStatCd, displayPrc}
  //   재고: sitmNoSlStatCd==="SALE" && stkQty>0 → stkQty(실수량) / 아니면 0(품절) / 키없음 → 미존재(제외, 거짓충분 방지)
  //   URL 확보: ① 페이지가 부른 mapping URL(performance) ② location 에서 spd/sitm 조립.
  //   ★ fail-safe: API 실패(URL/CORS/파싱/빈옵션) → DOM 스캔 폴백 → 그래도 0건이면 옵션 비움(거짓충분 절대 금지).
  let options = [];
  let mapUrl = "";
  // ① performance 엔트리(페이지가 이미 호출 — LO·PD 공통). 늦으면 ~10s 폴링. 쿼리 제거(경로만으로 200).
  for (let i = 0; i < 25; i++) {
    const hit = (performance.getEntriesByType("resource") || [])
      .map((e) => e.name).find((u) => /\/product\/v2\/detail\/option\/mapping\//.test(u));
    if (hit) { mapUrl = hit.split("?")[0]; break; }
    await sleep(400);
  }
  // ② 폴백: location 에서 조립 (/p/product/{spd}?sitmNo={sitm}) — LO형 URL 커버
  if (!mapUrl) {
    const spd = (location.pathname.match(/\/product\/([A-Za-z0-9]+)/) || [])[1] || "";
    const sitm = new URLSearchParams(location.search).get("sitmNo") || "";
    if (spd && sitm) mapUrl = "https://pbf.lotteon.com/product/v2/detail/option/mapping/" + spd + "/" + sitm;
  }
  if (mapUrl) {
    try {
      const resp = await fetch(mapUrl, { credentials: "include", headers: { accept: "application/json" } });
      if (resp.ok) {
        const j = await resp.json();
        const oi = (j && j.data && j.data.optionInfo) || {};
        const axes = oi.optionList || [];
        const omi = oi.optionMappingInfo || {};
        const colorAxis = axes.find((a) => a.title === "색상") || null;
        const sizeAxis = axes.find((a) => /사이즈|size/i.test(a.title || "")) || null;
        const colorOpts = (colorAxis && colorAxis.options) || [{ value: "", label: "" }];
        const sizeOpts = (sizeAxis && sizeAxis.options)
          || (axes.length ? (axes[axes.length - 1].options || []) : []);
        const skuStock = (sku) => {
          const sale = sku && sku.sitmNoSlStatCd === "SALE";
          const q = Number(sku && sku.stkQty);
          return (sale && q > 0) ? q : 0;
        };
        // [2026-06-19 fix #4] 대체상품 가드 — 롯데온은 사이즈가 품절되면 그 옵션 슬롯에 '다른 상품'
        //   (spdNo 다름·stkQty 999·가격 다름)을 끼워넣는다. 그 상품 재고를 이 사이즈 재고로 오인하면
        //   '품절인데 재고있음' 사고. 리스팅 진짜 상품 spdNo(=URL의 LO번호)와 다른 SKU → 실제 품절(0).
        const _realSpd = ((location.pathname.match(/\/product\/(LO[0-9]+)/i) || [])[1] || "").toUpperCase();
        if (sizeOpts.length) {
          for (const c of colorOpts) {
            for (const s of sizeOpts) {
              const key = (c.value || "") + "_" + (s.value || "");
              const sku = omi[key] || (!c.value ? omi[s.value] : null);
              if (!sku) continue;                          // 미존재 조합 제외(거짓충분 방지)
              const size = (s.label || "").replace(/mm/i, "").trim();
              if (!size) continue;
              const _isSub = _realSpd && sku.spdNo && String(sku.spdNo).toUpperCase() !== _realSpd;
              options.push({ color: (c.label || "").trim(), size, price: valid ? price : null, stock: _isSub ? 0 : skuStock(sku) });
            }
          }
        } else {
          // 옵션 없는 단일상품 — 매핑 1건이면 상품레벨 재고로
          const vals = Object.values(omi);
          if (vals.length === 1) options.push({ color: "", size: "", price: valid ? price : null, stock: skuStock(vals[0]) });
        }
      }
    } catch (e) { /* CORS/파싱 실패 → DOM 폴백 */ }
  }
  // ③ DOM 스캔 폴백 (API 0건). [품절]제거·숫자필터·N먼저(버그1수정).
  if (!options.length) {
    const m = {};
    for (const li of document.querySelectorAll("ul.selectLists > li")) {
      const cap = li.querySelector(".caption");
      if (!cap) continue;
      const size = (cap.textContent || "").replace(/^\s*\[품절\]\s*/, "").replace(/mm/i, "").trim();
      if (!/^\d{2,3}$/.test(size)) continue;
      const stEl = li.querySelector(".stock");
      const liSold = /품절|sold|disable|soldout/i.test((li.className || "").toString())
        || li.getAttribute("aria-disabled") === "true";
      let st = 999;
      if (liSold) st = 0;
      else {
        const t = stEl ? stEl.textContent.trim() : "";
        const mm = t.match(/(\d+)\s*개\s*남음/) || t.match(/마지막\s*(\d+)\s*개/);
        st = mm ? Math.max(0, parseInt(mm[1], 10)) : (/품절|일시품절/.test(t) ? 0 : 999);
      }
      if (!(size in m) || st < m[size]) m[size] = st;
    }
    options = Object.keys(m).map((size) => ({ color: "", size, price: valid ? price : null, stock: m[size] }));
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
  try { bgPersist(); } catch (_) {}   // 큐/상태 변화마다 체크포인트 갱신
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
  try { bgPersist(); } catch (_) {}   // 진행 변화마다 체크포인트 갱신
}

// ── SW 깨우기 + 자동 재개(2026-06-18) ──────────────────────────────────────
//   MV3 서비스워커는 유휴 ~30s 면 크롬이 잠재워 in-memory 루프(_mgr)가 사라진다.
//   대책: ① 상태를 chrome.storage.session 에 영속(bgPersist) ② keepalive 알람이
//   크롤 중 ~30s 마다 SW 를 깨움 → 깨어날 때 top-level bgBootResume 이 체크포인트의
//   '진행 중 크롤'을 감지해 runQueueBG 로 이어서 재가동(끊긴 모음전은 처음부터 재크롤,
//   하드리셋+finalize fail-safe 라 잘못 저장 없음). → "탭 닫아도/새로고침해도 지속".
try {
  chrome.alarms.onAlarm.addListener((a) => {
    if (!a || a.name !== "moum-keepalive") return;
    try { if (_mgr.running) bgPersist(); } catch (_) {}
    // SW 가 죽었다 알람으로 깨어난 경우(_mgr 비어있음) → 체크포인트로 재가동
    try { if (!_mgr.running) bgBootResume(); } catch (_) {}
  });
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
    try { bgClearPersist(); } catch (_) {}   // 크롤 종료 — 체크포인트 제거(불필요 재가동 방지)
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
      // [2026-06-14 fix] '현재 브라우저 기준' 혜택 스냅샷 필드 — 추출기가 긁은 혜택을
      //   서버(_build_crawl_snapshot)까지 전달. 이전엔 여기서 누락돼 무신사 미수집(폴백 게이트)됐음.
      benefits_ok: x.benefits_ok, benefit_lines: x.benefit_lines, benefit_amounts: x.benefit_amounts,
      surface_price: x.surface_price, member_price: x.member_price,
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

// ── [2026-06-18] 저장 헬퍼 — 결과 item 매핑 + crawl-result 저장(소싱처별 증분/최종 공용) ──
//   ★ 버그 수정: 기존엔 모든 소싱처 크롤이 끝난 뒤 '최종 1회'만 bgFetch 저장했는데,
//   그 마지막 저장이 조용히 0건 실패(창 다 닫힌 뒤 서비스탭 fetch 불안정)하면 수집한
//   가격이 전부 버려지고(하드리셋만 남아) 전 옵션이 판매차단됐다. 대책=소싱처가 끝날
//   때마다 그 소싱처 결과를 즉시 저장(크롤 도중 = bgFetch 정상 동작 구간) + 저장결과를
//   로그에 표면화(조용한 실패 제거). 최종 일괄 저장은 백스톱으로 유지(중복 저장은 무해).
function toItemBG(x) {
  return {
    url: x.url, price: x.price, stock: x.stock, options: x.options,
    status: x.status, product_name: x.product_name, error: x.error,
    is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
    benefits_ok: x.benefits_ok, benefit_lines: x.benefit_lines, benefit_amounts: x.benefit_amounts,
    surface_price: x.surface_price, member_price: x.member_price,
  };
}
async function saveItemsBG(items) {
  if (!items || !items.length) return { ok: true, updated: 0 };
  return await bgFetch("/api/sources/crawl-result", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: items.map(toItemBG) }),
  }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e && e.message ? e.message : e) }));
}

// ── 모음전 1건 전체 크롤(백그라운드판) — ext_bridge.crawlBundleAll 과 동일 로직 ──
async function crawlBundleAllBG(code) {
  _mgr.paused = false;
  const emit = (type, fields) => bgEmit(Object.assign({ type: type, bundle: code }, fields || {}));
  emit("start", { level: "", msg: "전체 로컬 크롤 시작: " + code });
  const ENC = encodeURIComponent(code);
  try { await bgFetch("/api/bundles/" + ENC + "/crawl-reset", { method: "POST" }); } catch (_) {}
  const _finalize = () => bgFetch("/api/bundles/" + ENC + "/crawl-finalize", { method: "POST" }).then((x) => x.json()).catch(() => null);
  let savedTotal = 0;   // 소싱처별 증분 저장 누적(완료 메시지·표면화용)

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
      (bySource[s.source_key] = bySource[s.source_key] || []).push({ source_key: s.source_key, url: s.product_url, url_type: s.url_type || "dan" });
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
    const srcOuts = [];   // 이 소싱처 결과 누적 → 소싱처 완료 즉시 증분 저장용
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
        // [2026-06-14 fix F] 하드 타임아웃으로 감싸 행 방지. 타임아웃/예외도 error 유닛으로
        //   표면화하고 다음 유닛 진행 → 한 건 행이 전체크롤을 마비시키지 않음 + 중지 반응성 회복.
        const _r = await withTimeout(crawlItemInTabBG(tabId, code, list[i]), UNIT_TIMEOUT_MS);
        if (_r && _r.__timeout) {
          out = { url: list[i].url, source_key: sk, status: "error", error: "유닛 타임아웃 " + (UNIT_TIMEOUT_MS / 1000) + "s(행 추정·건너뜀)" };
        } else if (_r && _r.__error) {
          out = { url: list[i].url, source_key: sk, status: "error", error: _r.__error };
        } else {
          out = _r || { url: list[i].url, source_key: sk, status: "error", error: "결과 없음" };
        }
        const sec = (Date.now() - t0) / 1000;
        latencies.push(sec); if (latencies.length > 12) latencies.shift();
        results.push(out); srcOuts.push(out); done++; sourceProgress[sk] = i + 1;
        if (cooldown > 0) cooldown--;
        emit("item-done", {
          source: sk, level: out.status === "ok" ? "" : "warn",
          url: (out && out.url) || (list[i] && list[i].url) || null,
          // [2026-06-19 D8] URL별 상세표(상품명·표면노출가)용 — 위젯이 per-URL 행 렌더에 사용.
          name: (out && out.product_name) || null,
          surf: (out && out.price != null) ? out.price : null,
          url_type: (list[i] && list[i].url_type) || "dan",
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
      // [2026-06-19 fix ②③] 실패(error) URL 1회 자동 재시도 — 일시 실패(타임아웃·순간차단) 자가치유.
      //   창이 아직 열린 상태에서 재크롤. 성공 시 srcOuts/results 의 해당 항목을 교체(저장은 ok만).
      if (!_mgr.stopped && !_mgr.paused) {
        const _failed = srcOuts.filter((o) => o && o.status === "error");
        if (_failed.length && tabId != null) {
          emit("retry", { source: sk, level: "", msg: sk + " 실패 " + _failed.length + "건 자동 재시도", metrics: { concurrency, cap, active, done, total } });
          for (const _f of _failed) {
            if (_mgr.stopped || _mgr.paused) break;
            const _orig = list.find((x) => x.url === _f.url) || { url: _f.url };
            const _r2 = await withTimeout(crawlItemInTabBG(tabId, code, _orig), UNIT_TIMEOUT_MS);
            const _out2 = (_r2 && !_r2.__timeout && !_r2.__error && _r2.status === "ok") ? _r2 : null;
            if (_out2) {
              const _si = srcOuts.indexOf(_f); if (_si >= 0) srcOuts[_si] = _out2;
              const _ri = results.indexOf(_f); if (_ri >= 0) results[_ri] = _out2;
              // [2026-06-22] "item-retried" 타입 사용 — "item-done" 은 bgUpdateView 에서 s.done++ 하므로
              //   재시도 성공 시에도 "item-done" 을 쓰면 s.done 이 이중 증가(42/40 오버카운트 버그).
              emit("item-retried", { source: sk, level: "", url: _out2.url, name: _out2.product_name || null, surf: (_out2.price != null) ? _out2.price : null, lineId: sk + "|" + _out2.url, msg: sk + " 재시도 성공 — 표면 " + (_out2.price != null ? _out2.price.toLocaleString() + "원" : "가격없음"), metrics: { concurrency, cap, active, done, total } });
            }
          }
        }
      }
    } finally {
      if (winId != null) { try { await handleCloseWin({ winId: winId }); } catch (_) {} }
    }
    if (pausedMid) { pendingSources.unshift(sk); return; }
    if (_mgr.stopped) return;
    delete sourceProgress[sk];
    // ★ 소싱처 완료 즉시 증분 저장(크롤 도중 = bgFetch 정상 구간). 최종 일괄저장 실패해도 보존.
    const okOuts = srcOuts.filter((o) => o && o.status === "ok");
    const sv = await saveItemsBG(okOuts);
    const svOk = !!(sv && sv.ok && (sv.updated || 0) > 0);
    savedTotal += (sv && sv.updated) || 0;
    emit("source-saved", {
      source: sk, level: svOk ? "done" : (okOuts.length ? "warn" : ""),
      msg: sk + " 저장 " + ((sv && sv.updated) || 0) + "/" + okOuts.length + "건"
        + ((sv && sv.error) ? (" ⚠️실패: " + sv.error) : ((okOuts.length && !svOk) ? " ⚠️0건(저장 실패)" : "")),
      metrics: { concurrency, cap, active, done, total },
    });
    // [2026-06-18] 정직성 게이트 — 성공 0건인데 '완료'로 위장하던 버그 제거(silent fail 표면화).
    //   okOuts = 이 소싱처 status==='ok' 건. 전건성공=완료 / 부분=부분실패 / 0건=전건실패.
    const _okN = okOuts.length;
    emit("source-done", {
      source: sk,
      level: (_okN > 0 && _okN >= list.length) ? "done" : "warn",
      msg: sk + (_okN === 0 ? " ⚠️ 전건 실패" : (_okN >= list.length ? " 완료" : " ⚠️ 부분 실패")) + " (" + _okN + "/" + list.length + "건 성공)",
      metrics: { concurrency, cap, active, done, total },
    });
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

  // 최종 일괄 저장(백스톱) — 소싱처별 증분 저장이 이미 됐으면 중복(무해). toItemBG 공용 매핑.
  const save = await saveItemsBG(results);
  // ★ 저장 결과 표면화 — 조용한 실패 제거([[project_silent_failure_bug_class]]).
  emit("save-result", {
    level: (save && save.ok && (save.updated || 0) > 0) ? "" : "warn",
    msg: "최종 일괄 저장 " + ((save && save.updated) || 0) + "건"
      + ((save && save.error) ? (" ⚠️실패: " + save.error) : ((save && !(save.updated > 0)) ? " ⚠️0건" : "")),
  });

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
        emit("item-final", { source: r.source_key, level: "done", lineId: r.lineId, url: r.url, surf: surf, buy: buy, steps: (b.steps || null), msg: r.source_key + " 표면 " + surf.toLocaleString() + "원 → 매입 " + buy.toLocaleString() + "원" });
      });
    }
  } catch (_) {}

  const okCount = results.filter((x) => x.status === "ok").length;
  const finalize = await _finalize();
  const stoppedTxt = endReason === "stopped" ? "중지됨 — " : "완료 — ";
  emit("finish", {
    level: endReason === "stopped" ? "warn" : "done", stopped: endReason === "stopped",
    msg: stoppedTxt + okCount + "/" + results.length + " 성공 · 저장 " + Math.max(savedTotal, (save && save.updated) || 0) + "건" + (finalize && finalize.blocked ? " · 판매차단 " + finalize.blocked : ""),
    metrics: { concurrency, cap, active, done, total, cpu: lastSys.cpu, mem: lastSys.mem },
  });
  return { ok: true, crawled: results.length, ok_count: okCount, save, finalize, stopped: endReason === "stopped" };
}

// ════════════════════════════════════════════════════════════════════
//  [2026-06-18] 백그라운드 크롤 상태 영속 + SW 재가동 자동재개
//   _mgr(큐·running·base·view)를 chrome.storage.session 에 저장한다(브라우저 세션 한정 —
//   브라우저 완전 종료 시 자동 소멸 = 재부팅 후엔 재개 안 함이 맞음). MV3 SW 가 잠들었다/
//   죽었다 다시 깨어나면(top-level 1회 + keepalive 알람) bgBootResume 이 체크포인트를 읽어
//   진행 중이던 크롤을 runQueueBG 로 이어서 돌린다. 추출·아이템 로직은 일절 안 건드림
//   (끊긴 모음전을 처음부터 재크롤만 — 하드리셋+finalize fail-safe 라 잘못 저장 없음).
// ════════════════════════════════════════════════════════════════════
const _CKPT_KEY = "moum_crawl_ckpt";
function bgPersist() {
  try {
    const ck = { queue: _mgr.queue.slice(), running: _mgr.running, base: _mgr.base,
                 paused: _mgr.paused, view: _mgr.view, ts: Date.now() };
    chrome.storage.session.set({ [_CKPT_KEY]: ck }, () => { void chrome.runtime.lastError; });
  } catch (_) {}
}
function bgClearPersist() {
  try { chrome.storage.session.remove(_CKPT_KEY, () => { void chrome.runtime.lastError; }); } catch (_) {}
}
let _bootResumed = false;
function bgBootResume() {
  if (_bootResumed || _mgr.running) return;   // 이미 재가동했거나 진행 중이면 중복 방지
  try {
    chrome.storage.session.get(_CKPT_KEY, (o) => {
      void chrome.runtime.lastError;
      const ck = o && o[_CKPT_KEY];
      if (!ck || !ck.running) return;          // 진행 중이던 크롤 없음 → no-op
      if (_bootResumed || _mgr.running) return; // 비동기 사이 새 크롤이 시작됐으면 양보
      _bootResumed = true;
      _mgr.base = ck.base || _mgr.base;
      _mgr.view = ck.view || {};
      const q = [ck.running];                  // 끊긴 모음전을 큐 맨 앞에 + 나머지 대기열 복원
      (ck.queue || []).forEach((c) => { if (c && q.indexOf(c) < 0) q.push(c); });
      _mgr.queue = q; _mgr.running = null; _mgr.paused = false; _mgr.stopped = false;
      bgEmit({ type: "resume-boot", bundle: ck.running, level: "", msg: "백그라운드 재가동 — 중단된 크롤 이어서 진행" });
      bgEmitQueue();
      runQueueBG();
    });
  } catch (_) {}
}
// SW 가 (재)기동될 때마다 1회 시도 — 진행 중이던 크롤이 있으면 자동 재개.
try { bgBootResume(); } catch (_) {}

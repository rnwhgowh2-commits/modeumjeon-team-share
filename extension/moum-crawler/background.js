// background.js — 확장 서비스 워커. 실제 크롤(소싱처 수집)을 담당.
//  소싱처별 "레시피(추출 함수)" = EXTRACTORS. 크롤 엔진이 각 URL을 백그라운드 탭으로
//  열고 → 그 페이지 컨텍스트에서 추출 함수 실행 → 결과 수집 → 탭 닫음.
//  (로그인된 브라우저로 직접 긁으므로 무신사 회원가·롯데온 SPA가 그대로 읽힘.)
//  결과 저장은 mou-m.com /api/sources/crawl-result (ext_bridge.crawlBundle 이 호출).

const MOUM_EXT_VERSION = "0.3.0";

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
  const tab = await chrome.tabs.create({ url: s.url, active: false });
  try {
    await waitTabComplete(tab.id, 25000);
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "ISOLATED", func: extractor,
    });
    return (out && out[0] && out[0].result) || { ok: false, error: "추출 결과 없음" };
  } finally {
    try { await chrome.tabs.remove(tab.id); } catch (_) {}
  }
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
  try {
    const ij = await fetch(base + "/options/v2/prioritized-inventories", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ optionValueNos: valueNos }),
    }).then((r) => r.json());
    (ij.data || []).forEach((x) => { invMap[x.productVariantId] = x; });
  } catch (e) { /* 재고 실패해도 가격은 진행 */ }

  let member = null;
  for (let i = 0; i < 12; i++) {
    const m = document.body.innerText.match(/([\d,]+)\s*원\s*나의\s*할인가/) ||
              document.body.innerText.match(/나의\s*할인가[^\d]*([\d,]+)/);
    if (m) { member = parseInt(m[1].replace(/,/g, ""), 10); break; }
    await sleep(500);
  }
  let sale = null;
  const sm = document.body.innerText.match(/(\d+)%\s*([\d,]+)\s*원/);
  if (sm) sale = parseInt(sm[2].replace(/,/g, ""), 10);
  const price = member || sale;

  const options = items.map((it) => {
    const code = it.managedCode || "";
    let color = "", size = "";
    if (code.includes("^")) { const p = code.split("^"); color = (p[0] || "").trim(); size = (p[1] || "").trim(); }
    else { size = code.trim(); }
    const inv = invMap[it.no] || {};
    const stock = inv.outOfStock ? 0 : (inv.remainQuantity == null ? 999 : Math.max(0, inv.remainQuantity));
    return { color, size: size.replace("mm", "").trim(), price, stock };
  });
  const anyStock = options.some((o) => o.stock > 0) || (member != null);

  return {
    ok: !!price,
    price: price,                       // product-level (회원가)
    stock: anyStock ? 999 : 0,          // 재고 있으면 sentinel
    product_name: document.title.split("-")[0].trim().slice(0, 120),
    member_price: member, sale_price: sale,
    is_logged_in: member != null,
    option_count: options.length, options,
    error: price ? null : "가격 추출 실패(로그인/렌더 확인)",
  };
}

// ════════════════════════════════════════════
//  롯데온 — www.lotteon.com/p/product/LO... (Vue SPA). 혜택가 = DOM '나의 혜택가'
// ════════════════════════════════════════════
async function lotteonExtractor() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let benefit = null, sale = null;
  for (let i = 0; i < 16; i++) {
    const t = document.body.innerText;
    const b = t.match(/([\d,]+)\s*원\s*나의\s*혜택가/) || t.match(/나의\s*혜택가[^\d]*([\d,]+)/);
    if (b) { benefit = parseInt(b[1].replace(/,/g, ""), 10); }
    const sm = t.match(/(\d+)%\s*([\d,]+)\s*원/);
    if (sm) sale = parseInt(sm[2].replace(/,/g, ""), 10);
    if (benefit) break;
    await sleep(500);
  }
  const price = benefit || sale;
  const soldOut = /품절|일시품절/.test(document.body.innerText) && !price;
  return {
    ok: !!price,
    price: price,
    stock: price && !soldOut ? 999 : 0,
    product_name: document.title.split(":")[0].trim().slice(0, 120),
    benefit_price: benefit, sale_price: sale,
    error: price ? null : "가격 추출 실패(렌더 확인)",
  };
}

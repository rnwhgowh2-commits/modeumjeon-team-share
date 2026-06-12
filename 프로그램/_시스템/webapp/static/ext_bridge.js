// ext_bridge.js — mou-m.com 페이지 쪽 확장 브리지.
//  확장(모음전 크롤러) 설치 감지 + 확장에 크롤 요청을 보내고 결과를 받는다.
//  확장의 content_mou.js 와 window.postMessage 규약으로 통신:
//    페이지 → { __moum:"page", type, payload, reqId }
//    확장   → { __moum:"ext",  reqId, ok, resp, error }
(function () {
  const _pending = {};
  let _seq = 0;

  window.addEventListener("message", (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d || d.__moum !== "ext" || !d.reqId) return;
    const cb = _pending[d.reqId];
    if (cb) {
      delete _pending[d.reqId];
      cb(d);
    }
  });

  function installed() {
    return !!document.documentElement.getAttribute("data-moum-ext");
  }
  function version() {
    return document.documentElement.getAttribute("data-moum-ext") || null;
  }

  function send(type, payload, timeoutMs) {
    timeoutMs = timeoutMs || 120000;
    return new Promise((resolve, reject) => {
      if (!installed()) return reject(new Error("확장 미설치 — 모음전 크롤러 설치 필요"));
      const reqId = "r" + ++_seq + "_" + Date.now();
      _pending[reqId] = (d) =>
        d.ok ? resolve(d.resp) : reject(new Error(d.error || "확장 오류"));
      window.postMessage({ __moum: "page", type, payload, reqId }, "*");
      setTimeout(() => {
        if (_pending[reqId]) {
          delete _pending[reqId];
          reject(new Error("확장 응답 시간초과"));
        }
      }, timeoutMs);
    });
  }

  // 모음전 1건을 확장으로 크롤 → 저장. 기본 대상 = 서버가 못 긁는 무신사·롯데온.
  async function crawlBundle(code, opts) {
    opts = opts || {};
    const sourceKeys = opts.sources || ["musinsa", "lotteon"];
    const r = await fetch("/api/bundles/" + encodeURIComponent(code) + "/option-matrix")
      .then((x) => x.json());
    const seen = new Set();
    const list = [];
    (r.options || []).forEach((o) =>
      (o.sources || []).forEach((s) => {
        if (!s.product_url || sourceKeys.indexOf(s.source_key) < 0) return;
        if (seen.has(s.product_url)) return;
        seen.add(s.product_url);
        list.push({ source_key: s.source_key, url: s.product_url });
      })
    );
    if (!list.length) return { ok: false, error: "대상 URL 없음" };
    const res = await send("crawl", { model_code: code, sources: list }, opts.timeoutMs || 300000);
    const results = (res && res.results) || [];
    const items = results.map((x) => ({
      url: x.url, price: x.price, stock: x.stock,
      status: x.ok ? "ok" : "error", product_name: x.product_name, error: x.error,
    }));
    const save = await fetch("/api/sources/crawl-result", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
    return { ok: true, crawled: results.length, ok_count: results.filter((x) => x.ok).length, save, results };
  }

  // ════════════════════════════════════════════════════════════════════
  //  crawlBundleAll — 6개 소싱처 전부 이 PC(확장)에서 로컬 창 크롤(A안).
  //   무신사·롯데온 = 기존 JS 추출기(send "crawl").
  //   르무통·SSF·SSG·스스르무통 = 창 HTML 수집(grabHtml) → POST /api/sources/parse.
  //   동시 창 수 = 적응형 처리량 언덕오르기 컨트롤러(설계 §4).
  //   주요 시점마다 'moum-crawl-log' CustomEvent 방출(대시보드 Phase 4 가 구독).
  // ════════════════════════════════════════════════════════════════════
  const PARSE_SOURCES = ["lemouton", "ssf", "ssg", "ss_lemouton"];
  const JS_SOURCES = ["musinsa", "lotteon"];

  function _emitLog(type, fields) {
    try {
      window.dispatchEvent(new CustomEvent("moum-crawl-log", {
        detail: Object.assign({ type: type, ts: Date.now(), source: null, level: "", msg: "", metrics: null }, fields || {}),
      }));
    } catch (_) { /* CustomEvent 미지원 등 — 로그는 베스트에포트 */ }
  }

  function _median(arr) {
    if (!arr.length) return 0;
    const s = arr.slice().sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  // 시스템 신호 폴(보조). 권한·실패 시 {cpu:null,mem:null}.
  async function _sysinfo() {
    try {
      const r = await send("sysinfo", {}, 8000);
      return { cpu: r && typeof r.cpu === "number" ? r.cpu : null,
               mem: r && typeof r.mem === "number" ? r.mem : null };
    } catch (_) { return { cpu: null, mem: null }; }
  }

  // 1건 처리(창 재사용) — 이미 열린 tabId 에서 url 로 이동하며 크롤.
  //  무신사·롯데온 = navExtract(창 안 JS 추출기). 비로그인 4개 = navGrab(렌더 HTML) → 서버 parse.
  async function _crawlItemInTab(tabId, code, item) {
    const sk = item.source_key, url = item.url;
    if (JS_SOURCES.indexOf(sk) >= 0) {
      const x = await send("navExtract", { tabId: tabId, url: url, source_key: sk }, 120000) || {};
      return {
        url: url, source_key: sk, price: x.price, stock: x.stock,
        status: x.ok ? "ok" : "error", product_name: x.product_name, error: x.error || null,
      };
    }
    // 비로그인 4개: 창에서 렌더 HTML 수집 → 서버 parse
    const grab = await send("navGrab", { tabId: tabId, url: url }, 90000);
    if (!grab || !grab.ok || !grab.html) {
      return { url: url, source_key: sk, status: "error", error: (grab && grab.error) || "HTML 수집 실패" };
    }
    let p;
    try {
      p = await fetch("/api/sources/parse", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_key: sk, url: url, html: grab.html }),
      }).then((x) => x.json());
    } catch (e) {
      return { url: url, source_key: sk, status: "error", error: "parse 호출 실패: " + e };
    }
    if (!p || !p.ok) {
      return { url: url, source_key: sk, status: "error", error: (p && (p.message || p.error)) || "parse 실패" };
    }
    // 서버 parse_html → CrawlResult(asdict): {source, product_url, product_name_raw, options:[{price,stock,...}], ...}
    //  crawl-result 엔드포인트는 상품단위 {price,stock} 를 받아 모든 옵션에 일괄 반영하므로,
    //  옵션들에서 대표값을 도출: price = 재고있는 옵션 중 최저가(없으면 전체 최저가), stock = 옵션 재고 합.
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
      url: url, source_key: sk,
      price: price,
      stock: stock,
      status: ok ? "ok" : "error",
      product_name: p.product_name_raw || null,
      error: ok ? null : "옵션 가격 없음",
    };
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  async function crawlBundleAll(code, opts) {
    opts = opts || {};
    _emitLog("start", { level: "", msg: "전체 로컬 크롤 시작: " + code });

    // 1) 소싱처별 URL 목록 수집(중복 제거). 6개 전부 대상.
    const r = await fetch("/api/bundles/" + encodeURIComponent(code) + "/option-matrix").then((x) => x.json());
    const ALL = JS_SOURCES.concat(PARSE_SOURCES);
    const seen = new Set();
    const bySource = {}; // source_key -> [{source_key,url}]  (같은 소싱처는 순차)
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
    if (!total) { _emitLog("finish", { level: "warn", msg: "대상 URL 없음" }); return { ok: false, error: "대상 URL 없음" }; }

    // 2) 컨트롤러 상태 — "같은 소싱처는 순차, 다른 소싱처는 동시".
    //    각 소싱처를 독립 큐로 두고, 활성 소싱처 수 = concurrency 만큼만 동시에 진행.
    let cap = clamp((navigator.hardwareConcurrency || 4) - 1, 1, 5);
    if (navigator.deviceMemory && navigator.deviceMemory < 4) cap = Math.min(cap, 2);
    if (opts.maxConcurrency) cap = Math.min(cap, opts.maxConcurrency); // 사용자 상한 우선
    let concurrency = 1;
    _emitLog("concurrency", { level: "", msg: "초기 동시 창 " + concurrency + "/" + cap, metrics: { concurrency, cap, active: 0, total, done: 0 } });

    const pendingSources = sourceKeys.slice();  // 아직 시작 안 한 소싱처
    const results = [];
    const latencies = [];        // 최근 1건 소요(sec)
    let done = 0;
    let lastSys = { cpu: null, mem: null };
    let cooldown = 0;            // concurrency 변경 후 재판정 보류 카운터
    let prevThroughput = 0;      // 직전 채택 처리량
    let active = 0;              // 현재 진행 중 소싱처(창) 수
    let stopped = false;

    // 한 소싱처의 URL들을 순차로 모두 처리(같은 소싱처 병렬 금지 — 차단 방지).
    //  소싱처별로 보이는 창 1개를 열고(openWin), 그 창에서 URL을 차례로 이동하며 크롤,
    //  끝나면 창을 닫는다(closeWin). finally 로 창 닫힘 보장(에러나도 창 안 남게).
    async function runSource(sk) {
      const list = bySource[sk];
      let winId = null, tabId = null;
      try {
        const w = await send("openWin", {}, 30000);
        if (!w || !w.ok || w.tabId == null) {
          // 창을 못 열면 이 소싱처 전체를 에러로 기록(다른 소싱처는 계속)
          for (let j = 0; j < list.length; j++) {
            results.push({ url: list[j].url, source_key: sk, status: "error", error: (w && w.error) || "창 생성 실패" });
            done++;
          }
          _emitLog("source-done", { source: sk, level: "warn", msg: sk + " 창 생성 실패 — " + list.length + "건 건너뜀", metrics: { concurrency, cap, active, done, total } });
          return;
        }
        winId = w.winId; tabId = w.tabId;
        _emitLog("window-open", { source: sk, level: "", msg: sk + " 창 시작", metrics: { concurrency, cap, active, done, total } });

        for (let i = 0; i < list.length; i++) {
          if (stopped) break;
          const t0 = Date.now();
          let out;
          try { out = await _crawlItemInTab(tabId, code, list[i]); }
          catch (e) { out = { url: list[i].url, source_key: sk, status: "error", error: String(e && e.message ? e.message : e) }; }
          const sec = (Date.now() - t0) / 1000;
          latencies.push(sec);
          if (latencies.length > 12) latencies.shift();
          results.push(out);
          done++;
          if (cooldown > 0) cooldown--;
          // [2026-06-12] 실시간 줄 = '표면노출가'(크롤 raw)만. lineId 를 붙여 저장 후
          //   같은 줄에 '→ 매입 N원'(최종매입가)을 덧붙여 갱신(아래 5)단계). V2 화살표 표기.
          _emitLog("item-done", {
            source: sk, level: out.status === "ok" ? "" : "warn",
            url: (out && out.url) || (list[i] && list[i].url) || null,
            lineId: out.status === "ok" ? (sk + "|" + ((out && out.url) || (list[i] && list[i].url) || "")) : null,
            msg: out.status === "ok"
              ? (sk + " 표면 " + (out.price != null ? out.price.toLocaleString() + "원" : "가격없음") + " (" + sec.toFixed(1) + "s)")
              : (sk + " 실패: " + (out.error || "")),
            metrics: { concurrency, cap, active, done, total, avgSec: +_median(latencies).toFixed(2), cpu: lastSys.cpu, mem: lastSys.mem },
          });
          // 주기적 시스템 폴(2~3건마다) — 보조 신호
          if (done % 3 === 0) {
            lastSys = await _sysinfo();
            if (lastSys.cpu != null || lastSys.mem != null) {
              // Windows 는 캐시로 메모리 사용률이 평상시 85~95% 라 메모리 임계는 높게(96/98), CPU 는 유지.
              const hot = (lastSys.cpu != null && lastSys.cpu >= 90) || (lastSys.mem != null && lastSys.mem >= 96);
              if (hot) _emitLog("resource", { level: "warn", msg: "자원 높음 — CPU " + lastSys.cpu + "% / MEM " + lastSys.mem + "%", metrics: { concurrency, cap, active, cpu: lastSys.cpu, mem: lastSys.mem } });
            }
          }
        }
      } finally {
        // ⚠️ 에러·정지 어떤 경우에도 창을 반드시 닫는다(창 누수 방지).
        if (winId != null) { try { await send("closeWin", { winId: winId }, 15000); } catch (_) {} }
      }
      _emitLog("source-done", { source: sk, level: "done", msg: sk + " 완료 (" + list.length + "건)", metrics: { concurrency, cap, active, done, total } });
    }

    // 처리량 언덕오르기 — 활성 소싱처 수(=동시 창)를 concurrency 에 맞춰 채운다.
    //   유효 처리량 = concurrency / (최근 latency 중앙값).  변경 후 최소 3건 쿨다운.
    function evaluateConcurrency() {
      if (cooldown > 0) return;                       // 변경 직후엔 보류
      if (latencies.length < 3) return;               // 표본 부족
      const med = _median(latencies) || 0.001;
      const throughput = concurrency / med;           // 분당 환산 불필요(상대비교)
      // 자원 안전 브레이크(보조)
      const cpu = lastSys.cpu, mem = lastSys.mem;
      if ((cpu != null && cpu >= 95) || (mem != null && mem >= 98)) {
        if (concurrency > 1) {
          concurrency--; cooldown = 3; prevThroughput = throughput;
          _emitLog("concurrency", { level: "down", msg: "자원 한계(CPU≥95·MEM≥98) 강제 −1 → " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } });
        }
        return;
      }
      const blockUp = (cpu != null && cpu >= 90) || (mem != null && mem >= 96);
      if (throughput > prevThroughput * 1.05) {
        // 개선 → 채택, 가능하면 +1 탐침
        prevThroughput = throughput;
        if (concurrency < cap && !blockUp) {
          concurrency++; cooldown = 3;
          _emitLog("concurrency", { level: "up", msg: "처리량 개선 → 창 +1 = " + concurrency + (blockUp ? "" : ""), metrics: { concurrency, cap, active, cpu, mem, done, total } });
        } else if (blockUp && concurrency < cap) {
          _emitLog("resource", { level: "warn", msg: "처리량 여력 있으나 자원 높음(CPU≥90·MEM≥96) → +1 보류", metrics: { concurrency, cap, active, cpu, mem, done, total } });
        }
      } else if (throughput < prevThroughput * 0.9 && concurrency > 1) {
        // 처리량 하락/정체 → 직전으로 되돌림(−1)
        concurrency--; cooldown = 3; prevThroughput = throughput;
        _emitLog("concurrency", { level: "down", msg: "처리량 하락 → 창 −1 = " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } });
      } else {
        prevThroughput = Math.max(prevThroughput, throughput);
      }
    }

    // 스케줄러 루프: active < concurrency 면 대기 소싱처를 하나 더 띄운다.
    //   타이머는 단 1개만 유지(중복 setTimeout 누적 방지). pump 는 (1)소싱처 완료 시,
    //   (2)단일 폴 타이머에서만 호출된다.
    await new Promise((resolveAll) => {
      let done2 = false;
      let pollTimer = null;
      function finish() { if (done2) return; done2 = true; if (pollTimer) clearTimeout(pollTimer); resolveAll(); }
      function schedulePoll() {
        if (pollTimer) clearTimeout(pollTimer);
        pollTimer = setTimeout(() => { pollTimer = null; pump(); }, 1200);
      }
      function pump() {
        if (done2) return;
        if (stopped) { if (active === 0) finish(); return; }
        evaluateConcurrency();
        while (active < concurrency && pendingSources.length > 0) {
          const sk = pendingSources.shift();
          active++;
          runSource(sk).catch((_) => {}).then(() => {
            active--;
            pump();   // 한 소싱처 끝나면 다음 채움
          });
        }
        if (active === 0 && pendingSources.length === 0) { finish(); return; }
        // 진행 중이면 단일 폴 타이머로 다음 평가(처리량/자원 변화 반영)
        schedulePoll();
      }
      pump();
    });

    // 3) 결과 저장(기존 엔드포인트 형식 그대로)
    const items = results.map((x) => ({
      url: x.url, price: x.price, stock: x.stock,
      status: x.status, product_name: x.product_name, error: x.error,
    }));
    const save = await fetch("/api/sources/crawl-result", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));

    // 4) '마지막 크롤 ㅇㅇ전' 표시 갱신 — 확장 크롤은 서버 run-now 를 안 거치므로
    //    Model.last_crawled_at 을 여기서 직접 bump(touch-crawled). 실패해도 저장엔 무관.
    try {
      await fetch("/api/bundles/" + encodeURIComponent(code) + "/touch-crawled", { method: "POST" });
    } catch (_) {}

    // 5) [2026-06-12] 줄(URL)마다 최종매입가 갱신 — fx 계산식과 100% 동일 출처(V2 표기).
    //   실시간 줄은 '표면노출가'(크롤 raw)만 찍는다. 저장이 끝난 뒤(=무신사 등 동적 혜택까지
    //   갱신된 상태) 매트릭스를 다시 읽어, 크롤한 URL마다 대표(재고있는 최저가) 옵션을 fx 패널과
    //   같은 /api/source-benefits/breakdowns 로 계산해, 같은 줄(lineId=source_key|url)에
    //   '표면 N원 → 매입 N원' 으로 제자리 갱신한다. 동일 엔드포인트·동일 sale_price 이므로
    //   fx 누를 때 값과 소수점까지 일치한다. (out-of-stock URL은 매입 갱신 없이 표면만 유지)
    try {
      const rr = await fetch("/api/bundles/" + encodeURIComponent(code) + "/option-matrix").then((x) => x.json());
      const repByLine = {}; // "source_key|product_url" -> {sku, source_id, source_key, url, sale_price, lineId}
      (rr.options || []).forEach((o) => (o.sources || []).forEach((s) => {
        const p = s.crawled_price;
        if (!(p > 0) || !s.product_url) return;
        const inStock = (s.crawled_stock == null) || (s.crawled_stock > 0);
        if (!inStock) return;
        const lid = s.source_key + "|" + s.product_url;
        const cur = repByLine[lid];
        if (!cur || p < cur.sale_price) {
          repByLine[lid] = { sku: o.sku, source_id: s.source_id, source_key: s.source_key, url: s.product_url, sale_price: p, lineId: lid };
        }
      }));
      const reps = Object.values(repByLine);
      if (reps.length) {
        const bd = await fetch("/api/source-benefits/breakdowns", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: reps.map((r) => ({ sku: r.sku, source_id: r.source_id, sale_price: r.sale_price })) }),
        }).then((x) => x.json()).catch(() => null);
        const bdres = (bd && bd.results) || {};
        reps.forEach((r) => {
          const b = bdres[r.sku + "|" + r.source_id];
          if (!b || b.error || b.final_price == null) return;
          const surf = Math.round(b.sale_price != null ? b.sale_price : r.sale_price);
          const buy = Math.round(b.final_price);
          // item-final: 같은 줄(lineId)을 '표면 → 매입' V2 형태로 제자리 갱신.
          //   대시보드가 lineId 줄을 못 찾으면(스크롤 정리 등) 새 줄로 append(fallback).
          _emitLog("item-final", {
            source: r.source_key, level: "done", lineId: r.lineId, url: r.url,
            surf: surf, buy: buy,
            msg: r.source_key + " 표면 " + surf.toLocaleString() + "원 → 매입 " + buy.toLocaleString() + "원",
          });
        });
      }
    } catch (_) { /* 갱신 실패는 크롤 저장 결과와 무관 — 무시 */ }

    const okCount = results.filter((x) => x.status === "ok").length;
    _emitLog("finish", {
      level: "done",
      msg: "완료 — " + okCount + "/" + results.length + " 성공 · 저장 " + ((save && save.updated) || 0) + "건",
      metrics: { concurrency, cap, active, done, total, cpu: lastSys.cpu, mem: lastSys.mem },
    });
    return { ok: true, crawled: results.length, ok_count: okCount, save };
  }

  // ── 이 PC 스케줄 크롤 ──
  //  '스케줄 크롤은 현재 컴퓨터로': localStorage['moum_sched_pc']==='1' 이고 확장 설치 시,
  //  mou-m.com 탭이 열려 있는 동안 주기적으로 전체 모음전의 무신사·롯데온을 확장으로 크롤.
  let _schedTimer = null;
  async function _schedTick() {
    if (!installed()) return;
    try {
      const r = await fetch("/api/bundles/codes").then((x) => x.json());
      const codes = (r && r.codes) || [];
      for (let i = 0; i < codes.length; i++) {
        try { await crawlBundle(codes[i]); } catch (_) {}
        await new Promise((res) => setTimeout(res, 4000)); // 사이트 부하 보호
      }
    } catch (_) {}
  }
  function startSchedule(intervalMin) {
    intervalMin = intervalMin || 30;
    stopSchedule();
    try { localStorage.setItem("moum_sched_pc", "1"); } catch (_) {}
    _schedTimer = setInterval(_schedTick, intervalMin * 60 * 1000);
    return { ok: true, intervalMin: intervalMin };
  }
  function stopSchedule() {
    if (_schedTimer) { clearInterval(_schedTimer); _schedTimer = null; }
    try { localStorage.setItem("moum_sched_pc", "0"); } catch (_) {}
    return { ok: true };
  }
  function scheduleStatus() {
    let flag = false;
    try { flag = localStorage.getItem("moum_sched_pc") === "1"; } catch (_) {}
    return { this_pc_scheduled: flag, running: !!_schedTimer };
  }
  // 자동 시작 — 이 PC가 스케줄 담당으로 지정돼 있으면 페이지 로드 시 켬
  try {
    if (localStorage.getItem("moum_sched_pc") === "1") {
      _schedTimer = setInterval(_schedTick, 30 * 60 * 1000);
    }
  } catch (_) {}

  window.MoumExt = {
    installed,
    version,
    ping: () => send("ping", {}, 8000),
    crawl: (payload, timeoutMs) => send("crawl", payload, timeoutMs),
    grabHtml: (url, timeoutMs) => send("grabHtml", { url }, timeoutMs || 60000),
    // 창 재사용 래퍼(v0.4.1) — 소싱처별 창 1개로 순차 크롤
    openWin: (timeoutMs) => send("openWin", {}, timeoutMs || 30000),
    navGrab: (tabId, url, timeoutMs) => send("navGrab", { tabId, url }, timeoutMs || 90000),
    navExtract: (tabId, url, source_key, timeoutMs) => send("navExtract", { tabId, url, source_key }, timeoutMs || 120000),
    closeWin: (winId, timeoutMs) => send("closeWin", { winId }, timeoutMs || 15000),
    sysinfo: () => send("sysinfo", {}, 8000),
    crawlBundle,
    crawlBundleAll,
    startSchedule,
    stopSchedule,
    scheduleStatus,
  };
})();

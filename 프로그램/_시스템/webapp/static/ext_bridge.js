// ext_bridge.js — mou-m.com 페이지 쪽 확장 브리지.
//  확장(모음전 크롤러) 설치 감지 + 확장에 크롤 요청을 보내고 결과를 받는다.
//  확장의 content_mou.js 와 window.postMessage 규약으로 통신:
//    페이지 → { __moum:"page", type, payload, reqId }
//    확장   → { __moum:"ext",  reqId, ok, resp, error }
//
//  [2026-06-14] 멀티 모음전 큐 + 일시중지/중지/재개(1단계):
//   - enqueueCrawl(code) 로 여러 모음전을 줄세워 순차 크롤(같은 시점 모음전 1개만 실행).
//   - pauseCrawl/resumeCrawl/stopCrawl — 일시중지·중지 둘 다 열린 크롤 창을 닫는다.
//     · 일시중지 = 진행 위치(소싱처별 인덱스) 기억 → 재개 시 이어서. 저장은 모음전 완료 시 1회.
//     · 중지     = 큐 비우고 현재 모음전 중단 → 긁은 것만 저장 + finalize(미크롤=판매차단 유지).
//   - 'moum-crawl-log' 이벤트에 bundle(모음전 코드) 태그 추가 → 대시보드가 모음전별로 분리 표시.
//   - 'queue' 이벤트로 진행중+대기중 모음전 목록 방출(마스터–디테일 레일).
(function () {
  const _pending = {};
  let _seq = 0;

  // [2026-06-14] 2단계: 백그라운드 크롤 엔진이 보낸 진행 로그(content_mou 가 중계)를
  //   'moum-crawl-log' CustomEvent 로 변환해 대시보드(crawl_log.js)가 그리게 한다.
  //   동시에 최신 queue 를 캐시(getCrawlState 동기 응답용).
  const _bgCache = { running: null, paused: false, queue: [] };
  window.addEventListener("message", (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d) return;
    if (d.__moum === "ext" && d.reqId) {
      const cb = _pending[d.reqId];
      if (cb) { delete _pending[d.reqId]; cb(d); }
      return;
    }
    if (d.__moum === "log" && d.detail) {
      const det = d.detail;
      if (det.type === "queue") {
        _bgCache.running = det.running || null;
        _bgCache.paused = !!det.paused;
        _bgCache.queue = (det.queue || []).filter((q) => q.status === "wait").map((q) => q.code);
      }
      try { window.dispatchEvent(new CustomEvent("moum-crawl-log", { detail: det })); } catch (_) {}
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
    const ENC = encodeURIComponent(code);
    // [2026-06-13] 크롤 시작 하드 리셋 — 옛 가격/재고/혜택 비우고 옵션 pessimistic block.
    //   크롤/마무리가 실패하면 차단 유지(fail-safe) → 옛값으로 잘못 판매되는 사고 방지.
    try { await fetch("/api/bundles/" + ENC + "/crawl-reset", { method: "POST" }); } catch (_) {}
    // 크롤 종료 후 — 유효 소싱가 없는 옵션 crawl_blocked 확정(성공=해제).
    const _finalize = () => fetch("/api/bundles/" + ENC + "/crawl-finalize",
      { method: "POST" }).then((x) => x.json()).catch(() => null);
    const r = await fetch("/api/bundles/" + ENC + "/option-matrix")
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
    if (!list.length) { const finalize = await _finalize(); return { ok: false, error: "대상 URL 없음", finalize }; }
    const res = await send("crawl", { model_code: code, sources: list }, opts.timeoutMs || 300000);
    const results = (res && res.results) || [];
    const items = results.map((x) => ({
      url: x.url, price: x.price, stock: x.stock,
      options: x.options,   // ★ 사이즈별 재고[{color,size,stock}] — 서버가 SourceOption.current_stock 에 반영
      status: x.ok ? "ok" : "error", product_name: x.product_name, error: x.error,
      is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
      benefits_ok: (x.benefits_ok === undefined ? false : !!x.benefits_ok),
      benefit_lines: x.benefit_lines || [],
      benefit_amounts: x.benefit_amounts || {},
    }));
    const save = await fetch("/api/sources/crawl-result", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
    const finalize = await _finalize();
    return { ok: true, crawled: results.length, ok_count: results.filter((x) => x.ok).length, save, finalize, results };
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
        detail: Object.assign({ type: type, ts: Date.now(), source: null, bundle: null, level: "", msg: "", metrics: null }, fields || {}),
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
        options: x.options,   // ★ 사이즈별 재고 보존(전체크롤 경로) — 없으면 상품레벨 999 둔갑
        status: x.ok ? "ok" : "error", product_name: x.product_name, error: x.error || null,
        is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
      };
    }
    // 비로그인 4개: 창에서 렌더 HTML 수집 → 서버 parse
    const grab = await send("navGrab", { tabId: tabId, url: url }, 90000);
    if (!grab || !grab.ok || !grab.html) {
      return { url: url, source_key: sk, status: "error", error: (grab && grab.error) || "HTML 수집 실패" };
    }
    // 스스 per-SKU 수집 진단(콘솔) — "ok:N" 성공 / "err:..." 실패 사유(둔갑 방지 null 유지).
    if (grab.sku_diag) console.log("[moum] sku_stock", sk, url, grab.sku_diag);
    let p;
    try {
      p = await fetch("/api/sources/parse", {
        method: "POST", headers: { "Content-Type": "application/json" },
        // sku_stock: 스스 per-SKU 재고 맵("색상||사이즈"→수량). 확장(로그인 브라우저)이
        //   n/v2 API 로 수집해 동봉 → 서버 파서가 옵션별 stock 을 이 값으로 교정.
        body: JSON.stringify({ source_key: sk, url: url, html: grab.html, sku_stock: grab.sku_stock || null }),
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
      // ★ 사이즈별 재고 보존 — 서버가 SourceOption.current_stock 에 옵션별 반영.
      //   기존엔 상품레벨 합계(stock)만 보내 모든 사이즈가 '재고있음' 둔갑(르무통 24935 등).
      options: opts2.map((o) => ({ color: o.color_text, size: o.size_text, stock: o.stock })),
      status: ok ? "ok" : "error",
      product_name: p.product_name_raw || null,
      error: ok ? null : "옵션 가격 없음",
    };
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  // ────────────────────────────────────────────────────────────────────
  //  멀티 모음전 큐 매니저 — 한 시점에 모음전 1개만 크롤, 나머지는 대기.
  //   pauseCrawl/resumeCrawl/stopCrawl 이 읽는 플래그(_mgr.paused/_mgr.stopped)를
  //   crawlBundleAll 의 루프가 매 아이템마다 확인한다. _mgr._kick = 현재 모음전의 pump.
  // ────────────────────────────────────────────────────────────────────
  const _mgr = { queue: [], running: null, paused: false, stopped: false, _kick: null };

  // [2026-06-14] 2단계 게이트 — 확장 0.5.0+ 면 크롤 엔진이 백그라운드(서비스워커)에 있어
  //   탭을 닫아도 지속된다. 그 경우 제어를 백그라운드로 위임. 구버전(<0.5.0)이면 페이지 엔진(1단계).
  function _bgEngine() {
    const v = version();   // content_mou 가 심은 data-moum-ext = 확장 버전
    if (!v) return false;
    const a = String(v).split(".").map((n) => parseInt(n, 10) || 0);
    return a[0] > 0 || a[1] >= 5;   // >= 0.5.0
  }
  // 백그라운드로 제어 메시지(베스트에포트, 응답 무시 가능)
  function _bgSend(type, payload) {
    try { return send(type, payload || {}, 15000); } catch (e) { return Promise.reject(e); }
  }

  function _emitQueue() {
    const q = [];
    if (_mgr.running) q.push({ code: _mgr.running, status: _mgr.paused ? "pause" : "run" });
    _mgr.queue.forEach((c) => q.push({ code: c, status: "wait" }));
    _emitLog("queue", { queue: q, running: _mgr.running, paused: _mgr.paused });
  }

  // 모음전을 큐에 추가(중복 무시) → 진행 중이 없으면 러너 시작.
  //  [2단계] 확장 0.5.0+ 면 백그라운드 엔진으로 위임(탭 닫아도 지속). 아니면 페이지 엔진.
  function enqueueCrawl(code, opts) {
    if (!code) return { ok: false, error: "code 없음" };
    if (_bgEngine()) {
      _bgSend("crawl.enqueue", { codes: [code], base: location.origin }).catch(() => {});
      return { ok: true, queued: true, bg: true };
    }
    if (code === _mgr.running) return { ok: true, already: true };
    if (_mgr.queue.indexOf(code) >= 0) return { ok: true, already: true };
    _mgr.queue.push(code);
    _emitQueue();
    if (!_mgr.running) _runQueue(opts);
    return { ok: true, queued: true, position: _mgr.queue.length };
  }

  // 큐 러너 — 모음전을 하나씩 꺼내 순차 크롤. 중지 시 큐 비움.
  async function _runQueue(opts) {
    while (_mgr.queue.length) {
      if (_mgr.stopped) break;
      const code = _mgr.queue.shift();
      _mgr.running = code;
      _mgr.paused = false;
      _emitQueue();
      try { await crawlBundleAll(code, opts); } catch (_) {}
      if (_mgr.stopped) break;
    }
    _mgr.queue = [];
    _mgr.running = null;
    _mgr.paused = false;
    _mgr.stopped = false;
    _mgr._kick = null;
    _emitQueue();
    // 모든 모음전 종료 — 현재 매트릭스 페이지면 자동 갱신
    try { if (typeof window.loadMatrix === "function") window.loadMatrix(); } catch (_) {}
  }

  function pauseCrawl() {
    if (_bgEngine()) { _bgSend("crawl.pause").catch(() => {}); return { ok: true, bg: true }; }
    if (!_mgr.running) return { ok: false, error: "진행 중 아님" };
    if (_mgr.paused) return { ok: true, already: true };
    _mgr.paused = true;
    _emitLog("bundle-paused", { bundle: _mgr.running, level: "warn", msg: "일시중지 — 창 닫는 중 (재개하면 이어서 크롤)" });
    _emitQueue();
    return { ok: true };
  }
  function resumeCrawl() {
    if (_bgEngine()) { _bgSend("crawl.resume").catch(() => {}); return { ok: true, bg: true }; }
    if (!_mgr.running) return { ok: false, error: "진행 중 아님" };
    if (!_mgr.paused) return { ok: true, already: true };
    _mgr.paused = false;
    _emitLog("bundle-resumed", { bundle: _mgr.running, level: "", msg: "재개 — 이어서 크롤" });
    _emitQueue();
    if (_mgr._kick) { try { _mgr._kick(); } catch (_) {} }
    return { ok: true };
  }
  function stopCrawl() {
    if (_bgEngine()) { _bgSend("crawl.stop").catch(() => {}); return { ok: true, bg: true }; }
    if (!_mgr.running && !_mgr.queue.length) return { ok: false, error: "진행 중 아님" };
    _mgr.stopped = true;
    _mgr.paused = false;
    _mgr.queue = [];
    _emitLog("bundle-stopping", { bundle: _mgr.running, level: "warn", msg: "중지 — 창 닫고 종료 (긁은 것까지 저장)" });
    if (_mgr._kick) { try { _mgr._kick(); } catch (_) {} }
    _emitQueue();
    return { ok: true };
  }
  function cancelQueued(code) {
    if (_bgEngine()) { _bgSend("crawl.cancel", { code: code }).catch(() => {}); return { ok: true, bg: true }; }
    const i = _mgr.queue.indexOf(code);
    if (i >= 0) { _mgr.queue.splice(i, 1); _emitQueue(); return { ok: true }; }
    return { ok: false, error: "대기열에 없음" };
  }
  function getCrawlState() {
    if (_bgEngine()) {
      return { running: _bgCache.running, paused: _bgCache.paused, stopped: false, queue: _bgCache.queue.slice(), bg: true };
    }
    return { running: _mgr.running, paused: _mgr.paused, stopped: _mgr.stopped, queue: _mgr.queue.slice() };
  }

  // [2단계] 페이지 (재)진입 시 백그라운드에 진행 상태를 물어 위젯을 재연결.
  //   진행 중인 크롤이 있으면 'snapshot' 이벤트로 대시보드를 복원한다(탭 닫았다 다시 와도 보임).
  function reattachFromBackground() {
    if (!_bgEngine()) return;
    _bgSend("crawl.getState").then((resp) => {
      const st = resp && resp.resp ? resp.resp : resp;   // send() 는 resp 를 그대로 resolve
      if (!st || !st.ok) return;
      _bgCache.running = st.running || null;
      _bgCache.paused = !!st.paused;
      _bgCache.queue = (st.queue || []).slice();
      const hasWork = st.running || (st.queue && st.queue.length) ||
        (st.view && Object.keys(st.view).some((k) => { const b = st.view[k]; return b && (b.status === "run" || b.status === "pause"); }));
      if (hasWork) {
        try { window.dispatchEvent(new CustomEvent("moum-crawl-log", { detail: { type: "snapshot", snapshot: st, ts: Date.now() } })); } catch (_) {}
      }
    }).catch(() => {});
  }

  async function crawlBundleAll(code, opts) {
    opts = opts || {};
    // 직접 호출(레거시) 안전 — 큐 러너가 안 거쳐도 일시중지/중지가 이 모음전에 걸리게.
    _mgr.running = code;
    _mgr.paused = false;
    // bundle(모음전 코드)을 모든 로그 이벤트에 태깅 → 대시보드 마스터–디테일 분리용.
    const emit = (type, fields) => _emitLog(type, Object.assign({ bundle: code }, fields || {}));
    emit("start", { level: "", msg: "전체 로컬 크롤 시작: " + code });
    const _ENC = encodeURIComponent(code);
    // [2026-06-13] 크롤 시작 하드 리셋 — 옛 가격/재고/혜택 비우고 옵션 pessimistic block.
    //   크롤/마무리 실패 시 차단 유지(fail-safe) → 옛값으로 잘못 판매되는 사고 방지.
    try { await fetch("/api/bundles/" + _ENC + "/crawl-reset", { method: "POST" }); } catch (_) {}
    const _finalize = () => fetch("/api/bundles/" + _ENC + "/crawl-finalize",
      { method: "POST" }).then((x) => x.json()).catch(() => null);

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
    if (!total) { await _finalize(); emit("finish", { level: "warn", msg: "대상 URL 없음" }); return { ok: false, error: "대상 URL 없음" }; }

    // 2) 컨트롤러 상태 — "같은 소싱처는 순차, 다른 소싱처는 동시".
    //    각 소싱처를 독립 큐로 두고, 활성 소싱처 수 = concurrency 만큼만 동시에 진행.
    let cap = clamp((navigator.hardwareConcurrency || 4) - 1, 1, 5);
    if (navigator.deviceMemory && navigator.deviceMemory < 4) cap = Math.min(cap, 2);
    if (opts.maxConcurrency) cap = Math.min(cap, opts.maxConcurrency); // 사용자 상한 우선
    let concurrency = 1;
    emit("concurrency", { level: "", msg: "초기 동시 창 " + concurrency + "/" + cap, metrics: { concurrency, cap, active: 0, total, done: 0 } });

    const pendingSources = sourceKeys.slice();  // 아직 시작/완료 안 한 소싱처
    const sourceProgress = {};   // sk -> 다음 처리할 인덱스(일시중지 재개용). 완료 시 삭제.
    const results = [];
    const latencies = [];        // 최근 1건 소요(sec)
    let done = 0;
    let lastSys = { cpu: null, mem: null };
    let cooldown = 0;            // concurrency 변경 후 재판정 보류 카운터
    let prevThroughput = 0;      // 직전 채택 처리량
    let active = 0;              // 현재 진행 중 소싱처(창) 수

    // 한 소싱처의 URL들을 순차로 모두 처리(같은 소싱처 병렬 금지 — 차단 방지).
    //  소싱처별로 보이는 창 1개를 열고(openWin), 그 창에서 URL을 차례로 이동하며 크롤,
    //  끝나면 창을 닫는다(closeWin). finally 로 창 닫힘 보장(에러나도·중지·일시중지도 창 안 남게).
    //  [2026-06-14] 중지(_mgr.stopped)/일시중지(_mgr.paused) 시 루프 중단 → finally 가 창 닫음.
    //   일시중지면 sourceProgress[sk]=다음인덱스 저장 + pendingSources 재투입 → 재개 시 이어서.
    async function runSource(sk) {
      const list = bySource[sk];
      const startIdx = sourceProgress[sk] || 0;
      let winId = null, tabId = null;
      let pausedMid = false;
      let _okN = 0;   // [2026-06-18] 이 소싱처 성공 건수(정직성 게이트용)
      try {
        const w = await send("openWin", {}, 30000);
        if (!w || !w.ok || w.tabId == null) {
          // 창을 못 열면 이 소싱처 남은 건을 에러로 기록(다른 소싱처는 계속)
          for (let j = startIdx; j < list.length; j++) {
            results.push({ url: list[j].url, source_key: sk, status: "error", error: (w && w.error) || "창 생성 실패" });
            done++;
          }
          delete sourceProgress[sk];
          emit("source-done", { source: sk, level: "warn", msg: sk + " 창 생성 실패 — " + (list.length - startIdx) + "건 건너뜀", metrics: { concurrency, cap, active, done, total } });
          return;
        }
        winId = w.winId; tabId = w.tabId;
        emit("window-open", { source: sk, level: "", msg: sk + " 창 시작", metrics: { concurrency, cap, active, done, total } });

        for (let i = startIdx; i < list.length; i++) {
          if (_mgr.stopped) break;                                   // 중지 — 즉시 중단
          if (_mgr.paused) { sourceProgress[sk] = i; pausedMid = true; break; }  // 일시중지 — 위치 저장
          const t0 = Date.now();
          let out;
          try { out = await _crawlItemInTab(tabId, code, list[i]); }
          catch (e) { out = { url: list[i].url, source_key: sk, status: "error", error: String(e && e.message ? e.message : e) }; }
          const sec = (Date.now() - t0) / 1000;
          latencies.push(sec);
          if (latencies.length > 12) latencies.shift();
          results.push(out);
          done++;
          if (out && out.status === "ok") _okN++;
          sourceProgress[sk] = i + 1;
          if (cooldown > 0) cooldown--;
          // [2026-06-12] 실시간 줄 = '표면노출가'(크롤 raw)만. lineId 를 붙여 저장 후
          //   같은 줄에 '→ 매입 N원'(최종매입가)을 덧붙여 갱신(아래 5)단계). V2 화살표 표기.
          emit("item-done", {
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
              if (hot) emit("resource", { level: "warn", msg: "자원 높음 — CPU " + lastSys.cpu + "% / MEM " + lastSys.mem + "%", metrics: { concurrency, cap, active, cpu: lastSys.cpu, mem: lastSys.mem } });
            }
          }
        }
      } finally {
        // ⚠️ 에러·정지·일시중지 어떤 경우에도 창을 반드시 닫는다(창 누수 방지).
        if (winId != null) { try { await send("closeWin", { winId: winId }, 15000); } catch (_) {} }
      }
      if (pausedMid) { pendingSources.unshift(sk); return; }   // 재개 시 이어서(같은 sk 재투입)
      if (_mgr.stopped) return;                                // 중지 — source-done 생략
      delete sourceProgress[sk];
      // [2026-06-18] 정직성 게이트 — 성공 0건 '완료' 위장 제거(background.js 와 동일 규칙).
      emit("source-done", {
        source: sk,
        level: (_okN > 0 && _okN >= list.length) ? "done" : "warn",
        msg: sk + (_okN === 0 ? " ⚠️ 전건 실패" : (_okN >= list.length ? " 완료" : " ⚠️ 부분 실패")) + " (" + _okN + "/" + list.length + "건 성공)",
        metrics: { concurrency, cap, active, done, total },
      });
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
          emit("concurrency", { level: "down", msg: "자원 한계(CPU≥95·MEM≥98) 강제 −1 → " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } });
        }
        return;
      }
      const blockUp = (cpu != null && cpu >= 90) || (mem != null && mem >= 96);
      if (throughput > prevThroughput * 1.05) {
        // 개선 → 채택, 가능하면 +1 탐침
        prevThroughput = throughput;
        if (concurrency < cap && !blockUp) {
          concurrency++; cooldown = 3;
          emit("concurrency", { level: "up", msg: "처리량 개선 → 창 +1 = " + concurrency + (blockUp ? "" : ""), metrics: { concurrency, cap, active, cpu, mem, done, total } });
        } else if (blockUp && concurrency < cap) {
          emit("resource", { level: "warn", msg: "처리량 여력 있으나 자원 높음(CPU≥90·MEM≥96) → +1 보류", metrics: { concurrency, cap, active, cpu, mem, done, total } });
        }
      } else if (throughput < prevThroughput * 0.9 && concurrency > 1) {
        // 처리량 하락/정체 → 직전으로 되돌림(−1)
        concurrency--; cooldown = 3; prevThroughput = throughput;
        emit("concurrency", { level: "down", msg: "처리량 하락 → 창 −1 = " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } });
      } else {
        prevThroughput = Math.max(prevThroughput, throughput);
      }
    }

    // 스케줄러 루프: active < concurrency 면 대기 소싱처를 하나 더 띄운다.
    //   타이머는 단 1개만 유지(중복 setTimeout 누적 방지). pump 는 (1)소싱처 완료 시,
    //   (2)단일 폴 타이머에서만 호출된다.
    //   [2026-06-14] 일시중지(_mgr.paused) 시 새 소싱처 안 띄움 + promise 안 resolve(재개 대기).
    //               중지(_mgr.stopped) 시 active=0 되면 즉시 종료(긁은 것까지 저장으로 진행).
    let endReason = "done";
    await new Promise((resolveAll) => {
      let done2 = false;
      let pollTimer = null;
      function finish(reason) { if (done2) return; done2 = true; endReason = reason; if (pollTimer) clearTimeout(pollTimer); resolveAll(); }
      function schedulePoll() {
        if (pollTimer) clearTimeout(pollTimer);
        pollTimer = setTimeout(() => { pollTimer = null; pump(); }, 1200);
      }
      function pump() {
        if (done2) return;
        if (_mgr.stopped) { if (active === 0) finish("stopped"); else schedulePoll(); return; }
        if (_mgr.paused) {
          // 일시중지: 새 소싱처 스케줄 안 함. in-flight 는 곧 멈춰 active=0 됨.
          //   active=0 이어도 resolve 안 함 → 재개(_kick) 때까지 대기.
          if (active > 0) schedulePoll();
          return;
        }
        evaluateConcurrency();
        while (active < concurrency && pendingSources.length > 0) {
          const sk = pendingSources.shift();
          active++;
          runSource(sk).catch((_) => {}).then(() => {
            active--;
            pump();   // 한 소싱처 끝나면 다음 채움
          });
        }
        if (active === 0 && pendingSources.length === 0) { finish("done"); return; }
        // 진행 중이면 단일 폴 타이머로 다음 평가(처리량/자원 변화 반영)
        schedulePoll();
      }
      _mgr._kick = pump;   // 재개 시 resumeCrawl 이 이 pump 를 호출
      pump();
    });
    _mgr._kick = null;

    // 3) 결과 저장(기존 엔드포인트 형식 그대로). 중지여도 긁은 것까지는 저장(폴백 아님 — 실제 크롤값).
    const items = results.map((x) => ({
      url: x.url, price: x.price, stock: x.stock,
      options: x.options,   // ★ 사이즈별 재고[{color,size,stock}] — 서버가 SourceOption.current_stock 에 반영
      status: x.status, product_name: x.product_name, error: x.error,
      is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
      benefits_ok: (x.benefits_ok === undefined ? false : !!x.benefits_ok),
      benefit_lines: x.benefit_lines || [],
      benefit_amounts: x.benefit_amounts || {},
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
          emit("item-final", {
            source: r.source_key, level: "done", lineId: r.lineId, url: r.url,
            surf: surf, buy: buy,
            msg: r.source_key + " 표면 " + surf.toLocaleString() + "원 → 매입 " + buy.toLocaleString() + "원",
          });
        });
      }
    } catch (_) { /* 갱신 실패는 크롤 저장 결과와 무관 — 무시 */ }

    const okCount = results.filter((x) => x.status === "ok").length;
    // [2026-06-13] 크롤 종료 마무리 — 유효 소싱가 없는 옵션 crawl_blocked 확정(성공=해제).
    const finalize = await _finalize();
    const stoppedTxt = endReason === "stopped" ? "중지됨 — " : "완료 — ";
    emit("finish", {
      level: endReason === "stopped" ? "warn" : "done",
      stopped: endReason === "stopped",
      msg: stoppedTxt + okCount + "/" + results.length + " 성공 · 저장 " + ((save && save.updated) || 0)
           + "건" + (finalize && finalize.blocked ? " · 판매차단 " + finalize.blocked : ""),
      metrics: { concurrency, cap, active, done, total, cpu: lastSys.cpu, mem: lastSys.mem },
    });
    return { ok: true, crawled: results.length, ok_count: okCount, save, finalize, stopped: endReason === "stopped" };
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

  // [2026-06-20] 특정 URL 목록만 '로컬 PC 창'에서 크롤(검증 재검증용).
  //   전체 크롤(crawlBundleAll)과 동일한 _crawlItemInTab 사용 → HTTP=navGrab→서버parse,
  //   무신사·롯데온=navExtract(로그인 브라우저). crawl-reset/finalize 없음(타 데이터 보존).
  //   opts.shouldStop()/shouldPause() 콜백으로 외부(검증 카드 버튼)에서 중지/일시정지 제어.
  async function crawlUrls(code, urlList, opts) {
    opts = opts || {};
    const shouldStop = opts.shouldStop || function () { return false; };
    const shouldPause = opts.shouldPause || function () { return false; };
    urlList = (urlList || []).filter(function (x) { return x && x.url && x.source_key; });
    if (!urlList.length) return { ok: false, error: "대상 URL 없음", results: [] };
    const emit = function (type, fields) { return _emitLog(type, Object.assign({ bundle: code }, fields || {})); };
    const total = urlList.length;
    emit("start", { level: "", msg: "선택 URL 로컬 창 크롤: " + total + "건", metrics: { total: total, done: 0 } });
    const results = [];
    let winId = null, tabId = null;
    try {
      const w = await send("openWin", {}, 30000);
      if (!w || !w.ok || w.tabId == null) {
        emit("finish", { level: "warn", msg: "창 생성 실패" });
        return { ok: false, error: (w && w.error) || "창 생성 실패", results: [] };
      }
      winId = w.winId; tabId = w.tabId;
      for (let i = 0; i < urlList.length; i++) {
        if (shouldStop()) break;
        while (shouldPause() && !shouldStop()) { await new Promise(function (r) { setTimeout(r, 300); }); }
        if (shouldStop()) break;
        let out;
        try { out = await _crawlItemInTab(tabId, code, urlList[i]); }
        catch (e) { out = { url: urlList[i].url, source_key: urlList[i].source_key, status: "error", error: String(e && e.message ? e.message : e) }; }
        results.push(out);
        emit("item-done", {
          source: urlList[i].source_key, level: out.status === "ok" ? "" : "warn",
          url: (out && out.url) || urlList[i].url,
          msg: out.status === "ok" ? ("표면 " + (out.price != null ? out.price.toLocaleString() + "원" : "가격없음")) : ("실패: " + (out.error || "")),
          metrics: { total: total, done: i + 1 },
        });
      }
    } finally {
      if (winId != null) { try { await send("closeWin", { winId: winId }, 10000); } catch (_) {} }
    }
    // 저장(options 포함) — 전체 크롤과 동일하게 SourceOption 반영
    const items = results.map(function (x) {
      return {
        url: x.url, price: x.price, stock: x.stock, options: x.options,
        status: x.status, product_name: x.product_name, error: x.error,
        is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
        benefits_ok: (x.benefits_ok === undefined ? false : !!x.benefits_ok),
        benefit_lines: x.benefit_lines || [], benefit_amounts: x.benefit_amounts || {},
      };
    });
    let save = null;
    if (items.length) {
      save = await fetch("/api/sources/crawl-result", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: items }),
      }).then(function (x) { return x.json(); }).catch(function (e) { return { ok: false, error: String(e) }; });
    }
    const okN = results.filter(function (x) { return x.status === "ok"; }).length;
    emit("finish", { level: "", msg: okN + "/" + results.length + " 성공", metrics: { total: total, done: results.length } });
    return { ok: true, crawled: results.length, ok_count: okN, save: save, results: results, stopped: shouldStop() };
  }

  window.MoumExt = {
    installed,
    version,
    ping: () => send("ping", {}, 8000),
    crawlUrls,
    crawl: (payload, timeoutMs) => send("crawl", payload, timeoutMs),
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
    // [2026-06-14] 멀티 큐 + 일시중지/중지(1단계) · 백그라운드 위임(2단계)
    enqueueCrawl,
    pauseCrawl,
    resumeCrawl,
    stopCrawl,
    cancelQueued,
    getCrawlState,
    reattachFromBackground,
    startSchedule,
    stopSchedule,
    scheduleStatus,
  };

  // [2단계] 페이지 로드 시 백그라운드에 진행 중 크롤이 있으면 위젯 재연결.
  //   확장(content_mou)이 data-moum-ext 를 document_start 에 심으므로 보통 이미 준비됨.
  //   혹시 늦을 수 있어 약간의 지연 후 시도(베스트에포트).
  function _initReattach() { try { reattachFromBackground(); } catch (_) {} }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(_initReattach, 600));
  } else {
    setTimeout(_initReattach, 600);
  }
})();

// ext_bridge.js — mou-m.com 페이지 쪽 확장 브리지.
//  확장(모음전 크롤러) 설치 감지 + 확장에 크롤 요청을 보내고 결과를 받는다.
//  확장의 content_mou.js 와 window.postMessage 규약으로 통신:
//    페이지 → { __moum:"page", type, payload, reqId }
//    확장   → { __moum:"ext",  reqId, ok, resp, error }
(function () {
  const _pending = {};
  let _seq = 0;

  // 백그라운드 큐 상태 캐시 (getCrawlState 동기 응답용)
  var _bgCache = { running: null, paused: false, queue: [] };

  window.addEventListener("message", (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d) return;
    // (1) 확장 응답 — reqId 대기 Promise resolve/reject
    if (d.__moum === "ext" && d.reqId) {
      const cb = _pending[d.reqId];
      if (cb) { delete _pending[d.reqId]; cb(d); }
      return;
    }
    // (2) 백그라운드 크롤 로그 — 'moum-crawl-log' CustomEvent 로 변환 (crawl_log.js 가 수신)
    if (d.__moum === "log" && d.detail) {
      var det = d.detail;
      if (det.type === "queue") {
        _bgCache.running = det.running || null;
        _bgCache.paused = !!det.paused;
        _bgCache.queue = (det.queue || []).filter(function(q) { return q.status === "wait"; }).map(function(q) { return q.code; });
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

  // [2026-06-28] 비-JSON(HTML 에러페이지·502/504·로그인 리다이렉트) 응답이면 x.json() 이
  //   SyntaxError 로 조용히 터지는 대신 명확한 에러를 던진다(res.ok·content-type 검증).
  //   조용한 실패 3원칙 (a) — 실패는 항상 표면화.
  async function fetchJson(url, opts) {
    const r = await fetch(url, opts);
    const ct = r.headers.get("content-type") || "";
    if (!r.ok || ct.indexOf("application/json") < 0) {
      throw new Error("서버 응답 오류 " + r.status + " (" + (ct || "no content-type") + ") — " + url);
    }
    return r.json();
  }

  // 모음전 1건을 확장으로 크롤 → 저장. 기본 대상 = 서버가 못 긁는 무신사·롯데온.
  async function crawlBundle(code, opts) {
    opts = opts || {};
    const sourceKeys = opts.sources || ["musinsa", "lotteon"];
    const r = await fetchJson("/api/bundles/" + encodeURIComponent(code) + "/option-matrix");
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
      is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
      // [2026-06-22] 회원 혜택 금액 추출용 — 서버 save_crawl_result 가 benefit_lines 에서
      //   등급적립·무신사머니 금액을 뽑는다. 누락 시 라이브 혜택 0 사고 → 반드시 전달.
      benefit_lines: x.benefit_lines || [], benefits_ok: x.benefits_ok,
      // [2026-06-26] 색·사이즈별 옵션 배열 전달 — 서버가 SourceOption 을 생성·영속
      //   (무신사 등 확장추출 경로의 사이즈별 재고). 누락 시 매트릭스가 상품 합계로 균일 둔갑.
      options: x.options || [],
    }));
    const save = await fetch("/api/sources/crawl-result", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
    return { ok: true, crawled: results.length, ok_count: results.filter((x) => x.ok).length, save, results };
  }

  // ── 이 PC 스케줄 크롤 ──
  //  '스케줄 크롤은 현재 컴퓨터로': localStorage['moum_sched_pc']==='1' 이고 확장 설치 시,
  //  mou-m.com 탭이 열려 있는 동안 주기적으로 전체 모음전의 무신사·롯데온을 확장으로 크롤.
  let _schedTimer = null;
  async function _schedTick() {
    if (!installed()) return;
    try {
      const r = await fetchJson("/api/bundles/codes");
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

  // URL 1건만 크롤 → 저장. option_url_modal 재크롤 버튼에서 호출.
  async function crawlSingleUrl(bundleCode, sourceKey, url, urlType) {
    const list = [{ source_key: sourceKey, url: url, url_type: urlType || 'dan' }];
    const res = await send("crawl", { model_code: bundleCode, sources: list }, 120000);
    const results = (res && res.results) || [];
    if (!results.length) return { ok: false, error: '결과 없음' };
    const x = results[0];
    await fetch("/api/sources/crawl-result", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: [{ url: x.url, price: x.price, stock: x.stock,
        status: x.ok ? "ok" : "error", product_name: x.product_name, error: x.error,
        is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
        benefit_lines: x.benefit_lines || [], benefits_ok: x.benefits_ok,
        options: x.options || [] }] }),
    }).catch(() => {});
    return { ok: x.ok || false, price: x.price, error: x.error };
  }

  // 백그라운드 큐에 모음전 1건 추가 — toss.js bundle-run-now 핸들러에서 호출.
  function enqueueCrawl(code) {
    send("crawl.enqueue", { code: code }, 10000).catch(function() {});
  }
  // 큐 상태 조회 — 동기. 백그라운드 queue 이벤트로 캐시된 _bgCache 반환.
  function getCrawlState() {
    return _bgCache;
  }
  // 큐 일시중지 / 재개 / 중지 / 취소
  function pauseCrawl()        { return send("crawl.pause",  {}, 5000); }
  function resumeCrawl()       { return send("crawl.resume", {}, 5000); }
  function stopCrawl()         { return send("crawl.stop",   {}, 5000); }
  function cancelCrawl(code)   { return send("crawl.cancel", { code: code }, 5000); }

  window.MoumExt = {
    installed,
    version,
    ping: () => send("ping", {}, 8000),
    crawl: (payload, timeoutMs) => send("crawl", payload, timeoutMs),
    crawlBundle,
    crawlSingleUrl,
    enqueueCrawl,
    getCrawlState,
    pauseCrawl,
    resumeCrawl,
    stopCrawl,
    cancelCrawl,
    startSchedule,
    stopSchedule,
    scheduleStatus,
  };
})();

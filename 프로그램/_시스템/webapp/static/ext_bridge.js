// ext_bridge.js — mou-m.com 페이지 쪽 확장 브리지.
//  확장(모음전 크롤러) 설치 감지 + 확장에 크롤 요청을 보내고 결과를 받는다.
//  확장의 content_mou.js 와 window.postMessage 규약으로 통신:
//    페이지 → { __moum:"page", type, payload, reqId }
//    확장   → { __moum:"ext",  reqId, ok, resp, error }
(function () {
  const _pending = {};
  let _seq = 0;

  // 백그라운드 큐 상태 캐시 (getCrawlState 동기 응답용)
  //   progress = 확장 실시간 집계(done/total) — 자동화 링이 위젯과 동일하게 움직이도록.
  //   확장 0.7.17+ 가 모든 크롤 이벤트에 detail.agg 를 실어 보냄(구버전이면 없음 → 링은 서버 폴백).
  var _bgCache = { running: null, paused: false, queue: [], progress: { done: 0, total: 0 } };

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
        if (!det.running) _bgCache.progress = { done: 0, total: 0 };   // 크롤 끝 = 진행 초기화
      }
      // 확장 0.7.17+ 실시간 집계 — 모든 이벤트에 실려옴. 링이 위젯과 동일하게 오름.
      if (det.agg && det.agg.total != null) _bgCache.progress = { done: +det.agg.done || 0, total: +det.agg.total || 0 };
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
        if (s.crawl_weight === 0) return;   // [2026-07-10] 계수 0 = 크롤 제외(안 긁음)
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

  // [2026-07-19 제거] '이 PC 스케줄 크롤'(startSchedule/stopSchedule/scheduleStatus + 30분 자동시작).
  //   화면에 켜고 끄는 UI 가 없는데 localStorage['moum_sched_pc']==='1' 이 남아 있으면
  //   페이지를 열 때마다 30분 주기로 전 모음전을 긁던 숨은 진입점 — 사용자가 인지·중단 불가.
  //   크롤 진입점은 ①「전체 크롤」·「자동화 설정」 ②소싱처 지도 예시 URL 크롤 둘로 한정한다.
  //   남은 플래그는 읽는 코드가 없어 무해(정리 목적으로 1회만 끔).
  try { localStorage.removeItem("moum_sched_pc"); } catch (_) {}

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

  // [2026-07-19 · S5] 소싱처 지도 예시 주소 「▶ 크롤」 — URL 1건, **저장 안 함**.
  //   crawlSingleUrl 과 다른 점 두 가지:
  //     ① 확장의 crawl.one(=엔진과 같은 라우터)을 부른다. 기존 crawl 메시지는
  //        무신사·롯데온만 알아 나머지 6개 소싱처에서 "레시피 없음"으로 실패한다.
  //     ② /api/sources/crawl-result 로 저장하지 않는다. 지도 예시 주소를 긁었다가
  //        실상품 가격·재고가 덮어써지면 안 된다. 계산·저장은 호출자가
  //        /sourcing-guide/api/<sid>/url-result 로 넘긴다.
  //   반환: 확장 raw 결과 {status:'ok'|'error', price, surface_price?, stock, benefit_lines?, ...}
  async function crawlGuideUrl(sourceKey, url, urlType) {
    if (!installed()) throw new Error("크롬 확장(모음전 크롤러)이 필요합니다.");
    var res;
    try {
      res = await send("crawl.one",
        { source_key: sourceKey, url: url, url_type: urlType || "dan" }, 180000);
    } catch (e) {
      // 구버전 확장은 crawl.one 을 모른다 — 조용히 실패한 척하지 않고 할 일을 알려준다.
      if (String(e && e.message).indexOf("unknown type") >= 0) {
        throw new Error("확장이 오래된 버전입니다(현재 " + (version() || "?")
          + "). 0.7.54 이상으로 새로고침해 주세요.");
      }
      throw e;
    }
    if (!res || res.ok !== true) {
      return { status: "error", error: (res && res.error) || "확장이 결과를 주지 않았습니다" };
    }
    return res.result || { status: "error", error: "결과 없음" };
  }

  // 백그라운드 큐에 모음전 1건 추가 — toss.js bundle-run-now 핸들러에서 호출.
  //   priority=true (모음전 상세 「전체크롤」) → 확장 큐 맨 앞(다음 순번). 자동 폴링은 뒤에 붙음.
  function enqueueCrawl(code, priority) {
    send("crawl.enqueue", { code: code, priority: !!priority }, 10000).catch(function() {});
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

  // 자동화: 서버 due-bundles 폴링 시작/정지 (실행/정지 토글에서 호출).
  //   서버 crawl_auto_enabled 게이트가 이중 안전 — 폴링이 켜져도 정지면 빈 목록.
  function autoPollStart()     { return send("moum.auto-poll.start", {}, 5000); }
  function autoPollStop()      { return send("moum.auto-poll.stop",  {}, 5000); }

  window.MoumExt = {
    installed,
    version,
    send: (type, payload, timeoutMs) => send(type, payload, timeoutMs),   // 범용 패스스루(롯데온 정산 크롤 등)
    ping: () => send("ping", {}, 8000),
    crawl: (payload, timeoutMs) => send("crawl", payload, timeoutMs),
    crawlBundle,
    crawlSingleUrl,
    crawlGuideUrl,
    enqueueCrawl,
    getCrawlState,
    pauseCrawl,
    resumeCrawl,
    stopCrawl,
    cancelCrawl,
    autoPollStart,
    autoPollStop,
    // [2026-07-12 · E2] 마진계산기 소싱처 주문상태 확인 — 로그인된 이 브라우저로 주문 URL 을 열어
    //   배경 워커가 상태를 읽는다(크롤=로컬). margin_ext_check.js(iframe)가 window.parent.MoumExt
    //   .checkSourcingOrder 로 호출. send 는 IIFE private 라 타입 메서드로만 노출한다.
    checkSourcingOrder: (payload, timeoutMs) => send("sourcing.check-order", payload, timeoutMs || 90000),
  };
})();

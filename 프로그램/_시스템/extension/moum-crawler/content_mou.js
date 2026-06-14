// content_mou.js — mou-m.com 페이지에 주입되는 콘텐츠 스크립트.
//  역할 2가지:
//   (1) 설치 마커 — <html data-moum-ext="버전"> 를 심어 페이지가 확장 설치를 감지.
//   (2) 페이지 ↔ 확장 메시지 브리지 — window.postMessage 와 chrome.runtime 사이를 중계.
//  (더망고도 동일 패턴: 콘텐츠 스크립트가 마커를 심고 페이지가 getAttribute 로 감지)

const MOUM_EXT_VERSION = "0.5.0";  // 0.5.0+ = 백그라운드 크롤 엔진(탭 닫아도 지속) 지원

// (1) 설치 마커 — document_start 시점이라 documentElement 는 이미 존재
try {
  document.documentElement.setAttribute("data-moum-ext", MOUM_EXT_VERSION);
} catch (e) {
  /* noop */
}

// (2) 페이지 → 확장 → 페이지 브리지
//   페이지가 보내는 메시지 규약: { __moum:"page", type, payload, reqId }
//   확장이 돌려주는 규약:        { __moum:"ext",  reqId, ok, resp, error }
window.addEventListener("message", (ev) => {
  if (ev.source !== window) return;            // 같은 창에서 온 것만
  const d = ev.data;
  if (!d || d.__moum !== "page" || !d.reqId) return;

  try {
    chrome.runtime.sendMessage(
      { type: d.type, payload: d.payload, reqId: d.reqId },
      (resp) => {
        const err = chrome.runtime.lastError;
        window.postMessage(
          {
            __moum: "ext",
            reqId: d.reqId,
            ok: !err,
            resp: err ? null : resp,
            error: err ? err.message : (resp && resp.error) || null,
          },
          "*"
        );
      }
    );
  } catch (e) {
    window.postMessage(
      { __moum: "ext", reqId: d.reqId, ok: false, resp: null, error: String(e) },
      "*"
    );
  }
});

// (3) [2026-06-14] 백그라운드 → 페이지 push 중계 (2단계).
//   백그라운드 크롤 엔진이 보내는 진행 로그를 페이지로 전달 → ext_bridge 가
//   'moum-crawl-log' CustomEvent 로 변환해 대시보드(crawl_log.js)가 그린다.
//   규약: 확장→ {__moumPush:"log", detail} / 페이지로 → {__moum:"log", detail}
try {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.__moumPush === "log" && msg.detail) {
      try { window.postMessage({ __moum: "log", detail: msg.detail }, "*"); } catch (_) {}
    }
  });
} catch (e) { /* noop */ }

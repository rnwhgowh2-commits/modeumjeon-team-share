// content_mou.js — mou-m.com 페이지에 주입되는 콘텐츠 스크립트.
//  역할 2가지:
//   (1) 설치 마커 — <html data-moum-ext="버전"> 를 심어 페이지가 확장 설치를 감지.
//   (2) 페이지 ↔ 확장 메시지 브리지 — window.postMessage 와 chrome.runtime 사이를 중계.
//  (더망고도 동일 패턴: 콘텐츠 스크립트가 마커를 심고 페이지가 getAttribute 로 감지)

const MOUM_EXT_VERSION = "0.7.39";   // 0.7.26 = [E2] 마진계산기 소싱처 주문상태 확인 배선 반영. 0.7.13 = 무신사 상품쿠폰 전량 수집(product_coupon_list). 0.7.12 = 롯데온 재고소스=base 엔드포인트 우선(완전 97셀). data-moum-ext 로 로드버전 확인 가능

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

// (3) 확장(백그라운드 SW) → 페이지 브리지 — 크롤 진행 로그 중계.
//   background.js 의 bgEmit 가 chrome.tabs.sendMessage(tabId, {__moumPush:"log", detail}) 로
//   푸시한 백그라운드 크롤 로그를, 여기서 페이지로 window.postMessage({__moum:"log", detail}) 중계.
//   → ext_bridge.js 가 'moum-crawl-log' CustomEvent 로 변환 → crawl_log.js 위젯 표시.
//   ⚠️ 이 리스너가 없으면 백그라운드 크롤 로그가 페이지에 도달 못 해 "전체크롤 눌러도 위젯 안 뜸"
//      버그가 난다(0.4.3 까지 누락 — 크롤이 페이지→백그라운드로 이전되며 드러난 빈틈).
try {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.__moumPush === "log" && msg.detail) {
      try { window.postMessage({ __moum: "log", detail: msg.detail }, "*"); } catch (_) {}
    }
  });
} catch (e) {
  /* noop */
}

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

// [2026-07-07 화해] 리포 ↔ 데스크톱 로드본(v0.7.17) 동기화 완료 — 롯데온 익스트랙터
//   (롯데오너스 lotte_member_discount_rate·재고 base/sitm 우선, 2026-07-03 fix Ⓑ·B) 이관.
//   이제 리포가 원천. 데스크톱은 리포에서 동기화(통째복사 금지·패치만).
const MOUM_EXT_VERSION = "0.7.55";  // 0.7.55 = [T6] 롯데온 pbf 혜택 API 이식 — lotteonExtractor 가 favorBox/benefits·qtyChangeFavorInfoList(둘 다 POST, body=base API 재구성+상수 — Playwright 실측으로 원본 body 와 응답 일치 확인, 최소 body 는 rc=422)를 직접 불러 lotteon_max_price(최대혜택 적용가 = qty.orderDcAplyTotAmt, 폴백 favor.totAmt)·lotteon_card_discounts([{label,amount,rate}] — 카드 판정 = lotteon.py is_card_coupon: 그룹 title=="카드즉시할인/장바구니쿠폰" OR prKndCd∈{CRD_IMMD,CPN_BSK_CPN} OR prTypCd=="CRD_PR")·lotteon_store_discount(1ST 스토어 즉시할인 합, 정보용) 3필드 emit. 실패=null/[] (폴백 금지 — 서버가 기존 베이스로 계산). MAIN world 로그인 쿠키라 로그인 한정 ORDER 그룹(카드) 보임. crawlItemInTabBG BG_JS 분기·toItemBG 화이트리스트에 3필드 통과 배선(서버 키는 T7). 0.7.54 = [S5] crawl.one — 소싱처 지도 예시 주소 「▶ 크롤」용 단건 크롤. 엔진과 같은 라우터(crawlItemInTabBG)를 태워 8개 소싱처 전부 지원(기존 crawl 은 EXTRACTORS=무신사·롯데온만 알아 나머지 6개가 "레시피 없음"으로 실패했다). 저장 안 함 — /api/sources/crawl-result 를 안 불러 실상품 데이터를 건드리지 않는다. 계산·저장은 서버 /sourcing-guide/api/<sid>/url-result. 0.7.53 = 정산 「자동 반복」을 확장이 소유(moum.settle-auto.set/getState) — chrome.alarms+storage.local 로 스케줄·순회를 SW 가 돌려 크롤-로그인 탭을 닫아도(크롬만 켜져 있으면) 계속 돈다. 계정목록은 서버 /accounts/api/crawl-login/accounts. 페이지는 토글·표시만(supported 응답으로 위임 판정 — 구버전이면 페이지 폴백 유지해 기능이 죽지 않게). 0.7.52 = 정산 「자동 반복」 탭 지킴이(moum.settle-keepawake) — 켜진 동안 크롤-로그인 탭 재우기 금지 + 재워졌으면 1분 알람이 되살림 → 다른 탭을 봐도 회차가 안 끊긴다. 스케줄 계산은 페이지가 단독(이중화 금지). ※manifest 와 이 상수가 어긋나 있었다(0.7.51 vs 0.7.36) — 맞춰 둔다. 0.7.34 = winless 동시 레인 — fetch형 소싱처(SW: lemouton·ssf·hmall = 창0 / same-origin: ssg·lotteimall = 도메인탭1개)는 창을 URL마다 안 열고 탭 1개(또는 0개) 안에서 '동시 상한'개 동시 fetch. '동시 상한'=레인수(창수 아님). winless 레인은 fetchOnly(창 폴백 생략·정직 error). 렌더(무신사·롯데온)만 창=레인 유지. 0.7.33 = 소싱처별 동시상한 클램프 3→8. 0.7.26 = [E2] 마진계산기 소싱처 주문상태 확인(sourcing.check-order → 주문 URL 창 오픈+사이트별 파서 주입, 크롤=로컬). spike = 무신사 창없는 probe(진단 전용, 엔진 미배선). 0.7.17 = 실시간 집계(agg done/total) 브로드캐스트 → 자동화 링이 위젯과 동일. 0.7.16 = 상세 전체크롤 최우선. 0.7.6 = 자동화 워커 폴링 + 무신사 상품쿠폰(product_coupon_list) 전량수집 API우선+DOM폴백. 0.7.5 = manifest 버전동기화. 0.7.4 = content_mou 백그라운드 로그 중계. 0.7.3 = 현대H몰 sellGbcd 품절판정(S19). 0.6.x: 백그라운드 크롤 상태 영속+SW 자동재개

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
  // ── [2026-07-19 · S5] 소싱처 지도 예시 주소 「▶ 크롤」 — URL 1건, 저장 없음 ──
  //   기존 "crawl" 은 EXTRACTORS(무신사·롯데온) 만 알아 나머지 6개 소싱처에서
  //   "레시피 없음"으로 실패한다. 여기서는 엔진이 실제로 쓰는 라우터
  //   crawlItemInTabBG 를 그대로 태워 8개 소싱처 전부 같은 경로로 긁는다
  //   (= 화면 값과 실크롤 값이 어긋나지 않는다).
  if (type === "crawl.one") {
    handleCrawlOne(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, status: "error", error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  // ── [2026-07-12 · Task E2] 소싱처 주문상태 확인 (마진계산기 '✓ 확인' 버튼) ──
  //   서버 Playwright(원본 /api/check-sourcing) 를 대체 — 로그인된 이 브라우저로 주문 URL 을 열어
  //   사이트별 파서를 주입해 상태를 읽고 창을 닫는다(크롤=로컬 원칙). 미로그인/파싱실패 정직 표면화.
  if (type === "sourcing.check-order") {
    handleCheckOrder(msg.payload || {})
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({
        ok: false, order_status: "", courier: "", tracking: "",
        site_name: (msg.payload || {}).site_name || "", source: "ext-local", logs: [],
        is_logged_in: null, error: String(e && e.message ? e.message : e),
      }));
    return true; // async
  }
  if (type === "sysinfo") {
    handleSysinfo()
      .then((r) => sendResponse(r))
      .catch((_) => sendResponse({ ok: true, cpu: null, mem: null }));
    return true; // async
  }
  if (type === "probe.musinsa") {
    probeMusinsaWindowless((msg.payload || {}).goodsId)
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  // [2026-07-07] 어댑터 단건 테스트(읽기 전용·저장 안 함) — G1 검증용. payload={sk,url}.
  if (type === "probe.adapter") {
    const _p = msg.payload || {};
    const _fn = FETCH_ADAPTERS[_p.sk];
    if (typeof _fn !== "function") { sendResponse({ ok: false, error: "어댑터 없음: " + _p.sk }); return false; }
    Promise.resolve(_fn({ source_key: _p.sk, url: _p.url, url_type: _p.url_type || "dan" }))
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e && e.message ? e.message : e) }));
    return true; // async
  }
  // ── [2026-06-14] 2단계: 백그라운드 오케스트레이터 제어 메시지 ──
  //   크롤 엔진이 이 서비스워커에서 돌아 페이지(탭)를 닫거나 이동해도 지속된다.
  if (type === "crawl.enqueue") {
    const _p = msg.payload || {};
    // [v0.6.7] 서버 타깃(base) = enqueue 한 페이지 origin 자동 — 라이브(mou-m)에서 크롤하면
    //   라이브, 로컬(localhost)에서 크롤하면 로컬 새코드 서버로 저장(배포 전 '크롤·검증').
    if (!_p.base && sender && sender.tab && sender.tab.url) {
      try { _p.base = new URL(sender.tab.url).origin; } catch (_) {}
    }
    sendResponse(mgrEnqueue(_p));
    return false;
  }
  if (type === "crawl.pause")  { sendResponse(mgrPause());  return false; }
  if (type === "crawl.resume") { sendResponse(mgrResume()); return false; }
  if (type === "crawl.stop")   { sendResponse(mgrStop());   return false; }
  if (type === "crawl.cancel") { sendResponse(mgrCancel((msg.payload || {}).code)); return false; }
  if (type === "crawl.getState") { sendResponse(mgrSnapshot()); return false; }
  // ── [2026-07-04] 자동화: 서버 due-bundles 폴링 시작/중지 (실행/정지 토글에서 발동) ──
  if (type === "moum.auto-poll.start") {
    if (!_mgr.base && sender && sender.tab && sender.tab.url) {
      try { _mgr.base = new URL(sender.tab.url).origin; } catch (_) {}
    }
    moumAutoPollStart();
    sendResponse({ ok: true });
    return false;
  }
  if (type === "moum.auto-poll.stop") { moumAutoPollStop(); sendResponse({ ok: true }); return false; }
  // ── [2026-07-17] 정산 「자동 반복」 켜짐 동안 크롤-로그인 탭 재우기 금지(다른 탭에 있어도 계속) ──
  if (type === "moum.settle-keepawake") {
    if ((msg.payload || {}).on) settleKeepAwakeStart(); else settleKeepAwakeStop();
    sendResponse({ ok: true });
    return false;
  }
  // ── [2026-07-17] 정산 「자동 반복」 스케줄을 확장이 소유(탭 닫아도 돎) ──
  //   페이지는 여기에 토글만 넘기고 상태를 받아 표시한다. supported:true 가 곧 '이 확장은
  //   탭 없이 돌릴 수 있다'는 신호 — 페이지는 이게 없으면 예전 방식(자체 타이머)으로 폴백한다.
  if (type === "moum.settle-auto.set") {
    const _p = msg.payload || {};
    let _base = _p.base || "";
    if (!_base && sender && sender.tab && sender.tab.url) { try { _base = new URL(sender.tab.url).origin; } catch (_) {} }
    settleAutoSet(!!_p.on, _p.min, _base)
      .then(() => settleLoad()).then((st) => sendResponse({ ok: true, supported: true, state: st }))
      .catch((e) => sendResponse({ ok: false, supported: true, error: String(e) }));
    return true; // async
  }
  if (type === "moum.settle-auto.getState") {
    settleLoad()
      .then((st) => sendResponse({ ok: true, supported: true, state: st, running: _settleRunning }))
      .catch((e) => sendResponse({ ok: false, supported: true, error: String(e) }));
    return true; // async
  }
  // ── [2026-07-16] 롯데온 정산 크롤: 로그인된 판매자센터 세션서 soapi selectBgt 페이징 수집 → 서버 push ──
  if (type === "lotteon.settle.crawl") {
    let base = "https://mou-m.com";
    if (sender && sender.tab && sender.tab.url) { try { base = new URL(sender.tab.url).origin; } catch (_) {} }
    handleLotteonSettleCrawl(msg.payload || {}, base)
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-07-16] 롯데온 방식A 자동 로그인: 저장 자격증명으로 판매자센터 로그인폼 자동입력·제출 ──
  if (type === "lotteon.autologin") {
    handleLotteonAutoLogin(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // 로그아웃(계정 전환용) — 판매자센터 로그아웃 후 로그인 페이지 대기
  if (type === "lotteon.logout") {
    handleLotteonLogout()
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // ── [2026-07-16] 롯데온 계정 1건 완전 자동(전용 탭서 로그아웃→로그인→정산수집 한 메시지로) ──
  //   전용 백그라운드 탭만 사용 → 사용자의 다른 롯데온 탭을 건드리지 않음(탭 오판 제거).
  if (type === "lotteon.account.collect") {
    handleLotteonAccountCollect(msg.payload || {})
      .then((r) => sendResponse(r)).catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // 전용 탭 닫기(전체 순회 종료 후 정리)
  if (type === "lotteon.closetab") {
    (async () => {
      if (_loTabId != null) { try { await chrome.tabs.remove(_loTabId); } catch (_) {} _loTabId = null; }
      sendResponse({ ok: true });
    })();
    return true;
  }
  sendResponse({ error: "unknown type: " + type });
  return false;
});

// ── [2026-07-16] 롯데온 정산 크롤 — 로그인된 store.lotteon.com 세션서 soapi 페이징 수집 → 서버 push ──
function _ymdOffset(days) {
  const d = new Date(); d.setDate(d.getDate() + days);
  return "" + d.getFullYear() + String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0");
}
async function handleLotteonSettleCrawl(payload, base) {
  const since = (payload.since || "").replace(/-/g, "") || _ymdOffset(-60);
  const until = (payload.until || "").replace(/-/g, "") || _ymdOffset(0);
  const trNo = payload.trNo || "";   // 판매자ID(예 LO10161082). 없으면 페이지 캡처값 시도.
  // 1) 로그인된 store.lotteon.com 탭 확보(없으면 임시로 열고 크롤 후 닫음 — 쿠키 공유로 로그인됨)
  let tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  let opened = false;
  if (!tab) {
    tab = await chrome.tabs.create({ url: "https://store.lotteon.com/cm/main/index_SO.wsp", active: false });
    opened = true;
    try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  }
  // 2) MAIN world 크롤(세션 토큰 읽어 selectBgt 페이징)
  let res;
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "MAIN",
      func: lotteonSettleCrawlInPage, args: [since, until, trNo],
    });
    res = (out && out[0] && out[0].result) || { ok: false, error: "실행 결과 없음" };
  } finally {
    if (opened) { try { await chrome.tabs.remove(tab.id); } catch (_) {} }
  }
  if (!res.ok) return res;
  // 3) 서버 push 는 페이지가 한다(SW fetch 는 mou-m 인증 쿠키 미전송 → upserted 0). rows 를
  //    호출 페이지(mou-m, 인증됨)로 돌려주고 페이지가 POST /api/margin/lotteon-settlement.
  return { ok: true, rows: res.rows, collected: res.rows.length, lines: res.lines, total: res.total, trNo: res.trNo };
}
// MAIN world 주입 — 페이지 컨텍스트(store.lotteon.com origin·세션쿠키)서 실행. 외부 스코프 참조 금지.
function lotteonSettleCrawlInPage(sinceYMD, untilYMD, trNoArg) {
  return new Promise(function (resolve) {
    (async function () {
      try {
        var tok = null, hex = /[0-9a-f]{56}/;
        for (var i = 0; i < sessionStorage.length; i++) {
          var v = "" + (sessionStorage.getItem(sessionStorage.key(i)) || "");
          var m = v.match(hex); if (m) { tok = m[0]; break; }
        }
        if (!tok) return resolve({ ok: false, error: "세션 토큰 없음 — 판매자센터 로그인 후 재시도" });
        // trNo(판매자ID) — 지정 없으면 로그인된 판매자센터 DOM에서 자동감지
        //   #mf_sellerShop_trNo(브랜드박스 옆 판매자코드) → 없으면 본문 LO######## 정규식.
        var trNo = trNoArg || (window.__H && window.__H.trNo) || "";
        if (!trNo) {
          try {
            var elT = document.getElementById("mf_sellerShop_trNo");
            if (elT) trNo = (elT.textContent || "").trim();
          } catch (e) {}
        }
        if (!trNo) {
          try { var mm = (document.body.innerText || "").match(/LO\d{8,}/); if (mm) trNo = mm[0]; } catch (e) {}
        }
        if (!trNo) return resolve({ ok: false, error: "trNo(판매자ID) 자동감지 실패 — 판매자센터 로그인 확인 or payload로 지정" });
        function get(p) {
          return new Promise(function (res) {
            var x = new XMLHttpRequest();
            var qs = "strtDttm=" + sinceYMD + "&endDttm=" + untilYMD + "&trNo=" + encodeURIComponent(trNo) +
                     "&lrtrNo=&inqDvsCd=&odSearchTypCd=01&odSearchTypNm=&pageNo=" + p + "&rowsPerPage=30";
            x.open("GET", "https://soapi.lotteon.com/settle/v1/so/mediationSettleManagement/selectBgtSettleManagementList?" + qs);
            x.setRequestHeader("authorization", "Bearer " + tok);
            x.setRequestHeader("x-timezone", "GMT+09:00");
            x.setRequestHeader("accept", "application/json");
            x.withCredentials = true;
            x.onload = function () { res({ s: x.status, t: x.responseText }); };
            x.onerror = function () { res({ s: 0, t: "neterr" }); };
            x.send();
          });
        }
        var agg = {}, page = 1, total = null, lines = 0;
        while (page <= 400) {
          var r = await get(page);
          if (r.s !== 200) return resolve({ ok: false, error: "HTTP " + r.s + " @page" + page, trNo: trNo });
          var j = JSON.parse(r.t);
          var d = (j && j.data) ? j.data : j;
          var list = (d && d.mediationSettleList && d.mediationSettleList.dataList) || (d && d.dataList) || [];
          if (total === null) total = (d && d.mediationSettleList && d.mediationSettleList.totalCount) || (d && d.totalCount) || null;
          for (var k = 0; k < list.length; k++) {
            var it = list[k], od = ("" + (it.odNo || "")).trim();
            if (!od) continue;                 // ★요약행(빈 odNo) 제외
            var seq = "" + (it.odSeq || "1"), key = od + "|" + seq;
            if (!agg[key]) agg[key] = { odNo: od, odSeq: seq, pymtTgtAmt: 0, slChNo: it.slChNo || null, trNo: it.trNo || trNo };
            agg[key].pymtTgtAmt += Math.round(parseFloat(it.pymtTgtAmt || 0));   // procSeq +X/-X 순액
            lines++;
          }
          if (list.length < 30) break;
          page++;
        }
        resolve({ ok: true, rows: Object.keys(agg).map(function (k) { return agg[k]; }), total: total, lines: lines, trNo: trNo });
      } catch (e) { resolve({ ok: false, error: String(e) }); }
    })();
  });
}

// ── [2026-07-16] 롯데온 방식A 자동 로그인 ──
//   저장 자격증명(login_id/password)으로 판매자센터 로그인폼을 자동입력·제출한다.
//   본인인증(새 기기·가끔)이 뜨면 needs_verify=true 로 멈춰 사용자가 직접 처리하게 한다.
const _LO_LOGIN_URL = "https://store.lotteon.com/cm/main/login_SO.wsp";
const _LO_HOME_URL = "https://store.lotteon.com/cm/main/index_SO.wsp";
let _loTabId = null;   // 전용 백그라운드 탭(전체 자동 순회 내내 재사용 — 사용자 다른 탭 안 건드림)
function _sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ★탭이 닫히면 즉시 잊는다 — 안 그러면 죽은 탭 번호로 계속 호출해
//   'No tab with id' 오류가 확장 「오류」 목록에 쌓인다(2026-07-17 사용자 화면 실제 발생).
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === _loTabId) _loTabId = null;
  if (tabId === _serviceTabId) { _serviceTabId = null; _serviceTabOwned = false; }
});

// 전용 탭 확보(없거나 닫혔으면 생성). active:false 백그라운드.
async function _loGetDedicatedTab() {
  if (_loTabId != null) {
    try { const t = await chrome.tabs.get(_loTabId); if (t) return t; } catch (_) { _loTabId = null; }
  }
  const t = await chrome.tabs.create({ url: _LO_LOGIN_URL, active: false });
  _loTabId = t.id;
  try { await waitTabComplete(t.id, 25000); } catch (_) {}
  return t;
}

// SW 백업 로그아웃 — chrome.cookies 로 lotteon 쿠키 제거(document.cookie 로 못 지우는 httpOnly 대비).
async function clearLotteonCookiesGlobal() {
  let n = 0;
  try {
    const list = await chrome.cookies.getAll({ domain: "lotteon.com" });
    for (const c of list) {
      const host = c.domain.replace(/^\./, "");
      for (const proto of ["https://", "http://"]) {
        try { await chrome.cookies.remove({ url: proto + host + (c.path || "/"), name: c.name }); n++; } catch (_) {}
      }
    }
  } catch (_) {}
  return n;
}

// ── [2026-07-16] 롯데온 계정 1건 완전 자동 — 전용 탭서 로그아웃→로그인→정산수집 ──
async function handleLotteonAccountCollect(payload) {
  const loginId = payload.login_id || payload.loginId || "";
  const password = payload.password || "";
  if (!loginId || !password) return { ok: false, error: "자격증명 없음(login_id/password 필요)" };
  const sinceYMD = (payload.since || "").replace(/-/g, "") || _ymdOffset(-60);
  const untilYMD = (payload.until || "").replace(/-/g, "") || _ymdOffset(0);
  const loginOnly = !!payload.login_only;   // 「🔑 로그인 테스트」 — 수집 없이 로그인만 확인

  // ★계정당 예산(240s) — 페이지 상한(300s) 안쪽에서 스스로 끝내고 '어느 단계'였는지 보고한다.
  //   예산이 없으면 대기가 누적돼 페이지가 먼저 죽고, 원인이 '확장 응답 시간초과' 한 줄로 뭉개져
  //   자격증명 문제인지 속도 문제인지 구분이 안 된다(2026-07-17 실측 — 이 때문에 오진했다).
  const deadline = Date.now() + 240000;
  const left = () => deadline - Date.now();
  const cap = (ms) => Math.max(1000, Math.min(ms, left()));
  let step = "탭 준비";
  const over = () => ({ ok: false, timeout: true, step: step, error: "시간초과 — '" + step + "' 단계에서 4분 초과" });

  const tab = await _loGetDedicatedTab();
  // 1) ★공식 로그아웃(신뢰기기 유지 → 재로그인 2단계 안 뜸) — 실검증 확정 레시피.
  //   쿠키클리어 로그아웃은 신뢰기기까지 지워 2단계 재발 → 폐기. 대신 홈으로 가서 로그인 상태면
  //   WebSquare 로그아웃 버튼 핸들러를 컴포넌트.trigger('onclick')로 발화 + 확인 모달 클릭.
  step = "이전 계정 로그아웃";
  try { await chrome.tabs.update(tab.id, { url: _LO_HOME_URL }); await waitTabComplete(tab.id, cap(25000)); } catch (_) {}
  await _sleep(1000);
  if (left() <= 0) return over();
  let st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.loggedIn) {
    // 로그아웃은 페이지를 이동시켜 프레임을 잃을 수 있다(정상) — 에러 무시.
    try { await _loInject(tab.id, lotteonOfficialLogoutInPage, []); } catch (_) {}
    // ★'로그아웃 될 때까지' 확인한다 — waitTabComplete 로 기다리면 안 된다.
    //   그 시점 탭은 이미 status=complete(홈이 떠 있는 상태)라 0초에 반환하고, 실질 대기가
    //   sleep 1.5초뿐이 된다. 롯데온 로그아웃(확인 모달→네비게이션)이 그보다 늦으면 로그인된
    //   채로 다음 단계에 가서 '이전 계정 로그아웃 실패(세션 유지)'가 난다(2026-07-17 라이브 실측
    //   — 계정1 성공 직후 계정2에서 재현). 최대 ~13초 폴링 + 중간 1회 재발화.
    for (let i = 0; i < 14; i++) {
      await _sleep(900);
      if (left() <= 0) return over();
      let s2 = null;
      try { s2 = await _loInject(tab.id, lotteonCheckStateInPage, [], { tries: 1 }); } catch (_) { continue; }
      if (s2 && !s2.loggedIn) break;                       // 로그아웃 확인됨
      if (i === 6) {                                        // 확인 모달을 놓친 경우 한 번 더 발화
        try { await _loInject(tab.id, lotteonOfficialLogoutInPage, []); } catch (_) {}
      }
    }
  }
  // 2) 로그인 페이지 확보 후 상태 확인
  step = "로그인 페이지 열기";
  if (left() <= 0) return over();
  try { await chrome.tabs.update(tab.id, { url: _LO_LOGIN_URL }); await waitTabComplete(tab.id, cap(25000)); } catch (_) {}
  await _sleep(900);
  st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.loggedIn) return { ok: false, step: step, error: "이전 계정 로그아웃 실패(세션 유지)", trNo: st.trNo };
  if (!st || !st.hasForm) return { ok: false, step: step, error: "로그인 폼을 찾지 못함(페이지 구조 변경?)" };
  // 3) 폼 자동입력 + 제출
  step = "로그인";
  const fr = await _loInject(tab.id, lotteonFillLoginInPage, [loginId, password]);
  if (!fr || !fr.submitted) return { ok: false, step: step, error: (fr && fr.error) || "로그인 제출 실패" };
  try { await waitTabComplete(tab.id, cap(25000)); } catch (_) {}
  // ★로그인 완료를 폴링(WebSquare 비동기 로그인 — 단일 체크는 너무 이르다. 실검증: 로그인은
  //   성공하는데 1.8초 체크가 폼을 봐 '실패' 오인). 최대 ~20초 대기.
  //   tries:1 — 루프가 곧 다시 물어보므로 여기서 재시도하면 대기만 16배로 불어난다.
  let logged = null;
  for (let i = 0; i < 16; i++) {
    await _sleep(1200);
    if (left() <= 0) return over();
    try { st = await _loInject(tab.id, lotteonCheckStateInPage, [], { tries: 1 }); } catch (_) { continue; }
    if (st && st.needsVerify) return { ok: false, needs_verify: true, step: step, error: "본인인증 필요(새 기기·가끔) — 직접 인증 후 재시도" };
    if (st && st.loggedIn) { logged = st; break; }
  }
  if (!logged) return { ok: false, step: step, error: "로그인 실패 — 아이디·비밀번호를 확인하세요(20초 안에 로그인 안 됨)" };
  if (loginOnly) return { ok: true, login_only: true, collected: 0, rows: [], trNo: logged.trNo || "" };
  // 4) 같은 탭서 정산 수집(검출된 trNo 전달 — 헤더 렌더 지연 대비)
  step = "정산 수집";
  if (left() <= 0) return over();
  const res = await _loInject(tab.id, lotteonSettleCrawlInPage, [sinceYMD, untilYMD, logged.trNo || ""]);
  if (!res || !res.ok) return { ok: false, step: step, error: (res && res.error) || "정산 수집 실패", trNo: logged.trNo };
  return { ok: true, rows: res.rows, collected: res.rows.length, lines: res.lines, total: res.total, trNo: res.trNo || logged.trNo };
}

// MAIN world — ★공식 로그아웃(신뢰기기 유지). WebSquare 로그아웃버튼 핸들러를 컴포넌트.trigger로
//   발화 → "로그아웃 하시겠습니까?" 확인 모달의 「확인」 클릭 → 공식 로그아웃(login_SO.wsp).
//   실검증(2026-07-17): 이 방식은 세션만 끊고 2단계 신뢰기기 쿠키는 유지 → 재로그인 2단계 안 뜸.
function lotteonOfficialLogoutInPage() {
  return new Promise(function (resolve) {
    (async function () {
      try {
        window.confirm = function () { return true; };
        window.alert = function () {};
        if (document.getElementById("mf_loginUserId")) return resolve({ ok: true, already: true });
        var comp = window.mf_btnLogout;
        if (!comp || typeof comp.trigger !== "function") return resolve({ ok: false, error: "로그아웃 컴포넌트 없음" });
        try { comp.trigger("onclick"); } catch (e) { try { comp.trigger("click"); } catch (e2) {} }
        for (var i = 0; i < 12; i++) {
          await new Promise(function (r) { setTimeout(r, 500); });
          if (document.getElementById("mf_loginUserId") || /login_SO/.test(location.href)) return resolve({ ok: true });
          var cands = Array.prototype.slice.call(document.querySelectorAll("a,button,input"));
          for (var j = 0; j < cands.length; j++) {
            var t = (cands[j].textContent || cands[j].value || "").trim();
            if (t === "확인" && cands[j].offsetParent !== null) { cands[j].click(); break; }
          }
        }
        resolve({ ok: true });
      } catch (e) { resolve({ ok: false, error: String(e) }); }
    })();
  });
}

// MAIN world — 이 문서에서 접근 가능한 쿠키 전부 만료(EC_BO_AUTH_CODE 등 세션쿠키 = 비 httpOnly, 실검증).
function lotteonClearCookiesInPage() {
  try {
    var names = document.cookie.split(";").map(function (c) { return c.trim().split("=")[0]; }).filter(Boolean);
    var doms = ["", ".lotteon.com", "store.lotteon.com", ".store.lotteon.com"];
    names.forEach(function (n) {
      doms.forEach(function (d) {
        document.cookie = n + "=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/" + (d ? ("; domain=" + d) : "");
      });
    });
    return { cleared: names.length };
  } catch (e) { return { cleared: 0, error: String(e) }; }
}

async function _loEnsureTab(url) {
  let tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  if (!tab) {
    tab = await chrome.tabs.create({ url: url, active: false });
    try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  }
  return tab;
}
async function _loInject(tabId, fn, args, opts) {
  // ★네비게이션 중 프레임 제거("Frame with ID 0 was removed") 등 일시오류는 잠깐 뒤 재시도.
  //   공식 로그아웃·로그인 제출이 페이지를 이동시켜 executeScript 가 프레임을 잃는 레이스 대응.
  // ★이미 반복 중인 폴 루프에서는 tries:1 로 부를 것 — 루프가 곧 다시 묻는데 여기서도 재시도하면
  //   대기가 곱해져 계정 예산을 통째로 먹는다(2026-07-17 '확장 응답 시간초과'의 실제 원인).
  const tries = (opts && opts.tries) || 4;
  let lastErr = null;
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      const out = await chrome.scripting.executeScript({
        target: { tabId: tabId }, world: "MAIN", func: fn, args: args || [],
      });
      return (out && out[0] && out[0].result) || null;
    } catch (e) {
      lastErr = e;
      // ★대기를 짧게 — 15초×4 는 계정당 240초 상한을 넘겨 '확장 응답 시간초과'를 유발했다.
      if (/Frame|removed|No frame|cannot be scripted|being unloaded|No tab with id/i.test(String(e))) {
        try { await waitTabComplete(tabId, 4000); } catch (_) {}
        await _sleep(500);
        continue;
      }
      throw e;
    }
  }
  throw lastErr;
}

async function handleLotteonAutoLogin(payload) {
  const loginId = payload.login_id || payload.loginId || "";
  const password = payload.password || "";
  if (!loginId || !password) return { ok: false, error: "자격증명 없음(login_id/password 필요)" };
  const tab = await _loEnsureTab(_LO_LOGIN_URL);
  // 1) ★항상 로그인 페이지로 새로 이동 후 판정 — 스테일 DOM·백그라운드 로그인탭 오판 방지.
  //    세션이 살아있으면 롯데온이 login→index 로 리다이렉트하므로 checkState 가 loggedIn 을 잡는다.
  try { await chrome.tabs.update(tab.id, { url: _LO_LOGIN_URL }); } catch (_) {}   // 탭이 사라졌을 수 있음
  try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  await new Promise((r) => setTimeout(r, 900));
  let st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.loggedIn) return { ok: true, already: true, trNo: st.trNo || null };
  if (!st || !st.hasForm) return { ok: false, error: "로그인 폼을 찾지 못함(페이지 구조 변경?)" };
  // 2) 폼 자동입력 + 제출
  const fr = await _loInject(tab.id, lotteonFillLoginInPage, [loginId, password]);
  if (!fr || !fr.submitted) return { ok: false, error: (fr && fr.error) || "로그인 제출 실패(버튼 못 찾음)" };
  // 4) 제출 후 네비게이션 대기 → 상태 재확인
  try { await waitTabComplete(tab.id, 25000); } catch (_) {}
  await new Promise((r) => setTimeout(r, 1500));   // WebSquare 렌더 여유
  st = await _loInject(tab.id, lotteonCheckStateInPage, []);
  if (st && st.needsVerify) return { ok: false, needs_verify: true, error: "본인인증 필요(새 기기·가끔) — 직접 인증 후 재시도" };
  if (st && st.loggedIn) return { ok: true, trNo: st.trNo || null };
  if (st && st.hasForm) return { ok: false, error: "로그인 실패(아이디/비번 확인) — 폼 그대로" };
  return { ok: false, error: "로그인 결과 불명(상태 미확정)" };
}

async function handleLotteonLogout() {
  // ★확실한 로그아웃 = 롯데온 세션 쿠키 클리어(판매자센터 로그아웃 버튼은 WebSquare 내부이벤트라
  //   DOM 조작으로 안 터진다). 쿠키 기반 세션이라 쿠키 제거 → 다음 요청 미인증 → 로그아웃.
  let cleared = 0;
  try {
    const domains = ["lotteon.com", ".lotteon.com", "store.lotteon.com", "soapi.lotteon.com"];
    const seen = new Set();
    for (const d of domains) {
      let list = [];
      try { list = await chrome.cookies.getAll({ domain: d }); } catch (_) {}
      for (const c of list) {
        const host = c.domain.replace(/^\./, "");
        const url = (c.secure ? "https://" : "http://") + host + (c.path || "/");
        const key = url + "|" + c.name;
        if (seen.has(key)) continue;
        seen.add(key);
        try { await chrome.cookies.remove({ url: url, name: c.name }); cleared++; } catch (_) {}
      }
    }
  } catch (e) { return { ok: false, error: "쿠키 클리어 실패: " + String(e) }; }
  // 열린 탭이 있으면 로그인 페이지로 이동(세션 무효 반영)
  const tab = (await chrome.tabs.query({ url: "https://store.lotteon.com/*" }))[0];
  if (tab) {
    try { await chrome.tabs.update(tab.id, { url: _LO_LOGIN_URL }); await waitTabComplete(tab.id, 20000); } catch (_) {}
    await new Promise((res) => setTimeout(res, 800));
    const st = await _loInject(tab.id, lotteonCheckStateInPage, []);
    return { ok: true, cleared: cleared, loggedOut: !!(st && !st.loggedIn) };
  }
  return { ok: true, cleared: cleared, loggedOut: true };
}

// MAIN world — 로그인 상태 판정. 외부 스코프 참조 금지.
function lotteonCheckStateInPage() {
  try {
    // ★로그인 후 안내 팝업 자동 처리 — 자동로그인이 여기서 막히지 않게.
    //   "비밀번호 필수 변경(2일 남음)" 팝업=「취소」, 공지 팝업=「창닫기/오늘 하루 보지 않기」.
    try {
      var pbody = (document.body && document.body.innerText) || "";
      var clickByText = function (labels) {
        var cs = Array.prototype.slice.call(document.querySelectorAll("a,button,input"));
        for (var ci = 0; ci < cs.length; ci++) {
          var t = (cs[ci].textContent || cs[ci].value || "").trim();
          if (labels.indexOf(t) >= 0 && cs[ci].offsetParent !== null) { try { cs[ci].click(); } catch (e) {} return true; }
        }
        return false;
      };
      if (/비밀번호 필수 변경|비밀번호를 변경하시겠습니까|비밀번호 변경 안내|변경일이 .* 남았습니다/.test(pbody)) {
        clickByText(["취소", "다음에", "나중에 변경", "나중에"]);
      }
      if (/중요 공지사항|모두 확인하셨나요/.test(pbody)) {
        clickByText(["창닫기", "오늘 하루 보지 않기", "닫기"]);
      }
    } catch (e) {}
    var trEl = document.getElementById("mf_sellerShop_trNo");
    var trNo = trEl ? (trEl.textContent || "").trim() : "";
    var idI = document.getElementById("mf_loginUserId");
    var pwI = document.getElementById("mf_sct_passwd");
    var hasForm = !!(idI && pwI && idI.offsetParent !== null && pwI.offsetParent !== null);
    // 세션 토큰(56 hex) 존재 여부
    var hasTok = false, hex = /[0-9a-f]{56}/;
    for (var i = 0; i < sessionStorage.length; i++) {
      var v = "" + (sessionStorage.getItem(sessionStorage.key(i)) || "");
      if (hex.test(v)) { hasTok = true; break; }
    }
    var body = (document.body && document.body.innerText) || "";
    // ★2단계 인증(SMS 보안코드) 화면 감지 — 실측 문구 "2단계 인증"·"보안코드"·"인증번호".
    //   자동로그인이 여기서 막히면 needs_verify 로 깔끔히 멈춰 사용자가 직접 인증하게 한다.
    var needsVerify = /2단계 인증|보안코드|본인인증|인증번호|휴대폰 인증|휴대전화 인증|이중 인증|OTP/.test(body) && !hasForm;
    var onLoginPage = /login_SO\.wsp/.test(location.href);
    // 로그인 판정: 판매자코드 노출 or 세션토큰 있고 로그인폼/로그인페이지 아님
    var loggedIn = (!!trNo || hasTok) && !hasForm && !onLoginPage;
    return { loggedIn: loggedIn, hasForm: hasForm, needsVerify: needsVerify, trNo: trNo, url: location.href };
  } catch (e) { return { loggedIn: false, hasForm: false, needsVerify: false, error: String(e) }; }
}

// MAIN world — 로그인 폼 자동입력 + 제출.
function lotteonFillLoginInPage(loginId, password) {
  try {
    var idI = document.getElementById("mf_loginUserId");
    var pwI = document.getElementById("mf_sct_passwd");
    if (!idI || !pwI) return { submitted: false, error: "입력칸 없음" };
    function setVal(el, val) {
      var proto = Object.getPrototypeOf(el);
      var desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) desc.set.call(el, val); else el.value = val;
      ["input", "change", "keyup", "blur"].forEach(function (t) {
        el.dispatchEvent(new Event(t, { bubbles: true }));
      });
    }
    idI.focus(); setVal(idI, loginId);
    pwI.focus(); setVal(pwI, password);
    // 로그인 버튼 찾기 — id/onclick/텍스트로. '아이디 찾기'·'비밀번호' 제외.
    var btn = document.getElementById("mf_btn_login") || document.getElementById("btn_login");
    if (!btn) {
      var cands = Array.prototype.slice.call(document.querySelectorAll("a,button,input[type=submit],[onclick]"));
      for (var i = 0; i < cands.length; i++) {
        var t = (cands[i].textContent || cands[i].value || "").trim();
        if (t === "로그인" && cands[i].offsetParent !== null) { btn = cands[i]; break; }
      }
    }
    if (!btn) return { submitted: false, error: "로그인 버튼 못 찾음" };
    btn.click();
    return { submitted: true };
  } catch (e) { return { submitted: false, error: String(e) }; }
}


// ── [스파이크 2026-07-07] 무신사 창없는 재고·가격 probe (서비스워커 직접 fetch) ──
//   목적: musinsaExtractor(탭 컨텍스트)와 동일한 API를 SW에서 호출해 200 되는지 실측.
//   엔진 미배선 — probe.musinsa 메시지로 수동 호출만. 폴백 금지: 실패는 http 코드로 그대로 표면화.
async function probeMusinsaWindowless(goodsId) {
  const t0 = Date.now();
  const base = "https://goods-detail.musinsa.com/api2/goods/" + goodsId;
  const out = { ok: false, goodsId: goodsId, http_options: null, http_inv: null,
                http_price: null, stock_map: null, salePrice: null, error: null };
  function finish() { out.elapsed_ms = Date.now() - t0; return out; }
  try {
    const or = await fetch(base + "/options", { credentials: "include", headers: { Accept: "application/json" } });
    out.http_options = or.status;
    if (!or.ok) { out.error = "options http " + or.status; return finish(); }
    const oj = await or.json();
    const basic = (oj.data || {}).basic || [];
    const valueNos = [];
    basic.forEach((g) => (g.optionValues || g.values || []).forEach((v) => { if (v.no != null) valueNos.push(v.no); }));

    const ir = await fetch(base + "/options/v2/prioritized-inventories", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ optionValueNos: valueNos }),
    });
    out.http_inv = ir.status;
    if (ir.ok) {
      const ij = await ir.json();
      const arr = (ij && ij.data) || [];
      const m = {};
      arr.forEach((x) => { m[x.productVariantId] = x; });
      out.stock_map = m;
    }

    const pr = await fetch(base, { credentials: "include", headers: { Accept: "application/json" } });
    out.http_price = pr.status;
    if (pr.ok) {
      const pj = await pr.json();
      out.salePrice = (((pj.data || {}).goodsPrice) || {}).salePrice != null
        ? pj.data.goodsPrice.salePrice : null;
    }

    out.ok = (out.http_options === 200 && out.http_inv === 200 && out.stock_map != null);
    return finish();
  } catch (e) {
    out.error = String(e && e.message ? e.message : e);
    return finish();
  }
}

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
      // [2026-06-22] n/v2 재고 API 는 간헐적으로 200+빈바디(empty-body)를 준다 — 재시도 없으면
      //   그 크롤만 sku_stock=null → 전 옵션 999('있음') 둔갑(좋은 재고 통째 소실). 유효 combos
      //   받으면 즉시 종료(정상 시 1회=영향 0), 못 받으면 0.6s·1.2s 백오프로 최대 3회.
      let _lastErr = "empty";
      for (let attempt = 0; attempt < 3; attempt++) {
        let resp, txt = "";
        try {
          resp = await fetch(`/n/v2/channels/${cu}/products/${pno}`, { credentials: "include", headers: { accept: "application/json" } });
          txt = await resp.text();
        } catch (e) { _lastErr = "fetch-exc:" + String(e).slice(0, 30); }
        if (txt && txt.length >= 2) {
          let j = null; try { j = JSON.parse(txt); } catch (e) { _lastErr = "api-parse:len" + txt.length; }
          if (j) {
            const ap = walkFor(j);
            if (ap.combos) return { map: ap.map, combos: ap.combos, via: "api" + (attempt ? "-r" + attempt : "") };
            _lastErr = "no-combos";
          }
        } else if (resp && !resp.ok) {
          _lastErr = "http-" + resp.status;
        } else {
          _lastErr = "empty-body:" + (txt ? txt.length : 0);
        }
        if (attempt < 2) await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
      }
      return { err: _lastErr };
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
      // [2026-06-22] n/v2 재고 API 는 간헐적으로 200+빈바디(empty-body)를 준다 — 재시도 없으면
      //   그 크롤만 sku_stock=null → 전 옵션 999('있음') 둔갑(좋은 재고 통째 소실). 유효 combos
      //   받으면 즉시 종료(정상 시 1회=영향 0), 못 받으면 0.6s·1.2s 백오프로 최대 3회.
      let _lastErr = "empty";
      for (let attempt = 0; attempt < 3; attempt++) {
        let resp, txt = "";
        try {
          resp = await fetch(`/n/v2/channels/${cu}/products/${pno}`, { credentials: "include", headers: { accept: "application/json" } });
          txt = await resp.text();
        } catch (e) { _lastErr = "fetch-exc:" + String(e).slice(0, 30); }
        if (txt && txt.length >= 2) {
          let j = null; try { j = JSON.parse(txt); } catch (e) { _lastErr = "api-parse:len" + txt.length; }
          if (j) {
            const ap = walkFor(j);
            if (ap.combos) return { map: ap.map, combos: ap.combos, via: "api" + (attempt ? "-r" + attempt : "") };
            _lastErr = "no-combos";
          }
        } else if (resp && !resp.ok) {
          _lastErr = "http-" + resp.status;
        } else {
          _lastErr = "empty-body:" + (txt ? txt.length : 0);
        }
        if (attempt < 2) await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
      }
      return { err: _lastErr };
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
      if (raw && raw.length > 5000) {
        // [2026-06-22] 데이터는 위 직접 fetch raw HTML 을 그대로 사용(품절임박 N 보존).
        //   단, 다른 소싱처처럼 '화면에도 상품 페이지가 보이도록' 탭을 이동시킨다.
        //   ※ 렌더 결과는 데이터로 쓰지 않으므로(보여주기 전용) lazy 렌더/JS소진 문제 무관.
        if (tabId != null) {
          try {
            await chrome.tabs.update(tabId, { url });
            await waitTabComplete(tabId, 25000);
          } catch (_) { /* 화면 표시 실패해도 데이터(raw)는 정상 반환 */ }
        }
        return { ok: true, html: raw };
      }
    } catch (e) { /* 실패 시 아래 렌더 grab 폴백 */ }
  }
  if (tabId == null) return { ok: false, error: "tabId 없음" };
  try { await chrome.tabs.update(tabId, { url }); } catch (e) { return { ok: false, error: "탭 없음/이동 실패: " + e }; }
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
  try { await chrome.tabs.update(tabId, { url }); } catch (e) { return { ok: false, error: "탭 없음/이동 실패: " + e }; }
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

// ── [2026-07-19 · S5] URL 1건 크롤 — 소싱처 지도 예시 주소 「▶ 크롤」 전용 ──
//   · 엔진과 **같은 라우터**(crawlItemInTabBG)를 탄다. 어댑터를 따로 부르지 않는다 —
//     따로 부르면 SSG·롯데아이몰처럼 엔진이 안 쓰는 경로로 긁혀 값이 어긋난다.
//   · **저장하지 않는다.** /api/sources/crawl-result 를 부르지 않으므로 실상품
//     가격·재고 데이터를 건드리지 않는다(지도에서 눌렀다가 매트릭스가 바뀌면 사고).
//     계산·저장은 페이지가 서버 /sourcing-guide/api/<sid>/url-result 로 넘긴다.
//   · 창은 여기서 열고 반드시 닫는다(실패해도 finally).
//   payload: {source_key, url, url_type?}
async function handleCrawlOne(payload) {
  const sk = payload.source_key, url = payload.url;
  if (!sk || !url) return { ok: false, status: "error", error: "source_key·url 이 필요합니다" };
  if (ALL_SOURCE_KEYS.indexOf(sk) < 0) {
    // 정직하게 거절 — 빈 결과를 성공으로 돌려주지 않는다.
    return { ok: false, status: "error",
             error: "이 소싱처는 아직 크롤을 지원하지 않습니다: " + sk };
  }
  const w = await handleOpenWin({});
  if (!w.ok) return { ok: false, status: "error", error: w.error || "창 생성 실패" };
  try {
    const out = await crawlItemInTabBG(
      w.tabId, null, { source_key: sk, url: url, url_type: payload.url_type || "dan" }, null);
    // crawlItemInTabBG 는 {status:'ok'|'error', price, stock, ...} 를 준다. 그대로 넘긴다.
    return { ok: true, result: out || { status: "error", error: "결과 없음" } };
  } finally {
    try { await chrome.windows.remove(w.winId); } catch (_) {}
  }
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
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(to);
      chrome.tabs.onUpdated.removeListener(listener);
      chrome.tabs.onRemoved.removeListener(onGone);
      resolve();
    };
    const to = setTimeout(finish, timeoutMs);
    function listener(id, info) { if (id === tabId && info.status === "complete") finish(); }
    // ★탭이 사라지면 즉시 끝낸다 — 없으면 죽은 탭을 timeoutMs(25초)만큼 헛기다려 예산을 태운다.
    function onGone(id) { if (id === tabId) finish(); }
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.onRemoved.addListener(onGone);
    // ★lastError 를 반드시 읽을 것 — 안 읽으면 크롬이 'Unchecked runtime.lastError: No tab with id'
    //   를 확장 「오류」로 기록한다(2026-07-17 실제 발생). 읽으면 조용해지고, 죽은 탭도 즉시 반환.
    chrome.tabs.get(tabId, (t) => {
      if (chrome.runtime.lastError) { finish(); return; }   // 탭 없음 = 기다릴 이유 없음
      if (t && t.status === "complete") finish();
    });
  });
}

// [2026-06-14 fix F] 유닛당 하드 타임아웃 — 한 소싱처 1건이 행(예: 네이버 봇차단 페이지가
//   never-complete)해도 전체크롤이 영구 정지하지 않게. 정상 무신사 유닛(waitTabComplete 25s
//   + 혜택 아코디언 ~8s)보다 넉넉히 큰 60s. 타임아웃 시 그 유닛만 error 로 표면화하고 진행.
const UNIT_TIMEOUT_MS = 60000;
// [2026-06-22] bgFetch(서비스 탭 executeScript) 1회 하드 타임아웃. 서버 응답은 0.6~0.8s 라
//   20s 면 충분 — 초과 = 탭 먹통/discard 로 간주하고 탭 교체 후 재시도.
const BGFETCH_TIMEOUT_MS = 20000;
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
  // ★ 2026-06-22 — goodsPrice 일시 실패(네트워크 blip·비JSON 응답) 시 재시도.
  //   배경: 크롤 시작이 가격을 NULL 로 하드리셋하므로, 여기서 fetch 가 '딱 한 번' 실패하면
  //   재시도 없이 price=null → 그 소싱처 전 옵션이 통째로 크롤실패(좋은 값 소실). 라이브 실측:
  //   같은 상품 API 가 직후엔 salePrice 정상 반환 → 일시 blip 이었음. 유효 salePrice 받으면
  //   즉시 종료(정상 시 성능 영향 0), 못 받으면 0.6s·1.2s 백오프로 최대 3회. 폴백은 여전히 금지.
  let surface = null, normal = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const gr = await fetch(base, { credentials: "include", headers: { Accept: "application/json" } });
      const gj = await gr.json();
      const gp = ((gj && (gj.data || gj)) || {}).goodsPrice || {};
      const _sp = parseInt(gp.salePrice, 10);
      if (Number.isFinite(_sp) && _sp > 0) {
        surface = _sp;
        normal = parseInt(gp.normalPrice, 10);
        break;   // 유효 표면가 확보 — 재시도 종료
      }
    } catch (e) { /* 일시 실패 — 아래서 재시도 */ }
    if (attempt < 2) await sleep(600 * (attempt + 1));   // 0.6s → 1.2s 백오프
  }

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

  // ★ 2026-07-04 — 무신사 "상품 쿠폰"(등급쿠폰 포함) 전량 수집. 서버가 쿠폰별로
  //   제외키워드 필터+최고금액 선택 판정(쿠폰별 게이트) — 여기선 원본 그대로 다 담아 보낸다.
  //   API 우선(getUsableCouponsByGoodsNo) → 실패/빈값이면 DOM 폴백(적용 중인 쿠폰 1건만이라도).
  //   스키마 미확정(라이브서 응답 바디 확인 못 함) → 필드명 방어적으로 여러 후보 탐색 +
  //   1회 원본 로그(개발자도구 콘솔서 실크롤 시 [moum][coupon-api] raw 로 스키마 확정용).
  async function collectProductCoupons(goodsNo, salePrice) {
    try {
      if (!goodsNo) return null;
      let comId = "", brand = "", specialtyCodes = "";
      try {
        const nd = document.getElementById("__NEXT_DATA__");
        if (nd && nd.textContent) {
          const dig = (obj, keys, depth) => {
            if (!obj || typeof obj !== "object" || depth > 6) return undefined;
            for (const k of Object.keys(obj)) {
              if (keys.indexOf(k) >= 0 && obj[k] != null) return obj[k];
            }
            for (const k of Object.keys(obj)) {
              const v = obj[k];
              if (v && typeof v === "object") {
                const found = dig(v, keys, depth + 1);
                if (found !== undefined) return found;
              }
            }
            return undefined;
          };
          const j = JSON.parse(nd.textContent);
          comId = dig(j, ["comId"], 0) || "";
          specialtyCodes = dig(j, ["specialtyCodes"], 0) || "";
        }
      } catch (e) { /* __NEXT_DATA__ 파싱 실패 — 빈 값으로 진행(API 가 브랜드 없이도 응답할 수 있음) */ }
      brand = comId || "";
      if (Array.isArray(specialtyCodes)) specialtyCodes = specialtyCodes.join(",");

      const qs = new URLSearchParams();
      qs.set("goodsNo", String(goodsNo));
      if (brand) qs.set("brand", brand);
      if (comId) qs.set("comId", comId);
      if (salePrice != null) qs.set("salePrice", String(salePrice));
      if (specialtyCodes) qs.set("specialtyCodes", specialtyCodes);
      const url = "https://api.musinsa.com/api2/coupon/coupons/getUsableCouponsByGoodsNo?" + qs.toString();

      const resp = await fetch(url, { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
      try { console.log("[moum][coupon-api] raw", JSON.stringify(resp).slice(0, 1500)); } catch (_) {}

      // 배열 탐색 — ★ 확정 스키마(라이브 실증 goodsNo 3728480): resp.data.list 우선(쿠폰 6건).
      //   그 뒤 방어적 폴백: resp 자체 → resp.data → data.{coupons|couponList} → data 첫 배열 프로퍼티.
      let arr = null;
      if (resp && resp.data && Array.isArray(resp.data.list)) arr = resp.data.list;
      else if (Array.isArray(resp)) arr = resp;
      else if (resp && Array.isArray(resp.data)) arr = resp.data;
      else if (resp && resp.data && typeof resp.data === "object") {
        const d = resp.data;
        if (Array.isArray(d.coupons)) arr = d.coupons;
        else if (Array.isArray(d.couponList)) arr = d.couponList;
        else {
          for (const k of Object.keys(d)) { if (Array.isArray(d[k])) { arr = d[k]; break; } }
        }
      }
      if (!Array.isArray(arr)) return null;

      const toAmount = (v) => {
        if (v == null) return NaN;
        if (typeof v === "number") return v;
        const n = parseInt(String(v).replace(/[^\d\-]/g, ""), 10);
        return Number.isFinite(n) ? n : NaN;
      };
      const NAME_KEYS = ["couponName", "name", "title", "couponTitle", "benefitName"];
      // ★ 확정: 원화 할인액 = salePrice(실증 salePrice=6390 == DOM "6,390원 할인"). 최우선.
      //   couponValue("5")+couponAmountKind("P"=%)는 '율'이지 원화 아님 → amount 로 쓰지 않음.
      //   maxLimitAmount(할인 상한)도 무시. 나머지는 방어적 폴백.
      const AMT_KEYS = ["salePrice", "discountAmount", "discountPrice", "saleAmount", "benefitAmount", "couponSalePrice", "amount", "discount"];
      const out = [];
      arr.forEach((c) => {
        if (!c || typeof c !== "object") return;
        let name = "";
        for (const k of NAME_KEYS) { if (c[k]) { name = String(c[k]); break; } }
        let amount = NaN;
        for (const k of AMT_KEYS) {
          if (c[k] != null) { const a = toAmount(c[k]); if (Number.isFinite(a) && a > 0) { amount = a; break; } }
        }
        if (name && Number.isFinite(amount) && amount > 0) out.push({ name: name, amount: amount });
      });
      return out;
    } catch (e) {
      return null; // API 실패 — 호출부가 DOM 폴백으로 전환
    }
  }

  // DOM 폴백: PDP 상 '상품 쿠폰{명}쿠폰변경-{금액}원' 적용 라인만이라도 최소 확보(non-interactive).
  function collectProductCouponsFromDom() {
    try {
      const t = (document.body.textContent || "").replace(/\s+/g, " ");
      const m = t.match(/상품\s*쿠폰(.*?)쿠폰변경\s*-\s*([\d,]+)\s*원/);
      if (!m) return [];
      const name = (m[1] || "").trim();
      const amount = parseInt((m[2] || "").replace(/,/g, ""), 10);
      if (!name || !Number.isFinite(amount) || amount <= 0) return [];
      return [{ name: name, amount: amount }];
    } catch (e) {
      return [];
    }
  }

  const _apiCoupons = await collectProductCoupons(id, surface);
  const product_coupon_list = (Array.isArray(_apiCoupons) && _apiCoupons.length ? _apiCoupons : null)
    || collectProductCouponsFromDom() || [];

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
    product_coupon_list: product_coupon_list,   // ★ 2026-07-04 — 상품쿠폰 전량(서버가 쿠폰별 게이트 판정)
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
    if (sale != null && benefit != null) break;   // 둘 다(표면가+혜택가) 잡히면 종료
    if (sale != null && i >= 6) break;             // 표면가만·혜택가 없음(비로그인/무혜택) → 종료
    await sleep(500);
  }
  // [2026-07-03 fix Ⓑ] 표면노출가 = 판매가(sale, 롯데오너스 제외). 기존엔 '나의 혜택가'
  //   (benefit, 롯데오너스 포함)를 저장 → 롯데오너스 이중차감 위험. 표면가 우선, 없으면 benefit 폴백.
  const price = (sale != null) ? sale : benefit;
  const valid = (price != null && price >= MIN);   // 하한 재확인(방어)
  // 롯데오너스(회원할인율) — 크롤가이드 §2 표준 키 lotte_member_discount_rate 로 emit해야
  //   서버(api_benefits compute_breakdown)가 자동 적용. 페이지의 '롯데오너스 … N%' 파싱,
  //   없으면 표면가·혜택가 차이로 산출. 있을 때만 실음(없으면 미반영 — 사용자 정책 2026-07-03).
  let ownusRate = 0;
  {
    const _bt = document.body.innerText;
    const _m = _bt.match(/롯데오너스[^%]{0,20}?(\d+(?:\.\d+)?)\s*%/);
    if (_m) ownusRate = parseFloat(_m[1]) / 100;
    else if (sale != null && benefit != null && benefit < sale) ownusRate = Math.round((sale - benefit) / sale * 1000) / 1000;
  }
  const _lotteBenefit = ownusRate > 0
    ? { lotte_member_discount_rate: ownusRate, lotte_member_discount_label: `롯데오너스 할인 ${(+(ownusRate * 100).toFixed(2))}%` }
    : {};
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
  // ★[2026-07-03 fix B] 재고 소스 = base/sitm 엔드포인트 우선 (전수조사+라이브 결론).
  //   option/mapping 은 크롤 시점(콜드) 부분응답(예 37/97)만 와서 나머지 셀 드롭 → 서버 last_stock
  //   (롯데온 999) 폴백 → '확인필요' 둔갑. 반면 base/sitm/{sitmNo}(페이지 최초 주력 API,
  //   서버 크롤러 LOTTEON_API_PATHS 首)는 optionInfo.optionMappingInfo 에 전 97셀을 담아 온다(라이브 확인).
  //   → base 우선, option/mapping 폴백. 둘 다 no-store 로 폴링해 최다 응답 채택.
  const _sitm = new URLSearchParams(location.search).get("sitmNo") || "";
  const _spd = (location.pathname.match(/\/product\/([A-Za-z0-9]+)/) || [])[1] || "";
  let _mapHit = "";
  for (let i = 0; i < 12; i++) {
    const hit = (performance.getEntriesByType("resource") || [])
      .map((e) => e.name).find((u) => /\/product\/v2\/detail\/option\/mapping\//.test(u));
    if (hit) { _mapHit = hit.split("?")[0]; break; }
    await sleep(300);
  }
  const _stockUrls = [];
  if (_sitm) _stockUrls.push("https://pbf.lotteon.com/product/v2/detail/search/base/sitm/" + _sitm);  // 우선: base
  if (_mapHit) _stockUrls.push(_mapHit);                                                                 // 폴백: 페이지 mapping
  else if (_spd && _sitm) _stockUrls.push("https://pbf.lotteon.com/product/v2/detail/option/mapping/" + _spd + "/" + _sitm);
  if (_stockUrls.length) {
    try {
      // [2026-07-03 fix Ⓒ] pbf 부분응답 방지 — 옵션조합 수가 안정(2회 연속 최대치)될 때까지
      //   재요청 후 '가장 많은 셀' 응답으로 추출. 크롤 시점 부분 pbf → 놓친 셀이 서버서
      //   999(확인필요)로 남던 문제(색상모음전 37/97 셀) 근본 수정.
      // ★롯데온 pbf 콜드-부분응답 대응 (전수조사 결론 2026-07-03) —
      //   크롤 시점 pbf 는 색상모음전 97셀이 '점진적으로' 채워진다(콜드). 매핑에 아직 없는 셀은
      //   아래 색×사이즈 루프서 드롭되고, 서버가 그 셀을 상품 last_stock(롯데온 999)로 폴백해
      //   '확인필요' 둔갑시킨다. pbf 엔 명시적 완성 개수 필드가 없으므로, '옵션조합 수 증가가
      //   멈출 때까지' 인내 폴링한다(콜드 플래토 버스트를 넘도록 넉넉히). cache:no-store 필수.
      //   예산=UNIT_TIMEOUT_MS 60s → 최대 ~17s(24×700ms) 안전(과거 6×450ms 는 콜드 구간 조기종료로
      //   37셀만 수집→60셀 999 회귀 원인). 최대치 응답을 keep, 증가 6회 연속 없으면 완성 간주.
      // base(우선)·mapping 후보를 no-store 폴링, optionMappingInfo 최다 응답 채택(콜드 인내).
      //   base 는 대개 첫 응답에 전 97셀 → 수초 내 종료. 예산 UNIT_TIMEOUT 60s → 최대 ~20s 안전.
      let oi = {}, _best = -1, _flat = 0;
      for (let _i = 0; _i < 20; _i++) {
        let _grew = false;
        for (const _u of _stockUrls) {
          try {
            const resp = await fetch(_u, { credentials: "include", cache: "no-store", headers: { accept: "application/json" } });
            if (resp.ok) {
              const _j = await resp.json();
              const _oi = (_j && _j.data && _j.data.optionInfo) || {};
              const _n = Object.keys(_oi.optionMappingInfo || {}).length;
              if (_n > _best) { _best = _n; oi = _oi; _grew = true; }   // 새 최대 채택
            }
          } catch (e) { /* 다음 후보/재시도 */ }
        }
        _flat = _grew ? 0 : _flat + 1;
        if (_best > 0 && _flat >= 4) break;   // 4회 정체 = 완성(base 완전시 즉시 종료)
        await sleep(500);
      }
      {
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
        //   (spdNo 다름·SALE·stkQty>0)을 끼워넣는다. 그 상품 재고를 이 사이즈 재고로 오인하면
        //   '품절인데 재고있음' 사고. 리스팅 진짜 상품 spdNo 와 다른 SKU → 실제 품절(0).
        // [2026-06-24 fix] 가드 강건화 — 기존엔 _realSpd 를 /product/(LO[0-9]+) 로만 뽑아 'LO' 접두
        //   URL 만 커버했다. 메이트 모음전처럼 'LO' 없는 숫자형 상품(/p/product/2673780784,
        //   sitmNo=2673780784_2673780785)은 _realSpd="" → _isSub 항상 false → 품절 사이즈의 대체상품
        //   재고(예: 265=4개)가 그대로 새어나옴. mapUrl 의 spd 추출과 동일한 범용 패턴([A-Za-z0-9]+)을
        //   쓰고, 'LO' 접두 유무에 안 휘둘리게 숫자만 비교. URL 에서 못 뽑으면 매핑의 최빈 spdNo
        //   (=리스팅 진짜 상품이 다수)로 보정.
        const _digitsOnly = (x) => String(x == null ? "" : x).replace(/\D/g, "");
        let _realSpd = _digitsOnly((location.pathname.match(/\/product\/([A-Za-z0-9]+)/) || [])[1] || "");
        {
          const _spdCount = {};
          for (const _v of Object.values(omi)) {
            const _sp = _digitsOnly(_v && _v.spdNo);
            if (_sp) _spdCount[_sp] = (_spdCount[_sp] || 0) + 1;
          }
          if (!_realSpd || !_spdCount[_realSpd]) {
            const _modal = Object.keys(_spdCount).sort((a, b) => _spdCount[b] - _spdCount[a])[0];
            if (_modal) _realSpd = _modal;
          }
        }
        if (sizeOpts.length) {
          for (const c of colorOpts) {
            for (const s of sizeOpts) {
              const key = (c.value || "") + "_" + (s.value || "");
              const sku = omi[key] || (!c.value ? omi[s.value] : null);
              if (!sku) continue;                          // 미존재 조합 제외(거짓충분 방지)
              const size = (s.label || "").replace(/mm/i, "").trim();
              if (!size) continue;
              const _isSub = _realSpd && sku.spdNo && _digitsOnly(sku.spdNo) !== _realSpd;
              options.push({ color: (c.label || "").trim(), size, price: valid ? price : null, stock: _isSub ? 0 : skuStock(sku), ..._lotteBenefit });
            }
          }
        } else {
          // 옵션 없는 단일상품 — 매핑 1건이면 상품레벨 재고로
          const vals = Object.values(omi);
          if (vals.length === 1) options.push({ color: "", size: "", price: valid ? price : null, stock: skuStock(vals[0]), ..._lotteBenefit });
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
    options = Object.keys(m).map((size) => ({ color: "", size, price: valid ? price : null, stock: m[size], ..._lotteBenefit }));
  }

  // ── [2026-07-23 · T6] pbf 혜택 API 이식 — 최대혜택 적용가 + 카드즉시할인 목록 ──
  //   서버 크롤러(lemouton/sourcing/crawlers/lotteon.py :703-707·:1037-1198·:1201-1238)의
  //   favorBox/benefits(쿠폰별 할인 그룹)·qtyChangeFavorInfoList(최종 적용가) 로직을 페이지 안
  //   fetch 로 이식. 서버판은 Playwright 로 페이지가 부른 응답을 스니핑만 하지만, 확장은 직접
  //   불러야 한다 — 두 API 는 **POST(JSON body)** 이고 body 는 페이지가 base API 응답
  //   (basicInfo·priceInfo·stckInfo·dlvInfo)+상수로 만든다(2026-07-23 Playwright 실측:
  //   base 재구성 body → 원본 캡처 응답과 완전 일치 rc=200, 최소 body 는 rc=422 거부).
  //   여긴 MAIN world(www.lotteon.com origin·로그인 쿠키 포함)라 로그인 한정 카드즉시할인
  //   (ORDER 그룹)이 그대로 보인다. 비로그인이면 favor 에 ORDER 그룹 자체가 안 옴(실측:
  //   aplyBestPrcChkTitle="로그인 하시면 더 정확한 혜택가를 알 수 있어요!") → 카드목록 [].
  //   ★폴백 금지: 값 못 얻으면 null/[] 그대로 — 서버가 기존 베이스로 계산하게 둔다.
  let lotteon_max_price = null, lotteon_card_discounts = null, lotteon_store_discount = null;
  try {
    // ① base 데이터 — 페이지가 실제로 부른 base URL(performance, 쿼리 포함) 우선.
    //    폴백 조립: sitm 형(/base/sitm/{sitmNo}) → pd 형(/base/pd/{spdNo}?isNotContainOptMapping=true, 실측 URL).
    const _baseHit = (performance.getEntriesByType("resource") || [])
      .map((e) => e.name).find((u) => /\/product\/v2\/detail\/search\/base\//.test(u));
    const _baseUrls = [];
    if (_baseHit) _baseUrls.push(_baseHit);
    if (_sitm) _baseUrls.push("https://pbf.lotteon.com/product/v2/detail/search/base/sitm/" + _sitm);
    if (_spd) _baseUrls.push("https://pbf.lotteon.com/product/v2/detail/search/base/pd/" + _spd + "?isNotContainOptMapping=true");
    let _bd = null;
    for (const _u of _baseUrls) {
      try {
        // 8s 개별 타임아웃 — 행 걸린 pbf 호출이 유닛 60s 타임아웃으로 번져
        //   이미 뽑은 price/stock 까지 버리는 것 방지 (AbortSignal.timeout = MAIN world 페이지 컨텍스트 OK).
        const _r = await fetch(_u, { credentials: "include", cache: "no-store", headers: { accept: "application/json" }, signal: AbortSignal.timeout(8000) });
        if (!_r.ok) continue;
        const _j = await _r.json();
        const _d = _j && _j.data;
        if (_d && _d.basicInfo && _d.priceInfo) { _bd = _d; break; }
      } catch (e) { /* 다음 후보 */ }
    }
    if (_bd) {
      // ② POST body 재구성 — 캡처된 페이지 원본 body 와 동일 구성(키 전부, 실측 검증).
      const _bi = _bd.basicInfo || {}, _pi = _bd.priceInfo || {}, _si = _bd.stckInfo || {}, _di = _bd.dlvInfo || {};
      const _n2 = (x) => String(x).padStart(2, "0");
      const _now = new Date();
      const _dttm = "" + _now.getFullYear() + _n2(_now.getMonth() + 1) + _n2(_now.getDate())
        + _n2(_now.getHours()) + _n2(_now.getMinutes()) + _n2(_now.getSeconds());
      const _body = {
        spdNo: _bi.spdNo, sitmNo: _bi.sitmNo,
        trGrpCd: _bi.trGrpCd, trNo: _bi.trNo, lrtrNo: _bi.lrtrNo,
        strCd: _bi.strCd || "", ctrtTypCd: _bi.ctrtTypCd,
        slPrc: _pi.slPrc, slQty: 1,
        scatNo: _bi.scatNo, brdNo: _bi.brdNo,
        sfcoPdMrgnRt: _pi.sfcoPdMrgnRt, sfcoPdLwstMrgnRt: _pi.sfcoPdLwstMrgnRt,
        afflPdMrgnRt: (_pi.afflPdMrgnRt === undefined ? null : _pi.afflPdMrgnRt),
        afflPdLwstMrgnRt: (_pi.afflPdLwstMrgnRt === undefined ? null : _pi.afflPdLwstMrgnRt),
        pcsLwstMrgnRt: _pi.pcsLwstMrgnRt,
        infwMdiaCd: "PC", chCsfCd: "DI", chTypCd: "DI02", chNo: "100195", chDtlNo: "1000617",
        aplyStdDttm: _dttm, cartDvsCd: _di.cartDvsCd,
        thdyPdYn: _bi.thdyPdYn || "N", dvCst: _di.dvCst || 0, fprdDvPdYn: "N",
        discountApplyProductList: [], maxPurQty: _bi.maxPurQty,
        stkMgtYn: _si.stkMgtYn, screenType: "PRODUCT",
        dmstOvsDvDvsCd: _bi.dmstOvsDvDvsCd, dvPdTypCd: _di.dvPdTypCd,
        dvCstStdQty: _di.dvCstStdQty || 0,
        aplyBestPrcChk: "Y", pyMnsExcpLst: [], cpnBoxVersion: "V2",
      };
      const _post = async (u, b) => {
        const _r = await fetch(u, {
          method: "POST", credentials: "include", cache: "no-store",
          headers: { "content-type": "application/json", accept: "application/json" },
          body: JSON.stringify(b),
          signal: AbortSignal.timeout(8000),   // 행 방지 — base fetch 와 동일 8s
        });
        if (!_r.ok) { try { console.log("[moum lotteon pbf ERR]", u.split("/").pop(), "http", _r.status); } catch (_) {} return null; }
        const _j = await _r.json();
        // pbf 는 실패도 HTTP 200 + returnCode 422 로 온다(실측) → returnCode 200 만 신뢰.
        if (!(_j && String(_j.returnCode) === "200" && _j.data)) {
          // 조용한실패 금지 — rc 값을 콘솔에 남긴다(비정상 body·구조 변경 감지 단서).
          try { console.log("[moum lotteon pbf ERR]", u.split("/").pop(), "rc", _j && _j.returnCode); } catch (_) {}
          return null;
        }
        return _j.data;
      };
      const _qd = await _post("https://pbf.lotteon.com/product/v2/extlmsa/promotion/qtyChangeFavorInfoList", _body);
      const _fd = await _post("https://pbf.lotteon.com/product/v2/extlmsa/promotion/favorBox/benefits", { ..._body, mallNo: "1" });

      // ③ 카드즉시할인 목록 + 스토어 즉시할인 — favor.discountGroups[] (lotteon.py :1084-1134 이식)
      //    카드 판정 = lotteon.py is_card_coupon 그대로: 그룹 title=="카드즉시할인/장바구니쿠폰"
      //    OR prKndCd∈{CRD_IMMD,CPN_BSK_CPN} OR prTypCd=="CRD_PR".
      //    (⚠️ dcTnnoCd 기준 아님 — lotteon.py :722-723 에서 4TH=쿠폰(스토어/상품), 5TH=카드즉시할인.
      //     4TH 를 카드로 묶으면 스토어쿠폰이 카드로 오염된다.)
      if (_fd && Array.isArray(_fd.discountGroups)) {
        const _cards = []; const _seen = {};
        let _storeAmt = 0, _sawStore = false;
        for (const _g of _fd.discountGroups) {
          const _gTitle = ((_g && _g.title) || "").trim();
          const _isCardGroup = _gTitle === "카드즉시할인/장바구니쿠폰";
          for (const _pr of (_g && _g.discountApplyPromotionList) || []) {
            const _knd = _pr.prKndCd || "", _typ = _pr.prTypCd || "", _tier = (_pr.dcTnnoCd || "").trim();
            const _amt = parseInt(_pr.dcAmt, 10) || 0;
            // dcRt = 퍼센트 단위(7=7%) — 0~1 분율 아님. T8 엔진 소비 시 /100 필수
            //   (타 필드 lotte_member_discount_rate 는 분율(0.01=1%)이라 혼동 주의).
            const _rate = parseFloat(_pr.dcRt) || 0;
            // 표시명 우선순위 = lotteon.py :1102-1106 (dispTitle → dispName → prNm)
            const _label = ((_pr.dispTitle || "").trim() || (_pr.dispName || "").trim() || (_pr.prNm || "").trim());
            const _isCard = _isCardGroup || _knd === "CRD_IMMD" || _knd === "CPN_BSK_CPN" || _typ === "CRD_PR";
            // dedupe 키 = label+amount+rate — 같은 라벨·다른 금액 프로모션 유실 방지
            //   (label 단독이면 T8 이 최적 카드를 고를 때 과소평가 위험).
            const _dk = _label + "|" + _amt + "|" + _rate;
            if (_isCard && _label && !_seen[_dk]) { _seen[_dk] = 1; _cards.push({ label: _label, amount: _amt, rate: _rate }); }
            // 스토어 즉시할인(정보용) — dcTnnoCd 1ST(스토어 즉시할인, lotteon.py :719)·적용중(prAplyYn=Y)만 합산
            if (_tier === "1ST" && String(_pr.prAplyYn || "").toUpperCase() === "Y") { _storeAmt += _amt; _sawStore = true; }
          }
        }
        lotteon_card_discounts = _cards;           // favor 성공 + 카드 0건(비로그인/무혜택) = [] (정직)
        if (_sawStore) lotteon_store_discount = _storeAmt;
      }
      // ④ 최대혜택 적용가 — qty.orderDcAplyTotAmt.
      //    ⚠️ lotteon.py _parse_lotteon_prices(:1206-1212) 의 max_price=immdDcAplyTotAmt 는
      //    카드즉시할인 **미포함**(즉시할인까지만) — 우리가 원하는 「최대 할인혜택 적용완료」
      //    나의 혜택가(카드 포함)가 아니다. 근거로 고른 필드:
      //      · orderDcAplyTotAmt = ORDER 그룹(카드즉시할인/장바구니쿠폰) 최적 적용 후 총액
      //        (lotteon.py :1207 주석 "orderDcAplyTotAmt (쿠폰까지 적용)" + 필드명 orderDc=ORDER 그룹 할인)
      //      · 요청 body aplyBestPrcChk:"Y" = 최적(최대) 혜택 계산 요청 — 사이트 「최대 할인혜택 적용하기」와 동일 경로
      //      · 비로그인 실측: order==immd(카드 없음) 로 일관 — 로그인 시 카드 반영분만큼 낮아지는 구조.
      //    폴백(2순위): favor.totAmt = totSlPrc − totDcAmt(bestPrAplyYn=Y 합) — 같은 의미의 사이트 계산값.
      //    둘 다 없으면 null(추정·계산 대체 금지). 카드 목록은 별도 유지(엔진이 경로 재구성 — T8).
      if (_qd) {
        const _ord = parseInt(_qd.orderDcAplyTotAmt, 10) || 0;
        if (_ord > 0) lotteon_max_price = _ord;
      }
      if (lotteon_max_price == null && _fd) {
        const _tot = parseInt(_fd.totAmt, 10) || 0;
        if (_tot > 0) lotteon_max_price = _tot;
      }
    }
  } catch (e) {
    // 전체 실패 = null/[] 유지 (폴백 금지 — 서버가 기존 베이스로 계산). 단 조용한실패 금지 — 로그는 남긴다.
    try { console.log("[moum lotteon pbf ERR]", String(e).slice(0, 120)); } catch (_) {}
  }

  return {
    ok: valid,
    price: valid ? price : null,
    stock: valid && !soldOut ? 999 : 0,
    product_name: document.title.split(":")[0].trim().slice(0, 120),
    benefit_price: benefit, sale_price: sale, ..._lotteBenefit,
    // [2026-07-23 · T6] 롯데온 pbf 혜택 — 최대혜택 적용가·카드즉시할인 목록·스토어 즉시할인(정보용)
    lotteon_max_price, lotteon_card_discounts, lotteon_store_discount,
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
// [v0.6.7] hmall·lotteimall 추가 — navGrab→서버 /api/sources/parse 로 추출(SSR/__NEXT_DATA__).
//   이게 없으면 전체크롤 소싱처 목록(ALL)에서 빠져 hmall URL 이 큐에 안 들어감(크롤 누락).
const BG_PARSE_SOURCES = ["lemouton", "ssf", "ssg", "ss_lemouton", "hmall", "lotteimall"];
const BG_JS_SOURCES = ["musinsa", "lotteon"];
// 크롤할 줄 아는 소싱처 전체. 전체크롤 큐 편입 기준이자, S5 단건 크롤(crawl.one)의
// 지원 여부 판정 기준 — 한 곳에서만 관리해 둘이 어긋나지 않게 한다.
const ALL_SOURCE_KEYS = BG_JS_SOURCES.concat(BG_PARSE_SOURCES);

// ── [2026-07-07] 창없는 Fast-lane 프레임워크 (플래그 OFF 기본) ──
//   FAST_FETCH_SOURCES 에 든 소싱처는 crawlItemInTabBG 최상단에서 어댑터(창 없이 직접 fetch)를
//   먼저 시도한다. 성공(status:"ok")이면 그 값을 쓰고, 실패/예외면 그대로 아래 기존 창 경로로
//   폴백한다(★경로 폴백이지 값 폴백 아님 — 가짜값 안 채움). 어댑터는 소싱처별 G1 검증 통과 후
//   Phase 2 에서 FETCH_ADAPTERS 에 등록하고 FAST_FETCH_SOURCES 에 그 소싱처 키를 추가한다.
//   배열이 비어 있는 동안(현재)은 어떤 소싱처도 fetch 경로를 타지 않아 기존 동작과 100% 동일.
// G1/안전 통과분만 ON. 르무통·SSF=색×사이즈 전수 실브라우저 100%일치(2026-07-08). ssg·lotteimall=
//   windowless==기존 서버파서 동일+raw없으면 창 폴백(자가보호)→데이터 악화 불가. 전셀 대조는 크롤-검사 탭.
//   ⚠️보류: musinsa(혜택=로그인DOM 손실)·hmall(색×사이즈 API보강 창필요)·ss_lemouton(per-SKU 로그인API)
//           =어댑터 '성공'반환하나 불완전→폴백안됨→정책확정 후 추가.
const FAST_FETCH_SOURCES = ["lemouton", "ssf", "hmall"];   // [2026-07-09] hmall 추가 — 창없이 raw __NEXT_DATA__ + item-stockcount SW fetch 실측 통과.
// [2026-07-09] SSG·롯데아이몰 = 확장 SW fetch(cross-site)를 WAF가 차단(Sec-Fetch-Site, JS 위조 불가).
//   해법 = 그 도메인 탭 안에서 same-origin fetch(WAF 통과·롯데아이몰 실증) → 렌더 없이 원문 확보.
//   데이터는 SSR 원문(uitemObj/itemInvQtyInfo)에 있고 서버 파서가 읽음 → 창(렌더 DOM)과 값 동일.
//   ★benefit_lines 미사용 소싱처(default navGrab 경로 = 혜택 크롤 안 함)라 창없이로도 손실 없음(무신사·롯데온과 다름).
const SAMEORIGIN_FETCH_SOURCES = ["ssg", "lotteimall"];
const FETCH_ADAPTERS = {};       // sk -> async (item) => crawlItemInTabBG 와 동일 형태 결과

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
// [v0.6.7] 서버 타깃 origin 기반 탭 glob — 로컬 모드(localhost)면 localhost 탭을 서비스/로그 대상으로.
function _baseOrigin() {
  try { return new URL(_mgr.base || "https://mou-m.com").origin; } catch (_) { return "https://mou-m.com"; }
}
function _baseGlobs() {
  const o = _baseOrigin();
  if (/localhost|127\.0\.0\.1/.test(o)) return [o + "/*"];
  return MOUM_TAB_GLOBS;
}
// [2026-07-06 v0.7.17] 실시간 집계(done/total) — 위젯(crawl_log)의 bundleProgress 와 동일식으로
//   모든 모음전 view 를 합산. bgEmit 이 매 이벤트에 실어 보내면 자동화 페이지 링이 위젯과 똑같이 오름.
function _aggProgress() {
  let done = 0, total = 0;
  for (const c in _mgr.view) {
    const b = _mgr.view[c]; total += (b.total || 0);
    const src = b.sources || {}; const keys = Object.keys(src);
    const urlKeys = keys.filter((k) => k.indexOf("|") >= 0);
    const use = urlKeys.length ? urlKeys : keys.filter((k) => k.indexOf("|") < 0);
    let ss = 0; for (const sk of use) ss += (src[sk] && src[sk].done) || 0;
    done += Math.max(ss, b.done || 0);
  }
  return { done: done, total: total };
}
function bgEmit(detail) {
  detail = detail || {};
  if (detail.ts == null) detail.ts = Date.now();
  try { bgUpdateView(detail); } catch (_) {}
  try { detail.agg = _aggProgress(); } catch (_) {}   // 자동화 링용 실시간 집계
  try {
    chrome.tabs.query({ url: _baseGlobs() }, (tabs) => {
      if (chrome.runtime.lastError) return;   // 오류를 안 읽으면 확장 「오류」에 기록됨
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
    case "item-retried": break; // [2026-06-22] 재시도 성공 — s.done 증가 없음(42/40 오버카운트 방지)
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
  try { const t = await chrome.tabs.get(tabId); if (!t || !t.url) return false;
    try { return new URL(t.url).origin === _baseOrigin(); } catch (_) { return false; } }
  catch (_) { return false; }
}
async function _isDiscarded(tabId) {
  try { const t = await chrome.tabs.get(tabId); return !!(t && t.discarded); } catch (_) { return true; }
}
// 선택한 서비스 탭이 크롬에 의해 다시 잠들지(discard) 않게 — 크롤 도중 executeScript 영구 대기 방지.
function _pinTab(tabId) { try { chrome.tabs.update(tabId, { autoDiscardable: false }, () => { void chrome.runtime.lastError; }); } catch (_) {} }
async function ensureServiceTab() {
  if (_serviceTabId != null && await _isMoumTab(_serviceTabId) && !(await _isDiscarded(_serviceTabId))) return _serviceTabId;
  _serviceTabId = null; _serviceTabOwned = false;
  // 이미 열린 mou-m 탭 재사용(사용자 탭이면 닫지 않음).
  // ★ [2026-06-22] discard(잠든) 탭은 executeScript 가 영구 대기 → 크롤 엔진 wedge 원인.
  //   깨어있는(!discarded·complete) 탭을 우선 선택하고, 없으면 하나 깨워서(reload) 사용.
  const tabs = (await chrome.tabs.query({ url: _baseGlobs() })) || [];
  let pick = tabs.find((t) => t && !t.discarded && t.status === "complete") || tabs.find((t) => t && !t.discarded);
  if (!pick && tabs.length) {
    pick = tabs[0];
    try { await chrome.tabs.reload(pick.id); await waitTabComplete(pick.id, 25000); } catch (_) {}
  }
  if (pick && pick.id != null) {
    _serviceTabId = pick.id; _serviceTabOwned = false; _pinTab(pick.id);
    return _serviceTabId;
  }
  // 없으면 백그라운드 탭 1개 생성(비활성) → 서비스 탭
  const base = _mgr.base || "https://mou-m.com";
  const t = await chrome.tabs.create({ url: base + "/", active: false });
  if (!t || t.id == null) throw new Error("서비스 탭 생성 실패");
  _pinTab(t.id);
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
      // ★ [2026-06-22] executeScript 하드 타임아웃 — 서비스 탭이 잠들었거나(discard) 주입이
      //   never-resolve 하면 bgFetch 가 영구 대기 → 백그라운드 엔진 전체가 wedge(목표 0 에서 멈춤,
      //   중지 버튼도 무력)되던 버그. 타임아웃 시 서비스 탭을 버리고 1회 재선택·재시도.
      const res = await withTimeout(chrome.scripting.executeScript({
        target: { tabId: tabId }, world: "ISOLATED", func: _injectedFetch, args: [path, opts || null],
      }), BGFETCH_TIMEOUT_MS);
      if (res && (res.__timeout || res.__error)) {
        _serviceTabId = null;   // 잠든·먹통 탭 폐기 → 재시도 시 깨어있는 탭 재선택
        if (attempt === 1) return { ok: false, status: 0, json: () => Promise.resolve(null), _err: res.__timeout ? "bgFetch 타임아웃(서비스 탭 응답 없음)" : res.__error };
        continue;
      }
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
  // [2026-07-06] priority=true (모음전 상세에서 직접 「전체크롤」) → 큐 맨 앞에 삽입해 다음 순번.
  //   자동 폴링(due-bundles)은 priority 없이 큐 뒤에 붙는다(오래된 순 유지).
  const prio = !!payload.priority;
  const fresh = [];
  for (const c of codes) {
    if (!c || c === _mgr.running || _mgr.queue.indexOf(c) >= 0) continue;
    fresh.push(c);
  }
  if (prio) _mgr.queue.unshift(...fresh);   // 앞에 삽입(순서 유지)
  else      _mgr.queue.push(...fresh);      // 뒤에 붙임
  bgEmitQueue();
  if (!_mgr.running) runQueueBG();
  return { ok: true, queued: fresh.length, position: prio ? 1 : _mgr.queue.length };
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
  let crawled = 0;
  try {
    while (_mgr.queue.length) {
      if (_mgr.stopped) break;
      const code = _mgr.queue.shift();
      _mgr.running = code; _mgr.paused = false;
      bgEmitQueue();
      try { await crawlBundleAllBG(code); crawled++; } catch (e) { console.warn("[moum] bundle err", code, e); }
      if (_mgr.stopped) break;
    }
  } finally {
    const wasStopped = _mgr.stopped;
    _mgr.queue = []; _mgr.running = null; _mgr.paused = false; _mgr.stopped = false; _mgr._kick = null;
    bgEmitQueue();
    bgKeepaliveStop();
    try { bgClearPersist(); } catch (_) {}   // 크롤 종료 — 체크포인트 제거(불필요 재가동 방지)
    // [2026-07-06 v0.7.17] 한 패스(전체 URL 1회) 완료 → 서버에 통보(오늘 바퀴 +1).
    //   중지·미크롤이면 안 보냄. 서비스탭 닫기 전에(bgFetch 가 탭 필요).
    if (crawled > 0 && !wasStopped) {
      try { await bgFetch("/api/crawl/pass-done", { method: "POST" }); } catch (_) {}
    }
    await closeServiceTabIfOwned();   // SW 가 띄운 백그라운드 mou-m 탭 정리
  }
}

// ── [2026-07-04] 자동화 워커: 서버 /api/crawl/due-bundles 폴링 → 기존 크롤 큐로 위임 ──
//   검증된 크롤 로직(crawlBundleAllBG·동시성·재시도·로그인세션)을 그대로 재사용한다.
//   서버 enabled 게이트가 이중 안전 — 실행/정지 끄면 빈 목록이 와서 아무것도 안 함.
// [2026-07-05 v0.7.15] MV3 서비스워커는 ~30초 유휴 시 언로드돼 setInterval 이 죽는다
//   → 자동 폴링이 한 번 돌고 멈추던 근본원인(라이브 실증). chrome.alarms 로 전환(잠들어도
//   Chrome 이 SW 를 깨워 폴). moum-keepalive 와 동일한 검증된 방식. (알람 최소주기 1분)
const MOUM_POLL_ALARM = "moum-auto-poll";
async function moumAutoPollOnce() {
  try {
    const r = await bgFetch("/api/crawl/due-bundles").then((x) => x.json());
    if (r && r.enabled && Array.isArray(r.codes) && r.codes.length) {
      mgrEnqueue({ codes: r.codes, base: _mgr.base });   // 기존 큐/동시성/재시도 재사용
    }
  } catch (e) { console.warn("[moum-auto-poll]", e && e.message ? e.message : e); }
}
function moumAutoPollStart() {
  moumAutoPollOnce();   // 즉시 1회
  try { chrome.alarms.create(MOUM_POLL_ALARM, { periodInMinutes: 1 }); } catch (_) {}
}
function moumAutoPollStop() {
  try { chrome.alarms.clear(MOUM_POLL_ALARM); } catch (_) {}
}
// 알람 발화 → 폴 1회 (SW 가 잠들었다 깨어난 경우에도 실행)
try {
  chrome.alarms.onAlarm.addListener((a) => { if (a && a.name === MOUM_POLL_ALARM) moumAutoPollOnce(); });
} catch (_) {}

// ══════════════════════════════════════════════════════════════════════════
//  [2026-07-17] 정산 「자동 반복」을 확장으로 이관 — 탭을 닫아도 돈다
//   예전엔 스케줄·순회가 전부 크롤-로그인 페이지 안에 있어 그 탭을 닫으면 멈췄다. 여기로
//   옮기면 자동화(소싱처) 폴링과 같은 구조가 된다 — chrome.alarms 가 SW 를 깨우고, 서버
//   호출이 필요하면 bgFetch 가 mou-m 탭을 재사용하거나 없으면 임시로 하나 띄웠다 닫는다.
//   ★크롤=로컬 원칙 유지(서버 크롤 아님 — 이 PC 브라우저 세션으로 수집).
//   ★스케줄 진실 원천은 여기 한 곳. 페이지는 토글·표시만 하고 자기 타이머를 안 돌린다
//    (둘 다 돌면 같은 회차가 두 번 = 중복 크롤).
//   ★설정은 storage.local — 크롬을 껐다 켜도 남는다. (크롤 체크포인트가 쓰는 storage.session
//    과 다르다. 저건 '중단된 크롤 이어하기'라 재부팅 후 재개가 오히려 위험해서 세션 한정.)
// ══════════════════════════════════════════════════════════════════════════
const MOUM_SETTLE_ALARM = "moum-settle-auto";
const _SETTLE_KEY = "moum_settle_auto";
const _SETTLE_DEFAULT = { on: false, min: 60, nextAt: 0, base: "", last: null };
let _settleRunning = false;

function settleLoad() {
  return new Promise((res) => {
    try {
      chrome.storage.local.get(_SETTLE_KEY, (o) => {
        void chrome.runtime.lastError;
        res(Object.assign({}, _SETTLE_DEFAULT, (o && o[_SETTLE_KEY]) || {}));
      });
    } catch (_) { res(Object.assign({}, _SETTLE_DEFAULT)); }
  });
}
function settleSave(st) {
  return new Promise((res) => {
    try { chrome.storage.local.set({ [_SETTLE_KEY]: st }, () => { void chrome.runtime.lastError; res(); }); }
    catch (_) { res(); }
  });
}
// 한 회차 = 저장된 계정 전체를 하나씩(직렬) 로그아웃→로그인→정산수집→서버반영.
//   ★직렬 필수 — 확장은 롯데온 전용 탭 하나를 재사용한다(동시 실행 시 서로 페이지를 갈아엎음).
async function settleRunOnce(st) {
  if (_settleRunning) return { busy: true };
  _settleRunning = true;
  const sum = { ok: 0, verify: 0, fail: 0, orders: 0, error: "" };
  try {
    if (st.base) _mgr.base = st.base;   // 어느 서버(라이브/로컬)에 반영할지 — 켤 때 잡아둔 origin
    const lr = await bgFetch("/accounts/api/crawl-login/accounts").then((x) => x.json()).catch(() => null);
    // ★정직 — 목록을 못 받으면(mou-m 미로그인·서버 무응답) '0계정 성공'이 아니라 오류로 남긴다.
    if (!lr || !lr.ok || !Array.isArray(lr.accounts)) {
      sum.error = "계정 목록을 못 받음 — mou-m 로그인이 풀렸거나 서버 응답 없음";
      return sum;
    }
    const accounts = lr.accounts.filter((a) => a && a.saved);
    if (!accounts.length) { sum.error = "저장된 로그인이 있는 계정이 없음"; return sum; }
    for (const a of accounts) {
      try {
        const creds = await bgFetch("/accounts/api/crawl-login/" + encodeURIComponent(a.env_prefix) + "/creds",
          { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
          .then((x) => x.json()).catch(() => null);
        if (!creds || !creds.ok) { sum.fail++; continue; }
        const r = await handleLotteonAccountCollect({ login_id: creds.login_id, password: creds.password });
        if (r && r.needs_verify) { sum.verify++; continue; }   // SMS 2단계 — 무인으론 못 넘김(정직히 셈)
        if (!(r && r.ok && r.rows)) { sum.fail++; continue; }
        await bgFetch("/api/margin/lotteon-settlement",
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r.rows) })
          .then((x) => x.json()).catch(() => null);
        sum.ok++; sum.orders += (r.collected || 0);
      } catch (_) { sum.fail++; }
    }
    try { if (_loTabId != null) { await chrome.tabs.remove(_loTabId); _loTabId = null; } } catch (_) {}
    await closeServiceTabIfOwned();   // 우리가 띄운 임시 mou-m 탭 정리(사용자 탭이면 안 닫음)
    return sum;
  } finally { _settleRunning = false; }
}
// 회차 실행 + 다음 마감 기록(성공·실패 무관하게 다음을 잡아야 멈추지 않는다).
async function settleRunAndArm(st) {
  const min = parseInt(st.min || 60, 10) || 60;
  const sum = await settleRunOnce(st);
  if (sum && sum.busy) return;
  const done = await settleLoad();
  await settleSave(Object.assign({}, done, {
    nextAt: Date.now() + min * 60000,   // 끝난 시점 기준으로 다시
    last: { at: Date.now(), ok: sum.ok, verify: sum.verify, fail: sum.fail, orders: sum.orders, error: sum.error || "" },
  }));
}
// 알람 1회 — '마감 지났나'만 본다(자동화 폴링과 동일 사고방식).
async function settleTick() {
  const st = await settleLoad();
  if (!st.on) { try { chrome.alarms.clear(MOUM_SETTLE_ALARM); } catch (_) {} return; }
  if (_settleRunning) return;
  if (st.nextAt && Date.now() < st.nextAt) return;
  // ★먼저 다음 마감을 밀어두고 돈다 — 도는 도중 알람이 또 떠도 재발사되지 않게(중복 크롤 방지).
  const min = parseInt(st.min || 60, 10) || 60;
  await settleSave(Object.assign({}, st, { nextAt: Date.now() + min * 60000 }));
  await settleRunAndArm(st);
}
async function settleAutoSet(on, min, base) {
  const st = await settleLoad();
  if (!on) {
    await settleSave(Object.assign({}, st, { on: false, nextAt: 0 }));
    try { chrome.alarms.clear(MOUM_SETTLE_ALARM); } catch (_) {}
    return;
  }
  const m = parseInt(min || st.min || 60, 10) || 60;
  await settleSave(Object.assign({}, st, { on: true, min: m, base: base || st.base || "", nextAt: Date.now() + m * 60000 }));
  try { chrome.alarms.create(MOUM_SETTLE_ALARM, { periodInMinutes: 1 }); } catch (_) {}
  const fresh = await settleLoad();
  settleRunAndArm(fresh);   // 켠 순간 즉시 1회(마감을 기다리지 않는 게 기대 동작)
}
try {
  chrome.alarms.onAlarm.addListener((a) => { if (a && a.name === MOUM_SETTLE_ALARM) settleTick(); });
} catch (_) {}
// SW 가 (재)기동될 때 — 켜져 있으면 알람을 되살린다(크롬 재시작 후에도 이어서 돌게).
try {
  settleLoad().then((st) => {
    if (st && st.on) { try { chrome.alarms.create(MOUM_SETTLE_ALARM, { periodInMinutes: 1 }); } catch (_) {} }
  });
} catch (_) {}

// ── [2026-07-17] 정산 「자동 반복」 탭 지킴이 — 크롤-로그인 탭이 재워지지 않게 ──
//   ※이제 스케줄은 확장이 갖지만(위), 구버전 확장으로 폴백한 페이지도 있을 수 있어 유지한다.
//   서버 호출(자격증명·정산 push)에 mou-m 로그인
//   쿠키가 필요한데 SW 직접 fetch 엔 안 실리기 때문(위 _serviceTabId 주석과 같은 이유).
//   그런데 페이지는 크롬 메모리 세이버가 탭을 재우면(discard) 통째로 사라져 마감 확인조차
//   못 한다 → 자동 반복이 조용히 멈춘다. 여기서는 딱 두 가지만 한다.
//     ① 크롤-로그인 탭에 autoDiscardable=false (재우기 금지)
//     ② 1분 알람으로 확인 — 이미 재워졌으면 되살린다(reload). 되살아난 페이지는 저장된
//        마감(localStorage)을 읽어 지났으면 즉시 따라잡는다.
//   ★회차 계산은 절대 여기서 하지 않는다 — 페이지와 이중화되면 두 스케줄이 어긋난다(모순).
const MOUM_SETTLE_AWAKE_ALARM = "moum-settle-keepawake";
async function settleTabs() {
  try { return (await chrome.tabs.query({ url: _baseGlobs() })) || []; } catch (_) { return []; }
}
async function settleKeepAwakeOnce() {
  const tabs = await settleTabs();
  const targets = tabs.filter((t) => t && t.url && t.url.indexOf("/accounts/crawl-login") >= 0);
  if (!targets.length) { settleKeepAwakeStop(); return; }   // 탭을 닫았으면 지킴이도 끝
  for (const t of targets) {
    _pinTab(t.id);                                    // 재우기 금지(크롤 서비스탭과 동일 수법)
    if (t.discarded) { try { await chrome.tabs.reload(t.id); } catch (_) {} }   // 이미 재워졌으면 되살림
  }
}
function settleKeepAwakeStart() {
  settleKeepAwakeOnce();
  try { chrome.alarms.create(MOUM_SETTLE_AWAKE_ALARM, { periodInMinutes: 1 }); } catch (_) {}
}
function settleKeepAwakeStop() {
  try { chrome.alarms.clear(MOUM_SETTLE_AWAKE_ALARM); } catch (_) {}
  // 고정 해제 — 자동 반복을 껐으면 크롬이 알아서 메모리를 회수하게 돌려놓는다.
  settleTabs().then((tabs) => tabs.forEach((t) => {
    if (t && t.url && t.url.indexOf("/accounts/crawl-login") >= 0) {
      try { chrome.tabs.update(t.id, { autoDiscardable: true }, () => { void chrome.runtime.lastError; }); } catch (_) {}
    }
  }));
}
try {
  chrome.alarms.onAlarm.addListener((a) => { if (a && a.name === MOUM_SETTLE_AWAKE_ALARM) settleKeepAwakeOnce(); });
} catch (_) {}

// ── [2026-06-29] 현대H몰 색상/모델모음전 사이즈별 실수량 보강 ──
//   2축(색×사이즈) 모음전 상품은 페이지 HTML(__NEXT_DATA__)에 1축(색)만 옴 → 색별 합계만.
//   사이즈별 실수량은 item-stockcount API(색 번호 uitmSeq별)로만 온다. www→api 는 CORS,
//   서버직접은 404(인증) → 확장(host권한+쿠키 first-party)만 호출 가능. 색별로 호출해
//   per-(색,사이즈) 옵션을 만들어 반환(없으면 null → 서버 parse 의 색-레벨 폴백 유지).
//   참고: reference_hmall_stockcount_api
//   [2026-06-29 v3] item-stockcount 는 www.hmall.com(= navGrab 페이지와 동일 출처)에 있다.
//   SW 컨텍스트 fetch 는 빈 응답(WAF 봇판정/컨텍스트 추정) → navGrab 한 그 탭의 '페이지
//   컨텍스트(MAIN world)'에서 same-origin 상대경로 fetch 로 호출(=SPA 와 동일, 확실). 색
//   번호(uitmSeq) 1..15 순회, 빈 응답이면 색 소진. 2축(uitm2AttrNm) 없으면 단품 → null.

// [2026-07-02] 색상모음전 per-size 옵션 색별 가격 이식. item-stockcount 는 재고만 주고
//   가격=0(sellPrc=0) 이라, 그대로 두면 확장이 'price>0 옵션 0개' → price=null →
//   status=error("옵션 가격 없음") → 크롤 위젯에 거짓 '크롤실패'가 뜬다(서버
//   save_crawl_result 는 fetch_combo_persize_options 로 이미 정상 저장 → 데이터는 옳고
//   위젯만 거짓). 색-레벨 parse 옵션(각 색 표면가 보유)에서 색별 가격을 per-size 에
//   옮겨 붙여 확장 판정을 정직하게 만든다. 서버 build_combo_persize_options 의 color_price
//   병합과 대칭. ⚠️ 이식할 가격이 전무하면 원본 유지(폴백가 날조 금지). 회귀:
//   scripts/test_hmall_combo_price_graft.js
function graftComboColorPrices(parseOptions, perSizeOptions) {
  if (!Array.isArray(perSizeOptions) || !perSizeOptions.length) return perSizeOptions;
  const hasPrice = (o) => o && typeof o.price === "number" && o.price > 0;
  if (perSizeOptions.every(hasPrice)) return perSizeOptions;
  const colorPrice = {};
  let anyPrice = null;
  for (const o of (parseOptions || [])) {
    if (hasPrice(o)) {
      const c = (o.color_text || "").trim();
      if (c && !(c in colorPrice)) colorPrice[c] = o.price;
      if (anyPrice == null) anyPrice = o.price;
    }
  }
  if (anyPrice == null) return perSizeOptions;
  for (const o of perSizeOptions) {
    if (!hasPrice(o)) {
      const c = (o.color_text || "").trim();
      const pr = (c && colorPrice[c] != null) ? colorPrice[c] : anyPrice;
      o.price = pr; o.sale_price = pr;
    }
  }
  return perSizeOptions;
}

async function hmallPerSizeOptions(tabId, url) {
  try {
    const um = String(url || "").match(/slitmCd=(\d+)/);
    if (!um) return { ok: false, why: "no-slitmCd", options: null };
    const slitmCd = um[1];
    let res;
    try {
      res = await chrome.scripting.executeScript({
        // [2026-06-29 v4] world:'MAIN' 은 async 함수 Promise 반환을 await 안 함(크롬 제약)
        //   → 결과 undefined 였음. 기본(ISOLATED) world 는 await 됨. same-origin fetch 동일 동작.
        target: { tabId: tabId }, args: [slitmCd],
        func: async (slitmCd) => {
          const out = [];
          let calls = 0, why = "";
          for (let seq = 1; seq <= 15; seq++) {
            const qs = new URLSearchParams({
              slitmCd: slitmCd, setItemYn: "N", uitmCombYn: "Y", uitmAttrTypeSeq: "2",
              selectBoxIdx: "1", uitmSeq: String(seq), rishpNotfExpsYn: "Y",
              befUitmSeq1: "0", befUitmSeq2: "0", befUitmSeq3: "0", setSlitmCd: slitmCd, setSlitmYn: "N",
            });
            let list = [];
            try {
              const r = await fetch("/api/hf/dp/v1/item-ptc/item-stockcount?" + qs.toString(), { credentials: "include" });
              const j = await r.json();
              list = (j && j.respData && j.respData.stockList) || [];
              calls++;
            } catch (e) { why = "fetch-fail@" + seq; break; }
            if (!list.length) { why = "empty@" + seq; break; }
            if (!list.some((it) => it.uitm2AttrNm)) return { dan: true };
            list.forEach((it) => {
              const c = it.uitm1AttrNm || "", s = it.uitm2AttrNm || "";
              if (c && s) out.push({
                color_text: c, size_text: s,
                // [2026-06-29 S19] 품절 판정 = sellGbcd("00"=판매 / 그 외 예:"11"=품절).
                //   stockCount 아님 — 품절 사이즈도 stockCount=1 로 옴(다크네이비 260/265/275mm).
                //   sellGbcd 없으면 stockCount 폴백(거짓 품절 방지).
                stock: (it.sellGbcd && String(it.sellGbcd) !== "00")
                  ? 0
                  : (typeof it.stockCount === "number" ? it.stockCount : null),
                price: (typeof it.sellPrc === "number" ? it.sellPrc : null),
              });
            });
          }
          return { options: out, calls: calls, why: why };
        },
      });
    } catch (e) { return { ok: false, why: "exec-fail:" + String(e && e.message ? e.message : e).slice(0, 30), options: null }; }
    const r = res && res[0] && res[0].result;
    if (!r) return { ok: false, why: "no-result", options: null };
    if (r.dan) return { ok: false, why: "단품(no-2nd-axis)", options: null };
    const opts = r.options || [];
    return { ok: opts.length > 0, why: opts.length ? ("ok " + opts.length + "옵션/" + r.calls + "색") : ("none " + (r.why || "")), options: opts.length ? opts : null };
  } catch (e) { return { ok: false, why: "exc:" + String(e && e.message ? e.message : e).slice(0, 40), options: null }; }
}

// ── 1건 처리(창 재사용) — 백그라운드 내부 핸들러 직접 호출(메시지 왕복 없음) ──
//   opts.fetchOnly=true → fetch 경로(SW/same-origin)만 시도하고, 실패해도 창(navGrab/렌더)
//   폴백을 안 탄다. winless 동시 레인이 공유 도메인탭을 렌더로 뺏어 오파싱하는 것을 차단(§4 무결성).
async function crawlItemInTabBG(tabId, code, item, opts) {
  const sk = item.source_key, url = item.url;
  // [2026-07-07] 창없는 fast-lane — 플래그 ON + 어댑터 등록된 소싱처만. 성공 시 즉시 반환,
  //   실패/예외면 아래 기존 창 경로로 폴백(경로 폴백). 플래그 비면 이 블록은 건너뜀(동작 불변).
  if (FAST_FETCH_SOURCES.indexOf(sk) >= 0 && typeof FETCH_ADAPTERS[sk] === "function") {
    try {
      const _fx = await FETCH_ADAPTERS[sk](item);
      if (_fx && _fx.status === "ok") return _fx;
    } catch (_e) { /* 창 경로로 폴백 */ }
  }
  // [2026-07-09] SSG·롯데아이몰 — 도메인 탭에서 same-origin fetch(렌더 없이 원문). WAF 통과 경로.
  //   탭이 이미 그 도메인이면 바로 fetch(빠름), 아니면 도메인 루트로 1회 이동해 origin 확보.
  //   원문·서버파서로 price/stock 산출 == 창 경로와 동일. 어떤 실패든 아래 navGrab 창 경로로 폴백(안전).
  if (SAMEORIGIN_FETCH_SOURCES.indexOf(sk) >= 0) {
    try {
      const origin = new URL(url).origin;
      let onOrigin = false;
      try { const cur = await chrome.tabs.get(tabId); onOrigin = !!(cur && cur.url && new URL(cur.url).origin === origin); } catch (_) {}
      if (!onOrigin) {
        try {
          await chrome.tabs.update(tabId, { url: origin + "/" });
          await waitTabComplete(tabId, 20000);
          const c2 = await chrome.tabs.get(tabId);
          onOrigin = !!(c2 && c2.url && new URL(c2.url).origin === origin);
        } catch (_) {}
      }
      if (onOrigin) {
        const out = await chrome.scripting.executeScript({
          target: { tabId: tabId }, world: "ISOLATED", args: [url],
          func: async (u) => {
            try {
              const r = await fetch(u, { credentials: "include" });
              if (!r.ok) return { err: "http " + r.status };
              const t = await r.text();
              return (t && t.length > 3000) ? { html: t } : { err: "short " + (t ? t.length : 0) };
            } catch (e) { return { err: "ex" }; }
          },
        });
        const res = out && out[0] && out[0].result;
        if (res && res.html) {
          let pp = null;
          try {
            pp = await bgFetch("/api/sources/parse", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ source_key: sk, url: url, html: res.html }),
            }).then((x) => x.json());
          } catch (_) { pp = null; }
          if (pp && pp.ok) {
            const o2 = Array.isArray(pp.options) ? pp.options : [];
            const pr = o2.filter((o) => o && typeof o.price === "number" && o.price > 0);
            const bu = pr.filter((o) => (o.stock == null) || o.stock > 0);
            const pl = bu.length ? bu : pr;
            let price = null; if (pl.length) price = pl.reduce((m, o) => (o.price < m ? o.price : m), pl[0].price);
            let st = null; const ssx = o2.filter((o) => o && typeof o.stock === "number"); if (ssx.length) st = ssx.reduce((a, o) => a + Math.max(0, o.stock), 0);
            if (price != null) return {
              url: url, source_key: sk, price: price, stock: st,
              // [2026-07-10] price 동봉 — 가격 변동 감지용(서버가 price 로 비교)
              options: o2.map((o) => ({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price })),
              status: "ok", product_name: pp.product_name_raw || null, error: null,
            };
          }
        }
      }
    } catch (_) { /* navGrab 창 경로로 폴백 */ }
  }
  // [2026-07-14] winless 동시 레인 모드 — fetch 실패 시 창(navGrab/렌더) 폴백을 생략하고
  //   정직하게 error 반환(공유 도메인탭 렌더 경쟁 원천 차단). 상위에서 1회 재시도(재-fetch)함.
  if (opts && opts.fetchOnly) {
    return { url: url, source_key: sk, status: "error", error: "fetch 실패(창 폴백 생략)" };
  }
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
      product_coupon_list: x.product_coupon_list || [],   // ★ 2026-07-04 무신사 상품쿠폰 전량(서버 쿠폰별 게이트)
      // [2026-07-23 · T6] 롯데온 pbf 혜택 3종 — 없으면 null(폴백 금지, 서버가 기존 베이스로 계산)
      lotteon_max_price: (x.lotteon_max_price === undefined ? null : x.lotteon_max_price),
      lotteon_card_discounts: (x.lotteon_card_discounts === undefined ? null : x.lotteon_card_discounts),
      lotteon_store_discount: (x.lotteon_store_discount === undefined ? null : x.lotteon_store_discount),
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
  let opts2 = Array.isArray(p.options) ? p.options : [];
  // [2026-06-29] 현대H몰 모음전(2축): 색별 item-stockcount API 로 사이즈별 실수량 보강.
  //   성공 시 색-레벨 옵션을 per-(색,사이즈) 옵션으로 교체 → 저장·매칭이 사이즈별 3상태 표시.
  if (sk === "hmall") {
    try {
      const ps = await hmallPerSizeOptions(tabId, url);
      try { console.log("[moum hmall 사이즈API]", url, ps && ps.why); } catch (_) {}
      // per-size 옵션(item-stockcount)은 가격 0 → 색-레벨 parse 옵션에서 색별 가격 이식
      //   (안 하면 거짓 '크롤실패'가 위젯에 뜬다. [2026-07-02])
      if (ps && ps.options && ps.options.length) opts2 = graftComboColorPrices(p.options, ps.options);
    } catch (e) { try { console.log("[moum hmall 사이즈API ERR]", e); } catch (_) {} }
  }
  const priced = opts2.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  let stock = null;
  const stocks = opts2.filter((o) => o && typeof o.stock === "number");
  if (stocks.length) stock = stocks.reduce((sum, o) => sum + Math.max(0, o.stock), 0);
  const ok = price != null;
  // [2026-06-22 진단] 스스 재고 all-999 원인 표면화 — sku_diag(확장 네이버 SKU 수집 결과)
  //   + 서버가 실수량(999 아님)을 몇 개 매핑했나. err:* → 수집실패 / ok:N + 실수량0 → 키불일치.
  const _realN = opts2.filter((o) => typeof o.stock === "number" && o.stock !== 999).length;
  return {
    url: url, source_key: sk, price: price, stock: stock,
    // [2026-07-10] price 동봉 — 서버 persist_crawled_options 는 price 를 받을 걸로 설계됐는데
    //   확장이 안 보내서 '가격 변동'이 영원히 0건이었다(회차 보고서 30회차 실측). 파서 옵션엔 price 있음.
    options: opts2.map((o) => ({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price })),
    status: ok ? "ok" : "error", product_name: p.product_name_raw || null,
    error: ok ? null : "옵션 가격 없음",
    sku_diag: grab.sku_diag || null,
    stock_real_n: _realN, stock_total_n: opts2.length,
  };
}

// ── [2026-06-18] 저장 헬퍼 — 결과 item 매핑 + crawl-result 저장(소싱처별 증분/최종 공용) ──
//   ★ 버그 수정: 기존엔 모든 소싱처 크롤이 끝난 뒤 '최종 1회'만 bgFetch 저장했는데,
//   그 마지막 저장이 조용히 0건 실패(창 다 닫힌 뒤 서비스탭 fetch 불안정)하면 수집한
//   가격이 전부 버려지고(하드리셋만 남아) 전 옵션이 판매차단됐다. 대책=소싱처가 끝날
//   때마다 그 소싱처 결과를 즉시 저장(크롤 도중 = bgFetch 정상 동작 구간) + 저장결과를
//   로그에 표면화(조용한 실패 제거). 최종 일괄 저장은 백스톱으로 유지(중복 저장은 무해).
// ══════════════════════════════════════════════════════════════════
//  [2026-07-07] 창없는 Fast-lane 어댑터 (Phase 2) — 전부 플래그 OFF(FAST_FETCH_SOURCES=[])
//   등록만 해두고, 소싱처별 G1(실브라우저 값 100% 대조) 통과 후에만 FAST_FETCH_SOURCES 에 추가.
// ══════════════════════════════════════════════════════════════════

// 공통 — BG_PARSE 소싱처(내장JSON/HTML): 창 없이 raw HTML fetch → 기존 서버 파서 재사용.
//   창 크롤(navGrab)과 유일한 차이 = "페이지를 열어 렌더 HTML" 대신 "raw HTML 직접 fetch".
//   데이터가 raw HTML(SSR/내장JSON)에 있으면 동일 결과. WAF/렌더로 비면 status!=ok → 창 폴백.
//   ⚠️ 혜택이 로그인 DOM 인 소싱처(현대H몰·SSF 일부)는 이 경로가 재고·표면가만 → 혜택은 창 필요(켤 때 G1 확인).
async function fetchRawParseAdapter(item) {
  const sk = item.source_key, url = item.url;
  // [2026-07-08] 봇차단(403)·과부하(429)·서버오류(5xx)·빈응답 대비 재시도(backoff).
  //   3회까지 재시도(0.4s·0.8s 대기). 그래도 실패하면 status:error 반환 → 상위 crawlItemInTabBG
  //   가 자동으로 '창 경로(navGrab)'로 폴백(렌더로 더 강하게 뚫음). 창도 실패하면 '확인불가'(거짓 금지).
  let html = null, lastErr = "";
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt) await new Promise((res) => setTimeout(res, 400 * attempt));
    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) {
        lastErr = "http " + r.status;
        if (r.status === 403 || r.status === 429 || r.status >= 500) continue; // 차단·과부하·서버오류=재시도
        break; // 그 외 4xx=재시도 무의미
      }
      const t = await r.text();
      if (!t || t.length < 500) { lastErr = "빈 HTML(" + (t ? t.length : 0) + ")"; continue; }
      html = t; break;
    } catch (e) { lastErr = "fetch 예외"; continue; }
  }
  if (!html) return { url: url, source_key: sk, status: "error", error: "SW fetch 실패(재시도3): " + lastErr };
  let p;
  try {
    p = await bgFetch("/api/sources/parse", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_key: sk, url: url, html: html }),
    }).then((x) => x.json());
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "parse 호출 실패" }; }
  if (!p || !p.ok) return { url: url, source_key: sk, status: "error", error: (p && (p.message || p.error)) || "parse 실패" };
  const opts2 = Array.isArray(p.options) ? p.options : [];
  const priced = opts2.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  let stock = null;
  const stocks = opts2.filter((o) => o && typeof o.stock === "number");
  if (stocks.length) stock = stocks.reduce((s, o) => s + Math.max(0, o.stock), 0);
  const ok = price != null;
  return {
    url: url, source_key: sk, price: price, stock: stock,
    // [2026-07-10] price 동봉 — 서버 persist_crawled_options 는 price 를 받을 걸로 설계됐는데
    //   확장이 안 보내서 '가격 변동'이 영원히 0건이었다(회차 보고서 30회차 실측). 파서 옵션엔 price 있음.
    options: opts2.map((o) => ({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price })),
    status: ok ? "ok" : "error", product_name: p.product_name_raw || null,
    error: ok ? null : "옵션 가격 없음",
  };
}

// 무신사 — 창 없이 재고 API(prioritized-inventories) + 표면가 API(goodsPrice.salePrice).
//   ⚠️ 회원 혜택은 로그인 DOM 이라 이 경로엔 없음 → 무신사 fast-lane 은 재고·표면가 갱신용.
//   혜택까지 필요한 전체크롤은 창 경로 유지(켤 때 정책 확정).
async function fetchMusinsaAdapter(item) {
  const url = item.url, sk = "musinsa";
  const id = (url.match(/products\/(\d+)/) || [])[1];
  if (!id) return { url: url, source_key: sk, status: "error", error: "product id 없음" };
  const base = "https://goods-detail.musinsa.com/api2/goods/" + id;
  try {
    const oj = await fetch(base + "/options", { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
    const basic = (oj.data || {}).basic || [];
    const its = (oj.data || {}).optionItems || [];
    const valueNos = [];
    basic.forEach((g) => (g.optionValues || g.values || []).forEach((v) => { if (v.no != null) valueNos.push(v.no); }));
    const ir = await fetch(base + "/options/v2/prioritized-inventories", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ optionValueNos: valueNos }),
    });
    if (!ir.ok) return { url: url, source_key: sk, status: "error", error: "inv http " + ir.status };
    const ij = await ir.json();
    const invMap = {};
    ((ij && ij.data) || []).forEach((x) => { invMap[x.productVariantId] = x; });
    const gj = await fetch(base, { credentials: "include", headers: { Accept: "application/json" } }).then((r) => r.json());
    const salePrice = (((gj.data || {}).goodsPrice) || {}).salePrice;
    if (salePrice == null) return { url: url, source_key: sk, status: "error", error: "표면가 없음" };
    // 재고 3상태: 품절=0 / 잔여 N개=N(한정) / 표식없음=999(충분·수량 비공개).
    const options = its.map((it) => {
      const size = (it.optionValues && it.optionValues[0] && it.optionValues[0].name) || it.managedCode || "";
      const inv = invMap[it.no];
      let st = null;
      if (inv) st = (inv.outOfStock === true) ? 0 : (typeof inv.remainQuantity === "number" ? inv.remainQuantity : 999);
      // [2026-07-10] price 동봉 — 무신사는 옵션별 가격이 없고 상품 표면가(salePrice) 공통.
      return { color: "", size: size, stock: st, price: salePrice };
    });
    const stock = options.reduce((s, o) => s + (typeof o.stock === "number" ? o.stock : 0), 0);
    return { url: url, source_key: sk, price: salePrice, stock: stock, options: options,
             status: "ok", product_name: null, surface_price: salePrice };
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "예외 " + String(e).slice(0, 40) }; }
}

// 현대H몰 — 창 없이. raw HTML(__NEXT_DATA__ SSR)로 표면가·색옵션 → 서버 parse,
//   + 색×사이즈 실재고는 item-stockcount API(uitmSeq 프로브)를 SW fetch(cross-origin)로.
//   ★hmall.py 파서는 __NEXT_DATA__ JSON 만 읽음 → 창(렌더)이든 raw든 값 동일(2026-07-09 실측 통과:
//     bbprc/sellPrc/stockList 원문 존재 + item-stockcount 200). 실패 시 error 반환→기존 창 경로 폴백.
async function fetchHmallPerSizeSW(slitmCd) {
  const out = [];
  for (let seq = 1; seq <= 15; seq++) {
    let list = [];
    try {
      const qs = new URLSearchParams({
        slitmCd: slitmCd, setItemYn: "N", uitmCombYn: "Y", uitmAttrTypeSeq: "2",
        selectBoxIdx: "1", uitmSeq: String(seq), rishpNotfExpsYn: "Y",
        befUitmSeq1: "0", befUitmSeq2: "0", befUitmSeq3: "0", setSlitmCd: slitmCd, setSlitmYn: "N",
      });
      const r = await fetch("https://www.hmall.com/api/hf/dp/v1/item-ptc/item-stockcount?" + qs.toString(),
        { credentials: "include", headers: { Accept: "application/json" } });
      const j = await r.json();
      list = (j && j.respData && j.respData.stockList) || [];
    } catch (e) { break; }
    if (!list.length) break;
    if (!list.some((it) => it.uitm2AttrNm)) return null;   // 2축(색×사이즈) 아님 → per-size 미적용
    list.forEach((it) => {
      const c = it.uitm1AttrNm || "", s = it.uitm2AttrNm || "";
      if (c && s) out.push({
        color_text: c, size_text: s,
        // 품절판정 = sellGbcd("00"=판매 / 그 외=품절). stockCount 아님(품절도 1 센티넬).
        stock: (it.sellGbcd && String(it.sellGbcd) !== "00")
          ? 0 : (typeof it.stockCount === "number" ? it.stockCount : null),
        price: (typeof it.sellPrc === "number" ? it.sellPrc : null),
      });
    });
  }
  return out.length ? out : null;
}

async function fetchHmallAdapter(item) {
  const url = item.url, sk = "hmall";
  let html;
  try {
    const r = await fetch(url, { credentials: "include" });
    if (!r.ok) return { url: url, source_key: sk, status: "error", error: "html http " + r.status };
    html = await r.text();
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "html fetch 예외" }; }
  if (!html || html.length < 500) return { url: url, source_key: sk, status: "error", error: "빈 HTML" };
  let p;
  try {
    p = await bgFetch("/api/sources/parse", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_key: sk, url: url, html: html }),
    }).then((x) => x.json());
  } catch (e) { return { url: url, source_key: sk, status: "error", error: "parse 호출 실패" }; }
  if (!p || !p.ok) return { url: url, source_key: sk, status: "error", error: (p && (p.message || p.error)) || "parse 실패" };
  let opts2 = Array.isArray(p.options) ? p.options : [];
  // 모음전(2축) 색×사이즈 실재고 보강 — 창 경로의 hmallPerSizeOptions 와 동일 로직을 SW fetch 로.
  const um = String(url).match(/slitmCd=(\d+)/);
  if (um) {
    try {
      const ps = await fetchHmallPerSizeSW(um[1]);
      if (ps && ps.length) opts2 = graftComboColorPrices(p.options, ps);   // per-size 가격 0 → 색별 가격 이식
    } catch (e) { /* per-size 실패 시 색-레벨 유지 */ }
  }
  const priced = opts2.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  let stock = null;
  const stocks = opts2.filter((o) => o && typeof o.stock === "number");
  if (stocks.length) stock = stocks.reduce((s, o) => s + Math.max(0, o.stock), 0);
  const ok = price != null;
  return {
    url: url, source_key: sk, price: price, stock: stock,
    // [2026-07-10] price 동봉 — 서버 persist_crawled_options 는 price 를 받을 걸로 설계됐는데
    //   확장이 안 보내서 '가격 변동'이 영원히 0건이었다(회차 보고서 30회차 실측). 파서 옵션엔 price 있음.
    options: opts2.map((o) => ({ color: o.color_text, size: o.size_text, stock: o.stock, price: o.price })),
    status: ok ? "ok" : "error", product_name: p.product_name_raw || null,
    error: ok ? null : "옵션 가격 없음",
  };
}

// 등록(플래그 OFF 이므로 아직 아무 소싱처도 이 경로를 타지 않음 — 켜기는 소싱처별 G1 후).
["lemouton", "ssg", "lotteimall", "ssf", "ss_lemouton"].forEach((k) => { FETCH_ADAPTERS[k] = fetchRawParseAdapter; });
FETCH_ADAPTERS["hmall"] = fetchHmallAdapter;     // [2026-07-09] 창없이 어댑터(raw __NEXT_DATA__ + item-stockcount SW fetch)
FETCH_ADAPTERS["musinsa"] = fetchMusinsaAdapter;

function toItemBG(x) {
  return {
    url: x.url, price: x.price, stock: x.stock, options: x.options,
    status: x.status, product_name: x.product_name, error: x.error,
    is_logged_in: (x.is_logged_in === undefined ? null : x.is_logged_in),
    benefits_ok: x.benefits_ok, benefit_lines: x.benefit_lines, benefit_amounts: x.benefit_amounts,
    surface_price: x.surface_price, member_price: x.member_price,
    product_coupon_list: x.product_coupon_list || [],   // ★ 2026-07-04 무신사 상품쿠폰 전량(서버 쿠폰별 게이트)
    // [2026-07-23 · T6] 롯데온 pbf 혜택 3종 — /api/sources/crawl-result 로 서버 전달(T7 서버 키).
    //   실패 = null/[] 그대로(폴백 금지). 롯데온 외 소싱처는 undefined → null.
    lotteon_max_price: (x.lotteon_max_price === undefined ? null : x.lotteon_max_price),
    lotteon_card_discounts: (x.lotteon_card_discounts === undefined ? null : x.lotteon_card_discounts),
    lotteon_store_discount: (x.lotteon_store_discount === undefined ? null : x.lotteon_store_discount),
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
  const ALL = ALL_SOURCE_KEYS;
  const seen = new Set();
  const bySource = {};
  (r.options || []).forEach((o) =>
    (o.sources || []).forEach((s) => {
      if (!s.product_url || ALL.indexOf(s.source_key) < 0) return;
      if (s.crawl_weight === 0) return;   // [2026-07-10] 계수 0 = 크롤 제외(자동/전체 크롤 모두 안 긁음)
      const key = s.source_key + "|" + s.product_url;
      if (seen.has(key)) return;
      seen.add(key);
      (bySource[s.source_key] = bySource[s.source_key] || []).push({ source_key: s.source_key, url: s.product_url, url_type: s.url_type || "dan" });
    })
  );
  const sourceKeys = Object.keys(bySource);
  const total = sourceKeys.reduce((n, k) => n + bySource[k].length, 0);
  if (!total) { await _finalize(); emit("finish", { level: "warn", msg: "대상 URL 없음" }); return { ok: false, error: "대상 URL 없음" }; }

  // [2026-07-12 2단계] 소싱처별 '동시 상한' — 서버(weight-tree)에서 받아 한 소싱처의 URL 을
  //   여러 창으로 나눠 병렬로 긁는다(공유 커서=중복 0). 못 받으면 1(=현행 순차) 폴백.
  // [2026-07-14 상향] 첫 배포 안전 클램프 3 → 8 (사용자 결정: 화면 설정대로).
  //   이제 화면의 '동시 상한' 스테퍼(5~8)가 실제 창 수를 정한다. 소싱처당 최대 8창.
  //   ⚠️사이트 차단 위험 영역: 첫 실크롤에서 차단·빈응답·중복 여부를 반드시 육안 검증하고,
  //     실패가 보이면 이 상한을 낮춘다(=🔒 재고·가격 정합성 우선).
  const PER_SOURCE_MAX = 8;
  const sourceCaps = {};
  try {
    const _wt = await bgFetch("/api/crawl/weight-tree").then((x) => x.json());
    (_wt && _wt.src || []).forEach((s) => { if (s && s.scope_key != null) sourceCaps[s.scope_key] = s.concurrency; });
  } catch (_) {}
  function effectiveCap(sk) {
    const v = sourceCaps[sk];
    return Math.max(1, Math.min(PER_SOURCE_MAX, (v == null ? 1 : (parseInt(v, 10) || 1))));
  }

  // [2026-07-12] 동시 창 상한 3→10 (사용자 요청) — 예전처럼 창을 넉넉히 열어 빠르게.
  //   실제 도달치는 '메모리 안전장치'(MEM≥96 보류·≥98 강제감소)가 정한다 = 브레이크는 메모리.
  //   ★CPU 기반 자동감소는 해제(evaluateConcurrency): chrome.system.cpu 는 PC 전체 CPU라
  //     다른 앱이 바쁘면 크롤이 지레 1개로 쪼그라들어 느려지던 원인(사용자 확인). 이제 메모리만 브레이크.
  let cap = 30;                         // 천장 30(사용자 요청). ⚠️한 모음전 소싱처 ~8개라 현 구조선 ~8 바인딩(30은 천장). 메모리가 실제 브레이크.
  // [2026-07-12] 시작부터 이 모음전의 소싱처를 한꺼번에 연다(burst) — 4에서 +1씩 기어오르며
  //   창이 찔끔찔끔 열리던 것 개선. 천장(cap)·소싱처 수 안에서 즉시 최대치. 메모리 높으면 자동 감소.
  let concurrency = Math.min(cap, Math.max(1, sourceKeys.length));
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
    let pausedMid = false;
    const srcOuts = [];   // 이 소싱처 결과 누적 → 소싱처 완료 즉시 증분 저장용
    const wins = [];      // 이 소싱처가 연 창들
    let cursor = startIdx;                 // ★ 레인들이 공유하는 URL 커서(단일스레드 → 원자적)
    const nLanes = Math.max(1, Math.min(effectiveCap(sk), list.length - startIdx));

    // [2026-07-14] 소싱처 유형별 병렬 방식 — '동시 상한'(effectiveCap)은 이제 '창 수'가 아니라
    //   "한꺼번에 몇 개를 동시에 긁느냐(레인 수)"다. 같은 URL 을 두 레인이 안 집도록 cursor 는
    //   단일스레드 원자 증가(i = cursor++). 창을 URL 마다 여는 게 병렬화의 본질이 아니다 —
    //   fetch 는 원래 동시 실행되므로 탭 1개(또는 0개) 안에서 동시에 쏘면 창 없이 빨라진다.
    //   · SW fetch(lemouton·ssf·hmall)  = 창 0개. 서비스워커에서 동시 어댑터 호출.
    //   · same-origin(ssg·lotteimall)   = 도메인 탭 1개. 그 탭에서 동시 fetch(창 1개, 렌더 없음).
    //   · 렌더(musinsa·lotteon)          = 레인마다 창 1개(기존 동작 보존).
    //   winless 레인은 fetchOnly=true → fetch 실패 시 창(navGrab) 폴백 생략·정직 error(§4 무결성).
    const isSW = FAST_FETCH_SOURCES.indexOf(sk) >= 0;
    const isSameOrigin = SAMEORIGIN_FETCH_SOURCES.indexOf(sk) >= 0;
    const winless = isSW || isSameOrigin;

    // 한 URL 처리(레인 공통 본문). tabId = null(SW) / 공유 도메인탭(same-origin) / 전용창(렌더).
    async function _processOne(tabId, laneOpts) {
      if (_mgr.paused) { pausedMid = true; return false; }
      const i = cursor++;                 // ★ 원자적(단일스레드) — 레인끼리 URL 안 겹침
      if (i >= list.length) return false;
      const t0 = Date.now();
      let out;
      const _r = await withTimeout(crawlItemInTabBG(tabId, code, list[i], laneOpts), UNIT_TIMEOUT_MS);
      if (_r && _r.__timeout) {
        out = { url: list[i].url, source_key: sk, status: "error", error: "유닛 타임아웃 " + (UNIT_TIMEOUT_MS / 1000) + "s(행 추정·건너뜀)" };
      } else if (_r && _r.__error) {
        out = { url: list[i].url, source_key: sk, status: "error", error: _r.__error };
      } else {
        out = _r || { url: list[i].url, source_key: sk, status: "error", error: "결과 없음" };
      }
      const sec = (Date.now() - t0) / 1000;
      latencies.push(sec); if (latencies.length > 12) latencies.shift();
      results.push(out); srcOuts.push(out); done++;
      if (cooldown > 0) cooldown--;
      emit("item-done", {
        source: sk, level: out.status === "ok" ? "" : "warn",
        url: (out && out.url) || (list[i] && list[i].url) || null,
        name: (out && out.product_name) || null,
        surf: (out && out.price != null) ? out.price : null,
        url_type: (list[i] && list[i].url_type) || "dan",
        lineId: out.status === "ok" ? (sk + "|" + ((out && out.url) || (list[i] && list[i].url) || "")) : null,
        msg: (out.status === "ok"
          ? (sk + " 표면 " + (out.price != null ? out.price.toLocaleString() + "원" : "가격없음") + " (" + sec.toFixed(1) + "s)")
          : (sk + " 실패: " + (out.error || "")))
          + (out.sku_diag != null ? (" [SKU재고 " + out.sku_diag + " · 실수량 " + (out.stock_real_n || 0) + "/" + (out.stock_total_n || 0) + "]") : ""),
        metrics: { concurrency, cap, active, done, total, avgSec: +bgMedian(latencies).toFixed(2), cpu: lastSys.cpu, mem: lastSys.mem },
      });
      if (done % 3 === 0) {
        lastSys = await handleSysinfo().then((s) => ({ cpu: s && s.cpu != null ? s.cpu : null, mem: s && s.mem != null ? s.mem : null })).catch(() => ({ cpu: null, mem: null }));
        if (lastSys.cpu != null || lastSys.mem != null) {
          const hot = (lastSys.cpu != null && lastSys.cpu >= 90) || (lastSys.mem != null && lastSys.mem >= 96);
          if (hot) emit("resource", { level: "warn", msg: "자원 높음 — CPU " + lastSys.cpu + "% / MEM " + lastSys.mem + "%", metrics: { concurrency, cap, active, cpu: lastSys.cpu, mem: lastSys.mem } });
        }
      }
      return true;
    }
    // 레인 = 공유 커서에서 URL 하나씩 뽑아 처리(레인 여러 개 = 동시성)
    async function _lane(tabId, laneOpts) {
      while (!_mgr.stopped) { const cont = await _processOne(tabId, laneOpts); if (!cont) break; }
    }

    let sharedTab = null;
    try {
      if (winless) {
        const laneOpts = { fetchOnly: true };
        if (isSameOrigin) {
          // 도메인 탭 1개 — origin 으로 미리 이동해 두면 레인들이 same-origin fetch(WAF 통과)만 한다.
          const w = await handleOpenWin({});
          if (!w || !w.ok || w.tabId == null) {   // 도메인 탭 못 열었음 → 전건 실패(정직)
            for (let j = startIdx; j < list.length; j++) { results.push({ url: list[j].url, source_key: sk, status: "error", error: "도메인 탭 생성 실패" }); done++; }
            delete sourceProgress[sk];
            emit("source-done", { source: sk, level: "warn", msg: sk + " 도메인 탭 생성 실패 — 건너뜀", metrics: { concurrency, cap, active, done, total } });
            return;
          }
          wins.push(w); sharedTab = w.tabId;
          try {
            const origin = new URL(list[startIdx].url).origin;
            await chrome.tabs.update(sharedTab, { url: origin + "/" });
            await waitTabComplete(sharedTab, 20000);
          } catch (_) { /* origin 확보 실패해도 crawlItemInTabBG 가 레인 내에서 재확보 시도 */ }
        }
        emit("window-open", { source: sk, level: "", wins: (sharedTab != null ? 1 : 0),
          msg: sk + (isSW ? " 창없이" : " 도메인탭 1개") + " · 동시 " + nLanes + "개 긁기",
          metrics: { concurrency, cap, active, done, total } });
        await Promise.all(Array.from({ length: nLanes }, () => _lane(sharedTab, laneOpts)));
      } else {
        // 렌더 경로(무신사·롯데온) — 레인마다 창 1개(기존 동작 보존).
        const _mkLane = async (wi) => {
          const w = await handleOpenWin({});
          if (!w || !w.ok || w.tabId == null) return;   // 이 창 실패 → 다른 창이 남은 URL 커버(커서 공유)
          wins.push(w);
          if (wi === 0) emit("window-open", { source: sk, level: "", wins: nLanes, msg: sk + " 창 시작" + (nLanes > 1 ? (" ×" + nLanes + " (URL 나눠 긁기)") : ""), metrics: { concurrency, cap, active, done, total } });
          await _lane(w.tabId, null);
        };
        await Promise.all(Array.from({ length: nLanes }, (_u, wi) => _mkLane(wi)));
        if (!wins.length) {   // 창을 하나도 못 열었음 → 전건 실패(기존 동작 보존)
          for (let j = startIdx; j < list.length; j++) { results.push({ url: list[j].url, source_key: sk, status: "error", error: "창 생성 실패" }); done++; }
          delete sourceProgress[sk];
          emit("source-done", { source: sk, level: "warn", msg: sk + " 창 생성 실패 — 건너뜀", metrics: { concurrency, cap, active, done, total } });
          return;
        }
      }
      // 실패 URL 1회 자동 재시도 — ★winless 는 '렌더 폴백'으로 한 번 더 뚫는다(기존 안전망 복원).
      //   fetch(fast)로 실패한 건만 렌더로 재시도 → raw fetch 가 WAF 챌린지/빈응답으로 비어도
      //   창 렌더로 값 확보(기존 동작과 동일 커버리지). 재시도는 순차라 공유탭 렌더 경쟁 없음.
      //   same-origin 은 이미 열린 도메인탭 재사용, SW 는 임시창 1개 열어 씀(끝나면 닫음).
      if (!_mgr.stopped && !_mgr.paused) {
        const _failed = srcOuts.filter((o) => o && o.status === "error");
        let _retryTab, _retryWin = null;
        if (winless) {
          if (sharedTab != null) { _retryTab = sharedTab; }                        // 도메인탭 재사용(same-origin)
          else if (_failed.length) { _retryWin = await handleOpenWin({}); _retryTab = (_retryWin && _retryWin.ok) ? _retryWin.tabId : null; }  // SW=임시창
        } else {
          _retryTab = wins[0] && wins[0].tabId;
        }
        const _retryOpts = null;   // ★재시도는 fetchOnly 끔 → 창(navGrab) 렌더 폴백 허용(안전망)
        if (_failed.length && _retryTab != null) {
          emit("retry", { source: sk, level: "", msg: sk + " 실패 " + _failed.length + "건 자동 재시도(렌더)", metrics: { concurrency, cap, active, done, total } });
          for (const _f of _failed) {
            if (_mgr.stopped || _mgr.paused) break;
            const _orig = list.find((x) => x.url === _f.url) || { url: _f.url, source_key: sk };
            const _r2 = await withTimeout(crawlItemInTabBG(_retryTab, code, _orig, _retryOpts), UNIT_TIMEOUT_MS);
            const _out2 = (_r2 && !_r2.__timeout && !_r2.__error && _r2.status === "ok") ? _r2 : null;
            if (_out2) {
              const _si = srcOuts.indexOf(_f); if (_si >= 0) srcOuts[_si] = _out2;
              const _ri = results.indexOf(_f); if (_ri >= 0) results[_ri] = _out2;
              emit("item-retried", { source: sk, level: "", url: _out2.url, name: _out2.product_name || null, surf: (_out2.price != null) ? _out2.price : null, lineId: sk + "|" + _out2.url, msg: sk + " 재시도 성공 — 표면 " + (_out2.price != null ? _out2.price.toLocaleString() + "원" : "가격없음"), metrics: { concurrency, cap, active, done, total } });
            }
          }
        }
        if (_retryWin && _retryWin.winId != null) { try { await handleCloseWin({ winId: _retryWin.winId }); } catch (_) {} }
      }
    } finally {
      for (const _w of wins) { if (_w && _w.winId != null) { try { await handleCloseWin({ winId: _w.winId }); } catch (_) {} } }
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
    // [2026-07-12] CPU 기반 감소 해제 — chrome.system.cpu 는 PC 전체 CPU라 다른 앱이 바쁘면
    //   크롤이 지레 1개로 줄어 느려졌다(사용자 확인). 브레이크는 '메모리'만 둔다.
    if (mem != null && mem >= 98) {
      if (concurrency > 1) { concurrency--; cooldown = 3; prevThroughput = throughput; emit("concurrency", { level: "down", msg: "메모리 한계(MEM≥98) 강제 −1 → " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
      return;
    }
    const blockUp = (mem != null && mem >= 96);   // 메모리 높을 때만 +1 보류(CPU는 무시)
    if (throughput > prevThroughput * 1.05) {
      prevThroughput = throughput;
      if (concurrency < cap && !blockUp) { concurrency++; cooldown = 3; emit("concurrency", { level: "up", msg: "처리량 개선 → 창 +1 = " + concurrency, metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
      else if (blockUp && concurrency < cap) { emit("resource", { level: "warn", msg: "처리량 여력 있으나 메모리 높음(MEM≥96) → +1 보류", metrics: { concurrency, cap, active, cpu, mem, done, total } }); }
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

  // ★ [2026-06-22] 최종 재시도 패스 — 동시창이 모두 닫혀 시스템 부하가 낮아진 지금,
  //   아직 실패(error)인 URL만 신규 창에서 1회 더 재크롤. 크롤 도중의 즉시 재시도(같은 창·
  //   고부하 시점)가 못 살린 '부하성·일시 hiccup' 실패를 자가치유 → 소싱처 통째 0% 방지.
  //   폴백 금지 — 여기서도 못 받으면 그대로 실패로 둔다(가짜값 안 채움).
  if (!_mgr.stopped) {
    const stillFailed = results.filter((o) => o && o.status === "error" && o.url);
    if (stillFailed.length) {
      emit("final-retry", { level: "", msg: "최종 재시도 — 실패 " + stillFailed.length + "건(부하 낮은 시점 재크롤)", metrics: { concurrency, cap, active, done, total } });
      await new Promise((r) => setTimeout(r, 1500));   // 일시 hiccup 가실 시간
      const bySk = {};
      stillFailed.forEach((o) => { (bySk[o.source_key] = bySk[o.source_key] || []).push(o); });
      for (const sk of Object.keys(bySk)) {
        if (_mgr.stopped) break;
        let rWinId = null, rTabId = null;
        try {
          const w = await handleOpenWin({});
          if (!w || !w.ok || w.tabId == null) continue;
          rWinId = w.winId; rTabId = w.tabId;
          const recovered = [];
          for (const _f of bySk[sk]) {
            if (_mgr.stopped) break;
            const _orig = (bySource[sk] || []).find((x) => x.url === _f.url) || { source_key: sk, url: _f.url };
            const _r3 = await withTimeout(crawlItemInTabBG(rTabId, code, _orig), UNIT_TIMEOUT_MS);
            if (_r3 && !_r3.__timeout && !_r3.__error && _r3.status === "ok") {
              const _ri = results.indexOf(_f); if (_ri >= 0) results[_ri] = _r3;
              recovered.push(_r3);
              // [2026-06-22] item-retried(복구) — done 불변 + 웹앱 fail→ok 보정(오버카운트/실패오표시 방지)
              emit("item-retried", { source: sk, level: "", url: _r3.url, name: _r3.product_name || null, surf: (_r3.price != null) ? _r3.price : null, lineId: sk + "|" + _r3.url, msg: sk + " 최종 재시도 성공 — 표면 " + (_r3.price != null ? _r3.price.toLocaleString() + "원" : "가격없음"), metrics: { concurrency, cap, active, done, total } });
            }
          }
          if (recovered.length) { const sv = await saveItemsBG(recovered); savedTotal += (sv && sv.updated) || 0; }
        } finally {
          if (rWinId != null) { try { await handleCloseWin({ winId: rWinId }); } catch (_) {} }
        }
      }
    }
  }

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

// ── [Task E2] 소싱처 주문상태 확인 ─────────────────────────────────────────
//   원본(단독앱) modules/sourcing_checker.py 의 check_order_sync → check_order_status 를
//   메커니즘만 이식: Python Playwright(전용 프로필) 대신, 로그인된 이 브라우저에서 주문 URL 을
//   보이는 창(focused:false)으로 열고 → 사이트별 파서(orderStatusExtractor)를 chrome.scripting
//   으로 주입해 상태를 읽고 → 창을 닫는다(handleCrawl/crawlOne 의 탭 수명주기와 동일).
//
//   반환: { ok, order_status, courier, tracking, site_name, source, logs, error, is_logged_in }
//     · ok=true       : 확정된 상태(배송완료/배송중/취소/반품/교환/미발송)를 읽음
//     · is_logged_in=false : 로그인 페이지로 리다이렉트됨 → 거짓 성공 금지, 정직 표면화
//     · 그 외          : 확인불가/파싱실패 사유를 error 에 담아 반환
//   창 누수 방지: 성공/실패/예외 무관하게 finally 에서 창을 닫는다.
async function handleCheckOrder(payload) {
  const url = payload.url || "";
  const siteKey = payload.site_key || "";
  const siteName = payload.site_name || "";
  const logs = [];
  const fail = (error, extra) => Object.assign({
    ok: false, order_status: "", courier: "", tracking: "",
    site_name: siteName, source: "ext-local", logs, is_logged_in: null, error,
  }, extra || {});

  if (!url) return fail("주문 URL 없음");
  logs.push("[1/3] 로그인된 브라우저로 주문 URL 열기: " + url);

  let win = null;
  try {
    win = await chrome.windows.create({ url, focused: false });
    const tab = win && win.tabs && win.tabs[0];
    if (!tab) return fail("주문 확인 창 생성 실패");
    const tabId = tab.id;
    await waitTabComplete(tabId, 25000);
    // SPA(무신사 등) 상태/송장 DOM 이 로드 완료 뒤 늦게 뜰 수 있어 안정화 대기.
    await new Promise((r) => setTimeout(r, 2500));
    logs.push("[2/3] 페이지 로드 완료 → 사이트별 상태 파싱(site_key=" + (siteKey || "generic") + ")");

    const out = await chrome.scripting.executeScript({
      target: { tabId }, world: "ISOLATED",
      func: orderStatusExtractor, args: [siteKey],
    });
    const res = (out && out[0] && out[0].result) || null;
    if (!res) return fail("상태 파싱 결과 없음(주입 실패)");

    if (res.status === "로그인필요") {
      logs.push("[3/3] 로그인 리다이렉트 감지 → 로그인 필요");
      return {
        ok: false, order_status: "", courier: "", tracking: "",
        site_name: siteName, source: "ext-local", logs, is_logged_in: false,
        error: "로그인 필요 — 이 브라우저에서 소싱처에 로그인 후 재시도",
      };
    }
    logs.push("[3/3] 상태: " + (res.status || "확인불가") + (res.detail ? (" (" + res.detail + ")") : ""));
    const confirmed = !!(res.status && res.status !== "확인불가" && !res.error);
    return {
      ok: confirmed,
      order_status: res.status || "확인불가",
      courier: res.courier || "",
      tracking: res.tracking || "",
      site_name: siteName, source: "ext-local", logs, is_logged_in: true,
      error: res.error || "",
    };
  } catch (e) {
    return fail(String(e && e.message ? e.message : e));
  } finally {
    if (win && win.id != null) { try { await chrome.windows.remove(win.id); } catch (_) {} }
  }
}

// orderStatusExtractor — 주문상세 페이지 컨텍스트(ISOLATED world)에서 실행되는 순수 파서.
//   ⚠️ 이 함수는 chrome.scripting 이 문자열화해 페이지에 주입한다 → 바깥 스코프 변수 참조 금지.
//      (site_key 는 args 로 전달됨.) 페이지 DOM 을 변형(버튼/메뉴 제거)하나 창은 곧 닫히므로 무해.
//
//   원본 sourcing_checker.py 이식(메커니즘 아닌 로직):
//     · _check_login_redirect  (URL 로그인 키워드)                         원본 2038
//     · _check_musinsa         (p.company-name / button.tracking-number)   원본 2067
//     · _check_ssfshop         (checkDelivery onclick 파싱)                원본 2202
//     · _extract_status_from_labels + _classify_status_text (범용 라벨/키워드) 원본 2281·2300
//     · _DOM_CLEAN_JS          (버튼/메뉴 제거 → '반품 신청' 버튼 오탐 방지)  원본 2329
//   미이식(라이브 확정 필요): 무신사 '배송 조회' 버튼 클릭 흐름·롯데 DeliveryTrace URL 이동·
//     쿠키 복원/자동로그인·오판 스냅샷 저장. → 송장/택배사는 best-effort.
function orderStatusExtractor(siteKey) {
  var S = {
    DELIVERED: "배송완료", SHIPPING: "배송중", NOT_SENT: "주문완료(미발송)",
    CANCEL: "취소", RETURN: "반품", EXCHANGE: "교환", UNKNOWN: "확인불가", LOGIN: "로그인필요",
  };
  function has(t, arr) { for (var i = 0; i < arr.length; i++) { if (t.indexOf(arr[i]) >= 0) return true; } return false; }

  // 0) 로그인 리다이렉트 감지 (원본 _check_login_redirect)
  var href = (location.href || "").toLowerCase();
  if (has(href, ["login", "member.one", "signin", "sign-in", "/auth", "lcloginmem"])) {
    return { status: S.LOGIN, courier: "", tracking: "", detail: "로그인 리다이렉트", error: "" };
  }

  var rawBody = "";
  try { rawBody = (document.body && document.body.innerText) || ""; } catch (e) { rawBody = ""; }
  if (!rawBody || rawBody.length < 20) {
    return { status: S.UNKNOWN, courier: "", tracking: "", detail: "", error: "페이지 본문 비어있음(렌더 실패/미로그인 가능)" };
  }
  // 없는 주문/접근 오류 = 계정불일치/번호오류 가능 → 정직하게 확인불가+사유
  if (has(rawBody, ["주문정보를 찾을 수 없", "주문 정보가 없", "존재하지 않는 주문", "찾을 수 없습니다"])) {
    return { status: S.UNKNOWN, courier: "", tracking: "", detail: "", error: "주문 정보 없음(계정 불일치/주문번호 오류 가능)" };
  }

  // 1) 택배사/송장 — 사이트별 셀렉터 우선, 실패 시 범용 라벨 패턴 (DOM 변형 전에 raw 에서 추출)
  var courier = "", tracking = "";
  var COURIERS = ["CJ대한통운", "롯데글로벌로지스", "대한통운", "한진택배", "롯데택배", "우체국택배", "로젠택배", "경동택배"];
  for (var ci = 0; ci < COURIERS.length; ci++) { if (rawBody.indexOf(COURIERS[ci]) >= 0) { courier = COURIERS[ci]; break; } }
  try {
    if (siteKey === "musinsa") {
      var cn = document.querySelector("p.company-name"); if (cn && (cn.innerText || "").trim()) courier = cn.innerText.trim();
      var tn = document.querySelector("button.tracking-number"); if (tn) tracking = (tn.innerText || "").trim();
    } else if (siteKey === "ssfshop") {
      var btn = document.querySelector('button[onclick*="checkDelivery"]');
      if (btn) {
        var oc = btn.getAttribute("onclick") || "";
        var mm = oc.match(/checkDelivery\s*\(\s*['"]([^'"]*)['"]\s*,\s*['"]([^'"]*)['"]/);
        if (mm) { if (mm[1]) courier = mm[1]; tracking = mm[2] || ""; }
      }
    }
  } catch (e) { /* 셀렉터 실패 → 범용 폴백 */ }
  if (!tracking) {
    var TW = ["송장번호", "운송장번호", "운송장", "송장", "트래킹", "tracking"];
    for (var ti = 0; ti < TW.length; ti++) {
      var kw = TW[ti].replace(/\s+/g, "\\s*");
      var m2 = rawBody.match(new RegExp(kw + "\\s*[:：#(]?\\s*([A-Z0-9\\-]{9,20})", "i"));
      if (m2) {
        var cand = m2[1];
        // 전화번호(0으로 시작 10~11자리) 배제
        if (/\d/.test(cand) && !/^0\d{8,10}$/.test(cand.replace(/[-\s]/g, ""))) { tracking = cand; break; }
      }
    }
  }

  // 2) 상태 판별용 정제 텍스트 — 버튼/메뉴 제거로 '반품 신청'·'교환 신청' 버튼 오탐 방지 (원본 _DOM_CLEAN_JS)
  var cleanBody = rawBody;
  try {
    var kill = [
      "button", "a.btn", 'a[class*="btn"]', ".btn-area", ".btns", ".btn-group",
      '[class*="button"]', '[role="button"]', 'input[type="button"]', 'input[type="submit"]',
      "nav", ".gnb", ".lnb", ".side-menu", ".snb", ".menu", ".category",
      "footer", "header", ".header", ".util", ".util-menu", ".quick-menu",
      ".order-btn", ".action-area", ".cs-area", ".cs-menu",
    ];
    kill.forEach(function (sel) {
      try { document.querySelectorAll(sel).forEach(function (el) { el.remove(); }); } catch (e) {}
    });
    cleanBody = (document.body && document.body.innerText) || rawBody;
  } catch (e) { cleanBody = rawBody; }

  // 3) 상태 분류 (원본 _classify_status_text — 종결상태 우선순위: 배송완료 > 반품완료 > 취소 > 반품접수 > 교환 > 배송중 > 미발송)
  function classify(text) {
    if (has(text, ["배송완료", "배달완료"])) return [S.DELIVERED, "배송완료 감지"];
    if (has(text, ["반품완료", "반품 완료", "반품처리완료"])) return [S.RETURN, "반품완료 감지"];
    if (has(text, ["주문취소", "취소완료", "결제취소", "취소 완료"])) return [S.CANCEL, "취소 감지"];
    if (has(text, ["반품접수", "반품신청"])) return [S.RETURN, "반품접수 감지"];
    if (has(text, ["교환완료", "교환 완료", "교환접수", "교환신청"])) return [S.EXCHANGE, "교환 감지"];
    if (has(text, ["배송중", "배송 중", "배달중", "배송출발", "간선상차"])) return [S.SHIPPING, "배송중 감지"];
    if (has(text, ["발송완료", "발송 완료", "출고완료", "출고 완료"])) return [S.SHIPPING, "발송완료 감지"];
    if (has(text, ["결제완료", "주문접수", "상품준비", "주문완료", "입금완료"])) return [S.NOT_SENT, "미발송 감지"];
    return ["", ""];
  }
  // 3a) 라벨 우선 ("주문상태: 배송완료" 등) — 원본 _extract_status_from_labels
  var labels = ["주문상태", "배송상태", "처리상태", "현재상태", "진행상태"];
  var labelVal = "";
  for (var li = 0; li < labels.length; li++) {
    var lm = cleanBody.match(new RegExp(labels[li] + "\\s*[:：\\n\\r\\s]+([가-힣A-Za-z0-9/\\s]{2,20}?)(?:\\n|$|\\s{2,})"));
    if (lm) { var v = (lm[1] || "").trim(); if (v.length >= 2 && v.length <= 15) { labelVal = v; break; } }
  }
  var st = "", dt = "";
  if (labelVal) { var r1 = classify(labelVal); if (r1[0]) { st = r1[0]; dt = "라벨[" + labelVal + "]→" + r1[1]; } }
  if (!st) { var r2 = classify(cleanBody); st = r2[0]; dt = r2[1]; }
  if (!st) {
    // ★ 송장번호만 있고 상태 키워드가 하나도 없으면 배송중으로 단정하지 않는다 —
    //   송장은 배송완료/반품 주문에도 남는다. 금전 판단(블랙스팟)에 오버클레임 금지 →
    //   확인불가(미확정)로 반환하되 송장은 그대로 노출(정보 손실 없음). 상태를 지어내지 않음.
    if (tracking) { st = S.UNKNOWN; dt = "송장번호만 발견 — 상태 미확정"; }
    else { st = S.UNKNOWN; dt = "상태 판별 불가"; }
  }
  return { status: st, courier: courier, tracking: tracking, detail: dt, error: "" };
}

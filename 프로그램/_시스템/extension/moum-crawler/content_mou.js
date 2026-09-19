// content_mou.js — mou-m.com 페이지에 주입되는 콘텐츠 스크립트.
//  역할 2가지:
//   (1) 설치 마커 — <html data-moum-ext="버전"> 를 심어 페이지가 확장 설치를 감지.
//   (2) 페이지 ↔ 확장 메시지 브리지 — window.postMessage 와 chrome.runtime 사이를 중계.
//  (더망고도 동일 패턴: 콘텐츠 스크립트가 마커를 심고 페이지가 getAttribute 로 감지)

const MOUM_EXT_VERSION = "0.8.04";  // 0.8.04 = background/manifest 와 동기화(자가 새로고침 알람 — chrome://extensions 수동 새로고침 불필요). 0.7.94 = background/manifest 와 동기화(확장 판 번호·0건 진단 전송). 0.7.93 = background/manifest 와 동기화(H몰은 받은 글에서 읽기). 0.7.92 = background/manifest 와 동기화(SSG 규칙 추가). 0.7.91 = background/manifest 와 동기화(H몰 주소 쪽 넘김). 0.7.90 = background/manifest 와 동기화(SSF 검색 주소는 쪽 안 붙임). 0.7.89 = background/manifest 와 동기화(무신사 다음쪽 주소 따라가기). 0.7.88 = background/manifest 와 동기화(단추로 여러 장 걷기). 0.7.87 = background/manifest 와 동기화(훑기 정확도 — 결과없음 가드·아이몰 규칙 교정·「더 있다」 표시). 0.7.86 = [정산] 11번가 **구매확정 전** 정산예정액 크롤 — 하루 전엔 「11번가는 그 구간을 마켓 자체가 안 준다(구조적 한계)」고 결론 냈는데 **틀렸다**. 근거로 삼은 「정산 미확정 0건」이 조회 축을 구매확정일(BUY_CNFRM_DT)로 놓은 결과였고, 구매확정 전 주문은 구매확정일이 없어 애초에 조회 대상이 아니었을 뿐이다. 결제일 축(searchDtType=STL_DT) + 정산 미확정(dtlSearchStlmntType=N)으로 부르니 발주확인·배송완료 건이 주문번호(ordNo·ordPrdSeq)와 정산예정액(stlAmt)까지 그대로 온다(2026-08-08 실측 10건 464,691원 — 화면 합계와 일치). ★0건은 「없다」가 아니라 「이 축으론 안 보인다」일 수 있다. ★화면 조회 상한이 한 달이라 90일을 달 단위로 토막내 부른다. ★로그인 풀리면 HTML 이 오므로 조용한 0건이 아니라 needLogin 으로 정직하게 실패. ★못 읽은 토막 수를 돌려준다(덜 긁은 합계를 온전한 값처럼 쓰지 않게).  0.7.85 = [정산] 롯데온 지급내역 크롤 — 롯데온은 정산 OpenAPI 8종·정산예정금액조회·정산요약·셀러머니 어디에도 **실지급일이 없다**. 셀러오피스 「중개거래정산관리 > 지급내역」 selectMediationSettleDetail 의 seCmptDt(정산완료일)가 유일한 답(2026-08-07 실브라우저 확인). 구매확정일(seStdDt) 단위 일정산이라 그 축으로 조인한다.  0.7.84 = 0.7.84 = background/manifest 와 동기화(훑기 규칙을 서버가 줌). 0.7.83 = background/manifest 와 동기화(낱개 주소 크롤).    // 0.7.82 = background/manifest 와 동기화(대량등록 검색필터 훑기).     // 0.7.81 = background/manifest 와 동기화(로켓그로스 정산 수집 — Wing 화면 API 로컬 크롤).  0.7.76 = background/manifest 와 동기화(옛 회차가 남의 탭을 닫던 것).  0.7.75 = background/manifest 와 동기화(정산 회차 — 롯데온 탭 재우기 금지·무한대기 차단·실패 재시도).  0.7.74 = background/manifest 와 동기화(정산 회차 이력 hist).  0.7.73 = background/manifest 와 동기화(정산 회차 심장박동+시작 도장).  0.7.72 = background/manifest 와 동기화(정산 회차 감시). ※0.7.71 때 이 상수만 0.7.70 에 멈춰 있었다(O25 재발) — 로드버전 진단이 틀리니 셋을 항상 같이 올릴 것.  0.7.70 = background/manifest 와 동기화(회차 via).  0.7.69 = background/manifest 와 동기화(계정별 회차 기록).  0.7.67 = [노션 보고] 캡처에 옆 요일 칸이 같이 찍히던 것 — 위로 올라가며 「충분히 큰 블록」을 잡으니 여러 요일을 감싸는 바깥 덩어리가 잡혔다(2026-08-02 실측: 일요일 옆에 목요일이 반쯤). → **요일 이름이 하나만 들어있는** 가장 큰 덩어리로 판별(dayCount>1 이면 거기서 멈춤). 라벨 개수 기준이라 노션 DOM 구조가 바뀌어도 버틴다.  0.7.66 = [노션 보고] 캡처 백지 재발 — 스크롤로 렌더를 유도한 게 틀렸다. 노션은 화면을 벗어난 블록을 **위아래 양쪽** 모두 지운다(2026-08-02 실측: 아래를 그리러 내려가니 위가 지워져 「일요일」 라벨만 남고 전부 백지). → 스크롤을 버리고 Emulation.setDeviceMetricsOverride 로 **화면 높이를 9000px 로 위장**한다. 노션이 칸 전체를 「보이는 것」으로 여겨 한꺼번에 그리므로 스크롤이 아예 필요 없다. 끝나면 clearDeviceMetricsOverride.  0.7.65 = [노션 보고] 캡처 아래가 잘리던 것 — 노션은 화면 밖 블록을 미리 안 그린다(지연 렌더). 재는 순간 높이만 믿고 찍으면 아직 안 그려진 아래쪽이 백지로 나온다(2026-08-02 실측: 「오후」 아래 전부 빈 칸). → 칸 끝까지 조금씩 훑어 내려 다 그리게 한 뒤 높이가 3회 연속 그대로일 때 잰다. 스크롤 중 요소가 교체될 수 있어 매 회 다시 찾는다. 높이 상한 6000→12000.  0.7.64 = [노션 보고] 노션 「투두리스트 (영빈)」 오늘 요일 칸을 잘라 mou-m 에 올린다(카톡 보고 사진). 1분 알람 → /api/reports/notion-todo/shot/needed 로 「발송 10분 전인가·신선한 캡처가 있나」 확인 → 필요할 때만 노션을 백그라운드 탭으로 열어 캡처 후 닫는다. ★captureVisibleTab 이 아니라 chrome.debugger 의 Page.captureScreenshot(captureBeyondViewport) — 보이는 화면만 찍으면 화면보다 긴 요일 칸이 잘린다. ★노션 CSS 클래스는 수시로 바뀌므로 클래스에 안 기댄다: 「요일 글자」 텍스트노드를 찾아 위로 올라가며 충분히 큰 [data-block-id] 블록을 고른다. 업로드는 mou-m 탭 안 same-origin fetch(SW 직접 fetch 는 SameSite=Lax 세션쿠키가 안 실림). 권한 추가: debugger + notion.so/notion.com/notion.site.  0.7.63 = [M4-5] 무신사·롯데온 상품 사진·상세설명 수집 배관(manifest/background 와 동기화).   // 0.7.62 = manifest/background 와 동기화(0.7.61 에 멈춰 있던 것 — O25 재발, 2026-07-23 지도 최신화에서 발견).   // 0.7.59 = background/manifest 와 동기화(0.7.54 로 굳어 있어 로드버전 진단이 틀렸다 — 2026-07-23 실측).   // 0.7.54 = [S5] crawl.one(지도 예시주소 단건 크롤) 지원. ※이 상수가 페이지의 data-moum-ext 를 정한다 — manifest·background.js 와 항상 같이 올릴 것(0.7.51 로 어긋나 있던 것을 맞춤). 0.7.26 = [E2] 마진계산기 소싱처 주문상태 확인 배선 반영. 0.7.13 = 무신사 상품쿠폰 전량 수집(product_coupon_list). 0.7.12 = 롯데온 재고소스=base 엔드포인트 우선(완전 97셀). data-moum-ext 로 로드버전 확인 가능

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

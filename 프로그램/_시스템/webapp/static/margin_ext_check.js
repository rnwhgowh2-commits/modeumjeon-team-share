// margin_ext_check.js — 마진계산기 iframe(/orders/margin-embed) 전용 소싱처 주문상태 검사 seam.
//
//  원본(단독앱)의 '✓ 확인' 버튼은 서버 /api/check-sourcing (Playwright Chrome 프로필) 로
//  소싱처 주문상태를 확인했다. 모음전 원칙 = 크롤은 로컬 PC(크롬 확장)로 한다(서버 Playwright 금지).
//  → 이 파일이 원본 fetch('/api/check-sourcing',{...}) 자리에 꽂혀, 부모(mou-m.com top frame)의
//    MoumExt 로컬 크롬확장에 'sourcing.check-order' 를 보내 주문상태를 읽어온다.
//
//  정직성(조용한 실패 금지):
//   · 확장 미설치        → '모음전 크롬확장 필요 (로컬 크롤)' 를 셀에 표면화 (서버 호출 안 함)
//   · 소싱처 미식별/URL없음 → '확인 불가' 를 표면화
//   · 소싱처 미로그인      → '로그인 필요' 를 표면화 (거짓 성공 금지)
//   · 파싱 실패           → '확인불가' + 사유
//
//  ※ MoumExt 는 top frame(부모 mou-m.com)에만 있다(content_mou 는 top frame 에만 마커/브리지 주입).
//    이 iframe 은 부모와 same-origin 이므로 window.parent.MoumExt 로 직접 호출한다.
(function () {
  // 부모(top frame)의 MoumExt — same-origin 이라 직접 접근. cross-origin(비정상)·부재 시 폴백.
  function _ext() {
    try {
      if (window.parent && window.parent !== window && window.parent.MoumExt) return window.parent.MoumExt;
    } catch (e) { /* cross-origin (정상 동작 시 same-origin 이라 여기 안 옴) */ }
    if (window.MoumExt) return window.MoumExt;   // iframe 자체에 로드된 경우(테스트/단독)
    return null;
  }

  // ── 간단메모 → {url, account_id, site_name, site_key} ─────────────────────
  //   블랙스팟 sourcing_parser.extract_memo_info 의 순수 파싱을 클라이언트로 미러(동일 regex/맵).
  var _NAME_KEY = [
    ["무신사", "musinsa"], ["MUSINSA", "musinsa"],
    ["SSF샵", "ssfshop"], ["SSF", "ssfshop"], ["ssfshop", "ssfshop"],
    ["ABC마트", "abc"], ["ABC", "abc"], ["abcmart", "abc"],
    ["그랜드스테이지", "grandstage"],
    ["롯데아이몰", "lotteimall"], ["롯데홈쇼핑", "lotteimall"], ["lotteimall", "lotteimall"],
    ["롯데온", "lotteon"],
    ["GS샵", "gs"], ["gs샵", "gs"],
    ["SSG", "ssg"], ["ssg", "ssg"],
    ["폴더", "folder"], ["folder", "folder"],
    ["르무통", "lemouton"]
  ];
  var _URL_MAP = [
    ["musinsa.com", "musinsa"], ["ssg.com", "ssg"], ["a-rt.com", "abc"], ["gsshop.com", "gs"],
    ["ssfshop.com", "ssfshop"], ["lotteimall.com", "lotteimall"], ["lottehomeshopping.com", "lotteimall"],
    ["lotteon.com", "lotteon"], ["nike.com", "nike"], ["oliveyoung.co.kr", "oliveyoung"],
    ["gmarket.co.kr", "gmarket"], ["fashionplus.co.kr", "fashionplus"],
    ["folderstyle.com", "folder"], ["folder.co.kr", "folder"], ["lemouton.co.kr", "lemouton"]
  ];

  function _parseMemo(memo) {
    var res = { url: "", account_id: "", site_name: "", site_key: "" };
    if (!memo || typeof memo !== "string") return res;
    memo = memo.trim();

    var um = memo.match(/(https?:\/\/\S+)/);
    if (um) res.url = um[1].replace(/\)+$/, "");

    if (res.url) {
      try {
        var h = (new URL(res.url).hostname || "").toLowerCase();
        for (var i = 0; i < _URL_MAP.length; i++) {
          if (h.indexOf(_URL_MAP[i][0]) >= 0) { res.site_key = _URL_MAP[i][1]; break; }
        }
      } catch (e) { /* URL 파싱 실패 → site_key 는 아래 이름 매칭으로 */ }
    }
    if (!res.site_key) {
      for (var j = 0; j < _NAME_KEY.length; j++) {
        if (memo.indexOf(_NAME_KEY[j][0]) >= 0) {
          res.site_key = _NAME_KEY[j][1];
          res.site_name = _NAME_KEY[j][0];
          break;
        }
      }
    }
    // 계정ID + 소싱처명 — 패턴A: "날짜 소싱처명 / 계정ID …"
    var sm = memo.match(/[\d.]+\s+([\s\S]+?)\s*\/\s*(\S+)/);
    if (sm) {
      if (!res.site_name) res.site_name = sm[1].trim();
      res.account_id = sm[2].trim();
    } else {
      // 패턴B: "계정 : 무신사/rnwhgowh2"
      var am = memo.match(/계정\s*[:：]\s*([^\s/]+)\s*\/\s*(\S+)/);
      if (am) {
        if (!res.site_name) res.site_name = am[1].trim();
        res.account_id = am[2].trim().replace(/[.,]+$/, "");
      }
    }
    return res;
  }

  // 배치 중지(AbortController) 지원 — in-flight 확인을 signal 'abort' 로 즉시 중단.
  //   원본 배치 소비 코드의 catch(e){ if(e.name==='AbortError') break; } 가 살아나도록 AbortError 를 던진다.
  function _withAbort(promise, signal) {
    if (!signal) return promise;
    if (signal.aborted) return Promise.reject(new DOMException("aborted", "AbortError"));
    return new Promise(function (resolve, reject) {
      var onAbort = function () { reject(new DOMException("aborted", "AbortError")); };
      signal.addEventListener("abort", onAbort, { once: true });
      promise.then(
        function (v) { try { signal.removeEventListener("abort", onAbort); } catch (e) {} resolve(v); },
        function (e) { try { signal.removeEventListener("abort", onAbort); } catch (_) {} reject(e); }
      );
    });
  }

  // ── 확장 호출 → UI 계약({status, courier, tracking, error})으로 매핑 ──────
  async function _run(memo, signal) {
    // 배치 중지: 이미 중단됐으면 즉시 AbortError (가짜 상태 표시 금지).
    if (signal && signal.aborted) throw new DOMException("aborted", "AbortError");

    var ext = _ext();
    if (!ext || !ext.installed || !ext.installed()) {
      // 조용한 실패 금지: 확장이 없으면 서버로 폴백하지 않고 그 사실을 그대로 표면화.
      return { error: "모음전 크롬확장 필요 (로컬 크롤) — 확장 로드 후 재시도" };
    }
    // 브리지 구버전 방어: MoumExt 에 checkSourcingOrder(타입 메서드)가 없으면 원시 TypeError 대신
    //   정직한 안내. (raw send 는 IIFE private 라 노출 안 됨 → 반드시 타입 메서드로 호출.)
    if (typeof ext.checkSourcingOrder !== "function") {
      return { error: "모음전 확장/브리지 업데이트 필요 (checkSourcingOrder 미노출) — 페이지 새로고침·확장 재로드" };
    }
    var info = _parseMemo(memo);
    if (!info.url) return { error: "간단메모에 URL 없음 — 확인 불가" };
    if (!info.site_key) return { error: "소싱처 식별 불가 — 확인 불가 (지원 소싱처 URL/이름 아님)" };

    var payload = {
      url: info.url,
      account_id: info.account_id,
      site_name: info.site_name,
      site_key: info.site_key,
      memo: memo
    };
    try {
      var resp = await _withAbort(ext.checkSourcingOrder(payload, 90000), signal);

      // 미로그인은 거짓 성공으로 덮지 않고 명시적으로 표면화.
      if (resp && resp.is_logged_in === false) {
        return { error: (resp.error || "로그인 필요") + " (" + (resp.site_name || info.site_name || "소싱처") + ")" };
      }
      if (resp && resp.ok) {
        return {
          status: resp.order_status || "확인불가",
          courier: resp.courier || "",
          tracking: resp.tracking || "",
          error: ""
        };
      }
      // 미확정(확인불가 등)도 order_status 를 그대로 노출 — 송장만 발견=배송중 둔갑 금지(background 가 확인불가로 반환).
      return {
        status: (resp && resp.order_status) || "",
        courier: (resp && resp.courier) || "",
        tracking: (resp && resp.tracking) || "",
        error: (resp && resp.error) || "확인 실패"
      };
    } catch (e) {
      if (e && e.name === "AbortError") throw e;   // 배치 중지 → 상위 루프가 처리(가짜 상태 금지)
      return { error: "확장 통신 오류: " + String((e && e.message) || e) };
    }
  }

  // 원본 fetch('/api/check-sourcing', {...}) 를 대체 — Response 유사 객체(.json()) 반환.
  //   원본 소비 코드: `var resp = await _moumExtCheckFetch(...); var result = await resp.json();`
  //   opts.signal(배치 AbortController) 을 _run 으로 전달해 중지가 in-flight 확인을 끊게 한다.
  window._moumExtCheckFetch = function (url, opts) {
    var memo = "";
    try { memo = (JSON.parse((opts && opts.body) || "{}").memo) || ""; } catch (e) { memo = ""; }
    var signal = opts && opts.signal;
    return { json: function () { return _run(memo, signal); } };  // .json() → Promise<{status,courier,tracking,error}>
  };

  // 테스트/디버그 노출 (순수 파서 단위 검증용).
  window._moumParseMemo = _parseMemo;
})();

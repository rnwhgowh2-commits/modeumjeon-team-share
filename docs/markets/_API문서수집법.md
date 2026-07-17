# 판매처 API 문서 수집법 — 접수 경로 × 신뢰도 매트릭스 · 전체 탭 계층 · 플레이북

> ⚠️ **이 문서는 자동 생성됩니다. 직접 고치지 마세요.**
> 정본 = `프로그램/_시스템/webapp/data/api_ingest_paths.json` · 생성 = `프로그램/_시스템/scripts/api_ingest/gen_doc.py`
> 화면(인앱 `판매처관리 › 데이터코드지도 › API문서수집법`)도 같은 정본을 읽습니다 → 중복·모순 0.
> **최종 실측일**: 2026-07-17
> **원칙**: 날조 금지 · 실측만 '가능' · robots·약관 준수 · 인증 URL 노출 금지 · 첨부에만 있으면 위치만 기록

---

## 1. 왜 필요한가

- 마켓 공식 API 문서를 「데이터 코드 지도」에 접수해두면 새 기능 만들 때 F12 반복 노가다 없이 지도만 보고 구현한다.
- 마켓마다 문서 접근 경로가 전부 다르다. 실측 결과 **6개 마켓이 6가지 다른 경로**로 뚫렸다.
- 마켓이 수십 개로 늘면 '어느 경로를, 어떤 순서로'를 미리 알아야 빠르고 빠짐이 없다 → 플레이북이 이 문서의 핵심.

**6대 마켓 = 6가지 다른 경로로 전부 공식 접수 완료(611 apis). 단일 경로로 다 되는 마켓은 없다 → 순서가 중요.**

### 💡 실측이 뒤집은 통념

1. **'SPA라 차단 = 끝'이 아니다.** 마켓이 문서를 신규 정적 사이트로 이관해뒀을 수 있다. → 스마트스토어: 옛 `/ko`(Angular SPA·정책차단) ❌ 이지만 신규 `/docs`(Docusaurus 정적) ✅ 전량 관통. 같은 도메인, 경로만 다름.
2. **'로그인 게이트 = 사람이 다 복붙'이 아니다.** 사용자가 로그인한 탭 콘솔에 스니펫 1회만 붙여넣으면 전 페이지가 자동 수집된다. → 11번가: 붙여넣기 1회 → 26페이지 크롤 → 구조화 스펙(jsonData) → 파일 다운로드 → Claude가 읽어 25 API 접수.

---

## 2. 신뢰도 등급 (산출물 품질)

| 등급 | 정의 | 기준 |
|---|---|---|
| **①** | 라이브 왕복검증 | 우리 코드로 실제 호출 → 응답 성공 확인 |
| **②** | 공식문서 완전 | 요청·응답·필드·예시·오류 4종 완비 |
| **③** | 공식문서 부분 | 일부만 · 본문 필드 불명 등 |
| **④** | 코드 근거만 | 스켈레톤 · 호출 안 해봄 |
| **⑤** | 추정 | 근거 없는 짐작 = 절대 금지 |

---

## 3. 접수 경로 도구상자

| 코드 | 방법 | 강점·기법 | 한계 |
|---|---|---|---|
| **A** | 자동 읽기(fetch) | SSR 사이트 관통 · 브라우저 안전차단을 우회(다른 경로) · raw=true로 링크 열거, start_index 이어읽기 | robots Disallow 차단 · 클라이언트렌더 SPA는 빈 껍데기 |
| **A-2** | ★신규 정적 이관본 | ‘SPA라 끝’이 아니다! 옛 포털이 막혀도 신규 문서가 정적사이트일 수 있음(스스: /ko Angular 차단 → /docs Docusaurus 관통). 열쇠 = sitemap.xml | OpenAPI 플러그인은 오퍼레이션 본문이 클라 렌더 → 필드는 구조체(/schemas/) 페이지에서 |
| **B** | WebFetch | A와 다른 구현 — A가 robots에 막혀도 B는 통과할 때가 있음(11번가 실측) · 프롬프트로 요약·구조 파악 | 일부 도메인 자체 차단 · 인증 페이지 실패 |
| **C** | 인앱/실 브라우저 | SPA도 navigate+DOM 추출로 구동(롯데온) · 로그인 세션 활용 · 네트워크 XHR 관찰(E 겸용) | 일부 도메인 안전차단 — 로그인해도 안 풀림(차단=도메인 정책) |
| **D** | 우리 어댑터 코드 | 라이브 왕복검증된 엔드포인트 = 신뢰 최상 ① | ‘우리가 쓰는 API’만(전체 카탈로그 아님) |
| **E** | SPA 백엔드 JSON | 앱이 부르는 문서 데이터 직격(번들 분석·네트워크 패턴) | 번들에 baked면 없음 · 차단 도메인은 관찰 불가 · 실측 3마켓 모두 실패 |
| **F** | 기계판독 · 공식 GitHub | swagger/OpenAPI · sitemap · Wiki · 릴리즈노트 | 배포 안 했으면 없음 · ⚠️이름만 비슷한 남의 스펙 주의(naver swagger=Clova, 커머스 아님) |
| **G** | 사용자 복붙 | 최후 수단 | 사람 반복노동 → I로 대체하라 |
| **H** | 공식 외부 블로그 | 마켓이 문서를 별도 도메인에 둠(ESM=Tistory etapi.gmarket.com) · SSR이라 A로 관통 | 공지가 API문서와 섞임 → [METHOD]+URL 유무로 선별 |
| **I** | ★로그인 콘솔 스니펫 | 로그인 게이트+A·C 차단의 정답(11번가). 사용자가 로그인한 탭 콘솔에 1회 붙여넣기 → 같은출처 fetch로 전 페이지 자동 크롤 → 파일 다운로드 → Claude가 Read | 사용자 1회 개입 · ⚠️인코딩(EUC-KR) 먼저 확인 · 구조 사전파악 권장 |

### 3-1. 경로 I 표준 절차 (로그인 게이트 마켓의 정답 · 11번가 실증)

| 항목 | 규칙 |
|---|---|
| **★0. 문서유형부터 판별** | **스니펫 성패는 문서유형이 100% 결정한다(2026-07-17 실측).** **정적**(Docusaurus 등)→숨은 iframe에 렌더 후 DOM 덤프 = **157/157 한 번에 성공**(스스). **서버렌더+로그인**→같은출처 fetch = **26/26 성공**(11번가). **SPA**(Nuxt/Vue)→iframe·링크클릭·라우터 **3방식 전부 0/115 실패**(롯데온: 앱 `getApiServiceData`가 자멸). **⇒ SPA엔 스니펫 쓰지 말고 C(실크롬) 1API/1콜로 가라.** |
| **같은출처 + 세션** | `fetch(url,{credentials:'include'})` — 사용자 쿠키로 로그인 문서 접근(우리는 쿠키를 만지지 않음) |
| **클라이언트 렌더 본문** | 위젯이 JS로 그리는 스키마(스스 openapi-explorer)는 fetch로 영원히 못 봄 → **숨은 iframe에 실제 렌더**시키고 스켈레톤이 사라질 때까지 폴링 후 `textContent` 덤프 |
| **⚠️ 텍스트 캡** | 대형 페이지(상품등록 등)는 **캡에 걸려 잘린다**. 30,000자로는 부족 → **넉넉히(10만+) 잡아라**. 잘리면 그 페이지만 재수집. |
| **⚠️ 인코딩** | 옛 한국 사이트는 **EUC-KR**. `.text()`는 UTF-8로 읽어 **한글이 U+FFFD로 깨지고 복구 불가** → 반드시 `arrayBuffer()+new TextDecoder('euc-kr')` (11번가 1차 실패 원인) |
| **구조화 우선** | 페이지에 `var jsonData={...}` 같은 스펙 객체가 있으면 표 파싱 말고 **브레이스 워크로 통째 추출**(가장 정확) |
| **출력** | 채팅 붙여넣기 ❌ → **Blob 파일 다운로드** ✅ (용량 무제한, Claude가 다운로드 폴더를 직접 Read) |
| **자가진단** | `console.log(페이지수 + 제목목록)` → 숫자만 불러주면 성공/보완 즉시 판단 |
| **안전망** | ① 숫자 이상 → 스니펫만 고쳐 재붙여넣기(수초) ② 최후 → **Save all as HAR** / 웹페이지 전체 저장 |

### 3-2. 스니펫 템플릿 (복붙용 · 코드 정본 = 이 JSON)

> 실행 코드는 `프로그램/_시스템/scripts/api_ingest/snippets/*.js` 로도 자동 생성된다(gen_doc.py). 인앱 탭 `📋 스니펫 템플릿(복붙)` 에서 바로 복사 가능.

#### 0️⃣ 판별 (제일 먼저 · 1줄)

- **언제**: 스니펫 쓰기 전 **무조건 먼저**. 이 결과로 아래 어느 템플릿을 쓸지 갈린다.
- **근거·주의**: 정적/SSR이면 `staticLike:true` · SPA면 `spa:true`(→스니펫 금지, 경로 C) · `charset`이 euc-kr이면 디코더 필요
- **파일**: `scripts/api_ingest/snippets/probe.js`

```javascript
(async () => {
  const r = await fetch(location.href, { credentials: 'include' });
  const ct = r.headers.get('content-type') || '';
  const buf = await r.arrayBuffer();
  const guess = /charset=([\w-]+)/i.exec(ct);
  const cs = (guess ? guess[1] : 'utf-8').toLowerCase();
  const html = new TextDecoder(cs).decode(buf);
  const spa = /<app-root|<div id="?__nuxt|<div id="?root"?><\/div>/i.test(html) && html.length < 12000;
  const gen = (/<meta name="?generator"? content="?([^">]+)/i.exec(html) || [])[1] || '';
  console.log({
    charset: cs,
    length: html.length,
    generator: gen,
    spa,
    staticLike: !spa && html.length > 12000,
    nuxt: !!window.$nuxt,
    sitemap: location.origin + '/sitemap.xml',
    docLinks: document.querySelectorAll('a[href]').length
  });
  console.log('👉 staticLike=true → 템플릿1(정적) · charset=euc-kr 또는 로그인문서 → 템플릿2(서버렌더) · spa/nuxt=true → 스니펫 금지, 경로 C(실크롬)');
})();
```

#### 1️⃣ 정적 문서 (Docusaurus 등) — iframe 렌더

- **언제**: 판별에서 `staticLike:true` · 본문이 **클라이언트 위젯으로 렌더**되는 경우(스스 openapi-explorer)도 이걸로 뚫린다.
- **근거·주의**: 실측 **157/157 성공·에러 0**(스마트스토어). `SITEMAP`·`FILTER`만 마켓에 맞게 수정.
- **파일**: `scripts/api_ingest/snippets/static.js`

```javascript
(async () => {
  const SITEMAP = location.origin + '/docs/sitemap.xml';   // ← 마켓에 맞게
  const FILTER  = u => u.includes('/docs/') && !u.includes('/schemas/');  // ← 대상 선별
  const CAP     = 100000;   // ★30,000은 대형페이지 절단됨. 넉넉히.
  const sm = await (await fetch(SITEMAP)).text();
  const urls = [...sm.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]).filter(FILTER);
  console.log(`▶ ${urls.length}개 렌더 시작 — 약 ${Math.ceil(urls.length*2.5/60)}분. 탭 닫지 마세요.`);
  const ifr = document.createElement('iframe');
  ifr.style.cssText = 'position:fixed;left:-99999px;top:0;width:1280px;height:1000px;border:0';
  document.body.appendChild(ifr);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = [];
  for (let i = 0; i < urls.length; i++) {
    try {
      await new Promise((res, rej) => { const t = setTimeout(() => rej(new Error('timeout')), 20000);
        ifr.onload = () => { clearTimeout(t); res(); }; ifr.src = urls[i]; });
      let d, w = 0;
      while (w < 9000) { d = ifr.contentDocument;
        if (!d.querySelector('.openapi-skeleton,[class*=skeleton]') &&
            d.querySelector('[class*=schema],[class*=openapi],table,article')) break;
        await sleep(250); w += 250; }
      await sleep(250); d = ifr.contentDocument;
      const art = d.querySelector('article,main') || d.body;
      out.push({ url: urls[i], title: ((d.querySelector('h1')||{}).textContent||'').trim(),
        text: (art.textContent||'').replace(/\s+/g,' ').trim().slice(0, CAP),
        hydrated: !d.querySelector('[class*=skeleton]') });
    } catch (e) { out.push({ url: urls[i], error: String(e) }); }
    if (i % 10 === 9 || i === urls.length-1) console.log(`  ${i+1}/${urls.length} …`);
  }
  ifr.remove();
  const b = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(b);
  a.download = 'docs_static.json'; document.body.appendChild(a); a.click();
  console.log(`✅ ${out.length}페이지 · 렌더성공 ${out.filter(o=>o.hydrated).length} · 실패 ${out.filter(o=>o.error).length} → docs_static.json`);
})();
```

#### 2️⃣ 서버렌더 + 로그인 게이트 — 같은출처 fetch

- **언제**: 로그인해야 보이는 문서(11번가 셀러 개발가이드). **사용자가 로그인한 탭**에서 실행.
- **근거·주의**: 실측 **26/26 성공**(11번가). ⚠️`DEC`를 판별에서 나온 charset으로. `MATCH`만 마켓에 맞게.
- **파일**: `scripts/api_ingest/snippets/server.js`

```javascript
(async () => {
  const DEC   = new TextDecoder('euc-kr');   // ★판별 charset 그대로. utf-8이면 'utf-8'
  const MATCH = /OpenApiGuide\.tmall/i;      // ← 문서 URL 패턴
  const CAP   = 100000;
  const norm = h => { try { const u = new URL(h, location.href); u.hash=''; return u.href; } catch(e){ return null; } };
  const ok = h => { try { return new URL(h, location.href).origin === location.origin && MATCH.test(h); } catch(e){ return false; } };
  // 페이지에 구조화 스펙 객체가 있으면 통째로(표 파싱보다 정확) — 예: var jsonData = {...}
  const grabObj = (s, key) => { const i = s.indexOf(key); if (i < 0) return '';
    let j = s.indexOf('{', i); if (j < 0) return ''; let dep = 0;
    for (let k = j; k < s.length; k++) { const c = s[k];
      if (c === '{') dep++; else if (c === '}') { dep--; if (!dep) return s.slice(j, k+1); } } return ''; };
  let queue = [norm(location.href), ...[...document.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')).filter(ok).map(norm)];
  queue = [...new Set(queue.filter(Boolean))];
  const seen = new Set(), out = [], P = new DOMParser();
  while (queue.length && out.length < 300) {
    const url = queue.shift(); if (!url || seen.has(url)) continue; seen.add(url);
    try {
      const buf = await (await fetch(url, { credentials: 'include' })).arrayBuffer();
      const html = DEC.decode(buf);
      const d = P.parseFromString(html, 'text/html');
      [...d.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')).filter(ok).map(norm)
        .forEach(n => { if (n && !seen.has(n) && !queue.includes(n)) queue.push(n); });
      const tables = [...d.querySelectorAll('table')].map(t =>
        [...t.querySelectorAll('tr')].map(r => [...r.querySelectorAll('th,td')].map(c => (c.textContent||'').replace(/\s+/g,' ').trim())));
      out.push({ url, title: ((d.querySelector('title')||{}).textContent||'').trim(),
        spec: grabObj(html, 'var jsonData'),
        text: (d.body ? d.body.textContent : '').replace(/\s+/g,' ').trim().slice(0, CAP), tables });
    } catch (e) { out.push({ url, error: String(e) }); }
  }
  const b = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(b);
  a.download = 'docs_server.json'; document.body.appendChild(a); a.click();
  console.log(`✅ ${out.length}페이지 · 구조화spec ${out.filter(o=>o.spec).length} · 실패 ${out.filter(o=>o.error).length} → docs_server.json`);
  console.log('한글 확인:', (out[1]||out[0]||{}).text?.slice(0,60));
})();
```

#### 3️⃣ SPA (Nuxt/Vue/Angular) — ⛔ 스니펫 쓰지 마라

- **언제**: 판별에서 `spa:true` 또는 `nuxt:true`.
- **근거·주의**: 실측 **0/115 전멸**(롯데온). iframe·링크클릭·`$router.push` **3방식 모두 실패** — 앱이 fresh 컨텍스트에서 `getApiServiceData: null`로 자멸하고 링크 textContent도 빈값. **경로 C(실크롬)로 1API/1콜**이 유일한 길(느려도 그게 된다).
- **파일**: `scripts/api_ingest/snippets/spa.js`

```javascript
// ⛔ SPA 문서에는 콘솔 스니펫을 쓰지 않는다 (실측 0/115).
// → 경로 C(실크롬): 문서 URL로 navigate → 1초 대기 → DOM/테이블 추출 → 다음 API.
//   느리지만 앱 상태가 살아있어 유일하게 동작한다. (롯데온 109/115 이 방식으로 접수)
```

---

## 4. 마켓 × 경로 매트릭스

| 마켓 | A·자동읽기 | C·실브라우저 | D·코드 | 기타(E/F/H/I) | 채택 경로 | 접수 | 등급 |
|---|---|---|---|---|---|---|---|
| **쿠팡** | ✅ 완전(Next SSR) | ❌ 안전차단 | ✅ 운영핵심 | ❌ F 없음 | **A** | 108 | ①② |
| **롯데온** | ❌ SPA 빈껍데기 | ✅ 완전(Nuxt) | ✅ 운영핵심 | ❌ E baked | **C** | 115 | ①② |
| **옥션** | ✅ 완전 | ⚠️ 미시도 | ✅ 운영핵심 | ✅ H·Tistory | **A+H** | 117 | ①② |
| **G마켓** | ✅ 완전 | ⚠️ 미시도 | ✅ 운영핵심 | ✅ H·옥션공통 | **A+H** | 117 | ①② |
| **스마트스토어** | ✅ ★신규 /docs 관통 | ❌ 안전차단 | ✅ 핵심 35 | ❌ E실패·F헛다리 | **A-2** | 129 | ①② |
| **11번가** | ❌ robots 금지 | ❌ 안전차단 | ✅ 핵심 4 | ✅ ★I·콘솔 | **I** | 25 | ①② |

범례: ✅ 뚫림 · ⚠️ 부분/미시도 · ❌ 막힘. robots·안전차단은 우회하지 않는다.

---

## 5. 마켓별 전체 탭 계층 (실측)

### 쿠팡 — A · 자동읽기

- **상위탭**: 홈 · 시작하기 · API 문서 · FAQ · 공지
- **카테고리**: 상품(22) · 카테고리(6) · 브랜드(3) · 배송/주문(12) · 반품(7) · 교환(4) · 프로모션/쿠폰(21) · 물류(8) · 고객문의(6) · 정산(2) · Rocket Growth(9)
- **비고**: developers.coupang.com/ko/api · 11패밀리 · 엔드포인트 100 + 시작하기 가이드 8(HMAC·ID모델·Key발급 180일)
- **상세 탭**: 요약 · 상세 · 경로 · 요청 · 응답 · 오류

### 롯데온 — C · 실 브라우저

- **상위탭**: 이용안내 · API 개발가이드 · 공지사항 · FAQ
- **카테고리**: 거래처(12) · 상품속성(4) · 상품(25) · 판촉(6) · 주문(1) · 클레임(19) · 고객센터(11) · 배송(12) · 정산(6) · 공통(7) · 전시(4) · 스마트픽(8)
- **비고**: api.lotteon.com/apiService · 13 카테고리 · 접수 109/115 (판촉6=사이트 죽은페이지) · ?apiNo=N 이동+1초대기+1API/1콜
- **상세 탭**: 요청 · 응답 · 사유코드 · + 변경이력

### 옥션·G마켓(ESM) — A+H · 공식 블로그

- **상위탭**: 공지 · API가이드 · 상품 · 주문|배송 · 클레임 · 정산조회 · CS · 서비스 · 스타배송
- **카테고리**: 상품(44) · 주문|배송(8) · 클레임(20) · 정산조회(3) · CS(5) · 서비스(12) · 스타배송(25)
- **비고**: etapi.gmarket.com = Tistory 공식블로그 · 23 리프 · 글198 중 API 117([METHOD]+URL로 선별) · 호출host sa2.esmplus.com · 옥션/G마켓 공통(ssi A:/G:)
- **상세 탭**: Description · Request · Response · 사유코드

### 스마트스토어 — A-2 · 신규 정적 이관본

- **상위탭**: 소개 · 커머스API · 변경이력(GitHub) · 솔루션 가이드
- **카테고리**: 오퍼레이션(115) · 공용 구조체(14) · 랜딩(스킵)(42) · 인증·N배송·문의·상품·정산·주문·클레임
- **비고**: ★옛 /ko=Angular SPA+안전차단 ❌ / 신규 /docs/commerce-api/current=Docusaurus 정적 ✅ · 열쇠=/docs/sitemap.xml(171페이지·v2.82.0). 구조체=서버렌더 완전 / 오퍼레이션 본문=클라 렌더(스켈레톤)→구조체 참조
- **상세 탭**: method·path · 설명 · 응답/에러코드 · 구조체: 필드·Possible values·예시JSON

### 11번가 — I · 로그인 콘솔 스니펫

- **상위탭**: 서비스 소개 · API 관리 · 개발 가이드 · 고객센터
- **카테고리**: 상품(8) · 주문(8) · 취소/반품/교환(3) · 해외물류(2) · 셀러기획전(1) · 긴급알리미(1)
- **비고**: openapi.11st.co.kr robots Disallow(A 금지)·C 안전차단 → I로 돌파. 셀러메뉴=?categoryNo=N(39~151) · ★페이지에 var jsonData=완전 스펙(information·fields·fieldEnums·sampleCodes) · ⚠️EUC-KR
- **상세 탭**: information(명·method·URL) · 요청/응답 필드계층 · fieldEnums 코드값 · 샘플코드

---

## 6. 플레이북 — 새 마켓 접수 시도 순서 (★경험 기반 최적 순서)

> 원리: 싸고 빠르고 사람 개입 없는 것부터. 각 단계는 판별 1가지로 다음 갈래가 결정된다. 뚫리면 그 자리에서 끝.

0. **정확한 문서 URL 확보** — ★사용자에게 요청. **옛 포털/신규 포털이 공존할 수 있다 — 최신 URL을 받아라(스스가 이걸로 갈림)
1. **A · 자동읽기(fetch raw)**로 index 요청 — 본문·표 나오면 **A 성공(SSR) → 끝 · 껍데기만이면 SPA → 다음
2. **★A-2 · 신규 정적 이관본 판별** — generator meta(Docusaurus/Redoc/Mintlify)·/docs·/developers 탐색 + **sitemap.xml**로 전 페이지 열거 → **전량 관통 → 끝
3. **robots.txt** 확인 — `Disallow:/` 면 A·B 금지(우회 절대 안 함) → 7로
4. **H · 공식 외부 블로그** — 마켓명+API 별도 도메인·Tistory. SSR이면 **A로 전량 → 끝
5. **F · 기계판독/공식 GitHub** — swagger·Wiki·릴리즈노트 있으면 **1파일로 전량 → 끝 · ⚠️남의 스펙 혼동주의
6. **C · 실 브라우저** — 정상 렌더면 **DOM 추출 → 끝(1페이지/1콜·렌더 대기) · ‘안전차단’이면 다음
7. **★I · 로그인 콘솔 스니펫** — B로 구조·인코딩 사전파악 → 스니펫 1회 → 자동 크롤 → 파일 다운로드 → Claude Read **→ 끝
8. **D · 우리 코드** + **G · 붙여넣기** — 전부 막히면 운영핵심 라이브검증(①) + 롱테일 붙여넣기(부분)

판별 5요소 : **① SSR인가?** → **② 신규 정적 이관본이 있나?** → **③ robots Disallow인가?** → **④ 공식 블로그·스펙이 있나?** → **⑤ 크롬 안전차단인가?** → (전부 막히면) **I**. 사람 개입 비용 : A/A-2/H/F/C(0) < I(붙여넣기 1회) < G(반복노동 ❌). **I가 G를 대체한다 — 복붙 노가다는 이제 안 한다.**

---

## 7. 미확보 · 후속 과제

- **스마트스토어 오퍼레이션 본문 필드**: openapi-explorer 위젯이 클라이언트 렌더 → 서버HTML엔 스켈레톤. 현재 구조체 14개로 보완. 완전화하려면 I 경로(콘솔에서 렌더 후 DOM 덤프) 또는 원본 OpenAPI 스펙 확보.
- **11번가 `categoryNo=67`** 1건 jsonData 브레이스 파싱 실패 → 재수집 시 보완.
- **롯데온 판촉 6**: 사이트 죽은 페이지(우리 문제 아님). 사이트 복구 시 재시도.
- **H 일반화**: 신규 마켓(위메프·티몬·카카오·인터파크 등)이 별도 공식 블로그/정적 포털을 두는지 조사.

---

## 8. 참고 파일

- 지도 데이터(SOT): `프로그램/_시스템/webapp/data/marketplace_api_map.json` — 611 apis(쿠팡108·옥션117·G마켓117·롯데온115·스스129·11번가25)
- 검증기: `프로그램/_시스템/webapp/marketplace_api_map.py` (완성게이트: st∈{ok,code} → req·res·fields·success 필수)
- 서빙: `/marketplace-guide/map-data.json` · `/marketplace-guide/ingest-paths.json` · 화면: `/marketplace-guide/map`
- 마켓 프로파일(코드 근거): `docs/markets/{coupang,smartstore,eleven11,auction,gmarket,lotteon}.yaml`
- 접수 이력(메모리): `project_marketplace_api_map_sot`

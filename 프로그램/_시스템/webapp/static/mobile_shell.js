/**
 * 모바일 앱 껍데기 — PC 화면(157개) 위에 뒤로가기·하단 탭·안내 띠를 얹는다 (Task 7).
 *
 * 🔴 PC 템플릿은 안 고친다(base.html 의 주입 몇 줄 제외). 판단은 브라우저가 한다.
 *    켜지는 조건: 홈 화면에 설치된 앱으로 실행 + 화면 폭 768px 이하.
 *    → 일반 PC 브라우저에서는 아무 일도 일어나지 않는다.
 *
 * 폰 전용 화면(/mobile/*)은 자기 탭(templates/mobile/_tabbar.html)을 이미 갖고
 * 있으므로 여기서는 건드리지 않는다 — 탭이 두 개 생기면 안 된다.
 *
 * 🔴 탭 목록을 여기에 적지 않는다 — 원천은 서버의 PHONE_NATIVE_ROWS 하나뿐이고,
 *    base.html 이 ms_shell_data() 를 <script type="application/json" id="ms-tabs-data">
 *    블록으로 심어 준다(admin 여부까지 서버가 이미 반영). 여기 주소를 적으면
 *    「같은 사실 두 곳에 적기」가 재발한다 — 시험 test_탭_주소는_JS에_직접_적지_않는다.
 *    [3단계] 같은 JSON 의 ready(MOBILE_READY_URLS)로 폰 대응이 끝난 PC 화면을
 *    알아보고 그 화면에서는 노란 안내 띠를 생략한다 — 이 주소도 여기 안 적는다.
 */
(function () {
  'use strict';

  function isInstalledApp() {
    return window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
  }

  function isNarrow() {
    return window.matchMedia('(max-width: 768px)').matches;
  }

  function isPhoneNativePage() {
    return window.location.pathname.indexOf('/mobile') === 0;
  }

  function readShellData() {
    // [3단계] JSON 은 {tabs, ready, readyPaths} 한 덩어리다 — tabs=하단 탭
    // (PHONE_NATIVE_ROWS), ready=폰 대응이 끝난 PC 주소(MOBILE_READY_URLS,
    // same_screen 으로 다듬은 모양), readyPaths=쿼리가 데이터 필터일 뿐인 화면의
    // 경로(MOBILE_READY_PATH_ONLY, same_route 모양) — /policies?brand=X 부류.
    var empty = { tabs: [], ready: [], readyPaths: [] };
    var el = document.getElementById('ms-tabs-data');
    if (!el) return empty;
    try {
      var d = JSON.parse(el.textContent);
      if (!d || typeof d !== 'object') return empty;
      return {
        tabs: Array.isArray(d.tabs) ? d.tabs : [],
        ready: Array.isArray(d.ready) ? d.ready : [],
        readyPaths: Array.isArray(d.readyPaths) ? d.readyPaths : []
      };
    } catch (e) {
      return empty;   // JSON 이 깨져도 화면은 살린다 — 탭·띠 생략만 안 붙는다
    }
  }

  /** 서버 same_screen(mobile_shell.py)과 **같은 다듬기** — #조각을 떼고 끝 빗금을
   *  떼되, 물음표 뒤는 남긴다(주문 관리는 탭 4개가 서로 다른 화면이다).
   *  🔴 여기 규칙을 더하거나 빼지 말 것 — 서버와 어긋나면 에러 없이 안내 띠만
   *  조용히 잘못 뜬다(배지의 그 조용한 실패와 같은 부류). */
  function sameScreen(path, search) {
    var p = path.split('#')[0].replace(/\/+$/, '') || '/';
    return p + (search || '');
  }

  /** 폰 대응이 끝난 화면인가 — 두 갈래.
   *  ① ready(정확 일치): 쿼리까지 그대로 비교 — 탭(?tab=)마다 템플릿이 갈리는
   *     화면이 있어 기본은 이쪽이다.
   *  ② readyPaths(경로 일치): 서버가 「쿼리는 데이터 필터일 뿐」이라고 opt-in 한
   *     화면만 — /policies?brand=아무값 처럼 열거 불가능한 쿼리를 흡수한다.
   *  🔴 ②를 전역으로 만들지 말 것 — /orders 는 탭마다 다른 템플릿이라, 경로만
   *     보면 전환 안 된 탭에도 띠가 사라진다(거짓 「폰 대응 완료」). */
  function isReadyScreen(ready, readyPaths) {
    if (ready.indexOf(sameScreen(window.location.pathname, window.location.search)) !== -1) return true;
    return readyPaths.indexOf(sameScreen(window.location.pathname, '')) !== -1;
  }

  function screenTitle() {
    // 첫 h1 이 숨겨진 화면이 있을 수 있다(모달 제목 등) — 보이는 h1 만 집는다.
    // 길이는 여기서 안 자른다 — .ms-title 의 ellipsis 가 화면 폭에 맞춰 자른다.
    var hs = document.querySelectorAll('h1');
    for (var i = 0; i < hs.length; i++) {
      var t = hs[i].textContent.trim();
      if (t && hs[i].offsetParent !== null) return t;
    }
    return (document.title || '모음전').split('·')[0].split('|')[0].trim();
  }

  function buildTopbar() {
    var bar = document.createElement('div');
    bar.className = 'ms-topbar';

    var back = document.createElement('button');
    back.className = 'ms-back';
    back.type = 'button';
    back.setAttribute('aria-label', '뒤로');
    back.textContent = '‹';
    back.addEventListener('click', function () {
      // 설치된 앱은 자기 세션 이력만 갖는다 — 첫 화면(length 1)일 때만 폰 홈으로.
      if (window.history.length > 1) window.history.back();
      else window.location.href = '/mobile';
    });

    var title = document.createElement('div');
    title.className = 'ms-title';
    title.textContent = screenTitle();

    bar.appendChild(back);
    bar.appendChild(title);
    return bar;
  }

  function buildNotice() {
    var n = document.createElement('div');
    n.className = 'ms-notice';
    n.textContent = 'ⓘ PC용 화면입니다 · 폰을 옆으로 눕히면 보기 편합니다';
    return n;
  }

  function buildTabbar(rows) {
    if (!rows.length) return null;
    var nav = document.createElement('nav');
    nav.className = 'ms-tabbar';
    nav.setAttribute('role', 'navigation');
    nav.setAttribute('aria-label', '하단 탭');
    rows.forEach(function (t) {
      var a = document.createElement('a');
      // PC 주소는 어느 탭의 화면도 아니다 — on 은 안 붙인다(_tabbar.html 과 같은 판정:
      // active_tab_key 는 PHONE_NATIVE_ROWS 밖 주소에 None 을 준다).
      a.className = 'ms-tab';
      a.href = t.url;
      var ic = document.createElement('span');
      ic.className = 'ms-tab-icon';
      ic.setAttribute('aria-hidden', 'true');
      ic.textContent = t.tab.icon;
      a.appendChild(ic);
      a.appendChild(document.createTextNode(t.tab.label));
      nav.appendChild(a);
    });
    return nav;
  }

  /** 최근 본 화면을 폰에만 저장한다(Task 7B) — 서버로는 아무것도 보내지 않는다.
   *  최대 5개, 같은 주소는 지우고 맨 앞으로. 키 'ms-recent' 는 홈(home.html)이 읽는다
   *  — 두 파일의 키가 같아야 한다(test_shell_pages.py 가 글자 그대로 묶는다).
   *  ★ mount() 에서만 부른다 = 껍데기가 붙는 PC 대체 화면에서만 기록한다.
   *    폰 전용 화면(홈·스캔·재고)은 하단 탭 한 번이면 가니, 기록하면 5칸이 늘
   *    그 화면들로 차서 정작 다시 찾기 어려운 PC 화면이 밀려난다. */
  function rememberPage() {
    try {
      var url = window.location.pathname + window.location.search;
      var item = { url: url, title: screenTitle() };
      var list = JSON.parse(localStorage.getItem('ms-recent') || '[]');
      if (!Array.isArray(list)) list = [];
      list = list.filter(function (it) { return it && it.url !== url; });
      list.unshift(item);
      localStorage.setItem('ms-recent', JSON.stringify(list.slice(0, 5)));
    } catch (e) { /* 저장 실패(시크릿 모드 등)로 화면을 못 살리게 두지 않는다 */ }
  }

  function mount() {
    if (document.querySelector('.ms-tabbar')) return;   // 두 번 붙이지 않는다
    var data = readShellData();
    // .ms-on 접두 CSS(상단바·안내 띠)가 살아나는 스위치 — html 에 붙인다.
    document.documentElement.classList.add('ms-on');
    var body = document.body;
    // 바닥 여백은 기존 body.m-body 규칙을 재사용한다 — 같은 여백을 두 규칙에 적으면
    // 탭 높이가 바뀔 때 한쪽만 고쳐지는 사고가 난다(mobile_shell.css 의 결정).
    body.classList.add('m-body');
    // [3단계] 폰 대응이 끝난 화면(ready)에는 'PC용 화면' 띠를 안 붙인다.
    // 주소 목록은 서버 JSON 에서만 온다 — 여기 주소를 적으면 원천이 둘로 갈라진다.
    if (!isReadyScreen(data.ready, data.readyPaths)) body.insertBefore(buildNotice(), body.firstChild);
    body.insertBefore(buildTopbar(), body.firstChild);
    var tb = buildTabbar(data.tabs);
    if (tb) body.appendChild(tb);
    rememberPage();
  }

  function start() {
    if (!isInstalledApp() || !isNarrow() || isPhoneNativePage()) return;
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mount);
    } else {
      mount();
    }
  }

  start();
})();

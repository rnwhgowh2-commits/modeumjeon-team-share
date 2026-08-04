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
 *    base.html 이 ms_tab_rows() 를 <script type="application/json" id="ms-tabs-data">
 *    블록으로 심어 준다(admin 여부까지 서버가 이미 반영). 여기 주소를 적으면
 *    「같은 사실 두 곳에 적기」가 재발한다 — 시험 test_탭_주소는_JS에_직접_적지_않는다.
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

  function readTabRows() {
    var el = document.getElementById('ms-tabs-data');
    if (!el) return [];
    try {
      var rows = JSON.parse(el.textContent);
      return Array.isArray(rows) ? rows : [];
    } catch (e) {
      return [];   // JSON 이 깨져도 화면은 살린다 — 탭만 안 붙는다
    }
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

  function mount() {
    if (document.querySelector('.ms-tabbar')) return;   // 두 번 붙이지 않는다
    // .ms-on 접두 CSS(상단바·안내 띠)가 살아나는 스위치 — html 에 붙인다.
    document.documentElement.classList.add('ms-on');
    var body = document.body;
    // 바닥 여백은 기존 body.m-body 규칙을 재사용한다 — 같은 여백을 두 규칙에 적으면
    // 탭 높이가 바뀔 때 한쪽만 고쳐지는 사고가 난다(mobile_shell.css 의 결정).
    body.classList.add('m-body');
    body.insertBefore(buildNotice(), body.firstChild);
    body.insertBefore(buildTopbar(), body.firstChild);
    var tb = buildTabbar(readTabRows());
    if (tb) body.appendChild(tb);
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

// crawl_log.js — 실시간 크롤 대시보드 (마스터–디테일: 좌측 모음전 레일 + 우측 상세)
//  [2026-06-14] 멀티 모음전 큐 + 일시중지/중지 대응(1단계, 시안 4번).
//   - 'moum-crawl-log' 이벤트(ext_bridge.js 방출)를 모음전(bundle)별로 분리 저장.
//   - 좌측 레일: 진행중●/대기⏳/완료✓ 모음전 목록(클릭 전환, 대기는 × 로 취소).
//   - 우측 상세: 선택한 모음전의 동시창·CPU·메모리 게이지 + 소싱처 카드 + 로그.
//   - 헤더: ⏸일시중지/▶재개 · ■중지 (둘 다 창 닫기). MoumExt.pause/resume/stopCrawl 호출.
// IIFE — 전역 오염 최소. window.addEventListener('moum-crawl-log', ...) 1회 등록.
(function () {
  'use strict';

  // ── 소싱처 메타 ─────────────────────────────────────────────────
  var SOURCE_LABELS = {
    lemouton:    '르무통 공홈',
    ssf:         'SSF',
    ssg:         'SSG',
    ss_lemouton: '스마트스토어',
    musinsa:     '무신사',
    lotteon:     '롯데온',
  };
  var SOURCE_ORDER = ['lemouton', 'ssf', 'ssg', 'ss_lemouton', 'musinsa', 'lotteon'];

  // ── 내부 상태 (모음전별) ─────────────────────────────────────────
  // bundles[code] = {
  //   code, label, status:'run'|'wait'|'pause'|'done'|'stop',
  //   total, done, startTs, metrics:{concurrency,cap,active,cpu,mem,avgSec},
  //   sources: { sk: { status:'wait'|'run'|'done', done, total, expanded,
  //                    logs:[{ts,level,msg,url,lineId,surf,buy}] } },
  //   lineIndex: { lineId: {sk, idx} },  // item-final 제자리 갱신용
  //   finishMsg, stopped,
  // }
  var bundles = {};
  var order = [];          // 표시 순서(진행중→대기→완료). 'queue' 이벤트로 갱신.
  var selected = null;     // 우측 상세에 표시할 모음전 code
  var anyRunning = false;
  var globalStartTs = 0;
  var _elapsedTimer = null;

  function bLabel(code) {
    var b = bundles[code];
    return (b && b.label) || code || '';
  }

  function getBundle(code) {
    if (!code) code = '_';
    if (!bundles[code]) {
      bundles[code] = {
        code: code, label: code, status: 'run', total: 0, done: 0, doneCount: 0, startTs: Date.now(),
        metrics: { concurrency: 0, cap: 0, active: 0, cpu: null, mem: null, avgSec: null },
        sources: {}, lineIndex: {}, finishMsg: '', stopped: false,
      };
      if (order.indexOf(code) < 0) order.push(code);
    }
    return bundles[code];
  }

  function getSource(b, sk) {
    if (!b.sources[sk]) {
      b.sources[sk] = { status: 'wait', done: 0, ok: 0, fail: 0, total: null, expanded: false, logs: [] };
    }
    return b.sources[sk];
  }

  // ── CSS 주입 (1회) ───────────────────────────────────────────────
  var CSS_ID = 'moum-crawl-log-css';
  function injectCSS() {
    if (document.getElementById(CSS_ID)) return;
    var style = document.createElement('style');
    style.id = CSS_ID;
    style.textContent = [
      '#mcl-panel {',
      // [2026-06-19] 폰트·크기 전체 1.5× + 좌측 확장. transform scale(우상단 기준)로 우측 고정·좌측 확장.
      //   (zoom은 좌상단 기준이라 right:0 패널이 화면 밖으로 밀림 → transform 사용.)
      //   height calc(100vh/1.5) × scale 1.5 = 화면상 100vh.
      '  position:fixed; top:0; right:0; width:520px; height:calc(100vh / 1.5);',
      '  transform:scale(1.5); transform-origin:top right;',
      '  background:#141B22; color:#CBD5E1; z-index:9000;',
      '  display:flex; flex-direction:column; font-family:"Pretendard",sans-serif;',
      '  box-shadow:-8px 0 32px rgba(0,0,0,.45); transition:transform .25s ease;',
      '}',
      '#mcl-panel.mcl-hidden { transform:scale(1.5) translateX(100%); pointer-events:none; }',

      '#mcl-header { padding:14px 16px 12px; border-bottom:1px solid #25303b; flex-shrink:0; }',
      '#mcl-header-top { display:flex; align-items:center; gap:7px; margin-bottom:10px; }',
      '#mcl-title { font-size:15px; font-weight:800; color:#F2F4F6; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }',
      '#mcl-elapsed { font-family:ui-monospace,monospace; font-size:12px; color:#8B95A1; flex-shrink:0; }',
      '.mcl-cbtn {',
      '  background:#25303b; border:1px solid #3A455C; cursor:pointer; color:#E6E9EF;',
      '  height:26px; border-radius:7px; display:inline-flex; align-items:center; justify-content:center;',
      '  font-size:12px; font-weight:700; padding:0 9px; gap:4px; flex-shrink:0; transition:.12s; line-height:1;',
      '}',
      '.mcl-cbtn:hover { background:#313A4D; border-color:#54627D; color:#fff; }',
      '.mcl-cbtn.pause { color:#FDE68A; border-color:#5A4A1E; background:#2A2410; }',
      '.mcl-cbtn.pause:hover { background:#3a3216; }',
      '.mcl-cbtn.resume { color:#86EFAC; border-color:#1c3a2b; background:#0f1a14; }',
      '.mcl-cbtn.stop { color:#FCA5A5; border-color:#5A1E1E; background:#2A1010; }',
      '.mcl-cbtn.stop:hover { background:#3a1616; }',
      '.mcl-cbtn.sq { width:30px; padding:0; }',
      '#mcl-close-btn { display:none; }',

      '#mcl-overall { display:flex; align-items:center; gap:10px; }',
      '#mcl-overall-ring { width:34px; height:34px; border-radius:50%; flex-shrink:0; background:conic-gradient(#3182F6 0deg,#25303b 0deg); display:flex; align-items:center; justify-content:center; }',
      '#mcl-overall-ring > i { width:25px; height:25px; border-radius:50%; background:#141B22; display:flex; align-items:center; justify-content:center; font-size:8.5px; font-weight:800; color:#CFE0FF; font-style:normal; }',
      '#mcl-overall-label { font-size:12px; color:#8B95A1; white-space:nowrap; }',
      '#mcl-overall-cnt { font-family:ui-monospace,monospace; font-size:13px; font-weight:800; color:#3182F6; }',
      '#mcl-overall-bar { flex:1; height:5px; background:#25303b; border-radius:3px; overflow:hidden; }',
      '#mcl-overall-fill { height:100%; background:#3182F6; border-radius:3px; transition:width .3s; width:0%; }',
      '#mcl-finish-summary {',
      '  display:none; margin-top:10px; padding:9px 12px; background:#0E3A6A;',
      '  border-radius:8px; font-size:13px; font-weight:700; color:#93C5FD; border-left:4px solid #3182F6;',
      '}',
      '#mcl-finish-summary.stopped { background:#3f1d1d; color:#fca5a5; border-left-color:#f87171; }',
      '#mcl-fd { display:grid; grid-template-columns:1fr 1fr; gap:18px; }',
      '#mcl-fd .fd-row { display:flex; justify-content:space-between; align-items:baseline; padding:4px 2px; font-weight:700; line-height:1.5; }',
      '#mcl-fd .fd-row.top { font-size:14px; border-bottom:1px solid #214a78; padding-bottom:6px; margin-bottom:3px; }',
      '#mcl-fd .fd-row.sub { padding-left:10px; font-size:12.5px; font-weight:600; }',
      '#mcl-fd .fd-row .k { color:#AFCBEC; } #mcl-fd .fd-row .v { font-variant-numeric:tabular-nums; font-weight:800; }',
      '#mcl-fd .fd-det { color:#9FC3FF; text-decoration:underline; text-underline-offset:2px; font-size:10px; cursor:pointer; margin-left:5px; }',
      '#mcl-fd .fd-stop { color:#fca5a5; font-size:11px; font-weight:700; margin-top:5px; }',
      '#mcl-fd .gn{color:#34D399} #mcl-fd .rd{color:#F87171} #mcl-fd .gy{color:#9aa6b2} #mcl-fd .bl{color:#7FB6FF}',

      /* 분할: 좌측 레일 + 우측 상세 */
      '#mcl-split { flex:1; display:flex; overflow:hidden; min-height:0; }',
      '#mcl-rail { width:158px; flex-shrink:0; border-right:1px solid #25303b; overflow-y:auto; padding:8px 0; }',
      '#mcl-rail::-webkit-scrollbar { width:4px; } #mcl-rail::-webkit-scrollbar-thumb { background:#25303b; border-radius:4px; }',
      '#mcl-rail-head { font-size:10px; font-weight:800; color:#4E5968; letter-spacing:.5px; padding:2px 12px 6px; }',
      '.mcl-rb {',
      '  padding:8px 10px 8px 12px; border-left:3px solid transparent; cursor:pointer; transition:.1s;',
      '  display:flex; align-items:flex-start; gap:7px;',
      '}',
      '.mcl-rb:hover { background:#18212b; }',
      '.mcl-rb.sel { background:#14233a; border-left-color:#3182F6; }',
      '.mcl-rb-dot { width:8px; height:8px; border-radius:50%; margin-top:4px; flex-shrink:0; }',
      '.mcl-rb-dot.run { background:#3182F6; box-shadow:0 0 0 3px rgba(49,130,246,.2); }',
      '.mcl-rb-dot.pause { background:#FBBF24; }',
      '.mcl-rb-dot.wait { background:#4B5563; }',
      '.mcl-rb-dot.done { background:#34D399; }',
      '.mcl-rb-dot.stop { background:#F87171; }',
      '.mcl-rb-body { flex:1; min-width:0; }',
      '.mcl-rb-name { font-size:12px; font-weight:700; color:#CBD5E1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }',
      '.mcl-rb.sel .mcl-rb-name { color:#fff; }',
      '.mcl-rb-sub { font-size:10px; margin-top:2px; }',
      '.mcl-rb-sub.run { color:#60A5FA; } .mcl-rb-sub.pause { color:#FBBF24; }',
      '.mcl-rb-sub.wait { color:#6B7684; } .mcl-rb-sub.done { color:#34D399; } .mcl-rb-sub.stop { color:#F87171; }',
      '.mcl-rb-x { color:#4E5968; cursor:pointer; font-size:14px; line-height:1; padding:2px 3px; flex-shrink:0; }',
      '.mcl-rb-x:hover { color:#F87171; }',
      '.mcl-rb-goto { color:#4E5968; cursor:pointer; font-size:13px; line-height:1; padding:3px 5px; margin-top:1px; flex-shrink:0; border-radius:6px; }',
      '.mcl-rb-goto:hover { color:#9FC3FF; background:#1D2A3A; }',
      '.mcl-rb-minibar { height:3px; background:#25303b; border-radius:2px; overflow:hidden; margin-top:5px; }',
      '.mcl-rb-minibar > i { display:block; height:100%; border-radius:2px; transition:width .3s; }',

      '#mcl-detail { flex:1; display:flex; flex-direction:column; min-width:0; overflow:hidden; }',

      /* 게이지 */
      '#mcl-gauges { padding:11px 16px; border-bottom:1px solid #25303b; flex-shrink:0; }',
      '.mcl-gauge-row { margin-bottom:8px; } .mcl-gauge-row:last-child { margin-bottom:0; }',
      '.mcl-gauge-head { display:flex; align-items:center; gap:8px; margin-bottom:4px; }',
      '.mcl-gauge-lbl { font-size:11.5px; font-weight:700; color:#8B95A1; }',
      '.mcl-gauge-val { margin-left:auto; font-family:ui-monospace,monospace; font-size:11px; color:#CBD5E1; }',
      '.mcl-gauge-track { height:6px; background:#25303b; border-radius:4px; overflow:hidden; }',
      '.mcl-gauge-fill { height:100%; border-radius:4px; transition:width .35s; width:0%; }',
      '.mcl-gauge-fill.conc { background:#3182F6; } .mcl-gauge-fill.cpu { background:#F97316; } .mcl-gauge-fill.mem { background:#8B5CF6; }',

      '#mcl-cards-wrap { flex:1; overflow-y:auto; padding:10px 14px 16px; min-height:0; }',
      '#mcl-cards-wrap::-webkit-scrollbar { width:4px; } #mcl-cards-wrap::-webkit-scrollbar-thumb { background:#25303b; border-radius:4px; }',
      '#mcl-empty { color:#4E5968; font-size:12px; text-align:center; padding:30px 10px; }',

      '.mcl-card { background:#1A2332; border:1px solid #25303b; border-radius:8px; margin-bottom:8px; overflow:hidden; }',
      '.mcl-card-header { display:flex; align-items:center; gap:8px; padding:9px 12px 8px; }',
      '.mcl-card-name { font-size:12px; font-weight:700; color:#CBD5E1; min-width:76px; }',
      '.mcl-card-tag { font-size:10px; font-weight:800; padding:2px 7px; border-radius:10px; flex-shrink:0; }',
      '.mcl-card-tag.wait { background:#25303b; color:#8B95A1; } .mcl-card-tag.run { background:#1B3A6A; color:#60A5FA; }',
      '.mcl-card-tag.done { background:#064E3B; color:#34D399; }',
      '.mcl-card-cnt { font-family:ui-monospace,monospace; font-size:11px; color:#8B95A1; margin-left:auto; flex-shrink:0; }',
      '.mcl-card-cnt .mcl-c-reg { color:#E5EAF0; font-weight:800; }',
      '.mcl-card-cnt .mcl-vdiv { color:#3a4654; margin:0 3px; }',
      '.mcl-card-cnt .mcl-c-ok { color:#34D399; font-weight:800; }',
      '.mcl-card-cnt .mcl-c-no { color:#F87171; font-weight:800; text-decoration:underline; text-underline-offset:2px; cursor:pointer; margin-left:4px; }',
      '.mcl-card-tag.mcl-hidden { display:none; }',
      '.mcl-card-toggle { font-size:11px; color:#60A5FA; background:none; border:none; cursor:pointer; padding:0 0 0 8px; flex-shrink:0; white-space:nowrap; }',
      '.mcl-card-toggle:hover { color:#93C5FD; }',
      '.mcl-card-bar-wrap { height:4px; background:#25303b; margin:0 12px 8px; border-radius:3px; overflow:hidden; }',
      '.mcl-card-bar-fill { height:100%; border-radius:3px; transition:width .3s; width:0%; }',
      '.mcl-card-bar-fill.wait { background:#4B5563; } .mcl-card-bar-fill.run { background:#38bdf8; } .mcl-card-bar-fill.done { background:#4ADE80; }',
      '.mcl-card-logs { border-top:1px solid #25303b; padding:6px 12px 8px; max-height:200px; overflow-y:auto; }',
      '.mcl-card-logs::-webkit-scrollbar { width:3px; } .mcl-card-logs::-webkit-scrollbar-thumb { background:#25303b; border-radius:3px; }',
      '.mcl-card-logs.mcl-hidden { display:none; }',
      '.mcl-d8-head { display:grid; grid-template-columns:60px 1fr 92px 108px; gap:8px; padding:3px 4px 5px; border-bottom:1px solid #2a3744; font-size:9.5px; color:#6B7A8C; font-weight:800; }',
      '.mcl-d8-head span:nth-child(3), .mcl-d8-head span:nth-child(4) { text-align:right; }',
      '.mcl-d8-row { display:grid; grid-template-columns:60px 1fr 92px 108px; gap:8px; padding:7px 4px; border-bottom:1px solid #1c2630; font-size:11.5px; align-items:start; line-height:1.45; }',
      /* 타입 배지 — 시안 A 칩·파스텔 */
      '.mcl-d8-badge { font-size:10px; font-weight:700; padding:2px 6px; border-radius:5px; white-space:nowrap; line-height:1.5; display:inline-block; }',
      '.mcl-d8-badge.t-dan { background:#1e2a44; color:#93C5FD; }',
      '.mcl-d8-badge.t-deal { background:#1a2e1a; color:#6EE7B7; }',
      '.mcl-d8-badge.t-none { background:#252b35; color:#6B7A8C; }',
      // [2026-06-19 시안A] 상품명 전체표시(줄바꿈) + URL 링크(↗). 기존 말줄임(nowrap/ellipsis) 제거.
      '.mcl-d8-nm { color:#CBD5E1; font-weight:600; white-space:normal; line-height:1.34; min-width:0; }',
      '.mcl-d8-nm a { color:#7FB4FF; text-decoration:none; }',
      '.mcl-d8-nm a:hover { text-decoration:underline; }',
      '.mcl-d8-nm .mcl-d8-ext { color:#4D9FFF; font-size:9.5px; margin-left:2px; white-space:nowrap; }',
      '.mcl-d8-row.fail .mcl-d8-nm { color:#F87171; }',
      '.mcl-d8-surf { color:#8B95A1; text-decoration:line-through; text-align:right; font-variant-numeric:tabular-nums; }',
      '.mcl-d8-buy { text-align:right; font-weight:800; color:#7FB6FF; font-variant-numeric:tabular-nums; }',
      '.mcl-d8-buy.clk { cursor:pointer; text-decoration:underline; text-underline-offset:2px; }',
      '.mcl-d8-buy.fail { color:#F87171; text-decoration:none; font-weight:700; }',
      '.mcl-d8-buy.calc { color:#6B7A8C; font-weight:600; }',
      '#mcl-rc-ov { position:fixed; inset:0; background:rgba(8,12,18,.55); z-index:9100; display:flex; align-items:center; justify-content:center; }',
      '#mcl-rc-ov.mcl-hidden { display:none; }',
      // [2026-06-19] fx 영수증 팝업 2배 확대(폰트·패딩·폭·라운드 비율 유지) — 작아서 안 보이던 것 개선.
      '#mcl-rc { width:640px; max-width:92vw; background:#161E28; border:1px solid #2a3744; border-radius:24px; box-shadow:0 28px 72px rgba(0,0,0,.6); color:#E5EAF0; overflow:hidden; font-family:"Pretendard",sans-serif; }',
      '#mcl-rc .rc-h { display:flex; align-items:center; gap:14px; padding:24px 28px; border-bottom:1px solid #25303b; }',
      '#mcl-rc .rc-fx { background:#3182F6; color:#fff; font-size:19px; font-weight:800; padding:4px 14px; border-radius:10px; }',
      '#mcl-rc .rc-t { font-size:25px; font-weight:800; } #mcl-rc .rc-x { margin-left:auto; cursor:pointer; color:#8B95A1; font-size:32px; }',
      '#mcl-rc .rc-b { padding:24px 30px; }',
      '#mcl-rc .rc-prod { font-size:22px; color:#9aa6b2; margin-bottom:16px; }',
      '#mcl-rc .rc-r { display:flex; justify-content:space-between; align-items:baseline; padding:9px 0; font-size:24px; }',
      '#mcl-rc .rc-r.surf { font-weight:700; } #mcl-rc .rc-r.surf .rc-v { color:#CBD5E1; }',
      '#mcl-rc .rc-r.step { font-size:22px; color:#AFCBEC; padding-left:14px; } #mcl-rc .rc-r.step .rc-v { color:#34D399; }',
      '#mcl-rc .rc-div { height:1px; background:#25303b; margin:14px 0; }',
      '#mcl-rc .rc-r.final { font-size:28px; font-weight:800; } #mcl-rc .rc-r.final .rc-v { color:#7FB6FF; }',
      '#mcl-rc .rc-v { font-variant-numeric:tabular-nums; }',
      '#mcl-rc .rc-note { font-size:18px; color:#6B7A8C; margin-top:16px; text-align:center; }',
      '.mcl-log-line { display:flex; gap:7px; font-size:11px; line-height:1.5; margin-bottom:1px; }',
      '.mcl-log-ts { font-family:ui-monospace,monospace; color:#4E5968; flex-shrink:0; }',
      '.mcl-log-ico { flex-shrink:0; }',
      '.mcl-log-msg { color:#9CA3AF; word-break:break-all; }',
      '.mcl-log-line.lvl-up .mcl-log-msg { color:#4ADE80; } .mcl-log-line.lvl-down .mcl-log-msg { color:#FB923C; }',
      '.mcl-log-line.lvl-warn .mcl-log-msg { color:#FBBF24; } .mcl-log-line.lvl-done .mcl-log-msg { color:#60A5FA; font-weight:700; }',
      '.mcl-log-line .mcl-pSurf { color:#9CA3AF; font-weight:400; } .mcl-log-line .mcl-pBuy { color:#7DD3FC; font-weight:800; }',
      '.mcl-log-line .mcl-lbl { color:#6B7684; font-weight:700; } .mcl-log-line .mcl-arrow { color:#5B6876; margin:0 3px; }',
      '.mcl-log-url { flex-shrink:0; margin-left:auto; color:#60A5FA; text-decoration:none; font-size:11px; opacity:.8; }',
      '.mcl-log-url:hover { opacity:1; text-decoration:underline; }',

      /* 최소화 카드(M4) — 스피너+모음전명+총 URL 진행률+바 */
      '#mcl-rail-min {',
      '  display:none; position:fixed; top:14px; right:14px; width:230px; z-index:9001;',
      '  background:#141B22; border:1px solid #25303b; border-radius:13px;',
      '  box-shadow:-6px 6px 24px rgba(0,0,0,.4); padding:13px 15px; cursor:pointer;',
      '  font-family:"Pretendard",sans-serif; transition:transform .12s;',
      '}',
      '#mcl-rail-min:hover { transform:translateY(-1px); }',
      '#mcl-rail-min .rm-top { display:flex; align-items:center; gap:8px; }',
      '#mcl-rail-min .rm-spin { width:16px; height:16px; border-radius:50%; border:2px solid #25303b; border-top-color:#3182F6; animation:mcl-spin 1s linear infinite; flex-shrink:0; }',
      '@keyframes mcl-spin { to { transform:rotate(360deg); } }',
      '#mcl-rail-min .rm-name { font-size:13px; font-weight:800; color:#E5EAF0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }',
      '#mcl-rail-min .rm-exp { margin-left:auto; color:#8B95A1; font-size:15px; flex-shrink:0; }',
      '#mcl-rail-min-num { font-size:18px; font-weight:800; color:#CBD5E1; margin-top:7px; font-variant-numeric:tabular-nums; }',
      '#mcl-rail-min-num b { color:#60A5FA; }',
      '#mcl-rail-min .rm-bar { height:6px; background:#202a34; border-radius:5px; overflow:hidden; margin-top:7px; }',
      '#mcl-rail-min .rm-bar > i { display:block; height:100%; background:linear-gradient(90deg,#3182F6,#60A5FA); width:0%; transition:width .3s; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  // ── DOM ──────────────────────────────────────────────────────────
  var PANEL_ID = 'mcl-panel';
  var RAIL_MIN_ID = 'mcl-rail-min';

  function buildPanelDOM() {
    var old = document.getElementById(PANEL_ID);
    if (old) old.parentNode.removeChild(old);

    var p = document.createElement('div');
    p.id = PANEL_ID;
    p.classList.add('mcl-hidden');
    p.innerHTML = [
      '<div id="mcl-header">',
      '  <div id="mcl-header-top">',
      '    <span id="mcl-title">크롤 진행 중</span>',
      '    <span id="mcl-elapsed">0s</span>',
      '    <button id="mcl-pause-btn" class="mcl-cbtn pause" type="button">⏸ 일시중지</button>',
      '    <button id="mcl-stop-btn" class="mcl-cbtn stop" type="button">■ 중지</button>',
      '    <button id="mcl-min-btn" class="mcl-cbtn sq" type="button" title="최소화">─</button>',
      '    <button id="mcl-close-btn" class="mcl-cbtn sq" type="button" title="닫기">\xd7</button>',
      '  </div>',
      '  <div id="mcl-overall">',
      '    <div id="mcl-overall-ring"><i>0%</i></div>',
      '    <span id="mcl-overall-label">전체</span>',
      '    <span id="mcl-overall-cnt">0 / 0</span>',
      '    <div id="mcl-overall-bar"><div id="mcl-overall-fill"></div></div>',
      '  </div>',
      '  <div id="mcl-finish-summary"></div>',
      '</div>',
      '<div id="mcl-split">',
      '  <div id="mcl-rail"><div id="mcl-rail-head">모음전</div></div>',
      '  <div id="mcl-detail">',
      '    <div id="mcl-gauges">',
      '      <div class="mcl-gauge-row"><div class="mcl-gauge-head"><span class="mcl-gauge-lbl">동시 창</span><span class="mcl-gauge-val" id="mcl-g-conc-val">0 / 0</span></div><div class="mcl-gauge-track"><div class="mcl-gauge-fill conc" id="mcl-g-conc-fill"></div></div></div>',
      '      <div class="mcl-gauge-row"><div class="mcl-gauge-head"><span class="mcl-gauge-lbl">CPU</span><span class="mcl-gauge-val" id="mcl-g-cpu-val">측정 안함</span></div><div class="mcl-gauge-track"><div class="mcl-gauge-fill cpu" id="mcl-g-cpu-fill"></div></div></div>',
      '      <div class="mcl-gauge-row"><div class="mcl-gauge-head"><span class="mcl-gauge-lbl">메모리</span><span class="mcl-gauge-val" id="mcl-g-mem-val">측정 안함</span></div><div class="mcl-gauge-track"><div class="mcl-gauge-fill mem" id="mcl-g-mem-fill"></div></div></div>',
      '    </div>',
      '    <div id="mcl-cards-wrap"></div>',
      '  </div>',
      '</div>',
    ].join('');
    document.body.appendChild(p);

    document.getElementById('mcl-close-btn').addEventListener('click', function () {
      var panel = document.getElementById(PANEL_ID);
      if (panel) panel.classList.add('mcl-hidden');
      hideRailMin();
    });
    document.getElementById('mcl-min-btn').addEventListener('click', minimizePanel);
    document.getElementById('mcl-pause-btn').addEventListener('click', onPauseClick);
    document.getElementById('mcl-stop-btn').addEventListener('click', onStopClick);

    buildRailMinDOM();
    return p;
  }

  function buildRailMinDOM() {
    var old = document.getElementById(RAIL_MIN_ID);
    if (old) old.parentNode.removeChild(old);
    var rail = document.createElement('div');
    rail.id = RAIL_MIN_ID;
    rail.title = '펼치기';
    rail.innerHTML = [
      '<div class="rm-top"><span class="rm-spin"></span><span class="rm-name" id="mcl-rail-min-name">크롤 진행 중</span><span class="rm-exp" title="펼치기">‹</span></div>',
      '<div id="mcl-rail-min-num">0 / 0</div>',
      '<div class="rm-bar"><i id="mcl-rail-min-bar"></i></div>',
    ].join('');
    document.body.appendChild(rail);
    rail.addEventListener('click', restorePanel);
    return rail;
  }

  function minimizePanel() {
    var panel = document.getElementById(PANEL_ID);
    if (panel) panel.classList.add('mcl-hidden');
    renderRailMin();
    var rail = document.getElementById(RAIL_MIN_ID);
    if (rail) rail.style.display = 'block';
  }
  function restorePanel() {
    var panel = document.getElementById(PANEL_ID);
    if (panel) panel.classList.remove('mcl-hidden');
    hideRailMin();
  }
  function hideRailMin() {
    var rail = document.getElementById(RAIL_MIN_ID);
    if (rail) rail.style.display = 'none';
  }
  function showPanel() {
    var p = document.getElementById(PANEL_ID);
    if (p) p.classList.remove('mcl-hidden');
  }

  // ── 버튼 동작 ────────────────────────────────────────────────────
  function runningBundle() {
    for (var i = 0; i < order.length; i++) {
      var b = bundles[order[i]];
      if (b && (b.status === 'run' || b.status === 'pause')) return b;
    }
    return null;
  }
  function onPauseClick() {
    if (!window.MoumExt) return;
    var rb = runningBundle();
    var paused = rb && rb.status === 'pause';
    try {
      if (paused) { window.MoumExt.resumeCrawl && window.MoumExt.resumeCrawl(); }
      else { window.MoumExt.pauseCrawl && window.MoumExt.pauseCrawl(); }
    } catch (_) {}
  }
  function onStopClick() {
    if (!window.MoumExt) return;
    if (!window.confirm('크롤을 중지할까요?\n열린 크롤 창을 닫고 종료합니다. (지금까지 긁은 가격은 저장되고, 못 긁은 옵션은 판매 차단으로 남습니다.)')) return;
    try { window.MoumExt.stopCrawl && window.MoumExt.stopCrawl(); } catch (_) {}
  }

  // ── 헬퍼 ─────────────────────────────────────────────────────────
  function safeText(el, txt) { if (el) el.textContent = String(txt == null ? '' : txt); }
  function setWidth(el, pct) { if (el) el.style.width = Math.min(100, Math.max(0, pct)) + '%'; }
  function fmtTime(ts) {
    var d = new Date(ts);
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2) + ':' + ('0' + d.getSeconds()).slice(-2);
  }
  function icoForLevel(level) {
    if (level === 'up') return '▲'; if (level === 'down') return '▼';
    if (level === 'warn') return '⚠'; if (level === 'done') return '✓'; return '\xb7';
  }
  function won(n) { return Number(n).toLocaleString() + '원'; }
  // m(metrics) 을 모음전 bucket 에 병합. done/total 은 bucket 직접 필드로 보관(레일 카운트용).
  function mergeMetrics(b, m) {
    if (!m) return;
    var dst = b.metrics;
    ['concurrency', 'cap', 'active', 'cpu', 'mem', 'avgSec'].forEach(function (k) {
      if (m[k] != null) dst[k] = m[k];
    });
    if (m.done != null) b.doneCount = m.done;
    if (m.total != null) b.total = m.total;
  }

  // ── 경과 타이머 ─────────────────────────────────────────────────
  function renderElapsed() {
    if (!globalStartTs) return;
    var sec = Math.floor((Date.now() - globalStartTs) / 1000);
    safeText(document.getElementById('mcl-elapsed'), sec < 60 ? (sec + 's') : (Math.floor(sec / 60) + 'm ' + (sec % 60) + 's'));
  }
  function startElapsedTimer() {
    stopElapsedTimer();
    renderElapsed();
    _elapsedTimer = setInterval(renderElapsed, 1000);
  }
  function stopElapsedTimer() { if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; } }

  // ── 모음전 진행 합계 ───────────────────────────────────────────
  function bundleProgress(b) {
    var sourceSum = 0, total = b.total || 0;
    SOURCE_ORDER.forEach(function (sk) { var s = b.sources[sk]; if (s) sourceSum += (s.done || 0); });
    // 소싱처 합 vs 전역 done(metrics) 중 큰 값(완료 모음전은 소싱처 이벤트 없이 finish 만 올 수 있음)
    var done = Math.max(sourceSum, b.doneCount || 0);
    return { done: done, total: total, pct: total > 0 ? Math.min(100, Math.round(done / total * 100)) : 0 };
  }

  // ── 레일(좌측 모음전 목록) 렌더 ──────────────────────────────────
  function renderRail() {
    var rail = document.getElementById('mcl-rail');
    if (!rail) return;
    // 헤더 유지, 나머지 비우고 다시 그림
    rail.innerHTML = '<div id="mcl-rail-head">모음전 ' + order.length + '</div>';
    order.forEach(function (code) {
      var b = bundles[code];
      if (!b) return;
      var prog = bundleProgress(b);
      var st = b.status;
      var subTxt, barCol;
      if (st === 'run') { subTxt = '● 진행중 ' + prog.done + '/' + (prog.total || '?'); barCol = '#3182F6'; }
      else if (st === 'pause') { subTxt = '⏸ 일시중지 ' + prog.done + '/' + (prog.total || '?'); barCol = '#FBBF24'; }
      else if (st === 'wait') { subTxt = '⏳ 대기 중'; barCol = '#4B5563'; }
      else if (st === 'stop') { subTxt = '■ 중지됨 ' + prog.done + '/' + (prog.total || '?'); barCol = '#F87171'; }
      else { subTxt = '✓ 완료 ' + prog.done + '/' + (prog.total || prog.done); barCol = '#34D399'; }

      var row = document.createElement('div');
      row.className = 'mcl-rb' + (code === selected ? ' sel' : '');
      row.setAttribute('data-code', code);

      var dot = document.createElement('div'); dot.className = 'mcl-rb-dot ' + st;
      var body = document.createElement('div'); body.className = 'mcl-rb-body';
      var nm = document.createElement('div'); nm.className = 'mcl-rb-name'; nm.textContent = b.label || code;
      var sub = document.createElement('div'); sub.className = 'mcl-rb-sub ' + st; sub.textContent = subTxt;
      body.appendChild(nm); body.appendChild(sub);
      if (st !== 'wait') {
        var mb = document.createElement('div'); mb.className = 'mcl-rb-minibar';
        var mbi = document.createElement('i'); mbi.style.width = (st === 'done' ? 100 : prog.pct) + '%'; mbi.style.background = barCol;
        mb.appendChild(mbi); body.appendChild(mb);
      }
      row.appendChild(dot); row.appendChild(body);

      // 대기 모음전은 × 로 취소 가능
      if (st === 'wait') {
        var x = document.createElement('div'); x.className = 'mcl-rb-x'; x.textContent = '\xd7'; x.title = '대기 취소';
        x.addEventListener('click', function (e) {
          e.stopPropagation();
          try { window.MoumExt && window.MoumExt.cancelQueued && window.MoumExt.cancelQueued(code); } catch (_) {}
        });
        row.appendChild(x);
      }
      // [2026-06-18 시안A] 바로가기(↗) — 이 모음전 편집 화면으로(새 탭). 행 클릭(상세 선택)과 분리.
      var go = document.createElement('div'); go.className = 'mcl-rb-goto'; go.textContent = '↗';
      go.title = '이 모음전 편집 화면으로 이동';
      go.addEventListener('click', function (e) {
        e.stopPropagation();
        var u = '/bundles/' + encodeURIComponent(code);
        try { window.open(u, '_blank'); } catch (_) { location.href = u; }
      });
      row.appendChild(go);
      row.addEventListener('click', function () { selected = code; renderRail(); renderDetail(); });
      rail.appendChild(row);
    });
  }

  // ── 게이지 렌더(선택 모음전) ────────────────────────────────────
  function renderGauges() {
    var b = bundles[selected];
    var m = (b && b.metrics) || { concurrency: 0, cap: 0, active: 0, cpu: null, mem: null, avgSec: null };
    var activeWin = (m.active != null) ? m.active : m.concurrency;
    var concPct = m.cap > 0 ? (activeWin / m.cap * 100) : 0;
    var concLabel = (activeWin || 0) + ' / ' + (m.cap || 0) + '  (목표 ' + (m.concurrency || 0) + ')';
    if (m.avgSec != null) concLabel += ' · 중앙 ' + m.avgSec + 's';
    safeText(document.getElementById('mcl-g-conc-val'), concLabel);
    setWidth(document.getElementById('mcl-g-conc-fill'), concPct);

    var cpuVal = document.getElementById('mcl-g-cpu-val'), cpuFill = document.getElementById('mcl-g-cpu-fill');
    if (m.cpu == null) { safeText(cpuVal, '측정 안함'); setWidth(cpuFill, 0); }
    else { safeText(cpuVal, m.cpu + '%'); setWidth(cpuFill, m.cpu); }
    var memVal = document.getElementById('mcl-g-mem-val'), memFill = document.getElementById('mcl-g-mem-fill');
    if (m.mem == null) { safeText(memVal, '측정 안함'); setWidth(memFill, 0); }
    else { safeText(memVal, m.mem + '%'); setWidth(memFill, m.mem); }
  }

  // ── 상세(우측: 선택 모음전의 소싱처 카드 + 로그) 렌더 ────────────
  function priceTokensInto(msgSpan, srcLabel, surf, buy) {
    function span(cls, txt) { var s = document.createElement('span'); if (cls) s.className = cls; s.textContent = txt; return s; }
    msgSpan.appendChild(span('', srcLabel + ' '));
    msgSpan.appendChild(span('mcl-lbl', '표면 '));
    msgSpan.appendChild(span('mcl-pSurf', won(surf)));
    msgSpan.appendChild(span('mcl-arrow', '→'));
    msgSpan.appendChild(span('mcl-lbl', '매입 '));
    msgSpan.appendChild(span('mcl-pBuy', won(buy)));
  }

  // [2026-06-18 H2] 소싱처 ✗(실패) 클릭 → 옵션 매트릭스 열기(어떤 옵션이 실패했는지 확인).
  //   현재 페이지에 '매트릭스 보기' 버튼 있으면 팝업, 없으면 그 모음전 매트릭스 탭으로 이동.
  function openMatrixForFail(code) {
    try {
      var btns = [].slice.call(document.querySelectorAll('button,a,div,span'));
      for (var i = 0; i < btns.length; i++) { var t = (btns[i].textContent || '').trim(); if (t === '매트릭스 보기' && t.length < 12) { btns[i].click(); return; } }
    } catch (_) {}
    try { if (code) location.href = '/bundles/' + encodeURIComponent(code) + '#tab=opt'; } catch (_) {}
  }

  // [2026-06-19 D8] URL → 짧은 표시명(상품명 없을 때 폴백).
  function shortUrl(u) {
    if (!u) return '';
    try { var p = u.split('?')[0].split('/').filter(Boolean); return decodeURIComponent(p[p.length - 1] || u).slice(0, 30); }
    catch (_) { return (u || '').slice(0, 30); }
  }
  function closeReceipt() { var ov = document.getElementById('mcl-rc-ov'); if (ov) ov.classList.add('mcl-hidden'); }
  // [2026-06-19] 최종매입가 클릭 → fx 영수증(표면→혜택 steps→최종). steps는 크롤 item-final 이 전달.
  function openReceipt(line, srcLabel) {
    var ov = document.getElementById('mcl-rc-ov');
    if (!ov) {
      ov = document.createElement('div'); ov.id = 'mcl-rc-ov'; ov.className = 'mcl-hidden';
      ov.innerHTML = '<div id="mcl-rc"><div class="rc-h"><span class="rc-fx">fx</span><span class="rc-t">최종매입가 영수증</span><span class="rc-x" title="닫기">\xd7</span></div><div class="rc-b" id="mcl-rc-b"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) closeReceipt(); });
      ov.querySelector('.rc-x').addEventListener('click', closeReceipt);
    }
    var nm = line.name || shortUrl(line.url);
    var h = '<div class="rc-prod">' + (srcLabel || '') + ' · ' + nm + '</div>'
      + '<div class="rc-r surf"><span>표면노출가</span><span class="rc-v">' + won(line.surf) + '</span></div>';
    var steps = line.steps || [];
    if (steps.length) {
      steps.forEach(function (st) {
        var label = st.label || st.name || st.type || '혜택';
        var amt = (st.amount != null ? st.amount : (st.value != null ? st.value : null));
        var amtTxt = amt == null ? '' : (Math.abs(amt) < 1
          ? ('−' + (+(amt * 100).toFixed(2)) + '%')
          : ('−' + Math.round(amt).toLocaleString() + '원'));
        h += '<div class="rc-r step"><span>' + label + '</span><span class="rc-v">' + amtTxt + '</span></div>';
      });
    }
    h += '<div class="rc-div"></div><div class="rc-r final"><span>최종매입가</span><span class="rc-v">' + won(line.buy) + '</span></div>';
    if (line.surf != null && line.buy != null) h += '<div class="rc-note">매트릭스 fx와 동일 계산 · 절감 −' + (line.surf - line.buy).toLocaleString() + '원</div>';
    document.getElementById('mcl-rc-b').innerHTML = h;
    ov.classList.remove('mcl-hidden');
  }

  function renderDetail() {
    renderGauges();
    var wrap = document.getElementById('mcl-cards-wrap');
    if (!wrap) return;
    wrap.innerHTML = '';
    var b = bundles[selected];
    if (!b) { wrap.innerHTML = '<div id="mcl-empty">진행 중인 크롤이 없습니다.</div>'; return; }

    var anyCard = false;
    SOURCE_ORDER.forEach(function (sk) {
      var s = b.sources[sk];
      if (!s) return;
      anyCard = true;

      var card = document.createElement('div'); card.className = 'mcl-card';
      var header = document.createElement('div'); header.className = 'mcl-card-header';
      var nameEl = document.createElement('span'); nameEl.className = 'mcl-card-name'; nameEl.textContent = SOURCE_LABELS[sk] || sk;
      // [2026-06-18 H2] 완료딱지는 성공 완료(실패 0)일 때만. 실패 있으면 딱지 제거.
      var _ok = s.ok || 0, _fail = s.fail || 0;
      var _hideTag = (s.status === 'done' && _fail > 0);
      var tagEl = document.createElement('span'); tagEl.className = 'mcl-card-tag ' + s.status + (_hideTag ? ' mcl-hidden' : '');
      tagEl.textContent = s.status === 'run' ? '진행중' : s.status === 'done' ? '완료' : '대기';
      // [2026-06-18 H2] URL 등록수(흰색·구조값) │ ✓성공 ✗실패(빨강·클릭→매트릭스). 실패 0이면 ✗ 숨김.
      var cntEl = document.createElement('span'); cntEl.className = 'mcl-card-cnt';
      var _reg = (s.total != null) ? (s.done + '/' + s.total) : (s.done || 0);
      var _res = '';
      if (s.status !== 'wait') {
        _res = ' <span class="mcl-vdiv">│</span> <span class="mcl-c-ok">✓ ' + _ok + '</span>'
             + (_fail > 0 ? ' <span class="mcl-c-no" title="클릭 → 옵션 매트릭스">✗ ' + _fail + '</span>' : '');
      }
      cntEl.innerHTML = '<span class="mcl-c-reg">URL 등록수 ' + _reg + '</span>' + _res;
      var _noEl = cntEl.querySelector('.mcl-c-no');
      if (_noEl) _noEl.addEventListener('click', function (e) { e.stopPropagation(); openMatrixForFail(selected); });
      var toggleEl = document.createElement('button'); toggleEl.type = 'button'; toggleEl.className = 'mcl-card-toggle';
      toggleEl.textContent = '로그 ' + s.logs.length + '건 ' + (s.expanded ? '▴' : '▾');
      toggleEl.addEventListener('click', function () { s.expanded = !s.expanded; renderDetail(); });
      header.appendChild(nameEl); header.appendChild(tagEl); header.appendChild(cntEl); header.appendChild(toggleEl);

      var barWrap = document.createElement('div'); barWrap.className = 'mcl-card-bar-wrap';
      var barFill = document.createElement('div'); barFill.className = 'mcl-card-bar-fill ' + s.status;
      var pct = s.status === 'done' ? 100 : (s.total != null && s.total > 0 ? Math.min(100, Math.round(s.done / s.total * 100)) : (s.done > 0 ? 30 : 0));
      barFill.style.width = pct + '%';
      barWrap.appendChild(barFill);

      var logArea = document.createElement('div'); logArea.className = 'mcl-card-logs' + (s.expanded ? '' : ' mcl-hidden');
      // [2026-06-19 D8] URL별 상세표 — URL행(item-done)만: 상품명 · 표면노출가 · 최종매입가(fx, 클릭→영수증).
      var urlLines = s.logs.filter(function (lg) { return lg.url; });
      if (urlLines.length) {
        var thead = document.createElement('div'); thead.className = 'mcl-d8-head';
        thead.innerHTML = '<span>타입</span><span>URL</span><span>표면노출가</span><span>최종매입가(fx)</span>';
        logArea.appendChild(thead);
        urlLines.forEach(function (lg) {
          var r = document.createElement('div'); r.className = 'mcl-d8-row' + (lg.level === 'warn' ? ' fail' : '');
          // 타입 배지 (단품/모델 모음전)
          var bdg = document.createElement('span');
          var ut = lg.url_type || '';
          var bdgTxt = ut === 'deal' ? '모델\n모음전' : (ut === 'dan' ? '단품' : '');
          bdg.className = 'mcl-d8-badge ' + (ut ? 't-' + ut : 't-none');
          bdg.textContent = bdgTxt || (ut || '-');
          r.appendChild(bdg);
          // [2026-06-19 시안A] 상품명 = 클릭 시 URL 열기 링크(↗) + 전체표시(CSS 줄바꿈).
          var nm = document.createElement('span'); nm.className = 'mcl-d8-nm';
          var nmA = document.createElement('a'); nmA.href = lg.url; nmA.target = '_blank'; nmA.rel = 'noopener'; nmA.title = lg.url;
          nmA.textContent = lg.name || shortUrl(lg.url);
          var nmExt = document.createElement('span'); nmExt.className = 'mcl-d8-ext'; nmExt.textContent = ' ↗';
          nmA.appendChild(nmExt); nm.appendChild(nmA);
          var sf = document.createElement('span'); sf.className = 'mcl-d8-surf'; sf.textContent = lg.surf != null ? won(lg.surf) : '-';
          var by = document.createElement('span'); by.className = 'mcl-d8-buy';
          if (lg.level === 'warn') { by.classList.add('fail'); by.textContent = '크롤실패'; }
          else if (lg.buy != null) {
            by.classList.add('clk'); by.textContent = won(lg.buy); by.title = '클릭 → fx 영수증';
            (function (line) { by.addEventListener('click', function () { openReceipt(line, SOURCE_LABELS[sk] || sk); }); })(lg);
          } else { by.textContent = '계산중…'; by.classList.add('calc'); }
          r.appendChild(nm); r.appendChild(sf); r.appendChild(by);
          logArea.appendChild(r);
        });
      } else {
        s.logs.forEach(function (lg) {
          var row = document.createElement('div'); row.className = 'mcl-log-line' + (lg.level ? ' lvl-' + lg.level : '');
          var ts = document.createElement('span'); ts.className = 'mcl-log-ts'; ts.textContent = fmtTime(lg.ts);
          var msg = document.createElement('span'); msg.className = 'mcl-log-msg'; msg.textContent = lg.msg;
          row.appendChild(ts); row.appendChild(msg); logArea.appendChild(row);
        });
      }

      card.appendChild(header); card.appendChild(barWrap); card.appendChild(logArea);
      wrap.appendChild(card);

      if (s.expanded) logArea.scrollTop = logArea.scrollHeight;
    });
    if (!anyCard) wrap.innerHTML = '<div id="mcl-empty">' + (b.status === 'wait' ? '대기 중 — 차례가 되면 시작합니다.' : '준비 중…') + '</div>';
  }

  // ── 헤더(타이틀·버튼·전체바·완료배너) 렌더 ──────────────────────
  // [2026-06-18 시안D] 완료 요약 — 옵션(전체=활성+비활성) + 크롤(완료=성공+실패) 구조 표기.
  //   크롤 수치는 위젯 소싱처 상태에서 집계. 옵션 활성/비활성은 현재 매트릭스 페이지의
  //   window.DATA(option-matrix)에서 카운트(같은 모음전일 때만 — 없으면 옵션 섹션 생략).
  function buildFinishHTML(b) {
    // [2026-06-19 P4] 단일 진실 — 이 모음전이 현재 매트릭스 페이지와 동일하면, 종료 후엔
    //   카드(소싱처별 진행)와 같은 백엔드 source_stats(DB) 로 URL 성공/실패를 표기한다.
    //   (이벤트 카운트는 이번 세션에 긁은 URL 만 세어 카드의 등록URL 기준과 단위가 달랐다.)
    //   DB 미가용(다른 모음전·페이지 밖)이면 이벤트 카운트로 폴백.
    var Y = 0, Y2 = 0, Y3 = 0, _fromDB = false;
    try {
      if (window.BUNDLE_CODE && b.code && window.BUNDLE_CODE === b.code
          && window.DATA && window.DATA.source_stats) {
        var ss = window.DATA.source_stats, uTry = 0, uDone = 0;
        Object.keys(ss).forEach(function (k) {
          var v = ss[k] || {}; uTry += (v.url_try || 0); uDone += (v.url_done || 0);
        });
        if (uTry > 0) { Y = uTry; Y2 = uDone; Y3 = uTry - uDone; _fromDB = true; }
      }
    } catch (_) {}
    if (!_fromDB) {
      SOURCE_ORDER.forEach(function (sk) {
        var s = b.sources[sk]; if (!s) return;
        var ok = s.ok || 0, fail = s.fail || 0;
        Y2 += ok; Y3 += fail;
        Y += (s.total != null ? s.total : (ok + fail));
      });
    }
    var Y1 = Y2 + Y3;
    if (Y < Y1) Y = Y1;
    var X = null, X1 = null, X2 = null;
    try {
      var opts = (window.DATA && window.DATA.options) || null;
      if (opts && opts.length) { X = opts.length; X2 = opts.filter(function (x) { return x.is_active === false; }).length; X1 = X - X2; }
    } catch (_) {}
    // 크롤을 좌측·우선(지적3) · '옵션/크롤링' 헤더 없음(지적2) · 행 여백 균등(지적1).
    var h = '<div id="mcl-fd">';
    // 좌: 크롤 (우선)
    h += '<div class="fd-col">'
      + '<div class="fd-row top"><span class="k">총 URL · 진행률</span><span class="v bl">' + Y1 + ' / ' + Y + '</span></div>'
      + '<div class="fd-row sub"><span class="k">완료</span><span class="v">' + Y1 + '</span></div>'
      + '<div class="fd-row sub"><span class="k">성공</span><span class="v gn">' + Y2 + '</span></div>'
      + '<div class="fd-row sub"><span class="k">실패</span><span class="v rd">' + Y3 + '</span></div>'
      + (b.status === 'stop' ? '<div class="fd-stop">■ 중지됨</div>' : '')
      + '</div>';
    // 우: 옵션 (매트릭스 데이터 있을 때만)
    if (X != null) {
      h += '<div class="fd-col">'
        + '<div class="fd-row top"><span class="k">전체 옵션</span><span class="v">' + X + '</span></div>'
        + '<div class="fd-row sub"><span class="k">활성<span class="fd-det">상세보기</span></span><span class="v gn">' + X1 + '</span></div>'
        + '<div class="fd-row sub"><span class="k">비활성</span><span class="v gy">' + X2 + '</span></div>'
        + '</div>';
    }
    h += '</div>';
    return h;
  }

  function renderHeader() {
    var rb = runningBundle();
    var title = document.getElementById('mcl-title');
    var pauseBtn = document.getElementById('mcl-pause-btn');
    var stopBtn = document.getElementById('mcl-stop-btn');
    var closeBtn = document.getElementById('mcl-close-btn');

    if (rb && rb.status === 'pause') {
      safeText(title, '일시중지됨 — ' + (rb.label || rb.code));
      if (pauseBtn) { pauseBtn.textContent = '▶ 재개'; pauseBtn.className = 'mcl-cbtn resume'; }
    } else if (rb) {
      var waitN = order.filter(function (c) { return bundles[c] && bundles[c].status === 'wait'; }).length;
      safeText(title, '크롤 진행 중' + (waitN ? ' · 대기 ' + waitN : ''));
      if (pauseBtn) { pauseBtn.textContent = '⏸ 일시중지'; pauseBtn.className = 'mcl-cbtn pause'; }
    } else {
      safeText(title, '크롤 완료');
    }

    var active = !!rb;
    if (pauseBtn) pauseBtn.style.display = active ? '' : 'none';
    if (stopBtn) stopBtn.style.display = active ? '' : 'none';
    if (closeBtn) closeBtn.style.display = active ? 'none' : '';

    // 전체바 = 선택 모음전 진행
    var b = bundles[selected];
    var prog = b ? bundleProgress(b) : { done: 0, total: 0, pct: 0 };
    safeText(document.getElementById('mcl-overall-cnt'), prog.done + ' / ' + (prog.total || prog.done));
    setWidth(document.getElementById('mcl-overall-fill'), prog.pct);
    // [2026-06-19 R2] 전체 진행률 도넛
    var oring = document.getElementById('mcl-overall-ring');
    if (oring) { oring.style.background = 'conic-gradient(#3182F6 ' + (prog.pct * 3.6) + 'deg,#25303b 0deg)'; var oi = oring.querySelector('i'); if (oi) oi.textContent = prog.pct + '%'; }

    // 완료 배너 — 선택 모음전이 끝났을 때
    var fin = document.getElementById('mcl-finish-summary');
    if (fin) {
      if (b && (b.status === 'done' || b.status === 'stop') && b.finishMsg) {
        fin.style.display = 'block';
        fin.className = b.status === 'stop' ? 'stopped' : '';
        fin.innerHTML = buildFinishHTML(b);
      } else {
        fin.style.display = 'none';
      }
    }
    renderRailMin();
  }

  function renderRailMin() {
    var rb = runningBundle();
    var b = rb || bundles[selected];
    var prog = b ? bundleProgress(b) : { done: 0, total: 0, pct: 0 };
    var nameEl = document.getElementById('mcl-rail-min-name');
    if (nameEl && b) nameEl.textContent = b.label || b.code || '크롤 진행 중';
    var numEl = document.getElementById('mcl-rail-min-num');
    if (numEl) numEl.innerHTML = '<b>' + prog.done + '</b> / ' + (prog.total || prog.done);
    var bar = document.getElementById('mcl-rail-min-bar');
    if (bar) bar.style.width = prog.pct + '%';
  }

  function renderAll() { renderRail(); renderDetail(); renderHeader(); }

  // ── 이벤트 핸들러 ────────────────────────────────────────────────
  var _registered = false;

  function ensurePanel() {
    injectCSS();
    if (!document.getElementById(PANEL_ID)) buildPanelDOM();
    showPanel();
    if (!globalStartTs) { globalStartTs = Date.now(); startElapsedTimer(); }
  }

  function handleCrawlLog(e) {
    var d = e.detail; if (!d) return;
    var type = d.type, ts = d.ts || Date.now(), code = d.bundle, sk = d.source, level = d.level || '', msg = d.msg || '', m = d.metrics;

    // 'queue' — 진행중+대기 목록 갱신(레일)
    if (type === 'queue') {
      ensurePanel();
      var q = d.queue || [];
      var seenCodes = {};
      q.forEach(function (it) {
        var b = getBundle(it.code);
        b.label = it.code;
        // 완료/중지된 건 큐에 없음 → run/pause/wait 만 갱신
        if (it.status === 'wait') b.status = 'wait';
        else if (it.status === 'pause') b.status = 'pause';
        else b.status = 'run';
        seenCodes[it.code] = true;
      });
      // 큐 순서 재구성: 큐(run/pause/wait) 먼저(이벤트 순서) + 그 외(done/stop)는 뒤에 기존순서 유지.
      //  큐에 없으면서 'wait' 였던 모음전 = 취소(또는 중지로 큐 비움) → 레일에서 제거.
      var newOrder = q.map(function (it) { return it.code; });
      order.forEach(function (c) {
        if (newOrder.indexOf(c) >= 0) return;
        var bb = bundles[c];
        if (bb && bb.status === 'wait') { delete bundles[c]; return; }  // 취소됨 — 제거
        newOrder.push(c);   // 완료/중지/진행후 = 유지
      });
      order = newOrder;
      anyRunning = q.some(function (it) { return it.status === 'run' || it.status === 'pause'; });
      if (!selected || !bundles[selected]) selected = (d.running || (q[0] && q[0].code) || order[0] || null);
      renderAll();
      return;
    }

    // 'snapshot' — [2단계] 페이지 (재)진입 시 백그라운드 진행 상태로 위젯 복원.
    //   로그 히스토리는 없지만(이후 로그는 실시간 스트림) 진행중·대기·완료와 진행률·게이지는 복원.
    if (type === 'snapshot') {
      var snap = d.snapshot; if (!snap) return;
      ensurePanel();
      var view = snap.view || {};
      Object.keys(view).forEach(function (bc) {
        var sv = view[bc];
        var bb = getBundle(bc);
        bb.label = sv.label || bc;
        bb.status = sv.status || 'run';
        if (sv.total != null) bb.total = sv.total;
        if (sv.done != null) bb.doneCount = sv.done;
        if (sv.metrics) { ['concurrency', 'cap', 'active', 'cpu', 'mem', 'avgSec'].forEach(function (k) { if (sv.metrics[k] != null) bb.metrics[k] = sv.metrics[k]; }); }
        if (sv.finishMsg) bb.finishMsg = sv.finishMsg;
        var svs = sv.sources || {};
        Object.keys(svs).forEach(function (sk) {
          var s = getSource(bb, sk);
          s.status = svs[sk].status || 'wait';
          if (svs[sk].done != null) s.done = svs[sk].done;
          if (svs[sk].total != null) s.total = svs[sk].total;
        });
      });
      // 대기열 순서: running 먼저 + queue(wait) + 나머지(done 등)
      var qcodes = (snap.queue || []).slice();
      var newOrd = [];
      if (snap.running && newOrd.indexOf(snap.running) < 0) newOrd.push(snap.running);
      qcodes.forEach(function (c) { if (newOrd.indexOf(c) < 0) newOrd.push(c); });
      Object.keys(view).forEach(function (c) { if (newOrd.indexOf(c) < 0) newOrd.push(c); });
      order = newOrd;
      // 대기 모음전 bucket 의 상태도 wait 로(큐에 있으면)
      qcodes.forEach(function (c) { if (bundles[c]) bundles[c].status = 'wait'; });
      selected = snap.running || (qcodes[0]) || order[0] || null;
      var snapActive = snap.running || qcodes.length;
      if (snapActive) { if (!globalStartTs) { globalStartTs = Date.now(); startElapsedTimer(); } }
      renderAll();
      // 재진입(다른 페이지서 돌아옴)은 '최소화 레일'로 표시 — 큰 패널이 갑자기 덮지 않게.
      //   진행 중이면 레일로, 이미 끝났으면 그대로(완료 요약). (사용자 요청: 사라지지 말고 최소화)
      if (snap.running) { minimizePanel(); }
      return;
    }

    if (!code) return;          // bundle 없는 이벤트(구버전) 무시
    var b = getBundle(code);
    b.label = code;

    switch (type) {
      case 'start': {
        ensurePanel();
        b.status = 'run'; b.startTs = ts; b.finishMsg = ''; b.stopped = false;
        if (m && m.total != null) b.total = m.total;
        selected = code;          // 새 모음전 시작 → 자동 포커스
        renderAll();
        break;
      }
      case 'concurrency':
      case 'resource': {
        mergeMetrics(b, m);
        if (m && m.total != null) b.total = m.total;
        if (code === selected) renderGauges();
        renderHeader();
        break;
      }
      case 'window-open': {
        if (sk) {
          var s1 = getSource(b, sk); s1.status = 'run'; s1.done = 0; s1.total = null; s1.expanded = true;
          s1.logs.push({ ts: ts, level: level, msg: msg || '창 시작' });
        }
        mergeMetrics(b, m);
        if (code === selected) renderDetail();
        renderRail(); renderHeader();
        break;
      }
      case 'item-done': {
        if (sk) {
          var s2 = getSource(b, sk); s2.done = (s2.done || 0) + 1;
          // [2026-06-18] URL별 성공/실패 카운트(시안D·소싱처카드 분해표기용). warn=실패, 그 외=성공.
          if (level === 'warn') s2.fail = (s2.fail || 0) + 1; else s2.ok = (s2.ok || 0) + 1;
          var line = { ts: ts, level: level, msg: msg, url: d.url || null, lineId: d.lineId || null, name: d.name || null, surf: (d.surf != null ? d.surf : null), buy: null, steps: null, url_type: d.url_type || '' };
          s2.logs.push(line);
          if (s2.logs.length > 200) s2.logs.shift();
          if (d.lineId) b.lineIndex[d.lineId] = { sk: sk, line: line };
        }
        mergeMetrics(b, m);
        if (code === selected) { renderDetail(); renderGauges(); }
        renderRail(); renderHeader();
        break;
      }
      case 'item-retried': {
        // [2026-06-22] 재시도 성공 로그 — done/ok/fail 카운터는 건드리지 않음(이미 최초 시도에서 계산).
        //   "item-done" 을 재사용하면 s.done++ 이중 증가(42/40 오버카운트 버그).
        if (sk) {
          var s2r = getSource(b, sk);
          var liner = { ts: ts, level: 'retried', msg: msg, url: d.url || null, lineId: d.lineId || null, name: d.name || null, surf: (d.surf != null ? d.surf : null), buy: null, steps: null, url_type: '' };
          s2r.logs.push(liner);
          if (s2r.logs.length > 200) s2r.logs.shift();
          if (d.lineId) b.lineIndex[d.lineId] = { sk: sk, line: liner };
        }
        mergeMetrics(b, m);
        if (code === selected) { renderDetail(); renderGauges(); }
        renderRail(); renderHeader();
        break;
      }
      case 'item-final': {
        // 저장 후 '표면 → 매입' 제자리 갱신
        if (d.lineId != null && d.surf != null && d.buy != null) {
          var rec = b.lineIndex[d.lineId];
          if (rec && rec.line) { rec.line.surf = d.surf; rec.line.buy = d.buy; rec.line.steps = d.steps || null; rec.line.level = 'done'; }
          else if (sk) { getSource(b, sk).logs.push({ ts: ts, level: 'done', msg: msg, surf: d.surf, buy: d.buy, steps: d.steps || null }); }
        } else if (sk) {
          getSource(b, sk).logs.push({ ts: ts, level: 'done', msg: msg });
        }
        if (code === selected) renderDetail();
        break;
      }
      case 'source-done': {
        if (sk) {
          var s3 = getSource(b, sk);
          if (s3.total != null) s3.done = s3.total;
          s3.status = 'done'; s3.expanded = false;
          s3.logs.push({ ts: ts, level: level, msg: msg });
        }
        mergeMetrics(b, m);
        if (code === selected) renderDetail();
        renderRail(); renderHeader();
        break;
      }
      case 'bundle-paused': { b.status = 'pause'; renderAll(); break; }
      case 'bundle-resumed': { b.status = 'run'; renderAll(); break; }
      case 'bundle-stopping': { b.stopped = true; renderHeader(); break; }
      case 'finish': {
        b.status = d.stopped ? 'stop' : 'done';
        b.finishMsg = msg;
        // 진행중이던 소싱처 카드 마감
        SOURCE_ORDER.forEach(function (k) { if (b.sources[k] && b.sources[k].status === 'run') b.sources[k].status = 'done'; });
        mergeMetrics(b, m);
        // 더 이상 도는 모음전 없으면 타이머 정지
        if (!runningBundle()) { stopElapsedTimer(); }
        renderAll();
        break;
      }
    }
  }

  // ── [2026-06-14] 탭/창 전환 시 사라지지 말고 '최소화(레일)'로 남게 ──────────
  //   페이지가 가려지면(다른 탭/창) 진행 중 크롤이 있을 때 큰 패널을 레일로 접는다.
  //   → 돌아와도 위젯이 사라지지 않고 작은 도넛 레일로 유지된다(사용자 요청).
  //   진행 중인데 패널·레일이 둘 다 없으면(어떤 이유로 숨겨짐) 레일을 복원한다.
  function ensureMinimizedWhileActive() {
    if (!runningBundle()) return;                 // 진행 중 아니면 관여 안 함
    var panel = document.getElementById(PANEL_ID);
    if (!panel) { buildPanelDOM(); renderAll(); }
    minimizePanel();                              // 패널 접고 레일 표시
  }
  function onVisibilityChange() {
    if (document.hidden) {
      ensureMinimizedWhileActive();
    } else {
      // 돌아왔을 때: 진행 중인데 위젯이 하나도 안 보이면 최소화 레일로 복원
      if (!runningBundle()) return;
      var panel = document.getElementById(PANEL_ID);
      var rail = document.getElementById(RAIL_MIN_ID);
      var panelShown = panel && !panel.classList.contains('mcl-hidden');
      var railShown = rail && rail.style.display !== 'none';
      if (!panelShown && !railShown) ensureMinimizedWhileActive();
    }
  }

  function register() {
    if (_registered) return;
    _registered = true;
    window.addEventListener('moum-crawl-log', handleCrawlLog);
    // [2026-06-19 P4] 매트릭스가 크롤 후 DB(source_stats) 재로딩을 끝내면 → 종료요약 재렌더
    //   (이벤트→DB 단일 진실 전환. buildFinishHTML 이 갱신된 window.DATA.source_stats 를 읽음.)
    window.addEventListener('moum-matrix-refreshed', function () { try { renderAll(); } catch (_) {} });
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('pagehide', ensureMinimizedWhileActive);
    window.addEventListener('blur', function () { if (document.hidden) ensureMinimizedWhileActive(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', register);
  else register();

})();

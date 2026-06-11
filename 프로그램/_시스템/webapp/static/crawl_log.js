// crawl_log.js — Phase 4 실시간 크롤 대시보드 (시안 8, moum-crawl-log 구독)
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

  // ── 내부 상태 ────────────────────────────────────────────────────
  var state = {
    sources: {},   // key -> { status:'wait'|'run'|'done', done:0, total:null }
    metrics: { concurrency: 0, cap: 0, cpu: null, mem: null, avgSec: null, done: 0, total: 0 },
    logs:    [],   // { ts, level, msg }
    startTs: 0,
    elapsed: 0,
  };
  var _elapsedTimer = null;

  function initState(total) {
    state.sources = {};
    SOURCE_ORDER.forEach(function (k) {
      state.sources[k] = { status: 'wait', done: 0, total: null };
    });
    state.metrics = { concurrency: 0, cap: 0, cpu: null, mem: null, avgSec: null, done: 0, total: total || 0 };
    state.logs = [];
    state.startTs = Date.now();
    state.elapsed = 0;
  }

  // ── CSS 주입 (1회) ───────────────────────────────────────────────
  var CSS_ID = 'moum-crawl-log-css';
  function injectCSS() {
    if (document.getElementById(CSS_ID)) return;
    var style = document.createElement('style');
    style.id = CSS_ID;
    style.textContent = [
      '#mcl-panel {',
      '  position:fixed; top:0; right:0; width:440px; height:100vh;',
      '  background:#191F28; color:#F2F4F6; z-index:9000;',
      '  display:flex; flex-direction:column; font-family:"Pretendard",sans-serif;',
      '  box-shadow:-8px 0 32px rgba(0,0,0,.45); transition:transform .25s ease;',
      '}',
      '#mcl-panel.mcl-hidden { transform:translateX(100%); pointer-events:none; }',

      /* 헤더 */
      '#mcl-header {',
      '  padding:16px 18px 12px; border-bottom:1px solid #2B3547; flex-shrink:0;',
      '}',
      '#mcl-header-top { display:flex; align-items:center; gap:10px; margin-bottom:10px; }',
      '#mcl-title { font-size:15px; font-weight:800; color:#F2F4F6; flex:1; }',
      '#mcl-elapsed { font-family:ui-monospace,monospace; font-size:12px; color:#8B95A1; }',
      '#mcl-close-btn {',
      '  display:none; background:none; border:none; cursor:pointer;',
      '  color:#8B95A1; font-size:18px; line-height:1; padding:2px 4px;',
      '}',
      '#mcl-close-btn:hover { color:#F2F4F6; }',
      '#mcl-overall { display:flex; align-items:center; gap:10px; }',
      '#mcl-overall-label { font-size:12px; color:#8B95A1; }',
      '#mcl-overall-cnt { font-family:ui-monospace,monospace; font-size:13px; font-weight:800; color:#3182F6; }',
      '#mcl-overall-bar { flex:1; height:5px; background:#2B3547; border-radius:3px; overflow:hidden; }',
      '#mcl-overall-fill { height:100%; background:#3182F6; border-radius:3px; transition:width .3s; width:0%; }',
      '#mcl-finish-summary {',
      '  display:none; margin-top:10px; padding:9px 12px; background:#0E3A6A;',
      '  border-radius:8px; font-size:13px; font-weight:700; color:#93C5FD;',
      '  border-left:4px solid #3182F6;',
      '}',

      /* 게이지 섹션 */
      '#mcl-gauges {',
      '  padding:12px 18px; border-bottom:1px solid #2B3547; flex-shrink:0;',
      '}',
      '.mcl-gauge-row { margin-bottom:9px; }',
      '.mcl-gauge-row:last-child { margin-bottom:0; }',
      '.mcl-gauge-head { display:flex; align-items:center; gap:8px; margin-bottom:4px; }',
      '.mcl-gauge-lbl { font-size:11.5px; font-weight:700; color:#8B95A1; }',
      '.mcl-gauge-val { margin-left:auto; font-family:ui-monospace,monospace; font-size:11px; color:#CBD2D9; }',
      '.mcl-gauge-track { height:6px; background:#2B3547; border-radius:4px; overflow:hidden; }',
      '.mcl-gauge-fill { height:100%; border-radius:4px; transition:width .35s; width:0%; }',
      '.mcl-gauge-fill.conc { background:#3182F6; }',
      '.mcl-gauge-fill.cpu  { background:#F97316; }',
      '.mcl-gauge-fill.mem  { background:#8B5CF6; }',
      '.mcl-gauge-na { font-size:11px; color:#6B7684; font-style:italic; }',

      /* 소싱처 진행 */
      '#mcl-sources {',
      '  padding:12px 18px; border-bottom:1px solid #2B3547; flex-shrink:0;',
      '}',
      '#mcl-sources-title { font-size:11.5px; font-weight:700; color:#8B95A1; margin-bottom:8px; }',
      '.mcl-src-row { display:flex; align-items:center; gap:8px; margin-bottom:6px; }',
      '.mcl-src-row:last-child { margin-bottom:0; }',
      '.mcl-src-nm { font-size:12px; font-weight:700; color:#CBD2D9; width:84px; flex-shrink:0; }',
      '.mcl-src-tag { font-size:10px; font-weight:800; padding:2px 7px; border-radius:10px; flex-shrink:0; }',
      '.mcl-src-tag.wait { background:#2B3547; color:#8B95A1; }',
      '.mcl-src-tag.run  { background:#1B3A6A; color:#60A5FA; }',
      '.mcl-src-tag.done { background:#064E3B; color:#34D399; }',
      '.mcl-src-bar-wrap { flex:1; height:5px; background:#2B3547; border-radius:3px; overflow:hidden; }',
      '.mcl-src-bar-fill { height:100%; border-radius:3px; transition:width .3s; width:0%; }',
      '.mcl-src-bar-fill.wait { background:#4B5563; }',
      '.mcl-src-bar-fill.run  { background:#3182F6; }',
      '.mcl-src-bar-fill.done { background:#10B981; }',
      '.mcl-src-cnt { font-family:ui-monospace,monospace; font-size:11px; color:#8B95A1; width:42px; text-align:right; flex-shrink:0; }',

      /* 로그 스트림 */
      '#mcl-log-wrap {',
      '  flex:1; overflow-y:auto; padding:10px 18px 14px;',
      '  min-height:0;',
      '}',
      '#mcl-log-wrap::-webkit-scrollbar { width:4px; }',
      '#mcl-log-wrap::-webkit-scrollbar-thumb { background:#2B3547; border-radius:4px; }',
      '#mcl-log-wrap::-webkit-scrollbar-track { background:transparent; }',
      '.mcl-log-line { display:flex; gap:8px; font-size:11.5px; line-height:1.5; margin-bottom:2px; }',
      '.mcl-log-ts { font-family:ui-monospace,monospace; color:#4E5968; flex-shrink:0; }',
      '.mcl-log-ico { flex-shrink:0; }',
      '.mcl-log-msg { color:#9CA3AF; word-break:break-all; }',
      '.mcl-log-line.lvl-up   .mcl-log-msg { color:#34D399; }',
      '.mcl-log-line.lvl-down .mcl-log-msg { color:#FB923C; }',
      '.mcl-log-line.lvl-warn .mcl-log-msg { color:#FBBF24; }',
      '.mcl-log-line.lvl-done .mcl-log-msg { color:#60A5FA; font-weight:700; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  // ── 패널 DOM 생성 ────────────────────────────────────────────────
  var PANEL_ID = 'mcl-panel';

  function buildPanel() {
    var p = document.createElement('div');
    p.id = PANEL_ID;
    p.classList.add('mcl-hidden');
    p.innerHTML = [
      /* 헤더 */
      '<div id="mcl-header">',
      '  <div id="mcl-header-top">',
      '    <span id="mcl-title">크롤 진행 중</span>',
      '    <span id="mcl-elapsed">0s</span>',
      '    <button id="mcl-close-btn" type="button" title="닫기">×</button>',
      '  </div>',
      '  <div id="mcl-overall">',
      '    <span id="mcl-overall-label">전체</span>',
      '    <span id="mcl-overall-cnt">0 / 0</span>',
      '    <div id="mcl-overall-bar"><div id="mcl-overall-fill"></div></div>',
      '  </div>',
      '  <div id="mcl-finish-summary"></div>',
      '</div>',
      /* 게이지 */
      '<div id="mcl-gauges">',
      '  <div class="mcl-gauge-row" id="mcl-g-conc">',
      '    <div class="mcl-gauge-head">',
      '      <span class="mcl-gauge-lbl">동시 창</span>',
      '      <span class="mcl-gauge-val" id="mcl-g-conc-val">0 / 0</span>',
      '    </div>',
      '    <div class="mcl-gauge-track"><div class="mcl-gauge-fill conc" id="mcl-g-conc-fill"></div></div>',
      '  </div>',
      '  <div class="mcl-gauge-row" id="mcl-g-cpu">',
      '    <div class="mcl-gauge-head">',
      '      <span class="mcl-gauge-lbl">CPU</span>',
      '      <span class="mcl-gauge-val" id="mcl-g-cpu-val">측정 안함</span>',
      '    </div>',
      '    <div class="mcl-gauge-track"><div class="mcl-gauge-fill cpu" id="mcl-g-cpu-fill"></div></div>',
      '  </div>',
      '  <div class="mcl-gauge-row" id="mcl-g-mem">',
      '    <div class="mcl-gauge-head">',
      '      <span class="mcl-gauge-lbl">메모리</span>',
      '      <span class="mcl-gauge-val" id="mcl-g-mem-val">측정 안함</span>',
      '    </div>',
      '    <div class="mcl-gauge-track"><div class="mcl-gauge-fill mem" id="mcl-g-mem-fill"></div></div>',
      '  </div>',
      '</div>',
      /* 소싱처 */
      '<div id="mcl-sources">',
      '  <div id="mcl-sources-title">소싱처별 진행</div>',
      '  <div id="mcl-src-list"></div>',
      '</div>',
      /* 로그 */
      '<div id="mcl-log-wrap"><div id="mcl-log-list"></div></div>',
    ].join('');
    document.body.appendChild(p);

    /* 닫기 버튼 */
    document.getElementById('mcl-close-btn').addEventListener('click', function () {
      hidePanel();
    });

    return p;
  }

  function getPanel() {
    return document.getElementById(PANEL_ID) || buildPanel();
  }

  function showPanel() {
    var p = getPanel();
    p.classList.remove('mcl-hidden');
  }

  function hidePanel() {
    var p = document.getElementById(PANEL_ID);
    if (p) p.classList.add('mcl-hidden');
  }

  // ── 렌더 헬퍼 ────────────────────────────────────────────────────
  function safeText(el, txt) {
    if (el) el.textContent = String(txt == null ? '' : txt);
  }

  function setWidth(el, pct) {
    if (el) el.style.width = Math.min(100, Math.max(0, pct)) + '%';
  }

  function renderGauges() {
    var m = state.metrics;

    /* 동시 창 */
    var concPct = m.cap > 0 ? (m.concurrency / m.cap * 100) : 0;
    safeText(document.getElementById('mcl-g-conc-val'), m.concurrency + ' / ' + m.cap);
    setWidth(document.getElementById('mcl-g-conc-fill'), concPct);

    /* CPU */
    var cpuVal = document.getElementById('mcl-g-cpu-val');
    var cpuFill = document.getElementById('mcl-g-cpu-fill');
    if (m.cpu == null) {
      safeText(cpuVal, '측정 안함');
      setWidth(cpuFill, 0);
    } else {
      safeText(cpuVal, m.cpu + '%');
      setWidth(cpuFill, m.cpu);
    }

    /* 메모리 */
    var memVal = document.getElementById('mcl-g-mem-val');
    var memFill = document.getElementById('mcl-g-mem-fill');
    if (m.mem == null) {
      safeText(memVal, '측정 안함');
      setWidth(memFill, 0);
    } else {
      safeText(memVal, m.mem + '%');
      setWidth(memFill, m.mem);
    }
  }

  function renderOverall() {
    var m = state.metrics;
    var total = m.total || 0;
    var done = m.done || 0;
    var pct = total > 0 ? (done / total * 100) : 0;
    safeText(document.getElementById('mcl-overall-cnt'), done + ' / ' + total);
    setWidth(document.getElementById('mcl-overall-fill'), pct);
  }

  function renderSources() {
    var list = document.getElementById('mcl-src-list');
    if (!list) return;
    var html = '';
    SOURCE_ORDER.forEach(function (k) {
      var s = state.sources[k] || { status: 'wait', done: 0, total: null };
      var st = s.status;
      var lbl = SOURCE_LABELS[k] || k;
      var pct = (s.total != null && s.total > 0)
        ? Math.min(100, Math.round(s.done / s.total * 100))
        : (st === 'done' ? 100 : 0);
      var tagTxt = st === 'run' ? '진행중' : st === 'done' ? '완료' : '대기';
      var cntTxt = (s.total != null) ? (s.done + '/' + s.total) : '';
      /* XSS 안전: lbl, tagTxt, cntTxt, pct 모두 우리가 만든 값. k는 소싱처 키(영문). */
      html += '<div class="mcl-src-row">';
      html += '<span class="mcl-src-nm">' + lbl + '</span>';
      html += '<span class="mcl-src-tag ' + st + '">' + tagTxt + '</span>';
      html += '<div class="mcl-src-bar-wrap"><div class="mcl-src-bar-fill ' + st + '" style="width:' + pct + '%"></div></div>';
      html += '<span class="mcl-src-cnt">' + cntTxt + '</span>';
      html += '</div>';
    });
    list.innerHTML = html;
  }

  function renderElapsed() {
    var sec = Math.floor((Date.now() - state.startTs) / 1000);
    var txt;
    if (sec < 60) {
      txt = sec + 's';
    } else {
      txt = Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
    }
    safeText(document.getElementById('mcl-elapsed'), txt);
  }

  /* 로그 자동스크롤 — 사용자가 위로 스크롤 중이면 건드리지 않는다 */
  function appendLog(ts, level, msg) {
    var wrap = document.getElementById('mcl-log-wrap');
    var logList = document.getElementById('mcl-log-list');
    if (!wrap || !logList) return;

    /* 스크롤이 맨 아래 근처(16px 이내)인지 확인 */
    var atBottom = (wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight) <= 16;

    var d = new Date(ts);
    var hh = String(d.getHours()).padStart(2, '0');
    var mm = String(d.getMinutes()).padStart(2, '0');
    var ss = String(d.getSeconds()).padStart(2, '0');
    var timeStr = hh + ':' + mm + ':' + ss;

    var ico = level === 'up' ? '▲' : level === 'down' ? '▼' : level === 'warn' ? '⚠' : level === 'done' ? '✓' : '·';

    var row = document.createElement('div');
    row.className = 'mcl-log-line' + (level ? ' lvl-' + level : '');

    var tsSpan = document.createElement('span');
    tsSpan.className = 'mcl-log-ts';
    tsSpan.textContent = timeStr;

    var icoSpan = document.createElement('span');
    icoSpan.className = 'mcl-log-ico';
    icoSpan.textContent = ico;

    var msgSpan = document.createElement('span');
    msgSpan.className = 'mcl-log-msg';
    msgSpan.textContent = msg;  /* XSS 안전: textContent */

    row.appendChild(tsSpan);
    row.appendChild(icoSpan);
    row.appendChild(msgSpan);
    logList.appendChild(row);

    /* 로그 최대 200줄 유지 (DOM 누적 방지) */
    var lines = logList.children;
    if (lines.length > 200) {
      logList.removeChild(lines[0]);
    }

    if (atBottom) {
      wrap.scrollTop = wrap.scrollHeight;
    }
  }

  /* metrics 부분 갱신 — null 인 필드는 덮어쓰지 않음 */
  function mergeMetrics(m) {
    if (!m) return;
    var keys = ['concurrency', 'cap', 'cpu', 'mem', 'avgSec', 'done', 'total'];
    keys.forEach(function (k) {
      if (m[k] != null) state.metrics[k] = m[k];
    });
  }

  // ── 경과 타이머 ──────────────────────────────────────────────────
  function startElapsedTimer() {
    stopElapsedTimer();
    renderElapsed();
    _elapsedTimer = setInterval(function () {
      renderElapsed();
    }, 1000);
  }

  function stopElapsedTimer() {
    if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
  }

  // ── 이벤트 핸들러 ────────────────────────────────────────────────
  var _registered = false;

  function handleCrawlLog(e) {
    var d = e.detail;
    if (!d) return;
    var type = d.type;
    var ts = d.ts || Date.now();
    var src = d.source;
    var level = d.level || '';
    var msg = d.msg || '';
    var m = d.metrics;

    switch (type) {

      case 'start': {
        /* 패널 생성·표시, 상태 초기화 */
        injectCSS();
        var total = (m && m.total) || 0;
        initState(total);
        buildPanel(); /* 중복 방지: buildPanel 내부에서 기존 패널 제거 후 재생성 */
        showPanel();
        startElapsedTimer();
        mergeMetrics(m);
        renderAll();
        appendLog(ts, level, msg);
        /* 완료 배너·닫기 버튼 초기 숨김 */
        var finDiv = document.getElementById('mcl-finish-summary');
        if (finDiv) finDiv.style.display = 'none';
        var closeBtn = document.getElementById('mcl-close-btn');
        if (closeBtn) closeBtn.style.display = 'none';
        break;
      }

      case 'concurrency': {
        mergeMetrics(m);
        renderGauges();
        appendLog(ts, level, msg);
        break;
      }

      case 'resource': {
        mergeMetrics(m);
        renderGauges();
        appendLog(ts, level, msg);
        break;
      }

      case 'window-open': {
        /* 해당 source 상태 → '진행' */
        if (src && state.sources[src]) {
          state.sources[src].status = 'run';
        }
        mergeMetrics(m);
        renderSources();
        renderGauges();
        appendLog(ts, level, msg);
        break;
      }

      case 'item-done': {
        /* source done++ / 전체 done 갱신 */
        if (src && state.sources[src]) {
          state.sources[src].done = (state.sources[src].done || 0) + 1;
          /* total은 bySource 목록 길이인데 직접 알 수 없음 — metrics.done/total 기준 */
        }
        mergeMetrics(m);
        /* avgSec 게이지 반영: 동시창 게이지에 avgSec 표기 추가 */
        if (state.metrics.avgSec != null) {
          var avgEl = document.getElementById('mcl-g-conc-val');
          if (avgEl) {
            avgEl.textContent = state.metrics.concurrency + ' / ' + state.metrics.cap
              + '  (중앙 ' + state.metrics.avgSec + 's)';
          }
        }
        renderOverall();
        renderSources();
        appendLog(ts, level, msg);
        break;
      }

      case 'source-done': {
        /* 해당 source 완료, 진행바 100% */
        if (src && state.sources[src]) {
          var s = state.sources[src];
          s.status = 'done';
          /* done/total 을 metrics 에서 추론: total = metrics.total 기준으론 전체라 그대로,
             source 단위 total 을 모르면 done == done 으로 막힘. done을 total과 같이 표시하기 위해 */
          if (s.total != null) {
            s.done = s.total;
          }
        }
        mergeMetrics(m);
        renderSources();
        renderOverall();
        appendLog(ts, level, msg);
        break;
      }

      case 'finish': {
        /* 경과 타이머 중단, 요약 강조, 닫기 버튼 노출 */
        stopElapsedTimer();
        mergeMetrics(m);
        renderAll();
        appendLog(ts, level, msg);

        /* 완료 배너 */
        var summary = document.getElementById('mcl-finish-summary');
        if (summary) {
          summary.style.display = 'block';
          summary.textContent = msg;  /* XSS 안전: textContent */
        }

        /* 타이틀 갱신 */
        safeText(document.getElementById('mcl-title'), '크롤 완료');

        /* 닫기 버튼 노출 */
        var closeBtnF = document.getElementById('mcl-close-btn');
        if (closeBtnF) closeBtnF.style.display = 'inline-block';

        /* 완료된 소싱처 전부 done 으로 마킹 */
        SOURCE_ORDER.forEach(function (k) {
          if (state.sources[k] && state.sources[k].status === 'run') {
            state.sources[k].status = 'done';
          }
        });
        renderSources();
        break;
      }
    }
  }

  function renderAll() {
    renderGauges();
    renderOverall();
    renderSources();
  }

  // buildPanel 을 중복 방지 처리: 기존 패널 있으면 제거 후 새로 생성
  // (이미 선언된 buildPanel 을 덮어쓰는 형태로 래핑)
  var _buildPanelOrig = buildPanel;
  buildPanel = function () { // eslint-disable-line no-func-assign
    var old = document.getElementById(PANEL_ID);
    if (old) old.parentNode.removeChild(old);
    return _buildPanelOrig();
  };

  // ── 리스너 등록 (DOMContentLoaded 후, 또는 이미 로드됐으면 즉시) ──
  function register() {
    if (_registered) return;
    _registered = true;
    window.addEventListener('moum-crawl-log', handleCrawlLog);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', register);
  } else {
    register();
  }

})();

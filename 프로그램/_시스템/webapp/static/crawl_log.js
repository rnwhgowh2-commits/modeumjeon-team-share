// crawl_log.js — Phase 4 실시간 크롤 대시보드 (D안: 소싱처별 카드 + 인라인 펼침)
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
  // bySource: key → { status:'wait'|'run'|'done', done:0, total:null, logs:[],
  //                   expanded:bool, el:cardEl, logListEl:el, logToggleEl:el,
  //                   barFillEl:el, tagEl:el, cntEl:el }
  var bySource = {};

  var metrics = { concurrency: 0, cap: 0, active: 0, cpu: null, mem: null, avgSec: null, done: 0, total: 0 };
  var startTs = 0;
  var _elapsedTimer = null;

  function initState(total) {
    bySource = {};
    metrics = { concurrency: 0, cap: 0, active: 0, cpu: null, mem: null, avgSec: null, done: 0, total: total || 0 };
    startTs = Date.now();
  }

  // ── CSS 주입 (1회) ───────────────────────────────────────────────
  var CSS_ID = 'moum-crawl-log-css';
  function injectCSS() {
    if (document.getElementById(CSS_ID)) return;
    var style = document.createElement('style');
    style.id = CSS_ID;
    style.textContent = [
      /* 패널 */
      '#mcl-panel {',
      '  position:fixed; top:0; right:0; width:440px; height:100vh;',
      '  background:#141B22; color:#CBD5E1; z-index:9000;',
      '  display:flex; flex-direction:column; font-family:"Pretendard",sans-serif;',
      '  box-shadow:-8px 0 32px rgba(0,0,0,.45); transition:transform .25s ease;',
      '}',
      '#mcl-panel.mcl-hidden { transform:translateX(100%); pointer-events:none; }',

      /* 헤더 */
      '#mcl-header {',
      '  padding:16px 18px 12px; border-bottom:1px solid #25303b; flex-shrink:0;',
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
      '#mcl-overall-bar { flex:1; height:5px; background:#25303b; border-radius:3px; overflow:hidden; }',
      '#mcl-overall-fill { height:100%; background:#3182F6; border-radius:3px; transition:width .3s; width:0%; }',
      '#mcl-finish-summary {',
      '  display:none; margin-top:10px; padding:9px 12px; background:#0E3A6A;',
      '  border-radius:8px; font-size:13px; font-weight:700; color:#93C5FD;',
      '  border-left:4px solid #3182F6;',
      '}',

      /* 게이지 섹션 */
      '#mcl-gauges {',
      '  padding:12px 18px; border-bottom:1px solid #25303b; flex-shrink:0;',
      '}',
      '.mcl-gauge-row { margin-bottom:9px; }',
      '.mcl-gauge-row:last-child { margin-bottom:0; }',
      '.mcl-gauge-head { display:flex; align-items:center; gap:8px; margin-bottom:4px; }',
      '.mcl-gauge-lbl { font-size:11.5px; font-weight:700; color:#8B95A1; }',
      '.mcl-gauge-val { margin-left:auto; font-family:ui-monospace,monospace; font-size:11px; color:#CBD5E1; }',
      '.mcl-gauge-track { height:6px; background:#25303b; border-radius:4px; overflow:hidden; }',
      '.mcl-gauge-fill { height:100%; border-radius:4px; transition:width .35s; width:0%; }',
      '.mcl-gauge-fill.conc { background:#3182F6; }',
      '.mcl-gauge-fill.cpu  { background:#F97316; }',
      '.mcl-gauge-fill.mem  { background:#8B5CF6; }',

      /* 소싱처 카드 스크롤 영역 */
      '#mcl-cards-wrap {',
      '  flex:1; overflow-y:auto; padding:10px 14px 16px;',
      '  min-height:0;',
      '}',
      '#mcl-cards-wrap::-webkit-scrollbar { width:4px; }',
      '#mcl-cards-wrap::-webkit-scrollbar-thumb { background:#25303b; border-radius:4px; }',
      '#mcl-cards-wrap::-webkit-scrollbar-track { background:transparent; }',

      /* 개별 카드 */
      '.mcl-card {',
      '  background:#1A2332; border:1px solid #25303b; border-radius:8px;',
      '  margin-bottom:8px; overflow:hidden;',
      '}',
      '.mcl-card:last-child { margin-bottom:0; }',

      /* 카드 헤더 행 */
      '.mcl-card-header {',
      '  display:flex; align-items:center; gap:8px; padding:9px 12px 8px;',
      '}',
      '.mcl-card-name {',
      '  font-size:12px; font-weight:700; color:#CBD5E1; min-width:76px;',
      '}',
      '.mcl-card-tag {',
      '  font-size:10px; font-weight:800; padding:2px 7px; border-radius:10px; flex-shrink:0;',
      '}',
      '.mcl-card-tag.wait { background:#25303b; color:#8B95A1; }',
      '.mcl-card-tag.run  { background:#1B3A6A; color:#60A5FA; }',
      '.mcl-card-tag.done { background:#064E3B; color:#34D399; }',
      '.mcl-card-cnt {',
      '  font-family:ui-monospace,monospace; font-size:11px; color:#8B95A1;',
      '  margin-left:auto; flex-shrink:0;',
      '}',
      '.mcl-card-toggle {',
      '  font-size:11px; color:#60A5FA; background:none; border:none; cursor:pointer;',
      '  padding:0 0 0 8px; flex-shrink:0; white-space:nowrap;',
      '}',
      '.mcl-card-toggle:hover { color:#93C5FD; }',

      /* 카드 진행바 */
      '.mcl-card-bar-wrap {',
      '  height:4px; background:#25303b; margin:0 12px 8px;',
      '  border-radius:3px; overflow:hidden;',
      '}',
      '.mcl-card-bar-fill {',
      '  height:100%; border-radius:3px; transition:width .3s; width:0%;',
      '}',
      '.mcl-card-bar-fill.wait { background:#4B5563; }',
      '.mcl-card-bar-fill.run  { background:#38bdf8; }',
      '.mcl-card-bar-fill.done { background:#4ADE80; }',

      /* 카드 인라인 로그 */
      '.mcl-card-logs {',
      '  border-top:1px solid #25303b; padding:6px 12px 8px;',
      '  max-height:180px; overflow-y:auto;',
      '}',
      '.mcl-card-logs::-webkit-scrollbar { width:3px; }',
      '.mcl-card-logs::-webkit-scrollbar-thumb { background:#25303b; border-radius:3px; }',
      '.mcl-card-logs::-webkit-scrollbar-track { background:transparent; }',
      '.mcl-card-logs.mcl-hidden { display:none; }',

      /* 로그 라인 */
      '.mcl-log-line { display:flex; gap:7px; font-size:11px; line-height:1.5; margin-bottom:1px; }',
      '.mcl-log-ts { font-family:ui-monospace,monospace; color:#4E5968; flex-shrink:0; }',
      '.mcl-log-ico { flex-shrink:0; }',
      '.mcl-log-msg { color:#9CA3AF; word-break:break-all; }',
      '.mcl-log-line.lvl-up   .mcl-log-msg { color:#4ADE80; }',
      '.mcl-log-line.lvl-down .mcl-log-msg { color:#FB923C; }',
      '.mcl-log-line.lvl-warn .mcl-log-msg { color:#FBBF24; }',
      '.mcl-log-line.lvl-done .mcl-log-msg { color:#60A5FA; font-weight:700; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  // ── 패널 DOM 생성 ────────────────────────────────────────────────
  var PANEL_ID = 'mcl-panel';

  function buildPanelDOM() {
    var old = document.getElementById(PANEL_ID);
    if (old) old.parentNode.removeChild(old);

    var p = document.createElement('div');
    p.id = PANEL_ID;
    p.classList.add('mcl-hidden');
    p.innerHTML = [
      /* 헤더 */
      '<div id="mcl-header">',
      '  <div id="mcl-header-top">',
      '    <span id="mcl-title">크롤 진행 중</span>',
      '    <span id="mcl-elapsed">0s</span>',
      '    <button id="mcl-close-btn" type="button" title="닫기">\xd7</button>',
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
      '  <div class="mcl-gauge-row">',
      '    <div class="mcl-gauge-head">',
      '      <span class="mcl-gauge-lbl">동시 창</span>',
      '      <span class="mcl-gauge-val" id="mcl-g-conc-val">0 / 0</span>',
      '    </div>',
      '    <div class="mcl-gauge-track"><div class="mcl-gauge-fill conc" id="mcl-g-conc-fill"></div></div>',
      '  </div>',
      '  <div class="mcl-gauge-row">',
      '    <div class="mcl-gauge-head">',
      '      <span class="mcl-gauge-lbl">CPU</span>',
      '      <span class="mcl-gauge-val" id="mcl-g-cpu-val">측정 안함</span>',
      '    </div>',
      '    <div class="mcl-gauge-track"><div class="mcl-gauge-fill cpu" id="mcl-g-cpu-fill"></div></div>',
      '  </div>',
      '  <div class="mcl-gauge-row">',
      '    <div class="mcl-gauge-head">',
      '      <span class="mcl-gauge-lbl">메모리</span>',
      '      <span class="mcl-gauge-val" id="mcl-g-mem-val">측정 안함</span>',
      '    </div>',
      '    <div class="mcl-gauge-track"><div class="mcl-gauge-fill mem" id="mcl-g-mem-fill"></div></div>',
      '  </div>',
      '</div>',
      /* 소싱처 카드 */
      '<div id="mcl-cards-wrap"></div>',
    ].join('');
    document.body.appendChild(p);

    document.getElementById('mcl-close-btn').addEventListener('click', function () {
      var panel = document.getElementById(PANEL_ID);
      if (panel) panel.classList.add('mcl-hidden');
    });

    return p;
  }

  function showPanel() {
    var p = document.getElementById(PANEL_ID);
    if (p) p.classList.remove('mcl-hidden');
  }

  // ── 렌더 헬퍼 ────────────────────────────────────────────────────
  function safeText(el, txt) {
    if (el) el.textContent = String(txt == null ? '' : txt);
  }

  function setWidth(el, pct) {
    if (el) el.style.width = Math.min(100, Math.max(0, pct)) + '%';
  }

  function fmtTime(ts) {
    var d = new Date(ts);
    var hh = String(d.getHours()).padStart(2, '0');
    var mm = String(d.getMinutes()).padStart(2, '0');
    var ss = String(d.getSeconds()).padStart(2, '0');
    return hh + ':' + mm + ':' + ss;
  }

  function icoForLevel(level) {
    if (level === 'up')   return '▲';
    if (level === 'down') return '▼';
    if (level === 'warn') return '⚠';
    if (level === 'done') return '✓';
    return '\xb7';
  }

  // ── 게이지 렌더 ─────────────────────────────────────────────────
  function renderGauges() {
    var m = metrics;
    var activeWin = (m.active != null) ? m.active : m.concurrency;
    var concPct   = m.cap > 0 ? (activeWin / m.cap * 100) : 0;
    var concLabel = activeWin + ' / ' + m.cap + '  (목표 ' + m.concurrency + ')';
    if (m.avgSec != null) {
      concLabel += ' · 중앙 ' + m.avgSec + 's';
    }
    safeText(document.getElementById('mcl-g-conc-val'), concLabel);
    setWidth(document.getElementById('mcl-g-conc-fill'), concPct);

    var cpuVal  = document.getElementById('mcl-g-cpu-val');
    var cpuFill = document.getElementById('mcl-g-cpu-fill');
    if (m.cpu == null) {
      safeText(cpuVal, '측정 안함');
      setWidth(cpuFill, 0);
    } else {
      safeText(cpuVal, m.cpu + '%');
      setWidth(cpuFill, m.cpu);
    }

    var memVal  = document.getElementById('mcl-g-mem-val');
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
    var total = metrics.total || 0;
    var done  = metrics.done  || 0;
    var pct   = total > 0 ? (done / total * 100) : 0;
    safeText(document.getElementById('mcl-overall-cnt'), done + ' / ' + total);
    setWidth(document.getElementById('mcl-overall-fill'), pct);
  }

  // ── metrics 부분 갱신 — null 인 필드는 덮어쓰지 않음 ───────────
  function mergeMetrics(m) {
    if (!m) return;
    var keys = ['concurrency', 'cap', 'active', 'cpu', 'mem', 'avgSec', 'done', 'total'];
    keys.forEach(function (k) {
      if (m[k] != null) metrics[k] = m[k];
    });
  }

  // ── 경과 타이머 ─────────────────────────────────────────────────
  function renderElapsed() {
    var sec = Math.floor((Date.now() - startTs) / 1000);
    var txt = sec < 60 ? (sec + 's') : (Math.floor(sec / 60) + 'm ' + (sec % 60) + 's');
    safeText(document.getElementById('mcl-elapsed'), txt);
  }

  function startElapsedTimer() {
    stopElapsedTimer();
    renderElapsed();
    _elapsedTimer = setInterval(renderElapsed, 1000);
  }

  function stopElapsedTimer() {
    if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
  }

  // ── 소싱처 카드 생성 ─────────────────────────────────────────────
  function createSourceCard(key, autoExpand) {
    var lbl  = SOURCE_LABELS[key] || key;
    var card = document.createElement('div');
    card.className = 'mcl-card';
    card.id = 'mcl-card-' + key;

    /* 헤더 행 */
    var header = document.createElement('div');
    header.className = 'mcl-card-header';

    var nameEl = document.createElement('span');
    nameEl.className = 'mcl-card-name';
    nameEl.textContent = lbl;

    var tagEl = document.createElement('span');
    tagEl.className = 'mcl-card-tag wait';
    tagEl.textContent = '대기';

    var cntEl = document.createElement('span');
    cntEl.className = 'mcl-card-cnt';
    cntEl.textContent = '';

    var toggleEl = document.createElement('button');
    toggleEl.type = 'button';
    toggleEl.className = 'mcl-card-toggle';
    toggleEl.textContent = '로그 0건 ▾';

    header.appendChild(nameEl);
    header.appendChild(tagEl);
    header.appendChild(cntEl);
    header.appendChild(toggleEl);

    /* 진행바 */
    var barWrap = document.createElement('div');
    barWrap.className = 'mcl-card-bar-wrap';
    var barFill = document.createElement('div');
    barFill.className = 'mcl-card-bar-fill wait';
    barWrap.appendChild(barFill);

    /* 인라인 로그 영역 */
    var logArea = document.createElement('div');
    logArea.className = 'mcl-card-logs' + (autoExpand ? '' : ' mcl-hidden');

    card.appendChild(header);
    card.appendChild(barWrap);
    card.appendChild(logArea);

    /* 토글 클릭 */
    toggleEl.addEventListener('click', function () {
      var bk = bySource[key];
      if (!bk) return;
      bk.expanded = !bk.expanded;
      if (bk.expanded) {
        logArea.classList.remove('mcl-hidden');
        /* 열릴 때 맨 아래로 스크롤 */
        logArea.scrollTop = logArea.scrollHeight;
      } else {
        logArea.classList.add('mcl-hidden');
      }
      updateToggleLabel(key);
    });

    /* 카드를 wrap에 삽입 (SOURCE_ORDER 순서 유지) */
    var wrap = document.getElementById('mcl-cards-wrap');
    if (wrap) {
      /* SOURCE_ORDER 기준 올바른 위치 찾기 */
      var myIdx = SOURCE_ORDER.indexOf(key);
      var inserted = false;
      var existingCards = wrap.children;
      for (var i = 0; i < existingCards.length; i++) {
        var cardId = existingCards[i].id; // 'mcl-card-<key>'
        var cardKey = cardId.replace('mcl-card-', '');
        if (SOURCE_ORDER.indexOf(cardKey) > myIdx) {
          wrap.insertBefore(card, existingCards[i]);
          inserted = true;
          break;
        }
      }
      if (!inserted) wrap.appendChild(card);
    }

    /* bySource 버킷 등록 */
    bySource[key] = {
      status:     'wait',
      done:       0,
      total:      null,
      logs:       [],
      expanded:   !!autoExpand,
      el:         card,
      logListEl:  logArea,
      barFillEl:  barFill,
      tagEl:      tagEl,
      cntEl:      cntEl,
      toggleEl:   toggleEl,
    };

    return bySource[key];
  }

  function getOrCreateBucket(key) {
    if (!bySource[key]) {
      createSourceCard(key, false);
    }
    return bySource[key];
  }

  // ── 카드 상태 갱신 ───────────────────────────────────────────────
  function updateCardStatus(key, status) {
    var bk = bySource[key];
    if (!bk) return;
    bk.status = status;

    /* 태그 */
    bk.tagEl.className = 'mcl-card-tag ' + status;
    bk.tagEl.textContent = status === 'run' ? '진행중' : status === 'done' ? '완료' : '대기';

    /* 진행바 색 */
    bk.barFillEl.className = 'mcl-card-bar-fill ' + status;

    /* 진행중이면 자동 펼침 */
    if (status === 'run' && !bk.expanded) {
      bk.expanded = true;
      bk.logListEl.classList.remove('mcl-hidden');
    }
    /* 완료이면 자동 접힘 */
    if (status === 'done' && bk.expanded) {
      bk.expanded = false;
      bk.logListEl.classList.add('mcl-hidden');
    }
    updateToggleLabel(key);
  }

  function updateCardProgress(key) {
    var bk = bySource[key];
    if (!bk) return;
    var total = bk.total;
    var done  = bk.done;
    var pct;
    if (bk.status === 'done') {
      pct = 100;
    } else if (total != null && total > 0) {
      pct = Math.min(100, Math.round(done / total * 100));
    } else {
      pct = 0;
    }
    bk.barFillEl.style.width = pct + '%';
    bk.cntEl.textContent = (total != null) ? (done + '/' + total) : (done > 0 ? done + '' : '');
  }

  function updateToggleLabel(key) {
    var bk = bySource[key];
    if (!bk) return;
    var cnt   = bk.logs.length;
    var arrow = bk.expanded ? '▴' : '▾';
    bk.toggleEl.textContent = '로그 ' + cnt + '건 ' + arrow;
  }

  // ── 카드 로그 추가 ───────────────────────────────────────────────
  function appendCardLog(key, ts, level, msg) {
    var bk = bySource[key];
    if (!bk) return;

    /* 로그 배열 누적 (최대 200) */
    bk.logs.push({ ts: ts, level: level, msg: msg });
    if (bk.logs.length > 200) bk.logs.shift();

    /* DOM 행 생성 (XSS: textContent) */
    var logArea = bk.logListEl;
    var atBottom = (logArea.scrollHeight - logArea.scrollTop - logArea.clientHeight) <= 16;

    var row = document.createElement('div');
    row.className = 'mcl-log-line' + (level ? ' lvl-' + level : '');

    var tsSpan = document.createElement('span');
    tsSpan.className = 'mcl-log-ts';
    tsSpan.textContent = fmtTime(ts);

    var icoSpan = document.createElement('span');
    icoSpan.className = 'mcl-log-ico';
    icoSpan.textContent = icoForLevel(level);

    var msgSpan = document.createElement('span');
    msgSpan.className = 'mcl-log-msg';
    msgSpan.textContent = msg;   /* XSS 안전: textContent */

    row.appendChild(tsSpan);
    row.appendChild(icoSpan);
    row.appendChild(msgSpan);
    logArea.appendChild(row);

    /* DOM 로그 최대 200줄 유지 */
    var lines = logArea.children;
    if (lines.length > 200) logArea.removeChild(lines[0]);

    /* 펼쳐져 있고 맨 아래 근처일 때만 auto-scroll */
    if (bk.expanded && atBottom) {
      logArea.scrollTop = logArea.scrollHeight;
    }

    updateToggleLabel(key);
  }

  // ── 이벤트 핸들러 ────────────────────────────────────────────────
  var _registered = false;

  function handleCrawlLog(e) {
    var d = e.detail;
    if (!d) return;
    var type  = d.type;
    var ts    = d.ts || Date.now();
    var src   = d.source;   // 소싱처 키 또는 null
    var level = d.level || '';
    var msg   = d.msg || '';
    var m     = d.metrics;

    switch (type) {

      case 'start': {
        injectCSS();
        var total = (m && m.total) || 0;
        initState(total);
        buildPanelDOM();
        showPanel();
        startElapsedTimer();
        mergeMetrics(m);
        renderGauges();
        renderOverall();
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
        /* source=null 이므로 카드 없음 */
        break;
      }

      case 'resource': {
        mergeMetrics(m);
        renderGauges();
        break;
      }

      case 'window-open': {
        /* 해당 source 카드 → 진행중, 로그 추가 */
        if (src) {
          var bkWO = getOrCreateBucket(src);
          updateCardStatus(src, 'run');
          /* total 초기화 — 이후 item-done metrics.done/total 로 보정 */
          bkWO.done  = 0;
          bkWO.total = null;
          updateCardProgress(src);
          appendCardLog(src, ts, level, msg || '창 시작');
        }
        mergeMetrics(m);
        renderGauges();
        break;
      }

      case 'item-done': {
        if (src) {
          var bkID = getOrCreateBucket(src);
          bkID.done = (bkID.done || 0) + 1;
          /* source 단위 total 은 모름 — 카드 카운터는 누적 done 만 표시 */
          updateCardProgress(src);
          appendCardLog(src, ts, level, msg);
        }
        mergeMetrics(m);
        renderGauges();
        renderOverall();
        break;
      }

      case 'source-done': {
        if (src) {
          var bkSD = getOrCreateBucket(src);
          /* 완료 처리 */
          if (bkSD.total != null) {
            bkSD.done = bkSD.total;
          }
          updateCardProgress(src);
          updateCardStatus(src, 'done');
          appendCardLog(src, ts, level, msg);
        }
        mergeMetrics(m);
        renderGauges();
        renderOverall();
        break;
      }

      case 'finish': {
        stopElapsedTimer();
        mergeMetrics(m);
        renderGauges();
        renderOverall();

        /* 아직 run 상태인 카드 done으로 마킹 */
        SOURCE_ORDER.forEach(function (k) {
          if (bySource[k] && bySource[k].status === 'run') {
            updateCardStatus(k, 'done');
          }
        });

        /* 완료 배너 */
        var finSummary = document.getElementById('mcl-finish-summary');
        if (finSummary) {
          finSummary.style.display = 'block';
          finSummary.textContent = msg;   /* XSS 안전: textContent */
        }

        /* 타이틀 갱신 */
        safeText(document.getElementById('mcl-title'), '크롤 완료');

        /* 닫기 버튼 노출 */
        var closeBtnF = document.getElementById('mcl-close-btn');
        if (closeBtnF) closeBtnF.style.display = 'inline-block';
        break;
      }
    }
  }

  // ── 리스너 등록 ─────────────────────────────────────────────────
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

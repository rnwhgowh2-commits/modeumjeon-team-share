/* margin_app.js — 마진계산기 화면. 서버가 계산한 결과를 렌더만 한다. */
(function (root) {
  'use strict';
  var state = { data: null };

  function won(v) {
    var n = Number(String(v == null ? 0 : v).replace(/,/g, ''));
    if (!isFinite(n)) n = 0;
    return n.toLocaleString('en-US');
  }
  function $(id) { return document.getElementById(id); }
  function post(url, body, isForm) {
    return fetch(url, isForm ? { method: 'POST', body: body }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, j: j }; }); });
  }

  function init() {
    if (!document.getElementById('margin-app')) return;
    var buyFile = $('mg-buy-file'), smFile = $('mg-sm-file');
    buyFile.addEventListener('change', function () { uploadBuy(buyFile.files[0]); });
    smFile.addEventListener('change', function () { uploadShopmine(smFile.files[0]); });
    $('mg-analyze-btn').addEventListener('click', analyze);
    bindSubnav();
    loadHistory();
  }

  function uploadBuy(file) {
    if (!file) return;
    var fd = new FormData(); fd.append('file', file);
    $('mg-buy-status').textContent = '읽는 중…';
    post('/api/margin/upload', fd, true).then(function (res) {
      if (!res.ok) { $('mg-buy-status').textContent = '오류: ' + (res.j.error || res.status); return; }
      var j = res.j;
      $('mg-buy-status').textContent = '매입 ' + j.rows + '건 · ' + (j.markets || []).join(', ');
      $('mg-since').value = j.period_from; $('mg-until').value = j.period_to;
      $('mg-period-auto').textContent = '(엑셀에서 자동 추론 — 바꿀 수 있어요)';
      document.querySelector('.mg-urow[data-step=buy]').classList.add('done');
      $('mg-analyze-btn').disabled = false;
      $('mg-analyze-status').textContent = '기간 확인 후 분석 시작을 누르세요';
    });
  }

  function uploadShopmine(file) {
    if (!file) return;
    var fd = new FormData(); fd.append('file', file);
    $('mg-sm-status').textContent = '읽는 중…';
    post('/api/margin/upload-shopmine', fd, true).then(function (res) {
      $('mg-sm-status').textContent = res.ok
        ? ('옥션·G마켓 ' + res.j.rows + '건 추가됨') : ('오류: ' + (res.j.error || res.status));
    });
  }

  function analyze() {
    var since = $('mg-since').value, until = $('mg-until').value;
    if (!since || !until) { $('mg-analyze-status').textContent = '조회 기간을 정하세요'; return; }
    $('mg-analyze-btn').disabled = true;
    $('mg-analyze-status').textContent = '마켓 주문 불러오는 중… (수십 초 걸릴 수 있어요)';
    post('/api/margin/analyze', { since: since, until: until }).then(function (res) {
      $('mg-analyze-btn').disabled = false;
      if (!res.ok) {
        $('mg-analyze-status').textContent = '실패: ' + (res.j.error || res.status);
        showWarn([res.j.error || ('분석 실패 (' + res.status + ')')]);
        return;
      }
      $('mg-analyze-status').textContent = '분석 완료 · ' + res.j.counts.matched + '건 매칭';
      render(res.j);
      loadHistory();
    });
  }

  function showWarn(lines) {
    var w = $('mg-warn');
    if (!lines || !lines.length) { w.hidden = true; return; }
    w.hidden = false;
    w.innerHTML = lines.map(function (l) { return '⚠ ' + l; }).join('<br>');
  }

  function render(data) {
    state.data = data;
    $('mg-empty').hidden = true; $('mg-panes').hidden = false;
    showWarn(data.markets_failed || []);
    if (root.MG_RENDER) root.MG_RENDER(data);  // Task 4+ 가 채우는 렌더러
  }

  function bindSubnav() {
    var nav = $('mg-subnav');
    nav.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-mtab]'); if (!a) return;
      nav.querySelectorAll('a').forEach(function (x) { x.classList.remove('on'); });
      a.classList.add('on');
      if (state.data && root.MG_SHOW_TAB) root.MG_SHOW_TAB(a.dataset.mtab, state.data);
    });
  }

  function loadHistory() {
    fetch('/api/margin/analyses').then(function (r) { return r.json(); }).then(function (list) {
      var box = $('mg-history-list'); if (!box) return;
      if (!list || !list.length) { box.innerHTML = '<div class="mg-hint">아직 분석 기록이 없어요.</div>'; return; }
      box.innerHTML = list.map(function (a) {
        return '<a class="mg-hitem" data-id="' + a.id + '">'
          + a.created_at.slice(0, 16).replace('T', ' ') + ' · '
          + a.buy_filename + ' · 매칭 ' + (a.counts && a.counts.matched || 0) + '건</a>';
      }).join('');
      box.querySelectorAll('.mg-hitem').forEach(function (el) {
        el.addEventListener('click', function () { openAnalysis(el.dataset.id); });
      });
    });
  }
  function openAnalysis(id) {
    fetch('/api/margin/analyses/' + id).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.matched) { render(j); $('mg-analyze-status').textContent = '과거 분석 불러옴 · ' + id; }
    });
  }

  if (typeof document !== 'undefined') {
    if (document.readyState !== 'loading') init();
    else document.addEventListener('DOMContentLoaded', init);
  }
  var api = { won: won };
  if (typeof module !== 'undefined' && module.exports) module.exports = { __test: api };
  root.MG_APP = api;
})(typeof window !== 'undefined' ? window : globalThis);

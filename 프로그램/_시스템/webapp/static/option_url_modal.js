/* ============================================================
 * 옵션 + URL 통합 모달 — H1 v9/v10 시안 풀 구현 (2026-05-24)
 *
 * 좌측(블루): 옵션 매트릭스 정의 + 칩 일괄 선택 + 활성/비활성 셀 + [적용 →]
 * 우측(그린): USL 풀 — 소싱처 탭 + URL 카드 + 빠른 선택 + 매트릭스
 * 저장: 옵션 생성 → URL + 매핑 순차 저장
 *
 * 진입점: window.openOptionUrlModal(bundleCode)
 * ============================================================ */
(function () {
  'use strict';

  // 소싱처 약식 규칙 — 한글 앞 2자 / 영문 앞 2자 소문자
  function abbr(label) {
    if (!label) return '?';
    const s = String(label).trim();
    if (!s) return '?';
    // 영문이면 앞 2자 소문자
    if (/^[a-zA-Z]/.test(s)) return s.replace(/[^a-zA-Z0-9]/g, '').slice(0, 2).toLowerCase();
    // 한글/숫자 앞 2자
    return s.slice(0, 2);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function parseValues(text) {
    const out = [];
    (text || '').split(',').forEach(raw => {
      const v = raw.trim();
      if (v && out.indexOf(v) < 0) out.push(v);
    });
    return out;
  }

  function cartesian(lists) {
    let acc = [[]];
    for (const lst of lists) {
      const next = [];
      for (const combo of acc) for (const v of lst) next.push(combo.concat([v]));
      acc = next;
    }
    return acc;
  }

  function keyOf(vals) { return JSON.stringify(vals); }

  // ─── 스타일 1회 주입 ───
  function injectStyle() {
    if (document.getElementById('oum-style')) return;
    const s = document.createElement('style');
    s.id = 'oum-style';
    s.textContent = `
      .oum-bg { position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:9999; display:flex; align-items:center; justify-content:center; padding:20px; }
      .oum-modal { background:#fff; border-radius:14px; width:1640px; max-width:100%; max-height:95vh; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 24px 48px rgba(0,0,0,.18); }
      .oum-mh { padding:13px 22px; border-bottom:1px solid #e5e8eb; display:flex; align-items:center; gap:10px; }
      .oum-mh h2 { margin:0; font-size:16px; font-weight:700; }
      .oum-mh .pill { background:#F0FDF4; color:#10b981; font-size:11px; font-weight:700; padding:2px 8px; border-radius:9px; }
      .oum-mh .close { margin-left:auto; color:#9ca3af; font-size:22px; cursor:pointer; background:none; border:0; }
      .oum-mb { padding:16px 22px; overflow-y:auto; flex:1; background:#FAFBFC; }
      .oum-mf { padding:11px 22px; border-top:1px solid #e5e8eb; display:flex; justify-content:flex-end; gap:8px; background:#fff; }
      .oum-btn { border:0; border-radius:6px; padding:9px 16px; font:inherit; font-size:13px; cursor:pointer; font-weight:600; }
      .oum-btn-pri { background:#3B82F6; color:#fff; }
      .oum-btn-pri:disabled { opacity:.4; cursor:not-allowed; }
      .oum-btn-sec { background:#fff; color:#4e5968; border:1px solid #d1d6db; }

      .oum-legend { display:flex; gap:14px; font-size:10.5px; color:#6b7684; padding:8px 12px; background:#fff; border-radius:6px; margin-bottom:10px; align-items:center; flex-wrap:wrap; border:1px solid #e5e8eb; }
      .oum-legend span { display:inline-flex; align-items:center; gap:4px; }
      .oum-legend .leg-b { display:inline-block; width:22px; height:18px; background:#3B82F6; border-radius:4px; }
      .oum-legend .leg-g { display:inline-block; width:22px; height:18px; background:#10b981; border-radius:4px; }
      .oum-legend .leg-off { display:inline-block; width:22px; height:18px; background:#e5e8eb; border-radius:4px; }

      .oum-split { display:grid; grid-template-columns:1fr 60px 1fr; gap:0; align-items:stretch; }

      .oum-panel { border-radius:10px; padding:14px 16px; display:flex; flex-direction:column; }
      .oum-ph { font-size:13px; font-weight:700; margin-bottom:10px; display:flex; align-items:center; gap:7px; padding-bottom:7px; border-bottom:1px solid #e5e8eb; }
      .oum-ph .badge { padding:2px 8px; border-radius:9px; font-size:10.5px; font-weight:700; }
      .oum-ph .right { margin-left:auto; font-size:11px; color:#8b95a1; font-weight:400; }

      .oum-blue { background:#EFF6FF; border:1px solid #bfdbfe; }
      .oum-blue .oum-ph { color:#1d4ed8; border-bottom-color:#bfdbfe; }
      .oum-blue .oum-ph .badge { background:#3B82F6; color:#fff; }
      .oum-green { background:#F0FDF4; border:1px solid #bbf7d0; }
      .oum-green .oum-ph { color:#15803d; border-bottom-color:#bbf7d0; }
      .oum-green .oum-ph .badge { background:#10b981; color:#fff; }

      .oum-bridge { display:flex; flex-direction:column; align-items:center; justify-content:center; padding-top:140px; }
      .oum-bridge .arr { font-size:24px; color:#10b981; background:#fff; border:2px solid #10b981; border-radius:50%; width:38px; height:38px; display:flex; align-items:center; justify-content:center; }
      .oum-bridge .lbl { font-size:10px; color:#15803d; margin-top:6px; font-weight:600; }

      /* 축 카드 */
      .oum-axis { background:#fff; border:1px solid #bfdbfe; border-radius:7px; padding:9px 11px; margin-bottom:6px; }
      .oum-axis-h { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
      .oum-axis-h .pos { background:#EFF6FF; color:#1d4ed8; padding:2px 8px; border-radius:9px; font-size:10.5px; font-weight:700; }
      .oum-axis-h .rec { font-size:10.5px; color:#9ca3af; font-weight:500; }
      .oum-axis-h .del { color:#dc2626; font-size:11px; cursor:pointer; padding:2px 6px; border-radius:4px; background:none; border:0; }
      .oum-axis-h .del:hover { background:#fee2e2; }
      .oum-axis-in { display:grid; grid-template-columns:120px 1fr; gap:6px; margin-bottom:5px; }
      .oum-axis-in input { border:1px solid #d1d6db; border-radius:4px; padding:6px 9px; font:inherit; font-size:12px; background:#fff; }
      .oum-axis-chips { display:flex; flex-wrap:wrap; gap:3px; }
      .oum-axis-chips .c { background:#EFF6FF; color:#1d4ed8; border-radius:10px; padding:2px 8px; font-size:10.5px; }
      .oum-add-axis { width:100%; background:#fff; border:1.5px dashed #bfdbfe; color:#3B82F6; padding:8px; border-radius:7px; font:inherit; font-size:11.5px; cursor:pointer; font-weight:600; margin-bottom:6px; }
      .oum-add-axis:disabled { opacity:.4; cursor:not-allowed; }

      /* 칩 일괄 선택 (좌·우 공용) */
      .oum-qs { background:#fff; border:1px solid; border-radius:7px; padding:9px 11px; margin-bottom:6px; }
      .oum-blue .oum-qs { border-color:#bfdbfe; }
      .oum-green .oum-qs { border-color:#bbf7d0; }
      .oum-qs-title { font-size:11px; color:#8b95a1; margin-bottom:6px; display:flex; justify-content:space-between; }
      .oum-qs-row { display:flex; align-items:center; gap:5px; margin-bottom:5px; flex-wrap:wrap; }
      .oum-qs-row:last-child { margin-bottom:0; }
      .oum-qs-label { font-size:11px; font-weight:700; width:80px; }
      .oum-blue .oum-qs-label { color:#1d4ed8; }
      .oum-green .oum-qs-label { color:#15803d; }
      .oum-chip { background:#fff; color:#4e5968; border:1px solid #d1d6db; padding:4px 10px; border-radius:13px; font:inherit; font-size:11px; cursor:pointer; font-weight:500; display:inline-flex; align-items:center; gap:4px; }
      .oum-chip .mini { font-size:9.5px; opacity:.75; font-family:ui-monospace,monospace; }
      .oum-blue .oum-chip.on { background:#3B82F6; color:#fff; border-color:#3B82F6; }
      .oum-blue .oum-chip.par { background:#EFF6FF; color:#3B82F6; border-color:#3B82F6; }
      .oum-green .oum-chip.on { background:#10b981; color:#fff; border-color:#10b981; }
      .oum-green .oum-chip.par { background:#F0FDF4; color:#10b981; border-color:#10b981; }
      .oum-chip.on .mini { color:rgba(255,255,255,.85); }

      /* 매트릭스 (좌측: 활성/비활성 / 우측: 매핑 ON/OFF) */
      .oum-mtx { background:#fff; border:1px solid; border-radius:7px; padding:9px 11px; flex:1; }
      .oum-blue .oum-mtx { border-color:#bfdbfe; }
      .oum-green .oum-mtx { border-color:#bbf7d0; }
      .oum-mtx-h { font-size:11.5px; font-weight:600; margin-bottom:6px; display:flex; justify-content:space-between; }
      .oum-blue .oum-mtx-h { color:#1d4ed8; }
      .oum-green .oum-mtx-h { color:#15803d; }
      .oum-mtx-all { font-size:10.5px; cursor:pointer; }
      .oum-blue .oum-mtx-all { color:#3B82F6; }
      .oum-green .oum-mtx-all { color:#10b981; }
      .oum-mtx-grp { margin-bottom:8px; }
      .oum-mtx-grp-h { font-size:11px; font-weight:600; margin:5px 0 4px; cursor:pointer; user-select:none; }
      .oum-blue .oum-mtx-grp-h { color:#1d4ed8; }
      .oum-green .oum-mtx-grp-h { color:#15803d; }
      .oum-mtx-table { border-collapse:collapse; font-size:10.5px; width:100%; }
      .oum-mtx-table th, .oum-mtx-table td { border:1px solid #fff; padding:0; text-align:center; height:28px; background:#fff; }
      .oum-mtx-table th { font-weight:500; font-size:10px; cursor:pointer; user-select:none; }
      .oum-blue .oum-mtx-table th { background:#EFF6FF; color:#1d4ed8; }
      .oum-blue .oum-mtx-table th.corner { background:#dbeafe; }
      .oum-green .oum-mtx-table th { background:#F0FDF4; color:#15803d; }
      .oum-green .oum-mtx-table th.corner { background:#dcfce7; }
      .oum-cell { display:inline-block; width:30px; height:22px; line-height:22px; border-radius:4px; cursor:pointer; font-size:11px; font-weight:600; position:relative; user-select:none; }
      .oum-blue .oum-cell.on { background:#3B82F6; color:#fff; }
      .oum-green .oum-cell.on { background:#10b981; color:#fff; }
      .oum-cell.off { background:#e5e8eb; color:#9ca3af; }
      .oum-cell.shared::after { content:attr(data-shared); position:absolute; top:-4px; right:-4px; background:#f59e0b; color:#fff; font-size:8.5px; width:12px; height:12px; border-radius:50%; line-height:12px; font-weight:700; }
      .oum-cell.disabled { background:#f8fafb; color:#cbd5e0; cursor:not-allowed; opacity:.5; }

      /* 적용 바 (좌측) - 가운데 정렬 */
      .oum-apply-bar { background:#fff; border:1px solid #bfdbfe; border-radius:7px; padding:11px; margin-top:10px; display:flex; flex-direction:column; align-items:center; gap:7px; }
      .oum-apply-bar .sum { font-size:11.5px; color:#1d4ed8; text-align:center; }
      .oum-apply-bar .sum b { font-weight:700; }
      .oum-apply-btn { background:#3B82F6; color:#fff; border:0; padding:10px 28px; border-radius:7px; font:inherit; font-size:13px; font-weight:700; cursor:pointer; display:inline-flex; align-items:center; gap:7px; }
      .oum-apply-btn:hover { background:#2563eb; }
      .oum-apply-btn:disabled { opacity:.4; cursor:not-allowed; }
      .oum-apply-btn.applied { background:#10b981; }

      /* 우측 USL */
      .oum-src-tabs { display:flex; gap:2px; border-bottom:1.5px solid #bbf7d0; padding:4px 4px 0; margin-bottom:8px; flex-wrap:wrap; }
      .oum-src-tab { background:none; border:0; padding:6px 10px; font:inherit; font-size:11.5px; font-weight:700; color:#8b95a1; cursor:pointer; display:flex; align-items:center; gap:5px; border-bottom:2px solid transparent; margin-bottom:-1.5px; }
      .oum-src-tab.on { color:#10b981; border-bottom-color:#10b981; }
      .oum-src-tab .lg { width:20px; height:20px; border-radius:5px; color:#fff; display:inline-flex; align-items:center; justify-content:center; font-size:9.5px; font-weight:800; letter-spacing:.3px; flex-shrink:0; }
      .oum-src-tab .full { font-size:11.5px; }
      .oum-src-tab .cnt { background:#f2f4f6; color:#8b95a1; padding:1px 6px; border-radius:9px; font-size:10px; font-weight:700; }
      .oum-src-tab.on .cnt { background:#F0FDF4; color:#10b981; }

      .oum-url-card { background:#fff; border:1px solid #bbf7d0; border-radius:7px; margin-bottom:6px; overflow:hidden; }
      .oum-url-card.open { box-shadow:0 2px 6px rgba(16,185,129,.15); }
      .oum-url-ch { padding:8px 11px; display:flex; align-items:center; gap:8px; font-size:11.5px; }
      .oum-url-card.open .oum-url-ch { background:#F0FDF4; border-bottom:1px solid #bbf7d0; }
      .oum-url-num { background:#10b981; color:#fff; width:20px; height:20px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:10.5px; font-weight:700; flex-shrink:0; }
      .oum-url-label { border:none; background:transparent; font:inherit; font-size:12px; font-weight:600; outline:none; padding:4px 6px; border-radius:4px; width:140px; color:#15803d; }
      .oum-url-label:hover, .oum-url-label:focus { background:#fff; }
      .oum-url-input { flex:1; min-width:180px; border:1px solid #bbf7d0; border-radius:5px; padding:5px 9px; font:inherit; font-size:11.5px; font-family:ui-monospace,monospace; color:#15803d; }
      .oum-url-cnt { background:#F0FDF4; padding:2px 7px; border-radius:8px; font-size:10px; color:#15803d; white-space:nowrap; }
      .oum-url-cnt b { color:#10b981; font-weight:700; }
      .oum-url-tog, .oum-url-del { background:#fff; border:1px solid #bbf7d0; border-radius:4px; padding:3px 7px; font:inherit; font-size:10.5px; color:#15803d; cursor:pointer; }
      .oum-url-del { color:#dc2626; border-color:#fecaca; }
      .oum-url-body { padding:10px 11px; background:#F0FDF4; }
      .oum-url-card:not(.open) .oum-url-body { display:none; }
      .oum-add-url { width:100%; background:#fff; border:1.5px dashed #bbf7d0; color:#10b981; padding:9px; border-radius:7px; font:inherit; font-size:12px; cursor:pointer; font-weight:700; margin-top:6px; }
      .oum-add-url:hover { background:#F0FDF4; border-color:#10b981; }
      .oum-add-url:disabled { opacity:.4; cursor:not-allowed; }
    `;
    document.head.appendChild(s);
  }

  // ───────────────────────────────────────────────────────────
  //                       MAIN ENTRY
  // ───────────────────────────────────────────────────────────
  async function openOptionUrlModal(bundleCode) {
    if (!bundleCode) { alert('모음전 코드를 찾을 수 없어요.'); return; }
    injectStyle();

    // 상태
    const state = {
      axes: [{ name: '', values: '' }, { name: '', values: '' }],  // [{name, values}]
      selected: new Set(),     // 옵션 활성 (JSON.stringify(axisVals))
      seen: new Set(),         // 매트릭스 변경 시 자동 ON 보존
      applied: false,          // 좌→우 적용 여부
      sources: [],             // [{key, label, color}]
      urls: {},                // {sourceKey: [{tempId, label, url, option_keys: [k,...]}]}
      openUrlId: null,         // 펼친 URL tempId
      tempIdSeq: 1,
    };

    // 모달 마크업
    const bg = document.createElement('div');
    bg.className = 'oum-bg';
    bg.addEventListener('click', e => { if (e.target === bg) bg.remove(); });

    const modal = document.createElement('div');
    modal.className = 'oum-modal';
    modal.innerHTML = `
      <div class="oum-mh">
        <h2>단계형 옵션 생성 + 소싱처 URL 매핑</h2>
        <span class="pill">✨ 동시 입력</span>
        <button class="close" type="button">×</button>
      </div>
      <div class="oum-mb">
        <div class="oum-legend">
          <b style="color:#191F28;">📖 셀 색 의미:</b>
          <span><span class="leg-b"></span>옵션 ON (좌측)</span>
          <span><span class="leg-g"></span>URL 연결 ON (우측)</span>
          <span><span class="leg-off"></span>비활성 (회색)</span>
          <span style="margin-left:auto; color:#92400E;">💡 좌측에서 옵션 만들고 [URL 매핑에 적용 →] 클릭</span>
        </div>
        <div class="oum-split">
          <div class="oum-panel oum-blue" id="oum-left"></div>
          <div class="oum-bridge"><div class="arr">→</div><div class="lbl">적용</div></div>
          <div class="oum-panel oum-green" id="oum-right"></div>
        </div>
      </div>
      <div class="oum-mf">
        <button class="oum-btn oum-btn-sec" id="oum-cancel" type="button">취소</button>
        <button class="oum-btn oum-btn-pri" id="oum-save" type="button" disabled>옵션 + URL 저장</button>
      </div>
    `;
    bg.appendChild(modal);
    document.body.appendChild(bg);

    const $ = sel => modal.querySelector(sel);
    const $$ = sel => modal.querySelectorAll(sel);

    // 소싱처 목록 로드 (기존 모음전 GET 활용)
    try {
      const r = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls`);
      const j = await r.json();
      if (j && j.ok) {
        state.sources = (j.sources || []).map(k => ({ key: k, label: k }));
        // 기존 URL 도 가져옴 (있으면 표시)
        Object.keys(j.urls || {}).forEach(sk => {
          const arr = (j.urls[sk] || []).filter(u => u.id);
          if (arr.length) {
            state.urls[sk] = arr.map(u => ({
              tempId: state.tempIdSeq++,
              dbId: u.id,
              label: u.label || '',
              url: u.url || '',
              option_keys: [],  // 기존 매핑은 옵션 sku 기반 → 새 옵션 만들면 매핑 무효
            }));
          }
        });
      }
    } catch (e) { console.warn('sources load fail', e); }

    // 소싱처 라벨 매핑 (사용자 친화)
    const SRC_LABELS = {
      lemouton: '르무통 공홈', musinsa: '무신사', ssf: 'SSF샵',
      lotteon: '롯데온', ss_lemouton: '스마트스토어 르무통',
    };
    const SRC_COLORS = {
      lemouton: '#a78bfa', musinsa: '#191F28', ssf: '#14b8a6',
      lotteon: '#ef4444', ss_lemouton: '#22c55e',
    };

    // 활성 소싱처 (기본 5개 보장)
    const builtinKeys = ['lemouton', 'musinsa', 'ssf', 'lotteon', 'ss_lemouton'];
    builtinKeys.forEach(k => {
      if (!state.sources.find(s => s.key === k)) {
        state.sources.unshift({ key: k, label: SRC_LABELS[k] || k });
      }
    });
    state.currentSrc = state.sources[0]?.key || 'lemouton';

    // ─── 유틸 ───
    function validAxes() {
      return state.axes
        .map(a => ({ name: (a.name || '').trim(), values: parseValues(a.values) }))
        .filter(a => a.values.length > 0);
    }

    function getAxisValuesArray(key) { try { return JSON.parse(key); } catch (e) { return []; } }

    function totalCombos() {
      const v = validAxes();
      if (!v.length) return 0;
      return v.reduce((acc, a) => acc * a.values.length, 1);
    }

    // ─── 좌측 렌더 ───
    const REC = ['색상', '사이즈', '모델'];
    const POS = ['1축 (가로)', '2축 (세로)', '3축 (겹)'];

    function renderLeft() {
      const left = $('#oum-left');
      const valid = validAxes();
      const totalCnt = totalCombos();
      const onCnt = state.selected.size;

      let html = `<div class="oum-ph">
        <span>🧩</span><span>옵션 매트릭스</span>
        <span class="badge">${onCnt}개</span>
        <span class="right">${valid.map(a => a.values.length).join(' × ') || '축 미정'}</span>
      </div>`;

      // 축 카드
      state.axes.forEach((axis, i) => {
        html += `<div class="oum-axis">
          <div class="oum-axis-h">
            <div style="display:flex; align-items:center; gap:7px;">
              <span class="pos">${POS[i] || `${i + 1}축`}</span>
              <span class="rec">💡 추천: ${REC[i] || '-'}</span>
            </div>
            ${state.axes.length > 1 ? `<button class="del" data-axis-del="${i}" type="button">삭제</button>` : ''}
          </div>
          <div class="oum-axis-in">
            <input data-axis-name="${i}" placeholder="축 이름 (예: ${REC[i] || '용량'})" value="${esc(axis.name)}">
            <input data-axis-values="${i}" placeholder="값 — 쉼표 구분 (예: 그레이,블랙,옐로우)" value="${esc(axis.values)}">
          </div>
          <div class="oum-axis-chips">${parseValues(axis.values).map(v => `<span class="c">${esc(v)}</span>`).join('')}</div>
        </div>`;
      });

      html += `<button class="oum-add-axis" id="oum-add-axis" ${state.axes.length >= 3 ? 'disabled' : ''} type="button">＋ 축 추가 (현재 ${state.axes.length}축 / 최대 3축)</button>`;

      // 칩 일괄 선택 (축별 동적)
      if (valid.length) {
        html += `<div class="oum-qs"><div class="oum-qs-title"><span>📦 빠른 선택 — 칩 클릭 시 일괄 적용</span><span style="color:#dc2626; cursor:pointer;" data-qs-reset>전체 해제</span></div>`;
        valid.forEach(axis => {
          html += `<div class="oum-qs-row"><span class="oum-qs-label">${esc(axis.name || '축')}별</span>`;
          axis.values.forEach(val => {
            const filtered = filterCombos(axis.name, val);
            const onN = filtered.filter(c => state.selected.has(keyOf(c))).length;
            const total = filtered.length;
            const st = onN === 0 ? '' : (onN === total ? 'on' : 'par');
            const ico = onN === 0 ? '' : (onN === total ? '✓ ' : '─ ');
            html += `<button class="oum-chip ${st}" data-qs-axis="${esc(axis.name)}" data-qs-val="${esc(val)}" type="button">${ico}${esc(val)} <span class="mini">${onN}/${total}</span></button>`;
          });
          html += `</div>`;
        });
        html += `</div>`;
      }

      // 매트릭스
      html += `<div class="oum-mtx">
        <div class="oum-mtx-h">
          <span>조합 매트릭스 ${onCnt}/${totalCnt}</span>
          <span class="oum-mtx-all" data-mtx-all>전체 선택/해제</span>
        </div>
        ${renderMatrix(valid)}
      </div>`;

      // 적용 바 (가운데)
      html += `<div class="oum-apply-bar">
        <div class="sum">${valid.length ? `✓ 옵션 <b>${onCnt}개</b> 활성 / ${totalCnt - onCnt}개 비활성 — 우측에 적용?` : '먼저 축을 입력하세요'}</div>
        <button class="oum-apply-btn ${state.applied ? 'applied' : ''}" id="oum-apply" ${onCnt === 0 ? 'disabled' : ''} type="button">${state.applied ? '✓ 적용됨 (다시 적용)' : 'URL 매핑에 적용 →'}</button>
      </div>`;

      left.innerHTML = html;
    }

    function filterCombos(axisName, val) {
      const valid = validAxes();
      const allCombos = cartesian(valid.map(a => a.values));
      const axisIdx = valid.findIndex(a => a.name === axisName);
      if (axisIdx < 0) return allCombos;
      return allCombos.filter(c => c[axisIdx] === val);
    }

    function renderMatrix(valid) {
      if (!valid.length) {
        return `<div style="font-size:11.5px; color:#8b95a1; padding:14px; text-align:center;">값을 입력하면 조합 매트릭스가 나옵니다</div>`;
      }
      if (valid.length === 1) {
        return renderMatrix1D(valid[0]);
      }
      if (valid.length === 2) {
        return renderMatrix2D(valid[0], valid[1], []);
      }
      // 3축 — 마지막 축 그룹
      const groupAxis = valid[valid.length - 1];
      const colAxis = valid[0], rowAxis = valid[1];
      let html = '';
      groupAxis.values.forEach(gv => {
        const baseFilter = [{ axisIdx: valid.length - 1, val: gv }];
        const combos = cartesian(valid.map(a => a.values))
          .filter(c => c[valid.length - 1] === gv);
        const onN = combos.filter(c => state.selected.has(keyOf(c))).length;
        html += `<div class="oum-mtx-grp">
          <div class="oum-mtx-grp-h" data-grp-axis="${esc(groupAxis.name)}" data-grp-val="${esc(gv)}">
            ▾ ${esc(groupAxis.name || '축')}: ${esc(gv)} <span style="font-weight:400; opacity:.7;">${onN}/${combos.length} 선택됨</span>
          </div>
          ${renderMatrix2D(colAxis, rowAxis, [{ idx: valid.length - 1, val: gv }])}
        </div>`;
      });
      return html;
    }

    function renderMatrix1D(axis) {
      const valid = validAxes();
      let html = `<table class="oum-mtx-table"><tbody><tr>`;
      axis.values.forEach(v => {
        const k = keyOf([v]);
        const on = state.selected.has(k);
        html += `<td><span class="oum-cell ${on ? 'on' : 'off'}" data-cell-key='${esc(k)}'>${on ? '✓' : '·'}</span></td>`;
      });
      html += `</tr></tbody></table>`;
      return html;
    }

    function renderMatrix2D(colAxis, rowAxis, baseFilter) {
      const valid = validAxes();
      const colIdx = valid.findIndex(a => a === colAxis);
      const rowIdx = valid.findIndex(a => a === rowAxis);

      let html = `<table class="oum-mtx-table"><thead><tr>
        <th class="corner" data-corner-axes='${esc(JSON.stringify(baseFilter))}'>⌐</th>`;
      colAxis.values.forEach(cv => {
        html += `<th data-col-axis="${esc(colAxis.name)}" data-col-val="${esc(cv)}" data-base='${esc(JSON.stringify(baseFilter))}'>${esc(cv)}</th>`;
      });
      html += `</tr></thead><tbody>`;

      rowAxis.values.forEach(rv => {
        html += `<tr><th data-row-axis="${esc(rowAxis.name)}" data-row-val="${esc(rv)}" data-base='${esc(JSON.stringify(baseFilter))}'>${esc(rv)}</th>`;
        colAxis.values.forEach(cv => {
          // 키 만들기 — base + col + row 조합
          const arr = new Array(valid.length);
          baseFilter.forEach(b => { arr[b.idx] = b.val; });
          arr[colIdx] = cv;
          arr[rowIdx] = rv;
          const k = keyOf(arr);
          const on = state.selected.has(k);
          html += `<td><span class="oum-cell ${on ? 'on' : 'off'}" data-cell-key='${esc(k)}'>${on ? '✓' : '·'}</span></td>`;
        });
        html += `</tr>`;
      });

      html += `</tbody></table>`;
      return html;
    }

    // ─── 우측 렌더 (USL 풀) ───
    function renderRight() {
      const right = $('#oum-right');
      const totalActive = state.selected.size;

      let html = `<div class="oum-ph">
        <span>📍</span><span>소싱처 URL 매핑</span>
        <span class="badge">${countAllUrls()} URL</span>
        <span class="right">${state.applied ? `활성 옵션 ${totalActive}개에 매핑` : '먼저 좌측에서 [적용 →] 클릭'}</span>
      </div>`;

      if (!state.applied) {
        html += `<div style="padding:60px 20px; text-align:center; color:#9ca3af; background:#fff; border:2px dashed #bbf7d0; border-radius:8px;">
          <div style="font-size:32px; margin-bottom:10px;">⬅</div>
          <div style="font-size:13px; font-weight:600; color:#15803d;">좌측에서 옵션 만들고 [적용 →] 클릭하면 활성화</div>
        </div>`;
        right.innerHTML = html;
        return;
      }

      // 소싱처 탭
      html += `<div class="oum-src-tabs">`;
      state.sources.forEach(src => {
        const cnt = (state.urls[src.key] || []).length;
        const isOn = src.key === state.currentSrc;
        const label = SRC_LABELS[src.key] || src.label;
        const color = SRC_COLORS[src.key] || '#3B82F6';
        html += `<button class="oum-src-tab ${isOn ? 'on' : ''}" data-src-tab="${esc(src.key)}" type="button">
          <span class="lg" style="background:${color};">${abbr(label)}</span>
          <span class="full">${esc(label)}</span>
          <span class="cnt">${cnt}</span>
        </button>`;
      });
      html += `</div>`;

      // 현재 탭 URL 카드 리스트
      const srcLabel = SRC_LABELS[state.currentSrc] || state.currentSrc;
      const arr = state.urls[state.currentSrc] || [];
      if (!arr.length) {
        html += `<div style="padding:14px; text-align:center; color:#9ca3af; font-size:12px; background:#fff; border:1px dashed #bbf7d0; border-radius:7px;">등록된 URL이 없습니다</div>`;
      } else {
        arr.forEach((u, i) => {
          html += renderUrlCard(u, i + 1);
        });
      }

      html += `<button class="oum-add-url" data-add-url type="button">＋ 새 ${esc(srcLabel)} URL 추가</button>`;

      right.innerHTML = html;
    }

    function countAllUrls() {
      let n = 0;
      Object.values(state.urls).forEach(arr => { n += arr.length; });
      return n;
    }

    function renderUrlCard(u, num) {
      const isOpen = state.openUrlId === u.tempId;
      const totalActive = state.selected.size;
      const mapped = (u.option_keys || []).length;

      let html = `<div class="oum-url-card ${isOpen ? 'open' : ''}" data-url-id="${u.tempId}">
        <div class="oum-url-ch">
          <span class="oum-url-num">${num}</span>
          <input class="oum-url-label" data-field="label" value="${esc(u.label)}" placeholder="라벨 (선택)">
          <input class="oum-url-input" data-field="url" value="${esc(u.url)}" placeholder="URL 입력">
          <span class="oum-url-cnt"><b>${mapped}</b>/${totalActive}</span>
          <button class="oum-url-tog" data-url-tog type="button">${isOpen ? '▾ 닫기' : '▸ 매핑'}</button>
          <button class="oum-url-del" data-url-del type="button">✕</button>
        </div>`;

      if (isOpen) {
        html += `<div class="oum-url-body">${renderUrlBody(u)}</div>`;
      }
      html += `</div>`;
      return html;
    }

    function renderUrlBody(u) {
      const valid = validAxes();
      if (!valid.length || !state.selected.size) {
        return `<div style="font-size:11.5px; color:#9ca3af; padding:10px;">활성 옵션이 없습니다</div>`;
      }
      const mappedSet = new Set(u.option_keys || []);

      // 빠른 선택 칩
      let html = `<div class="oum-qs"><div class="oum-qs-title"><span>📦 빠른 선택</span><span style="color:#dc2626; cursor:pointer;" data-url-qs-reset>전체 해제</span></div>`;
      valid.forEach(axis => {
        html += `<div class="oum-qs-row"><span class="oum-qs-label">${esc(axis.name || '축')}별</span>`;
        axis.values.forEach(val => {
          // 이 axis=val 에 해당하는 활성 옵션만
          const matching = Array.from(state.selected).map(getAxisValuesArray)
            .filter(c => {
              const axisIdx = valid.findIndex(a => a.name === axis.name);
              return c[axisIdx] === val;
            });
          const onN = matching.filter(c => mappedSet.has(keyOf(c))).length;
          const total = matching.length;
          if (!total) return;
          const st = onN === 0 ? '' : (onN === total ? 'on' : 'par');
          const ico = onN === 0 ? '' : (onN === total ? '✓ ' : '─ ');
          html += `<button class="oum-chip ${st}" data-url-qs-axis="${esc(axis.name)}" data-url-qs-val="${esc(val)}" type="button">${ico}${esc(val)} <span class="mini">${onN}/${total}</span></button>`;
        });
        html += `</div>`;
      });
      html += `</div>`;

      // 매트릭스 — 활성 옵션만 매핑 가능, 비활성은 회색 disabled
      html += renderUrlMatrix(u, valid, mappedSet);

      return html;
    }

    function renderUrlMatrix(u, valid, mappedSet) {
      const sharedMap = computeSharedMap(u);

      if (valid.length === 1) {
        let html = `<div class="oum-mtx"><table class="oum-mtx-table"><tbody><tr>`;
        valid[0].values.forEach(v => {
          const k = keyOf([v]);
          const active = state.selected.has(k);
          const on = mappedSet.has(k);
          const sh = sharedMap[k] || 0;
          let cls = active ? (on ? 'on' : 'off') : 'disabled';
          if (on && sh > 1) cls += ' shared';
          const sharedAttr = (on && sh > 1) ? ` data-shared="${sh}"` : '';
          html += `<td><span class="oum-cell ${cls}" data-url-cell-key='${esc(k)}'${sharedAttr}>${active ? (on ? '✓' : '·') : '·'}</span></td>`;
        });
        html += `</tr></tbody></table></div>`;
        return html;
      }

      if (valid.length === 2) {
        return `<div class="oum-mtx">${renderUrlMatrix2D(u, valid[0], valid[1], [], mappedSet, sharedMap)}</div>`;
      }

      // 3축
      const groupAxis = valid[valid.length - 1];
      const colAxis = valid[0], rowAxis = valid[1];
      let html = `<div class="oum-mtx">`;
      groupAxis.values.forEach(gv => {
        html += `<div class="oum-mtx-grp"><div class="oum-mtx-grp-h">▾ ${esc(groupAxis.name || '축')}: ${esc(gv)}</div>`;
        html += renderUrlMatrix2D(u, colAxis, rowAxis, [{ idx: valid.length - 1, val: gv }], mappedSet, sharedMap);
        html += `</div>`;
      });
      html += `</div>`;
      return html;
    }

    function renderUrlMatrix2D(u, colAxis, rowAxis, baseFilter, mappedSet, sharedMap) {
      const valid = validAxes();
      const colIdx = valid.findIndex(a => a === colAxis);
      const rowIdx = valid.findIndex(a => a === rowAxis);

      let html = `<table class="oum-mtx-table"><thead><tr><th class="corner">⌐</th>`;
      colAxis.values.forEach(cv => {
        html += `<th>${esc(cv)}</th>`;
      });
      html += `</tr></thead><tbody>`;

      rowAxis.values.forEach(rv => {
        html += `<tr><th>${esc(rv)}</th>`;
        colAxis.values.forEach(cv => {
          const arr = new Array(valid.length);
          baseFilter.forEach(b => { arr[b.idx] = b.val; });
          arr[colIdx] = cv;
          arr[rowIdx] = rv;
          const k = keyOf(arr);
          const active = state.selected.has(k);
          const on = mappedSet.has(k);
          const sh = sharedMap[k] || 0;
          let cls = active ? (on ? 'on' : 'off') : 'disabled';
          if (on && sh > 1) cls += ' shared';
          const sharedAttr = (on && sh > 1) ? ` data-shared="${sh}"` : '';
          html += `<td><span class="oum-cell ${cls}" data-url-cell-key='${esc(k)}'${sharedAttr}>${active ? (on ? '✓' : '·') : '·'}</span></td>`;
        });
        html += `</tr>`;
      });

      html += `</tbody></table>`;
      return html;
    }

    function computeSharedMap(currentUrl) {
      const map = {};
      const arr = state.urls[state.currentSrc] || [];
      arr.forEach(u => {
        (u.option_keys || []).forEach(k => {
          map[k] = (map[k] || 0) + 1;
        });
      });
      return map;
    }

    // ─── 이벤트 ───
    function rerender() {
      renderLeft();
      renderRight();
      updateSaveBtn();
    }

    function updateSaveBtn() {
      const save = $('#oum-save');
      const hasOpts = state.selected.size > 0;
      save.disabled = !hasOpts;
      save.textContent = hasOpts ? `옵션 ${state.selected.size}개 + URL 저장` : '옵션 + URL 저장';
    }

    // 좌측 이벤트
    $('#oum-left').addEventListener('click', e => {
      // 축 삭제
      const del = e.target.closest('[data-axis-del]');
      if (del) {
        state.axes.splice(+del.dataset.axisDel, 1);
        recalcMatrix();
        rerender();
        return;
      }
      // 축 추가
      if (e.target.closest('#oum-add-axis')) {
        if (state.axes.length < 3) {
          state.axes.push({ name: '', values: '' });
          rerender();
        }
        return;
      }
      // 빠른 선택 칩
      const qs = e.target.closest('[data-qs-axis]');
      if (qs) {
        toggleAxis(qs.dataset.qsAxis, qs.dataset.qsVal);
        return;
      }
      // 빠른 선택 reset
      if (e.target.closest('[data-qs-reset]')) {
        state.selected.clear();
        rerender();
        return;
      }
      // 매트릭스 셀
      const cell = e.target.closest('[data-cell-key]');
      if (cell) {
        const k = cell.dataset.cellKey;
        if (state.selected.has(k)) state.selected.delete(k);
        else state.selected.add(k);
        rerender();
        return;
      }
      // 매트릭스 헤더 (col/row)
      const colH = e.target.closest('[data-col-axis]');
      if (colH) { toggleHeaderRange(colH); return; }
      const rowH = e.target.closest('[data-row-axis]');
      if (rowH) { toggleHeaderRange(rowH); return; }
      // 좌상단 / 그룹 헤더
      const corner = e.target.closest('[data-corner-axes]');
      if (corner) { toggleCorner(corner); return; }
      const grp = e.target.closest('[data-grp-axis]');
      if (grp) { toggleGroup(grp.dataset.grpAxis, grp.dataset.grpVal); return; }
      // 전체 선택/해제
      if (e.target.closest('[data-mtx-all]')) {
        const all = cartesian(validAxes().map(a => a.values));
        const allOn = all.every(c => state.selected.has(keyOf(c)));
        if (allOn) state.selected.clear();
        else all.forEach(c => state.selected.add(keyOf(c)));
        rerender();
        return;
      }
      // 적용 버튼
      if (e.target.closest('#oum-apply')) {
        state.applied = true;
        rerender();
        return;
      }
    });

    // 좌측 input 변경
    $('#oum-left').addEventListener('input', e => {
      const nm = e.target.closest('[data-axis-name]');
      if (nm) {
        state.axes[+nm.dataset.axisName].name = e.target.value;
        rerender(); return;
      }
      const vl = e.target.closest('[data-axis-values]');
      if (vl) {
        state.axes[+vl.dataset.axisValues].values = e.target.value;
        recalcMatrix();
        rerender();
        return;
      }
    });

    function recalcMatrix() {
      const valid = validAxes();
      if (!valid.length) { state.selected.clear(); state.seen.clear(); return; }
      const combos = cartesian(valid.map(a => a.values));
      const curKeys = new Set(combos.map(keyOf));
      [...state.selected].forEach(k => { if (!curKeys.has(k)) state.selected.delete(k); });
      [...state.seen].forEach(k => { if (!curKeys.has(k)) state.seen.delete(k); });
      combos.forEach(c => { const k = keyOf(c); if (!state.seen.has(k)) { state.seen.add(k); state.selected.add(k); } });
      state.applied = false;  // 매트릭스 변경 시 적용 무효화
    }

    function toggleAxis(axisName, val) {
      const matching = filterCombos(axisName, val);
      const allOn = matching.every(c => state.selected.has(keyOf(c)));
      matching.forEach(c => { const k = keyOf(c); if (allOn) state.selected.delete(k); else state.selected.add(k); });
      rerender();
    }

    function toggleHeaderRange(el) {
      // base + col/row 만 선택된 셀 토글
      const isCol = !!el.dataset.colAxis;
      const axisName = isCol ? el.dataset.colAxis : el.dataset.rowAxis;
      const val = isCol ? el.dataset.colVal : el.dataset.rowVal;
      let base = [];
      try { base = JSON.parse(el.dataset.base || '[]'); } catch (e) {}
      const valid = validAxes();
      const allCombos = cartesian(valid.map(a => a.values));
      const axisIdx = valid.findIndex(a => a.name === axisName);
      const matching = allCombos.filter(c => {
        if (c[axisIdx] !== val) return false;
        return base.every(b => c[b.idx] === b.val);
      });
      const allOn = matching.every(c => state.selected.has(keyOf(c)));
      matching.forEach(c => { const k = keyOf(c); if (allOn) state.selected.delete(k); else state.selected.add(k); });
      rerender();
    }

    function toggleCorner(el) {
      let base = [];
      try { base = JSON.parse(el.dataset.cornerAxes || '[]'); } catch (e) {}
      const valid = validAxes();
      const allCombos = cartesian(valid.map(a => a.values));
      const matching = allCombos.filter(c => base.every(b => c[b.idx] === b.val));
      const allOn = matching.every(c => state.selected.has(keyOf(c)));
      matching.forEach(c => { const k = keyOf(c); if (allOn) state.selected.delete(k); else state.selected.add(k); });
      rerender();
    }

    function toggleGroup(axisName, val) {
      toggleAxis(axisName, val);
    }

    // 우측 이벤트
    $('#oum-right').addEventListener('click', e => {
      // 탭 전환
      const tab = e.target.closest('[data-src-tab]');
      if (tab) {
        state.currentSrc = tab.dataset.srcTab;
        state.openUrlId = null;
        renderRight();
        return;
      }
      // URL 추가
      if (e.target.closest('[data-add-url]')) {
        const url = prompt(`새 ${SRC_LABELS[state.currentSrc] || state.currentSrc} URL 입력:`);
        if (!url || !url.trim()) return;
        if (!state.urls[state.currentSrc]) state.urls[state.currentSrc] = [];
        const newU = { tempId: state.tempIdSeq++, label: '', url: url.trim(), option_keys: [] };
        state.urls[state.currentSrc].push(newU);
        state.openUrlId = newU.tempId;
        renderRight();
        return;
      }
      // URL 카드 토글
      const card = e.target.closest('[data-url-id]');
      const tog = e.target.closest('[data-url-tog]');
      if (tog && card) {
        const tid = +card.dataset.urlId;
        state.openUrlId = (state.openUrlId === tid) ? null : tid;
        renderRight();
        return;
      }
      // URL 삭제
      const del = e.target.closest('[data-url-del]');
      if (del && card) {
        if (!confirm('이 URL 삭제?')) return;
        const tid = +card.dataset.urlId;
        state.urls[state.currentSrc] = state.urls[state.currentSrc].filter(u => u.tempId !== tid);
        if (state.openUrlId === tid) state.openUrlId = null;
        renderRight();
        return;
      }
      // 빠른 선택 reset
      if (e.target.closest('[data-url-qs-reset]')) {
        const u = currentUrl();
        if (u) { u.option_keys = []; renderRight(); }
        return;
      }
      // 빠른 선택 칩
      const qs = e.target.closest('[data-url-qs-axis]');
      if (qs) {
        const u = currentUrl();
        if (!u) return;
        toggleUrlAxis(u, qs.dataset.urlQsAxis, qs.dataset.urlQsVal);
        return;
      }
      // 매트릭스 셀
      const cell = e.target.closest('[data-url-cell-key]');
      if (cell && !cell.classList.contains('disabled')) {
        const u = currentUrl();
        if (!u) return;
        const k = cell.dataset.urlCellKey;
        const idx = u.option_keys.indexOf(k);
        if (idx >= 0) u.option_keys.splice(idx, 1);
        else u.option_keys.push(k);
        renderRight();
        return;
      }
    });

    // 우측 input 변경 (label / url)
    $('#oum-right').addEventListener('input', e => {
      const card = e.target.closest('[data-url-id]');
      if (!card) return;
      const tid = +card.dataset.urlId;
      const u = (state.urls[state.currentSrc] || []).find(x => x.tempId === tid);
      if (!u) return;
      const f = e.target.dataset.field;
      if (f === 'label') u.label = e.target.value;
      else if (f === 'url') u.url = e.target.value;
    });

    function currentUrl() {
      if (!state.openUrlId) return null;
      return (state.urls[state.currentSrc] || []).find(u => u.tempId === state.openUrlId);
    }

    function toggleUrlAxis(u, axisName, val) {
      const valid = validAxes();
      const axisIdx = valid.findIndex(a => a.name === axisName);
      const matching = Array.from(state.selected).map(getAxisValuesArray)
        .filter(c => c[axisIdx] === val);
      const set = new Set(u.option_keys);
      const allOn = matching.every(c => set.has(keyOf(c)));
      matching.forEach(c => { const k = keyOf(c); if (allOn) set.delete(k); else set.add(k); });
      u.option_keys = [...set];
      renderRight();
    }

    // 모달 닫기 / 저장
    $('.oum-mh .close').addEventListener('click', () => bg.remove());
    $('#oum-cancel').addEventListener('click', () => bg.remove());

    $('#oum-save').addEventListener('click', async () => {
      if (!state.selected.size) return;
      const save = $('#oum-save');
      save.disabled = true; save.textContent = '저장 중...';

      try {
        // 1) 옵션 생성
        const validList = validAxes();
        const selectedArr = [...state.selected].map(getAxisValuesArray);
        const res = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/options/combo`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ steps: validList, selected: selectedArr }),
        });
        const j = await res.json();
        if (!j || !j.ok) {
          alert('옵션 생성 실패: ' + ((j && j.error) || ''));
          save.disabled = false; save.textContent = '옵션 + URL 저장';
          return;
        }

        // 2) URL 매핑 저장 — 각 URL을 POST + option_keys → canonical_sku 매핑은 백엔드가 알아서
        // 우선 URL만 저장 (옵션 sku 매핑은 별도 단계 — 추후 통합)
        let urlSaved = 0, urlFailed = 0;
        for (const sk of Object.keys(state.urls)) {
          for (const u of state.urls[sk]) {
            if (!u.url || !u.url.trim()) continue;
            try {
              await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source_key: sk, url: u.url.trim(), label: u.label || null }),
              });
              urlSaved++;
            } catch (e) { urlFailed++; }
          }
        }

        // 알림 + 리로드
        if (typeof flash === 'function') {
          flash(`옵션 ${j.created || 0}개 + URL ${urlSaved}개 저장됨${urlFailed ? ` (URL ${urlFailed}개 실패)` : ''}`);
        }
        bg.remove();
        setTimeout(() => location.reload(), 700);
      } catch (e) {
        alert('저장 중 오류: ' + e.message);
        save.disabled = false; save.textContent = '옵션 + URL 저장';
      }
    });

    // 초기 렌더
    rerender();
  }

  window.openOptionUrlModal = openOptionUrlModal;

  // ─── monkey patch: 기존 openStepDesignModal 자리를 새 통합 모달로 대체 ───
  // toss.js 의 step-design action 이 이 함수를 호출 → 새 모달이 뜸.
  // 기존 함수는 _origOpenStepDesignModal 로 백업 (fallback 필요 시).
  if (typeof window.openStepDesignModal === 'function') {
    window._origOpenStepDesignModal = window.openStepDesignModal;
  }
  window.openStepDesignModal = openOptionUrlModal;
})();

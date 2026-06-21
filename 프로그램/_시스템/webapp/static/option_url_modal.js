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

  // [2026-05-27] URL → 도메인 강조용 분리 (시안 2 적용)
  //   "https://www.lemouton.co.kr/product/detail.html?product_no=121&..."
  //   → { domain: "lemouton.co.kr", rest: "/product/detail.html?product_no=121&..." }
  //   파싱 실패 시 rest 에 원본, domain 빈 문자열 — 마크업이 안전하게 fallback
  function splitUrl(url) {
    try {
      const u = new URL(url);
      const domain = u.hostname.replace(/^www\./, '');
      const rest = (u.pathname || '') + (u.search || '') + (u.hash || '');
      return { domain, rest };
    } catch (e) {
      return { domain: '', rest: String(url || '') };
    }
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
      .oum-bg { position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:9999; display:flex; align-items:center; justify-content:center; padding:15px; }
      .oum-modal { background:#fff; border-radius:21px; width:2880px; max-width:97vw; max-height:96vh; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 24px 48px rgba(0,0,0,.18); font-size:27px; }
      .oum-mh { padding:40.5px 42px; border-bottom:1px solid #e5e8eb; display:flex; align-items:center; gap:18px; }
      .oum-mh h2 { margin:0; font-size:33px; font-weight:700; }
      .oum-mh .pill { background:#F0FDF4; color:#10b981; font-size:21px; font-weight:700; padding:6.75px 16.5px; border-radius:16.5px; }
      .oum-mh .close { margin-left:auto; color:#9ca3af; font-size:45px; cursor:pointer; background:none; border:0; }
      .oum-mb { padding:45px 42px; overflow-y:auto; flex:1; background:#FAFBFC; }
      .oum-mf { padding:31.5px 42px; border-top:1px solid #e5e8eb; display:flex; justify-content:flex-end; gap:15px; background:#fff; }
      .oum-btn { border:0; border-radius:12px; padding:27px 33px; font:inherit; font-size:24px; cursor:pointer; font-weight:600; }
      .oum-btn-pri { background:#3B82F6; color:#fff; }
      .oum-btn-pri:disabled { opacity:.4; cursor:not-allowed; }
      .oum-btn-sec { background:#fff; color:#4e5968; border:1px solid #d1d6db; }

      .oum-legend { display:flex; gap:18px; font-size:18px; color:#6b7684; padding:18px 24px; background:#fff; border-radius:12px; margin-bottom:21px; align-items:center; flex-wrap:wrap; border:1px solid #e5e8eb; }
      .oum-legend span { display:inline-flex; align-items:center; gap:7.5px; }
      /* [2026-05-29 시안 v6] 누적 색 시스템 범례 — 회색→파랑→초록 */
      .oum-legend .leg-empty { display:inline-block; width:38px; height:30px; background:#F3F4F6; border:1px dashed #D1D6DB; border-radius:6px; }
      .oum-legend .leg-gray { display:inline-block; width:38px; height:30px; background:#9CA3AF; border-radius:6px; }
      .oum-legend .leg-blue { display:inline-block; width:38px; height:30px; background:#4F67FF; border-radius:6px; }
      .oum-legend .leg-green { display:inline-block; width:38px; height:30px; background:#03A65A; border-radius:6px; }
      /* 옛 클래스 — 호환 (다른 곳에서 참조 가능) */
      .oum-legend .leg-b { display:inline-block; width:38px; height:30px; background:#4F67FF; border-radius:6px; }
      .oum-legend .leg-g { display:inline-block; width:38px; height:30px; background:#03A65A; border-radius:6px; }
      .oum-legend .leg-off { display:inline-block; width:38px; height:30px; background:#9CA3AF; border-radius:6px; }

      .oum-split { display:grid; grid-template-columns:2fr 70px 5fr; gap:0; align-items:stretch; }

      .oum-panel { border-radius:18px; padding:40.5px 30px; display:flex; flex-direction:column; }
      .oum-ph { font-size:25.5px; font-weight:700; margin-bottom:21px; display:flex; align-items:center; gap:13.5px; padding-bottom:15px; border-bottom:1px solid #e5e8eb; }
      .oum-ph .badge { padding:6.75px 16.5px; border-radius:16.5px; font-size:19.5px; font-weight:700; }
      .oum-ph .right { margin-left:auto; font-size:21px; color:#8b95a1; font-weight:400; }

      .oum-blue { background:#EFF6FF; border:1px solid #bfdbfe; }
      .oum-blue .oum-ph { color:#1d4ed8; border-bottom-color:#bfdbfe; }
      .oum-blue .oum-ph .badge { background:#3B82F6; color:#fff; }
      .oum-green { background:#F0FDF4; border:1px solid #bbf7d0; }
      .oum-green .oum-ph { color:#15803d; border-bottom-color:#bbf7d0; }
      .oum-green .oum-ph .badge { background:#10b981; color:#fff; }

      .oum-bridge { display:flex; flex-direction:column; align-items:center; justify-content:center; padding-top:210px; }
      .oum-bridge .arr { font-size:36px; color:#10b981; background:#fff; border:2px solid #10b981; border-radius:50%; width:57px; height:57px; display:flex; align-items:center; justify-content:center; }
      .oum-bridge .lbl { font-size:15px; color:#15803d; margin-top:9px; font-weight:600; }

      /* 축 카드 */
      .oum-axis { background:#fff; border:1px solid #bfdbfe; border-radius:13.5px; padding:29.25px 22.5px; margin-bottom:13.5px; }
      .oum-axis-h { display:flex; justify-content:space-between; align-items:center; margin-bottom:13.5px; }
      .oum-axis-h .pos { background:#EFF6FF; color:#1d4ed8; padding:9px 16.5px; border-radius:16.5px; font-size:21px; font-weight:700; }
      .oum-axis-h .rec { font-size:21px; color:#9ca3af; font-weight:500; }
      .oum-axis-h .del { color:#dc2626; font-size:21px; cursor:pointer; padding:9px 13.5px; border-radius:7.5px; background:none; border:0; }
      .oum-axis-h .del:hover { background:#fee2e2; }
      .oum-axis-in { display:grid; grid-template-columns:160px 1fr; gap:13.5px; margin-bottom:12px; }
      .oum-axis-in input { border:1.5px solid #d1d6db; border-radius:9px; padding:22.5px 21px; font:inherit; font-size:25.5px; background:#fff; }
      .oum-axis-in input:focus { border-color:#3B82F6; outline:none; }
      .oum-axis-chips { display:flex; flex-wrap:wrap; gap:7.5px; align-items:center; }
      .oum-axis-chips .c { background:#EFF6FF; color:#1d4ed8; border-radius:18px; padding:9px 16.5px; font-size:20.25px; display:inline-flex; align-items:center; gap:6px; cursor:grab; user-select:none; }
      .oum-axis-chips .c .dh { color:#9bb7e8; font-size:18px; cursor:grab; line-height:1; }
      .oum-axis-chips .c.dragging { opacity:.35; }
      .oum-axis-chips .c.over { outline:3px dashed #3B82F6; outline-offset:2px; }
      .oum-drag-hint { font-size:16.5px; color:#b0b8c1; margin-left:4px; }
      .oum-sortbtns { display:inline-flex; gap:5px; }
      .oum-sortb { font:inherit; font-size:18px; cursor:pointer; border:1.5px solid #d1d6db; background:#fff; color:#475569; border-radius:9px; padding:7px 14px; font-weight:600; }
      .oum-sortb:hover { background:#EFF6FF; border-color:#bfdbfe; color:#1d4ed8; }
      .oum-mtx-table th.oum-th-drag { cursor:grab; }
      .oum-mtx-table th.oum-th-dragging { opacity:.4; }
      .oum-mtx-table th.oum-th-over { outline:2.5px dashed #3B82F6; outline-offset:-3px; background:#dbeafe; }
      .oum-add-axis { width:100%; background:#fff; border:2px dashed #bfdbfe; color:#3B82F6; padding:16.5px; border-radius:13.5px; font:inherit; font-size:22.5px; cursor:pointer; font-weight:600; margin-bottom:13.5px; }
      .oum-add-axis:disabled { opacity:.4; cursor:not-allowed; }

      /* 칩 일괄 선택 (좌·우 공용) */
      .oum-qs { background:#fff; border:1px solid; border-radius:10.5px; padding:20.25px 16.5px; margin-bottom:9px; }
      .oum-blue .oum-qs { border-color:#bfdbfe; }
      .oum-green .oum-qs { border-color:#bbf7d0; }
      .oum-qs-title { font-size:16.5px; color:#8b95a1; margin-bottom:9px; display:flex; justify-content:space-between; }
      .oum-qs-row { display:flex; align-items:center; gap:7.5px; margin-bottom:7.5px; flex-wrap:wrap; }
      .oum-qs-row:last-child { margin-bottom:0; }
      .oum-qs-label { font-size:16.5px; font-weight:700; width:120px; }
      .oum-blue .oum-qs-label { color:#1d4ed8; }
      .oum-green .oum-qs-label { color:#15803d; }
      .oum-chip { background:#fff; color:#4e5968; border:1px solid #d1d6db; padding:9px 15px; border-radius:19.5px; font:inherit; font-size:16.5px; cursor:pointer; font-weight:500; display:inline-flex; align-items:center; gap:6px; }
      .oum-chip .mini { font-size:14.25px; opacity:.75; font-family:ui-monospace,monospace; }
      .oum-blue .oum-chip.on { background:#3B82F6; color:#fff; border-color:#3B82F6; }
      .oum-blue .oum-chip.par { background:#EFF6FF; color:#3B82F6; border-color:#3B82F6; }
      .oum-green .oum-chip.on { background:#10b981; color:#fff; border-color:#10b981; }
      .oum-green .oum-chip.par { background:#F0FDF4; color:#10b981; border-color:#10b981; }
      .oum-chip.on .mini { color:rgba(255,255,255,.85); }

      /* 매트릭스 (좌측: 활성/비활성 / 우측: 매핑 ON/OFF) */
      .oum-mtx { background:#fff; border:1px solid; border-radius:10.5px; padding:20.25px 16.5px; flex:1; }
      .oum-blue .oum-mtx { border-color:#bfdbfe; }
      .oum-green .oum-mtx { border-color:#bbf7d0; }
      .oum-mtx-h { font-size:17.25px; font-weight:600; margin-bottom:9px; display:flex; justify-content:space-between; }
      .oum-blue .oum-mtx-h { color:#1d4ed8; }
      .oum-green .oum-mtx-h { color:#15803d; }
      .oum-mtx-all { font-size:15.75px; cursor:pointer; }
      .oum-blue .oum-mtx-all { color:#3B82F6; }
      .oum-green .oum-mtx-all { color:#10b981; }
      .oum-mtx-grp { margin-bottom:12px; }
      .oum-mtx-grp-h { font-size:16.5px; font-weight:600; margin:11.25px 0 6px; cursor:pointer; user-select:none; }
      .oum-blue .oum-mtx-grp-h { color:#1d4ed8; }
      .oum-green .oum-mtx-grp-h { color:#15803d; }
      .oum-mtx-table { border-collapse:collapse; font-size:15.75px; width:100%; }
      .oum-mtx-table th, .oum-mtx-table td { border:1px solid #fff; padding:0; text-align:center; height:42px; background:#fff; }
      .oum-mtx-table th { font-weight:500; font-size:15px; cursor:pointer; user-select:none; transition:background .12s, color .12s; }
      .oum-blue .oum-mtx-table th { background:#EFF6FF; color:#1d4ed8; }
      .oum-blue .oum-mtx-table th.corner { background:#dbeafe; }
      .oum-blue .oum-mtx-table th:hover { background:#3B82F6; color:#fff; }
      .oum-green .oum-mtx-table th { background:#F0FDF4; color:#15803d; }
      .oum-green .oum-mtx-table th.corner { background:#dcfce7; }
      .oum-green .oum-mtx-table th:hover { background:#10b981; color:#fff; }
      /* 그룹 헤더(3축) 호버 — div 라 transition 별도 */
      .oum-mtx-grp-h { transition:background .12s, color .12s; padding:11.25px 12px; border-radius:7.5px; }
      .oum-blue .oum-mtx-grp-h:hover { background:#dbeafe; }
      .oum-green .oum-mtx-grp-h:hover { background:#dcfce7; }
      /* [2026-05-29 시안 v6 E3] 셀에 상태 태그까지 — 세로 stack (체크표시 + 작은 라벨) */
      .oum-cell { display:inline-flex; flex-direction:column; align-items:center; justify-content:center; width:56px; height:38px; line-height:1.1; border-radius:6px; cursor:pointer; font-size:14px; font-weight:700; position:relative; user-select:none; padding:2px 0; }
      .oum-cell .tag { font-size:9.5px; font-weight:600; opacity:.92; letter-spacing:.2px; margin-top:1px; }
      /* [2026-05-29] 시안 v6 E3 — 누적 색 시스템 (회색→파랑→초록) + 상태 태그.
         단일 진실 원천: opt-on / url-on / has-inv 클래스만 의미. */
      .oum-cell.disabled,
      .oum-cell.off,
      .oum-cell.mapped-off { background:#F3F4F6 !important; color:#9CA3AF !important; border:1px dashed #D1D6DB; cursor:pointer; }  /* ⬜ 옅음 — 비활성/미선택. cursor:pointer (클릭으로 ON 토글 가능) */
      .oum-cell.disabled:hover,
      .oum-cell.off:hover,
      .oum-cell.mapped-off:hover { background:#E5E8EB !important; color:#4E5968 !important; }
      .oum-cell.opt-on { background:#9CA3AF !important; color:#fff !important; border:none; cursor:pointer; }                            /* 🩶 회색 — 옵션 ON */
      .oum-cell.url-on,
      .oum-cell.opt-on.url-on,
      .oum-cell.on { background:#4F67FF !important; color:#fff !important; border:none; cursor:pointer; }                                /* 🟦 파랑 — + URL 매핑 */
      .oum-cell.has-inv,
      .oum-cell.opt-on.has-inv,
      .oum-cell.url-on.has-inv,
      .oum-cell.on.has-inv { background:#03A65A !important; color:#fff !important; border:none; cursor:pointer; }                        /* 🟩 초록 — + 재고 매핑 */
      .oum-cell.shared::after { content:attr(data-shared); position:absolute; top:-4px; right:-4px; background:#f59e0b; color:#fff; font-size:12.75px; width:18px; height:18px; border-radius:50%; line-height:18px; font-weight:700; }

      /* [2026-05-29] 시안 v3 C3 — 우측 패널 [URL]/[재고관리] 2탭 + B3-3 in-place 매핑 표 */
      .oum-rt-tabs { display:flex; gap:4px; border-bottom:2px solid #E5E8EB; margin-bottom:14px; padding:0 4px; align-items:flex-end; }
      .oum-rt-tab { background:transparent; border:0; padding:11px 18px; font:inherit; font-size:14.5px; font-weight:700; color:#8B95A1; cursor:pointer; border-bottom:3px solid transparent; margin-bottom:-2px; display:inline-flex; align-items:center; gap:7px; }
      .oum-rt-tab.on { color:#03A65A; border-bottom-color:#03A65A; }
      .oum-rt-tab.on[data-rt-tab="url"] { color:#3B82F6; border-bottom-color:#3B82F6; }
      .oum-rt-tab .cnt { background:#F2F4F6; color:#8B95A1; padding:1px 8px; border-radius:99px; font-size:11.5px; font-weight:700; }
      .oum-rt-tab.on .cnt { background:#F0FDF4; color:#03A65A; }
      .oum-rt-tab.on[data-rt-tab="url"] .cnt { background:#EFF6FF; color:#3B82F6; }
      /* [v20 D4] 통계 흡수 — 탭 우측 인라인 (E4 폰트 150% = 17px) */
      .oum-rt-stats { margin-left:auto; padding-bottom:8px; font-size:17px; color:#6B7684; display:inline-flex; align-items:center; gap:10px; }
      .oum-rt-stats b { font-weight:800; }
      .oum-rt-stats .ok b { color:#15803d; }
      .oum-rt-stats .wn b { color:#F59E0B; }
      .oum-rt-stats .er b { color:#DC2626; }
      .oum-rt-stats .sep { color:#D1D6DB; }

      /* [v20] 재고관리 매핑 — 액션바 (정리 + 브랜드/모델 + 자동매칭) */
      .oum-inv-action { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:10px; }
      .oum-inv-action-left, .oum-inv-action-right { display:inline-flex; align-items:center; gap:7px; flex-wrap:wrap; }
      .oum-inv-label { font-size:13px; font-weight:600; color:#6B7684; }
      .oum-grp-dd { position:relative; display:inline-block; }
      .oum-grp-dd-btn { background:#fff; border:1px solid #BBF7D0; color:#03A65A; padding:6px 12px; border-radius:6px; font:inherit; font-size:13px; font-weight:700; cursor:pointer; display:inline-flex; align-items:center; gap:5px; }
      .oum-grp-dd-btn::after { content:'▾'; font-size:10px; margin-left:3px; }
      .oum-grp-dd-menu { position:absolute; top:38px; left:0; background:#fff; border:1px solid #E5E8EB; border-radius:7px; box-shadow:0 4px 12px rgba(0,0,0,0.1); min-width:200px; z-index:20; overflow:hidden; }
      .oum-grp-dd-it { padding:9px 14px; font-size:13px; cursor:pointer; color:#4E5968; }
      .oum-grp-dd-it:hover { background:#F0FDF4; color:#03A65A; }
      .oum-grp-dd-it.on { background:#F0FDF4; color:#03A65A; font-weight:700; }
      .oum-grp-dd-it.on::before { content:'✓ '; }
      /* 브랜드 검색 (보라) */
      .oum-br-search { position:relative; display:inline-block; }
      .oum-br-search .ic { position:absolute; left:9px; top:50%; transform:translateY(-50%); font-size:12px; pointer-events:none; }
      .oum-br-search input { padding:6px 10px 6px 30px; border:1px solid #DDD6FE; border-radius:6px; font:inherit; font-size:13px; width:130px; outline:none; }
      .oum-br-search input:focus { border-color:#7C3AED; }
      .oum-br-dd { position:absolute; top:38px; left:0; background:#fff; border:1px solid #DDD6FE; border-radius:7px; box-shadow:0 4px 12px rgba(0,0,0,0.1); min-width:260px; max-height:260px; overflow-y:auto; z-index:21; }
      .oum-br-it { padding:8px 12px; font-size:13px; cursor:pointer; border-bottom:1px solid #F1F1F4; display:flex; align-items:center; gap:8px; }
      .oum-br-it:hover { background:#F5F3FF; }
      .oum-br-it.on { background:#F5F3FF; color:#7C3AED; font-weight:700; }
      .oum-br-it.on::before { content:'✓'; color:#7C3AED; font-weight:800; margin-right:3px; }
      .oum-br-it.kbd-hl, .oum-md-it.kbd-hl { background:#F5F3FF; box-shadow:inset 3px 0 0 #7C3AED; }
      .oum-md-it.kbd-hl { background:#EFF6FF; box-shadow:inset 3px 0 0 #3B82F6; }

      /* [v20.2/v20.7] 인라인 SKU/제품명 자동완성 dropdown — body 직속 + position:fixed (JS 로 위치 계산) */
      .oum-ac-wrap { position:relative; }
      .oum-inv-ac-dd { background:#fff; border:1px solid #03A65A; border-radius:7px; box-shadow:0 6px 18px rgba(0,0,0,0.15); overflow-y:auto; z-index:99999; }
      .oum-inv-ac-dd::-webkit-scrollbar { width:8px; }
      .oum-inv-ac-dd::-webkit-scrollbar-thumb { background:#BBF7D0; border-radius:4px; }
      .oum-inv-ac-dd::-webkit-scrollbar-thumb:hover { background:#03A65A; }
      .oum-inv-ac-it { padding:8px 12px; font-size:12.5px; cursor:pointer; border-bottom:1px solid #F1F1F4; }
      .oum-inv-ac-it:last-child { border-bottom:0; }
      .oum-inv-ac-it:hover, .oum-inv-ac-it.kbd-hl { background:#F0FDF4; box-shadow:inset 3px 0 0 #03A65A; }
      .oum-inv-ac-it .nm { font-weight:600; color:#191F28; margin-bottom:2px; }
      .oum-inv-ac-it .meta { font-size:10.5px; color:#15803d; font-family:ui-monospace,monospace; display:flex; gap:8px; align-items:center; }
      .oum-inv-ac-it .meta .stk { color:#03A65A; font-weight:700; font-family:inherit; }
      .oum-inv-ac-it .meta .stk.zero { color:#DC2626; }
      .oum-br-it:not(.on)::before { content:''; display:inline-block; width:12px; }
      .oum-br-it .swatch { width:22px; height:22px; border-radius:5px; background:#7C3AED; color:#fff; font-size:10px; display:inline-flex; align-items:center; justify-content:center; font-weight:800; flex-shrink:0; }
      .oum-br-it .nm { flex:1; }
      .oum-br-it .meta { font-size:10.5px; color:#9CA3AF; font-weight:600; }
      .oum-step-arrow { color:#9CA3AF; font-size:13px; margin:0 2px; }
      /* 모델 검색 (파랑) */
      .oum-md-search { position:relative; display:inline-block; }
      .oum-md-search .ic { position:absolute; left:9px; top:50%; transform:translateY(-50%); font-size:12px; pointer-events:none; }
      .oum-md-search input { padding:6px 10px 6px 30px; border:1px solid #BFDBFE; border-radius:6px; font:inherit; font-size:13px; width:170px; outline:none; }
      .oum-md-search input:focus { border-color:#3B82F6; }
      .oum-md-search.disabled input { background:#F9FAFB; color:#9CA3AF; cursor:not-allowed; border-color:#E5E8EB; }
      .oum-md-search.disabled .ic { opacity:.4; }
      .oum-md-dd { position:absolute; top:38px; left:0; background:#fff; border:1px solid #BFDBFE; border-radius:7px; box-shadow:0 4px 12px rgba(0,0,0,0.1); min-width:260px; max-height:260px; overflow-y:auto; z-index:20; }
      .oum-md-grp-h { padding:5px 12px; background:#F5F3FF; font-size:11px; color:#7C3AED; font-weight:800; }
      .oum-md-it { padding:8px 12px; font-size:13px; cursor:pointer; border-bottom:1px solid #F1F1F4; display:flex; align-items:center; gap:8px; }
      .oum-md-it:hover { background:#EFF6FF; }
      .oum-md-it.on { background:#EFF6FF; color:#1d4ed8; font-weight:700; }
      .oum-md-it.on::before { content:'✓'; color:#3B82F6; font-weight:800; margin-right:3px; }
      .oum-md-it:not(.on)::before { content:''; display:inline-block; width:12px; }
      .oum-md-it .nm { flex:1; }
      .oum-md-it .meta { font-size:10.5px; color:#9CA3AF; font-family:ui-monospace,monospace; }
      /* 자동 매칭 (옅은 outline) */
      .oum-auto-btn-sm { background:#fff; border:1px solid #FED7AA; color:#92400E; padding:6px 12px; border-radius:6px; font:inherit; font-size:13px; font-weight:700; cursor:pointer; }
      .oum-auto-btn-sm:hover { background:#FFF7ED; }

      /* 매칭 범위 안내 */
      .oum-inv-filter-hint { padding:7px 11px; background:#F5F3FF; border:1px solid #DDD6FE; border-radius:6px; font-size:12px; color:#6B21A8; margin-bottom:10px; }
      .oum-inv-filter-hint b { color:#7C3AED; font-weight:800; }

      /* 그룹 details */
      .oum-inv-grp { border:1px solid #E5E8EB; border-radius:8px; margin-bottom:8px; overflow:hidden; background:#fff; }
      .oum-inv-grp summary { padding:11px 14px; background:#F9FAFB; cursor:pointer; display:flex; align-items:center; gap:10px; font-size:14px; font-weight:700; list-style:none; }
      .oum-inv-grp summary::-webkit-details-marker { display:none; }
      .oum-inv-grp summary::before { content:'▶'; font-size:10px; color:#9CA3AF; margin-right:5px; transition:transform 0.15s; }
      .oum-inv-grp[open] summary { border-bottom:1px solid #E5E8EB; }
      .oum-inv-grp[open] summary::before { transform:rotate(90deg); }
      .oum-inv-grp summary .val { font-weight:800; font-size:14px; }
      .oum-inv-grp summary .cnt { background:#F0FDF4; color:#15803d; padding:2px 10px; border-radius:99px; font-size:12px; font-weight:700; margin-left:auto; white-space:nowrap; }
      .oum-inv-grp summary .cnt.warn { background:#FFFBEB; color:#92400E; }
      .oum-inv-grp summary .cnt.err { background:#FEF2F2; color:#991B1B; }

      /* [v20.8 T1] 정렬 가능 컬럼 헤더 */
      .oum-inv-sort-head { display:flex; background:#F9FAFB; font-size:11.5px; color:#6B7684; font-weight:700; border-bottom:1px solid #E5E8EB; }
      .oum-inv-sort-col { padding:9px 14px; cursor:pointer; display:inline-flex; align-items:center; gap:5px; user-select:none; transition:background .1s; }
      .oum-inv-sort-col:hover { background:#F2F4F6; }
      .oum-inv-sort-col.sorted { color:#1d4ed8; background:#EFF6FF; }
      .oum-inv-sort-col .arrow { font-size:10px; opacity:.4; font-weight:800; }
      .oum-inv-sort-col.sorted .arrow { opacity:1; color:#3B82F6; }
      .oum-inv-sort-col.col-opt { width:120px; }
      .oum-inv-sort-col.col-prod { flex:1; }
      .oum-inv-sort-col.col-stat { width:90px; justify-content:center; }

      /* 표 (행 색 G1: 자동=초록 / 수기=노랑 / 미매핑=빨강) */
      .oum-inv-tbl-new { width:100%; border-collapse:separate; border-spacing:0; font-size:13px; }
      .oum-inv-tbl-new td { padding:10px 14px; border-bottom:1px solid #F1F1F4; vertical-align:middle; }
      .oum-inv-tbl-new tr:last-child td { border-bottom:0; }
      .oum-inv-tbl-new tr.auto { background:#F0FDF4; }
      .oum-inv-tbl-new tr.manual { background:#FFFBEB; }
      .oum-inv-tbl-new tr.empty { background:#FEF2F2; }
      .oum-col-opt { width:120px; font-weight:600; color:#191F28; }
      .oum-col-prod { color:#191F28; }
      .oum-col-stat { width:90px; text-align:center; }
      .oum-prod-info { display:flex; flex-direction:column; gap:2px; }
      .oum-prod-name { font-weight:600; font-size:13px; color:#191F28; display:inline-flex; align-items:center; gap:6px; }
      .oum-prod-meta { font-size:11px; color:#15803d; font-family:ui-monospace,monospace; font-weight:600; }
      /* [v20.4] 수기 매핑 행의 ✎ 다시 입력 버튼 */
      .oum-row-reedit { background:#fff; border:1px solid #FCD34D; color:#92400E; width:22px; height:22px; border-radius:5px; font-size:11px; cursor:pointer; padding:0; line-height:1; display:inline-flex; align-items:center; justify-content:center; transition:all .12s; }
      .oum-row-reedit:hover { background:#FFFBEB; border-color:#F59E0B; }
      /* 상태 뱃지 (한 줄, min-width 보장) */
      .oum-stat-pill { padding:3px 10px; border-radius:99px; font-size:12px; font-weight:700; color:#fff; white-space:nowrap; display:inline-flex; align-items:center; gap:3px; min-width:54px; justify-content:center; }
      .oum-stat-pill.auto { background:#03A65A; }
      .oum-stat-pill.manual { background:#F59E0B; }
      .oum-stat-pill.empty { background:#9CA3AF; }
      /* 인라인 SKU 검색 input */
      .oum-inv-search { width:100%; padding:6px 10px; border:1px solid transparent; border-radius:5px; font:inherit; font-size:12.5px; background:transparent; font-family:ui-monospace,monospace; outline:none; }
      .oum-inv-tbl-new tr.manual .oum-inv-search { background:#FFFBEB; border-color:#F59E0B; }
      .oum-inv-tbl-new tr.empty .oum-inv-search { background:#FEF2F2; border-color:#FCA5A5; color:#991B1B; }
      .oum-inv-tbl-new .oum-inv-search:focus { background:#fff; border-color:#F59E0B; }
      .oum-ac-wrap { position:relative; }

      /* 적용 버튼 */
      .oum-inv-foot-new { margin-top:12px; display:flex; justify-content:flex-end; }
      .oum-apply-btn-new { background:#03A65A; color:#fff; border:0; padding:9px 18px; border-radius:7px; font:inherit; font-size:13.5px; font-weight:700; cursor:pointer; }
      .oum-apply-btn-new:hover { background:#15803d; }

      /* (옛 oum-rt-tabs 정의는 위에서 v20 으로 갈음 — 아래 옛 정의 유지) */

      /* [v20 B3] 좌측 4단계 progress dot */
      .oum-step-progress { display:flex; gap:0; margin-bottom:14px; padding:11px 14px; background:#fff; border:1px solid #BFDBFE; border-radius:8px; position:relative; }
      .oum-step-dot { flex:1; display:flex; flex-direction:column; align-items:center; position:relative; }
      .oum-step-dot::after { content:''; position:absolute; top:11px; left:calc(50% + 16px); right:calc(-50% + 16px); height:2px; background:#E5E8EB; z-index:0; }
      .oum-step-dot:last-child::after { display:none; }
      .oum-step-dot .n { width:22px; height:22px; border-radius:50%; background:#E5E8EB; color:#9CA3AF; display:inline-flex; align-items:center; justify-content:center; font-size:12px; font-weight:800; position:relative; z-index:1; }
      .oum-step-dot.done .n { background:#10b981; color:#fff; }
      .oum-step-dot.now .n { background:#3B82F6; color:#fff; box-shadow:0 0 0 3px rgba(59,130,246,0.2); }
      .oum-step-dot .lbl { margin-top:5px; font-size:12px; color:#9CA3AF; font-weight:600; }
      .oum-step-dot.done .lbl { color:#15803d; }
      .oum-step-dot.now .lbl { color:#1d4ed8; font-weight:700; }
      /* B3-3 in-place 표 */
      .oum-inv-tbl { width:100%; border-collapse:separate; border-spacing:0; font-size:12.5px; background:#fff; border:1px solid #E5E8EB; border-radius:8px; overflow:hidden; }
      .oum-inv-tbl th { background:#F9FAFB; padding:8px 10px; text-align:left; font-weight:700; color:#4E5968; font-size:11.5px; border-bottom:1px solid #E5E8EB; }
      .oum-inv-tbl td { padding:7px 10px; border-bottom:1px solid #F1F1F4; vertical-align:middle; }
      .oum-inv-tbl tr.auto-matched { background:#F0FDF4; }                   /* 초록 — 자동 매칭 */
      .oum-inv-tbl tr.manual { background:#FFFBEB; }                          /* 노란 — 수동 입력 (시안 v3) */
      .oum-inv-tbl tr.unused { background:#F9FAFB; color:#9CA3AF; font-style:italic; }
      .oum-inv-tbl input { width:100%; padding:4px 7px; border:1px dashed transparent; border-radius:3px; font-size:12px; background:transparent; font-family:inherit; }
      .oum-inv-tbl tr.manual input { background:#FFFBEB; border-color:#F59E0B; }
      .oum-inv-tbl input:focus { background:#fff; border:1px solid #F59E0B; outline:none; }
      .oum-inv-tbl .stat-ok { background:#03A65A; color:#fff; padding:3px 8px; border-radius:99px; font-size:11px; font-weight:700; }
      .oum-inv-tbl .stat-manual { background:#FFB454; color:#fff; padding:3px 8px; border-radius:99px; font-size:11px; font-weight:700; }
      .oum-inv-tbl .stat-empty { background:#E5E8EB; color:#6B7684; padding:3px 8px; border-radius:99px; font-size:11px; font-weight:700; }
      .oum-inv-tbl .sku-mono { font-family:ui-monospace,monospace; color:#292A2F; }
      .oum-inv-toolbar { display:flex; align-items:center; gap:8px; padding:10px 12px; background:#FFF7ED; border:1px solid #FED7AA; border-radius:8px; margin-bottom:12px; font-size:12.5px; }
      .oum-inv-toolbar .auto-btn { background:#F59E0B; color:#fff; border:0; padding:6px 13px; border-radius:5px; font-size:12px; font-weight:700; cursor:pointer; margin-left:auto; }
      .oum-inv-toolbar .auto-btn:hover { background:#D97706; }
      .oum-inv-foot { display:flex; align-items:center; gap:10px; margin-top:10px; font-size:11.5px; color:#6B7684; }
      .oum-inv-foot .legend-sw { display:inline-block; width:11px; height:11px; border-radius:2px; vertical-align:middle; margin-right:4px; }
      .oum-inv-foot .add-btn { background:#fff; border:1px solid #CBCCD3; color:#292A2F; padding:5px 11px; border-radius:5px; font-size:11.5px; cursor:pointer; margin-left:auto; }
      .oum-inv-foot .apply-btn { background:#03A65A; color:#fff; border:0; padding:6px 13px; border-radius:5px; font-size:12px; font-weight:700; cursor:pointer; margin-left:6px; }

      /* 적용 바 (좌측) - 가운데 정렬 */
      .oum-apply-bar { background:#fff; border:1px solid #bfdbfe; border-radius:10.5px; padding:16.5px; margin-top:15px; display:flex; flex-direction:column; align-items:center; gap:10.5px; }
      .oum-apply-bar .sum { font-size:17.25px; color:#1d4ed8; text-align:center; }
      .oum-apply-bar .sum b { font-weight:700; }
      .oum-apply-btn { background:#3B82F6; color:#fff; border:0; padding:22.5px 42px; border-radius:10.5px; font:inherit; font-size:19.5px; font-weight:700; cursor:pointer; display:inline-flex; align-items:center; gap:10.5px; }
      .oum-apply-btn:hover { background:#2563eb; }
      .oum-apply-btn:disabled { opacity:.4; cursor:not-allowed; }
      .oum-apply-btn.applied { background:#10b981; }

      /* 우측 USL */
      .oum-src-tabs { display:flex; gap:2px; border-bottom:1.5px solid #bbf7d0; padding:9px 6px 0; margin-bottom:12px; flex-wrap:wrap; }
      .oum-src-tab { background:none; border:0; padding:13.5px 15px; font:inherit; font-size:17.25px; font-weight:700; color:#8b95a1; cursor:pointer; display:flex; align-items:center; gap:7.5px; border-bottom:2px solid transparent; margin-bottom:-1.5px; }
      .oum-src-tab.on { color:#10b981; border-bottom-color:#10b981; }
      .oum-src-tab .lg { width:30px; height:30px; border-radius:7.5px; color:#fff; display:inline-flex; align-items:center; justify-content:center; font-size:14.25px; font-weight:800; letter-spacing:.3px; flex-shrink:0; }
      .oum-src-tab .full { font-size:17.25px; }
      .oum-src-tab .cnt { background:#f2f4f6; color:#8b95a1; padding:1px 9px; border-radius:13.5px; font-size:15px; font-weight:700; }
      .oum-src-tab.on .cnt { background:#F0FDF4; color:#10b981; }

      .oum-url-card { background:#fff; border:1px solid #bbf7d0; border-radius:10.5px; margin-bottom:9px; overflow:hidden; }
      .oum-url-card.open { box-shadow:0 2px 6px rgba(16,185,129,.15); }
      .oum-url-ch { padding:18px 16.5px; display:flex; align-items:center; gap:12px; font-size:17.25px; }
      .oum-url-card.open .oum-url-ch { background:#F0FDF4; border-bottom:1px solid #bbf7d0; }
      .oum-url-num { background:#10b981; color:#fff; width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:15.75px; font-weight:700; flex-shrink:0; }
      .oum-url-label { border:none; background:transparent; font:inherit; font-size:18px; font-weight:600; outline:none; padding:9px 9px; border-radius:6px; width:210px; color:#15803d; }
      .oum-url-label:hover, .oum-url-label:focus { background:#fff; }
      .oum-url-input { flex:1; min-width:270px; border:1px solid #bbf7d0; border-radius:7.5px; padding:11.25px 13.5px; font:inherit; font-size:17.25px; font-family:ui-monospace,monospace; color:#15803d; }
      /* [2026-05-27 통일] URL 카드 액션 버튼 — 모두 같은 height·padding (시안 2 변형 적용) */
      .oum-url-cnt, .oum-url-tog, .oum-url-copy, .oum-url-del {
        height: 36px; padding: 0 12px; border: 1px solid #bbf7d0; background: #fff;
        border-radius: 7.5px; font: inherit; font-size: 15px; font-weight: 600;
        color: #15803d; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;
        white-space: nowrap; line-height: 1; box-sizing: border-box;
      }
      .oum-url-cnt { background: #F0FDF4; cursor: default; font-variant-numeric: tabular-nums; }
      .oum-url-cnt b { color: #10b981; font-weight: 800; }
      .oum-url-tog:hover, .oum-url-copy:hover { background:#F0FDF4; }
      .oum-url-del { color:#dc2626; border-color:#fecaca; }
      .oum-url-del:hover { background:#FEF2F2; }
      /* [2026-06-05] 크롤 실패 URL — 빨강 카드 + ❌ 배지 + 🔄 재크롤 */
      .oum-url-card.crawl-fail { border-color:#fca5a5; background:#FFF7F7; }
      .oum-url-card.crawl-fail .oum-url-ch { background:#FEF2F2; }
      .oum-url-cnt.fail { background:#FEE2E2; }
      .oum-url-cnt.fail b { color:#dc2626; }
      .oum-url-recrawl { background:#E4002B; color:#fff; border:1px solid #E4002B; border-radius:7px; padding:0 11px; height:33px; font-size:12px; font-weight:800; cursor:pointer; white-space:nowrap; }
      .oum-url-recrawl:hover { background:#c00; }
      .oum-url-failmsg { padding:8px 14px; background:#FEF2F2; color:#B91C1C; font-size:11.5px; font-weight:700; line-height:1.5; border-top:1px dashed #fca5a5; }
      /* [2026-06-12] 딜·기획전 허브 — 단품으로 커버됨 (실패 아님, 중립 안내) */
      .oum-url-card.crawl-covered { border-color:#bfdbfe; background:#F5F9FF; }
      .oum-url-covered { padding:8px 14px; background:#EFF6FF; color:#1D4ED8; font-size:11.5px; font-weight:700; line-height:1.5; border-top:1px dashed #bfdbfe; }
      /* [2026-06-11] 크롤 실패 요약 배너 — 어떤 URL이 왜 실패했는지 한눈에 */
      .oum-failsum { margin:0 0 10px; padding:10px 12px; background:#FEF2F2; border:1px solid #fca5a5; border-radius:9px; }
      .oum-failsum-h { display:flex; align-items:center; gap:8px; flex-wrap:wrap; color:#B91C1C; font-size:13px; font-weight:800; }
      .oum-failsum-jump { margin-left:auto; background:#E4002B; color:#fff; border:0; border-radius:7px; padding:4px 10px; font-size:11.5px; font-weight:800; cursor:pointer; white-space:nowrap; }
      .oum-failsum-jump:hover { background:#c00; }
      .oum-failsum-list { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
      .oum-failsum-item { background:#fff; border:1px solid #fca5a5; border-radius:999px; padding:3px 10px; font-size:11.5px; font-weight:700; color:#7f1d1d; }
      .oum-failsum-item em { font-style:normal; color:#dc2626; font-weight:800; }
      /* 실패 카드 깜빡임 강조 (자동 스크롤 도착 시) */
      @keyframes oumFailFlash { 0%,100%{ box-shadow:0 0 0 0 rgba(228,0,43,0); } 30%{ box-shadow:0 0 0 4px rgba(228,0,43,.45); } 60%{ box-shadow:0 0 0 4px rgba(228,0,43,.20); } }
      .oum-url-card.oum-fail-flash { animation:oumFailFlash 1.6s ease-in-out 1; }
      /* [2026-06-13] URL 중복 경고 배너 (시안 A) — 등록 수 ≠ 실제 크롤 수(중복 제거 후) */
      .oum-dupwarn { margin:0 0 10px; padding:10px 12px; background:#FFFBEB; border:1px solid #FCD34D; border-left:4px solid #F59E0B; border-radius:9px; }
      .oum-dupwarn.cross { background:#FEF2F2; border-color:#fca5a5; border-left-color:#EF4444; }
      .oum-dupwarn-h { color:#92400E; font-size:13px; font-weight:800; line-height:1.55; }
      .oum-dupwarn.cross .oum-dupwarn-h { color:#B91C1C; }
      .oum-dupwarn-h b { font-weight:900; }
      .oum-dupwarn-list { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
      .oum-dupwarn-item { background:#fff; border:1px solid #FCD34D; border-radius:999px; padding:4px 11px; font-size:11.5px; font-weight:700; color:#78350f; cursor:pointer; }
      .oum-dupwarn-item:hover { background:#FFFBEB; }
      .oum-dupwarn-item.cross { border-color:#fca5a5; color:#7f1d1d; }
      .oum-dupwarn-item.covered { border-color:#bfdbfe; color:#1d4ed8; }
      .oum-dupwarn-item em { font-style:normal; color:#dc2626; font-weight:800; }
      .oum-dupwarn-why { color:#9ca3af; font-weight:600; font-size:10.5px; margin-left:4px; }
      /* [2026-05-27] 카드 미니 액션 — 순서 변경 ↑↓ + 복사 ⎘ */
      .oum-url-actions { display:inline-flex; gap:2px; }
      .oum-url-mini { background:#fff; border:1px solid #d1d6db; border-radius:6px; width:33px; height:33px; display:inline-flex; align-items:center; justify-content:center; font-size:18px; color:#4e5968; cursor:pointer; padding:0; line-height:1; transition:all .12s; }
      .oum-url-mini:hover:not(:disabled) { background:#3B82F6; color:#fff; border-color:#3B82F6; }
      .oum-url-mini:disabled { opacity:.35; cursor:not-allowed; }
      /* [2026-05-27] C5 복사 버튼 — SVG 아이콘 + "복사" 텍스트 콤보 (▸매핑·✕ 와 동일 톤) */
      /* [2026-05-27] oum-url-copy 는 위 통일 스타일 사용 — active scale 만 유지 */
      .oum-url-copy:active { transform:scale(.97); }
      /* [2026-05-27] 드래그앤드랍 — ⋮⋮ 핸들 + 드래그 시각 피드백 + 드롭 라인 */
      .oum-url-drag { display:inline-flex; align-items:center; justify-content:center; width:30px; height:33px; color:#9ca3af; cursor:grab; font-size:24px; line-height:1; letter-spacing:-4px; user-select:none; flex-shrink:0; }
      .oum-url-drag:hover { color:#3B82F6; }
      .oum-url-card { cursor:default; }
      .oum-url-card.dragging { opacity:.4; cursor:grabbing; }
      .oum-url-card.drop-above { box-shadow:0 -3px 0 0 #3B82F6 inset; }
      .oum-url-card.drop-below { box-shadow:0 3px 0 0 #3B82F6 inset; }
      .oum-url-body { padding:22.5px 16.5px; background:#F0FDF4; }
      .oum-url-card:not(.open) .oum-url-body { display:none; }
      .oum-add-url { width:100%; background:#fff; border:1.5px dashed #bbf7d0; color:#10b981; padding:13.5px; border-radius:10.5px; font:inherit; font-size:18px; cursor:pointer; font-weight:700; margin-top:9px; }
      .oum-add-url:hover { background:#F0FDF4; border-color:#10b981; }
      .oum-add-url:disabled { opacity:.4; cursor:not-allowed; }

      /* [2026-05-27 B2-2] 셀 shared 배지 hover floating card — Card Stack 스타일
         pointer-events:auto — 마우스가 tooltip 안에 있으면 안 닫힘 (↗ 버튼 클릭 가능)
         max-height + overflow-y:auto — 매핑 많아도 휠 스크롤로 모두 확인 */
      .oum-shared-tip { position:fixed; z-index:99999; background:#fff; border:1px solid #d1d6db; border-radius:15px; padding:15px; min-width:510px; max-width:660px; max-height:80vh; overflow-y:auto; box-shadow:0 10px 24px rgba(0,0,0,.18); pointer-events:none; }
      /* tooltip 내부 스크롤바 — 깔끔하게 */
      .oum-shared-tip::-webkit-scrollbar { width:12px; }
      .oum-shared-tip::-webkit-scrollbar-track { background:#f2f4f6; border-radius:0 15px 15px 0; }
      .oum-shared-tip::-webkit-scrollbar-thumb { background:#cbd5e0; border-radius:6px; }
      .oum-shared-tip::-webkit-scrollbar-thumb:hover { background:#94a3b8; }
      .oum-shared-tip .arrow { position:absolute; width:0; height:0; border:6px solid transparent; }
      .oum-shared-tip.below .arrow { bottom:100%; left:50%; transform:translateX(-50%); border-bottom-color:#fff; }
      .oum-shared-tip.below .arrow::before { content:''; position:absolute; top:1px; left:-7px; width:0; height:0; border:7px solid transparent; border-bottom-color:#d1d6db; z-index:-1; }
      .oum-shared-tip.above .arrow { top:100%; left:50%; transform:translateX(-50%); border-top-color:#fff; }
      .oum-shared-tip.above .arrow::before { content:''; position:absolute; bottom:1px; left:-7px; width:0; height:0; border:7px solid transparent; border-top-color:#d1d6db; z-index:-1; }
      /* [v25-A 2026-06-01] 가로 placement — 카드를 셀 우측/좌측 옆에 띄움 (위·아래 인접 행 안 가림) */
      .oum-shared-tip.right .arrow { right:100%; top:50%; transform:translateY(-50%); border-right-color:#fff; }
      .oum-shared-tip.right .arrow::before { content:''; position:absolute; left:1px; top:-7px; width:0; height:0; border:7px solid transparent; border-right-color:#d1d6db; z-index:-1; }
      .oum-shared-tip.left .arrow { left:100%; top:50%; transform:translateY(-50%); border-left-color:#fff; }
      .oum-shared-tip.left .arrow::before { content:''; position:absolute; right:1px; top:-7px; width:0; height:0; border:7px solid transparent; border-left-color:#d1d6db; z-index:-1; }
      /* [v25-A.1 2026-06-02] hover bridge — 카드 좌/우 가상 padding 으로 hover 영역 확장 (셀↔카드 사이 deadzone 0)
         pointer-events:auto + tip 자체 mouseenter 가 ::before/::after 영역에서도 트리거됨 */
      .oum-shared-tip { pointer-events:auto; }
      .oum-shared-tip.left::after { content:''; position:absolute; left:-14px; top:0; width:14px; height:100%; background:transparent; }
      .oum-shared-tip.right::after { content:''; position:absolute; right:-14px; top:0; width:14px; height:100%; background:transparent; }
      .oum-shared-tip .stp-grp { background:#FAFBFC; border-radius:10.5px; padding:15.75px 13.5px; margin-bottom:9px; }
      .oum-shared-tip .stp-grp:last-child { margin-bottom:0; }
      .oum-shared-tip .stp-grp-h { display:flex; align-items:center; gap:10.5px; margin-bottom:7.5px; padding-bottom:6px; border-bottom:1px dashed #e5e8eb; text-align:left; }
      .oum-shared-tip .stp-chip { width:33px; height:33px; border-radius:9px; display:flex; align-items:center; justify-content:center; font-size:15px; font-weight:800; color:#fff; flex-shrink:0; }
      .oum-shared-tip .stp-name { font-size:18.75px; font-weight:700; color:#191F28; flex:1; text-align:left; }
      .oum-shared-tip .stp-cnt { background:#3B82F6; color:#fff; font-size:15.75px; font-weight:700; padding:2px 12px; border-radius:12px; flex-shrink:0; }
      .oum-shared-tip .stp-url-row { padding:4.5px 0; text-align:left; display:flex; align-items:center; gap:9px; }
      .oum-shared-tip .stp-url-row .stp-text { flex:1; min-width:0; }
      .oum-shared-tip .stp-lbl { font-size:16.5px; font-weight:600; color:#191F28; }
      /* [2026-05-27 시안2] URL 한 줄 + 도메인 강조 — 셀 가림 완화 */
      .oum-shared-tip .stp-url { font-family:ui-monospace,monospace; font-size:15px; color:#6b7684; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; word-break:normal; }
      .oum-shared-tip .stp-url .stp-url-domain { color:#1d4ed8; font-weight:700; }
      /* [2026-05-27 A4] 그룹 내부 스크롤 — 헤더는 보이고 그룹 안 URL list 만 max-height 180px + 휠 스크롤 */
      .oum-shared-tip .stp-grp-body { max-height:180px; overflow-y:auto; padding-right:4px; }
      .oum-shared-tip .stp-grp-body::-webkit-scrollbar { width:6px; }
      .oum-shared-tip .stp-grp-body::-webkit-scrollbar-track { background:#f2f4f6; border-radius:3px; }
      .oum-shared-tip .stp-grp-body::-webkit-scrollbar-thumb { background:#cbd5e0; border-radius:3px; }
      .oum-shared-tip .stp-grp-body::-webkit-scrollbar-thumb:hover { background:#94a3b8; }

      /* [2026-05-27 B1] URL 바로가기 버튼 — ↗ 22×22 사각형, 호버 시 파란색 */
      /* [2026-05-27 통일] ↗ 열기 — 다른 액션 버튼과 같은 36 height + 아이콘만 (width=height) */
      .oum-url-go { background:#fff; border:1px solid #bbf7d0; border-radius:7.5px; width:36px; height:36px; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; color:#3B82F6; font-size:18px; font-weight:700; line-height:1; padding:0; transition:all .12s; flex-shrink:0; text-decoration:none; box-sizing:border-box; }
      .oum-url-go:hover { background:#EFF6FF; border-color:#bfdbfe; }
      .oum-url-go:active { transform:scale(.95); }
    `;
    document.head.appendChild(s);
  }

  // ─── 마지막 작업 상태 저장·복원 (localStorage) ───
  //   모음전 코드별로 마지막 활성 탭(currentSrc) + 펼친 카드의 URL dbId 저장
  //   재진입 시 자동 복원 — "작업하던 그대로" 열림
  const LS_KEY = (bundleCode) => `oum:lastState:${bundleCode}`;
  function saveLastState(bundleCode, currentSrc, openDbId) {
    try {
      localStorage.setItem(LS_KEY(bundleCode), JSON.stringify({
        currentSrc: currentSrc || null,
        openDbId: openDbId || null,
        ts: Date.now(),
      }));
    } catch (e) { /* private mode 등 — 조용히 무시 */ }
  }
  function loadLastState(bundleCode) {
    try {
      const raw = localStorage.getItem(LS_KEY(bundleCode));
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) { return null; }
  }

  // ───────────────────────────────────────────────────────────
  //                       MAIN ENTRY
  // ───────────────────────────────────────────────────────────
  async function openOptionUrlModal(bundleCode, opts) {
    if (!bundleCode) { alert('모음전 코드를 찾을 수 없어요.'); return; }
    // [2026-06-05] opts.focusSourceKey — 매트릭스 실패 카드 클릭 시 해당 소싱처 탭을 우선 활성화.
    const _focusSourceKey = (opts && typeof opts === 'object') ? (opts.focusSourceKey || null) : null;
    // [2026-06-11] opts.scrollToFail — 매트릭스 "URL N개 실패" 카드 클릭으로 들어온 경우,
    //   초기 렌더 후 첫 실패 URL 카드로 자동 스크롤 + 깜빡임 강조 (1회만).
    let _pendingFailScroll = (opts && typeof opts === 'object') ? !!opts.scrollToFail : false;
    injectStyle();

    // 상태
    const state = {
      axes: [{ name: '', values: '' }, { name: '', values: '' }],  // [{name, values}]
      selected: new Set(),     // 옵션 활성 (JSON.stringify(axisVals))
      seen: new Set(),         // 매트릭스 변경 시 자동 ON 보존
      // [2026-05-27 D1] is_active=false 옵션 — 사용자 OFF 했지만 매핑 있어 데이터 보존
      // 매트릭스에서 mapped-off (노란 빗금 + 🔗 + tooltip) 으로 표시. selected 에는 들어가지 않음.
      mappedOff: new Set(),
      applied: false,          // 좌→우 적용 여부
      sources: [],             // [{key, label, color}]
      urls: {},                // {sourceKey: [{tempId, label, url, option_keys: [k,...]}]}
      openUrlId: null,         // 펼친 URL tempId
      tempIdSeq: 1,
      // [2026-05-29 시안 v3 C3] 우측 패널 탭 — 'url' (소싱처 URL) | 'inv' (재고관리 매핑 B3-3)
      rightTab: 'url',
      // [B3-3] 재고관리 매핑 표 — {bundleSku: {invSku, color, size, model, isManual, isUnused}}
      //   (셀 자동매칭 결과 + 사용자 수정값. 적용 클릭 시 서버에 mappings 로 push)
      invRows: {},
      // candidates 백업 (서버 alias 매칭 결과)
      invCandidates: {},
      // 재고 옵션 풀 (검색·드롭다운용)
      invOptions: [],
      // [perf 2026-05-29] 재고 매핑 셀(초록) 표시용 — 배경 로드 전 빈 Set 으로 안전
      invMappedKeys: new Set(),
      // [v20 2026-05-30] 브랜드 → 모델 2단계 검색 메타
      invBrands: [],                          // [{name, model_count, option_count}]
      invModelsByBrand: {},                   // {brand: [{model_name, option_count}]}
      invBundleMeta: { brand: '', model_name: '', model_code: '' },  // 모음전 자체 메타 (자동 추론용)
      invFilter: { brand: '', model: '' },    // 사용자 선택 필터 (없으면 bundle_meta 사용)
      // [v20.4] 사용자가 직접 변경했는지 추적 — 변경 후엔 bundle_meta fallback 안 함
      invFilterUserSet: { brand: false, model: false },
      invGroupBy: 'axis-0',                   // 그룹화 기준 — 'axis-0' / 'axis-1' / ... / 'flat' / 'status'
      // [v20.8] 표 컬럼 정렬 — col: 'opt' (옵션값=사이즈 등) / 'prod' (제품명) / 'status' (자동/수기/미매핑)
      invSort: { col: 'opt', dir: 'asc' },
      invBrandDdOpen: false,
      invModelDdOpen: false,
    };

    // 모달 마크업
    const bg = document.createElement('div');
    bg.className = 'oum-bg';
    // 배경 클릭 닫기 — 자동 저장 fire-and-forget + 마지막 상태 기록
    //   (snapshotLastState 는 아래에서 정의되므로 클로저 캡처 가능 — addEventListener 호출 시점은 정의 이후)
    bg.addEventListener('click', e => {
      if (e.target === bg) {
        try { snapshotLastState(); } catch (err) {}
        autoSave();
        bg.remove();
      }
    });

    const modal = document.createElement('div');
    modal.className = 'oum-modal';
    modal.innerHTML = `
      <div class="oum-mh">
        <h2>옵션 조합 생성 및 수정 + 소싱처 URL 매핑</h2>
        <span class="pill">✨ 동시 입력</span>
        <button class="close" type="button">×</button>
      </div>
      <div class="oum-mb">
        <div class="oum-legend">
          <b style="color:#191F28;">📖 셀 색 (좌측 매트릭스):</b>
          <span><span class="leg-empty"></span>OFF (꺼짐)</span>
          <span><span class="leg-gray"></span>ON (옵션 켜짐)</span>
          <span style="margin-left:auto; color:#92400E;">💡 좌측에서 옵션 만들고 [URL 매핑에 적용 →] · 매핑 색(파랑/초록)은 우측 탭 안에서</span>
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

    // [perf 2026-05-29] 즉시 로딩 표시 — 데이터 도착 전에도 창이 살아있음을 보여줌
    //   (모달 껍데기는 위에서 이미 append 됨 → 클릭 즉시 창이 뜨고 "불러오는 중" 노출)
    $('#oum-left').innerHTML = '<div style="padding:48px 16px;text-align:center;color:#8B95A1;font-size:14px">옵션 매트릭스 불러오는 중…</div>';
    $('#oum-right').innerHTML = '<div style="padding:48px 16px;text-align:center;color:#8B95A1;font-size:14px">불러오는 중…</div>';

    // [perf 2026-05-29] 함수 스코프로 hoist — 재고 매핑은 배경 로드(.then) 후 적용하므로
    //   keyBySku / _invMapPromise 를 try 바깥에서 참조 가능해야 함.
    let keyBySku = {};
    let _invMapPromise = null;

    // 재고 매핑 데이터 적용 — 배경 로드 완료 시 호출 (모달 초기 표시를 막지 않음).
    //   기존: source-urls 처리 중 await 로 블로킹 → 안 보이는 재고탭 데이터 때문에 표시 지연.
    //   변경: 옵션·URL UI 는 즉시 렌더, 재고 매핑은 도착하면 셀 초록색·재고탭만 갱신.
    function applyInvData(ij) {
      if (!ij || !ij.ok) return;
      state.invOptions = ij.inventory_options || [];
      state.invCandidates = ij.candidates || {};
      // [v20] 브랜드 → 모델 검색 메타
      state.invBrands = ij.brands || [];
      state.invModelsByBrand = ij.models_by_brand || {};
      state.invBundleMeta = ij.bundle_meta || { brand: '', model_name: '', model_code: '' };
      // [v20.6] 초기 필터 = 서버가 받은 값 그대로 (공란이면 공란 유지, bundle_meta fallback 없음)
      if (ij.filter_applied) {
        state.invFilter = {
          brand: ij.filter_applied.brand || '',
          model: ij.filter_applied.model || '',
        };
      }
      state.invMappedKeys = new Set();
      state.invRows = {};
      Object.entries(ij.mappings || {}).forEach(([bSku, invList]) => {
        if (Array.isArray(invList) && invList.length > 0) {
          const k = keyBySku[bSku];
          if (k) state.invMappedKeys.add(k);
          // B3-3 표는 1:1 — 첫 매핑 inv_sku 표시
          const inv = state.invOptions.find(o => o.sku === invList[0]);
          state.invRows[bSku] = {
            invSku: invList[0],
            model: inv ? inv.model_name : '',
            color: inv ? inv.color : '',
            size: inv ? inv.size : '',
            isManual: false,
            isUnused: false,
          };
        }
      });
    }

    // 소싱처 목록 + 기존 옵션 로드 (기존 모음전 GET 활용)
    try {
      // [perf 2026-05-29] 두 요청 병렬화 — inventory-mapping 을 배경으로 먼저 띄워두고
      //   source-urls 만 await. 재고 매핑은 아래 rerender 이후 .then 으로 비동기 적용.
      _invMapPromise = fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/inventory-mapping`)
        .then(res => res.json()).catch(() => null);
      const r = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls`);
      const j = await r.json();
      if (j && j.ok) {
        state.sources = (j.sources || []).map(k => ({ key: k, label: k }));
        // [2026-05-25] 옵션 canonical_sku ↔ axis values key 매핑 — 매핑 복원·자동저장 공용
        //   재진입 시 option_ids 를 option_keys 로 복원해야 매트릭스 매핑이 살아 있음
        keyBySku = {};
        const skuByKey = {};
        (j.options || []).forEach(o => {
          if (Array.isArray(o.axis_values)) {
            const k = JSON.stringify(o.axis_values.map(v => String(v)));
            keyBySku[o.canonical_sku] = k;
            skuByKey[k] = o.canonical_sku;
          }
        });
        state.skuByKey = skuByKey;
        // 재고 매핑(invRows/invOptions/...)은 await 하지 않음 → 모달 즉시 표시.
        //   실제 적용은 함수 끝 rerender() 직후 _invMapPromise.then(applyInvData) 에서.

        // 기존 URL 도 가져옴 (있으면 표시) — option_ids → option_keys 복원
        //   [2026-05-27] 옛 sku + 새 sku 가 같은 axis_values 로 중복 매핑된 경우
        //   같은 key 가 두 번 들어가서 shared 카운트가 부풀려짐 → Set 으로 중복 제거
        Object.keys(j.urls || {}).forEach(sk => {
          const arr = (j.urls[sk] || []).filter(u => u.id);
          if (arr.length) {
            state.urls[sk] = arr.map(u => ({
              tempId: state.tempIdSeq++,
              dbId: u.id,
              label: u.label || '',
              url: u.url || '',
              url_type: u.url_type || '',
              // [2026-06-05] 크롤 상태 — 실패 URL 빨강·재크롤 표시용 (신규 추가 URL은 undefined)
              crawled: u.crawled,
              lastStatus: u.last_status || null,
              option_keys: [...new Set(
                (u.option_ids || [])
                  .map(sku => keyBySku[sku])
                  .filter(Boolean)
              )],
            }));
          }
        });

        // [2026-05-24 A-1 v2] BundleOptionStep (axis_steps) 우선 — 정식 단일 진실 원천
        //   · 축 이름은 BundleOptionStep.axis_name (사용자가 '색상'·'사이즈'·'재질' 등 입력)
        //   · 축 값은 BundleOptionStep.values_json
        //   · 옵션의 axis_values 는 단순 값 array 라 axis name 정보 X
        const axisSteps = j.axis_steps || [];
        const opts = j.options || [];
        if (axisSteps.length > 0) {
          // 정식 경로: BundleOptionStep 으로 axes 재구성
          state.axes = axisSteps.map(st => ({
            name: st.axis_name || '',
            values: (st.values || []).join(','),
          }));
          state.applied = true;
          // [2026-05-27 FIX] 비활성 상태 보존 — 매트릭스 전체 콤보를 seen 에 미리 채움
          //   배경: recalcMatrix() 가 seen 에 없는 콤보를 "처음 보는 새 콤보" 로 인식해
          //   자동 활성화함. DB 엔 활성 옵션만 저장돼 재진입 시 비활성 24 개가 seen 누락
          //   → 어떤 trigger 로든 recalcMatrix() 호출되면 비활성이 활성으로 되돌아오는 버그.
          //   매트릭스 풀(BundleOptionStep cartesian)은 이미 사용자가 본 적 있다고 간주.
          const stepValuesList = axisSteps.map(st => (st.values || []).map(v => String(v)));
          if (stepValuesList.every(v => v.length > 0)) {
            cartesian(stepValuesList).forEach(c => state.seen.add(JSON.stringify(c)));
          }
          // selected — 각 옵션 axis_values (값 array) 를 그대로 key 로
          //   [2026-05-27 D1] is_active=false 옵션은 mappedOff 로 (selected 아님 — 매트릭스에서 빗금 표시)
          opts.forEach(o => {
            const av = Array.isArray(o.axis_values) ? o.axis_values : null;
            if (!av || av.length !== axisSteps.length) return;
            const key = JSON.stringify(av.map(v => String(v)));
            state.seen.add(key);
            if (o.is_active === false) {
              state.mappedOff.add(key);
            } else {
              state.selected.add(key);
            }
          });
        } else if (opts.length > 0) {
          // 레거시 폴백: axis_steps 없으면 옵션의 color_code/size_code 로 2축 추정
          const colorSet = new Set();
          const sizeSet = new Set();
          opts.forEach(o => {
            if (o.color_display) colorSet.add(o.color_display);
            if (o.size_display) sizeSet.add(o.size_display);
          });
          const colors = [...colorSet];
          const sizes = [...sizeSet];
          if (colors.length > 0 && sizes.length > 0) {
            state.axes = [
              { name: '색상', values: colors.join(',') },
              { name: '사이즈', values: sizes.join(',') },
            ];
            state.applied = true;
            opts.forEach(o => {
              const key = JSON.stringify([String(o.color_display || ''), String(o.size_display || '')]);
              state.selected.add(key);
              state.seen.add(key);
            });
          }
        }
      }
    } catch (e) { console.warn('sources load fail', e); }

    // 소싱처 라벨 매핑 (사용자 친화)
    const SRC_LABELS = {
      lemouton: '르무통 공홈', musinsa: '무신사', ssf: 'SSF샵', ssg: 'SSG',
      lotteon: '롯데온', ss_lemouton: '스마트스토어 르무통',
    };
    const SRC_COLORS = {
      lemouton: '#a78bfa', musinsa: '#191F28', ssf: '#14b8a6', ssg: '#F47216',
      lotteon: '#ef4444', ss_lemouton: '#22c55e',
    };
    // 약식 오버라이드 — abbr(label) 이 SSF/SSG 둘 다 'ss' 로 만들어 혼동되는 케이스 구분
    const SRC_ABBR = { ssg: 'sg' };

    // 활성 소싱처 (기본 6개 보장)
    const builtinKeys = ['lemouton', 'musinsa', 'ssf', 'ssg', 'lotteon', 'ss_lemouton'];
    builtinKeys.forEach(k => {
      if (!state.sources.find(s => s.key === k)) {
        state.sources.unshift({ key: k, label: SRC_LABELS[k] || k });
      }
    });

    // ─── 마지막 작업 상태 복원 — "작업하던 그대로" 열림 ───
    //   1) currentSrc — 저장된 탭이 sources 에 있으면 그걸로, 없으면 default 첫 탭
    //   2) openUrlId  — 저장된 dbId 의 URL 카드가 현재 탭에 있으면 자동 펼침
    const lastState = loadLastState(bundleCode);
    const savedSrc = lastState && lastState.currentSrc;
    if (_focusSourceKey && state.sources.find(s => s.key === _focusSourceKey)) {
      state.currentSrc = _focusSourceKey;   // 실패 카드 클릭 → 해당 소싱처 탭 우선
    } else if (savedSrc && state.sources.find(s => s.key === savedSrc)) {
      state.currentSrc = savedSrc;
    } else {
      state.currentSrc = state.sources[0]?.key || 'lemouton';
    }
    const savedOpenDbId = lastState && lastState.openDbId;
    if (savedOpenDbId) {
      const arr = state.urls[state.currentSrc] || [];
      const target = arr.find(u => u.dbId === savedOpenDbId);
      if (target) state.openUrlId = target.tempId;
    }

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

      // [v20 B3] 4단계 진행 표시 — 현재 단계 추론
      //   ① 축 생성 / ② 옵션명 입력 / ③ 매트릭스 자동 생성 / ④ OFF 클릭
      let stepNow;
      if (state.axes.length === 0 || state.axes.every(a => !a.name)) stepNow = 1;
      else if (valid.length === 0 || valid.every(a => a.values.length === 0)) stepNow = 2;
      else if (onCnt === totalCnt && totalCnt > 0) stepNow = 3;  // 모든 셀 ON = 자동 생성 직후
      else stepNow = 4;  // 일부 OFF = 사용자 편집 중
      const STEPS = ['축 생성', '옵션명', '자동 생성', 'OFF 클릭'];
      let html = '<div class="oum-step-progress">';
      STEPS.forEach((lbl, i) => {
        const n = i + 1;
        const cls = n < stepNow ? 'done' : (n === stepNow ? 'now' : '');
        html += `<div class="oum-step-dot ${cls}"><span class="n">${n}</span><span class="lbl">${lbl}</span></div>`;
      });
      html += '</div>';

      html += `<div class="oum-ph">
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
            <div style="display:flex; align-items:center; gap:6px; margin-left:auto;">
              <span class="oum-sortbtns">
                <button class="oum-sortb" data-axis-sort="${i}" data-dir="asc" type="button" title="오름차순 정렬">▲ 오름</button>
                <button class="oum-sortb" data-axis-sort="${i}" data-dir="desc" type="button" title="내림차순 정렬">▼ 내림</button>
              </span>
              ${state.axes.length > 1 ? `<button class="del" data-axis-del="${i}" type="button">삭제</button>` : ''}
            </div>
          </div>
          <div class="oum-axis-in">
            <input data-axis-name="${i}" placeholder="축 이름 (예: ${REC[i] || '용량'})" value="${esc(axis.name)}">
            <input data-axis-values="${i}" placeholder="값 — 쉼표 구분 (예: 그레이,블랙,옐로우)" value="${esc(axis.values)}">
          </div>
          <div class="oum-axis-chips">${parseValues(axis.values).map(v => `<span class="c">${esc(v)}</span>`).join('')}<span class="oum-drag-hint">순서 변경: 아래 매트릭스 헤더를 드래그하세요</span></div>
        </div>`;
      });

      html += `<button class="oum-add-axis" id="oum-add-axis" ${state.axes.length >= 3 ? 'disabled' : ''} type="button">＋ 축 추가 (현재 ${state.axes.length}축 / 최대 3축)</button>`;

      // [2026-05-24] 빠른 선택 칩 영역 제거 — 사용자 피드백 (매트릭스 행/열 헤더 클릭으로 충분)

      // 매트릭스
      html += `<div class="oum-mtx">
        <div class="oum-mtx-h">
          <span>조합 매트릭스 ${onCnt}/${totalCnt}</span>
          <span class="oum-mtx-all" data-mtx-all>전체 선택/해제</span>
        </div>
        ${renderMatrix(valid)}
      </div>`;

      // [2026-06-04] 적용 버튼 제거 — on/off 가 우측 URL/재고 패널에 자동 반영
      if (valid.length) state.applied = true;
      html += `<div class="oum-apply-bar">
        <div class="sum">${valid.length ? `✓ 옵션 <b>${onCnt}개</b> 활성 / ${totalCnt - onCnt}개 비활성 — 우측에 적용?` : '먼저 축을 입력하세요'}</div>
      </div>`;

      left.innerHTML = html;
    }

    function filterCombos(axisName, val) {
      const valid = validAxes();
      const allCombos = cartesian(valid.map(a => a.values));
      // [2026-05-24 BUG FIX] axis 못 찾으면 빈 배열 반환 (이전: allCombos → 전체 토글 버그)
      const ax = String(axisName == null ? '' : axisName).trim();
      const axisIdx = valid.findIndex(a => String(a.name || '').trim() === ax);
      if (axisIdx < 0) {
        console.warn('[oum] filterCombos axis not found:', axisName, '— available:', valid.map(a => a.name));
        return [];
      }
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

    // [2026-05-30 시안 v18 색 단순화] 좌측 옵션 매트릭스 = ON/OFF 2색만 (파랑·초록 제거)
    //   URL 카드 안 매트릭스 = ON / URL 매핑 2색만 (초록 제거)
    //   urlMapped 인자로 분기:
    //     - 좌측(주 옵션 매트릭스): cellState(active, false, _) → opt-on / disabled
    //     - URL 카드(매핑): cellState(active, urlMapped, _) → opt-on / url-on / disabled
    //   재고 매핑(has-inv) 은 더 이상 매트릭스 색으로 표시 안 함 (재고관리 매핑 탭의 그룹 표에서 상태)
    function cellState(active, urlMapped, _hasInvLegacy) {
      if (!active) return { cls: 'disabled', inner: '<span>·</span>' };
      if (urlMapped) return { cls: 'opt-on url-on', inner: '<span>✓</span>' };
      return { cls: 'opt-on', inner: '<span>ON</span>' };
    }

    function renderMatrix1D(axis) {
      const valid = validAxes();
      let html = `<table class="oum-mtx-table"><tbody><tr>`;
      axis.values.forEach(v => {
        const k = keyOf([v]);
        const on = state.selected.has(k);
        // [2026-06-04 FIX] mappedOff(is_active=false)는 OFF 로 표시해야 함.
        //   기존 active = on||mappedOff → OFF 저장한 옵션이 재진입 시 ON 으로 보이던 버그.
        const hasInv = on && state.invMappedKeys && state.invMappedKeys.has(k);
        // 좌측 매트릭스: URL 매핑은 표시 안 함 (우측에서) → urlMapped=false. ON 은 selected 만.
        const s = cellState(on, false, hasInv);
        html += `<td><span class="oum-cell ${s.cls}" data-cell-key='${esc(k)}'>${s.inner}</span></td>`;
      });
      html += `</tr></tbody></table>`;
      return html;
    }

    function renderMatrix2D(colAxis, rowAxis, baseFilter) {
      const valid = validAxes();
      // [2026-05-24 BUG FIX] validAxes() 새 배열 → 객체 참조 비교 실패 (-1)
      //   → 모든 셀이 같은 key → 셀 클릭 시 전체 토글되는 버그
      //   해결: 이름 기반 매칭
      const colIdx = valid.findIndex(a => a.name === colAxis.name);
      const rowIdx = valid.findIndex(a => a.name === rowAxis.name);

      let html = `<table class="oum-mtx-table"><thead><tr>
        <th class="corner" data-corner-axes='${esc(JSON.stringify(baseFilter))}'>⌐</th>`;
      colAxis.values.forEach(cv => {
        html += `<th class="oum-th-drag" draggable="true" data-col-axis="${esc(colAxis.name)}" data-col-val="${esc(cv)}" data-base='${esc(JSON.stringify(baseFilter))}' title="클릭=열 전체 토글 · 드래그=순서 변경">${esc(cv)}</th>`;
      });
      html += `</tr></thead><tbody>`;

      rowAxis.values.forEach(rv => {
        html += `<tr><th class="oum-th-drag" draggable="true" data-row-axis="${esc(rowAxis.name)}" data-row-val="${esc(rv)}" data-base='${esc(JSON.stringify(baseFilter))}' title="클릭=행 전체 토글 · 드래그=순서 변경">${esc(rv)}</th>`;
        colAxis.values.forEach(cv => {
          // 키 만들기 — base + col + row 조합
          const arr = new Array(valid.length);
          baseFilter.forEach(b => { arr[b.idx] = b.val; });
          arr[colIdx] = cv;
          arr[rowIdx] = rv;
          const k = keyOf(arr);
          const on = state.selected.has(k);
          // [2026-06-04 FIX] mappedOff 는 OFF 로 표시 (ON 은 selected 만).
          const hasInv = on && state.invMappedKeys && state.invMappedKeys.has(k);
          const s = cellState(on, false, hasInv);
          html += `<td><span class="oum-cell ${s.cls}" data-cell-key='${esc(k)}'>${s.inner}</span></td>`;
        });
        html += `</tr>`;
      });

      html += `</tbody></table>`;
      return html;
    }

    // [B3-3] 자동 매칭 — candidates(서버 alias 매칭) 결과 → invRows
    function invAutoMatch() {
      const skuByKey = state.skuByKey || {};
      [...state.selected].forEach(k => {
        const bSku = skuByKey[k];
        if (!bSku) return;
        const cands = state.invCandidates[bSku] || [];
        if (cands.length > 0) {
          const invSku = cands[0];
          const inv = (state.invOptions || []).find(o => o.sku === invSku);
          state.invRows[bSku] = {
            invSku: invSku,
            model: inv ? inv.model_name : '',
            color: inv ? inv.color : '',
            size: inv ? inv.size : '',
            isManual: false,
            isUnused: false,
          };
          state.invMappedKeys.add(k);
        }
      });
    }

    // [B3-3] 매핑 서버 저장 (POST /api/bundles/<code>/inventory-mapping)
    async function invApplyMapping(bundleCode) {
      const skuByKey = state.skuByKey || {};
      const mappings = {};
      [...state.selected].forEach(k => {
        const bSku = skuByKey[k];
        if (!bSku) return;
        const row = state.invRows[bSku];
        if (row && row.invSku && row.invSku.trim()) {
          mappings[bSku] = [row.invSku.trim()];
        }
      });
      try {
        const r = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/inventory-mapping`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mappings }),
        });
        const j = await r.json();
        if (j && j.ok) {
          alert('✅ 재고 매핑 저장 완료 — ' + (j.mapped || 0) + '건');
        } else {
          alert('❌ 저장 실패: ' + (j.error || '알 수 없음'));
        }
      } catch (err) {
        alert('❌ 요청 실패: ' + err.message);
      }
    }

    // [v20 2026-05-30] 재고관리 매핑 패널 — D4 통계 흡수 + 브랜드/모델 검색 + 그룹 details
    //   변경 사항:
    //     - 큰 통계 카드 3개 → renderRight 에서 탭 우측 인라인 흡수
    //     - 옵션축 박스 / "정리 기준" 박스 → 작은 액션바
    //     - "alias 자동매칭" → "⚡ 자동 매칭"
    //     - 그룹 details (첫 축 기준) + 행 색 3색 (auto/manual/empty)
    //     - 인라인 자동완성 (브랜드/모델 그룹 헤더)
    //     - 뱃지 한 줄 (white-space:nowrap + min-width)
    function renderInvPanel() {
      const selectedKeys = [...state.selected];
      const skuByKey = state.skuByKey || {};

      if (!state.applied) {
        return `<div style="padding:60px 20px; text-align:center; color:#9CA3AF; background:#fff; border:2px dashed #FBBF24; border-radius:8px;">
          <div style="font-size:32px; margin-bottom:10px;">⬅</div>
          <div style="font-size:13px; font-weight:600; color:#92400E;">좌측에서 옵션 만들고 [적용 →] 클릭하면 활성화</div>
        </div>`;
      }

      if (selectedKeys.length === 0) {
        return `<div style="padding:50px 20px;text-align:center;color:#9CA3AF;background:#fff;border:1px dashed #BBF7D0;border-radius:8px;font-size:13px">활성 옵션이 없습니다 — 좌측 매트릭스에서 옵션 ON 후 [적용 →]</div>`;
      }

      // 액션바 — 정리 + 브랜드/모델 + 자동매칭
      const valid = validAxes();
      const groupOpts = [];
      valid.forEach((ax, i) => {
        groupOpts.push({ key: 'axis-' + i, label: `축 ${i+1} (${ax.name || '이름없음'})별` });
      });
      groupOpts.push({ key: 'flat', label: '그룹화 X (평면)' });
      groupOpts.push({ key: 'status', label: '매핑 상태별' });
      const curGrp = groupOpts.find(g => g.key === state.invGroupBy) || groupOpts[0];

      // [v20.6] invFilter 그대로 사용 (bundle_meta 자동 추론 제거 — 초기엔 공란)
      const fb = state.invFilter.brand || '';
      const fm = state.invFilter.model || '';

      let html = '<div class="oum-inv-action">';
      html += '<div class="oum-inv-action-left">';
      html += '<span class="oum-inv-label">정리</span>';
      html += `<div class="oum-grp-dd"><button class="oum-grp-dd-btn" data-grp-toggle type="button">${esc(curGrp.label)}</button>`;
      html += `<div class="oum-grp-dd-menu" style="display:none">`;
      groupOpts.forEach(g => {
        html += `<div class="oum-grp-dd-it ${g.key === state.invGroupBy ? 'on' : ''}" data-grp-key="${esc(g.key)}">${esc(g.label)}</div>`;
      });
      html += `</div></div>`;
      html += '</div>';

      html += '<div class="oum-inv-action-right">';
      html += '<span class="oum-inv-label">매칭</span>';
      // 브랜드 검색
      html += `<div class="oum-br-search"><span class="ic">🏷️</span><input id="oum-br-in" type="text" placeholder="브랜드" value="${esc(fb)}" autocomplete="off">`;
      html += `<div class="oum-br-dd" style="display:none">`;
      (state.invBrands || []).forEach(b => {
        const on = b.name === fb;
        html += `<div class="oum-br-it ${on ? 'on' : ''}" data-br-name="${esc(b.name)}"><span class="swatch">${esc((b.name||'?').slice(0,2))}</span><span class="nm">${esc(b.name)}</span><span class="meta">${b.model_count} 모델 · ${b.option_count} 옵션</span></div>`;
      });
      if (fb) html += `<div class="oum-br-it" data-br-clear style="color:#9CA3AF"><span style="font-style:italic">필터 해제 (모든 브랜드)</span></div>`;
      html += `</div></div>`;
      html += `<span class="oum-step-arrow">→</span>`;
      // 모델 검색
      const modelsForBrand = (state.invModelsByBrand && fb) ? (state.invModelsByBrand[fb] || []) : [];
      const mdDisabled = !fb ? ' disabled' : '';
      html += `<div class="oum-md-search${mdDisabled ? ' disabled' : ''}"><span class="ic">🧩</span><input id="oum-md-in" type="text" placeholder="${fb ? '모델' : '브랜드 먼저'}" value="${esc(fm)}" autocomplete="off"${mdDisabled}>`;
      html += `<div class="oum-md-dd" style="display:none">`;
      if (fb) html += `<div class="oum-md-grp-h">🏷️ ${esc(fb)}</div>`;
      modelsForBrand.forEach(m => {
        const on = m.model_name === fm;
        html += `<div class="oum-md-it ${on ? 'on' : ''}" data-md-name="${esc(m.model_name)}"><span class="nm">${esc(m.model_name)}</span><span class="meta">${m.option_count} 옵션</span></div>`;
      });
      html += `</div></div>`;
      html += `<button class="oum-auto-btn-sm" data-inv-auto type="button">⚡ 자동 매칭</button>`;
      html += '</div>';
      html += '</div>';

      // 매칭 범위 안내 (얇게)
      if (fb && fm) {
        html += `<div class="oum-inv-filter-hint">🔎 매칭 범위: <b>${esc(fb)}</b> · <b>${esc(fm)}</b></div>`;
      }

      // 그룹화 + 표
      const groups = buildInvGroups(selectedKeys, skuByKey, valid);
      groups.forEach(g => {
        const cntCls = g.matchedN === g.total ? '' : (g.matchedN === 0 ? ' err' : ' warn');
        html += `<details class="oum-inv-grp" ${g.open ? 'open' : ''}>`;
        html += `<summary><span class="val">${esc(g.label)}</span><span class="cnt${cntCls}">${g.matchedN}/${g.total} 매핑</span></summary>`;
        // [v20.8 T1] 정렬 가능 컬럼 헤더 — 정렬 컬럼은 옅은 파란 배경 + ▲▼
        const sc = state.invSort && state.invSort.col || 'opt';
        const sd = state.invSort && state.invSort.dir || 'asc';
        const arr = (col) => sc === col ? (sd === 'asc' ? '▲' : '▼') : '⬍';
        const cls = (col) => sc === col ? 'sorted' : '';
        html += `<div class="oum-inv-sort-head">`;
        html += `<div class="oum-inv-sort-col col-opt ${cls('opt')}" data-inv-sort="opt">옵션값 <span class="arrow">${arr('opt')}</span></div>`;
        html += `<div class="oum-inv-sort-col col-prod ${cls('prod')}" data-inv-sort="prod">제품 정보 <span class="arrow">${arr('prod')}</span></div>`;
        html += `<div class="oum-inv-sort-col col-stat ${cls('status')}" data-inv-sort="status">상태 <span class="arrow">${arr('status')}</span></div>`;
        html += `</div>`;
        html += '<table class="oum-inv-tbl-new"><tbody>';
        g.rows.forEach(r => {
          const cls = r.cls;  // auto / manual / empty
          const opt = r.opt;
          const statHtml = r.status === 'auto'
            ? '<span class="oum-stat-pill auto">⚡ 자동</span>'
            : r.status === 'manual'
              ? '<span class="oum-stat-pill manual">✏️ 수기</span>'
              : '<span class="oum-stat-pill empty">❌ 미매핑</span>';
          html += `<tr class="${cls}" data-inv-row='${esc(r.key)}'>`;
          html += `<td class="oum-col-opt">${esc(r.optLabel)}</td>`;
          // [v20.4] 자동/수기 매핑 완료 (opt 있음) = 동일 양식 (모델명+색상+사이즈 + SKU)
          //         미매핑 = 검색 input
          if (opt) {
            // 수기 행에도 "다시 입력" 버튼 (data-inv-reedit) 제공 → 클릭 시 input 모드
            const reEdit = r.status === 'manual'
              ? `<button class="oum-row-reedit" data-inv-reedit='${esc(r.key)}' title="다시 입력" type="button">✎</button>`
              : '';
            html += `<td class="oum-col-prod"><div class="oum-prod-info"><span class="oum-prod-name">${esc(opt.model_name)} ${esc(opt.color)} ${esc(opt.size)} ${reEdit}</span><span class="oum-prod-meta">${esc(opt.sku)}</span></div></td>`;
          } else {
            const bSku = skuByKey[r.key];
            const row = (bSku && state.invRows[bSku]) || { invSku: '' };
            html += `<td class="oum-col-prod"><div class="oum-ac-wrap"><input class="oum-inv-search" data-inv-search-key='${esc(r.key)}' value="${esc(row.invSku || '')}" placeholder="🔍 SKU/제품명 검색..."></div></td>`;
          }
          html += `<td class="oum-col-stat">${statHtml}</td>`;
          html += '</tr>';
        });
        html += '</tbody></table>';
        html += '</details>';
      });

      // [v31] 적용 버튼 제거 — on/off 우측 패널 자동 반영. (foot div 통째 삭제)
      return html;
    }

    // [v20] 그룹화 빌더 — state.invGroupBy 기반 행 묶음
    function buildInvGroups(selectedKeys, skuByKey, valid) {
      const groupBy = state.invGroupBy || 'axis-0';
      // 키 → 행 정보
      const rows = selectedKeys.map(k => {
        const bSku = skuByKey[k];
        const row = (bSku && state.invRows[bSku]) || null;
        let status = 'empty', cls = 'empty', optMatched = null;
        if (row && row.invSku) {
          status = row.isManual ? 'manual' : 'auto';
          cls = status;
          optMatched = (state.invOptions || []).find(o => o.sku === row.invSku) || null;
        }
        // 축 값 파싱 (k = JSON stringified array)
        let arr = [];
        try { arr = JSON.parse(k); } catch (e) { arr = []; }
        const optLabel = arr.length === 1 ? String(arr[0])
                       : (arr.slice(1).map(String).join(' · ') || String(arr[0] || ''));
        const allLabel = arr.map(String).join(' · ');
        return { key: k, status, cls, opt: optMatched, axes: arr, optLabel, allLabel };
      });

      // [v20.8] 정렬 — col: 'opt'(옵션값) / 'prod'(제품명) / 'status'(자동→수기→미매핑)
      //   자연 정렬 (220, 240, 250 / S, M, L / SKU 등 적절히)
      const _statusOrder = { auto: 1, manual: 2, empty: 3 };
      function _sortRows(rs) {
        const { col, dir } = state.invSort || { col: 'opt', dir: 'asc' };
        const sign = dir === 'desc' ? -1 : 1;
        const cmp = (a, b) => {
          let ka, kb;
          if (col === 'status') { ka = _statusOrder[a.status] || 9; kb = _statusOrder[b.status] || 9; }
          else if (col === 'prod') {
            ka = a.opt ? `${a.opt.model_name} ${a.opt.color} ${a.opt.size}` : 'zzz';
            kb = b.opt ? `${b.opt.model_name} ${b.opt.color} ${b.opt.size}` : 'zzz';
            return sign * String(ka).localeCompare(String(kb), undefined, { numeric: true, sensitivity: 'base' });
          }
          else { ka = a.optLabel || ''; kb = b.optLabel || ''; return sign * String(ka).localeCompare(String(kb), undefined, { numeric: true, sensitivity: 'base' }); }
          if (ka === kb) return 0;
          return sign * (ka < kb ? -1 : 1);
        };
        return rs.slice().sort(cmp);
      }

      // 그룹화
      const groups = [];  // [{label, rows, total, matchedN, open}]
      const grpMap = new Map();
      if (groupBy === 'flat') {
        groups.push({ label: '전체', rows: _sortRows(rows), total: rows.length,
                      matchedN: rows.filter(r => r.status !== 'empty').length, open: true });
      } else if (groupBy === 'status') {
        const buckets = { auto: [], manual: [], empty: [] };
        rows.forEach(r => buckets[r.status].push(r));
        if (buckets.auto.length) groups.push({ label: '⚡ 자동 매칭', rows: _sortRows(buckets.auto), total: buckets.auto.length, matchedN: buckets.auto.length, open: false });
        if (buckets.manual.length) groups.push({ label: '✏️ 수기 입력', rows: _sortRows(buckets.manual), total: buckets.manual.length, matchedN: buckets.manual.length, open: true });
        if (buckets.empty.length) groups.push({ label: '❌ 미매핑', rows: _sortRows(buckets.empty), total: buckets.empty.length, matchedN: 0, open: true });
      } else {
        // axis-N
        const axisIdx = parseInt(String(groupBy).split('-')[1] || '0', 10) || 0;
        rows.forEach(r => {
          const gv = (r.axes[axisIdx] != null) ? String(r.axes[axisIdx]) : '(없음)';
          // 그룹 안 행 라벨 = 나머지 축 값
          const otherVals = r.axes.filter((_, i) => i !== axisIdx).map(String);
          const innerLabel = otherVals.join(' · ') || gv;
          if (!grpMap.has(gv)) grpMap.set(gv, []);
          grpMap.get(gv).push({ ...r, optLabel: innerLabel });
        });
        [...grpMap.entries()].forEach(([label, gRows]) => {
          const matchedN = gRows.filter(r => r.status !== 'empty').length;
          groups.push({ label, rows: _sortRows(gRows), total: gRows.length, matchedN, open: matchedN < gRows.length });
        });
      }
      return groups;
    }

    // ─── [2026-06-19 P4] URL 크롤링 검증 탭 — 소싱처별 수집·최종매입가·매칭 ───
    // [2026-06-20 재설계] 트리(소싱처▸URL) + 상세(2단·4케이스) + 배너(스택바·전체분류) + 실패정산.
    function _vTypeBadge(t) {
      // [2026-06-20 명칭변경] 단품 / 색상 모음전(mo) / 모델 모음전(deal)
      var b = 'font-size:10px;font-weight:800;border-radius:5px;padding:1px 4px;text-align:center;display:inline-block;width:72px;white-space:nowrap';
      if (t === 'deal') return '<span style="' + b + ';background:#FFE9EC;color:#D6334B">모델 모음전</span>';
      if (t === 'mo') return '<span style="' + b + ';background:#EEE9FF;color:#6B3FD4">색상 모음전</span>';
      return '<span style="' + b + ';background:#E3F1FF;color:#1B64DA">단품</span>';
    }
    function _vStatusMeta(st, stock_out) {
      if (st === 'ok') return { dot: '#16A34A', label: '매칭', cls: 'color:#16A34A;font-weight:800' };
      if (st === 'soldout') return { dot: '#DC2626', label: '품절', cls: 'color:#DC2626;font-weight:800' };
      if (st === 'absent') return { dot: '#94A3B8', label: '옵션없음 or 매핑실패', cls: 'color:#94A3B8;font-weight:800' };
      return { dot: '#DC2626', label: '가격없음', cls: 'color:#DC2626;font-weight:800' };
    }
    function renderVerifyPanel() {
      try {
        if (state.verifyLoading) return '<div style="padding:34px;text-align:center;color:#8B95A1;font-size:15px">🔍 검증 중… (URL별 수집 · 최종매입가 · 옵션 매칭 계산)</div>';
        const data = state.verifyData;
        if (!data) return '<div style="padding:34px;text-align:center;color:#8B95A1;font-size:15px">검증 데이터 로딩…</div>';
        if (data.error) return '<div style="padding:34px;text-align:center;color:#dc2626;font-size:15px">검증 실패: ' + esc(String(data.error)) + '</div>';
        const g = data.global || {};
        const srcs = data.sources || [];
        const fd = data.fail_detail || {};
        if (!state.verifyChecks) state.verifyChecks = {};
        const allUrls = [];
        srcs.forEach(function (ps) { (ps.urls || []).forEach(function (u) { allUrls.push(u); }); });
        let selUrl = state.verifySelUrl;
        if (!selUrl || !allUrls.some(function (u) { return u.product_url === selUrl; }))
          selUrl = allUrls.length ? allUrls[0].product_url : null;
        const sel = allUrls.find(function (u) { return u.product_url === selUrl; }) || null;
        const selCount = Object.keys(state.verifyChecks).filter(function (k) { return state.verifyChecks[k]; }).length;

        // ── 배너 (스택바 + 전체 URL 분류) ──
        const totp = g.total || 0, mp = g.matched || 0, ap = g.absent || 0, np = g.noprice || 0;
        const wM = totp ? (mp / totp * 100) : 0, wA = totp ? (ap / totp * 100) : 0, wN = totp ? (np / totp * 100) : 0;
        const failTrig = (ap || np)
          ? '<span data-verify-fail style="cursor:pointer;font-weight:800;color:' + (g.crawl_error_urls ? '#DC2626' : '#6B7684') + ';text-decoration:underline dotted">'
            + (g.crawl_error_urls ? ('크롤에러 URL ' + g.crawl_error_urls) : '실패 상세') + ' ' + (state.verifyFailOpen ? '▴' : '▾') + '</span>'
          : '';
        const banner =
          '<div style="display:flex;align-items:center;gap:20px;padding:14px 2px;border-top:1px solid #EAEDF1;border-bottom:1px solid #EAEDF1;margin-bottom:14px">' +
            '<div style="display:flex;flex-direction:column"><div style="font-size:14px;font-weight:800;color:#16A34A">' + esc(g.min_final_source || '—') + '</div>' +
            '<div style="font-size:15px;color:#8B95A1;font-weight:700">전체 최저 최종매입가</div>' +
            '<div style="font-size:23px;font-weight:900;font-family:monospace;color:#1B64DA;line-height:1.25">' + (g.min_final ? g.min_final.toLocaleString() + '원' : '—') + '</div></div>' +
            '<div style="width:1px;height:46px;background:#EAEDF1"></div>' +
            '<div style="display:flex;flex-direction:column">' +
              '<div style="font-size:15px;color:#8B95A1;font-weight:700">검증 결과 (전체 URL · <b style="color:#16A34A">성공 ' + (g.success_rate || 0) + '%</b>)</div>' +
              '<div style="display:flex;height:11px;border-radius:999px;overflow:hidden;width:240px;margin:5px 0;background:#EEF1F5">' +
                '<i style="display:block;height:100%;width:' + wM + '%;background:#16A34A"></i>' +
                '<i style="display:block;height:100%;width:' + wA + '%;background:#94A3B8"></i>' +
                '<i style="display:block;height:100%;width:' + wN + '%;background:#DC2626"></i></div>' +
              '<div style="font-size:16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center">' +
                '<span style="color:#16A34A;font-weight:800">● 매칭 ' + mp + '</span>' +
                '<span style="color:#94A3B8;font-weight:800">● 옵션없음 or 매핑실패 ' + ap + '</span>' +
                '<span style="color:#DC2626;font-weight:800">● 가격없음 ' + np + '</span>' + failTrig + '</div></div>' +
            '<div style="margin-left:auto;display:flex;flex-direction:column;align-items:stretch;gap:6px">' +
              '<div id="v-recrawl-card" style="' + (state.vcrawl ? '' : 'display:none') + '">' + _vcrawlCardHtml() + '</div>' +
              '<div style="display:flex;gap:8px;justify-content:flex-end">' +
                '<button data-verify-refresh-sel type="button" style="background:#fff;color:#4E5968;border:1px solid #D1D6DB;border-radius:8px;padding:8px 12px;font-weight:700;font-size:13px;cursor:pointer">↻ 선택 URL 재검증' + (selCount ? ' (' + selCount + ')' : '') + '</button>' +
                '<button data-verify-refresh type="button" style="background:#7C3AED;color:#fff;border:0;border-radius:8px;padding:8px 13px;font-weight:700;font-size:13px;cursor:pointer">🔍 전체 재검증</button>' +
              '</div>' +
            '</div>' +
          '</div>';

        // ── 실패 정산 (분류 그룹 2열) ──
        let failPanel = '';
        if (state.verifyFailOpen) {
          // [2026-06-20] 소싱처 배지(고정폭 정렬) + 숫자 클릭 시 해당 옵션 인라인 펼침
          if (!state.verifyFailExpand) state.verifyFailExpand = {};
          const _failCol = function (urls, key) {
            const numColor = key === 'absent' ? '#94A3B8' : '#DC2626';
            const rows = urls.map(function (u) {
              const cnt = key === 'absent' ? u.absent : u.noprice;
              if (!cnt) return '';
              const ekey = (u.product_url || '') + '|' + key;
              const expanded = !!state.verifyFailExpand[ekey];
              let chips = '';
              if (expanded) {
                const opts = (u.options || []).filter(function (o) { return o.status === key; });
                const shown = opts.slice(0, 80).map(function (o) {
                  return '<span style="display:inline-block;font-size:13px;font-weight:700;background:#EEF1F5;color:#5B6573;border-radius:6px;padding:3px 9px;margin:2px">' + esc((o.color || '') + ' ' + (o.size == null ? '' : o.size)) + '</span>';
                }).join('');
                const more = opts.length > 80 ? '<span style="font-size:11px;color:#8B95A1;margin-left:4px">+' + (opts.length - 80) + '</span>' : '';
                chips = '<div style="padding:2px 12px 10px;background:#FAFBFC">' + shown + more + '</div>';
              }
              return '<div style="display:grid;grid-template-columns:64px 1fr 50px;gap:8px;align-items:center;padding:9px 12px;border-bottom:1px solid #F2F4F6;font-size:14px">' +
                '<span style="font-size:12px;font-weight:800;border-radius:5px;padding:2px 4px;text-align:center;background:#EAF1FB;color:#1B64DA;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(u.source_name || '') + '">' + esc(u.source_name || '?') + '</span>' +
                '<a href="' + esc(u.product_url || '#') + '" target="_blank" rel="noopener" title="URL 직접 확인" style="font-weight:600;color:#191F28;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left">' + esc(u.product_name || '(이름없음)') + (u.crawl_error ? ' <span style="color:#D6334B;font-weight:800">·크롤실패</span>' : '') + '</a>' +
                '<span data-fail-exp="' + esc(ekey) + '" style="text-align:right;font-weight:800;color:' + numColor + ';cursor:pointer;text-decoration:underline">' + cnt + (expanded ? ' ▾' : ' ▸') + '</span></div>' + chips;
            }).join('');
            return rows || '<div style="padding:10px 12px;color:#C0C6CE;font-size:12px">없음</div>';
          };
          const absRows = _failCol(allUrls.filter(function (u) { return u.absent; }).sort(function (a, b) { return b.absent - a.absent; }), 'absent');
          const noRows = _failCol(allUrls.filter(function (u) { return u.noprice; }).sort(function (a, b) { return b.noprice - a.noprice; }), 'noprice');
          failPanel =
            '<div style="border:1px solid #F0D7D7;background:#FFFAFA;border-radius:12px;padding:14px 16px;margin-bottom:14px">' +
              '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
                '<div style="border:1px solid #EAEDF1;border-radius:10px;overflow:hidden">' +
                  '<div style="padding:9px 12px;font-weight:800;font-size:12px;background:#F4F6F8;display:flex;align-items:center;gap:7px;border-bottom:1px solid #EAEDF1"><span style="width:8px;height:8px;border-radius:50%;background:#94A3B8;display:inline-block"></span>옵션없음 or 매핑실패<span style="margin-left:auto;color:#94A3B8">' + (fd.absent_total || 0) + '</span></div>' + absRows + '</div>' +
                '<div style="border:1px solid #EAEDF1;border-radius:10px;overflow:hidden">' +
                  '<div style="padding:9px 12px;font-weight:800;font-size:12px;background:#FFF4F4;color:#B23B3B;display:flex;align-items:center;gap:7px;border-bottom:1px solid #EAEDF1"><span style="width:8px;height:8px;border-radius:50%;background:#DC2626;display:inline-block"></span>가격없음<span style="margin-left:auto;color:#DC2626">' + (fd.noprice_total || 0) + '</span></div>' + noRows + '</div>' +
              '</div><div style="margin-top:8px;font-size:11px;color:#16A34A;font-weight:700">✓ 옵션없음 ' + (fd.absent_total || 0) + ' + 가격없음 ' + (fd.noprice_total || 0) + ' = 검증결과 합계와 일치 · 상품명 클릭 = URL 직접 확인 · 숫자 클릭 = 옵션 펼침</div></div>';
        }

        // ── 트리 ──
        let tree = '';
        srcs.forEach(function (ps) {
          tree += '<div style="font-size:15px;font-weight:800;color:#8B95A1;padding:14px 8px 4px;border-top:1px solid #F2F4F6">' + esc(ps.name) + ' — 최저 ' + (ps.min_final ? ps.min_final.toLocaleString() : '—') + ' · ' + (ps.success_rate || 0) + '%</div>';
          (ps.urls || []).forEach(function (u) {
            const on = u.product_url === selUrl;
            const cntColor = u.needs_model ? '#A66A00' : ((u.crawl_error || u.noprice) ? '#DC2626' : (u.absent ? '#94A3B8' : '#16A34A'));
            const cntTxt = u.needs_model ? '모델선택 필요' : (u.crawl_error ? '실패' : ('✓' + u.matched));
            const need = (u.type === 'deal') ? '<span style="font-size:10px;font-weight:800;border-radius:5px;padding:1px 6px;background:#FFF1D6;color:#A66A00">🧩 모델</span>' : '';
            tree += '<div data-vurl="' + esc(u.product_url) + '" style="display:grid;grid-template-columns:18px 72px 1fr auto;align-items:center;gap:8px;padding:8px;border-radius:7px;cursor:pointer;' + (on ? 'background:#E8F1FF' : '') + '">' +
              '<input type="checkbox" data-vcheck="' + esc(u.product_url) + '" ' + (state.verifyChecks[u.product_url] ? 'checked' : '') + ' style="width:15px;height:15px;accent-color:#1B64DA">' +
              _vTypeBadge(u.type) +
              '<span style="font-size:18px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left">' + esc(u.product_name || '(이름없음)') + '</span>' +
              '<span style="display:flex;align-items:center;gap:7px;justify-content:flex-end">' + need + '<span style="font-size:15px;font-weight:800;color:' + cntColor + '">' + cntTxt + '</span></span></div>';
          });
        });

        // ── 상세 ──
        let detail;
        if (!sel) {
          detail = '<div style="padding:34px;text-align:center;color:#8B95A1;font-size:14px">좌측에서 URL을 선택하세요</div>';
        } else {
          const tyName = sel.type === 'mo' ? '색상 모음전' : (sel.type === 'deal' ? '모델 모음전' : '단품');
          const optRows = (sel.options || []).slice(0, 400).map(function (o) {
            const m = _vStatusMeta(o.status, o.stock_out);
            const blank = (o.status === 'absent');
            const fin = o.final ? o.final.toLocaleString() : (o.status === 'noprice' ? '— (혜택 미수집)' : '—');
            return '<tr' + (o.status === 'absent' ? ' style="background:#FBFCFE"' : (o.status === 'noprice' ? ' style="background:#FFFCF6"' : '')) + '>' +
              '<td style="padding:8px;border-bottom:1px solid #F2F4F6;font-weight:700">' + esc((o.color || '') + ' ' + (o.size == null ? '' : o.size)) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #F2F4F6"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:' + m.dot + ';margin-right:4px"></span><span style="' + m.cls + '">' + m.label + '</span></td>' +
              '<td style="padding:8px;border-bottom:1px solid #F2F4F6;font-size:13px;color:' + (blank ? '#C0C6CE' : '#4E5968') + '">' + esc(blank ? '—' : (o.url_product_name || '—')) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #F2F4F6;font-family:monospace;font-size:13px;color:' + (blank ? '#C0C6CE' : '#4E5968') + '">' + esc(blank ? '—' : (o.url_option || '—')) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #F2F4F6;text-align:center">' + (blank ? '<span style="color:#C0C6CE">—</span>' : (o.stock_out ? '<span style="color:#DC2626;font-weight:700">' + esc(o.stock_label || '품절') + '</span>' : '<span style="color:#16A34A;font-weight:700">' + esc(o.stock_label || '재고있음') + '</span>')) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #F2F4F6;text-align:right;text-decoration:' + (blank ? 'none' : 'line-through') + ';color:#94A3B8;font-family:monospace">' + (o.surface ? o.surface.toLocaleString() : '—') + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #F2F4F6;text-align:right;font-family:monospace;font-weight:800;color:' + (o.final ? '#1B64DA' : '#C0C6CE') + '">' + fin + '</td></tr>';
          }).join('');
          detail =
            '<div style="display:flex;align-items:center;gap:10px">' + _vTypeBadge(sel.type) +
              '<a href="' + esc(sel.product_url || '#') + '" target="_blank" rel="noopener" title="URL 직접 확인" style="font-size:15px;font-weight:800;color:#191F28;text-decoration:none">' + esc(sel.product_name || '(이름없음)') + ' 🔗</a>' +
              '<button data-verify-refresh-one="' + esc(sel.product_url) + '" type="button" style="margin-left:auto;background:#fff;color:#4E5968;border:1px solid #D1D6DB;border-radius:8px;padding:5px 10px;font-weight:700;font-size:11px;cursor:pointer">🔍 해당 ' + tyName + '만 재검증</button></div>' +
            '<div style="font-family:monospace;font-size:11px;color:#8B95A1;margin:4px 0 14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(sel.product_url || '') + '</div>' +
            '<div style="height:1px;background:#EAEDF1;margin:14px 0"></div>' +
            '<div style="display:flex;align-items:stretch;margin-bottom:10px">' +
              '<div style="flex:1"><div style="font-size:13px;font-weight:800;color:#8B95A1;margin-bottom:8px">검증 결과</div>' +
                '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:8px"><span style="font-size:21px;font-weight:900;color:#16A34A">' + (sel.success_rate || 0) + '%</span><span style="font-size:13px;color:#8B95A1">옵션 크롤 성공률 (' + (sel.matched || 0) + ' / ' + (sel.total || 0) + ' · 품절 포함)</span></div>' +
                '<div style="display:flex;gap:16px;font-size:17px;flex-wrap:wrap"><span style="color:#16A34A">● 매칭 ' + (sel.matched || 0) + '</span><span style="color:#94A3B8">● 옵션없음 or 매핑실패 ' + (sel.absent || 0) + '</span><span style="color:#DC2626">● 가격없음 ' + (sel.noprice || 0) + '</span></div></div>' +
              '<div style="width:1px;background:#EAEDF1;margin:0 14px"></div>' +
              '<div style="flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center"><div style="font-size:13px;font-weight:800;color:#8B95A1">URL 최저 최종매입가</div><div style="font-size:26px;font-weight:900;font-family:monospace;color:#1B64DA;margin-top:3px">' + (sel.min_final ? sel.min_final.toLocaleString() + '원' : '—') + '</div></div></div>' +
            '<div style="height:1px;background:#EAEDF1;margin:14px 0"></div>' +
            '<table style="width:100%;border-collapse:collapse;font-size:18px">' +
              '<thead><tr style="color:#8B95A1;font-size:15px;background:#FAFBFC"><td style="padding:7px 8px;border-bottom:1.5px solid #EAEDF1">옵션(우리 지정)</td><td style="padding:7px 8px;border-bottom:1.5px solid #EAEDF1">상태</td><td style="padding:7px 8px;border-bottom:1.5px solid #EAEDF1">URL 상품명</td><td style="padding:7px 8px;border-bottom:1.5px solid #EAEDF1">URL옵션</td><td style="padding:7px 8px;border-bottom:1.5px solid #EAEDF1;text-align:center">재고</td><td style="padding:7px 8px;border-bottom:1.5px solid #EAEDF1;text-align:right">표면노출가</td><td style="padding:7px 8px;border-bottom:1.5px solid #EAEDF1;text-align:right">최종매입가</td></tr></thead><tbody>' +
              optRows + '</tbody></table>';
        }

        return '<div style="padding:2px 2px 16px">' + banner + failPanel +
          '<div style="display:grid;grid-template-columns:360px 1fr;border:1px solid #EAEDF1;border-radius:12px;overflow:hidden;min-height:480px">' +
          '<div id="v-tree" style="padding:10px;overflow:auto;max-height:600px;border-right:1px solid #EAEDF1">' + tree + '</div>' +
          '<div style="padding:14px 20px;overflow:auto;max-height:600px">' + detail + '</div></div></div>';
      } catch (e) {
        return '<div style="padding:22px;color:#dc2626">검증 패널 오류: ' + esc(String((e && e.message) || e)) + '</div>';
      }
    }
    async function loadVerifyData() {
      state.verifyLoading = true;
      try {
        const code = window.BUNDLE_CODE || window.currentBundleCode || '';
        const r = await fetch('/api/bundles/' + encodeURIComponent(code) + '/verify-urls',
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const j = await r.json();
        state.verifyData = j.ok ? j : { error: (j.error || ('HTTP ' + r.status)) };
      } catch (e) {
        state.verifyData = { error: String((e && e.message) || e) };
      }
      state.verifyLoading = false;
      if (state.rightTab === 'verify') renderRight();
    }

    // ─── [2026-06-20] 재검증 = 실제 재크롤 + 미니 토스트(일시중지/중지/시작) ───
    function _vUrlSourceKey(url) {
      const u = (url || '').toLowerCase();
      if (u.includes('smartstore.naver') || u.includes('naver.com')) return 'ss_lemouton';
      if (u.includes('lemouton')) return 'lemouton';
      if (u.includes('musinsa')) return 'musinsa';
      if (u.includes('ssfshop')) return 'ssf';
      if (u.includes('lotteon')) return 'lotteon';
      if (u.includes('ssg.com')) return 'ssg';
      return null;
    }
    function _vAllUrls() {
      const d = state.verifyData;
      if (!d || !d.sources) return [];
      const out = [];
      d.sources.forEach(function (ps) { (ps.urls || []).forEach(function (u) { out.push(u); }); });
      return out;
    }
    function _vDonut(pct, color) {
      return '<svg width="30" height="30" viewBox="0 0 36 36"><circle cx="18" cy="18" r="15" fill="none" stroke="#EEF1F5" stroke-width="5"/>' +
        '<circle cx="18" cy="18" r="15" fill="none" stroke="' + color + '" stroke-width="5" pathLength="100" stroke-dasharray="' + pct + ' 100" stroke-linecap="round" transform="rotate(-90 18 18)"/></svg>';
    }
    // [2026-06-20 시안3] 크롤 현황 = 검증 버튼 '위' 카드(버튼 행과 같은 폭, 왼쪽 라인 정렬).
    function _vcrawlCardHtml() {
      const vc = state.vcrawl;
      if (!vc) return '';
      const pct = vc.total ? Math.round(vc.done / vc.total * 100) : 0;
      const card = 'display:flex;align-items:center;gap:10px;border-radius:10px;padding:8px 12px;overflow:hidden';
      const ic = 'border-radius:7px;padding:5px 9px;font-size:13px;font-weight:800;cursor:pointer;flex:none;line-height:1';
      const bGh = ic + ';background:#fff;color:#4E5968;border:1px solid #D1D6DB';
      const bStop = ic + ';background:#fff;color:#DC2626;border:1px solid #F2C0C0';
      const bGo = ic + ';background:#16A34A;color:#fff;border:0';
      const bP = ic + ';background:#7C3AED;color:#fff;border:0;padding:5px 12px';
      if (vc.running && !vc.paused) {
        return '<div style="' + card + ';background:#F4F0FF;border:1px solid #E2D6FB">' + _vDonut(pct, '#1B64DA') +
          '<div style="flex:1;min-width:0"><div style="font-size:14px;font-weight:800;color:#5B2BC4">검증 재크롤 ' + pct + '%</div><div style="font-size:12px;color:#8B95A1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + vc.done + '/' + vc.total + (vc.cur ? ' · ' + esc(String(vc.cur)) : '') + '</div></div>' +
          '<button data-vc-pause title="일시중지" style="' + bGh + '">⏸</button><button data-vc-stop title="중지" style="' + bStop + '">■</button></div>';
      } else if (vc.running && vc.paused) {
        return '<div style="' + card + ';background:#FFFBF2;border:1px solid #F0DDB0">' + _vDonut(pct, '#C9A14A') +
          '<div style="flex:1;min-width:0"><div style="font-size:14px;font-weight:800;color:#A66A00">일시정지됨 ' + pct + '%</div><div style="font-size:12px;color:#8B95A1">' + vc.done + '/' + vc.total + ' · 멈춤</div></div>' +
          '<button data-vc-resume title="시작" style="' + bGo + '">▶</button><button data-vc-stop title="중지" style="' + bStop + '">■</button></div>';
      }
      const stopped = vc.stopped;
      return '<div style="' + card + ';background:' + (stopped ? '#FFF6F6;border:1px solid #F2C0C0' : '#F4FBF6;border:1px solid #BfE3C9') + '">' +
        '<span style="font-size:20px;font-weight:900;color:' + (stopped ? '#DC2626' : '#16A34A') + ';flex:none">' + (stopped ? '■' : '✓') + '</span>' +
        '<div style="flex:1;min-width:0"><div style="font-size:14px;font-weight:800;color:' + (stopped ? '#B23B3B' : '#1A7F37') + '">' + (stopped ? '재크롤 중지됨' : '검증 재크롤 완료') + '</div>' +
        '<div style="font-size:12px;color:#8B95A1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">성공 ' + vc.ok + ' · 실패 ' + vc.fail + (vc.ext ? ' · 확장필요 ' + vc.ext : '') + '</div></div>' +
        '<button data-vc-close title="닫기" style="' + bP + '">닫기</button></div>';
    }
    function renderVcrawlToast() {
      const el = document.getElementById('v-recrawl-card');
      if (!el) return;  // 검증 탭 카드 슬롯이 없으면(다른 탭) 갱신 생략 — 크롤은 계속
      el.style.display = state.vcrawl ? '' : 'none';
      el.innerHTML = _vcrawlCardHtml();
      // 카드 폭 = 버튼 행 폭(왼쪽=선택재검증 좌측라인, 오른쪽=전체재검증 우측라인 정렬)
      if (state.vcrawl) {
        const row = el.nextElementSibling;  // 버튼 행
        if (row) el.style.width = row.offsetWidth + 'px';
      } else {
        el.style.width = '';
      }
    }
    async function startVerifyRecrawl(urls, label) {
      urls = (urls || []).filter(function (u) { return u && u.product_url; });
      if (!urls.length) { alert('재크롤할 URL이 없습니다.'); return; }
      if (state.vcrawl && state.vcrawl.running) return;  // 이미 진행 중
      const code = window.BUNDLE_CODE || window.currentBundleCode || '';
      const extOk = !!(window.MoumExt && window.MoumExt.installed && window.MoumExt.installed());

      if (extOk && window.MoumExt.crawlUrls) {
        // === 로컬 PC 창 크롤(전체 크롤과 동일 추출, 창 뜸). 선택 URL만. HTTP·무신사·롯데온 전부 ===
        state.vcrawl = { running: true, paused: false, stopped: false, mode: 'win', total: urls.length, done: 0, ok: 0, fail: 0, ext: 0, label: label || '', cur: '' };
        renderVcrawlToast();
        const urlList = urls.map(function (u) { return { source_key: _vUrlSourceKey(u.product_url), url: u.product_url }; })
          .filter(function (x) { return x.source_key && x.url; });
        const onLog = function (ev) {
          const d = ev.detail || {}; const m = d.metrics;
          if (m && typeof m.total === 'number') { state.vcrawl.total = m.total; state.vcrawl.done = (typeof m.done === 'number' ? m.done : state.vcrawl.done); }
          if (d.source) state.vcrawl.cur = String(d.source);
          renderVcrawlToast();
        };
        window.addEventListener('moum-crawl-log', onLog);
        try {
          const r = await window.MoumExt.crawlUrls(code, urlList, {
            shouldStop: function () { return !!state.vcrawl.stopped; },
            shouldPause: function () { return !!state.vcrawl.paused; },
          }).catch(function (e) { return { ok: false, error: String(e) }; });
          state.vcrawl.ok = (r && r.ok_count) || 0;
          state.vcrawl.fail = Math.max(0, ((r && r.crawled) || 0) - ((r && r.ok_count) || 0));
        } catch (e) { /* noop */ }
        window.removeEventListener('moum-crawl-log', onLog);
      } else {
        // === 확장 없음 — 서버 per-URL 크롤(HTTP만, 무신사·롯데온은 '확장필요') ===
        state.vcrawl = { running: true, paused: false, stopped: false, mode: 'url', total: urls.length, done: 0, ok: 0, fail: 0, ext: 0, label: label || '', cur: '' };
        renderVcrawlToast();
        for (let i = 0; i < urls.length; i++) {
          if (state.vcrawl.stopped) break;
          while (state.vcrawl.paused && !state.vcrawl.stopped) { await new Promise(function (r) { setTimeout(r, 300); }); }
          if (state.vcrawl.stopped) break;
          const u = urls[i];
          const sk = _vUrlSourceKey(u.product_url);
          state.vcrawl.cur = u.product_name || u.source_name || '';
          renderVcrawlToast();
          if (!sk) { state.vcrawl.fail++; state.vcrawl.done++; renderVcrawlToast(); continue; }
          if (sk === 'musinsa' || sk === 'lotteon') { state.vcrawl.ext++; state.vcrawl.done++; renderVcrawlToast(); continue; }
          try {
            const _ctrl = new AbortController();
            state.vcrawl._abort = _ctrl;
            const j = await fetch('/api/bundles/' + encodeURIComponent(code) + '/recrawl-url',
              { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_key: sk, url: u.product_url }), signal: _ctrl.signal })
              .then(function (r) { return r.json(); }).catch(function (e) { return { ok: false, _aborted: (e && e.name === 'AbortError') }; });
            if (j && j._aborted) { break; }
            if (j && j.crawl_ok) state.vcrawl.ok++;
            else if (j && j.status === 'need_extension') state.vcrawl.ext++;
            else state.vcrawl.fail++;
          } catch (e) { state.vcrawl.fail++; }
          state.vcrawl.done++;
          renderVcrawlToast();
        }
      }
      state.vcrawl.running = false;
      renderVcrawlToast();
      // 결과 반영 — 검증 데이터 재계산
      state.verifyData = null;
      if (state.rightTab === 'verify') renderRight();
      loadVerifyData();
    }
    // 토스트 제어(일시중지/시작/중지/닫기) — 1회 위임 바인딩. full 모드는 MoumExt 엔진 제어로 위임.
    if (!window.__vcToastBound) {
      window.__vcToastBound = true;
      document.addEventListener('click', function (ev) {
        const vc = state.vcrawl;
        if (!vc) return;
        const full = vc.mode === 'full';
        const M = window.MoumExt || {};
        if (ev.target.closest('[data-vc-pause]')) { vc.paused = true; if (full && M.pauseCrawl) try { M.pauseCrawl(); } catch (e) {} renderVcrawlToast(); }
        else if (ev.target.closest('[data-vc-resume]')) { vc.paused = false; if (full && M.resumeCrawl) try { M.resumeCrawl(); } catch (e) {} renderVcrawlToast(); }
        else if (ev.target.closest('[data-vc-stop]')) {
          vc.stopped = true; vc.running = false;
          if (full && M.stopCrawl) { try { M.stopCrawl(); } catch (e) {} }
          if (vc._abort) { try { vc._abort.abort(); } catch (e) {} }  // 진행 중 per-URL 요청 즉시 중단
          renderVcrawlToast();
        }
        else if (ev.target.closest('[data-vc-close]')) { state.vcrawl = null; renderVcrawlToast(); }
      });
    }

    // ─── 우측 렌더 (시안 v3 C3 — 2탭 분기) ───
    function renderRight() {
      const right = $('#oum-right');
      const totalActive = state.selected.size;
      const urlCount = countAllUrls();
      const invCount = Object.keys(state.invRows || {}).filter(k => (state.invRows[k] || {}).invSku).length;

      // [v20 D4] 재고 탭 통계 흡수 — 자동/수기/미매핑 카운트
      let invAuto = 0, invManual = 0, invEmpty = 0;
      if (state.rightTab === 'inv') {
        const skuByKey0 = state.skuByKey || {};
        [...state.selected].forEach(k => {
          const bSku = skuByKey0[k];
          const row = (bSku && state.invRows[bSku]) || null;
          if (!row || !row.invSku) invEmpty++;
          else if (row.isManual) invManual++;
          else invAuto++;
        });
      }
      const invStatsHtml = state.rightTab === 'inv'
        ? `<div class="oum-rt-stats"><span class="ok">자동 <b>${invAuto}</b></span><span class="sep">·</span><span class="wn">수기 <b>${invManual}</b></span><span class="sep">·</span><span class="er">미매핑 <b>${invEmpty}</b></span></div>`
        : '';

      // 탭 nav (항상)
      let html = `<div class="oum-rt-tabs">
        <button class="oum-rt-tab ${state.rightTab === 'url' ? 'on' : ''}" data-rt-tab="url" type="button">📍 소싱처 URL 매핑 <span class="cnt">${urlCount}</span></button>
        <button class="oum-rt-tab ${state.rightTab === 'inv' ? 'on' : ''}" data-rt-tab="inv" type="button">📋 재고관리 매핑 <span class="cnt">${invCount}</span></button>
        <button class="oum-rt-tab ${state.rightTab === 'verify' ? 'on' : ''}" data-rt-tab="verify" type="button" style="${state.rightTab === 'verify' ? 'color:#7c3aed;border-bottom-color:#7c3aed' : ''}">🔍 크롤링 검증</button>
        ${invStatsHtml}
      </div>`;

      if (state.rightTab === 'inv') {
        html += renderInvPanel();
        right.innerHTML = html;
        return;
      }

      if (state.rightTab === 'verify') {
        // [2026-06-20] 트리 스크롤 보존 — URL행/체크박스/실패펼침 등 모든 재렌더에서 위로 안 튀게.
        const _trOld = document.getElementById('v-tree');
        const _savedScroll = _trOld ? _trOld.scrollTop : null;
        html += renderVerifyPanel();
        right.innerHTML = html;
        if (_savedScroll != null) { const _trNew = document.getElementById('v-tree'); if (_trNew) _trNew.scrollTop = _savedScroll; }
        if (state.vcrawl) renderVcrawlToast();  // 카드 폭=버튼 행 동기화
        if (!state.verifyData && !state.verifyLoading) loadVerifyData();
        return;
      }

      // [2026-06-13] 등록 URL 수 ≠ 실제 크롤 수 경고 배너 (시안 A).
      //   크롤 제외 사유 2가지: ① 같은 주소 중복(dedup, 1번만 크롤)
      //   ② SSG 딜·기획전 URL(last_status='covered' — 색상별 단품이 가격·재고 커버, 크롤 제외).
      //   실제 크롤 = 등록 - 중복분 - covered. 차이를 사유별로 표면화한다.
      const _dupGroups = findDuplicateUrls();
      const _coveredUrls = [];
      Object.keys(state.urls || {}).forEach(sk => {
        (state.urls[sk] || []).forEach(u => {
          const _isDeal = (u.lastStatus === 'covered') ||
            (sk === 'ssg' && (u.url || '').toLowerCase().includes('dealitemview'));
          if (_isDeal) _coveredUrls.push({ srcKey: sk, label: (u.label || '').trim() });
        });
      });
      const _dupExtra = _dupGroups.reduce((n, g) => n + (g.entries.length - 1), 0);
      const _reg = urlCount;
      const _crawl = _reg - _dupExtra - _coveredUrls.length;
      if (_dupExtra > 0 || _coveredUrls.length > 0) {
        const _hasCross = _dupGroups.some(g => g.crossOption);
        let _items = _dupGroups.map(g => {
          const _lab = SRC_LABELS[g.srcKey] || g.srcKey;
          const _names = g.entries.map(en => esc(en.label || '(라벨 없음)')).join(' ＝ ');
          const _cr = g.crossOption ? ` <em>⚠ 다른 옵션끼리 — 오타 의심</em>` : '';
          return `<button class="oum-dupwarn-item${g.crossOption ? ' cross' : ''}" data-dupjump="${esc(g.srcKey)}" type="button">🔗 [${esc(_lab)}] ${_names}${_cr} <span class="oum-dupwarn-why">같은 주소 — 1번만 크롤</span></button>`;
        }).join('');
        _items += _coveredUrls.map(d => {
          const _lab = SRC_LABELS[d.srcKey] || d.srcKey;
          return `<button class="oum-dupwarn-item covered" data-dupjump="${esc(d.srcKey)}" type="button">📌 [${esc(_lab)}] ${esc(d.label || '(라벨 없음)')} <span class="oum-dupwarn-why">딜·기획전 — 단품이 커버, 크롤 제외</span></button>`;
        }).join('');
        html += `<div class="oum-dupwarn${_hasCross ? ' cross' : ''}" data-dupwarn>
          <div class="oum-dupwarn-h">⚠ 등록 <b>${_reg}개</b> ≠ 실제 크롤 <b>${_crawl}개</b> — 아래 <b>${_reg - _crawl}건</b>이 크롤에서 빠집니다 (클릭 시 해당 소싱처로 이동)</div>
          <div class="oum-dupwarn-list">${_items}</div>
        </div>`;
      }

      // URL 탭 — 기존 헤더 + 적용 가드
      html += `<div class="oum-ph">
        <span>📍</span><span>소싱처 URL 매핑</span>
        <span class="badge">${urlCount} URL</span>
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
          <span class="lg" style="background:${color};">${SRC_ABBR[src.key] || abbr(label)}</span>
          <span class="full">${esc(label)}</span>
          <span class="cnt">${cnt}</span>
        </button>`;
      });
      html += `</div>`;

      // 현재 탭 URL 카드 리스트
      const srcLabel = SRC_LABELS[state.currentSrc] || state.currentSrc;
      const arr = state.urls[state.currentSrc] || [];

      // [2026-06-11] 크롤 실패 요약 배너 — "어떤 URL이 왜 실패했는지" 한눈에.
      //   대시보드 "URL N개 실패" 와 동일 기준(crawled===false). 아래 빨강 카드와 1:1 대응.
      const _failArr = arr.filter(u => u.crawled === false);
      if (_failArr.length) {
        const _items = _failArr.map(u => {
          const _reason = u.lastStatus === 'error' ? '응답 오류'
            : (u.lastStatus === 'not_crawled' ? '미크롤' : (u.lastStatus || '실패'));
          let _nm = (u.label && u.label.trim()) || (u.url || '');
          if (_nm.length > 38) _nm = _nm.slice(0, 38) + '…';
          return `<span class="oum-failsum-item">${esc(_nm)} <em>(${esc(_reason)})</em></span>`;
        }).join('');
        html += `<div class="oum-failsum" data-failsum>
          <div class="oum-failsum-h">⚠ ${esc(srcLabel)} URL ${_failArr.length}개 크롤 실패 — 가격·재고를 못 받았어요 <button class="oum-failsum-jump" data-failsum-jump type="button">↓ 실패 URL로 이동</button></div>
          <div class="oum-failsum-list">${_items}</div>
        </div>`;
      }

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

    // [2026-06-13] 등록 URL 중복 검사 — 같은 주소(정규화 후)를 2번 이상 등록한 그룹 반환.
    //   크롤 경로(ext_bridge.crawlBundle)는 seen=Set 으로 같은 URL 1번만 크롤 →
    //   같은 주소 N번 등록 시 '등록 수 > 실제 크롤 수'. 어떤 URL이 왜 다른지 표면화.
    //   crossOption=두 중복이 '서로 다른 옵션 집합'에 매핑(겹침<50%) → 색상 오타 의심.
    function findDuplicateUrls() {
      const byUrl = {};
      Object.keys(state.urls || {}).forEach(sk => {
        (state.urls[sk] || []).forEach(u => {
          const raw = (u.url || '').trim();
          if (!raw) return;
          const norm = raw.replace(/\/+$/, '').toLowerCase();
          (byUrl[norm] = byUrl[norm] || []).push({
            srcKey: sk, tempId: u.tempId, label: (u.label || '').trim(),
            keys: new Set(u.option_keys || []),
          });
        });
      });
      const groups = [];
      Object.keys(byUrl).forEach(norm => {
        const arr = byUrl[norm];
        if (arr.length < 2) return;
        let cross = false;
        for (let i = 0; i < arr.length; i++) {
          for (let j = i + 1; j < arr.length; j++) {
            const a = arr[i].keys, b = arr[j].keys;
            if (a.size && b.size) {
              let inter = 0; a.forEach(k => { if (b.has(k)) inter++; });
              if (inter / Math.min(a.size, b.size) < 0.5) cross = true;
            }
          }
        }
        groups.push({ srcKey: arr[0].srcKey, entries: arr, crossOption: cross });
      });
      return groups;
    }

    // [2026-06-19 P3] 딜 URL 모델 선택 드롭다운 + 모델 목록 로드
    function renderModelPicker(u) {
      const md = (state.urlModelData || {})[u.tempId];
      const box = function (inner) { return '<div style="margin:2px 0 9px;padding:11px 13px;background:#faf5ff;border:1.5px solid #ddd6fe;border-radius:10px">' + inner + '</div>'; };
      if (!md || md.loading) return box('<div style="font-size:13px;color:#7c3aed">🧩 묶인 모델 불러오는 중… (상품들 확인, 최대 ~10초)</div>');
      if (md.error) return box('<div style="font-size:13px;color:#dc2626">모델 해석 실패: ' + esc(String(md.error)) + '</div>');
      if (md.is_multi === false) return box('<div style="font-size:13px;color:#6B7684">단일상품 URL — 모델 선택 불필요</div>');
      const matchedId = md.matched ? md.matched.item_id : null;
      const items = (md.models || []).map(function (m) {
        const sel = (m.item_id === matchedId);
        return '<div data-model-pick="' + esc(m.url) + '" data-model-name="' + esc(m.name) + '" style="display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid ' + (sel ? '#7c3aed' : '#eceaf5') + ';border-radius:8px;margin:4px 0;cursor:pointer;font-size:12.5px;background:' + (sel ? '#f0e9ff' : '#fff') + '">' +
          (sel ? '<b style="color:#7c3aed">✓ 추천</b> ' : '') + esc(m.name) + '</div>';
      }).join('');
      return box('<div style="font-size:12.5px;font-weight:700;color:#7c3aed;margin-bottom:6px">🧩 이 딜에 묶인 ' + (md.models || []).length + '개 모델 — 우리 모음전에 쓸 모델을 고르면 <b>그 모델만</b> 수집합니다</div>' + items +
        '<div style="text-align:right;margin-top:6px"><button data-model-close type="button" style="background:#f2f4f6;border:0;border-radius:7px;padding:6px 12px;font-size:12px;cursor:pointer">닫기</button></div>');
    }
    async function loadUrlModels(u) {
      state.urlModelData = state.urlModelData || {};
      state.urlModelData[u.tempId] = { loading: true };
      renderRight();
      try {
        const target = (window.BUNDLE_CODE || '').replace(/_/g, ' ');
        const r = await fetch('/api/sources/resolve-deal-models', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: u.url, target_model: target })
        });
        const j = await r.json();
        state.urlModelData[u.tempId] = j.ok ? j : { error: (j.error || ('HTTP ' + r.status)) };
      } catch (e) {
        state.urlModelData[u.tempId] = { error: String((e && e.message) || e) };
      }
      if (state.urlModelPicker === u.tempId) renderRight();
    }

    function renderUrlCard(u, num) {
      const isOpen = state.openUrlId === u.tempId;
      const totalActive = state.selected.size;
      const mapped = (u.option_keys || []).length;
      // [2026-06-05] 크롤 실패 URL — 빨강 카드 + ❌ 배지 + 🔄 재크롤. (신규 추가 URL=undefined 는 정상 취급)
      // [2026-06-12] SSG 딜(dealItemView) = 색상별 단품 URL로 커버되는 허브 → 'covered' 중립 상태.
      //   실패가 아니므로 빨강 카드/재크롤 대상에서 제외, 안내 배지만 표시.
      const isCovered = u.lastStatus === 'covered';
      const isFail = u.crawled === false && !isCovered;
      // [2026-06-19 P3] 딜(멀티모델) URL — 모델 배지로 우리 모델만 골라 수집
      const isDeal = (u.url || '').toLowerCase().includes('dealitemview');
      // [2026-06-20] 유형 사전지정 — dan/mo/deal. 미지정 기본 = 단품. 단, dealItemView URL은
      //   기본 '모델 모음전'(딜 감지는 100% 확실 + 모델 선택 버튼이 떠야 모델 지정 가능).
      const _ut = u.url_type || (isDeal ? 'deal' : 'dan');
      // [2026-06-21] 모델 선택 버튼·드롭다운은 '실제 딜(dealItemView) URL'일 때만 노출.
      //   (모델 선택 후 URL 이 단일 itemView 로 바뀌면 isDeal=false → 버튼 사라짐 = 이미 선택 완료.
      //   기존엔 버튼은 유형(_ut)으로, 드롭다운은 isDeal 로 떠 불일치 → '버튼 안 눌림' 버그.)
      const showModel = (_ut === 'deal') && isDeal;
      const _segCss = 'border:0;background:#fff;padding:5px 8px;font-size:11px;font-weight:800;color:#8B95A1;cursor:pointer;border-right:1px solid #EEF1F5';
      const _onCol = { dan: '#1B64DA', mo: '#6B3FD4', deal: '#D6334B' };
      const _seg = (v, lbl) => `<button data-url-type="${v}" type="button" style="${_segCss}${_ut === v ? ';background:' + _onCol[v] + ';color:#fff' : ''}">${lbl}</button>`;
      const tySeg = `<span class="oum-url-tyseg" title="유형: 단품 / 색상 모음전 / 모델 모음전 (지정 시 검증이 이 값 사용)" style="display:inline-flex;border:1px solid #DDE2E6;border-radius:8px;overflow:hidden;flex:none">${_seg('dan', '단품')}${_seg('mo', '색상')}${_seg('deal', '모델')}</span>`;
      const statusTxt = u.lastStatus === 'error' ? '응답 오류'
        : (u.lastStatus === 'not_crawled' ? '아직 크롤 안 됨' : (u.lastStatus || '실패'));

      // [2026-05-27 B1] URL input 옆에 ↗ 바로가기 버튼 — URL 있을 때만 표시
      const goBtn = u.url && u.url.trim()
        ? `<a class="oum-url-go" href="${esc(u.url)}" target="_blank" rel="noopener noreferrer" title="새 탭에서 열기">↗</a>`
        : '';
      // [2026-05-27] 드래그앤드랍 — 카드 전체 draggable + 드래그 핸들 ⋮⋮ 표시
      //   복사 ⎘ 버튼은 유지 (시안 v8 선택 후 디자인 교체 예정)
      let html = `<div class="oum-url-card ${isOpen ? 'open' : ''}${isFail ? ' crawl-fail' : ''}${isCovered ? ' crawl-covered' : ''}" data-url-id="${u.tempId}" draggable="true">
        <div class="oum-url-ch">
          ${tySeg}
          <span class="oum-url-drag" title="드래그해서 순서 변경" data-url-drag>⋮⋮</span>
          <span class="oum-url-num">${num}</span>
          <input class="oum-url-label" data-field="label" value="${esc(u.label)}" placeholder="라벨 (선택)">
          <input class="oum-url-input" data-field="url" value="${esc(u.url)}" placeholder="URL 입력">
          ${goBtn}
          <span class="oum-url-cnt ${isFail ? 'fail' : ''}" title="이 URL 에 매핑된 옵션 / 전체 활성 옵션">📌 <b>${mapped}</b>/${totalActive}</span>
          ${showModel ? `<button class="oum-url-model" data-url-model type="button" title="모델 모음전 — 우리 모델만 골라 수집" style="background:#ede9fe;color:#7c3aed;border:1px solid #ddd6fe;border-radius:8px;padding:5px 10px;font-size:12.5px;font-weight:700;cursor:pointer;white-space:nowrap">${u.modelLabel ? '모델: ' + esc(u.modelLabel) : '모델 선택'} ▾</button>` : ''}
          ${isFail ? `<button class="oum-url-recrawl" data-url-recrawl type="button" title="이 URL 다시 크롤">🔄 재크롤</button>` : ''}
          <button class="oum-url-tog" data-url-tog type="button">${isOpen ? '▾ 닫기' : '▸ 매핑'}</button>
          <button class="oum-url-copy" data-url-copy type="button" title="이 카드 그대로 복사">📋 복사</button>
          <button class="oum-url-del" data-url-del type="button">✕ 삭제</button>
        </div>
        ${isFail ? `<div class="oum-url-failmsg">❌ 크롤 실패 (${esc(statusTxt)}) — 이 URL 의 옵션 <b>${mapped}건</b>은 가격/재고를 못 받았어요. 🔄 재크롤하거나 URL 을 확인하세요.</div>` : ''}
        ${isCovered ? `<div class="oum-url-covered">📦 딜·기획전 허브 — 색상별 단품 URL로 가격·재고가 커버됩니다. 이 URL은 따로 크롤하지 않아요 (정상).</div>` : ''}
        ${(isDeal && state.urlModelPicker === u.tempId) ? renderModelPicker(u) : ''}`;

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

      // [2026-05-26] 헤더 클릭 일괄 선택 안내 — 사용자가 헤더 클릭 가능함을 인지하게
      let html = `<div style="font-size:11px; color:#15803d; padding:4px 8px 8px; display:flex; gap:10px; flex-wrap:wrap;">
        <span>💡 <b>색상/사이즈 헤더 클릭</b> → 그 줄 전체 일괄 ON/OFF</span>
        <span>·</span>
        <span>⌐ 코너 클릭 → 전체</span>
      </div>`;

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
          const urlMapped = mappedSet.has(k);
          const hasInv = active && state.invMappedKeys && state.invMappedKeys.has(k);
          const info = sharedMap[k] || { count: 0, mappings: [] };
          const sh = info.count;
          const s = cellState(active, urlMapped, hasInv);
          let cls = s.cls;
          if (urlMapped && sh > 1) cls += ' shared';
          const sharedAttr = (urlMapped && sh > 1) ? ` data-shared="${sh}"` : '';
          const mappingsAttr = (sh > 1) ? ` data-shared-mappings='${esc(JSON.stringify(info.mappings))}'` : '';
          html += `<td><span class="oum-cell ${cls}" data-url-cell-key='${esc(k)}'${sharedAttr}${mappingsAttr}>${s.inner}</span></td>`;
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
        html += `<div class="oum-mtx-grp"><div class="oum-mtx-grp-h" data-url-grp-axis="${esc(groupAxis.name)}" data-url-grp-val="${esc(gv)}">▾ ${esc(groupAxis.name || '축')}: ${esc(gv)}</div>`;
        html += renderUrlMatrix2D(u, colAxis, rowAxis, [{ idx: valid.length - 1, val: gv }], mappedSet, sharedMap);
        html += `</div>`;
      });
      html += `</div>`;
      return html;
    }

    function renderUrlMatrix2D(u, colAxis, rowAxis, baseFilter, mappedSet, sharedMap) {
      const valid = validAxes();
      // [2026-05-24 BUG FIX] 같은 객체 참조 버그 — 이름 기반 매칭
      const colIdx = valid.findIndex(a => a.name === colAxis.name);
      const rowIdx = valid.findIndex(a => a.name === rowAxis.name);

      const baseStr = esc(JSON.stringify(baseFilter));
      let html = `<table class="oum-mtx-table"><thead><tr><th class="corner" data-url-corner-axes='${baseStr}'>⌐</th>`;
      colAxis.values.forEach(cv => {
        html += `<th data-url-col-axis="${esc(colAxis.name)}" data-url-col-val="${esc(cv)}" data-url-base='${baseStr}'>${esc(cv)}</th>`;
      });
      html += `</tr></thead><tbody>`;

      rowAxis.values.forEach(rv => {
        html += `<tr><th data-url-row-axis="${esc(rowAxis.name)}" data-url-row-val="${esc(rv)}" data-url-base='${baseStr}'>${esc(rv)}</th>`;
        colAxis.values.forEach(cv => {
          const arr = new Array(valid.length);
          baseFilter.forEach(b => { arr[b.idx] = b.val; });
          arr[colIdx] = cv;
          arr[rowIdx] = rv;
          const k = keyOf(arr);
          const active = state.selected.has(k);
          const urlMapped = mappedSet.has(k);
          const hasInv = active && state.invMappedKeys && state.invMappedKeys.has(k);
          const info = sharedMap[k] || { count: 0, mappings: [] };
          const sh = info.count;
          const s = cellState(active, urlMapped, hasInv);
          let cls = s.cls;
          if (urlMapped && sh > 1) cls += ' shared';
          const sharedAttr = (urlMapped && sh > 1) ? ` data-shared="${sh}"` : '';
          const mappingsAttr = (sh > 1) ? ` data-shared-mappings='${esc(JSON.stringify(info.mappings))}'` : '';
          html += `<td><span class="oum-cell ${cls}" data-url-cell-key='${esc(k)}'${sharedAttr}${mappingsAttr}>${s.inner}</span></td>`;
        });
        html += `</tr>`;
      });

      html += `</tbody></table>`;
      return html;
    }

    // [2026-05-26] 전체 소싱처 합산 — 한 옵션이 모든 탭/카드 통틀어 몇 개 URL 에 매핑됐는지
    //   반환: { [optionKey]: { count, mappings: [{sk, label, url}, ...] } }
    //   매트릭스 셀 우상단 배지 카운트 + hover tooltip 데이터로 사용
    function computeSharedMap() {
      const map = {};
      Object.keys(state.urls || {}).forEach(sk => {
        (state.urls[sk] || []).forEach(u => {
          (u.option_keys || []).forEach(k => {
            if (!map[k]) map[k] = { count: 0, mappings: [] };
            map[k].count += 1;
            map[k].mappings.push({ sk, label: u.label || '', url: u.url || '' });
          });
        });
      });
      return map;
    }

    // [2026-05-27 B2-2] 셀 hover floating card — Card Stack 스타일
    //   소싱처별 그룹 → 흰 카드 + 회색 그룹 카드 + 색칩+소싱처명+카운트뱃지 + URL 들
    //   document.body 에 fixed 로 append (모달 overflow:hidden 영향 X)
    //   위치 자동: 셀 아래 공간 부족하면 위로, 좌우 화면 밖이면 클램프
    let _sharedTipEl = null;
    function showSharedTip(cellEl) {
      // [v25-A.1 2026-06-02] 같은 셀이면 재생성 X (깜빡임 + race 방지)
      //   셀 안의 자식 element 사이 mouseover 가 반복 발동해도 카드 그대로 유지.
      if (_sharedTipEl && _sharedTipEl._cellRef === cellEl) {
        cancelSharedTipClose();
        return;
      }
      hideSharedTip();
      const raw = cellEl.getAttribute('data-shared-mappings');
      if (!raw) return;
      let mappings;
      try { mappings = JSON.parse(raw); } catch (e) { return; }
      if (!mappings || !mappings.length) return;

      // 소싱처별 그룹화 — 처음 등장 순서 유지
      const groups = {};
      const order = [];
      mappings.forEach(m => {
        if (!groups[m.sk]) { groups[m.sk] = []; order.push(m.sk); }
        groups[m.sk].push(m);
      });

      const tip = document.createElement('div');
      tip.className = 'oum-shared-tip';
      let html = '<div class="arrow"></div>';
      order.forEach(sk => {
        const label = SRC_LABELS[sk] || sk;
        const color = SRC_COLORS[sk] || '#3B82F6';
        const items = groups[sk];
        // [2026-05-27 A4] 그룹 헤더는 항상 보이고, 그룹 안 URL list 만 자체 스크롤 (max-height 120px)
        html += `<div class="stp-grp">
          <div class="stp-grp-h">
            <span class="stp-chip" style="background:${esc(color)};">${esc((typeof SRC_ABBR !== 'undefined' && SRC_ABBR[sk]) || abbr(label))}</span>
            <span class="stp-name">${esc(label)}</span>
            <span class="stp-cnt">${items.length}개</span>
          </div>
          <div class="stp-grp-body">`;
        items.forEach(m => {
          // [2026-05-27 B1] 각 URL row 에 ↗ 바로가기 버튼 — 새 탭에서 URL 열기
          // [2026-05-27 시안2] URL → domain 강조 + 한 줄 ellipsis. 전체 URL 은 title attr 로 hover 시 확인.
          const sp = splitUrl(m.url);
          const urlInner = sp.domain
            ? `<span class="stp-url-domain">${esc(sp.domain)}</span>${esc(sp.rest)}`
            : esc(sp.rest);
          html += `<div class="stp-url-row">
            <div class="stp-text">
              ${m.label ? `<div class="stp-lbl">${esc(m.label)}</div>` : ''}
              <div class="stp-url" title="${esc(m.url)}">${urlInner}</div>
            </div>
            <a class="oum-url-go" href="${esc(m.url)}" target="_blank" rel="noopener noreferrer" title="새 탭에서 열기">↗</a>
          </div>`;
        });
        html += `</div></div>`;
      });
      tip.innerHTML = html;
      // [2026-05-27 B1] tooltip 자체에 hover 시 닫기 delay 취소 — 마우스가 tooltip 안에 있으면 유지
      tip.addEventListener('mouseenter', () => {
        if (_sharedTipCloseTimer) { clearTimeout(_sharedTipCloseTimer); _sharedTipCloseTimer = null; }
      });
      tip.addEventListener('mouseleave', () => scheduleSharedTipClose());
      document.body.appendChild(tip);
      _sharedTipEl = tip;
      _sharedTipEl._cellRef = cellEl;  // [v25-A.1] 같은 셀 재진입 시 재생성 skip 용
      positionSharedTip(cellEl, tip);
    }

    // 셀에서 mouseout 후 일정 시간 동안 tooltip 으로 이동할 시간 (gap) 허용
    //   [v25-A.1 2026-06-02] 200 → 500ms — hover deadzone (셀↔카드 사이 빈 공간) 통과 시간 확보
    let _sharedTipCloseTimer = null;
    function scheduleSharedTipClose() {
      if (_sharedTipCloseTimer) clearTimeout(_sharedTipCloseTimer);
      _sharedTipCloseTimer = setTimeout(() => { hideSharedTip(); }, 500);
    }
    function cancelSharedTipClose() {
      if (_sharedTipCloseTimer) { clearTimeout(_sharedTipCloseTimer); _sharedTipCloseTimer = null; }
    }

    function positionSharedTip(cellEl, tip) {
      // [v25-A 2026-06-01] 카드를 셀 우측/좌측 옆으로 배치 (위/아래 인접 행 안 가림)
      //   이전: 셀 아래 vs 위 → 같은 컬럼의 다른 행 셀들이 카드에 가려짐
      //   변경: 셀 우측 vs 좌측 → 다른 행 셀들 항상 보임. URL 데이터·매핑 0 변경.
      const cellRect = cellEl.getBoundingClientRect();
      const tipRect = tip.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      // [v25-A.1 2026-06-02] gap 10 → 4 — 셀↔카드 사이 hover deadzone 최소화
      //   카드 좌측 CSS padding (::before bridge) + 짧은 gap 으로 마우스 이동 끊김 없음
      const gap = 4;
      const margin = 8;  // viewport 가장자리 여백

      // 수평: 셀 우측 vs 좌측 공간 비교 — 더 큰 쪽으로 펼침 (우측 우선)
      const spaceRight = vw - cellRect.right - gap - margin;
      const spaceLeft = cellRect.left - gap - margin;
      let left, placement;
      if (spaceRight >= tipRect.width || spaceRight >= spaceLeft) {
        // 우측으로 — 카드 화살표는 카드 좌측에 표시 (left placement class)
        left = cellRect.right + gap;
        placement = 'left';   // arrow points from left edge of card → cell on left
      } else {
        // 좌측으로 — 카드 화살표는 카드 우측에 표시 (right placement class)
        left = cellRect.left - tipRect.width - gap;
        placement = 'right';  // arrow points from right edge of card → cell on right
      }

      // viewport 좌/우 가장자리 클램프
      if (left < margin) left = margin;
      if (left + tipRect.width > vw - margin) left = vw - tipRect.width - margin;
      if (left < margin) left = margin;

      // 수직: 셀 중앙에 카드 중앙 맞추되 viewport 안에 들어오게 클램프
      let top = cellRect.top + cellRect.height / 2 - tipRect.height / 2;
      const maxTop = Math.max(margin, vh - tipRect.height - margin);
      top = Math.max(margin, Math.min(top, maxTop));

      tip.style.top = top + 'px';
      tip.style.left = left + 'px';
      tip.classList.add(placement);

      // 화살표 — 셀 수직 중앙 위치에 맞춰 top 보정 (가로 placement 라 top 보정)
      const arrow = tip.querySelector('.arrow');
      if (arrow) {
        const cellCenterY = cellRect.top + cellRect.height / 2;
        const arrowTop = cellCenterY - top;
        arrow.style.top = Math.max(12, Math.min(tipRect.height - 12, arrowTop)) + 'px';
        arrow.style.transform = 'translateY(-50%)';
        arrow.style.left = '';  // 가로 placement 에선 left 초기화
      }
    }

    function hideSharedTip() {
      if (_sharedTipEl && _sharedTipEl.parentNode) {
        _sharedTipEl.parentNode.removeChild(_sharedTipEl);
      }
      _sharedTipEl = null;
    }

    // ─── 이벤트 ───
    function rerender() {
      renderLeft();
      renderRight();
      updateSaveBtn();
    }

    // [2026-06-11] 현재 탭의 첫 크롤 실패 URL 카드로 스크롤 + 깜빡임 강조.
    //   매트릭스 실패 카드 클릭(scrollToFail)·배너 "↓ 실패 URL로 이동" 버튼에서 호출.
    function scrollToFirstFail() {
      const card = modal.querySelector('.oum-url-card.crawl-fail');
      if (!card) return false;
      try { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { card.scrollIntoView(); }
      card.classList.remove('oum-fail-flash');
      // reflow 강제 후 클래스 재부여 — 같은 카드 반복 클릭에도 애니메이션 재생
      void card.offsetWidth;
      card.classList.add('oum-fail-flash');
      setTimeout(() => card.classList.remove('oum-fail-flash'), 1800);
      return true;
    }

    function updateSaveBtn() {
      const save = $('#oum-save');
      const hasOpts = state.selected.size > 0;
      save.disabled = !hasOpts;
      save.textContent = hasOpts ? `옵션 ${state.selected.size}개 + URL 저장` : '옵션 + URL 저장';
    }

    // 좌측 이벤트 — try-catch 로 JS 에러 시 다음 핸들러 계속 동작
    $('#oum-left').addEventListener('click', e => {
      try {
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
      // [순서 v33] 축 정렬 (오름/내림) — 값이 모두 숫자면 숫자 정렬, 아니면 한글/문자 정렬
      const sortb = e.target.closest('[data-axis-sort]');
      if (sortb) {
        const ai = +sortb.dataset.axisSort;
        const vals = parseValues(state.axes[ai].values);
        const numeric = vals.length > 0 && vals.every(v => v.trim() !== '' && isFinite(v.trim()));
        vals.sort((a, b) => numeric ? (parseFloat(a) - parseFloat(b)) : String(a).localeCompare(String(b), 'ko'));
        if (sortb.dataset.dir === 'desc') vals.reverse();
        state.axes[ai].values = vals.join(',');
        recalcMatrix(); rerender();
        return;
      }
      // 빠른 선택 칩
      const qs = e.target.closest('[data-qs-axis]');
      if (qs) {
        toggleAxis(qs.dataset.qsAxis, qs.dataset.qsVal);
        return;
      }
      // 빠른 선택 reset — mappedOff 도 같이 정리 (v20.5)
      if (e.target.closest('[data-qs-reset]')) {
        state.selected.clear();
        if (state.mappedOff) state.mappedOff.clear();
        rerender();
        return;
      }
      // 매트릭스 셀 — _isCellActive 헬퍼 사용 (v20.5 통일)
      const cell = e.target.closest('[data-cell-key]');
      if (cell) {
        const k = cell.dataset.cellKey;
        if (_isCellActive(k)) _deactivateCell(k);
        else _activateCell(k);
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
      // 전체 선택/해제 — mappedOff 도 함께 정리 (v20.5 fix)
      if (e.target.closest('[data-mtx-all]')) {
        const all = cartesian(validAxes().map(a => a.values));
        const allOn = all.every(c => _isCellActive(keyOf(c)));
        if (allOn) {
          state.selected.clear();
          if (state.mappedOff) state.mappedOff.clear();
        } else {
          all.forEach(c => { const k = keyOf(c); _activateCell(k); });
        }
        rerender();
        return;
      }
      // 적용 버튼
      if (e.target.closest('#oum-apply')) {
        console.log('[oum] 적용 클릭 — selected:', state.selected.size, 'sources:', state.sources.length);
        state.applied = true;
        rerender();
        return;
      }
      } catch (err) {
        console.error('[oum] click handler error:', err);
      }
    });

    // ─── [순서 v33] 칩 드래그앤드랍 수동 순서 변경 (axis.values 재배열) ───
    let _dragChip = null;
    function _clearDragMarks() {
      $('#oum-left').querySelectorAll('.oum-axis-chips .c.dragging, .oum-axis-chips .c.over')
        .forEach(x => x.classList.remove('dragging', 'over'));
    }
    $('#oum-left').addEventListener('dragstart', e => {
      const c = e.target.closest('[data-axis-chip]');
      if (!c) return;
      _dragChip = c; c.classList.add('dragging');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', ''); } catch (_) {}
    });
    $('#oum-left').addEventListener('dragover', e => {
      const c = e.target.closest('[data-axis-chip]');
      if (!c || !_dragChip || c.dataset.axisChip !== _dragChip.dataset.axisChip || c === _dragChip) return;
      e.preventDefault();
      $('#oum-left').querySelectorAll('.oum-axis-chips .c.over').forEach(x => x.classList.remove('over'));
      c.classList.add('over');
    });
    $('#oum-left').addEventListener('drop', e => {
      const c = e.target.closest('[data-axis-chip]');
      if (!c || !_dragChip || c.dataset.axisChip !== _dragChip.dataset.axisChip) { _clearDragMarks(); _dragChip = null; return; }
      e.preventDefault();
      const ai = +_dragChip.dataset.axisChip;
      const from = +_dragChip.dataset.chipIdx, to = +c.dataset.chipIdx;
      _clearDragMarks(); _dragChip = null;
      if (from === to || isNaN(from) || isNaN(to)) return;
      const vals = parseValues(state.axes[ai].values);
      const moved = vals.splice(from, 1)[0];
      vals.splice(to, 0, moved);
      state.axes[ai].values = vals.join(',');
      recalcMatrix(); rerender();
    });
    $('#oum-left').addEventListener('dragend', () => { _clearDragMarks(); _dragChip = null; });

    // ─── [순서 v33] 매트릭스 헤더 드래그 → 행/열 순서 변경 (헤더 클릭=토글은 그대로 유지) ───
    let _dragHdr = null; // { axisName, val, kind:'col'|'row' }
    function _clearHdrMarks() {
      $('#oum-left').querySelectorAll('.oum-th-dragging, .oum-th-over').forEach(x => x.classList.remove('oum-th-dragging', 'oum-th-over'));
    }
    function _hdrInfo(th) {
      if (!th) return null;
      if (th.dataset.colAxis != null) return { axisName: th.dataset.colAxis, val: th.dataset.colVal, kind: 'col' };
      if (th.dataset.rowAxis != null) return { axisName: th.dataset.rowAxis, val: th.dataset.rowVal, kind: 'row' };
      return null;
    }
    $('#oum-left').addEventListener('dragstart', e => {
      const th = e.target.closest('.oum-th-drag');
      const info = _hdrInfo(th);
      if (!info) return;
      _dragHdr = info; th.classList.add('oum-th-dragging');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', ''); } catch (_) {}
    });
    $('#oum-left').addEventListener('dragover', e => {
      const th = e.target.closest('.oum-th-drag');
      const info = _hdrInfo(th);
      if (!info || !_dragHdr || info.kind !== _dragHdr.kind) return;
      e.preventDefault();
      $('#oum-left').querySelectorAll('.oum-th-over').forEach(x => x.classList.remove('oum-th-over'));
      th.classList.add('oum-th-over');
    });
    $('#oum-left').addEventListener('drop', e => {
      const th = e.target.closest('.oum-th-drag');
      const info = _hdrInfo(th);
      if (!info || !_dragHdr || info.kind !== _dragHdr.kind) { _clearHdrMarks(); _dragHdr = null; return; }
      e.preventDefault();
      const axisName = _dragHdr.axisName, movingVal = _dragHdr.val, targetVal = info.val;
      _clearHdrMarks(); _dragHdr = null;
      if (movingVal === targetVal) return;
      const ax = state.axes.find(a => a.name === axisName);
      if (!ax) return;
      const vals = parseValues(ax.values);
      const from = vals.indexOf(movingVal), to = vals.indexOf(targetVal);
      if (from < 0 || to < 0) return;
      const m = vals.splice(from, 1)[0]; vals.splice(to, 0, m);
      ax.values = vals.join(',');
      recalcMatrix(); rerender();
    });
    $('#oum-left').addEventListener('dragend', () => { _clearHdrMarks(); _dragHdr = null; });

    // ─── 좌측 input 변경 — 한글 IME 안전 + focus 유지 ───
    // [핵심] composition 이벤트 추적 — IME 활성 중 rerender 절대 skip
    // (rerender 시 DOM 교체 → IME composition 컨텍스트 파괴 → 한글 자모 깨짐 방지)
    let isComposing = false;

    $('#oum-left').addEventListener('compositionstart', () => { isComposing = true; });
    $('#oum-left').addEventListener('compositionend', e => {
      isComposing = false;
      // 한글 입력 완료 시점 — state 갱신 + 디바운스 rerender
      const t = e.target;
      if (t.dataset && t.dataset.axisName != null) {
        state.axes[+t.dataset.axisName].name = t.value;
        scheduleRerender({ kind: 'name', idx: +t.dataset.axisName });
      } else if (t.dataset && t.dataset.axisValues != null) {
        state.axes[+t.dataset.axisValues].values = t.value;
        scheduleRerender({ kind: 'values', idx: +t.dataset.axisValues, recalc: true });
      }
    });

    $('#oum-left').addEventListener('input', e => {
      const nm = e.target.closest('[data-axis-name]');
      const vl = e.target.closest('[data-axis-values]');

      // ① IME 활성 중 — state만 갱신, rerender 절대 X
      if (isComposing) {
        if (nm) state.axes[+nm.dataset.axisName].name = e.target.value;
        else if (vl) state.axes[+vl.dataset.axisValues].values = e.target.value;
        return;
      }

      // ② 비-IME (영문/숫자) — 기존 로직 (디바운스 + focus 복원)
      if (nm) {
        state.axes[+nm.dataset.axisName].name = e.target.value;
        scheduleRerender({ kind: 'name', idx: +nm.dataset.axisName });
        return;
      }
      if (vl) {
        state.axes[+vl.dataset.axisValues].values = e.target.value;
        scheduleRerender({ kind: 'values', idx: +vl.dataset.axisValues, recalc: true });
        return;
      }
    });

    // 디바운스 + focus 복원 (입력 끊김 방지)
    function scheduleRerender(focusHint) {
      clearTimeout(state._inputTimer);
      state._inputTimer = setTimeout(() => {
        // IME 활성 중이면 또 skip (안전망)
        if (isComposing) return;
        const active = document.activeElement;
        const focusSel = (active && active.dataset && (active.dataset.axisName != null || active.dataset.axisValues != null))
          ? (active.dataset.axisName != null
              ? `[data-axis-name="${active.dataset.axisName}"]`
              : `[data-axis-values="${active.dataset.axisValues}"]`)
          : null;
        const caret = active && active.selectionStart != null ? active.selectionStart : null;
        if (focusHint && focusHint.recalc) recalcMatrix();
        rerender();
        if (focusSel) {
          const el = modal.querySelector(focusSel);
          if (el) {
            el.focus();
            if (caret != null) { try { el.setSelectionRange(caret, caret); } catch (e) {} }
          }
        }
      }, 250);
    }

    function recalcMatrix() {
      const valid = validAxes();
      if (!valid.length) { state.selected.clear(); state.seen.clear(); return; }
      const combos = cartesian(valid.map(a => a.values));
      const curKeys = new Set(combos.map(keyOf));
      [...state.selected].forEach(k => { if (!curKeys.has(k)) state.selected.delete(k); });
      [...state.seen].forEach(k => { if (!curKeys.has(k)) state.seen.delete(k); });
      combos.forEach(c => { const k = keyOf(c); if (!state.seen.has(k)) { state.seen.add(k); state.selected.add(k); } });
      // [2026-05-27] state.urls 의 카드 option_keys 도 새 axes 풀에서 없어진 키만 제거
      //   기존 매핑 보존 (초기화 X) — 새로 추가된 옵션은 자동 매핑 X (사용자 결정)
      Object.keys(state.urls || {}).forEach(sk => {
        (state.urls[sk] || []).forEach(u => {
          if (u.option_keys && u.option_keys.length) {
            u.option_keys = u.option_keys.filter(k => curKeys.has(k));
          }
        });
      });
      // state.applied 는 그대로 유지 — 사용자가 [적용 →] 다시 안 눌러도 우측 보임
    }

    // [v20.5 fix] 좌측 매트릭스 active 통합 헬퍼 — selected 또는 mappedOff 둘 중 하나라도 있으면 ON
    //   토글 시 mappedOff 도 같이 정리해야 "전체 해제"·"줄/코너 해제" 등 일괄 토글에서
    //   잔류 mappedOff 셀이 ON 으로 남는 버그 차단. 단일 셀 클릭은 이미 v20.3 에서 처리됨.
    function _isCellActive(k) {
      // [2026-06-04 FIX] ON 판정 = selected 만. (mappedOff=비활성이므로 클릭하면 다시 켜져야 함)
      return state.selected.has(k);
    }
    function _activateCell(k) {
      state.selected.add(k);
      if (state.mappedOff) state.mappedOff.delete(k);
    }
    function _deactivateCell(k) {
      state.selected.delete(k);
      if (state.mappedOff) state.mappedOff.delete(k);
    }

    function toggleAxis(axisName, val) {
      const matching = filterCombos(axisName, val);
      if (!matching.length) return;  // axis 못 찾았으면 동작 안 함
      const allOn = matching.every(c => _isCellActive(keyOf(c)));
      matching.forEach(c => { const k = keyOf(c); if (allOn) _deactivateCell(k); else _activateCell(k); });
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
      // [2026-05-24 BUG FIX] axis 못 찾으면 동작 안 함
      const ax = String(axisName == null ? '' : axisName).trim();
      const axisIdx = valid.findIndex(a => String(a.name || '').trim() === ax);
      if (axisIdx < 0) {
        console.warn('[oum] toggleHeaderRange axis not found:', axisName);
        return;
      }
      const allCombos = cartesian(valid.map(a => a.values));
      const matching = allCombos.filter(c => {
        if (c[axisIdx] !== val) return false;
        return base.every(b => c[b.idx] === b.val);
      });
      if (!matching.length) return;
      const allOn = matching.every(c => _isCellActive(keyOf(c)));
      matching.forEach(c => { const k = keyOf(c); if (allOn) _deactivateCell(k); else _activateCell(k); });
      rerender();
    }

    function toggleCorner(el) {
      let base = [];
      try { base = JSON.parse(el.dataset.cornerAxes || '[]'); } catch (e) {}
      const valid = validAxes();
      const allCombos = cartesian(valid.map(a => a.values));
      const matching = allCombos.filter(c => base.every(b => c[b.idx] === b.val));
      const allOn = matching.every(c => _isCellActive(keyOf(c)));
      matching.forEach(c => { const k = keyOf(c); if (allOn) _deactivateCell(k); else _activateCell(k); });
      rerender();
    }

    function toggleGroup(axisName, val) {
      toggleAxis(axisName, val);
    }

    // [2026-05-27] 드래그앤드랍 — 같은 소싱처 안에서 카드 순서 변경
    let _dragSrcCard = null;
    $('#oum-right').addEventListener('dragstart', e => {
      const card = e.target.closest('.oum-url-card');
      if (!card) return;
      _dragSrcCard = card;
      card.classList.add('dragging');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', card.dataset.urlId); } catch (err) {}
    });
    $('#oum-right').addEventListener('dragend', e => {
      const card = e.target.closest('.oum-url-card');
      if (card) card.classList.remove('dragging');
      // 모든 drop 표시 제거
      $$('.oum-url-card').forEach(c => c.classList.remove('drop-above', 'drop-below'));
      _dragSrcCard = null;
    });
    $('#oum-right').addEventListener('dragover', e => {
      const target = e.target.closest('.oum-url-card');
      if (!target || !_dragSrcCard || target === _dragSrcCard) return;
      e.preventDefault();
      try { e.dataTransfer.dropEffect = 'move'; } catch (err) {}
      // 상/하 표시
      const rect = target.getBoundingClientRect();
      const isAbove = e.clientY < rect.top + rect.height / 2;
      $$('.oum-url-card').forEach(c => c.classList.remove('drop-above', 'drop-below'));
      target.classList.add(isAbove ? 'drop-above' : 'drop-below');
    });
    $('#oum-right').addEventListener('drop', e => {
      const target = e.target.closest('.oum-url-card');
      if (!target || !_dragSrcCard || target === _dragSrcCard) return;
      e.preventDefault();
      const srcId = +_dragSrcCard.dataset.urlId;
      const tgtId = +target.dataset.urlId;
      const arr = state.urls[state.currentSrc] || [];
      const srcIdx = arr.findIndex(u => u.tempId === srcId);
      const tgtIdx = arr.findIndex(u => u.tempId === tgtId);
      if (srcIdx < 0 || tgtIdx < 0) return;
      const rect = target.getBoundingClientRect();
      const isAbove = e.clientY < rect.top + rect.height / 2;
      // src 를 제거하고 target 위/아래에 삽입
      const [moved] = arr.splice(srcIdx, 1);
      let insertIdx = arr.findIndex(u => u.tempId === tgtId);
      if (!isAbove) insertIdx += 1;
      arr.splice(insertIdx, 0, moved);
      renderRight();
    });

    // [2026-05-27 B2-2 + B1] 우측 매트릭스 셀 hover → floating card 동적 생성
    // delay 메커니즘: 셀 mouseout → 200ms 후 닫기, tooltip mouseenter → 취소
    //   사용자가 셀에서 tooltip 안 ↗ 버튼으로 마우스 이동할 시간 확보
    $('#oum-right').addEventListener('mouseover', e => {
      const cell = e.target.closest('[data-shared-mappings]');
      if (cell) {
        cancelSharedTipClose();
        showSharedTip(cell);
      }
    });
    $('#oum-right').addEventListener('mouseout', e => {
      const cell = e.target.closest('[data-shared-mappings]');
      if (cell) scheduleSharedTipClose();
    });
    // 모달 닫기/스크롤 시 tooltip 제거
    bg.addEventListener('scroll', hideSharedTip, true);

    // 우측 이벤트 — async (autoSave 는 fire-and-forget, await 안 함)
    $('#oum-right').addEventListener('click', async e => {
      // [2026-05-29 시안 v3 C3] 우측 탭 전환 (URL ↔ 재고관리)
      const rtTab = e.target.closest('[data-rt-tab]');
      if (rtTab) {
        const tgt = rtTab.dataset.rtTab;
        if (tgt && tgt !== state.rightTab) {
          state.rightTab = tgt;
          renderRight();
        }
        return;
      }
      // [2026-06-20] 검증 탭 — 전체/선택/개별 재검증 · URL 트리 선택·체크 · 실패 정산 펼침
      const vCheck = e.target.closest('[data-vcheck]');
      if (vCheck) {
        if (!state.verifyChecks) state.verifyChecks = {};
        const k = vCheck.dataset.vcheck;
        state.verifyChecks[k] = !state.verifyChecks[k];
        renderRight();
        return;
      }
      const vFail = e.target.closest('[data-verify-fail]');
      if (vFail) { state.verifyFailOpen = !state.verifyFailOpen; renderRight(); return; }
      const vFExp = e.target.closest('[data-fail-exp]');
      if (vFExp) {
        if (!state.verifyFailExpand) state.verifyFailExpand = {};
        const fk = vFExp.dataset.failExp;
        state.verifyFailExpand[fk] = !state.verifyFailExpand[fk];
        renderRight();
        return;
      }
      // 재검증(전체/선택/개별) — 실제 재크롤(recrawl-url 배치) + 미니 토스트.
      const rOne = e.target.closest('[data-verify-refresh-one]');
      const rSel = e.target.closest('[data-verify-refresh-sel]');
      const rAll = e.target.closest('[data-verify-refresh]');
      if (rOne || rSel || rAll) {
        const all = _vAllUrls();
        let targets;
        let lbl = '전체';
        if (rOne) { const pu = rOne.dataset.verifyRefreshOne; targets = all.filter(function (u) { return u.product_url === pu; }); lbl = '해당'; }
        else if (rSel) {
          targets = all.filter(function (u) { return state.verifyChecks && state.verifyChecks[u.product_url]; });
          lbl = '선택';
          if (!targets.length) { alert('선택된 URL이 없습니다. 좌측 체크박스로 URL을 선택하세요.'); return; }
        } else { targets = all; }
        startVerifyRecrawl(targets, lbl);
        return;
      }
      const vUrl = e.target.closest('[data-vurl]');
      if (vUrl) { state.verifySelUrl = vUrl.dataset.vurl; renderRight(); return; }  // 스크롤 보존은 renderRight 가 처리
      // [2026-06-20] URL 유형 세그먼트(단품/색상/모델) — 사전 지정
      const tyBtn = e.target.closest('[data-url-type]');
      if (tyBtn) {
        const card = tyBtn.closest('[data-url-id]');
        const u = (state.urls[state.currentSrc] || []).find(x => String(x.tempId) === (card && card.dataset.urlId));
        if (u) {
          const v = tyBtn.dataset.urlType;
          u.url_type = (u.url_type === v) ? '' : v;  // 같은 값 재클릭 = 해제(미지정)
          if (u.url_type !== 'deal') state.urlModelPicker = null;  // 모델 아니면 모델피커 닫기
          renderRight();
        }
        return;
      }
      // [2026-06-19 P3] 딜 URL 모델 배지 — 열기/선택/닫기
      const mBtn = e.target.closest('[data-url-model]');
      if (mBtn) {
        const card = mBtn.closest('[data-url-id]');
        const u = (state.urls[state.currentSrc] || []).find(x => String(x.tempId) === (card && card.dataset.urlId));
        if (u) {
          state.urlModelPicker = (state.urlModelPicker === u.tempId) ? null : u.tempId;
          renderRight();
          if (state.urlModelPicker === u.tempId && !(state.urlModelData || {})[u.tempId]) loadUrlModels(u);
        }
        return;
      }
      const mPick = e.target.closest('[data-model-pick]');
      if (mPick) {
        const card = mPick.closest('[data-url-id]');
        const u = (state.urls[state.currentSrc] || []).find(x => String(x.tempId) === (card && card.dataset.urlId));
        if (u) {
          u.url = mPick.dataset.modelPick;
          u.modelLabel = mPick.dataset.modelName;
          state.urlModelPicker = null;
          renderRight();
        }
        return;
      }
      const mClose = e.target.closest('[data-model-close]');
      if (mClose) { state.urlModelPicker = null; renderRight(); return; }
      // [2026-06-13] 크롤 실패 URL 재크롤 — 실제로 서버사이드 크롤 호출 후 성공/실패 표시.
      //   HTTP 소싱처(ssf·ssg·lemouton·smartstore)=서버 크롤. 무신사·롯데온=브라우저 필요라
      //   서버가 status='need_extension' 반환 → 크롬 확장(MoumExt)으로 크롤 후 결과 저장.
      const recrawlBtn = e.target.closest('[data-url-recrawl]');
      if (recrawlBtn) {
        const card = recrawlBtn.closest('[data-url-id]');
        const u = (state.urls[state.currentSrc] || []).find(x => String(x.tempId) === (card && card.dataset.urlId));
        if (!u || !u.url) return;
        const _src = state.currentSrc;
        const _toast = (m, k) => { try { if (window.showToast) window.showToast(m, k); } catch (_) {} };
        recrawlBtn.disabled = true;
        recrawlBtn.textContent = '⏳ 크롤 중…';
        try {
          let res = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/recrawl-url`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_key: _src, url: u.url }),
          }).then(r => r.json()).catch(err => ({ ok: false, error: String(err) }));
          // 서버에 브라우저 없음(무신사·롯데온) → 크롬 확장으로 크롤 시도
          if (res && res.status === 'need_extension') {
            if (window.MoumExt && window.MoumExt.installed && window.MoumExt.installed()) {
              _toast('🧩 확장으로 크롤 중…', 'ok');
              const ext = await window.MoumExt.crawl(
                { model_code: bundleCode, sources: [{ source_key: _src, url: u.url }] }, 120000
              ).catch(err => ({ ok: false, error: String(err) }));
              const one = ext && ext.results && ext.results[0];
              if (one) {
                await fetch('/api/sources/crawl-result', {
                  method: 'POST', headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ items: [{ url: u.url, price: one.price, stock: one.stock, status: one.ok ? 'ok' : 'error', product_name: one.product_name, error: one.error }] }),
                }).catch(() => {});
                res = { crawl_ok: !!one.ok, price: one.price, stock: one.stock, error: one.error };
              } else {
                res = { crawl_ok: false, error: (ext && ext.error) || '확장 크롤 실패' };
              }
            } else {
              res = { crawl_ok: false, error: '이 소싱처는 크롬 확장(모음전 크롤러)이 필요합니다' };
            }
          }
          if (res && res.crawl_ok) {
            u.crawled = true; u.lastStatus = 'ok';
            _toast(`✅ 크롤 성공 — ${u.label || _src}${res.price ? ` · ${Number(res.price).toLocaleString()}원` : ''}`, 'ok');
          } else {
            u.crawled = false; u.lastStatus = 'error';
            _toast(`❌ 크롤 실패 — ${(res && res.error) || '알 수 없는 오류'}`, 'err');
          }
        } catch (err) {
          u.crawled = false; u.lastStatus = 'error';
          _toast(`❌ 크롤 실패 — ${err}`, 'err');
        }
        renderRight();
        return;
      }
      // [B3-3] 재고 자동 매칭 버튼
      if (e.target.closest('[data-inv-auto]')) {
        // [v20] 필터(브랜드+모델) 가 변경됐을 수 있으니 서버에 재요청 후 자동 매칭
        const fb = state.invFilter.brand || '';
        const fm = state.invFilter.model || '';
        const qs = (fb || fm) ? `?brand=${encodeURIComponent(fb)}&model=${encodeURIComponent(fm)}` : '';
        try {
          const r = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/inventory-mapping${qs}`);
          const ij = await r.json();
          if (ij && ij.ok) {
            state.invCandidates = ij.candidates || {};
            state.invOptions = ij.inventory_options || [];
          }
        } catch (err) { /* fallback to cached candidates */ }
        invAutoMatch();
        renderRight();
        rerender();
        return;
      }
      // [v20] 정리 기준 드롭다운 토글
      const grpTog = e.target.closest('[data-grp-toggle]');
      if (grpTog) {
        const menu = grpTog.parentElement.querySelector('.oum-grp-dd-menu');
        if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
        return;
      }
      const grpIt = e.target.closest('[data-grp-key]');
      if (grpIt) {
        state.invGroupBy = grpIt.dataset.grpKey;
        renderRight();
        return;
      }
      // [v20] 브랜드 선택
      const brIt = e.target.closest('[data-br-name]');
      if (brIt) {
        state.invFilter.brand = brIt.dataset.brName;
        state.invFilter.model = '';  // 브랜드 바뀌면 모델 초기화
        // [v20.4] 사용자 직접 설정 — bundle_meta fallback 비활성 (모델 input 공란 유지)
        state.invFilterUserSet.brand = true;
        state.invFilterUserSet.model = true;
        renderRight();
        return;
      }
      if (e.target.closest('[data-br-clear]')) {
        state.invFilter.brand = '';
        state.invFilter.model = '';
        state.invFilterUserSet.brand = true;
        state.invFilterUserSet.model = true;
        renderRight();
        return;
      }
      // [v20] 모델 선택
      const mdIt = e.target.closest('[data-md-name]');
      if (mdIt) {
        state.invFilter.model = mdIt.dataset.mdName;
        state.invFilterUserSet.model = true;
        renderRight();
        return;
      }
      // [v20.8 T1] 컬럼 헤더 클릭 → 정렬 토글
      const sortCol = e.target.closest('[data-inv-sort]');
      if (sortCol) {
        const c = sortCol.dataset.invSort;
        if (!state.invSort) state.invSort = { col: 'opt', dir: 'asc' };
        if (state.invSort.col === c) {
          // 같은 컬럼 → 방향 반전
          state.invSort.dir = state.invSort.dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.invSort.col = c;
          state.invSort.dir = 'asc';
        }
        renderRight();
        return;
      }
      // [v20.4] 수기 행의 ✎ 다시 입력 — invRows[bSku] 비우고 input 모드로
      const reEdit = e.target.closest('[data-inv-reedit]');
      if (reEdit) {
        e.stopPropagation();
        const k = reEdit.dataset.invReedit;
        const skuByKey = state.skuByKey || {};
        const bSku = skuByKey[k];
        if (bSku && state.invRows[bSku]) {
          delete state.invRows[bSku];
          state.invMappedKeys.delete(k);
        }
        renderRight();
        return;
      }
      // [v20.7] 인라인 SKU 자동완성 항목 클릭은 body 레벨 _handleInvAcPickClick 가 처리
      // [v20] 브랜드/모델 input 클릭 — dropdown 열기
      if (e.target.id === 'oum-br-in') {
        const dd = e.target.parentElement.querySelector('.oum-br-dd');
        if (dd) dd.style.display = 'block';
        return;
      }
      if (e.target.id === 'oum-md-in' && !e.target.disabled) {
        const dd = e.target.parentElement.querySelector('.oum-md-dd');
        if (dd) dd.style.display = 'block';
        return;
      }
      // 외부 클릭 시 dropdown 닫기
      if (!e.target.closest('.oum-br-search') && !e.target.closest('.oum-md-search') && !e.target.closest('.oum-grp-dd')) {
        modal.querySelectorAll('.oum-br-dd, .oum-md-dd, .oum-grp-dd-menu').forEach(d => d.style.display = 'none');
      }
      // [B3-3] 적용 버튼 — 매핑 서버 저장
      if (e.target.closest('[data-inv-apply]')) {
        await invApplyMapping(bundleCode);
        return;
      }
      // [2026-05-27] 탭 전환 즉시 — autoSave 백그라운드 (사용자 대기 X)
      //   pending 큐 가드로 inflight 중 호출도 마지막 저장 보장
      // [2026-06-11] 실패 요약 배너 "↓ 실패 URL로 이동" — 첫 실패 카드로 스크롤·강조
      const failJump = e.target.closest('[data-failsum-jump]');
      if (failJump) { scrollToFirstFail(); return; }
      // [2026-06-13] 중복 경고 배너 항목 클릭 → 해당 소싱처 탭으로 이동
      const dupJump = e.target.closest('[data-dupjump]');
      if (dupJump) {
        const sk = dupJump.dataset.dupjump;
        if (sk && sk !== state.currentSrc) {
          autoSave();
          state.currentSrc = sk;
          state.openUrlId = null;
          renderRight();
          saveLastState(bundleCode, state.currentSrc, null);
        }
        return;
      }
      const tab = e.target.closest('[data-src-tab]');
      if (tab) {
        if (tab.dataset.srcTab !== state.currentSrc) {
          autoSave();  // fire-and-forget
        }
        state.currentSrc = tab.dataset.srcTab;
        state.openUrlId = null;
        renderRight();
        saveLastState(bundleCode, state.currentSrc, null);
        return;
      }
      // 매트릭스 헤더 (col/row/corner/group) — 활성 옵션 한정 일괄 토글
      const colH = e.target.closest('[data-url-col-axis]');
      if (colH) { toggleUrlHeaderRange(colH); return; }
      const rowH = e.target.closest('[data-url-row-axis]');
      if (rowH) { toggleUrlHeaderRange(rowH); return; }
      const cornerH = e.target.closest('[data-url-corner-axes]');
      if (cornerH) { toggleUrlCorner(cornerH); return; }
      const grpH = e.target.closest('[data-url-grp-axis]');
      if (grpH) { toggleUrlGroup(grpH.dataset.urlGrpAxis, grpH.dataset.urlGrpVal); return; }
      // [2026-05-27] URL 추가 — prompt 제거, 빈 카드 직접 추가 + 자동 펼침 + URL input focus
      if (e.target.closest('[data-add-url]')) {
        if (!state.urls[state.currentSrc]) state.urls[state.currentSrc] = [];
        const newU = { tempId: state.tempIdSeq++, label: '', url: '', option_keys: [] };
        state.urls[state.currentSrc].push(newU);
        state.openUrlId = newU.tempId;
        renderRight();
        // 추가된 카드의 URL input 에 자동 focus
        setTimeout(() => {
          const card = modal.querySelector(`[data-url-id="${newU.tempId}"]`);
          const inp = card && card.querySelector('.oum-url-input');
          if (inp) inp.focus();
        }, 0);
        return;
      }
      // [2026-05-27] URL 복사 — 위 카드 그대로 복제 (바로 아래에 삽입)
      const cpBtn = e.target.closest('[data-url-copy]');
      if (cpBtn) {
        const card = cpBtn.closest('[data-url-id]');
        const tid = +card.dataset.urlId;
        const arr = state.urls[state.currentSrc] || [];
        const idx = arr.findIndex(u => u.tempId === tid);
        if (idx < 0) return;
        const src = arr[idx];
        const dup = {
          tempId: state.tempIdSeq++,
          label: src.label || '',
          url: src.url || '',
          option_keys: [...(src.option_keys || [])],
        };
        arr.splice(idx + 1, 0, dup);  // 바로 아래에 삽입
        state.openUrlId = dup.tempId;
        renderRight();
        return;
      }
      // [2026-05-27] 순서 변경은 드래그앤드랍으로 대체 — ↑/↓ 버튼 제거됨
      // URL 카드 토글 — 펼친 카드의 dbId 기록 (없으면 null)
      const card = e.target.closest('[data-url-id]');
      const tog = e.target.closest('[data-url-tog]');
      if (tog && card) {
        const tid = +card.dataset.urlId;
        state.openUrlId = (state.openUrlId === tid) ? null : tid;
        renderRight();
        const openedU = state.openUrlId ? (state.urls[state.currentSrc] || []).find(u => u.tempId === state.openUrlId) : null;
        saveLastState(bundleCode, state.currentSrc, openedU ? openedU.dbId : null);
        return;
      }
      // URL 삭제
      //   [BUG-FIX 2026-06-13] 이전엔 화면(state)에서만 제거하고 서버 DELETE 를 호출하지
      //   않아, 저장(autoSave)이 '남은 URL' 만 POST/PUT → 삭제된 행이 DB 에 영구 잔류 →
      //   새로고침 시 부활하는 버그. dbId 있으면 서버에서도 삭제하고, 실패하면 화면도 유지
      //   (조용한 실패 금지 — 화면과 DB 상태를 항상 일치시킴).
      const del = e.target.closest('[data-url-del]');
      if (del && card) {
        if (!confirm('이 URL 삭제?')) return;
        const tid = +card.dataset.urlId;
        const arr = state.urls[state.currentSrc] || [];
        const target = arr.find(u => u.tempId === tid);
        if (!target) return;
        // 진행 중인 자동 저장이 끝난 뒤 삭제 — 신규 카드가 POST 로 dbId 를 받기 전에
        // 화면에서 지워 DB 에 고아(orphan) 행이 남는 경우를 방지
        if (_autoSaveInflight) { try { await _autoSaveInflight; } catch (_) {} }
        // DB 에 이미 저장된 URL 이면 서버에서도 삭제 (dbId 없으면 화면만 제거)
        if (target.dbId) {
          del.disabled = true;
          try {
            const r = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls/${target.dbId}`, { method: 'DELETE' });
            const j = await r.json().catch(() => ({}));
            if (!r.ok || !j.ok) {
              alert('URL 삭제 실패 — 서버에서 삭제하지 못했습니다.\n새로고침 후 다시 시도해 주세요.');
              del.disabled = false;
              return;  // 화면에서도 제거하지 않음 → 실제(DB) 상태와 일치 유지
            }
          } catch (err) {
            console.warn('[oum] URL delete fail:', err);
            alert('URL 삭제 실패 — 네트워크 오류.\n잠시 후 다시 시도해 주세요.');
            del.disabled = false;
            return;
          }
        }
        state.urls[state.currentSrc] = arr.filter(u => u.tempId !== tid);
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

    // [v20.2 2026-05-31] 인라인 SKU/제품명 자동완성 — 미매칭/수기 행 input 에 dropdown 표시
    //   state.invOptions(모음전 외 모든 재고 옵션) 에서 brand/model_name/color/size/sku 매칭
    //   [v20.7] dropdown 을 body 직속 + position:fixed 로 띄워 그룹 details overflow:hidden 클리핑 회피
    function _removeAllInvAcDd() {
      document.querySelectorAll('.oum-inv-ac-dd').forEach(d => d.remove());
    }
    function _positionInvAcDd(dd, input) {
      const r = input.getBoundingClientRect();
      const vw = window.innerWidth, vh = window.innerHeight;
      const maxH = 280;
      // 아래 공간 우선, 부족하면 위로
      const spaceBelow = vh - r.bottom - 8;
      const spaceAbove = r.top - 8;
      const useAbove = spaceBelow < 180 && spaceAbove > spaceBelow;
      const h = Math.min(maxH, useAbove ? spaceAbove : spaceBelow);
      dd.style.position = 'fixed';
      dd.style.left = r.left + 'px';
      dd.style.width = r.width + 'px';
      dd.style.maxHeight = h + 'px';
      if (useAbove) { dd.style.bottom = (vh - r.top + 4) + 'px'; dd.style.top = ''; }
      else          { dd.style.top    = (r.bottom + 4) + 'px';   dd.style.bottom = ''; }
      dd.style.zIndex = 99999;
    }
    function showInvSearchDd(input, key) {
      _removeAllInvAcDd();  // 모든 기존 dropdown 제거 (다른 input 의 것도)
      const q = (input.value || '').trim().toLowerCase();
      if (!q || q.length < 1) return;
      // brand/model 필터 우선 + 텍스트 매칭
      // [v20.4] 사용자 직접 설정 우선
      const fb = state.invFilterUserSet.brand
        ? state.invFilter.brand
        : (state.invFilter.brand || state.invBundleMeta.brand || '');
      const fm = state.invFilterUserSet.model
        ? state.invFilter.model
        : (state.invFilter.model || state.invBundleMeta.model_name || '');
      const matched = [];
      for (const o of (state.invOptions || [])) {
        const hay = `${o.brand} ${o.model_name} ${o.color} ${o.size} ${o.sku}`.toLowerCase();
        if (!hay.includes(q)) continue;
        let score = 0;
        if (fb && o.brand === fb) score += 10;
        if (fm && o.model_name === fm) score += 10;
        matched.push({ o, score });
        if (matched.length > 30) break;  // 안전 cap
      }
      matched.sort((a, b) => b.score - a.score);
      if (!matched.length) return;
      // dropdown DOM
      const dd = document.createElement('div');
      dd.className = 'oum-inv-ac-dd';
      dd.setAttribute('data-key', key);
      let html = '';
      matched.slice(0, 15).forEach((m, i) => {
        const o = m.o;
        const stock = (o.stock_total != null) ? o.stock_total : 0;
        const stockHtml = stock > 0 ? `<span class="stk">📦 ${stock}개</span>` : '<span class="stk zero">📦 0개</span>';
        html += `<div class="oum-inv-ac-it ${i===0?'kbd-hl':''}" data-inv-pick-sku="${esc(o.sku)}" data-inv-pick-key="${esc(key)}">
          <div class="nm">${esc(o.brand)} ${esc(o.model_name)} ${esc(o.color)} ${esc(o.size)}</div>
          <div class="meta">${esc(o.sku)} ${stockHtml}</div>
        </div>`;
      });
      dd.innerHTML = html;
      // [v20.7] body 직속 + position:fixed → 그룹 details overflow:hidden 클리핑 회피
      document.body.appendChild(dd);
      _positionInvAcDd(dd, input);
      // input ↔ dd 연결 (이벤트 핸들러용)
      dd.__sourceInput = input;
      input.__activeDd = dd;
    }

    // [v20.1 2026-05-31] 브랜드/모델 input 자동완성 — typing 시 dropdown 필터
    function filterDdItems(input, ddSel, itemSel, getTextFn) {
      const dd = input.parentElement.querySelector(ddSel);
      if (!dd) return [];
      dd.style.display = 'block';
      const q = (input.value || '').trim().toLowerCase();
      let visibleItems = [];
      dd.querySelectorAll(itemSel).forEach(it => {
        const txt = (getTextFn ? getTextFn(it) : it.textContent).toLowerCase();
        const show = !q || txt.includes(q);
        it.style.display = show ? '' : 'none';
        if (show) visibleItems.push(it);
      });
      // 첫 visible item 강조 (keyboard nav 용)
      dd.querySelectorAll('.kbd-hl').forEach(x => x.classList.remove('kbd-hl'));
      if (visibleItems[0]) visibleItems[0].classList.add('kbd-hl');
      return visibleItems;
    }
    // [v20.7] body 직속 dropdown 클릭 → 매핑 확정 (body 레벨 핸들러)
    function _handleInvAcPickClick(e) {
      const acPick = e.target.closest('[data-inv-pick-sku]');
      if (!acPick) {
        // 외부 클릭 시 dropdown 닫기 (input 도 제외)
        if (!e.target.closest('[data-inv-search-key]')) _removeAllInvAcDd();
        return;
      }
      const pickSku = acPick.dataset.invPickSku;
      const k = acPick.dataset.invPickKey;
      const skuByKey = state.skuByKey || {};
      const bSku = skuByKey[k];
      if (bSku) {
        const inv = (state.invOptions || []).find(o => o.sku === pickSku);
        state.invRows[bSku] = {
          invSku: pickSku,
          model: inv ? inv.model_name : '',
          color: inv ? inv.color : '',
          size: inv ? inv.size : '',
          isManual: true,
          isUnused: false,
        };
        state.invMappedKeys.add(k);
      }
      _removeAllInvAcDd();
      renderRight();
    }
    document.addEventListener('click', _handleInvAcPickClick);
    // 모달 닫힐 때 핸들러 제거 + dropdown 정리
    bg.addEventListener('click', e => { if (e.target === bg) { document.removeEventListener('click', _handleInvAcPickClick); _removeAllInvAcDd(); } });
    // 스크롤 시 dropdown 재배치
    document.addEventListener('scroll', () => {
      document.querySelectorAll('.oum-inv-ac-dd').forEach(dd => {
        if (dd.__sourceInput && document.body.contains(dd.__sourceInput)) {
          _positionInvAcDd(dd, dd.__sourceInput);
        } else {
          dd.remove();
        }
      });
    }, true);

    // [v20.1/v20.2] 키보드 — Enter(첫매칭 선택) / Esc(닫기) / ArrowUp/Down(이동)
    $('#oum-right').addEventListener('keydown', e => {
      // [v20.2] 인라인 SKU 검색 input — Enter 시 첫 매칭 자동 선택
      const acInp = e.target.closest('[data-inv-search-key]');
      if (acInp) {
        // [v20.7] dropdown 이 body 직속이라 input.__activeDd 로 직접 참조
        const dd = acInp.__activeDd || document.querySelector('.oum-inv-ac-dd');
        if (!dd) return;
        const visible = [...dd.querySelectorAll('.oum-inv-ac-it')];
        const curHl = dd.querySelector('.oum-inv-ac-it.kbd-hl');
        const curIdx = visible.indexOf(curHl);
        if (e.key === 'Enter') {
          e.preventDefault();
          (curHl || visible[0])?.click();
          return;
        }
        if (e.key === 'Escape') { e.preventDefault(); dd.remove(); acInp.blur(); return; }
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (curHl) curHl.classList.remove('kbd-hl');
          const next = visible[Math.min(curIdx + 1, visible.length - 1)] || visible[0];
          if (next) { next.classList.add('kbd-hl'); next.scrollIntoView({block:'nearest'}); }
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (curHl) curHl.classList.remove('kbd-hl');
          const prev = visible[Math.max(curIdx - 1, 0)] || visible[visible.length - 1];
          if (prev) { prev.classList.add('kbd-hl'); prev.scrollIntoView({block:'nearest'}); }
          return;
        }
        return;
      }
      const isBr = e.target.id === 'oum-br-in';
      const isMd = e.target.id === 'oum-md-in' && !e.target.disabled;
      if (!isBr && !isMd) return;
      const ddSel = isBr ? '.oum-br-dd' : '.oum-md-dd';
      const itemSel = isBr ? '.oum-br-it' : '.oum-md-it';
      const dd = e.target.parentElement.querySelector(ddSel);
      if (!dd) return;
      const visible = [...dd.querySelectorAll(itemSel)].filter(it => it.style.display !== 'none');
      const curHl = dd.querySelector('.kbd-hl');
      const curIdx = visible.indexOf(curHl);
      if (e.key === 'Enter') {
        e.preventDefault();
        const pick = curHl || visible[0];
        if (!pick) return;
        const brName = pick.dataset.brName;
        const mdName = pick.dataset.mdName;
        if (brName !== undefined) {
          state.invFilter.brand = brName;
          state.invFilter.model = '';
          renderRight();
        } else if (mdName !== undefined) {
          state.invFilter.model = mdName;
          renderRight();
        } else if (pick.dataset.brClear !== undefined) {
          state.invFilter.brand = '';
          state.invFilter.model = '';
          renderRight();
        }
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        dd.style.display = 'none';
        e.target.blur();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (curHl) curHl.classList.remove('kbd-hl');
        const next = visible[Math.min(curIdx + 1, visible.length - 1)] || visible[0];
        if (next) { next.classList.add('kbd-hl'); next.scrollIntoView({block: 'nearest'}); }
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (curHl) curHl.classList.remove('kbd-hl');
        const prev = visible[Math.max(curIdx - 1, 0)] || visible[visible.length - 1];
        if (prev) { prev.classList.add('kbd-hl'); prev.scrollIntoView({block: 'nearest'}); }
        return;
      }
    });
    $('#oum-right').addEventListener('input', e => {
      // [v20.1] 브랜드 input 자동완성
      if (e.target.id === 'oum-br-in') {
        filterDdItems(e.target, '.oum-br-dd', '.oum-br-it', it => {
          const nm = it.querySelector('.nm');
          return (nm ? nm.textContent : it.textContent);
        });
        return;
      }
      // [v20.1] 모델 input 자동완성
      if (e.target.id === 'oum-md-in' && !e.target.disabled) {
        filterDdItems(e.target, '.oum-md-dd', '.oum-md-it', it => {
          const nm = it.querySelector('.nm');
          return (nm ? nm.textContent : it.textContent);
        });
        return;
      }
      // [v20] 새 oum-inv-search input — 수기 입력 시 invRows 갱신 + 자동완성 dropdown
      const searchInp = e.target.closest('[data-inv-search-key]');
      if (searchInp) {
        const k = searchInp.dataset.invSearchKey;
        const skuByKey = state.skuByKey || {};
        const bSku = skuByKey[k];
        // [v20.2] 자동완성 dropdown — invOptions 필터링
        showInvSearchDd(searchInp, k);
        if (!bSku) return;
        if (!state.invRows[bSku]) state.invRows[bSku] = {};
        state.invRows[bSku].invSku = searchInp.value.trim();
        state.invRows[bSku].isManual = true;
        if (searchInp.value.trim()) state.invMappedKeys.add(k);
        else state.invMappedKeys.delete(k);
        return;
      }
      const invInp = e.target.closest('[data-inv-fld]');
      if (invInp) {
        const k = invInp.dataset.key;
        const fld = invInp.dataset.invFld;
        const skuByKey = state.skuByKey || {};
        const bSku = skuByKey[k];
        if (!bSku) return;
        if (!state.invRows[bSku]) state.invRows[bSku] = {};
        state.invRows[bSku][fld] = invInp.value;
        state.invRows[bSku].isManual = true;  // 사용자 수정 → 수동 표시
        // 매트릭스 셀 색 갱신 (invMappedKeys)
        if (fld === 'invSku') {
          if (invInp.value.trim()) state.invMappedKeys.add(k);
          else state.invMappedKeys.delete(k);
        }
        // 상태 chip 갱신 + 행 배경만 부분 갱신 (전체 rerender 피함)
        const tr = invInp.closest('tr');
        if (tr) {
          tr.classList.remove('auto-matched');
          tr.classList.add('manual');
          const statTd = tr.querySelector('td:last-child');
          if (statTd && state.invRows[bSku].invSku) {
            statTd.innerHTML = '<span class="stat-manual">수정</span>';
          }
        }
        return;
      }
      // 우측 input 변경 (label / url)
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

    // ─── 우측 매트릭스 헤더 일괄 토글 (좌측 옵션 매트릭스와 동등) ───
    //   활성 옵션(state.selected) 중에서만 토글 — 비활성 셀은 건드리지 않음
    function toggleUrlHeaderRange(el) {
      const u = currentUrl();
      if (!u) return;
      const isCol = !!el.dataset.urlColAxis;
      const axisName = isCol ? el.dataset.urlColAxis : el.dataset.urlRowAxis;
      const val = isCol ? el.dataset.urlColVal : el.dataset.urlRowVal;
      let base = [];
      try { base = JSON.parse(el.dataset.urlBase || '[]'); } catch (e) {}
      const valid = validAxes();
      const ax = String(axisName == null ? '' : axisName).trim();
      const axisIdx = valid.findIndex(a => String(a.name || '').trim() === ax);
      if (axisIdx < 0) return;
      const allCombos = cartesian(valid.map(a => a.values));
      const matching = allCombos.filter(c => {
        if (c[axisIdx] !== val) return false;
        if (!base.every(b => c[b.idx] === b.val)) return false;
        return state.selected.has(keyOf(c));
      });
      if (!matching.length) return;
      applyUrlToggle(u, matching);
    }

    function toggleUrlCorner(el) {
      const u = currentUrl();
      if (!u) return;
      let base = [];
      try { base = JSON.parse(el.dataset.urlCornerAxes || '[]'); } catch (e) {}
      const valid = validAxes();
      const allCombos = cartesian(valid.map(a => a.values));
      const matching = allCombos.filter(c =>
        base.every(b => c[b.idx] === b.val) && state.selected.has(keyOf(c)));
      if (!matching.length) return;
      applyUrlToggle(u, matching);
    }

    function toggleUrlGroup(axisName, val) {
      const u = currentUrl();
      if (!u) return;
      const valid = validAxes();
      const ax = String(axisName == null ? '' : axisName).trim();
      const axisIdx = valid.findIndex(a => String(a.name || '').trim() === ax);
      if (axisIdx < 0) return;
      const allCombos = cartesian(valid.map(a => a.values));
      const matching = allCombos.filter(c =>
        c[axisIdx] === val && state.selected.has(keyOf(c)));
      if (!matching.length) return;
      applyUrlToggle(u, matching);
    }

    function applyUrlToggle(u, combos) {
      const set = new Set(u.option_keys);
      const allOn = combos.every(c => set.has(keyOf(c)));
      combos.forEach(c => {
        const k = keyOf(c);
        if (allOn) set.delete(k);
        else set.add(k);
      });
      u.option_keys = [...set];
      renderRight();
    }

    // ─── 자동 저장 ───────────────────────────────────────────────
    //   가로 탭 전환·모달 닫기 직전 호출 — 옵션·URL·매핑 모두 저장
    //   실패는 console.warn 만 — 사용자 알림 X (사용자 결정)
    //   - 새 URL 카드 (dbId 없음) → POST → 응답 id 를 dbId 로 설정
    //   - 기존 URL (dbId 있음) → PUT
    //   - 옵션 매트릭스 매핑(option_keys) → axis_values → canonical_sku 변환 → option_ids
    // [2026-05-27] inflight 중 새 호출 오면 pending 표시 → 첫 호출 끝나면 한 번 더 실행
    //   탭 빠르게 전환해도 마지막 상태가 반드시 저장됨
    let _autoSaveInflight = null;
    let _autoSavePending = false;
    async function autoSave() {
      if (!state.selected.size || !state.applied) return;
      // 중복 호출 — pending 표시만 하고 첫 promise 만 기다림 (실제 저장은 첫 promise 의 do-while 가 처리)
      if (_autoSaveInflight) { _autoSavePending = true; try { await _autoSaveInflight; } catch (e) {} return; }
      _autoSaveInflight = (async () => {
        // do-while 로 pending 플래그 처리 — 도중에 들어온 변경도 한 번 더 저장
        do {
          _autoSavePending = false;
        try {
          // 1. 옵션 콤보 (prune=true) — selected 와 동기화
          const validList = validAxes();
          const selectedArr = [...state.selected].map(getAxisValuesArray);
          await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/options/combo`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ steps: validList, selected: selectedArr, prune: true }),
          });

          // 2. 옵션 axis_values → canonical_sku 매핑 재로딩
          const r = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls`);
          const j = await r.json();
          const skuByKey = {};
          if (j && Array.isArray(j.options)) {
            j.options.forEach(o => {
              if (Array.isArray(o.axis_values)) {
                skuByKey[JSON.stringify(o.axis_values.map(v => String(v)))] = o.canonical_sku;
              }
            });
          }

          // 3. 각 URL 카드 저장 — POST(new) / PUT(existing) + option_ids + sort_order (배열 인덱스)
          //   [v27 2026-06-02] 병렬화 — for-await 순차 처리에서 Promise.all 로 변경.
          //   기존: 41개 URL × ~50ms = 2초+ 직렬. 변경 후: 41개 동시 = ~200ms.
          //   PUT/POST 페이로드·endpoint·DB 동작 100% 그대로. 처리 순서만 병렬.
          const urlSavePromises = [];
          for (const sk of Object.keys(state.urls)) {
            const arr = state.urls[sk] || [];
            for (let i = 0; i < arr.length; i++) {
              const u = arr[i];
              if (!u.url || !u.url.trim()) continue;
              const option_ids = (u.option_keys || [])
                .map(k => skuByKey[k])
                .filter(Boolean);
              const task = (async () => {
                try {
                  if (u.dbId) {
                    await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls/${u.dbId}`, {
                      method: 'PUT', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ url: u.url.trim(), label: u.label || null, url_type: u.url_type || '', option_ids, sort_order: i }),
                    });
                  } else {
                    const res = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls`, {
                      method: 'POST', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ source_key: sk, url: u.url.trim(), label: u.label || null, url_type: u.url_type || '', option_ids }),
                    });
                    const rj = await res.json();
                    if (rj && rj.id) u.dbId = rj.id;
                  }
                } catch (e) {
                  console.warn('[oum] auto-save URL fail:', e);
                }
              })();
              urlSavePromises.push(task);
            }
          }
          await Promise.all(urlSavePromises);
        } catch (e) {
          console.warn('[oum] auto-save fail:', e);
        }
        } while (_autoSavePending);  // pending 있으면 한 번 더
      })();
      try { await _autoSaveInflight; } finally { _autoSaveInflight = null; _autoSavePending = false; }
    }

    // 모달 닫기 / 저장 — X·취소 클릭 시 자동 저장 fire-and-forget + 마지막 상태 기록
    function snapshotLastState() {
      const openedU = state.openUrlId ? (state.urls[state.currentSrc] || []).find(u => u.tempId === state.openUrlId) : null;
      saveLastState(bundleCode, state.currentSrc, openedU ? openedU.dbId : null);
    }
    $('.oum-mh .close').addEventListener('click', () => { snapshotLastState(); hideSharedTip(); autoSave(); bg.remove(); });
    $('#oum-cancel').addEventListener('click', () => { snapshotLastState(); hideSharedTip(); autoSave(); bg.remove(); });

    // [2026-05-26 BUG-FIX] [저장] 버튼은 이전에 dbId 검사 없이 무조건 POST 했음 → 누를 때마다
    //   같은 URL 카드가 새로 생성되어 누적되는 심각한 버그. autoSave() 로 통일 — dbId 있으면 PUT,
    //   없으면 POST 후 응답.id 를 dbId 로 설정. matrix option_ids 매핑도 함께 저장.
    $('#oum-save').addEventListener('click', async () => {
      if (!state.selected.size) return;
      const save = $('#oum-save');
      save.disabled = true; save.textContent = '저장 중...';

      try {
        snapshotLastState();
        await autoSave();
        if (typeof flash === 'function') flash('저장 완료');
        bg.remove();
        // [v27 2026-06-02] reload 대기 700 → 200ms — 체감 즉시 갱신
        setTimeout(() => location.reload(), 200);
      } catch (e) {
        alert('저장 중 오류: ' + e.message);
        save.disabled = false; save.textContent = '옵션 + URL 저장';
      }
    });

    // 초기 렌더 — source-urls 만으로 옵션 매트릭스·URL UI 즉시 표시 (재고 매핑 기다리지 않음)
    rerender();

    // [2026-06-11] 매트릭스 "URL N개 실패" 카드 클릭으로 들어온 경우 — 첫 실패 URL 로 자동 이동.
    //   렌더 직후 DOM 이 준비되면 1회만 스크롤·강조 (실패 카드 없으면 조용히 skip).
    if (_pendingFailScroll) {
      _pendingFailScroll = false;
      setTimeout(() => { try { scrollToFirstFail(); } catch (e) {} }, 120);
    }

    // [perf 2026-05-29] 재고 매핑은 배경 로드 → 도착 시 셀 초록색·재고탭 갱신.
    //   모달 표시·옵션 작업은 이미 가능한 상태. 데이터 도착이 늦어도 UI 안 막힘.
    if (_invMapPromise) {
      _invMapPromise.then(ij => {
        applyInvData(ij);
        rerender();
      }).catch(() => { /* 재고 매핑 실패해도 모달은 정상 동작 */ });
    }
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

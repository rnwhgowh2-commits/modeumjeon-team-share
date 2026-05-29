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

      .oum-split { display:grid; grid-template-columns:1fr 70px 1fr; gap:0; align-items:stretch; }

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
      .oum-axis-chips { display:flex; flex-wrap:wrap; gap:7.5px; }
      .oum-axis-chips .c { background:#EFF6FF; color:#1d4ed8; border-radius:18px; padding:9px 16.5px; font-size:20.25px; }
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
      .oum-cell.mapped-off { background:#F3F4F6 !important; color:#9CA3AF !important; border:1px dashed #D1D6DB; cursor:not-allowed; }  /* ⬜ 옅음 — 비활성/미선택 */
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
      .oum-rt-tabs { display:flex; gap:4px; border-bottom:2px solid #E5E8EB; margin-bottom:14px; padding:0 4px; }
      .oum-rt-tab { background:transparent; border:0; padding:11px 18px; font:inherit; font-size:14.5px; font-weight:700; color:#8B95A1; cursor:pointer; border-bottom:3px solid transparent; margin-bottom:-2px; display:inline-flex; align-items:center; gap:7px; }
      .oum-rt-tab.on { color:#03A65A; border-bottom-color:#03A65A; }
      .oum-rt-tab .cnt { background:#F2F4F6; color:#8B95A1; padding:1px 8px; border-radius:99px; font-size:11.5px; font-weight:700; }
      .oum-rt-tab.on .cnt { background:#F0FDF4; color:#03A65A; }
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
  async function openOptionUrlModal(bundleCode) {
    if (!bundleCode) { alert('모음전 코드를 찾을 수 없어요.'); return; }
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
          <b style="color:#191F28;">📖 셀 색 의미 (시안 v6 누적):</b>
          <span><span class="leg-empty"></span>비활성·미선택</span>
          <span><span class="leg-gray"></span>옵션 ON</span>
          <span><span class="leg-blue"></span>+ URL 매핑</span>
          <span><span class="leg-green"></span>+ 재고 매핑</span>
          <span style="margin-left:auto; color:#92400E;">💡 좌측에서 옵션 만들고 [URL 매핑에 적용 →]</span>
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

    // 소싱처 목록 + 기존 옵션 로드 (기존 모음전 GET 활용)
    try {
      // [perf 2026-05-29] 두 요청 병렬화 — inventory-mapping 을 먼저 띄워두고
      //   source-urls 처리와 동시에 진행 (기존: 순차 await → 대기시간 합산).
      const _invMapPromise = fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/inventory-mapping`)
        .then(res => res.json()).catch(() => null);
      const r = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls`);
      const j = await r.json();
      if (j && j.ok) {
        state.sources = (j.sources || []).map(k => ({ key: k, label: k }));
        // [2026-05-25] 옵션 canonical_sku ↔ axis values key 매핑 — 매핑 복원·자동저장 공용
        //   재진입 시 option_ids 를 option_keys 로 복원해야 매트릭스 매핑이 살아 있음
        const keyBySku = {};
        const skuByKey = {};
        (j.options || []).forEach(o => {
          if (Array.isArray(o.axis_values)) {
            const k = JSON.stringify(o.axis_values.map(v => String(v)));
            keyBySku[o.canonical_sku] = k;
            skuByKey[k] = o.canonical_sku;
          }
        });
        state.skuByKey = skuByKey;

        // [2026-05-29 시안 v6/v3 B3-3] 재고 매핑 fetch — 셀 색·도트 + 우측 매핑 표
        //   GET /api/bundles/<code>/inventory-mapping → {bundle_sku: [inv_sku, ...], candidates, inventory_options}
        state.invMappedKeys = new Set();
        state.invRows = {};
        state.invCandidates = {};
        state.invOptions = [];
        try {
          const ij = await _invMapPromise;  // [perf] 위에서 병렬로 띄운 결과 수령
          if (ij && ij.ok) {
            state.invOptions = ij.inventory_options || [];
            state.invCandidates = ij.candidates || {};
            // 옵션 SKU 별 매핑 풀어서 invRows + invMappedKeys
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
        } catch (_e) { /* ignore — 재고 매핑 없어도 모달 동작 */ }
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
    if (savedSrc && state.sources.find(s => s.key === savedSrc)) {
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

      // [2026-05-24] 빠른 선택 칩 영역 제거 — 사용자 피드백 (매트릭스 행/열 헤더 클릭으로 충분)

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

    // [2026-05-29 시안 v6 E3] 셀 클래스 + 라벨 통합 결정
    //   active = 옵션 ON (state.selected.has) | urlMapped = 이 URL 에 매핑 (우측만 의미) | hasInv = 재고 매핑 있음
    //   반환: { cls, inner } — 우선순위 has-inv > url-on > opt-on > disabled
    function cellState(active, urlMapped, hasInv) {
      if (!active) return { cls: 'disabled', inner: '<span>·</span>' };
      if (hasInv)   return { cls: 'opt-on has-inv', inner: '<span>✓</span><span class="tag">+재고</span>' };
      if (urlMapped) return { cls: 'opt-on url-on', inner: '<span>✓</span><span class="tag">+URL</span>' };
      return { cls: 'opt-on', inner: '<span>✓</span><span class="tag">옵션</span>' };
    }

    function renderMatrix1D(axis) {
      const valid = validAxes();
      let html = `<table class="oum-mtx-table"><tbody><tr>`;
      axis.values.forEach(v => {
        const k = keyOf([v]);
        const on = state.selected.has(k);
        const mappedOff = !on && state.mappedOff && state.mappedOff.has(k);
        const active = on || mappedOff;
        const hasInv = active && state.invMappedKeys && state.invMappedKeys.has(k);
        // 좌측 매트릭스: URL 매핑은 표시 안 함 (우측에서) → urlMapped=false
        const s = cellState(active, false, hasInv);
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
          const mappedOff = !on && state.mappedOff && state.mappedOff.has(k);
          const active = on || mappedOff;
          const hasInv = active && state.invMappedKeys && state.invMappedKeys.has(k);
          const s = cellState(active, false, hasInv);
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

    // [시안 v3 B3-3] 재고관리 매핑 패널 — in-place 표
    function renderInvPanel() {
      // 좌측에서 활성한 옵션 (selected) 들의 axis_values 기준 매트릭스 셀 = 행
      const selectedKeys = [...state.selected];
      // skuByKey 가 있으면 옵션 SKU 도. 없으면 임시 키.
      const skuByKey = state.skuByKey || {};

      // 자동 매칭 / 수동 / 미사용 카운트
      let autoN = 0, manualN = 0, unusedN = 0;
      selectedKeys.forEach(k => {
        const bSku = skuByKey[k];
        if (!bSku) { unusedN++; return; }
        const row = state.invRows[bSku];
        if (!row || !row.invSku) { unusedN++; return; }
        if (row.isManual) manualN++;
        else autoN++;
      });

      let html = '<div class="oum-inv-toolbar">';
      html += `<span><b style="color:#92400E">📋 자동 매칭</b> · 옵션 ${autoN}건 / 수동 ${manualN}건 / 미사용 ${unusedN}건</span>`;
      html += `<button class="auto-btn" data-inv-auto type="button">⚡ 재고관리 자동 매칭</button>`;
      html += '</div>';

      if (!state.applied) {
        html += `<div style="padding:60px 20px; text-align:center; color:#9ca3af; background:#fff; border:2px dashed #FBBF24; border-radius:8px;">
          <div style="font-size:32px; margin-bottom:10px;">⬅</div>
          <div style="font-size:13px; font-weight:600; color:#92400E;">좌측에서 옵션 만들고 [적용 →] 클릭하면 활성화</div>
        </div>`;
        return html;
      }

      // B3-3 표 — 매트릭스 셀별 행
      html += '<div style="overflow:auto; max-height:60vh">';
      html += '<table class="oum-inv-tbl"><thead><tr>';
      html += '<th style="width:130px">매트릭스 셀</th>';
      html += '<th style="width:130px">재고관리 SKU</th>';
      html += '<th>모델</th>';
      html += '<th>색상</th>';
      html += '<th style="width:70px">사이즈</th>';
      html += '<th style="width:70px">상태</th>';
      html += '</tr></thead><tbody>';

      if (selectedKeys.length === 0) {
        html += '<tr><td colspan="6" style="text-align:center; padding:30px; color:#9CA3AF">좌측 매트릭스에서 옵션 선택 후 [적용→] 클릭</td></tr>';
      } else {
        selectedKeys.forEach(k => {
          const bSku = skuByKey[k];
          const row = (bSku && state.invRows[bSku]) || { invSku: '', model: '', color: '', size: '', isManual: false };
          const cellLabel = k.replace(/^\[/, '').replace(/\]$/, '').replace(/","/g, ' × ').replace(/"/g, '');
          let cls = '';
          let stat = '';
          if (row.invSku) {
            if (row.isManual) { cls = 'manual'; stat = '<span class="stat-manual">수정</span>'; }
            else { cls = 'auto-matched'; stat = '<span class="stat-ok">✓ 자동</span>'; }
          } else {
            cls = ''; stat = '<span class="stat-empty">미매칭</span>';
          }
          html += `<tr class="${cls}" data-inv-row='${esc(k)}'>`;
          html += `<td>${esc(cellLabel)}</td>`;
          html += `<td><input class="sku-mono" data-inv-fld="invSku" data-key='${esc(k)}' value="${esc(row.invSku || '')}" placeholder="SKU-XXXXXXXX"></td>`;
          html += `<td><input data-inv-fld="model" data-key='${esc(k)}' value="${esc(row.model || '')}" placeholder="모델"></td>`;
          html += `<td><input data-inv-fld="color" data-key='${esc(k)}' value="${esc(row.color || '')}" placeholder="색상"></td>`;
          html += `<td><input data-inv-fld="size" data-key='${esc(k)}' value="${esc(row.size || '')}" placeholder="사이즈"></td>`;
          html += `<td>${stat}</td>`;
          html += '</tr>';
        });
      }
      html += '</tbody></table>';
      html += '</div>';

      // 범례 + 액션
      html += '<div class="oum-inv-foot">';
      html += `<span><span class="legend-sw" style="background:#F0FDF4; border:1px solid #BBF7D0"></span>자동 매칭 ${autoN}건</span>`;
      html += `<span><span class="legend-sw" style="background:#FFFBEB; border:1px solid #F59E0B"></span>수동 입력 ${manualN}건</span>`;
      html += `<button class="apply-btn" data-inv-apply type="button">💾 ${selectedKeys.length}건 적용</button>`;
      html += '</div>';
      return html;
    }

    // ─── 우측 렌더 (시안 v3 C3 — 2탭 분기) ───
    function renderRight() {
      const right = $('#oum-right');
      const totalActive = state.selected.size;
      const urlCount = countAllUrls();
      const invCount = Object.keys(state.invRows || {}).filter(k => (state.invRows[k] || {}).invSku).length;

      // 탭 nav (항상)
      let html = `<div class="oum-rt-tabs">
        <button class="oum-rt-tab ${state.rightTab === 'url' ? 'on' : ''}" data-rt-tab="url" type="button">📍 소싱처 URL 매핑 <span class="cnt">${urlCount}</span></button>
        <button class="oum-rt-tab ${state.rightTab === 'inv' ? 'on' : ''}" data-rt-tab="inv" type="button">📋 재고관리 매핑 <span class="cnt">${invCount}</span></button>
      </div>`;

      if (state.rightTab === 'inv') {
        html += renderInvPanel();
        right.innerHTML = html;
        return;
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

      // [2026-05-27 B1] URL input 옆에 ↗ 바로가기 버튼 — URL 있을 때만 표시
      const goBtn = u.url && u.url.trim()
        ? `<a class="oum-url-go" href="${esc(u.url)}" target="_blank" rel="noopener noreferrer" title="새 탭에서 열기">↗</a>`
        : '';
      // [2026-05-27] 드래그앤드랍 — 카드 전체 draggable + 드래그 핸들 ⋮⋮ 표시
      //   복사 ⎘ 버튼은 유지 (시안 v8 선택 후 디자인 교체 예정)
      let html = `<div class="oum-url-card ${isOpen ? 'open' : ''}" data-url-id="${u.tempId}" draggable="true">
        <div class="oum-url-ch">
          <span class="oum-url-drag" title="드래그해서 순서 변경" data-url-drag>⋮⋮</span>
          <span class="oum-url-num">${num}</span>
          <input class="oum-url-label" data-field="label" value="${esc(u.label)}" placeholder="라벨 (선택)">
          <input class="oum-url-input" data-field="url" value="${esc(u.url)}" placeholder="URL 입력">
          ${goBtn}
          <span class="oum-url-cnt" title="이 URL 에 매핑된 옵션 / 전체 활성 옵션">📌 <b>${mapped}</b>/${totalActive}</span>
          <button class="oum-url-tog" data-url-tog type="button">${isOpen ? '▾ 닫기' : '▸ 매핑'}</button>
          <button class="oum-url-copy" data-url-copy type="button" title="이 카드 그대로 복사">📋 복사</button>
          <button class="oum-url-del" data-url-del type="button">✕ 삭제</button>
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
      positionSharedTip(cellEl, tip);
    }

    // 셀에서 mouseout 후 일정 시간 동안 tooltip 으로 이동할 시간 (gap) 허용
    let _sharedTipCloseTimer = null;
    function scheduleSharedTipClose() {
      if (_sharedTipCloseTimer) clearTimeout(_sharedTipCloseTimer);
      _sharedTipCloseTimer = setTimeout(() => { hideSharedTip(); }, 200);
    }
    function cancelSharedTipClose() {
      if (_sharedTipCloseTimer) { clearTimeout(_sharedTipCloseTimer); _sharedTipCloseTimer = null; }
    }

    function positionSharedTip(cellEl, tip) {
      const cellRect = cellEl.getBoundingClientRect();
      const tipRect = tip.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const gap = 10;
      const margin = 8;  // viewport 가장자리 여백

      // 수직: 셀 아래 vs 위 공간 비교 — 더 큰 쪽으로 펼침
      const spaceBelow = vh - cellRect.bottom - gap - margin;
      const spaceAbove = cellRect.top - gap - margin;
      let top, placement;
      if (spaceBelow >= tipRect.height || spaceBelow >= spaceAbove) {
        // 아래로
        top = cellRect.bottom + gap;
        placement = 'below';
      } else {
        // 위로
        top = cellRect.top - tipRect.height - gap;
        placement = 'above';
      }

      // [2026-05-27] viewport 위/아래로 나가지 않게 클램프
      //   tooltip 자체 max-height:80vh + overflow-y:auto 이므로 잘림 영역은 휠 스크롤 가능
      if (top < margin) top = margin;
      if (top + tipRect.height > vh - margin) top = vh - tipRect.height - margin;
      if (top < margin) top = margin;  // 그래도 크면 위에서 잘림

      // 수평: 셀 중앙에 tooltip 중앙 맞추되 화면 밖 안 나가게 클램프
      //   [2026-05-27] vw < tipRect.width 인 좁은 화면에서도 음수 안 되게 Math.max 강화
      let left = cellRect.left + cellRect.width / 2 - tipRect.width / 2;
      const maxLeft = Math.max(margin, vw - tipRect.width - margin);
      left = Math.max(margin, Math.min(left, maxLeft));

      tip.style.top = top + 'px';
      tip.style.left = left + 'px';
      tip.classList.add(placement);

      // 화살표 — 셀 중앙 위치에 맞춰 left 보정
      const arrow = tip.querySelector('.arrow');
      if (arrow) {
        const cellCenterX = cellRect.left + cellRect.width / 2;
        const arrowLeft = cellCenterX - left;
        arrow.style.left = Math.max(12, Math.min(tipRect.width - 12, arrowLeft)) + 'px';
        arrow.style.transform = 'translateX(-50%)';
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
        console.log('[oum] 적용 클릭 — selected:', state.selected.size, 'sources:', state.sources.length);
        state.applied = true;
        rerender();
        return;
      }
      } catch (err) {
        console.error('[oum] click handler error:', err);
      }
    });

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

    function toggleAxis(axisName, val) {
      const matching = filterCombos(axisName, val);
      if (!matching.length) return;  // axis 못 찾았으면 동작 안 함
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
      // [B3-3] 재고 자동 매칭 버튼
      if (e.target.closest('[data-inv-auto]')) {
        invAutoMatch();
        renderRight();
        rerender();
        return;
      }
      // [B3-3] 적용 버튼 — 매핑 서버 저장
      if (e.target.closest('[data-inv-apply]')) {
        await invApplyMapping(bundleCode);
        return;
      }
      // [2026-05-27] 탭 전환 즉시 — autoSave 백그라운드 (사용자 대기 X)
      //   pending 큐 가드로 inflight 중 호출도 마지막 저장 보장
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

    // [B3-3] 재고관리 매핑 표 인라인 편집
    $('#oum-right').addEventListener('input', e => {
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
          for (const sk of Object.keys(state.urls)) {
            const arr = state.urls[sk] || [];
            for (let i = 0; i < arr.length; i++) {
              const u = arr[i];
              if (!u.url || !u.url.trim()) continue;
              const option_ids = (u.option_keys || [])
                .map(k => skuByKey[k])
                .filter(Boolean);
              try {
                if (u.dbId) {
                  await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls/${u.dbId}`, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: u.url.trim(), label: u.label || null, option_ids, sort_order: i }),
                  });
                } else {
                  const res = await fetch(`/api/bundles/${encodeURIComponent(bundleCode)}/source-urls`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ source_key: sk, url: u.url.trim(), label: u.label || null, option_ids }),
                  });
                  const rj = await res.json();
                  if (rj && rj.id) u.dbId = rj.id;
                }
              } catch (e) {
                console.warn('[oum] auto-save URL fail:', e);
              }
            }
          }
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

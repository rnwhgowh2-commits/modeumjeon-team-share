/* margin_settle_cell.js — 전체내역 「정산예정금액(배송비포함)」 칸 정직성 표시 (모음전 신규)

   왜 필요한가 (2026-07-25):
   ────────────────────────────────────────────────────────────
   마진 숫자 중 일부는 마켓 실정산이 아직 안 들어와 **추정치**다. 지금 화면은
   추정 줄과 실정산 줄이 똑같이 보여, 사장님이 어느 숫자를 믿어야 할지 모른다.
   · 요약 아래 색칩 3개(실정산 · 추정 · 미확인) — _moumSettleChips(rows)
     칩 자체에 마우스를 올리면 그 칸이 무슨 뜻인지 설명이 뜬다(사장님 요청).
   · 추정/미확인 줄엔 정산 칸에 작은 배지 + 호버 설명(왜 추정인지) — _moumSettleCell
     호버 = 판매→구매확정→실정산 타임라인 + 산정식(실결제×정산율) + 마켓·사유·주문.

   🔴 툴팁은 position:fixed + JS 위치계산 — 전체내역 표는 가로 스크롤(overflow) 래퍼가
     있어 position:absolute 툴팁이 표 경계에서 잘린다. fixed 는 뷰포트 기준이라 안 잘린다.

   _settle_source(pipeline): real/store=실정산 확정 · estimated=추정 ·
     unknown/none=미확인 · zero_cancel=취소완료(정산0·배지 없음).
   색은 기존 토큰 재사용 — 추정 #FFF8E1/#E6A700(badge-margin-high 계열),
     미확인 #F1EFE8/#5F5E5A(판매경로 '미확인' 칩과 동일). 실정산 줄은 원본 그대로.
   본문(margin_embed.html)은 씨앗 빌드라 직접 편집 금지 — build_margin_embed.py
     SEAM 이 이 함수를 호출한다(없으면 원본 그대로 폴백).
*/
(function (root) {
  'use strict';

  var doc = (typeof document !== 'undefined') ? document : null;
  if (doc && !doc.getElementById('moum-settle-style')) {
    var st = doc.createElement('style');
    st.id = 'moum-settle-style';
    st.textContent = [
      '.moum-sbadge{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px;white-space:nowrap;cursor:help;position:relative;margin-left:6px;vertical-align:middle}',
      '.moum-sbadge.est{background:#FFF8E1;color:#E6A700}',
      '.moum-sbadge.unk{background:#F1EFE8;color:#5F5E5A}',
      /* 툴팁 — position:fixed 라 표 overflow 래퍼에 안 잘린다(좌표는 JS가 hover 때 넣는다) */
      '.moum-stip{position:fixed;left:-9999px;top:0;opacity:0;visibility:hidden;transition:opacity .12s;z-index:99999;pointer-events:none;background:#fff;border:1px solid #e5e8eb;box-shadow:0 14px 40px rgba(0,0,0,.18);border-radius:16px;padding:22px 26px;width:640px;max-width:calc(100vw - 24px);text-align:left;white-space:normal;font-weight:400;color:#191F28}',
      '.moum-sbadge:hover .moum-stip,.moum-sbadge:focus .moum-stip{opacity:1;visibility:visible}',
      '.moum-tl{display:flex;align-items:center;margin:4px 0 20px}',
      '.moum-tl .st{display:flex;flex-direction:column;align-items:center;flex:1}',
      '.moum-tl .dot{width:17px;height:17px;border-radius:50%;border:3px solid #e5e8eb;background:#fff}',
      '.moum-tl .dot.done{background:#1AB053;border-color:#1AB053}',
      '.moum-tl .dot.now{background:#E6A700;border-color:#E6A700;box-shadow:0 0 0 6px #FFF8E1}',
      '.moum-tl .bar{height:3px;flex:1;background:#e5e8eb}',
      '.moum-tl .bar.done{background:#1AB053}',
      '.moum-tl .cap{font-size:15px;color:#8a929b;margin-top:8px;text-align:center;line-height:1.4}',
      '.moum-tl .cap.on{color:#E6A700;font-weight:700}',
      '.moum-scalc{font-size:20px;color:#B7791F;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.5}',
      '.moum-srs{font-size:17px;color:#4b5563;line-height:1.65;margin-top:14px}',
      '.moum-srs b{color:#B7791F}',
      '.moum-so{font-size:14px;color:#adb5bd;margin-top:14px}',
      '.moum-schips{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}',
      '.moum-schip{position:relative;display:flex;flex-direction:column;gap:1px;border-radius:9px;padding:7px 14px 6px;border:1px solid;min-width:106px;cursor:pointer;transition:filter .1s}',
      '.moum-schip:hover{filter:brightness(0.97)}',
      '.moum-schip .lbl{font-size:11px;font-weight:600;display:flex;align-items:center;gap:5px}',
      '.moum-schip .num{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}',
      '.moum-schip .num small{font-size:12px;font-weight:500;margin-left:1px}',
      '.moum-schip.real{background:#E7F7EF;border-color:#B7E9CE;color:#12864a}',
      '.moum-schip.est{background:#FFF8E1;border-color:#F0DDB4;color:#B7791F}',
      '.moum-schip.unk{background:#F1EFE8;border-color:#DEE2E6;color:#5F5E5A}',
      '.moum-schip:hover .moum-stip,.moum-schip:focus .moum-stip{opacity:1;visibility:visible}',
      '.moum-schip .moum-stip{color:#4b5563;font-size:17px;line-height:1.7}',
      '.moum-schip .moum-stip b{color:#191F28}',
      '.moum-sw{width:8px;height:8px;border-radius:50%;display:inline-block}'
    ].join('');
    (doc.head || doc.documentElement).appendChild(st);

    /* 🔴 fixed 툴팁 위치 — hover/focus 대상의 화면 좌표 아래(공간 부족하면 위)에 붙인다. */
    var place = function (trigger) {
      var tip = trigger.querySelector('.moum-stip');
      if (!tip) return;
      var r = trigger.getBoundingClientRect();
      var vw = window.innerWidth || 1200, vh = window.innerHeight || 800;
      var tw = tip.offsetWidth || 288, th = tip.offsetHeight || 130;
      var left = Math.min(Math.max(8, r.left + r.width / 2 - tw / 2), vw - tw - 8);
      var below = r.bottom + 8;
      var top = (below + th > vh - 8 && r.top - th - 8 > 8) ? (r.top - th - 8) : below;
      tip.style.left = left + 'px';
      tip.style.top = Math.max(8, top) + 'px';
    };
    var onEnter = function (e) {
      var t = e.target && e.target.closest && e.target.closest('.moum-sbadge,.moum-schip');
      if (t && t.querySelector('.moum-stip')) place(t);
    };
    doc.addEventListener('mouseover', onEnter, true);
    doc.addEventListener('focusin', onEnter, true);
  }

  function esc0(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function num(v) {
    var n = parseFloat(String(v == null ? '' : v).replace(/,/g, ''));
    return isNaN(n) ? null : n;
  }
  function won(v) {
    var n = num(v);
    return n == null ? '—' : Math.round(n).toLocaleString();
  }
  function pick(r, keys) {
    for (var i = 0; i < keys.length; i++) {
      var v = r && r[keys[i]];
      if (v != null && String(v).trim() !== '') return String(v).trim();
    }
    return '';
  }
  function dateOnly(s) { return String(s || '').trim().split(' ')[0]; }

  /* 주문상태 → 사유 + 타임라인 '지금' 위치. 추측 없이 상태 문자열로만 판정. */
  function stateInfo(status) {
    var s = String(status || '');
    if (s.indexOf('구매확정') >= 0)
      return { reason: '구매확정은 됐지만 실정산이 아직 안 들어왔어요', confirmed: true };
    if (s.indexOf('배송완료') >= 0)
      return { reason: '배송완료 — 구매확정되면 실정산이 나와요', confirmed: false };
    if (s.indexOf('배송중') >= 0 || s.indexOf('발송') >= 0)
      return { reason: '아직 구매확정 전이라 실정산이 안 나왔어요', confirmed: false };
    return { reason: '마켓 실정산이 아직 안 들어왔어요', confirmed: false };
  }

  function timeline(saleDate, confirmed) {
    var d1 = 'done';
    var d2 = confirmed ? 'done' : 'now';
    var d3 = confirmed ? 'now' : '';
    return '<div class="moum-tl">'
      + '<div class="st"><div class="dot ' + d1 + '"></div><div class="cap">판매' + (saleDate ? '<br>' + esc0(saleDate) : '') + '</div></div>'
      + '<div class="bar ' + (confirmed ? 'done' : '') + '"></div>'
      + '<div class="st"><div class="dot ' + d2 + '"></div><div class="cap' + (confirmed ? '' : ' on') + '">구매확정' + (confirmed ? '' : '<br>대기') + '</div></div>'
      + '<div class="bar"></div>'
      + '<div class="st"><div class="dot ' + d3 + '"></div><div class="cap' + (confirmed ? ' on' : '') + '">실정산' + (confirmed ? '<br>대기' : '') + '</div></div>'
      + '</div>';
  }

  /* 추정 툴팁 HTML. 산정식은 '=' 아닌 '←'(유래) — 반올림 오차가 버그로 안 보이게. */
  function estTip(r, v) {
    var market = pick(r, ['마켓', '쇼핑몰', '판매처']);
    var status = pick(r, ['마켓주문상태 (오픈 마켓 연동)', '샵마인_주문상태', '주문상태', '더망고주문상태 (사용자 연동)']);
    var ono = pick(r, ['마켓주문번호', '오픈마켓주문번호']);
    var sale = dateOnly(pick(r, ['주문일']));
    var paid = num(pick(r, ['실결제금액']));
    var feePct = num(pick(r, ['수수료율']));
    var info = stateInfo(status);

    var calc;
    if (paid != null && feePct != null && feePct > 0) {
      var rate = Math.round((100 - feePct) * 100) / 100;
      calc = '<div class="moum-scalc">추정 ' + won(v) + ' ← 실결제 ' + won(paid)
        + ' × 정산율 ' + rate + '%</div>';
    } else if (paid != null) {
      calc = '<div class="moum-scalc">추정 ' + won(v) + ' ← 실결제 ' + won(paid) + ' 기준</div>';
    } else {
      calc = '<div class="moum-scalc">추정 ' + won(v) + '</div>';
    }

    return '<span class="moum-stip">'
      + timeline(sale, info.confirmed)
      + '<div class="moum-srs">' + (market ? '<b>' + esc0(market) + '</b> · ' : '') + esc0(info.reason) + '</div>'
      + calc
      + (ono ? '<div class="moum-so">주문 ' + esc0(ono) + (sale ? ' · ' + esc0(sale) : '') + '</div>' : '')
      + '</span>';
  }

  function unkTip(r) {
    var market = pick(r, ['마켓', '쇼핑몰', '판매처']);
    var ono = pick(r, ['마켓주문번호', '오픈마켓주문번호']);
    return '<span class="moum-stip">'
      + '<div class="moum-srs">' + (market ? '<b>' + esc0(market) + '</b> · ' : '')
      + '정산 정보가 아직 없어 마진을 낼 수 없어요. 실정산이 들어오면 자동으로 채워져요.</div>'
      + (ono ? '<div class="moum-so">주문 ' + esc0(ono) + '</div>' : '')
      + '</span>';
  }

  /* 정산 칸 <td>. real/store/zero_cancel = 원본 그대로(배지 없음). */
  root._moumSettleCell = function (r, v, esc) {
    var plain = '<td title="' + String(v == null ? '' : v).replace(/"/g, '&quot;') + '">' + esc(v) + '</td>';
    var ss = String((r && r['_settle_source']) || '');
    if (ss === 'estimated') {
      return '<td>' + esc(v)
        + '<span class="moum-sbadge est" tabindex="0">추정' + estTip(r, v) + '</span></td>';
    }
    if (ss === 'unknown' || ss === 'none') {
      return '<td>' + esc(v)
        + '<span class="moum-sbadge unk" tabindex="0">미확인' + unkTip(r) + '</span></td>';
    }
    return plain;   /* real·store·zero_cancel·기타 = 변경 없음 */
  };

  /* 배지 span 만 반환(<td> 없음). 정산 열이 인라인 편집 <input> 으로 렌더될 때
     input 옆에 붙이는 용도 — _moumSettleCell(전체 <td>)이 인라인 편집 분기에
     가로채여 안 불릴 때 여기로 배지를 얹는다. real/store/zero_cancel = 빈 문자열.
     v 는 정산예상금액 값(툴팁 산정식용). */
  root._moumSettleBadge = function (r, v) {
    var ss = String((r && r['_settle_source']) || '');
    if (ss === 'estimated')
      return '<span class="moum-sbadge est" tabindex="0">추정' + estTip(r, v) + '</span>';
    if (ss === 'unknown' || ss === 'none')
      return '<span class="moum-sbadge unk" tabindex="0">미확인' + unkTip(r) + '</span>';
    return '';
  };

  /* 요약 아래 3색칩. rows = 화면에 반영된 matched(제외·기간 필터 후) → 필터 정직.
     ★칩을 누르면 「전체내역」을 그 항목만으로 걸러 보여준다(_moumFilterSettle). */
  var CLICK = '<br><b style="color:#3182f6">클릭하면 「전체내역」에서 이 항목만 보여드려요.</b>';
  var CHIP_TIP = {
    real: '마켓이 <b>실제로 정산한 확정 금액</b>이에요. 가장 정확합니다.' + CLICK,
    est: '마켓 실정산이 아직 안 들어와, 실결제에 마켓 수수료율을 적용해 <b>어림한 값</b>이에요. 며칠 뒤 자동으로 실값으로 바뀝니다.<br>「추정」 줄의 정산 칸 배지에 마우스를 올리면 주문별 이유를 볼 수 있어요.' + CLICK,
    unk: '정산 정보가 아직 없어 <b>마진을 못 낸</b> 주문이에요. 실정산이 들어오면 자동으로 채워집니다.' + CLICK
  };
  root._moumSettleChips = function (rows) {
    if (!rows || !rows.length) return '';
    var real = 0, est = 0, unk = 0;
    for (var i = 0; i < rows.length; i++) {
      var s = String((rows[i] && rows[i]['_settle_source']) || '');
      if (s === 'real' || s === 'store') real++;
      else if (s === 'estimated') est++;
      else if (s === 'unknown' || s === 'none') unk++;
      /* zero_cancel(취소완료) = 정산0 확정 → 신뢰도 축에서 제외 */
    }
    function chip(cls, sw, lbl, n) {
      return '<div class="moum-schip ' + cls + '" tabindex="0" role="button"'
        + ' onclick="window._moumFilterSettle&&window._moumFilterSettle(\'' + cls + '\')"'
        + ' onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();window._moumFilterSettle&&window._moumFilterSettle(\'' + cls + '\')}">'
        + '<span class="lbl"><span class="moum-sw" style="background:' + sw + '"></span>' + lbl + '</span>'
        + '<span class="num">' + n + '<small>건</small></span>'
        + '<span class="moum-stip">' + CHIP_TIP[cls] + '</span></div>';
    }
    var h = '<div class="moum-schips">';
    h += chip('real', '#12864a', '실정산 확정', real);
    h += chip('est', '#E6A700', '추정치', est);
    if (unk > 0) h += chip('unk', '#5F5E5A', '미확인', unk);
    h += '</div>';
    return h;
  };

  /* 색칩 클릭 → 「전체내역」 탭을 그 정산근거(src)만으로 걸러 다시 그린다.
     기존 렌더러(buildDetailTable)를 그대로 쓰되 행만 걸러 넘긴다 — 필터는
     화면에 보이는 matched(제외·기간 반영) 기준. '전체' 로 되돌리려면 「전체내역」 탭 재클릭. */
  function matchSrc(r, cls) {
    var s = String((r && r['_settle_source']) || '');
    if (cls === 'real') return s === 'real' || s === 'store';
    if (cls === 'est') return s === 'estimated';
    if (cls === 'unk') return s === 'unknown' || s === 'none';
    return true;
  }
  root._moumFilterSettle = function (cls) {
    if (!doc) return;
    try {
      /* 1) 「전체내역」 탭으로 전환(없으면 무시) — 탭이 buildDetailTable 컨테이너를 만든다 */
      var tab = null, btns = doc.querySelectorAll('.tab-btn');
      for (var i = 0; i < btns.length; i++) {
        if (btns[i].getAttribute('data-tab') === 'all') { tab = btns[i]; break; }
      }
      if (tab) tab.click();
      /* 2) 탭이 그린 뒤, 전체 matched 를 정산근거로 걸러 같은 렌더러로 다시 그린다 */
      setTimeout(function () {
        var all;
        try {
          all = (typeof window._getRowsByCardFilter === 'function')
            ? window._getRowsByCardFilter('all')
            : ((window.analysisData && window.analysisData.matched) || []);
        } catch (e) { all = (window.analysisData && window.analysisData.matched) || []; }
        var f = (all || []).filter(function (r) { return matchSrc(r, cls); });
        if (typeof window.buildDetailTable === 'function') {
          window.buildDetailTable('__CARD_ALL__', f, 'all');
          /* 필터 배지 + 전체 보기 되돌리기 안내 */
          var ds = doc.getElementById('detail-section');
          if (ds && !ds.querySelector('.moum-filter-note')) {
            var lbl = cls === 'real' ? '실정산 확정' : (cls === 'est' ? '추정치' : '미확인');
            var note = doc.createElement('div');
            note.className = 'moum-filter-note';
            note.style.cssText = 'margin:6px 2px 0;font-size:12.5px;color:#3182f6';
            note.innerHTML = '「' + lbl + '」 ' + f.length + '건만 보는 중 · '
              + '<a href="#" style="color:#3182f6;text-decoration:underline" '
              + 'onclick="event.preventDefault();var t=[].filter.call(document.querySelectorAll(\'.tab-btn\'),function(b){return b.getAttribute(\'data-tab\')===\'all\'})[0];if(t)t.click();">전체 보기</a>';
            ds.insertBefore(note, ds.firstChild);
          }
        }
      }, 140);
    } catch (e) { /* 조용히 무시 — 원래 화면 유지 */ }
  };
})(typeof window !== 'undefined' ? window : globalThis);

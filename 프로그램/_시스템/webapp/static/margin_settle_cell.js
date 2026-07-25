/* margin_settle_cell.js — 전체내역 「정산예정금액(배송비포함)」 칸 정직성 표시 (모음전 신규)

   왜 필요한가 (2026-07-25):
   ────────────────────────────────────────────────────────────
   마진 숫자 중 일부는 마켓 실정산이 아직 안 들어와 **추정치**다. 지금 화면은
   추정 줄과 실정산 줄이 똑같이 보여, 사장님이 어느 숫자를 믿어야 할지 모른다.
   · 요약 아래 색칩 3개(실정산 · 추정 · 미확인) — _moumSettleChips(rows)
   · 추정/미확인 줄엔 정산 칸에 작은 배지 + 호버 설명(왜 추정인지) — _moumSettleCell
     호버 = 판매→구매확정→실정산 타임라인 + 산정식(실결제×정산율) + 마켓·사유·주문.

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
      '.moum-stip{position:absolute;right:0;top:calc(100% + 8px);opacity:0;visibility:hidden;transition:.12s;z-index:1000;pointer-events:none;background:#fff;border:1px solid #e5e8eb;box-shadow:0 8px 24px rgba(0,0,0,.16);border-radius:12px;padding:12px 14px;width:288px;text-align:left;white-space:normal;font-weight:400}',
      '.moum-sbadge:hover .moum-stip,.moum-sbadge:focus .moum-stip{opacity:1;visibility:visible}',
      '.moum-tl{display:flex;align-items:center;margin:2px 0 9px}',
      '.moum-tl .st{display:flex;flex-direction:column;align-items:center;flex:1}',
      '.moum-tl .dot{width:11px;height:11px;border-radius:50%;border:2px solid #e5e8eb;background:#fff}',
      '.moum-tl .dot.done{background:#1AB053;border-color:#1AB053}',
      '.moum-tl .dot.now{background:#E6A700;border-color:#E6A700;box-shadow:0 0 0 4px #FFF8E1}',
      '.moum-tl .bar{height:2px;flex:1;background:#e5e8eb}',
      '.moum-tl .bar.done{background:#1AB053}',
      '.moum-tl .cap{font-size:10px;color:#8a929b;margin-top:4px;text-align:center;line-height:1.25}',
      '.moum-tl .cap.on{color:#E6A700;font-weight:700}',
      '.moum-scalc{font-size:12px;color:#B7791F;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.4}',
      '.moum-srs{font-size:11.5px;color:#4b5563;line-height:1.5;margin-top:6px}',
      '.moum-srs b{color:#B7791F}',
      '.moum-so{font-size:10.5px;color:#adb5bd;margin-top:6px}',
      '.moum-schips{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}',
      '.moum-schip{display:flex;flex-direction:column;gap:1px;border-radius:9px;padding:7px 14px 6px;border:1px solid;min-width:106px}',
      '.moum-schip .lbl{font-size:11px;font-weight:600;display:flex;align-items:center;gap:5px}',
      '.moum-schip .num{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}',
      '.moum-schip .num small{font-size:12px;font-weight:500;margin-left:1px}',
      '.moum-schip.real{background:#E7F7EF;border-color:#B7E9CE;color:#12864a}',
      '.moum-schip.est{background:#FFF8E1;border-color:#F0DDB4;color:#B7791F}',
      '.moum-schip.unk{background:#F1EFE8;border-color:#DEE2E6;color:#5F5E5A}',
      '.moum-sw{width:8px;height:8px;border-radius:50%;display:inline-block}'
    ].join('');
    (doc.head || doc.documentElement).appendChild(st);
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
    var feeStr = pick(r, ['수수료율']);
    var feePct = num(feeStr);
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

  /* 요약 아래 3색칩. rows = 화면에 반영된 matched(제외·기간 필터 후) → 필터 정직. */
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
      return '<div class="moum-schip ' + cls + '"><span class="lbl">'
        + '<span class="moum-sw" style="background:' + sw + '"></span>' + lbl
        + '</span><span class="num">' + n + '<small>건</small></span></div>';
    }
    var h = '<div class="moum-schips" title="정산이 마켓 실값(실정산)인지, 아직 안 들어와 어림한 추정치인지 나눠 보여줘요">';
    h += chip('real', '#12864a', '실정산 확정', real);
    h += chip('est', '#E6A700', '추정치', est);
    if (unk > 0) h += chip('unk', '#5F5E5A', '미확인', unk);
    h += '</div>';
    return h;
  };
})(typeof window !== 'undefined' ? window : globalThis);

/* 대량등록 수기 입력 — 폼 → POST /bulk/api/drafts → 목록 갱신.
   기능 우선. 디자인·UX 다듬기는 설계서 §8 의 별도 시안 라운드에서. */
(function () {
  const form = document.getElementById('bulk-manual-form');
  if (!form) return;
  const $ = (n) => form.querySelector(`[name="${n}"]`);
  const msg = document.getElementById('bd-msg');

  function optRows() {
    const out = [];
    document.querySelectorAll('#bd-opt-table tr[data-opt]').forEach((tr) => {
      const g = (k) => tr.querySelector(`[data-k="${k}"]`).value.trim();
      const stock = parseInt(g('stock'), 10);
      out.push({
        color: g('color'), size: g('size'),
        stock: isNaN(stock) ? 0 : stock,
        extra_price: parseInt(g('extra'), 10) || 0,
        sku: g('sku'),
      });
    });
    return out;
  }

  document.getElementById('bd-opt-add').addEventListener('click', () => {
    const tr = document.createElement('tr');
    tr.setAttribute('data-opt', '1');
    tr.innerHTML =
      '<td><input data-k="color" autocomplete="off"></td>' +
      '<td><input data-k="size" autocomplete="off"></td>' +
      '<td><input data-k="stock" type="number" min="0" value="0" autocomplete="off"></td>' +
      '<td><input data-k="extra" type="number" value="0" autocomplete="off"></td>' +
      '<td><input data-k="sku" autocomplete="off"></td>' +
      '<td><button type="button" class="btn btn-sm" data-del>삭제</button></td>';
    tr.querySelector('[data-del]').addEventListener('click', () => tr.remove());
    document.getElementById('bd-opt-table').appendChild(tr);
  });

  document.getElementById('bd-save').addEventListener('click', async () => {
    const images = $('bd_images').value.split('\n').map(s => s.trim()).filter(Boolean);
    const body = {
      name: $('bd_name').value.trim(),
      brand: $('bd_brand').value.trim(),
      sale_price: parseInt($('bd_sale_price').value, 10) || 0,
      normal_price: parseInt($('bd_normal_price').value, 10) || null,
      notice_type: $('bd_notice_type').value,
      notice: {
        material: $('bd_notice_material').value.trim(),
        color: $('bd_notice_color').value.trim(),
        size: $('bd_notice_size').value.trim(),
        type: $('bd_notice_type_detail').value.trim(),
        manufacturer: $('bd_notice_manufacturer').value.trim(),
        caution: $('bd_notice_caution').value.trim(),
        warranty_policy: $('bd_notice_warranty').value.trim(),
        after_service_director: $('bd_notice_as').value.trim(),
      },
      images: images,
      detail_html: $('bd_detail_html').value,
      options: optRows(),
      // 빈 칸은 보내지 않는다 — 서버가 기본값을 쓴다. `|| 0` 로 쓰면 빈 칸이 0(무료배송)이 돼 돈이 샌다.
      delivery_fee: $('bd_delivery_fee').value.trim(),
      return_fee: $('bd_return_fee').value.trim(),
      after_service_phone: $('bd_as_phone').value.trim(),
      after_service_guide: $('bd_as_guide').value.trim(),
    };
    msg.textContent = '저장 중…';
    const res = await fetch('/bulk/api/drafts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json());
    msg.textContent = res.ok ? `저장했습니다 (#${res.draft_id})` : `저장 실패: ${res.error}`;
    if (res.ok) loadList();
  });

  async function loadList() {
    const res = await fetch('/bulk/api/drafts').then(r => r.json());
    const t = document.getElementById('bd-list');
    t.querySelectorAll('tr[data-row]').forEach(r => r.remove());
    (res.rows || []).forEach((d) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-row', '1');
      const mk = (d.markets || []).map(m =>
        `${m.market}:${m.status}${m.market_product_id ? '(' + m.market_product_id + ')' : ''}`
      ).join(' · ') || '—';
      tr.innerHTML =
        `<td>${d.name}</td><td class="num">${(d.sale_price || 0).toLocaleString('ko-KR')}</td>` +
        `<td>${d.status}</td><td>${mk}</td>` +
        `<td><button type="button" class="btn btn-sm" data-reg="${d.id}">등록</button></td>`;
      t.appendChild(tr);
    });
  }

  document.getElementById('bd-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-reg]');
    if (!btn) return;
    const cat = prompt('스마트스토어 리프 카테고리 ID:');
    if (!cat) return;
    btn.disabled = true;
    const res = await fetch(`/bulk/api/drafts/${btn.dataset.reg}/register/smartstore`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category_code: cat }),
    }).then(r => r.json());
    btn.disabled = false;
    if (res.blocked) alert('실등록이 꺼져 있습니다 — ' + res.error);
    else if (!res.ok) alert('등록 실패: ' + res.error);
    else if ((res.excluded || []).length) {
      // 입력한 옵션이 빠졌으면 반드시 알린다 — '성공' 만 띄우면 조용한 실패
      const lines = res.excluded.map(e => `· ${e.color}/${e.size} — ${e.reason}`).join('\n');
      alert(`등록했습니다 (${res.market_product_id})\n\n다만 아래 옵션은 빠졌습니다:\n${lines}`);
    }
    loadList();
  });

  // ══════════════════════════════════════════════════════════════════════
  //  매입가·마진 미리보기 (Phase 1B M2)
  //
  //  ★ 이 블록에 금액 산수가 한 줄도 없다는 점이 핵심이다.
  //    최종매입가는 서버(POST /bulk/api/margin-preview → compute_final_price,
  //    매트릭스 fx영수증과 같은 엔진)가 계산해 내려주고, 여기는 그 숫자를 그리기만
  //    한다. JS 에서 곱셈·버림을 다시 짜면 파이썬과 어긋나 '화면가 ≠ 업로드가'가
  //    된다(이 저장소에 반올림 불일치 전례가 있다).
  //  ★ 실패하면 0원·추정가를 절대 그리지 않는다 — '계산 불가'로 드러낸다.
  // ══════════════════════════════════════════════════════════════════════
  const PR = ['bd_pr_source_id', 'bd_pr_surface_price', 'bd_pr_inflow',
              'bd_pr_card_key', 'bd_pr_naver_pay', 'bd_pr_cashback_name'];
  const elFinal = document.getElementById('bmg-final');
  const elMargin = document.getElementById('bmg-margin');
  const elWarn = document.getElementById('bmg-warn');
  const elRcp = document.getElementById('bmg-receipt');
  const elTog = document.getElementById('bmg-toggle');
  const won = (n) => Number(n).toLocaleString('ko-KR') + '원';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function setFail(msg) {
    elFinal.textContent = '계산 불가';
    elFinal.className = 'bmg-num bmg-fail';
    elMargin.textContent = '—';
    elMargin.className = 'bmg-num';
    // 영수증은 숨기는 데 그치지 않고 **비운다** — 옛 금액이 DOM 에 남아 있다가
    // 다시 펼쳐질 때 지금 입력과 무관한 숫자를 보여주는 일이 없도록.
    elRcp.innerHTML = ''; elRcp.hidden = true; elTog.hidden = true;
    if (msg) { elWarn.textContent = msg; elWarn.hidden = false; }
    else { elWarn.hidden = true; }
  }

  function setIdle() {
    elFinal.textContent = '—'; elFinal.className = 'bmg-num';
    elMargin.textContent = '—'; elMargin.className = 'bmg-num';
    elWarn.hidden = true;
    elRcp.innerHTML = ''; elRcp.hidden = true; elTog.hidden = true;
  }

  /* 영수증 — 매트릭스 fx 팝업(smRenderFxPopBody)과 같은 steps[] 계약, 같은 전역
     클래스(.fxpop-v2 .cf-receipt)로 그린다. 새 시각 언어를 만들지 않는다.
     steps[i] = {name, type, value, deduct, base_after}. */
  function receiptHtml(j) {
    const circ = (n) => ['', '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨'][n] || String(n);
    const steps = j.steps || [];
    let ln = `<div class="cf-rc-ln"><span class="lbl">표면 노출가</span>` +
             `<span class="num">${won(j.surface_price || 0)}</span></div>`;
    let baseNo = 0;
    steps.forEach((st, i) => {
      const pct = st.type === 'rate'
        ? ` <span class="rc-pct">(${(st.value * 100).toFixed(2)}%)</span>` : '';
      ln += `<div class="cf-rc-ln sub"><span class="lbl">└ ${esc(st.name)}${pct}</span>` +
            `<span class="num">-${won(st.deduct || 0)}</span></div>`;
      /* 2026-07-19 — 캐시백은 결제 전액이 아니라 부가세 뺀 '공급가'에 적립된다.
         적립율은 위 줄에 원본(1.10%) 그대로 두고, 계수는 여기서 밝힌다. */
      if (st.base_note && st.base_ratio != null && st.base_ratio !== 1) {
        const bAmt = Math.round((st.base_after || 0) + (st.deduct || 0));
        ln += `<div class="cf-rc-ln cf-rc-note">${esc(st.base_note)} · ${won(bAmt)} × ` +
              `${(st.base_ratio * 100).toFixed(0)}% × ${(st.value * 100).toFixed(2)}%` +
              ` = ${won(st.deduct || 0)}</div>`;
      }
      if (i !== steps.length - 1) {
        baseNo += 1;
        const nx = steps[i + 1];
        const nxRatio = (nx && nx.base_ratio != null && nx.base_ratio !== 1)
          ? `공급가 ${(nx.base_ratio * 100).toFixed(0)}% × ` : '';
        const tag = (nx && nx.type === 'rate')
          ? `<span class="tag">${nxRatio}${(nx.value * 100).toFixed(2)}% 기준</span>` : '';
        ln += `<div class="cf-rc-ln base"><span class="lbl">베이스금액${circ(baseNo)}${tag}</span>` +
              `<span class="num">${won(st.base_after || 0)}</span></div>`;
      }
    });
    if (!steps.length) {
      ln += `<div class="cf-rc-ln sub"><span class="lbl">└ 적용된 혜택 없음</span>` +
            `<span class="num">-0원</span></div>`;
    }
    // 어떤 카드 경로가 채택됐는지 — '왜 이 카드인가'를 숨기지 않는다.
    const p = j.path || null;
    const pathTxt = p
      ? `결제 경로: ${p.pay_method ? esc(p.pay_method) : '무결제'} · N쇼핑 경유 ${p.naver_via ? 'O' : 'X'}`
      : '결제 경로: 택1 없음';
    return `<div class="cf-receipt">${ln}<div class="cf-rc-div"></div>` +
           `<div class="cf-rc-ln fin"><span class="lbl">최종 매입가</span>` +
           `<span class="num">${won(j.final_price || 0)}</span></div>` +
           `<div class="cf-rc-note">${pathTxt}</div></div>`;
  }

  let prSeq = 0;
  async function refreshMargin() {
    const sid = $('bd_pr_source_id').value;
    const surf = $('bd_pr_surface_price').value.trim();
    if (!sid || !surf) { setIdle(); return; }
    const body = {
      source_id: sid,
      surface_price: surf,
      sale_price: $('bd_sale_price').value.trim(),
      inflow: $('bd_pr_inflow').value,
      card_key: $('bd_pr_card_key').value,
      naver_pay: $('bd_pr_naver_pay').value,
      cashback_name: $('bd_pr_cashback_name').value,
    };
    const my = ++prSeq;   // 늦게 도착한 옛 응답이 새 값을 덮지 않게 (경합 방지)
    let res;
    try {
      res = await fetch('/bulk/api/margin-preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json());
    } catch (e) {
      if (my === prSeq) setFail('계산 요청 실패: ' + e);
      return;
    }
    if (my !== prSeq) return;
    if (!res || !res.ok) { setFail(res && res.error ? res.error : '계산에 실패했습니다.'); return; }

    elFinal.textContent = won(res.final_price);
    elFinal.className = 'bmg-num';
    if (res.margin == null) {
      elMargin.textContent = '판매가 미입력';
      elMargin.className = 'bmg-num bmg-fail';
    } else {
      elMargin.textContent = won(res.margin);
      // 역마진은 눈에 띄게 — 조용히 지나가면 팔수록 손해다.
      elMargin.className = 'bmg-num' + (res.margin < 0 ? ' bmg-neg' : '');
    }
    const ws = res.warnings || [];
    if (ws.length) { elWarn.innerHTML = ws.map(w => `· ${esc(w)}`).join('<br>'); elWarn.hidden = false; }
    else { elWarn.hidden = true; }
    elRcp.innerHTML = receiptHtml(res);
    elTog.hidden = false;
  }

  elTog.addEventListener('click', () => {
    elRcp.hidden = !elRcp.hidden;
    elTog.textContent = elRcp.hidden ? '계산 내역 보기' : '계산 내역 숨기기';
  });

  let prTimer = null;
  function scheduleMargin() {
    clearTimeout(prTimer);
    prTimer = setTimeout(refreshMargin, 250);   // 타이핑 중 요청 폭주 방지
  }
  PR.concat(['bd_sale_price']).forEach((n) => {
    const el = $(n);
    if (el) { el.addEventListener('input', scheduleMargin); el.addEventListener('change', scheduleMargin); }
  });

  /* 소싱처가 바뀌면 그 소싱처의 캐시백 항목으로 드롭다운을 다시 채운다.
     캐시백 적립율은 소싱처마다 달라 화면에서 지어내지 않고 소싱처 혜택에서 읽는다. */
  async function loadMeta(sourceId) {
    const url = '/bulk/api/margin-meta' + (sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : '');
    const res = await fetch(url).then(r => r.json()).catch(() => null);
    if (!res || !res.ok) return;
    const srcSel = $('bd_pr_source_id');
    if (!srcSel.dataset.filled) {
      (res.sources || []).forEach((s) => {
        const o = document.createElement('option');
        o.value = s.id; o.textContent = s.name; srcSel.appendChild(o);
      });
      srcSel.dataset.filled = '1';
    }
    const cardSel = $('bd_pr_card_key');
    if (!cardSel.dataset.filled) {
      (res.cards || []).forEach((c) => {
        const o = document.createElement('option');
        o.value = c.key;
        o.textContent = c.accrual_rate > 0
          ? `${c.label} (적립 ${(c.accrual_rate * 100).toFixed(2).replace(/\.?0+$/, '')}%)`
          : `${c.label} (적립 0%)`;
        cardSel.appendChild(o);
      });
      cardSel.dataset.filled = '1';
    }
    if (res.cashback_items) {
      const cb = $('bd_pr_cashback_name');
      const keep = cb.value;
      cb.querySelectorAll('option[data-dyn]').forEach(o => o.remove());
      res.cashback_items.forEach((it) => {
        const o = document.createElement('option');
        o.value = it.name; o.setAttribute('data-dyn', '1');
        o.textContent = it.type === 'rate'
          ? `${it.name} (${(it.value * 100).toFixed(2).replace(/\.?0+$/, '')}%)`
          : `${it.name} (${Number(it.value).toLocaleString('ko-KR')}원)`;
        cb.appendChild(o);
      });
      cb.value = Array.from(cb.options).some(o => o.value === keep) ? keep : '';
    }
  }

  $('bd_pr_source_id').addEventListener('change', () => {
    loadMeta($('bd_pr_source_id').value);
  });
  loadMeta('');

  loadList();
})();

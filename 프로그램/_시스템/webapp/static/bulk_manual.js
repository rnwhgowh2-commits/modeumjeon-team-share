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

  /* 지금 편집 중인 드래프트 id. null = 새 상품.
     저장이 항상 POST 면 '열기 → 수정 → 저장'이 매번 새 행을 만들어 같은 상품이
     조금씩 다른 값으로 여러 벌 남는다(= 어느 게 진짜인지 모르는 상태). */
  let editingId = null;
  const elEditing = document.getElementById('bd-editing');

  function setEditing(id) {
    editingId = id;
    if (elEditing) {
      elEditing.textContent = id ? `#${id} 수정 중` : '';
      elEditing.hidden = !id;
    }
    const nb = document.getElementById('bd-new');
    if (nb) nb.hidden = !id;
  }

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
      /* 「6 매입가·마진」 6칸 — 화면 값을 **있는 그대로** 보낸다.
         `|| null`·`|| ''` 같은 보정을 넣지 않는 게 핵심이다. ''(소싱처 기본값으로
         남겨둠)와 'none'(없음을 골랐음)은 계산 결과가 다른 별개의 값이라, 한쪽을
         다른 쪽으로 바꿔 보내면 사장님이 하지 않은 선택이 저장된다. */
      source_id: $('bd_pr_source_id').value,
      surface_price: $('bd_pr_surface_price').value.trim(),
      inflow: $('bd_pr_inflow').value,
      card_key: $('bd_pr_card_key').value,
      naver_pay: $('bd_pr_naver_pay').value,
      cashback_name: $('bd_pr_cashback_name').value,
    };
    msg.textContent = '저장 중…';
    const isEdit = editingId != null;
    const res = await fetch(isEdit ? `/bulk/api/drafts/${editingId}` : '/bulk/api/drafts', {
      method: isEdit ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json());
    if (res.ok) {
      const id = isEdit ? editingId : res.draft_id;
      setEditing(id);
      msg.textContent = `저장했습니다 (#${id})`;
      loadList();
    } else {
      msg.textContent = `저장 실패: ${res.error}`;
    }
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
        `<td><button type="button" class="btn btn-sm" data-open="${d.id}">열기</button> ` +
        `<button type="button" class="btn btn-sm" data-reg="${d.id}">등록</button></td>`;
      t.appendChild(tr);
    });
  }

  /* ── 다시 열기 (복원) ──────────────────────────────────────────────────
     ★ 저장된 값을 **그대로** 칸에 되돌린다. `|| ''` 로 뭉개지 않는 게 핵심이다.
       null(입력받지 않음)과 ''(소싱처 기본값으로 남겨둠)를 둘 다 빈 칸으로
       그리는 건 어쩔 수 없지만(select 에 상태가 둘뿐), 저장소에는 서로 다른
       값으로 남아 있고 화면이 그걸 바꿔 쓰지 않는다. 사용자가 손대지 않고
       저장하면 원래 값이 그대로 다시 저장된다. */
  function setVal(name, v) {
    const el = $(name);
    if (!el) return;
    el.value = (v === null || v === undefined) ? '' : String(v);
  }

  async function openDraft(id) {
    const res = await fetch(`/bulk/api/drafts/${id}`).then(r => r.json()).catch(() => null);
    if (!res || !res.ok) { msg.textContent = '불러오기 실패'; return; }
    const d = res.draft;
    setVal('bd_name', d.name); setVal('bd_brand', d.brand);
    setVal('bd_sale_price', d.sale_price); setVal('bd_normal_price', d.normal_price);
    setVal('bd_notice_type', d.notice_type);
    const n = d.notice || {};
    setVal('bd_notice_material', n.material); setVal('bd_notice_color', n.color);
    setVal('bd_notice_size', n.size); setVal('bd_notice_type_detail', n.type);
    setVal('bd_notice_manufacturer', n.manufacturer);
    setVal('bd_notice_caution', n.caution);
    setVal('bd_notice_warranty', n.warranty_policy);
    setVal('bd_notice_as', n.after_service_director);
    setVal('bd_images', (d.images || []).join('\n'));
    setVal('bd_detail_html', d.detail_html);
    setVal('bd_delivery_fee', d.delivery_fee); setVal('bd_return_fee', d.return_fee);
    setVal('bd_as_phone', d.after_service_phone);
    setVal('bd_as_guide', d.after_service_guide);

    // 옵션 표 — 저장된 행으로 다시 그린다
    const tbl = document.getElementById('bd-opt-table');
    tbl.querySelectorAll('tr[data-opt]').forEach(tr => tr.remove());
    (d.options || []).forEach((o) => {
      document.getElementById('bd-opt-add').click();
      const tr = tbl.querySelector('tr[data-opt]:last-child');
      const set = (k, v) => { tr.querySelector(`[data-k="${k}"]`).value = v == null ? '' : v; };
      set('color', o.color); set('size', o.size); set('stock', o.stock);
      set('extra', o.extra_price); set('sku', o.sku);
    });

    // 매입가·마진 6칸 — 소싱처를 먼저 세팅하고, 그 소싱처의 캐시백 목록을 채운
    // **뒤에** 캐시백 선택을 복원한다(옵션이 없으면 select 가 값을 버린다).
    setVal('bd_pr_source_id', d.source_id);
    setVal('bd_pr_surface_price', d.surface_price);
    setVal('bd_pr_inflow', d.inflow);
    setVal('bd_pr_card_key', d.card_key);
    setVal('bd_pr_naver_pay', d.naver_pay);
    if (d.source_id) await loadMeta(d.source_id);
    setVal('bd_pr_cashback_name', d.cashback_name);

    setEditing(d.id);
    msg.textContent = `#${d.id} 을(를) 불러왔습니다.`;
    refreshMargin();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  document.getElementById('bd-list').addEventListener('click', async (e) => {
    const openBtn = e.target.closest('[data-open]');
    if (openBtn) { openDraft(openBtn.dataset.open); return; }
    const btn = e.target.closest('[data-reg]');
    if (!btn) return;
    // 마켓 선택 — 6마켓 (2026-07-21 옥션·G마켓·11번가·롯데온 실등록 검증 후 연결)
    const MKTS = ['smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'];
    const pick = prompt(
      '어느 마켓에 등록할까요? 번호를 입력하세요.\n' +
      '1 스마트스토어 / 2 쿠팡 / 3 옥션 / 4 G마켓 / 5 11번가 / 6 롯데온', '1');
    if (!pick) return;
    const market = MKTS[Number(pick) - 1];
    if (!market) { alert('1~6 사이 번호를 입력해 주세요.'); return; }
    // 마켓별 "카테고리 칸"의 뜻이 다르다 — 안내문을 정확히(조용한 오입력 방지)
    const CAT_HINT = {
      smartstore: '스마트스토어 리프 카테고리 ID:',
      coupang: '쿠팡 카테고리 코드(displayCategoryCode):',
      auction: '옥션: ESM카테고리코드/사이트카테고리코드\n(예: 00120005002000000000/37500700)',
      gmarket: 'G마켓: ESM카테고리코드/사이트카테고리코드\n(예: 00120005002100000000/300006243)',
      eleven11: '11번가 최하위 카테고리 번호(dispCtgrNo)\n(예: 1011634)',
      lotteon: '롯데온: 본보기 기존 상품번호(spdNo, LO로 시작)\n같은 계정의 비슷한 카테고리 판매중 상품\n(예: LO2727500650)',
    };
    let cat = prompt(CAT_HINT[market] + '\n\n※ 번호를 모르면 ?검색어 (예: ?운동화) 로 찾을 수 있어요' +
      (market === 'lotteon' ? ' (상품 이름으로 검색)' : '') + '.');
    if (!cat) return;
    // '?키워드' → 이름 검색(11번가 카테고리 / 롯데온 본보기 상품)
    while (cat.trim().startsWith('?')) {
      const kw = cat.trim().slice(1).trim();
      if (!kw) return;
      const sr = await fetch(`/bulk/api/category-search?market=${market}&q=${encodeURIComponent(kw)}`)
        .then(r => r.json()).catch(() => null);
      if (!sr || !sr.ok) { alert('검색 실패: ' + (sr && sr.error || '지원하지 않는 마켓')); return; }
      const lines = (sr.rows || []).map(r => `${r.code} — ${r.name}`).join('\n') || '(결과 없음)';
      cat = prompt(`「${kw}」 검색 결과 ${sr.count}건 — 왼쪽 번호를 복사해 입력하세요:\n\n${lines}\n\n` +
        '(다시 검색하려면 ?검색어)');
      if (!cat) return;
    }
    // 계정 선택(4마켓) — 비우면 기본(첫 활성) 계정. 스스·쿠팡은 아직 기본 계정만.
    let accountKey = 'default';
    if (['auction', 'gmarket', 'eleven11', 'lotteon'].includes(market)) {
      const a = prompt('계정 키 (비우면 기본 계정으로 등록):', '');
      if (a === null) return;
      accountKey = a.trim() || 'default';
    }
    btn.disabled = true;
    const res = await fetch(`/bulk/api/drafts/${btn.dataset.reg}/register/${market}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category_code: cat.trim(), account_key: accountKey }),
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
      // 편집 중이면 draft_id 도 보낸다 — 화면이 안 보낸 칸(예: 판매가 빈칸)을
      // 서버가 저장값으로 메울 수 있게. 보낸 칸은 화면 값이 이긴다(미리보기).
      draft_id: editingId,
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

  /* 「새 상품으로」 — 편집 상태만 푼다. 칸을 비우지 않는 게 의도다: 비슷한 상품을
     이어서 등록하는 게 흔하고, 실수로 누른 사람의 입력을 지워버리지 않는다. */
  const newBtn = document.getElementById('bd-new');
  if (newBtn) newBtn.addEventListener('click', () => {
    setEditing(null);
    msg.textContent = '새 상품으로 전환했습니다 — 저장하면 새로 만들어집니다.';
  });

  setEditing(null);
  loadList();
})();

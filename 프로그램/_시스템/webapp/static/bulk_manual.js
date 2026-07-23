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

  /* 장부(ProductDraftMarket) status → 사람 말. 목록·상세가 같은 말을 쓰게 한다.
     ★ 'uncertain' 은 「등록됨」이 아니다 — 이 한 칸이 갈리면 사장님 판단이 갈린다. */
  const LEDGER_LABEL = {
    pending: '대기', ok: '등록됨', failed: '실패', blocked: '막힘',
    uncertain: '확인 필요',
  };

  async function loadList() {
    const res = await fetch('/bulk/api/drafts').then(r => r.json());
    const t = document.getElementById('bd-list');
    t.querySelectorAll('tr[data-row]').forEach(r => r.remove());
    (res.rows || []).forEach((d) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-row', '1');
      // 목록의 마켓 칸도 **한글 상태**로 읽힌다 — 여기만 영문 상태값이 날것으로 나오면
      // 사장님이 'uncertain' 을 「등록된 것」으로 읽을 수 있다(4차리뷰 화면 전수 점검).
      const mk = (d.markets || []).map(m =>
        `${m.market}:${LEDGER_LABEL[m.status] || m.status}` +
        `${m.market_product_id ? '(' + m.market_product_id + ')' : ''}`
      ).join(' · ') || '—';
      tr.innerHTML =
        `<td>${d.name}</td><td class="num">${(d.sale_price || 0).toLocaleString('ko-KR')}</td>` +
        `<td>${d.status}</td><td>${mk}</td>` +
        `<td><button type="button" class="btn btn-sm" data-open="${d.id}">열기</button> ` +
        `<button type="button" class="btn btn-sm" data-pre="${d.id}">점검</button> ` +
        `<button type="button" class="btn btn-sm" data-reg="${d.id}">등록</button></td>`;
      t.appendChild(tr);
    });
  }

  /* ── 「올릴 수 있는 마켓 점검」 (M4-1 드라이런) ────────────────────────────
     등록을 눌러봐야 무엇이 부족한지 알던 것을, 누르기 **전에** 마켓별로 보여준다.
     서버(POST /bulk/api/drafts/<id>/preflight)는 마켓 API 를 부르지 않는다 —
     등록 흐름의 '예비 컴파일'만 6마켓으로 돌린 결과다.
     ★ 「올릴 수 있음」이 등록 성공 보장은 아니다 — 게이트 뒤 선행자원에서 실패할 수
       있고, 그 사실을 caveats(주의)로 그대로 같이 보여준다(거짓 초록 금지). */
  // registered = [2026-07-23 C1] 이 마켓에는 **이미 올라가 있다**(장부에 상품번호가 있다).
  //   「올릴 수 있음」으로 보여주면 화면이 체크까지 해 줘서 같은 상품이 두 번 올라간다.
  // uncertain  = [재리뷰 C-2] 올라갔는지 **모른다**(전송 뒤 끊김·옵션 부착 실패 등).
  //   확인 전까지 잠근다 — 「모른다」를 「없다」로 칠하면 그 한 번의 클릭이 유령을 만든다.
  const PRE_LABEL = {
    ready: '올릴 수 있음', missing: '보충 필요',
    blocked: '제외', need_category: '카테고리 필요', registered: '이미 등록됨',
    uncertain: '확인 필요',
    /* 브랜드가 비면 지재권 제한표가 판정조차 못 한다 — 「모름」을 「통과」로 읽지 않는다. */
    need_brand: '브랜드 필요',
  };
  // 색은 기존 클래스(toss.css .dot.ok/.warn/.danger)를 그대로 쓴다 — 새 스타일 없음.
  // ★ registered 는 초록(ok)이 아니라 회색(na) — 초록은 「올릴 수 있음」의 색이라
  //   나란히 놓이면 같은 뜻으로 읽힌다(리뷰 사소③). 잠긴 줄은 조용한 색이 맞다.
  const PRE_DOT = {
    ready: 'ok', missing: 'warn', need_category: 'warn', blocked: 'danger',
    registered: 'na', uncertain: 'warn', need_brand: 'danger',
  };
  const PRE_MARKET = {
    smartstore: '스마트스토어', coupang: '쿠팡', auction: '옥션',
    gmarket: 'G마켓', eleven11: '11번가', lotteon: '롯데온',
  };

  /* ── 타 마켓 브랜딩 이미지 (2026-07-23 사장님 결정 (나)안) ────────────────
     소싱처 셀러가 상세에 심어 둔 **경쟁 마켓 기획전 배너**다. 그대로 옥션·G마켓·
     11번가·롯데온 본문으로 올라가면 판매금지·상품삭제 사유가 된다.
     ★ **자동으로 지우지 않는다.** 파일명 판정은 오탐이 나서(`ssg` 가 들어간 멀쩡한
       상품 사진) 자동 삭제는 상품 사진을 조용히 없앤다. 보여 주고, 사장님이 고른
       것만 「상세에서 빼기」로 뺀다. 되돌리기는 재크롤이다. */
  const FA_TOKEN = {
    ssg: 'SSG.COM', shinsegae: '신세계', emart: '이마트', coupang: '쿠팡',
    '11st': '11번가', elevenst: '11번가', gmarket: 'G마켓', auction: '옥션',
    lotteon: '롯데온', lotteimall: '롯데아이몰', interpark: '인터파크',
    wemakeprice: '위메프', tmon: '티몬', smartstore: '스마트스토어', naver: '네이버',
  };

  function foreignAssetsHtml(id, market, assets) {
    const items = assets.map((a) => {
      const label = FA_TOKEN[a.token] || a.token;
      const kind = a.where === 'link' ? '링크' : '사진';
      return '<label style="display:flex;gap:8px;align-items:center;padding:3px 0">' +
        `<input type="checkbox" checked data-fa-url="${esc(a.url)}">` +
        `<span class="chip-v3 chip-warn">${esc(label)} ${esc(kind)}</span>` +
        `<span class="muted" style="word-break:break-all">${esc(a.url)}</span>` +
        '</label>';
    }).join('');
    // 체크박스는 **같은 상세를 쓰는 4마켓에 똑같이** 뜬다 — 한 곳에서 빼면 4곳 모두
    // 반영되므로, 뺀 뒤에는 점검을 다시 돌려 네 행을 한꺼번에 갱신한다.
    return `<tr data-fa-market="${esc(market)}"><td colspan="5">` +
      '<details style="font-size:12px">' +
      `<summary style="cursor:pointer">🔴 타 마켓 이미지 ${assets.length}개 — ` +
      '눌러서 확인하고 뺄 것만 고르세요</summary>' +
      `<div style="margin:6px 0 0">${items}</div>` +
      '<p class="muted" style="margin:6px 0">되돌리려면 다시 크롤해야 합니다 — ' +
      '상품 사진이 섞여 있지 않은지 보고 빼 주세요.</p>' +
      `<button type="button" class="btn btn-sm" data-fa-remove="${esc(id)}">` +
      '상세에서 빼기</button>' +
      '</td></tr>';
  }

  /* 확정 칸(상품번호 입력 + 「이 상품번호로 확정」) — **세 화면이 같은 조각을 쓴다.**
     ★★ [5차리뷰 C2] 점검 패널·등록 패널·결과표 셋 다 서버 문구가 「이 상품번호로 확정」을
       누르라고 말한다. 조각을 한 벌로 두지 않으면 화면 하나가 또 빠진다(이번이 세 번째다).
     판정은 서버가 준 confirm_supported 하나뿐 — 화면이 자체 조건을 세우지 않는다. */
  function confirmBoxHtml(r, draftId) {
    if (!r.confirm_supported) return '';
    return '<div class="cfm-box" style="margin-top:4px;font-size:11.5px"' +
      `${draftId ? ` data-cfm-draft="${esc(draftId)}"` : ''}>` +
      `<input data-cfm-input="${esc(r.market)}" size="16" autocomplete="off" ` +
      `placeholder="마켓에서 확인한 상품번호" value="${esc(r.market_product_id || '')}">` +
      ` <button type="button" class="btn btn-sm" data-cfm="${esc(r.market)}">` +
      '이 상품번호로 확정</button>' +
      '<span class="muted"> — 마켓에 있으면 이 번호로 「등록됨」 처리합니다</span>' +
      `<div data-lookupout-m="${esc(r.market)}"></div></div>`;
  }

  function preflightHtml(id, rows) {
    const body = (rows || []).map((r) => {
      const cav = (r.caveats || []).map((c) => `· ${esc(c)}`).join('<br>');
      const src = r.category_source === 'mapped' ? ' (맵핑 확정)'
        : (r.category_source === 'given' ? ' (이번에 지정)' : '');
      const fa = r.foreign_assets || [];
      // [C2] 「확인 필요」 줄에는 여기서도 확정 칸을 낸다 — 서버 문구가 가리키는 버튼이
      //   이 화면에 없으면, 남는 행동은 「다시 올리기 = 중복」뿐이다.
      const look = (r.status === 'uncertain' && r.lookup_supported)
        ? ` <button type="button" class="btn btn-sm" data-lookup="${esc(r.market)}">` +
          '마켓에서 상품 찾아보기</button>' : '';
      return '<tr>' +
        `<td>${esc(PRE_MARKET[r.market] || r.market)}</td>` +
        `<td><span class="dot ${PRE_DOT[r.status] || 'na'}"></span>` +
        `${esc(PRE_LABEL[r.status] || r.status)}</td>` +
        `<td>${r.category_code ? esc(r.category_code) + esc(src) : '—'}</td>` +
        `<td>${esc(r.reason) || '—'}${look}${confirmBoxHtml(r, id)}</td>` +
        `<td>${cav || '—'}</td></tr>` +
        (fa.length ? foreignAssetsHtml(id, r.market, fa) : '');
    }).join('');
    return '<table style="width:100%;font-size:12px">' +
      '<tr><th>마켓</th><th>상태</th><th>카테고리</th><th>사유</th><th>주의</th></tr>' +
      body + '</table>';
  }

  async function fillPreflight(id, panel) {
    panel.innerHTML = '<td colspan="5">점검 중…</td>';
    let res = null;
    try {
      res = await fetch(`/bulk/api/drafts/${id}/preflight`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }).then((r) => r.json());
    } catch (e) { res = null; }

    if (!res || !res.ok) {
      panel.innerHTML = '<td colspan="5">점검하지 못했습니다 — ' +
        esc((res && res.error) || '요청 실패') + '</td>';
      return;
    }
    panel.innerHTML = `<td colspan="5">${preflightHtml(id, res.rows)}` +
      '<p class="muted" style="font-size:11.5px;margin:6px 0 0">' +
      '「올릴 수 있음」은 <b>필수값이 다 찼다</b>는 뜻입니다 — 등록 성공 보장이 아닙니다. ' +
      '오른쪽 「주의」를 함께 확인하세요.</p></td>';
  }

  async function runPreflight(btn) {
    const id = btn.dataset.pre;
    const t = document.getElementById('bd-list');
    const owner = btn.closest('tr');
    // 다시 누르면 접는다 — 모달 없이 그 행 아래에서 펼쳤다 접었다 한다.
    const open = t.querySelector(`tr[data-pre-for="${id}"]`);
    if (open) { open.remove(); return; }
    t.querySelectorAll('tr[data-pre-for]').forEach((r) => r.remove());

    const panel = document.createElement('tr');
    panel.setAttribute('data-row', '1');
    panel.setAttribute('data-pre-for', id);
    owner.after(panel);

    btn.disabled = true;
    await fillPreflight(id, panel);
    btn.disabled = false;
  }

  /* 「상세에서 빼기」 — 체크한 주소만 서버에 보내 상세에서 뺀다.
     ★ 자동이 아니다. 사장님이 고른 것만, 누른 그때만 빠진다((나)안).
     뺀 뒤에는 점검을 다시 돌려 4마켓 행을 한꺼번에 갱신한다(같은 상세라서). */
  async function removeForeignAssets(btn) {
    const id = btn.dataset.faRemove;
    const box = btn.closest('td');
    const urls = Array.from(box.querySelectorAll('[data-fa-url]'))
      .filter((c) => c.checked).map((c) => c.dataset.faUrl);
    if (!urls.length) { alert('뺄 이미지를 하나 이상 골라 주세요.'); return; }
    if (!confirm(`${urls.length}개를 상세에서 뺍니다. 되돌리려면 다시 크롤해야 합니다.`)) return;

    btn.disabled = true;
    let res = null;
    try {
      res = await fetch(`/bulk/api/drafts/${id}/detail/remove-assets`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls }),
      }).then((r) => r.json());
    } catch (e) { res = null; }
    btn.disabled = false;

    if (!res || !res.ok) {
      alert('빼지 못했습니다 — ' + ((res && res.error) || '요청 실패'));
      return;
    }
    const panel = document.querySelector(`tr[data-pre-for="${id}"]`);
    if (panel) await fillPreflight(id, panel);
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
    /* 판매가 0 = 「아직 안 정했다」(크롤 초안). 칸에 0 을 그리면 '0원으로 정했다'로
       읽혀 그대로 저장될 수 있다 — 빈 칸으로 두고 사람이 정하게 한다. */
    setVal('bd_sale_price', d.sale_price > 0 ? d.sale_price : '');
    setVal('bd_normal_price', d.normal_price);
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

  /* ── 「등록」 — 여러 마켓에 한 번에 (M4-6) ──────────────────────────────────
     예전엔 prompt 로 마켓 1개를 고르고 결과도 1개만 봤다. 이제는
       ① 「등록」을 누르면 **사전점검부터** 돌려 마켓별 상태를 표로 보여주고
       ② 올릴 수 있는 마켓만 체크박스가 켜진 채로 준다(못 올리는 마켓은 잠금+사유)
       ③ 「선택한 마켓에 등록」 한 번으로 복수 라우트를 불러 **건별 결과표**를 그린다.
     카테고리는 confirmed 맵핑이 있으면 서버가 자동으로 쓰고, 없을 때만 그 행의
     「고르기」가 기존 검색 흐름을 탄다 — 프롬프트 연쇄가 그 한 마켓에만 남는다.
     ★ 새 스타일을 만들지 않는다 — 기존 카드·표·.dot·.btn 클래스만 쓴다. */
  const MKTS = ['smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'];
  //: 계정 키를 직접 넣을 수 있는 마켓. 스스·쿠팡은 아직 기본 계정만(서버가 막는다).
  const ACCT_MKTS = ['auction', 'gmarket', 'eleven11', 'lotteon'];
  // unknown = 등록 스레드가 그 마켓을 부르던 중 끊긴 것. 성공도 실패도 아니라서
  // 「확인 필요」다 — 「실패」로 칠하면 이미 올라간 상품(유령)을 못 찾는다.
  // already   = 이미 올라가 있어 **부르지 않은** 마켓. 실패도 건너뜀도 아니다.
  // uncertain = 올라갔는지 몰라서 **부르지 않은** 마켓(장부가 잠갔다).
  const REG_LABEL = { ok: '등록됨', failed: '실패', blocked: '막힘', skipped: '건너뜀',
                      unknown: '확인 필요', already: '이미 등록됨',
                      uncertain: '확인 필요(안 보냄)' };
  // 색은 기존 클래스(.dot.ok/.warn/.danger)를 그대로 — 새 스타일 없음.
  const REG_DOT = { ok: 'ok', failed: 'danger', blocked: 'danger', skipped: 'warn',
                    unknown: 'warn', already: 'na', uncertain: 'warn' };

  // 마켓별 "카테고리 칸"의 뜻이 다르다 — 안내문을 정확히(조용한 오입력 방지)
  const CAT_HINT = {
    smartstore: '스마트스토어 리프 카테고리 ID:',
    coupang: '쿠팡 카테고리 코드(displayCategoryCode):',
    auction: '옥션: ESM카테고리코드/사이트카테고리코드\n(예: 00120005002000000000/37500700)',
    gmarket: 'G마켓: ESM카테고리코드/사이트카테고리코드\n(예: 00120005002100000000/300006243)',
    eleven11: '11번가 최하위 카테고리 번호(dispCtgrNo)\n(예: 1011634)',
    lotteon: '롯데온: 본보기 기존 상품번호(spdNo, LO로 시작)\n같은 계정의 비슷한 카테고리 판매중 상품\n(예: LO2727500650)',
  };

  /* 열려 있는 등록 패널 1개의 상태.
     codes/keys 는 **이번 등록에 한정된 사용자 지정값**이다 — 서버는 confirmed 맵핑을
     항상 우선하므로, 여기 값은 맵핑이 없을 때만 쓰인다(추측이 확정값을 못 이긴다).
     redo 는 「다시 올리기」 opt-in — 이미 등록된 마켓에 한 번 더 올리겠다는 명시적
     선택이다(기본 꺼짐. 판정은 서버가 하고 여기는 그 뜻을 실어 보내기만 한다). */
  let regPanel = null;   // {id, tr, codes, keys, checked, redo, rows, detail}

  /* 「다시 올리기」를 켠 마켓 목록 — 서버 body 의 reregister 그대로. */
  function redoList(st) {
    return Object.keys(st.redo || {}).filter((m) => st.redo[m]);
  }

  async function learnMapping(srcSite, srcPath, market, code) {
    // 학습 저장 — 실패해도 등록 자체는 막지 않는다(맵핑은 편의 기능). 단, 조용히
    // 삼키기만 하면 저장이 안 됐다는 걸 아무도 모른다 — 최소한 콘솔 경고는 남긴다
    // (I3: 사용자 alert 는 흐름을 방해하니 금지, console.warn 은 방해 없이 흔적을 남김).
    try {
      const r = await fetch('/bulk/api/catmap/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: srcSite, path: srcPath, market, code }),
      });
      const body = await r.json().catch(() => null);
      if (!r.ok || !body || !body.ok) {
        console.warn('[learnMapping] 맵핑 학습 저장 실패 — ', market, code, body && body.error);
      }
    } catch (e) {
      console.warn('[learnMapping] 맵핑 학습 저장 요청 실패 — ', market, code, e);
    }
  }

  /* 마켓 1곳의 카테고리를 정한다 → 코드 문자열, 또는 취소면 null.
     예전 등록 흐름(맵핑 자동/후보확정/사전검색/ESM표준코드 보완)을 **그대로** 옮겼다. */
  async function chooseCategory(draftId, market, detail) {
    const srcSite = detail && detail.source_site;
    const srcPath = detail && detail.source_category_path;
    let cat = '';

    // M2: 소싱처 드래프트면 catmap/resolve 로 먼저 판정한다 —
    // confirmed=자동 / suggested=후보선택확정 / none=기존 검색(선택 시 학습).
    if (srcSite && srcPath) {
      const rs = await fetch('/bulk/api/catmap/resolve?source=' + encodeURIComponent(srcSite) +
        '&path=' + encodeURIComponent(srcPath) + '&market=' + market)
        .then(r => r.json()).catch(() => null);
      if (rs && rs.ok && rs.status === 'confirmed' && rs.code) {
        // I2-2: alert(강제 통보) 대신 confirm(선택권) — 잘못 확정된 맵핑이라도 취소하면
        // 아래 기존 검색 흐름으로 빠져 직접 고를 수 있다.
        const label = (rs.path || String(rs.code)) + ' [' + rs.code + ']';
        const proceed = confirm('맵핑 자동: ' + label + '\n\n이 카테고리로 등록할까요?\n취소하면 직접 고릅니다');
        if (proceed) {
          cat = String(rs.code);
        } else if (rs.map_id) {
          // 취소 = "이 자동 적용이 틀렸다". 그대로 두면 다음 등록에서 또 같은 걸 물어본다 —
          // 그 자리에서 지울 기회를 준다(map_id 가 있어야 가능. 실패해도 등록은 계속).
          if (confirm('이 맵핑이 틀렸다면 지울까요?\n(지우면 다음부터 다시 직접 고르게 됩니다)')) {
            try {
              const dr2 = await fetch('/bulk/api/catmap/' + rs.map_id, { method: 'DELETE' });
              const db = await dr2.json().catch(() => null);
              if (!dr2.ok || !db || !db.ok) {
                alert('맵핑을 지우지 못했습니다 — ' + ((db && db.error) || dr2.status));
              }
            } catch (e) {
              alert('맵핑 삭제 요청 실패 — ' + e);
            }
          }
        }
      } else if (rs && rs.ok && rs.status === 'suggested' && (rs.candidates || []).length) {
        const menu = rs.candidates.map((c, i) => (i + 1) + ') ' + (c.path || c.name) + '  [' + c.code + ']').join('\n');
        const pick2 = prompt('맵핑 후보를 골라 확정해 주세요 (1~' + rs.candidates.length + ')\n\n' + menu);
        if (pick2 !== null) {
          const idx2 = parseInt(pick2, 10) - 1;
          if (idx2 >= 0 && idx2 < rs.candidates.length) {
            cat = String(rs.candidates[idx2].code);
            await learnMapping(srcSite, srcPath, market, cat);
          }
        }
      }
      // status === 'none' (또는 후보를 못 골랐으면) → 아래 기존 검색 흐름으로 진행
    }

    // 카테고리 사전(market_categories) 검색어 입력 → 후보 목록에서 번호 선택.
    // '#코드' 로 시작하면 사전 검색을 건너뛰고 코드를 직접 입력한 것으로 취급(탈출구).
    while (!cat) {
      const q = prompt(CAT_HINT[market] + '\n\n카테고리 검색어를 입력하세요 (예: 여성운동화)\n' +
        '말을 띄어서 여러 개 넣으면 더 좁혀집니다 (예: 남성의류 티셔츠) — 찾는 물건은 맨 뒤에.\n' +
        '(코드를 이미 알면 #코드 로 직접 입력)');
      if (q === null) return null;                              // 취소
      const trimmed = q.trim();
      if (!trimmed) continue;
      if (trimmed.startsWith('#')) { cat = trimmed.slice(1).trim(); break; }   // 직접 입력 탈출구
      const sr = await fetch(`/bulk/api/category-search?market=${market}&q=${encodeURIComponent(trimmed)}`)
        .then(r => r.json()).catch(() => null);
      if (!sr) { alert('검색 요청 실패'); continue; }
      if (!sr.ok) { alert(sr.error); continue; }                 // 빈 사전 안내 = "설정 탭에서 수집 먼저"
      if (!sr.count) { alert('검색 결과 없음: ' + trimmed); continue; }
      const menu = sr.rows.map((row, i) => (i + 1) + ') ' + (row.path || row.name) + '  [' + row.code + ']').join('\n');
      // [2026-07-24] 상한에 걸려 잘렸으면 그 사실을 말한다 — 조용히 자르면 사장님은
      //   「이게 전부」로 믿고 목록에 없는(더 정확한) 카테고리를 못 찾는다.
      //   서버가 관련도순으로 줄 세워 주므로 위쪽이 더 정확한 후보다.
      const cut = (sr.total && sr.total > sr.count)
        ? ('\n※ 전체 ' + sr.total + '건 중 관련도가 높은 ' + sr.count + '건만 보여드립니다'
           + '\n   더 좁히시려면 말을 띄어서 더 넣으세요 (예: 「남성의류 티셔츠」).'
           + ' 찾는 물건은 맨 뒤에 쓰시면 됩니다.\n')
        : '';
      const pick = prompt('번호를 고르세요 (1~' + sr.count + ')' + cut + '\n' + menu);
      // 취소는 **null 로** 돌려준다 — 이 함수의 계약이 「코드 문자열 또는 null」이다
      //   (main 의 bare return 은 undefined 라 계약이 갈린다).
      if (pick === null) return null;
      const idx = parseInt(pick, 10) - 1;
      if (idx >= 0 && idx < sr.rows.length) {
        cat = sr.rows[idx].code;
        if (srcSite && srcPath) await learnMapping(srcSite, srcPath, market, cat);
      } else alert('올바른 번호가 아닙니다 (1~' + sr.count + ')');
    }

    // 옥션·G마켓 등록은 'ESM표준코드/사이트코드' 쌍이 필요한데 사전은 사이트코드만 안다.
    // 미완성 코드로 조용히 실패하지 않게 여기서 보완받는다 — 맵핑 자동/후보선택/검색
    // 어느 경로로 cat 이 정해졌든 공통 적용.
    if (cat && (market === 'auction' || market === 'gmarket') && !cat.includes('/')) {
      const sd = prompt('옥션·G마켓은 ESM표준코드가 따로 필요합니다.\n' +
        'ESM표준코드를 입력하세요 (기존 상품 상세에서 확인, 예: 00120005002000000000)\n' +
        '→ 최종 코드는 "ESM표준코드/' + cat + '" 형태가 됩니다:');
      if (sd === null) return null;
      const sdTrim = sd.trim();
      if (!sdTrim) { alert('ESM표준코드 없이는 등록할 수 없습니다 — 다시 검색하거나 #코드/코드 로 직접 입력하세요'); return null; }
      cat = sdTrim + '/' + cat;
    }
    return cat.trim();
  }

  /* 지금 화면의 체크 상태를 상태 객체로 걷어 둔다 — 다시 그릴 때 사용자의 선택이
     초기화되면 「내가 껐는데 다시 켜져 있다」가 되어 원치 않는 마켓에 올라간다. */
  function captureChecks() {
    if (!regPanel) return;
    regPanel.tr.querySelectorAll('input[data-m]').forEach((el) => {
      // 잠긴(disabled) 체크박스는 **사용자의 선택이 아니다** — 그걸 false 로 기억하면
      // 나중에 「다시 올리기」로 풀렸을 때도 꺼진 채로 남는다.
      if (!el.disabled) regPanel.checked[el.dataset.m] = el.checked;
    });
    regPanel.tr.querySelectorAll('input[data-redo]').forEach((el) => {
      regPanel.redo[el.dataset.redo] = el.checked;
    });
    regPanel.tr.querySelectorAll('input[data-acct]').forEach((el) => {
      const v = el.value.trim();
      if (v) regPanel.keys[el.dataset.acct] = v;
      else delete regPanel.keys[el.dataset.acct];
    });
  }

  function regPickRowHtml(r, st) {
    const on = r.status === 'ready' && st.checked[r.market] !== false;
    const src = r.category_source === 'mapped' ? ' (맵핑 확정)'
      : (r.category_source === 'given' ? ' (이번에 지정)' : '');
    const cav = (r.caveats || []).map((c) => `· ${esc(c)}`).join('<br>');
    // 계정 칸: 4마켓만 입력 가능. 스스·쿠팡에 칸을 주면 「넣어도 되는 줄」 알고 넣었다가
    // 서버가 막는다(기록과 실제 전송 계정이 어긋나는 것을 막는 가드).
    const acct = ACCT_MKTS.indexOf(r.market) >= 0
      ? `<input data-acct="${esc(r.market)}" value="${esc(st.keys[r.market] || '')}" ` +
        'placeholder="기본 계정" size="9" autocomplete="off">'
      : '<span class="muted">기본</span>';
    // [C1·C-2] 이미 등록됐거나 올라갔는지 모르는 마켓 — 잠기고 체크가 꺼진 채로 나오고,
    // 「다시 올리기」를 켜야만 다시 올릴 수 있다(기본 꺼짐). 켜면 서버가 다시 점검한다.
    // 불확실한 마켓은 **확인 수단을 먼저** 준다 — 확인 없이 다시 올리면 유령이 둘 된다.
    const look = r.status === 'uncertain' && r.lookup_supported
      ? ` <button type="button" class="btn btn-sm" data-lookup="${esc(r.market)}">` +
        '마켓에서 상품 찾아보기</button>' : '';
    // ★★ [4차리뷰 치명①] 확정 칸은 **6마켓 전부**에 낸다(조회 API 유무와 무관).
    //   ★ [5차리뷰 I2] 그 칸을 「다시 올리기」 안에 끼워 넣으면 실제 규칙이
    //     `confirm_supported AND status ∈ {registered, uncertain}` 이 되어, 바로 위
    //     주석이 말하는 「confirm_supported 하나만 본다」와 갈린다 — **밖으로 뺀다.**
    const cfm = confirmBoxHtml(r, null);
    const redo = (r.status === 'registered' || r.status === 'uncertain')
      ? '<br>' + look + '<label style="font-size:11.5px;margin-left:6px">' +
        `<input type="checkbox" data-redo="${esc(r.market)}"` +
        `${st.redo[r.market] ? ' checked' : ''}> 다시 올리기(같은 상품을 한 번 더)</label>`
      : '';
    return '<tr>' +
      `<td><input type="checkbox" data-m="${esc(r.market)}"` +
      `${on ? ' checked' : ''}${r.status === 'ready' ? '' : ' disabled'}></td>` +
      `<td>${esc(PRE_MARKET[r.market] || r.market)}` +
      `${r.status === 'ready' ? '' : ' 🔒'}</td>` +
      `<td><span class="dot ${PRE_DOT[r.status] || 'na'}"></span>` +
      `${esc(PRE_LABEL[r.status] || r.status)}</td>` +
      `<td>${r.category_code ? esc(r.category_code) + esc(src) : '—'} ` +
      `<button type="button" class="btn btn-sm" data-cat="${esc(r.market)}">고르기</button></td>` +
      `<td>${acct}</td>` +
      `<td>${esc(r.reason) || '—'}${redo}${cfm}${cav ? '<br>' + cav : ''}</td></tr>`;
  }

  /* 등록 패널 = 사전점검 결과 + 마켓 체크박스. 점검은 마켓 API 를 안 부르므로
     몇 번을 다시 돌려도 위험이 없다(순수 컴파일 + 우리 DB 조회뿐). */
  async function renderRegPanel() {
    const st = regPanel;
    if (!st) return;
    st.tr.innerHTML = '<td colspan="5">점검 중…</td>';
    let res = null;
    try {
      res = await fetch(`/bulk/api/drafts/${st.id}/preflight`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markets: MKTS, category_codes: st.codes,
                               account_keys: st.keys,
                               reregister: redoList(st) }),
      }).then((r) => r.json());
    } catch (e) { res = null; }
    if (!regPanel || regPanel !== st) return;                    // 그 사이 닫혔다
    if (!res || !res.ok) {
      st.tr.innerHTML = '<td colspan="5">점검하지 못했습니다 — ' +
        esc((res && res.error) || '요청 실패') + '</td>';
      return;
    }
    st.rows = res.rows || [];
    const readyN = st.rows.filter((r) => r.status === 'ready').length;
    st.tr.innerHTML = '<td colspan="5">' +
      '<table style="width:100%;font-size:12px">' +
      '<tr><th></th><th>마켓</th><th>상태</th><th>카테고리</th><th>계정</th>' +
      '<th>사유·주의</th></tr>' +
      st.rows.map((r) => regPickRowHtml(r, st)).join('') + '</table>' +
      '<p class="muted" style="font-size:11.5px;margin:6px 0">' +
      '체크한 마켓만 올립니다 — 마켓을 <b>하나씩 순서대로</b> 부르고, 한 곳이 실패해도 ' +
      '나머지는 계속합니다. 「올릴 수 있음」은 <b>필수값이 다 찼다</b>는 뜻이지 ' +
      '등록 성공 보장이 아닙니다.</p>' +
      `<button type="button" class="btn btn-primary btn-sm" data-regrun="${st.id}"` +
      `${readyN ? '' : ' disabled'}>선택한 마켓에 등록</button> ` +
      `<button type="button" class="btn btn-sm" data-regre="${st.id}">다시 점검</button>` +
      '<div data-regout></div></td>';
    // [M4-7] 이 드래프트가 이미 등록 중이면(다른 탭·다른 사람이 눌렀거나 새로고침 뒤)
    // 그 실행의 진행 상황을 그대로 이어서 보여준다 — 안 보여주면 "아무 일도 없다"고
    // 믿고 다시 눌러 같은 상품을 두 번 올린다.
    resumeRegisterIfRunning(st);
  }

  async function resumeRegisterIfRunning(st) {
    let body = null;
    try {
      body = await fetch(`/bulk/api/drafts/${st.id}/register/status`).then((r) => r.json());
    } catch (e) { return; }
    if (!body || !body.ok || !regPanel || regPanel !== st) return;
    if (!body.running && !(body.rows || []).length) return;   // 시작한 적 없음
    const out = st.tr.querySelector('[data-regout]');
    if (out) out.innerHTML = regResultHtml(body);
    if (body.running) pollRegister(st, out, st.tr.querySelector('[data-regrun]'));
  }

  /* 건별 결과표 — 성공·실패가 섞여도 각각 그대로 보인다.
     ★ 마켓이 준 원문(raw)을 버리지 않는다. 4xx 본문이 진짜 실패 사유다.
     ★★ [M4-7] 등록이 백그라운드로 돌기 때문에 이 표는 **폴링할 때마다 다시 그려진다** —
        마켓 하나가 끝날 때마다 그 줄이 확정돼 채워진다. 아직 부르지 않은 마켓은
        「대기」로 따로 보여준다(빈 줄이면 "실패했나?" 로 오해한다). */
  function regResultHtml(body) {
    const rows = (body.rows || []).map((r) => {
      const notes = (r.notes || []).map((c) => `· ${esc(c)}`).join('<br>');
      const detail = r.error || r.reason || '';
      const code = r.error_code
        ? ` <span class="muted">[${esc(r.error_code)}]</span>` : '';
      const raw = r.raw
        ? `<br><span class="muted">마켓 응답: ${esc(String(r.raw).slice(0, 600))}</span>` : '';
      const exc = (r.excluded || []).length
        ? '<br>빠진 옵션: ' + esc(r.excluded.map(
            (x) => `${x.color}/${x.size} — ${x.reason}`).join(' · '))
        : '';
      // 불확실한 마켓만 「마켓에서 확인」 버튼을 준다 — 이름으로 찾는 조회 API 가 있는
      // 마켓에서만 켜진다(없는 마켓에 버튼을 달면 눌러도 못 찾고 "없다"는 거짓 확신을 준다).
      const look = (r.status === 'unknown' && r.lookup_supported)
        ? `<br><button type="button" class="btn btn-sm" data-lookup="${esc(r.market)}">` +
          '마켓에서 상품 찾아보기</button>' : '';
      // [4차리뷰 치명①·사소⑤] 확정 칸은 **서버가 준 confirm_supported 하나만** 본다 —
      //   화면이 따로 조건을 세우면(status 목록 등) 서버와 갈린다(그게 그 구멍이었다).
      const cfm = confirmBoxHtml(r, null);
      return '<tr>' +
        `<td>${esc(PRE_MARKET[r.market] || r.market)}</td>` +
        `<td><span class="dot ${REG_DOT[r.status] || 'na'}"></span>` +
        `${esc(REG_LABEL[r.status] || r.status)}</td>` +
        `<td>${r.market_product_id ? esc(r.market_product_id) : '—'}</td>` +
        `<td>${esc(detail) || '—'}${code}${raw}${exc}${look}${cfm}</td>` +
        `<td>${notes || '—'}</td></tr>`;
    }).join('');
    // 아직 손도 안 댄 마켓 — 「안 올라갔다」가 확실한 유일한 칸이다(부른 적이 없다).
    //   ★ [5차 I5] 단, 장부가 이미 잠근 마켓이면 **왜 안 불렀는지**를 같이 말한다.
    //     안 그러면 같은 화면이 「아직 부르지 않았습니다」와 「이미 등록됨」을 동시에 말한다.
    const lockedMap = body.pending_locked || {};
    const pend = (body.pending || []).map((m) => {
      const lk = lockedMap[m];
      const why = lk
        ? `이 실행에서는 부르지 않았습니다 — ${lk.kind === 'registered' ? '이미 등록됨' : '확인 필요'}` +
          `${lk.market_product_id ? ' (상품번호 ' + esc(lk.market_product_id) + ')' : ''}`
        : '아직 부르지 않았습니다';
      return '<tr>' +
        `<td>${esc(PRE_MARKET[m] || m)}</td>` +
        `<td><span class="dot ${lk ? (lk.kind === 'registered' ? 'na' : 'warn') : 'na'}"></span>` +
        `${lk ? esc(REG_LABEL[lk.kind === 'registered' ? 'already' : 'uncertain']) : '대기'}</td>` +
        `<td>${lk && lk.market_product_id ? esc(lk.market_product_id) : '—'}</td>` +
        `<td class="muted">${why}</td><td>—</td></tr>`;
    }).join('');
    const s = body.summary || {};
    const head = body.running
      ? '<p class="muted" style="font-size:11.5px;margin:10px 0 4px">등록 중… ' +
        `${body.done || 0}/${body.total || 0} 마켓` +
        (body.current_market
          ? ` · 지금 ${esc(PRE_MARKET[body.current_market] || body.current_market)} 처리 중`
          : '') + ' (마켓을 하나씩 순서대로 올립니다)</p>'
      : '<p class="muted" style="font-size:11.5px;margin:10px 0 4px">결과 — ' +
        `등록 ${s.ok || 0} · 실패 ${s.failed || 0} · 막힘 ${s.blocked || 0} · ` +
        `건너뜀 ${s.skipped || 0}` +
        (s.already ? ` · 이미 등록됨 ${s.already}` : '') +
        ((s.unknown || s.uncertain)
          ? ` · <b>확인 필요 ${(s.unknown || 0) + (s.uncertain || 0)}</b>` : '') + '</p>';
    // ★ 불확실 경고 — 서버 문구를 **그대로** 보여준다(요약·완곡화 금지).
    //   성공도 실패도 아니라는 사실이 이 화면에서 가장 중요한 정보다.
    const warn = (body.uncertain && body.uncertain.message)
      ? '<p style="font-size:12px;margin:6px 0;padding:8px;border-radius:6px;' +
        'background:#fff4e5"><b>⚠ ' + esc(body.uncertain.message) + '</b></p>' : '';
    const err = body.error
      ? `<p class="muted" style="font-size:11.5px;margin:4px 0">${esc(body.error)}</p>` : '';
    return head + warn + err +
      '<table style="width:100%;font-size:12px">' +
      '<tr><th>마켓</th><th>결과</th><th>상품번호</th>' +
      '<th>사유(마켓 응답 원문)</th><th>주의</th></tr>' + rows + pend + '</table>' +
      '<div data-lookupout></div>';
  }

  /* 목록을 새로고침해도 결과표가 사라지지 않게 패널을 다시 붙인다.
     loadList() 는 tr[data-row] 를 전부 지우는데 등록 패널도 그중 하나다 — 그냥 부르면
     방금 나온 건별 결과가 눈앞에서 사라져 실패 사유를 읽을 수 없다. */
  async function refreshListKeepingPanel() {
    const st = regPanel;
    await loadList();
    if (!st || regPanel !== st) return;
    const owner = document.querySelector(`#bd-list [data-reg="${st.id}"]`);
    if (owner) owner.closest('tr').after(st.tr);
    else regPanel = null;                       // 그 드래프트가 목록에서 사라졌다
  }

  /* 진행 상황 폴링 — 마켓 하나가 끝날 때마다 그 줄이 표에 확정된다.
     [M4-7] 등록은 이제 백그라운드로 돈다. 서버가 6마켓을 한 요청 안에서 처리하면
     gunicorn(--timeout 60, sync 워커)이 워커를 죽여 요청도 응답도 증발하고, 이미
     마켓에 만들어진 상품은 회수되지 못한 채 남는다(과거이력의 유령 상품 사고).
     ★ 폴링이 실패해도 「실패」로 칠하지 않는다 — 화면이 못 읽은 것과 등록이 안 된 것은
       완전히 다른 사실이다. */
  const REG_POLL_MS = 2000;

  async function pollRegister(st, out, runBtn) {
    if (st.polling) return;                       // 폴링은 패널당 1개만
    st.polling = true;
    try {
      for (;;) {
        if (!regPanel || regPanel !== st) return; // 패널이 닫혔다 — 조용히 그만둔다
        let body = null;
        try {
          body = await fetch(`/bulk/api/drafts/${st.id}/register/status`)
            .then((r) => r.json());
        } catch (e) { body = null; }
        if (!regPanel || regPanel !== st) return;
        if (body && body.ok) {
          if (out) out.innerHTML = regResultHtml(body);
          if (!body.running) {
            if (runBtn) runBtn.disabled = false;
            await refreshListKeepingPanel();
            return;
          }
        } else if (out) {
          // [5차 S4] 한 줄만 유지한다 — beforeend 면 2초마다 무한히 쌓여 화면을 덮는다.
          let warn = out.querySelector('[data-poll-warn]');
          if (!warn) {
            warn = document.createElement('p');
            warn.setAttribute('data-poll-warn', '1');
            warn.className = 'muted';
            warn.style.fontSize = '11.5px';
            out.appendChild(warn);
          }
          warn.textContent = '진행 상황을 못 읽었습니다 — 다시 시도합니다. '
            + '(등록이 실패했다는 뜻은 아닙니다)';
        }
        await new Promise((r) => setTimeout(r, REG_POLL_MS));
      }
    } finally {
      st.polling = false;
    }
  }

  async function runRegister(runBtn) {
    const st = regPanel;
    if (!st) return;
    captureChecks();
    const markets = (st.rows || [])
      .filter((r) => r.status === 'ready' && st.checked[r.market] !== false)
      .map((r) => r.market);
    if (!markets.length) { alert('올릴 마켓을 하나 이상 골라 주세요.'); return; }
    const out = st.tr.querySelector('[data-regout]');
    runBtn.disabled = true;
    if (out) out.innerHTML = '<p class="muted" style="font-size:11.5px">등록을 시작하는 중…</p>';
    let res = null;
    let body = null;
    try {
      res = await fetch(`/bulk/api/drafts/${st.id}/register`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markets, category_codes: st.codes,
                               account_keys: st.keys,
                               // 서버도 같은 판정을 한다 — 화면이 안 보내면 이미 등록된
                               // 마켓은 서버가 막는다(가드는 서버가 진짜다).
                               reregister: redoList(st) }),
      });
      body = await res.json();
    } catch (e) { res = null; body = null; }

    // 409 = 이 상품이 이미 등록 중. 다시 시작하지 않고 **진행 중인 그 실행**을 보여준다
    // (여기서 또 시작하면 같은 상품이 두 번 올라간다 = 유령 상품).
    if (res && res.status === 409) {
      if (out) out.innerHTML = '<p class="muted" style="font-size:11.5px">' +
        esc((body && body.error) || '이미 등록이 진행 중입니다') + '</p>';
      pollRegister(st, out, runBtn);
      return;
    }
    if (!res || !body || !body.ok) {
      // ★ 응답을 못 받은 등록은 '안 됐다'가 아니라 '모른다' 다 — 과거이력의 유령 상품
      //   사고(502 로 워커가 죽어 롤백이 안 돈 채 판매중으로 남음)를 그대로 경고한다.
      runBtn.disabled = false;
      if (out) {
        out.innerHTML = '<p class="muted" style="font-size:11.5px">등록 요청이 실패했습니다 — ' +
          esc((body && body.error) || '요청 실패') + '<br>' +
          '응답을 못 받았다는 것은 「안 올라갔다」가 아니라 「모른다」입니다 — ' +
          '마켓에서 상품이 생겼는지 반드시 확인해 주세요.</p>';
      }
      await refreshListKeepingPanel();
      return;
    }
    // 202 = 「시작했다」만 확인된 상태. 결과는 폴링으로 채워 나간다.
    st.jobId = body.job_id;
    pollRegister(st, out, runBtn);
  }

  /* 유령 상품 확인 — 그 마켓에 이 상품명이 실제로 있는지 조회만 한다(쓰기 없음).
     0건이 「안 올라갔다」의 증명은 아니라는 점을 서버 note 로 같이 보여준다. */
  async function runMarketLookup(btn) {
    const st = regPanel;
    if (!st) return;
    const market = btn.dataset.lookup;
    // 답은 **누른 버튼과 같은 줄**에 쓴다. [5차 S3] 예전엔 패널 전체에서 첫 번째
    //   [data-lookupout-m] 을 잡아, 결과표에서 눌러도 위쪽 점검표 밑에 답이 떴다.
    const near = btn.closest('tr') || st.tr;
    const out = near.querySelector(`[data-lookupout-m="${market}"]`)
      || st.tr.querySelector(`[data-lookupout-m="${market}"]`)
      || st.tr.querySelector('[data-lookupout]');
    btn.disabled = true;
    if (out) out.innerHTML = '<p class="muted" style="font-size:11.5px">마켓에서 찾는 중…</p>';
    let body = null;
    try {
      body = await fetch(
        `/bulk/api/drafts/${st.id}/market-lookup?market=${encodeURIComponent(market)}`)
        .then((r) => r.json());
    } catch (e) { body = null; }
    btn.disabled = false;
    if (!out) return;
    if (!body || !body.ok) {
      out.innerHTML = '<p class="muted" style="font-size:11.5px">조회하지 못했습니다 — ' +
        esc((body && body.error) || '요청 실패') + '<br>' +
        '조회에 실패했다는 것은 「없다」가 아닙니다 — 판매자센터에서 직접 확인해 주세요.</p>';
      return;
    }
    // [3차리뷰 중요③] 찾았으면 **그 번호로 확정**할 수 있어야 한다. 확정 경로가 없으면
    //   「확인 필요」가 영구 교착이 되고, 남는 행동이 「다시 올리기 = 중복 감수」뿐이다.
    const hits = (body.rows || []).map((r) =>
      `· ${esc(r.code)} ${esc(r.name)} ` +
      `<button type="button" class="btn btn-sm" data-confirm-pid="${esc(r.code)}" ` +
      `data-confirm-market="${esc(body.market)}">이 상품번호로 확정</button>`).join('<br>');
    // [I1] 「무엇을 어디까지 봤는가」를 건수 바로 옆에 붙인다 — 0건이 「없다」인지
    //   「거기까진 못 봤다」인지는 이 한 줄로만 구분된다(그 구분이 곧 중복 등록 방지다).
    const scope = body.scope
      ? `<br><span class="muted">확인 범위: ${esc(body.scope)}` +
        `${body.complete ? '' : ' (상한에서 멈춤 — 그 뒤는 못 봤습니다)'}</span>`
      : '';
    out.innerHTML = '<p style="font-size:12px;margin:6px 0">' +
      `${esc(PRE_MARKET[body.market] || body.market)}에서 「${esc(body.query)}」 검색 — ` +
      `<b>${body.count}건</b>${scope}` + (hits ? '<br>' + hits : '') + '</p>' +
      `<p class="muted" style="font-size:11.5px;margin:0">${esc(body.note || '')}</p>`;
  }

  /* 「이 상품번호로 확정」 — 사람이 마켓에서 확인한 사실을 장부에 넣는다.
     ★ 이 버튼이 「확인 필요」의 정직한 결말이다. 눌러도 마켓을 부르지 않는다(기록만). */
  async function confirmMarketProduct(btn) {
    const st = regPanel;
    // 점검 패널에서 부르면 regPanel 이 없다 — 그때는 DOM 이 알려준 드래프트 id 를 쓴다.
    const draftId = (st && st.id) || btn.dataset.cfmDraft;
    if (!draftId) return;
    const market = btn.dataset.confirmMarket;
    const pid = btn.dataset.confirmPid;
    if (!confirm(`${PRE_MARKET[market] || market} 상품번호 ${pid} 로 확정할까요?\n\n` +
                 '확정하면 이 마켓은 「이미 등록됨」으로 잠기고, 가격·재고 자동갱신 ' +
                 '대상에 들어갑니다.')) return;
    if ('disabled' in btn) btn.disabled = true;
    let body = null;
    try {
      body = await postConfirm(draftId, market, pid, (st && st.keys[market]) || '', false);
    } catch (e) { body = null; }
    // ★ [5차 C1] 번호를 확인하지 못했다고 **확정을 영구히 막지 않는다.** 서버가
    //   needs_force 로 되물으면 그 사유를 그대로 보여주고, 사장님이 「그래도 확정」을
    //   고르면 다시 보낸다(막아 두면 남는 행동이 「다시 올리기 = 중복」뿐이다).
    if (body && body.needs_force) {
      if (!confirm(body.error + '\n\n그래도 이 번호로 확정할까요?')) {
        if ('disabled' in btn) btn.disabled = false;
        return;
      }
      try {
        body = await postConfirm(draftId, market, pid, (st && st.keys[market]) || '', true);
      } catch (e) { body = null; }
    }
    if (!body || !body.ok) {
      if ('disabled' in btn) btn.disabled = false;
      // 서버 사유를 그대로 보여준다 — 「그 번호를 마켓에서 못 찾았습니다」가 곧 답이다.
      alert('확정하지 못했습니다 — ' + ((body && body.error) || '요청 실패'));
      return;
    }
    if (body.note) alert(body.note);
    // 잠금 상태가 바뀌었으니 화면을 사실에 맞춘다(어느 패널에서 눌렀든).
    if (st) { delete st.redo[market]; renderRegPanel(); }
    else { refreshOpenPreflight(draftId); }
  }

  /* 확정 POST 한 번 — force 재시도가 같은 계약을 쓰게 한 곳에 둔다. */
  async function postConfirm(draftId, market, pid, accountKey, force) {
    return fetch(`/bulk/api/drafts/${draftId}/market-confirm`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ market, market_product_id: pid,
                             account_key: accountKey, force: !!force }),
    }).then((r) => r.json());
  }

  /* 점검 패널이 열려 있으면 다시 채운다(확정 뒤 잠금 상태가 바뀐다). */
  function refreshOpenPreflight(draftId) {
    const panel = document.querySelector(`#bd-list tr[data-pre-for="${draftId}"]`);
    if (panel) fillPreflight(draftId, panel);
  }

  document.getElementById('bd-list').addEventListener('change', (e) => {
    // 계정 키를 고치면 그 값으로 다시 점검한다(계정에 따라 올릴 수 있는지가 달라진다).
    const acct = e.target.closest('input[data-acct]');
    if (acct && regPanel) { captureChecks(); renderRegPanel(); return; }
    // [C1] 「다시 올리기」 — 켠 상태로 다시 점검한다(잠금이 풀리는지 그 자리에서 보인다).
    //   ★ [3차리뷰 사소④] 체크박스는 **자동으로 켜지 않는다.** 잠금을 푸는 것과 올리는
    //     것은 다른 결정이다 — 오클릭 한 번이 곧 「등록 대기」가 되면 안 된다.
    //     잠금이 풀린 뒤 사장님이 체크를 직접 켜야 그 마켓이 올라간다(두 번 확인).
    const redo = e.target.closest('input[data-redo]');
    if (redo && regPanel) {
      captureChecks();
      if (redo.checked) regPanel.checked[redo.dataset.redo] = false;
      renderRegPanel();
      return;
    }
    const chk = e.target.closest('input[data-m]');
    if (chk && regPanel) captureChecks();
  });

  document.getElementById('bd-list').addEventListener('click', async (e) => {
    const openBtn = e.target.closest('[data-open]');
    if (openBtn) { openDraft(openBtn.dataset.open); return; }
    const preBtn = e.target.closest('[data-pre]');
    if (preBtn) { runPreflight(preBtn); return; }
    // [2026-07-23 (나)안] 상세에서 타 마켓 이미지 빼기 — 점검 패널 안 버튼.
    const faBtn = e.target.closest('[data-fa-remove]');
    if (faBtn) { removeForeignAssets(faBtn); return; }

    const catBtn = e.target.closest('[data-cat]');
    if (catBtn) {
      if (!regPanel) return;
      captureChecks();
      const market = catBtn.dataset.cat;
      const code = await chooseCategory(regPanel.id, market, regPanel.detail);
      if (code) {
        regPanel.codes[market] = code;
        renderRegPanel();          // 새 코드로 다시 점검 → 초록으로 바뀌는지 바로 보인다
      }
      return;
    }
    const reBtn = e.target.closest('[data-regre]');
    if (reBtn) { captureChecks(); renderRegPanel(); return; }
    const runBtn = e.target.closest('[data-regrun]');
    if (runBtn) { runRegister(runBtn); return; }
    const lookBtn = e.target.closest('[data-lookup]');
    if (lookBtn) { runMarketLookup(lookBtn); return; }
    const cfmBtn = e.target.closest('[data-confirm-pid]');
    if (cfmBtn) { confirmMarketProduct(cfmBtn); return; }
    // 입력칸에 직접 넣은 번호로 확정(조회 API 가 없는 마켓의 유일한 탈출구).
    //   ★ [5차 C2] 점검 패널에는 regPanel 상태가 없다 — 드래프트 id 를 DOM 에서 찾는다.
    const cfmIn = e.target.closest('[data-cfm]');
    if (cfmIn) {
      const market = cfmIn.dataset.cfm;
      const box = cfmIn.closest('.cfm-box').querySelector(`[data-cfm-input="${market}"]`);
      const pid = (box && box.value || '').trim();
      if (!pid) { alert('마켓에서 확인한 상품번호를 넣어 주세요.'); return; }
      confirmMarketProduct({ dataset: { confirmMarket: market, confirmPid: pid,
                                        cfmDraft: cfmIn.closest('.cfm-box').dataset.cfmDraft } });
      return;
    }

    const btn = e.target.closest('[data-reg]');
    if (!btn) return;

    const id = btn.dataset.reg;
    const t = document.getElementById('bd-list');
    // 다시 누르면 접는다 — 점검 패널과 같은 규칙(모달 없이 그 행 아래에서 펼침).
    const open = t.querySelector(`tr[data-reg-for="${id}"]`);
    if (open) { open.remove(); regPanel = null; return; }
    t.querySelectorAll('tr[data-reg-for]').forEach((r) => r.remove());

    const panel = document.createElement('tr');
    panel.setAttribute('data-row', '1');
    panel.setAttribute('data-reg-for', id);
    panel.innerHTML = '<td colspan="5">점검 중…</td>';
    btn.closest('tr').after(panel);

    // 소싱처 분류(맵핑 판정의 재료). 조회에 실패해도 기존 검색 흐름으로 계속 진행한다.
    let detail = null;
    try {
      const dr = await fetch(`/bulk/api/drafts/${id}`).then((r) => r.json());
      if (dr && dr.ok) detail = dr.draft;
    } catch (err) { detail = null; }

    regPanel = { id, tr: panel, codes: {}, keys: {}, checked: {}, redo: {},
                 rows: [], detail };
    renderRegPanel();
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

  /* ══════════════════════════════════════════════════════════════════════
     0 소싱처 URL → 초안 (크롤 → 등록 다리)

     ★ 이 화면은 소싱처에 접속하지 않는다. 서버도 마찬가지다 —
       크롤은 이 PC(크롬 확장) 몫이고, 크롤 결과가 없으면 초안을 만들지 않고
       "먼저 크롤이 돌아야 합니다" 라고 말한다(CLAUDE.md 정합성 원칙 3).
     ★ 「만들었습니다」로 끝내지 않는다 — 무엇이 채워졌고 어느 마켓에 무엇이
       부족한지를 같은 화면에서 그대로 보여준다(조용한 실패 금지).
       마켓 표는 「점검」과 **같은 렌더러**(preflightHtml)를 쓴다.
     ══════════════════════════════════════════════════════════════════════ */
  const fuBtn = document.getElementById('bd-fromurl');
  const fuMsg = document.getElementById('bd-fromurl-msg');
  const fuOut = document.getElementById('bd-fromurl-out');

  /* 재고는 숫자만 세지 않는다 — 0(품절)·-1(확인불가)·null(미크롤)은 서로 다른 뜻이다.
     ★ 주석만 그렇게 써 놓고 화면은 평면 재고를 아예 안 그리고 있었다(리뷰 m5).
       숫자만 찍으면 -1 이 「재고 -1개」로 읽히므로 뜻으로 적는다. */
  function fuStock(v) {
    if (v === null || v === undefined) return '재고 미크롤';
    if (v < 0) return '재고 확인불가';
    if (v === 0) return '재고 품절(0)';
    return `재고 ${Number(v).toLocaleString('ko-KR')}개`;
  }

  function fuFilled(f) {
    const bits = [];
    if (f.brand) bits.push(`브랜드 ${esc(f.brand)}`);
    if (f.source_category_path) bits.push(`분류 ${esc(f.source_category_path)}`);
    bits.push(`옵션 ${f.options}개 (팔 수 있는 것 ${f.sellable_options}개)`);
    /* 평면 재고 — 옵션이 없는 상품은 이 값이 곧 판매 가능 여부다. */
    if (!f.options) bits.push(fuStock(f.stock_quantity));
    bits.push(`이미지 ${f.images}장`);
    bits.push(f.detail_html ? '상세설명 있음' : '상세설명 없음');
    bits.push(f.sale_price > 0
      ? `판매가 ${Number(f.sale_price).toLocaleString('ko-KR')}원`
      : '판매가 미정');
    return bits.join(' · ');
  }

  function fuRowHtml(r) {
    if (!r.ok) {
      return '<div class="card" style="margin-top:10px">' +
        `<b>${esc(r.url)}</b><p class="hint">${esc(r.error)}</p></div>`;
    }
    const warn = (r.warnings || []).length
      ? '<ul class="hint" style="margin:6px 0 0;padding-left:18px">' +
        r.warnings.map((w) => `<li>${esc(w)}</li>`).join('') + '</ul>'
      : '';
    const human = '<details style="margin-top:8px"><summary class="hint">' +
      '크롤이 줄 수 없어 사람이 채워야 하는 칸</summary>' +
      '<ul class="hint" style="margin:6px 0 0;padding-left:18px">' +
      (r.human_only || []).map((h) => `<li>${esc(h)}</li>`).join('') + '</ul></details>';
    /* ★ 갱신이 무엇을 덮었는지 접지 않고 그대로 보여준다(리뷰 I3).
         「기존 초안을 갱신했습니다」 한 줄로 끝내면 사람이 넣은 값이 덮여도 아무도 모른다. */
    const changed = (r.changes || []).length
      ? '<div class="card" style="margin-top:8px;padding:8px 10px">' +
        '<b style="font-size:12px">이번 갱신이 바꾼 것</b>' +
        '<ul class="hint" style="margin:4px 0 0;padding-left:18px">' +
        r.changes.map((c) => `<li>${esc(c)}</li>`).join('') + '</ul></div>'
      : '';
    return '<div class="card" style="margin-top:10px">' +
      `<b>#${r.draft_id} ${esc(r.filled.name) || '(상품명 없음)'}</b> ` +
      `<span class="hint">${r.created ? '새로 만들었습니다' : '기존 초안을 갱신했습니다'}` +
      ` · ${esc(r.source_site)}</span>` +
      `<p class="hint" style="margin:4px 0 0">${fuFilled(r.filled)}</p>` +
      changed + warn + human +
      `<div style="margin-top:10px">${preflightHtml(r.missing)}</div>` +
      '<button type="button" class="btn btn-sm" data-fu-open="' + r.draft_id + '">' +
      '폼으로 열기</button></div>';
  }

  if (fuBtn) fuBtn.addEventListener('click', async () => {
    const urls = ($('bd_src_urls').value || '').split('\n')
      .map((s) => s.trim()).filter(Boolean);
    if (!urls.length) { fuMsg.textContent = '소싱처 상품 URL 을 붙여넣어 주세요.'; return; }
    fuBtn.disabled = true;
    fuMsg.textContent = '만드는 중…';
    fuOut.innerHTML = '';
    let res = null;
    try {
      res = await fetch('/bulk/api/drafts/from-url', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // 1건이어도 urls 로 보낸다 — 응답 모양이 한 가지라 화면 분기가 없다.
        body: JSON.stringify({ urls: urls }),
      }).then((r) => r.json());
    } catch (e) { res = { ok: false, error: e.message }; }
    fuBtn.disabled = false;

    if (!res || !res.ok) {
      fuMsg.textContent = '만들지 못했습니다 — ' + ((res && res.error) || '요청 실패');
      return;
    }
    const rows = res.rows || [];
    const failed = rows.length - res.made;
    fuMsg.textContent = `${res.made}건을 만들었습니다.`
      + (failed ? ` (${failed}건은 만들지 못했습니다 — 아래 사유)` : '');
    fuOut.innerHTML = rows.map(fuRowHtml).join('');
    loadList();
  });

  if (fuOut) fuOut.addEventListener('click', (e) => {
    const b = e.target.closest('[data-fu-open]');
    if (b) openDraft(Number(b.dataset.fuOpen));
  });

  setEditing(null);
  loadList();
})();

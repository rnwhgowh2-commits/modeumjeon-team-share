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

  loadList();
})();

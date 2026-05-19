/* ─────────────────────────────────────────────────────────────
 * 혜택 추가 폼 인터랙션 (v7.1 A2 — 무채색)
 *
 * 동작:
 *   1. .pop-add 클릭 → .add-form toggle (hidden 제거 + 폼 reset)
 *   2. .pill 클릭 → 단위 자동 전환 (% ↔ 원) + active 토글
 *   3. .scope-list .item 클릭 → 단일 선택 (4 scope)
 *   4. 입력 변경 시 impact preview 실시간 갱신 (계산식 + 영향 옵션 수)
 *   5. .save 클릭 → POST /api/benefits/crud → 성공 시 매트릭스 갱신
 *
 * 의존성: toss_add_benefit.css (.add-form 시리즈)
 * 호출 endpoint: api_benefits_crud.py POST /api/benefits/crud
 * ───────────────────────────────────────────────────────────── */

(function() {
  'use strict';

  // ─── popover 안 + 추가 버튼 클릭 → 폼 toggle ───────────
  document.addEventListener('click', function(e) {
    // popover 안 .pop-add 클릭
    const addBtn = e.target.closest('.pop-add');
    if (addBtn) {
      const pop = addBtn.closest('.cell-fx-pop');
      if (!pop) return;
      const form = pop.querySelector('.add-form');
      if (!form) return;
      e.preventDefault();
      e.stopPropagation();
      form.hidden = false;
      addBtn.style.display = 'none';
      resetForm(form);
      const nameInput = form.querySelector('input[name=name]');
      if (nameInput) nameInput.focus();
      return;
    }

    // type chip
    const chip = e.target.closest('.add-form .pill');
    if (chip) {
      const group = chip.parentElement;
      group.querySelectorAll('.pill').forEach(c => {
        c.classList.remove('on');
        c.setAttribute('aria-checked', 'false');
      });
      chip.classList.add('on');
      chip.setAttribute('aria-checked', 'true');
      const form = chip.closest('.add-form');
      const unitEl = form.querySelector('.unit');
      const isAmount = chip.dataset.type === 'amount';
      if (unitEl) unitEl.textContent = isAmount ? '원' : '%';
      updatePreview(form);
      return;
    }

    // scope item
    const scopeItem = e.target.closest('.add-form .scope-list .item');
    if (scopeItem) {
      const form = scopeItem.closest('.add-form');
      form.querySelectorAll('.scope-list .item').forEach(o => {
        o.classList.remove('on');
        o.setAttribute('aria-checked', 'false');
      });
      scopeItem.classList.add('on');
      scopeItem.setAttribute('aria-checked', 'true');
      updatePreview(form);
      return;
    }

    // 취소
    const cancel = e.target.closest('.add-form .cancel');
    if (cancel) {
      e.preventDefault();
      const form = cancel.closest('.add-form');
      closeForm(form);
      return;
    }

    // 저장
    const save = e.target.closest('.add-form .save');
    if (save && !save.disabled) {
      e.preventDefault();
      const form = save.closest('.add-form');
      submitForm(form, save);
      return;
    }
  });

  // ─── input 변경 시 preview 실시간 ─────────────────────
  document.addEventListener('input', function(e) {
    const form = e.target.closest('.add-form');
    if (!form) return;
    updatePreview(form);
  });

  // ─── 폼 reset ─────────────────────────────────────────
  function resetForm(form) {
    form.querySelectorAll('input[type=text]').forEach(i => i.value = '');
    // type 기본 = 정률
    form.querySelectorAll('.pill').forEach(c => {
      const isRate = c.dataset.type === 'rate';
      c.classList.toggle('on', isRate);
      c.setAttribute('aria-checked', String(isRate));
    });
    const unitEl = form.querySelector('.unit');
    if (unitEl) unitEl.textContent = '%';
    // scope 기본 = 모음전 전체
    form.querySelectorAll('.scope-list .item').forEach(o => {
      const isBundle = o.dataset.scope === 'bundle';
      o.classList.toggle('on', isBundle);
      o.setAttribute('aria-checked', String(isBundle));
    });
    updatePreview(form);
  }

  // ─── 폼 닫기 ──────────────────────────────────────────
  function closeForm(form) {
    form.hidden = true;
    const pop = form.closest('.cell-fx-pop');
    if (pop) {
      const addBtn = pop.querySelector('.pop-add');
      if (addBtn) addBtn.style.display = '';
    }
  }

  // ─── impact preview + 저장 버튼 활성/비활성 ────────────
  function updatePreview(form) {
    const name = (form.querySelector('input[name=name]')?.value || '').trim();
    const valStr = (form.querySelector('input[name=value]')?.value || '').trim();
    const val = parseFloat(valStr.replace(/[^0-9.]/g, ''));
    const typeEl = form.querySelector('.pill.on');
    const type = typeEl?.dataset.type || 'rate';
    const scopeEl = form.querySelector('.scope-list .item.on');
    const scope = scopeEl?.dataset.scope || 'bundle';

    const cntBundle = parseInt(form.dataset.optionCountBundle, 10) || 0;
    const cntColor = parseInt(form.dataset.optionCountColor, 10) || 0;
    const sourceName = form.dataset.sourceName || '소싱처';

    // 영향 요약 텍스트
    const summaryMap = {
      option: `이 옵션만 (1 옵션)`,
      color: `동일 컬러 (${cntColor} 옵션)`,
      bundle: `모음전 전체 (${cntBundle} 옵션)`,
      source: `${sourceName} 소싱처 전체 (다수 모음전)`,
    };
    const noteMap = {
      option: ' · 다른 옵션 영향 없음',
      color: ' · 다른 컬러 영향 없음',
      bundle: ' · 다른 모음전 영향 없음',
      source: ' · 다수 모음전 영향',
    };
    const summaryEl = form.querySelector('.impact-preview .scope-summary');
    const noteSpan = form.querySelector('.impact-preview .text');
    if (summaryEl) summaryEl.textContent = summaryMap[scope] || summaryMap.bundle;
    if (noteSpan) noteSpan.innerHTML = `선택: <b class="scope-summary">${summaryMap[scope] || summaryMap.bundle}</b>${noteMap[scope] || ''}`;

    // 계산식 미리보기 (sale_price 기반 추정)
    const popSale = form.closest('.cell-fx-pop')?.querySelector('.cf-sale .num')?.textContent;
    const salePrice = parseInt((popSale || '').replace(/[^0-9]/g, ''), 10) || 0;
    let calcText = '—';
    if (val > 0 && salePrice > 0) {
      let deduct = 0;
      if (type === 'amount') {
        deduct = val;
      } else {
        // rate — sale_price 기준 추정 (실제 산식은 백엔드 compute_breakdown 가 계산)
        deduct = Math.round(salePrice * (val / 100));
      }
      calcText = `≈ -${deduct.toLocaleString()}원`;
    }
    const calcEl = form.querySelector('.impact-preview .calc');
    if (calcEl) calcEl.textContent = calcText;

    // 저장 버튼 활성화 조건: name + val > 0
    const saveBtn = form.querySelector('.save');
    if (saveBtn) {
      saveBtn.disabled = !(name.length > 0 && val > 0);
    }
  }

  // ─── 저장 (POST /api/benefits/crud) ───────────────────
  async function submitForm(form, saveBtn) {
    const name = form.querySelector('input[name=name]').value.trim();
    const val = parseFloat(form.querySelector('input[name=value]').value.replace(/[^0-9.]/g, ''));
    const type = form.querySelector('.pill.on')?.dataset.type || 'rate';
    const scope = form.querySelector('.scope-list .item.on')?.dataset.scope || 'bundle';

    const payload = {
      name: name,
      benefit_type: type === 'amount' ? 'amount' : 'rate',
      value: type === 'amount' ? val : (val / 100),  // rate 는 0.05 같은 소수
      scope: scope,
      source_id: parseInt(form.dataset.sourceId, 10),
      canonical_sku: form.dataset.sku || null,
      bundle_id: form.dataset.bundleId ? parseInt(form.dataset.bundleId, 10) : null,
    };

    saveBtn.disabled = true;
    const origText = saveBtn.textContent;
    saveBtn.textContent = '저장 중...';

    try {
      const resp = await fetch('/api/benefits/crud', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        throw new Error(data.error || `HTTP ${resp.status}`);
      }
      // 성공 — 폼 닫고 매트릭스 갱신
      const appliedCount = data.applied_count || 0;
      const msg = `✓ "${name}" 추가 — ${appliedCount}개 옵션에 적용`;
      // 운영 toss.js 의 toast 함수가 있으면 사용, 없으면 alert
      if (window.tossToast) {
        window.tossToast(msg, 'success');
      } else {
        console.log('[add-benefit] ' + msg);
      }
      closeForm(form);
      // 매트릭스 갱신 — 운영 toss.js 의 reloadMatrix 가 있으면 호출, 없으면 페이지 reload
      if (typeof window.reloadMatrix === 'function') {
        window.reloadMatrix();
      } else {
        setTimeout(() => location.reload(), 500);
      }
    } catch (err) {
      console.error('[add-benefit] 저장 실패:', err);
      alert('혜택 추가 실패: ' + err.message);
      saveBtn.disabled = false;
      saveBtn.textContent = origText;
    }
  }
})();

/* ─────────────────────────────────────────────────────────────
 * 혜택 추가 폼 인터랙션 (v8 B2 — 영향도 게이지 드롭다운)
 *
 * 동작:
 *   1. .pop-add 클릭 → .add-form toggle (hidden 제거 + 폼 reset)
 *   2. .pill 클릭 → 단위 자동 전환 (% ↔ 원) + active 토글
 *   3. .b2-drop .b2-selected 클릭 → 드롭 메뉴 toggle open
 *   4. .b2-drop .b2-opt 클릭 → 선택 swap (lbl·cnt·gauge 동기) + 닫기
 *   5. document 외부 클릭 → 열린 드롭 모두 닫기
 *   6. 입력 변경 시 impact preview 실시간 갱신
 *   7. .save 클릭 → POST /api/benefits/crud → 성공 시 매트릭스 갱신
 *
 * 의존성: toss_add_benefit.css (.b2-drop 시리즈)
 * 호출 endpoint: api_benefits_crud.py POST /api/benefits/crud
 * ───────────────────────────────────────────────────────────── */

(function() {
  'use strict';

  // scope bar 채움 단계 (영향도)
  const SCOPE_FILLS = { option: 1, color: 2, bundle: 3, source: 4 };

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

    // pill (정액/정률)
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

    // b2-drop selected → 드롭 토글
    const b2sel = e.target.closest('.add-form .b2-drop .b2-selected');
    if (b2sel) {
      e.preventDefault();
      const drop = b2sel.closest('.b2-drop');
      // 다른 popover 의 열린 드롭 닫기 (한 번에 하나만)
      document.querySelectorAll('.b2-drop.open').forEach(d => { if (d !== drop) d.classList.remove('open'); });
      drop.classList.toggle('open');
      return;
    }

    // b2-drop 옵션 클릭 → 선택 swap
    const b2opt = e.target.closest('.add-form .b2-drop .b2-opt');
    if (b2opt) {
      e.preventDefault();
      const drop = b2opt.closest('.b2-drop');
      const scope = b2opt.dataset.scope;
      drop.dataset.active = scope;
      drop.querySelectorAll('.b2-opt').forEach(o => o.classList.toggle('on', o === b2opt));
      // selected 헤더 동기: 라벨·카운트
      const lblTxt = b2opt.querySelector('.b2-opt-lbl').textContent;
      const cntTxt = b2opt.querySelector('.b2-opt-cnt').textContent;
      drop.querySelector('.b2-selected .b2-lbl').textContent = lblTxt;
      // cnt 는 게이지 옆 짧게 (+38 / + 다수 etc)
      const shortCnt = cntTxt.replace(' 옵션', '');
      drop.querySelector('.b2-selected .b2-cnt').textContent = shortCnt;
      // 게이지 막대 재칠
      const fills = SCOPE_FILLS[scope] || 3;
      drop.querySelectorAll('.b2-bars .b2-bar').forEach((bar, i) => {
        bar.className = 'b2-bar' + (i < fills ? ' on b2-' + scope : '');
      });
      drop.classList.remove('open');
      // preview 갱신
      const form = drop.closest('.add-form');
      if (form) updatePreview(form);
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

    // 외부 클릭 — 열린 드롭 닫기
    if (!e.target.closest('.b2-drop')) {
      document.querySelectorAll('.b2-drop.open').forEach(d => d.classList.remove('open'));
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
    // scope 기본 = 모음전 전체 (bundle)
    const drop = form.querySelector('.b2-drop');
    if (drop) {
      drop.dataset.active = 'bundle';
      drop.classList.remove('open');
      drop.querySelectorAll('.b2-opt').forEach(o => o.classList.toggle('on', o.dataset.scope === 'bundle'));
      const bundleOpt = drop.querySelector('.b2-opt[data-scope=bundle]');
      if (bundleOpt) {
        drop.querySelector('.b2-selected .b2-lbl').textContent = bundleOpt.querySelector('.b2-opt-lbl').textContent;
        drop.querySelector('.b2-selected .b2-cnt').textContent = bundleOpt.querySelector('.b2-opt-cnt').textContent.replace(' 옵션', '');
      }
      // 게이지 3 칸 채움 (bundle)
      drop.querySelectorAll('.b2-bars .b2-bar').forEach((bar, i) => {
        bar.className = 'b2-bar' + (i < 3 ? ' on b2-bundle' : '');
      });
    }
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
    const drop = form.querySelector('.b2-drop');
    const scope = drop?.dataset.active || 'bundle';

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
    const scope = form.querySelector('.b2-drop')?.dataset.active || 'bundle';

    const payload = {
      name: name,
      benefit_type: type === 'amount' ? 'amount' : 'rate',
      value: type === 'amount' ? val : (val / 100),
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
      const appliedCount = data.applied_count || 0;
      const msg = `✓ "${name}" 추가 — ${appliedCount}개 옵션에 적용`;
      if (window.tossToast) {
        window.tossToast(msg, 'success');
      } else {
        console.log('[add-benefit] ' + msg);
      }
      closeForm(form);
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

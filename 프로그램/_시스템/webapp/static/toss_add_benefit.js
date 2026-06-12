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

  // _matrix_v3.html 의 .sp-row 위임이 추가 폼 preview 를 갱신할 수 있도록 노출
  window._tossUpdateAddPreview = function(form) { if (form) updatePreview(form); };

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
      const bd = form.parentElement && form.parentElement.querySelector('.add-backdrop');
      if (bd) bd.hidden = false;
      addBtn.style.display = 'none';
      resetForm(form);
      const nameInput = form.querySelector('input[name=name]');
      if (nameInput) nameInput.focus();
      return;
    }

    // 모달 백드롭 클릭 → 닫기
    const bdrop = e.target.closest('.add-backdrop');
    if (bdrop) {
      const form2 = bdrop.parentElement && bdrop.parentElement.querySelector('.add-form');
      if (form2) closeForm(form2);
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

  // ─── 분류(카테고리) 선택 → 기본 단위 자동 (정액=원, 그 외=%). 사용자가 단위 토글로 재변경 가능.
  document.addEventListener('change', function(e) {
    const sel = e.target.closest('.add-form .cat-select');
    if (!sel) return;
    const form = sel.closest('.add-form');
    const defType = (sel.value === '정액') ? 'amount' : 'rate';
    setUnit(form, defType);
    updatePreview(form);
  });

  // 단위 토글 상태 설정 (pills + unit span 동기화)
  function setUnit(form, type) {
    const isAmount = type === 'amount';
    form.querySelectorAll('.unit-pills .pill').forEach(p => {
      const on = (p.dataset.type === type);
      p.classList.toggle('on', on);
      p.setAttribute('aria-checked', String(on));
    });
    const unitEl = form.querySelector('.unit');
    if (unitEl) unitEl.textContent = isAmount ? '원' : '%';
  }

  // ─── 폼 reset ─────────────────────────────────────────
  function resetForm(form) {
    form.querySelectorAll('input[type=text]').forEach(i => i.value = '');
    // 분류 기본 = 정률
    const catSel = form.querySelector('.cat-select');
    if (catSel) catSel.value = '정률';
    // 단위 기본 = % (정률)
    setUnit(form, 'rate');
    // scope 기본 = 옵션 1개 (option) — 위상 2단계 그룹 picker
    const host = form.querySelector('.sp-host');
    if (host) {
      host.dataset.skus = '[]';
      host.querySelectorAll('.sp-row').forEach(r => r.classList.toggle('on', r.dataset.scope === 'option'));
      const selAct = host.querySelector('.sp-row[data-scope=select] .sp-act');
      if (selAct) selAct.textContent = '선택 →';
    }
    updatePreview(form);
  }

  // ─── 폼 닫기 ──────────────────────────────────────────
  function closeForm(form) {
    form.hidden = true;
    const bd = form.parentElement && form.parentElement.querySelector('.add-backdrop');
    if (bd) bd.hidden = true;
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
    const host = form.querySelector('.sp-host');
    const st = window.readScopePicker ? window.readScopePicker(host) : {scope:'option', skus:[]};
    const scope = st.scope;

    const cntBundle = parseInt(form.dataset.optionCountBundle, 10) || 0;
    const sourceName = form.dataset.sourceName || '소싱처';

    // 영향 요약 텍스트 (위상 2단계 4항목 — 옛 bundle 제거)
    const summaryMap = {
      option: `옵션 1개 (1 옵션)`,
      select: `고른 옵션 (${st.skus.length} 옵션)`,
      bundle_all_src: `옵션 전체 · 모든 소싱처 (${cntBundle} 옵션 × 소싱처)`,
      source: `해당 소싱처 기본값 (${sourceName})`,
    };
    const noteMap = {
      option: ' · 해당 모음전 · 해당 소싱처',
      select: ' · 해당 모음전 · 해당 소싱처',
      bundle_all_src: ' · 해당 모음전 · 모든 소싱처',
      source: ' · 전체 모음전 적용',
    };
    const summaryEl = form.querySelector('.impact-preview .scope-summary');
    const noteSpan = form.querySelector('.impact-preview .text');
    if (summaryEl) summaryEl.textContent = summaryMap[scope] || summaryMap.option;
    if (noteSpan) noteSpan.innerHTML = `선택: <b class="scope-summary">${summaryMap[scope] || summaryMap.option}</b>${noteMap[scope] || ''}`;

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
    const type = form.querySelector('.unit-pills .pill.on')?.dataset.type || 'rate';
    const category = form.querySelector('.cat-select')?.value || null;
    const host = form.querySelector('.sp-host');
    const st = window.readScopePicker ? window.readScopePicker(host) : {scope:'option', skus:[]};
    const scope = st.scope;
    if (scope === 'select' && !st.skus.length) {
      alert('옵션을 먼저 선택하세요 ("옵션 매트릭스 직접 선택" 클릭)');
      return;
    }
    const sources = (window.DATA && window.DATA.sources) || [];

    const payload = {
      name: name,
      benefit_type: type === 'amount' ? 'amount' : 'rate',
      value: type === 'amount' ? val : (val / 100),
      category: category,
      scope: scope,
      source_id: parseInt(form.dataset.sourceId, 10),
      canonical_sku: form.dataset.sku || null,
      // bundle_id 는 정수 PK(있으면), bundle_code 는 모음전 코드(model_code/group_code).
      // 실제 옵션↔모음전 매핑은 코드 기반이므로 코드도 함께 전송 (bundle scope 해석용).
      bundle_id: (form.dataset.bundleId && /^\d+$/.test(form.dataset.bundleId)) ? parseInt(form.dataset.bundleId, 10) : null,
      bundle_code: form.dataset.bundleCode || form.dataset.bundleId || null,
      skus: scope === 'select' ? st.skus : undefined,
      source_ids: scope === 'bundle_all_src' ? sources.map(x => x.source_id != null ? x.source_id : x.id) : undefined,
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

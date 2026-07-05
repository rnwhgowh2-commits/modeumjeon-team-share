// [E] Toss UI 인터랙션 — 페이지 공통 helpers + 전역 click dispatch.

// ============================================================
// [v2] 임시저장 Floating Bubble — 시안 C
// ============================================================
window.LEMOUTON_DRAFT_KEYS = {
  new: 'lemouton:draft:new',
  migrate: 'lemouton:draft:migrate',
};
const DRAFT_PAGE_LABEL = {
  new: '🆕 신규 모음전 등록',
  migrate: '🔄 기존 마켓 상품 연동',
};
const DRAFT_PAGE_URL = {
  new: '/bundles/new',
  migrate: '/bundles/migrate',
};

function getAllDrafts() {
  const out = [];
  for (const [page, key] of Object.entries(window.LEMOUTON_DRAFT_KEYS)) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const data = JSON.parse(raw);
      if (!data || Object.values(data).every(v => !v)) continue;
      out.push({ page, key, data, ts: data._ts || 0 });
    } catch (e) {}
  }
  return out.sort((a, b) => b.ts - a.ts);
}

function _draftSummary(page, data) {
  if (page === 'migrate') {
    return `${data['m-origin-no'] || '?'} → ${data['m-code'] || '?'}`;
  }
  if (page === 'new') {
    return `${data['model_code'] || '?'} (${data['brand'] || '브랜드?'})`;
  }
  return JSON.stringify(data);
}

function _formatTs(ts) {
  if (!ts) return '방금 전';
  const diff = (Date.now() - ts) / 1000;
  if (diff < 60) return '방금 전';
  if (diff < 3600) return `${Math.round(diff/60)}분 전`;
  if (diff < 86400) return `${Math.round(diff/3600)}시간 전`;
  return `${Math.round(diff/86400)}일 전`;
}

function refreshDraftBubble() {
  const fab = document.getElementById('draft-fab');
  const count = document.getElementById('draft-fab-count');
  const body = document.getElementById('draft-popup-body');
  if (!fab) return;
  const drafts = getAllDrafts();
  fab.style.display = '';  // 항상 보임 (빈 상태도)
  count.textContent = drafts.length;
  fab.classList.toggle('empty', drafts.length === 0);
  if (!body) return;
  if (drafts.length === 0) {
    body.innerHTML = '<div class="draft-empty">임시저장된 작업 없음</div>';
    return;
  }
  body.innerHTML = drafts.map(d => `
    <div class="draft-row" data-key="${d.key}">
      <div class="draft-meta">${_formatTs(d.ts)} · ${DRAFT_PAGE_LABEL[d.page] || d.page}</div>
      <div class="draft-key">${_draftSummary(d.page, d.data)}</div>
      <div class="draft-actions">
        <a href="${DRAFT_PAGE_URL[d.page]}">이어서 작업 →</a>
        <button data-discard="${d.key}">🗑 버리기</button>
      </div>
    </div>
  `).join('');
  body.querySelectorAll('[data-discard]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!confirm('이 임시저장을 버릴까요?')) return;
      localStorage.removeItem(btn.getAttribute('data-discard'));
      refreshDraftBubble();
    });
  });
}

function mountDraftBubble() {
  const fab = document.getElementById('draft-fab');
  const popup = document.getElementById('draft-popup');
  if (!fab || !popup) return;
  fab.addEventListener('click', () => {
    popup.classList.toggle('open');
    refreshDraftBubble();
  });
  refreshDraftBubble();
  // 다른 탭에서 localStorage 변경 시 자동 refresh
  window.addEventListener('storage', refreshDraftBubble);
}

// 페이지별 자동 임시저장 helper (input 변경 시 debounce 저장)
function setupDraftAutoSave(page, inputIds) {
  const key = window.LEMOUTON_DRAFT_KEYS[page];
  if (!key) return;
  let timer;
  function save() {
    const data = { _ts: Date.now() };
    inputIds.forEach(id => { data[id] = (document.getElementById(id)?.value || ''); });
    if (Object.entries(data).every(([k, v]) => k === '_ts' || !v)) {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, JSON.stringify(data));
    }
    refreshDraftBubble();
  }
  inputIds.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(save, 500); });
    el.addEventListener('change', () => { clearTimeout(timer); timer = setTimeout(save, 500); });
  });
  // 진입 시 복구 confirm
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return;
    const draft = JSON.parse(raw);
    if (Object.entries(draft).every(([k, v]) => k === '_ts' || !v)) return;
    if (confirm('이전에 입력하던 내용이 있습니다. 이어서 작업할까요?\n(취소하면 새로 시작)')) {
      inputIds.forEach(id => { if (draft[id]) document.getElementById(id).value = draft[id]; });
    } else {
      localStorage.removeItem(key);
      refreshDraftBubble();
    }
  } catch (e) {}
}

function clearDraft(page) {
  const key = window.LEMOUTON_DRAFT_KEYS[page];
  if (key) localStorage.removeItem(key);
  refreshDraftBubble();
}

// 페이지 진입 시 mount
document.addEventListener('DOMContentLoaded', mountDraftBubble);

// ============================================================

// ============================================================
// [v2] 변경사항 추적 + 페이지 이탈 confirm + 자동저장
// ============================================================
window.__lemoutonDirty = false;
function markDirty() { window.__lemoutonDirty = true; }
function clearDirty() { window.__lemoutonDirty = false; }

// ---- 모음전 편집 페이지 자동저장 ----
// 헤더 우상단 인디케이터 상태 갱신 (idle/saving/saved/error)
function setAutoSaveIndicator(state, msg) {
  const ind = document.getElementById('autosave-indicator');
  if (!ind) return;
  const map = {
    idle:   { html: '', cls: 'idle' },
    saving: { html: '✏ 저장 중...', cls: 'saving' },
    saved:  { html: '💾 저장됨 ✓', cls: 'saved' },
    error:  { html: '⚠ 저장 실패 (다시 시도)', cls: 'error' },
  };
  const v = map[state] || map.idle;
  ind.innerHTML = v.html;
  ind.dataset.state = v.cls;
  ind.title = msg || '';
}

// 실제 저장 — 기존 save-bundle 로직과 동일 (서버 API 호출)
async function autoSaveBundle() {
  const code = currentBundleCode();
  if (!code) return;
  const inputs = document.querySelectorAll('.bundle-content input[name], .bundle-content select[name]');
  if (!inputs.length) return;
  const payload = {};
  inputs.forEach(i => {
    if (i.type === 'checkbox') payload[i.name] = i.checked;
    else payload[i.name] = i.value;
  });
  setAutoSaveIndicator('saving');
  try {
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}`, payload);
    if (res.ok) {
      clearDirty();
      setAutoSaveIndicator('saved');
      // 2.5초 뒤 idle 로 (다음 변경 전에 사라지지 않게)
      clearTimeout(window.__autosaveFadeTimer);
      window.__autosaveFadeTimer = setTimeout(() => {
        if (!window.__lemoutonDirty) setAutoSaveIndicator('idle');
      }, 2500);
    } else {
      setAutoSaveIndicator('error', res.error || '');
    }
  } catch (e) {
    setAutoSaveIndicator('error', String(e));
  }
}

// debounce 700ms
let _autoSaveTimer = null;
function scheduleAutoSave() {
  clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(autoSaveBundle, 700);
}

// 모음전 편집 페이지 + 옵션 디테일에서 사용 (input/select/checkbox 변경 감지)
document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname;
  const isBundlePage = /^\/bundles\/[^/]+/.test(path) || path === '/bundles/new';
  if (!isBundlePage) return;
  const isBundleEditPage = !!document.querySelector('.bundle-content');
  // 페이지 진입 직후 잠시 무시 (초기 렌더링 시 false 변경 무시)
  setTimeout(() => {
    document.querySelectorAll('input, select, textarea').forEach(el => {
      el.addEventListener('input', () => {
        markDirty();
        // 모음전 편집 페이지 + name 속성 가진 .bundle-content 안의 필드만 자동저장
        if (isBundleEditPage && el.closest('.bundle-content') && el.name &&
            !el.matches('#bundle-code-input')) {
          scheduleAutoSave();
        }
      });
      el.addEventListener('change', () => {
        markDirty();
        if (isBundleEditPage && el.closest('.bundle-content') && el.name &&
            !el.matches('#bundle-code-input')) {
          scheduleAutoSave();
        }
      });
    });
    // 인디케이터 클릭 시 즉시 재시도
    const ind = document.getElementById('autosave-indicator');
    if (ind) {
      ind.addEventListener('click', () => {
        if (ind.dataset.state === 'error') autoSaveBundle();
      });
    }
  }, 500);
});

// 사이드바 / 다른 링크 클릭 시 confirm
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href]');
  if (!a) return;
  const href = a.getAttribute('href') || '';
  // 빈 링크·앵커·자바스크립트 무시
  if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
  // 같은 페이지 내 링크 무시
  if (href === window.location.pathname || href === window.location.href) return;
  if (window.__lemoutonDirty) {
    if (!confirm('💾 저장 안 한 변경사항이 있습니다.\n정말 페이지를 떠나시겠어요?\n\n(확인 = 변경사항 잃고 이동, 취소 = 머무름)')) {
      e.preventDefault();
      e.stopPropagation();
    } else {
      clearDirty();  // 사용자가 동의했으니 dirty 해제
    }
  }
}, true);

// 브라우저 닫기·새로고침 confirm
window.addEventListener('beforeunload', (e) => {
  if (window.__lemoutonDirty) {
    e.preventDefault();
    e.returnValue = '저장 안 한 변경사항이 있습니다.';
  }
});

// [v2] 옵션 매트릭스 행 클릭 → 옵션 디테일 페이지로 이동
document.addEventListener('click', (e) => {
  // 모달 안 클릭은 행-네비 대상 아님 (매칭 모달 등에서 tr[data-sku] 재사용)
  if (e.target.closest('[data-modal-root]')) return;
  const tr = e.target.closest('tr[data-sku]');
  if (!tr) return;
  if (e.target.closest('input, label, button, a, select, textarea, option')) return;
  // M4 카드 (가격 셀 안 소싱·사입 stack) 클릭은 우선순위 전환용 — row 네비 X
  if (e.target.closest('.m4-card, .c9-bar, .pmb-row')) return;
  // v23 — fx popover (계산식 + 혜택 편집) 안 클릭은 row 네비 X
  if (e.target.closest('.cell-fx-pop, .opt-detail-overlay, .sm-side-panel')) return;
  // v23 — 통합 매트릭스 (Phase 6) row 는 명시 클릭 시만 이동 — 자동 이동 비활성
  if (tr.closest('.integrated-mtx, .opt-table.integrated-mtx, table.opt-table')) return;
  const sku = tr.getAttribute('data-sku');
  const code = (typeof currentBundleCode === 'function')
    ? currentBundleCode() : window.location.pathname.split('/').filter(Boolean).pop();
  if (sku && code) {
    window.location = `/bundles/${encodeURIComponent(code)}/option/${encodeURIComponent(sku)}`;
  }
});

// ===== Modal helpers =====
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add('visible');
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove('visible');
}
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('modal-bg')) {
    e.target.classList.remove('visible');
  }
});

// ===== Chip toggle =====
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.chip-add').forEach(c => {
    c.addEventListener('click', () => flash('칩 추가 모달은 후속 작업', 'warn'));
  });
});

// ===== Searchable dropdown =====
function toggleSdrop(id) {
  document.querySelectorAll('.sdrop-menu').forEach(m => {
    if (m.parentElement && m.parentElement.id !== id) m.classList.remove('visible');
  });
  const menu = document.querySelector('#' + id + ' .sdrop-menu');
  if (menu) menu.classList.toggle('visible');
}
document.addEventListener('click', e => {
  if (!e.target.closest || !e.target.closest('.sdrop-wrap')) {
    document.querySelectorAll('.sdrop-menu').forEach(m => m.classList.remove('visible'));
  }
});
function filterSdrop(inputEl, itemSelector) {
  const q = (inputEl.value || '').toLowerCase().trim();
  const menu = inputEl.closest('.sdrop-menu');
  if (!menu) return;
  menu.querySelectorAll(itemSelector || '.sdrop-item').forEach(it => {
    it.style.display = (it.textContent || '').toLowerCase().includes(q) ? '' : 'none';
  });
}

// ===== AJAX helpers =====
async function apiPost(path, data) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {}),
  });
  return r.json();
}
async function apiGet(path) {
  const r = await fetch(path);
  return r.json();
}

function flash(msg, kind) {
  const el = document.createElement('div');
  el.textContent = msg;
  const bg = kind === 'err' ? 'var(--danger)'
           : kind === 'warn' ? '#FBA94A'
           : 'var(--primary)';
  el.style.cssText = `position:fixed;bottom:20px;right:20px;padding:12px 18px;background:${bg};color:#fff;border-radius:8px;font-weight:700;z-index:9999;box-shadow:var(--shadow-md)`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

// 모음전 코드 추출 — 이미 인코딩된 path를 1회만 인코딩하기 위해 디코드 후 다시 인코딩.
function currentBundleCode() {
  const last = window.location.pathname.split('/').pop();
  try { return decodeURIComponent(last); } catch (e) { return last; }
}

// ===== 우측 nav active 동기화 =====
document.addEventListener('DOMContentLoaded', () => {
  const navItems = document.querySelectorAll('.bundle-nav-item');
  if (!navItems.length) return;
  const sections = Array.from(document.querySelectorAll('.bundle-section'));
  function sync() {
    const top = window.scrollY + 120;
    let active = sections[0];
    for (const s of sections) {
      if (s.offsetTop <= top) active = s;
    }
    if (!active) return;
    navItems.forEach(n => {
      n.classList.toggle('active',
        n.getAttribute('href') === '#' + active.id);
    });
  }
  window.addEventListener('scroll', sync, { passive: true });
  sync();
});

// ===== sdrop 항목 클릭 → 템플릿 변경 (모음전 편집 페이지) =====
document.addEventListener('click', async (e) => {
  const item = e.target.closest('.sdrop-item[data-id]');
  if (!item) return;
  const wrap = item.closest('.sdrop-wrap');
  if (!wrap || !wrap.id) return;
  const map = { 'sd-price': 'price_template_id',
                'sd-color': 'color_template_id',
                'sd-size': 'size_template_id' };
  const field = map[wrap.id];
  if (!field) return;
  const code = currentBundleCode();
  const tpl_id = parseInt(item.getAttribute('data-id'), 10);
  const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}`, { [field]: tpl_id });
  if (res.ok) {
    wrap.querySelectorAll('.sdrop-item').forEach(x => x.classList.remove('applied'));
    item.classList.add('applied');
    const trigger = wrap.querySelector('.sdrop-trigger strong');
    if (trigger) trigger.textContent = item.querySelector('.sdrop-item-name')?.textContent.replace(/✓.*$/, '').trim() || trigger.textContent;
    flash('템플릿이 변경됐어요.');
    toggleSdrop(wrap.id);
  } else {
    flash('템플릿 변경 실패: ' + res.error, 'err');
  }
});

// ===== 옵션 매트릭스 — SS/쿠팡 토글 즉시 저장 =====
document.addEventListener('change', async (e) => {
  const cb = e.target;
  if (cb.tagName !== 'INPUT' || cb.type !== 'checkbox') return;
  const sku = cb.getAttribute('data-sku');
  const market = cb.getAttribute('data-market');
  if (!sku || !market) return;
  const code = currentBundleCode();
  const field = market === 'ss' ? 'market_visible_ss' : 'market_visible_coupang';
  const res = await apiPost(
    `/api/bundles/${encodeURIComponent(code)}/option/${encodeURIComponent(sku)}`,
    { [field]: cb.checked }
  );
  flash(res.ok ? `${sku} ${market} 노출 ${cb.checked ? 'ON' : 'OFF'}` : ('저장 실패: ' + res.error),
        res.ok ? 'ok' : 'err');
});

// ===== 알림 채널 매트릭스 — 체크박스 즉시 저장 =====
document.addEventListener('change', async (e) => {
  const cb = e.target;
  if (cb.tagName !== 'INPUT' || cb.type !== 'checkbox') return;
  const key = cb.getAttribute('data-key');
  const channel = cb.getAttribute('data-channel');
  if (!key || !channel) return;
  const res = await apiPost('/api/alerts/route',
    { event_key: key, channel: channel, enabled: cb.checked });
  flash(res.ok ? '저장됐어요.' : ('저장 실패: ' + res.error), res.ok ? 'ok' : 'err');
});

// ===== 메인 click dispatcher (data-action 기반) =====
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.getAttribute('data-action');

  // ----- 모음전 편집 -----
  // [2026-05-25] save-bundle 액션 제거 — autoSaveBundle (debounce 700ms) 로 대체됨

  if (action === 'rename-bundle') {
    e.preventDefault();
    const oldCode = currentBundleCode();
    const input = document.getElementById('bundle-code-input');
    const newCode = (input.value || '').trim();
    const original = input.getAttribute('data-original');
    if (!newCode || newCode === original) {
      flash('새 코드를 입력하세요 (기존과 달라야 함).', 'warn');
      return;
    }
    const reason = prompt(
      `모음전 코드 변경:\n\n  '${oldCode}' → '${newCode}'\n\n` +
      `옵션·이력·매핑이 모두 cascade 갱신됩니다 (트랜잭션, 롤백 가능).\n` +
      `변경 사유를 입력하세요 (audit 로그 기록용):`,
      ''
    );
    if (reason === null) return;  // 취소
    const res = await apiPost(
      `/api/bundles/${encodeURIComponent(oldCode)}/rename`,
      { new_code: newCode, reason: reason || null }
    );
    if (res.ok) {
      flash(`코드 변경 완료: ${oldCode} → ${newCode} (옵션 ${res.options_updated || 0}, 콤보 ${res.combos_updated || 0}, 매핑 ${res.links_updated || 0})`, 'ok');
      setTimeout(() => { window.location = res.redirect; }, 1200);
    } else {
      flash('코드 변경 실패: ' + (res.error || ''), 'err');
      input.value = original;  // 입력 되돌림
    }
    return;
  }

  if (action === 'duplicate-bundle') {
    e.preventDefault();
    const code = currentBundleCode();
    const newCode = prompt(`'${code}' 복제 — 새 모음전 코드를 입력하세요:`, code + '_복제');
    if (!newCode) return;
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/duplicate`,
                              { new_code: newCode });
    if (res.ok) {
      flash('복제 완료');
      setTimeout(() => { window.location = `/bundles/${encodeURIComponent(newCode)}`; }, 800);
    } else flash('복제 실패: ' + res.error, 'err');
    return;
  }

  if (action === 'delete-bundle') {
    e.preventDefault();
    const code = currentBundleCode();
    // [v2] Dry-run 미리보기 — 삭제 영향 표시
    const preview = await apiPost(
      `/api/bundles/${encodeURIComponent(code)}/preview-delete`, {}
    );
    if (!preview.ok) {
      flash('미리보기 실패: ' + (preview.error || ''), 'err');
      return;
    }
    let msg = `'${code}' 모음전 삭제 영향:\n\n`;
    msg += `• 옵션 ${preview.options_to_remove || 0}개 제거\n`;
    msg += `• 계정 등록 매핑 ${preview.bundle_registrations || 0}개\n`;
    msg += `• 마켓 등록된 항목 ${preview.registered_in_marketplaces || 0}개\n`;
    msg += `• 옵션 등록 매핑 ${preview.option_registrations || 0}개\n`;
    msg += `• 소싱 링크 ${preview.source_links || 0}개\n\n`;
    if (preview.warning) msg += `⚠ ${preview.warning}\n\n`;
    msg += '진짜 삭제할까요? (이 작업은 되돌리기 어려움)';
    if (!confirm(msg)) return;
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/delete`, {});
    if (res.ok) {
      flash('삭제 완료');
      setTimeout(() => { window.location = '/bundles'; }, 600);
    } else flash('삭제 실패: ' + res.error, 'err');
    return;
  }

  if (action === 'sync-ss-options') {
    e.preventDefault();
    const code = currentBundleCode();
    btn.disabled = true; const orig = btn.textContent; btn.textContent = '⏳ 동기화 중...';
    try {
      const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/sync-ss-options`, {});
      if (!res.ok) {
        flash('동기화 실패: ' + (res.error || ''), 'err');
        return;
      }
      openSsMatchingModal(code, res, 'smartstore');
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
    return;
  }

  if (action === 'sync-cp-options') {
    e.preventDefault();
    const code = currentBundleCode();
    btn.disabled = true; const orig = btn.textContent; btn.textContent = '⏳ 동기화 중...';
    try {
      const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/sync-cp-options`, {});
      if (!res.ok) {
        flash('쿠팡 동기화 실패: ' + (res.error || ''), 'err');
        return;
      }
      openSsMatchingModal(code, res, 'coupang');
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
    return;
  }

  if (action === 'open-ss-edit') {
    e.preventDefault();
    const code = currentBundleCode();
    btn.disabled = true; const orig = btn.textContent; btn.textContent = '⏳ 창 여는 중...';
    try {
      const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/open-ss-edit`, {});
      if (!res.ok) {
        flash(res.error || '창 열기 실패', 'err');
        return;
      }
      flash(`판매자 센터 창이 열렸어요 (${res.account || ''})`);
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
    return;
  }

  if (action === 'open-coupang-edit') {
    e.preventDefault();
    const code = currentBundleCode();
    btn.disabled = true; const orig = btn.textContent; btn.textContent = '⏳ 창 여는 중...';
    try {
      const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/open-coupang-edit`, {});
      if (!res.ok) {
        flash(res.error || '창 열기 실패', 'err');
        return;
      }
      flash(`쿠팡 윙 창이 열렸어요 (${res.account || ''})`);
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
    return;
  }

  if (action === 'register-ss' || action === 'register-coupang') {
    e.preventDefault();
    const code = currentBundleCode();
    const market = action === 'register-ss' ? 'smartstore' : 'coupang';
    const catKey = market === 'smartstore' ? 'leaf_category_id' : 'display_category_code';
    const catLabel = market === 'smartstore' ? '리프 카테고리 ID' : '쿠팡 디스플레이 카테고리 코드';
    const cat = prompt(`${market} 등록 — ${catLabel} 입력:`, '');
    if (!cat) return;
    const img = prompt('이미지 URL (Naver CDN — shop-phinf.pstatic.net 권장):',
                       'https://shop-phinf.pstatic.net/...');
    if (!img) return;
    btn.disabled = true;
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/register/${market}`,
      { [catKey]: cat, image_url: img, detail_html: '<p>상세 페이지</p>' });
    btn.disabled = false;
    if (res.ok) {
      flash(`${market} 등록 완료 (${res.origin_product_no || res.seller_product_id})`);
      setTimeout(() => window.location.reload(), 1200);
    } else {
      flash('등록 실패: ' + (res.error || 'unknown'), 'err');
    }
    return;
  }

  if (action === 'upload-active') {
    e.preventDefault();
    const code = currentBundleCode();
    btn.disabled = true;
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/upload`, {});
    btn.disabled = false;
    flash(res.ok ? '업로드 완료' : ('업로드 실패: ' + res.error), res.ok ? 'ok' : 'err');
    return;
  }

  // ----- 큐 -----
  if (action === 'resolve-queue') {
    e.preventDefault();
    const id = btn.getAttribute('data-id');
    const res = await apiPost(`/api/queue/${id}/resolve`, { status: 'resolved' });
    if (res.ok) {
      btn.closest('tr')?.remove();
      flash('처리 완료');
    } else flash('실패: ' + res.error, 'err');
    return;
  }

  // ----- DLQ -----
  if (action === 'retry-one') {
    e.preventDefault();
    const sku = btn.getAttribute('data-sku');
    const market = btn.getAttribute('data-market');
    btn.disabled = true;
    const res = await apiPost(`/api/dlq/${encodeURIComponent(sku)}/${market}/retry`, {});
    btn.disabled = false;
    flash(res.ok ? '재시도 완료' : ('실패: ' + res.error), res.ok ? 'ok' : 'err');
    return;
  }

  if (action === 'retry-all') {
    e.preventDefault();
    if (!confirm('실패함의 모든 항목을 재시도할까요?')) return;
    btn.disabled = true;
    const res = await apiPost('/api/dlq/retry-all', {});
    btn.disabled = false;
    flash(res.ok ? `재시도 완료 (${res.count || ''}건)` : ('실패: ' + res.error),
          res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => window.location.reload(), 800);
    return;
  }

  // ----- Boxhero -----
  if (action === 'boxhero-sync') {
    e.preventDefault();
    btn.disabled = true;
    const res = await apiPost('/api/boxhero/sync', {});
    btn.disabled = false;
    flash(res.ok ? `동기화 완료 — ${res.synced || 0}건` : ('실패: ' + res.error),
          res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => window.location.reload(), 1000);
    return;
  }
  if (action === 'boxhero-api' || action === 'boxhero-xlsx') {
    e.preventDefault();
    flash(action === 'boxhero-api' ? 'API 연동 모드 (.env BOXHERO_API_TOKEN 사용)'
                                   : '엑셀 업로드 화면 — 후속 작업', 'warn');
    return;
  }

  // ----- Templates 페이지 -----
  if (action === 'new-price-tpl') {
    e.preventDefault();
    openPriceTplModal(null);
    return;
  }
  if (action === 'edit-price-tpl' || action === 'dup-price-tpl' || action === 'del-price-tpl') {
    e.preventDefault();
    const id = btn.getAttribute('data-id');
    if (action === 'del-price-tpl') {
      if (!confirm('삭제할까요?')) return;
      const res = await apiPost(`/api/templates/price/${id}/delete`, {});
      flash(res.ok ? '삭제 완료' : ('실패: ' + (res.error || '')), res.ok ? 'ok' : 'err');
      if (res.ok) setTimeout(() => location.reload(), 600);
      return;
    }
    if (action === 'dup-price-tpl') {
      const res = await apiPost(`/api/templates/price/${id}/duplicate`, {});
      flash(res.ok ? '복제 완료' : '실패', res.ok ? 'ok' : 'err');
      if (res.ok) setTimeout(() => location.reload(), 600);
      return;
    }
    openPriceTplModal(id);
    return;
  }
  if (action === 'new-color-tpl') { e.preventDefault(); openColorTplModal(null); return; }
  if (action === 'edit-color-tpl') { e.preventDefault(); openColorTplModal(btn.getAttribute('data-id')); return; }
  if (action === 'dup-color-tpl') {
    e.preventDefault();
    const id = btn.getAttribute('data-id');
    const res = await apiPost(`/api/templates/color/${id}/duplicate`, {});
    flash(res.ok ? '복제 완료' : '실패', res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => location.reload(), 600);
    return;
  }
  if (action === 'del-color-tpl') {
    e.preventDefault();
    const id = btn.getAttribute('data-id');
    if (!confirm('삭제할까요?')) return;
    const res = await apiPost(`/api/templates/color/${id}/delete`, {});
    flash(res.ok ? '삭제 완료' : ('실패: ' + (res.error || '')), res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => location.reload(), 600);
    return;
  }
  if (action === 'new-size-tpl') { e.preventDefault(); openSizeTplModal(null); return; }
  if (action === 'edit-size-tpl') { e.preventDefault(); openSizeTplModal(btn.getAttribute('data-id')); return; }
  if (action === 'dup-size-tpl') {
    e.preventDefault();
    const id = btn.getAttribute('data-id');
    const res = await apiPost(`/api/templates/size/${id}/duplicate`, {});
    flash(res.ok ? '복제 완료' : '실패', res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => location.reload(), 600);
    return;
  }
  if (action === 'del-size-tpl') {
    e.preventDefault();
    const id = btn.getAttribute('data-id');
    if (!confirm('삭제할까요?')) return;
    const res = await apiPost(`/api/templates/size/${id}/delete`, {});
    flash(res.ok ? '삭제 완료' : ('실패: ' + (res.error || '')), res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => location.reload(), 600);
    return;
  }
  if (action === 'new-color') { e.preventDefault(); openColorDictModal(null); return; }
  if (action === 'edit-color') { e.preventDefault(); openColorDictModal(btn.getAttribute('data-code')); return; }
  if (action === 'del-color-dict') {
    e.preventDefault();
    const code = btn.getAttribute('data-code');
    if (!confirm(`색상 사전 항목 '${code}' 삭제할까요?`)) return;
    const res = await apiPost(`/api/dict/color/${encodeURIComponent(code)}/delete`, {});
    flash(res.ok ? '삭제 완료' : ('실패: ' + (res.error || '')), res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => location.reload(), 600);
    return;
  }
  if (action === 'edit-size-rule') {
    e.preventDefault();
    flash('사이즈 사전 편집은 후속 작업', 'warn');
    return;
  }
  // ----- 옵션 매트릭스 개별 CRUD -----
  if (action === 'add-option-direct') {
    e.preventDefault();
    const code = currentBundleCode();
    const color = prompt('색상 코드 (예: 블랙):', '');
    if (!color) return;
    const size = prompt('사이즈 코드 (예: 240):', '');
    if (!size) return;
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/options`,
                              { color_code: color.trim(), size_code: size.trim() });
    if (res.ok) { flash(`옵션 ${res.canonical_sku} 추가됨`); setTimeout(() => location.reload(), 600); }
    else flash('실패: ' + (res.error || ''), 'err');
    return;
  }
  if (action === 'del-option') {
    e.preventDefault();
    const code = currentBundleCode();
    const sku = btn.getAttribute('data-sku');
    if (!confirm(`옵션 '${sku}' 삭제할까요?\n(이력·매핑·등록 정보 함께 cascade)`)) return;
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/options/${encodeURIComponent(sku)}/delete`, {});
    if (res.ok) { flash('삭제 완료'); setTimeout(() => location.reload(), 500); }
    else flash('실패: ' + (res.error || ''), 'err');
    return;
  }
  if (action === 'rename-option') {
    e.preventDefault();
    const code = currentBundleCode();
    const sku = btn.getAttribute('data-sku');
    const tr = btn.closest('tr');
    const cur = (tr?.querySelector('td.mono')?.textContent || '').trim();
    const newColor = prompt(`현재: ${cur}\n새 색상 코드:`, cur.split('-')[0] || '');
    if (!newColor) return;
    const newSize = prompt(`현재: ${cur}\n새 사이즈 코드:`, cur.split('-').slice(1).join('-') || '');
    if (!newSize) return;
    const reason = prompt('변경 사유 (선택, audit 기록):', '') || null;
    const res = await apiPost(
      `/api/bundles/${encodeURIComponent(code)}/options/${encodeURIComponent(sku)}/rename`,
      { new_color: newColor.trim(), new_size: newSize.trim(), reason }
    );
    if (res.ok) {
      flash(`${sku} → ${res.new_sku}`);
      setTimeout(() => location.reload(), 800);
    } else flash('실패: ' + (res.error || ''), 'err');
    return;
  }

  // ----- 콤보(색상·사이즈 조합) -----
  if (action === 'add-combo' || action === 'new-combo') {
    e.preventDefault();
    openComboModal(null);
    return;
  }
  if (action === 'edit-combo') {
    e.preventDefault();
    openComboModal(btn.getAttribute('data-id'));
    return;
  }
  if (action === 'del-combo') {
    e.preventDefault();
    const cid = btn.getAttribute('data-id');
    const removeOpts = confirm('이 조합과 관련된 옵션도 함께 삭제할까요?\n\n(취소 = 콤보만 삭제, 옵션 유지)');
    const code = currentBundleCode();
    const res = await apiPost(
      `/api/bundles/${encodeURIComponent(code)}/combos/${cid}/delete`,
      { remove_options: removeOpts }
    );
    flash(res.ok ? `삭제 완료 (옵션 ${res.options_removed || 0}개 정리)` : ('실패: ' + (res.error || '')),
          res.ok ? 'ok' : 'err');
    if (res.ok) setTimeout(() => location.reload(), 800);
    return;
  }

  // ----- [Phase 2] 단계형 옵션 생성 (1~3축 조합) -----
  if (action === 'step-design') {
    e.preventDefault();
    openStepDesignModal(currentBundleCode());
    return;
  }
});

// ============================================================
// [v2] 템플릿 편집 모달 (가격 / 색상 / 사이즈) — inline overlay
// ============================================================

function _modalBg(content, onClose) {
  const bg = document.createElement('div');
  bg.dataset.modalRoot = '1';
  bg.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  bg.addEventListener('click', (e) => { if (e.target === bg) { bg.remove(); if (onClose) onClose(); } });
  bg.appendChild(content);
  document.body.appendChild(bg);
  return bg;
}

function _modalBox(title, innerHTML, footerButtons) {
  const box = document.createElement('div');
  box.style.cssText = 'background:#fff;border-radius:14px;max-width:720px;width:100%;max-height:90vh;overflow:auto;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,0.3)';
  box.innerHTML = `
    <h2 style="margin:0 0 14px;font-size:18px;font-weight:700">${title}</h2>
    <div class="modal-body">${innerHTML}</div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px;padding-top:14px;border-top:1px solid #eee">${footerButtons}</div>
  `;
  return box;
}

// ============================================================
// [Phase 2] 단계형 옵션 생성 모달 — 1~3축 조합 → 옵션ID 일괄 생성
// ============================================================
function _sdEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function _sdParseValues(text) {
  const out = [];
  (text || '').split(',').forEach(raw => {
    const v = raw.trim();
    if (v && out.indexOf(v) < 0) out.push(v);
  });
  return out;
}
function _sdCartesian(lists) {
  let acc = [[]];
  for (const lst of lists) {
    const next = [];
    for (const combo of acc) for (const v of lst) next.push(combo.concat([v]));
    acc = next;
  }
  return acc;
}

// 시안 E (칩 매트릭스) — 모든 옵션 칸 크기 동일. 1회만 주입.
function _sdInjectStyle() {
  if (document.getElementById('sd-style')) return;
  const s = document.createElement('style');
  s.id = 'sd-style';
  s.textContent = `
    .sd-axis { border:1px solid #eceef1; border-radius:11px; padding:11px 12px; margin-bottom:8px; }
    .sd-axis-top { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
    .sd-axis-tag { font-size:12px; font-weight:800; color:#4e5968; }
    .sd-del { margin-left:auto; background:none; border:0; color:#e5484d; cursor:pointer; font-size:12px; }
    .sd-inrow { display:flex; gap:8px; flex-wrap:wrap; }
    .sd-name, .sd-values { font:inherit; font-size:13px; padding:8px 10px; border:1px solid #d8dce0; border-radius:8px; color:#1a1d21; }
    .sd-name { flex:0 0 130px; } .sd-values { flex:1; min-width:200px; }
    .sd-chips { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
    .sd-chip { font-size:12px; font-weight:700; color:#4e5968; background:#f2f4f6; border-radius:999px; padding:4px 4px 4px 11px; display:flex; align-items:center; gap:3px; }
    .sd-chip .x { cursor:pointer; color:#aab2bd; width:18px; height:18px; display:flex; align-items:center; justify-content:center; border-radius:50%; font-size:13px; }
    .sd-chip .x:hover { background:#dfe3e7; color:#4e5968; }
    .sd-chip-empty { font-size:12px; color:#b0b8c1; margin-top:8px; }
    .sd-mtxhead { display:flex; align-items:center; gap:10px; margin:18px 0 9px; }
    .sd-mtxhead .lbl { font-size:13.5px; font-weight:800; }
    .sd-mtxhead .cnt { font-size:12px; color:#8b95a1; } .sd-mtxhead .cnt b { color:#3182f6; }
    .sd-grid { display:grid; gap:6px; min-width:max-content; }
    .sd-gh { display:flex; align-items:center; justify-content:center; height:40px; font-size:12px; font-weight:700; color:#4e5968; }
    .sd-gh.corner { font-size:10.5px; color:#b0b8c1; cursor:pointer; }
    .sd-gh.colh, .sd-gh.rowh { cursor:pointer; border-radius:8px; }
    .sd-gh.colh:hover, .sd-gh.rowh:hover { background:#f2f4f6; }
    .sd-cell { height:40px; border-radius:9px; cursor:pointer; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:14px; }
    .sd-cell.on { background:#3182f6; color:#fff; }
    .sd-cell.off { background:#f2f4f6; color:#cdd2d8; }
    .sd-cell.off:hover { background:#e7eaed; }
    .sd-cell.c1 { font-size:13px; padding:0 8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .sd-layer { font-weight:700; font-size:12.5px; margin:14px 0 6px; color:#333d4b; }
  `;
  document.head.appendChild(s);
}

function openStepDesignModal(code) {
  if (!code) { alert('모음전 코드를 찾을 수 없어요.'); return; }
  _sdInjectStyle();
  const steps = [{ name: '색상', values: '' }, { name: '사이즈', values: '' }];
  const selected = new Set();   // key = JSON.stringify(valuesArray)
  const seen = new Set();
  const keyOf = (vals) => JSON.stringify(vals);

  const box = _modalBox('단계형 옵션 생성',
    '<div style="font-size:13px;color:var(--n500,#888);margin-bottom:12px">'
    + '축마다 이름과 값(쉼표 구분)을 넣으면 값이 칩으로 정리되고 <b>조합 매트릭스</b>가 나옵니다. '
    + '칸을 클릭해 켜고(✓) 끄세요 — 켜진 칸만 옵션으로 만들어집니다.</div>'
    + '<div id="sd-steps"></div>'
    + '<button class="btn btn-sm" id="sd-add-step" type="button" style="margin-top:6px">＋ 축 추가 (최대 3축)</button>'
    + '<div class="sd-mtxhead"><span class="lbl">조합 매트릭스</span>'
    + '<span id="sd-count" class="cnt"></span>'
    + '<button class="btn btn-sm" id="sd-all" type="button" style="margin-left:auto">전체 선택/해제</button></div>'
    + '<div id="sd-matrix"></div>',
    '<button class="btn" id="sd-cancel" type="button">취소</button>'
    + '<button class="btn btn-primary" id="sd-submit" type="button">옵션 생성</button>');
  const bg = _modalBg(box);
  const $ = (sel) => box.querySelector(sel);
  const $$ = (sel) => box.querySelectorAll(sel);
  const close = () => bg.remove();
  let cellVals = [];   // idx → values 배열 (현재 렌더 기준)

  function renderSteps() {
    $('#sd-steps').innerHTML = steps.map((st, i) => `
      <div class="sd-axis">
        <div class="sd-axis-top">
          <span class="sd-axis-tag">${i + 1}축${i === 0 ? ' · 가로 ↔' : i === 1 ? ' · 세로 ↕' : ' · 겹 ▦'}</span>
          ${steps.length > 1 ? `<button class="sd-del" data-i="${i}" type="button">삭제</button>` : ''}
        </div>
        <div class="sd-inrow">
          <input class="sd-name" data-i="${i}" placeholder="축 이름" value="${_sdEsc(st.name)}">
          <input class="sd-values" data-i="${i}" placeholder="값 — 쉼표로 구분 (예: 블랙, 화이트, 그레이)" value="${_sdEsc(st.values)}">
        </div>
        <div class="sd-chips" id="sd-chips-${i}"></div>
      </div>`).join('');
    steps.forEach((_, i) => refreshChips(i));
    const addBtn = $('#sd-add-step');
    addBtn.disabled = steps.length >= 3;
    addBtn.style.opacity = steps.length >= 3 ? 0.4 : 1;
  }

  function refreshChips(i) {
    const wrap = $('#sd-chips-' + i);
    if (!wrap) return;
    const vals = _sdParseValues(steps[i].values);
    wrap.innerHTML = vals.length
      ? vals.map((v, vi) => `<span class="sd-chip">${_sdEsc(v)}`
          + `<span class="x" data-i="${i}" data-vi="${vi}" role="button">×</span></span>`).join('')
      : '<span class="sd-chip-empty">쉼표로 값을 입력하면 칩으로 정리됩니다.</span>';
  }

  function validSteps() {
    return steps
      .map(st => ({ axis_name: (st.name || '').trim() || '축', values: _sdParseValues(st.values) }))
      .filter(st => st.values.length > 0);
  }

  function paintCounts(total) {
    const sub = $('#sd-submit'), n = selected.size;
    sub.disabled = n === 0;
    sub.style.opacity = n === 0 ? 0.4 : 1;
    sub.textContent = n === 0 ? '옵션 생성' : `옵션 ${n}개 생성`;
    const cnt = $('#sd-count');
    if (cnt) cnt.textContent = total ? `선택 ${n}개 / 전체 ${total}개` : '';
  }

  function pushCell(vals) {
    const idx = cellVals.length;
    cellVals.push(vals);
    return { idx, on: selected.has(keyOf(vals)) };
  }

  function renderMatrix() {
    const valid = validSteps();
    const wrap = $('#sd-matrix');
    cellVals = [];
    if (!valid.length) {
      wrap.innerHTML = '<div style="font-size:13px;color:var(--n500,#888)">값을 입력하면 조합 매트릭스가 나타납니다.</div>';
      selected.clear(); seen.clear(); paintCounts(0);
      return;
    }
    const combos = _sdCartesian(valid.map(s => s.values));
    const curKeys = new Set(combos.map(c => keyOf(c)));
    [...selected].forEach(k => { if (!curKeys.has(k)) selected.delete(k); });
    [...seen].forEach(k => { if (!curKeys.has(k)) seen.delete(k); });
    combos.forEach(c => { const k = keyOf(c); if (!seen.has(k)) { seen.add(k); selected.add(k); } });

    let html = '';
    if (valid.length === 1) {
      html += `<div class="sd-grid" style="grid-template-columns:repeat(${valid[0].values.length},96px)">`;
      combos.forEach(c => {
        const { idx, on } = pushCell(c);
        html += `<div class="sd-cell c1 ${on ? 'on' : 'off'}" data-idx="${idx}">${on ? '✓ ' : ''}${_sdEsc(c[0])}</div>`;
      });
      html += '</div>';
    } else {
      const cols = valid[0].values, rows = valid[1].values;
      const layers = valid.length === 3 ? valid[2].values : [null];
      const gtc = `82px repeat(${cols.length},58px)`;
      layers.forEach((layerVal, ti) => {
        if (valid.length === 3) {
          html += `<div class="sd-layer">${_sdEsc(valid[2].axis_name)}: `
            + `<span style="color:var(--primary,#3182f6)">${_sdEsc(layerVal)}</span></div>`;
        }
        html += `<div style="overflow:auto;margin-bottom:4px"><div class="sd-grid" style="grid-template-columns:${gtc}">`;
        html += `<div class="sd-gh corner" data-sd="corner" data-tbl="${ti}">`
          + `${_sdEsc(valid[1].axis_name)} \\ ${_sdEsc(valid[0].axis_name)}</div>`;
        cols.forEach((cv, ci) => {
          html += `<div class="sd-gh colh" data-sd="col" data-tbl="${ti}" data-ci="${ci}">${_sdEsc(cv)}</div>`;
        });
        rows.forEach((rv, ri) => {
          html += `<div class="sd-gh rowh" data-sd="row" data-tbl="${ti}" data-ri="${ri}">${_sdEsc(rv)}</div>`;
          cols.forEach((cv, ci) => {
            const vals = valid.length === 3 ? [cv, rv, layerVal] : [cv, rv];
            const { idx, on } = pushCell(vals);
            html += `<div class="sd-cell ${on ? 'on' : 'off'}" data-idx="${idx}" `
              + `data-tbl="${ti}" data-ci="${ci}" data-ri="${ri}">${on ? '✓' : ''}</div>`;
          });
        });
        html += '</div></div>';
      });
    }
    wrap.innerHTML = html;
    paintCounts(combos.length);
  }

  function toggleKeys(keys) {
    const anyOff = keys.some(k => !selected.has(k));
    keys.forEach(k => anyOff ? selected.add(k) : selected.delete(k));
    renderMatrix();
  }
  const cellKeys = (sel) => [...$$(sel)].map(x => keyOf(cellVals[+x.dataset.idx]));

  $('#sd-steps').addEventListener('input', (e) => {
    const i = +e.target.dataset.i;
    if (e.target.classList.contains('sd-name')) steps[i].name = e.target.value;
    else if (e.target.classList.contains('sd-values')) { steps[i].values = e.target.value; refreshChips(i); }
    renderMatrix();
  });
  $('#sd-steps').addEventListener('click', (e) => {
    const del = e.target.closest('.sd-del');
    if (del) { steps.splice(+del.dataset.i, 1); renderSteps(); renderMatrix(); return; }
    const x = e.target.closest('.sd-chip .x');
    if (x) {
      const i = +x.dataset.i;
      const vals = _sdParseValues(steps[i].values);
      vals.splice(+x.dataset.vi, 1);
      steps[i].values = vals.join(', ');
      const inp = $(`.sd-values[data-i="${i}"]`);
      if (inp) inp.value = steps[i].values;
      refreshChips(i); renderMatrix();
    }
  });
  $('#sd-add-step').addEventListener('click', () => {
    if (steps.length >= 3) return;
    steps.push({ name: '', values: '' });
    renderSteps(); renderMatrix();
  });
  $('#sd-all').addEventListener('click', () => {
    if (cellVals.length) toggleKeys(cellKeys('#sd-matrix .sd-cell'));
  });
  $('#sd-matrix').addEventListener('click', (e) => {
    const c = e.target.closest('.sd-cell');
    if (c) {
      const k = keyOf(cellVals[+c.dataset.idx]);
      selected.has(k) ? selected.delete(k) : selected.add(k);
      renderMatrix(); return;
    }
    const sd = e.target.closest('[data-sd]');
    if (!sd) return;
    const tb = sd.dataset.tbl, t = sd.dataset.sd;
    if (t === 'corner') toggleKeys(cellKeys(`#sd-matrix .sd-cell[data-tbl="${tb}"]`));
    else if (t === 'col') toggleKeys(cellKeys(`#sd-matrix .sd-cell[data-tbl="${tb}"][data-ci="${sd.dataset.ci}"]`));
    else if (t === 'row') toggleKeys(cellKeys(`#sd-matrix .sd-cell[data-tbl="${tb}"][data-ri="${sd.dataset.ri}"]`));
  });
  $('#sd-cancel').addEventListener('click', close);
  $('#sd-submit').addEventListener('click', async () => {
    const payloadSteps = validSteps();
    if (!payloadSteps.length || selected.size === 0) return;
    const btn = $('#sd-submit');
    btn.disabled = true; btn.textContent = '생성 중…';
    const res = await apiPost(
      `/api/bundles/${encodeURIComponent(code)}/options/combo`,
      { steps: payloadSteps, selected: [...selected].map(k => JSON.parse(k)) });
    if (res && res.ok) {
      flash(`옵션 ${res.created || 0}개 생성 완료`);
      close();
      setTimeout(() => location.reload(), 700);
    } else {
      flash('실패: ' + ((res && res.error) || '알 수 없는 오류'), 'err');
      btn.disabled = false; renderMatrix();
    }
  });

  renderSteps();
  renderMatrix();
}

// ============================================================
// [Phase 3] 옵션 소싱처 URL 관리 모달 — 한 소싱처 다중 URL
// ============================================================
function openOptionUrlModal(sku, onChange) {
  if (!sku) return;
  let data = { urls: [], sources: [] };
  let changed = false;

  const box = _modalBox('옵션 소싱처 URL 관리',
    `<div style="font-size:13px;color:var(--n600,#555);margin-bottom:6px">옵션 <b>${_sdEsc(sku)}</b></div>`
    + '<div style="font-size:12.5px;color:var(--n500,#888);margin-bottom:14px">한 소싱처에 URL을 여러 개 등록할 수 있어요. URL 없이 둬도 됩니다 (오프라인 전용 옵션).</div>'
    + '<div id="ou-list" style="font-size:13px;color:var(--n500,#888)">불러오는 중…</div>'
    + '<div style="margin-top:14px;padding-top:14px;border-top:1px solid #f0f2f4">'
    + '<div style="font-size:12px;font-weight:800;color:#4e5968;margin-bottom:7px">＋ URL 추가</div>'
    + '<div style="display:flex;gap:8px;flex-wrap:wrap">'
    + '<select id="ou-src" style="font:inherit;font-size:13px;padding:8px 10px;border:1px solid #d8dce0;border-radius:8px;flex:0 0 150px"></select>'
    + '<input id="ou-url" placeholder="https://..." style="font:inherit;font-size:13px;padding:8px 10px;border:1px solid #d8dce0;border-radius:8px;flex:1;min-width:200px">'
    + '<button class="btn btn-primary btn-sm" id="ou-add" type="button">추가</button>'
    + '</div></div>',
    '<button class="btn" id="ou-close" type="button">닫기</button>');
  const finish = () => { bg.remove(); if (changed && onChange) onChange(); };
  const bg = _modalBg(box, () => { if (changed && onChange) onChange(); });
  const $ = (s) => box.querySelector(s);

  function renderList() {
    const wrap = $('#ou-list');
    if (!data.urls.length) {
      wrap.innerHTML = '<div style="padding:14px;text-align:center;background:#f7f8f9;border-radius:9px;color:#b0b8c1">'
        + '등록된 URL이 없습니다 — 오프라인 전용 옵션도 정상입니다.</div>';
      return;
    }
    const groups = {};
    data.urls.forEach(u => {
      (groups[u.source_id] = groups[u.source_id] || { name: u.source_name, items: [] }).items.push(u);
    });
    wrap.innerHTML = Object.keys(groups).map(sid => {
      const g = groups[sid];
      return `<div style="margin-bottom:10px">
        <div style="font-size:12px;font-weight:800;color:var(--primary,#3182f6);margin-bottom:5px">`
        + `${_sdEsc(g.name)} <span style="color:#b0b8c1">· ${g.items.length}개</span></div>`
        + g.items.map(u => `<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid #eceef1;border-radius:8px;margin-bottom:4px">
            <span style="flex:1;min-width:0;font-size:12px;color:#4e5968;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_sdEsc(u.product_url)}</span>
            <button class="ou-del" data-id="${u.id}" type="button" style="background:none;border:0;color:#e5484d;cursor:pointer;font-size:12px;font-weight:700">삭제</button>
          </div>`).join('')
        + '</div>';
    }).join('');
  }

  async function load() {
    const j = await apiGet(`/api/options/${encodeURIComponent(sku)}/source-urls`);
    if (!j || !j.ok) { $('#ou-list').innerHTML = '<div style="color:#e5484d">불러오기 실패</div>'; return; }
    data = j;
    $('#ou-src').innerHTML = data.sources.map(x => `<option value="${x.id}">${_sdEsc(x.name)}</option>`).join('');
    renderList();
  }

  $('#ou-list').addEventListener('click', async (e) => {
    const del = e.target.closest('.ou-del');
    if (!del) return;
    if (!confirm('이 URL을 삭제할까요?')) return;
    const r = await fetch(`/api/options/${encodeURIComponent(sku)}/source-urls/${del.dataset.id}`, { method: 'DELETE' });
    const j = await r.json().catch(() => null);
    if (j && j.ok) { changed = true; flash('URL 삭제됨'); load(); }
    else flash('삭제 실패', 'err');
  });
  $('#ou-add').addEventListener('click', async () => {
    const srcId = $('#ou-src').value, url = $('#ou-url').value.trim();
    if (!srcId) { flash('소싱처를 선택하세요', 'err'); return; }
    if (!url) { flash('URL을 입력하세요', 'err'); return; }
    const res = await apiPost(`/api/options/${encodeURIComponent(sku)}/source-urls`,
      { source_id: +srcId, product_url: url });
    if (res && res.ok) { changed = true; $('#ou-url').value = ''; flash('URL 추가됨'); load(); }
    else flash('추가 실패: ' + ((res && res.error) || ''), 'err');
  });
  $('#ou-close').addEventListener('click', finish);

  load();
}

// ============================================================
// [소싱처 재설계] 사이트 소싱처 추가 모달 — 도메인 자동감지 (시안 B)
// ============================================================
function openAddSourceModal() {
  let probed = {};
  let color = '#3182f6';
  const COLORS = ['#191f28', '#3182f6', '#e5484d', '#03c75a', '#7c3aed', '#f59e0b', '#1f3a93'];
  const box = _modalBox('사이트 소싱처 추가',
    '<div style="font-size:13px;color:var(--n500,#888);margin-bottom:13px">사이트 주소를 넣고 <b>불러오기</b>를 누르면 로고·이름을 자동으로 가져옵니다. '
    + '추가하면 소싱처 계정 페이지에도 함께 등록됩니다 (통합 목록).</div>'
    + '<div style="margin-bottom:12px"><div style="font-size:12px;font-weight:800;color:#4e5968;margin-bottom:5px">사이트 주소</div>'
    + '<div style="display:flex;gap:7px"><input id="as-domain" placeholder="예: 29cm.co.kr" '
    + 'style="flex:1;font:inherit;font-size:13px;padding:9px 11px;border:1px solid #d8dce0;border-radius:8px">'
    + '<button class="btn" id="as-probe" type="button">불러오기</button></div></div>'
    + '<div style="margin-bottom:12px"><div style="font-size:12px;font-weight:800;color:#4e5968;margin-bottom:5px">소싱처 이름</div>'
    + '<input id="as-label" placeholder="예: 29CM" style="width:100%;font:inherit;font-size:13px;padding:9px 11px;border:1px solid #d8dce0;border-radius:8px"></div>'
    + '<div style="display:flex;align-items:center;gap:11px"><span style="font-size:12px;font-weight:800;color:#4e5968">로고</span>'
    + '<span id="as-logo" style="width:34px;height:34px;border-radius:9px;background:#3182f6;color:#fff;font-weight:800;'
    + 'display:flex;align-items:center;justify-content:center;font-size:14px">?</span>'
    + '<span id="as-colors" style="display:flex;gap:6px"></span></div>',
    '<button class="btn" id="as-cancel" type="button">취소</button>'
    + '<button class="btn btn-primary" id="as-submit" type="button">소싱처 추가</button>');
  const bg = _modalBg(box);
  const $ = (s) => box.querySelector(s);
  function paintLogo() {
    const lbl = $('#as-label').value.trim();
    $('#as-logo').textContent = (lbl[0] || '?').toUpperCase();
    $('#as-logo').style.background = color;
  }
  $('#as-colors').innerHTML = COLORS.map(c =>
    `<span class="as-c" data-c="${c}" style="width:21px;height:21px;border-radius:6px;background:${c};cursor:pointer;display:inline-block"></span>`).join('');
  $('#as-colors').addEventListener('click', (e) => {
    const c = e.target.closest('.as-c');
    if (c) { color = c.dataset.c; paintLogo(); }
  });
  $('#as-label').addEventListener('input', paintLogo);
  $('#as-probe').addEventListener('click', async () => {
    const d = $('#as-domain').value.trim();
    if (!d) { flash('사이트 주소를 입력하세요', 'err'); return; }
    const r = await apiPost('/api/sources/probe', { url: d });
    if (r && r.ok) {
      probed = r;
      if (!$('#as-label').value.trim()) $('#as-label').value = r.title || r.label_suggestion || '';
      if (r.logo_color) color = r.logo_color;
      paintLogo();
      flash('자동 감지 완료');
    } else flash('감지 실패 — 직접 입력하세요', 'warn');
  });
  $('#as-cancel').addEventListener('click', () => bg.remove());
  $('#as-submit').addEventListener('click', async () => {
    const label = $('#as-label').value.trim();
    const domain = $('#as-domain').value.trim();
    if (!label || !domain) { flash('이름과 주소를 입력하세요', 'err'); return; }
    const btn = $('#as-submit');
    btn.disabled = true; btn.textContent = '추가 중…';
    const res = await apiPost('/api/sources/add', {
      label: label, domain: domain, logo_color: color,
      logo_letter: (label[0] || '').toUpperCase(),
      favicon_url: probed.favicon_url || '',
    });
    if (res && res.ok) {
      flash(`'${label}' 소싱처 추가됨`);
      bg.remove();
      setTimeout(() => location.reload(), 700);
    } else {
      flash('추가 실패: ' + ((res && res.error) || ''), 'err');
      btn.disabled = false; btn.textContent = '소싱처 추가';
    }
  });
  paintLogo();
}

async function openPriceTplModal(id, initialTab) {
  let initial = {};
  if (id) {
    const r = await fetch(`/api/templates/price/${id}`);
    const j = await r.json();
    if (!j.ok) { alert('불러오기 실패: ' + (j.error || '')); return; }
    initial = j.template || {};
  }
  const v = (k) => (initial[k] != null ? initial[k] : '');

  const row = (label, inner) => `
    <div style="display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid #f3f3f3">
      <label style="flex:0 0 200px;font-size:13px;color:#555">${label}</label>
      <div style="flex:1;min-width:0">${inner}</div>
    </div>`;
  const num = (k, ph, step) => `
    <input type="number" data-key="${k}" ${step ? `step="${step}"` : ''}
           value="${v(k)}" placeholder="${ph || ''}"
           style="width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;box-sizing:border-box;font-variant-numeric:tabular-nums">`;
  const txt = (k, ph) => `
    <input type="text" data-key="${k}" value="${v(k)}" placeholder="${ph || ''}"
           style="width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;box-sizing:border-box">`;
  const delivery = (prefix) => {
    const raw = initial[`${prefix}_delivery_fee`];
    const isFree = !raw || Number(raw) === 0;
    return `
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <label style="font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer">
          <input type="radio" name="ptm-${prefix}-deliv" value="free" ${isFree ? 'checked' : ''}>무료배송</label>
        <label style="font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer">
          <input type="radio" name="ptm-${prefix}-deliv" value="paid" ${isFree ? '' : 'checked'}>배송비</label>
        <input type="number" data-key="${prefix}_delivery_fee" value="${isFree ? 0 : raw}" ${isFree ? 'disabled' : ''}
               placeholder="배송비" style="width:120px;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
        <span style="font-size:12px;color:#9CA3AF">원</span>
      </div>`;
  };
  // [2026-05-25] B6 라디오+인라인 한 줄 — 소싱처/사입 각각 (마진율 / 마진금액 / 지정가) 행 3개
  // 활성 행 = 파란 보더 + 밑줄, 비활성 = 보더 없음 회색. 비활성 입력값도 보존 (전환 시 잃지 않음).
  // 좌측 채널 색 세로줄 없음. 소싱처 색상 = 초록(옵션 트리·toss.css btn-bulk-conv 와 통일).
  const modeCards = (prefix, side) => {
    // side = 'sourcing' (소싱처) | 'purchase' (사입)
    const modeKey   = `${prefix}_mode_${side}`;
    const rateKey   = `${prefix}_rate_${side}`;
    const amountKey = `${prefix}_amount_${side}`;
    // 지정가는 기존 컬럼 재사용: 소싱 = external_sale_price, 사입 = boxhero_sale_price
    const fixedKey = side === 'sourcing' ? `${prefix}_external_sale_price` : `${prefix}_boxhero_sale_price`;
    const curMode = initial[modeKey] || 'rate';
    const radioRow = (mode, label, valKey, suffix, defaultRate) => {
      const isOn = curMode === mode;
      const rawVal = initial[valKey];
      // rate 모드는 0.0945 → 9.45 로 표시 (사용자 친화 %)
      let dispVal = rawVal != null ? rawVal : (mode === 'rate' ? defaultRate : '');
      if (mode === 'rate' && rawVal != null) dispVal = (Number(rawVal) * 100).toFixed(2);
      return `
        <button type="button" class="ptm-modecard" data-prefix="${prefix}" data-side="${side}" data-mode="${mode}"
                style="display:grid;grid-template-columns:16px 60px 1fr 60px;gap:8px;align-items:center;padding:7px 10px;background:${isOn ? '#E8F3FF' : 'transparent'};border:1px solid ${isOn ? '#3182F6' : 'transparent'};border-radius:7px;cursor:pointer;font-family:inherit;transition:all .12s;width:100%;text-align:left">
          <span class="ptm-radio" style="width:14px;height:14px;border-radius:50%;border:1.5px solid ${isOn ? '#3182F6' : '#D1D6DB'};display:inline-block;position:relative;box-sizing:border-box">
            <span class="ptm-radio-fill" style="position:absolute;inset:2px;background:#3182F6;border-radius:50%;display:${isOn ? 'block' : 'none'}"></span>
          </span>
          <span class="ptm-mode-label" style="font-size:12px;color:${isOn ? '#1D4CB0' : '#4E5968'};font-weight:700">${label}</span>
          <input type="number" data-key="${valKey}" data-mode-input="${mode}" data-rate-display="${mode === 'rate' ? '1' : '0'}"
                 value="${dispVal}" step="${mode === 'rate' ? '0.01' : '1'}"
                 style="width:100%;border:0;border-bottom:1px solid ${isOn ? '#3182F6' : 'transparent'};background:transparent;outline:none;font-weight:800;font-size:14px;font-family:inherit;color:${isOn ? '#191F28' : '#9CA3AF'};padding:2px 0;text-align:right">
          <span style="font-size:11px;color:#6B7684;text-align:right">${suffix}</span>
        </button>`;
    };
    const sideLabel = side === 'sourcing' ? '소싱처' : '사입';
    // 색 통일: 소싱처 = 초록(#DCFCE7/#0E7C3A), 사입 = 앰버(#FEF3C7/#92400E) — toss.css btn-bulk-conv 와 일치
    const sideColor = side === 'sourcing'
      ? {bg:'#DCFCE7', tx:'#0E7C3A'}
      : {bg:'#FEF3C7', tx:'#92400E'};
    const defaultRate = prefix === 'ss' ? '9.45' : '12.42';
    return `
      <div style="background:#FAFBFC;border:1px solid #EAEDF0;border-radius:8px;padding:12px 14px;margin-bottom:10px">
        <div style="font-size:12px;font-weight:700;color:#4E5968;margin-bottom:8px;display:flex;align-items:center;gap:6px">
          <span style="background:${sideColor.bg};color:${sideColor.tx};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">${sideLabel}</span>
          책정 방식
        </div>
        <div style="display:flex;flex-direction:column;gap:3px">
          ${radioRow('rate',   '마진율',   rateKey,   '%',         defaultRate)}
          ${radioRow('amount', '마진금액', amountKey, '원',        '')}
          ${radioRow('fixed',  '지정가',   fixedKey,  '원 (할인가)', '')}
        </div>
        <input type="hidden" data-key="${modeKey}" data-mode-hidden="${prefix}-${side}" value="${curMode}">
      </div>`;
  };
  const market = (prefix, topHtml) => `
    ${topHtml || ''}
    ${row('마켓 수수료율', num(prefix + '_fee_rate', '0.06 = 6%', '0.0001'))}
    ${row('정상가', num(prefix + '_normal_price', '원'))}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
      ${modeCards(prefix, 'sourcing')}
      ${modeCards(prefix, 'purchase')}
    </div>
    ${row('배송타입', delivery(prefix))}
    ${row('반품비', num(prefix + '_return_fee', '원'))}
    ${row('교환비', num(prefix + '_exchange_fee', '원'))}`;

  // [2026-06-02] 매입가 산정 우선순위 — 「평균 매입가」 바로 아래 보조행 (시안3)
  //   사입 카드 0원 차단 UX 의 단일 진실 원천. 같은 템플릿 옵션 모두 일괄 적용.
  //   설명은 초딩도 알아듣게 평이하게. 버튼 선택에 따라 PRIO_DESC 로 교체.
  const PRIO_DESC = {
    template: `📌 <b>이 칸에 직접 적은 매입가</b>를 먼저 써요.<br>` +
              `• 이 칸이 비어 있으면(0원) → <b>옵션마다 실제로 사온 평균 가격</b>을 대신 써요.<br>` +
              `• 두 값이 모두 없으면 → 원가를 몰라 손해 볼 수 있으니 <b style="color:#DC2626;">판매를 멈춰요.</b>`,
    avg: `📌 <b>옵션마다 실제로 사온 평균 가격</b>을 먼저 써요.<br>` +
         `• 그 값이 없으면(0원) → <b>이 칸에 직접 적은 매입가</b>를 대신 써요.<br>` +
         `• 두 값이 모두 없으면 → 원가를 몰라 손해 볼 수 있으니 <b style="color:#DC2626;">판매를 멈춰요.</b>`,
  };
  const prioSubRow = (curPri) => {
    const isAvg = curPri === 'avg';
    return `
    <div class="ptm-prio-sub" style="display:flex; flex-direction:column; gap:9px; padding:8px 0 12px; border-bottom:1px solid #f3f3f3;">
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="flex:0 0 200px; font-size:13px; color:#555;">매입가(원가) 어느 걸 먼저?</span>
        <div style="display:inline-flex; border:1px solid #D1D6DB; border-radius:7px; overflow:hidden;">
          <button type="button" class="ptm-prio-opt" data-prio="template"
                  style="border:none; background:${isAvg?'#fff':'#3182F6'}; color:${isAvg?'#4E5968':'#fff'}; font-size:12px; font-weight:700; padding:7px 13px; cursor:pointer; font-family:inherit; border-right:1px solid #D1D6DB; white-space:nowrap;">이 칸에 적은 값</button>
          <button type="button" class="ptm-prio-opt" data-prio="avg"
                  style="border:none; background:${isAvg?'#3182F6':'#fff'}; color:${isAvg?'#fff':'#4E5968'}; font-size:12px; font-weight:700; padding:7px 13px; cursor:pointer; font-family:inherit; white-space:nowrap;">옵션 실제 매입가</button>
        </div>
      </div>
      <div id="ptm-prio-desc" style="font-size:12px; color:#8B95A1; line-height:1.75; padding-left:208px;">${isAvg?PRIO_DESC.avg:PRIO_DESC.template}</div>
    </div>
    <input type="hidden" data-key="price_source_priority" id="ptm-prio-hidden" value="${curPri}">`;
  };

  // [2026-05-25] D3 시안 — 판매가 정책 토글 (색상 통일 / 옵션별 cheapest) + 르무통 케이스 ! 툴팁
  const policyBlock = (curPolicy) => {
    const isColor = curPolicy === 'color';
    const sliderBg = isColor ? '#3182F6' : '#D1D6DB';
    const knobX = isColor ? '23px' : '3px';
    const pillBg = isColor ? '#3182F6' : '#E5E8EB';
    const pillFg = isColor ? '#fff' : '#4E5968';
    const pillTx = isColor ? '켜짐' : '꺼짐';
    const statusTx = isColor ? '색상 통일' : '옵션별 cheapest (기본)';
    return `
    <div class="ptm-policy-block" style="margin-top:14px; padding-top:14px; border-top:1px dashed #E5E8EB;">
      <div style="font-size:12.5px; color:#3182F6; font-weight:700; margin-bottom:10px; letter-spacing:.2px;">▦ 판매가 정책</div>
      <div style="display:flex; align-items:flex-start; gap:14px; padding:14px 16px; background:#FAFBFC; border:1.5px solid #E5E8EB; border-radius:12px;">
        <label id="ptm-policy-switch" style="position:relative; width:48px; height:28px; flex-shrink:0; cursor:pointer; margin-top:2px;">
          <span class="ptm-policy-slider" style="position:absolute; inset:0; background:${sliderBg}; border-radius:28px; transition:.2s;">
            <span class="ptm-policy-knob" style="position:absolute; height:22px; width:22px; left:${knobX}; top:3px; background:#fff; border-radius:50%; transition:.2s; box-shadow:0 2px 6px rgba(0,0,0,.2);"></span>
          </span>
        </label>
        <div style="flex:1; min-width:0;">
          <div style="display:flex; align-items:center; gap:7px; font-size:15px; font-weight:700; color:#191F28; letter-spacing:-.2px;">
            색상 통일 모드
            <span class="ptm-policy-info" style="position:relative; display:inline-flex; width:18px; height:18px; align-items:center; justify-content:center; border-radius:50%; background:#3182F6; color:#fff; font-size:11px; font-weight:800; cursor:help; font-family:inherit; font-style:normal; user-select:none; line-height:1;">!</span>
          </div>
          <div style="font-size:13px; color:#6B7684; margin-top:3px; line-height:1.55;">
            같은 색상은 같은 가격으로 통일해요.<br>비싼 소싱처 기준이라 손해 볼 일이 없어요.
          </div>
          <div style="font-size:12px; color:#8B95A1; margin-top:6px;">
            현재 <span class="ptm-policy-pill" style="display:inline-block; padding:2px 8px; background:${pillBg}; color:${pillFg}; border-radius:5px; font-weight:700; font-size:11px;">${pillTx}</span> · <span class="ptm-policy-status">${statusTx}</span>
          </div>
        </div>
      </div>
      <input type="hidden" data-key="pricing_policy" id="ptm-policy-hidden" value="${curPolicy}">
    </div>`;
  };
  const tabBtn = (key, label) => `
    <button type="button" class="ptm-tab" data-tab="${key}"
            style="padding:8px 16px;background:none;border:none;border-bottom:2px solid transparent;font-size:14px;color:#8B95A1;font-weight:500;cursor:pointer">${label}</button>`;

  const inner = `
    <div style="display:flex;gap:2px;border-bottom:1px solid #E5E8EB;margin-bottom:6px">
      ${tabBtn('basic', '기본정보')}${tabBtn('ss', '스마트스토어')}${tabBtn('cp', '쿠팡')}
    </div>
    <div class="ptm-panel" data-panel="basic">
      <div style="position:relative;margin:8px 0 4px">
        <input id="ptm-prod-search" type="text" autocomplete="off"
               placeholder="제품(모델) 검색 — 선택 시 평균 매입가 자동 입력"
               style="width:100%;padding:8px 10px;border:1px solid #D1D6DB;border-radius:6px;font-size:13px;box-sizing:border-box">
        <div id="ptm-prod-results" style="display:none;position:absolute;left:0;right:0;top:40px;background:#fff;border:1px solid #D1D6DB;border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,0.14);max-height:240px;overflow:auto;z-index:20"></div>
      </div>
      ${row('템플릿명', txt('name', '브랜드명 + 모델명 (예: 르무통 클래식)'))}
      ${row('평균 매입가', num('boxhero_purchase_price', '원'))}
      ${prioSubRow(v('price_source_priority') || 'template')}
      ${row('매입가 하한', num('guardrail_lower', '원'))}
      ${row('매입가 상한', num('guardrail_upper', '원'))}
    </div>
    <div class="ptm-panel" data-panel="ss" style="display:none">
      ${market('ss')}
      ${policyBlock(v('pricing_policy') || 'cheapest')}
    </div>
    <div class="ptm-panel" data-panel="cp" style="display:none">
      ${market('coupang', row('위너 프리미엄가', num('winner_premium_price', '원')))}
    </div>`;

  const box = _modalBox(
    id ? `💰 가격 템플릿 편집 (id=${id})` : '💰 새 가격 템플릿',
    inner,
    `<button class="btn" id="ptm-cancel">취소</button>
     <button class="btn btn-primary" id="ptm-save">저장</button>`
  );
  // [2026-05-25] B6 좌우 병렬 적용 — 소싱처/사입 2열 들어가도록 모달 폭 확장
  box.style.maxWidth = '960px';
  const bg = _modalBg(box);

  // 탭 전환
  const tabs = box.querySelectorAll('.ptm-tab');
  const panels = box.querySelectorAll('.ptm-panel');
  const activateTab = (name) => {
    tabs.forEach(t => {
      const on = t.dataset.tab === name;
      t.style.color = on ? '#3182F6' : '#8B95A1';
      t.style.fontWeight = on ? '700' : '500';
      t.style.borderBottomColor = on ? '#3182F6' : 'transparent';
    });
    panels.forEach(p => { p.style.display = p.dataset.panel === name ? '' : 'none'; });
  };
  tabs.forEach(t => t.addEventListener('click', () => activateTab(t.dataset.tab)));
  // [2026-05-25] 호출자가 initialTab 전달 시 해당 탭 활성 (예: 마켓 행 "수정" → 'ss'/'cp')
  const validTabs = ['basic', 'ss', 'cp'];
  activateTab(validTabs.includes(initialTab) ? initialTab : 'basic');

  // 배송타입 라디오 ↔ 배송비 입력 연동 (무료배송 = 배송비 0)
  ['ss', 'coupang'].forEach(prefix => {
    const feeInput = box.querySelector(`input[data-key="${prefix}_delivery_fee"]`);
    box.querySelectorAll(`input[name="ptm-${prefix}-deliv"]`).forEach(radio => {
      radio.addEventListener('change', () => {
        if (!radio.checked) return;
        if (radio.value === 'free') {
          feeInput.value = '0';
          feeInput.disabled = true;
        } else {
          feeInput.disabled = false;
          if (!feeInput.value || feeInput.value === '0') feeInput.value = '';
          feeInput.focus();
        }
      });
    });
  });

  // [2026-05-25] D3 — 정책 토글 스위치 (색상 통일 ↔ 옵션별 cheapest)
  const policySwitch = box.querySelector('#ptm-policy-switch');
  const policyHidden = box.querySelector('#ptm-policy-hidden');
  if (policySwitch && policyHidden) {
    policySwitch.addEventListener('click', () => {
      const cur = policyHidden.value === 'color' ? 'color' : 'cheapest';
      const next = cur === 'color' ? 'cheapest' : 'color';
      policyHidden.value = next;
      const isColor = next === 'color';
      const slider = policySwitch.querySelector('.ptm-policy-slider');
      const knob   = policySwitch.querySelector('.ptm-policy-knob');
      if (slider) slider.style.background = isColor ? '#3182F6' : '#D1D6DB';
      if (knob)   knob.style.left = isColor ? '23px' : '3px';
      const pill = box.querySelector('.ptm-policy-pill');
      if (pill) {
        pill.textContent = isColor ? '켜짐' : '꺼짐';
        pill.style.background = isColor ? '#3182F6' : '#E5E8EB';
        pill.style.color = isColor ? '#fff' : '#4E5968';
      }
      const status = box.querySelector('.ptm-policy-status');
      if (status) status.textContent = isColor ? '색상 통일' : '옵션별 cheapest (기본)';
    });
  }
  // [2026-06-02] 매입가 우선순위 토글 (template / avg) — 선택 시 설명도 교체
  const prioHidden = box.querySelector('#ptm-prio-hidden');
  const prioBtns = box.querySelectorAll('.ptm-prio-opt');
  const prioDesc = box.querySelector('#ptm-prio-desc');
  if (prioHidden && prioBtns.length) {
    prioBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const next = btn.dataset.prio === 'avg' ? 'avg' : 'template';
        prioHidden.value = next;
        prioBtns.forEach(b => {
          const on = b.dataset.prio === next;
          b.style.background = on ? '#3182F6' : '#fff';
          b.style.color = on ? '#fff' : '#4E5968';
        });
        if (prioDesc) prioDesc.innerHTML = PRIO_DESC[next];
      });
    });
  }

  // [2026-05-25] D3 — ! 정보 hover 시 르무통 메이트 블랙 240mm 케이스 툴팁
  const policyInfo = box.querySelector('.ptm-policy-info');
  if (policyInfo) {
    const tip = document.createElement('div');
    // [2026-05-25] 가독성 — 글씨·창 180% 스케일 (사용자 요청, ×1.8)
    // position:fixed + document.body portal — 모달 overflow 에 잘리지 않음
    tip.style.cssText = 'display:none; position:fixed; top:0; left:0; width:680px; background:#191F28; border-radius:14px; box-shadow:0 16px 40px rgba(0,0,0,.4); padding:32px 36px 28px; color:#E5E8EB; font-family:inherit; font-style:normal; font-weight:400; text-align:left; z-index:10000; pointer-events:none; font-variant-numeric:tabular-nums; letter-spacing:-.1px;';
    tip.innerHTML = `
      <div style="font-size:22px; color:#9BC1FF; font-weight:700; letter-spacing:.3px;">예시</div>
      <div style="font-size:27px; color:#fff; font-weight:700; margin-top:5px; letter-spacing:-.3px;">르무통 메이트 블랙 240mm</div>

      <div style="margin-top:22px; padding:22px 25px; background:#0F141A; border-radius:12px;">
        <div style="display:grid; grid-template-columns:108px 158px 1fr; gap:25px; padding:7px 0; font-size:23px; align-items:baseline;">
          <span style="color:#9CA3AF;">무신사</span>
          <span style="color:#fff; font-weight:600; text-align:right;">90,000원</span>
          <span style="color:#FBBF24; font-size:21px;">240mm 품절</span>
        </div>
        <div style="display:grid; grid-template-columns:108px 158px 1fr; gap:25px; padding:7px 0; font-size:23px; align-items:baseline;">
          <span style="color:#9CA3AF;">르무통</span>
          <span style="color:#fff; font-weight:600; text-align:right;">100,000원</span>
          <span style="color:#9BE0BD; font-size:21px;">전체 재고</span>
        </div>
      </div>

      <div style="margin-top:22px; display:flex; flex-direction:column; gap:14px;">
        <div style="padding:22px 25px; border-radius:12px; background:#0F141A;">
          <div style="display:flex; align-items:center; gap:14px; font-size:22px; font-weight:700; color:#FCA5A5; letter-spacing:-.1px;">
            <span style="font-size:23px;">⚪</span>끄면 · 옵션별 cheapest (기본)
          </div>
          <p style="margin:13px 0 0; color:#CBD5E1; font-size:22px; line-height:1.75;">
            판매가는 <span style="color:#fff; font-weight:600;">90,000원</span>인데 240mm가 팔리면 <span style="color:#fff; font-weight:600;">100,000원</span>에 사야 해요.<br>
            <span style="color:#FCA5A5; font-weight:600;">건당 10,000원씩 손해</span>예요.
          </p>
        </div>
        <div style="padding:22px 25px; border-radius:12px; background:#0F141A;">
          <div style="display:flex; align-items:center; gap:14px; font-size:22px; font-weight:700; color:#9BE0BD; letter-spacing:-.1px;">
            <span style="font-size:23px;">🟢</span>켜면 · 색상 통일
          </div>
          <p style="margin:13px 0 0; color:#CBD5E1; font-size:22px; line-height:1.75;">
            판매가를 <span style="color:#fff; font-weight:600;">100,000원</span>으로 통일해요.<br>
            다른 사이즈는 무신사에서 <span style="color:#fff; font-weight:600;">90,000원</span>에 살 수 있어서<br>
            <span style="color:#9BE0BD; font-weight:600;">건당 10,000원 추가 마진</span>까지 나요.
          </p>
        </div>
      </div>`;
    // Portal to body — 모달 overflow:hidden 으로 잘리지 않게
    document.body.appendChild(tip);

    function positionTip() {
      // viewport 정중앙
      const tipR = tip.getBoundingClientRect();
      const top  = Math.max(12, (window.innerHeight - tipR.height) / 2);
      const left = Math.max(12, (window.innerWidth  - tipR.width)  / 2);
      tip.style.top  = top  + 'px';
      tip.style.left = left + 'px';
    }

    policyInfo.addEventListener('mouseenter', () => {
      tip.style.display = 'block';
      // 보여진 다음 프레임에 측정 (정확한 height 얻기)
      requestAnimationFrame(positionTip);
    });
    policyInfo.addEventListener('mouseleave', () => {
      tip.style.display = 'none';
    });

    // 모달 닫힐 때 tip 도 정리
    const cleanup = () => {
      if (tip.parentNode) tip.parentNode.removeChild(tip);
      observer.disconnect();
    };
    const observer = new MutationObserver(() => {
      if (!document.body.contains(policyInfo)) cleanup();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // 제품 검색 → 평균 매입가 자동 불러오기
  const searchInput = box.querySelector('#ptm-prod-search');
  const resultsBox = box.querySelector('#ptm-prod-results');
  let searchTimer = null;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimer);
    const q = searchInput.value.trim();
    if (!q) { resultsBox.style.display = 'none'; resultsBox.innerHTML = ''; return; }
    searchTimer = setTimeout(async () => {
      let j = {};
      try {
        const r = await fetch('/api/templates/price/product-search?q=' + encodeURIComponent(q));
        j = await r.json();
      } catch (e) { j = {}; }
      if (!j.ok || !j.items || !j.items.length) {
        resultsBox.innerHTML = '<div style="padding:10px 12px;font-size:13px;color:#9CA3AF">검색 결과 없음</div>';
        resultsBox.style.display = 'block';
        return;
      }
      resultsBox.innerHTML = j.items.map(it => {
        const disp = ((it.brand ? it.brand + ' ' : '') + it.name).replace(/"/g, '&quot;');
        const priceTxt = it.avg_purchase_price
          ? it.avg_purchase_price.toLocaleString() + '원'
          : '매입 이력 없음';
        return `<div class="ptm-prod-item" data-name="${disp}" data-price="${it.avg_purchase_price || 0}"
                  style="padding:8px 12px;cursor:pointer;border-bottom:1px solid #f3f3f3">
                  <div style="font-size:13px;font-weight:600">${disp}</div>
                  <div style="font-size:12px;color:#6B7684">평균 매입가 ${priceTxt} · 옵션 ${it.option_count}개</div>
                </div>`;
      }).join('');
      resultsBox.style.display = 'block';
    }, 250);
  });
  searchInput.addEventListener('blur', () => {
    setTimeout(() => { resultsBox.style.display = 'none'; }, 180);
  });
  resultsBox.addEventListener('click', (ev) => {
    const item = ev.target.closest('.ptm-prod-item');
    if (!item) return;
    const price = Number(item.dataset.price || 0);
    const pname = item.dataset.name || '';
    const ppInput = box.querySelector('input[data-key="boxhero_purchase_price"]');
    if (ppInput && price > 0) ppInput.value = price;
    const nameInput = box.querySelector('input[data-key="name"]');
    if (nameInput && !nameInput.value.trim()) nameInput.value = pname;
    resultsBox.style.display = 'none';
    searchInput.value = '';
    flash(price > 0 ? `평균 매입가 ${price.toLocaleString()}원 불러옴` : '매입 이력이 없어 매입가는 비워둡니다',
          price > 0 ? 'ok' : 'warn');
  });

  // [2026-05-25] 책정 모드 카드 클릭 → 활성 전환 (시각·활성 인풋만 적용)
  box.querySelectorAll('.ptm-modecard').forEach(card => {
    card.addEventListener('click', (ev) => {
      // input 클릭은 카드 활성 변경 X (값 편집만)
      if (ev.target.tagName === 'INPUT') return;
      const prefix = card.dataset.prefix;
      const side = card.dataset.side;
      const mode = card.dataset.mode;
      // 같은 (prefix, side) 카드 그룹의 모든 카드 비활성
      box.querySelectorAll(`.ptm-modecard[data-prefix="${prefix}"][data-side="${side}"]`).forEach(c => {
        const isOn = c.dataset.mode === mode;
        c.style.background = isOn ? '#E8F3FF' : 'transparent';
        c.style.border = `1px solid ${isOn ? '#3182F6' : 'transparent'}`;
        // 라디오 점을 선택 항목으로 이동 (핵심 수정)
        const radio = c.querySelector('.ptm-radio');
        if (radio) radio.style.border = `1.5px solid ${isOn ? '#3182F6' : '#D1D6DB'}`;
        const fill = c.querySelector('.ptm-radio-fill');
        if (fill) fill.style.display = isOn ? 'block' : 'none';
        const nameEl = c.querySelector('.ptm-mode-label');
        if (nameEl) { nameEl.style.color = isOn ? '#1D4CB0' : '#4E5968'; }
        const inp = c.querySelector('input');
        if (inp) {
          inp.style.borderBottom = `1px solid ${isOn ? '#3182F6' : 'transparent'}`;
          inp.style.fontWeight = isOn ? '800' : '800';
          inp.style.background = 'transparent';
          inp.style.color = isOn ? '#191F28' : '#9CA3AF';
        }
      });
      // hidden mode 인풋 갱신
      const hidden = box.querySelector(`input[data-mode-hidden="${prefix}-${side}"]`);
      if (hidden) hidden.value = mode;
    });
  });

  box.querySelector('#ptm-cancel').addEventListener('click', () => bg.remove());
  box.querySelector('#ptm-save').addEventListener('click', async () => {
    const payload = id ? { id: parseInt(id) } : {};
    box.querySelectorAll('input[data-key]').forEach(i => {
      const k = i.getAttribute('data-key');
      const val = i.value.trim();
      if (val === '') return;
      let parsed = (i.type === 'number') ? parseFloat(val) : val;
      // 책정 모드의 rate 입력은 사용자가 % 단위로 (9.45) → DB는 비율(0.0945)로 저장
      if (i.dataset.rateDisplay === '1' && typeof parsed === 'number') {
        parsed = parsed / 100;
      }
      payload[k] = parsed;
    });
    if (!payload.name || !String(payload.name).trim()) {
      alert('템플릿명을 입력하세요.');
      activateTab('basic');
      return;
    }
    const res = await apiPost('/api/templates/price', payload);
    if (res.ok) { flash('저장 완료'); bg.remove(); setTimeout(() => location.reload(), 500); }
    else flash('실패: ' + (res.error || ''), 'err');
  });
}

async function openColorTplModal(id) {
  let initial = { name: '', color_codes: [], note: '' };
  if (id) {
    const r = await fetch(`/api/templates/color/${id}`);
    const j = await r.json();
    if (!j.ok) { alert('불러오기 실패: ' + (j.error || '')); return; }
    initial = j.template || initial;
  }
  const codesHtml = (initial.color_codes || []).map(c => `<span class="chip on" data-code="${c}" style="cursor:pointer">${c} ✕</span>`).join('');
  const box = _modalBox(
    id ? `🎨 색상 템플릿 편집 (id=${id})` : '🎨 새 색상 템플릿',
    `
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">이름</label>
      <input id="ctm-name" type="text" value="${initial.name || ''}"
             style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px">
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">색상 코드 (칩 클릭 = 삭제)</label>
      <div id="ctm-chips" class="chip-row" style="margin-bottom:8px">${codesHtml}</div>
      <div style="display:flex;gap:6px">
        <input id="ctm-new-code" type="text" placeholder="블랙 / 베이지 / 네이비 ..."
               style="flex:1;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
        <button class="btn" id="ctm-add">+ 추가</button>
      </div>
    </div>
    <div>
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">메모 (선택)</label>
      <input id="ctm-note" type="text" value="${initial.note || ''}"
             style="width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
    </div>
    `,
    `<button class="btn" id="ctm-cancel">취소</button>
     <button class="btn btn-primary" id="ctm-save">저장</button>`
  );
  const bg = _modalBg(box);
  const refreshChips = () => {
    const codes = Array.from(box.querySelectorAll('#ctm-chips .chip')).map(c => c.getAttribute('data-code'));
    box.querySelector('#ctm-chips').innerHTML = codes.map(c => `<span class="chip on" data-code="${c}" style="cursor:pointer">${c} ✕</span>`).join('');
  };
  box.querySelector('#ctm-add').addEventListener('click', () => {
    const inp = box.querySelector('#ctm-new-code');
    const v = (inp.value || '').trim();
    if (!v) return;
    const exists = Array.from(box.querySelectorAll('#ctm-chips .chip')).some(c => c.getAttribute('data-code') === v);
    if (exists) { inp.value = ''; return; }
    const span = document.createElement('span');
    span.className = 'chip on';
    span.setAttribute('data-code', v);
    span.style.cursor = 'pointer';
    span.textContent = v + ' ✕';
    box.querySelector('#ctm-chips').appendChild(span);
    inp.value = '';
  });
  box.querySelector('#ctm-chips').addEventListener('click', (ev) => {
    const c = ev.target.closest('.chip[data-code]');
    if (c) c.remove();
  });
  box.querySelector('#ctm-cancel').addEventListener('click', () => bg.remove());
  box.querySelector('#ctm-save').addEventListener('click', async () => {
    const name = box.querySelector('#ctm-name').value.trim();
    const note = box.querySelector('#ctm-note').value.trim();
    const codes = Array.from(box.querySelectorAll('#ctm-chips .chip')).map(c => c.getAttribute('data-code'));
    if (!name) { alert('이름 필수'); return; }
    const payload = { name, color_codes: codes, note };
    if (id) payload.id = parseInt(id);
    const res = await apiPost('/api/templates/color', payload);
    if (res.ok) { flash('저장 완료'); bg.remove(); setTimeout(() => location.reload(), 500); }
    else flash('실패: ' + (res.error || ''), 'err');
  });
}

// ----- 색상 사전 모달 -----
async function openColorDictModal(code) {
  let initial = { color_code: '', variants: [], note: '' };
  if (code) {
    const r = await fetch(`/api/dict/color/${encodeURIComponent(code)}`);
    const j = await r.json();
    if (!j.ok) { alert('불러오기 실패: ' + (j.error || '')); return; }
    initial = j.item || initial;
  }
  const variantsHtml = (initial.variants || []).map(v =>
    `<span class="chip on" data-v="${v}" style="cursor:pointer">${v} ✕</span>`
  ).join('');
  const box = _modalBox(
    code ? `🎨 색상 사전 편집 — ${code}` : '🎨 새 색상 사전 항목',
    `
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">표준 색상명 (예: 블랙)</label>
      <input id="cdm-code" type="text" value="${initial.color_code || ''}"
             style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px">
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">변형 텍스트 (사이트 표기 매칭용 — 예: 블랙, Black, BK, 검정)</label>
      <div id="cdm-chips" class="chip-row" style="margin-bottom:8px">${variantsHtml}</div>
      <div style="display:flex;gap:6px">
        <input id="cdm-new-v" type="text" placeholder="변형 텍스트 입력 후 +"
               style="flex:1;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
        <button class="btn" id="cdm-add">+ 추가</button>
      </div>
    </div>
    <div>
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">메모 (선택)</label>
      <input id="cdm-note" type="text" value="${initial.note || ''}"
             style="width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
    </div>
    `,
    `<button class="btn" id="cdm-cancel">취소</button>
     <button class="btn btn-primary" id="cdm-save">저장</button>`
  );
  const bg = _modalBg(box);
  box.querySelector('#cdm-add').addEventListener('click', () => {
    const inp = box.querySelector('#cdm-new-v');
    const v = (inp.value || '').trim();
    if (!v) return;
    const exists = Array.from(box.querySelectorAll('#cdm-chips .chip')).some(c => c.getAttribute('data-v') === v);
    if (exists) { inp.value = ''; return; }
    const span = document.createElement('span');
    span.className = 'chip on';
    span.setAttribute('data-v', v);
    span.style.cursor = 'pointer';
    span.textContent = v + ' ✕';
    box.querySelector('#cdm-chips').appendChild(span);
    inp.value = '';
  });
  box.querySelector('#cdm-chips').addEventListener('click', (ev) => {
    const c = ev.target.closest('.chip[data-v]');
    if (c) c.remove();
  });
  box.querySelector('#cdm-cancel').addEventListener('click', () => bg.remove());
  box.querySelector('#cdm-save').addEventListener('click', async () => {
    const newCode = box.querySelector('#cdm-code').value.trim();
    const note = box.querySelector('#cdm-note').value.trim();
    const variants = Array.from(box.querySelectorAll('#cdm-chips .chip')).map(c => c.getAttribute('data-v'));
    if (!newCode) { alert('표준 색상명 필수'); return; }
    const payload = { color_code: newCode, variants, note };
    if (code) payload.original_code = code;
    const res = await apiPost('/api/dict/color', payload);
    if (res.ok) { flash('저장 완료'); bg.remove(); setTimeout(() => location.reload(), 500); }
    else flash('실패: ' + (res.error || ''), 'err');
  });
}

// ----- 콤보(색상·사이즈 조합) 모달 -----
async function openComboModal(cid) {
  const code = currentBundleCode();
  let initial = { name: '', colors: [], sizes: [] };
  if (cid) {
    const r = await fetch(`/api/bundles/${encodeURIComponent(code)}/combos/${cid}`);
    const j = await r.json();
    if (!j.ok) { alert('불러오기 실패: ' + (j.error || '')); return; }
    initial = j.combo || initial;
  }
  // 색상·사이즈 후보 — 모음전 적용 템플릿 chip 가져오기 (백엔드 신규 endpoint)
  let colorOptions = [], sizeOptions = [];
  try {
    const sg = await apiGet(`/api/bundles/${encodeURIComponent(code)}/template-suggestions`);
    if (sg.ok) { colorOptions = sg.colors || []; sizeOptions = sg.sizes || []; }
  } catch (e) {}
  colorOptions = Array.from(new Set(colorOptions));
  sizeOptions = Array.from(new Set(sizeOptions));

  const colorChips = (initial.colors || []).map(c =>
    `<span class="chip on" data-c="${c}" style="cursor:pointer">${c} ✕</span>`).join('');
  const sizeChips = (initial.sizes || []).map(s =>
    `<span class="chip on" data-s="${s}" style="cursor:pointer">${s} ✕</span>`).join('');
  const colorSuggest = colorOptions.length
    ? colorOptions.filter(c => !(initial.colors || []).includes(c))
        .map(c => `<span class="chip" data-suggest="color" data-v="${c}" style="cursor:pointer">+ ${c}</span>`).join('')
    : '<span style="font-size:12px;color:#888">색상 템플릿 적용 시 추천 표시 (지금은 직접 입력)</span>';
  const sizeSuggest = sizeOptions.length
    ? sizeOptions.filter(s => !(initial.sizes || []).includes(s))
        .map(s => `<span class="chip" data-suggest="size" data-v="${s}" style="cursor:pointer">+ ${s}</span>`).join('')
    : '<span style="font-size:12px;color:#888">사이즈 템플릿 적용 시 추천 표시 (지금은 직접 입력)</span>';

  const box = _modalBox(
    cid ? '🧩 조합 편집' : '🧩 새 조합 추가',
    `
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">조합 이름 (선택)</label>
      <input id="cmb-name" type="text" value="${initial.name || ''}"
             placeholder="예: 메인 조합, 신상 조합"
             style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px">
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">🎨 색상 (선택된 색상은 ✕ 클릭 = 제거)</label>
      <div id="cmb-colors" class="chip-row" style="margin-bottom:8px;min-height:30px">${colorChips}</div>
      ${colorOptions.length ? `<div style="font-size:12px;color:#666;margin-bottom:4px">템플릿 추천:</div><div class="chip-row" id="cmb-color-suggest" style="margin-bottom:8px">${colorSuggest}</div>` : ''}
      <div style="display:flex;gap:6px">
        <input id="cmb-new-color" type="text" placeholder="직접 색상 입력 (예: 블랙)"
               style="flex:1;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
        <button class="btn" id="cmb-add-color">+ 추가</button>
      </div>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">📐 사이즈 (선택된 사이즈는 ✕ 클릭 = 제거)</label>
      <div id="cmb-sizes" class="chip-row" style="margin-bottom:8px;min-height:30px">${sizeChips}</div>
      <div style="font-size:12px;color:#666;margin-bottom:4px">템플릿 추천:</div>
      <div class="chip-row" id="cmb-size-suggest" style="margin-bottom:8px">${sizeSuggest}</div>
      <div style="display:flex;gap:6px">
        <input id="cmb-new-size" type="text" placeholder="직접 사이즈 입력 (예: 240)"
               style="flex:1;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
        <button class="btn" id="cmb-add-size">+ 추가</button>
      </div>
    </div>
    <div style="font-size:12px;color:#666;background:#f7f9fc;padding:10px;border-radius:6px">
      💡 저장 시 색상×사이즈 cartesian product 로 옵션 매트릭스 자동 생성됩니다.
    </div>
    `,
    `<button class="btn" id="cmb-cancel">취소</button>
     <button class="btn btn-primary" id="cmb-save">저장</button>`
  );
  const bg = _modalBg(box);
  const addChip = (containerId, attr, value) => {
    const container = box.querySelector(containerId);
    if (Array.from(container.querySelectorAll('.chip')).some(c => c.getAttribute(attr) === value)) return;
    const span = document.createElement('span');
    span.className = 'chip on';
    span.setAttribute(attr, value);
    span.style.cursor = 'pointer';
    span.textContent = value + ' ✕';
    container.appendChild(span);
  };
  box.querySelector('#cmb-add-color').addEventListener('click', () => {
    const inp = box.querySelector('#cmb-new-color');
    const v = (inp.value || '').trim();
    if (v) { addChip('#cmb-colors', 'data-c', v); inp.value = ''; }
  });
  box.querySelector('#cmb-add-size').addEventListener('click', () => {
    const inp = box.querySelector('#cmb-new-size');
    const v = (inp.value || '').trim();
    if (v) { addChip('#cmb-sizes', 'data-s', v); inp.value = ''; }
  });
  box.querySelector('#cmb-colors').addEventListener('click', (ev) => {
    const c = ev.target.closest('.chip[data-c]');
    if (c) c.remove();
  });
  box.querySelector('#cmb-sizes').addEventListener('click', (ev) => {
    const c = ev.target.closest('.chip[data-s]');
    if (c) c.remove();
  });
  const sugC = box.querySelector('#cmb-color-suggest');
  if (sugC) sugC.addEventListener('click', (ev) => {
    const s = ev.target.closest('.chip[data-suggest="color"]');
    if (s) { addChip('#cmb-colors', 'data-c', s.getAttribute('data-v')); s.remove(); }
  });
  const sugS = box.querySelector('#cmb-size-suggest');
  if (sugS) sugS.addEventListener('click', (ev) => {
    const s = ev.target.closest('.chip[data-suggest="size"]');
    if (s) { addChip('#cmb-sizes', 'data-s', s.getAttribute('data-v')); s.remove(); }
  });
  box.querySelector('#cmb-cancel').addEventListener('click', () => bg.remove());
  box.querySelector('#cmb-save').addEventListener('click', async () => {
    const name = box.querySelector('#cmb-name').value.trim();
    const colors = Array.from(box.querySelectorAll('#cmb-colors .chip')).map(c => c.getAttribute('data-c'));
    const sizes = Array.from(box.querySelectorAll('#cmb-sizes .chip')).map(c => c.getAttribute('data-s'));
    if (colors.length === 0 || sizes.length === 0) { alert('색상·사이즈 각 1개 이상 필요'); return; }
    const payload = { name, colors, sizes };
    if (cid) payload.id = parseInt(cid);
    const res = await apiPost(`/api/bundles/${encodeURIComponent(code)}/combos`, payload);
    if (res.ok) { flash(`저장 완료 (옵션 ${res.options_created || 0}개 신규 생성)`); bg.remove(); setTimeout(() => location.reload(), 800); }
    else flash('실패: ' + (res.error || ''), 'err');
  });
}

// ----- 스스 옵션 매칭 모달 ([Phase 4] 미매칭 3단: 추천후보·검색·직접입력) -----
function openSsMatchingModal(code, syncResult, market) {
  const mkt = market || syncResult.market || 'smartstore';
  const isCp = mkt === 'coupang';
  const optIdKey = isCp ? 'coupang_option_id' : 'naver_option_id';
  const matches = syncResult.matches || [];
  const externalOptions = syncResult.external_options || [];
  const auto = matches.filter(m => m.confidence === 'auto');
  const fuzzy = matches.filter(m => m.confidence === 'fuzzy');
  const failed = matches.filter(m => m.confidence === 'failed');
  const esc = _sdEsc;

  // 색상별 일괄 적용용 그룹화 (failed + fuzzy)
  const colorGroups = {};
  [...fuzzy, ...failed].forEach(m => {
    const key = m.color_code;
    if (!colorGroups[key]) colorGroups[key] = { rows: [], externalColors: new Set() };
    colorGroups[key].rows.push(m);
    (m.candidates || []).forEach(c => {
      const ec = (c.name || '').split('/')[0].trim();
      if (ec) colorGroups[key].externalColors.add(ec);
    });
  });
  const groupsWithBulk = Object.entries(colorGroups).filter(([_, g]) => g.rows.length >= 2);

  const renderRow = (m) => {
    const left = `<td style="font-weight:600">${esc(m.color_code)} / ${esc(m.size_code)}</td>`;
    if (m.confidence === 'auto') {
      return `<tr style="background:#f0fdf4">${left}
        <td>🟢 자동 매칭</td>
        <td><strong>${esc(m.matched_external_name || '')}</strong> <span style="font-size:11px;color:#666">(${m.matched_option_id})</span></td>
        <td>—</td></tr>`;
    }
    // [Phase 4] 미매칭 — 3단 드롭다운 (추천후보 / 검색 / 직접입력)
    const cands = m.candidates || [];
    const candOpts = cands.map(c =>
      `<option value="cand:${c.option_id}">${esc(c.name)} · 재고 ${c.stock} · ID ${c.option_id}</option>`).join('');
    const bg = m.confidence === 'fuzzy' ? '#fefce8' : '#fef2f2';
    const emoji = m.confidence === 'fuzzy' ? '🟡' : '🔴';
    const sku = esc(m.canonical_sku);
    return `<tr style="background:${bg}" data-sku="${sku}">${left}
      <td>${emoji} ${m.confidence === 'fuzzy' ? '확인 필요' : '매칭 실패'}</td>
      <td>
        <div class="ssm-picker" data-sku="${sku}" data-optid="">
          <select class="field-input ssm-mode" style="padding:6px;font-size:12px;width:100%">
            <option value="">— 선택 —</option>
            ${cands.length ? `<optgroup label="추천 후보">${candOpts}</optgroup>` : ''}
            <option value="__search__">🔍 전체 마켓 옵션에서 검색…</option>
            <option value="__direct__">✏️ 옵션 ID 직접 입력…</option>
          </select>
          <div class="ssm-search-box" style="display:none;margin-top:5px">
            <input class="field-input ssm-search" placeholder="마켓 옵션명 검색 (예: 블랙)" style="padding:6px;font-size:12px;width:100%">
            <select class="field-input ssm-search-result" size="5" style="display:none;padding:4px;font-size:12px;width:100%;margin-top:4px"></select>
          </div>
          <div class="ssm-direct-box" style="display:none;margin-top:5px">
            <input class="field-input ssm-direct" type="number" placeholder="마켓 옵션 ID 숫자 직접 입력" style="padding:6px;font-size:12px;width:100%">
          </div>
          <div class="ssm-chosen" style="font-size:11px;color:#16a34a;font-weight:700;margin-top:3px"></div>
        </div>
      </td>
      <td style="font-size:11px;color:#666">${esc(m.reason || '')}</td></tr>`;
  };

  const summary = `
    <div style="margin-bottom:14px;font-size:13px">
      <strong>${esc(syncResult.product_name || '상품')}</strong>
      (originProductNo: ${syncResult.origin_product_no})<br>
      외부 옵션 ${syncResult.external_total}개 / 우리 옵션 ${syncResult.total}개<br>
      🟢 자동 ${auto.length}  🟡 확인 필요 ${fuzzy.length}  🔴 실패 ${failed.length}
    </div>`;

  const tableRows = [...auto, ...fuzzy, ...failed].map(renderRow).join('');

  const bulkPanel = groupsWithBulk.length === 0 ? '' : `
    <div style="margin-bottom:14px;padding:12px;background:#f8f9fa;border-radius:8px;border:1px solid #ddd">
      <div style="font-size:13px;font-weight:600;margin-bottom:8px">🎯 색상별 일괄 적용 (사이즈만 다른 경우)</div>
      ${groupsWithBulk.map(([color, g]) => `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:12px">
          <span style="min-width:120px;font-weight:600">${esc(color)}</span>
          <span style="color:#666;min-width:70px">${g.rows.length}개 사이즈</span>
          <select class="field-input ssm-bulk" data-color="${esc(color)}" style="flex:1;padding:6px;font-size:12px">
            <option value="">— 외부 색상 선택 —</option>
            ${[...g.externalColors].map(ec => `<option value="${esc(ec)}">${esc(ec)}</option>`).join('')}
          </select>
        </div>
      `).join('')}
      <div style="font-size:11px;color:#666;margin-top:6px">💡 외부 색상을 선택하면 같은 색상의 모든 사이즈가 자동으로 채워져요.</div>
    </div>`;

  const box = _modalBox(
    isCp ? '📥 쿠팡 옵션 매칭 결과' : '📥 스마트스토어 옵션 매칭 결과',
    summary + bulkPanel + `
    <div style="overflow:auto;max-height:58vh;border:1px solid #ddd;border-radius:8px">
      <table class="opt-table" style="width:100%">
        <thead><tr><th>우리 옵션</th><th>상태</th><th style="min-width:240px">매칭 외부 옵션</th><th>비고</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
    <div style="font-size:12px;color:#666;margin-top:10px">
      💡 🟡·🔴 옵션은 <b>추천 후보</b>에서 고르거나, 없으면 <b>검색</b>·<b>ID 직접 입력</b>으로 지정하세요. 미지정 옵션은 저장 안 됩니다.
    </div>`,
    `<button class="btn" id="ssm-cancel">취소</button>
     <button class="btn btn-primary" id="ssm-apply">전체 매칭 적용</button>`
  );
  const bg = _modalBg(box);

  function setChosen(picker, optId, label) {
    picker.dataset.optid = optId || '';
    picker.querySelector('.ssm-chosen').textContent = optId ? `✓ 선택: ${label}` : '';
  }

  box.addEventListener('change', (e) => {
    if (e.target.classList.contains('ssm-mode')) {
      const picker = e.target.closest('.ssm-picker');
      const v = e.target.value;
      picker.querySelector('.ssm-search-box').style.display = v === '__search__' ? 'block' : 'none';
      picker.querySelector('.ssm-direct-box').style.display = v === '__direct__' ? 'block' : 'none';
      if (v.startsWith('cand:')) {
        setChosen(picker, v.slice(5), e.target.options[e.target.selectedIndex].text);
      } else {
        setChosen(picker, '', '');
      }
    } else if (e.target.classList.contains('ssm-search-result')) {
      const picker = e.target.closest('.ssm-picker');
      if (e.target.value) setChosen(picker, e.target.value, e.target.options[e.target.selectedIndex].text);
    }
  });
  box.addEventListener('input', (e) => {
    if (e.target.classList.contains('ssm-search')) {
      const picker = e.target.closest('.ssm-picker');
      const q = e.target.value.trim().toLowerCase();
      const res = picker.querySelector('.ssm-search-result');
      if (!q) { res.style.display = 'none'; return; }
      const hits = externalOptions.filter(o =>
        (o.name || '').toLowerCase().includes(q) || String(o.option_id).includes(q)).slice(0, 30);
      res.innerHTML = hits.length
        ? hits.map(o => `<option value="${o.option_id}">${esc(o.name)} · 재고 ${o.stock} · ID ${o.option_id}</option>`).join('')
        : '<option value="">검색 결과 없음</option>';
      res.style.display = 'block';
    } else if (e.target.classList.contains('ssm-direct')) {
      const picker = e.target.closest('.ssm-picker');
      const v = e.target.value.trim();
      setChosen(picker, v, v ? `ID ${v} (직접입력)` : '');
    }
  });

  box.querySelectorAll('.ssm-bulk').forEach(bulkSel => {
    bulkSel.addEventListener('change', () => {
      const externalColor = bulkSel.value;
      if (!externalColor) return;
      const color = bulkSel.dataset.color;
      const group = colorGroups[color];
      if (!group) return;
      let applied = 0;
      group.rows.forEach(m => {
        const cand = (m.candidates || []).find(c => {
          const name = (c.name || '').trim();
          return name.startsWith(externalColor + ' /') || name.startsWith(externalColor + '/') || name === externalColor;
        });
        if (cand) {
          const picker = box.querySelector(`.ssm-picker[data-sku="${m.canonical_sku.replace(/"/g, '\\"')}"]`);
          const sel = picker && picker.querySelector('.ssm-mode');
          if (sel) {
            sel.value = `cand:${cand.option_id}`;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
            applied++;
          }
        }
      });
      flash(`${color} → ${externalColor}: ${applied}/${group.rows.length}개 자동 선택`);
    });
  });
  box.querySelector('#ssm-cancel').addEventListener('click', () => bg.remove());
  box.querySelector('#ssm-apply').addEventListener('click', async () => {
    const finalMatches = [];
    auto.forEach(m => finalMatches.push({
      canonical_sku: m.canonical_sku, [optIdKey]: m.matched_option_id,
    }));
    box.querySelectorAll('.ssm-picker').forEach(p => {
      const id = p.dataset.optid;
      if (id && /^\d+$/.test(id)) {
        finalMatches.push({ canonical_sku: p.dataset.sku, [optIdKey]: parseInt(id, 10) });
      }
    });
    if (finalMatches.length === 0) { alert('매칭할 옵션이 없어요.'); return; }
    const r = await apiPost(`/api/bundles/${encodeURIComponent(code)}/apply-${isCp ? 'cp' : 'ss'}-matching`,
                            { matches: finalMatches });
    if (r.ok) {
      flash(`${r.updated}개 옵션 ID 저장 완료`);
      bg.remove();
      setTimeout(() => location.reload(), 800);
    } else flash('실패: ' + (r.error || ''), 'err');
  });
}

// ----- §6 마켓 모드 탭 -----
function marketModeTab(mode) {
  document.querySelectorAll('#market-mode-tabs .step-tab').forEach(t => {
    t.classList.toggle('active', t.getAttribute('data-mode') === mode);
  });
  document.querySelectorAll('.market-mode-pane').forEach(p => {
    p.style.display = (p.getAttribute('data-mode') === mode) ? '' : 'none';
  });
}

async function openSizeTplModal(id) {
  let initial = { name: '', category: '신발', size_codes: [], note: '' };
  if (id) {
    const r = await fetch(`/api/templates/size/${id}`);
    const j = await r.json();
    if (!j.ok) { alert('불러오기 실패: ' + (j.error || '')); return; }
    initial = j.template || initial;
  }
  const codesHtml = (initial.size_codes || []).map(c => `<span class="chip on" data-code="${c}" style="cursor:pointer">${c} ✕</span>`).join('');
  const cats = ['신발', '의류', '가방'];
  const catOpts = cats.map(c => `<option value="${c}" ${c === initial.category ? 'selected' : ''}>${c}</option>`).join('');
  const box = _modalBox(
    id ? `📐 사이즈 템플릿 편집 (id=${id})` : '📐 새 사이즈 템플릿',
    `
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">이름</label>
      <input id="stm-name" type="text" value="${initial.name || ''}"
             style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px">
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">카테고리</label>
      <select id="stm-cat" style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px">${catOpts}</select>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">사이즈 코드 (칩 클릭 = 삭제)</label>
      <div id="stm-chips" class="chip-row" style="margin-bottom:8px">${codesHtml}</div>
      <div style="display:flex;gap:6px">
        <input id="stm-new-code" type="text" placeholder="230 / 240 / 250 ..."
               style="flex:1;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
        <button class="btn" id="stm-add">+ 추가</button>
      </div>
    </div>
    <div>
      <label style="display:block;font-size:13px;color:#555;margin-bottom:4px">메모 (선택)</label>
      <input id="stm-note" type="text" value="${initial.note || ''}"
             style="width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px">
    </div>
    `,
    `<button class="btn" id="stm-cancel">취소</button>
     <button class="btn btn-primary" id="stm-save">저장</button>`
  );
  const bg = _modalBg(box);
  box.querySelector('#stm-add').addEventListener('click', () => {
    const inp = box.querySelector('#stm-new-code');
    const v = (inp.value || '').trim();
    if (!v) return;
    const exists = Array.from(box.querySelectorAll('#stm-chips .chip')).some(c => c.getAttribute('data-code') === v);
    if (exists) { inp.value = ''; return; }
    const span = document.createElement('span');
    span.className = 'chip on';
    span.setAttribute('data-code', v);
    span.style.cursor = 'pointer';
    span.textContent = v + ' ✕';
    box.querySelector('#stm-chips').appendChild(span);
    inp.value = '';
  });
  box.querySelector('#stm-chips').addEventListener('click', (ev) => {
    const c = ev.target.closest('.chip[data-code]');
    if (c) c.remove();
  });
  box.querySelector('#stm-cancel').addEventListener('click', () => bg.remove());
  box.querySelector('#stm-save').addEventListener('click', async () => {
    const name = box.querySelector('#stm-name').value.trim();
    const category = box.querySelector('#stm-cat').value;
    const note = box.querySelector('#stm-note').value.trim();
    const codes = Array.from(box.querySelectorAll('#stm-chips .chip')).map(c => c.getAttribute('data-code'));
    if (!name) { alert('이름 필수'); return; }
    const payload = { name, category, size_codes: codes, note };
    if (id) payload.id = parseInt(id);
    const res = await apiPost('/api/templates/size', payload);
    if (res.ok) { flash('저장 완료'); bg.remove(); setTimeout(() => location.reload(), 500); }
    else flash('실패: ' + (res.error || ''), 'err');
  });
}

// ===== 색상/사이즈 사전 검색 (클라사이드 필터) =====
document.addEventListener('input', (e) => {
  if (e.target.id !== 'color-dict-search') return;
  const q = e.target.value.toLowerCase().trim();
  document.querySelectorAll('.tp[data-pane="2"] table tbody tr').forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
});

// ===== 홈 — 지금 바로 실행 / 일시정지 (overrideable global) =====
window.runFullCycleNow = async function () {
  if (!confirm('지금 바로 풀 사이클을 실행할까요?')) return;
  const res = await apiPost('/api/scheduler/run-now', {});
  flash(res.ok ? '사이클 실행 시작 — 완료 시 알림으로 안내' : ('실패: ' + res.error),
        res.ok ? 'ok' : 'err');
};
window.pauseScheduler = async function () {
  const res = await apiPost('/api/scheduler/pause', {});
  flash(res.ok ? (res.paused ? '일시 정지됨' : '재개됨') : ('실패: ' + res.error),
        res.ok ? 'ok' : 'err');
};

// ===== 모음전 목록 — 툴바 (전체 크롤링 / 업로드 실행 모달) + 카드별 실행 =====
function showActionResult(res, label) {
  if (!res.ok) {
    flash(`${label} 실패: ${res.error || 'unknown'}`, 'err');
    return;
  }
  const r = res.result || {};
  const sources = r.sources || {};
  const markets = r.markets || {};
  const srcParts = Object.entries(sources).map(([k, v]) =>
    `${k}: ${v.ok ? '✓' + (v.items_crawled ? ' ' + v.items_crawled : '') : '✗'}`);
  const mktParts = Object.entries(markets).map(([k, v]) =>
    `${k}: ${v.ok ? `변동${v.uploaded || 0}/스킵${v.skipped || 0}/실패${v.failed || 0}` : '✗'}`);
  const summary = [
    srcParts.length ? `🌐 ${srcParts.join(' · ')}` : '',
    mktParts.length ? `📤 ${mktParts.join(' · ')}` : '',
  ].filter(Boolean).join(' | ') || '완료';
  flash(`${label} 완료 — ${summary}`, 'ok');
}

// 카드/내부 페이지의 모음전 단위 실행 버튼 (data-action="bundle-run-now")
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action="bundle-run-now"]');
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  const code = btn.getAttribute('data-code');
  const phase = btn.getAttribute('data-phase') || 'full';
  if (!code) return;
  const phaseLabel = phase === 'crawl' ? '크롤링' : phase === 'upload' ? '업로드' : '크롤링 + 업로드';
  if (!confirm(`'${code}' ${phaseLabel}을(를) 지금 실행할까요?`)) return;
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="ic">⟳</span> 실행 중...';
  btn.classList.add('running');
  flash(`'${code}' ${phaseLabel} 시작 — 완료 시 결과 표시`, 'ok');
  try {
    // [2026-06-11] 전체 로컬 크롤(A안): 확장 설치 시 6개 소싱처 전부 이 PC(확장)가
    //   보이는 창으로 크롤한다(crawlBundleAll, 적응형 동시성). 서버 자동 크롤은 호출 안 함.
    //   - phase 'crawl' → 로컬 크롤만(서버 run-now 미호출).
    //   - phase 'full'  → 로컬 크롤 완료 후 서버 업로드(run-now phase='upload')만 호출.
    //   - phase 'upload'→ 서버 run-now 그대로(확장 무관).
    //   확장 미설치 → 기존 폴백: 서버 run-now(주어진 phase) + 설치 안내.
    const extInstalled = !!(window.MoumExt && window.MoumExt.installed());
    // [2026-06-11] 버전 게이트: 전부-로컬(crawlBundleAll)은 grabHtml/sysinfo 가 있는
    //   확장 v0.4.0+ 에서만 사용. 구버전(v0.3.x)이 설치돼 있으면 grabHtml 미지원이라
    //   4개 공개 소싱처가 깨지므로 → 서버 run-now 폴백으로 안전 처리(배포-재설치 순서 무관).
    function _verGte(v, min) {
      const a = String(v || '0').split('.').map((n) => parseInt(n, 10) || 0);
      const b = String(min).split('.').map((n) => parseInt(n, 10) || 0);
      for (let i = 0; i < Math.max(a.length, b.length); i++) {
        if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) > (b[i] || 0);
      }
      return true;
    }
    let extV4 = false;
    if (extInstalled && (phase === 'crawl' || phase === 'full')) {
      try { const p = await window.MoumExt.ping(); extV4 = _verGte(p && p.version, '0.4.0'); } catch (_) {}
    }

    if ((phase === 'crawl' || phase === 'full') && extV4) {
      // [2026-06-14] 멀티 모음전 큐 — 이미 크롤 중이면 줄세움(동시 실행 금지),
      //   아니면 즉시 시작. 진행/대기/완료는 우상단 마스터–디테일 위젯에서 확인.
      //   crawlBundleAll 을 직접 await 하지 않고 enqueueCrawl(비동기 러너)로 위임 →
      //   여러 번 눌러도 안전하고 일시중지/중지가 올바르게 걸린다.
      let busy = false;
      try {
        const st = window.MoumExt.getCrawlState && window.MoumExt.getCrawlState();
        busy = !!(st && (st.running || (st.queue && st.queue.length)));
      } catch (_) {}
      try {
        if (window.MoumExt.enqueueCrawl) {
          window.MoumExt.enqueueCrawl(code);
        } else {
          // 구버전 ext_bridge 폴백 — 단일 실행
          window.MoumExt.crawlBundleAll(code).then((r) => {
            if (typeof loadMatrix === 'function') { try { loadMatrix(); } catch (_) {} }
          }).catch(() => {});
        }
      } catch (e) { flash('로컬 크롤 오류: ' + e, 'err'); }
      flash(busy
        ? `'${code}' 크롤 대기열에 추가 — 우상단 위젯에서 진행 확인`
        : `'${code}' 6개 소싱처 로컬 크롤 시작 — 우상단 위젯에서 진행 확인`, 'ok');
      // full 이면 이 모음전 크롤 완료(finish 이벤트) 시 1회 업로드.
      if (phase === 'full') {
        const onFin = (ev) => {
          const dd = ev.detail;
          if (!dd || dd.type !== 'finish' || dd.bundle !== code) return;
          window.removeEventListener('moum-crawl-log', onFin);
          if (dd.stopped) { flash(`'${code}' 크롤 중지됨 — 업로드 생략`, 'warn'); return; }
          apiPost(`/api/bundles/${encodeURIComponent(code)}/run-now`, { phase: 'upload' })
            .then((up) => { if (up && up.ok) flash(`'${code}' 업로드 진행 중 — 우상단 위젯에서 확인`, 'ok'); })
            .catch(() => {});
        };
        window.addEventListener('moum-crawl-log', onFin);
      }
    } else {
      // 확장 미설치(또는 upload 전용) → 기존 서버 run-now 경로
      const res = await apiPost(
        `/api/bundles/${encodeURIComponent(code)}/run-now`, { phase });
      // [2026-06-03] run-now 는 백그라운드 스레드 → 즉시 'running' 반환.
      if (!res.ok) {
        showActionResult(res, `'${code}' ${phaseLabel}`);  // 실패 표시
      } else if (res.accepted || res.status === 'running') {
        flash(`'${code}' ${phaseLabel} 진행 중 — 우상단 진행 위젯에서 실시간 확인`, 'ok');
      } else {
        showActionResult(res, `'${code}' ${phaseLabel}`);  // 동기 완료(레거시)
      }
      if (phase === 'crawl' || phase === 'full') {
        if (!extInstalled) {
          flash('전체 로컬 크롤은 "모음전 크롤러" 확장 필요 — 설치 시 6개 소싱처 모두 이 PC에서 크롤', 'err');
        } else if (!extV4) {
          flash('확장이 구버전이에요 — v0.4.0으로 업데이트하면 6개 소싱처 전부 이 PC에서 크롤됩니다(지금은 서버 크롤).', 'err');
        }
      }
    }

    if (!extV4 && phase === 'crawl') {
      // 백그라운드 크롤 완료 폴링 — page reload 없이 ticker 자동 갱신
      // (run-now 는 background thread, API 는 즉시 반환 → record_end 가
      //  last_crawled_at 업데이트할 때까지 polling)
      const crawlEl = document.querySelector('.b-stat-val[data-kind="crawl"]');
      const initialIso = crawlEl ? (crawlEl.getAttribute('data-iso') || '') : '';
      let polls = 0;
      const maxPolls = 60;  // 3초 × 60 = 3분 max
      const poller = setInterval(async () => {
        polls++;
        if (polls > maxPolls) {
          clearInterval(poller);
          flash(`'${code}' 크롤링 완료 확인 시간초과`, 'err');
          return;
        }
        try {
          const sr = await fetch(`/api/bundles/${encodeURIComponent(code)}/crawl-status`);
          const sj = await sr.json();
          if (sj.ok && sj.last_crawled_at && sj.last_crawled_at !== initialIso) {
            if (typeof window.setLastCrawled === 'function') {
              window.setLastCrawled(sj.last_crawled_at);
            }
            if (typeof loadMatrix === 'function') {
              try { loadMatrix(); } catch(_) {}
            }
            flash(`'${code}' 크롤링 완료 — 데이터 갱신됨`, 'ok');
            clearInterval(poller);
          }
        } catch(_) {}
      }, 3000);
    }
  } catch (err) {
    flash(`${phaseLabel} 호출 실패: ${err}`, 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
    btn.classList.remove('running');
  }
});

// [v3] 모음전 그룹 해체 (cluster_size>=2 카드 전용 버튼)
window.dissolveBundleGroup = async function (btn) {
  const gid = btn.getAttribute('data-group-id');
  const gname = btn.getAttribute('data-group-name') || '(이름없음)';
  const members = btn.getAttribute('data-cluster-models') || '';
  if (!gid) { alert('group_id 누락'); return; }
  const msg = `🔓 '${gname}' 그룹을 해체할까요?\n\n` +
              `포함 모델: ${members}\n\n` +
              `→ 각 모델은 자신만의 단독 모음전으로 분리됩니다.\n` +
              `→ 가격·재고·소싱처 URL 데이터는 보존됩니다 (그룹 연결만 끊음).\n\n` +
              `📌 기존 마켓 상품(스마트스토어·쿠팡)은 그대로 유지됩니다.\n` +
              `   분리/해제는 정보 수집 단위 변경이며,\n` +
              `   분리된 그룹의 신규 등록은 별도로 진행됩니다.`;
  if (!confirm(msg)) return;
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '⟳ 해체 중...';
  try {
    const res = await apiPost(`/api/bundle-groups/${gid}/dissolve`, {});
    if (res.ok) {
      flash(`그룹 해체 완료 — ${(res.moved || []).length}개 모델 분리됨`, 'ok');
      setTimeout(() => window.location.reload(), 1200);
    } else {
      flash(`해체 실패: ${res.error || 'unknown'}`, 'err');
      btn.disabled = false; btn.innerHTML = original;
    }
  } catch (err) {
    flash(`해체 호출 실패: ${err}`, 'err');
    btn.disabled = false; btn.innerHTML = original;
  }
};

// [v3] 모델 1개를 그룹에서 분리 (matrix 페이지에서 사용)
window.removeModelFromGroup = async function (btn) {
  const gid = btn.getAttribute('data-group-id');
  const mc = btn.getAttribute('data-model-code');
  if (!gid || !mc) { alert('group_id 또는 model_code 누락'); return; }
  if (!confirm(`'${mc}' 모델을 이 그룹에서 분리할까요?\n\n` +
               `→ 자신만의 단독 모음전으로 복원됩니다.\n` +
               `→ 가격·재고·소싱처 URL 데이터는 보존됩니다.\n\n` +
               `📌 기존 마켓 상품(스마트스토어·쿠팡)은 그대로 유지됩니다.\n` +
               `   분리는 정보 수집 단위 변경이며, 신규 등록은 별도로 진행됩니다.`)) return;
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '⟳';
  try {
    const res = await apiPost(`/api/bundle-groups/${gid}/remove-model`, { model_code: mc });
    if (res.ok) {
      flash(`'${mc}' 분리 완료 — '${res.restored_group_code}' 단독 그룹으로 복원`, 'ok');
      setTimeout(() => window.location.reload(), 1200);
    } else {
      flash(`분리 실패: ${res.error || 'unknown'}`, 'err');
      btn.disabled = false; btn.innerHTML = original;
    }
  } catch (err) {
    flash(`분리 호출 실패: ${err}`, 'err');
    btn.disabled = false; btn.innerHTML = original;
  }
};

// 툴바 — 전체 크롤링 실행
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action="bulk-crawl"]');
  if (!btn) return;
  e.preventDefault();
  if (!confirm('전체 모음전 크롤링을 실행할까요? (5개 사이트 — 수 분 소요)')) return;
  btn.disabled = true;
  const res = await apiPost('/api/cycle/crawl', {});
  btn.disabled = false;
  if (res && res.server_crawl_disabled) {
    // 크롤=로컬 원칙 — 서버 전체크롤 비활성. 로컬 확장(각 모음전 '실행'/크롤 위젯)이 담당.
    flash(res.message || '서버 크롤은 비활성 — 로컬 확장이 크롤합니다.', 'ok');
  } else if (res.ok) {
    flash('전체 크롤링 시작 — 완료 시 텔레그램·실행 이력으로 결과 안내', 'ok');
  } else {
    flash('전체 크롤링 실패: ' + (res.error || 'unknown'), 'err');
  }
});

// 툴바 — 업로드 실행 모달 열기/닫기/제출
document.addEventListener('click', (e) => {
  const open = e.target.closest('[data-action="open-upload-modal"]');
  if (open) { e.preventDefault(); openModal('upload-modal'); return; }
  const close = e.target.closest('[data-action="close-upload-modal"]');
  if (close) { e.preventDefault(); closeModal('upload-modal'); return; }
});

// 모달 안 마켓 선택 토글
document.addEventListener('click', (e) => {
  const row = e.target.closest('#upload-modal .modal-row');
  if (!row) return;
  const cb = row.querySelector('input[type="checkbox"]');
  if (!cb) return;
  cb.checked = !cb.checked;
  row.classList.toggle('on', cb.checked);
  const check = row.querySelector('.check');
  if (check) check.textContent = cb.checked ? '✓' : '';
});

// 모달 — 업로드 시작 제출
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action="submit-upload-modal"]');
  if (!btn) return;
  e.preventDefault();
  const modal = document.getElementById('upload-modal');
  if (!modal) return;
  const markets = Array.from(modal.querySelectorAll('input[name="market"]:checked'))
    .map(i => i.value);
  if (!markets.length) {
    flash('마켓을 1개 이상 선택해 주세요.', 'err');
    return;
  }
  const modeEl = modal.querySelector('input[name="upload-mode"]:checked');
  const mode = modeEl ? modeEl.value : 'diff';
  btn.disabled = true;
  const res = await apiPost('/api/cycle/upload', { markets, mode });
  btn.disabled = false;
  if (res.ok) {
    flash(`업로드 시작 — 마켓 ${markets.join('·')} / ${mode}`, 'ok');
    closeModal('upload-modal');
  } else {
    flash('업로드 실패: ' + (res.error || 'unknown'), 'err');
  }
});

// 실행 이력 — 행 클릭 시 상세 토글
document.addEventListener('click', (e) => {
  const toggle = e.target.closest('.run-toggle');
  const row = e.target.closest('.run-row');
  if (!toggle && !row) return;
  const trigger = toggle || row;
  const detailId = (toggle && toggle.getAttribute('data-target'))
    || (row && 'run-detail-' + row.getAttribute('data-run-id'));
  if (!detailId) return;
  const detail = document.getElementById(detailId);
  if (!detail) return;
  const open = detail.style.display === 'none' || !detail.style.display;
  detail.style.display = open ? 'table-row' : 'none';
  if (toggle) toggle.classList.toggle('open', open);
});


// ===== 실시간 실행 로그 패널 (모음전 list 페이지 하단 — 크롤 | 업로드 2칼럼) =====
(function () {
  const listCrawl  = document.getElementById('runlog-list-crawl');
  const listUpload = document.getElementById('runlog-list-upload');
  if (!listCrawl || !listUpload) return;
  const emptyCrawl  = document.getElementById('runlog-empty-crawl');
  const emptyUpload = document.getElementById('runlog-empty-upload');
  const countCrawl  = document.getElementById('runlog-running-count-crawl');
  const countUpload = document.getElementById('runlog-running-count-upload');
  const pulseCrawl  = document.getElementById('runlog-pulse-crawl');
  const pulseUpload = document.getElementById('runlog-pulse-upload');

  // 같은 모음전에 대해 빠르게 연타 시 중복 placeholder 방지
  const recentlyTriggered = new Map();  // key: model_code|phase  → ts

  function fmtAgo(iso) {
    if (!iso) return '—';
    const dt = new Date(iso);
    const sec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000));
    if (sec < 60) return sec + '초 전';
    if (sec < 3600) return Math.floor(sec / 60) + '분 전';
    if (sec < 86400) return Math.floor(sec / 3600) + '시간 전';
    return Math.floor(sec / 86400) + '일 전';
  }

  function fmtDur(d) {
    if (d == null) return '—';
    if (d < 60) return d.toFixed(1) + '초';
    return (d / 60).toFixed(1) + '분';
  }

  function phaseLabel(p) {
    return p === 'crawl' ? '🌐 크롤링' : p === 'upload' ? '📤 업로드' : '▶ 전체';
  }

  function statusBadge(s) {
    const t = s === 'running' ? '⏳ 실행 중'
            : s === 'ok' ? '✅ 완료'
            : s === 'partial' ? '⚠ 부분'
            : s === 'failed' ? '❌ 실패' : s;
    return `<span class="status ${s}">${t}</span>`;
  }

  // panelKind: 'crawl' | 'upload' — 어느 패널에서 호출됐는지에 따라 렌더링이 달라짐
  function renderRow(item, panelKind) {
    const isCrawl = panelKind === 'crawl';
    const code = item.is_bulk ? `(전체 ${phaseLabel(item.phase)})` : (item.model_code || '?');
    const cls = ['pg-card', item.status, item.is_bulk ? 'bulk' : ''].filter(Boolean).join(' ');
    const startedAgo = fmtAgo(item.started_at);
    const dur = item.status === 'running' ? '실행 중' : fmtDur(item.duration_sec);

    // 진행률 계산 — 해당 panel 의 sources/markets 만 사용
    const dataMap = isCrawl ? (item.sources || {}) : (item.markets || {});
    const stageEntries = Object.entries(dataMap);
    const total = stageEntries.length || (isCrawl ? 5 : 2);
    const done = stageEntries.filter(([, v]) => v && v.ok).length;
    const failedCount = stageEntries.filter(([, v]) => v && v.error).length;
    let pct;
    if (item.status === 'ok' || item.status === 'partial') pct = 100;
    else if (item.status === 'failed') pct = total ? Math.round((done / total) * 100) : 50;
    else pct = total ? Math.round((done / total) * 100) : 5;  // running

    // 단계 칩 — crawl: 5소싱처, upload: 2마켓
    const orderedKeys = isCrawl
      ? ['lemouton', 'musinsa', 'ssf', 'lotteon', 'ss_lemouton']
      : ['smartstore', 'coupang'];
    const labelMap = {
      lemouton: '르무통', musinsa: '무신사', ssf: 'SSF', lotteon: '롯데온', ss_lemouton: '스스',
      smartstore: '스스', coupang: '쿠팡',
    };
    const stageHtml = orderedKeys.map(k => {
      const v = dataMap[k];
      let cl = '', icon = '';
      if (v && v.ok) { cl = 'done'; icon = '✅'; }
      else if (v && v.error) { cl = 'fail'; icon = '❌'; }
      else if (item.status === 'running') { cl = ''; icon = '⏸'; }
      return `<div class="pg-stage ${cl}">${labelMap[k] || k}${icon ? ' ' + icon : ''}</div>`;
    }).join('');

    // 콘솔 라인 (details 데이터에서 합성)
    const lines = [];
    const startTs = (item.started_at || '').replace('T', ' ').slice(0, 19) || '—';
    lines.push(`<div><span class="ts">[${startTs}]</span> <span class="info">${isCrawl ? 'crawl' : 'upload'} start — ${code}${item.triggered_by && item.triggered_by !== 'manual' ? ' (⚡' + item.triggered_by + ')' : ''}</span></div>`);
    for (const k of orderedKeys) {
      const v = dataMap[k];
      if (!v) continue;
      const lbl = labelMap[k] || k;
      if (v.ok) {
        const detail = isCrawl
          ? (v.items_crawled != null ? `${v.items_crawled} 건` : 'ok')
          : `↑${v.uploaded || 0} ⏭${v.skipped || 0} ✗${v.failed || 0}`;
        lines.push(`<div><span class="ts">[${startTs}]</span> <span class="ok">${lbl}: ${detail}</span></div>`);
      } else if (v.error) {
        lines.push(`<div><span class="ts">[${startTs}]</span> <span class="err">${lbl}: ${linkifyUrls(String(v.error).slice(0, 200))}</span></div>`);
      }
    }
    if (item.status === 'running') {
      lines.push(`<div><span class="cur">진행 중...</span> <span class="pg-pulse-dot" style="margin-left:4px"></span></div>`);
    } else if (item.status === 'failed' && item.error) {
      lines.push(`<div><span class="err">FAILED — ${linkifyUrls(item.error.slice(0, 200))}</span></div>`);
    } else if (item.status === 'ok' || item.status === 'partial') {
      const summary = isCrawl
        ? `FINISHED — ${done}/${total} ok · ${dur}`
        : `FINISHED — ${dur}`;
      lines.push(`<div><span class="ok">${summary}</span></div>`);
    }
    const consoleHtml = `<div class="pg-console">${lines.join('')}</div>`;

    // 아이콘
    const iconClass = isCrawl ? '' : 'upload';
    const icon = item.status === 'failed' ? '❌' : (isCrawl ? '🌐' : '📤');
    const iconCls = item.status === 'failed' ? 'failed' : iconClass;

    // sub 라벨
    const subParts = [];
    subParts.push(`🕒 ${startedAgo}`);
    if (item.triggered_by && item.triggered_by !== 'manual') subParts.push(`⚡ ${item.triggered_by}`);
    if (item.is_bulk && item.phase === 'full') subParts.push('phase=full');

    // 추가 펼침 영역
    const extraKv = [
      ['실행 ID', '#' + item.id],
      ['대상', item.is_bulk ? '🌐 전체 모음전' : '📦 ' + item.model_code],
      ['단계', phaseLabel(item.phase)],
      ['트리거', item.triggered_by || 'manual'],
      ['시작', item.started_at || '—'],
      ['종료', item.ended_at || '— (실행 중)'],
      ['소요', dur],
    ].map(([k, v]) => `<span class="k">${k}</span><span>${v}</span>`).join('');
    const extraHtml = `<div class="pg-extra"><div class="kv">${extraKv}</div></div>`;

    // 실패 시 재시도 버튼
    const retryBtn = item.status === 'failed' && !item.is_bulk
      ? `<button type="button" class="pg-retry" data-action="bundle-run-now" data-code="${item.model_code}" data-phase="${item.phase}">↻ 재시도</button>`
      : '';

    return `
      <div class="${cls}" data-run-id="${item.id}" data-status="${item.status}" data-key="${item.model_code || '*'}|${item.phase}">
        <div class="pg-top">
          <div class="pg-icon ${iconCls}">${icon}</div>
          <div class="pg-name-wrap">
            <div class="pg-name" title="${code}">${code}</div>
            <div class="pg-sub">${subParts.join(' · ')}</div>
          </div>
          <span class="pg-status ${item.status}">${item.status === 'running' ? '⏳ 실행 중' : item.status === 'ok' ? '✅ 완료' : item.status === 'partial' ? '⚠ 부분' : '❌ 실패'}</span>
        </div>
        <div class="pg-progress ${item.status === 'failed' ? 'failed' : ''}">
          <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
          <div class="lbl"><span>${done} / ${total} ${isCrawl ? '소싱처' : '마켓'}${failedCount ? ' · ❌ ' + failedCount : ''}</span><span>${pct}%</span></div>
        </div>
        <div class="pg-stages">${stageHtml}</div>
        ${consoleHtml}
        ${extraHtml}
        ${retryBtn}
      </div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // [2026-05-27] 실행 로그 에러 메시지 안의 URL 을 자동 linkify — 발견된 URL 뒤에 ↗ 추가
  function linkifyUrls(s) {
    const esc = escapeHtml(s);
    return esc.replace(/(https?:\/\/[^\s<>'"]+)/g, (m) => {
      const safe = m.replace(/"/g, '&quot;');
      return `${m} <a class="url-go dark" href="${safe}" target="_blank" rel="noopener noreferrer" title="새 탭에서 열기">↗</a>`;
    });
  }

  // 펼침 상태를 토글 후에도 보존
  let expandedIds = new Set();

  function isCrawl(item) { return item.phase === 'crawl' || item.phase === 'full'; }
  function isUpload(item) { return item.phase === 'upload' || item.phase === 'full'; }

  function renderInto(listEl, emptyEl, countEl, pulseEl, items, panelKind) {
    const runningCount = items.filter(i => i.status === 'running').length;
    if (countEl) countEl.textContent = `${runningCount} 실행중`;
    if (pulseEl) pulseEl.style.display = runningCount ? 'inline-block' : 'none';

    // placeholder 정리:
    //  (a) 서버에 같은 key + 시작시각이 placeholder 시각 이후인 record 가 있으면 → 제거 (running/완료 모두)
    //  (b) placeholder 가 12초 넘게 살아있으면 → 강제 제거 (서버 record_start 가 늦거나 실패한 경우)
    // Python record_start 가 UTC isoformat 을 'Z' 없이 저장하므로, JS Date.parse 가 로컬로 해석하지 않게 보정
    function parseUtc(s) {
      if (!s) return 0;
      if (/[zZ]|[+-]\d\d:?\d\d$/.test(s)) return Date.parse(s) || 0;
      return Date.parse(s + 'Z') || 0;
    }
    const serverByKey = new Map();
    for (const i of items) {
      const k = `${i.model_code || '*'}|${i.phase}`;
      const ts = parseUtc(i.started_at);
      const cur = serverByKey.get(k);
      if (!cur || ts > cur) serverByKey.set(k, ts);
    }
    listEl.querySelectorAll('.pg-card.placeholder').forEach(ph => {
      const k = ph.getAttribute('data-key');
      const phTs = parseInt((ph.getAttribute('data-run-id') || '').replace('_ph_', ''), 10) || 0;
      const serverTs = serverByKey.get(k);
      if (serverTs && serverTs >= phTs - 2000) { ph.remove(); return; }
      if (Date.now() - phTs > 12000) ph.remove();
    });

    if (!items.length) {
      if (emptyEl) emptyEl.style.display = 'block';
      listEl.querySelectorAll('.pg-card:not(.placeholder)').forEach(r => r.remove());
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    const html = items.map(it => renderRow(it, panelKind)).join('');
    const phs = Array.from(listEl.querySelectorAll('.pg-card.placeholder'))
      .map(el => el.outerHTML).join('');
    listEl.innerHTML = phs + html;

    listEl.querySelectorAll('.pg-card').forEach(r => {
      const id = r.getAttribute('data-run-id');
      if (id && expandedIds.has(id)) r.classList.add('expanded');
    });
  }

  async function refresh() {
    let res;
    try { res = await apiGet('/api/runs/active?limit=50'); }
    catch (e) { return; }
    if (!res || !res.ok) return;
    const items = res.items || [];
    renderInto(listCrawl,  emptyCrawl,  countCrawl,  pulseCrawl,  items.filter(isCrawl),  'crawl');
    renderInto(listUpload, emptyUpload, countUpload, pulseUpload, items.filter(isUpload), 'upload');
  }

  // 카드 클릭 → 펼침/접힘 (콘솔 확장 + 메타 노출)
  function bindRowClick(listEl) {
    listEl.addEventListener('click', (e) => {
      const row = e.target.closest('.pg-card');
      if (!row) return;
      if (e.target.closest('a, button')) return;
      row.classList.toggle('expanded');
      const id = row.getAttribute('data-run-id');
      if (id) {
        if (row.classList.contains('expanded')) expandedIds.add(id);
        else expandedIds.delete(id);
      }
    });
  }
  bindRowClick(listCrawl);
  bindRowClick(listUpload);

  // 새로고침 버튼 — 양쪽 패널 헤더에 공통 클래스 .runlog-refresh
  document.querySelectorAll('.runlog-refresh').forEach(btn => {
    btn.addEventListener('click', () => refresh());
  });

  // 즉시 placeholder 추가 — 백엔드 record_start 사이의 race 메꿔주기 위한 낙관적 UI
  function addPlaceholder({ model_code, phase, is_bulk }) {
    const key = `${model_code || '*'}|${phase}`;
    const now = Date.now();
    if (recentlyTriggered.get(key) && (now - recentlyTriggered.get(key)) < 1500) return;
    recentlyTriggered.set(key, now);
    const id = '_ph_' + now;
    const code = is_bulk ? `(전체 ${phaseLabel(phase)})` : (model_code || '?');
    function makeHtml(panelKind) {
      const isCrawl = panelKind === 'crawl';
      const icon = isCrawl ? '🌐' : '📤';
      return `
        <div class="pg-card running placeholder ${is_bulk ? 'bulk' : ''}" data-run-id="${id}" data-key="${key}">
          <div class="pg-top">
            <div class="pg-icon ${isCrawl ? '' : 'upload'}">${icon}</div>
            <div class="pg-name-wrap">
              <div class="pg-name" title="${code}">${code}</div>
              <div class="pg-sub">🕒 방금 · 시작 중...</div>
            </div>
            <span class="pg-status running">⏳ 시작 중</span>
          </div>
          <div class="pg-progress"><div class="bar"><div class="fill" style="width:5%"></div></div><div class="lbl"><span>준비 중...</span><span>5%</span></div></div>
          <div class="pg-console"><div><span class="cur">실행 시작 중...</span> <span class="pg-pulse-dot" style="margin-left:4px"></span></div></div>
        </div>`;
    }
    if (phase === 'crawl' || phase === 'full') {
      if (emptyCrawl) emptyCrawl.style.display = 'none';
      listCrawl.insertAdjacentHTML('afterbegin', makeHtml('crawl'));
    }
    if (phase === 'upload' || phase === 'full') {
      if (emptyUpload) emptyUpload.style.display = 'none';
      listUpload.insertAdjacentHTML('afterbegin', makeHtml('upload'));
    }
  }

  // 실행 트리거 hook — 기존 핸들러보다 먼저 placeholder 띄움
  document.addEventListener('click', (e) => {
    const runBtn = e.target.closest('[data-action="bundle-run-now"]');
    if (runBtn) {
      addPlaceholder({
        model_code: runBtn.getAttribute('data-code'),
        phase: runBtn.getAttribute('data-phase') || 'full',
        is_bulk: false,
      });
      setTimeout(refresh, 600);
      return;
    }
    const bulkCrawl = e.target.closest('[data-action="bulk-crawl"]');
    if (bulkCrawl) {
      addPlaceholder({ model_code: null, phase: 'crawl', is_bulk: true });
      setTimeout(refresh, 600);
      return;
    }
    const bulkUp = e.target.closest('[data-action="submit-upload-modal"]');
    if (bulkUp) {
      addPlaceholder({ model_code: null, phase: 'upload', is_bulk: true });
      setTimeout(refresh, 600);
      return;
    }
  }, true);  // capture phase — 기존 핸들러가 reload 하기 전에 실행

  // 폴링 — 실행 중이면 빠르게(2s), 없으면 느리게(8s)
  let pollMs = 8000;
  function tick() {
    refresh().finally(() => {
      const running = document.querySelectorAll('#runlog-section .pg-card.running, #runlog-section .pg-card.placeholder').length;
      pollMs = running > 0 ? 2000 : 8000;
      setTimeout(tick, pollMs);
    });
  }
  tick();
})();

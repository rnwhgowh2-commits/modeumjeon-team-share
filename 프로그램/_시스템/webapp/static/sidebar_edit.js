/* 사이드바 v3 — 호버 ⋮ + 노션 DnD + 이모지/Phosphor 아이콘 풀모달
   Flask 백엔드 연동: GET/PUT /api/sidebar/layout
   2026-05-13 사용자 피드백 반영: 라이트 톤 / 우클릭 즉시 모달 / Phosphor 1248 아이콘 + 색상 */
(function(){
'use strict';

const $ = (s, p) => (p || document).querySelector(s);
const $$ = (s, p) => [...(p || document).querySelectorAll(s)];
const root = $('#sb3-root');
if (!root) return;

const STAGE_COLORS = ['#FF9500','#3182F6','#03C75A','#A855F7','#F04438','#5B8DEF','#FFD166','#6B7684'];
const ICON_COLORS = window.SB3_ICON_COLORS || ['#191F28','#3182F6','#03C75A','#FF9500','#F04438','#A855F7','#5B8DEF','#FFD166'];
let data = JSON.parse(root.dataset.layout);
const badges = JSON.parse(root.dataset.badges || '{}');
const activeKey = root.dataset.active || '';

/* ===== 드래그 리사이즈 (사이드바 폭) ===== */
const SB3_W_KEY = 'sb3_sidebar_width';
const SB3_W_MIN = 200, SB3_W_MAX = 560, SB3_W_DEFAULT = 320;
(function initWidth(){
  const stored = parseInt(localStorage.getItem(SB3_W_KEY) || SB3_W_DEFAULT, 10);
  const w = Math.max(SB3_W_MIN, Math.min(SB3_W_MAX, isNaN(stored) ? SB3_W_DEFAULT : stored));
  root.style.width = w + 'px';
  root.style.position = 'relative';
  const handle = document.createElement('div');
  handle.className = 'sb3-resize-handle';
  handle.title = '드래그하여 사이드바 폭 조절 (' + SB3_W_MIN + '~' + SB3_W_MAX + 'px)';
  root.appendChild(handle);
  let dragging = false, startX = 0, startW = 0;
  handle.addEventListener('mousedown', e => {
    dragging = true;
    startX = e.clientX;
    startW = root.offsetWidth;
    handle.classList.add('dragging');
    document.body.classList.add('sb3-resizing');
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    const newW = Math.max(SB3_W_MIN, Math.min(SB3_W_MAX, startW + dx));
    root.style.width = newW + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.classList.remove('sb3-resizing');
    const w = parseInt(root.style.width, 10);
    if (!isNaN(w)) localStorage.setItem(SB3_W_KEY, w);
  });
  // 더블클릭 = 기본값으로 리셋
  handle.addEventListener('dblclick', () => {
    root.style.width = SB3_W_DEFAULT + 'px';
    localStorage.setItem(SB3_W_KEY, SB3_W_DEFAULT);
  });
})();

/* ===== 영속화 ===== */
let saveTimer = null;
function persist(){
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fetch('/api/sidebar/layout', {
      method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data),
    }).catch(err => console.warn('[sb3] save failed', err));
  }, 400);
}

/* ===== 히스토리 ===== */
const history = [];
let toastTimer = null;
function snapshot(msg){
  history.push({data: JSON.parse(JSON.stringify(data)), msg});
  if (history.length > 20) history.shift();
  showToast(msg);
  persist();
}
function undo(){
  if (!history.length) return;
  const last = history.pop();
  data = last.data;
  render();
  persist();
  hideToast();
}
function showToast(msg){
  $('#sb3-toast-msg').textContent = msg;
  const t = $('#sb3-toast');
  t.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('on'), 5000);
}
function hideToast(){ $('#sb3-toast').classList.remove('on'); }
$('#sb3-toast-undo').addEventListener('click', undo);
$('#sb3-toast-close').addEventListener('click', hideToast);

/* ===== 렌더 ===== */
function escapeHtml(s){ return String(s||'').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'})[c]); }
function badgeFor(key){
  if (!key) return '';
  const v = badges[key];
  if (!v) return '';
  return `<span class="badge${key === 'failed' ? ' alert' : ''}">${v}</span>`;
}
function iconSpanHTML(it, fallbackColor){
  if (it.icon){
    return `<span class="emo pi" data-act="emoji" style="color:${escapeHtml(it.icon_color || fallbackColor || 'currentColor')}"><i class="ph-light ph-${escapeHtml(it.icon)}"></i></span>`;
  }
  const empty = !it.emoji;
  return `<span class="emo${empty?' empty':''}" data-act="emoji">${escapeHtml(it.emoji||'·')}</span>`;
}
function itemHTML(it, parentId){
  const isActive = it.active_key && it.active_key === activeKey;
  return `<div data-url="${escapeHtml(it.url||'#')}" class="sb3-item${isActive?' on':''}" draggable="true" tabindex="0"
    data-type="item" data-id="${escapeHtml(it.id)}" data-parent="${escapeHtml(parentId)}">
    <span class="drag-h" title="잡고 끌어 이동">⠿</span>
    ${iconSpanHTML(it)}
    <span class="nm" data-act="rename">${escapeHtml(it.name)}</span>
    ${badgeFor(it.badge_key)}
    <span class="menu-b" data-act="menu">⋮</span>
  </div>`;
}
function stageHTML(st){
  const items = (st.items || []).map(it => itemHTML(it, st.id)).join('');
  const iconHTML = st.icon
    ? `<span class="st-emo pi" data-act="emoji" style="color:${escapeHtml(st.icon_color || 'currentColor')}"><i class="ph-light ph-${escapeHtml(st.icon)}"></i></span>`
    : `<span class="st-emo${!st.emoji?' empty':''}" data-act="emoji">${escapeHtml(st.emoji||'·')}</span>`;
  return `<div class="sb3-stage${st.collapsed?' collapsed':''}" draggable="true" tabindex="0"
    data-type="stage" data-id="${escapeHtml(st.id)}" data-color="${escapeHtml(st.color)}">
    <span class="st-drag" title="잡고 끌어 카테고리 이동">⠿</span>
    <div class="st-head">
      ${iconHTML}
      <span class="st-nm" data-act="rename">${escapeHtml(st.name)}</span>
      <span class="st-menu" data-act="menu">⋮</span>
      <span class="st-toggle">${st.collapsed?'▶':'▼'}</span>
    </div>
    <div class="st-items" data-drop-zone="${escapeHtml(st.id)}">${items}</div>
    <div class="add-item" data-add-to="${escapeHtml(st.id)}">＋ 항목 추가</div>
  </div>`;
}
function render(){
  $$('.sb3-stage', root).forEach(el => el.remove());
  const stand = $('.sb3-stand', root);
  stand.innerHTML = data.standalone.map(it => itemHTML(it, 'standalone')).join('');
  const addStage = $('#sb3-add-stage');
  addStage.insertAdjacentHTML('beforebegin', data.stages.map(stageHTML).join(''));
  root.dataset.layout = JSON.stringify(data);
  attachAll();
}

/* ===== 이벤트 ===== */
function attachAll(){
  $$('.sb3-item, .sb3-stage', root).forEach(el => {
    el.addEventListener('dragstart', onDragStart);
    el.addEventListener('dragend', onDragEnd);
    el.addEventListener('contextmenu', onContextMenu);
  });
  // div 항목 클릭 → 페이지 이동 (a 태그 대체) — v32 수정: 「어디 클릭해도 탭 이동」 사용자 요청
  $$('.sb3-item', root).forEach(el => {
    let mdX = 0, mdY = 0, mdT = 0;
    el.addEventListener('mousedown', e => {
      mdX = e.clientX; mdY = e.clientY; mdT = Date.now();
    });
    el.addEventListener('mouseup', e => {
      // 명시적 액션 버튼만 무시 — ⋮ menu, v32 picker 의 ✎/🎨 mini 버튼
      if (e.target.closest('[data-act="menu"], .icp-edit-btn, .icp-color-btn')) return;
      // 드래그 의도 (>4px 또는 >300ms) — navigation X (조금 관대)
      const dx = Math.abs(e.clientX - mdX);
      const dy = Math.abs(e.clientY - mdY);
      const dt = Date.now() - mdT;
      if (dx > 4 || dy > 4 || dt > 300) return;
      // 모든 자식 (이름/이모지/배지/드래그핸들) 클릭 시 navigation
      const url = el.dataset.url;
      if (url && url !== '#') window.location.href = url;
    });
  });
  // v32 — 카테고리(stage) 헤더 클릭 시 펼침/접힘 (전체 영역)
  $$('.sb3-stage', root).forEach(stage => {
    const head = stage.querySelector('.st-head');
    if (!head) return;
    head.addEventListener('click', e => {
      if (e.target.closest('[data-act="menu"], [data-act="emoji"], [data-act="rename"], .icp-edit-btn, .icp-color-btn')) return;
      stage.classList.toggle('collapsed');
      const tog = stage.querySelector('.st-toggle');
      if (tog) tog.textContent = stage.classList.contains('collapsed') ? '▶' : '▼';
    });
  });
  $$('[data-drop-zone], .sb3-stand', root).forEach(z => {
    z.addEventListener('dragover', onDragOver);
    z.addEventListener('drop', onDrop);
  });
  root.addEventListener('dragover', onRootDragOver, true);
  $$('[data-act]', root).forEach(el => {
    el.addEventListener('click', e => {
      e.stopPropagation(); e.preventDefault();
      const act = el.dataset.act;
      const host = el.closest('[data-type]');
      if (!host) return;
      if (act === 'emoji') openEmojiModal(host);
      else if (act === 'rename') startInlineEdit(el, host);
      else if (act === 'menu') openDropdown(host, el);
    });
    // 우클릭으로 이모지 = 즉시 모달 (사용자 요청)
    if (el.dataset.act === 'emoji'){
      el.addEventListener('contextmenu', e => {
        e.preventDefault(); e.stopPropagation();
        const host = el.closest('[data-type]');
        if (host) openEmojiModal(host);
      });
    }
  });
  $$('.st-toggle', root).forEach(t => {
    t.addEventListener('click', e => {
      e.stopPropagation(); e.preventDefault();
      const stage = t.closest('.sb3-stage');
      const st = data.stages.find(s => s.id === stage.dataset.id);
      st.collapsed = !st.collapsed;
      stage.classList.toggle('collapsed');
      t.textContent = st.collapsed ? '▶' : '▼';
      persist();
    });
  });
  // 카테고리 헤더 어디 클릭해도 토글 (BoxHero 풍 — 헤더 전체가 클릭 영역)
  $$('.sb3-stage .st-head', root).forEach(h => {
    h.addEventListener('click', e => {
      // 이모지·이름·메뉴 클릭은 각자 핸들러 우선이라 stopPropagation 됨 → 헤더 빈 영역만 토글
      if (e.target.closest('[data-act],.st-toggle')) return;
      const toggle = h.querySelector('.st-toggle');
      if (toggle) toggle.click();
    });
  });
  $$('.add-item', root).forEach(b => {
    b.addEventListener('click', e => {
      e.stopPropagation(); e.preventDefault();
      const stId = b.dataset.addTo;
      const st = data.stages.find(s => s.id === stId);
      st.items.push({id:'i_'+Date.now(), emoji:'', icon:'plus-circle', icon_color:null, name:'새 항목', url:'#', active_key:null, badge_key:null});
      snapshot('"새 항목" 추가됨');
      render();
    });
  });
}

/* ===== DnD ===== */
let dragEl=null, dragType=null;
function onDragStart(e){
  // 핵심 fix: item 의 dragstart 가 부모 stage 로 bubble 되면 dragType 이 stage 로 덮어씌워짐
  e.stopPropagation();
  dragEl = e.currentTarget;
  dragType = dragEl.dataset.type;
  dragEl.classList.add('dragging');
  try {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragEl.dataset.id);
    e.dataTransfer.setDragImage(dragEl, 16, dragEl.offsetHeight / 2);
  } catch(_){}
  console.log('[sb3] dragstart', dragType, dragEl.dataset.id);
}
function onDragEnd(){
  if (dragEl) dragEl.classList.remove('dragging');
  removeDropLine();
  dragEl = null; dragType = null;
}
function onRootDragOver(e){ if (dragEl) e.preventDefault(); }
function onDragOver(e){
  if (!dragEl) return;
  e.preventDefault(); e.stopPropagation();
  e.dataTransfer.dropEffect = 'move';
  if (dragType === 'item'){
    const zone = e.currentTarget;
    const items = $$('[data-type="item"]', zone).filter(x => x !== dragEl);
    if (!items.length){ placeDropLineAtEnd(zone); return; }
    let before = null;
    for (const it of items){
      const r = it.getBoundingClientRect();
      if (e.clientY < r.top + r.height/2){ before = it; break; }
    }
    if (before) placeDropLineBefore(before);
    else placeDropLineAfter(items[items.length-1]);
  } else if (dragType === 'stage'){
    const stages = $$('.sb3-stage', root).filter(x => x !== dragEl);
    let before = null;
    for (const st of stages){
      const r = st.getBoundingClientRect();
      if (e.clientY < r.top + r.height/2){ before = st; break; }
    }
    removeDropLine();
    if (before) placeDropLineBefore(before);
    else if (stages.length) placeDropLineAfter(stages[stages.length-1]);
  }
}
function onDrop(e){
  if (!dragEl) return;
  e.preventDefault(); e.stopPropagation();
  console.log('[sb3] drop', dragType, 'into', e.currentTarget.dataset.dropZone);
  if (dragType === 'stage'){ dropStage(); return; }
  if (dragType !== 'item') return;
  const zone = e.currentTarget;
  const newParent = zone.dataset.dropZone;
  if (!newParent) return;
  const oldParent = dragEl.dataset.parent;
  const id = dragEl.dataset.id;
  let moved;
  if (oldParent === 'standalone'){
    const i = data.standalone.findIndex(it => it.id === id);
    moved = data.standalone.splice(i, 1)[0];
  } else {
    const st = data.stages.find(s => s.id === oldParent);
    const i = st.items.findIndex(it => it.id === id);
    moved = st.items.splice(i, 1)[0];
  }
  const line = $('.sb3-drop-line');
  const target = newParent === 'standalone' ? data.standalone : data.stages.find(s => s.id === newParent).items;
  let idx;
  if (line){
    const b = line.dataset.before, a = line.dataset.after;
    if (b) idx = target.findIndex(it => it.id === b);
    else if (a) idx = target.findIndex(it => it.id === a) + 1;
    else idx = target.length;
  } else idx = target.length;
  target.splice(idx, 0, moved);
  const newName = newParent === 'standalone' ? '독립' : data.stages.find(s => s.id === newParent).name;
  snapshot(`"${moved.name}" → ${newName}`);
  render();
}
function dropStage(){
  const line = $('.sb3-drop-line');
  if (!line) return;
  const fromIdx = data.stages.findIndex(s => s.id === dragEl.dataset.id);
  const moved = data.stages.splice(fromIdx, 1)[0];
  const b = line.dataset.before, a = line.dataset.after;
  let idx;
  if (b) idx = data.stages.findIndex(s => s.id === b);
  else if (a) idx = data.stages.findIndex(s => s.id === a) + 1;
  else idx = data.stages.length;
  data.stages.splice(idx, 0, moved);
  snapshot(`"${moved.name}" 카테고리 이동`);
  render();
}
function placeDropLineBefore(el){ removeDropLine(); const l=document.createElement('div'); l.className='sb3-drop-line'; l.dataset.before=el.dataset.id; el.parentNode.insertBefore(l, el); }
function placeDropLineAfter(el){ removeDropLine(); const l=document.createElement('div'); l.className='sb3-drop-line'; l.dataset.after=el.dataset.id; el.parentNode.insertBefore(l, el.nextSibling); }
function placeDropLineAtEnd(zone){ removeDropLine(); const l=document.createElement('div'); l.className='sb3-drop-line'; zone.appendChild(l); }
function removeDropLine(){ $$('.sb3-drop-line', root).forEach(l => l.remove()); }

/* ===== 인라인 편집 ===== */
function startInlineEdit(el, host){
  el.setAttribute('contenteditable', 'true');
  el.focus();
  const r = document.createRange(); r.selectNodeContents(el);
  const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
  const orig = el.textContent;
  function commit(save){
    el.removeAttribute('contenteditable');
    el.removeEventListener('keydown', kh);
    el.removeEventListener('blur', bh);
    const v = el.textContent.trim() || orig;
    if (save && v !== orig){ updateName(host, v); snapshot(`이름: "${orig}" → "${v}"`); }
    else el.textContent = orig;
  }
  function kh(e){ if (e.key==='Enter'){ e.preventDefault(); commit(true); } else if (e.key==='Escape'){ e.preventDefault(); commit(false); } }
  function bh(){ commit(true); }
  el.addEventListener('keydown', kh); el.addEventListener('blur', bh);
}
function updateName(host, name){
  if (host.dataset.type === 'stage') data.stages.find(s => s.id === host.dataset.id).name = name;
  else {
    const p = host.dataset.parent;
    const list = p === 'standalone' ? data.standalone : data.stages.find(s => s.id === p).items;
    list.find(it => it.id === host.dataset.id).name = name;
  }
}

/* ===== 드롭다운 ===== */
const dd = $('#sb3-dropdown');
const ddColorBtn = dd.querySelector('[data-act="color"]');
let ddHost = null;
function openDropdown(host, anchor){
  ddHost = host;
  ddColorBtn.style.display = host.dataset.type === 'stage' ? '' : 'none';
  $('#sb3-dd-main').style.display = '';
  $('#sb3-dd-color').style.display = 'none';
  dd.classList.add('on');
  const r = anchor.getBoundingClientRect();
  let x = r.right + 4, y = r.top;
  if (x + 240 > innerWidth) x = r.left - 240;
  if (y + 350 > innerHeight) y = innerHeight - 360;
  dd.style.left = x + 'px'; dd.style.top = y + 'px';
}
function closeDropdown(){ dd.classList.remove('on'); ddHost = null; }
dd.addEventListener('click', e => {
  const btn = e.target.closest('button');
  if (!btn || !ddHost) return;
  e.stopPropagation(); e.preventDefault();
  if (btn.dataset.act === 'color'){
    $('#sb3-dd-main').style.display = 'none';
    $('#sb3-dd-color').style.display = 'block';
    return;
  }
  handleAction(btn.dataset.act, ddHost);
  closeDropdown();
});
const sws = $('#sb3-color-sws');
STAGE_COLORS.forEach(c => {
  const d = document.createElement('div');
  d.className = 'sw'; d.style.background = c;
  d.addEventListener('click', e => {
    e.stopPropagation();
    if (ddHost && ddHost.dataset.type === 'stage'){
      const st = data.stages.find(s => s.id === ddHost.dataset.id);
      const orig = st.color;
      st.color = c;
      snapshot(`색상: ${orig} → ${c}`);
      render();
    }
    closeDropdown();
  });
  sws.appendChild(d);
});
$('#sb3-color-hex').addEventListener('keydown', e => {
  if (e.key === 'Enter'){
    const v = e.target.value.trim();
    if (/^#[0-9A-Fa-f]{6}$/.test(v) && ddHost && ddHost.dataset.type === 'stage'){
      const st = data.stages.find(s => s.id === ddHost.dataset.id);
      const orig = st.color;
      st.color = v;
      snapshot(`색상: ${orig} → ${v}`);
      render();
      closeDropdown();
    }
  }
});
document.addEventListener('click', e => {
  if (!dd.contains(e.target)) closeDropdown();
  if (!ctxmenu.contains(e.target)) closeContextMenu();
});

/* ===== 액션 ===== */
function handleAction(act, host){
  if (act === 'emoji') openEmojiModal(host);
  else if (act === 'rename'){ const nm = host.querySelector('[data-act="rename"]'); startInlineEdit(nm, host); }
  else if (act === 'up') moveItem(host, -1);
  else if (act === 'down') moveItem(host, 1);
  else if (act === 'dup') duplicateItem(host);
  else if (act === 'delete') deleteItem(host);
}
function moveItem(host, dir){
  if (host.dataset.type === 'stage'){
    const i = data.stages.findIndex(s => s.id === host.dataset.id);
    const ni = i + dir;
    if (ni < 0 || ni >= data.stages.length) return;
    [data.stages[i], data.stages[ni]] = [data.stages[ni], data.stages[i]];
    snapshot(`"${data.stages[ni].name}" 카테고리 ${dir<0?'위로':'아래로'}`);
  } else {
    const p = host.dataset.parent;
    const list = p === 'standalone' ? data.standalone : data.stages.find(s => s.id === p).items;
    const i = list.findIndex(it => it.id === host.dataset.id);
    const ni = i + dir;
    if (ni < 0 || ni >= list.length) return;
    [list[i], list[ni]] = [list[ni], list[i]];
    snapshot(`"${list[ni].name}" ${dir<0?'위로':'아래로'}`);
  }
  render();
}
function duplicateItem(host){
  if (host.dataset.type === 'stage'){
    const i = data.stages.findIndex(s => s.id === host.dataset.id);
    const orig = data.stages[i];
    const copy = JSON.parse(JSON.stringify(orig));
    copy.id = 'cp_' + Date.now();
    copy.name = orig.name + ' 복사본';
    copy.items.forEach(it => it.id = 'cp_' + Date.now() + '_' + Math.random().toString(36).slice(2,6));
    data.stages.splice(i+1, 0, copy);
    snapshot(`"${orig.name}" 복제됨`);
  } else {
    const p = host.dataset.parent;
    const list = p === 'standalone' ? data.standalone : data.stages.find(s => s.id === p).items;
    const i = list.findIndex(it => it.id === host.dataset.id);
    const orig = list[i];
    const copy = {...orig, id: 'cp_'+Date.now(), name: orig.name + ' 복사본'};
    list.splice(i+1, 0, copy);
    snapshot(`"${orig.name}" 복제됨`);
  }
  render();
}
function deleteItem(host){
  if (host.dataset.type === 'stage'){
    const i = data.stages.findIndex(s => s.id === host.dataset.id);
    const st = data.stages[i];
    if (st.items.length && !confirm(`"${st.name}" 카테고리와 안의 항목 ${st.items.length}개를 모두 삭제할까요?`)) return;
    data.stages.splice(i, 1);
    snapshot(`"${st.name}" 카테고리 삭제됨`);
  } else {
    const p = host.dataset.parent;
    const list = p === 'standalone' ? data.standalone : data.stages.find(s => s.id === p).items;
    const i = list.findIndex(it => it.id === host.dataset.id);
    const orig = list.splice(i, 1)[0];
    snapshot(`"${orig.name}" 삭제됨`);
  }
  render();
}

/* ===== 우클릭 ===== */
const ctxmenu = $('#sb3-ctxmenu');
let ctxHost = null;
function onContextMenu(e){
  // 이모지 자체 우클릭은 위 attachAll 에서 처리 — 여기 도달 시 비-이모지
  e.preventDefault();
  openContextMenu(e.currentTarget, e.clientX, e.clientY);
}
function openContextMenu(host, x, y){
  ctxHost = host;
  ctxmenu.querySelectorAll('[data-stage-only]').forEach(b => b.style.display = host.dataset.type === 'stage' ? '' : 'none');
  ctxmenu.classList.add('on');
  if (x + 220 > innerWidth) x = innerWidth - 230;
  if (y + 280 > innerHeight) y = innerHeight - 290;
  ctxmenu.style.left = x + 'px'; ctxmenu.style.top = y + 'px';
}
function closeContextMenu(){ ctxmenu.classList.remove('on'); ctxHost = null; }
ctxmenu.addEventListener('click', e => {
  const btn = e.target.closest('button');
  if (!btn || !ctxHost) return;
  e.stopPropagation(); e.preventDefault();
  if (btn.dataset.act === 'color' && ctxHost.dataset.type === 'stage'){
    openDropdown(ctxHost, ctxHost);
    $('#sb3-dd-main').style.display = 'none';
    $('#sb3-dd-color').style.display = 'block';
  } else handleAction(btn.dataset.act, ctxHost);
  closeContextMenu();
});

/* ===== 새 카테고리 ===== */
$('#sb3-add-stage').addEventListener('click', () => {
  const id = 's_' + Date.now();
  data.stages.push({id, emoji:'', icon:'tag-simple', icon_color:null, name:'새 카테고리', color:'#5B8DEF', collapsed:false, items:[]});
  snapshot('"새 카테고리" 추가됨');
  render();
});

/* ===== 아이콘 모달 (탭: 이모지 / Phosphor 아이콘) ===== */
const modal = $('#sb3-emoji-modal');
const emGrid = $('#sb3-em-grid');
const emSearch = $('#sb3-em-search');
const emCats = $('#sb3-em-cats');
const emStyleToggleWrap = $('#sb3-em-style-wrap');
const emColorRow = $('#sb3-em-color-row');
const emColorSws = $('#sb3-em-color-sws');
const emColorHex = $('#sb3-em-color-hex');
const emStat = $('#sb3-em-stat');
const emTabs = $$('#sb3-em-tabs button');

let emHost = null;
let emCurrent = null;       // 현재 선택된 char (이모지) 또는 phosphor name
let emCurrentMode = 'icon'; // 'icon' | 'emoji'
let emCurrentColor = '#191F28';
let emCursorIdx = 0;
let emFiltered = [];
let emFilter = {cat:'전체', q:'', style:'color'};
let recentEmojis = JSON.parse(localStorage.getItem('sb3_recent_emojis') || '[]');
let recentIcons = JSON.parse(localStorage.getItem('sb3_recent_icons') || '[]');

function pushRecent(){
  if (!emCurrent) return;
  if (emCurrentMode === 'emoji'){
    recentEmojis = [emCurrent, ...recentEmojis.filter(x => x !== emCurrent)].slice(0, 24);
    localStorage.setItem('sb3_recent_emojis', JSON.stringify(recentEmojis));
  } else {
    recentIcons = [emCurrent, ...recentIcons.filter(x => x !== emCurrent)].slice(0, 24);
    localStorage.setItem('sb3_recent_icons', JSON.stringify(recentIcons));
  }
}

function currentDB(){ return emCurrentMode === 'icon' ? window.SB3_ICON_DB : window.SB3_EMOJI_DB; }
function currentCats(){ return emCurrentMode === 'icon' ? window.SB3_ICON_CATS : window.SB3_EMOJI_CATS; }
function currentRecent(){ return emCurrentMode === 'icon' ? recentIcons : recentEmojis; }

function renderCats(){
  emCats.innerHTML = '';
  const cats = currentCats();
  const db = currentDB();
  const recent = currentRecent();
  cats.forEach(c => {
    const b = document.createElement('button');
    b.textContent = c === '전체' ? '전체 ' + db.length : c === '최근' ? `최근 ${recent.length}` : c;
    b.dataset.cat = c;
    if (c === emFilter.cat) b.classList.add('on');
    b.addEventListener('click', () => {
      $$('button', emCats).forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      emFilter.cat = c;
      emCursorIdx = 0;
      renderItems();
    });
    emCats.appendChild(b);
  });
}

function renderItems(){
  const db = currentDB();
  let filtered;
  if (emFilter.cat === '최근'){
    const recent = currentRecent();
    if (emCurrentMode === 'icon'){
      filtered = recent.map(n => db.find(x => x.n === n) || {n, k:'', c:'최근'});
    } else {
      filtered = recent.map(e => db.find(x => x.e === e) || {e, k:'', c:'최근'});
    }
  } else {
    filtered = db;
    if (emFilter.cat !== '전체') filtered = filtered.filter(x => x.c === emFilter.cat);
  }
  if (emFilter.q){
    filtered = filtered.filter(x => {
      const key = emCurrentMode === 'icon' ? x.n : x.e;
      return (key && key.toLowerCase().includes(emFilter.q)) || (x.k && x.k.toLowerCase().includes(emFilter.q));
    });
  }
  emFiltered = filtered;
  emStat.textContent = `${filtered.length} / ${db.length}`;
  emGrid.innerHTML = '';
  if (!filtered.length){
    emGrid.innerHTML = `<div class="em-empty">"${escapeHtml(emFilter.q)}" 검색 결과 없음 — 다른 키워드 시도하세요</div>`;
    return;
  }
  if (emCursorIdx >= filtered.length) emCursorIdx = filtered.length - 1;
  if (emCursorIdx < 0) emCursorIdx = 0;
  filtered.forEach((x, i) => {
    const b = document.createElement('button');
    if (emCurrentMode === 'icon'){
      b.innerHTML = `<i class="ph-light ph-${x.n}" style="color:${emCurrentColor}"></i>`;
      b.title = x.n + ' · ' + (x.k || '');
      if (x.n === emCurrent) b.classList.add('cur');
    } else {
      b.textContent = x.e;
      b.title = x.k || '';
      if (x.e === emCurrent) b.classList.add('cur');
    }
    if (i === emCursorIdx) b.classList.add('cur-kb');
    b.addEventListener('click', () => {
      emCurrent = emCurrentMode === 'icon' ? x.n : x.e;
      emCursorIdx = i;
      renderItems();
    });
    b.addEventListener('dblclick', confirmSelection);
    emGrid.appendChild(b);
  });
  const kb = emGrid.querySelector('.cur-kb');
  if (kb) kb.scrollIntoView({block:'nearest'});
}

function switchTab(mode){
  emCurrentMode = mode;
  emTabs.forEach(b => b.classList.toggle('on', b.dataset.tab === mode));
  if (mode === 'icon'){
    emColorRow.style.display = '';
    emStyleToggleWrap.style.display = 'none';
    emGrid.classList.add('icon-mode');
    emGrid.classList.remove('grayscale');
  } else {
    emColorRow.style.display = 'none';
    emStyleToggleWrap.style.display = '';
    emGrid.classList.remove('icon-mode');
  }
  emFilter.cat = currentRecent().length ? '최근' : '전체';
  emCursorIdx = 0;
  renderCats();
  renderItems();
}
emTabs.forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

// 색상 팔레트 (아이콘 모드)
ICON_COLORS.forEach(c => {
  const d = document.createElement('div');
  d.className = 'sw'; d.style.background = c; d.dataset.color = c;
  d.addEventListener('click', () => {
    emCurrentColor = c;
    $$('.sw', emColorSws).forEach(x => x.classList.toggle('cur', x.dataset.color === c));
    emColorHex.value = c;
    renderItems();
  });
  emColorSws.appendChild(d);
});
emColorHex.addEventListener('input', () => {
  const v = emColorHex.value.trim();
  if (/^#[0-9A-Fa-f]{6}$/.test(v)){
    emCurrentColor = v;
    $$('.sw', emColorSws).forEach(x => x.classList.toggle('cur', x.dataset.color === v));
    renderItems();
  }
});

emSearch.addEventListener('input', () => {
  emFilter.q = emSearch.value.toLowerCase().trim();
  emCursorIdx = 0;
  renderItems();
});
$$('.em-style-toggle button', modal).forEach(b => b.addEventListener('click', () => {
  $$('.em-style-toggle button', modal).forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  emFilter.style = b.dataset.style;
  emGrid.classList.toggle('grayscale', emFilter.style === 'bw');
}));

function openEmojiModal(host){
  emHost = host;
  const t = getCurrentTarget(host);
  // 현재 상태로 초기화
  if (t.icon){
    emCurrentMode = 'icon';
    emCurrent = t.icon;
    emCurrentColor = t.icon_color || (host.dataset.type === 'stage' ? (data.stages.find(s=>s.id===host.dataset.id).color || '#191F28') : '#191F28');
  } else {
    emCurrentMode = 'emoji';
    emCurrent = t.emoji || null;
    emCurrentColor = '#191F28';
  }
  // 모달 UI 갱신
  $('#sb3-em-subtitle').textContent = `"${t.name}"의 아이콘을 변경합니다`;
  emTabs.forEach(b => b.classList.toggle('on', b.dataset.tab === emCurrentMode));
  if (emCurrentMode === 'icon'){
    emColorRow.style.display = '';
    emStyleToggleWrap.style.display = 'none';
    emGrid.classList.add('icon-mode');
    $$('.sw', emColorSws).forEach(x => x.classList.toggle('cur', x.dataset.color === emCurrentColor));
    emColorHex.value = emCurrentColor;
  } else {
    emColorRow.style.display = 'none';
    emStyleToggleWrap.style.display = '';
    emGrid.classList.remove('icon-mode');
  }
  emFilter = {cat: currentRecent().length ? '최근' : '전체', q:'', style:'color'};
  emCursorIdx = 0;
  emSearch.value = '';
  emGrid.classList.remove('grayscale');
  renderCats();
  $$('.em-style-toggle button', modal).forEach((x,i) => x.classList.toggle('on', i === 0));
  renderItems();
  modal.classList.add('on');
  setTimeout(() => emSearch.focus(), 50);
}
function closeEmojiModal(){ modal.classList.remove('on'); emHost = null; }
$('#sb3-em-close').addEventListener('click', closeEmojiModal);
modal.addEventListener('click', e => { if (e.target === modal) closeEmojiModal(); });

function getCurrentTarget(host){
  if (host.dataset.type === 'stage') return data.stages.find(s => s.id === host.dataset.id);
  const p = host.dataset.parent;
  const list = p === 'standalone' ? data.standalone : data.stages.find(s => s.id === p).items;
  return list.find(it => it.id === host.dataset.id);
}
function setIcon(host, mode, value, color){
  const t = getCurrentTarget(host);
  if (mode === 'icon'){
    t.icon = value;
    t.icon_color = color || null;
    t.emoji = '';  // 둘 동시 보유 X
  } else {
    t.emoji = value;
    t.icon = null;
    t.icon_color = null;
  }
}

function confirmSelection(){
  if (!emHost) return;
  if (emFiltered.length && emFiltered[emCursorIdx]){
    emCurrent = emCurrentMode === 'icon' ? emFiltered[emCursorIdx].n : emFiltered[emCursorIdx].e;
  }
  if (!emCurrent) { closeEmojiModal(); return; }
  const t = getCurrentTarget(emHost);
  const origDesc = t.icon ? `🎨 ${t.icon}` : (t.emoji || '없음');
  const newDesc = emCurrentMode === 'icon' ? `🎨 ${emCurrent}` : emCurrent;
  setIcon(emHost, emCurrentMode, emCurrent, emCurrentColor);
  pushRecent();
  snapshot(`아이콘: ${origDesc} → ${newDesc}`);
  render();
  closeEmojiModal();
}
$('#sb3-em-confirm').addEventListener('click', confirmSelection);
$('#sb3-em-remove').addEventListener('click', () => {
  if (!emHost) return;
  const t = getCurrentTarget(emHost);
  const orig = t.icon || t.emoji || '없음';
  t.icon = null; t.icon_color = null; t.emoji = '';
  snapshot(`아이콘 제거 (${orig} → 없음)`);
  render();
  closeEmojiModal();
});

/* ===== 키보드 ===== */
document.addEventListener('keydown', e => {
  if (modal.classList.contains('on')){
    if (e.target === emSearch){
      if (e.key === 'Escape'){ closeEmojiModal(); return; }
      if (e.key === 'Enter'){ e.preventDefault(); confirmSelection(); return; }
      if (['ArrowDown','ArrowUp'].includes(e.key)){
        e.preventDefault();
        moveCursor(e.key === 'ArrowDown' ? 16 : -16);
      }
      return;
    }
    if (e.key === 'Escape'){ closeEmojiModal(); return; }
    if (e.key === 'Enter'){ e.preventDefault(); confirmSelection(); return; }
    if (['ArrowDown','ArrowUp','ArrowLeft','ArrowRight'].includes(e.key)){
      e.preventDefault();
      const map = {ArrowDown:16, ArrowUp:-16, ArrowRight:1, ArrowLeft:-1};
      moveCursor(map[e.key]);
    }
    return;
  }
  if (e.target.isContentEditable || e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if ((e.ctrlKey || e.metaKey) && e.key === 'z'){ e.preventDefault(); undo(); }
});
function moveCursor(delta){
  const n = emFiltered.length;
  if (!n) return;
  emCursorIdx = Math.max(0, Math.min(n-1, emCursorIdx + delta));
  renderItems();
}

/* ===== 편집 가이드 ===== */
$('#sb3-edit-toggle').addEventListener('click', () => {
  alert('💡 사이드바 편집 가이드\n\n' +
    '① 이름 변경 — 텍스트 더블클릭 또는 ⋮ 메뉴\n' +
    '② 호버 메뉴 — 항목 위 마우스 → 우측 ⋮ 클릭\n' +
    '③ 드래그 — 좌측 ⋮⋮ 핸들 잡고 끌기 (카테고리 간 자유 이동)\n' +
    '④ 우클릭 — 항목 또는 이모지 자체 우클릭으로 즉시 메뉴\n' +
    '⑤ 아이콘 모달 — 이모지·아이콘 직접 클릭 (빈 곳도 클릭 가능)\n' +
    '    - [라인 아이콘] 탭: 1,248개 Phosphor + 색상 8 팔레트 + HEX\n' +
    '    - [이모지] 탭: 240+ 이모지 + 흑백/색상 토글\n' +
    '⑥ 되돌리기 — 5초 토스트 또는 Ctrl+Z\n\n' +
    '편집은 자동 저장됩니다 (서버 PUT /api/sidebar/layout)'
  );
});

attachAll();
})();

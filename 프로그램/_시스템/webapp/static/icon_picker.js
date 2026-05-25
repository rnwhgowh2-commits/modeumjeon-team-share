/* v32 — 아이콘 picker (노션 스타일)
 * 사용:
 *   window.openIconPicker({
 *     current: {icon: '🏠', color: 'default'},
 *     onPick: (icon, color) => { ... },
 *     onClear: () => { ... },
 *     title: '아이콘 선택',
 *     subtitle: '"홈" 항목의 아이콘을 변경합니다',
 *   });
 *
 * 이모지 데이터셋 — STEP 2 에서 외부 JSON 분리 예정. 현재 인라인 (간소판).
 * (사용자 후속 결정 — 이모지 vs Lucide — 에 따라 교체 가능)
 */
(function() {
  'use strict';

  // ─────── 이모지 데이터셋 (간소판 — STEP 2 에서 외부 JSON 으로 확장) ───────
  const EMOJI_DATA = {
    '최근': [], // localStorage 기반
    '스마일': '😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 🙃 😉 😌 😍 🥰 😘 😗 😙 😚 😋 😛 😝 😜 🤪 🤨 🧐 🤓 😎 🤩 🥳'.split(' '),
    '사람': '👶 🧒 👦 👧 🧑 👨 👩 🧓 👴 👵 🙍 🙎 🙅 🙆 💁 🙋 🧏 🙇 🤦 🤷 👮 🕵️ 💂 👷 🤴 👸 👳 👲 🧕'.split(' '),
    '동물': '🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐽 🐸 🐵 🙈 🙉 🙊 🐒 🐔 🐧 🐦 🐤 🐣 🐥 🦆 🦅 🦉 🦇 🐺 🐗'.split(' '),
    '음식': '🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍈 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🍆 🥑 🥦 🥬 🥒 🌶️ 🫑 🌽 🥕 🫒 🧄 🧅 🥔 🍠'.split(' '),
    '여행': '🚗 🚕 🚙 🚌 🚎 🏎️ 🚓 🚑 🚒 🚐 🚚 🚛 🚜 🛵 🏍️ ✈️ 🚀 🚁 🚂 🚆 🚇 🚊 🚉 ✈️ 🛫 🛬 🛩️ 💺 🛸 🚢'.split(' '),
    '활동': '⚽ 🏀 🏈 ⚾ 🥎 🎾 🏐 🏉 🥏 🎱 🪀 🏓 🏸 🏒 🏑 🥍 🏏 🥅 ⛳ 🪁 🏹 🎣 🤿 🥊 🥋 🎽 🛹 🛼 🛷 ⛸️'.split(' '),
    '물건': '⌚ 📱 📲 💻 ⌨️ 🖥️ 🖨️ 🖱️ 🖲️ 🕹️ 🗜️ 💽 💾 💿 📀 📼 📷 📸 📹 🎥 📽️ 🎞️ 📞 ☎️ 📟 📠 📺 📻 🎙️ 🎚️ 🎛️ ⏱️ ⏲️ ⏰'.split(' '),
    '건물·장소': '🏠 🏡 🏘️ 🏚️ 🏗️ 🏭 🏢 🏬 🏣 🏤 🏥 🏦 🏨 🏪 🏫 🏩 💒 🏛️ ⛪ 🕌 🛕 🕍 ⛩️ 🕋 ⛲ ⛺ 🌁 🌃 🏙️ 🌄 🌅 🌆 🌇 🌉'.split(' '),
    '업무·도구': '📁 📂 🗂️ 📅 📆 🗒️ 🗓️ 📇 📈 📉 📊 📋 📌 📍 📎 🖇️ 📏 📐 ✂️ 🗃️ 🗄️ 🗑️ 🔒 🔓 🔏 🔐 🔑 🗝️ 🔨 🪓 ⛏️ ⚒️ 🛠️ 🗡️ ⚔️'.split(' '),
    '기호': '⭐ 🌟 ✨ ⚡ 🔥 💧 🌊 🎯 🎨 🎭 🎪 🎰 🎲 🧩 ♟️ 🎯 🔔 🔕 📣 📢 ❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘'.split(' '),
    '국기': '🇰🇷 🇺🇸 🇯🇵 🇨🇳 🇬🇧 🇫🇷 🇩🇪 🇮🇹 🇪🇸 🇨🇦 🇦🇺 🇧🇷 🇮🇳 🇷🇺 🇲🇽 🇳🇱 🇧🇪 🇸🇪 🇳🇴 🇫🇮 🇩🇰 🇨🇭 🇦🇹 🇵🇱 🇨🇿 🇭🇺 🇬🇷'.split(' '),
  };

  // 한글/영문 키워드 매핑 (검색용 간소판)
  const SEARCH_KEYWORDS = {
    '🏠': ['집', 'house', 'home', '하우스', '홈'],
    '🏡': ['집', 'house', '주택', 'home'],
    '📦': ['상자', 'box', 'package', '박스', '소포', '모음전'],
    '🛒': ['장바구니', 'cart', 'shopping', '쇼핑'],
    '🛍️': ['쇼핑백', 'bag', 'shopping'],
    '👟': ['운동화', 'shoe', 'sneaker', '신발'],
    '👞': ['구두', 'shoe', '신발'],
    '⭐': ['별', 'star', '스타', '즐겨찾기'],
    '🔥': ['불', 'fire', '핫', '인기'],
    '⚡': ['번개', 'lightning', '빠른', 'fast'],
    '📊': ['차트', 'chart', '통계', 'stat'],
    '📈': ['상승', 'up', '오름'],
    '📉': ['하락', 'down', '내림'],
    '🔔': ['알림', 'bell', 'notification'],
    '🔒': ['잠금', 'lock', 'locked'],
    '🔓': ['열림', 'unlock'],
    '🎨': ['팔레트', 'palette', '디자인', '색'],
    '🎯': ['타겟', 'target', '목표', '과녁'],
    '💰': ['돈', 'money', '돈주머니'],
    '💳': ['카드', 'card', '신용카드'],
    '🏪': ['편의점', 'store', '가게'],
    '🏬': ['백화점', 'department', 'mall'],
    '🇰🇷': ['한국', 'korea', '대한민국'],
    '🇺🇸': ['미국', 'usa', '아메리카'],
    '🇯🇵': ['일본', 'japan'],
    // ... 외부 JSON 에서 확장
  };

  // 색상 palette (default + 9색)
  const COLORS = [
    {key: 'default', label: '기본 (흑백)', hex: '#4E5968'},
    {key: 'blue', label: '파랑', hex: '#3182F6'},
    {key: 'green', label: '초록', hex: '#03C75A'},
    {key: 'orange', label: '주황', hex: '#F59E0B'},
    {key: 'red', label: '빨강', hex: '#EF4444'},
    {key: 'purple', label: '보라', hex: '#7C3AED'},
    {key: 'teal', label: '청록', hex: '#14B8A6'},
    {key: 'pink', label: '핑크', hex: '#EC4899'},
    {key: 'indigo', label: '인디고', hex: '#6366F1'},
    {key: 'cyan', label: '시안', hex: '#06B6D4'},
  ];

  // 최근 사용 (localStorage)
  const RECENT_KEY = 'icp-recent';
  function getRecent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); } catch (_) { return []; }
  }
  function pushRecent(icon) {
    const cur = getRecent().filter(e => e !== icon);
    cur.unshift(icon);
    localStorage.setItem(RECENT_KEY, JSON.stringify(cur.slice(0, 24)));
  }

  // 검색 — 키워드 매칭
  function searchEmojis(query) {
    if (!query.trim()) return [];
    const q = query.trim().toLowerCase();
    const matches = new Set();
    // 모든 카테고리 emoji 순회
    Object.values(EMOJI_DATA).forEach(arr => {
      arr.forEach(e => {
        const kws = SEARCH_KEYWORDS[e];
        if (kws && kws.some(k => k.toLowerCase().includes(q))) {
          matches.add(e);
        }
      });
    });
    return [...matches];
  }

  // 색상 모드 시 자동 클래스 (c1~c9 순환)
  function colorClass(idx) {
    return 'c' + ((idx % 9) + 1);
  }

  // ─────── picker 생성 ───────
  let _activeOverlay = null;
  window.openIconPicker = function(opts) {
    opts = opts || {};
    const onPick = opts.onPick || (() => {});
    const onClear = opts.onClear || (() => {});
    const current = opts.current || {icon: null, color: 'default'};
    const title = opts.title || '아이콘 선택';
    const subtitle = opts.subtitle || '';

    // 기존 close
    if (_activeOverlay) closeIconPicker();

    let curIcon = current.icon || null;
    let curColor = current.color || 'default';
    // v34 — 아이콘 picker 안에서도 바탕/글자색 분리 (hex). 기존 curColor 는 호환용.
    let curBg = current.bg_color || '';
    let curFg = current.fg_color || '';
    // 기존 curColor 가 hex 이면 글자색에 자동 매핑 (호환)
    if (!curFg && curColor && curColor !== 'default' && /^#[0-9a-fA-F]{6}$/.test(curColor)) {
      curFg = curColor.toUpperCase();
    }
    let mode = 'bw';                // 'bw' | 'color'
    let activeCat = '전체';
    let searchQ = '';

    // 카테고리 + 전체 + 최근
    const cats = ['전체', '최근', ...Object.keys(EMOJI_DATA).filter(k => k !== '최근')];

    function getDisplayEmojis() {
      if (searchQ) return searchEmojis(searchQ);
      if (activeCat === '최근') return getRecent();
      if (activeCat === '전체') {
        const all = [];
        Object.entries(EMOJI_DATA).forEach(([k, v]) => { if (k !== '최근') all.push(...v); });
        return all;
      }
      return EMOJI_DATA[activeCat] || [];
    }

    // ─── DOM 생성 ───
    const overlay = document.createElement('div');
    overlay.className = 'icp-overlay';
    overlay.innerHTML = `
      <div class="icp-modal" role="dialog" aria-label="아이콘 선택">
        <div class="icp-head">
          <h3>${escapeHtml(title)}</h3>
          ${subtitle ? `<span class="icp-sub">${escapeHtml(subtitle)}</span>` : ''}
          <button type="button" class="icp-esc">Esc ✕</button>
        </div>
        <div class="icp-search">
          <input type="text" placeholder="🔍 검색 — 한글/영문/키워드 (예: 집·home·홈)" autocomplete="off">
          <div class="icp-mode">
            <button type="button" data-mode="color">🌈 색상</button>
            <button type="button" data-mode="bw" class="on">⚫ 흑백</button>
          </div>
        </div>
        <div class="icp-cats"></div>
        <div class="icp-grid"></div>
        <div class="icp-palette"></div>
        <div class="icp-foot">
          <span class="icp-hint">
            <kbd>↑↓←→</kbd> 탐색 · <kbd>Enter</kbd> 선택 · <kbd>Esc</kbd> 닫기
          </span>
          <div class="icp-acts">
            <button type="button" class="icp-clear">아이콘 제거</button>
            <button type="button" class="icp-pick" disabled>선택</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    _activeOverlay = overlay;

    const $modal = overlay.querySelector('.icp-modal');
    const $input = overlay.querySelector('.icp-search input');
    const $cats = overlay.querySelector('.icp-cats');
    const $grid = overlay.querySelector('.icp-grid');
    const $palette = overlay.querySelector('.icp-palette');
    const $pickBtn = overlay.querySelector('.icp-pick');
    const $clearBtn = overlay.querySelector('.icp-clear');
    const $modeBtns = overlay.querySelectorAll('.icp-mode button');

    // 카테고리 렌더
    function renderCats() {
      $cats.innerHTML = cats.map(c => {
        const cnt = c === '전체'
          ? Object.values(EMOJI_DATA).reduce((a, v) => a + v.length, 0)
          : (c === '최근' ? getRecent().length : (EMOJI_DATA[c] || []).length);
        return `<button type="button" data-cat="${c}" ${c === activeCat ? 'class="on"' : ''}>${c} <span class="icp-cnt">${cnt}</span></button>`;
      }).join('');
    }

    // 그리드 렌더
    function renderGrid() {
      const items = getDisplayEmojis();
      if (!items.length) {
        $grid.innerHTML = `<div class="icp-empty">${searchQ ? '검색 결과 없음' : (activeCat === '최근' ? '아직 사용한 아이콘 없음' : '항목 없음')}</div>`;
        return;
      }
      $grid.innerHTML = items.map((e, i) => {
        const cls = ['icp-cell'];
        if (mode === 'color') cls.push('cmode', colorClass(i));
        if (e === curIcon) cls.push('selected');
        return `<button type="button" class="${cls.join(' ')}" tabindex="0" data-icon="${escapeHtml(e)}">${e}</button>`;
      }).join('');
    }

    // 색상 palette 렌더 — v34: 바탕/글자 분리 + 프리셋 + native + HEX
    function renderPalette() {
      if (!curIcon) {
        $palette.style.display = 'none';
        return;
      }
      $palette.style.display = 'block';
      $palette.classList.add('icp-cp-v34');
      const previewBg = curBg || '#F2F4F6';
      const previewFg = curFg || '#191F28';
      $palette.innerHTML = `
        <div class="icp-cp-inline-row">
          <div class="icp-cp-preview-chip" style="background:${previewBg};color:${previewFg};font-size:20px;padding:8px 14px;">${curIcon}</div>
          <div class="icp-cp-inline-hint">바탕색·글자색을 각각 지정 — 비우면 기본</div>
        </div>

        <div class="icp-cp-section">
          <div class="icp-cp-row-label">🟦 바탕색</div>
          <div class="icp-cp-photo-host" data-target="bg"></div>
          <div class="icp-cp-grid">
            ${COLOR_PALETTE.map(c => `
              <button type="button" class="icp-cp-cell ${(c.bg || '').toUpperCase() === curBg.toUpperCase() ? 'on' : ''}" data-target="bg" data-hex="${c.bg}" title="${c.label}"
                      style="background:${c.bg || 'transparent'};border:${c.bg ? 'none' : '1.5px dashed #B0B8C1'}">${c.bg ? '' : '⊘'}</button>
            `).join('')}
          </div>
          <div class="icp-cp-input-row">
            <input type="text" class="icp-cp-hex" data-target="bg" value="${curBg}" placeholder="#RRGGBB (비우면 기본)" maxlength="7">
            <span class="icp-cp-swatch" data-target="bg" style="background:${curBg}"></span>
          </div>
        </div>

        <div class="icp-cp-section">
          <div class="icp-cp-row-label">🅰 글자색</div>
          <div class="icp-cp-photo-host" data-target="fg"></div>
          <div class="icp-cp-grid">
            ${COLOR_PALETTE.map(c => `
              <button type="button" class="icp-cp-cell ${(c.bg || '').toUpperCase() === curFg.toUpperCase() ? 'on' : ''}" data-target="fg" data-hex="${c.bg}" title="${c.label}"
                      style="background:${c.bg || 'transparent'};border:${c.bg ? 'none' : '1.5px dashed #B0B8C1'}">${c.bg ? '' : '⊘'}</button>
            `).join('')}
          </div>
          <div class="icp-cp-input-row">
            <input type="text" class="icp-cp-hex" data-target="fg" value="${curFg}" placeholder="#RRGGBB (비우면 기본)" maxlength="7">
            <span class="icp-cp-swatch" data-target="fg" style="background:${curFg}"></span>
          </div>
        </div>
      `;

      // v34.5 — photoPicker 인스턴스 (모달 안. native picker 제거)
      const _modalPhotoPickers = {};
      ['bg', 'fg'].forEach(t => {
        const host = $palette.querySelector(`.icp-cp-photo-host[data-target="${t}"]`);
        if (!host) return;
        const initial = (t === 'bg' ? curBg : curFg) || (t === 'bg' ? '#3182F6' : '#191F28');
        const pp = _createPhotoPicker(initial, (hex) => {
          if (t === 'bg') curBg = hex; else curFg = hex;
          // 미리보기·hex·swatch 만 갱신 — re-render 시 photoPicker 가 새로 만들어져 드래그가 끊기는 것 방지
          const chip = $palette.querySelector('.icp-cp-preview-chip');
          if (chip) {
            chip.style.background = curBg || '#F2F4F6';
            chip.style.color = curFg || '#191F28';
          }
          const inp = $palette.querySelector(`.icp-cp-hex[data-target="${t}"]`);
          if (inp) inp.value = hex;
          const swatch = $palette.querySelector(`.icp-cp-swatch[data-target="${t}"]`);
          if (swatch) swatch.style.background = hex;
        });
        host.appendChild(pp.el);
        _modalPhotoPickers[t] = pp;
      });

      // 프리셋 클릭
      $palette.querySelectorAll('.icp-cp-cell').forEach(b => b.addEventListener('click', e => {
        e.stopPropagation();
        const t = b.dataset.target;
        const hex = b.dataset.hex || '';
        if (t === 'bg') curBg = hex; else curFg = hex;
        if (hex && _modalPhotoPickers[t]) _modalPhotoPickers[t].setHex(hex);
        renderPalette();
      }));

      // HEX 입력
      $palette.querySelectorAll('.icp-cp-hex').forEach(h => {
        h.addEventListener('input', e => {
          e.stopPropagation();
          const t = h.dataset.target;
          const v = _normHex(h.value);
          if (h.value.trim() === '') {
            if (t === 'bg') curBg = ''; else curFg = '';
            const chip = $palette.querySelector('.icp-cp-preview-chip');
            if (chip) {
              chip.style.background = curBg || '#F2F4F6';
              chip.style.color = curFg || '#191F28';
            }
            return;
          }
          if (!v) return;
          if (t === 'bg') curBg = v; else curFg = v;
          if (_modalPhotoPickers[t]) _modalPhotoPickers[t].setHex(v);
          const chip = $palette.querySelector('.icp-cp-preview-chip');
          if (chip) {
            chip.style.background = curBg || '#F2F4F6';
            chip.style.color = curFg || '#191F28';
          }
          const swatch = $palette.querySelector(`.icp-cp-swatch[data-target="${t}"]`);
          if (swatch) swatch.style.background = v;
        });
      });
    }

    // 푸터 버튼 상태
    function renderFoot() {
      $pickBtn.disabled = !curIcon;
      $pickBtn.textContent = curIcon ? `선택 (${curIcon})` : '선택';
    }

    function rerender() { renderCats(); renderGrid(); renderPalette(); renderFoot(); }

    // ─── 이벤트 ───
    $input.addEventListener('input', e => { searchQ = e.target.value; renderGrid(); });
    $cats.addEventListener('click', e => {
      const b = e.target.closest('button[data-cat]');
      if (!b) return;
      activeCat = b.dataset.cat;
      searchQ = ''; $input.value = '';
      renderCats(); renderGrid();
    });
    $modeBtns.forEach(b => b.addEventListener('click', () => {
      $modeBtns.forEach(x => x.classList.toggle('on', x === b));
      mode = b.dataset.mode;
      renderGrid();
    }));
    $grid.addEventListener('click', e => {
      const c = e.target.closest('.icp-cell');
      if (!c) return;
      curIcon = c.dataset.icon;
      renderGrid(); renderPalette(); renderFoot();
    });
    // v34 — palette 내부 클릭은 renderPalette 안에서 직접 바인딩 (셀/native/hex)
    $clearBtn.addEventListener('click', () => {
      try { onClear(); } catch (_) {}
      closeIconPicker();
    });
    $pickBtn.addEventListener('click', () => {
      if (!curIcon) return;
      pushRecent(curIcon);
      // v34 — 글자색 hex 가 있으면 color 파라미터로도 전달 (하위 호환)
      const colorArg = curFg || curColor;
      try { onPick(curIcon, colorArg, {bg_color: curBg || null, fg_color: curFg || null}); } catch (_) {}
      closeIconPicker();
    });
    overlay.querySelector('.icp-esc').addEventListener('click', closeIconPicker);
    overlay.addEventListener('click', e => { if (e.target === overlay) closeIconPicker(); });
    document.addEventListener('keydown', _keyHandler);

    // ─── 키보드 (↑↓←→ Enter Esc) ───
    function _keyHandler(e) {
      if (overlay !== _activeOverlay) return;
      if (e.key === 'Escape') { e.preventDefault(); closeIconPicker(); return; }
      if (e.key === 'Enter') {
        if (curIcon) { e.preventDefault(); $pickBtn.click(); }
        return;
      }
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        e.preventDefault();
        const cells = [...$grid.querySelectorAll('.icp-cell')];
        if (!cells.length) return;
        const cur = cells.findIndex(c => c.dataset.icon === curIcon);
        const cols = 15;
        let next = cur < 0 ? 0 : cur;
        if (e.key === 'ArrowRight') next = Math.min(cur + 1, cells.length - 1);
        else if (e.key === 'ArrowLeft') next = Math.max(cur - 1, 0);
        else if (e.key === 'ArrowDown') next = Math.min(cur + cols, cells.length - 1);
        else if (e.key === 'ArrowUp') next = Math.max(cur - cols, 0);
        curIcon = cells[next].dataset.icon;
        cells[next].scrollIntoView({block: 'nearest', behavior: 'smooth'});
        renderGrid(); renderPalette(); renderFoot();
      }
    }

    // 최초 렌더
    rerender();
    setTimeout(() => $input.focus(), 30);

    function escapeHtml(s) {
      return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    // close handler 등록
    overlay._cleanup = () => document.removeEventListener('keydown', _keyHandler);
  };

  // 종료
  window.closeIconPicker = function() {
    if (!_activeOverlay) return;
    try { if (_activeOverlay._cleanup) _activeOverlay._cleanup(); } catch (_) {}
    _activeOverlay.remove();
    _activeOverlay = null;
  };

  // ─────── 글로벌 트리거 — [data-icon-edit] 우클릭 또는 ✎ 버튼 클릭 시 picker ───────
  // 사용법: <span data-icon-edit="context|target_id" data-icon-current="🏠" data-icon-color="blue">🏠</span>
  //   · 호버 시 우측 상단에 ✎ 버튼 노출
  //   · ✎ 클릭 또는 우클릭(contextmenu) 시 picker 열림
  //   · 일반 클릭은 원래 동작 (a 태그 navigation 등) 그대로 유지
  function _openPickerFor(trigger) {
    // v32 — 사이드바 자체 picker (sb3-emoji-modal) 가 있는 곳이면 그것 호출 (Phosphor 라인 아이콘 더 풍부)
    const sidebarHost = trigger.closest('.sb3-item, .sb3-stage');
    if (sidebarHost && (trigger.matches('.emo, .st-emo') || trigger.querySelector('.ph-light'))) {
      // 자체 picker — emo/st-emo 의 클릭 핸들러 호출 (이미 [data-act="emoji"] 가 trigger)
      const emoEl = trigger.matches('.emo, .st-emo') ? trigger : trigger.querySelector('.emo, .st-emo');
      if (emoEl) { emoEl.click(); return; }
    }
    const ctx = trigger.dataset.iconEdit;
    const [context, targetId] = (ctx || '').split('|');
    const cur = trigger.dataset.iconCurrent || trigger.textContent.trim();
    const col = trigger.dataset.iconColor || 'default';
    const curBgInit = trigger.dataset.iconBg || '';
    const curFgInit = trigger.dataset.iconFg || '';
    const label = trigger.dataset.iconLabel || '';
    window.openIconPicker({
      title: '아이콘 선택',
      subtitle: label ? `"${label}" 항목의 아이콘을 변경합니다` : '',
      current: {icon: cur, color: col, bg_color: curBgInit, fg_color: curFgInit},
      onPick: async (icon, color, extras) => {
        const bg = (extras && extras.bg_color) || null;
        const fg = (extras && extras.fg_color) || null;
        // inline 모드 (Type B — 이모지 + 텍스트) 시 첫 글자만 교체
        if (trigger.hasAttribute('data-icon-inline')) {
          const oldIcon = trigger.dataset.iconCurrent || '';
          const fullText = trigger.textContent;
          const m = fullText.match(INLINE_EMOJI_RE);
          if (m) {
            trigger.textContent = icon + fullText.slice(m[1].length);
          } else if (oldIcon && fullText.startsWith(oldIcon)) {
            trigger.textContent = icon + fullText.slice(oldIcon.length);
          } else {
            trigger.textContent = icon + ' ' + fullText;
          }
        } else {
          trigger.textContent = icon;
        }
        trigger.dataset.iconCurrent = icon;
        trigger.dataset.iconColor = color;
        trigger.dataset.iconBg = bg || '';
        trigger.dataset.iconFg = fg || '';
        // 글자색 — hex 가 있으면 직접 적용, 없으면 기존 key 기반 fallback
        if (fg) {
          trigger.style.color = fg;
        } else if (color && color !== 'default' && !/^#/.test(color)) {
          const hex = (COLORS.find(c => c.key === color) || COLORS[0]).hex;
          trigger.style.color = hex;
        } else {
          trigger.style.color = '';
        }
        // 바탕색 — 신규 v34
        trigger.style.backgroundColor = bg || '';
        try {
          await fetch('/api/icon/set', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({context, target_id: targetId, icon, color, bg_color: bg, fg_color: fg}),
          });
        } catch (_) {}
      },
      onClear: async () => {
        trigger.textContent = '';
        trigger.dataset.iconCurrent = '';
        trigger.dataset.iconBg = '';
        trigger.dataset.iconFg = '';
        trigger.style.color = '';
        trigger.style.backgroundColor = '';
        try {
          await fetch('/api/icon/set', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({context, target_id: targetId, icon: null, color: null, bg_color: null, fg_color: null}),
          });
        } catch (_) {}
      },
    });
  }

  // 우클릭 → picker
  document.addEventListener('contextmenu', e => {
    const trigger = e.target.closest('[data-icon-edit]');
    if (!trigger) return;
    e.preventDefault();
    e.stopPropagation();
    _openPickerFor(trigger);
  });

  // 호버 시 ✎ 버튼 표시 — v33.1: 1000ms 딜레이 (UX 안정성)
  //   진입 후 1초 머물러야 ✎ 노출. 1초 안에 빠져나가면 cancel.
  const HOVER_DELAY_MS = 1000;
  const _icoHoverTimers = new WeakMap();
  document.addEventListener('mouseover', e => {
    const trigger = e.target.closest('[data-icon-edit]');
    if (!trigger) return;
    if (trigger.querySelector('.icp-edit-btn')) return;
    if (_icoHoverTimers.get(trigger)) return; // 이미 대기 중
    const tid = setTimeout(() => {
      _icoHoverTimers.delete(trigger);
      if (trigger.querySelector('.icp-edit-btn')) return;
      // 1초 경과 시점에도 트리거가 DOM에 있는지·실제 hover 상태인지 확인
      if (!document.body.contains(trigger)) return;
      if (!trigger.matches(':hover')) return;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'icp-edit-btn';
      btn.title = '아이콘 변경 (또는 우클릭)';
      btn.textContent = '✎';
      btn.addEventListener('click', evt => {
        evt.preventDefault(); evt.stopPropagation();
        _openPickerFor(trigger);
      });
      btn.addEventListener('mousedown', evt => { evt.preventDefault(); evt.stopPropagation(); });
      trigger.appendChild(btn);
    }, HOVER_DELAY_MS);
    _icoHoverTimers.set(trigger, tid);
  });
  document.addEventListener('mouseout', e => {
    const trigger = e.target.closest('[data-icon-edit]');
    if (!trigger) return;
    if (trigger.contains(e.relatedTarget)) return;
    // 대기 중인 타이머가 있으면 cancel
    const tid = _icoHoverTimers.get(trigger);
    if (tid) { clearTimeout(tid); _icoHoverTimers.delete(trigger); }
    const btn = trigger.querySelector('.icp-edit-btn');
    if (btn) btn.remove();
  });

  // ─────── 자동 감지 모드 — 이모지/큰 아이콘 자동 trigger 부여 ───────
  // 사용자가 「모든 곳 적용」 요청 — 명시적 data-icon-edit 없는 곳도 자동 인식.
  // 조건:
  //  · 텍스트가 단일 이모지 + 공백/빈 자식 외 없음
  //  · 또는 클래스가 알려진 아이콘 클래스
  //  · `data-icon-no-edit` 속성 있으면 skip
  //  · 이미 trigger 있는 부모 안이면 skip (중첩 방지)
  const KNOWN_ICON_CLASSES = [
    'bh-thumb', 'bl-thumb', 'hub-ico', 'hub-hero-ic',
    'sb-mode-ic', 'sb3-emo', 'st-emo', 'emo', 'sb-ic',
    'kpi-icon', 'stage-icon', 'hero-icon',
    'page-emoji', 'card-emoji', 'header-emoji',
    'kpi-ic', 'kpi-emoji', 'kpi-card-ic', 'card-ic',
    'home-kpi-ic', 'home-card-ic',
    'dashboard-card-ic', 'stat-ic',
    'mkt-badge', 'mkt-chip', 'market-ic',
    'pi',  // Phosphor icon wrapper
    // v32 — 전수 분석 결과 추가
    'nav-item', 'nav-group-title',   // 인벤토리 사이드바
    'draft-fab',                      // 「⏳ 임시저장」 FAB
    'step-tab',                       // 단계 탭 (1·2)
    'add-item', 'add-stage',          // 「＋ 항목 추가」 / 「＋ 새 카테고리」
    'sj-icon-btn',                    // 소싱처 계정 액션 아이콘
    'btn-sm-emo',                     // 작은 버튼 emoji
    'm4v1-mkt-logo',                  // 매트릭스 마켓 logo wrapper
    'brand-favi',                     // brand favicon
    // v33 — matrix v3 상세 페이지 (동적 렌더)
    'ga-ico',                         // 그룹 액션 아이콘 (▼ 펼치기 등)
    'mc-icon',                        // 마켓 셀 prefix (ss/cp 컬러)
    'site-logo',                      // 사이트 칸 헤더 로고
    'odd-site-ico',                   // INV 드로어 사이트 아이콘
    'd2-src-logo',                    // 소싱처 d2 로고
    'sc-logo',                        // 사이트 칸 로고 변형
    'brand-icon',                     // 브랜드 폴백 아이콘 (FN/CP/SS 등)
    'mkt-prefix',                     // 마켓 prefix
    'm4-mkt-prefix',                  // matrix4 마켓 prefix
    'mkt-emoji',                      // 마켓 이모지
    'inv-id-chip',                    // INV-xxxx 칩의 prefix
  ];
  // 단일 이모지 정규식 (대략) — 이모지 + variation selector 포함
  const EMOJI_RE = /^[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{1F300}-\u{1F9FF}][\u{FE0F}\u{200D}\u{20E3}\u{E0020}-\u{E007F}]*$/u;

  // v32 — 이모지 + 텍스트 inline 매칭 정규식 (Type B)
  //   "📍 사이트 소싱처 URL" / "＋ 항목 추가" / "⏳ 임시저장 (0)" 처럼 첫 글자가 이모지
  const INLINE_EMOJI_RE = /^([\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{1F300}-\u{1F9FF}][\u{FE0F}\u{200D}\u{20E3}]*|[＋+×])\s+(\S)/u;

  function autoDetect() {
    // 1) 알려진 클래스 — class 매칭 (단일 이모지 검사 생략, known 이면 통과)
    KNOWN_ICON_CLASSES.forEach(cls => {
      document.querySelectorAll('.' + cls).forEach(el => attachAutoTrigger(el, {known: true}));
    });
    // 2) 단일 이모지 — span/div/i 의 text 만 이모지인 경우
    document.querySelectorAll('span, div, i, em, b, h1, h2, h3, h4, h5, h6, p, label, a, button, td').forEach(el => {
      if (el.children.length > 0) return;
      const t = (el.textContent || '').trim();
      if (!t || t.length > 4) return;
      if (!EMOJI_RE.test(t)) return;
      const fs = parseFloat(getComputedStyle(el).fontSize) || 14;
      if (fs < 13) return;
      attachAutoTrigger(el);
    });
    // 3) Type B — 이모지 + 텍스트 inline (예: "📍 사이트 소싱처 URL")
    //    첫 글자가 이모지 + 공백 + 텍스트 → element 자체에 trigger (변경 시 첫 글자만 교체)
    document.querySelectorAll('h1, h2, h3, h4, h5, h6, .add-item, .add-stage, .draft-fab, .step-tab, .nav-item').forEach(el => {
      if (el.hasAttribute('data-icon-edit')) return;
      if (el.children.length > 0) {
        // 자식 있으면 — 직접 텍스트 노드의 첫 글자가 이모지인지 확인
        const firstText = el.firstChild;
        if (!firstText || firstText.nodeType !== Node.TEXT_NODE) return;
        const t = firstText.textContent.trim();
        if (!INLINE_EMOJI_RE.test(t)) return;
      } else {
        const t = (el.textContent || '').trim();
        if (!INLINE_EMOJI_RE.test(t)) return;
      }
      attachAutoTrigger(el, {inline: true});
    });
  }

  function attachAutoTrigger(el, opts) {
    opts = opts || {};
    if (!el || el.hasAttribute('data-icon-edit')) return;
    if (el.hasAttribute('data-icon-no-edit')) return;
    if (el.closest('[data-icon-no-edit]')) return;
    // 중첩 방지 — 부모에 trigger 있으면 skip
    if (el.parentElement && el.parentElement.closest('[data-icon-edit]')) return;
    // 시스템 UI 위치 — 제외
    if (el.closest('#theme-toggle-wrap, #bell-wrap, .icp-overlay, #g-progress-widget')) return;
    if (el.closest('.sb3-modal-overlay, .sb3-dropdown, .sb3-ctxmenu')) return;
    // [data-act="emoji"] 자체는 skip 안 함 — v32 호버 ✎ 표시 + 클릭 시 자체 picker 호출 (_openPickerFor 가 분기 처리)
    // 단, [data-act="emoji"] 안의 자식만 skip (중첩 방지)
    if (el.closest('[data-act="emoji"]') && !el.matches('[data-act="emoji"]')) return;
    // v32 — 사이드바 메뉴 항목의 emo/st-emo/sb-mode-ic 는 호버 ✎ 표시 허용 (클릭 시 자체 picker 호출)
    if (el.closest('.sb3-stage, .sb3-item, .sb3-stand')) {
      if (!el.matches('.emo, .st-emo, .sb-mode-ic') && !el.querySelector('.ph-light')) return;
    }
    if (el.closest('.cell-fx-pop, .opt-detail-overlay, .b1-side-h')) return;
    // v32 추가 — 액션 버튼·토스트·검색·드롭다운·메뉴 아이콘 등 시스템 UI 제외
    // v32 — button 안이어도 known class 매칭이면 통과 (템플릿 페이지 btn-sm 등)
    if (el.closest('button:not([data-icon-edit])')) {
      const hasKnown = KNOWN_ICON_CLASSES.some(k => el.classList.contains(k));
      if (!hasKnown) return;
    }
    if (el.closest('a:not([data-icon-edit])')) {
      // a 태그 안이면 위치 확인 — known icon class 만 통과
      const hasKnownClass = KNOWN_ICON_CLASSES.some(k => el.classList.contains(k));
      if (!hasKnownClass) return;
    }
    if (el.closest('.toast, .flash, .flash-message, [class*="flash"], .alert, .ribbon')) return;
    if (el.closest('.qsearch, .search-icon, [class*="search"]')) return;
    if (el.closest('.modal, .popover, .tooltip, .dropdown, .ctx-menu, .ctxmenu')) return;
    if (el.closest('.sb-ic-row, .menu-item, .submenu-item, .dropdown-item')) return;
    if (el.closest('[role="button"], [role="menu"], [role="menuitem"]')) return;
    // v32 — 액션 기호 정밀화 — 시스템 UI 핵심 기호만 skip
    //   사용자 의도: 🔍, ＋ 등도 변경 가능해야 → ACTION_SYMBOLS 에서 제거
    const ACTION_SYMBOLS = new Set(['✕', '✖', '✗', '⠿', '×', '—',
                                     '↑', '↓', '←', '→', '▶', '▼', '◀', '▲', '⋮', '⋯',
                                     '·']);
    const t2 = (el.textContent || '').trim();
    if (ACTION_SYMBOLS.has(t2)) return;
    // 토스트 / 변경 안내 류
    if (el.closest('[class*="toast"], [class*="undo"], [class*="notify"], [class*="change-bar"]')) return;
    // 아이콘 의미가 있는 텍스트 (단일 이모지 또는 known class)
    const t = (el.textContent || '').trim();
    el.setAttribute('data-icon-edit', 'auto|' + _autoId(el));
    // inline 모드 (Type B) — 첫 글자만 icon, 텍스트는 보존
    if (opts.inline) {
      el.setAttribute('data-icon-inline', '1');
      const m = t.match(INLINE_EMOJI_RE);
      if (m) {
        el.setAttribute('data-icon-current', m[1]);
        el.setAttribute('data-icon-label', t.slice(m[1].length).trim().slice(0, 40));
      } else {
        el.setAttribute('data-icon-current', t.slice(0, 4));
      }
    } else {
      el.setAttribute('data-icon-current', t);
      if (!el.hasAttribute('data-icon-label')) {
        const sib = el.nextElementSibling;
        const lbl = (sib && sib.textContent || el.parentElement?.textContent || '').trim().slice(0, 40);
        el.setAttribute('data-icon-label', lbl || '아이콘');
      }
    }
  }
  function _autoId(el) {
    // 안정 id 부여 (xpath 단순화)
    if (el.id) return el.id;
    let p = el, path = [];
    while (p && p !== document.body && path.length < 5) {
      let s = p.tagName.toLowerCase();
      if (p.className) s += '.' + (p.className + '').split(' ')[0];
      path.unshift(s);
      p = p.parentElement;
    }
    return path.join('>');
  }

  // 페이지 로드 + dynamic content 시 자동 적용
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoDetect);
  } else {
    autoDetect();
  }
  // dynamic content (loadMatrix 등) 후 재실행 — 글로벌 노출
  window.icpAutoDetect = autoDetect;

  // ═══════════════════════════════════════════════════════════════
  //  v32 — 색상 박스 mini picker (마켓 chip · brand chip · badge 등)
  //
  //  사용:
  //   · [data-color-edit="context|target_id"] 속성 가진 element 호버 → 🎨 mini 버튼
  //   · 또는 우클릭 → 색상 palette popover (12색)
  //   · 클릭 시 background-color (또는 color) 변경 + 서버 저장
  // ═══════════════════════════════════════════════════════════════
  const COLOR_PALETTE = [
    {key: 'green',   bg: '#03C75A', fg: '#fff', label: '초록 (네이버)'},
    {key: 'green-d', bg: '#0E7C3A', fg: '#fff', label: '진초록'},
    {key: 'orange',  bg: '#F59E0B', fg: '#fff', label: '주황 (쿠팡)'},
    {key: 'red',     bg: '#EF4444', fg: '#fff', label: '빨강'},
    {key: 'red-d',   bg: '#B91C1C', fg: '#fff', label: '진빨강'},
    {key: 'blue',    bg: '#3182F6', fg: '#fff', label: '파랑'},
    {key: 'blue-d',  bg: '#1B64DA', fg: '#fff', label: '진파랑'},
    {key: 'purple',  bg: '#7C3AED', fg: '#fff', label: '보라'},
    {key: 'pink',    bg: '#EC4899', fg: '#fff', label: '핑크'},
    {key: 'teal',    bg: '#14B8A6', fg: '#fff', label: '청록'},
    {key: 'indigo',  bg: '#6366F1', fg: '#fff', label: '인디고'},
    {key: 'cyan',    bg: '#06B6D4', fg: '#fff', label: '시안'},
    {key: 'yellow',  bg: '#FCD34D', fg: '#191F28', label: '노랑'},
    {key: 'lime',    bg: '#84CC16', fg: '#fff', label: '라임'},
    {key: 'gray',    bg: '#6B7684', fg: '#fff', label: '회색'},
    {key: 'dark',    bg: '#191F28', fg: '#fff', label: '검정'},
    {key: 'white',   bg: '#fff',    fg: '#191F28', label: '흰색 (라이트)'},
    {key: 'default', bg: '',        fg: '',       label: '기본 (해제)'},
  ];

  // ═══════════════════════════════════════════════════════════════
  // v34.3 — 포토샵식 커스텀 color picker (HSV/Hue 평면)
  //   native <input type="color"> 대체. 「적용」 누르기 전엔 절대 확정 X.
  // ═══════════════════════════════════════════════════════════════
  function _hexToRgb(hex) {
    const m = /^#?([0-9a-fA-F]{6})$/.exec((hex || '').replace('#',''));
    if (!m) return [0, 0, 0];
    const n = parseInt(m[1], 16);
    return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
  }
  function _rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(n => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0')).join('').toUpperCase();
  }
  function _rgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    let h = 0;
    if (d > 0) {
      if (max === r) h = ((g - b) / d) % 6;
      else if (max === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h *= 60; if (h < 0) h += 360;
    }
    const s = max === 0 ? 0 : d / max;
    return [h, s, max];
  }
  function _hsvToRgb(h, s, v) {
    const c = v * s;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m = v - c;
    let rp, gp, bp;
    if (h < 60)       [rp, gp, bp] = [c, x, 0];
    else if (h < 120) [rp, gp, bp] = [x, c, 0];
    else if (h < 180) [rp, gp, bp] = [0, c, x];
    else if (h < 240) [rp, gp, bp] = [0, x, c];
    else if (h < 300) [rp, gp, bp] = [x, 0, c];
    else              [rp, gp, bp] = [c, 0, x];
    return [(rp + m) * 255, (gp + m) * 255, (bp + m) * 255];
  }

  // photoPicker 팩토리. hex 초기값 받고, 변경 시 onChange(hex) 호출 (드래그 중 매번).
  //   반환: {el, setHex(hex)}
  function _createPhotoPicker(initHex, onChange) {
    const [r0, g0, b0] = _hexToRgb(initHex || '#FF0000');
    let [h, s, v] = _rgbToHsv(r0, g0, b0);
    if (!initHex) { h = 0; s = 1; v = 1; }

    const wrap = document.createElement('div');
    wrap.className = 'icp-photo';
    wrap.innerHTML = `
      <div class="icp-photo-sv" tabindex="0">
        <div class="icp-photo-sv-cursor"></div>
      </div>
      <div class="icp-photo-hue" tabindex="0">
        <div class="icp-photo-hue-cursor"></div>
      </div>
    `;
    const $sv = wrap.querySelector('.icp-photo-sv');
    const $svCur = wrap.querySelector('.icp-photo-sv-cursor');
    const $hue = wrap.querySelector('.icp-photo-hue');
    const $hueCur = wrap.querySelector('.icp-photo-hue-cursor');

    function applyVisual() {
      const hueRgb = _hsvToRgb(h, 1, 1);
      $sv.style.background = `
        linear-gradient(to top, #000, transparent),
        linear-gradient(to right, #fff, rgb(${hueRgb.map(Math.round).join(',')}))
      `;
      $svCur.style.left = (s * 100) + '%';
      $svCur.style.top = ((1 - v) * 100) + '%';
      $hueCur.style.left = ((h / 360) * 100) + '%';
    }

    function fireChange() {
      const [r, g, b] = _hsvToRgb(h, s, v);
      const hex = _rgbToHex(r, g, b);
      try { onChange && onChange(hex); } catch (_) {}
    }

    function setHex(hex) {
      const [r, g, b] = _hexToRgb(hex);
      [h, s, v] = _rgbToHsv(r, g, b);
      // 회색이면 hue 가 0 으로 떨어짐 — 기존 hue 유지 위해 v 가 0 일 때 보정 생략
      applyVisual();
    }

    // SV 드래그
    let svDragging = false;
    function svFromEvent(e) {
      const rect = $sv.getBoundingClientRect();
      const cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
      const cy = (e.touches ? e.touches[0].clientY : e.clientY) - rect.top;
      s = Math.max(0, Math.min(1, cx / rect.width));
      v = Math.max(0, Math.min(1, 1 - cy / rect.height));
      applyVisual();
      fireChange();
    }
    $sv.addEventListener('mousedown', e => {
      e.preventDefault(); e.stopPropagation();
      svDragging = true; svFromEvent(e);
    });
    window.addEventListener('mousemove', e => { if (svDragging) { e.preventDefault(); svFromEvent(e); } });
    window.addEventListener('mouseup', () => { svDragging = false; });

    // Hue 드래그
    let hueDragging = false;
    function hueFromEvent(e) {
      const rect = $hue.getBoundingClientRect();
      const cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
      h = Math.max(0, Math.min(360, (cx / rect.width) * 360));
      applyVisual();
      fireChange();
    }
    $hue.addEventListener('mousedown', e => {
      e.preventDefault(); e.stopPropagation();
      hueDragging = true; hueFromEvent(e);
    });
    window.addEventListener('mousemove', e => { if (hueDragging) { e.preventDefault(); hueFromEvent(e); } });
    window.addEventListener('mouseup', () => { hueDragging = false; });

    applyVisual();
    return {el: wrap, setHex};
  }

  // v34.5 — 외부 사용을 위해 노출 (예: _matrix_v3.html 자체 popover, 다른 페이지의 색상 picker)
  window.icpCreatePhotoPicker = _createPhotoPicker;

  // ─── v34 — HEX 정규화·검증 ───
  function _normHex(v) {
    if (!v) return '';
    v = String(v).trim();
    if (!v.startsWith('#')) v = '#' + v;
    if (/^#[0-9a-fA-F]{3}$/.test(v)) {
      // #abc → #aabbcc
      return '#' + v.slice(1).split('').map(c => c + c).join('').toUpperCase();
    }
    if (/^#[0-9a-fA-F]{6}$/.test(v)) return v.toUpperCase();
    return '';
  }

  // ─── v34 — 브랜드 클래스 감지 ───
  //   element 의 class 중 'brand-musinsa' 같은 패턴이 있으면 브랜드 모드 진입.
  //   target_id = 'musinsa' (즉 brand- 접두 제거).
  // v34.7 — .brand-app-logo 패턴도 인식: <span class="brand-app-logo ssf"> → "ssf"
  const _BRAND_KEYS_APP_LOGO = new Set([
    // 마켓
    'smartstore', 'coupang', 'gmarket', 'auction', 'eleven', 'wemakeprice', 'tmon',
    'kakaogift', 'cafe24', 'naver',
    // 소싱처
    'musinsa', 'lemouton', 'ssf', 'lotteon', 'lotte', 'cm29', 'wconcept',
    'eqlnow', 'handsome', 'interpark', '29cm', 'ssg',
  ]);
  function _detectBrand(el) {
    if (!el) return null;
    // 자기 자신 + 가까운 brand 컨테이너 확인
    const node = el.closest('.brand-icon, .brand-favi, .brand-app-logo') || el;
    const cls = (node.className || '').split(/\s+/);
    // 우선 — brand-* 접두어 (기존 시스템)
    for (const c of cls) {
      if (c.startsWith('brand-') && c !== 'brand-icon' && c !== 'brand-favi' && c !== 'brand-card'
          && c !== 'brand-info' && c !== 'brand-name' && c !== 'brand-meta'
          && c !== 'brand-actions' && c !== 'brand-default' && c !== 'brand-app-logo') {
        return c.slice(6);  // 'brand-musinsa' → 'musinsa'
      }
    }
    // v34.7 — brand-app-logo 패턴: 같은 element 에 'ssf', 'musinsa' 같은 별도 key 클래스
    if (cls.includes('brand-app-logo')) {
      for (const c of cls) {
        if (_BRAND_KEYS_APP_LOGO.has(c)) return c;
      }
    }
    return null;
  }

  // ─── v34 — 동적 stylesheet 주입 (브랜드 색상 동기화) ───
  //   .brand-musinsa { background: ... !important; color: ... !important; }
  //   페이지 내 모든 브랜드 칩에 즉시 반영 + 새로고침 시 부트스트랩으로 다시 주입.
  function _ensureBrandStyle() {
    let s = document.getElementById('brand-overrides');
    if (!s) {
      s = document.createElement('style');
      s.id = 'brand-overrides';
      document.head.appendChild(s);
    }
    return s;
  }
  // brand 키 → {bg, fg} 메모리 캐시
  const _brandColorCache = {};
  function _applyBrandColor(brandKey, bg, fg) {
    if (bg) _brandColorCache[brandKey] = {bg, fg: fg || _brandColorCache[brandKey]?.fg || ''};
    else if (fg) _brandColorCache[brandKey] = {bg: _brandColorCache[brandKey]?.bg || '', fg};
    else delete _brandColorCache[brandKey];
    _rebuildBrandStyle();
  }
  function _rebuildBrandStyle() {
    const style = _ensureBrandStyle();
    const rules = [];
    for (const [key, val] of Object.entries(_brandColorCache)) {
      // v34.9 — 세 패턴 모두 매치:
      //   '.brand-ssf' (기존 brand pill)
      //   '.brand-app-logo.ssf' (sourcing·list 등 카드형)
      //   '.brand-favi.ssf' (매트릭스 헤더 카드의 favicon 컨테이너)
      const k = CSS.escape(key);
      const sel = `.brand-${k}, .brand-app-logo.${k}, .brand-favi.${k}`;
      const decls = [];
      if (val.bg) decls.push(`background: ${val.bg} !important`);
      if (val.fg) decls.push(`color: ${val.fg} !important`);
      if (decls.length) rules.push(`${sel} { ${decls.join('; ')}; }`);
    }
    style.textContent = rules.join('\n');
  }
  // 부트스트랩 — /api/icon/list 의 'brand' 컨텍스트 항목 적용
  // v34.9 — Fly.io 멀티 인스턴스 + 파일 시스템 분리 환경 안전망:
  //   - 페이지 HTML 응답 SSR stylesheet 는 항상 진실 (Flask context_processor 가 박음)
  //   - fetch /api/icon/list 가 다른 머신으로 가서 빈 응답일 수 있음 → SSR 덮어쓰면 색 사라짐
  //   - 따라서 응답이 비어있으면 SSR stylesheet 유지 (cache 갱신·rebuildStyle 호출 X)
  async function _bootstrapBrandColors() {
    try {
      const r = await fetch('/api/icon/list');
      if (!r.ok) return;  // 401/5xx → SSR fallback 유지
      const d = await r.json();
      const brandMap = (d.icons || {}).brand || {};
      const hasAnyData = Object.values(brandMap).some(e => e && (e.bg_color || e.fg_color));
      if (!hasAnyData) {
        // 응답에 brand 데이터 없음 — SSR stylesheet 유지 (덮어쓰지 않음).
        // 사용자가 진짜로 모든 색을 초기화했다면 다음 페이지 로드 시 SSR 가 빈 stylesheet 로 박힘.
        return;
      }
      // cache 전체 리셋 후 응답으로 채움 (응답이 진실 원천)
      Object.keys(_brandColorCache).forEach(k => delete _brandColorCache[k]);
      for (const [key, entry] of Object.entries(brandMap)) {
        if (entry && (entry.bg_color || entry.fg_color)) {
          _brandColorCache[key] = {bg: entry.bg_color || '', fg: entry.fg_color || ''};
        }
      }
      _rebuildBrandStyle();
    } catch (_) {
      // SSR 인라인 stylesheet 가 fallback. 추가 동작 불필요.
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _bootstrapBrandColors);
  } else {
    _bootstrapBrandColors();
  }
  // 외부에서 호출 가능 (테스트/SPA 전환)
  window.icpBootstrapBrandColors = _bootstrapBrandColors;

  let _activeColorPop = null;
  let _activeColorPopEscHandler = null;
  function _closeColorPop() {
    if (_activeColorPop) { _activeColorPop.remove(); _activeColorPop = null; }
    if (_activeColorPopEscHandler) {
      document.removeEventListener('keydown', _activeColorPopEscHandler);
      _activeColorPopEscHandler = null;
    }
  }
  function openColorPopover(trigger, anchorEvent) {
    _closeColorPop();
    const ctx = trigger.dataset.colorEdit || '';
    const [context, targetId] = ctx.split('|');

    // v34 — 브랜드 모드 진입 판정
    const brandKey = _detectBrand(trigger);
    const isBrand = !!brandKey;

    // 현재 색상 — 브랜드면 캐시에서, 아니면 computed
    let curBg, curFg;
    if (isBrand) {
      const cached = _brandColorCache[brandKey];
      const cs = getComputedStyle(trigger);
      curBg = cached?.bg || _rgb2hex(cs.backgroundColor) || '';
      curFg = cached?.fg || _rgb2hex(cs.color) || '';
    } else {
      const cs = getComputedStyle(trigger);
      curBg = trigger.dataset.bgColor || _rgb2hex(cs.backgroundColor) || '';
      curFg = trigger.dataset.fgColor || _rgb2hex(cs.color) || '';
    }

    const pop = document.createElement('div');
    pop.className = 'icp-color-pop icp-cp-v34';
    pop.innerHTML = `
      <div class="icp-cp-head">
        <span class="icp-cp-title">${isBrand ? `🏷 브랜드 색상 — ${escapeHtmlSafe(brandKey)}` : '🎨 색상 선택'}</span>
        ${isBrand ? `<small class="icp-cp-sub">프로그램 전체의 모든 "${escapeHtmlSafe(brandKey)}" 로고에 즉시 적용</small>` : ''}
      </div>

      <div class="icp-cp-section">
        <div class="icp-cp-row-label">🟦 바탕색</div>
        <div class="icp-cp-photo-host" data-target="bg"></div>
        <div class="icp-cp-grid">
          ${COLOR_PALETTE.map(c => `
            <button type="button" class="icp-cp-cell" data-target="bg" data-hex="${c.bg}" title="${c.label}"
                    style="background:${c.bg || 'transparent'};border:${c.bg ? 'none' : '1.5px dashed #B0B8C1'}">${c.bg ? '' : '⊘'}</button>
          `).join('')}
        </div>
        <div class="icp-cp-input-row">
          <input type="text" class="icp-cp-hex" data-target="bg" value="${curBg}" placeholder="#RRGGBB (비우면 기본)" maxlength="7">
          <span class="icp-cp-swatch" data-target="bg" style="background:${curBg}"></span>
        </div>
      </div>

      <div class="icp-cp-section">
        <div class="icp-cp-row-label">🅰 글자색</div>
        <div class="icp-cp-photo-host" data-target="fg"></div>
        <div class="icp-cp-grid">
          ${COLOR_PALETTE.map(c => `
            <button type="button" class="icp-cp-cell" data-target="fg" data-hex="${c.bg}" title="${c.label}"
                    style="background:${c.bg || 'transparent'};border:${c.bg ? 'none' : '1.5px dashed #B0B8C1'}">${c.bg ? '' : '⊘'}</button>
          `).join('')}
        </div>
        <div class="icp-cp-input-row">
          <input type="text" class="icp-cp-hex" data-target="fg" value="${curFg}" placeholder="#RRGGBB (비우면 기본)" maxlength="7">
          <span class="icp-cp-swatch" data-target="fg" style="background:${curFg}"></span>
        </div>
      </div>

      <div class="icp-cp-preview">
        <span class="icp-cp-preview-chip" style="background:${curBg || '#E5E8EB'};color:${curFg || '#191F28'}">${isBrand ? escapeHtmlSafe(brandKey) : '미리보기'}</span>
        <div class="icp-cp-acts">
          <small class="icp-cp-auto-hint">변경 즉시 자동 저장</small>
          <button type="button" class="icp-cp-reset" title="원래대로 (저장 해제)">초기화</button>
          <button type="button" class="icp-cp-apply" title="닫기 (변경은 이미 저장됨)">완료</button>
        </div>
      </div>
    `;
    // 위치 결정 — 트리거 아래, 화면 밖 방지
    const r = trigger.getBoundingClientRect();
    pop.style.position = 'fixed';
    pop.style.top = (r.bottom + 6) + 'px';
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 440)) + 'px';
    pop.style.zIndex = '9100';
    document.body.appendChild(pop);
    _activeColorPop = pop;

    // 현재 선택 상태 (모달 내 임시)
    const state = {bg: curBg, fg: curFg};

    function updatePreview() {
      const chip = pop.querySelector('.icp-cp-preview-chip');
      chip.style.background = state.bg || '#E5E8EB';
      chip.style.color = state.fg || '#191F28';
      pop.querySelectorAll('.icp-cp-swatch').forEach(s => {
        s.style.background = state[s.dataset.target] || '';
      });
      pop.querySelectorAll('.icp-cp-cell').forEach(c => {
        const t = c.dataset.target, hex = (c.dataset.hex || '').toUpperCase();
        c.classList.toggle('on', hex === (state[t] || '').toUpperCase());
      });
    }
    updatePreview();

    // v34.4 — 자동 적용 함수: 「적용」 버튼 없이도 변경 즉시 서버 저장·실 칩 동기화.
    //   debounce 250ms — 드래그·연속 타이핑 중 호출 폭주 방지.
    let _autoApplyTimer = null;
    function _autoApply() {
      if (_autoApplyTimer) clearTimeout(_autoApplyTimer);
      _autoApplyTimer = setTimeout(async () => {
        const bg = state.bg || null;
        const fg = state.fg || null;
        if (isBrand) {
          _applyBrandColor(brandKey, bg, fg);
          try {
            await fetch('/api/icon/set', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                context: 'brand', target_id: brandKey,
                icon: brandKey, color: bg || 'default',
                bg_color: bg, fg_color: fg,
              }),
            });
          } catch(_) {}
        } else {
          trigger.dataset.bgColor = bg || '';
          trigger.dataset.fgColor = fg || '';
          trigger.style.backgroundColor = bg || '';
          trigger.style.color = fg || '';
          try {
            await fetch('/api/icon/set', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                context: 'color:' + (context || ''), target_id: targetId || '',
                icon: 'custom', color: bg || 'default',
                bg_color: bg, fg_color: fg,
              }),
            });
          } catch(_) {}
        }
      }, 250);
    }

    // v34.3 — 포토샵식 photoPicker 인스턴스 (target 별)
    const photoPickers = {};
    ['bg', 'fg'].forEach(t => {
      const host = pop.querySelector(`.icp-cp-photo-host[data-target="${t}"]`);
      if (!host) return;
      const initial = state[t] || (t === 'bg' ? '#3182F6' : '#FFFFFF');
      const pp = _createPhotoPicker(initial, (hex) => {
        // 드래그 중 — 미리보기 + debounced 자동 적용
        state[t] = hex;
        const inp = pop.querySelector(`.icp-cp-hex[data-target="${t}"]`);
        if (inp) inp.value = hex;
        updatePreview();
        _autoApply();  // debounce → 드래그 끝나면 250ms 후 한 번만 발사
      });
      host.appendChild(pp.el);
      photoPickers[t] = pp;
    });

    // 프리셋 클릭 — 미리보기 + photoPicker 위치 + 자동 적용
    pop.querySelectorAll('.icp-cp-cell').forEach(b => b.addEventListener('click', e => {
      e.stopPropagation();
      const t = b.dataset.target;
      state[t] = b.dataset.hex || '';
      const inp = pop.querySelector(`.icp-cp-hex[data-target="${t}"]`);
      if (inp) inp.value = state[t];
      if (state[t] && photoPickers[t]) photoPickers[t].setHex(state[t]);
      updatePreview();
      _autoApply();
    }));

    // HEX 입력 — 정상 6자리 입력 시 자동 적용 (입력 중 debounce 로 처리)
    pop.querySelectorAll('.icp-cp-hex').forEach(h => {
      h.addEventListener('input', e => {
        e.stopPropagation();
        const t = h.dataset.target;
        const v = _normHex(h.value);
        if (h.value.trim() === '') {
          state[t] = '';
          updatePreview();
          _autoApply();
          return;
        }
        if (v) {
          state[t] = v;
          if (photoPickers[t]) photoPickers[t].setHex(v);
          updatePreview();
          _autoApply();
        }
      });
      h.addEventListener('click', e => e.stopPropagation());
    });

    // 적용
    pop.querySelector('.icp-cp-apply').addEventListener('click', async e => {
      e.stopPropagation();
      const bg = state.bg || null;
      const fg = state.fg || null;
      if (isBrand) {
        _applyBrandColor(brandKey, bg, fg);
        try {
          await fetch('/api/icon/set', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              context: 'brand', target_id: brandKey,
              icon: brandKey, color: bg || 'default',
              bg_color: bg, fg_color: fg,
            }),
          });
        } catch(_) {}
      } else {
        // 위치별 개별 적용 — 기존 호환
        trigger.dataset.bgColor = bg || '';
        trigger.dataset.fgColor = fg || '';
        trigger.style.backgroundColor = bg || '';
        trigger.style.color = fg || '';
        try {
          await fetch('/api/icon/set', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              context: 'color:' + (context || ''),
              target_id: targetId || '',
              icon: 'custom', color: bg || 'default',
              bg_color: bg, fg_color: fg,
            }),
          });
        } catch(_) {}
      }
      _closeColorPop();
    });

    // 초기화 — 저장된 override 해제
    pop.querySelector('.icp-cp-reset').addEventListener('click', async e => {
      e.stopPropagation();
      if (isBrand) {
        _applyBrandColor(brandKey, null, null);
        try {
          await fetch('/api/icon/set', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              context: 'brand', target_id: brandKey,
              icon: null, color: null,
              bg_color: null, fg_color: null,
            }),
          });
        } catch(_) {}
      } else {
        trigger.dataset.bgColor = '';
        trigger.dataset.fgColor = '';
        trigger.style.backgroundColor = '';
        trigger.style.color = '';
      }
      _closeColorPop();
    });

    // popover 내부 클릭은 닫지 않음
    pop.addEventListener('click', e => e.stopPropagation());

    // v34.2 — 외부 클릭 닫기 제거. 이유: native color picker(hue 슬라이더·SV 평면)
    //   의 클릭이 document 까지 bubble 되어 popover 가 의도치 않게 닫히는 문제 해결.
    //   닫기 방법: 「적용」 / 「초기화」 버튼, ESC 키, 또는 새 popover 열기 (자동 닫힘).
    _activeColorPopEscHandler = (e) => {
      if (e.key === 'Escape' || e.key === 'Esc') { e.preventDefault(); _closeColorPop(); }
    };
    document.addEventListener('keydown', _activeColorPopEscHandler);
  }

  // rgb(r,g,b) → #RRGGBB
  function _rgb2hex(rgb) {
    if (!rgb) return '';
    if (rgb.startsWith('#')) return rgb.toUpperCase();
    const m = rgb.match(/rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (!m) return '';
    return '#' + [m[1], m[2], m[3]].map(n => parseInt(n, 10).toString(16).padStart(2, '0')).join('').toUpperCase();
  }

  function escapeHtmlSafe(s) {
    return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // 우클릭 → color popover
  document.addEventListener('contextmenu', e => {
    const trigger = e.target.closest('[data-color-edit]');
    if (!trigger) return;
    e.preventDefault(); e.stopPropagation();
    openColorPopover(trigger, e);
  });
  // 호버 → 🎨 mini 버튼 — v33.1: 1000ms 딜레이 (UX 안정성)
  const _colHoverTimers = new WeakMap();
  document.addEventListener('mouseover', e => {
    const t = e.target.closest('[data-color-edit]');
    if (!t || t.querySelector('.icp-color-btn')) return;
    if (_colHoverTimers.get(t)) return;
    const tid = setTimeout(() => {
      _colHoverTimers.delete(t);
      if (t.querySelector('.icp-color-btn')) return;
      if (!document.body.contains(t)) return;
      if (!t.matches(':hover')) return;
      const btn = document.createElement('button');
      btn.className = 'icp-color-btn';
      btn.type = 'button';
      btn.title = '색상 변경 (또는 우클릭)';
      btn.textContent = '🎨';
      btn.addEventListener('click', evt => { evt.preventDefault(); evt.stopPropagation(); openColorPopover(t, evt); });
      btn.addEventListener('mousedown', evt => { evt.preventDefault(); evt.stopPropagation(); });
      t.appendChild(btn);
    }, HOVER_DELAY_MS);
    _colHoverTimers.set(t, tid);
  });
  document.addEventListener('mouseout', e => {
    const t = e.target.closest('[data-color-edit]');
    if (!t || t.contains(e.relatedTarget)) return;
    const tid = _colHoverTimers.get(t);
    if (tid) { clearTimeout(tid); _colHoverTimers.delete(t); }
    const b = t.querySelector('.icp-color-btn');
    if (b) b.remove();
  });

  // 색상 박스 auto-discovery — known class 가진 chip/badge
  const COLOR_BOX_SELECTORS = [
    '.brand-app-logo',     // v34.7 — 마켓·소싱처 박스 (sourcing/list/upload 도처) — brand-app-logo.ssf 등
    '.brand-icon',         // 브랜드 풀네임 칩 (brand-musinsa 등)
    '.brand-favi',         // 브랜드 favicon container
    '.m4v1-pri',           // 매트릭스 우선 chip (소싱/사입)
    '.applied-badge',      // ✓ 적용 뱃지
    '.m4v1-stock-chip',    // 재고 chip
    '.m4v1-inv-link',      // + 재고관리 link
    '.hub-hero-cnt',       // hero 카운트 chip
    '.hub-cnt',            // hub 카운트
    '.bl-mkt',             // 모음전 row 마켓 chip
    '.bl-mkt-chip',
    '.bl-cluster',         // cluster 뱃지
    '.bp-opt',             // 가격 정책 opt
    '.cell-fx-pop .pop-add',
    '.cell-fx-row .badge',
    '.tree-stock-chip',    // 트리 재고 chip
    '.tree-grp-stock',     // 그룹 합산
    '.sb3-item .badge',    // 사이드바 뱃지
    '.b1-side-h .scell .pct',
    // v32 추가 — 마켓 라벨 (N 스마트스토어 / 쿠팡 등)
    '.mkt-badge', '.mkt-chip', '.market-label',
    '.m4v1-mkt-logo',      // 매트릭스 마켓 로고 N
    '.brand-favi',         // brand favicon container
    '.m4-mkt-prefix',      // 마켓 prefix
    // KPI 카드 색상 박스
    '.kpi-card', '.kpi-box', '.kpi-bg',
    // 홈 ribbon, status 뱃지 등
    '.home-ribbon', '.status-badge', '.pri-chip',
    '.pi',                 // Phosphor icon container
    // v33 — matrix v3 동적 셀/칩/뱃지
    '.mc-icon',            // 마켓 셀 컬러 prefix (.ss 초록 / .cp 주황)
    '.chip-auto',          // AUTO 칩 (파랑 계열)
    '.chip-manual',        // 수기 칩 (회색)
    '.bp-chip',            // 정책 칩 (다채로움)
    '.scell',              // 사이트 칸 (상태별 컬러)
    '.scell .top',         // 사이트 헤더 영역
    '.iad-save-badge',     // 자동 저장 뱃지 (대기/저장됨)
    '.iad-dot',            // 자동 저장 dot
    '.odd-chip',           // INV 드로어 상태 칩
    '.odd-chip.green',     // ✓ 연동 (초록)
    '.scope-badge',        // 적용 범위 카운터
    '.scope-badge.sel-ct', // 선택 카운터
    '.cf-card-chip',       // 카드 칩
    '.key-chip',           // 키 색상 칩
    '.group-badge',        // 그룹 헤더 뱃지
    '.chip-color',         // 색상 dot
    '.cell-price',         // 셀 가격 박스
    '.amount-auto',        // 자동 가격 강조
    '.mc-margin',          // 마진 % 칩
    '.unit-text',          // 단위 (원)
    '.m4v1-mkt-name',      // 매트릭스 마켓 이름
    '.m4v1-mkt-price',     // 매트릭스 마켓 가격
    '.m4v1-mkt-margin',    // 매트릭스 마켓 마진
    '.m4v1-head',          // 매트릭스 head
    '.d2-src-status-error',
    '.d2-src-empty',
    '.btn-ico', '.btn-icon',  // 셀 인라인 액션 버튼 (🔄 ✎ 🗑 ↗)
  ];
  function autoDetectColors() {
    COLOR_BOX_SELECTORS.forEach(sel => {
      document.querySelectorAll(sel).forEach(el => {
        if (el.hasAttribute('data-color-edit')) return;
        if (el.hasAttribute('data-color-no-edit')) return;
        if (el.closest('.icp-overlay, .icp-color-pop, .sb3-modal-overlay')) return;
        const cur = getComputedStyle(el).backgroundColor;
        const ctxKey = el.className.split(' ')[0] || 'box';
        const idKey = (el.textContent || '').trim().slice(0, 20) || 'unk';
        el.setAttribute('data-color-edit', ctxKey + '|' + idKey);
        el.setAttribute('data-color-current', cur);
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoDetectColors);
  } else {
    autoDetectColors();
  }
  window.icpAutoDetectColors = autoDetectColors;

  // ═══════════════════════════════════════════════════════════════
  // v33 — MutationObserver: matrix v3 등 동적 렌더 노드 자동 감지
  //   loadMatrix() 가 끝나도 별도 호출 없이 새 셀/칩/뱃지에 trigger 자동 부여.
  //   debounce 80ms — 연속 추가 시 한 번에 처리.
  // ═══════════════════════════════════════════════════════════════
  let _icpReDetectTimer = null;
  function _scheduleReDetect() {
    if (_icpReDetectTimer) return;
    _icpReDetectTimer = setTimeout(() => {
      _icpReDetectTimer = null;
      try { autoDetect(); } catch(_) {}
      try { autoDetectColors(); } catch(_) {}
    }, 80);
  }
  function _startObserver() {
    if (!document.body || window.__icpObserverOn) return;
    window.__icpObserverOn = true;
    const obs = new MutationObserver(muts => {
      // 의미 있는 추가/변경만 트리거 (텍스트 변경·data-icon-edit 자가 부착 무시)
      for (const m of muts) {
        if (m.type === 'childList' && (m.addedNodes.length > 0 || m.removedNodes.length > 0)) {
          // 아이콘 picker 가 자신의 ✎/🎨 버튼을 붙이는 경우 제외
          let onlyOwnNodes = true;
          for (const n of m.addedNodes) {
            if (n.nodeType !== 1) { onlyOwnNodes = false; break; }
            if (!n.classList || (!n.classList.contains('icp-edit-btn') && !n.classList.contains('icp-color-btn'))) {
              onlyOwnNodes = false; break;
            }
          }
          if (!onlyOwnNodes) { _scheduleReDetect(); return; }
        }
      }
    });
    obs.observe(document.body, {childList: true, subtree: true});
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _startObserver);
  } else {
    _startObserver();
  }

})();

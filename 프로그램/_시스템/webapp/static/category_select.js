/* 카테고리 선택 — '+ 새 카테고리' 직접 입력 위젯.
   <select data-category-add> 에 자동 적용.
   select 가 canonical element 로 유지되므로 .value / name 기반 폼 수집이 그대로 동작한다.
   (입력값은 select 안의 임시 <option> 에 담겨 select.value 로 노출됨) */
(function () {
  'use strict';
  var NEW_VALUE = '__newcat__';

  function enhance(select) {
    if (select.dataset.catEnhanced) return;
    select.dataset.catEnhanced = '1';

    // '+ 새 카테고리' 옵션
    var newOpt = document.createElement('option');
    newOpt.value = NEW_VALUE;
    newOpt.textContent = '+ 새 카테고리…';
    select.appendChild(newOpt);

    // 직접 입력 UI (select 바로 뒤)
    var wrap = document.createElement('span');
    wrap.style.cssText = 'display:none;gap:6px;align-items:center';

    var input = document.createElement('input');
    input.type = 'text';
    input.className = select.className;          // field-input 등 동일 스타일
    input.placeholder = '새 카테고리명 입력';
    input.style.cssText = 'flex:1;width:auto;min-width:0';

    var back = document.createElement('button');
    back.type = 'button';
    back.textContent = '↩ 목록';
    back.style.cssText = 'white-space:nowrap;padding:8px 12px;border:1px solid var(--n300,#D1D6DB);' +
      'background:#fff;border-radius:8px;cursor:pointer;font-family:inherit;font-size:14px;color:var(--n600,#6B7684)';

    wrap.appendChild(input);
    wrap.appendChild(back);
    select.parentNode.insertBefore(wrap, select.nextSibling);

    // 입력값을 담는 임시 option (select.value 노출용)
    var tempOpt = null;
    var inNewMode = false;

    function ensureTemp() {
      if (!tempOpt) {
        tempOpt = document.createElement('option');
        tempOpt.dataset.catTemp = '1';
        select.insertBefore(tempOpt, newOpt);
      }
      return tempOpt;
    }

    function enterNewMode() {
      inNewMode = true;
      ensureTemp();
      tempOpt.value = '';
      tempOpt.textContent = '(새 카테고리)';
      select.value = '';
      select.style.display = 'none';
      wrap.style.display = 'flex';
      input.value = '';
      input.focus();
    }

    function exitNewMode() {
      inNewMode = false;
      if (tempOpt) { select.removeChild(tempOpt); tempOpt = null; }
      wrap.style.display = 'none';
      select.style.display = '';
      select.selectedIndex = 0;                  // 첫 실제 카테고리로 복귀
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    select.addEventListener('change', function () {
      if (inNewMode) return;
      if (select.value === NEW_VALUE) enterNewMode();
    });

    input.addEventListener('input', function () {
      var v = input.value.trim();
      ensureTemp();
      tempOpt.value = v;
      tempOpt.textContent = v || '(새 카테고리)';
      select.value = v;
      // 외부 autosave/draft 가 select 변경을 감지하도록 알림
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });

    back.addEventListener('click', exitNewMode);
  }

  function init() {
    var list = document.querySelectorAll('select[data-category-add]');
    for (var i = 0; i < list.length; i++) enhance(list[i]);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

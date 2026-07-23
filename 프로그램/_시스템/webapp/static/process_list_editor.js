/* 가공 규칙 「목록형 칸」 붙여넣기 해석기.
 *
 * 하는 일은 딱 하나 — **클립보드 글자를 줄·칸으로 쪼개는 것**.
 *   · 엑셀에서 복사하면 열은 탭(\t), 행은 줄바꿈(\r\n)으로 온다.
 *   · 쉼표·따옴표가 든 칸은 엑셀이 "..." 로 감싸고 안쪽 따옴표를 "" 로 겹쳐 보낸다.
 *
 * ★ 여기서 「값이 옳은지」는 판단하지 않는다. 검사는 서버 validate_config 한 벌뿐이다
 *   (중복·모순 금지). 화면은 서버가 돌려준 알림을 보여주기만 한다.
 *
 * 브라우저에서는 window.ListEditor, 테스트(node)에서는 require 로 쓴다.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
  if (root) { root.ListEditor = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function splitLines(text) {
    return String(text == null ? '' : text).split(/\r\n|\r|\n/);
  }

  /** 엑셀이 감싼 따옴표를 벗긴다. `"팬""다"` → `팬"다` */
  function dequote(cell) {
    var s = String(cell == null ? '' : cell);
    if (s.length >= 2 && s.charAt(0) === '"' && s.charAt(s.length - 1) === '"') {
      s = s.slice(1, -1).replace(/""/g, '"');
    }
    return s;
  }

  /** 1열 목록 — 글이 적힌 줄만 골라낸다.
   *
   * ★ 화면 카운터(「지금 N줄」)가 이걸 쓴다. **따옴표를 벗기지 않는다** —
   *   서버 검사(_clean_text_list)도 안 벗기기 때문이다. 화면이 서버와 다르게
   *   세면 「지금 2줄인데 3개 저장됨」 처럼 어긋난다.
   *   저장된 **개수**는 언제나 서버 응답에서만 가져온다.
   */
  function parseLines(text) {
    return splitLines(text)
      .map(function (line) { return line.trim(); })
      .filter(function (line) { return line !== ''; });
  }

  /** 한 줄에 적힌 게 있나? (양쪽 칸이 다 비면 '빈 입력줄') */
  function hasContent(row) {
    var a = (row && row[0] != null) ? String(row[0]) : '';
    var b = (row && row[1] != null) ? String(row[1]) : '';
    return a.trim() !== '' || b.trim() !== '';
  }

  /** 표에는 **늘 한 줄은** 있어야 한다 — 줄이 없으면 붙여넣을 칸조차 없다. */
  function atLeastOneRow(rows) {
    return (rows && rows.length) ? rows : [['', '']];
  }

  /** 아직 아무것도 안 적은 **빈 입력줄**은 값이 아니라 빈 폼이라 서버로 안 보낸다.
   *  한쪽만 적힌 줄은 **그대로 보낸다** — 옳고 그름은 서버가 판정한다. */
  function formRowsToSend(rows) {
    return (rows || []).filter(hasContent);
  }

  /** 붙여넣은 줄들을 표 어디에 끼울지 정한다 (순수 계산 — DOM 은 안 건드린다).
   *  · 커서가 있던 줄 자리에 끼운다.
   *  · 그 줄이 비어 있었으면 없앤다 — 빈 줄을 대신 채운 셈이 된다. */
  function planPaste(rows, focusIndex, pasted) {
    var out = (rows || []).map(function (r) { return [r[0], r[1]]; });
    var inside = focusIndex >= 0 && focusIndex < out.length;
    var at = inside ? focusIndex : out.length;
    if (inside && !hasContent(out[focusIndex])) { out.splice(focusIndex, 1); }
    return out.slice(0, at).concat(pasted || [], out.slice(at));
  }

  /** 2열 표 — [찾을 말, 바꿀 말] 행 목록. 탭이 없으면 두 번째 칸은 빈 칸. */
  function parseTable(text) {
    var rows = [];
    splitLines(text).forEach(function (line) {
      if (line.trim() === '') { return; }
      var cells = line.split('\t').map(dequote);
      var a = (cells[0] || '').trim();
      var b = (cells[1] || '').trim();
      if (a === '' && b === '') { return; }
      rows.push([a, b]);
    });
    return rows;
  }

  /** 표·여러 줄로 붙여넣은 것인가? 단어 하나면 평범한 붙여넣기로 둔다. */
  function looksTabular(text) {
    var s = String(text == null ? '' : text);
    return s.indexOf('\t') >= 0 || /[\r\n]/.test(s.trim());
  }

  return {
    splitLines: splitLines,
    parseLines: parseLines,
    parseTable: parseTable,
    looksTabular: looksTabular,
    hasContent: hasContent,
    atLeastOneRow: atLeastOneRow,
    formRowsToSend: formRowsToSend,
    planPaste: planPaste
  };
});

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

  /** 1열 목록 — 한 줄에 하나. 빈 줄과 앞뒤 공백은 버린다. */
  function parseLines(text) {
    return splitLines(text)
      .map(function (line) { return dequote(line).trim(); })
      .filter(function (line) { return line !== ''; });
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
    looksTabular: looksTabular
  };
});

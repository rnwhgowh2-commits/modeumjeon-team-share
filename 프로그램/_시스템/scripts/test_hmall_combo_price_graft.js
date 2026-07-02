/** 현대H몰 색상모음전(2축) per-size 옵션 색별 가격 이식 회귀 테스트.
 *   node test_hmall_combo_price_graft.js
 *
 * 배경(2026-07-02): 색상모음전은 사이즈별 재고를 item-stockcount API 로 긁는데 이 API 는
 *   재고만 주고 가격=0(sellPrc=0) 이다. 확장(background.js)이 per-size 옵션의 price 를
 *   sellPrc(=0) 그대로 채워 → 'price>0 인 옵션 0개' → price=null → status=error("옵션
 *   가격 없음") → 크롤 위젯에 빨간 '크롤실패'로 뜬다. 그러나 서버 save_crawl_result 는
 *   fetch_combo_persize_options 로 베이스 페이지 표면가를 색별 병합해 이미 정상 저장한다
 *   (last_status=ok, 126900) → 데이터는 옳고 위젯만 거짓(false-negative).
 *   해법: 확장도 색-레벨 parse 옵션(각 색 표면가 보유)에서 색별 가격을 per-size 옵션에
 *   이식한다(서버 build_combo_persize_options 의 color_price 병합과 대칭). 아래는 그
 *   순수함수(graftComboColorPrices) 를 background.js 와 동일하게 잠근다.
 */

// ── background.js graftComboColorPrices 와 동일(로직 락) ──
function graftComboColorPrices(parseOptions, perSizeOptions) {
  if (!Array.isArray(perSizeOptions) || !perSizeOptions.length) return perSizeOptions;
  const hasPrice = (o) => o && typeof o.price === "number" && o.price > 0;
  if (perSizeOptions.every(hasPrice)) return perSizeOptions; // 이미 다 가격 있음 → 무변경
  const colorPrice = {};
  let anyPrice = null;
  for (const o of (parseOptions || [])) {
    if (hasPrice(o)) {
      const c = (o.color_text || "").trim();
      if (c && !(c in colorPrice)) colorPrice[c] = o.price;
      if (anyPrice == null) anyPrice = o.price;
    }
  }
  if (anyPrice == null) return perSizeOptions; // 이식할 가격 없음 → 조작 금지(원본 유지)
  for (const o of perSizeOptions) {
    if (!hasPrice(o)) {
      const c = (o.color_text || "").trim();
      const pr = (c && colorPrice[c] != null) ? colorPrice[c] : anyPrice;
      o.price = pr; o.sale_price = pr;
    }
  }
  return perSizeOptions;
}

// crawlItemInTabBG 의 가격 산출(동일): priced>buyable>pool → min. price==null → status=error.
function extPriceOk(opts) {
  const priced = opts.filter((o) => o && typeof o.price === "number" && o.price > 0);
  const buyable = priced.filter((o) => (o.stock == null) || o.stock > 0);
  const pool = buyable.length ? buyable : priced;
  let price = null;
  if (pool.length) price = pool.reduce((m, o) => (o.price < m ? o.price : m), pool[0].price);
  return { price: price, ok: price != null };
}

let fail = 0;
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) { console.log(`   got ${JSON.stringify(got)} want ${JSON.stringify(want)}`); fail++; }
};

// 색-레벨 parse 옵션(hmall.py parse_html 이 combo 페이지에서 만드는 형태) — 각 색 표면가 126900
const parseOpts = [
  { color_text: "블랙", size_text: "", price: 126900 },
  { color_text: "다크네이비", size_text: "", price: 126900 },
];
// per-size 옵션(item-stockcount) — 가격 0(=크롤실패 유발), 재고 3상태
const mkPerSize = () => [
  { color_text: "블랙", size_text: "250", price: 0, stock: 5 },
  { color_text: "블랙", size_text: "260", price: 0, stock: 0 },   // 품절
  { color_text: "다크네이비", size_text: "270", price: 0, stock: 999 },
];

// 1) 버그 재현 — 이식 전엔 가격 없음 → status=error(거짓 크롤실패)
eq("이식 전: 확장이 price=null → 크롤실패(버그 재현)", extPriceOk(mkPerSize()).ok, false);

// 2) 이식 후 — 색별 가격이 붙어 status=ok
const grafted = graftComboColorPrices(parseOpts, mkPerSize());
eq("이식 후: 블랙 250 price=126900", grafted[0].price, 126900);
eq("이식 후: 블랙 250 sale_price=126900", grafted[0].sale_price, 126900);
eq("이식 후: 다크네이비 270 price=126900", grafted[2].price, 126900);
eq("이식 후: 재고 유지(블랙 260 품절=0)", grafted[1].stock, 0);
eq("이식 후: 확장 price 산출 성공 → ok", extPriceOk(grafted).ok, true);
eq("이식 후: 표면가 = 색별 최저 126900", extPriceOk(grafted).price, 126900);

// 3) 색 이름이 parse 에 없으면 anyPrice 폴백(색 라벨 표기 흔들려도 크롤실패 방지)
const g3 = graftComboColorPrices(parseOpts, [{ color_text: "그레이", size_text: "255", price: 0, stock: 3 }]);
eq("색 미매칭 → anyPrice(126900) 폴백", g3[0].price, 126900);

// 4) 이미 가격 있는 옵션(단품 등)은 무변경 — 오염 금지
const priced = [{ color_text: "블랙", size_text: "250", price: 111111, stock: 5 }];
eq("이미 가격 있으면 무변경", graftComboColorPrices(parseOpts, priced)[0].price, 111111);

// 5) 이식할 가격이 아예 없으면(모든 parse 옵션 가격 0) 조작 금지 — 폴백가 날조 금지
const g5 = graftComboColorPrices([{ color_text: "블랙", price: 0 }], [{ color_text: "블랙", size_text: "250", price: 0, stock: 5 }]);
eq("이식 소스 가격 전무 → 원본 유지(0, 날조 금지)", g5[0].price, 0);
eq("이식 소스 가격 전무 → 여전히 status=error(정직한 실패)", extPriceOk(g5).ok, false);

console.log(fail === 0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail === 0 ? 0 : 1);

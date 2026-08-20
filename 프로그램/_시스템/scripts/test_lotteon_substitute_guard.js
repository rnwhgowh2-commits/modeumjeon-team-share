/**
 * 롯데온 대체상품(substitute) 재고 가드 회귀 테스트.
 *
 * 배경(2026-06-24): 르무통 메이트 모음전 롯데온(1) 단품에서 품절 사이즈(265/275/280)가
 *   매트릭스에 '4개/있음' 으로 새어나옴. 원인 = lotteonExtractor 의 대체상품 가드가
 *   _realSpd 를 `/product/(LO[0-9]+)` 로만 추출 → 'LO' 없는 숫자형 상품
 *   (예: /p/product/2673780784, sitmNo=2673780784_2673780785)은 _realSpd="" →
 *   _isSub 항상 false → 품절 슬롯에 끼워진 대체상품(spdNo 다름·SALE·stkQty>0) 재고가
 *   그대로 노출.
 *
 * 이 테스트는 가드 계산만 순수 함수로 추출해 OLD 가 버그를, NEW 가 수정을 증명한다.
 * 실행: node test_lotteon_substitute_guard.js  (종료코드 0 = PASS)
 */

// ── 가드 로직(추출판) ──────────────────────────────────────────
//   skuStock: SALE 이고 stkQty>0 이면 실수량, 아니면 0(품절).
const skuStock = (sku) => {
  const sale = sku && sku.sitmNoSlStatCd === "SALE";
  const q = Number(sku && sku.stkQty);
  return (sale && q > 0) ? q : 0;
};

// OLD — 현재(버그) 가드: LO 접두 하드코딩 + 대문자 문자열 비교.
function buildStocksOLD(pathname, omi, colorOpts, sizeOpts) {
  const _realSpd = ((pathname.match(/\/product\/(LO[0-9]+)/i) || [])[1] || "").toUpperCase();
  const out = {};
  for (const c of colorOpts) {
    for (const s of sizeOpts) {
      const key = (c.value || "") + "_" + (s.value || "");
      const sku = omi[key] || (!c.value ? omi[s.value] : null);
      if (!sku) continue;
      const size = (s.label || "").replace(/mm/i, "").trim();
      if (!size) continue;
      const _isSub = _realSpd && sku.spdNo && String(sku.spdNo).toUpperCase() !== _realSpd;
      out[size] = _isSub ? 0 : skuStock(sku);
    }
  }
  return out;
}

// NEW — 강건 가드: mapUrl 과 동일한 범용 패턴 + 숫자만 비교 + 최빈 spdNo 폴백.
function buildStocksNEW(pathname, omi, colorOpts, sizeOpts) {
  const _digitsOnly = (x) => String(x == null ? "" : x).replace(/\D/g, "");
  let _realSpd = _digitsOnly((pathname.match(/\/product\/([A-Za-z0-9]+)/) || [])[1] || "");
  {
    const _spdCount = {};
    for (const v of Object.values(omi)) {
      const sp = _digitsOnly(v && v.spdNo);
      if (sp) _spdCount[sp] = (_spdCount[sp] || 0) + 1;
    }
    if (!_realSpd || !_spdCount[_realSpd]) {
      const _modal = Object.keys(_spdCount).sort((a, b) => _spdCount[b] - _spdCount[a])[0];
      if (_modal) _realSpd = _modal;
    }
  }
  const out = {};
  for (const c of colorOpts) {
    for (const s of sizeOpts) {
      const key = (c.value || "") + "_" + (s.value || "");
      const sku = omi[key] || (!c.value ? omi[s.value] : null);
      if (!sku) continue;
      const size = (s.label || "").replace(/mm/i, "").trim();
      if (!size) continue;
      const _isSub = _realSpd && sku.spdNo && _digitsOnly(sku.spdNo) !== _realSpd;
      out[size] = _isSub ? 0 : skuStock(sku);
    }
  }
  return out;
}

// ── 픽스처 ────────────────────────────────────────────────────
// 단품(단일색) 메이트: color value "" / 사이즈 4개. 255=실재고10, 260=진짜품절(non-SALE),
//   265=품절이라 대체상품(spdNo 다름·SALE·4개) 끼워짐, 270=실재고10.
const colorOpts = [{ value: "", label: "" }];
const sizeOpts = [
  { value: "255", label: "255" },
  { value: "260", label: "260" },
  { value: "265", label: "265" },
  { value: "270", label: "270" },
];
const REAL = "2673780784";   // 리스팅 진짜 상품 spdNo (숫자형)
const SUB = "9988776655";    // 대체상품 spdNo
function omiFixture() {
  return {
    "_255": { spdNo: REAL, sitmNoSlStatCd: "SALE", stkQty: 10 },
    "_260": { spdNo: REAL, sitmNoSlStatCd: "SOLDOUT", stkQty: 0 },
    "_265": { spdNo: SUB, sitmNoSlStatCd: "SALE", stkQty: 4 },   // 대체상품 누출 후보
    "_270": { spdNo: REAL, sitmNoSlStatCd: "SALE", stkQty: 10 },
  };
}

let failures = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) { console.log(`   got : ${JSON.stringify(got)}`); console.log(`   want: ${JSON.stringify(want)}`); failures++; }
}

// 1) 숫자형 URL — OLD 는 265 에 대체재고 4개가 새어나와야(버그 재현).
check("OLD numeric-form leaks substitute (265=4, BUG)",
  buildStocksOLD("/p/product/2673780784", omiFixture(), colorOpts, sizeOpts),
  { "255": 10, "260": 0, "265": 4, "270": 10 });

// 2) 숫자형 URL — NEW 는 265=0(품절) 로 막아야(수정 증명).
check("NEW numeric-form blocks substitute (265=0, FIXED)",
  buildStocksNEW("/p/product/2673780784", omiFixture(), colorOpts, sizeOpts),
  { "255": 10, "260": 0, "265": 0, "270": 10 });

// 3) LO 접두 URL + API spdNo 는 숫자형 — OLD 는 전부 0 으로 과차단(잠재 버그).
const REAL_DIGITS = "2158462914";
function omiLO() {
  return {
    "_255": { spdNo: REAL_DIGITS, sitmNoSlStatCd: "SALE", stkQty: 10 },
    "_265": { spdNo: SUB, sitmNoSlStatCd: "SALE", stkQty: 4 },
  };
}
const sizeOptsLO = [{ value: "255", label: "255" }, { value: "265", label: "265" }];
check("OLD LO-form over-zeros real stock (255=0, latent BUG)",
  buildStocksOLD("/p/product/LO2158462914", omiLO(), colorOpts, sizeOptsLO),
  { "255": 0, "265": 0 });

// 4) LO 접두 URL — NEW 는 진짜는 살리고 대체만 차단.
check("NEW LO-form keeps real, blocks substitute (255=10, 265=0)",
  buildStocksNEW("/p/product/LO2158462914", omiLO(), colorOpts, sizeOptsLO),
  { "255": 10, "265": 0 });

console.log(failures === 0 ? "\nALL PASS" : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);

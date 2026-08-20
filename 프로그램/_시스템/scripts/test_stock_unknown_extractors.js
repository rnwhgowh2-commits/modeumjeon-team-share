/** 재고 '불명(-1)' 추출 규칙 회귀 테스트. node test_stock_unknown_extractors.js
 *
 * 배경(2026-06-24): 크롤러가 재고 신호를 못 읽으면 999(충분)로 둔갑 → 품절/한정이
 *   '있음'으로 떠 손실. 규칙을 뒤집어 "못 읽으면 -1(불명, 서버가 ⚠️확인필요·수량0)".
 *   확장(background.js) 추출기의 stock 산출 규칙을 순수함수로 추출해 잠근다.
 */

// 무신사 stock 규칙(musinsaExtractor 와 동일): 호출실패/미매칭→-1, 품절→0, 수량→N, 그 외 충분→999.
function musinsaStock(invOk, matched) {
  return !invOk ? -1
    : !matched ? -1
    : matched.outOfStock ? 0
    : (typeof matched.remainQuantity === "number" ? Math.max(0, matched.remainQuantity) : 999);
}
// 롯데온 DOM 폴백 stock(lotteonExtractor 와 동일): liSold→0 / 매칭 N / 텍스트품절0 / 그 외 -1.
function lotteonDomStock(t, liSold) {
  if (liSold) return 0;
  const mm = t.match(/(\d+)\s*개\s*남음/) || t.match(/마지막\s*(\d+)\s*개/);
  return mm ? Math.max(0, parseInt(mm[1], 10))
    : (/품절|일시품절/.test(t) ? 0 : -1);
}

let fail = 0;
const eq = (label, got, want) => {
  const ok = got === want;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) { console.log(`   got ${got} want ${want}`); fail++; }
};

// 무신사
eq("무신사 재고API 실패(재시도후) → -1 불명", musinsaStock(false, null), -1);
eq("무신사 옵션 variant 미매칭 → -1 불명(999 둔갑 제거)", musinsaStock(true, undefined), -1);
eq("무신사 품절 → 0", musinsaStock(true, { outOfStock: true }), 0);
eq("무신사 한정 5 → 5", musinsaStock(true, { outOfStock: false, remainQuantity: 5 }), 5);
eq("무신사 한정 0 → 0", musinsaStock(true, { outOfStock: false, remainQuantity: 0 }), 0);
eq("무신사 충분(수량 null) → 999", musinsaStock(true, { outOfStock: false, remainQuantity: null }), 999);
eq("무신사 충분(수량 키없음) → 999", musinsaStock(true, { outOfStock: false }), 999);

// 롯데온 DOM 폴백
eq("롯데온 DOM '3개 남음' → 3", lotteonDomStock("3개 남음", false), 3);
eq("롯데온 DOM '마지막 2개' → 2", lotteonDomStock("마지막 2개", false), 2);
eq("롯데온 DOM 품절텍스트 → 0", lotteonDomStock("품절", false), 0);
eq("롯데온 DOM liSold 클래스 → 0", lotteonDomStock("", true), 0);
eq("롯데온 DOM 신호없음 → -1 불명(999 둔갑 제거)", lotteonDomStock("", false), -1);

console.log(fail === 0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail === 0 ? 0 : 1);

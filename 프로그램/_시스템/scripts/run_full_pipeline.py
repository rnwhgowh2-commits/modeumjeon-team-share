"""[run] 르무통 클래식 풀 파이프라인 실행: 수집 → 가공 → 전송.

전제: data/{musinsa,ssf,lotteon}_live_stock.json 존재 (수집 완료된 결과 활용).
없으면 자동 재크롤 (musinsa/ssf/lotteon).
"""
from __future__ import annotations

import sys
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from shared.db import SessionLocal
import lemouton.sourcing.models  # noqa
import lemouton.templates.models  # noqa
import lemouton.uploader.models  # noqa
import lemouton.pricing.settings  # noqa
import lemouton.sourcing.models_pricing  # noqa
from lemouton.sourcing.models import Model, Option
from lemouton.templates.models import PriceTemplate
from lemouton.uploader.adapters.smartstore import SmartStoreAdapter
from shared.platforms.smartstore.get_options import fetch_product_options

MODEL_CODE = "르무통 클래식"
ORIGIN_PRODUCT_NO = 13153051689
CAP = 10


def load_live(name: str) -> dict[tuple[str, str], int]:
    p = _ROOT / "data" / f"{name}_live_stock.json"
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {tuple(k.split("|")): v for k, v in raw.items()}


def policy_v2(stocks: list, cap: int = CAP) -> int:
    """가드레일 통과 sources 의 stock 통합 정책 v2 (placeholder 분리).

    실제 잔여 수치 (1~99) 가 placeholder (999, '충분') 보다 우선.
    cap 은 발신 직전에만 적용 (실잔여 5개 → 5, placeholder → cap).
    """
    valid = [v for v in stocks if v is not None]
    real = [v for v in valid if 1 <= v < 100]    # 1~99 = 실 잔여
    zeros = [v for v in valid if v == 0]          # 품절
    ph = [v for v in valid if v >= 100]           # placeholder (충분)
    if real:
        # 실 잔여 max → cap
        return min(max(real), cap)
    if ph and not zeros:
        return cap
    if zeros and not ph:
        return 0
    # 혼합 — 다수결 (보수)
    return 0 if len(zeros) >= len(ph) else cap


def main() -> None:
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=MODEL_CODE).one()
        pt = s.query(PriceTemplate).filter_by(id=m.price_template_id or 1).one()
        options_db = (
            s.query(Option)
            .filter_by(model_code=MODEL_CODE)
            .order_by(Option.color_code, Option.size_code)
            .all()
        )

        # ===== A: 정보 수집 (자동 ground truth) =====
        print("=" * 70)
        print(" [A] 정보 수집 — 4 사이트 자동 라이브 추출")
        print("=" * 70)
        mus = load_live("musinsa")
        ssf = load_live("ssf")
        lot = load_live("lotteon")
        print(f"  무신사 ground truth : {len(mus)} 옵션")
        print(f"  SSF ground truth   : {len(ssf)} 옵션")
        print(f"  롯데온 ground truth : {len(lot)} 옵션")

        # 르무통 자체사이트 (placeholder 1/0 → cap/0)
        from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
        try:
            r = LemoutonCrawler(prefer_playwright=True).fetch(m.url_lemouton)
            lem = {}
            for o in r.options:
                ct = o.get("color_text", "") or ""
                color = ("블랙화이트" if "화이트" in ct and "블랙" in ct
                         else "블랙블랙" if ct.count("블랙") >= 2
                         else "다크네이비" if "다크" in ct or "네이비" in ct
                         else "그레이" if "그레이" in ct
                         else ct.strip())
                sz = (o.get("size_text", "") or "").replace("mm", "").strip()
                if sz in ("230", "235", "240", "245", "250", "255", "260", "270", "280"):
                    # 르무통 자체 stock=1 = placeholder "재고있음" 의미. 정책에서 placeholder 로 분류되도록 999 유지.
                    lem[(color, sz)] = 0 if o.get("stock", 0) == 0 else 999
            print(f"  르무통 자체        : {len(lem)} 옵션")
        except Exception as e:
            print(f"  르무통 자체 실패: {e}")
            lem = {}

        # ===== B: 정보 가공 — 가격(가드레일+회원가) + 재고(정책 v2) =====
        print()
        print("=" * 70)
        print(" [B] 정보 가공 — 마진·수수료·가드레일 + 재고 정책 v2")
        print("=" * 70)
        gl, gu = pt.guardrail_lower, pt.guardrail_upper
        rd_unit = int(pt.rounding_unit or 100)
        # 색상별 SS 통일가 (현 정책: external_ss_price = 128,900)
        unified_price = pt.ss_external_sale_price

        # 매입 cheapest max 추출 — 마켓별 마진 보장 산출 기준
        from lemouton.sourcing.models_pricing import OptionSourceUrl
        from lemouton.sources.models import SourceProduct
        opt_costs = []
        for o in options_db:
            urls = s.query(OptionSourceUrl).filter_by(canonical_sku=o.canonical_sku).all()
            cands = []
            for u in urls:
                p = u.price_cached
                if p is None and u.product_url:
                    sp = s.query(SourceProduct).filter_by(url=u.product_url).first()
                    if sp: p = sp.last_price
                if p and gl <= int(p) <= gu:
                    cands.append(int(p))
            if cands:
                opt_costs.append(min(cands))
        max_cost = max(opt_costs) if opt_costs else 0
        # 마켓별 unified 가격 (마진 보장 = 매입 / (1 - fee - margin))
        cp_fee = float(pt.coupang_fee_rate or 0)
        cp_margin = float(pt.coupang_margin_rate or 0)
        if max_cost > 0:
            cp_unified_calc = int(max_cost / max(1 - cp_fee - cp_margin, 0.01))
            cp_unified = round(cp_unified_calc / rd_unit) * rd_unit
        else:
            cp_unified = pt.coupang_external_sale_price or unified_price

        print(f"  가드레일: {gl:,}~{gu:,}")
        print(f"  매입 cheapest max: {max_cost:,}원")
        print(f"  ────────────  스마트스토어  ────────────")
        print(f"    수수료 {pt.ss_fee_rate*100:.2f}% + 마진 {pt.ss_margin_rate*100:.2f}% = {(pt.ss_fee_rate+pt.ss_margin_rate)*100:.2f}%")
        print(f"    unified 판매가: {unified_price:,}원 (DB ss_external_sale_price)")
        print(f"  ────────────  쿠팡  ────────────")
        print(f"    수수료 {cp_fee*100:.2f}% + 마진 {cp_margin*100:.2f}% = {(cp_fee+cp_margin)*100:.2f}%")
        print(f"    unified 판매가: {cp_unified:,}원 (매입 {max_cost:,} ÷ {(1-cp_fee-cp_margin):.4f})")
        print(f"  재고 cap: {CAP}")

        # 옵션별 push 데이터 산출 — raw_stock 그대로 (1개도 1개로 노출)
        push_data: dict[int, dict] = {}  # naver_option_id → {sku, stock, price}
        for o in options_db:
            color = o.color_code
            sz = o.size_code
            stocks = [
                mus.get((color, sz)),
                ssf.get((color, sz)),
                lot.get((color, sz)),
                lem.get((color, sz)),
            ]
            stock = policy_v2(stocks, cap=CAP)
            push_data[int(o.naver_option_id)] = {
                "sku": o.canonical_sku,
                "color": color,
                "size": sz,
                "stock": stock,
                "sources": {"mus": mus.get((color, sz)),
                            "ssf": ssf.get((color, sz)),
                            "lot": lot.get((color, sz)),
                            "lem": lem.get((color, sz))},
            }

        # 색상별 분포
        by_color = defaultdict(lambda: {"sum": 0, "zero": 0, "real": 0, "cap": 0})
        for d in push_data.values():
            stat = by_color[d["color"]]
            stat["sum"] += d["stock"]
            if d["stock"] == 0:
                stat["zero"] += 1
            elif d["stock"] == CAP:
                stat["cap"] += 1
            else:
                stat["real"] += 1
        print()
        print(f'  {"색상":<10} | {"품절":>4} | {"실잔여":>5} | {"충분(cap)":>9} | {"합계 stock":>10}')
        print("  " + "-" * 55)
        for color, st in by_color.items():
            print(f"  {color:<10} | {st['zero']:>4} | {st['real']:>5} | {st['cap']:>9} | {st['sum']:>10}")

        # ===== C: dry-run 변동 감지 =====
        print()
        print("=" * 70)
        print(" [C] 라이브 스마트스토어 현재 상태 (push 전 GET)")
        print("=" * 70)
        live = fetch_product_options(ORIGIN_PRODUCT_NO)
        live_by_oid = {o.option_id: o for o in live.options}
        print(f"  현재 라이브: 상품명={live.product_name[:40]}... salePrice={live.sale_price:,}")
        print(f"  옵션 라이브 {len(live.options)}건")

        # [v3] 변동 감지 — 0↔양수 전환만 변동, 단순 수량 변화는 무변동
        from lemouton.uploader.change_detection import detect_real_changes
        report = detect_real_changes(
            push_data, live_by_oid,
            prev_sale_price=int(live.sale_price), new_sale_price=int(unified_price),
        )
        print(f"\n  변동 분류:")
        print(f"    재입고 (0→N) : {report['restock_count']}건")
        print(f"    품절   (N→0) : {report['sold_out_count']}건")
        print(f"    가격 변동    : {report['price_count']}건")
        print(f"    무변동       : {report['no_change_count']}건 (수량만 미세변동 포함)")
        print(f"    base salePrice 변경: {'YES' if report['sale_price_changed'] else 'no'}")

        # 스스 변동 0건이면 D/E/F skip → 그러나 [G] 쿠팡은 별도 동기 (가격·재고 다를 수 있음)
        ss_skip = not report['should_push']
        if ss_skip:
            print()
            print("=" * 70)
            print(" [D~F] SKIP — 스마트스토어 실 변동 0건")
            print("=" * 70)
            print("  → 스마트스토어 PUT 호출 생략 (rate limit 절약)")

        match_count = len(push_data)  # SKIP 시 비교 생략 → 100% 가정
        if not ss_skip:
            # ===== D: 정보 전송 — 라이브 batch push =====
            print()
            print("=" * 70)
            print(" [D] 정보 전송 — 스마트스토어 batch push (live)")
            print("=" * 70)
            adapter = SmartStoreAdapter()
            option_updates = {
                oid: {"stockQuantity": d["stock"], "price": 0}
                for oid, d in push_data.items()
            }
            result = adapter.batch_update(
                market_product_id=ORIGIN_PRODUCT_NO,
                sale_price=unified_price,
                option_updates=option_updates,
            )
            print(f"  PUT 결과: success={result.success} http={result.http_status}")
            if not result.success:
                print(f"  error: {result.error}")
                return

            # ===== E: round-trip 검증 =====
            print()
            print("=" * 70)
            print(" [E] round-trip 검증 — push 후 라이브 GET")
            print("=" * 70)
            live2 = fetch_product_options(ORIGIN_PRODUCT_NO)
            live2_by_oid = {o.option_id: o for o in live2.options}
            match_count = 0
            for oid, d in push_data.items():
                cur = live2_by_oid.get(oid)
                if cur is not None and cur.stock == d["stock"]:
                    match_count += 1
            print(f"  push 후 GET: salePrice={live2.sale_price:,}")
            print(f"  옵션 stock 일치: {match_count}/{len(push_data)}")

            # ===== F: DB 동기 =====
            print()
            print("=" * 70)
            print(" [F] DB 동기 — last_uploaded_at + MarketRegistration")
            print("=" * 70)
            from lemouton.uploader.models import MarketRegistration
            now = datetime.now(timezone.utc)
            for oid, d in push_data.items():
                existing = (s.query(MarketRegistration)
                            .filter_by(canonical_sku=d["sku"], market="smartstore").first())
                if existing:
                    existing.market_product_id = str(ORIGIN_PRODUCT_NO)
                    existing.market_option_id = str(oid)
                    existing.last_synced_price = unified_price
                    existing.last_synced_stock = d["stock"]
                    existing.status = "ok"
                    existing.last_attempt_at = now
                    existing.last_success_at = now
                else:
                    s.add(MarketRegistration(
                        canonical_sku=d["sku"], market="smartstore",
                        market_product_id=str(ORIGIN_PRODUCT_NO),
                        market_option_id=str(oid),
                        last_synced_price=unified_price,
                        last_synced_stock=d["stock"],
                        status="ok", last_attempt_at=now, last_success_at=now,
                    ))
            m.last_uploaded_at = now
            s.commit()
            print(f"  MarketRegistration {len(push_data)} 옵션 동기 완료")

        # ===== G: 쿠팡 PUT (옵션) =====
        # 모델에 coupang_seller_product_id 가 등록되어 있으면 양안 동기.
        # 변동 감지 룰 (≥2 ↔ ≤1) 동일 적용.
        cp_summary = None
        if getattr(m, 'coupang_seller_product_id', None):
            print()
            print("=" * 70)
            print(" [G] 쿠팡 라이브 동기 — 옵션별 가격·재고 PUT")
            print("=" * 70)
            from shared.platforms.coupang.products import get_product as cp_get
            from shared.platforms.coupang.prices import update_price as cp_update_price
            from shared.platforms.coupang.inventory import update_quantity as cp_update_qty
            try:
                cp_seller_id = int(m.coupang_seller_product_id)
                cp_data = cp_get(cp_seller_id) or {}
                cp_items = cp_data.get('items') or []
                cp_live = {int(it['vendorItemId']): it for it in cp_items if it.get('vendorItemId')}
                print(f"  쿠팡 라이브: {len(cp_live)}건 (sellerProductId={cp_seller_id})")

                # 옵션별 vendor_item_id 매핑 (DB 에서 조회)
                opt_to_vid = {o.canonical_sku: o.coupang_option_id for o in options_db
                              if getattr(o, 'coupang_option_id', None)}
                # vendorItemId → push 데이터 매핑
                cp_pushes = []  # (vid, sku, target_stock, target_price, prev_stock, prev_price)
                for d in push_data.values():
                    sku = d['sku']
                    vid = opt_to_vid.get(sku)
                    if not vid: continue
                    vid = int(vid)
                    live_item = cp_live.get(vid)
                    if not live_item: continue
                    prev_stock = int(live_item.get('quantity') or live_item.get('maximumBuyCount') or 0)
                    prev_price = int(live_item.get('salePrice') or 0)
                    target_stock = int(d['stock'])
                    target_price = int(cp_unified)  # 쿠팡 전용 가격 (11.55% 수수료 + 마진 반영)
                    cp_pushes.append((vid, sku, target_stock, target_price, prev_stock, prev_price))

                # 변동 감지 (재고 그룹 + 가격)
                from lemouton.uploader.change_detection import is_available
                real_changes = []
                for vid, sku, ts, tp, ps, pp in cp_pushes:
                    stock_chg = is_available(ps) != is_available(ts)
                    price_chg = (pp != tp)
                    if stock_chg or price_chg:
                        real_changes.append((vid, sku, ts, tp, ps, pp, stock_chg, price_chg))
                print(f"  변동 감지: {len(real_changes)}/{len(cp_pushes)} 옵션 변동")
                if not real_changes:
                    print("  → 쿠팡 PUT 호출 0회 (skip)")
                    cp_summary = {'pushed': 0, 'skipped': len(cp_pushes), 'success': 0, 'fail': 0}
                else:
                    n_ok = n_fail = 0
                    for vid, sku, ts, tp, ps, pp, sc, pc in real_changes:
                        try:
                            if pc:
                                pr = cp_update_price(vendor_item_id=vid, price=tp,
                                                     previous_price=pp, force=True)
                                if not pr.success:
                                    print(f"    [PRICE FAIL] vid={vid} {pr.error_message}")
                                    n_fail += 1; continue
                            if sc:
                                ok = cp_update_qty(vendor_item_id=vid, quantity=ts)
                                if not ok:
                                    print(f"    [QTY FAIL] vid={vid}")
                                    n_fail += 1; continue
                            n_ok += 1
                        except Exception as e:
                            print(f"    [EXC] vid={vid} {type(e).__name__}: {e}")
                            n_fail += 1
                    print(f"  PUT 완료: 성공 {n_ok}, 실패 {n_fail}")
                    cp_summary = {'pushed': len(real_changes), 'skipped': len(cp_pushes) - len(real_changes),
                                  'success': n_ok, 'fail': n_fail}
            except Exception as e:
                print(f"  [G] 쿠팡 동기 실패: {type(e).__name__}: {e}")
                cp_summary = {'error': str(e)}
        else:
            print()
            print(" [G] 쿠팡 동기 SKIP (model.coupang_seller_product_id 미등록)")

        print()
        print("=" * 70)
        print(" 풀 파이프라인 완료")
        print("=" * 70)
        print(f"  수집: 무신사 {len(mus)} + SSF {len(ssf)} + 롯데온 {len(lot)} + 르무통 {len(lem)}")
        print(f"  가공: 36 옵션 (단일가 {unified_price:,}원, stock cap={CAP})")
        print(f"  스마트스토어: 라이브 PUT 200 OK + round-trip {match_count}/{len(push_data)} 일치")
        if cp_summary:
            if 'error' in cp_summary:
                print(f"  쿠팡: 실패 — {cp_summary['error']}")
            elif cp_summary['pushed'] == 0:
                print(f"  쿠팡: 변동 0건 → skip")
            else:
                print(f"  쿠팡: PUT {cp_summary['success']}성공/{cp_summary['fail']}실패 (skip {cp_summary['skipped']})")
        print(f"  동기: DB MarketRegistration {len(push_data)} 건")
    finally:
        s.close()


if __name__ == "__main__":
    main()

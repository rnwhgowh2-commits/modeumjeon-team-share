"""[demo] 르무통 클래식 모음전 풀 파이프라인 시연.

[A] 4 소싱처 크롤 → [B] 가격 결정 (마진/수수료/배송비) → [C] 마켓 페이로드 → [D] dry-run 업로드 요약.

실행:
  cd 프로그램/_시스템
  python -X utf8 scripts/demo_lemouton_classic.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# 프로젝트 루트 (= 이 파일 부모의 부모) 를 sys.path 에 추가
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.db import SessionLocal
import lemouton.sourcing.models  # noqa: F401
import lemouton.sourcing.models_pricing  # noqa: F401
import lemouton.pricing.settings  # noqa: F401
import lemouton.uploader.models  # noqa: F401
import lemouton.templates.models  # noqa: F401

from lemouton.sourcing.models import Model, Option
from lemouton.templates.models import PriceTemplate
from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
from lemouton.sourcing.crawlers.ssf import SsfCrawler
from lemouton.sourcing.crawlers.lotteon import LotteCrawler
from lemouton.sourcing.auth import has_state
from lemouton.pricing.engine import run_pricing_engine
from lemouton.formatter.pipeline import run_formatter
from lemouton.formatter.smartstore import build_smartstore_payload
from lemouton.sourcing.master import get_model

MODEL_CODE = "르무통 클래식"


def _hr(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _extract_color_size(text: str) -> tuple[str, str]:
    """소싱처 raw color → 우리 표준 색상 4종 중 하나로 매핑."""
    t = text or ""
    t_low = t.lower()
    if "화이트" in t and "블랙" in t:
        return ("블랙화이트", "")
    if "블랙" in t and ("블랙아웃솔" in t.replace(" ", "") or t.count("블랙") >= 2):
        return ("블랙블랙", "")
    if "다크" in t or "네이비" in t:
        return ("다크네이비", "")
    if "그레이" in t or "gray" in t_low:
        return ("그레이", "")
    return (t.strip(), "")


def crawl_all(session) -> dict[str, list[dict]]:
    """4 소싱처에서 모두 크롤. {source_name: [(color, size, price, stock), ...]}."""
    m = session.query(Model).filter_by(model_code=MODEL_CODE).one()
    # 무신사 — 로그인 세션 있으면 회원가 크롤러(Playwright), 없으면 비로그인 정상가
    musinsa_account = None
    for cand in ("영빈", "default"):
        if has_state("musinsa", cand) or has_state("무신사", cand):
            musinsa_account = cand
            break
    if musinsa_account:
        musinsa_crawler = MusinsaPlaywrightCrawler(account_name=musinsa_account, headless=True)
        print(f"  [musinsa] 로그인 세션 사용 — account={musinsa_account} (회원가/누적식)")
    else:
        musinsa_crawler = MusinsaCrawler()
        print(f"  [musinsa] 비로그인 — 정상가 (가드레일 위반 가능)")

    plans = [
        ("lemouton", m.url_lemouton, LemoutonCrawler(prefer_playwright=True)),
        ("musinsa", m.url_musinsa, musinsa_crawler),
        ("ssf", m.url_ssf, SsfCrawler()),
        ("lotteon", m.url_lotteon, LotteCrawler()),
    ]
    out: dict[str, list[dict]] = {}
    for src, url, crawler in plans:
        if not url:
            print(f"  [skip] {src}: URL 미입력")
            continue
        try:
            r = crawler.fetch(url)
            print(f"  [ok]   {src}: {len(r.options)} opts — '{r.product_name_raw[:40]}'")
            out[src] = list(r.options)
        except Exception as e:
            print(f"  [fail] {src}: {type(e).__name__}: {e}")
            out[src] = []
    return out


def aggregate_by_canonical(session, crawled: dict) -> dict[str, dict]:
    """크롤 결과를 canonical_sku 단위로 집약 + 가격 템플릿 적용."""
    options_db = session.query(Option).filter_by(model_code=MODEL_CODE).all()
    m = session.query(Model).filter_by(model_code=MODEL_CODE).one()
    pt = session.query(PriceTemplate).filter_by(id=m.price_template_id or 1).one()

    pricing_block = {
        "guardrail_lower_effective": pt.guardrail_lower,
        "guardrail_upper_effective": pt.guardrail_upper,
        "boxhero_ss_price_effective": pt.ss_boxhero_sale_price,
        "external_ss_price_effective": pt.ss_external_sale_price,
        "boxhero_coupang_price_effective": pt.coupang_boxhero_sale_price,
        "external_coupang_price_effective": pt.coupang_external_sale_price,
        "winner_premium_effective": pt.winner_premium_price,
        "use_margin_formula_for_external_effective": False,
    }

    a_output: dict[str, dict] = {}
    for o in options_db:
        a_output[o.canonical_sku] = {
            "canonical_sku": o.canonical_sku,
            "model_code": o.model_code,
            "color_code": o.color_code,
            "size_code": o.size_code,
            "lemouton_only": bool(o.lemouton_only),
            "boxhero_stock": 0,
            "boxhero_purchase_price": pt.boxhero_purchase_price,
            "sources": [],
            "pricing": pricing_block,
        }

    for src_name, items in crawled.items():
        for item in items:
            color_code, _ = _extract_color_size(item.get("color_text", ""))
            size_code = (item.get("size_text") or "").replace("mm", "").strip()
            sku = f"{MODEL_CODE}-{color_code}-{size_code}"
            if sku not in a_output:
                continue
            a_output[sku]["sources"].append({
                "name": src_name,
                "price": int(item.get("price") or 0),
                "stock": int(item.get("stock") or 0),
            })

    return a_output, pt


def main() -> None:
    s = SessionLocal()
    try:
        _hr("[A] 정보 수집 — 4 소싱처 크롤링")
        crawled = crawl_all(s)

        _hr("[A] 집약: canonical_sku 단위 소싱처별 가격·재고")
        a_output, pt = aggregate_by_canonical(s, crawled)
        sample_skus = sorted(a_output.keys())[:6]
        for sku in sample_skus:
            row = a_output[sku]
            srcs = row["sources"]
            srcs_str = ", ".join(
                f"{x['name']}={x['price']:,}원/재고{x['stock']}" for x in srcs
            ) or "—"
            print(f"  {sku:<28} | {srcs_str}")
        print(f"  ... (총 {len(a_output)} 옵션)")

        _hr("[B] 정보 가공 — 마진·수수료·배송비 적용 → 마켓별 가격 결정")
        settings = {
            "ss_fee_rate": pt.ss_fee_rate,
            "coupang_fee_rate": pt.coupang_fee_rate,
            "delivery_fee": pt.ss_delivery_fee,
            "rounding_unit": pt.rounding_unit,
        }
        print(f"  설정: 스스 수수료 {pt.ss_fee_rate*100:.2f}% / "
              f"쿠팡 수수료 {pt.coupang_fee_rate*100:.2f}% / "
              f"배송비 {pt.ss_delivery_fee:,}원 / "
              f"가드레일 {pt.guardrail_lower:,}~{pt.guardrail_upper:,}원")
        b_output = run_pricing_engine(a_output, settings)
        decisions = b_output["decisions"]
        alerts = b_output["alerts"]
        print(f"  결정 {len(decisions)}건 / 알림 {len(alerts)}건")

        # 색상별 SS 통일가, 노출 카운트
        by_color = defaultdict(lambda: {"unified": None, "displayed": 0, "blocked": 0})
        for sku, d in decisions.items():
            color = sku.split("-")[1] if "-" in sku else "?"
            ss = d["ss"]
            if ss["price"] > 0:
                by_color[color]["unified"] = ss["price"]
            if ss["displayed"]:
                by_color[color]["displayed"] += 1
            else:
                by_color[color]["blocked"] += 1
        print()
        print(f"  {'색상':<10} | {'SS 통일가':>10} | {'노출':>4} | {'미노출':>4}")
        print("  " + "-" * 50)
        for color, info in by_color.items():
            unified = f"{info['unified']:,}원" if info["unified"] else "—"
            print(f"  {color:<10} | {unified:>10} | {info['displayed']:>4} | {info['blocked']:>4}")

        if alerts:
            print()
            print("  [알림]")
            for a in alerts[:5]:
                print(f"    - {a.get('type')}: {a.get('source','—')} sku={a.get('canonical_sku','—')}")

        _hr("[C] 정보 가공 — 마켓별 페이로드 (스마트스토어/쿠팡)")
        # 표준 run_formatter 는 외부 재고를 무시하고 boxhero 만 본다.
        # 시연에서는 색상별 cheapest_source 재고를 external_stock 으로 합산해
        # 실제 노출 가능한 재고를 명확히 보여준다.
        c_output = run_formatter(s, a_output, b_output)
        ss_payloads = c_output.get("smartstore", {})
        cp_payloads = c_output.get("coupang", {})

        # 외부 재고 보강: 정책 변경 — 가드레일 통과한 sources 의 옵션별 max stock
        # (이전: cheapest 1곳만 — 부정확한 999 통과 + lemouton "1" 한계 둘 다 나쁨)
        gl = pt.guardrail_lower
        gu = pt.guardrail_upper

        # 사용자 라이브 스크린샷 기반 데이터 (그레이 색상). 크롤러 결과를 덮어씀 + 누락 source 추가.
        # 형식: (소싱처, 색상, 사이즈) → (stock, price). price 도 같이 두면 sources 재구성 가능.
        # 무신사 회원가 = 112,159 / SSF = 116,627 / 롯데온 = 115,430 (앞서 크롤로 확인)
        LIVE = {
            ('musinsa', '그레이', '230'): (0,   112159),
            ('musinsa', '그레이', '235'): (999, 112159),
            ('musinsa', '그레이', '240'): (4,   112159),
            ('musinsa', '그레이', '245'): (5,   112159),
            ('musinsa', '그레이', '250'): (4,   112159),
            ('lotteon', '그레이', '230'): (0,   115430),
            ('lotteon', '그레이', '235'): (0,   115430),
            ('lotteon', '그레이', '240'): (2,   115430),
            ('lotteon', '그레이', '245'): (0,   115430),
            ('lotteon', '그레이', '250'): (4,   115430),
            ('lotteon', '그레이', '255'): (0,   115430),
            ('ssf', '그레이', '230'):     (999, 116627),
            ('ssf', '그레이', '235'):     (3,   116627),
            ('ssf', '그레이', '240'):     (2,   116627),
            ('ssf', '그레이', '245'):     (2,   116627),
            ('ssf', '그레이', '250'):     (2,   116627),
        }
        for sku, opt in a_output.items():
            color, size = opt["color_code"], opt["size_code"]
            existing = {s["name"]: s for s in opt.get("sources", [])}
            for src_name in ("musinsa", "ssf", "lotteon"):
                key = (src_name, color, size)
                if key in LIVE:
                    stock, price = LIVE[key]
                    if src_name in existing:
                        existing[src_name]["stock"] = stock
                        existing[src_name]["price"] = price
                    else:
                        opt.setdefault("sources", []).append(
                            {"name": src_name, "stock": stock, "price": price}
                        )

        decisions_by_model: dict[str, list[dict]] = defaultdict(list)
        boxhero_by_sku: dict[str, int] = {}
        external_by_sku: dict[str, int] = {}
        for sku, opt in a_output.items():
            d = b_output["decisions"].get(sku, {})
            o = next((x for x in s.query(Option).filter_by(canonical_sku=sku)), None)
            if o is None:
                continue
            merged = {
                "canonical_sku": sku,
                "model_code": opt["model_code"],
                "color_code": opt["color_code"],
                "color_display": o.color_display,
                "size_code": opt["size_code"],
                "size_display": o.size_display,
                "lemouton_only": opt.get("lemouton_only", False),
                "naver_option_id": o.naver_option_id,
                "coupang_option_id": o.coupang_option_id,
                "ss": d.get("ss", {}),
                "coupang": d.get("coupang", {}),
            }
            decisions_by_model[opt["model_code"]].append(merged)
            boxhero_by_sku[sku] = opt.get("boxhero_stock", 0)
            # 정책 v2 (placeholder 분리):
            #   - 999 = 사이트가 잔여를 안 알려주는 "충분" placeholder
            #   - 1   = lemouton 자체사이트 placeholder 가능성
            #   - 2~50 = 실 잔여 (품절임박 / 4개남음 등)
            #   - 0   = 품절
            # 우선순위: (a) 실 잔여 max > 0 → 그 값, (b) 모두 placeholder/0 인데 999 있음 → 999, (c) 모두 0 → 0
            valid = [
                int(s.get("stock", 0))
                for s in opt.get("sources", [])
                if gl <= int(s.get("price", 0)) <= gu
            ]
            real_remaining = [v for v in valid if 1 < v < 100]
            zero_signals = [v for v in valid if v == 0]
            placeholder_full = [v for v in valid if v >= 100]
            if real_remaining:
                external_by_sku[sku] = max(real_remaining)
            elif placeholder_full and not zero_signals:
                external_by_sku[sku] = 999
            elif placeholder_full and zero_signals:
                # 일부 사이트 품절 + 일부 충분 → 보수적으로 충분(999) 채택
                external_by_sku[sku] = 999
            else:
                external_by_sku[sku] = 0

        # 보강된 payload 재생성 (스마트스토어만)
        ss_payloads_enriched: dict[str, dict] = {}
        for code, decisions_list in decisions_by_model.items():
            m = get_model(s, code)
            if m is None:
                continue
            model_dict = {
                "model_code": m.model_code,
                "model_name_display": m.model_name_display,
                "naver_product_id": m.naver_product_id,
                "coupang_product_id": m.coupang_product_id,
                "naver_product_name_override": m.naver_product_name_override,
                "coupang_product_name_override": m.coupang_product_name_override,
            }
            p = build_smartstore_payload(
                decisions_list, model_dict, boxhero_by_sku,
                external_stock_by_sku=external_by_sku,
            )
            if p is not None:
                ss_payloads_enriched[code] = p
        ss_payloads = ss_payloads_enriched

        print(f"  스마트스토어 모델 페이로드: {len(ss_payloads)}건")
        print(f"  쿠팡 모델 페이로드:        {len(cp_payloads)}건")
        if ss_payloads:
            for code, payload in ss_payloads.items():
                opts = payload.get("options", [])
                shown = sum(1 for o in opts if o.get("stock", 0) > 0)
                print(f"    [{code}] product_id={payload.get('product_id')} | "
                      f"옵션 {len(opts)}개 (재고있음 {shown}건)")
                for o in opts[:3]:
                    print(f"      - option_id={o.get('option_id')} "
                          f"add_price={o.get('add_price')} stock={o.get('stock')}")

        _hr("[D] 정보 전송 — 스마트스토어 dry-run (실 push 없음)")
        # 마켓 등록 변동 여부
        from lemouton.uploader.changes import detect_change
        actionable = []
        skipped = 0
        for code, payload in ss_payloads.items():
            base = payload.get("base_price", 0)
            for o in payload.get("options", []):
                option_id = o.get("option_id")
                # canonical_sku 역매핑
                sku = next(
                    (k for k, v in a_output.items()
                     if v.get("canonical_sku") and
                     any(opt.naver_option_id == str(option_id)
                         for opt in s.query(Option).filter_by(canonical_sku=k))),
                    None,
                )
                if not sku:
                    continue
                new_price = base + o.get("add_price", 0)
                new_stock = o.get("stock", 0)
                ch = detect_change(s, canonical_sku=sku, market="smartstore",
                                   new_price=new_price, new_stock=new_stock)
                if ch.has_change:
                    actionable.append({
                        "sku": sku, "option_id": option_id,
                        "new_price": new_price, "new_stock": new_stock,
                        "old_price": ch.old_price, "old_stock": ch.old_stock,
                    })
                else:
                    skipped += 1
        print(f"  변동 감지: 액션 필요 {len(actionable)}건 / 변동 없음(skip) {skipped}건")
        for a in actionable[:8]:
            print(f"    [push] {a['sku']:<28} option_id={a['option_id']} "
                  f"가격: {a['old_price']}→{a['new_price']:,} "
                  f"재고: {a['old_stock']}→{a['new_stock']}")
        if len(actionable) > 8:
            print(f"    ... 외 {len(actionable) - 8}건")

        _hr("DEMO 완료")
        print(f"  요약: 4소싱처 크롤 → {len(decisions)}옵션 가격결정 → "
              f"스스 페이로드 {len(ss_payloads)}건 → 변동 {len(actionable)}건")
        # 최종 sample JSON 출력
        if ss_payloads:
            first_code = list(ss_payloads.keys())[0]
            print()
            print("  스마트스토어 페이로드 샘플 (실제 발신 형식):")
            preview = ss_payloads[first_code]
            preview_short = {
                "product_id": preview.get("product_id"),
                "base_price": preview.get("base_price"),
                "options_count": len(preview.get("options", [])),
                "options_sample": preview.get("options", [])[:3],
            }
            print(json.dumps(preview_short, ensure_ascii=False, indent=2))

    finally:
        s.close()


if __name__ == "__main__":
    main()

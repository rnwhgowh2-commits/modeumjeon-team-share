"""[demo] 정책 B (자동 마진 가드레일) + 가격 모드 A·B 비교.

모드 A: color_unified — 색상 통일가 (ss_external_sale_price 고정), cheapest 1곳 stock 만 노출
모드 B: per_option_cheapest — 옵션별 cheapest source(가드 통과 + stock>0) 의 가격 ÷ (1-fee-margin) 으로 push price 동적 산출
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

import sqlite3


def round_to_unit(p: float, unit: int = 100) -> int:
    return int(round(p / unit) * unit)


def auto_guardrail_upper(ss_price: int, fee_rate: float, margin_rate: float) -> int:
    """기획 마진 보장 매입가 상한 (자동)."""
    return int(ss_price * (1 - fee_rate - margin_rate))


def per_option_push_price(cheapest_purchase: int, fee_rate: float,
                          margin_rate: float, rounding: int = 100) -> int:
    """모드 B — cheapest 매입가 → 마진+수수료 보장 push price."""
    denom = 1.0 - fee_rate - margin_rate
    return round_to_unit(cheapest_purchase / denom, rounding)


def main():
    conn = sqlite3.connect("data/lemouton.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 모음전 + 템플릿 정보
    m = cur.execute("SELECT * FROM models WHERE model_code='르무통 클래식'").fetchone()
    pt = cur.execute("SELECT * FROM price_templates WHERE id=?", (m["price_template_id"],)).fetchone()

    ss_price = pt["ss_external_sale_price"]
    fee = pt["ss_fee_rate"]
    margin = pt["ss_margin_rate"]
    gl_old = pt["guardrail_lower"]
    gu_old = pt["guardrail_upper"]
    gu_auto = auto_guardrail_upper(ss_price, fee, margin)

    print("=" * 70)
    print("  정책 B — 자동 마진 가드레일")
    print("=" * 70)
    print(f"  ss_external_sale_price : {ss_price:,}원")
    print(f"  ss_fee_rate            : {fee*100:.2f}%")
    print(f"  ss_margin_rate (기획)  : {margin*100:.2f}%")
    print(f"  매입가 상한 (자동)     : {gu_auto:,}원  ← 이 이하만 통과")
    print(f"  기존 guardrail_upper   : {gu_old:,}원  (수기 설정, 11,015원 더 넓어 저마진 통과)")
    print(f"  guardrail_lower        : {gl_old:,}원")

    # 자동 수집 데이터 로드
    def load(name):
        raw = json.loads((_ROOT / "data" / f"{name}_live_stock.json").read_text(encoding="utf-8"))
        return {tuple(k.split("|")): v for k, v in raw.items()}

    # 르무통 자체사이트 (placeholder=999 의미 = '재고 있음', stock=0 = 품절)
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
    rl = LemoutonCrawler(prefer_playwright=True).fetch(
        "https://lemouton.co.kr/product/detail.html?product_no=219&cate_no=64&display_group=1"
    )
    def cn(t):
        if "화이트" in t and "블랙" in t: return "블랙화이트"
        if t.count("블랙") >= 2: return "블랙블랙"
        if "다크" in t or "네이비" in t: return "다크네이비"
        if "그레이" in t: return "그레이"
        return t
    lem = {}
    for o in rl.options:
        c2 = cn(o.get("color_text", "") or "")
        s2 = (o.get("size_text", "") or "").replace("mm", "").strip()
        if s2 in ("230","235","240","245","250","255","260","270","280"):
            lem[(c2, s2)] = 0 if o.get("stock", 0) == 0 else 999

    SOURCES = {
        "lemouton": (107709, lem),
        "musinsa":  (112159, load("musinsa")),
        "ssf":      (116627, load("ssf")),
        "lotteon":  (115430, load("lotteon")),
    }

    # 옵션 매핑
    options = list(cur.execute("SELECT canonical_sku, color_code, size_code FROM options WHERE model_code='르무통 클래식'"))

    # 두 모드로 옵션별 push 데이터 산출
    print()
    print("=" * 70)
    print("  모드 비교 — 36 옵션 push 데이터 (cap=10)")
    print("=" * 70)
    print(f'  {"SKU":<22} | sources(stock,price) | A:price/stock  | B:price/stock')
    print("  " + "-" * 95)

    diff_count = 0
    sample_rows = []
    for o in options:
        c, sz, sku = o["color_code"], o["size_code"], o["canonical_sku"]
        # 옵션별 가드 통과 source 들 (정책 B: gu_auto 적용)
        candidates = []
        for src_name, (price, data) in SOURCES.items():
            stock = data.get((c, sz))
            if stock is None:
                continue
            if not (gl_old <= price <= gu_auto):  # 정책 B 가드
                continue
            candidates.append((src_name, price, stock))

        # cheapest = 가드통과 source 중 가격 최저
        cheapest = min(candidates, key=lambda x: x[1]) if candidates else None

        # 모드 A: 색상 통일가 + cheapest 1곳 stock
        if cheapest:
            mode_a_price = ss_price
            mode_a_stock = min(cheapest[2], 10) if cheapest[2] > 0 else 0
        else:
            mode_a_price = 0
            mode_a_stock = 0

        # 모드 B: 옵션별 cheapest 가격으로 동적 산출
        # 단, stock > 0 인 source 중 cheapest 만 사용 (재고 0 source 제외)
        in_stock = [c for c in candidates if c[2] > 0]
        if in_stock:
            cheapest_in_stock = min(in_stock, key=lambda x: x[1])
            mode_b_price = per_option_push_price(cheapest_in_stock[1], fee, margin, pt["rounding_unit"])
            mode_b_stock = min(cheapest_in_stock[2], 10)
        else:
            mode_b_price = 0
            mode_b_stock = 0

        same = (mode_a_price == mode_b_price and mode_a_stock == mode_b_stock)
        if not same:
            diff_count += 1

        srcs_str = " ".join(f"{x[0][:3]}={x[2]}/{x[1]//1000}k" for x in candidates) if candidates else "-"
        line = f'  {sku:<22} | {srcs_str:<28} | {mode_a_price:>6,}/{mode_a_stock:<2} | {mode_b_price:>6,}/{mode_b_stock:<2}'
        if not same:
            line += "  ★"
        sample_rows.append((c, line))

    # 색상별 정렬해서 출력
    for color in ["그레이", "다크네이비", "블랙블랙", "블랙화이트"]:
        for c, line in sample_rows:
            if c == color:
                print(line)

    print()
    print(f"  두 모드 결과 차이: {diff_count}/36 옵션 ★")

    # 모드 B 만의 가격 분포
    print()
    print("=" * 70)
    print("  모드 B (옵션별 cheapest) — 색상별 가격 분포")
    print("=" * 70)
    from collections import defaultdict
    color_prices = defaultdict(list)
    for color in ["그레이", "다크네이비", "블랙블랙", "블랙화이트"]:
        for o in options:
            if o["color_code"] != color:
                continue
            c, sz = o["color_code"], o["size_code"]
            candidates = []
            for src_name, (price, data) in SOURCES.items():
                stock = data.get((c, sz))
                if stock is None or stock == 0:
                    continue
                if not (gl_old <= price <= gu_auto):
                    continue
                candidates.append((src_name, price, stock))
            if candidates:
                cheapest = min(candidates, key=lambda x: x[1])
                push_p = per_option_push_price(cheapest[1], fee, margin, pt["rounding_unit"])
                color_prices[color].append(push_p)
    for color, prices in color_prices.items():
        if prices:
            print(f"  {color:<10}: 옵션별 가격 = {set(prices)} (재고 있는 옵션 {len(prices)}개)")

    conn.close()


if __name__ == "__main__":
    main()

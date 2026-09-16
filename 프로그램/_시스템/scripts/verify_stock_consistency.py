# -*- coding: utf-8 -*-
"""재고 정합성 자동 검증 도구 (2026-06-25).

매트릭스 저장값(verify_input.json: 브라우저에서 다운로드) vs 각 소싱처 실제 크롤을
대조해 불일치만 리포트한다. 즉석 파서 금지 — 프로그램 자체 크롤러 + 검증된 API 사용.

  · ssf/ssg/lemouton : 프로그램 크롤러(정답 파서) standalone
  · lotteon          : pbf.lotteon.com 매핑 API (HTML→sitm→mapping, 대체상품 가드+999센티넬)
  · musinsa          : goods-detail API (/options + /prioritized-inventories)
  · ss_lemouton      : 네이버 WAF(서버 429) → 브라우저 전용, 스킵(표기)

비교 granularity(사이트가 주는 만큼만):
  · 정확수량 사이트(ssg/lotteon/musinsa) : 수량까지 비교 (999=충분·-1=불명·0=품절 정규화)
  · 충분만 주는 사이트(ssf/lemouton)      : 품절/있음(boolean) 수준 비교
실행(한국 IP 로컬): python verify_stock_consistency.py [verify_input.json]
"""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 프로그램/_시스템 (lemouton 패키지)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from curl_cffi import requests as R

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
_dig = lambda x: re.sub(r"\D", "", str(x or ""))
_nsz = lambda s: re.sub(r"\D", "", str(s or ""))     # 사이즈 숫자만


def _norm_exact(v):
    """정확수량 비교용 정규화."""
    if v is None:
        return "미크롤"
    if v == -1:
        return "불명"
    if isinstance(v, (int, float)) and v >= 900:
        return "충분"
    return v


def _norm_bool(v):
    """품절/있음 비교용."""
    if v is None:
        return "미크롤"
    if v == -1:
        return "불명"
    return "품절" if v == 0 else "있음"


# ── 소싱처별 실제 크롤 → {sizeNum: (color, stock)} 리스트 ──
def crawl_lotteon(url):
    lo = (re.search(r"/product/(LO[0-9]+)", url) or [None, None])[1]
    if not lo:
        return None
    h = R.get("https://www.lotteon.com/p/product/" + lo, impersonate="chrome120", timeout=20).text
    m = re.search(lo + r"_\d+", h)
    if not m:
        return None
    j = R.get("https://pbf.lotteon.com/product/v2/detail/option/mapping/%s/%s" % (lo, m.group(0)),
              impersonate="chrome120", headers={"accept": "application/json",
              "referer": "https://www.lotteon.com/p/product/" + lo}, timeout=20).json()
    oi = (j.get("data") or {}).get("optionInfo") or {}
    axes = oi.get("optionList") or []
    omi = oi.get("optionMappingInfo") or {}
    cA = next((a for a in axes if a.get("title") == "색상"), None)
    sA = next((a for a in axes if "사이즈" in (a.get("title") or "") or "size" in (a.get("title") or "").lower()), None)
    cOpts = (cA or {}).get("options") or [{"value": "", "label": ""}]
    sOpts = (sA or {}).get("options") or []
    spd = _dig(lo)
    out = []
    for c in cOpts:
        for s in sOpts:
            key = (c.get("value") or "") + "_" + (s.get("value") or "")
            sku = omi.get(key) or (omi.get(s.get("value")) if not c.get("value") else None)
            sz = _nsz(s.get("label"))
            if not sku or not sz:
                continue
            is_sub = spd and sku.get("spdNo") and _dig(sku.get("spdNo")) != spd
            sale = sku.get("sitmNoSlStatCd") == "SALE"
            q = sku.get("stkQty")
            try:
                q = int(q)
            except (TypeError, ValueError):
                q = 0
            st = 0 if is_sub else (q if (sale and q > 0 and q < 900) else (-1 if (sale and q >= 900) else 0))
            out.append((sz, (c.get("label") or "").strip(), st))
    return out


def crawl_musinsa(url):
    gid = (re.search(r"products/(\d+)", url) or [None, None])[1]
    if not gid:
        return None
    base = "https://goods-detail.musinsa.com/api2/goods/" + gid
    oj = R.get(base + "/options", impersonate="chrome120", headers={"accept": "application/json"}, timeout=15).json()
    d = oj.get("data") or {}
    items = d.get("optionItems") or []
    vnos = []
    for g in d.get("basic") or []:
        for v in (g.get("optionValues") or g.get("values") or []):
            if v.get("no") is not None:
                vnos.append(v["no"])
    ij = R.post(base + "/options/v2/prioritized-inventories", impersonate="chrome120",
                headers={"content-type": "application/json", "accept": "application/json"},
                data=json.dumps({"optionValueNos": vnos}), timeout=15).json()
    inv = {x.get("productVariantId"): x for x in (ij.get("data") or [])}
    out = []
    for it in items:
        code = it.get("managedCode") or ""
        color, size = ("", code.strip())
        if "^" in code:
            p = code.split("^"); color, size = (p[0] or "").strip(), (p[1] or "").strip()
        m = inv.get(it.get("no"))
        st = -1 if not m else (0 if m.get("outOfStock") else (max(0, m["remainQuantity"]) if isinstance(m.get("remainQuantity"), int) else 999))
        out.append((_nsz(size), color, st))
    return out


def crawl_via_project(url, source_key):
    """ssf/ssg/lemouton — 프로그램 크롤러 standalone."""
    if source_key == "ssf":
        from lemouton.sourcing.crawlers.ssf import SsfCrawler as C
    elif source_key == "ssg":
        from lemouton.sourcing.crawlers.ssg import SsgCrawler as C
    elif source_key == "lemouton":
        from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler as C
    else:
        return None
    cr = C().fetch(url)
    return [(_nsz(o.get("size_text")), (o.get("color_text") or "").strip(), o.get("stock")) for o in (cr.options or [])]


EXACT_SRC = {"ssg", "lotteon", "musinsa"}     # 정확수량 비교
BOOL_SRC = {"ssf", "lemouton"}                # 품절/있음 비교
SKIP_SRC = {"ss_lemouton", "lotteimall"}      # 브라우저 전용/별도


def real_for(src, url):
    if src == "lotteon":
        return crawl_lotteon(url)
    if src == "musinsa":
        return crawl_musinsa(url)
    if src in ("ssf", "ssg", "lemouton"):
        return crawl_via_project(url, src)
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/seung/Downloads/verify_input.json"
    data = json.load(open(path, encoding="utf-8"))
    total_ok = total_bad = 0
    print("=== 재고 정합성 전수 검증 ===")
    for spid, info in sorted(data.items(), key=lambda kv: (kv[1]["src"], int(kv[0]) if kv[0].isdigit() else 0)):
        src, url, stored = info["src"], info["url"], info["opts"]
        if src in SKIP_SRC:
            print("sp%-4s %-12s SKIP(브라우저전용)" % (spid, src))
            continue
        try:
            real = real_for(src, url)
        except Exception as e:
            print("sp%-4s %-12s CRAWL_ERR %s" % (spid, src, str(e)[:70]))
            continue
        if real is None:
            print("sp%-4s %-12s 크롤결과없음" % (spid, src))
            continue
        # size -> list of (color, stock)
        from collections import defaultdict
        rbysz = defaultdict(list)
        for sz, col, st in real:
            rbysz[sz].append((col, st))
        norm = _norm_exact if src in EXACT_SRC else _norm_bool
        ok = bad = 0
        misses = []
        for k, sv in stored.items():
            col, sz = k.split("|"); szn = _nsz(sz)
            cand = rbysz.get(szn)
            if not cand:
                continue
            # 색 매칭: 정확색 우선, 없으면 단일후보
            rv = None
            exact = [st for c, st in cand if c and (c == col or col in c or c in col)]
            if exact:
                rv = exact[0]
            elif len(cand) == 1:
                rv = cand[0][1]
            else:
                rv = cand[0][1]
            if norm(sv) == norm(rv):
                ok += 1
            else:
                bad += 1
                if len(misses) < 8:
                    misses.append("%s %s 저장=%s 실제=%s" % (col, sz, sv, rv))
        total_ok += ok; total_bad += bad
        flag = "✅" if bad == 0 else "❌"
        print("sp%-4s %-12s %s 일치 %d / 불일치 %d %s" % (spid, src, flag, ok, bad, ("| " + " ; ".join(misses)) if misses else ""))
    print("=== 합계: 일치 %d / 불일치 %d ===" % (total_ok, total_bad))


if __name__ == "__main__":
    main()

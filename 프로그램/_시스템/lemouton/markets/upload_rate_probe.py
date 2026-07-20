# -*- coding: utf-8 -*-
"""업로드 속도 한도 실측 프로브 — **쓰기 프로브**(조사용, 상시 기능 아님).

목적: 마켓별 **업로드 API** 가 실제로 몇 개까지 받아주는지 재고 **무변화 갱신**으로
      점진 증속하며 찾는다. 지금 프로그램에 박힌 한도는 전부 「조회」 한도를 빌려온
      가설값이라, 실측 없이는 제한장치를 제대로 만들 수 없다.

★ 지키는 선
  ① 가격은 어떤 경로로도 건드리지 않는다. 재고 필드만.
     (스마트스토어 edit_options 는 sale_price=None 으로 현재값 유지)
  ② 현재 재고를 못 읽으면 **쓰지 않는다** — 무변화를 보장할 수 없으므로.
  ③ 429 만 한도초과로 센다. 403(IP 미등록)·401·500 을 429 로 읽으면 **없는 상한을
     날조**한다. 그 경우 '판별불가'로 남긴다.
  ④ 시작 전 원래 재고를 기억하고(Baseline), 끝나면 원복하고 **다시 읽어 확인**한다.

마켓 API 는 서버 IP 허용목록에 묶여 있어 로컬 PC 에서는 인증 이전에 거부된다.
그래서 이 모듈은 서버에서 돌고, `webapp/routes/upload_rate_probe.py` 가 통로다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# 1건 업로드에 드는 API 호출 수 — lemouton/uploader/throttle.py 와 같아야 한다
from lemouton.uploader.throttle import calls_per_upload  # noqa: E402  (재수출)

__all__ = [
    "ProbeUnsafe", "WriteOutcome", "Baseline", "Toggler",
    "is_rate_limited", "status_of_exception", "read_stock", "write_stock",
    "noop_write", "measure_burst", "ramp_up", "recommended_rate",
    "calls_per_upload",
]


class ProbeUnsafe(RuntimeError):
    """안전 전제가 깨져 프로브를 시작·계속할 수 없다."""


@dataclass(frozen=True)
class WriteOutcome:
    status: Optional[int]
    headers: Optional[dict]
    elapsed_ms: float
    error: Optional[str] = None

    @property
    def is_rate_limited(self) -> bool:
        return is_rate_limited(self.status)


# ── 판정 ────────────────────────────────────────────────────────

def is_rate_limited(status) -> bool:
    """429 만 한도초과. 403·401·500 은 아니다(다른 원인)."""
    return status == 429


def status_of_exception(exc) -> Optional[int]:
    """예외에서 HTTP 상태코드를 뽑는다. 없으면 None(=한도로 오해 금지)."""
    st = getattr(exc, "status_code", None)
    if isinstance(st, int):
        return st
    # 스마트스토어는 429 를 전용 예외로 던진다(상태코드 속성이 없다)
    if type(exc).__name__ == "SmartStoreRateLimitError":
        return 429
    return None


# ── 읽기 ────────────────────────────────────────────────────────

def read_stock(market: str, *, client, product_id: str, option_id: str) -> Optional[int]:
    """현재 재고. 못 읽으면 None (0 으로 대체 금지 — 품절 둔갑)."""
    try:
        if market == "coupang":
            from shared.platforms.coupang.inventory import get_quantity
            return get_quantity(int(option_id), client=client)

        if market == "smartstore":
            from shared.platforms.smartstore.get_options import fetch_product_options
            r = fetch_product_options(int(product_id), client=client)
            if not getattr(r, "success", False):
                return None
            for o in r.options:
                if str(o.option_id) == str(option_id):
                    return o.stock
            return None

        if market == "lotteon":
            from shared.platforms.lotteon.products import get_product_detail, extract_items
            detail = get_product_detail(str(product_id), client=client)
            for it in extract_items(detail):
                if str(it.get("sitm_no")) == str(option_id):
                    return it.get("stock")
            return None

        if market == "eleven11":
            # option_id = prdStckNo(재고번호) — 재고수량 변경 키와 같은 것
            from shared.platforms.eleven11.stocks_query import get_stocks
            for s in (get_stocks(str(product_id), client=client) or []):
                if str(s.get("prd_stck_no") or "") == str(option_id):
                    return s.get("stock")
            return None

        if market in ("auction", "gmarket"):
            from shared.platforms.esm.inventory import (
                get_recommended_options, _option_id_of)
            from shared.platforms.esm.products import (
                site_field, _ci_get, get_goods_detail)
            key = site_field(market)
            # option_id 가 비면 **옵션 없는 단일상품** → 본품 재고를 읽는다.
            #   ESM 은 사이트별 값을 qty{gmkt|iac} 로 준다 — products._site_val 이 정본.
            if not str(option_id).strip():
                from shared.platforms.esm.products import _site_val
                det = get_goods_detail(str(product_id), client=client)
                for cand in ("qty", "stock", "stockQty", "quantity"):
                    q = _ci_get(det, cand)
                    if isinstance(q, dict):
                        v = _site_val(q, market)
                        if v is not None:
                            return int(v)
                    elif q is not None:
                        try:
                            return int(q)
                        except (TypeError, ValueError):
                            pass
                return None
            for d in (get_recommended_options(str(product_id), client=client) or []):
                if _option_id_of(d) == str(option_id):
                    qty = _ci_get(d, "qty")
                    if not isinstance(qty, dict):
                        return None
                    for k, v in qty.items():
                        if str(k).lower() == key:
                            return int(v) if v is not None else None
                    return None
            return None
    except Exception as e:  # noqa: BLE001 — 못 읽은 것은 못 읽은 것. 추정 금지.
        logger.warning("[upload_probe] 재고 조회 실패 %s %s/%s: %s",
                       market, product_id, option_id, e)
        return None
    raise ProbeUnsafe(f"미지원 마켓: {market}")


# ── 쓰기 (재고만) ───────────────────────────────────────────────

def write_stock(market: str, *, client, product_id: str, option_id: str, stock: int):
    """재고만 기록한다. **가격은 어떤 인자로도 넘기지 않는다.**

    응답 객체(또는 None)를 돌려주고, 실패는 예외로 표면화한다
    (bool 로 삼키면 429 를 못 본다).
    """
    stock = int(stock)
    if stock < 0:
        raise ProbeUnsafe(f"재고는 0 이상이어야 한다: {stock}")

    if market == "coupang":
        from shared.platforms import COUPANG
        path = COUPANG["paths"]["update_quantity"].format(
            vendorItemId=int(option_id), quantity=stock)
        return client.request(method="PUT", path=path)

    if market == "lotteon":
        from shared.platforms import LOTTEON
        cfg = getattr(client, "_cfg", None) or LOTTEON
        body = {"itmStkLst": [{
            "trGrpCd": cfg.get("tr_grp_cd", "SR"),
            "trNo": cfg.get("tr_no", ""),
            "lrtrNo": cfg.get("lrtr_no", ""),
            "spdNo": str(product_id),
            "sitmNo": str(option_id),
            "stkQty": stock,
        }]}
        return client.request(method="POST",
                              path=cfg["paths"]["stock_change"], body=body)

    if market == "eleven11":
        from shared.platforms.eleven11.inventory import _PATH_STOCKQTY, _xml_escape
        body = ('<?xml version="1.0" encoding="euc-kr"?>'
                f"<ProductStock><prdNo>{_xml_escape(str(product_id))}</prdNo>"
                f"<prdStckNo>{_xml_escape(str(option_id))}</prdStckNo>"
                f"<stckQty>{stock}</stckQty></ProductStock>")
        return client.request("PUT",
                              _PATH_STOCKQTY.format(prd_stck_no=str(option_id)), body)

    if market == "smartstore":
        # sale_price=None → **현재값 유지**. 판매가를 명시 전달하지 않는다.
        from shared.platforms.smartstore.edit_product import edit_options
        return edit_options(int(product_id),
                            option_updates={int(option_id): {"stockQuantity": stock}},
                            client=client)

    if market in ("auction", "gmarket"):
        from shared.platforms.esm.inventory import (
            get_recommended_options, _option_id_of, _set_site_qty)
        # option_id 가 비면 **옵션 없는 단일상품** → 본품 재고 경로(문서 /194)
        if not str(option_id).strip():
            from shared.platforms.esm.products import site_field
            cfg0 = getattr(client, "_cfg", None) or {}
            tmpl = (cfg0.get("paths") or {}).get("stock_change")
            if not tmpl:
                raise ProbeUnsafe("ESM 본품 재고수정 경로 미설정")
            return client.request(method="PUT",
                                  path=tmpl.format(goodsNo=str(product_id)),
                                  body={"stock": {site_field(market): stock}})
        details = get_recommended_options(str(product_id), client=client)
        target = next((d for d in details
                       if _option_id_of(d) == str(option_id)), None)
        if target is None:
            raise ProbeUnsafe(f"대상 옵션 없음: {product_id}/{option_id}")
        _set_site_qty(target, market, stock)
        cfg = getattr(client, "_cfg", None) or {}
        path = (cfg.get("paths") or {})["options"].format(goodsNo=str(product_id))
        return client.request(method="PUT", path=path, body={"details": details})

    raise ProbeUnsafe(f"미지원 마켓: {market}")


# ── 무변화 갱신 1회 ─────────────────────────────────────────────

def noop_write(market: str, *, client, product_id: str, option_id: str,
               known_stock: Optional[int] = None) -> WriteOutcome:
    """현재값을 읽어 **그 값 그대로** 다시 쓴다.

    ``known_stock`` 을 주면 조회를 건너뛴다(측정 루프에서 매회 조회하면
    호출 수가 2배가 되어 속도 측정이 오염된다).
    """
    cur = known_stock if known_stock is not None else read_stock(
        market, client=client, product_id=product_id, option_id=option_id)
    if cur is None:
        return WriteOutcome(None, None, 0.0,
                            error="현재 재고를 못 읽어 무변화를 보장할 수 없음 — 쓰지 않음")

    t0 = time.monotonic()
    try:
        resp = write_stock(market, client=client, product_id=product_id,
                           option_id=option_id, stock=int(cur))
    except Exception as e:  # noqa: BLE001
        st = status_of_exception(e)
        return WriteOutcome(st, None, (time.monotonic() - t0) * 1000,
                            error=f"{type(e).__name__}: {e}")
    return WriteOutcome(getattr(resp, "status_code", 200),
                        dict(getattr(resp, "headers", {}) or {}),
                        (time.monotonic() - t0) * 1000)


# ── 기준선(기억·원복) ───────────────────────────────────────────

@dataclass
class Baseline:
    market: str
    product_id: str
    option_id: str
    original_stock: int
    captured_at: float

    @classmethod
    def capture(cls, market: str, *, client, product_id: str,
                option_id: str) -> "Baseline":
        """시작 전 원래 재고를 기억한다. 못 읽으면 시작 자체를 막는다."""
        cur = read_stock(market, client=client, product_id=product_id,
                         option_id=option_id)
        if cur is None:
            raise ProbeUnsafe(
                f"{market} {product_id}/{option_id}: 현재 재고를 못 읽음 — "
                f"원복을 보장할 수 없어 시작하지 않는다")
        return cls(market, str(product_id), str(option_id), int(cur), time.time())

    def restore(self, *, client) -> WriteOutcome:
        """원래 값을 다시 쓴다."""
        t0 = time.monotonic()
        try:
            resp = write_stock(self.market, client=client,
                               product_id=self.product_id,
                               option_id=self.option_id,
                               stock=self.original_stock)
        except Exception as e:  # noqa: BLE001
            return WriteOutcome(status_of_exception(e), None,
                                (time.monotonic() - t0) * 1000,
                                error=f"원복 실패 {type(e).__name__}: {e}")
        return WriteOutcome(getattr(resp, "status_code", 200), None,
                            (time.monotonic() - t0) * 1000)

    def verify_restored(self, *, client) -> bool:
        """썼다고 믿지 않고 **다시 읽어** 원래 값인지 확인한다."""
        cur = read_stock(self.market, client=client,
                         product_id=self.product_id, option_id=self.option_id)
        return cur is not None and int(cur) == int(self.original_stock)

    def as_dict(self) -> dict:
        return {"market": self.market, "product_id": self.product_id,
                "option_id": self.option_id,
                "original_stock": self.original_stock,
                "captured_at": self.captured_at}


class Toggler:
    """무변화가 안 통할 때의 대안 — 재고 ±1 토글.

    ★ 반드시 **짝수 회**로 끝내야 원래 값으로 돌아온다(``at_original`` 확인).
    """

    def __init__(self, market: str, *, client, product_id: str, option_id: str,
                 base_stock: int):
        self.market = market
        self.client = client
        self.product_id = str(product_id)
        self.option_id = str(option_id)
        self.base = int(base_stock)
        self._n = 0

    @property
    def at_original(self) -> bool:
        return self._n % 2 == 0

    def step(self) -> WriteOutcome:
        target = self.base + 1 if self._n % 2 == 0 else self.base
        t0 = time.monotonic()
        try:
            resp = write_stock(self.market, client=self.client,
                               product_id=self.product_id,
                               option_id=self.option_id, stock=target)
        except Exception as e:  # noqa: BLE001
            self._n += 1
            return WriteOutcome(status_of_exception(e), None,
                                (time.monotonic() - t0) * 1000,
                                error=f"{type(e).__name__}: {e}")
        self._n += 1
        return WriteOutcome(getattr(resp, "status_code", 200),
                            dict(getattr(resp, "headers", {}) or {}),
                            (time.monotonic() - t0) * 1000)


# ── 측정 ────────────────────────────────────────────────────────

def measure_burst(probe: Callable[[], WriteOutcome], *,
                  max_calls: int = 60) -> dict:
    """간격 없이 연속 호출 → 첫 429 직전까지의 성공 수 = 버스트 용량."""
    ok = 0
    for _ in range(max_calls):
        r = probe()
        if r.is_rate_limited:
            return {"capacity": ok, "hit_429": True, "note": ""}
        if r.status is None or r.status >= 400:
            return {"capacity": ok, "hit_429": False,
                    "note": f"429 아닌 오류 status={r.status} — 중단(판별불가)"}
        ok += 1
    return {"capacity": ok, "hit_429": False,
            "note": "상한 미도달 — max_calls 를 올려 재측정 필요"}


def ramp_up(holds_at: Callable[[float], bool], steps=(0.2, 0.5, 1, 2, 3, 5, 8, 12, 20)) -> dict:
    """계단식 증속. 처음 실패한 계단과 그 직전 성공 계단.

    이분탐색만 하면 첫 시도가 최고속도라 곧바로 차단당한다.
    """
    last_ok = None
    for rate in steps:
        if holds_at(rate):
            last_ok = rate
        else:
            return {"last_ok": last_ok, "first_fail": rate}
    return {"last_ok": last_ok, "first_fail": None}


def recommended_rate(measured_max: float, *, margin: float = 0.7) -> float:
    """제한장치에 넣을 값 = 실측 상한 × 안전마진.

    경계값을 그대로 쓰면 순간 지터로 429 가 난다.
    """
    return round(float(measured_max) * float(margin), 2)

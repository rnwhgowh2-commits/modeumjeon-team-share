# -*- coding: utf-8 -*-
"""롯데온 중개셀러통합정보(SettleItmdSales) — 구매확정 주문의 완전 정산 성분.

POST /v1/openapi/settle/v1/se/SettleItmdSales (startDate/endDate yyyymmdd, 정산기준일=구매확정일).
data[] 단품 라인 → 주문번호별 지급대상금액(pymtAmt) 합 + 제휴 여부(pcsCmsn>0). 폴백·추측 없음.
정산완료 주문은 이 값이 마켓 실지급액 = 계산 불필요.
"""
import logging
from datetime import datetime
from typing import Optional

from shared.platforms import LOTTEON as _CFG
from shared.platforms.lotteon.client import LotteonClient
from shared.platforms.lotteon.claims import _windows

_log = logging.getLogger(__name__)

_PATH = "/v1/openapi/settle/v1/se/SettleItmdSales"

PAGE_SIZE = 100          # 롯데온 목록 API 의 rowsPerPage 상한(settle_orders 와 동일 실측)

#  롯데온 정산 계열 성공 코드(settle_orders 실측과 동일) — 화이트리스트가 좁으면
#  성공 응답을 실패로 읽는다. "SUCCESS"·"0000" 둘 다 성공.
_OK_CODES = {"", "0", "00", "0000", "success", "ok"}


def _ok(resp: dict) -> bool:
    return str((resp or {}).get("returnCode") or "").strip().lower() in _OK_CODES


def _fetch_itmd_rows(cfg: dict, w_from: datetime, w_to: datetime, *, client) -> list:
    """한 창(≤29일)의 **전체** data 행. 페이징을 먼저 시도하고 거부되면 무페이징으로 되돌린다.

    🔴 페이징이 필요한데 안 넣으면 첫 100건만 조용히 오고 나머지가 사라진다
      (settle_orders._fetch_window 의 실측 사고와 동형). dataCount 로 끝을 판정한다.
    """
    base = {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
            "lrtrNo": cfg.get("lrtr_no", ""),
            "startDate": w_from.strftime("%Y%m%d"), "endDate": w_to.strftime("%Y%m%d")}

    def _req(page=None):
        body = dict(base)
        if page is not None:
            body["pageNo"] = page
            body["rowsPerPage"] = PAGE_SIZE
        return client.request(method="POST", path=_PATH, body=body) or {}

    # 🔴 중복 제거로 블로업 방지 — 서버가 pageNo 를 무시하고 같은 100건을 계속 주는데
    #   dataCount 마저 없으면(이 endpoint 는 참조 SettleProduct 와 다를 수 있다) 끝 판정이
    #   안 걸려 page 1000 까지 append → parse_itmd 가 pymtAmt 를 최대 1000배 부풀린다.
    #   참조 _fetch_window 는 호출부(iter_rows)가 (odNo,odSeq,procSeq)로 dedup 해 면역이지만
    #   여기 소비자(parse_itmd)는 dedup 이 없으므로 수집 단계에서 직접 접는다.
    seen: set = set()

    def _extend(dst: list, got: list) -> int:
        added = 0
        for r in got:
            key = (str(r.get("odNo") or ""), str(r.get("odSeq") or ""),
                   str(r.get("procSeq") or ""))
            if key in seen:
                continue
            seen.add(key)
            dst.append(r)
            added += 1
        return added

    first = _req(page=1)
    if not _ok(first):
        # 페이징 파라미터를 안 받는 API 일 수 있다 → 원래 방식(무페이징)으로 1회.
        plain = _req(page=None)
        if not _ok(plain):
            # 조용한 실패 금지 — 부분/빈 수집을 성공처럼 넘기지 않고 예외로 올린다
            #   (참조 _fetch_window 규약과 동일 → 스윕 stat['errors']·인라인 추정 폴백).
            raise RuntimeError(
                f"SettleItmdSales 실패 {base['startDate']}~{base['endDate']}: "
                f"paged={first.get('returnCode')} plain={plain.get('returnCode')} "
                f"{plain.get('returnMessage') or first.get('returnMessage') or ''}")
        return list(plain.get("data") or [])

    rows: list = []
    _extend(rows, list(first.get("data") or []))
    total = first.get("dataCount")
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None

    page = 1
    while True:
        if len(rows) < PAGE_SIZE * page:              # 마지막 페이지가 상한 미만 → 끝
            break
        if total is not None and len(rows) >= total:  # dataCount 를 다 채움 → 끝
            break
        page += 1
        if page > 1000:                               # 무한 페이징 방지
            _log.warning("SettleItmdSales 페이지 상한 도달 %s~%s",
                         base["startDate"], base["endDate"])
            break
        nxt = _req(page=page)
        if not _ok(nxt):
            # 중간 페이지 실패 = 부분 수집. 조용히 넘기면 정산액이 과소 → 예외로 올린다.
            raise RuntimeError(
                f"SettleItmdSales 페이지 {page} 실패 {base['startDate']}~{base['endDate']}: "
                f"{nxt.get('returnCode')} {nxt.get('returnMessage') or ''}")
        got = list(nxt.get("data") or [])
        if not got or _extend(rows, got) == 0:        # 새 행이 없으면(서버가 pageNo 무시) 끝
            break
    if total is not None and len(rows) < total:
        _log.warning("SettleItmdSales 수집 부족 %s~%s: %d/%d",
                     base["startDate"], base["endDate"], len(rows), total)
    return rows


def _num(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _is_product_line(r: dict) -> bool:
    """이 정산 행이 **상품 판매대금**인가 — 아니면 주문에 붙은 별도 항목인가.

    🔴🔴 [2026-08-04] 왜 갈라야 하나 (라이브 정합성 검사에서 드러남)
      셀러오피스 크롤과 공식 API 를 전수 대조하니 4건이 어긋났는데, **넷 다 공식 쪽이
      정확히 10,000원**이었다. 원문을 보니 상품 정산이 아닌 별도 라인이었다:
        정상  procSeq "1"   spdNo "LO2679592341"  165,207원
        문제  procSeq "202" spdNo ""               10,000원
      옛 코드는 procSeq 구분 없이 전부 합산해, 그 주문에 상품 라인이 아직 없으면
      **10,000원이 그 주문의 정산예정금**이 됐다(실제 지급액은 9,868·54,187·−1,436).

    ★판별을 **procSeq 목록이 아니라 상품번호(spdNo) 유무**로 하는 이유 —
      라이브 전수(2026-05-01~08-04, 7계정 833행) 결과가 완전히 갈렸다:
        procSeq 1·2·3      760행 → 상품번호 **전부 있음**  (2=환불, 금액 음수)
        procSeq 202~207·빈값 73행 → 상품번호 **전부 없음**  (거의 다 정확히 10,000원)
      procSeq 허용목록(1,2,3)으로 거르면 롯데온이 새 번호(4·208…)를 쓰기 시작한 날
      **멀쩡한 상품 정산을 조용히 버린다**. 상품번호는 「상품 정산인가」를 직접 묻는
      질문이라 새 번호가 생겨도 안 깨진다.

    ★별도 항목을 **버리는** 게 아니라 상품 라인에 **섞지 않는** 것이다. 섞으면 그 벌의
      판매대금이 아닌 돈이 판매대금으로 보여 마진이 틀린다. 상품 라인이 아예 없는
      주문은 「아직 상품 정산이 안 잡힘」이 사실이고, 그 자리는 셀러오피스 크롤값이나
      추정이 채운다(그쪽이 실제 지급액을 안다 — 위 4건에서 크롤이 맞았다).
    """
    return bool(str(r.get("spdNo") or "").strip())


def parse_itmd(resp: dict) -> dict:
    out: dict = {}
    for r in ((resp or {}).get("data") or []):
        od = str(r.get("odNo") or "")
        if not od or not _is_product_line(r):
            continue                       # 상품 정산이 아닌 별도 라인 — 위 주석 참조
        cur = out.setdefault(od, {"pymtAmt": 0, "pcs_cmsn": 0, "is_affiliate": False})
        cur["pymtAmt"] += _num(r.get("pymtAmt"))
        pcs = _num(r.get("pcsCmsn"))
        cur["pcs_cmsn"] += pcs
        if pcs > 0:
            cur["is_affiliate"] = True
    return out


def parse_itmd_lines(resp: dict) -> dict:
    """SettleItmdSales data → {(odNo, odSeq): pymtAmt} **라인(벌) 단위** 지급액.

    🔴 왜 odNo 총액이 아니라 라인 단위인가 (2026-07-25 다품 1건 실측·라이브 diag 확인)
      네이버 롯데온 정산은 **벌(odSeq)마다 별도 pymtAmt** 를 준다(주문 2026070213054145:
      odSeq1=41,624 · odSeq2=41,624). `parse_itmd` 는 이를 odNo 로 합산(83,248)하는데,
      order_export·스윕이 그 **주문 총액을 각 라인에 통째로 대입**해 2벌 주문이 정확히
      2배가 됐다(각 라인 83,248 → 합 166,496 = 2×). 라인 키로 나눠 대입하면 각 41,624 =
      샵마인 벌값과 일치한다. 같은 (odNo,odSeq) 의 여러 procSeq(부분취소 등)는 합산.

    ★[2026-08-04] 상품 정산이 아닌 별도 라인은 뺀다 — `_is_product_line` 주석 참조.
      부분취소(procSeq 2, 금액 음수)는 상품번호가 있으므로 그대로 합산된다(순액 규약 유지).
    """
    out: dict = {}
    for r in ((resp or {}).get("data") or []):
        od = str(r.get("odNo") or "")
        if not od or not _is_product_line(r):
            continue
        key = (od, str(r.get("odSeq") or ""))
        out[key] = out.get(key, 0) + _num(r.get("pymtAmt"))
    return out


def parse_itmd_line_dates(resp: dict) -> dict:
    """SettleItmdSales data → {(odNo, odSeq): seStdDt} **구매확정일**.

    🔴 [2026-08-12] 이 필드가 응답에 **줄곧 있었는데 우리가 안 읽고 있었다**
      (라이브 진단 실측: ajstDcAmt·…·seStdDt·… 36개 필드 중 하나).
      seStdDt = 정산기준일 = **구매확정일**이고, 롯데온 지급내역(실입금일)이 바로
      이 날짜 단위로 묶여 있다(lotteon_paid.paid_date_map 의 키). 그래서 이 값이
      없으면 「롯데온은 입금 확인 창구가 없다」가 되고, 있으면 조인이 된다.

    ★ 같은 라인의 procSeq 가 여럿이면 **가장 이른 날**을 쓴다 — 부분취소 등으로 뒤에
      붙은 회차가 원래 확정일을 밀어내면 안 된다.
    """
    out: dict = {}
    for r in ((resp or {}).get("data") or []):
        od = str(r.get("odNo") or "")
        if not od or not _is_product_line(r):
            continue
        d = str(r.get("seStdDt") or "").strip()[:10].replace("/", "-")
        if len(d) == 8 and d.isdigit():
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if len(d) != 10:
            continue                       # 날짜가 아니면 담지 않는다(날조 금지)
        key = (od, str(r.get("odSeq") or ""))
        if key not in out or d < out[key]:
            out[key] = d
    return out


def itmd_line_map(since: datetime, until: datetime, *,
                  client: Optional[LotteonClient] = None,
                  with_dates: bool = False):
    """[since, until] 구매확정 주문의 {(odNo, odSeq): pymtAmt} — 라인(벌) 단위 지급액.

    with_dates=True 면 `(금액맵, 구매확정일맵)` 두 개를 돌려준다 — 같은 응답에서
    같이 뽑는다(창을 두 번 부르면 롯데온을 두 번 두들기고 경계도 어긋난다).
    """
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or _CFG
    rows = _fetch_all_itmd_rows(cfg, since, until, client=client)
    amts = parse_itmd_lines({"data": rows})
    if with_dates:
        return amts, parse_itmd_line_dates({"data": rows})
    return amts


def _fetch_all_itmd_rows(cfg: dict, since: datetime, until: datetime, *, client) -> list:
    """[since, until] 전 구간의 SettleItmdSales data 행 — **창을 가로질러 dedup**.

    🔴 왜 여기서 다시 dedup 하나 (2026-07-25 샵마인 실측 6건·+37만원, pymtAmt 정확히 2배)
      `_windows` 는 [cur, cur+step], [cur+step, ...] 로 나뉘어 **경계일이 앞뒤 창에 겹친다**
      (endDate == 다음 startDate, 정산 API 는 날짜 범위 양끝 포함). `_fetch_itmd_rows` 의
      `seen` 은 **창 하나 안에서만** 접어서, 경계일에 구매확정된 주문의 (odNo,odSeq,procSeq)
      행이 두 창에 각각 한 번씩 들어온다. 옛 코드는 창별 parse_itmd 결과를 pymtAmt += 로
      합산해 그 주문이 정확히 2배가 됐다. 라인 단위로 한 번만 세도록 여기서 접는다.
    """
    all_rows: list = []
    seen: set = set()
    for w_from, w_to in _windows(since, until):
        for r in _fetch_itmd_rows(cfg, w_from, w_to, client=client):
            key = (str(r.get("odNo") or ""), str(r.get("odSeq") or ""),
                   str(r.get("procSeq") or ""))
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(r)
    return all_rows


def itmd_map(since: datetime, until: datetime, *,
             client: Optional[LotteonClient] = None) -> dict:
    """[since, until] 구매확정 주문의 {odNo:{pymtAmt,pcs_cmsn,is_affiliate}}."""
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or _CFG
    # 창을 가로질러 라인 단위로 접은 뒤 **한 번만** 집계 — 경계일 이중가산 방지.
    rows = _fetch_all_itmd_rows(cfg, since, until, client=client)
    return parse_itmd({"data": rows})


def parse_product_affiliate(resp: dict) -> dict:
    """{spdNo: bool} — 그 상품 라인에 제휴(pcsCmsn>0)가 하나라도 있으면 True."""
    out: dict = {}
    for r in ((resp or {}).get("data") or []):
        sp = str(r.get("spdNo") or "")
        if not sp:
            continue
        out[sp] = out.get(sp, False) or (_num(r.get("pcsCmsn")) > 0)
    return out


def scan(since: datetime, until: datetime, *,
         client: Optional[LotteonClient] = None):
    """한 번 순회로 (주문별 정산맵, 라인별 지급액맵, 상품별 제휴여부맵) 반환.

    주문맵  = {odNo:{pymtAmt,pcs_cmsn,is_affiliate}} — 제휴 판정용(odNo 단위 집계).
    라인맵  = {(odNo,odSeq): pymtAmt} — **정산액 대입용**(다품 주문 2배 방지, parse_itmd_lines).
    상품맵  = {spdNo: bool} — 미정산 주문의 제휴 여부를 상품 이력으로 추정하는 데 쓴다(판매경로는
    고객 유입경로라 주문 API엔 없음 → 상품별 제휴 이력이 최선 추정).

    ★정산액은 반드시 라인맵으로 대입한다 — 주문맵(odNo 총액)을 각 라인에 통째로 넣으면
      다품(2벌) 주문이 정확히 2배가 된다(2026-07-25 실측 1건, diag 확인 odSeq1=odSeq2=41,624).
    """
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or _CFG
    # 창을 가로질러 라인 단위로 접은 뒤 **한 번만** 집계 — 경계일 이중가산 방지
    #  (itmd_map 과 동일 규약). 옛 코드는 창별 결과를 pymtAmt += 로 합쳐, 경계일 구매확정
    #  주문이 정확히 2배가 됐다(2026-07-25 실측 6건).
    rows = _fetch_all_itmd_rows(cfg, since, until, client=client)
    resp = {"data": rows}
    orders = parse_itmd(resp)
    lines = parse_itmd_lines(resp)
    products = parse_product_affiliate(resp)
    return orders, lines, products

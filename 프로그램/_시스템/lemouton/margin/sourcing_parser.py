# -*- coding: utf-8 -*-
"""Phase 2a 호환 레이어 (블랙스팟 원본 검사 로직은 sourcing_checker 에).

블랙스팟 원본 `sourcing_checker.py` 에 있는 `SOURCING_SITES`, `detect_site_key`
는 그대로 재노출 (동일 사전/로직).

`extract_memo_info` 는 이 파일에서 Phase 2a 버전으로 로컬 정의.
(블랙스팟 버전과 regex 가 달라 공유하지 않음 — 기존 테스트·`/api/fetch_order_no`
  는 Phase 2a 버전을 통해 호출되어야 함)

Phase 2a 에서만 추가된 `detect_order_no_from_url`, `fetch_order_no` 는 유지.
"""
import re

# 블랙스팟 원본과 공용 (동일 사전/함수)
from lemouton.margin.sourcing_sites import SOURCING_SITES, detect_site_key


def extract_memo_info(memo) -> dict:
    """간단메모에서 URL·계정·소싱처명·주문번호 추출 (Phase 2a 버전).

    메모 예시:
        26.04.14 무신사 / rnwhgowh1 은순 https://www.musinsa.com/order/order-detail/ABC
        25.08.03 주문번호 : 202508031019270004 -. 계정 : 무신사/rnwhgowh2

    Returns:
        {"url", "account_id", "site_name", "site_key", "order_no"}
    """
    result = {"url": "", "account_id": "", "site_name": "",
              "site_key": "", "order_no": ""}

    if not memo or not isinstance(memo, str):
        return result

    memo = memo.strip()

    # 1) 주문번호 텍스트 (URL 없어도 잡힘)
    #    주의: 영문 키워드 앞에 다른 영문이 붙지 않도록 negative lookbehind 로 단어 경계 보장
    #    (예: "orordNo=XXX" 에서 "ordNo" 매칭 방지)
    on_match = re.search(
        r'(?<![A-Za-z])(?:주문번호|orderNo|ord_no|order_no|oid|ordNo)\s*[:：=]?\s*([A-Za-z0-9][A-Za-z0-9_\-]{5,29})',
        memo,
    )
    if on_match:
        result["order_no"] = on_match.group(1).strip()

    # 2) URL 추출
    url_match = re.search(r'(https?://\S+)', memo)
    if url_match:
        result["url"] = url_match.group(1).rstrip(")")

    # 3) site_key: URL 우선, 없으면 소싱처명 텍스트
    if result["url"]:
        result["site_key"] = detect_site_key(result["url"])
    if not result["site_key"]:
        # site name map from blackspot's sourcing_checker
        from lemouton.margin.sourcing_sites import _SITE_NAME_KEY_MAP
        for name, key in _SITE_NAME_KEY_MAP.items():
            if name in memo:
                result["site_key"] = key
                result["site_name"] = name
                break

    # 4) 계정ID + 소싱처명
    #   패턴A: "날짜 소싱처명 / 계정ID 이름 URL"
    slash_match = re.search(r'[\d.]+\s+(.+?)\s*/\s*(\S+)', memo)
    if slash_match:
        if not result["site_name"]:
            result["site_name"] = slash_match.group(1).strip()
        result["account_id"] = slash_match.group(2).strip()
    else:
        # 패턴B: "계정 : 무신사/rnwhgowh2"
        acct_match = re.search(r'계정\s*[:：]\s*([^\s/]+)\s*/\s*(\S+)', memo)
        if acct_match:
            if not result["site_name"]:
                result["site_name"] = acct_match.group(1).strip()
            result["account_id"] = acct_match.group(2).strip().rstrip(".,")

    return result


def _template_to_regex(template: str) -> str:
    """order_detail_url 템플릿을 정규식으로 변환.

    예: "https://www.musinsa.com/order/order-detail/{orderNo}"
         → r"^https?://www\\.musinsa\\.com/order/order\\-detail/([A-Za-z0-9\\-_]+)"

    {orderNo} 위치는 캡처그룹, 나머지는 literal escape.
    쿼리스트링 추가 파라미터 허용 (URL 뒤에 &other=... 가 와도 매칭).
    """
    if "{orderNo}" not in template:
        return ""
    parts = template.split("{orderNo}")
    escaped = [re.escape(p) for p in parts]
    pattern = "^" + "([A-Za-z0-9\\-_]+)".join(escaped)
    return pattern


def detect_order_no_from_url(url: str, site_key: str) -> str:
    """URL 에서 해당 site_key 의 주문번호 추출.

    SOURCING_SITES[site_key]['order_detail_url'] 템플릿을 역변환해 매칭.
    매칭 실패 시 빈 문자열.
    """
    if not url or not site_key:
        return ""
    site_cfg = SOURCING_SITES.get(site_key)
    if not site_cfg:
        return ""
    template = site_cfg.get("order_detail_url", "")
    if not template:
        return ""
    pattern = _template_to_regex(template)
    if not pattern:
        return ""
    m = re.match(pattern, url)
    if m:
        return m.group(1)
    return ""


def fetch_order_no(memo) -> dict:
    """간단메모에서 소싱처 주문번호 자동 추출.

    우선순위:
      1) 메모 텍스트에 "주문번호: XXX" 또는 "orderNo=XXX" 형태로 명시됨
      2) 메모 URL 의 path/query 에서 템플릿 매칭으로 추출
      3) 실패 시 수동 입력 유도

    Returns:
        {success, order_no, site_key, site_name, account_id, source, logs, error}
    """
    logs = []
    result = {
        "success":    False,
        "order_no":   "",
        "site_key":   "",
        "site_name":  "",
        "account_id": "",
        "source":     "",
        "logs":       logs,
        "error":      "",
    }

    if not memo:
        result["error"] = "간단메모 비어있음"
        logs.append("간단메모가 비어있어 추출 불가")
        return result

    logs.append(f"[1/3] 간단메모 파싱 중... (길이 {len(str(memo))}자)")
    info = extract_memo_info(memo)
    result["site_key"]   = info.get("site_key", "")
    result["site_name"]  = info.get("site_name", "") or (
        SOURCING_SITES.get(info.get("site_key", ""), {}).get("name", "")
    )
    result["account_id"] = info.get("account_id", "")

    # 1) 텍스트 주문번호
    if info.get("order_no"):
        logs.append(f"[2/3] 메모 텍스트에서 주문번호 발견: {info['order_no']}")
        result["success"]  = True
        result["order_no"] = info["order_no"]
        result["source"]   = "메모텍스트"
        logs.append(f"[3/3] ✓ {result['site_name'] or '소싱처'} 주문번호: {info['order_no']}")
        return result

    # 2) URL 에서 추출
    if info.get("url") and info.get("site_key"):
        logs.append(f"[2/3] 메모 URL 에서 {result['site_name']} 주문번호 파싱 시도...")
        order_no = detect_order_no_from_url(info["url"], info["site_key"])
        if order_no:
            result["success"]  = True
            result["order_no"] = order_no
            result["source"]   = "URL파싱"
            logs.append(f"[3/3] ✓ URL 에서 주문번호 추출: {order_no}")
            return result
        logs.append("URL 에 주문번호 포함 안 됨")

    # 3) 실패
    if not info.get("url") and not info.get("order_no"):
        result["error"] = "메모에 주문번호·URL 둘 다 없음 — 수동 입력 필요"
    elif not info.get("site_key"):
        result["error"] = "소싱처 식별 불가 — 수동 입력 필요"
    else:
        result["error"] = "URL 에서 주문번호 추출 실패 — 수동 입력 필요"
    logs.append(f"[3/3] ✗ 추출 실패: {result['error']}")
    return result

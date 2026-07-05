"""크롤 실패 사유 → 유형 분류 (순수 함수).

에러 메시지의 키워드로 유형을 판정한다. 근거 = 크롤링 가이드 §5 에러 이력·재고탭
(차단/로그인/파싱·매핑/타임아웃). 어느 유형에도 안 걸리면 '유형 외'(etc) —
유형 외를 계속 줄이며 개선하기 위해 별도로 표기한다.

실제 실패 데이터가 담기는 필드·화면 연결은 후속(P5 실행중/실패 UI).
"""

# 우선순위 순서(위에서부터 먼저 매칭). 키워드는 소문자 비교.
FAILURE_TYPES = {
    "block":   {"label": "차단",       "emoji": "🚫",
                "keywords": ["차단", "waf", "403", "forbidden", "blocked", "captcha", "봇", "bot"]},
    "login":   {"label": "로그인",     "emoji": "🔑",
                "keywords": ["로그인", "login", "회원", "인증", "session", "세션", "401", "unauthorized", "로그아웃"]},
    "parse":   {"label": "옵션 못읽음", "emoji": "🧩",
                "keywords": ["옵션없음", "옵션 없음", "파싱", "parse", "매핑", "미매칭", "no option", "옵션 li"]},
    "network": {"label": "응답 지연",   "emoji": "⏱",
                "keywords": ["타임아웃", "timeout", "timed out", "네트워크", "network", "econn", "refused", "응답 없음", "연결"]},
    "etc":     {"label": "유형 외",     "emoji": "❔", "keywords": []},
}

_ORDER = ["block", "login", "parse", "network"]


def classify_crawl_failure(status, error_message):
    """실패 1건을 유형으로. status가 실패가 아니면 None.

    반환: {"type", "label", "emoji"} 또는 None(실패 아님).
    """
    if status == "ok":
        return None
    msg = (error_message or "").lower()
    for t in _ORDER:
        if any(k.lower() in msg for k in FAILURE_TYPES[t]["keywords"]):
            return {"type": t, "label": FAILURE_TYPES[t]["label"], "emoji": FAILURE_TYPES[t]["emoji"]}
    # 어느 유형에도 안 걸림(메시지 없음 포함) → 유형 외
    return {"type": "etc", "label": FAILURE_TYPES["etc"]["label"], "emoji": FAILURE_TYPES["etc"]["emoji"]}

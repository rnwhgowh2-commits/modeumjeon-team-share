# -*- coding: utf-8 -*-
"""소싱처 사이트 설정·URL 매핑 — 블랙스팟 `modules/sourcing_checker.py` 에서
순수 데이터/순수 파싱 조각만 발췌 이식.

원본 `sourcing_checker.py`(3944줄) 는 Playwright 크롬 프로필 로그인·주문상태 DOM
파싱까지 섞여 있다. 여기엔 그중 **브라우저·네트워크 없이** 동작하는 순수 조각만 옮긴다:

  · SOURCING_SITES     (사이트별 설정 dict — order_detail_url 템플릿 포함)  원본 37–323
  · _URL_SITE_MAP      (호스트명 → site_key)                               원본 348–364
  · detect_site_key()  (URL → site_key, urlparse 만 사용)                  원본 530–543
  · _SITE_NAME_KEY_MAP (소싱처명 텍스트 → site_key)                        원본 404–415

이식하지 않은 것(브라우저 코드 — 로컬 확장 Task E2 소관): LOGIN_METHODS·프로필 관리·
쿠키·`check_order_sync`·`_run_in_pw_loop`·상태 DOM 파서 등 나머지 전부.

sourcing_parser.fetch_order_no 의 순수 파싱 경로가 import 하는 것은 위 4개뿐이라
바로 그 4개만 옮겼다.
"""
from urllib.parse import urlparse


# ═══════════════════════════════════════════════════════════
# 소싱처 설정 (원본 sourcing_checker.py 37–323 그대로)
# ═══════════════════════════════════════════════════════════

SOURCING_SITES = {
    "musinsa": {
        "name": "무신사",
        "home_url": "https://www.musinsa.com",
        "login_url": "https://www.musinsa.com/auth/login",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://www.musinsa.com/order/order-detail/{orderNo}",
        "delivery_trace_url": "https://www.musinsa.com/order-service/my/delivery/trace?ord_no={orderNo}",
        "selectors": {
            "courier": "p.company-name",
            "tracking": "button.tracking-number",
        },
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "우체국택배": "우체국택배", "로젠택배": "로젠택배",
            "로센택배": "로젠택배", "경동택배": "경동택배",
        },
        "has_chatbot": True,
    },
    "ssg": {
        "name": "SSG",
        "home_url": "https://www.ssg.com",
        "login_url": "https://login.ssg.com/login/login.ssg",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://pay.ssg.com/myssg/orderInfoDetail.ssg?orordNo={orderNo}",
        "selectors": {
            "courier": ".tx_state em span",
            "tracking_container": ".tx_state em",
        },
        "courier_name_map": {
            "대한통운": "CJ대한통운", "CJ대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "롯데(현대)택배": "롯데택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "abc": {
        "name": "ABC마트",
        "home_url": "https://abcmart.a-rt.com",
        "login_url": "https://abcmart.a-rt.com/login",
        "login_button_selectors": [
            'a[href*="/login"]',
            'a:has-text("LOGIN")',
            'a:has-text("로그인")',
        ],
        "order_detail_url": "https://abcmart.a-rt.com/mypage/order/read-order-detail?orderNo={orderNo}",
        "selectors": {
            "courier": "div.status-info .info-desc",
            "tracking": "div.status-info .info-link",
        },
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "롯데(현대)택배": "롯데택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "abcGs": {
        "name": "그랜드스테이지",
        "home_url": "https://grandstage.a-rt.com",
        "login_url": "https://grandstage.a-rt.com/login",
        "login_button_selectors": [
            'a[href*="/login"]',
            'a:has-text("LOGIN")',
            'a:has-text("로그인")',
        ],
        "order_detail_url": "https://grandstage.a-rt.com/mypage/order/read-order-detail?orderNo={orderNo}",
        "selectors": {
            "courier": "div.status-info .info-desc",
            "tracking": "div.status-info .info-link",
        },
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "롯데(현대)택배": "롯데택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "gs": {
        "name": "GS샵",
        "home_url": "https://www.gsshop.com",
        "login_url": "https://www.gsshop.com/member/login.gs",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://www.gsshop.com/ord/dlvcursta/popup/ordDtl.gs?ordNo={orderNo}&ecOrdTypCd=S",
        "selectors": {
            "tracking_link": 'a[data-action="dlvTrace"]',
        },
        "courier_code_map": {
            "CJ": "CJ대한통운", "HJ": "한진택배", "KG": "로젠택배",
            "LO": "롯데택배", "LT": "롯데택배", "EP": "우체국택배",
            "POST": "우체국택배", "RZ": "로젠택배", "DS": "대신택배",
            "IL": "일양로지스", "KD": "경동택배", "CH": "천일택배",
            "HD": "롯데택배", "SL": "SLX택배",
        },
    },
    "folder": {
        "name": "폴더스타일",
        "home_url": "https://www.folderstyle.com",
        "login_url": "https://www.folderstyle.com/member/login.html",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://www.folderstyle.com/mypage/orderDetail?oid={orderNo}",
        "order_history_url": "https://www.folderstyle.com/mypage/orderHistory",
        "selectors": {
            "invoice_link": "a.devInvoice",
        },
        "courier_code_map": {
            "01": "우체국택배", "04": "CJ대한통운", "05": "한진택배",
            "06": "로젠택배", "08": "롯데택배", "09": "기타택배",
            "11": "경동택배", "12": "일양로지스", "13": "CU편의점택배",
            "14": "대신택배", "17": "천일택배", "18": "롯데택배",
            "22": "CJ대한통운", "23": "한진택배", "24": "롯데택배",
        },
    },
    "ssfshop": {
        "name": "SSF",
        "home_url": "https://www.ssfshop.com",
        "login_url": "https://www.ssfshop.com/public/member/login",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://www.ssfshop.com/secured/mypage/{orderNo}/orderInfo",
        "selectors": {
            "delivery_button": 'button[onclick*="checkDelivery"]',
        },
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "롯데(현대)택배": "롯데택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "lotteimall": {
        "name": "롯데아이몰",
        "home_url": "https://www.lotteimall.com",
        "login_url": "https://www.lotteimall.com/main/viewMain.lotte",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://www.lotteimall.com/mypage/getOrderDtlInfo.lotte?ord_no={orderNo}",
        "selectors": {
            "delivery_trace_func": "fn_DeliveryTrace",
        },
        "courier_name_map": {
            "롯데글로벌로지스": "롯데택배", "롯데택배": "롯데택배",
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "lotteon": {
        "name": "롯데온",
        "home_url": "https://www.lotteon.com",
        "login_url": "https://www.lotteon.com/login",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "selectors": {
            "delivery_detail_button": "배송상세조회",
        },
        "courier_name_map": {
            "롯데택배": "롯데택배", "롯데(현대)택배": "롯데택배",
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배",
        },
    },
    "nike": {
        "name": "나이키",
        "home_url": "https://www.nike.com/kr",
        "login_url": "https://www.nike.com/kr/login",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
            'button:has-text("Sign In")',
        ],
        "order_detail_url": "https://www.nike.com/kr/orders/sales/{orderNo}/",
        "courier_url_map": {
            "cjlogistics.com": "CJ대한통운", "hanjin.co.kr": "한진택배",
            "lotteglogis.com": "롯데택배", "epost.go.kr": "우체국택배",
            "ilogen.com": "로젠택배", "doortodoor.co.kr": "기타택배",
            "kdexp.com": "경동택배",
        },
        "tracking_param_map": {
            "cjlogistics.com": "gnbInvcNo", "hanjin.co.kr": "waybillNo",
            "lotteglogis.com": "InvNo", "epost.go.kr": "sid1",
            "ilogen.com": "slipno",
        },
    },
    "oliveyoung": {
        "name": "올리브영",
        "home_url": "https://www.oliveyoung.co.kr",
        "login_url": "https://www.oliveyoung.co.kr/store/mypage/login.do",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://www.oliveyoung.co.kr/store/mypage/getOrderDetail.do?ordNo={orderNo}",
        "selectors": {
            "popup": ".layer_pop_wrap",
            "section_heading": "배송 정보",
            "list_container_class": "lineBox2",
        },
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "롯데(현대)택배": "롯데택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "gmarket": {
        "name": "지마켓",
        "home_url": "https://www.gmarket.co.kr",
        "login_url": "https://signinssl.gmarket.co.kr/login/login",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://my.gmarket.co.kr/ko/pc/detail/basic/{orderNo}",
        "tracking_url": "https://tracking.gmarket.co.kr/track/{orderNo}",
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "롯데(현대)택배": "롯데택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "fashionplus": {
        "name": "패션플러스",
        "home_url": "https://www.fashionplus.co.kr",
        "login_url": "https://www.fashionplus.co.kr/login",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "order_detail_url": "https://www.fashionplus.co.kr/mypage/order/detail/{orderNo}",
        "tracking_url": "https://trace.goodsflow.com/VIEW/V1/whereis/fashionplus/{orderNo}-{itemNo}",
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "롯데택배": "롯데택배", "롯데(현대)택배": "롯데택배",
            "한진택배": "한진택배", "우체국택배": "우체국택배",
            "로젠택배": "로젠택배", "경동택배": "경동택배",
        },
    },
    "lemouton": {
        "name": "르무통",
        "home_url": "https://lemouton.co.kr",
        "login_url": "https://lemouton.co.kr/member/login.html",
        "login_button_selectors": [
            'a[href*="login"]',
            'a:has-text("로그인")',
            'button:has-text("로그인")',
        ],
        "selectors": {},
        "courier_name_map": {
            "CJ대한통운": "CJ대한통운", "대한통운": "CJ대한통운",
            "한진택배": "한진택배", "롯데택배": "롯데택배",
            "우체국택배": "우체국택배", "로젠택배": "로젠택배",
        },
    },
}


# ═══════════════════════════════════════════════════════════
# URL → site_key 매핑 (원본 348–364 그대로)
# ═══════════════════════════════════════════════════════════

_URL_SITE_MAP = {
    "musinsa.com":       "musinsa",
    "ssg.com":           "ssg",
    "a-rt.com":          "abc",     # ABC마트 / 그랜드스테이지 공용
    "gsshop.com":        "gs",
    "ssfshop.com":       "ssfshop",
    "lotteimall.com":    "lotteimall",
    "lottehomeshopping.com": "lotteimall",
    "lotteon.com":       "lotteon",
    "nike.com":          "nike",
    "oliveyoung.co.kr":  "oliveyoung",
    "gmarket.co.kr":     "gmarket",
    "fashionplus.co.kr": "fashionplus",
    "folderstyle.com":   "folder",
    "folder.co.kr":      "folder",
    "lemouton.co.kr":    "lemouton",
}


# ── 소싱처명 텍스트 → site_key 매핑 (원본 404–415 그대로) ──
_SITE_NAME_KEY_MAP = {
    "무신사": "musinsa", "MUSINSA": "musinsa",
    "SSF샵": "ssfshop", "SSF": "ssfshop", "ssfshop": "ssfshop",
    "ABC마트": "abc", "ABC": "abc", "abcmart": "abc",
    "그랜드스테이지": "grandstage",
    "롯데아이몰": "lotteimall", "롯데홈쇼핑": "lotteimall", "lotteimall": "lotteimall",
    "롯데온": "lotteon",
    "GS샵": "gs", "gs샵": "gs",
    "SSG": "ssg", "ssg": "ssg",
    "폴더": "folder", "folder": "folder",
    "르무통": "lemouton",
}


def detect_site_key(url: str) -> str:
    """URL에서 소싱처 site_key 판별. (원본 530–543 그대로)"""
    if not url:
        return ""
    try:
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower()
    except Exception:
        return ""

    for pattern, key in _URL_SITE_MAP.items():
        if pattern in hostname:
            return key
    return ""

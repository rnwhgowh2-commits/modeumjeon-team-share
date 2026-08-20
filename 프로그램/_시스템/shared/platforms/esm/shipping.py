# -*- coding: utf-8 -*-
"""ESM(옥션·G마켓) 발송처리 — ShippingInfo · 택배사 코드 · 거짓성공 방지.

발송처리(문서 /70): POST /shipping/v1/Delivery/ShippingInfo
  body = {"OrderNo": long, "ShippingDate": "YYYY-MM-DDThh:mm:ss",
          "DeliveryCompanyCode": int, "InvoiceNo": "..."}
  · ShippingDate 는 호출시점 2일 이내여야 한다(문서).
  · DeliveryCompanyCode 는 아래 코드표의 값만 유효.

택배사 코드표 = 마켓 조회 API(GET /item/v1/shipping/delivery-company)가 2026-07-21 에
그대로 돌려준 201개 전부(추측·문서 베끼기 아님 — 마켓 본인의 답).
이름이 우리 화면 표기와 동일한 한국어라 그대로 매칭된다(로젠택배·롯데택배 등).
"""
from __future__ import annotations

import datetime as _dt

PATH = "/shipping/v1/Delivery/ShippingInfo"

# 마켓 조회 API 원본 그대로 (deliveryCompName -> deliveryCompCode)
COURIER_CODES: dict = {
    '대한통운': 10001,
    '로젠택배': 10003,
    '우체국택배': 10005,
    '등기우편': 10006,
    '한진택배': 10007,
    '롯데택배': 10008,
    'CJ택배': 10013,
    '대신택배': 10014,
    '일양택배': 10015,
    '경동택배': 10016,
    '천일택배': 10017,
    'DHL': 10022,
    'FEDEX': 10023,
    '일반우편': 10024,
    '퀵서비스': 10025,
    'LG전자물류': 10027,
    '삼성전자물류': 10028,
    '직접배송': 10031,
    '자체배송': 10032,
    '기타택배': 10034,
    '방문수령': 10035,
    'EMS': 10036,
    '(소형항공)우체국': 10038,
    '우리택배': 10039,
    'USPS': 10041,
    'UPS': 10042,
    'GSMNTON': 10043,
    'WarpEx': 10044,
    '성원글로벌': 10045,
    '홈플러스택배': 10048,
    '건영택배': 10050,
    'WIZWA': 10051,
    '(해외)우체국': 10054,
    '(해외)DHL': 10055,
    '(해외)DPD': 10056,
    '(G마켓)CJ택배': 10065,
    '(G마켓)편의점택배': 10067,
    '(G마켓)대한통운': 10068,
    '기타': 10070,
    'CJ국제특송': 10072,
    '편의점택배(GS25)': 10073,
    '합동택배': 10074,
    '롯데국제특송': 10075,
    'SLX': 10077,
    '대우전자': 10078,
    '범한판토스': 10079,
    'GPS LOGIX': 10080,
    '한의사랑택배': 10081,
    '세방택배': 10082,
    '쉽트랙': 10084,
    'ACI': 10085,
    'Gsfresh': 10086,
    '택배사미정': 10089,
    'Global Shipping2': 10091,
    'Global Shipping3': 10092,
    'Global Shipping4': 10093,
    'Global Shipping': 10094,
    'Global Shipping5': 10095,
    '롯데마트': 10096,
    '트랙스로지스': 10097,
    '현대글로비스': 10098,
    '부릉': 10099,
    '이마트몰': 10100,
    '투데이': 10101,
    '아르고': 10102,
    '위니온로지스': 10103,
    '한덱스': 10104,
    'TNT': 10105,
    'i-parcel': 10106,
    '대운글로벌': 10107,
    '에어보이익스프레스': 10108,
    'LineExpress': 10109,
    'GSI익스프레스': 10110,
    'ECMS익스프레스': 10111,
    'EFS': 10112,
    '시알로지텍': 10113,
    '브리지로지스': 10114,
    'Cway express': 10115,
    'ACE express': 10116,
    '스마트로지스': 10117,
    '에스더쉬핑': 10118,
    '로토스': 10119,
    '은하쉬핑': 10120,
    '유프레이트 코리아': 10121,
    '하이브시티': 10122,
    'LTL': 10123,
    '캐나다쉬핑': 10124,
    '지디에이코리아': 10125,
    '올타코리아': 10126,
    'yunda express': 10127,
    '웅지익스프레스': 10128,
    'YDH': 10129,
    'ACCcargo': 10130,
    '허싱카고코리아': 10131,
    '시노트랜스': 10132,
    '패스트박스': 10133,
    '팬스타국제특송': 10134,
    '에이씨티앤코아물류': 10135,
    'kt express': 10136,
    'ibpcorp': 10137,
    '엠티인터네셔널': 10138,
    '골드스넵스': 10139,
    'BGF포스트': 10140,
    '용마로지스': 10141,
    '원더스퀵': 10142,
    '농협택배': 10143,
    'HI택배': 10144,
    '홈픽택배': 10145,
    'KGL네트웍스': 10146,
    '2fast익스프레스': 10147,
    'GTS로지스': 10148,
    '홈이노베이션로지스': 10149,
    '자이언트': 10150,
    '우리동네택배': 10151,
    '퍼레버택배': 10152,
    '엘서비스': 10153,
    '로지스밸리택배': 10154,
    '제니엘시스템': 10155,
    '애니트랙': 10156,
    '제이로지스트': 10157,
    '두발히어로': 10158,
    '큐런': 10159,
    '프레시솔루션': 10160,
    '한샘': 10161,
    '굿투럭': 10162,
    '지니고': 10163,
    '카카오 T 당일배송': 10164,
    '노곡물류': 10165,
    '스페이시스원': 10166,
    '로지스팟': 10167,
    'DHL GlobalMail': 10168,
    '프레시메이트': 10169,
    'NK로지솔루션': 10170,
    '도도플렉스': 10171,
    '배송하기좋은날': 10172,
    '이투마스': 10173,
    '에이스물류': 10174,
    '바바바로지스': 10175,
    '롯데칠성': 10176,
    '발렉스': 10177,
    '국제익스프레스': 10178,
    '윈핸드해운항공': 10179,
    '탱고앤고': 10180,
    'SBGLS': 10181,
    '핑퐁': 10182,
    '1004홈': 10183,
    '나은물류': 10184,
    '엔티엘피스': 10185,
    '삼다수가정배송': 10186,
    '딜리래빗': 10187,
    '홈픽오늘도착': 10188,
    '대림통운': 10189,
    '로지스파트너': 10190,
    '고박스': 10191,
    '케이제이티': 10192,
    '더함전자물류': 10193,
    '오늘회러쉬': 10194,
    '한국야구르트': 10195,
    '로지스밸리': 10196,
    '라스트마일시스템즈': 10197,
    '에이치케이홀딩스': 10198,
    '직구문': 10199,
    '큐브플로우': 10200,
    '성훈물류': 10201,
    '지비에스': 10202,
    '반품구조대': 10203,
    '화물을부탁해': 10204,
    'Global Shipping6': 10205,
    'Global Shipping7': 10206,
    'Global Shipping8': 10207,
    'Global Shipping9': 10208,
    'Global Shipping10': 10209,
    '팀프레시': 10210,
    'Global Shipping11': 10211,
    'Global Shipping12': 10212,
    'Global Shipping13': 10213,
    'Global Shipping14': 10214,
    'Global Shipping15': 10215,
    'Global Shipping16': 10216,
    'Global Shipping17': 10217,
    'Global Shipping18': 10218,
    'Global Shipping19': 10219,
    'Global Shipping20': 10220,
    '지에이치스피드': 10221,
    '쉽트랙(Ship G)': 10223,
    '딜리박스': 10224,
    '티에스지로지스': 10225,
    'ocs': 10226,
    '든든택배': 10227,
    '모든로지스': 10228,
    '물류대장': 10229,
    '제이더블유티앤엘': 10230,
    '지케이글로벌': 10231,
    'JCLS': 10232,
    '고넬로': 10234,
    'Cainiao': 10235,
    'CU 편의점택배': 10236,
    '이마트24 편의점택배': 10237,
    '온데이 당일택배': 10238,
    '(G마켓)CJ택배_신용': 10240,
    '한샘소파': 10241,
}


def send_shipping(order_no, courier_code: int, invoice_no, *, client,
                  shipping_date: _dt.datetime | None = None) -> None:
    """발송처리 1건. 성공이면 조용히 반환, 실패면 사유를 담아 RuntimeError.

    ★ 거짓 성공 금지 — HTTP 200 이어도 ResultCode 가 0/success 가 아니면 실패다.
      마켓이 본문에 적어 보낸 Message 를 그대로 올린다(읽지 않고 버리면 원인 추적 불가
      — 2026-07-20~21 세 번 데인 패턴).
    """
    if shipping_date is None:
        shipping_date = _dt.datetime.now()
    body = {
        "OrderNo": int(order_no),
        "ShippingDate": shipping_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "DeliveryCompanyCode": int(courier_code),
        "InvoiceNo": str(invoice_no),
    }
    resp = client.post(PATH, body) or {}
    rc = resp.get("ResultCode")
    if rc in (0, "0", None) or str(rc).strip().lower() == "success":
        return
    raise RuntimeError(
        f"ESM 발송처리 거부 ResultCode={rc} {resp.get('Message') or ''}".strip())


ORDER_CHECK_PATH = "/shipping/v1/Order/OrderCheck/{OrderNo}"


def order_check(order_no, *, client) -> None:
    """주문확인(문서 /68) — 결제완료 → 배송준비중. 성공 조용히, 실패 사유와 함께 예외.

    ★ 주문번호 단위로만 처리 가능(문서 p27). ResultCode≠0 은 마켓 Message 포함 실패.
    """
    path = ORDER_CHECK_PATH.format(OrderNo=int(order_no))
    resp = client.post(path, {}) or {}
    rc = resp.get("ResultCode")
    if rc in (0, "0", None) or str(rc).strip().lower() == "success":
        return
    raise RuntimeError(
        f"ESM 주문확인 거부 ResultCode={rc} {resp.get('Message') or ''}".strip())

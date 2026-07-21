# -*- coding: utf-8 -*-
"""[일회성] 2026-07-22 판매처 지도 최신화 — 4마켓 실등록·판매중지·옵션 실측 반영.

update-data-code-map 갈래 A. 근거 커밋: f7913c17~ef6c0929 (본 세션 라이브 실증).
실행 후 validate_map·pytest 통과 확인하고 이 스크립트는 남겨둔다(갱신 근거 기록).
"""
import io
import json

P = 'webapp/data/marketplace_api_map.json'
d = json.load(io.open(P, encoding='utf-8'))
apis = d['apis']
by_id = {a['id']: a for a in apis}

changed = {'st': 0, 'traps': 0, 'inc': 0}


def promote(aid, note):
    a = by_id.get(aid)
    if a and a.get('st') != 'ok':
        a['st'] = 'ok'
        changed['st'] += 1
    if a is not None:
        traps = a.setdefault('idTraps', [])
        if note and note not in traps:
            traps.append(note)
            changed['traps'] += 1


def add_traps(aid, notes):
    a = by_id.get(aid)
    if not a:
        return
    traps = a.setdefault('idTraps', [])
    for n in notes:
        if n not in traps:
            traps.append(n)
            changed['traps'] += 1


# ── st 승격 + 핵심 트랩 (라이브 실증 상품번호를 근거로 명기) ──
for m in ('auction', 'gmarket'):
    promote(f'{m}.esm.20',
            '[2026-07-21 라이브 실증] 실등록→판매중지 왕복 성공(옥션 6477606513·G마켓 6477646133, '
            '파이프라인 6477870979/6477875678). 구현: shared/platforms/esm/products.py')
    add_traps(f'{m}.esm.20', [
        '★등록 400 3함정(실측): ①price·stock 은 Gmkt·Iac **둘 다 required**(stock 0 불가·price 10원~10억) — '
        '비대상 사이트에 0 넣으면 400. 노출 사이트는 itemBasicInfo.category.site[] 가 결정 '
        '②itemAddtionalInfo.isAdultProduct 필수(지도 required 공란이지만 실 API 는 400) '
        '③shipping.policy.feeType=2(상품별배송비)면 each{feeType,feePayType,fee} 필수',
        '★마스터 카탈로그는 옥션·G마켓 공용 — siteId 검색에도 반대 사이트 전용 상품이 섞인다. '
        '선행자원(발송정책 등) 재사용 시 값이 다 찰 때까지 본보기 상품을 순회할 것(1건만 보면 G마켓 실패 실측). '
        '상세 순회 + 옵션 봉투 조회를 분리하면 60초(gunicorn) 초과 502 — 한 순회에서 같이 수확',
    ])
    promote(f'{m}.esm.155',
            '[2026-07-22 라이브 실측] catCode 조회 성공 — details[].recommendedOptNo(색상=1·신발사이즈=977 등)와 '
            "'직접입력'=optNo 0 이 존재. 축코드 0 이면 옵션명·값 직접입력으로 등록 가능(합성 봉투 실증)")
    add_traps(f'{m}.esm.26', [
        '[2026-07-22 실측] 신규 상품 옵션 부착 = 등록(무옵션) 직후 이 API 로 PUT. 봉투는 기존 옵션상품 GET '
        '실물 미러링 또는 합성(축코드 recommendedOptNo1/2=0 직접입력·recommendedOptValue1/2.koreanText). '
        '값·재고·추가금·노출·품절은 사이트별 4키(qty/addAmntSite/isDisplaySite/isSoldOutSite). '
        '부착 실패 시 옵션 없는 단일상품이 판매중으로 남으므로 즉시 set_sold_out 회수(파이프라인 배선됨)',
    ])

promote('eleven11.81',
        '[2026-07-21 라이브 실증] 실등록→전시중지 성공(9508004984·9508128090·옵션 9508477357). '
        '구현: shared/platforms/eleven11/products.py build_register_xml+register_product')
add_traps('eleven11.81', [
    '★XML 선언은 euc-kr 로(client 가 body 를 euc-kr 인코딩 — UTF-8 선언이면 한글에서 500 "Invalid UTF-8 start byte")',
    '★실측 필수(스펙 [필수] 표기 밖): aplBgnDy/aplEndDy(YYYY/MM/DD·selTermUseYn=N=영구판매), rtngExchDetail(교환반품안내)',
    '★상품정보제공고시 ProductNotification: type 891011=9개 항목 필수. 코드표 첨부 미확보 시 같은 유효코드 '
    '23759468 을 9번 중복해도 통과(실증 우회). 검증순서=①개수 ②코드존재(에러 오라클로 판별 가능)',
    '★계정당 판매중 상품 10,000개 한도 — 초과 계정은 등록 자체 거부(브랜드박스·위시 실측). 여유 계정으로 등록',
    '★옵션 = 싱글옵션 ProductOption 반복(optSelectYn=Y·colTitle·colValue0="색상/사이즈" 조합값·colCount=옵션별 재고·'
    'colOptPrice). 멀티옵션은 API 로 옵션별 재고 불가(일괄만)·옵션가 0원만',
])
promote('eleven11.42', '[2026-07-21 라이브 실증] 전시중지 즉시 가능(ESM 과 달리 등록 직후 대기 불필요). 검증=selStatCd 105')
promote('eleven11.43',
        '[2026-07-21 라이브 실측] outboundarea=출고지(addrSeq). ★반품지는 문서에 없는 대칭 경로 '
        'GET /rest/areaservice/inboundarea 가 실재(addrSeq 별도) — 등록 addrSeqIn 은 반품지 addrSeq 를 써야 함')
promote('eleven11.tegory',
        '[2026-07-22 라이브 실측] 전체 트리 반환(depth/leafYn/parentDispNo) — 대량등록 카테고리 이름검색 배선'
        '(GET /bulk/api/category-search?market=eleven11)')

promote('lotteon.product.create',
        '[2026-07-21 라이브 실증] 실등록→판매종료 성공(LO2729045338·LO2729068316·옵션 LO2729209534). '
        '구현: shared/platforms/lotteon/products.py build_register_payload+register_product')
add_traps('lotteon.product.create', [
    '★★body 는 {"spdLst":[{...}]} 래퍼 필수 — 래퍼 없이 보내면 returnCode 9999+"정상 처리되었습니다"+data[] 로 '
    '**0건 접수를 정상이라 답한다**(조용한 무시·상품 미생성)',
    '★★성공/실패는 최상위 returnCode 가 아니라 data[] 항목별 resultCode — 성공=data[0].spdNo 발급만',
    '★등록 body = 기존 상품 detail 응답과 동일 구조(본보기 복사가 정공법). 필수 실측 23필드는 '
    'products.py _REGISTER_TEMPLATE_FIELDS. slStrtDttm/slEndDttm 은 YYYYMMDDHHMMSS 숫자만',
    '★"출고지 번호 필수" 에러의 실필드명은 owhpNo(출하지)·회수지=rtrpNo — dvpNo 아님. 값은 getDvpListSr 의 dvpNo',
    '★단품 itmOptLst 의 optNm 은 카테고리 사전값(색상/의류 사이즈 등) — 임의 변경하면 "판매옵션정보를 선택해주세요". '
    'optVal 만 교체. 옵션 상품 = 본보기 단품 복제(itmLst 다건·대표 rprtSitmYn 1개)',
    '★구 경로 /v1/openapi/product/v1/product/regist 는 404(yaml TODO 였음) — registration/request 가 정답',
    '⚠️신규 등록 직후 detail 의 stkQty 가 999999999 로 표시(보낸 값 아님 — 심사중 추정). 정식 운영은 등록 후 재고 API 재설정 권장',
])
promote('lotteon.product.status.change',
        '[2026-07-21 라이브 실증] slStatCd END 로 판매종료 + detail 재조회 검증. 즉시 가능(대기 불필요)')
promote('lotteon.contract.location.list',
        '[2026-07-21 라이브 실측] body={afflTrCd:trNo}. dvpTypCd 01=회수지/02=출고지(같은 dvpNo 가능). '
        '등록의 owhpNo/rtrpNo 값 원천')
promote('lotteon.contract.shipcost.list',
        '[2026-07-21 라이브 실측] body={afflTrCd:trNo} — dvCstPolNo 재사용(등록 시 기존 계약 재사용으로 3계약 신규등록 불필요)')

# ── incidents (HARD-RULE 4 — 이번 실증에서 해결한 것 전부) ──
NEW_INCIDENTS = [
    {"id": "2026-07-21-esm-register-400-triple", "date": "2026-07-21",
     "markets": ["auction", "gmarket"], "area": "상품등록",
     "title": "ESM 등록 400 3연발 — 양쪽 price/stock 필수·isAdultProduct·개별배송비 each",
     "symptom": "옥션 전용 등록인데 400 이 3번: ①Gmkt 필드 1~10억/1~99999 범위 ②isAdultProduct 누락 ③개별배송비(each) 필수.",
     "cause": "비대상 사이트(Gmkt)에 0 을 넣는 조립(반대편 0 이라는 가정)·isAdultProduct 는 지도 required 공란이지만 실 API 필수·feeType 2 는 each 하위블록 요구.",
     "fix": "build_esm_register_payload: price/stock 양쪽 유효값(노출은 category.site 가 통제)·isAdultProduct=False 고정·policy.each={feeType:1,feePayType:1,fee:0}. register-esm 진단이 실패 시 esm_body(4xx 본문)를 표면화해 사유를 드러냄.",
     "commit": "d9267444,4dbfafa7,5855ae72", "severity": "high", "status": "resolved",
     "lesson": "dry-run(조립 검증)은 마켓 수용성을 못 잡는다 — 400 본문(resultCode 1000 message)이 진짜 스펙이다. raise_for_status 로 본문을 버리면 스펙 발굴이 불가능해진다."},
    {"id": "2026-07-21-esm-master-catalog-crosssite-prereq", "date": "2026-07-21",
     "markets": ["gmarket"], "area": "상품등록",
     "title": "G마켓 선행자원이 빈다 — 마스터 카탈로그 공용이라 옥션 전용 상품이 섞임(+순회 분리 시 60초 502)",
     "symptom": "siteId=2 검색 첫 상품에서 선행자원을 뜨면 dispatch_policy_no(gmkt)=0 으로 등록 실패. 본보기·옵션봉투 순회를 따로 돌리자 60초 초과 502.",
     "cause": "ESM 마스터 카탈로그는 옥션·G마켓 공용 — siteId 필터에도 반대 사이트 전용 상품이 반환된다. 상세조회 순회 2회(선행자원+옵션봉투)는 gunicorn 60초를 넘긴다.",
     "fix": "send_more._register_esm: 선행자원이 다 찰 때까지 최대 15건 순회하며, 같은 순회에서 옵션형 상품(봉투 본보기)도 동시 수확. 502 재발 0.",
     "commit": "7f3c6fd5,c9be38bc", "severity": "high", "status": "resolved",
     "lesson": "ESM 에서 '그 사이트의 값'이 필요하면 첫 검색 결과를 믿지 말고 값이 찰 때까지 순회하라. 라이브 왕복이 긴 순회는 한 번에 겸용으로."},
    {"id": "2026-07-22-esm-option-attach-synth-envelope", "date": "2026-07-22",
     "markets": ["auction", "gmarket"], "area": "상품등록",
     "title": "신규 상품 옵션 부착 — 봉투 미러링/합성(축코드 0=직접입력)·실패 시 자동 판매중지 회수",
     "symptom": "등록 payload 의 recommendedOpts 로는 옵션값번호가 필요해 보였고, G마켓은 봉투 본보기(옵션형 판매중 상품)가 없어 부착 실패·옵션 없는 단일상품이 판매중으로 남을 뻔.",
     "cause": "조합형 봉투의 축코드 recommendedOptNo1/2 가 실물에서 0(직접입력)임을 몰랐고, PUT 은 GET 봉투 전체 echo-back 규격.",
     "fix": "등록(무옵션)→직후 recommended-options PUT. 봉투=기존 옵션상품 GET 미러링, 없으면 실측 스키마로 합성(_synth_esm_envelope — 축코드 0·koreanText 직접입력). 부착 실패 시 set_sold_out 자동 회수(두 차례 실측 작동). 옥션 6478176871·G마켓 6478210710 실증.",
     "commit": "3f6d6724,57df024a,ef6c0929", "severity": "high", "status": "resolved",
     "lesson": "옵션 축코드 0=직접입력이면 옵션코드 조회 없이도 등록 가능. '등록됐지만 옵션 없음'은 실판매 사고 — 부착 실패는 반드시 상품 회수로 마무리."},
    {"id": "2026-07-21-eleven11-register-euckr-notification", "date": "2026-07-21",
     "markets": ["eleven11"], "area": "상품등록",
     "title": "11번가 등록 발굴 — euc-kr 선언·고시 891011 중복 우회·비문서 inboundarea·계정 10,000개 한도",
     "symptom": "한글 포함 XML 이 500(Invalid UTF-8 start byte)·상품고시 항목코드 표를 구할 수 없음·반품지 주소코드 API 가 지도에 없음·일부 계정은 등록 자체 거부.",
     "cause": "client 가 body 를 euc-kr 인코딩하는데 XML 선언이 UTF-8 — 선언·실바이트 불일치. 고시 코드표는 오픈API센터 로그인 뒤 첨부라 미확보. outboundarea 만 문서화. 판매중 상품 10,000개 계정 한도.",
     "fix": "선언을 euc-kr 로(search_products 도 같이 — 한글검색 종래 불가였음). 고시=type 891011 에 유효코드 23759468 을 9번 중복(검증순서 ①개수 ②코드존재 — 에러 오라클로 발굴). 반품지=inboundarea(대칭 경로 실측·addrSeq 3). 한도는 여유 계정(브랜드타임)으로 등록. 9508004984 실증.",
     "commit": "91483ada,3e92efac,6480af5b", "severity": "high", "status": "resolved",
     "lesson": "11번가 에러 메시지는 필드명을 정확히 짚는다 — 한 필드씩 채우는 반복이 통한다. 문서에 없는 API 도 대칭 경로를 실측 프로브로 확인하라."},
    {"id": "2026-07-21-lotteon-register-spdlst-silent", "date": "2026-07-21",
     "markets": ["lotteon"], "area": "상품등록",
     "title": "롯데온 등록 — spdLst 래퍼 없으면 0건 접수를 '정상'이라 응답(조용한 무시)·owhpNo·optNm 사전값",
     "symptom": "returnCode 9999 + '정상 처리되었습니다' + data[] 인데 상품이 안 생김. '출고지 번호 필수'는 어떤 필드명인지 불명. 옵션명 바꾸면 '판매옵션정보를 선택해주세요'.",
     "cause": "등록 body 는 {spdLst:[...]} 래퍼 필수 — 없으면 0건으로 접수돼 '정상' 응답. 출하지 실필드명=owhpNo(회수지 rtrpNo). itmOptLst.optNm 은 카테고리 사전값.",
     "fix": "spdLst 래퍼+data[0].spdNo 성공판정(register_product)·본보기 detail 복사(build_register_payload·필수 23필드)·owhpNo/rtrpNo=getDvpListSr 의 dvpNo·optNm 유지/optVal 만 교체. LO2729045338 실증. yaml 의 404 경로(/regist) 정정.",
     "commit": "9021ee9a,247d284e", "severity": "high", "status": "resolved",
     "lesson": "'정상 처리되었습니다'를 믿지 말고 data[] 안 항목별 resultCode·발급 ID 로만 성공 판정. 필드명은 에러 메시지가 아니라 detail 응답 실물에서 찾아라(dvpNo 아님·owhpNo)."},
    {"id": "2026-07-22-lotteon-options-passthrough-bug", "date": "2026-07-22",
     "markets": ["lotteon"], "area": "상품등록",
     "title": "옵션 파이프라인 전달 누락 — 본보기 단품이 그대로 등록됨(실물 재조회로 발견)",
     "symptom": "옵션 2건(블랙/250·화이트/260)을 등록했는데 detail 재조회에 본보기 단품('BK(블랙) / 100') 1건만 있었다.",
     "cause": "빌더(build_register_payload)에 options 파라미터를 추가하고 호출부(send_more._register_lotteon)를 안 고쳐 무옵션 경로가 탔다.",
     "fix": "options=spec['options'] 전달 + 등록 직후 detail 재조회로 단품 구성 검증을 절차화. 재등록 LO2729209534 에서 단품 2건·추가금 반영 확인.",
     "commit": "9243896f", "severity": "high", "status": "resolved",
     "lesson": "등록 성공(ID 발급)≠내용 정확. 옵션·가격 같은 내용은 반드시 마켓 재조회 실물로 대조하라 — 파이프라인 각 층(빌더·호출부)이 따로 갈 수 있다."},
]
existing_ids = {i.get('id') for i in d.get('incidents') or []}
for inc in NEW_INCIDENTS:
    if inc['id'] not in existing_ids:
        d['incidents'].append(inc)
        changed['inc'] += 1

json.dump(d, io.open(P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('st 승격:', changed['st'], '| idTraps 추가:', changed['traps'], '| incidents 추가:', changed['inc'])

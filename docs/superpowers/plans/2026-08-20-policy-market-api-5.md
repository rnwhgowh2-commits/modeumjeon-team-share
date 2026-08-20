# 정책생성 → 5대 마켓(스마트스토어·G마켓·옥션·11번가·롯데온) API 실등록 연동 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 정책생성에서 채운 13항목이 5개 마켓에 실제로 API 등록되도록, 안전장치를 놓치지 않고 마켓별로 검증한다.

**Architecture:** 새 폴더/모듈 없음. 기존 `lemouton/registration/service.py`(게이트+디스패치) → `compile_more.py`/`compile_smartstore.py`(스펙 조립) → `send_more.py`(마켓 API 호출)를 고친다. 안전장치는 각 마켓의 `shared/platforms/{market}/`에 이미 있는 판매중지 함수를 등록 직후 자동 호출하도록 배선한다.

**Tech Stack:** Python, pytest, Flask (`webapp/routes/live_send_test.py`가 실등록 수동 시험 경로), SQLAlchemy.

**작업 위치:** `C:/dev/_wt_marketreg` (branch `feature/policy-market-api-5`, `origin/main` 기준). 모든 경로는 이 워크트리 기준 `프로그램/_시스템/` 하위.

**⚠️ 이 계획의 특성:** Task 1~5는 순수 코드(TDD 가능). Task 6부터는 실제 마켓 API에 진짜로 상품을 등록해보고 결과를 관찰하는 "실등록 검증" 작업이라 사전에 정답을 알 수 없다 — 코드가 아니라 **정해진 절차**를 따른다. 실등록은 반드시 로컬 개발서버에서 `LIVE_REGISTER_ARMED=1`(운영 GH 변수는 그대로 0)로만 하고, 매 실등록 직후 즉시 판매중지까지 확인한다.

---

## Task 1: ESM(G마켓·옥션) 등록 직후 자동 판매중지 배선

**Files:**
- Modify: `프로그램/_시스템/lemouton/registration/send_more.py:78-` (`_register_esm`)
- Test: `프로그램/_시스템/tests/registration/test_send_more_esm.py` (신규)

**배경:** `service.py:_send_live`는 스마트스토어만 등록 직후 `mark_suspension()`을 부른다(:257-282). ESM은 `shared/platforms/esm/inventory.py:set_sold_out(goods_no, market, *, client)`가 이미 있는데 등록 경로(`_register_esm`)에서 안 부른다.

**⚠️ 계획 리뷰(독립 에이전트)에서 이 태스크의 최초 초안에 2가지 실오류가 발견돼 아래는 수정본이다:**
1. 옵션 부착 로직이 `register_goods` 호출과 `return` 사이에 있다(161-186행) — `set_sold_out`은 그 **뒤**(옵션 부착까지 끝난 뒤)에 호출해야 한다. 안 그러면 옵션 붙이기 전에 상품이 판매중지되고, 옵션 실패시 이미 있는 롤백 로직(171-185행)과 순서가 꼬인다.
2. `build_esm_register_payload` 호출부(140-157행)가 mock 밖의 진짜 코드라 `spec`에 `goods_name/cat_code/site_cat_code/price/stock/image_url/detail_html/is_vat_free/model_no/bar_code/is_adult_product`가 다 있어야 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# 프로그램/_시스템/tests/registration/test_send_more_esm.py
from unittest.mock import MagicMock, patch

from lemouton.registration.send_more import _register_esm

_SPEC = {
    'goods_name': '테스트상품', 'cat_code': '100', 'site_cat_code': '200',
    'price': 10000, 'stock': 1, 'image_url': 'http://img.example/1.jpg',
    'detail_html': '<p>상세</p>', 'is_vat_free': False, 'model_no': 'MD1',
    'bar_code': '8800000000001', 'is_adult_product': False,
    # options 키를 안 넣어 spec.get('options') 가 falsy → 옵션 부착 분기는 안 탄다
    # (옵션 분기 자체는 이 테스트의 관심사가 아니라 별도 테스트로 다룬다).
}
_PREREQ = {'place_no': '1', 'dispatch_policy_no': '2', 'return_addr_no': '3',
          'delivery_company_no': '4', 'official_notice_no': '5',
          'official_notice_details': {}}


def test_register_esm_calls_set_sold_out_after_success(monkeypatch):
    """등록(+옵션부착 있으면 그것까지) 끝난 뒤에 판매중지(set_sold_out) 를 호출해야 한다."""
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._esm_client', lambda market, prefix: fake_client)

    with patch('lemouton.registration.send_more.search_goods',
               return_value={'items': [{'goodsNo': '111'}]}), \
         patch('lemouton.registration.send_more.get_goods_detail',
               return_value={'itemAddtionalInfo': {}}), \
         patch('lemouton.registration.send_more.extract_register_prereq',
               return_value=_PREREQ), \
         patch('lemouton.registration.send_more.build_esm_register_payload',
               return_value={}), \
         patch('lemouton.registration.send_more.register_goods',
               return_value={'goodsNo': '999888'}), \
         patch('shared.platforms.esm.inventory.set_sold_out') as mock_suspend:
        mock_suspend.return_value = True
        result = _register_esm('auction', dict(_SPEC), '')

    assert result['product_id'] == '999888'
    mock_suspend.assert_called_once_with('999888', 'auction', client=fake_client)
```

(patch 대상을 `shared.platforms.esm.products.*`가 아니라 `lemouton.registration.send_more.*`로 쓴 이유: `send_more.py` 상단에서 이미 `from shared.platforms.esm.products import (...)`로 이름을 가져와 쓰고 있다면 그 로컬 이름을 patch해야 한다 — 정확한 import 형태를 Step 1 작성 직전에 `send_more.py` 상단 import문으로 재확인할 것)

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_send_more_esm.py -v`
Expected: FAIL — `set_sold_out` not called (mock_suspend.assert_called_once_with 에러). import나 KeyError로 죽으면 위 patch 경로나 `_SPEC` 누락 필드부터 다시 확인.

- [ ] **Step 3: 최소 구현**

`send_more.py:186`(현재 `return {'product_id': goods_no_new, 'raw': result}` 한 줄)을 다음으로 교체 — **옵션 부착 if-블록(161-185행) 뒤, 그 return 자리**:

```python
    # ★ 등록(+옵션부착) 끝난 뒤 판매중지 — 스마트스토어(service.py:_send_live)와 같은
    #   안전장치. ESM 은 등록 즉시 판매중(11)으로 뜬다. 실패해도 상품ID 는 잃지 않는다
    #   (best-effort — 옵션부착 실패 시의 기존 롤백(171-185행)과 별개 경로).
    from shared.platforms.esm.inventory import set_sold_out
    try:
        suspended = set_sold_out(goods_no_new, market, client=client)
        if not suspended:
            logger.warning('%s 판매중지 전환 실패 goodsNo=%s — 상품이 판매중 상태로 남았습니다.',
                           market, goods_no_new)
    except Exception:  # noqa: BLE001
        logger.exception('%s 판매중지 전환 예외 goodsNo=%s', market, goods_no_new)
    return {'product_id': goods_no_new, 'raw': result}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_send_more_esm.py -v`
Expected: PASS

- [ ] **Step 5: 기존 등록 테스트 회귀 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/ -k "esm or more" -v`
Expected: 전부 PASS (기존 것 깨지지 않음)

- [ ] **Step 6: 커밋**

```bash
git add 프로그램/_시스템/lemouton/registration/send_more.py 프로그램/_시스템/tests/registration/test_send_more_esm.py
git commit -m "fix(등록): ESM 등록 직후 자동 판매중지 — 스마트스토어와 같은 안전장치"
```

---

## Task 2: 11번가 등록 직후 자동 전시중지(판매중단) 배선

**Files:**
- Modify: `프로그램/_시스템/lemouton/registration/send_more.py:341-376` (`_register_eleven11`)
- Test: `프로그램/_시스템/tests/registration/test_send_more_eleven11.py` (신규)

**배경:** `shared/platforms/eleven11/products.py:stop_display(prdNo, client)`가 이미 있고 `webapp/routes/live_send_test.py:1283`(`/api/live-send-test/suspend-eleven11`)에서 수동으로만 쓰인다. 등록 경로(`_register_eleven11`)에서 자동으로 안 부른다.

**⚠️ Task 1(ESM) 코드품질 리뷰에서 나온 교훈 반영: 전시중지가 실패해도 로그만 남기면 DB 기록엔 흔적이 없다(이 프로젝트의 반복된 사고 유형 — 조용한 실패). `result['_suspend_failed'] = True`를 실패/예외 양쪽 분기에 반드시 같이 넣는다(아래 Step 3에 이미 반영됨 — Task 1처럼 나중에 따로 고치지 말고 처음부터 넣을 것).**

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# 프로그램/_시스템/tests/registration/test_send_more_eleven11.py
from unittest.mock import MagicMock, patch

from lemouton.registration.send_more import _register_eleven11


def test_register_eleven11_calls_stop_display_after_success(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._eleven11_client', lambda prefix: fake_client)
    fake_client.request.side_effect = [
        '<areaservice><addrSeq>10</addrSeq></areaservice>',  # outboundarea
        '<areaservice><addrSeq>20</addrSeq></areaservice>',  # inboundarea
    ]
    with patch('shared.platforms.eleven11.products.build_register_xml',
               return_value='<xml/>'), \
         patch('shared.platforms.eleven11.products.register_product',
               return_value={'productNo': '55501'}), \
         patch('shared.platforms.eleven11.products.stop_display') as mock_stop:
        mock_stop.return_value = {'resultCode': '200'}
        result = _register_eleven11({'name': '테스트상품'}, '')

    assert result['product_id'] == '55501'
    mock_stop.assert_called_once_with('55501', client=fake_client)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_send_more_eleven11.py -v`
Expected: FAIL — `stop_display` 미호출

- [ ] **Step 3: 최소 구현**

`send_more.py:374-376`을 다음으로 교체:

```python
    result = register_product(xml_body, client=client)   # productNo 없으면 raise
    product_no = str(result['productNo'])
    # ★ 등록 직후 전시중지 — 11번가는 등록 즉시 전시(판매)로 뜬다(ESM·스스와 같은 이유).
    #   실패해도 product_id 는 잃지 않는다(best-effort). 실패 흔적은 result 안에 남겨
    #   row.raw_json 으로 DB에 보이게 한다(로그만 남기면 조용한 실패가 된다 — Task1 교훈).
    from shared.platforms.eleven11.products import stop_display
    try:
        stop_resp = stop_display(product_no, client=client)
        if not stop_resp:
            logger.warning('eleven11 전시중지 응답 없음 prdNo=%s', product_no)
            result['_suspend_failed'] = True
    except Exception:  # noqa: BLE001
        logger.exception('eleven11 전시중지 예외 prdNo=%s', product_no)
        result['_suspend_failed'] = True
    return {'product_id': product_no, 'raw': result}
```

테스트에 다음 2개도 추가(Task 1의 최종 형태와 같은 패턴 — `stop_display`가 falsy를 돌려줄 때, 예외를 던질 때 각각 `result['raw']['_suspend_failed'] is True`인지 확인):

```python
def test_register_eleven11_marks_suspend_failed_when_stop_display_falsy(monkeypatch):
    ...  # mock_stop.return_value = None 로, result['raw'].get('_suspend_failed') is True 확인

def test_register_eleven11_marks_suspend_failed_when_stop_display_raises(monkeypatch):
    ...  # mock_stop.side_effect = RuntimeError('...') 로, result['raw'].get('_suspend_failed') is True 확인
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_send_more_eleven11.py -v`
Expected: PASS (성공케이스 + suspend_failed 2케이스 전부)

- [ ] **Step 5: 회귀 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/ -k "eleven11 or more" -v`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add 프로그램/_시스템/lemouton/registration/send_more.py 프로그램/_시스템/tests/registration/test_send_more_eleven11.py
git commit -m "fix(등록): 11번가 등록 직후 자동 전시중지 — 스마트스토어와 같은 안전장치"
```

---

## Task 3: 롯데온 등록 직후 자동 판매중단 배선

**Files:**
- Modify: `프로그램/_시스템/lemouton/registration/send_more.py:427-454` (`_register_lotteon`)
- Test: `프로그램/_시스템/tests/registration/test_send_more_lotteon.py` (신규)

**배경:** `shared/platforms/lotteon/products.py:set_sale_status(spd_no, sl_stat_cd, *, client)`가 이미 있다(`sl_stat_cd`: END=판매종료/SOUT=품절). 등록 경로(`_register_lotteon`)에서 안 부른다.

**⚠️ END를 고른 이유(계획 리뷰에서 지적 — 코드 주석엔 END/SOUT 중 선택 근거가 없어 여기서 명시): SOUT(품절)은 재고 수치에 연동된 상태라, 이후 재고 동기화 작업이 재고를 채우면 자동으로 판매중으로 되돌아갈 위험이 있다. END(판매종료)는 재고와 무관하게 고정되는 상태라 "테스트 상품이 실수로 다시 노출되는" 사고를 막기에 더 안전하다 — 이 판단이 틀렸다고 보이면(예: 롯데온이 END 상품의 재등록/삭제를 더 까다롭게 요구한다면) Task 3 실행 직전에 SOUT로 바꿀 것.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# 프로그램/_시스템/tests/registration/test_send_more_lotteon.py
from unittest.mock import MagicMock, patch

from lemouton.registration.send_more import _register_lotteon


def test_register_lotteon_calls_set_sale_status_after_success(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._lotteon_client', lambda prefix: fake_client)
    template = {'dmstOvsDvDvsCd': 'DMST', 'spdSlStatCd': 'SALE',
               'itmLst': [{'itmImgLst': [{'origImgFileNm': 'old.jpg'}]}]}
    with patch('shared.platforms.lotteon.products.get_product_detail',
               return_value=template), \
         patch('shared.platforms.lotteon.products.build_register_payload',
               return_value={'itmLst': [{'itmImgLst': [{'origImgFileNm': 'old.jpg'}]}]}), \
         patch('shared.platforms.lotteon.products.register_product',
               return_value={'spdNo': '77701'}), \
         patch('shared.platforms.lotteon.products.set_sale_status') as mock_status:
        mock_status.return_value = True
        result = _register_lotteon(
            {'template_spd_no': '1', 'spd_nm': '테스트', 'price': 10000, 'stock': 1,
             'image_url': 'new.jpg'}, '')

    assert result['product_id'] == '77701'
    mock_status.assert_called_once_with('77701', 'END', client=fake_client)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_send_more_lotteon.py -v`
Expected: FAIL — `set_sale_status` 미호출

- [ ] **Step 3: 최소 구현**

`send_more.py:453-454`를 다음으로 교체:

```python
    result = register_product(inner, client=client)   # spdNo 없으면 raise
    spd_no = str(result['spdNo'])
    # ★ 등록 직후 판매종료 — 롯데온은 등록 즉시 판매중(SALE)으로 뜬다. 실패해도
    #   product_id 는 잃지 않는다(best-effort). 실패 흔적은 result 안에 남겨
    #   row.raw_json 으로 DB에 보이게 한다(로그만 남기면 조용한 실패가 된다 — Task1 교훈).
    from shared.platforms.lotteon.products import set_sale_status
    try:
        ok = set_sale_status(spd_no, 'END', client=client)
        if not ok:
            logger.warning('lotteon 판매종료 전환 실패 spdNo=%s', spd_no)
            result['_suspend_failed'] = True
    except Exception:  # noqa: BLE001
        logger.exception('lotteon 판매종료 전환 예외 spdNo=%s', spd_no)
        result['_suspend_failed'] = True
    return {'product_id': spd_no, 'raw': result}
```

테스트에 다음 2개도 추가(Task 1과 같은 패턴 — `set_sale_status`가 falsy를 돌려줄 때, 예외를 던질 때 각각 `result['raw']['_suspend_failed'] is True`인지 확인):

```python
def test_register_lotteon_marks_suspend_failed_when_set_sale_status_falsy(monkeypatch):
    ...  # mock_status.return_value = False 로, result['raw'].get('_suspend_failed') is True 확인

def test_register_lotteon_marks_suspend_failed_when_set_sale_status_raises(monkeypatch):
    ...  # mock_status.side_effect = RuntimeError('...') 로, result['raw'].get('_suspend_failed') is True 확인
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_send_more_lotteon.py -v`
Expected: PASS (성공케이스 + suspend_failed 2케이스 전부)

- [ ] **Step 5: 회귀 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/ -k "lotteon or more" -v`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add 프로그램/_시스템/lemouton/registration/send_more.py 프로그램/_시스템/tests/registration/test_send_more_lotteon.py
git commit -m "fix(등록): 롯데온 등록 직후 자동 판매종료 — 스마트스토어와 같은 안전장치"
```

**✅ 실행 완료(e377f025) — 계획 대비 확장된 부분 기록:** 구현자가 `set_sale_status`의 docstring("반환 True 여도 재조회 검증 권장")과 같은 파일의 `register_product`용 "함정2"(최상위 returnCode 성공이어도 data[] 항목별 resultCode는 실패일 수 있음)를 근거로 **재조회 검증(get_product_detail → spdSlStatCd=='END' 확인)을 자체 판단으로 추가**함(Task 2/11번가와 동일 패턴). 코드품질 리뷰가 이 판단을 실코드 근거로 재확인·승인함. 참고로 Task 1(ESM)의 `set_sold_out`은 같은 리뷰에서 확인한 결과 docstring에 재조회 권장 문구가 없어 재조회 불필요로 판정됨(누락 아님).

---

## Task 4: 옥션 사이트부담할인 필드 누락 버그 수정

**Files:**
- Modify: `프로그램/_시스템/lemouton/policy/fields.py:60`
- Test: `프로그램/_시스템/tests/policy/test_fields_extra_items.py` (신규)

**배경:** `required.py:304-308` 지도 주석은 "옥션·G마켓 둘 다 필수(Y)"라는데 `fields.py:60`의 `only: ['gmarket', 'lotteon']`엔 `'auction'`이 빠져 있다 — 옥션 정책 화면에 이 필드가 안 뜨고, `_register_esm`도 이 값을 못 채운 채 등록하게 된다.

**⚠️ 계획 리뷰에서 정정: `fields.py`에 `items_for_market`이라는 함수는 없다 — 실제 이름은 `item_keys_for(market)`(키 목록만 바로 줌).**

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# 프로그램/_시스템/tests/policy/test_fields_extra_items.py
from lemouton.policy.fields import item_keys_for


def test_auction_has_site_discount_item():
    """required.py 지도: 옥션도 사이트부담 지원할인이 필수다 — G마켓만 있으면 안 된다."""
    assert '_site_discount' in item_keys_for('auction'), (
        '옥션 정책 화면에 사이트부담 지원할인 항목이 없다 — '
        'ESM 전문(addtionalInfo.siteDiscount.iac)이 필수인데 입력할 곳이 없다')
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/policy/test_fields_extra_items.py -v`
Expected: FAIL — `_site_discount` not in keys

- [ ] **Step 3: 최소 구현**

`fields.py:60`:

```python
        'note': 'G마켓·옥션·롯데온만 있는 항목.', 'only': ['gmarket', 'auction', 'lotteon'],
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/policy/test_fields_extra_items.py -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/policy/ -v`
Expected: 전부 PASS (특히 `all_item_keys`/`label_of`를 쓰는 기존 테스트)

- [ ] **Step 6: 커밋**

```bash
git add 프로그램/_시스템/lemouton/policy/fields.py 프로그램/_시스템/tests/policy/test_fields_extra_items.py
git commit -m "fix(정책): 옥션에 사이트부담 지원할인 항목 누락 — G마켓만 있던 버그"
```

---

## Task 5: 착수 전 안전 회귀 스위트 확인

**Files:** 없음 (실행만)

- [ ] **Step 1: 전체 등록/정책 테스트 스위트 실행**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/ tests/policy/ -v`
Expected: PASS (Task 1~4 반영 후 전부 통과 — 여기서 실패가 있으면 Task 6 이후 실등록으로 넘어가지 않는다)

- [ ] **Step 2: LIVE_REGISTER_ARMED 게이트 테스트 확인**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_register_guards.py tests/registration/test_register_many_route.py -v`
Expected: PASS — 게이트가 여전히 기본 차단 상태인지 재확인(Task 1~3에서 실수로 게이트 우회 코드를 안 넣었는지 확인하는 안전판)

---

## Task 6: G마켓·옥션 — 로컬 실등록 검증 (1순위 마켓)

**사전 조건:** Task 1~5 전부 완료·통과.

- [ ] **Step 1: 로컬 개발서버를 실등록 모드로 기동**

```bash
cd 프로그램/_시스템
LIVE_REGISTER_ARMED=1 python app.py
```
(운영 GitHub 저장소 변수는 그대로 0 — 이 환경변수는 이 로컬 프로세스에만 적용됨)

- [ ] **Step 2: 카테고리 1개(예: 의류 중 흔한 카테고리)로 옥션 실등록 1건**

`webapp/routes/live_send_test.py`의 옥션/G마켓 등록 엔드포인트에 `arm=1`과 함께 정책이 적용된 실제 초안 1건의 스펙을 보낸다(화면의 「실전송 시험」 UI 사용, 또는 해당 라우트에 직접 POST). 기록할 것:
  - 응답에 `goodsNo`(상품ID)가 왔는가
  - Task 1에서 추가한 자동 판매중지가 실제로 걸렸는가(`get_sell_status`로 재조회, `isSell.iac`/`isSell.gmkt`가 false인지)
  - **⚠️ 옥션 사이트부담할인 필드(Task 4)는 정책 화면엔 뜨지만 실제 전문(`addtionalInfo.siteDiscount.iac`)엔 아직 안 실린다 — `shared/platforms/esm/products.py:build_esm_register_payload`가 이 값을 `{"gmkt": False, "iac": False}`로 하드코딩 중이고, EXTRA_ITEMS 전체(마켓별 추가항목)가 compile 단계에서 아예 안 읽힘을 계획 검토 중 발견함. 13항목과는 별개 배선 공백이라 이번 사이클 범위 밖으로 분리(task_9d4bf0ad로 별도 세션 위임). 이 Step에서는 "아직 실리지 않음"을 확인만 하고 넘어갈 것 — 새로 발견한 버그로 착각해 여기서 고치려 하지 말 것.**

- [ ] **Step 3: `TO_VERIFY_BY_LIVE` 항목 확인 — auction KC**

`lemouton/policy/required.py:339-340`의 `eleven11 kc` 항목이 아니라 `auction`용 확인은 required.py에 명시된 게 없으므로, ESM 전문에서 KC 칸이 있는지(있다면 required.py에 추가), 없다면 고시정보로 갈음되는지 위 실등록 결과의 응답 raw로 확인. 결과를 `required.py`에 반영(칸이 없다고 확정되면 새 `TABLE['auction']`/`TABLE['gmarket']` 항목에 "마켓 등록 API 에 없는 칸입니다" 주석 추가).

- [ ] **Step 4: `TO_VERIFY_BY_LIVE` 항목 확인 — auction 태그**

`required.py:345` "ESM 전문에서 태그 칸을 못 찾았다"를 위 실등록 응답으로 확인. 태그 칸이 실제로 없다고 확정되면:

```python
# required.py 의 _ESM 딕셔너리에 추가
'tags': _o('마켓 등록 API 에 없는 칸입니다 — ESM 전문 확인(2026-08-20 실등록).'),
```
`TO_VERIFY_BY_LIVE`에서 `('auction', 'tags', ...)` 항목 삭제.

- [ ] **Step 5: 확인된 항목 정리**

`required.py:336-346`의 `TO_VERIFY_BY_LIVE` 리스트에서 이번에 확인된 `('auction', 'kc', ...)`, `('auction', 'tags', ...)` 항목을 삭제(확인 안 된 항목만 남긴다).
`docs/markets/gmarket.yaml`/`docs/markets/auction.yaml`(있다면)에 이번 실등록 근거(상품ID, 날짜) 1줄 추가.

- [ ] **Step 6: 커밋**

```bash
git add 프로그램/_시스템/lemouton/policy/required.py docs/markets/
git commit -m "verify(등록): G마켓·옥션 실등록 검증 완료 — KC·태그 칸 확인, TO_VERIFY_BY_LIVE 정리"
```

- [ ] **Step 7: 등록한 테스트 상품 최종 확인**

셀러센터(또는 재조회 API)로 Step 2에서 만든 상품이 판매중지 상태로 남아있는지 최종 확인 — 판매중이면 즉시 수동으로 내린다.

---

## Task 7: 스마트스토어 — 고시유형 자동판정 회귀 테스트 + 로컬 실등록 검증

**배경:** `notice_type_guess.py`(고시유형 SHOES/BAG 자동판정)는 2026-08-20 오늘 이미 merge·배선완료(`send/as_draft.py:147-148`) — 새로 고칠 버그 없음. 이 태스크는 확인 테스트 추가 + 실등록 검증만.

**Files:**
- Test: `프로그램/_시스템/tests/registration/test_smartstore_notice_wiring.py` (신규)

- [ ] **Step 1: 배선 확인 테스트 작성 (이미 GREEN이어야 정상)**

```python
# 프로그램/_시스템/tests/registration/test_smartstore_notice_wiring.py
from lemouton.registration.notice_type_guess import guess_notice_type


def test_shoes_category_guessed_correctly():
    """신발 카테고리 상품이 고시유형 SHOES 로 자동판정되는지 — as_draft.upsert 배선 확인."""
    assert guess_notice_type('신발>스니커즈>여성운동화') == 'SHOES'


def test_wear_category_stays_default():
    """의류는 명시 판정이 없어 기존 기본값 WEAR 로 유지되는지."""
    assert guess_notice_type('여성의류>원피스') is None  # 호출자가 None → 'WEAR' 유지
```

- [ ] **Step 2: 실행 — GREEN 확인 (RED 아님, 이미 구현된 것의 회귀방지 확인)**

Run: `cd 프로그램/_시스템 && python -m pytest tests/registration/test_smartstore_notice_wiring.py -v`
Expected: PASS (이미 구현·배선된 기능이므로 즉시 통과해야 함 — FAIL 이면 이 사이클 최우선 조사 대상)

- [ ] **Step 3: 로컬 실등록 — 신발 카테고리 1건**

Task 6과 같은 방식으로 `LIVE_REGISTER_ARMED=1` 로컬서버에서 스마트스토어에 신발 카테고리 상품 1건 실등록. 확인할 것:
  - `productInfoProvidedNoticeType`이 실제로 `"SHOES"`로 나갔는지(`notice.py:build_notice` 결과가 그대로 전송됐는지)
  - 등록 직후 자동 SUSPENSION 전환 확인(기존 기능, 회귀만 확인)

- [ ] **Step 4: `TO_VERIFY_BY_LIVE` 항목 확인 — 배송정보 미전송**

`required.py:341-342` "배송 정보를 통째로 안 보내면 「배송 없는 상품」이 되는지"를 실등록으로 확인 — 배송 필드를 일부러 빼고 등록 시도, 결과(성공/실패/기본배송 적용) 기록.
확인되면 `TO_VERIFY_BY_LIVE`에서 `('smartstore', 'shipping', ...)` 삭제하고 `required.py`의 `TABLE['smartstore']`(또는 해당 위치)에 확정 사실 반영.

- [ ] **Step 5: 커밋**

```bash
git add 프로그램/_시스템/tests/registration/test_smartstore_notice_wiring.py 프로그램/_시스템/lemouton/policy/required.py docs/markets/
git commit -m "test(등록): 스마트스토어 고시유형 배선 회귀테스트 + 배송정보 실등록 검증"
```

- [ ] **Step 6: 테스트 상품 판매중지 최종 확인**

---

## Task 8: 11번가 — 로컬 실등록 검증

**Files:** 없음 (검증 + 문서 갱신)

- [ ] **Step 1: 카테고리 1~2개로 실등록**

Task 2에서 추가한 자동 전시중지가 걸리는지 포함해 실등록. `send_more.py:366-370`의 고시코드 임시값(type=891011, code=23759468×9)이 이번 카테고리에서도 통과하는지 확인.

- [ ] **Step 2: `TO_VERIFY_BY_LIVE` 항목 확인 — KC 칸 카테고리 의존성**

`required.py:339-340` "문서는 [필수]인데 우리 XML은 이 칸 없이 등록에 성공했다(2026-07-21) — 카테고리에 따라 갈리는지 확인"을 이번 카테고리(신발 등 KC 대상 가능성 있는 카테고리 포함)로 재확인.
  - 갈리지 않는다(전 카테고리 불필요) → `TO_VERIFY_BY_LIVE`에서 삭제, `TABLE['eleven11']`에 확정 반영
  - 갈린다(특정 카테고리만 필요) → `required.py`에 카테고리 조건부로 명시(삭제하지 않음, 조건 추가)

- [ ] **Step 3: 커밋**

```bash
git add 프로그램/_시스템/lemouton/policy/required.py docs/markets/eleven11.yaml
git commit -m "verify(등록): 11번가 실등록 검증 — KC 칸 카테고리 의존성 확인"
```

- [ ] **Step 4: 테스트 상품 전시중지 최종 확인**

---

## Task 9: 롯데온 — 13항목 필드매핑 실등록 검증

**배경:** 등록 메커니즘 자체는 2026-07-21 이미 라이브 검증됨(LO2729045338). 이번엔 정책 13항목 각각이 실제로 어느 필드에 어떻게 매핑되는지 확인 — `required.py:337-338`이 "롯데온 13항목 거의 전부"를 확인 대상으로 명시.

**방법(2026-08-02 확정):** 한 번에 한 항목씩, 그 항목만 비운 채 등록 → 결과 관찰 → 즉시 판매종료(Task 3에서 자동화됨).

- [ ] **Step 1: 기준 등록 — 13항목 전부 채운 채로 1건**

정책 13항목을 전부 채운 초안으로 실등록. 상품ID(spdNo) 수령 확인 + Task 3 자동 판매종료 확인. 이 결과를 "기준 응답"으로 저장(이후 항목별 비교 대상).

- [ ] **Step 2~14: 항목별 확인 (13항목 각각)**

13항목: 상품명·카테고리·판매가·옵션·이미지·상세페이지·배송·고시정보·브랜드·원산지·KC인증·태그·모델번호/바코드·과세구분·미성년자구매·제조사 — 이미 확실한 것(카테고리는 required.py에 "확인됨"으로 표시돼 있음, Step 1의 기준등록으로 상품명·판매가·옵션·이미지도 사실상 확인됨)은 건너뛰고, **불확실한 잔여 항목만** 개별 확인:
  - 각 항목을 기준 등록에서 하나만 비우고 재등록 → 실패하면 필수, 성공하면 그 필드의 실제 API 요구사항(형식·코드값)을 응답/재조회로 확정
  - 매 시도 직후 Task 3 자동 판매종료가 걸렸는지 확인(안 걸렸으면 수동으로 즉시 내림)

- [ ] **Step 15: `docs/markets/lotteon.yaml` 13항목 매핑표 채우기**

`_schema.yaml`의 `fields.register` 형식(name·type·required·default·source)에 맞춰 13항목 각각의 실제 API 필드명·필수여부·기본값·출처(이번 실측)를 기록.

- [ ] **Step 16: `required.py` 정리**

`TO_VERIFY_BY_LIVE`에서 `('lotteon', '*', ...)` 항목을 삭제하고, 확정된 매핑을 `TABLE['lotteon']`(신규 생성 필요시)에 반영.

- [ ] **Step 17: 커밋**

```bash
git add docs/markets/lotteon.yaml 프로그램/_시스템/lemouton/policy/required.py
git commit -m "verify(등록): 롯데온 13항목 실등록 필드매핑 검증 완료"
```

---

## Task 10: 사이클 마무리 — 회귀 전체 확인 + 운영 게이트 전환 확인 요청

**Files:** 없음

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `cd 프로그램/_시스템 && python -m pytest tests/ -v`
Expected: 기존에 알려진 무관 실패([reference_pytest_preexisting_failures](../../reference_pytest_preexisting_failures.md) 참고) 외 전부 PASS

- [ ] **Step 2: `docs/markets/*.yaml` 5개 마켓 전부 최신화 확인**

각 파일의 `meta.last_analyzed`를 오늘 날짜로, `register` 섹션이 이번 검증 결과를 반영했는지 확인.

- [ ] **Step 3: 사용자에게 운영 게이트 전환 명시적 확인 요청**

5마켓 전부 로컬 실등록 성공 확인 후에만, 사장님께 "운영 `LIVE_REGISTER_ARMED`를 0→1로 켜도 될까요?"를 명시적으로 여쭙는다(배포 파이프라인 변수 변경 — 자동 전환 금지, `docs/.workflow-state.md`의 `user_decisions.switch_timing` 참고).

- [ ] **Step 4: 승인 시 전환**

```bash
gh variable set LIVE_REGISTER_ARMED --body "1"
```
전환 후 다음 배포부터 반영(`scripts/deploy_direct.py:58,234-235` 배선 참고) — 배포 트리거 필요.

---

## Self-Review 체크(계획 작성자용, 실행 전 확인)

- [x] LIGHT_SPEC.md 5개 마켓 전부 태스크 있음 (Task 6~9)
- [x] 안전장치(자동 판매중지/전시중지/판매종료) 4마켓 전부 태스크 있음 (Task 1~3, 스마트스토어는 기존)
- [x] TO_VERIFY_BY_LIVE 6항목(lotteon *, eleven11 kc, smartstore shipping, auction kc, auction tags — coupang origin은 범위 밖) 전부 태스크에 반영
- [x] 알려진 버그(옥션 사이트할인 누락) 태스크 있음, 스마트스토어 고시유형은 이미 해결됨을 반영해 정정
- [x] 운영 게이트 전환은 사용자 명시 승인 게이트로 별도 분리(자동 금지)

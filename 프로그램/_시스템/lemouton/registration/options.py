# -*- coding: utf-8 -*-
"""옵션(색상×사이즈) → 마켓별 옵션 구조.

스스 공식 규격 (marketplace_api_map.json → smartstore.create-product-product):
    optionCombinationGroupNames: {optionGroupName1..4}
    optionCombinations: [{optionName1..4, stockQuantity, price, usable, sellerManagerCode}]
    · price 는 '옵션가'(추가금)지 절대 판매가가 아니다.
    · 조합형 옵션 그룹은 최대 3개.
    · optionInfo: 표준형·단독형·조합형·직접입력형 중 최소 한 개는 입력해야 한다.
      서로 배타적일 뿐 조합형이 금지된 게 아니다 — 우리는 조합형을 쓴다.

쿠팡은 옵션가 개념이 없어 items[] 마다 절대가(salePrice)를 싣는다.

[재고 규칙 — 프로젝트 원칙]
    stock > 0  → 등록
    stock == 0 → 품절 → 등록 제외 (설계서 §7-9)
    stock < 0  → '확인불가' → 등록 제외. 999 같은 폴백을 넣지 않는다 (오버셀 방지).
    stock 없음 → '재고미입력' → 등록 제외. **0(품절)과 다른 상태다.**
      (집 관례: lemouton/sources/lap_report.py:43 — 0=품절 / -1=확인불가 / None=미크롤)
      `or 0` 로 뭉개면 배선 버그(예: 폼이 stock 대신 qty 를 보냄)가 '전부 품절' 이라는
      거짓 업무 메시지로 둔갑한다.

[제외는 보고한다 — 조용한 실패 금지]
    사용자가 폼에 직접 입력한 행이다. 9개 중 8개가 빠졌는데 '성공' 이라고 답하면 안 된다.
    두 빌더 모두 excluded 목록을 함께 돌려주고, 상위(컴파일러)가 사용자에게 보여준다.

[입력 경계]
    opts 는 ProductDraft.options_json — 결국 UI 폼에서 온 자유형 JSON 이다.
    타입을 믿지 않는다. 숫자 사이즈(250), 문자 재고('3.0') 가 정상 입력이다.
    AttributeError·bare ValueError 는 상위 except 를 그냥 통과해 500 이 되므로
    전부 OptionError 하위로 바꿔서 던진다.
"""
# [2026-07-17] 대량등록 Phase 1A Task 4 + Task 4b (단일축)

import math

_SIZE_GROUP = '사이즈'
_COLOR_GROUP = '색상'
#: 3축의 첫 갈래 — 구매자 드롭다운에 이 이름 그대로 보인다.
_MODEL_GROUP = '모델명'

# 알파 사이즈 순서.
# ★ 이 배열 순서가 곧 구매자가 보는 드롭다운 순서다 — optionCombinationSortType 을
#   보내지 않으면 스스 기본값이 등록순(CREATE) 이기 때문. 문자 정렬에 맡기면
#   ['XL','S','M','L','XS'] 가 L,M,S,XL,XS 로 나온다 (의류에서 매번 발생).
_ALPHA_SIZE_ORDER = ('XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL')
_ALPHA_SIZE_RANK = {name: i for i, name in enumerate(_ALPHA_SIZE_ORDER)}

# 제외 사유 (사용자에게 그대로 보여줄 말)
REASON_SOLD_OUT = '품절'
REASON_UNKNOWN = '확인불가'
REASON_NO_STOCK = '재고미입력'


class OptionError(ValueError):
    """옵션 처리 실패 — 상위(컴파일러)가 이 하나만 잡으면 된다."""


class NoSellableOption(OptionError):
    """판매 가능한 옵션이 하나도 없음. 빈 옵션 목록을 조용히 보내지 않는다."""


class OptionValueInvalid(OptionError):
    """옵션 입력값이 잘못됨. 추측해서 고치지 않고 실패시킨다 (폴백 금지)."""


def _text(raw) -> str:
    """자유형 JSON 입력값 → 문자열. int 250 · None 이 와도 터지지 않게.

    AttributeError 는 ValueError 가 아니라서 상위 핸들러를 그냥 통과해 500 이 된다.
    None 이 문자열 'None' 으로 둔갑하지 않게 먼저 걸러낸다.
    """
    if raw is None:
        return ''
    return str(raw).strip()


def _num(raw, field: str):
    """자유형 JSON 숫자 → int. 미입력(None·빈칸)은 None.

    폼·엑셀 붙여넣기·JS toFixed 는 3, '3', '3.0', 3.0 을 다 보낸다. 전부 3 이다.
    읽을 수 없는 값을 조용히 0 으로 만들지 않는다 (재고 0 = 품절 = 오판).
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # 파이썬에서 True == 1 이라 그냥 두면 재고 1개로 등록된다.
        raise OptionValueInvalid(f'{field} 값에 참/거짓이 왔습니다: {raw!r}')
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        f = raw
    else:
        s = _text(raw)
        if not s:
            return None
        try:
            f = float(s.replace(',', ''))
        except ValueError:
            raise OptionValueInvalid(
                f'{field} 값을 숫자로 읽을 수 없습니다: {raw!r}') from None
    if not math.isfinite(f):
        # nan·inf. int(nan)=ValueError, int(inf)=OverflowError 라 둘 다 새어나간다.
        raise OptionValueInvalid(f'{field} 값이 숫자가 아닙니다: {raw!r}')
    if f != int(f):
        raise OptionValueInvalid(f'{field} 값은 정수여야 합니다: {raw!r}')
    return int(f)


def _size_key(size):
    """사이즈 정렬 키 — 숫자 > 알파(XS→XXXL) > 나머지(문자순).

    구매자 드롭다운 순서가 되므로 정렬이 곧 UX 다.

    Raises:
        OptionValueInvalid: nan·inf 사이즈
    """
    s = _text(size)
    try:
        num = float(s.replace(',', ''))
    except ValueError:
        pass
    else:
        if not math.isfinite(num):
            # 'nan' 은 비교가 전부 False 라 정렬을 조용히 뒤섞는다.
            raise OptionValueInvalid(f'사이즈 값이 숫자가 아닙니다: {size!r}')
        return (0, num, '')
    rank = _ALPHA_SIZE_RANK.get(s.upper())
    if rank is not None:
        return (1, float(rank), '')
    return (2, 0.0, s)


def _normalize(opts, *, split_model=False):
    """자유형 입력 → 검증된 행 목록. 값이 이상하면 여기서 전부 실패시킨다.

    split_model: 이 전송이 **모델명을 옵션 이름에 싣는가**.

      🔴 불변식은 하나다 — **마켓에 나가는 옵션 이름이 서로 달라야 한다.**
         그래서 중복 검사 키는 「모델 칸이 있느냐」가 아니라
         **「이번 전송이 모델을 이름에 싣느냐」** 로 정한다.
         · 싣는다(3갈래·1갈래 합침) → (모델, 색상, 사이즈) 가 유일해야 한다
         · 안 싣는다(2갈래·쿠팡)   → (색상, 사이즈) 가 유일해야 한다.
           모델이 달라도 마켓엔 같은 이름으로 나가므로 **겹치면 막아야 한다.**

      🔴 이 인자가 없으면 사고가 난다(2026-08-13 실측). 키를 무조건
         (모델,색상,사이즈)로 넓혔더니, 3축 상품을 쿠팡으로 보낼 때
         `블랙-260` 두 줄이 **에러 없이 통과**했다. 공용 정규화기라 쓰는 곳
         두 군데(스스·쿠팡)를 다 세어야 한다.
    """
    # 그릇부터 믿지 않는다. options_json 은 제약 없는 Text 컬럼이고, 등록 라우트가
    # 클라이언트 payload 를 검증 없이 json.dumps 해서 넣는다 — {"options": ["블랙"]}
    # 이 저장은 멀쩡히 되고 한참 뒤 등록 시점에 AttributeError(=500) 로 터진다.
    if not isinstance(opts, list):
        raise OptionValueInvalid(
            f'옵션 목록이 배열이 아닙니다: {type(opts).__name__} ({opts!r})')
    rows = []
    seen = {}
    for i, o in enumerate(opts):
        if not isinstance(o, dict):
            raise OptionValueInvalid(
                f'{i + 1}번째 옵션이 객체가 아닙니다: {type(o).__name__} ({o!r})')
        color = _text(o.get('color'))
        size = _text(o.get('size'))
        if not color:
            # 색상은 항상 필수 (사용자가 파는 단일축 상품은 '색상만' 형태).
            # ★ 지어내라는 뜻으로 읽히면 안 된다 — 'FREE'·'-' 를 채우면 그 값이
            #   구매자 드롭다운에 그대로 노출된다(우리 배열 값 = 구매자가 보는 값).
            raise OptionValueInvalid(
                f'{i + 1}번째 옵션: 색상이 비어 있습니다 (필수). 값을 임의로 '
                f'지어내지 마세요 — 구매자 화면에 그대로 노출됩니다.')
        if size:
            _size_key(size)  # 정렬 시점 말고 여기서 먼저 터지게 (nan 조기 차단)

        # [2026-08-13] 중복 검사 키 = **이번 전송이 실제로 내보내는 이름 조합.**
        #   #988 에서 고친 매트릭스 중복 키와 같은 계열이다 — 축이 3개인데 2개로 셌다.
        #   ★ 검사를 없앤 게 아니다. 모델을 안 싣는 전송에서는 예전 그대로 (색상,사이즈).
        model = _text(o.get('model'))
        key = (model, color, size) if split_model else (color, size)
        if key in seen:
            # 재고를 합치지 않는다 — 사용자가 표현한 적 없는 의도를 지어내는 셈이다.
            보임 = '/'.join(p for p in key if p) or '(빈 이름)'
            앞 = opts[seen[key]] if isinstance(opts[seen[key]], dict) else {}
            먼저모델 = _text(앞.get('model'))
            if not split_model and model and 먼저모델 and model != 먼저모델:
                # 🔴 여기가 진짜 사고 자리 — 사장님 눈엔 다른 옵션인데
                #   이 마켓엔 같은 이름으로 나간다. 사유를 정확히 말한다.
                raise OptionValueInvalid(
                    f'모델이 다른 옵션이 이 마켓에서는 같은 이름이 됩니다: '
                    f'{보임} (「{먼저모델}」 {seen[key] + 1}번째 · 「{model}」 {i + 1}번째). '
                    f'이 전송은 색상·사이즈 두 갈래로만 나가서 모델명이 실리지 않습니다 — '
                    f'상품가공 「옵션 축 구성」을 「모델명 · 색상 · 사이즈」 3갈래로 '
                    f'바꾸거나, 모델을 나눠서 올리세요.')
            raise OptionValueInvalid(
                f'같은 옵션이 두 번 들어왔습니다: {보임} '
                f'({seen[key] + 1}번째 · {i + 1}번째). 어느 쪽이 맞는지는 사용자만 압니다.')
        seen[key] = i

        extra = _num(o.get('extra_price'), '옵션 추가금')
        rows.append({
            'model': model,
            'color': color,
            'size': size,
            'stock': _num(o.get('stock'), '재고'),
            'extra_price': 0 if extra is None else extra,
            'sku': _text(o.get('sku')),
        })

    # ★ 한 상품 안에서 사이즈 유무가 섞이면 안 된다 — 스스 옵션 그룹은 상품 단위로
    #   고정이라(사이즈 축이 있거나 없거나 둘 중 하나), 일부만 사이즈가 있으면 마켓이
    #   payload 를 거부한다. 조용히 한쪽으로 뭉개지 않고 실패시킨다.
    has_size = [bool(r['size']) for r in rows]
    if rows and any(has_size) and not all(has_size):
        n_with = sum(has_size)
        raise OptionValueInvalid(
            f'옵션 {len(rows)}개 중 {n_with}개만 사이즈가 있습니다 — 한 상품은 '
            f'전부 사이즈가 있거나(색상×사이즈) 전부 없어야(색상만) 합니다. 섞을 수 없습니다.')
    return rows


def _split(rows):
    """행 목록 → (판매가능 정렬본, 제외 목록).

    Raises:
        NoSellableOption: 판매 가능한 옵션 0개
    """
    sellable, excluded = [], []
    for r in rows:
        stock = r['stock']
        if stock is None:
            reason = REASON_NO_STOCK
        elif stock > 0:
            sellable.append(r)
            continue
        elif stock == 0:
            reason = REASON_SOLD_OUT
        else:
            reason = REASON_UNKNOWN
        # 모델명도 같이 싣는다 — 3축 상품에서 색상·사이즈만 적으면 빠진 두 줄이
        # 화면에 똑같이 보여, 사장님이 어느 모델이 빠졌는지 알 수 없다.
        excluded.append({'model': r.get('model', ''),
                         'color': r['color'], 'size': r['size'],
                         'stock': stock, 'reason': reason})

    if not sellable:
        # 사유를 지어내지 않는다 — 실제로 무엇 때문에 비었는지 그대로 센다.
        if not excluded:
            raise NoSellableOption('판매 가능한 옵션이 없습니다 — 옵션 목록이 비어 있습니다.')
        counts = {}
        for e in excluded:
            counts[e['reason']] = counts.get(e['reason'], 0) + 1
        detail = ', '.join(f'{k} {v}개' for k, v in counts.items())
        raise NoSellableOption(f'판매 가능한 옵션이 없습니다 ({detail}).')

    # 사이즈가 있으면 색상→사이즈, 없으면(단일축) 색상만. _size_key('') 는 모든 빈값에
    # 같은 상수를 주므로 색상 정렬만 남아 안전하다 (삼항 없이 그대로 호출).
    sellable.sort(key=lambda r: (r['color'], _size_key(r['size'])))
    return sellable, excluded


def _final_price(base: int, o) -> int:
    """판매가 + 옵션가 = 구매자가 실제로 낼 돈. 0원 이하면 실패시킨다.

    음수 옵션가 자체는 정상이다 (더 싼 변형 = 할인 옵션가). 막아야 할 건 **합계**다.
    스스에도 똑같이 적용한다 — 우리가 절대가를 보내지 않을 뿐, 스스가 서버에서
    같은 덧셈을 하므로 구멍은 동일하다.
    가격 오류 = 금전 손실 (CLAUDE.md: 가격·재고 정확성은 타협 없음).
    """
    price = base + o['extra_price']
    if price <= 0:
        raise OptionValueInvalid(
            f"{o['color']}/{o['size']} 최종 가격이 {price:,}원입니다 "
            f"(판매가 {base:,} + 옵션가 {o['extra_price']:,}). 0원 이하로는 등록하지 않습니다.")
    return price


#: 1축으로 합칠 때 쓰는 축 이름 — 구매자 드롭다운에 그대로 보인다.
_ONE_GROUP = '옵션'

#: 노션 ①「마켓별 업로드 시 2/3축 구성 쪼갤 수 있음 — 2축(색상,사이즈) 3축(모델명,색상,사이즈)」
#:   우리 옵션은 언제나 하나의 옵션번호(1축)지만, 마켓에 올릴 때 몇 갈래로 보일지는
#:   마켓마다 다르게 정할 수 있다.
AXIS_ONE, AXIS_TWO, AXIS_THREE = 'one', 'two', 'three'


def build_smartstore_options(opts, *, sale_price, axis=AXIS_TWO):
    """옵션 목록 → (optionCombinationGroupNames, optionCombinations, excluded).

    sale_price: 상품 판매가. payload 에 싣지는 않지만(스스는 옵션가만 받는다)
                판매가+옵션가 합계가 0원 이하인지 검사하는 데 필요하다.
    axis: 'two'(기본) 색상·사이즈 두 갈래 / 'one' 한 갈래로 합침("메이트 블랙 260")
          / 'three' 모델명·색상·사이즈 세 갈래.
          모르는 값은 'two' 로 본다 — 축 구성은 구매자가 보는 드롭다운이라
          지어낸 모양으로 올리지 않는다.

          🔴 [2026-08-13] 'three' 를 **연다.** 예전엔 여기서 거절했고 사유가
             「옵션 행에 모델명 칸이 없어서」였다 — 마켓 탓이 아니라 우리 칸이
             없던 것이다. 칸을 만들었다(`policy/to_payload._options_json` 의 `model`,
             값은 `matrix/option_name.model_name_of`).
             마켓 근거(근거 서열 2 = 스스 개발자센터 원문, 판매처 지도에 수록):
               `optionCombinations` — 「최대 등록 가능한 옵션 개수는
               조합형은 3개, 지점형은 4개입니다.」
             ⚠️ 다만 카테고리가 **표준형 옵션**을 요구하면 3축 조합형은 못 쓴다
               (같은 원문: 「표준형 옵션, 단독형 옵션, 조합형 옵션은 함께 사용할 수
               없습니다」). 판정은 `GET /v1/options/standard-options` 의
               `useStandardOption`·`optionSetRequired` — 아직 안 부른다.
    excluded: [{'color','size','stock','reason'}] — 등록에서 빠진 행.
              상위가 사용자에게 보여줘야 한다 (조용한 실패 금지).

    Raises:
        OptionValueInvalid: 입력값이 잘못됨 (읽을 수 없는 재고·중복 옵션·빈 색상·
                            최종가 0원 이하 …)
        NoSellableOption: 판매 가능한 옵션 0개
        (둘 다 OptionError 하위 — 상위에서 OptionError 하나만 잡으면 된다)
    """
    base = _num(sale_price, '판매가')
    if base is None:
        raise OptionValueInvalid('판매가가 없습니다.')
    # 모델명을 이름에 싣는 전송(3갈래·1갈래 합침)에서만 중복 키를 넓힌다.
    rows, excluded = _split(_normalize(opts,
                                       split_model=axis in (AXIS_ONE, AXIS_THREE)))
    # optionName1/GroupName1 만 [필수], 2는 선택 → 사이즈 없는 상품(색상만)은 1축으로.
    has_size = bool(rows and rows[0]['size'])
    one = (axis == AXIS_ONE)
    three = (axis == AXIS_THREE)
    if three:
        # 🔴 3축인데 모델명이 빈 행이 있으면 **거절한다.** 「?」·모델코드로 채우면
        #   그 값이 구매자 드롭다운에 그대로 노출된다(우리 배열 값 = 구매자가 보는 값).
        빈 = [i + 1 for i, o in enumerate(rows) if not o.get('model')]
        if 빈:
            raise OptionValueInvalid(
                f'3갈래(모델명·색상·사이즈)로 올리려는데 모델명이 빈 옵션이 있습니다: '
                f'{", ".join(map(str, 빈))}번째. 값을 임의로 지어내지 마세요 — '
                f'구매자 화면에 그대로 노출됩니다.')
        groups = {'optionGroupName1': _MODEL_GROUP,
                  'optionGroupName2': _COLOR_GROUP}
        if has_size:
            groups['optionGroupName3'] = _SIZE_GROUP
    elif one:
        groups = {'optionGroupName1': _ONE_GROUP}
    elif has_size:
        groups = {'optionGroupName1': _COLOR_GROUP, 'optionGroupName2': _SIZE_GROUP}
    else:
        groups = {'optionGroupName1': _COLOR_GROUP}
    combos = []
    for o in rows:
        _final_price(base, o)   # 합계 검사만 — 스스에 싣는 건 옵션가(추가금)다
        if one:
            # 1축이면 축 값을 한 값으로 합친다("메이트 블랙 260").
            #  없는 축은 빈 칸이 뒤에 붙지 않게 걸러 낸다.
            첫칸 = ' '.join(v for v in (o.get('model'), o['color'], o['size']) if v)
        elif three:
            첫칸 = o['model']
        else:
            첫칸 = o['color']
        combo = {
            'optionName1': 첫칸,
            'stockQuantity': o['stock'],
            'price': o['extra_price'],
            'usable': True,
        }
        if three:
            combo['optionName2'] = o['color']
            if has_size:
                combo['optionName3'] = o['size']
        elif has_size and not one:
            combo['optionName2'] = o['size']
        if o['sku']:
            combo['sellerManagerCode'] = o['sku']
        combos.append(combo)
    return groups, combos, excluded


def build_coupang_items(opts, *, sale_price, image_url):
    """옵션 목록 → (쿠팡 items[], excluded). 옵션 추가금은 절대가에 가산한다.

    Raises:
        OptionValueInvalid: 입력값이 잘못됨 (최종가 0원 이하 포함)
        NoSellableOption: 판매 가능한 옵션 0개
    """
    base = _num(sale_price, '판매가')
    if base is None:
        raise OptionValueInvalid('판매가가 없습니다.')
    rows, excluded = _split(_normalize(opts))
    items = []
    for o in rows:
        price = _final_price(base, o)
        images = ([{'imageOrder': 0, 'imageType': 'REPRESENTATION',
                    'vendorPath': image_url}]
                  if image_url else [])
        # 사이즈 없으면(색상만) itemName·attributes 에서 사이즈를 뺀다 —
        # 빈 attributeValueName 은 쿠팡이 필수라 거부한다.
        item_name = f"{o['color']}-{o['size']}" if o['size'] else o['color']
        attrs = [{'attributeTypeName': '색상', 'attributeValueName': o['color']}]
        if o['size']:
            attrs.append({'attributeTypeName': '사이즈', 'attributeValueName': o['size']})
        items.append({
            'itemName': item_name,
            'originalPrice': price,
            'salePrice': price,
            'maximumBuyCount': o['stock'],
            'externalVendorSku': o['sku'],
            'images': images,
            'attributes': attrs,
        })
    return items, excluded

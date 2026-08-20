# -*- coding: utf-8 -*-
"""마켓으로 **정해져 나가는 값** — 사장님이 화면에서 정한 적 없는 것들.

━━ 왜 이 파일이 있나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  정책 화면에는 칸조차 없는데, 등록 코드에 **값이 박힌 채** 마켓으로 나가는 것들이
  있다. 예를 들어 쿠팡에는 과세구분이 늘 「과세」로 나간다 — 사장님이 고른 적이 없다.

  값 자체는 대부분 사장님 뜻과 맞다(엑셀 「마켓별 상품등록 정보」와 대조 완료).
  문제는 **화면 어디에서도 그 사실을 알 수 없다는 것**이다:
    · 무엇이 정해져 나가는지 모른다 → 「왜 이렇게 등록됐지」로 헤맨다
    · 정책에서 바꿔도 안 먹는데 화면은 조용하다 → 바뀐 줄 안다

🔴 **이 표는 「지금 코드가 무엇을 보내는가」의 사본이다.** 코드를 고치면 여기도
   같이 고쳐야 한다 — 안 고치면 화면이 거짓말을 한다. 그래서 시험이
   `compile_*` 원본을 읽어 이 표와 대조한다(tests/policy/test_fixed_sends.py).

🔴 **여기 적힌 것은 「사장님이 못 고치는 값」이다.** 정책 항목처럼 보이면 안 된다 —
   고칠 수 있는 칸과 섞이면 「고쳤는데 왜 안 먹지」가 된다.
"""
from __future__ import annotations

#: 값이 어디서 오는가
FROM_CODE = 'code'        # 등록 코드에 박혀 있다
FROM_DEFAULT = 'default'  # 초안(상품) 칸의 기본값이 그대로 나간다


class Fixed:
    """정해져 나가는 값 하나."""

    __slots__ = ('label', 'value', 'source', 'where', 'policy_item', 'note',
                 'policy_wins')

    def __init__(self, label, value, source, where, policy_item='', note='',
                 policy_wins=False):
        self.label = label            # 사장님이 읽는 이름
        self.value = value            # 실제로 나가는 값(사람 말로)
        self.source = source          # FROM_CODE | FROM_DEFAULT
        self.where = where            # 파일:라인 — 근거
        self.policy_item = policy_item  # 대응하는 정책 항목 key ('' 면 정책에 칸 없음)
        self.note = note
        # 🔴 [2026-08-13 2단계] 정책에 값을 넣으면 **그 값이 이기는** 칸.
        #   여기 표시를 안 하면 화면이 「정책 2,500 / 실제 3,000」이라고
        #   **반대 방향으로 거짓말**한다 — 이미 정책값이 나가고 있는데도.
        self.policy_wins = policy_wins

    def as_dict(self) -> dict:
        return {'label': self.label, 'value': self.value, 'source': self.source,
                'where': self.where, 'policy_item': self.policy_item,
                'note': self.note, 'policy_wins': self.policy_wins}


#: 마켓 → 정해져 나가는 값들
#:   🔴 「확인한 것만」 적는다. 옥션·G마켓·11번가·롯데온은 최종 전송값을 라이브에서
#:     조립하며 이번에 열지 않았다 — 비워 두고 화면이 「확인 못 했습니다」라고 말한다.
FIXED: dict[str, list] = {
    'coupang': [
        # [2026-08-13] 이어졌다 — 전에는 'TAX' 가 박혀 있어 면세로 바꿔도 과세로 나갔다.
        Fixed('과세구분', '과세', FROM_DEFAULT,
              'compile_coupang.py:256', 'listing',
              '정책에서 「면세」로 정하면 그대로 나갑니다 — 안 정하면 이 값입니다.',
              policy_wins=True),
        # 🔴 [2026-08-13 사장님 확정] 「무조건 새상품」 — 고를 것이 아니라 정해진 값이라
        #   정책 항목에서 빼고 여기로 옮겼다. 쿠팡 문서: 「상품 생성 후에는 변경 불가능」.
        Fixed('상품상태', '새상품', FROM_CODE,
              'compile_coupang.py:261', '',
              '전에는 아무것도 안 보내 쿠팡 기본값에 기대고 있었습니다 — 이제 명시해서 보냅니다.'),
        # [2026-08-13 2단계] 이어졌다 — 전에는 무조건 전연령으로 나갔다.
        Fixed('미성년자 구매', '전연령 구매 가능', FROM_DEFAULT,
              'compile_coupang.py:251', 'listing',
              '정책에서 「19세 이상만」으로 정하면 그대로 나갑니다 — 안 정하면 이 값입니다.',
              policy_wins=True),
        # 🔴 [2026-08-13 사장님 확정] 「마켓마다 가장 긴 것으로 알아서」 — 고를 것이
        #   아니므로 정책 항목에서 뺐다. 쿠팡은 2099년이 상한(문서 안내).
        Fixed('상품 판매기간', '2026-01-01 ~ 2099-12-31', FROM_CODE,
              'compile_coupang.py:20-21', '',
              '쿠팡은 종료일이 필수라 「설정 안 함」이 없습니다 — 문서가 길게 잡으라고 안내합니다. '
              '옥션·G마켓은 「무제한」, 11번가는 3년이 상한이라 마켓마다 가장 긴 값이 나갑니다.'),
        Fixed('병행수입 여부', '병행수입 아님', FROM_CODE,
              'compile_coupang.py:264', '_parallel_import'),
        Fixed('해외구매 여부', '해외구매 아님', FROM_CODE,
              'compile_coupang.py:265'),
        Fixed('개인통관부호', '필요 없음', FROM_CODE,
              'compile_coupang.py:266'),
        Fixed('택배사', 'CJ대한통운', FROM_CODE,
              'compile_coupang.py:22', 'shipping'),
        Fixed('출고 소요일', '3일', FROM_CODE,
              'compile_coupang.py:245', 'shipping'),
        Fixed('인당 최대 구매수', '제한 없음', FROM_CODE,
              'compile_coupang.py:243', '_max_per_person'),
        Fixed('상품정보제공고시', '비어 있음', FROM_CODE,
              'compile_coupang.py:242', 'notice',
              '🔴 쿠팡에는 고시정보가 통째로 비어 나갑니다 — 스마트스토어에는 들어갑니다.'),
    ],
    'smartstore': [
        Fixed('원산지', '국내산', FROM_DEFAULT,
              'registration/process_apply.py:OPERATIONAL_FALLBACKS', 'origin',
              '정책에서 「고정값」으로 정하면 그 값이 나갑니다 — 안 정하면(자동) 이 값입니다.',
              policy_wins=True),
        Fixed('수입사', '- (하이픈)', FROM_CODE,
              'compile_smartstore.py:86'),
        Fixed('가격비교 노출', '노출함', FROM_CODE,
              'compile_smartstore.py:165', 'price_compare',
              '사장님 엑셀도 「노출」이라 값은 맞습니다.'),
    ],
    # ── [2026-08-13 3단계] 11번가 조립 코드를 열었다 ────────────────────────
    #   🔴 앞에서는 「안 열어 봤다」로 비워 두고 있었다. 이번에 과세구분·제조사·
    #     모델번호·미성년자를 이으며 `build_register_xml` 을 전수로 읽었으니
    #     이제 「확인함」이다 — 안 열어 봤다고 계속 말하면 그것도 거짓말이다.
    'eleven11': [
        Fixed('과세구분', '과세', FROM_DEFAULT,
              'eleven11/products.py:275', 'listing',
              '정책에서 「면세」로 정하면 그대로 나갑니다 — 안 정하면 이 값입니다.',
              policy_wins=True),
        Fixed('상품상태', '새상품', FROM_CODE,
              'eleven11/products.py:282', '',
              '11번가는 상품상태가 필수라 늘 보냅니다.'),
        Fixed('미성년자 구매', '전연령 구매 가능', FROM_DEFAULT,
              'eleven11/products.py:287', 'listing',
              '정책에서 「19세 이상만」으로 정하면 그대로 나갑니다 — 안 정하면 이 값입니다.',
              policy_wins=True),
        Fixed('상품 판매기간', '오늘부터 3년', FROM_CODE,
              'eleven11/products.py:305-310', '',
              '11번가는 3년이 상한이라 이것이 가장 긴 값입니다. 빼면 500 이 납니다(실측).'),
        Fixed('판매방식', '고정가판매', FROM_CODE,
              'eleven11/products.py:271', '_sell_method'),
        Fixed('원산지', '상세설명 참조', FROM_CODE,
              'eleven11/products.py:277-278', 'origin',
              '🔴 11번가에는 정책에서 정한 원산지가 아직 안 나갑니다 — '
              '「기타(원산지명 입력)」로 「상세설명 참조」가 박혀 나갑니다.'),
        Fixed('배송비', '무료(선결제)', FROM_CODE,
              'eleven11/products.py:290-292', 'shipping',
              '🔴 11번가에는 정책 배송비가 아직 안 나갑니다 — 무료로 박혀 나갑니다.'),
        Fixed('묶음배송', '불가', FROM_CODE,
              'eleven11/products.py:293'),
        Fixed('제주·도서산간 배송비', '0원', FROM_CODE,
              'eleven11/products.py:294-295'),
        Fixed('바코드', '보내지 않음(칸 없음)', FROM_CODE,
              'eleven11/products.py:322-324', '',
              '11번가 등록에는 바코드 칸이 아예 없습니다(요청 필드 235개 전수 확인) — '
              '「확인 못 함」이 아니라 「없음」입니다.'),
        Fixed('검색태그', '보내지 않음', FROM_CODE,
              'eleven11/products.py:325-326', 'tags',
              '11번가 태그는 로드샵셀러·아울렛셀러만 쓸 수 있어 우리는 못 씁니다.'),
    ],
}
#: 옥션·G마켓은 **같은 ESM 조립기 하나**를 쓴다 — 표도 하나에서 갈라 쓴다.
#:   따로 적으면 한쪽만 고쳐져 갈린다.
_ESM_FIXED = [
    Fixed('과세구분', '과세', FROM_DEFAULT,
          'esm/products.py:479', 'listing',
          '정책에서 「면세」로 정하면 그대로 나갑니다 — 안 정하면 이 값입니다.',
          policy_wins=True),
    Fixed('미성년자 구매', '전연령 구매 가능', FROM_DEFAULT,
          'esm/products.py:478', 'listing',
          '정책에서 「19세 이상만」으로 정하면 그대로 나갑니다 — 안 정하면 이 값입니다.',
          policy_wins=True),
    Fixed('상품 판매기간', '무제한', FROM_CODE,
          'esm/products.py:414', '',
          '옥션·G마켓은 「무제한」이 있어 이것이 가장 긴 값입니다.'),
    Fixed('제조사', '보내지 않음(칸 없음)', FROM_CODE,
          'esm/products.py:452-457', 'listing',
          '옥션·G마켓 일반 상품에는 제조사 칸이 없습니다 — 「예약설치 상품」 전용 칸뿐입니다.'),
    Fixed('검색태그', '보내지 않음(칸 없음)', FROM_CODE,
          'esm/products.py:452-457', 'tags',
          '옥션·G마켓 등록 전문에서 태그 칸을 찾지 못했습니다.'),
    Fixed('배송비', '무료(개별배송비 0원)', FROM_CODE,
          'esm/products.py:468-469', 'shipping',
          '🔴 옥션·G마켓에는 정책 배송비가 아직 안 나갑니다 — 무료로 박혀 나갑니다.'),
    Fixed('사이트 할인', '쓰지 않음', FROM_CODE,
          'esm/products.py:484'),
]
FIXED['auction'] = list(_ESM_FIXED)
FIXED['gmarket'] = list(_ESM_FIXED)

#: 마켓과 무관하게 초안(상품) 기본값이 그대로 나가는 것
COMMON_DEFAULTS: list = [
    # [2026-08-20] 이어졌다 — 전에는 모음전 경로가 notice_type 을 전혀 채우지 않아
    #   신발·가방도 전부 「의류」로 나갔다. 이제 source_category_path 텍스트로
    #   신발·가방을 판정해 자동으로 채운다(send/as_draft.py::upsert →
    #   registration/notice_type_guess.guess_notice_type). 패션잡화(벨트·모자 등)
    #   는 판정하지 않는다(범위 밖 — 모듈 docstring 참고).
    Fixed('고시 유형', '의류(신발·가방은 자동 판정)', FROM_DEFAULT,
          'send/as_draft.py:notice_type_guess (registration/models.py:43 기본값)',
          'notice',
          '카테고리 텍스트로 신발·가방을 판정하지 못하면(애매하거나 패션잡화 등)'
          ' 여전히 「의류」로 나갑니다 — 잘못 단정하는 것보다 안전하기 때문입니다.'),
    Fixed('배송비', '3,000원', FROM_DEFAULT,
          'registration/process_apply.py:OPERATIONAL_FALLBACKS', 'shipping',
          '정책에서 정하면 그 금액이 나갑니다 — 안 정하면 이 값입니다.',
          policy_wins=True),
    Fixed('반품 배송비', '5,000원', FROM_DEFAULT,
          'registration/process_apply.py:OPERATIONAL_FALLBACKS', 'shipping',
          '정책에서 정하면 그 금액이 나갑니다 — 안 정하면 이 값입니다.',
          policy_wins=True),
]

#: 아직 확인하지 못한 마켓 — 「없다」가 아니라 「안 열어 봤다」
#:   [2026-08-13 3단계] 11번가·옥션·G마켓은 조립 코드를 전수로 읽어 표를 채웠다.
#:   롯데온만 남는다 — 등록 body 가 본보기 상품 상세를 그대로 베끼는 구조라
#:   무엇이 고정으로 나가는지 그 상품마다 다르다(아직 안 열었다).
UNCHECKED = ('lotteon',)
UNCHECKED_REASON = (
    '이 마켓들은 최종 전송값을 라이브에서 조립합니다 — 그 조립 코드를 아직 열지 '
    '않아 무엇이 정해져 나가는지 확인하지 못했습니다. 없다는 뜻이 아닙니다.'
)


#: ── [2026-08-13 사장님 확정 시안 v2 · 2번] 「마켓마다 어떤 값으로 나가는지 보기」 ──
#:   라디오 옆 접힘표가 읽는 표. 사장님이 「면세」를 고를 때 **어느 마켓에 무엇이
#:   나가는지**를 그 자리에서 볼 수 있어야 한다 — 마켓마다 값이 다르기 때문이다.
#:
#:   🔴 이 표도 「지금 코드가 무엇을 보내는가」의 사본이다. 조립기를 고치면 여기도
#:     고쳐야 하고, 그 대조는 시험이 조립기 원본을 읽어서 한다
#:     (tests/policy/test_fixed_sends.py::test_마켓별_전송표가_실제_코드와_같다).
#:   🔴 롯데온은 **「없다」가 아니라 「모른다」**다 — 등록 body 가 본보기 상품 상세를
#:     그대로 베끼는 구조라 아직 안 열었다. 빈칸으로 두지 말고 그렇게 적는다.
_UNKNOWN = ''          # 보내는 칸을 모른다 (화면은 '—' 로 그리고 회색으로 둔다)
_NO_FIELD = None       # 그 마켓에 칸 자체가 없다

SENDS_BY_MARKET: dict[str, list] = {
    # (마켓 id, 보내는 칸, 보내는 값 설명)
    'tax_type': [
        ('coupang', 'items.taxType', '과세=TAX / 면세=FREE'),
        ('smartstore', 'detailAttribute.taxType', '과세=TAX / 면세=DUTYFREE'),
        ('eleven11', 'suplDtyfrPrdClfCd', '과세=01 / 면세=02'),
        ('auction', 'itemAddtionalInfo > isVatFree', '과세=false / 면세=true'),
        ('gmarket', 'itemAddtionalInfo > isVatFree', '과세=false / 면세=true'),
        ('lotteon', _UNKNOWN, '등록 문서를 아직 못 열어 확인하지 못했습니다'),
    ],
    'minor_purchase': [
        ('coupang', 'items.adultOnly', '전연령=EVERYONE / 19세 이상만=ADULT_ONLY'),
        ('smartstore', 'detailAttribute.minorPurchasable', '전연령=true / 19세 이상만=false'),
        ('eleven11', 'minorSelCnYn', '전연령=Y / 19세 이상만=N'),
        ('auction', 'itemAddtionalInfo > isAdultProduct', '전연령=false / 19세 이상만=true'),
        ('gmarket', 'itemAddtionalInfo > isAdultProduct', '전연령=false / 19세 이상만=true'),
        ('lotteon', _UNKNOWN, '등록 문서를 아직 못 열어 확인하지 못했습니다'),
    ],
    'manufacturer_mode': [
        ('coupang', 'manufacture', '비우면 브랜드가 그대로 나갑니다(쿠팡 문서 권고)'),
        ('smartstore', 'naverShoppingSearchInfo.manufacturerName', '값이 있을 때만 나갑니다'),
        ('eleven11', 'company', '비우면 브랜드가 그대로 나갑니다'),
        ('auction', _NO_FIELD, '옥션 일반 상품에는 제조사 칸이 없습니다'),
        ('gmarket', _NO_FIELD, 'G마켓 일반 상품에는 제조사 칸이 없습니다'),
        ('lotteon', _UNKNOWN, '등록 문서를 아직 못 열어 확인하지 못했습니다'),
    ],
}


def sends_table(field_key: str) -> list:
    """그 칸이 마켓마다 어떤 이름·값으로 나가는지 — 화면(접힘표)이 쓰는 모양.

    Returns:
        [{market, label, field, value, state}] — state 는 'ok'|'unknown'|'none'
    """
    from lemouton.policy.fields import MARKET_LABEL
    out = []
    for mk, field, value in SENDS_BY_MARKET.get(field_key, []):
        state = 'ok' if field else ('none' if field is _NO_FIELD else 'unknown')
        out.append({'market': mk, 'label': MARKET_LABEL.get(mk, mk),
                    'field': field or '—', 'value': value, 'state': state})
    return out


def for_market(market: str) -> dict:
    """그 마켓에 정해져 나가는 값 — 화면이 쓰는 모양.

    Returns:
        {'rows': [...], 'checked': bool, 'reason': str}
    """
    mk = str(market or '').strip()
    if mk in UNCHECKED:
        return {'rows': [], 'checked': False, 'reason': UNCHECKED_REASON}
    rows = [f.as_dict() for f in FIXED.get(mk, [])]
    rows += [f.as_dict() for f in COMMON_DEFAULTS]
    return {'rows': rows, 'checked': bool(rows), 'reason': ''}


def conflicts(market: str, values: dict) -> list:
    """정책에 채운 값과 **실제로 나가는 값**이 어긋나는 곳.

    🔴 지금은 정책 쪽 값을 코드가 아예 안 읽으므로, 정책에 무엇을 넣든 고정값이
      나간다. 그 사실을 「조용히」 두면 사장님이 바꾼 줄 안다.

    Args:
        values: `policy.service.values_for()` 결과 — {item_key: config}

    Returns:
        [{label, policy, actual, where}] — 어긋난 것만
    """
    out = []
    for row in for_market(market)['rows']:
        key = row.get('policy_item')
        if not key or key not in (values or {}):
            continue                      # 정책에 안 채웠으면 어긋남이 아니다
        if row.get('policy_wins'):
            continue                      # 정책이 이기는 칸은 어긋날 수가 없다
        got = _policy_text(key, row['label'], values[key])
        if got and got != row['value']:
            out.append({'label': row['label'], 'policy': got,
                        'actual': row['value'], 'where': row['where']})
    return out


def by_item(market: str, values: dict) -> dict:
    """항목별로 「정책에 넣은 값 / 실제로 나가는 값」 — 화면이 늘 보여줄 모양.

    사장님 확정 B2 = **늘 나란히 보이기.** 다를 때만 보여주면 「같다」는 사실도
    확인이 안 되고, 안 보이는 동안 사장님은 정책값이 나가는 줄 안다.

    🔴 색은 다를 때만 준다 — 전부 주황이면 아무도 안 읽는다.

    Returns:
        {item_key: [{label, policy, actual, same, where}]}
        · policy 가 None 이면 「정책엔 안 정했고 실제로는 이 값이 나간다」는 뜻.
    """
    out: dict[str, list] = {}
    vals = values or {}
    for row in for_market(market)['rows']:
        key = row.get('policy_item')
        if not key:
            continue                      # 정책에 대응 칸이 없는 값은 접힌 표에만 나온다
        got = _policy_text(key, row['label'], vals.get(key) or {})
        # 🔴 정책이 이기는 칸은, 정책에 값이 있으면 **그 값이 실제로 나간다.**
        #   이 갈래가 없으면 화면이 「정책 2,500 / 실제 3,000」이라고 반대로
        #   거짓말한다 — 2단계에서 이미 정책값이 나가게 됐는데도.
        actual = got if (row.get('policy_wins') and got) else row['value']
        out.setdefault(key, []).append({
            'label': row['label'],
            'policy': got,                # None = 안 정함
            'actual': actual,
            'same': bool(got) and got == actual,
            'where': row['where'],
        })
    return out


#: 정책 칸 → 사람이 읽는 한 마디. 비교할 수 있는 것만 적는다.
_READERS = {
    ('listing', '과세구분'): lambda c: c.get('tax_type'),
    ('listing', '미성년자 구매'): lambda c: c.get('minor_purchase'),
    ('shipping', '배송비'): lambda c: (f"{c['fee_amount']:,}원"
                                       if isinstance(c.get('fee_amount'), int) else None),
    ('shipping', '반품 배송비'): lambda c: (f"{c['return_fee']:,}원"
                                            if isinstance(c.get('return_fee'), int) else None),
}


def _policy_text(item_key: str, label: str, cfg: dict):
    """그 정책 항목의 그 줄에서 「비교할 값」 한 마디. 못 뽑으면 None(비교 안 함).

    🔴 항목 이름만으로 고르면 안 된다 — 「배송」 하나에 배송비·반품비가 같이 들어 있어
      첫 번째 것만 걸린다(처음 이렇게 짰다가 잡았다).
    """
    fn = _READERS.get((item_key, label))
    if fn is None:
        return None
    try:
        got = fn(cfg or {})
    except Exception:                     # noqa: BLE001 — 값 모양이 달라도 화면은 살아야 한다
        return None
    return str(got) if got else None

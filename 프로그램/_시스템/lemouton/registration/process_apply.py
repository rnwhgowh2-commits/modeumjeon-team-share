# -*- coding: utf-8 -*-
"""가공 규칙 **적용** 엔진 — 순수함수. DB 는 라우트가 읽어 `rules` 로 넘긴다.

여기까지 가공 규칙은 정의(`process_rule_schema.py`)·저장(`process_policy.py`)·편집
(`/bulk?tab=process`)만 있었고 **적용하는 코드가 한 줄도 없었다.** 사장님이 화면에서
값을 넣어도 등록에 아무 영향이 없는 「조용한 거짓 기능」이었다. 이 모듈이 그 자리다.

■ 모양은 `brand_restrict.py` 와 똑같다
  순수함수 + 라우트가 DB 를 읽어 규칙을 주입. 여기서 세션을 만들거나 조회하지 않는다.
  (규칙을 읽어 오는 자리는 `process_policy.resolve_rules_for_draft` 하나다 — 두 곳이
   서로 다른 규칙을 읽으면 그 자체가 모순이다.)

■ 저장값은 건드리지 않는다
  `notice_defaults.DraftNoticeView` 와 같은 규율 — 저장된 드래프트는 사장님이 넣은
  그대로 남고, 가공은 **적용 시점에 만든 읽기 전용 사본**에서만 일어난다.
  드래프트에 미리 써 넣으면 ① 사장님이 넣은 값과 프로그램이 만든 값이 뭉개지고
  ② 다시 적용할 때 이미 가공된 값 위에 또 얹혀 「나이키 나이키 에어포스」가 된다.

■ 조용한 실패 금지 / 폴백 금지
  적용 못 한 것은 전부 :func:`apply_rules` 의 세 번째 반환값(`skipped`)에 **사유와
  함께** 남는다. 못 정한 값을 그럴듯하게 지어내지 않는다 — 못 정하면 「보류」다.
  `blocking=True` 인 항목이 하나라도 있으면 그 상태로 등록하면 안 된다(호출자가 막는다).

━━ 이번 범위 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [2026-07-31] 사장님 지시 — 「13항목 세부항목 모두 적용」. 항목별 현재 상태:

  여기서 하는 것
    · name     §7-1  상품명 조합 · 치환표 · 중복단어 · 글자수
    · brand    §7-6  브랜드 표기·위치
    · banned_words   수집/업로드 금지어
    · tags     §7-11 태그 (★ 아직 어느 마켓 payload 에도 안 실린다 — 미리보기)
    · options  §7-9  품절 제외. 정렬·조합형은 컴파일러가 고정이라 사유로 남긴다.
    · images   §7-3  올릴 장수 고르기 · 이미지 제외 브랜드 차단
    · detail   §7-4  상단·원본·하단 재조립
    · shipping §7-10 배송비·반품비 — **빈 칸만** 채운다(사람이 넣은 값이 우선)
    · origin   §7-6  원산지 코드·수입사 — 빈 칸만

  다른 곳이 담당하는 것 — 여기서 또 하면 두 답이 갈린다
    · notice   §7-5  → `notice_defaults.apply_notice_defaults` (M4-3)
    · category §7-8  → `webapp/routes/bulk/drafts.py::_mapped_category`
    · price    §7-2  → 마진 엔진(compute_final_price). 가공 사본에서 판매가를 만들면
                       「에러 없이 틀린 숫자」가 된다(금전 손실).

  칸이 없어 못 하는 것 — 사유에 **무엇이 없어서인지** 적는다
    · kc       §7-7  ProductDraft 에 KC 칸이 없다
    · shipping 제주·도서산간·묶음배송·출고소요일 — 칸도 마켓 payload 도 없다
"""
# [2026-07-23] M4 가공 규칙 적용 엔진
from __future__ import annotations

import json
import re

from lemouton.registration import market_limits as ML
from lemouton.registration.process_policy import ITEM_LABELS
# ★ [리뷰 C1] 금지어는 **말 단위**로 본다. 맨 포함검사면 수집 금지어 'Men' 이
#   'Mentoring Jacket' 에 걸려 초안이 통째로 사라진다('SET'·'BAG'·'SALE' 도 마찬가지).
#   판정기는 카테고리 제안과 **같은 것 하나**다(규칙을 두 벌 두면 한쪽만 고쳐져 갈린다).
from lemouton.registration.word_match import contains_word

#: 상품명 조립에 쓰는 토큰. 여기 없는 문자열은 **임의 텍스트**로 그대로 들어간다
#: (설계서 §7-1 「맨앞·맨뒤·중간에 임의 텍스트 삽입」).
NAME_TOKENS = ('brand', 'origin_name', 'model_no')

#: 브랜드가 비어 가공정책을 **고를 수조차 없는** 상태에 붙는 사유.
#: 사전 점검·등록·초안 생성이 **같은 문장**을 쓴다(brand_restrict.BRAND_REQUIRED_REASON 선례).
NO_BRAND_FOR_RULES_REASON = (
    '가공 규칙을 적용하지 못했습니다 — 브랜드가 정해지지 않았습니다. 가공정책은 '
    '「소싱처 × 브랜드」로 붙는데 이 상품의 브랜드가 비어 있어 어느 정책을 따라야 할지 '
    '고를 수 없습니다. 상품의 실제 브랜드를 넣어 주시면 규칙이 적용됩니다 '
    '(상품명에서 짐작해 넣으면 엉뚱한 정책이 적용됩니다).')

_HANGUL = re.compile(r'[가-힣ㄱ-ㅎㅏ-ㅣ]')
_LATIN = re.compile(r'[A-Za-z]')
_WS = re.compile(r'\s+')


# ── 읽기 전용 사본 ──────────────────────────────────────────────────────────

class DraftProcessView:
    """드래프트의 **읽기 전용 사본** — 가공된 칸만 바꿔 보여준다.

    `notice_defaults.DraftNoticeView` 와 같은 구조다. 컴파일러는 `draft.name` 을 읽을
    뿐이라, 저장된 행을 손대지 않고 이 사본만 넘기면 「저장값은 그대로, 적용 시점에만
    가공」이 지켜진다. 쓰기는 막는다 — 실수로 여기에 값을 넣으면 DB 에 안 남고 사라진다.

    [2026-07-31] 덮는 칸이 상품명·태그 둘뿐이던 것을 **임의의 칸**으로 넓혔다
    (옵션·이미지·상세·배송·원산지도 가공 대상이 됐다). 덮는 값은 `_over` 하나에
    모아 둔다 — 칸마다 슬롯을 늘리면 「어디까지 가공됐나」를 한눈에 볼 수 없다.

    `process_tags` 는 ProductDraft 에 없는 칸이다(아래 태그 절 주석 참고).
    """

    __slots__ = ('_draft', '_over')

    def __init__(self, draft, name, process_tags, over=None):
        object.__setattr__(self, '_draft', draft)
        merged = dict(over or {})
        merged['name'] = name
        # [리뷰 S3] 튜플로 얼려 둔다 — 리스트를 그대로 내주면 받은 쪽이 태그를
        # 뒤에서 고쳐도 「읽기 전용 사본」이라는 말이 거짓이 된다.
        merged['process_tags'] = tuple(process_tags or ())
        object.__setattr__(self, '_over', merged)

    @property
    def processed_fields(self) -> tuple:
        """가공으로 **실제로 달라진 칸 이름들**. 「무엇이 사본에서 바뀌었나」의 답.

        원본과 같은 값은 세지 않는다 — 안 바뀐 칸까지 「가공됨」이라고 하면
        사장님이 화면에서 무엇을 확인해야 하는지 알 수 없다.
        """
        draft = object.__getattribute__(self, '_draft')
        out = []
        for k, v in object.__getattribute__(self, '_over').items():
            # process_* 는 ProductDraft 의 칸이 아니라 컴파일러에 넘기는 값이다
            # (태그·옵션 축). 「바뀐 저장 칸」으로 세면 안 된다.
            if k.startswith('process_'):
                continue
            if v != getattr(draft, k, None):
                out.append(k)
        return tuple(out)

    def __getattr__(self, attr):
        over = object.__getattribute__(self, '_over')
        if attr in over:
            return over[attr]
        return getattr(object.__getattribute__(self, '_draft'), attr)

    def __setattr__(self, attr, value):
        raise AttributeError(
            'DraftProcessView 는 읽기 전용 사본입니다 — 원본 드래프트에 저장하세요.')

    def __repr__(self):
        return f'<DraftProcessView draft={object.__getattribute__(self, "_draft")!r}>'


# ── 로그 만들기 ─────────────────────────────────────────────────────────────

def _field_label(item, field):
    """항목 안의 칸 이름을 **한글 라벨**로. 없으면 키 그대로.

    ★ [2026-07-24 2차 리뷰 I-5] 예전에는 영문 필드키를 그대로 찍어
      「상품명 · replacements」·「금지어 · collect_banned」가 화면에 나왔다.
      사장님은 비개발자다. 스키마에 「치환표」·「수집 금지어」 라벨이 이미 있다.
    """
    from lemouton.registration.process_rule_schema import SCHEMAS
    sc = SCHEMAS.get(item)
    if sc is not None:
        for f in sc.fields:
            if f.key == field:
                return f.label
    # 조립 토큰은 스키마 「칸」이 아니라 token_order 의 값이라 따로 이름을 준다.
    return _TOKEN_LABEL.get(field, field)


#: 조립 토큰(§7-1) 이름 — 화면 문구용.
_TOKEN_LABEL = {
    'brand': '브랜드', 'origin_name': '원본 상품명', 'model_no': '품번',
}


def _label(item, field=''):
    lab = ITEM_LABELS.get(item, item)
    # field == item 은 「그 항목의 최종 결과」를 뜻하는 요약 줄이다 — 겹쳐 쓰지 않는다.
    if not field or field == item:
        return lab
    return f'{lab} · {_field_label(item, field)}'


def _applied(item, field, before, after, note=''):
    return {'item': item, 'field': field, 'label': _label(item, field),
            'before': before, 'after': after, 'note': note}


def _skip(item, field, code, reason, blocking, *, gap=False):
    """적용 못 한 사유 1건.

    gap=True 는 **이 상품의 문제가 아니라 프로그램에 기능이 아직 없다**는 뜻이다.
    ★ 이 구분이 없으면 「정사각 자르기 못 함」처럼 기본값이 켜져 있는 항목이 상품마다
      6마켓마다 상시로 떠서, **진짜 이 상품의 문제가 그 속에 묻힌다**
      (같은 이유로 「치환표가 비었다」를 사유로 남기지 않기로 한 선례가 있다 —
       :func:`_build_name` 리뷰 S2). 화면은 gap 을 따로 접어서 보여준다.
    """
    return {'item': item, 'field': field, 'label': _label(item, field),
            'code': code, 'reason': reason, 'blocking': bool(blocking),
            'gap': bool(gap)}


def capability_gaps(skipped):
    """`skipped` 중 **기능이 없어서 못 한 것**들. 상품별 문제와 섞지 않는다."""
    return [s for s in (skipped or []) if s.get('gap')]


def product_issues(skipped):
    """`skipped` 중 **이 상품을 고치면 되는 것**들."""
    return [s for s in (skipped or []) if not s.get('gap')]


def blocking_reasons(skipped):
    """`skipped` 중 **등록하면 안 되는** 사유들만. 화면이 그대로 보여준다."""
    return [s['reason'] for s in (skipped or []) if s.get('blocking')]


def has_code(skipped, code):
    return any(s.get('code') == code for s in (skipped or []))


# ── 브랜드 미확정 판정기 (함정: 크롤 초안은 브랜드가 자주 빈다) ─────────────

def needs_brand_for_rules(brand, policy_brands):
    """브랜드가 비어 정책을 고를 수 없으면 사유, 아니면 None.

    ★ `draft_from_crawl.py:301-303` — 크롤 초안의 브랜드는 **구조적으로 자주 빈다**
      (옵션 링크가 없거나 브랜드가 둘 이상이면 ''). 그대로 두면
      「브랜드 미확정 → 정책 미적용 → 조용히 원본 그대로 등록」이 된다.
      `brand_restrict.needs_brand` 와 같은 모양 — 「모름」을 「통과」로 읽지 않는다.

    Args:
        policy_brands: 그 소싱처에 가공정책이 붙어 있는 브랜드들.
            비어 있으면 애초에 적용할 정책이 없다 = 「미배정」이지 「브랜드 미확정」이
            아니다(미배정은 `unassigned_sources` 가 따로 표면화한다).
    """
    if str(brand or '').strip():
        return None
    if not [b for b in (policy_brands or []) if str(b or '').strip()]:
        return None
    return NO_BRAND_FOR_RULES_REASON


# ── 금지어 ──────────────────────────────────────────────────────────────────

def _norm_text(s):
    return _WS.sub(' ', str(s or '')).strip()


def _split_word(entry):
    """금지어 항목 → (단어, 정책이름).

    수집 금지어는 소싱처 단위로 모으느라 `(단어, 정책이름)` 짝으로 온다
    (`process_policy.collect_banned_for_source` — 리뷰 I-6: 어느 정책의 금지어인지
    말해 주지 않으면 사장님이 어디 가서 지워야 하는지 알 수 없다).
    업로드 금지어는 이 정책·이 마켓의 규칙이라 그냥 문자열이다.
    """
    if isinstance(entry, tuple) and len(entry) == 2:
        return entry[0], str(entry[1] or '')
    return entry, ''


def _read_word_list(raw, item, field):
    """금지어 목록 → (단어들, 문제 항목 사유들).

    읽을 수 없는 항목은 **조용히 건너뛰지 않는다** — 걸러야 할 단어를 못 읽은 채
    통과시키면 금지어 기능이 있으나 마나가 된다.

    돌려주는 단어는 `(단어, 정책이름)` 짝이다(정책 이름이 없으면 '').
    """
    words, bad = [], []
    for i, entry in enumerate(raw or [], 1):
        w, policy = _split_word(entry)
        if isinstance(w, str) and w.strip():
            words.append((w.strip(), policy))
        elif isinstance(w, str):
            continue                      # 빈 문자열은 그냥 빈 줄이다
        else:
            bad.append(_skip(item, field, 'BAD_BANNED_ENTRY',
                             f'금지어 목록 {i}번째를 읽을 수 없습니다: {w!r} — '
                             f'글자만 넣어 주세요. 못 읽은 단어가 있는 채로 통과시키면 '
                             f'금지어를 거른다는 말이 거짓이 됩니다.'
                             + (f' (정책 「{policy}」)' if policy else ''), True))
    return words, bad


def collect_banned_hits(text, words):
    """금지어 목록 중 그 글에 **말 단위로** 들어 있는 것들 (없으면 []).

    ★ [리뷰 C1] 맨 포함검사(`w.lower() in hay`)였다가 고쳤다. 그 시절엔
      수집 금지어 'Men' 이 'Mentoring Jacket' 에 걸려 **초안 자체가 안 만들어졌다.**
      'SET'·'BAG'·'SALE' 같은 짧은 영단어를 넣는 순간 카탈로그가 통째로 사라진다.
      판정기는 :func:`word_match.contains_word` 하나 — 카테고리 제안과 같은 잣대다.

    ★ 이 함수가 **수집 금지어 판정의 정본**이다. 초안 생성 라우트(from-url)와
      :func:`apply_rules` 가 같은 함수를 부른다(두 답이 갈리면 그게 곧 모순).

    `words` 는 문자열 목록이거나 `(단어, 정책이름)` 짝 목록. 돌려주는 것은
    받은 모양 그대로다(짝을 주면 짝이 돌아온다 — 사유에 정책 이름을 싣기 위해).
    """
    hay = _norm_text(text)
    return [w for w in (words or []) if contains_word(hay, _split_word(w)[0])]


def _word_text(hits):
    """걸린 항목들 → 화면 문구 (「단어(정책 「…」)」)."""
    out = []
    for h in hits:
        w, policy = _split_word(h)
        out.append(f'{w} (정책 「{policy}」)' if policy else str(w))
    return ', '.join(out)


def collect_banned_skip(hits):
    """수집 금지어에 걸렸다는 사유 1건 — **문구의 정본**.

    초안 생성 라우트(소싱처 이름 기준)와 :func:`_check_banned`(초안 이름 기준)가
    같은 문장을 쓴다. 문구를 두 곳에 적으면 한쪽만 고쳐져 갈린다.
    """
    return _skip('banned_words', 'collect_banned', 'COLLECT_BANNED',
                 f'수집 금지어가 소싱처 상품명에 있습니다: {_word_text(hits)} — '
                 f'수집 금지어는 어느 마켓에도 올리지 않습니다. '
                 f'데이터가공 탭에서 그 정책의 「수집 금지어」를 고쳐 주세요.', True)




# ── 치환표 ──────────────────────────────────────────────────────────────────

_ARROWS = ('→', '=>', '->', '⇒')


def _read_replacement(row, index):
    """치환 규칙 1줄 → ({'from','to','ignore_case'}, 사유) 중 하나.

    화면(policy_detail.html:139-141)이 아직 list 형 칸을 편집시키지 못한다 — UI 는
    다른 세션 몫이다. 여기서는 **어떤 모양이 와도 뜻이 분명한 것만** 받는다:
        {'from': '재킷', 'to': '자켓 재킷', 'ignore_case': False}
        ['재킷', '자켓 재킷']
        '재킷 → 자켓 재킷'   (→ / => / -> / ⇒)
    """
    if isinstance(row, dict):
        src = str(row.get('from') or row.get('src') or '').strip()
        dst = row.get('to', row.get('dst', ''))
        if src:
            return ({'from': src, 'to': str(dst or ''),
                     'ignore_case': bool(row.get('ignore_case'))}, None)
    elif isinstance(row, (list, tuple)) and len(row) >= 2:
        src = str(row[0] or '').strip()
        if src:
            return ({'from': src, 'to': str(row[1] or ''), 'ignore_case': False}, None)
    elif isinstance(row, str):
        for arrow in _ARROWS:
            if arrow in row:
                src, dst = row.split(arrow, 1)
                if src.strip():
                    return ({'from': src.strip(), 'to': dst.strip(),
                             'ignore_case': False}, None)
    return (None, _skip(
        'name', 'replacements', 'BAD_REPLACEMENT',
        f'치환표 {index}번째 줄을 읽을 수 없습니다: {row!r} — 「바꿀 말 → 바뀔 말」 '
        f'형태여야 합니다. 반쯤 적용된 치환은 엉뚱한 상품명을 만들기 때문에 '
        f'이 줄을 못 읽으면 가공을 멈춥니다.', True))


def _apply_replacements(text, rows):
    """(바뀐 글, 적용 로그, 사유들).

    ★ [리뷰 I2] 한 줄이라도 못 읽으면 **한 줄도 적용하지 않는다.** 예전에는
      읽을 수 있는 줄만 적용해 놓고 못 읽은 줄만 보고했는데, 그러면 미리보기에
      반쯤 가공된 이름이 뜬다(주석은 「멈춘다」고 적혀 있어 코드와 모순이었다).
      치환은 전부 되거나 전부 안 되거나 둘 중 하나여야 한다.
      ※ 브랜드 조립은 이 앞 단계라 되돌리지 않는다 — 「원본 그대로」가 아니라
        「치환 전 조립본 그대로」다.

    ★ [2026-07-24 2차 리뷰 ②] 치환은 **위에서 아래로 이어서** 적용된다.
      `재킷→자켓` 다음에 `자켓→JACKET` 이 있으면 결과는 `JACKET` 이다(연쇄).
      의도된 동작이다 — 「한글 병기 뒤 영문 통일」처럼 단계를 나눠 쓸 수 있다.
      원치 않으면 두 줄의 순서를 바꾸거나 한 줄로 합치면 된다.
    """
    parsed, bad = [], []
    for i, row in enumerate(rows or [], 1):
        rule, err = _read_replacement(row, i)
        if err:
            bad.append(err)
        else:
            parsed.append(rule)
    if bad:
        return (text, [], bad)

    out, notes = text, []
    for rule in parsed:
        src, dst = rule['from'], rule['to']
        if rule['ignore_case']:
            new = re.sub(re.escape(src), dst.replace('\\', '\\\\'), out,
                         flags=re.IGNORECASE)
        else:
            new = out.replace(src, dst)
        if new != out:
            notes.append(f'{src} → {dst}')
            out = new
    return out, notes, bad


# ── 브랜드 표기 ─────────────────────────────────────────────────────────────

def _brand_token(brand_raw, mode, brand_case):
    """(브랜드 토큰, 사유) — 못 만들면 (None, 사유).

    ★ 번역·추정 금지. 「영문 표기」인데 국문 브랜드밖에 없으면 지어내지 않고 보류한다.
    ★ [리뷰 C2] 단, 표기를 **고르지 않았으면**(`as_is`) 아무것도 요구하지 않는다.
      사장님이 고르지 않은 것을 「국문 요구」로 단정해 막으면, 영문 브랜드 상품이
      6마켓 전부 차단되고 안내문이 brand 칸을 고치게 만들어 실데이터까지 오염된다.
    """
    raw = str(brand_raw or '').strip()
    if not raw:
        return (None, _skip('brand', 'mode', 'BRAND_MODE_UNMET',
                            '브랜드가 비어 있어 상품명에 브랜드를 넣을 수 없습니다 — '
                            '상품의 실제 브랜드를 넣어 주세요.', True))
    ko, en = bool(_HANGUL.search(raw)), bool(_LATIN.search(raw))
    if mode == 'korean' and not ko:
        return (None, _skip('brand', 'mode', 'BRAND_MODE_UNMET',
                            f'브랜드 표기를 「국문」으로 정하셨는데 저장된 브랜드는 '
                            f'「{raw}」 뿐입니다 — 국문 브랜드명을 넣어 주세요 '
                            f'(프로그램이 번역해 지어내지 않습니다).', True))
    if mode == 'english' and not en:
        return (None, _skip('brand', 'mode', 'BRAND_MODE_UNMET',
                            f'브랜드 표기를 「영문」으로 정하셨는데 저장된 브랜드는 '
                            f'「{raw}」 뿐입니다 — 영문 브랜드명을 넣어 주세요 '
                            f'(프로그램이 번역해 지어내지 않습니다).', True))
    if mode == 'both' and not (ko and en):
        return (None, _skip('brand', 'mode', 'BRAND_MODE_UNMET',
                            f'브랜드 표기를 「국문+영문 병기」로 정하셨는데 저장된 '
                            f'브랜드는 한 가지 표기뿐입니다: 「{raw}」 — '
                            f'「노스페이스 THE NORTH FACE」처럼 두 표기를 다 넣어 주세요.',
                            True))
    token = raw
    # ★ [2026-07-24 3차 리뷰 2] 표기를 「지정 안 함」(as_is)으로 두셨으면 대소문자도
    #   건드리지 않는다. 표기 자체를 안 고르셨는데 대문자로 바꾸는 건 「고르지 않은
    #   표기 변형」이라 mode='as_is' 취지에 어긋난다(brand_case 는 표기를 고른 뒤에만).
    if mode != 'as_is' and brand_case == 'upper':
        # 영문만 대문자로. 한글은 대소문자가 없어 그대로다.
        token = ''.join(c.upper() if _LATIN.match(c) else c for c in token)
    return (token, None)


# ── 태그 ────────────────────────────────────────────────────────────────────

def _auto_tags(draft):
    """설계서 §7-11 「브랜드+카테고리+색상+소재 자동 생성」 — **있는 값만** 쓴다."""
    out = []
    brand = str(getattr(draft, 'brand', '') or '').strip()
    if brand:
        out.append(brand)
    path = str(getattr(draft, 'source_category_path', '') or '').strip()
    for seg in reversed([p.strip() for p in path.split('>') if p.strip()]):
        out.append(seg)
    try:
        opts = json.loads(getattr(draft, 'options_json', None) or '[]')
    except (ValueError, TypeError):
        opts = []
    if isinstance(opts, list):
        for o in opts:
            if isinstance(o, dict) and str(o.get('color') or '').strip():
                out.append(str(o['color']).strip())
    try:
        notice = json.loads(getattr(draft, 'notice_json', None) or '{}')
    except (ValueError, TypeError):
        notice = {}
    if isinstance(notice, dict) and str(notice.get('material') or '').strip():
        out.append(str(notice['material']).strip())
    return out


#: 자를 때 **뒤에 남겨 두면 안 되는** 글자 — 이것만 남으면 앞 글자와 짝이 깨진다.
#:   U+200D  ZWJ        (👨‍👩‍👧‍👦 처럼 이모지를 잇는 글자)
#:   U+FE0F/E  변이선택자 (❤️ 의 뒤 글자)
#:   서러게이트/결합문자는 파이썬 str 이 코드포인트 단위라 여기서는 안 생긴다.
_DANGLING = ('‍', '️', '︎')


def _cut_safe(text, cap):
    """`cap` 글자로 자르되 **이어붙은 이모지를 반토막 내지 않는다**.

    ★ [2026-07-24 2차 리뷰 ①] `'가'*98 + '👨‍👩‍👧‍👦'` 를 100자로 자르면 매달린 ZWJ 가
      남아 마켓 화면에 깨진 글자가 뜬다. 잘린 끝이 ZWJ·변이선택자면 그 짝까지 더 뗀다.
    """
    cut = text[:cap]
    while cut and (cut[-1] in _DANGLING):
        cut = cut[:-1]          # 매달린 ZWJ·변이선택자
        if cut:
            cut = cut[:-1]      # 그 앞 글자(짝이 깨진 이모지)까지
    return cut.rstrip()


def _cut_to_bytes(text, cap_b):
    """UTF-8 `cap_b` 바이트에 맞게 자른다 — **글자를 반토막 내지 않는다**.

    ★ 왜 글자 단위로 물러나나: 바이트 경계에서 그냥 자르면 한글 한 글자가 쪼개져
      깨진 글자가 마켓에 올라간다. `errors='ignore'` 로 뭉개는 방법도 있지만
      그러면 깨진 바이트가 조용히 남을 수 있어 쓰지 않는다.
    ★ 이모지 안전 처리는 `_cut_safe` 와 같은 규칙을 그대로 태운다 — 두 벌로 만들면
      한쪽만 고쳐져 어긋난다.
    """
    if not text or cap_b is None or cap_b <= 0:
        return text
    n = len(text)
    while n > 0:
        cut = _cut_safe(text, n)
        if len(cut.encode('utf-8')) <= cap_b:
            return cut
        n -= 1
    return ''


def _dedupe_keep_first(items):
    seen, out = set(), []
    for it in items:
        key = str(it).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(it).strip())
    return out


# ── 옵션 (§7-9) ─────────────────────────────────────────────────────────────

def _load_rows(draft, attr, empty):
    """JSON 칸을 읽는다 — 못 읽으면 (None, 사유). 조용히 빈 값으로 두지 않는다."""
    raw = getattr(draft, attr, None)
    if raw is None or raw == '':
        return (list(empty) if isinstance(empty, list) else dict(empty)), None
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        return None, f'{attr} 를 읽을 수 없습니다(손상된 JSON): {raw!r:.80}'
    if not isinstance(val, type(empty)):
        return None, f'{attr} 의 모양이 다릅니다: {type(val).__name__}'
    return val, None


def _apply_options(draft, cfg):
    """옵션 가공 — (options_json 문자열 | None, applied, skipped).

    ★ **컴파일러가 이미 하는 일을 여기서 또 하지 않는다.**
      `options._split` 이 판매가능 옵션을 (색상, 사이즈오름차순)으로 정렬하고
      품절·확인불가를 이미 뺀다. 그래서 규칙값이 그 동작과 **같은 쪽**이면 여기서
      할 일이 없고(「적용됨」으로 적되 어디가 하는지 밝힌다), **다른 쪽**이면
      컴파일러를 고쳐야 하므로 사유로 남긴다. 지어내지 않는다.
    """
    applied, skipped = [], []
    rows, err = _load_rows(draft, 'options_json', [])
    if err:
        return None, applied, [_skip('options', '', 'BAD_OPTIONS_JSON', err, True)]

    # ── 품절 옵션 제외 ──
    if cfg.get('exclude_soldout'):
        # 0 = 품절만 뺀다. None(미크롤)·음수(확인불가)는 **품절이 아니다** —
        # 여기서 빼 버리면 「모름」이 「없음」으로 둔갑한다(마켓 컴파일러가 따로 막는다).
        kept = [r for r in rows
                if not (isinstance(r, dict) and r.get('stock') == 0)]
        if len(kept) != len(rows):
            applied.append(_applied('options', 'exclude_soldout',
                                    f'{len(rows)}개', f'{len(kept)}개',
                                    note=f'품절(재고 0) 옵션 {len(rows) - len(kept)}개를 뺐습니다.'))
            rows = kept
        if not rows:
            skipped.append(_skip('options', 'exclude_soldout', 'ALL_SOLDOUT',
                                 '품절 옵션을 빼고 나니 남는 옵션이 없습니다 — '
                                 '이대로 올리면 살 수 없는 상품이 됩니다.', True))
    else:
        skipped.append(_skip('options', 'exclude_soldout', 'SOLDOUT_ALWAYS_EXCLUDED',
                             '「품절 옵션 제외」를 끄셨지만 지금은 끌 수 없습니다 — '
                             '마켓 컴파일러(options.py `_split`)가 품절·확인불가 옵션을 '
                             '항상 뺍니다. 품절 옵션을 올리면 주문을 받고 못 보내는 '
                             '오버셀이 나기 때문입니다.', False, gap=True))

    # ── 사이즈 정렬 ──
    order = cfg.get('size_order') or 'small_to_big'
    if order == 'small_to_big':
        applied.append(_applied('options', 'size_order', None, None,
                                note='사이즈를 작은 것부터 정렬합니다 '
                                     '(마켓 컴파일러 options.py `_split` 이 합니다).'))
    else:
        skipped.append(_skip('options', 'size_order', 'SORT_ALWAYS_ON',
                             '「정렬 안 함」을 고르셨지만 지금은 끌 수 없습니다 — '
                             '마켓 컴파일러가 항상 작은 사이즈부터 정렬합니다. '
                             '구매자 드롭다운 순서가 곧 이 정렬입니다.', False, gap=True))

    # ── 조합형 ──
    if not cfg.get('combine', True):
        skipped.append(_skip('options', 'combine', 'COMBINE_ONLY',
                             '「색상 × 사이즈 조합형」을 끄셨지만 지금은 끌 수 없습니다 — '
                             '6개 마켓 컴파일러가 모두 조합형만 만듭니다. 단독형으로 '
                             '바꾸면 사이즈별 재고를 어디에 실을지 정해야 합니다.', False, gap=True))

    # ── 옵션별 추가금 (노션 「(3) 마켓별 가격 정책 — 옵션별 추가금」) ──
    if (cfg.get('extra_price_mode') or 'as_is') == 'into_price':
        skipped.append(_skip('options', 'extra_price_mode', 'NO_EXTRA_INTO_PRICE',
                             '「판매가에 합치기」를 고르셨지만 지금은 할 수 없습니다 — '
                             '추가금은 옵션마다 다른데 판매가는 상품에 하나뿐이라, '
                             '어느 옵션 기준으로 합칠지 정할 수가 없습니다. '
                             '지금은 옵션 추가금을 그대로 마켓에 보냅니다.', False, gap=True))

    # ── 색상별 대표 이미지 ──
    if cfg.get('color_image_link'):
        skipped.append(_skip('options', 'color_image_link', 'NO_PER_COLOR_IMAGE',
                             '색상별 대표 이미지를 연결하지 못했습니다 — 옵션 칸에 '
                             '색상별 이미지 주소가 없습니다(옵션은 색상·사이즈·재고·'
                             '추가금·SKU 만 담습니다). 크롤이 색상별 이미지를 모아 오기 '
                             '전까지는 대표 이미지 한 장만 나갑니다.', False, gap=True))

    return json.dumps(rows, ensure_ascii=False), applied, skipped


def option_axis(cfg):
    """옵션 축 구성 — (축, applied, skipped). 노션 「(1) 마켓별 옵션 1/2/3축 구성」.

    우리 옵션번호는 언제나 하나다. 바뀌는 것은 **구매자에게 보이는 갈래 수**뿐이다.
    ★ 값은 사본에 실어 컴파일러로 보낸다(태그와 같은 방식). 컴파일러는 draft 만
      받으므로 사본에 얹지 않으면 화면에만 있고 안 먹는다.
    """
    from lemouton.registration.options import AXIS_ONE, AXIS_THREE, AXIS_TWO
    applied, skipped = [], []
    axis = (cfg or {}).get('axis') or AXIS_TWO
    if axis == AXIS_THREE:
        # 🔴 [2026-08-13] 강등을 **푼다.** 예전 사유는 「옵션에 모델명을 담는 칸이
        #   없습니다」였는데, 마켓 탓이 아니라 우리 칸이 없던 것이었다.
        #   칸을 만들었다 — `policy/to_payload._options_json` 의 `model`.
        #   마켓 근거(스스 개발자센터 원문, 판매처 지도 수록):
        #     「최대 등록 가능한 옵션 개수는 조합형은 3개, 지점형은 4개입니다.」
        #   🔴 [2026-08-13 정정] 한때 「카테고리가 표준형을 요구하면 못 쓴다」고
        #     적었으나 **검증 안 된 추론**이었다. 지도 `optionInfo` 원문에 표준형이
        #     아예 없고(「단독형·조합형·직접입력형 중 최소 한 개」),
        #     `docs/.../2026-07-17-대량등록-Phase1A.md:903` 이 이미
        #     「표준형은 강제가 아니다 — 조합형으로 진행이 맞다」로 결론냈다.
        #     사전 판정 게이트는 짓지 않는다 — 없는 제약을 만들지 않는다.
        applied.append(_applied('options', 'axis', '색상 · 사이즈',
                                '모델명 · 색상 · 사이즈',
                                note='세 갈래로 쪼개 올립니다 — 쪼개져도 옵션번호는 '
                                     '하나입니다(메이트 블랙 265). '
                                     '스마트스토어에만 드러납니다.'))
    elif axis not in (AXIS_ONE, AXIS_TWO):
        skipped.append(_skip('options', 'axis', 'UNKNOWN_AXIS',
                             f'모르는 축 구성입니다: {axis!r} — 구매자가 보는 드롭다운이라 '
                             f'지어내지 않고 기본(색상·사이즈)으로 올립니다.', False))
        axis = AXIS_TWO
    elif axis == AXIS_ONE:
        applied.append(_applied('options', 'axis', '색상 · 사이즈', '옵션 한 갈래',
                                note='「블랙 260」처럼 한 줄로 합쳐 올립니다 — '
                                     '스마트스토어에만 드러납니다(다른 마켓은 원래 '
                                     '한 덩어리로 보냅니다).'))
    return axis, applied, skipped


# ── 이미지 (§7-3) ───────────────────────────────────────────────────────────

def _apply_images(draft, cfg):
    """어느 이미지를 올릴지 고른다 — (images_json 문자열 | None, applied, skipped).

    ★ 여기서 고른 목록이 실제로 올라가려면 `service.py` 의 CDN 업로드가 **사본**을
      읽어야 한다(저장본을 읽으면 화면에서 고른 규칙이 아무 효과가 없다).
    """
    applied, skipped = [], []
    urls, err = _load_rows(draft, 'images_json', [])
    if err:
        return None, applied, [_skip('images', '', 'BAD_IMAGES_JSON', err, True)]
    urls = [u for u in urls if isinstance(u, str) and u.strip()]

    # ── 이미지를 쓰면 안 되는 브랜드 ──
    excluded = [str(b).strip() for b in (cfg.get('excluded_brands') or [])
                if str(b or '').strip()]
    brand = str(getattr(draft, 'brand', '') or '').strip()
    if brand and any(b.lower() == brand.lower() for b in excluded):
        skipped.append(_skip('images', 'excluded_brands', 'BRAND_IMAGE_BLOCKED',
                             f'「{brand}」 은 이미지 제외 브랜드입니다 — 소싱처 이미지를 '
                             f'쓰지 않기로 정하신 브랜드라 이 상품은 올리지 않습니다. '
                             f'직접 찍은 이미지를 넣으시면 올라갑니다.', True))
        return None, applied, skipped

    if not urls:
        skipped.append(_skip('images', '', 'NO_IMAGES',
                             '이미지가 한 장도 없습니다 — 어느 마켓에도 이미지 없이는 '
                             '올릴 수 없습니다.', True))
        return None, applied, skipped

    mode = cfg.get('mode') or 'rep_only'
    before = len(urls)
    if mode == 'rep_only':
        picked = urls[:1]
        note = '대표 이미지 1장만 올립니다.'
    elif mode == 'rep_plus_extra':
        extra = cfg.get('extra_count')
        extra = extra if isinstance(extra, int) and not isinstance(extra, bool) and extra > 0 else 0
        picked = urls[:1 + extra]
        note = f'대표 1장 + 추가 {min(extra, max(before - 1, 0))}장을 올립니다.'
    elif mode == 'range':
        f = cfg.get('range_from')
        t = cfg.get('range_to')
        f = f if isinstance(f, int) and not isinstance(f, bool) and f >= 1 else 1
        t = t if isinstance(t, int) and not isinstance(t, bool) and t >= 1 else f
        if t < f:
            skipped.append(_skip('images', 'range_to', 'BAD_RANGE',
                                 f'이미지 범위가 거꾸로입니다({f}번째부터 {t}번째까지) — '
                                 f'끝 번호가 시작 번호보다 작습니다.', True))
            return None, applied, skipped
        picked = urls[f - 1:t]
        note = f'{f}번째부터 {t}번째까지 올립니다.'
    else:
        skipped.append(_skip('images', 'mode', 'UNKNOWN_IMAGE_MODE',
                             f'모르는 이미지 방식입니다: {mode!r} — 지어내지 않고 멈춥니다.',
                             True))
        return None, applied, skipped

    if not picked:
        skipped.append(_skip('images', 'mode', 'IMAGE_PICK_EMPTY',
                             f'고른 범위에 이미지가 없습니다 — 이 상품의 이미지는 '
                             f'{before}장뿐입니다.', True))
        return None, applied, skipped
    if len(picked) != before:
        applied.append(_applied('images', 'mode', f'{before}장', f'{len(picked)}장',
                                note=note))

    if cfg.get('square_crop'):
        skipped.append(_skip('images', 'square_crop', 'NO_CROP',
                             '정사각 자르기를 하지 못했습니다 — 지금은 소싱처 이미지를 '
                             '그대로 네이버 CDN 에 올립니다(image_prep.py 는 자르기 '
                             '기능이 없습니다). 비율이 다른 이미지는 마켓 화면에서 '
                             '여백이 생길 수 있습니다.', False, gap=True))

    return json.dumps(picked, ensure_ascii=False), applied, skipped


# ── 상세설명 (§7-4) ─────────────────────────────────────────────────────────

def _img_tags(urls):
    out = []
    for u in urls or []:
        s = str(u or '').strip()
        if s:
            out.append(f'<img src="{s}">')
    return out


def _apply_detail(draft, cfg):
    """상세설명 조립 — (detail_html | None, applied, skipped)."""
    applied, skipped = [], []
    original = str(getattr(draft, 'detail_html', '') or '')
    mode = cfg.get('mode') or 'recombine'

    top = _img_tags(cfg.get('top_images'))
    bottom = _img_tags(cfg.get('bottom_images'))

    if mode == 'original':
        if top or bottom:
            skipped.append(_skip('detail', 'mode', 'ORIGINAL_KEEPS_ALL',
                                 '상세를 「원본 그대로」로 두셔서 상단·하단 삽입 이미지를 '
                                 '넣지 않았습니다 — 원본 그대로는 아무것도 덧붙이지 '
                                 '않는다는 뜻입니다.', False))
        body = original
    elif mode == 'frame':
        body = ''
    elif mode == 'recombine':
        body = original
    else:
        skipped.append(_skip('detail', 'mode', 'UNKNOWN_DETAIL_MODE',
                             f'모르는 상세 방식입니다: {mode!r} — 지어내지 않고 멈춥니다.',
                             True))
        return None, applied, skipped

    if mode != 'original':
        parts = list(top) + ([body] if body.strip() else []) + list(bottom)
        html = '\n'.join(parts)
    else:
        html = body

    if mode == 'frame' and not (top or bottom):
        skipped.append(_skip('detail', 'mode', 'FRAME_EMPTY',
                             '상세를 「틀만」으로 두셨는데 상단·하단 삽입 이미지가 '
                             '비어 있습니다 — 상세설명이 통째로 빈 채 올라갑니다.', True))

    if cfg.get('common_notice'):
        skipped.append(_skip('detail', 'common_notice', 'NO_COMMON_NOTICE',
                             '하단 공통안내를 붙이지 못했습니다 — 붙일 안내문이 아직 '
                             '어디에도 저장돼 있지 않습니다. 안내문을 정해 주시면 '
                             '상세 맨 아래에 자동으로 붙습니다.', False, gap=True))
    if cfg.get('hide_source_logo'):
        skipped.append(_skip('detail', 'hide_source_logo', 'NO_LOGO_MASK',
                             '소싱처 로고를 가리지 못했습니다 — 이미지 안의 로고를 '
                             '지우려면 이미지를 편집해야 하는데 그 기능이 없습니다. '
                             '로고가 든 이미지는 「이미지 제외 브랜드」로 막거나 직접 '
                             '찍은 사진을 쓰셔야 합니다.', False, gap=True))

    if html != original:
        applied.append(_applied('detail', 'mode', f'{len(original)}자', f'{len(html)}자',
                                note={'recombine': '상단·원본·하단 순서로 다시 조립했습니다.',
                                      'frame': '원본 상세를 빼고 틀만 남겼습니다.'}.get(mode, '')))
        return html, applied, skipped
    return None, applied, skipped


# ── 배송 · 원산지 · KC (§7-10 / §7-6 / §7-7) ────────────────────────────────
#
# 규율: **사람이 넣은 값이 규칙보다 우선한다.** 규칙은 「비어 있을 때 쓰는 기본값」이다.
#   드래프트의 배송비·반품비·원산지는 사람이 화면에서 채운 운영 사실이다. 규칙으로
#   덮으면 사장님이 이 상품에만 다르게 정한 값이 조용히 사라진다 —
#   `draft_from_crawl` 이 이름·브랜드를 「비어 있을 때만」 채우는 것과 같은 규율이다.

def _is_blank(v):
    """「아직 안 정함」인가. 0 은 **정한 값**이다(무료배송·반품비 0)."""
    return v is None or (isinstance(v, str) and not v.strip())


def _apply_shipping(draft, cfg):
    """배송 — (덮을 칸 dict, applied, skipped). 빈 칸만 채운다."""
    applied, skipped, over = [], [], {}

    fee_mode = cfg.get('fee_mode') or 'free'
    fee_amount = cfg.get('fee_amount')
    fee_amount = fee_amount if isinstance(fee_amount, int) and not isinstance(fee_amount, bool) else 0
    if fee_mode == 'free':
        want_fee = 0
    elif fee_mode in ('paid', 'free_over'):
        want_fee = fee_amount
    else:
        skipped.append(_skip('shipping', 'fee_mode', 'UNKNOWN_FEE_MODE',
                             f'모르는 배송비 방식입니다: {fee_mode!r} — 지어내지 않고 '
                             f'저장된 배송비를 그대로 씁니다.', False))
        want_fee = None

    if want_fee is not None:
        cur = getattr(draft, 'delivery_fee', None)
        if _is_blank(cur):
            over['delivery_fee'] = want_fee
            applied.append(_applied('shipping', 'fee_amount', None, want_fee,
                                    note='배송비가 비어 있어 규칙값을 넣었습니다.'))
        elif cur != want_fee:
            skipped.append(_skip('shipping', 'fee_amount', 'KEEP_HUMAN_VALUE',
                                 f'이 상품에 저장된 배송비({cur}원)를 그대로 씁니다 — '
                                 f'규칙값({want_fee}원)으로 덮지 않습니다. 사람이 넣은 '
                                 f'값이 규칙보다 우선입니다. 규칙을 따르게 하려면 '
                                 f'상품의 배송비 칸을 비워 주세요.', False))

    ret = cfg.get('return_fee')
    if isinstance(ret, int) and not isinstance(ret, bool):
        cur = getattr(draft, 'return_fee', None)
        if _is_blank(cur):
            over['return_fee'] = ret
            applied.append(_applied('shipping', 'return_fee', None, ret,
                                    note='반품 배송비가 비어 있어 규칙값을 넣었습니다.'))
        elif cur != ret:
            skipped.append(_skip('shipping', 'return_fee', 'KEEP_HUMAN_VALUE',
                                 f'이 상품에 저장된 반품 배송비({cur}원)를 그대로 씁니다 — '
                                 f'규칙값({ret}원)으로 덮지 않습니다.', False))

    if fee_mode == 'free_over':
        skipped.append(_skip('shipping', 'free_over', 'NO_FREE_OVER_FIELD',
                             '「이 금액 이상 무료」를 보내지 못했습니다 — 상품에 그 칸이 '
                             '없고, 쿠팡 payload 의 freeShipOverAmount 는 0 으로 고정돼 '
                             '있습니다(compile_coupang.py). 지금은 조건부 무료가 아니라 '
                             '유료배송으로 나갑니다.', True, gap=True))

    # ── A/S 안내 (노션 「AS안내메세지(스스:A/S번호포함)」) ──────────────────
    #   스마트스토어는 A/S 전화·안내가 없으면 등록 자체를 거부한다
    #   (compile_smartstore 가 가짜 번호를 넣지 않고 막는다). 정책에 적어 두면
    #   상품마다 다시 입력하지 않아도 되게 **빈 칸만** 채운다.
    for key, attr, label in (('as_phone', 'after_service_phone', 'A/S 전화번호'),
                             ('as_guide', 'after_service_guide', 'A/S 안내 문구')):
        want = str(cfg.get(key) or '').strip()
        if not want:
            continue
        cur = getattr(draft, attr, None)
        if _is_blank(cur):
            over[attr] = want
            applied.append(_applied('shipping', key, None, want,
                                    note=f'{label}가 비어 있어 정책값을 넣었습니다.'))
        elif str(cur).strip() != want:
            skipped.append(_skip('shipping', key, 'KEEP_HUMAN_VALUE',
                                 f'이 상품에 저장된 {label}를 그대로 씁니다 — '
                                 f'정책값으로 덮지 않습니다.', False))

    # ── 아직 보낼 자리가 없는 칸들 ──────────────────────────────────────────
    for key, label, why in (
            ('ship_from', '출하지 주소',
             '출고지는 마켓 계정에 등록된 주소로만 나갑니다 — 상품마다 다르게 보내는 '
             '길이 6개 마켓 어디에도 아직 없습니다.'),
            ('return_to', '반품 회송지 주소',
             '회송지도 마켓 계정 설정을 따릅니다 — 상품별로 보낼 자리가 없습니다.'),
            ('courier', '반품·교환 택배사',
             '등록 payload 에 택배사를 지정하는 칸이 없습니다(마켓 기본 택배사로 나갑니다).'),
            ('exchange_fee', '교환 배송비',
             '지금은 반품 배송비의 2배로 자동 계산됩니다(compile_more.py). '
             '따로 지정하는 칸이 없습니다.')):
        v = cfg.get(key)
        if v in (None, '', 0, False):
            continue
        skipped.append(_skip('shipping', key, 'NO_SHIPPING_FIELD',
                             f'「{label}」을 마켓에 보내지 못했습니다 — {why}',
                             False, gap=True))

    for key, label in (('jeju_extra', '제주 추가'), ('island_extra', '도서산간 추가'),
                       ('bundle', '묶음배송'), ('ship_days', '출고 소요일')):
        v = cfg.get(key)
        if v in (None, 0, False, ''):
            continue
        skipped.append(_skip('shipping', key, 'NO_SHIPPING_FIELD',
                             f'「{label}」을 마켓에 보내지 못했습니다 — 상품에 담을 칸도, '
                             f'6개 마켓 등록 payload 에 실을 자리도 아직 없습니다. '
                             f'마켓별로 어디에 넣을지 정해야 붙일 수 있습니다.', False, gap=True))
    return over, applied, skipped


def _apply_origin(draft, cfg):
    """원산지 — (덮을 칸 dict, applied, skipped). 빈 칸만 채운다."""
    applied, skipped, over = [], [], {}
    mode = cfg.get('mode') or 'auto'
    if mode == 'auto':
        # 「자동」 = 크롤·사람이 채운 값을 그대로 쓴다. 여기서 만들 것이 없다.
        return over, applied, skipped
    if mode != 'fixed':
        skipped.append(_skip('origin', 'mode', 'UNKNOWN_ORIGIN_MODE',
                             f'모르는 원산지 방식입니다: {mode!r} — 지어내지 않습니다.',
                             False))
        return over, applied, skipped

    fixed = str(cfg.get('fixed_value') or '').strip()
    if not fixed:
        skipped.append(_skip('origin', 'fixed_value', 'NO_FIXED_ORIGIN',
                             '원산지를 「고정값」으로 정하셨는데 고정값이 비어 있습니다 — '
                             '무엇으로 고정할지 적어 주세요(프로그램이 지어내지 않습니다).',
                             True))
        return over, applied, skipped

    cur = getattr(draft, 'origin_area_code', None)
    if _is_blank(cur):
        over['origin_area_code'] = fixed
        applied.append(_applied('origin', 'fixed_value', None, fixed,
                                note='원산지가 비어 있어 고정값을 넣었습니다.'))
    elif cur != fixed:
        skipped.append(_skip('origin', 'fixed_value', 'KEEP_HUMAN_VALUE',
                             f'이 상품에 저장된 원산지({cur})를 그대로 씁니다 — '
                             f'고정값({fixed})으로 덮지 않습니다.', False))
    return over, applied, skipped


# ── 배송비·반품비·원산지 「프로그램 최종 기본값」 (2026-08-20) ───────────────
#
# 왜 있나: `_apply_shipping`/`_apply_origin` 은 **정책이 있을 때만** 빈 칸을 채운다
#   (`apply_rules` 가 `rules.get('shipping')/('origin')` 이 None 이면 아예 안 부른다).
#   그런데 정책 자체가 없는 초안(수기 대량등록·크롤 초안은 흔히 그렇다)도 결국
#   마켓으로 나간다 — 그때 배송비·원산지가 빈 채로 나가면 「0원=무료배송」·
#   「원산지 미표기」처럼 마켓이 다르게 해석해 돈이 새거나 거부당한다.
#
#   예전엔 `ProductDraft` 컬럼 기본값(3000·5000·'0200037')이 이 자리를 메웠는데,
#   그 기본값이 **초안이 만들어지는 순간** 박혀 정책값을 영영 못 먹게 막았다
#   (바로 위 `_apply_shipping`/`_apply_origin` 의 `_is_blank` 판정 참고).
#
#   그래서 같은 숫자를 **여기 한 곳**으로 옮겼다 — 정책도 사람도 다 따진
#   **컴파일 직전**에만, 그래도 빈 칸이면 채운다. `fixed_sends.py` COMMON_DEFAULTS 가
#   화면에 보여주는 「정책 없으면 이 값」이 가리키는 곳이 바로 여기다 — 값을 바꾸면
#   거기도 같이 고쳐야 한다(그 파일 머리말 규율과 같다).
#
#   (item, field, draft 칸, 기본값) — item/field 는 `_apply_shipping`/`_apply_origin` 이
#   그 칸을 채울 때 쓰는 것과 **같은 이름**을 쓴다 — 화면 로그에 같은 항목으로 보여야
#   「정책이 채웠다」와 「기본값이 채웠다」를 같은 자리에서 비교할 수 있다.
OPERATIONAL_FALLBACKS = (
    ('shipping', 'fee_amount', 'delivery_fee', 3000),
    ('shipping', 'return_fee', 'return_fee', 5000),
    ('origin', 'fixed_value', 'origin_area_code', '0200037'),
)


def apply_operational_fallbacks(view):
    """정책도 사람도 안 정한 배송비·반품비·원산지에 프로그램 최종 기본값을 채운다.

    🔴 `apply_rules()` 가 다 끝난 **뒤**, 컴파일 바로 직전에만 부른다
      (`registration/service.py:prepare_compile_draft`). 저장된 드래프트는 절대
      건드리지 않는다 — 모듈 머리말 규율과 같다.

    Args:
        view: `apply_rules()` 가 돌려준 사본(또는 정책이 없어 그대로인 원본).

    Returns:
        (view, applied) — 채울 게 없으면 원본 view 를 그대로 돌려준다.
    """
    over = {}
    applied = []
    for item, field, attr, fallback in OPERATIONAL_FALLBACKS:
        cur = getattr(view, attr, None)
        if not _is_blank(cur):
            continue
        over[attr] = fallback
        applied.append(_applied(item, field, cur, fallback,
                                note='정책도 사람 입력도 없어 프로그램 기본값을 넣었습니다.'))
    if not over:
        return view, []
    return (DraftProcessView(view, getattr(view, 'name', ''),
                             getattr(view, 'process_tags', ()), over),
            applied)


#: 「판매방식·통관」 중 **초안에 담을 칸이 아직 없는** 것들.
#:   🔴 지어내서 마켓으로 보내면 금전 사고다 — 마켓별 payload 를 열어 어디에
#:     넣을지 정하기 전까지는 「못 보냅니다」라고 말만 한다.
#:   🔴 [2026-08-13] 여기 있던 넷이 전부 빠졌다 — 이제 칸이 생겨 실제로 나간다.
#:     · 과세구분·제조사 → 초안 칸 추가 + 4마켓 배선
#:     · 상품상태·판매기간 → 고를 것이 아니라 정해진 값이라 정책에서 뺐다
#:       (`policy/fixed_sends.py` 의 「정해져 나가는 값」이 보여준다)
#:     비면 이 목록은 비어 있어야 정상이다. 새로 「못 보내는 칸」이 생기면 여기 적는다.
_LISTING_NO_FIELD = ()

#: 화면 글자 → 초안 Boolean. 🔴 모르는 글자는 **지어내지 않는다**.
_MINOR_CHOICES = {'전연령 구매 가능': True, '19세 이상만': False}

#: 과세구분 선택지. 🔴 「영세」는 사장님 확정으로 뺐다 — 쿠팡·옥션·G마켓엔 보낼 칸이 없다.
_TAX_CHOICES = ('과세', '면세')


def _apply_listing(draft, cfg):
    """판매방식·통관 — 칸이 있는 것만 잇고, 없는 것은 사유로 말한다.

    🔴 이 항목은 원래 **아무도 안 읽었다.** 사장님이 「19세 이상만」으로 바꿔도
      초안은 그대로였고 화면은 조용했다.
    """
    applied, skipped, over = [], [], {}
    cfg = cfg or {}

    # ── 칸이 있는 것: 미성년자 구매 ─────────────────────────────────────────
    want = str(cfg.get('minor_purchase') or '').strip()
    if want:
        if want not in _MINOR_CHOICES:
            skipped.append(_skip('listing', 'minor_purchase', 'UNKNOWN_MINOR_CHOICE',
                                 f'모르는 값입니다: {want!r} — 지어내지 않습니다.', False))
        else:
            val = _MINOR_CHOICES[want]
            cur = getattr(draft, 'minor_purchasable', None)
            if cur is not val:
                over['minor_purchasable'] = val
                applied.append(_applied('listing', 'minor_purchase', cur, val,
                                        note=f'정책대로 「{want}」으로 맞췄습니다.'))

    # ── 칸이 있는 것: 과세구분 ───────────────────────────────────────────────
    #   🔴 정책이 말하지 않으면 손대지 않는다 — 사람이 상품에 넣어 둔 값을 덮으면
    #     「내가 면세로 해 뒀는데 왜 과세로 나가지」가 된다.
    want_tax = str(cfg.get('tax_type') or '').strip()
    if want_tax:
        if want_tax not in _TAX_CHOICES:
            skipped.append(_skip('listing', 'tax_type', 'UNKNOWN_TAX_TYPE',
                                 f'모르는 과세구분입니다: {want_tax!r} — 지어내지 않습니다. '
                                 f'「영세」는 쿠팡·옥션·G마켓에 보낼 칸이 없어 뺐습니다.',
                                 False))
        elif str(getattr(draft, 'tax_type', '') or '') != want_tax:
            over['tax_type'] = want_tax
            applied.append(_applied('listing', 'tax_type',
                                    getattr(draft, 'tax_type', None), want_tax,
                                    note=f'정책대로 「{want_tax}」로 맞췄습니다.'))

    # ── 칸이 있는 것: 제조사 ────────────────────────────────────────────────
    #   「브랜드와 동일」이면 **아무것도 안 넣는다** — 컴파일러가 비면 브랜드로
    #   갈음한다(쿠팡 문서 권고). 여기서 브랜드를 복사해 넣으면 원천이 둘이 된다.
    mode = str(cfg.get('manufacturer_mode') or '').strip()
    if mode == '직접 입력':
        fixed = str(cfg.get('manufacturer_fixed') or '').strip()
        if not fixed:
            skipped.append(_skip('listing', 'manufacturer_fixed', 'NO_MANUFACTURER',
                                 '제조사를 「직접 입력」으로 두셨는데 값이 비어 있습니다 — '
                                 '지금은 브랜드명이 그대로 나갑니다.', False))
        elif str(getattr(draft, 'manufacturer', '') or '') != fixed:
            over['manufacturer'] = fixed
            applied.append(_applied('listing', 'manufacturer_fixed',
                                    getattr(draft, 'manufacturer', None), fixed,
                                    note='정책에 적은 제조사를 넣었습니다.'))

    # ── 칸이 있는 것: 자동 가격 조정 최저가 (쿠팡 전용) ─────────────────────
    #   정책 항목은 `_auto_pricing`(fields.py) — mode/min_margin_pct/min_price.
    ap = cfg.get('_auto_pricing') if isinstance(cfg.get('_auto_pricing'), dict) else cfg
    ap_mode = str(ap.get('mode') or '').strip()
    if ap_mode.startswith('씀'):
        if '직접 입력' in ap_mode:
            try:
                floor = int(ap.get('min_price') or 0)
            except (TypeError, ValueError):
                floor = 0
            if floor <= 0:
                skipped.append(_skip('listing', 'auto_pricing_min', 'NO_AUTO_MIN',
                                     '자동 가격 조정을 「직접 입력」으로 두셨는데 최저 '
                                     '판매가가 비어 있습니다 — 최저가 없이 켜면 바닥 없이 '
                                     '값이 내려가므로 켜지 않았습니다.', False))
            elif getattr(draft, 'auto_pricing_min', None) != floor:
                over['auto_pricing_min'] = floor
                applied.append(_applied('listing', 'auto_pricing_min',
                                        getattr(draft, 'auto_pricing_min', None), floor,
                                        note=f'최저 판매가 {floor:,}원으로 켰습니다 '
                                             f'(쿠팡만 해당).'))
        else:
            # 🔴 「최저가를 마진율로 계산」은 **값을 만드는 일**이라 여기서 하지 않는다.
            #   판매가를 가공 사본에서 만들면 「에러 없이 틀린 숫자」가 된다(이 파일
            #   맨 위 규칙 — price 는 마진 엔진 몫). 지어내는 대신 못 했다고 말한다.
            skipped.append(_skip('listing', 'auto_pricing_min', 'AUTO_MIN_BY_MARGIN',
                                 '자동 가격 조정을 「최저가를 마진율로 계산」으로 '
                                 '두셨습니다 — 최저가를 마진율로 내는 계산은 아직 잇지 '
                                 '않아 켜지 않았습니다. 지금은 「최저가 직접 입력」만 '
                                 '나갑니다(엉뚱한 최저가로 켜면 값이 그만큼 내려갑니다).',
                                 False, gap=True))

    # ── 칸이 없는 것: 기본값과 다를 때만 말한다 ────────────────────────────
    #   기본값까지 사유로 만들면 화면이 경고로 뒤덮여 진짜 경고가 안 읽힌다.
    for key, label, default, why in _LISTING_NO_FIELD:
        v = str(cfg.get(key) or '').strip()
        if not v or v == default:
            continue
        skipped.append(_skip('listing', key, 'NO_LISTING_FIELD',
                             f'「{label}」을 「{v}」으로 정하셨지만 마켓에 보내지 '
                             f'못했습니다 — {why}', False, gap=True))
    return over, applied, skipped


#: 마켓이 「필수」라고 못 박은 것 중 **비면 진짜로 깨진 상품이 등록되는** 칸.
#:   (정책 항목 key, 초안 칸 이름, 사람이 읽는 이름)
#:
#: 🔴 required.py 가 필수라고 한 것을 **전부 막으면 안 된다.** 대부분은 상품
#:   기본값이 늘 차 있고(배송비 3,000 등), 몇몇은 정책이 아니라 다른 담당처가
#:   채운다(고시·카테고리·판매가). 여기 적는 것은 「비면 마켓에 빈 칸이 그대로
#:   올라가는」 것만이다. 실제로 확인했다 — 상품명·상세설명이 빈 채로
#:   sellerProductName='' / content='' 로 조립됐다.
_MUST_NOT_BE_EMPTY = (
    ('name', 'name', '상품명'),
    ('brand', 'brand', '브랜드'),
)

#: 필수인데 비었지만 **막지는 않는** 것 — 칸 자체가 없어서 비는 것들.
#:   🔴 상세설명은 모음전 경로에 **담을 칸이 아예 없다**(`to_payload.set_view` 의
#:     `'detail_html': ''` — 「상세는 아직 구성에 칸이 없다」). 여기서 막으면
#:     모음전 전송이 **통째로 멈춘다.** 「칸이 있는데 비었다」와 「칸이 없다」는
#:     다른 문제다 — 앞은 막고, 뒤는 말한다.
_EMPTY_BUT_NO_FIELD = (
    ('detail', 'detail_html', '상세설명',
     '모음전 구성에는 상세설명을 담을 칸이 아직 없습니다 — 정책의 「상세설명」 '
     '항목에 상단·하단 이미지를 넣으면 그것이 상세가 됩니다.'),
)

#: 마켓 슬러그 → 사장님이 읽는 이름
_MARKET_LABEL = {'coupang': '쿠팡', 'smartstore': '스마트스토어', 'eleven11': '11번가',
                 'auction': '옥션', 'gmarket': 'G마켓', 'lotteon': '롯데온'}


def _check_market_required(draft, name, over, market):
    """마켓 필수 칸이 **빈 채로 나가려 하면** 막는다.

    🔴 `policy/required.py` 는 지금까지 화면만 읽었다 — 전송 경로는 한 번도
      보지 않았다. 「필수라고 화면에 배지까지 달아 놓고 빈 채로 보내는」 것은
      아는데 안 막은 것이다.

    🔴 「확인 불가」는 막지 않는다. 롯데온은 등록 API 문서를 아직 못 열어 전 항목이
      unknown 이다 — 모르는 것으로 막으면 라이브 전송이 조용히 멈춘다.
    """
    if not market or market not in _MARKET_LABEL:
        return []                          # 공통 가공엔 마켓 필수 판정이 없다
    try:
        from lemouton.policy import required as REQ    # 순환 import 회피(지연)
    except Exception:                       # noqa: BLE001 — 판정을 못 해도 전송은 살아야 한다
        logger.exception('[필수검사] required 판정표를 못 읽었습니다 market=%s', market)
        return []

    mk = _MARKET_LABEL[market]
    out = []
    for item, attr, label in _MUST_NOT_BE_EMPTY:
        try:
            if REQ.status_of(market, item)[0] != REQ.REQUIRED:
                continue
        except Exception:                   # noqa: BLE001
            continue
        # 가공 결과가 있으면 그것이 실제로 나가는 값이다(상품명은 여기서 조립된다).
        val = over[attr] if attr in over else (name if attr == 'name'
                                               else getattr(draft, attr, None))
        if not _is_blank(val):
            continue
        out.append(_skip(item, attr, 'MARKET_REQUIRED_EMPTY',
                         f'「{label}」이 비어 있어 {mk}에 보낼 수 없습니다 — '
                         f'{mk} 등록 API 가 필수로 요구하는 값입니다. '
                         f'빈 채로 올리면 상품이 거부되거나 빈 칸으로 등록됩니다.',
                         True))

    # 칸 자체가 없어 비는 것 — 막지 않고 말한다.
    for item, attr, label, why in _EMPTY_BUT_NO_FIELD:
        try:
            if REQ.status_of(market, item)[0] != REQ.REQUIRED:
                continue
        except Exception:                   # noqa: BLE001
            continue
        val = over[attr] if attr in over else getattr(draft, attr, None)
        if _is_blank(val):
            out.append(_skip(item, attr, 'MARKET_REQUIRED_NO_FIELD',
                             f'「{label}」이 빈 채로 {mk}에 나갑니다 — {mk} 등록 API 는 '
                             f'이 값을 필수로 요구합니다. {why}', False, gap=True))
    return out


def _apply_price_compare(draft, cfg):
    """가격비교 노출 (§7-6) — (덮을 칸, applied, skipped).

    🔴 [2026-08-24 Phase 4-5] 이 항목은 **저장만 되고 아무 데도 안 갔다.**
      스스는 `naverShoppingRegistration: True` 가 코드에 박혀 있었고,
      11번가·ESM 은 칸 자체를 안 보냈다. 사장님이 「노출 안 함」으로 정해도
      그대로 노출됐다는 뜻이다 — 가격비교는 수수료가 더 붙는다(금전 직결).

    ■ 마켓별 칸 (2026-08-24 지도 전문 + 라이브 대조 실측)
      · 스마트스토어 `naverShoppingRegistration` (boolean) **필수**
        ⚠️ 네이버 쇼핑 광고주가 아니면 보낸 값과 무관하게 false 로 저장된다.
      · 11번가 `prcCmpExpYn` (Y/N, 선택) · 할인적용 `prcDscCmpExpYn` (Y/N, 선택)
      · 옥션 `addtionalInfo>pcs>isUse` (Boolean) · 쿠폰 `isUseIacPcsCoupon`
      · G마켓 `addtionalInfo>pcs>isUse` (Boolean)
        🔴 쿠폰 칸(`isUseGmkPcsCoupon`)은 지도에 **「사용불가」** — 설정 못 한다.
      · 쿠팡 **칸 없음** (지도·라이브 둘 다 0건)
      · 롯데온 **확인 불가** — 등록 API 필드가 지도에 부분만 실려 있다.

    🔴 정책이 말하지 않으면 손대지 않는다 — 지금까지의 동작이 그대로 유지된다.
    """
    over, applied, skipped = {}, [], []
    if 'expose' in cfg:
        want = cfg.get('expose')
        if isinstance(want, bool):
            over['price_compare_expose'] = want
            applied.append(_applied('price_compare', 'expose', None, want,
                                    note=('가격비교에 노출합니다.' if want else
                                          '가격비교에 노출하지 않습니다 — 수수료 가산이 '
                                          '붙지 않습니다.')))
        else:
            skipped.append(_skip('price_compare', 'expose', 'BAD_EXPOSE',
                                 f'노출 여부가 예/아니오가 아닙니다: {want!r} — '
                                 '지어내지 않습니다.', False))
    if 'coupon' in cfg:
        want_c = cfg.get('coupon')
        if isinstance(want_c, bool):
            over['price_compare_coupon'] = want_c
            applied.append(_applied('price_compare', 'coupon', None, want_c,
                                    note='가격비교에서 쿠폰 적용 여부입니다 — '
                                         '11번가·옥션만 정할 수 있습니다'
                                         '(G마켓은 마켓이 설정을 막아 뒀습니다).'))
    return over, applied, skipped


def _apply_kc(draft, cfg):
    """KC 인증 — 담을 칸이 없다. **조용히 넘기지 않고** 무엇이 없어서인지 말한다."""
    skipped = []
    if cfg.get('safety_target'):
        skipped.append(_skip('kc', 'safety_target', 'NO_KC_FIELD',
                             '「안전기준준수 대상」을 마켓에 보내지 못했습니다 — 상품에 '
                             'KC 칸이 없습니다(product_drafts 전수 확인). 지금은 상품고시'
                             '정보에 사람이 적은 내용만 나갑니다.', False, gap=True))
    if cfg.get('collect_kc_no'):
        skipped.append(_skip('kc', 'collect_kc_no', 'NO_KC_COLLECT',
                             '「KC 인증번호 수집」을 켜 두셨지만 크롤이 KC 번호를 모아 오지 '
                             '않습니다 — 소싱처 어댑터에 그 항목이 없습니다.', False, gap=True))
    return {}, [], skipped


# ── 다른 곳이 담당하는 항목 대조 (§7-5 / §7-8 / §7-2) ───────────────────────

def crosscheck_delegated(rules, *, notice_filled_from=None, category_code=None,
                         sale_price=None):
    """규칙값이 **실제 담당처의 동작과 맞는지** 대조해 어긋나면 사유로 돌려준다.

    고시·카테고리·판매가는 이 엔진이 만들지 않는다(만들면 두 곳에서 같은 값을 만들어
    갈린다). 그렇다고 규칙을 **읽지도 않고 넘기면** 사장님은 화면에서 값을 정해 놓고
    아무 일도 안 일어나는 이유를 알 수 없다 — 그래서 「누가 하고 있는지」를 말한다.
    """
    out = []
    rules = rules or {}

    cat = rules.get('category')
    if cat is not None:
        if not cat.get('auto_map'):
            out.append(_skip('category', 'auto_map', 'AUTOMAP_ALWAYS_ON',
                             '「자동 매핑」을 끄셨지만 지금은 끌 수 없습니다 — 카테고리는 '
                             '언제나 확정된 매핑표(CategoryMapRow)에서 찾습니다. 매핑이 '
                             '없으면 등록을 보류합니다.', False, gap=True))
        if cat.get('on_fail') == 'default_category':
            out.append(_skip('category', 'on_fail', 'NO_DEFAULT_CATEGORY',
                             '「실패하면 기본 카테고리로」를 고르셨지만 기본 카테고리가 '
                             '정해져 있지 않습니다 — 엉뚱한 카테고리에 올리면 마켓 제재 '
                             '대상이라 지어내지 않고 보류합니다.', False, gap=True))
        elif category_code in (None, '', 0):
            out.append(_skip('category', 'on_fail', 'CATEGORY_HELD',
                             '카테고리를 찾지 못해 보류합니다 — 매핑표에서 이 소싱처 '
                             '카테고리를 확정해 주세요.', True))

    nt = rules.get('notice')
    if nt is not None:
        if not nt.get('auto_from_crawl'):
            out.append(_skip('notice', 'auto_from_crawl', 'NOTICE_DEFAULTS_ALWAYS',
                             '「크롤 값 우선」을 끄셨지만 지금은 끌 수 없습니다 — '
                             '고시정보는 사람이 넣은 값이 먼저이고, 빈 칸만 기본값으로 '
                             '채웁니다(notice_defaults). 규칙으로 그 순서를 뒤집는 길이 '
                             '아직 없습니다.', False, gap=True))
        if nt.get('warn_on_missing') and not notice_filled_from:
            out.append(_skip('notice', 'warn_on_missing', 'NOTICE_NOT_FILLED',
                             '고시정보를 기본값으로 채운 칸이 하나도 없습니다 — 빈 칸이 '
                             '남아 있으면 마켓이 등록을 거부합니다.', False))

    pr = rules.get('price')
    if pr is not None:
        # [2026-08-01] 칸 이름이 소싱/사입으로 갈렸다. 옛 칸 번역은 price_cfg 한 곳만
        #   거친다 — 여기서 또 번역하면 미리보기와 갈린다.
        from lemouton.policy.price_cfg import read_side
        side = read_side(pr, 'sourcing')
        if side.mode == 'fixed_price':
            want = side.fixed
            if not want:
                out.append(_skip('price', 'sourcing_fixed', 'NO_FIXED_PRICE',
                                 '판매가를 「지정가」로 정하셨는데 금액이 비어 '
                                 '있습니다 — 0원으로 올릴 수 없어 멈춥니다.', True))
            elif sale_price is not None and sale_price != want:
                out.append(_skip('price', 'sourcing_fixed', 'PRICE_NOT_APPLIED',
                                 f'규칙의 지정 판매가({want:,}원)가 이 상품의 판매가'
                                 f'({sale_price:,}원)와 다릅니다 — 판매가는 마진 엔진과 '
                                 f'상품 화면이 정합니다. 가공 규칙이 판매가를 덮으면 '
                                 f'같은 금액을 두 곳에서 만들게 돼 갈립니다.', False))
        else:
            out.append(_skip('price', 'sourcing_rate', 'PRICE_BY_MARGIN_ENGINE',
                             '판매가는 마진 엔진이 최종매입가에 마진율을 붙여 만듭니다 — '
                             '가공 규칙의 마진율은 계산에 쓰이지 않습니다. 마진율은 '
                             '「정책 생성」에서 정해 주세요(같은 숫자를 두 곳에 두면 '
                             '반드시 갈립니다).', False, gap=True))
    return out


# ── 본체 ────────────────────────────────────────────────────────────────────

def apply_rules(draft_like, rules, *, market='', collect_banned_words=None):
    """드래프트 + 규칙 한 벌 → (읽기 전용 사본, applied, skipped).

    Args:
        draft_like: ProductDraft 또는 그 사본(DraftNoticeView 등). **변경하지 않는다.**
        rules: `{item_key: config}` — `process_policy.rules_for()` 가 주는 그 모양.
        market: 마켓 슬러그. ''(공통)이면 마켓별 상한을 적용하지 않는다.
        collect_banned_words: **수집 금지어** 목록. 라우트가
            `process_policy.collect_banned_for_source` 로 읽어 주입한다.
            ★ [리뷰 I5] 수집 금지어는 「소싱처 단위」 게이트다 — 브랜드가 비어
              정책을 못 고르는 상태에서도 반드시 돌아야 한다. 그래서 `rules` 안이
              아니라 **밖에서 주입**받는다(브랜드 미확정이면 rules 가 {} 라서,
              rules 에서 읽으면 「짝퉁 스니커즈」가 그대로 초안이 됐다).

    Returns:
        (view, applied, skipped)
          view    : 가공된 상품명·태그를 가진 읽기 전용 사본. 바뀐 게 없으면 원본 그대로.
          applied : [{item, field, label, before, after, note}] — 무엇이 무엇으로 바뀌었나
          skipped : [{item, field, label, code, reason, blocking}] — 왜 적용 못 했나
    """
    # [리뷰 S5] 이미 가공된 사본을 또 넣으면 브랜드가 두 번 붙는다
    # (dedupe_words 가 꺼져 있으면 「나이키 나이키 …」로 바로 드러난다).
    if isinstance(draft_like, DraftProcessView):
        raise TypeError(
            'apply_rules 에 이미 가공된 사본(DraftProcessView)을 다시 넣었습니다 — '
            '원본 드래프트를 넘기세요(두 번 적용하면 브랜드·치환이 겹칩니다).')

    rules = rules or {}
    applied, skipped = [], []

    name_cfg = rules.get('name')
    brand_cfg = rules.get('brand')
    banned_cfg = rules.get('banned_words')
    tags_cfg = rules.get('tags')

    original_name = str(getattr(draft_like, 'name', '') or '')
    name = original_name

    # ── 1) 상품명 조립 (§7-1) ───────────────────────────────────────────────
    if name_cfg is not None:
        name, a, s = _build_name(draft_like, name_cfg, brand_cfg, market)
        applied.extend(a)
        skipped.extend(s)
    elif brand_cfg is not None:
        # 브랜드 규칙만 저장돼 있으면 붙일 자리가 없다 — 조용히 「적용됨」으로 치지 않는다.
        skipped.append(_skip('brand', 'position', 'NO_NAME_RULE',
                             '브랜드 표기 규칙은 상품명 조합 규칙과 함께 써야 합니다 — '
                             '「상품명」 항목을 저장하기 전까지는 브랜드 위치가 '
                             '상품명에 반영되지 않습니다.', False))

    # ── 2) 금지어 (§7-1 2분류) ──────────────────────────────────────────────
    #   수집 금지어 = 주입값(소싱처 단위) · 업로드 금지어 = 이 정책·이 마켓의 규칙
    collect, cbad = _read_word_list(collect_banned_words,
                                    'banned_words', 'collect_banned')
    upload, ubad = _read_word_list((banned_cfg or {}).get('upload_banned'),
                                   'banned_words', 'upload_banned')

    # ★ [2026-07-24 2차 리뷰 I-2] 규칙에 수집 금지어가 있는데 **주입되지 않았으면**
    #   그 게이트는 통째로 꺼진 것이다. 예전에는 그 상태에서 「아직 등록된 금지어가
    #   없습니다」라고 말했다 — 사장님이 등록한 금지어가 있는데 없다고 말하는 거짓 안내다.
    #   조용히 넘어가지 않고 **막는다**(호출자가 주입을 빼먹으면 여기서 터진다).
    rule_collect = [w for w in ((banned_cfg or {}).get('collect_banned') or [])
                    if not (isinstance(w, str) and not w.strip())]
    injected = {repr(_split_word(w)[0]) for w in (collect_banned_words or [])}
    missing = [w for w in rule_collect if repr(w) not in injected]
    if missing:
        skipped.append(_skip(
            'banned_words', 'collect_banned', 'COLLECT_NOT_INJECTED',
            f'수집 금지어 {len(missing)}개가 검사에 쓰이지 않았습니다: '
            f'{", ".join(str(w) for w in missing[:5])} — 수집 금지어는 소싱처 단위로 '
            f'따로 모아 넘겨야 합니다(process_policy.collect_banned_for_source). '
            f'이대로 두면 금지어를 거른다고 해 놓고 못 거릅니다.', True))

    if banned_cfg is not None or collect:
        # 주입이 빠진 상태는 「목록이 비었다」가 **아니다** — 거짓 안내를 막는다(I-2).
        skipped.extend(_check_banned(collect, cbad, upload, ubad,
                                     original_name, name, market,
                                     have_words=bool(missing)))
        if (collect or upload) and not (cbad or ubad):
            # ★ [리뷰 I-3] **무엇을 검사했는지**까지 말한다. 지금 보는 것은 상품명뿐이고,
            #   브랜드 칸·옵션명·상세는 검사하지 않는다(11번가는 brand 를 별도 payload 로
            #   보낸다 — compile_more.py:132-140). 「아예 안 가져옵니다」라는 안내만 두면
            #   검사 안 하는 칸까지 걸러 준다고 믿게 된다.
            applied.append(_applied('banned_words', 'collect_banned',
                                    None, None,
                                    note=f'상품명에서 수집 금지어 {len(collect)}개 · '
                                         f'업로드 금지어 {len(upload)}개를 검사했습니다 '
                                         f'(브랜드 칸·옵션명·상세설명은 아직 검사하지 '
                                         f'않습니다).'))

    # ── 3) 태그 (§7-11) ─────────────────────────────────────────────────────
    tags = []
    if tags_cfg is not None:
        tags, a, s = _build_tags(draft_like, tags_cfg, collect + upload)
        applied.extend(a)
        skipped.extend(s)

    # ── 4) 내용 가공 — 옵션·이미지·상세 (§7-9 / §7-3 / §7-4) ────────────────
    #   전부 **사본에만** 쓴다. 저장된 드래프트는 손대지 않는다(모듈 머리말 규율).
    over = {}
    for item, fn, attr in (('options', _apply_options, 'options_json'),
                           ('images', _apply_images, 'images_json'),
                           ('detail', _apply_detail, 'detail_html')):
        cfg = rules.get(item)
        if cfg is None:
            continue
        val, a, s = fn(draft_like, cfg)
        applied.extend(a)
        skipped.extend(s)
        if val is not None:
            over[attr] = val

    # 옵션 축은 저장 칸이 아니라 **컴파일러에 넘기는 값**이라 따로 얹는다.
    if rules.get('options') is not None:
        axis, a, s = option_axis(rules['options'])
        applied.extend(a)
        skipped.extend(s)
        over['process_option_axis'] = axis

    # ── 4-b) 즉시할인 — 옥션·G마켓은 등록 요청 안에 실어 보낸다 ─────────────
    #   🔴 [2026-08-26 지도 전수정독] `addtionalInfo.sellerDiscount` 는 **별도 API 가
    #     아니라 등록 payload 안**에 있다. 그래서 여기(가공)에서 사본에 실어야
    #     조립기가 집어 갈 수 있다.
    #   🔴 판정·검사는 `policy/discount.py` 한 곳이다 — 여기서 다시 계산하면
    #     화면이 「보낸다」고 한 값과 실제로 나가는 값이 갈린다.
    #   🔴 못 받을 값이면 **안 싣는다.** `problem_for` 가 이미 사람 말로 사유를
    #     말하므로, 조용히 깎거나 반올림해서 보내지 않는다.
    if market and rules.get('price') is not None:
        from lemouton.policy import discount as _DC
        _dc = _DC.discount_of(rules)
        if _dc:
            _why = _DC.problem_for(market, _dc)
            if _why:
                skipped.append(_skip('price', 'discount_value', 'DISCOUNT_NOT_SENT',
                                     _why, False))
            else:
                _sd = _DC.esm_seller_discount(market, _dc)
                if _sd:
                    over['seller_discount'] = _sd
                    applied.append(_applied(
                        'price', 'discount_value', None, _dc['value'],
                        note=(f'{_DC.market_label(market)} 즉시할인을 '
                              + (f"{_dc['value']:,}원" if _dc['unitType'] == 'WON'
                                 else f"{_dc['value']}%")
                              + ' 걸어 보냅니다.')))

    # ── 5) 운영값 — 배송·원산지·KC (§7-10 / §7-6 / §7-7) ────────────────────
    #   빈 칸만 채운다. 사람이 넣은 값은 규칙보다 우선이고, 다르면 사유로 말한다.
    for item, fn in (('shipping', _apply_shipping), ('origin', _apply_origin),
                     ('kc', _apply_kc), ('listing', _apply_listing),
                     ('price_compare', _apply_price_compare)):
        cfg = rules.get(item)
        if cfg is None:
            continue
        fields, a, s = fn(draft_like, cfg)
        applied.extend(a)
        skipped.extend(s)
        over.update(fields)

    # ── 6) 마켓 필수 칸이 빈 채로 나가려 하는가 (§전송 게이트) ─────────────
    #   🔴 가공을 다 마친 **최종 값**으로 본다 — 원본이 비어도 규칙이 채웠으면
    #     막을 일이 아니고, 원본이 차 있어도 규칙이 비웠으면 막아야 한다.
    skipped += _check_market_required(draft_like, name, over, market)

    if name == original_name and not tags and not over:
        return (draft_like, applied, skipped)
    return (DraftProcessView(draft_like, name, tags, over), applied, skipped)


def _build_name(draft, cfg, brand_cfg, market):
    """상품명 조립 — (이름, applied, skipped)."""
    applied, skipped = [], []
    before = str(getattr(draft, 'name', '') or '')

    order = list(cfg.get('token_order') or ['brand', 'origin_name'])
    sep = cfg.get('separator')
    sep = ' ' if sep is None else str(sep)
    brand_case = cfg.get('brand_case') or 'upper'

    # ★ [리뷰 C2] 브랜드 규칙이 저장돼 있지 않거나 표기를 고르지 않았으면
    #   **표기를 강제하지 않는다**('as_is'). 예전 `or 'korean'` 은 사장님이 고르지도
    #   않은 「국문 요구」를 지어내, 영문 브랜드 상품을 6마켓 전부 막았다.
    brand_mode = (brand_cfg or {}).get('mode') or 'as_is'
    # ★ [2026-07-24 2차 리뷰 C-new] 위치도 마찬가지 — 고르지 않았으면('as_is')
    #   **조립 순서를 그대로 따른다.** 예전 기본값 'front' 는 사장님이 정한
    #   ['origin_name','brand'] 를 고른 적 없는 값으로 뒤집었다.
    brand_pos = (brand_cfg or {}).get('position') or 'as_is'

    # 브랜드 위치를 **명시적으로 고른** 경우에만 조립 순서의 brand 자리를 덮어쓴다.
    if brand_pos in ('front', 'back', 'none'):
        was = list(order)
        order = [t for t in order if t != 'brand']
        if brand_pos == 'front':
            order.insert(0, 'brand')
        elif brand_pos == 'back':
            order.append('brand')
        if brand_pos == 'none':
            applied.append(_applied('brand', 'position', was, order,
                                    note='브랜드 위치를 「없음」으로 정하셔서 상품명에서 '
                                         '브랜드를 뺐습니다.'))
        elif order != was and 'brand' in was:
            # ★ 순서가 실제로 바뀐 경우 반드시 말한다 — 말하지 않으면 사장님이
            #   「내가 정한 조립 순서가 왜 뒤집혔지」를 화면에서 알 길이 없다.
            applied.append(_applied('brand', 'position', was, order,
                                    note='브랜드 위치 규칙이 「상품명」의 조립 순서보다 '
                                         '우선합니다 — 브랜드를 '
                                         + ('맨 앞' if brand_pos == 'front' else '맨 뒤')
                                         + '으로 옮겼습니다.'))

    parts = []
    for tok in order:
        key = str(tok or '')
        if key == 'brand':
            token, err = _brand_token(getattr(draft, 'brand', ''), brand_mode, brand_case)
            if err:
                skipped.append(err)
                continue
            parts.append(token)
        elif key == 'origin_name':
            if not before.strip():
                skipped.append(_skip('name', 'origin_name', 'NO_NAME',
                                     '원본 상품명이 비어 있습니다 — 크롤이 이름을 못 '
                                     '가져왔습니다. 이름 없이는 어느 마켓에도 올릴 수 '
                                     '없습니다.', True))
                continue
            parts.append(before.strip())
        elif key == 'model_no':
            # ★ [2026-08-24 Phase 3] 품번은 `Model.article_no` 에 있다.
            #   구성 사본(`to_payload.set_view`)이 실어 주면 여기서 붙는다.
            #   예전엔 「담을 칸이 아예 없다」였는데, 칸은 있고 사본이 안 실어
            #   주고 있었을 뿐이다. 그래도 **비면 조용히 빼지 않고 말한다** —
            #   다음 사람이 「규칙이 안 먹는다」로 오해하지 않게.
            art = str(getattr(draft, 'article_no', '') or '').strip()
            if art:
                parts.append(art)
            else:
                skipped.append(_skip('name', 'model_no', 'NO_MODEL_NO',
                                     '이 상품에는 품번이 비어 있어 상품명에 품번을 '
                                     '넣지 못했습니다 — 조립 순서에서 품번은 빠집니다.',
                                     False))
        elif key == 'product_no':
            # 상품번호 — 화면에서 보이는 번호가 있으면 그것, 없으면 모델 코드.
            pno = (str(getattr(draft, 'display_no', '') or '').strip()
                   or str(getattr(draft, 'model_code', '') or '').strip())
            if pno:
                parts.append(pno)
            else:
                skipped.append(_skip('name', 'product_no', 'NO_PRODUCT_NO',
                                     '이 상품에는 상품번호가 없어 상품명에 넣지 '
                                     '못했습니다.', False))
        elif key == 'category':
            # 🔴 '신발>스니커즈' 를 통째로 넣으면 상품명에 꺾쇠가 들어간다 —
            #   맨 끝 칸(가장 좁은 분류)만 쓴다.
            path = str(getattr(draft, 'source_category_path', '') or '').strip()
            leaf = path.replace('>', '/').split('/')[-1].strip() if path else ''
            if leaf:
                parts.append(leaf)
            else:
                skipped.append(_skip('name', 'category', 'NO_CATEGORY',
                                     '이 상품에는 카테고리가 없어 상품명에 넣지 '
                                     '못했습니다.', False))
        elif key.strip():
            parts.append(key.strip())        # 임의 텍스트 (§7-1)

    name = sep.join(p for p in parts if p)

    # 치환표 — [리뷰 I2] 한 줄이라도 못 읽으면 한 줄도 적용되지 않는다(_apply_replacements)
    reps = cfg.get('replacements')
    if reps:
        name, notes, bad = _apply_replacements(name, reps)
        skipped.extend(bad)
        if notes:
            applied.append(_applied('name', 'replacements', before, name,
                                    note='치환: ' + ' · '.join(notes)))
    # ★ [리뷰 S2] 「치환표가 비었다」는 사유로 남기지 않는다 — 치환을 안 쓰는 것이
    #   정상 상태라 모든 마켓 행에 상시 뜨고, 늘 뜨는 경고는 안 읽힌다.
    #   (금지어는 다르다 — 「거른다」고 해 놓고 못 거르는 상태라 반드시 남긴다.)

    # 치환으로 말이 빠지면 공백이 겹친다 — [리뷰 I6] '나이키  패딩' 이 그대로 나가면
    # 마켓 노출 상품명이 지저분해진다. 조립·치환이 끝난 뒤 한 번 정리한다.
    squeezed = _WS.sub(' ', name).strip()
    if squeezed != name:
        applied.append(_applied('name', 'separator', name, squeezed,
                                note='겹친 공백을 정리했습니다.'))
        name = squeezed

    # 중복 단어 제거
    if cfg.get('dedupe_words'):
        words = name.split()
        kept = _dedupe_keep_first(words)
        if len(kept) != len(words):
            dropped = len(words) - len(kept)
            name = ' '.join(kept)
            applied.append(_applied('name', 'dedupe_words', ' '.join(words), name,
                                    note=f'중복 단어 {dropped}개를 뺐습니다.'))

    # 글자수 상한 — 사장님이 정한 값 + (확인된) 마켓 상한 중 **작은 쪽**
    limits, notes = [], []
    rule_max = cfg.get('max_len')
    if isinstance(rule_max, int) and not isinstance(rule_max, bool) and rule_max > 0:
        limits.append((rule_max, '가공 규칙'))
    # ★ [2026-08-24] 마켓 한도는 **글자수와 바이트 두 가지**다. 예전엔 글자수만 봤다.
    #   마켓 문서가 「100자」라고 적어 둔 곳도 실제 등록기는 바이트로 자른다 —
    #   한글은 UTF-8 로 3바이트라, 글자수만 통과시키면 마켓이 거부하거나 잘라 버린다.
    #   🔴 11번가 99바이트·롯데ON 149바이트는 삼바 실측값이다(그 값으로 매일 등록된다).
    mk_lim = ML.name_limit_for(market)
    mk_max = mk_lim['chars']
    mk_bytes = mk_lim['bytes']
    if mk_max:
        limits.append((mk_max, f'{market} 상한'))
    if not mk_max and not mk_bytes and market:
        # 글자수도 바이트도 모를 때만 「확인 불가」다. 바이트만 아는 마켓(롯데ON)을
        # 여기로 떨어뜨리면 **상한이 없는 셈**이 되어 잘린 이름이 그대로 팔린다.
        why = ML.name_limit_unknown_reason(market)
        if why:
            skipped.append(_skip('name', 'max_len', 'NO_MARKET_LIMIT', why, False))
    if limits:
        cap, who = min(limits, key=lambda x: x[0])
        if len(name) > cap:
            cut = _cut_safe(name, cap)
            applied.append(_applied('name', 'max_len', name, cut,
                                    note=f'{who}({cap}자)에 맞춰 뒤를 잘랐습니다.'))
            name = cut
    if mk_bytes and len(name.encode('utf-8')) > mk_bytes:
        cut = _cut_to_bytes(name, mk_bytes)
        applied.append(_applied('name', 'max_len', name, cut,
                                note=f'{market} 상한({mk_bytes}바이트)에 맞춰 뒤를 '
                                     f'잘랐습니다 — 한글은 한 글자가 3바이트입니다.'))
        name = cut

    if name != before:
        applied.append(_applied('name', 'name', before, name,
                                note='가공 규칙으로 만든 상품명입니다.'))
    return (name, applied, skipped)


def _check_banned(collect, cbad, upload, ubad, original_name, final_name, market,
                  *, have_words=False):
    """금지어 검사 — 사유들만 돌려준다(적용 로그는 호출자가 붙인다).

    ★ [리뷰 I1] **무엇을 기준으로 보는지가 두 금지어에서 다르다.**
      · 수집 금지어 → **원본 상품명**. 「이 단어가 있으면 아예 안 가져옵니다」(§7-1)
        이므로 소싱처가 준 이름이 기준이다.
      · 업로드 금지어 → **전송할 이름(가공 결과)**. 예전엔 원본까지 같이 봐서,
        치환표로 「병행수입 → (삭제)」 해 놓고도 그 마켓이 계속 막혔다 —
        「금지어를 치환으로 처리한다」는 정상 운영이 원천 봉쇄됐다.
    """
    out = []
    out.extend(cbad)
    out.extend(ubad)

    if not collect and not upload and not (cbad or ubad) and not have_words:
        out.append(_skip('banned_words', '', 'EMPTY_BANNED_LIST',
                         '아직 등록된 금지어가 없습니다 — 금지어 목록이 비어 있는 동안엔 '
                         '아무 단어도 걸러지지 않습니다(화면에서 금지어를 넣어 주세요).',
                         False))
        return out

    hit_c = collect_banned_hits(original_name, collect)
    if hit_c:
        # ★ [리뷰 I-6] **어느 정책의 금지어인지**까지 말한다 — 소싱처 단위 합집합이라
        #   다른 브랜드 정책의 금지어에 걸릴 수 있고, 그때 어디 가서 지워야 하는지
        #   말해 주지 않으면 사장님이 찾을 방법이 없다. 문구의 정본은 한 곳이다.
        out.append(collect_banned_skip(hit_c))
    hit_u = collect_banned_hits(final_name, upload)
    if hit_u:
        where = f'{market} 에는' if market else '해당 마켓에는'
        out.append(_skip('banned_words', 'upload_banned', 'UPLOAD_BANNED',
                         f'업로드 금지어가 등록할 상품명에 있습니다: {_word_text(hit_u)} — '
                         f'{where} 올리지 않습니다(다른 마켓은 그대로 갑니다). '
                         f'치환표로 그 말을 빼면 올라갑니다.', True))
    return out


def _build_tags(draft, cfg, banned_words):
    """태그 만들기 — (태그들, applied, skipped).

    ★ 지금은 **어느 마켓 payload 에도 실리지 않는다.** ProductDraft 에 태그 칸이 없고
      compile_* 6개 어디에도 태그 필드가 없다(전수 확인). 그 사실을 매번 말한다 —
      말하지 않으면 「태그를 넣었는데 왜 안 올라가지」가 조용한 거짓 기능이 된다.
    """
    applied, skipped = [], []
    fixed = [str(t).strip() for t in (cfg.get('fixed_tags') or []) if str(t or '').strip()]
    auto = _auto_tags(draft) if cfg.get('auto_generate') else []

    tags = _dedupe_keep_first(list(fixed) + list(auto))
    if banned_words:
        kept = [t for t in tags if not collect_banned_hits(t, banned_words)]
        if len(kept) != len(tags):
            applied.append(_applied('tags', 'fixed_tags', tags, kept,
                                    note='금지어가 든 태그를 뺐습니다(§7-11).'))
        tags = kept

    max_count = cfg.get('max_count')
    if isinstance(max_count, int) and not isinstance(max_count, bool) and max_count > 0:
        if len(tags) > max_count:
            applied.append(_applied('tags', 'max_count', tags, tags[:max_count],
                                    note=f'최대 {max_count}개까지만 씁니다.'))
            tags = tags[:max_count]

    if not tags:
        skipped.append(_skip('tags', '', 'NO_TAGS',
                             '만들 태그가 없습니다 — 고정 태그가 비어 있고 자동 생성에 '
                             '쓸 값(브랜드·카테고리·색상·소재)도 없습니다.', False))
        return (tags, applied, skipped)

    applied.append(_applied('tags', 'auto_generate', None, tags,
                            note=f'태그 {len(tags)}개를 만들었습니다.'))
    skipped.append(_skip('tags', '', 'TAGS_NOT_DELIVERED',
                         '만든 태그는 아직 **어느 마켓에도 전달되지 않습니다** — '
                         '초안에 태그 칸이 없고 마켓별 등록 코드에도 태그 필드가 '
                         '없습니다(다음 단계). 지금은 미리보기입니다.', False))
    return (tags, applied, skipped)

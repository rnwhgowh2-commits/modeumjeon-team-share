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
  하는 것 : name(상품명 조합) · brand(브랜드 표기) · banned_words(금지어) · tags(태그)

  안 하는 것 — **미구현이 아니라 다른 곳이 이미 담당하거나 범위 밖**이다.
  다음 사람이 「가공 규칙이 통째로 안 먹는다」로 오판하지 않게 여기 적어 둔다.
    · notice   §7-5  → `notice_defaults.apply_notice_defaults` 가 이미 한다(M4-3).
                       규칙의 auto_from_crawl·warn_on_missing 은 그쪽 동작과 겹친다.
    · category §7-8  → `webapp/routes/bulk/drafts.py::_mapped_category` +
                       CategoryMapRow(confirmed) 가 이미 한다. 실패=보류도 이미 있다.
    · price    §7-2  → 판매가는 마진 엔진(compute_final_price) 몫이다. 가공 사본에서
                       판매가를 만들면 「에러 없이 틀린 숫자」가 된다(금전 손실).
    · options  §7-9  → 옵션 표준화는 크롤 소유 칸(`draft_from_crawl.CRAWL_OWNED_FIELDS`)
                       을 건드려야 해서 재크롤 머지 규칙(리뷰 C1)과 함께 설계해야 한다.
    · images   §7-3  → 이미지는 게이트 뒤 CDN 재호스팅(service.py:299~)과 얽혀 있다.
    · detail   §7-4  → 상세 조립은 별도 기능(remove_detail_assets·foreign_assets).
    · shipping §7-10 / origin §7-6 / kc §7-7
                     → ProductDraft 에 이미 칸이 있고 사람이 채운 값을 쓴다. 규칙으로
                       덮으면 「저장값 불변」을 깬다 — 별도 결정이 필요하다.
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
    """드래프트의 **읽기 전용 사본** — 가공된 상품명·태그만 바꿔 보여준다.

    `notice_defaults.DraftNoticeView` 와 같은 구조다. 컴파일러는 `draft.name` 을 읽을
    뿐이라, 저장된 행을 손대지 않고 이 사본만 넘기면 「저장값은 그대로, 적용 시점에만
    가공」이 지켜진다. 쓰기는 막는다 — 실수로 여기에 값을 넣으면 DB 에 안 남고 사라진다.

    `process_tags` 는 ProductDraft 에 없는 칸이다(아래 태그 절 주석 참고).
    """

    __slots__ = ('_draft', 'name', 'process_tags')

    def __init__(self, draft, name, process_tags):
        object.__setattr__(self, '_draft', draft)
        object.__setattr__(self, 'name', name)
        # [리뷰 S3] 튜플로 얼려 둔다 — 리스트를 그대로 내주면 받은 쪽이 태그를
        # 뒤에서 고쳐도 「읽기 전용 사본」이라는 말이 거짓이 된다.
        object.__setattr__(self, 'process_tags', tuple(process_tags or ()))

    def __getattr__(self, attr):
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


def _skip(item, field, code, reason, blocking):
    return {'item': item, 'field': field, 'label': _label(item, field),
            'code': code, 'reason': reason, 'blocking': bool(blocking)}


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
    if brand_case == 'upper':
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


def _dedupe_keep_first(items):
    seen, out = set(), []
    for it in items:
        key = str(it).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(it).strip())
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

    if name == original_name and not tags:
        return (draft_like, applied, skipped)
    return (DraftProcessView(draft_like, name, tags), applied, skipped)


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
            # ★ ProductDraft 에 품번 칸이 없다(models.py:23~ 전수 확인). 조용히 빼지
            #   않고 말한다 — 다음 사람이 「규칙이 안 먹는다」로 오해하지 않게.
            skipped.append(_skip('name', 'model_no', 'NO_MODEL_NO',
                                 '품번을 담는 칸이 아직 없어 상품명에 품번을 넣지 '
                                 '못했습니다 — 조립 순서에서 품번은 빠집니다.', False))
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
    mk_max = ML.name_max_len(market)
    if mk_max:
        limits.append((mk_max, f'{market} 상한'))
    elif market:
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

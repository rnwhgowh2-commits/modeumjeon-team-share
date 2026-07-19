# -*- coding: utf-8 -*-
"""대량등록 수기 입력 — 「6 매입가·마진」 6칸의 저장 계약 (Phase 1B M2-저장).

■ 왜 라우트가 아니라 별도 모듈인가
  같은 6칸을 세 곳이 읽고 쓴다: 저장(POST /bulk/api/drafts), 수정(PUT), 계산
  (POST /bulk/api/margin-preview). 세 곳에 파싱을 복붙하면 한 곳만 고쳤을 때
  나머지가 조용히 옛 규칙으로 돈다 — 이 저장소가 가장 경계하는 유형이다.
  화면 payload 키 ↔ DB 컬럼 대응과 유효값 판정을 여기 한 곳에 둔다.

■ 세 가지 '빈 값'을 절대 뭉개지 않는다 (핵심)
    None  (키 자체가 payload 에 없음) = "이 칸을 입력받지 않았다"
    ''    (키는 있고 값이 빈 문자열)  = "「소싱처 기본값」으로 남겨뒀다"
    'none'                            = "「없음」을 명시적으로 골랐다"
  셋은 뜻이 다르다. 특히 ''와 'none' 은 계산 결과가 갈린다 — ''는 소싱처 혜택을
  그대로 쓰고, 'none' 은 그 축의 혜택을 전부 끈다. 어느 하나를 기본값으로 채우면
  나중에 "사장님이 의도적으로 비운 것인지 프로그램이 채운 것인지" 알 수 없다.
  → 여기서도, 컬럼 DEFAULT 에서도, 화면 복원에서도 폴백을 만들지 않는다.

■ 금액은 저장하지 않는다
  최종매입가·마진은 소싱처 혜택 템플릿이 바뀌면 같이 바뀌어야 하는 파생값이다.
  저장하면 옛 금액이 화면에 남아 '에러 없이 틀린 숫자'가 된다. 저장하는 건
  **사람이 고른 입력**뿐이고, 금액은 필요할 때마다 엔진이 다시 낸다.
"""
from lemouton.registration.compile_common import coerce_int, CompileError

# 화면 select 의 유효값. '' = 안 고름(소싱처 기본값), 'none' = 없음 명시.
INFLOW_CHOICES = ('', 'naver_via', 'cashback', 'none')
NAVER_PAY_CHOICES = ('', 'on', 'off')

#: payload 키 → ProductDraft 컬럼명.
#: 화면·API 는 짧은 이름(source_id)을 쓰고 모델은 충돌 없는 이름(pricing_source_id)을
#: 쓴다 — ProductDraft.source 는 '누가 채웠나'(manual/crawl)라 뜻이 전혀 다르다.
PAYLOAD_TO_COLUMN = {
    'source_id': 'pricing_source_id',
    'surface_price': 'surface_price',
    'inflow': 'pricing_inflow',
    'card_key': 'pricing_card_key',
    'naver_pay': 'pricing_naver_pay',
    'cashback_name': 'pricing_cashback_name',
}

_INT_FIELDS = {'source_id': '소싱처', 'surface_price': '표면가'}
_CHOICE_FIELDS = {
    'inflow': (INFLOW_CHOICES, '유입경로'),
    'naver_pay': (NAVER_PAY_CHOICES, '네이버페이'),
}


def _column_width(name: str):
    """ProductDraft 의 문자열 컬럼 폭을 **모델에서 읽는다**(하드코딩 금지).

    폭을 나중에 넓히면 이 검사가 자동으로 따라간다.
    """
    from lemouton.registration.models import ProductDraft
    col = ProductDraft.__table__.columns[name]
    return getattr(col.type, 'length', None)


def parse_pricing_inputs(payload: dict) -> dict:
    """payload → {컬럼명: 값}. **payload 에 있는 키만** 담아 돌려준다.

    없는 키는 결과에 아예 없다 → 호출부가 "건드리지 않음"으로 다룰 수 있다
    (수정 시 화면에 없던 칸이 NULL 로 지워지는 사고 방지).

    Raises:
        CompileError: 숫자로 못 읽는 값 / 유효하지 않은 선택지 / 컬럼 폭 초과.
    """
    out = {}
    for key, column in PAYLOAD_TO_COLUMN.items():
        if key not in payload:
            continue
        raw = payload[key]

        if key in _INT_FIELDS:
            # coerce_int: 빈칸·None → None(미입력), '15,000' → 15000, 'abc' → CompileError.
            # 0 은 그대로 0 이다 — 미입력과 다른 값이라 뭉개지 않는다.
            out[column] = coerce_int(raw, _INT_FIELDS[key])
            continue

        if raw is None:
            # JSON null = "입력받지 않음". ''(소싱처 기본값)로 바꾸지 않는다.
            out[column] = None
            continue

        val = str(raw).strip()

        if key in _CHOICE_FIELDS:
            choices, label = _CHOICE_FIELDS[key]
            if val not in choices:
                raise CompileError(f'{label} 값이 올바르지 않습니다: {val}')

        width = _column_width(column)
        if width is not None and len(val) > width:
            # 개발기(SQLite)는 길이를 무시해 조용히 통과하고 **라이브(PostgreSQL)에서만**
            # 저장이 깨진다. 그 격차를 여기서 400 으로 끌어올린다.
            raise CompileError(
                f'{key} 값이 저장 한도({width}자)를 넘습니다: {len(val)}자')

        out[column] = val
    return out


def pricing_payload(draft) -> dict:
    """저장된 드래프트 → 화면·계산이 쓰는 payload 형태 {짧은키: 값}.

    NULL 은 None 그대로 내보낸다. ''로 바꾸면 "입력받지 않음"이 "소싱처 기본값을
    골랐음"으로 둔갑한다.
    """
    return {key: getattr(draft, column, None)
            for key, column in PAYLOAD_TO_COLUMN.items()}


def merge_choice(payload: dict, draft, key: str):
    """계산에 쓸 값 하나를 고른다 — payload 에 키가 있으면 그 값, 없으면 저장값.

    "화면이 보낸 빈 문자열"과 "화면이 아예 안 보냄"을 구분하는 게 요점이다.
    전자는 사용자가 방금 「소싱처 기본값」으로 되돌린 것이므로 저장값을 덮어야 하고,
    후자(예: draft_id 만 주고 계산을 요청)는 저장값을 써야 한다.
    """
    if key in payload:
        return payload[key]
    return getattr(draft, PAYLOAD_TO_COLUMN[key], None) if draft is not None else None


__all__ = [
    'INFLOW_CHOICES', 'NAVER_PAY_CHOICES', 'PAYLOAD_TO_COLUMN',
    'parse_pricing_inputs', 'pricing_payload', 'merge_choice', 'CompileError',
]

# -*- coding: utf-8 -*-
"""상품고시정보 **기본값** 저장소 + 적용(병합) — M4-3.

왜 필요한가:
  스마트스토어는 고시정보 13~14칸이 필수인데(notice.py), 그중 대부분은 **크롤로 절대
  안 나오는 값**이다(품질보증기준·A/S책임자·소재·제조자…). 지금은 드래프트마다
  사람이 손으로 채워야 하고, 안 채우면 컴파일이 「상품고시정보 미완성」으로 거부한다.

값의 성격을 나눠 다르게 다룬다:
  · 셀러 고정값(A/S책임자·품질보증기준 등) → **전역(global) 기본값** 한 번 저장
  · 상품마다 다른 값(소재·색상·치수·제조자)   → **소싱처별(source:<id>) 기본값**

★ 폴백 금지 — 여기 있는 기본값은 전부 **사장님이 화면에서 직접 입력한 값**이다.
  프로그램이 지어낸 값은 한 글자도 넣지 않는다. 기본값이 없는 칸은 **비운 채로 두고**
  사전 점검(preflight)이 빨간불로 표시한다. (notice.py 상단 「기본값 원칙」과 같은 규율)

★ 저장값은 건드리지 않는다 — 드래프트의 notice_json 은 사장님이 저장한 그대로 남고,
  병합은 **컴파일 직전**에 만든 읽기 전용 사본에서만 일어난다. 드래프트에 미리 써 넣으면
  「사장님이 입력한 값」과 「프로그램이 채운 값」이 뭉개져 구분이 영영 불가능해진다.

우선순위: 드래프트 입력값 > 소싱처 기본값 > 전역 기본값 > (notice.py 의 네이버 공식 문구)
"""
# [2026-07-23] M4 Task 3
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from shared.db import Base
from lemouton.registration import notice as _N


def _utcnow():
    return datetime.now(timezone.utc)


# ── 저장소 ──────────────────────────────────────────────────────────────────

GLOBAL_SCOPE = 'global'
SOURCE_SCOPE_PREFIX = 'source:'


class NoticeDefault(Base):
    """고시정보 기본값 1행 = (스코프 × 고시유형).

    Alembic 없음 — 신규 테이블은 shared/db.py:init_db() 의 create_all 이 만든다.
    (app.py 가 이 모듈을 import 해야 등록된다 — CLAUDE.md 「검증」 절)

    scope:
        'global'            전역 — 셀러 고정값(A/S책임자·품질보증기준…)
        'source:<source_id>' 소싱처별 — source_id = ProductDraft.source_site
                             (= SourceCategory.source_id = 크롤 소싱처 키. 'musinsa' 등)

    values_json: {입력키: 값} — 입력키는 notice.py 가 읽는 그 키 그대로다
        (공통 7 = snake_case, 유형별 = 한 단어 소문자). 빈 값은 저장하지 않는다
        (빈 문자열을 저장하면 「설정했는데 빈 값」과 「설정 안 함」이 구분되지 않는다).
    """
    __tablename__ = 'notice_defaults'

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(64), nullable=False)
    notice_type = Column(String(32), nullable=False)
    values_json = Column(Text, nullable=False, default='{}')
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('scope', 'notice_type', name='uq_notice_defaults_scope_type'),
    )


class NoticeDefaultsError(ValueError):
    """스코프·고시유형·키가 규격에 안 맞음. 라우트가 400 으로 바꿔 보여준다."""


def source_scope(source_id) -> str:
    """소싱처 id → 스코프 문자열."""
    sid = str(source_id or '').strip()
    if not sid:
        raise NoticeDefaultsError('소싱처를 골라 주세요.')
    return SOURCE_SCOPE_PREFIX + sid


def parse_scope(scope: str):
    """스코프 문자열 → ('global', None) | ('source', source_id). 규격 위반이면 예외."""
    s = str(scope or '').strip()
    if s == GLOBAL_SCOPE:
        return (GLOBAL_SCOPE, None)
    if s.startswith(SOURCE_SCOPE_PREFIX):
        sid = s[len(SOURCE_SCOPE_PREFIX):].strip()
        if sid:
            return ('source', sid)
    raise NoticeDefaultsError(
        f"스코프는 '{GLOBAL_SCOPE}' 또는 '{SOURCE_SCOPE_PREFIX}<소싱처>' 여야 합니다. "
        f'받은 값: {scope!r}')


def check_notice_type(notice_type: str) -> str:
    nt = str(notice_type or '').strip()
    if nt not in _N.NOTICE_TYPES:
        raise NoticeDefaultsError(
            f'고시유형은 {_N.NOTICE_TYPES} 중 하나여야 합니다. 받은 값: {notice_type!r}')
    return nt


# ── 유형별 필수 칸 목록 (notice.py 를 **읽어서** 만든다 — 하드코딩 금지) ─────
#
# 화면 폼도 이 목록으로 그린다. notice.py 의 규격이 바뀌면 화면이 자동으로 따라간다.
# 라벨만 여기서 붙인다(라벨은 규격이 아니라 표시용 — 모르는 키는 키 그대로 보여준다).

_LABELS = {
    # 공통 7 (입력 snake 키 기준)
    'return_cost_reason': '반품비용 부담 주체',
    'no_refund_reason': '청약철회 제한 사유',
    'quality_assurance_standard': '교환·반품·보증 조건',
    'compensation_procedure': '환불 지연 시 지연배상금 기준',
    'trouble_shooting_contents': '소비자 피해보상·분쟁처리 기준',
    'warranty_policy': '품질보증기준',
    'after_service_director': 'A/S 책임자와 전화번호',
    # 유형별 필수
    'material': '소재',
    'color': '색상',
    'size': '치수',
    'type': '종류',
    'manufacturer': '제조자(수입자)',
    'caution': '취급 시 주의사항',
}


def field_specs(notice_type: str) -> list:
    """이 고시유형에서 **비면 등록이 막히는** 칸 목록.

    Returns: [{key, label, group('common'|'type'), has_official_default}]
        has_official_default=True → 미입력이어도 네이버 공식 문구가 들어가는 칸
        (notice.py._COMMON_DEFAULTS). 즉 사장님이 꼭 채워야 하는 칸은 False 인 것들이다.

    ★ 선택 필드(굽높이·제조연월)는 일부러 뺐다 — 상품마다 다른 값이라 「기본값」이
      성립하지 않는다(모든 상품에 같은 굽높이를 박는 셈).
    """
    nt = check_notice_type(notice_type)
    out = []
    for camel, in_key in _N._COMMON_IN_KEY.items():
        out.append({
            'key': in_key,
            'label': _LABELS.get(in_key, in_key),
            'group': 'common',
            'has_official_default': bool(_N._COMMON_DEFAULTS.get(camel)),
        })
    for key in _N._PER_TYPE_REQUIRED[nt]:
        out.append({
            'key': key,
            'label': _LABELS.get(key, key),
            'group': 'type',
            'has_official_default': False,
        })
    return out


def field_keys(notice_type: str) -> list:
    return [f['key'] for f in field_specs(notice_type)]


# ── 조회·저장 ───────────────────────────────────────────────────────────────

def _loads(raw) -> dict:
    """values_json → dict. 깨져 있어도 화면 전체를 죽이지 않는다(빈 기본값 = 아무것도 안 채움).

    자유 텍스트 컬럼이라 언제든 깨질 수 있고, 깨진 기본값은 「기본값 없음」과 같은 뜻이다
    (없는 값을 지어내지 않으므로 안전한 방향). 대신 병합 결과가 비면 preflight 가 빨간불이다.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def get_values(session, scope: str, notice_type: str) -> dict:
    """스코프 × 고시유형의 기본값 dict (없으면 {})."""
    parse_scope(scope)
    nt = check_notice_type(notice_type)
    row = (session.query(NoticeDefault)
           .filter_by(scope=str(scope).strip(), notice_type=nt).first())
    return _loads(row.values_json) if row is not None else {}


def save_values(session, scope: str, notice_type: str, values: dict) -> dict:
    """기본값 저장(upsert). 빈 칸은 저장하지 않는다 = 그 칸 기본값 해제.

    모르는 키는 거부한다 — 오타를 조용히 저장하면 「설정했는데 안 채워지는」 상태가 된다.
    커밋은 호출자(라우트) 몫.
    """
    parse_scope(scope)
    nt = check_notice_type(notice_type)
    if not isinstance(values, dict):
        raise NoticeDefaultsError('values 는 객체(딕셔너리)여야 합니다.')

    allowed = set(field_keys(nt))
    unknown = sorted(k for k in values if k not in allowed)
    if unknown:
        raise NoticeDefaultsError(
            f'{nt} 고시에 없는 칸입니다: {unknown} — 쓸 수 있는 칸: {sorted(allowed)}')

    clean = {}
    for k, v in values.items():
        text = _N._text(v)
        if text:
            clean[k] = text

    row = (session.query(NoticeDefault)
           .filter_by(scope=str(scope).strip(), notice_type=nt).first())
    if row is None:
        row = NoticeDefault(scope=str(scope).strip(), notice_type=nt)
        session.add(row)
    row.values_json = json.dumps(clean, ensure_ascii=False)
    row.updated_at = _utcnow()
    return clean


def known_source_ids(session) -> list:
    """기본값 스코프로 고를 수 있는 소싱처 id 목록 (우리 DB 가 실제로 아는 것만).

    없는 소싱처를 지어내지 않는다 — 소싱처 카테고리 사전·맵핑표·드래프트·이미 저장된
    기본값에서 실제로 관측된 id 들의 합집합.
    """
    from lemouton.registration.models import CategoryMapRow, ProductDraft, SourceCategory

    ids = set()
    for model, col in ((SourceCategory, SourceCategory.source_id),
                       (CategoryMapRow, CategoryMapRow.source_id),
                       (ProductDraft, ProductDraft.source_site)):
        for (v,) in session.query(col).distinct().all():
            if v:
                ids.add(str(v))
    for (scope,) in session.query(NoticeDefault.scope).distinct().all():
        if scope and scope.startswith(SOURCE_SCOPE_PREFIX):
            sid = scope[len(SOURCE_SCOPE_PREFIX):].strip()
            if sid:
                ids.add(sid)
    return sorted(ids)


# ── 병합(적용) ──────────────────────────────────────────────────────────────

def merge_values(notice_type: str, draft_values: dict, *,
                 source_values: dict = None, source_id=None,
                 global_values: dict = None):
    """드래프트 입력값 + 기본값 → (병합본, filled_from).

    우선순위: 드래프트 입력값 > 소싱처 기본값 > 전역 기본값.
      · 드래프트에 값이 있으면 절대 덮지 않는다.
      · 드래프트가 비었고(또는 그 칸이 없고) 기본값도 없으면 **비운 채로 둔다** —
        여기서 지어내면 실제 판매 상품에 가짜 고시가 올라간다(폴백 금지).

    ★ notice.py 의 「일부러 빈칸 ≠ 미입력」 규율과의 관계: 여기서 채우는 값은 전부
      사장님이 저장한 것이라 「프로그램이 지어낸 문구로 덮는」 사고가 아니다. 고시 필수칸을
      일부러 비워 두는 것은 뜻이 없다(비우면 어차피 등록이 거부된다) → 빈 칸도 채운다.
      네이버 공식 문구 기본값(notice.py._COMMON_DEFAULTS)은 여전히 「키가 아예 없을 때」만
      적용되므로, 그 규율은 그대로 남는다.

    Returns:
        (merged: dict, filled_from: {키: 'source:<id>'|'global'})
    """
    nt = check_notice_type(notice_type)
    merged = dict(draft_values or {})
    filled_from = {}

    tiers = []
    if source_values:
        tiers.append((source_scope(source_id) if source_id else 'source', source_values))
    if global_values:
        tiers.append((GLOBAL_SCOPE, global_values))

    for key in field_keys(nt):
        if _N._text(merged.get(key)):
            continue
        for scope_name, values in tiers:
            val = _N._text((values or {}).get(key))
            if val:
                merged[key] = val
                filled_from[key] = scope_name
                break
    return merged, filled_from


def resolve_for_draft(session, draft):
    """드래프트 1건에 적용될 (소싱처 기본값, 전역 기본값, 소싱처 id)."""
    nt = str(getattr(draft, 'notice_type', '') or '')
    if nt not in _N.NOTICE_TYPES:
        # 모르는 유형은 notice.py 가 UnknownNoticeType 으로 막는 게 맞다 — 여기선 아무것도 안 한다.
        return ({}, {}, None)
    sid = str(getattr(draft, 'source_site', '') or '').strip() or None
    src = get_values(session, source_scope(sid), nt) if sid else {}
    glb = get_values(session, GLOBAL_SCOPE, nt)
    return (src, glb, sid)


class DraftNoticeView:
    """드래프트의 **읽기 전용 사본** — notice_json 만 병합본으로 바꿔 보여준다.

    컴파일러(compile_smartstore)는 draft.notice_type·notice_json 을 읽을 뿐이라, 저장된
    행을 손대지 않고 이 사본만 넘기면 「저장값은 그대로, 적용 시점에만 병합」이 지켜진다.
    쓰기는 막는다 — 실수로 이 사본에 값을 넣으면 DB 에 안 남고 조용히 사라진다.
    """
    __slots__ = ('_draft', 'notice_json')

    def __init__(self, draft, notice_json: str):
        object.__setattr__(self, '_draft', draft)
        object.__setattr__(self, 'notice_json', notice_json)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_draft'), name)

    def __setattr__(self, name, value):
        raise AttributeError(
            'DraftNoticeView 는 읽기 전용 사본입니다 — 원본 드래프트에 저장하세요.')

    def __repr__(self):
        return f'<DraftNoticeView draft={object.__getattribute__(self, "_draft")!r}>'


def apply_notice_defaults(session, draft):
    """컴파일에 넘길 드래프트(사본) + 어느 칸이 어디서 채워졌는지.

    Returns:
        (draft_or_view, filled_from)  — 채운 게 없으면 원본 draft 를 그대로 돌려준다.

    깨진 notice_json 은 여기서 손대지 않는다 — 컴파일러의 loads_json 이 사용자에게
    「고시 JSON 이 깨졌다」고 말하게 두는 편이 낫다(여기서 {} 로 덮으면 원인이 숨는다).
    """
    raw = getattr(draft, 'notice_json', None)
    try:
        parsed = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return (draft, {})
    if not isinstance(parsed, dict):
        return (draft, {})

    src, glb, sid = resolve_for_draft(session, draft)
    if not src and not glb:
        return (draft, {})

    merged, filled_from = merge_values(draft.notice_type, parsed,
                                       source_values=src, source_id=sid,
                                       global_values=glb)
    if not filled_from:
        return (draft, {})
    return (DraftNoticeView(draft, json.dumps(merged, ensure_ascii=False)), filled_from)

# -*- coding: utf-8 -*-
"""축 매핑 저장소 — 「우리 축 값 ↔ 소싱처 표기」를 소싱처 단위로 기억한다.

설계: docs/사전점검_옵션URL매핑_설계.md §15 (축 맞추기 확정안), §16 1단계

왜 필요한가
  소싱처는 `BLACK`, 우리는 `검정` 이라 부른다. 조합(색×사이즈)마다 맞추면 6색×10사이즈
  = 60번이지만, **축**만 맞추면 색 6 + 사이즈 10 = 16번이고, 한 번 맞춘 것은 그 소싱처의
  다음 상품에서 다시 묻지 않는다(0번). 이 표가 그 「다시 묻지 않음」을 담는 곳이다.

규칙 (사장님 확정 2026-08-02)
  · 저장 단위 = **소싱처**. 무신사에서 맞춘 것이 롯데온에 새지 않는다.
  · 축 이름은 **고정이 아니다**. 매트릭스에서 지은 이름 그대로(색상·사이즈·모델·재질…).
  · **1:1** — 우리 값 하나에 소싱처 값 하나. 두 우리 값이 같은 소싱처 값을 쓰면
    그 소싱처 옵션의 재고가 두 배로 계산되어 초과 판매가 난다 → `AliasConflict` 로 막는다.
  · 되돌리기(`clear_alias`)는 한 번에. 되돌리면 그 소싱처 값이 풀려 다른 값이 쓸 수 있다.
  · `origin` 으로 「사장님이 고른 것(manual)」과 「자동이 고른 것(auto)」을 구분한다.
    나중에 값이 이상할 때 자동 탓인지 수기 탓인지 가리기 위한 것 (시안 v6 파란 「수기」 표시).

비교 기준
  저장은 **사장님이 본 표기 그대로** 하고, 비교(중복·역방향 조회)만 정규화형으로 한다.
  정규화 = `shared.sku_format.normalize_label` (소문자 + 공백·`-`·`_`·`.` 제거).
  화면에는 원문이 보여야 하므로 원문을 버리지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, Column, DateTime, Index, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Session

from shared.db import Base
from shared.sku_format import normalize_label


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AliasConflict(Exception):
    """이미 다른 우리 값이 그 소싱처 표기를 쓰고 있다 (1:1 위반).

    `holder` = 그 표기를 붙잡고 있는 우리 값. 화면이 「누구한테서 빼앗을지」를
    말하려면 이 값이 필요하다(2026-08-12).

    🔴 [2026-08-13 감사] `holders` 도 같이 준다 — 이 표엔 DB 유일 제약이 없어
       같은 표기를 **두 줄 이상**이 붙잡고 있을 수 있다. 하나만 놓아 주면 빼앗기가
       다시 막히고, 그 두 번째 예외가 `except` 안에서 터져 **500** 이 됐다(실측).
    """

    def __init__(self, message: str, holder: str = '', holders=None):
        super().__init__(message)
        self.holder = holder
        self.holders = list(holders or ([holder] if holder else []))


class SourceAxisAlias(Base):
    """(소싱처, 축 이름, 우리 값) → 소싱처 표기."""

    __tablename__ = "source_axis_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String(32), nullable=False, index=True)   # musinsa · lotteon …
    axis_name = Column(String(64), nullable=False)                # 색상 · 사이즈 · 모델 …
    our_value = Column(String(128), nullable=False)               # 검정
    source_value = Column(String(255), nullable=False, default="")   # BLACK (원문 보존)
    source_value_norm = Column(String(255), nullable=False, default="")  # black (비교용)
    origin = Column(String(8), nullable=False, default="manual")  # manual | auto
    # [2026-08-02] 「이 소싱처엔 이 값이 없다」 — 사장님이 **정한** 것.
    #   이게 없으면 사전이 틀리게 붙였을 때 거부할 방법이 없다(라이브에서 잡힌 결함).
    #   True 면 source_value 는 빈 값이고, 1:1 잠금에서도 표기를 차지하지 않는다.
    is_absent = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        # 우리 값 하나 = 소싱처 값 하나
        UniqueConstraint("source_key", "axis_name", "our_value",
                         name="uq_axis_alias_our"),
        # 잠금·역방향 조회 (같은 소싱처 표기를 누가 쓰나)
        Index("ix_axis_alias_srcval", "source_key", "axis_name", "source_value_norm"),
    )


# ── 내부 ────────────────────────────────────────────────────────────────

# 🔴 [2026-08-05 성능] 판정 경로(is_absent·resolve)를 **세션 캐시**로 돌린다.
#   왜: match_one 이 비교 한 번마다 이 둘을 각각 쿼리해서, 매트릭스 조립이
#   옵션 102개 × 소싱처 URL × 후보 수십 × 색·사이즈 2축 = **수만~수십만 쿼리**가
#   됐다. 로컬 SQLite 는 티가 안 나는데 라이브(Supabase 원격, 왕복 수 ms)에선
#   구성 하나 조립에 **12분**이 걸렸다(2026-08-05 send job 4 실측 713초).
#   (소싱처, 축) 한 쌍의 전체 행을 1번에 읽어 세션에 담으면 쌍당 1쿼리로 끝난다.
#   · 쓰기(set_alias·set_absent·clear_alias)는 그 쌍 캐시를 버린다 — 같은 세션
#     안에서 쓰고 바로 읽어도 어긋나지 않는다.
#   · 다른 세션이 고친 것은 이 세션 캐시에 안 보인다 — 웹 요청 세션은 요청마다
#     새로 열리니 문제 없고, 전송 작업(장수명 세션)은 「시작 시점의 맞춤」으로
#     일관 판정하는 것이 오히려 안전하다(도중에 바뀌면 앞뒤 옵션 판정이 갈린다).

def _pair_cache(session: Session, source_key: str, axis_name: str) -> dict:
    cache = session.info.setdefault("_axis_alias_pairs", {})
    key = (source_key, axis_name)
    got = cache.get(key)
    if got is None:
        rows = (session.query(SourceAxisAlias)
                .filter_by(source_key=source_key, axis_name=axis_name).all())
        got = {
            "absent": {r.our_value for r in rows if r.is_absent},
            "by_norm": {r.source_value_norm: r.our_value
                        for r in rows if not r.is_absent and r.source_value_norm},
        }
        cache[key] = got
    return got


def _drop_pair_cache(session: Session, source_key: str,
                     axis_name: str | None = None) -> None:
    cache = session.info.get("_axis_alias_pairs")
    if not cache:
        return
    if axis_name is None:
        for k in [k for k in cache if k[0] == source_key]:
            cache.pop(k, None)
    else:
        cache.pop((source_key, axis_name), None)


def _clean(name: str, value) -> str:
    v = (value or "").strip() if isinstance(value, str) else ""
    if not v:
        raise ValueError(f"{name} 이(가) 비었습니다.")
    return v


def _release_confirm(session: Session, source_key: str) -> None:
    """맞춤이 바뀌면 그 소싱처 확인 도장을 푼다 (import 는 순환 방지로 지연)."""
    try:
        from .axis_confirm import release_source
        release_source(session, source_key)
    except Exception:
        pass


def _row(session: Session, source_key: str, axis_name: str, our_value: str):
    return (session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, our_value=our_value)
            .first())


# ── 쓰기 ────────────────────────────────────────────────────────────────

def set_alias(session: Session, *, source_key: str, axis_name: str,
              our_value: str, source_value: str,
              origin: str = "manual") -> SourceAxisAlias:
    """축 한 줄을 맞춘다. 같은 우리 값이면 덮어쓴다(행이 늘지 않는다).

    Raises:
        ValueError: 넷 중 하나라도 비었을 때.
        AliasConflict: 그 소싱처 표기를 **다른** 우리 값이 이미 쓰고 있을 때.
    """
    source_key = _clean("소싱처", source_key)
    axis_name = _clean("축 이름", axis_name)
    our_value = _clean("우리 값", our_value)
    source_value = _clean("소싱처 표기", source_value)
    norm = normalize_label(source_value)
    if not norm:
        raise ValueError("소싱처 표기 이(가) 비었습니다.")
    if origin not in ("manual", "auto"):
        origin = "manual"

    # 1:1 — 같은 표기를 다른 우리 값이 쓰고 있으면 막는다(재고 이중계상 차단)
    # 🔴 `.first()` 가 아니라 **전부** 본다 — 이 표엔 DB 유일 제약이 없어 같은 표기를
    #   두 줄 이상이 붙잡고 있을 수 있다. 하나만 알려 주면 빼앗기가 다시 막힌다.
    others = [r for r in session.query(SourceAxisAlias)
              .filter_by(source_key=source_key, axis_name=axis_name,
                         source_value_norm=norm, is_absent=False).all()
              if r.our_value != our_value]
    if others:
        names = [r.our_value for r in others]
        raise AliasConflict(
            f"「{source_value}」 은(는) 이미 「{'」·「'.join(names)}」 이(가) 쓰고 있습니다. "
            f"먼저 그 줄에서 놓아야 합니다.", holder=names[0], holders=names)

    row = _row(session, source_key, axis_name, our_value)
    if row is None:
        row = SourceAxisAlias(source_key=source_key, axis_name=axis_name,
                              our_value=our_value)
        session.add(row)
    row.source_value = source_value
    row.source_value_norm = norm
    row.origin = origin
    row.is_absent = False
    # [2026-08-02] 맞춤이 바뀌면 그 소싱처의 「확인 도장」을 푼다 — 안 그러면
    #   「확인했다」가 옛 상태를 가리켜 바뀐 값이 확인받은 것처럼 보인다.
    _release_confirm(session, source_key)
    _drop_pair_cache(session, source_key, axis_name)   # 같은 세션에서 바로 읽어도 새 값
    session.flush()
    return row


def set_absent(session: Session, *, source_key: str, axis_name: str,
               our_value: str) -> SourceAxisAlias:
    """「이 소싱처엔 이 값이 없다」고 정한다.

    사전이 틀리게 붙였을 때 **거부하는 유일한 방법**이다. 이걸 정해 두면
    `match_one` 이 그 우리 값에는 어떤 표기도 안 붙인다(사전보다 우선).
    되돌리려면 `clear_alias` — 그러면 다시 사전에 맡긴다.
    """
    source_key = _clean("소싱처", source_key)
    axis_name = _clean("축 이름", axis_name)
    our_value = _clean("우리 값", our_value)
    row = _row(session, source_key, axis_name, our_value)
    if row is None:
        row = SourceAxisAlias(source_key=source_key, axis_name=axis_name,
                              our_value=our_value)
        session.add(row)
    row.source_value = ""
    row.source_value_norm = ""      # 빈 값 — 1:1 잠금에서 표기를 차지하지 않는다
    row.origin = "manual"
    row.is_absent = True
    _release_confirm(session, source_key)
    _drop_pair_cache(session, source_key, axis_name)
    session.flush()
    return row


def clear_alias(session: Session, source_key: str, axis_name: str,
                our_value: str) -> bool:
    """맞춘 것을 되돌린다. 지웠으면 True, 원래 없었으면 False."""
    row = _row(session, source_key, axis_name, our_value)
    if row is None:
        return False
    session.delete(row)
    _release_confirm(session, source_key)
    _drop_pair_cache(session, source_key, axis_name)
    session.flush()
    return True


# ── 읽기 ────────────────────────────────────────────────────────────────

def get_map(session: Session, source_key: str, axis_name: str) -> dict[str, str]:
    """{우리 값: 소싱처 표기} — 화면 드롭다운의 현재 선택값."""
    return {r.our_value: r.source_value
            for r in session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, is_absent=False).all()}


def taken_values(session: Session, source_key: str, axis_name: str) -> dict[str, str]:
    """{소싱처 표기: 그것을 쓰는 우리 값} — 드롭다운 회색 잠금 표시용."""
    return {r.source_value: r.our_value
            for r in session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, is_absent=False).all()}


def resolve(session: Session, source_key: str, axis_name: str,
            source_value: str) -> str | None:
    """소싱처 표기 → 우리 값. 못 찾으면 None. (대소문자·띄어쓰기 무시)

    판정 경로라 세션 캐시(_pair_cache)를 쓴다 — 행마다 쿼리하면 라이브 조립이
    12분이 된다(위 캐시 주석). 결과는 행 단위 쿼리와 동일하다.
    """
    norm = normalize_label(source_value)
    if not norm:
        return None
    return _pair_cache(session, source_key, axis_name)["by_norm"].get(norm)


def list_aliases(session: Session, source_key: str,
                 axis_name: str | None = None) -> list[dict]:
    """화면 표시용 목록. axis_name 을 주면 그 축만."""
    q = session.query(SourceAxisAlias).filter_by(source_key=source_key)
    if axis_name:
        q = q.filter_by(axis_name=axis_name)
    rows = q.order_by(SourceAxisAlias.axis_name, SourceAxisAlias.our_value).all()
    return [{
        "id": r.id,
        "source_key": r.source_key,
        "axis_name": r.axis_name,
        "our_value": r.our_value,
        "source_value": r.source_value,
        "origin": r.origin,
        "absent": bool(r.is_absent),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in rows]


def absent_values(session: Session, source_key: str, axis_name: str) -> set[str]:
    """「이 소싱처엔 없다」고 정해 둔 우리 값들."""
    return {r.our_value for r in session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, is_absent=True).all()}


def is_absent(session: Session, source_key: str, axis_name: str, our_value: str) -> bool:
    """판정 경로 — 세션 캐시(_pair_cache)를 쓴다. 결과는 행 단위 쿼리와 동일."""
    return (our_value or "").strip() in _pair_cache(session, source_key, axis_name)["absent"]


def users_of(session: Session, axis_name: str, our_value: str) -> list[str]:
    """그 축 값을 **실제로 쓰고 있는** 매트릭스 코드들. 비었으면 「유령」이다.

    [2026-08-12] 왜 필요한가
      이 표는 **소싱처 전역 사전**이라 매트릭스에 매이지 않는다(모듈 독스트링).
      그래서 매트릭스를 지우거나 만들다 취소해도 alias 행은 그대로 남는다
      (`optgen.api_delete_option_box` 는 `models.model_code` FK 를 가진 표만 훑는데
       `source_axis_aliases` 에는 그 FK 가 없다).
      남은 행이 소싱처 표기를 붙잡고 있으면 다시 맞추려 할 때 1:1 잠금에 걸리는데,
      화면은 **지금 매트릭스의 축 값 줄만** 그리므로 그 유령은 화면에 안 나타나
      **놓아줄 방법이 없다.** 「먼저 그 줄에서 놓아야 합니다」가 가리킬 줄이 없다.
      → 사장님이 실제로 막히신 자리다(노션 옵션 c).

    판정은 축 설계(`BundleOptionStep.values_json`)를 파이썬에서 읽어 한다.
    🔴 `LIKE '%…%'` 로는 안 된다 — JSON 이스케이프 때문에 틀린다.
    """
    import json as _json

    from .models import BundleOptionStep

    want = (our_value or '').strip()
    if not want:
        return []
    out: list[str] = []
    for code, raw in (session.query(BundleOptionStep.model_code,
                                    BundleOptionStep.values_json)
                      .filter(BundleOptionStep.axis_name == axis_name).all()):
        try:
            vals = _json.loads(raw or '[]')
        except (ValueError, TypeError):
            continue
        if any(str(v).strip() == want for v in vals) and code not in out:
            out.append(code)
    return out

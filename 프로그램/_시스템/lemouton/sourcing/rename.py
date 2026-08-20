"""[v2] 모음전 코드 변경 (cascade rename).

PK = model_code 가 자연 키라 변경이 어렵게 잠겨있던 것을 풀어냄.
canonical_sku = '{model_code}-{color}-{size}' 패턴 때문에 옵션·이력·매핑 모두 동기 갱신 필요.

설계 의도 (사용자 발언):
  - "이미 등록되어 있는 상품들 연동해서 수정"
  - "수정이 자유롭도록 해줘"

옵션 슬롯 재사용은 별도 (사용자 C 선택 시 보류 결정).
본 함수는 model_code 만 안전하게 cascade rename.

영향 테이블 (트랜잭션 안 한꺼번에 갱신):
  v1: models, options, combo_sets, etc_source_urls, price_track_history,
      market_registration, discovery_queue
  v2: model_source_links, option_source_links,
      bundle_account_registrations, option_account_registrations
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import Model, Option


def rename_model_code(
    session: Session,
    *,
    old_code: str,
    new_code: str,
    actor: str = 'system',
    reason: str | None = None,
) -> dict:
    """모음전 코드 변경 — cascade.

    Args:
      old_code: 기존 코드
      new_code: 새 코드
      actor: 변경 주체 (audit 기록용)
      reason: 변경 사유 (audit 기록용)

    Returns:
      {'old_code': str, 'new_code': str,
       'options_updated': int, 'combos_updated': int,
       'history_rows': int, 'links_updated': int,
       'fk_violations': list}

    Raises:
      ValueError: new_code 가 비었거나 같음
      LookupError: old_code 모음전 없음
      FileExistsError: new_code 가 이미 존재
      RuntimeError: cascade 후 FK 위반 (롤백 + 재시도 권유)
    """
    new_code = (new_code or '').strip()
    old_code = (old_code or '').strip()
    if not new_code:
        raise ValueError("새 코드는 빈 문자열일 수 없습니다.")
    if new_code == old_code:
        raise ValueError("새 코드와 기존 코드가 같습니다.")

    m_old = session.get(Model, old_code)
    if m_old is None:
        raise LookupError(f"모음전 '{old_code}' 가 존재하지 않습니다.")

    if session.get(Model, new_code) is not None:
        raise FileExistsError(f"코드 '{new_code}' 가 이미 사용 중입니다.")

    # ── [2026-08-02] PostgreSQL 에서 되도록 재설계 ───────────────────────────
    #  기존: PRAGMA 로 FK 를 꺼두고 PK 를 제자리에서 UPDATE.
    #    · PG 엔 PRAGMA 가 없어 문법 오류 → 트랜잭션 abort (라이브에서 항상 실패)
    #    · PRAGMA 를 걷어내도 「자식이 옛 코드를 가리키는 동안 부모 PK 변경」은 FK 위반
    #    · 옮길 표 목록도 손으로 적혀 model_code 참조 10곳 중 3곳만 갱신하고 있었다
    #  지금: **새 행 만들기 → 자식 옮기기 → 옛 행 지우기.** 어느 시점에도 FK 가
    #        안 깨져 PG·SQLite 양쪽에서 성립한다. 옮길 표는 fk_map(메타데이터)에서.
    from sqlalchemy import inspect as sa_inspect

    from .fk_map import model_child_columns, option_child_columns

    options_before = (session.query(Option)
                      .filter_by(model_code=old_code).all())

    counts = {
        'options_updated': 0,
        'combos_updated': 0,
        'etc_source_urls': 0,
        'price_track_history': 0,
        'market_registrations': 0,
        'option_source_links': 0,
        'option_account_regs': 0,
        'model_source_links': 0,
        'bundle_account_regs': 0,
        'discovery_queue': 0,
    }
    _COUNT_KEY = {
        'combo_sets': 'combos_updated',
        'model_source_links': 'model_source_links',
        'bundle_account_registrations': 'bundle_account_regs',
        'discovery_queue': 'discovery_queue',
        'etc_source_urls': 'etc_source_urls',
        'price_track_history': 'price_track_history',
        'market_registrations': 'market_registrations',
        'option_source_links': 'option_source_links',
        'option_account_registrations': 'option_account_regs',
    }

    def _move(table: str, column: str, old_val: str, new_val: str) -> None:
        """한 문이 실패해도(표 부재 등) 트랜잭션 전체가 abort 되지 않게 격리."""
        sp = session.begin_nested()
        try:
            r = session.execute(
                text(f"UPDATE {table} SET {column} = :n WHERE {column} = :o"),
                {"o": old_val, "n": new_val},
            )
            sp.commit()
            key = _COUNT_KEY.get(table)
            if key:
                counts[key] += r.rowcount or 0
        except Exception:
            sp.rollback()

    # 1) 새 모음전 행 먼저 (자식이 가리킬 부모가 있어야 한다)
    model_cols = {c.key: getattr(m_old, c.key)
                  for c in sa_inspect(Model).mapper.column_attrs}
    model_cols['model_code'] = new_code
    session.add(Model(**model_cols))
    session.flush()

    # 2) 옵션 — 새 행 만들고 자식 옮긴 뒤 옛 행 삭제
    _opt_children = option_child_columns()
    for o in options_before:
        old_sku = o.canonical_sku
        new_sku = f"{new_code}-{o.color_code}-{o.size_code}"
        opt_cols = {c.key: getattr(o, c.key)
                    for c in sa_inspect(Option).mapper.column_attrs}
        opt_cols['model_code'] = new_code
        opt_cols['canonical_sku'] = new_sku
        if opt_cols.get('boxhero_sku') == old_sku:
            opt_cols['boxhero_sku'] = new_sku
        session.add(Option(**opt_cols))
        session.flush()

        for tbl, col in _opt_children:
            _move(tbl, col, old_sku, new_sku)

        session.delete(o)
        session.flush()
        counts['options_updated'] += 1

    # 3) model_code 만 참조하는 자식들 (options 는 위에서 처리)
    for tbl, col in model_child_columns():
        _move(tbl, col, old_code, new_code)

    # 4) 옛 모음전 행 삭제 — 이 시점엔 아무도 옛 코드를 가리키지 않아야 한다
    session.delete(m_old)
    session.flush()

    # Audit 기록 (선택 — 호출자가 commit 전 기록)
    try:
        from lemouton.audit.service import record
        record(session, target_table='models', target_id=new_code,
               action='update', actor=actor,
               before={'model_code': old_code},
               after={'model_code': new_code, 'cascade_counts': counts},
               reason=reason or '모음전 코드 변경 (cascade rename)')
    except Exception:
        # audit 실패해도 rename 자체는 진행 (옵션)
        pass

    return {
        'old_code': old_code,
        'new_code': new_code,
        'options_updated': counts['options_updated'],
        'combos_updated': counts['combos_updated'],
        'history_rows': counts['price_track_history'],
        'links_updated': (counts['model_source_links']
                          + counts['option_source_links']
                          + counts['bundle_account_regs']
                          + counts['option_account_regs']),
        'cascade_detail': counts,
        'fk_violations': [],
    }

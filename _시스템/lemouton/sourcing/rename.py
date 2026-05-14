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

    # 자식 행 개수 (보고용)
    options_before = (session.query(Option)
                      .filter_by(model_code=old_code).all())
    options_count = len(options_before)

    # SQLite FK 제약 우회 — PRAGMA 로 일시적 OFF
    # rename 시작 전 baseline 캡처 (무관한 leftover violation 무시 위해)
    baseline_violations = set(
        tuple(row) for row in
        session.execute(text("PRAGMA foreign_key_check")).fetchall()
    )
    session.execute(text("PRAGMA foreign_keys=OFF"))

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

    # SKU prefix 매핑: '{old_code}-' → '{new_code}-'
    for o in options_before:
        old_sku = o.canonical_sku
        new_sku = f"{new_code}-{o.color_code}-{o.size_code}"

        # canonical_sku 참조하는 모든 자식 행 cascade
        for table_name in ('etc_source_urls', 'price_track_history',
                           'market_registrations',
                           'option_source_links',
                           'option_account_registrations'):
            r = session.execute(
                text(f"UPDATE {table_name} "
                     f"SET canonical_sku = :n WHERE canonical_sku = :o"),
                {"o": old_sku, "n": new_sku},
            )
            key_map = {
                'etc_source_urls': 'etc_source_urls',
                'price_track_history': 'price_track_history',
                'market_registrations': 'market_registrations',
                'option_source_links': 'option_source_links',
                'option_account_registrations': 'option_account_regs',
            }
            counts[key_map[table_name]] += r.rowcount or 0

        # options 행 자체 갱신 (PK + FK 동시)
        session.execute(
            text("UPDATE options "
                 "SET model_code = :nc, canonical_sku = :ns "
                 "WHERE canonical_sku = :os"),
            {"os": old_sku, "nc": new_code, "ns": new_sku},
        )
        counts['options_updated'] += 1

    # model_code 만 참조하는 자식들
    for table_name in ('combo_sets', 'model_source_links',
                       'bundle_account_registrations'):
        r = session.execute(
            text(f"UPDATE {table_name} "
                 f"SET model_code = :n WHERE model_code = :o"),
            {"o": old_code, "n": new_code},
        )
        key_map = {
            'combo_sets': 'combos_updated',
            'model_source_links': 'model_source_links',
            'bundle_account_registrations': 'bundle_account_regs',
        }
        counts[key_map[table_name]] = r.rowcount or 0

    # discovery_queue 텍스트 참조
    r = session.execute(
        text("UPDATE discovery_queue "
             "SET suggested_model_code = :n "
             "WHERE suggested_model_code = :o"),
        {"o": old_code, "n": new_code},
    )
    counts['discovery_queue'] = r.rowcount or 0

    # 마지막으로 부모 PK 변경
    session.execute(
        text("UPDATE models SET model_code = :n WHERE model_code = :o"),
        {"o": old_code, "n": new_code},
    )

    # FK 무결성 재확인 — rename 으로 새로 생긴 violation 만 catch
    session.execute(text("PRAGMA foreign_keys=ON"))
    after = set(
        tuple(row) for row in
        session.execute(text("PRAGMA foreign_key_check")).fetchall()
    )
    new_violations = after - baseline_violations
    if new_violations:
        session.rollback()
        raise RuntimeError(
            f"FK 무결성 위반 — 롤백됨. 위반: {sorted(new_violations)}"
        )

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

"""자식 행 지도 — **손으로 적지 않고** metadata 의 FK 선언에서 뽑는다.

[2026-08-02] 삭제·이름변경 코드가 저마다 "지울/바꿀 표"를 손으로 적고 있었고,
실제로 뒤처져 있었다:
  · 옵션 삭제  — 4개 누락 (matrix_option_members·set_options·option_price_config·
                option_source_urls). 앞의 둘은 ondelete 가 없어 삭제 자체가 막힌다.
  · 모음전 코드 변경 — model_code 를 가리키는 표 10개 중 3개만 갱신하고 있었다.

🔴 로컬 SQLite 는 FK 를 느슨하게 봐서 이 부류가 테스트를 통과한다. 라이브
   PostgreSQL 만 거부한다. 그래서 목록을 사람이 관리하지 않는다 — 새 표가 FK 를
   걸고 생기면 아무 데도 손대지 않아도 자동으로 포함된다.
"""
from __future__ import annotations

# FK 를 선언하지 않아 metadata 로는 잡히지 않는 참조 (표, 칸)
_OPTION_EXTRA: tuple[tuple[str, str], ...] = (
    ('price_track_history', 'canonical_sku'),
    ('market_registrations', 'canonical_sku'),
    ('option_account_registrations', 'canonical_sku'),
    ('option_benefit_overrides', 'canonical_sku'),
    ('option_product_links', 'option_canonical_sku'),
    ('option_product_links', 'product_canonical_sku'),
)

_MODEL_EXTRA: tuple[tuple[str, str], ...] = (
    ('bundle_account_registrations', 'model_code'),
    ('discovery_queue', 'suggested_model_code'),   # 텍스트 참조 (FK 아님)
)


def child_columns(target: str, extra: tuple[tuple[str, str], ...] = ()) -> list[tuple[str, str]]:
    """`target`(예: 'options.canonical_sku')을 가리키는 (표, 칸) 전부."""
    from shared.db import Base
    cols: set[tuple[str, str]] = {
        (t.name, c.name)
        for t in Base.metadata.sorted_tables
        for c in t.columns
        for fk in c.foreign_keys
        if fk.target_fullname == target
    }
    cols.update(extra)
    return sorted(cols)


def option_child_columns() -> list[tuple[str, str]]:
    """옵션(options.canonical_sku)을 가리키는 (표, 칸) 전부."""
    return child_columns('options.canonical_sku', _OPTION_EXTRA)


def model_child_columns(*, include_options: bool = False) -> list[tuple[str, str]]:
    """모음전(models.model_code)을 가리키는 (표, 칸) 전부.

    options 는 canonical_sku 까지 함께 바뀌어 따로 다뤄야 하므로 기본 제외.
    """
    cols = child_columns('models.model_code', _MODEL_EXTRA)
    if not include_options:
        cols = [(t, c) for t, c in cols if t != 'options']
    return cols

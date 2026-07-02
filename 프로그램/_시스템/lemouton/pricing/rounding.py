"""금액 라운딩 헬퍼."""


def round_to_unit(value: int, unit: int) -> int:
    """value를 unit 단위로 **버림(floor)**. unit<=0이면 그대로.

    [2026-07-02] 반올림→버림 변경. 사용자 규칙: 금액은 백원 단위까지만 표기,
    그 이하는 버림(예: 107,355 → 107,300). rounding_unit 기본 100.
    """
    if unit <= 0:
        return value
    return (int(value) // unit) * unit

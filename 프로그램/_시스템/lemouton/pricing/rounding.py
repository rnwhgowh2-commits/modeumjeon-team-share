"""반올림 헬퍼."""


def round_to_unit(value: int, unit: int) -> int:
    """value를 unit 단위로 반올림. unit<=0이면 그대로."""
    if unit <= 0:
        return value
    half = unit // 2
    return ((value + half) // unit) * unit

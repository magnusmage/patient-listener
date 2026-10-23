"""Workbook D-16 spelling similarity, implemented by RapidFuzz."""
from rapidfuzz.fuzz import ratio as _ratio


def ratio(a: str, b: str) -> float:
    """Normalized Indel similarity in [0, 100]; callers own normalization."""
    return _ratio(a, b)

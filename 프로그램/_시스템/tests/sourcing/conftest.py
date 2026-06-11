"""tests/sourcing 공용 pytest fixture."""
import pathlib
import pytest

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def html_of():
    def _load(key):
        return (FIX / f"{key}_sample.html").read_text(encoding="utf-8")
    return _load

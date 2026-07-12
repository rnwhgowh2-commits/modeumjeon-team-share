# -*- coding: utf-8 -*-
"""MarginAnalysis 모델 — 컬럼 + Base 등록 + app.py import."""
from shared.db import Base


def test_model_registered_on_base():
    from lemouton.margin.models import MarginAnalysis  # noqa: F401
    assert "margin_analyses" in Base.metadata.tables


def test_columns():
    from lemouton.margin.models import MarginAnalysis
    cols = {c.name for c in MarginAnalysis.__table__.columns}
    assert cols == {
        "id", "created_at", "created_by", "period_from", "period_to",
        "buy_file_key", "buy_filename", "shopmine_file_key", "shopmine_filename",
        "markets_fetched", "markets_failed", "counts", "result_blob",
    }


def test_app_imports_margin_models():
    """create_all 이 테이블을 만들려면 app.py 가 모델을 import 해야 한다.
    (이 저장소에 Alembic 은 없다 — shared/db.py:init_db 의 create_all 이 유일한 경로.)"""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "app.py"
    assert "import lemouton.margin.models" in src.read_text(encoding="utf-8")

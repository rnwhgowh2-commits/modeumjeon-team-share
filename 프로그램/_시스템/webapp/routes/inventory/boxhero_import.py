"""[I] /inventory/data/boxhero-import — 박스히어로 1회 import 페이지.

ADR-005 핵심 진입점 (R2 가치 도착).
ai-workflow STEP 7 Sprint 1B Task 1.9
"""
import os
import tempfile

from flask import render_template, request, redirect, url_for, flash

from shared.db import SessionLocal
from lemouton.inventory.boxhero_import import import_xlsx, verify_after_import

from . import bp


@bp.get('/data/boxhero-import')
def data_boxhero_import():
    s = SessionLocal()
    try:
        verify = verify_after_import(s)
        return render_template(
            'inventory/data/boxhero_import.html',
            active='data-import',
            verify=verify,
        )
    finally:
        s.close()


@bp.post('/data/boxhero-import/upload')
def data_boxhero_import_upload():
    file = request.files.get('xlsx')
    if not file or not file.filename:
        flash("파일을 선택해주세요.", 'error')
        return redirect(url_for('inventory.data_boxhero_import'))
    if not file.filename.lower().endswith(('.xlsx', '.xls')):
        flash(".xlsx 파일만 가능합니다.", 'error')
        return redirect(url_for('inventory.data_boxhero_import'))

    threshold = int(request.form.get('threshold', 80))

    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    s = SessionLocal()
    try:
        result = import_xlsx(tmp_path, s, threshold_auto=threshold)
        s.commit()
        msg = (
            f"✅ 박스히어로 import 완료 — "
            f"records {result['records_count']} | "
            f"자동 매핑 {len(result['mapped'])} | "
            f"검토 큐 {len(result['queued'])} | "
            f"재고 갱신 {result['stock_updated']}"
        )
        if result['errors']:
            msg += f" | 오류 {len(result['errors'])}건"
        flash(msg, 'success')
    except Exception as e:
        s.rollback()
        flash(f"import 실패: {e}", 'error')
    finally:
        s.close()
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return redirect(url_for('inventory.data_boxhero_import'))

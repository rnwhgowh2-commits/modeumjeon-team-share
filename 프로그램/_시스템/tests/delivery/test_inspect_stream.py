# -*- coding: utf-8 -*-
"""[TEST] /inspect/upload-stream — 업로드 진행현황 NDJSON 스트리밍 글루."""
import io
import json

import pytest
from flask import Flask

from webapp.routes import orders as om
import lemouton.delivery.market_enrich as me


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(om.bp)

    class _S:
        def close(self):
            pass
    monkeypatch.setattr(om, "SessionLocal", lambda: _S())
    monkeypatch.setattr(om, "parse_mango_xls",
                        lambda raw: [{"mango_uid": "1"}, {"mango_uid": "2"}])
    monkeypatch.setattr(om._dsvc, "seed_default_status_map", lambda s: None)
    monkeypatch.setattr(om._dsvc, "upsert_orders",
                        lambda s, rows, **kw: {"inserted": len(rows), "updated": 0})

    def fake_iter(session, uids, warnings=None):
        yield {"phase": "start", "skipped": 0,
               "markets": [{"slug": "coupang", "label": "쿠팡", "total": 2}]}
        yield {"phase": "market", "slug": "coupang", "label": "쿠팡",
               "total": 2, "matched": 0, "state": "fetching"}
        yield {"phase": "market", "slug": "coupang", "label": "쿠팡",
               "total": 2, "matched": 2, "state": "done"}
        yield {"phase": "done", "checked": 2, "unmatched": 0, "skipped": 0, "warnings": []}
    monkeypatch.setattr(me, "iter_enrich", fake_iter)
    return app.test_client()


def test_upload_stream_emits_ndjson_events(client):
    r = client.post("/orders/inspect/upload-stream",
                    data={"file": (io.BytesIO(b"x"), "m.xls")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    lines = [json.loads(x) for x in r.get_data(as_text=True).splitlines() if x.strip()]
    phases = [e["phase"] for e in lines]
    assert phases == ["parsed", "start", "market", "market", "done"]
    assert lines[0]["parsed"] == 2                       # 파싱 건수
    assert lines[-1]["checked"] == 2                     # 최종 대조 건수
    md = [e for e in lines if e["phase"] == "market" and e["state"] == "done"][0]
    assert md["matched"] == 2 and md["label"] == "쿠팡"


def test_upload_stream_no_file_400(client):
    r = client.post("/orders/inspect/upload-stream", data={}, content_type="multipart/form-data")
    assert r.status_code == 400

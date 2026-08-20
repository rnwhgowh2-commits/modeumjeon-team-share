import os
os.environ["ENVIRONMENT"] = "test"   # admin 게이트 우회(team-share-dev 아님)
import pytest
from flask import Flask
from webapp.routes.api_sources_parse import bp

@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    return app.test_client()

def test_parse_endpoint_ssf(client, html_of):
    r = client.post("/api/sources/parse", json={
        "source_key": "ssf",
        "url": "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good",
        "html": html_of("ssf"),
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["source"] == "ssf"
    assert len(d["options"]) > 0 and all(o["price"] > 0 for o in d["options"])

def test_parse_endpoint_bad_source(client):
    r = client.post("/api/sources/parse", json={"source_key": "nope", "url": "x", "html": "<html></html>"})
    assert r.status_code == 400

def test_parse_endpoint_bad_input(client):
    r = client.post("/api/sources/parse", json={"source_key": "ssf", "url": "x", "html": ""})
    assert r.status_code == 400

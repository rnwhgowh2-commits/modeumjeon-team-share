"""[TEST] shared.storage 어댑터 — 가공 seam + R2 업로드 계약.

실제 R2 호출 없이 가짜 클라이언트로 동작을 검증한다.
"""
import pytest

from shared import storage


class _FakeClient:
    """boto3 S3 클라이언트 스텁 — put/delete 호출을 기록만 한다."""
    def __init__(self):
        self.puts = []
        self.deletes = []

    def put_object(self, **kw):
        self.puts.append(kw)

    def delete_object(self, **kw):
        self.deletes.append(kw)


@pytest.fixture
def fake(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(storage, "_get_client", lambda: client)
    monkeypatch.setattr(storage.Config, "R2_BUCKET", "test-bucket")
    monkeypatch.setattr(storage.Config, "R2_PUBLIC_BASE_URL", "https://pub-test.r2.dev")
    return client


def test_public_url_joins_base_and_key(fake):
    assert storage.public_url("product/ABC.jpg") == "https://pub-test.r2.dev/product/ABC.jpg"


def test_public_url_strips_trailing_slash(monkeypatch, fake):
    monkeypatch.setattr(storage.Config, "R2_PUBLIC_BASE_URL", "https://pub-test.r2.dev/")
    assert storage.public_url("a.png") == "https://pub-test.r2.dev/a.png"


def test_put_object_uploads_and_returns_url(fake):
    url = storage.put_object(b"hello", "product/x.png", "image/png")
    assert url == "https://pub-test.r2.dev/product/x.png"
    assert len(fake.puts) == 1
    put = fake.puts[0]
    assert put["Bucket"] == "test-bucket"
    assert put["Key"] == "product/x.png"
    assert put["Body"] == b"hello"
    assert put["ContentType"] == "image/png"


def test_processors_run_in_order_before_upload(fake):
    def add_a(b): return b + b"A"
    def add_b(b): return b + b"B"
    storage.put_object(b"x", "k.png", "image/png", processors=[add_a, add_b])
    assert fake.puts[0]["Body"] == b"xAB"  # add_a 먼저, add_b 다음


def test_put_upload_infers_content_type_from_ext(fake):
    class _FS:
        def read(self): return b"data"
        def seek(self, *a): pass
    storage.put_upload(_FS(), "attachment/doc.pdf")
    assert fake.puts[0]["ContentType"] == "application/pdf"
    assert fake.puts[0]["Key"] == "attachment/doc.pdf"


def test_put_upload_unknown_ext_falls_back_to_octet_stream(fake):
    class _FS:
        def read(self): return b"data"
        def seek(self, *a): pass
    storage.put_upload(_FS(), "x.bin")
    assert fake.puts[0]["ContentType"] == "application/octet-stream"


def test_put_upload_no_extension_falls_back_to_octet_stream(fake):
    class _FS:
        def read(self): return b"data"
        def seek(self, *a): pass
    storage.put_upload(_FS(), "product/SKU-NO-DOT")
    assert fake.puts[0]["ContentType"] == "application/octet-stream"
    assert fake.puts[0]["Key"] == "product/SKU-NO-DOT"


def test_delete_object_calls_client(fake):
    storage.delete_object("product/x.png")
    assert fake.deletes == [{"Bucket": "test-bucket", "Key": "product/x.png"}]

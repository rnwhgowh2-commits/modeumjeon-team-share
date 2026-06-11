"""[TEST] lemouton.sourcing.screenshot — ④ 예제 기준 스크린샷 R2 저장 계약.

실제 Playwright/R2 없이 가짜 클라이언트로 키 형식·Content-Type·content-addressed 동작 검증.
"""
import pytest

from shared import storage
from lemouton.sourcing import screenshot as shot


class _FakeClient:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


@pytest.fixture
def fake(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(storage, "_get_client", lambda: client)
    monkeypatch.setattr(storage.Config, "R2_BUCKET", "test-bucket")
    monkeypatch.setattr(storage.Config, "R2_PUBLIC_BASE_URL", "https://pub-test.r2.dev")
    return client


def test_store_uses_content_addressed_jpeg_key(fake):
    url = shot.store_guide_screenshot(3, 1, b"\xff\xd8jpegbytes")
    assert url.startswith("https://pub-test.r2.dev/guide-shots/3/ex1-")
    assert url.endswith(".jpg")
    put = fake.puts[0]
    assert put["Bucket"] == "test-bucket"
    assert put["ContentType"] == "image/jpeg"
    assert put["Body"] == b"\xff\xd8jpegbytes"


def test_store_same_bytes_same_key_diff_bytes_diff_key(fake):
    a = shot.store_guide_screenshot(3, 0, b"AAAA")
    b = shot.store_guide_screenshot(3, 0, b"AAAA")
    c = shot.store_guide_screenshot(3, 0, b"BBBB")
    assert a == b          # 같은 내용 → 같은 키(멱등)
    assert a != c          # 다른 내용 → 다른 키(캐시 무효화)


def test_capture_rejects_non_http():
    with pytest.raises(RuntimeError):
        shot.capture_screenshot("ftp://x")

# R2 이미지 저장 인프라 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사진/첨부 저장을 서버 디스크 → Cloudflare R2(공개 버킷)로 옮기고, 미래 가공 기능이 끼워질 seam을 갖춘 단일 스토리지 어댑터를 만든다.

**Architecture:** `shared/storage.py` 단일 어댑터("창고 직원")가 R2(S3 호환)와의 모든 대화를 캡슐화한다. 업로드 3곳이 이 어댑터를 호출하도록 교체하되, R2 미설정 시 기존 디스크 저장으로 자동 폴백한다(로컬 개발·점진 전환 안전). 기존 사진은 별도 1회성 스크립트로 안전 이사한다.

**Tech Stack:** Python, Flask, boto3(S3 호환 클라이언트), Cloudflare R2, pytest + monkeypatch.

**관련 설계 문서:** `docs/superpowers/specs/2026-05-31-r2-image-storage-design.md`

---

## 파일 구조

| 파일 | 역할 | 작업 |
|------|------|------|
| `프로그램/_시스템/requirements.txt` | 의존성 — boto3 추가 | Modify |
| `프로그램/_시스템/config.py` | R2 환경변수 로드 | Modify |
| `프로그램/_시스템/shared/storage.py` | **스토리지 어댑터(창고 직원)** | Create |
| `프로그램/_시스템/tests/test_storage.py` | 어댑터 단위 테스트 | Create |
| `프로그램/_시스템/webapp/routes/inventory/data.py` | 상품 이미지 업로드 2곳 → 어댑터 | Modify |
| `프로그램/_시스템/webapp/routes/inventory/notifications.py` | 첨부 업로드 → 어댑터 | Modify |
| `프로그램/_시스템/scripts/migrate_images_to_r2.py` | 기존 파일 1회성 이사(Phase 2) | Create |
| `프로그램/_시스템/.env` | R2 비밀값(로컬, gitignore됨) | Modify(수동) |

> **테스트 실행 규약:** pytest는 `프로그램\_시스템` 디렉터리를 루트로 동작한다(설정 파일 없음 → 이 폴더가 sys.path 루트). 모든 테스트 명령은 **`프로그램\_시스템` 안에서** 실행한다. PowerShell 예: `cd '프로그램\_시스템'; python -m pytest tests/test_storage.py -v`

---

## Task 1: boto3 의존성 + R2 설정

**Files:**
- Modify: `프로그램/_시스템/requirements.txt`
- Modify: `프로그램/_시스템/config.py:24` (LOG_DIR 정의 아래)

- [ ] **Step 1: requirements.txt에 boto3 추가**

`프로그램/_시스템/requirements.txt` 의 `cryptography>=43,<46` 줄(19번째) 바로 아래에 추가:

```text
boto3>=1.34,<2.0  # Cloudflare R2 (S3 호환) 오브젝트 스토리지 — shared/storage.py
```

- [ ] **Step 2: 설치**

Run (`프로그램\_시스템` 안에서): `pip install 'boto3>=1.34,<2.0'`
Expected: `Successfully installed boto3-... botocore-... s3transfer-...`

- [ ] **Step 3: config.py에 R2 설정 추가**

`프로그램/_시스템/config.py` 의 `LOG_DIR = PROJECT_ROOT / "logs"` 줄(24번째) 바로 아래, 같은 `Config` 클래스 들여쓰기로 추가:

```python

    # ─── Cloudflare R2 (이미지/첨부 오브젝트 스토리지) ───
    # 값은 .env / Fly secrets 에서 주입. 미설정 시 R2_ENABLED=False → 업로드는 디스크 폴백.
    R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET = os.environ.get("R2_BUCKET", "modeumjeon-images")
    R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "")  # 예: https://pub-xxxx.r2.dev
    R2_ENABLED = bool(R2_ACCOUNT_ID and R2_PUBLIC_BASE_URL)
```

- [ ] **Step 4: 설정 로드 확인**

Run (`프로그램\_시스템` 안에서): `python -c "from config import Config; print('R2_ENABLED=', Config.R2_ENABLED, 'BUCKET=', Config.R2_BUCKET)"`
Expected: `R2_ENABLED= False BUCKET= modeumjeon-images` (아직 .env에 값 없으므로 False가 정상)

- [ ] **Step 5: Commit**

```bash
git add 프로그램/_시스템/requirements.txt 프로그램/_시스템/config.py
git commit -m "feat(storage): boto3 의존성 + R2 환경설정 추가"
```

---

## Task 2: 스토리지 어댑터(창고 직원) + 테스트

**Files:**
- Create: `프로그램/_시스템/shared/storage.py`
- Test: `프로그램/_시스템/tests/test_storage.py`

TDD 순서로 진행한다.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `프로그램/_시스템/tests/test_storage.py`:

```python
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
    storage.put_upload(_FS(), "attachment/doc.pdf")
    assert fake.puts[0]["ContentType"] == "application/pdf"
    assert fake.puts[0]["Key"] == "attachment/doc.pdf"


def test_put_upload_unknown_ext_falls_back_to_octet_stream(fake):
    class _FS:
        def read(self): return b"data"
    storage.put_upload(_FS(), "x.bin")
    assert fake.puts[0]["ContentType"] == "application/octet-stream"


def test_delete_object_calls_client(fake):
    storage.delete_object("product/x.png")
    assert fake.deletes == [{"Bucket": "test-bucket", "Key": "product/x.png"}]
```

- [ ] **Step 2: 테스트 실패 확인**

Run (`프로그램\_시스템` 안에서): `python -m pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.storage'`

- [ ] **Step 3: 어댑터 구현**

Create `프로그램/_시스템/shared/storage.py`:

```python
"""R2(S3 호환) 오브젝트 스토리지 어댑터 — "창고 직원".

호출부(업로드 라우트)는 R2를 몰라도 된다. 저장/삭제/URL계산만 시킨다.

가공 seam: put_object(processors=[...]) 의 processors 는 bytes->bytes 함수 목록.
지금은 호출부에서 안 넘기므로 그냥 통과. 미래에 resize/watermark 함수를 끼우면 됨.
"""
from typing import Callable, List, Optional

import boto3
from botocore.config import Config as BotoConfig

from config import Config

Processor = Callable[[bytes], bytes]

# 확장자 → Content-Type (브라우저가 이미지로 인식하도록)
_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "csv": "text/csv", "txt": "text/plain",
}

_client = None  # 지연 생성 후 모듈 캐시


def _get_client():
    """boto3 S3 클라이언트(R2 엔드포인트). 최초 1회 생성 후 재사용. 테스트는 이 함수를 monkeypatch."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{Config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=Config.R2_ACCESS_KEY_ID,
            aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,
            config=BotoConfig(signature_version="s3v4"),
            region_name="auto",
        )
    return _client


def public_url(key: str) -> str:
    """key의 공개 URL 계산(네트워크 호출 없음)."""
    base = Config.R2_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/{key}"


def put_object(data: bytes, key: str, content_type: str,
               *, processors: Optional[List[Processor]] = None) -> str:
    """processors를 순서대로 통과시킨 뒤 R2에 업로드, 공개 URL 반환."""
    for proc in (processors or []):
        data = proc(data)
    _get_client().put_object(
        Bucket=Config.R2_BUCKET, Key=key, Body=data, ContentType=content_type,
    )
    return public_url(key)


def put_upload(file_storage, key: str,
               *, processors: Optional[List[Processor]] = None) -> str:
    """Flask FileStorage 편의 래퍼 — 확장자로 Content-Type 추론 후 put_object."""
    data = file_storage.read()
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
    return put_object(data, key, content_type, processors=processors)


def delete_object(key: str) -> None:
    """R2에서 key 삭제(존재하지 않아도 에러 없음)."""
    _get_client().delete_object(Bucket=Config.R2_BUCKET, Key=key)
```

- [ ] **Step 4: 테스트 통과 확인**

Run (`프로그램\_시스템` 안에서): `python -m pytest tests/test_storage.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add 프로그램/_시스템/shared/storage.py 프로그램/_시스템/tests/test_storage.py
git commit -m "feat(storage): R2 어댑터(put/delete/url + 가공 seam) + 단위 테스트"
```

---

## Task 3: 상품 이미지 업로드 라우트 → R2 (data.py:43 `data_item_upload_image`)

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/inventory/data.py:43-67`

기존 라우트는 `UPLOAD_DIR`에 디스크 저장 후 `image_url`에 `/inventory/...` 경로를 기록한다. R2 사용 시 R2 공개 URL을 기록하고, 미설정 시 기존 디스크 동작을 그대로 유지한다.

- [ ] **Step 1: 라우트 본문 교체**

`프로그램/_시스템/webapp/routes/inventory/data.py` 의 47~57행(파일 검증 후 저장 블록)에서, 아래 기존 코드:

```python
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = sku.replace('/', '_').replace(' ', '_')
    fname = f'{safe}.{ext}'
    file.save(str(UPLOAD_DIR / fname))
    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == sku).first()
        if opt:
            opt.image_url = f'/inventory/data/product-image/{fname}'
            s.commit()
            flash(f'이미지 업로드 완료 — {sku}', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.data_items'))
```

를 다음으로 교체:

```python
    safe = sku.replace('/', '_').replace(' ', '_')
    fname = f'{safe}.{ext}'
    from config import Config
    if Config.R2_ENABLED:
        from shared import storage
        new_url = storage.put_upload(file, f'product/{fname}')
    else:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file.save(str(UPLOAD_DIR / fname))
        new_url = f'/inventory/data/product-image/{fname}'
    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == sku).first()
        if opt:
            opt.image_url = new_url
            s.commit()
            flash(f'이미지 업로드 완료 — {sku}', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.data_items'))
```

- [ ] **Step 2: import 깨짐 없는지 정적 확인**

Run (`프로그램\_시스템` 안에서): `python -c "import ast; ast.parse(open('webapp/routes/inventory/data.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 폴백 경로 회귀 테스트(R2 미설정 시 디스크 동작 유지)**

R2_ENABLED=False 환경(기본)에서 앱이 정상 import 되는지 확인:

Run (`프로그램\_시스템` 안에서): `python -c "from config import Config; assert Config.R2_ENABLED is False; print('fallback path active')"`
Expected: `fallback path active`

- [ ] **Step 4: Commit**

```bash
git add 프로그램/_시스템/webapp/routes/inventory/data.py
git commit -m "feat(storage): 상품 이미지 업로드(upload-image) R2 연동 + 디스크 폴백"
```

---

## Task 4: 상품 이미지 편집 라우트 → R2 (data.py:406 모델+색상 그룹 저장)

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/inventory/data.py:406-424`

이 경로는 `img_<model>_<color>.<ext>` 규칙으로 저장하고 같은 모델·색상 형제 옵션에 동일 URL을 적용한다. 저장 부분만 R2로 바꾸고 형제 적용 로직은 그대로 둔다.

- [ ] **Step 1: 저장 블록 교체**

`프로그램/_시스템/webapp/routes/inventory/data.py` 의 409~420행에서 아래 기존 코드:

```python
            if ext in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                # [2026-05-29 2부-1] 모델+색상 그룹 키로 저장 → 같은 모델·색상 모든 옵션 공유
                #   파일명: img_<model_code>_<color>.<ext> (sanitize)
                import re as _re
                color_key = (opt.color_display or opt.color_code or 'one').strip() or 'one'
                model_key = opt.model_code or sku
                safe_model = _re.sub(r'[^A-Za-z0-9가-힣_\-]', '_', model_key)[:40]
                safe_color = _re.sub(r'[^A-Za-z0-9가-힣_\-]', '_', color_key)[:30]
                fname = f'img_{safe_model}_{safe_color}.{ext}'
                file.save(str(UPLOAD_DIR / fname))
                new_url = f'/inventory/data/product-image/{fname}'
```

를 다음으로 교체(들여쓰기 유지):

```python
            if ext in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
                # [2026-05-29 2부-1] 모델+색상 그룹 키로 저장 → 같은 모델·색상 모든 옵션 공유
                #   파일명: img_<model_code>_<color>.<ext> (sanitize)
                import re as _re
                color_key = (opt.color_display or opt.color_code or 'one').strip() or 'one'
                model_key = opt.model_code or sku
                safe_model = _re.sub(r'[^A-Za-z0-9가-힣_\-]', '_', model_key)[:40]
                safe_color = _re.sub(r'[^A-Za-z0-9가-힣_\-]', '_', color_key)[:30]
                fname = f'img_{safe_model}_{safe_color}.{ext}'
                from config import Config
                if Config.R2_ENABLED:
                    from shared import storage
                    new_url = storage.put_upload(file, f'product/{fname}')
                else:
                    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                    file.save(str(UPLOAD_DIR / fname))
                    new_url = f'/inventory/data/product-image/{fname}'
```

- [ ] **Step 2: 정적 파싱 확인**

Run (`프로그램\_시스템` 안에서): `python -c "import ast; ast.parse(open('webapp/routes/inventory/data.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add 프로그램/_시스템/webapp/routes/inventory/data.py
git commit -m "feat(storage): 상품 이미지 편집 저장(모델+색상 그룹) R2 연동 + 디스크 폴백"
```

---

## Task 5: 첨부 업로드 라우트 → R2 (notifications.py:51 `upload_attachment`)

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/inventory/notifications.py:65-73`

기존은 `ATTACHMENT_DIR`에 저장하고 `/inventory/api/attachment/<safe_name>`를 반환한다. R2 사용 시 R2 공개 URL을 반환한다. `secrets`, `os`는 파일 상단에서 이미 import됨(10~11행).

- [ ] **Step 1: 저장/반환 블록 교체**

`프로그램/_시스템/webapp/routes/inventory/notifications.py` 의 65~73행에서 아래 기존 코드:

```python
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = secrets.token_hex(8) + '.' + ext
    file.save(str(ATTACHMENT_DIR / safe_name))
    return jsonify(
        url=f'/inventory/api/attachment/{safe_name}',
        name=file.filename,
        size=size,
        stored=safe_name,
    )
```

를 다음으로 교체:

```python
    safe_name = secrets.token_hex(8) + '.' + ext
    from config import Config
    if Config.R2_ENABLED:
        from shared import storage
        file.seek(0)
        url = storage.put_upload(file, f'attachment/{safe_name}')
    else:
        ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
        file.save(str(ATTACHMENT_DIR / safe_name))
        url = f'/inventory/api/attachment/{safe_name}'
    return jsonify(
        url=url,
        name=file.filename,
        size=size,
        stored=safe_name,
    )
```

> 참고: 65행 위에서 size 계산을 위해 `file.seek(0, os.SEEK_END)` 후 `file.seek(0)`을 이미 했지만, R2 경로에서 `put_upload`가 `read()`하기 전에 안전하게 `file.seek(0)`을 한 번 더 호출한다(스트림 선두 보장).

- [ ] **Step 2: 정적 파싱 확인**

Run (`프로그램\_시스템` 안에서): `python -c "import ast; ast.parse(open('webapp/routes/inventory/notifications.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add 프로그램/_시스템/webapp/routes/inventory/notifications.py
git commit -m "feat(storage): 첨부 업로드(upload-attachment) R2 연동 + 디스크 폴백"
```

---

## Task 6: 기존 사진 1회성 이사 스크립트 (Phase 2 — 실 검증 후 실행)

**Files:**
- Create: `프로그램/_시스템/scripts/migrate_images_to_r2.py`

기존 디스크 파일을 R2로 복사하고 DB의 옛 URL을 R2 URL로 갱신한다. **원본 파일은 삭제하지 않는다(되돌림 안전).** 이 스크립트는 작성·커밋만 하고, 실제 실행은 R2 연동이 라이브에서 검증된 뒤 사용자 승인하에 수행한다.

- [ ] **Step 1: 스크립트 작성**

Create `프로그램/_시스템/scripts/migrate_images_to_r2.py`:

```python
"""[1회성] 기존 디스크 사진 → R2 이사.

- data/product_images/*  → R2 'product/<fname>' + Option.image_url 갱신
- data/attachments/*     → R2 'attachment/<fname>' (DB 참조는 첨부 JSON 안에 박혀
                           있어 자동 갱신 대상 아님 → 신규 첨부부터 R2, 구 첨부는
                           기존 디스크 라우트로 계속 서빙. 파일만 R2 백업 복사.)

원본 파일은 삭제하지 않는다. 실행 후 며칠 검증 뒤 사용자가 수동 정리.

실행(프로그램\\_시스템 안에서):  python scripts/migrate_images_to_r2.py --dry-run
                              python scripts/migrate_images_to_r2.py --commit
"""
import argparse
from pathlib import Path

from config import Config
from shared import storage
from shared.db import SessionLocal
from lemouton.sourcing.models import Option

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DIR = ROOT / 'data' / 'product_images'
ATTACH_DIR = ROOT / 'data' / 'attachments'


def migrate_products(commit: bool) -> int:
    """product_images 파일을 R2로 올리고, 그 파일을 가리키던 image_url을 R2 URL로 갱신."""
    if not PRODUCT_DIR.exists():
        print('product_images 디렉터리 없음 — 건너뜀')
        return 0
    n = 0
    s = SessionLocal()
    try:
        for f in PRODUCT_DIR.iterdir():
            if not f.is_file():
                continue
            key = f'product/{f.name}'
            old_url = f'/inventory/data/product-image/{f.name}'
            new_url = storage.public_url(key)
            print(f'  {f.name}  ->  {new_url}')
            if commit:
                with f.open('rb') as fh:
                    storage.put_object(fh.read(), key,
                                       _content_type(f.name))
                # 이 파일을 가리키던 모든 옵션 갱신
                opts = s.query(Option).filter(Option.image_url == old_url).all()
                for opt in opts:
                    opt.image_url = new_url
            n += 1
        if commit:
            s.commit()
    finally:
        s.close()
    return n


def migrate_attachments(commit: bool) -> int:
    """attachments 파일을 R2로 백업 복사(DB 참조 갱신은 안 함 — 신규부터 R2)."""
    if not ATTACH_DIR.exists():
        print('attachments 디렉터리 없음 — 건너뜀')
        return 0
    n = 0
    for f in ATTACH_DIR.iterdir():
        if not f.is_file():
            continue
        key = f'attachment/{f.name}'
        print(f'  {f.name}  ->  {storage.public_url(key)}')
        if commit:
            with f.open('rb') as fh:
                storage.put_object(fh.read(), key, _content_type(f.name))
        n += 1
    return n


def _content_type(name: str) -> str:
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return storage._CONTENT_TYPES.get(ext, 'application/octet-stream')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true', help='실제 업로드/DB갱신 수행')
    ap.add_argument('--dry-run', action='store_true', help='미리보기만')
    args = ap.parse_args()
    commit = args.commit and not args.dry_run
    if not Config.R2_ENABLED:
        raise SystemExit('R2 미설정(.env) — R2_ACCOUNT_ID / R2_PUBLIC_BASE_URL 필요')
    mode = 'COMMIT' if commit else 'DRY-RUN'
    print(f'=== 이미지 R2 이사 [{mode}] ===')
    print('[상품 이미지]')
    p = migrate_products(commit)
    print('[첨부]')
    a = migrate_attachments(commit)
    print(f'완료 — 상품 {p}건, 첨부 {a}건 ({mode})')
    if not commit:
        print('실제 반영하려면 --commit 으로 다시 실행')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 정적 파싱 확인**

Run (`프로그램\_시스템` 안에서): `python -c "import ast; ast.parse(open('scripts/migrate_images_to_r2.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add 프로그램/_시스템/scripts/migrate_images_to_r2.py
git commit -m "feat(storage): 기존 사진 R2 이사 스크립트(원본 보존, dry-run 기본)"
```

---

## Task 7: Cloudflare 수동 세팅 + 비밀값 주입 (사용자 협업)

**Files:**
- Modify: `프로그램/_시스템/.env` (로컬, gitignore됨 — 수동)

> 이 태스크는 코드가 아니라 운영 절차다. 사용자가 클라우드플레어 화면에서 값을 만들고, 그 값을 함께 주입한다.

- [ ] **Step 1: 사용자 — Cloudflare R2 버킷 생성**

1. Cloudflare 가입/로그인 → R2 메뉴 진입(카드 등록 1회, 10GB 무료).
2. **Create bucket** → 이름 `modeumjeon-images` (config 기본값과 일치).

- [ ] **Step 2: 사용자 — 버킷 공개(Public) 활성화**

버킷 Settings → **Public access** → r2.dev 공개 URL 허용 → 발급된 `https://pub-xxxxxxxx.r2.dev` 주소 확보.

- [ ] **Step 3: 사용자 — API 토큰 발급**

R2 → **Manage API Tokens** → Create token → 권한 **Object Read & Write**, 대상 버킷 `modeumjeon-images` → 발급된 **Access Key ID / Secret Access Key / Account ID** 확보.

- [ ] **Step 4: 로컬 .env에 값 주입**

`프로그램/_시스템/.env` 끝에 추가(실제 값으로 치환):

```text
R2_ACCOUNT_ID=<Account ID>
R2_ACCESS_KEY_ID=<Access Key ID>
R2_SECRET_ACCESS_KEY=<Secret Access Key>
R2_BUCKET=modeumjeon-images
R2_PUBLIC_BASE_URL=https://pub-xxxxxxxx.r2.dev
```

- [ ] **Step 5: 로컬 연결 스모크 테스트**

Run (`프로그램\_시스템` 안에서):
```
python -c "from config import Config; from shared import storage; print(storage.put_object(b'hi', 'product/_smoketest.txt', 'text/plain'))"
```
Expected: `https://pub-xxxxxxxx.r2.dev/product/_smoketest.txt` 출력 + 그 URL을 브라우저로 열면 `hi` 표시. (확인 후 Cloudflare 대시보드에서 `_smoketest.txt` 삭제)

- [ ] **Step 6: Fly secrets 주입**

Run (저장소 루트 또는 `프로그램\_시스템`에서, flyctl 로그인 상태):
```
fly secrets set R2_ACCOUNT_ID=<...> R2_ACCESS_KEY_ID=<...> R2_SECRET_ACCESS_KEY=<...> R2_BUCKET=modeumjeon-images R2_PUBLIC_BASE_URL=https://pub-xxxxxxxx.r2.dev -a modeumjeon-team-share
```
Expected: `Secrets are staged for the first deployment` 또는 재배포 트리거 메시지.

---

## Task 8: 라이브 검증 + 마무리

- [ ] **Step 1: 전체 단위 테스트**

Run (`프로그램\_시스템` 안에서): `python -m pytest tests/ -v`
Expected: 기존 테스트 + `test_storage.py` 모두 PASS.

- [ ] **Step 2: 브라우저 실검증** — `/live-browser-verify` → `/ui-verify`

상품 이미지 업로드 → R2 URL로 표시되는지, 첨부 드래그앤드롭 → R2 URL 반환·표시되는지, Cloudflare 대시보드에 객체 생성되는지 확인.

- [ ] **Step 3 (검증 통과 후): 기존 사진 이사**

Run (`프로그램\_시스템` 안에서): `python scripts/migrate_images_to_r2.py --dry-run` → 목록 확인 → `python scripts/migrate_images_to_r2.py --commit`
이후 며칠 정상 확인되면 사용자 승인하에 볼륨의 원본 정리.

---

## Self-Review 메모

- **Spec 커버리지:** §4 어댑터→Task2 / §5 흐름(업로드 3곳)→Task3·4·5 / §6 마이그레이션→Task6·8 / §7 수동세팅→Task7 / §8 검증→Task8 / §3 결정(공개·폴백)→Task1 R2_ENABLED. 누락 없음.
- **삭제(delete) seam:** 어댑터에 `delete_object` 구현·테스트는 있으나, 이번 단계 업로드 라우트에서 호출하진 않음(이미지 삭제 플래그는 DB url만 비움 — 고아 객체는 무해·저비용, YAGNI). 미래 확장에서 연결.
- **타입 일관성:** `put_object`/`put_upload`/`delete_object`/`public_url`/`_get_client`/`_CONTENT_TYPES` 명칭이 어댑터·테스트·마이그레이션 스크립트 전반에서 일치.
- **폴백 안전:** 모든 업로드 라우트가 `Config.R2_ENABLED` 분기로 R2 미설정 시 기존 디스크 동작을 100% 보존 → 로컬 개발·점진 전환 무중단.

# -*- coding: utf-8 -*-
"""세션 전역 conftest — 모든 SQLAlchemy 모델을 한 번 등록한다.

여러 테스트가 `Base.metadata.create_all(engine)` 을 호출하는데, 이는 그 시점에
`Base.metadata` 에 등록된 **모든** 모델의 테이블을 만든다. 일부 모델만 import 된
상태에서 create_all 하면 FK 타겟 테이블(예: `bundle_sets.size_template_id` →
`size_templates`)이 metadata 에 없어 `NoReferencedTableError` 로 실패한다 —
어떤 테스트가 먼저 돌아 어떤 모델을 import 했는지에 따라 갈리는 순서 의존 버그다.
(app.py 도 create_app 에서 같은 이유로 모델을 전부 import 한 뒤 init_db 한다:
 "fresh DB 에서 create_all 시 모든 FK 타겟 테이블 필요".)

app.py 의 모델 등록 목록을 그대로 미러링해, 어떤 create_all 이든 완전한 metadata
위에서 돌도록 보장한다. 모델 모듈 import 는 테이블 등록뿐이라 부작용이 없다.
"""

# ══════════════════════════════════════════════════════════════════════════
# 시험용 DB 격리 — 공용 SQLite(data/lemouton.db) 를 안 건드린다 (2026-08-01)
#
# 왜 (실측으로 규명한 것):
#   테스트가 배운 쿠팡 수수료율을 공용 DB 에 **진짜로 남긴다**
#   (learned_rates_store.merge_safe — 기능이라 정상). 그래서 전체 실행을 한 번 하고 나면
#   data/lemouton.db 에 {"VI-1":0.1235,"9":0.1155,"82914":0.1262} 가 남고,
#   **다음 실행**에서 tests/markets/test_coupang_paid_amount.py 같은 추정 테스트가
#   그 값을 읽어 다른 숫자를 내며 깨졌다. 이게 「실패 개수가 22~51 로 널뛴다」의 정체다.
#   (CI 는 매번 새 체크아웃이라 그 파일이 없어 멀쩡했다 — 로컬만 두 번째부터 달라졌다.)
#
# 무엇을 하나:
#   시험 세션마다 **빈 임시 SQLite** 를 만들어 DATABASE_URL 로 준다. 그러면
#   로컬이 CI 와 같은 조건(빈 DB)이 되고, 몇 번을 돌리든 결과가 같다.
#
# 🔴 반드시 `config` / `shared.db` 를 import 하기 **전에** 해야 한다.
#    engine 과 SessionLocal 은 import 시점에 Config.DB_URL 로 굳는다. 나중에
#    shared.db.SessionLocal 만 갈아끼우면, 최상단에서 `from shared.db import SessionLocal`
#    한 20여 개 모듈은 옛 것을 그대로 들고 있어 안 먹는다.
#
# 일부러 진짜 DB 로 돌려 보고 싶으면 MOUM_TEST_KEEP_DB=1 로 끈다.
# ══════════════════════════════════════════════════════════════════════════
import atexit as _atexit
import os as _os
import shutil as _shutil
import tempfile as _tempfile

if not _os.environ.get("MOUM_TEST_KEEP_DB") and not _os.environ.get("DATABASE_URL"):
    _tmpdir = _tempfile.mkdtemp(prefix="moum_test_db_")
    _os.environ["DATABASE_URL"] = "sqlite:///" + _os.path.join(_tmpdir, "test.db").replace("\\", "/")
    _atexit.register(lambda: _shutil.rmtree(_tmpdir, ignore_errors=True))


_ALL_MODEL_MODULES = [
    "lemouton.sourcing.models",
    "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.axis_alias",       # 축 매핑 저장소 (source_axis_aliases)
    "lemouton.sourcing.axis_confirm",     # 소싱처별 확인 도장
    "lemouton.pricing.settings",
    "lemouton.uploader.models",
    "lemouton.templates.models",
    "lemouton.inventory.models",
    "lemouton.sets.models",
    "lemouton.margin.models",
    "lemouton.delivery.models",
    "lemouton.sources.models",        # bundle_*, source_options (FK 타겟)
    "lemouton.sourcing.models_v2",
    "lemouton.multitenancy.models",
    "lemouton.audit.models",
    "lemouton.mapping.models",
    "lemouton.registration.models",   # 대량등록 — ProductDraft, ProductDraftMarket
    "lemouton.registration.notice_defaults",  # 고시정보 기본값 — notice_defaults
    "webapp.auth.models",
    "webapp.icon_store_model",
    "webapp.server_ip_model",
    # [2026-08-01] app.py 는 이 둘을 **init_db() 안에서** import 한다(최상단이 아니다).
    #   그래서 이 목록에서 빠져 있었고, `options.matrix_option_id` 의 FK 타겟인
    #   `matrix_options` 가 metadata 에 없어 create_all 이 통째로 실패했다
    #   (tests/policy 52건 오류 — origin/main 에서도 같이 났다).
    "lemouton.matrix.models",         # 매트릭스 원본/파생 옵션 (options 의 FK 타겟)
    "lemouton.policy.models",         # 정책 생성 — market_policies 외 3표
    # app.py 최상단에서 import 하는데 이 목록엔 없던 것들 — 같은 사고를 막는다.
    "lemouton.catalog.models",
    "lemouton.claims.models",
    "lemouton.cs_inquiries.models",
    "lemouton.markets.models_orders",
    "lemouton.markets.models_lotteon_so",
    "lemouton.markets.models_purchase",   # 실매입가 저장소 (order_line_purchases)
    "lemouton.markets.models_supply",     # 공급방식 저장소 (order_line_supplies)
    # 「주문 관리」 상태 (order_status_options · order_line_status)
    "lemouton.markets.models_order_status",
    # [2026-08-06] app.py:92 는 import 하는데 이 목록엔 빠져 있었다 — 같은 부류의 누락.
    "lemouton.send.models",           # 마켓 전송 작업·건별 결과
]

for _mod in _ALL_MODEL_MODULES:
    try:
        __import__(_mod)
    except ImportError:
        pass  # 모델 파일 없는 환경(정상)


# ══════════════════════════════════════════════════════════════════════════
# 표를 **여기서 한 번** 만든다 — 「단독으로 돌리면 실패」를 없앤다 (2026-08-06)
#
# 위에서 모델을 import 하는 것은 `Base.metadata` 에 **등록**만 한다. 실제 표는
# 각 시험이 자기 fixture 에서 `create_all` 을 부를 때 생겼다. 그래서 표를 안 만드는
# 시험은 **앞서 돈 다른 시험이 만들어 준 표에 얹혀** 통과했다.
#   실측(2026-08-06): tests/margin 의 골든 3건이 단독으로는
#   `no such table: card_keyword_config` 로 실패하고, tests/orders 와 같이 돌리면 통과.
#   「단독 통과 ≠ 전체 통과」의 반대 방향이라 더 헷갈린다 — 전체는 되는데 단독이 안 된다.
#
# DB 는 위에서 만든 **빈 임시 SQLite** 라 여기서 다 만들어도 남의 데이터를 안 건드린다.
# `create_all` 은 이미 있는 표를 건너뛰므로(checkfirst) 뒤에 나오는 fixture 들과 안 부딪힌다.
# ══════════════════════════════════════════════════════════════════════════
try:
    from shared.db import Base as _Base, engine as _engine
    _Base.metadata.create_all(_engine)
except Exception:   # noqa: BLE001 — DB 없는 환경에서도 수집은 되게(각 시험이 알아서 실패)
    pass


# ══════════════════════════════════════════════════════════════════════════
# 격리 목록 적용 — 배포 게이트가 「엉뚱한 이유」로 막히지 않게 (2026-08-01)
#   목록·이유는 tests/QUARANTINE.txt 에만 적는다(여긴 읽어서 붙이는 일만).
#
# ★건너뛰지(skip) 않고 xfail 로 붙인다 — 그대로 돌려 보고
#     · 여전히 실패하면 : xfail 로 조용히 지나감(배포 안 막힘)
#     · 고쳐져서 통과하면: XPASS 로 결과에 뜸 → 목록에서 지우라는 신호
#   그래서 목록이 썩지 않는다. (strict 아님 — XPASS 가 배포를 막지는 않게)
# ══════════════════════════════════════════════════════════════════════════
import pytest as _pytest

_QUARANTINE_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "QUARANTINE.txt")


def _load_quarantine() -> dict:
    """{nodeid: 사유} — 없거나 못 읽으면 빈 목록(격리는 보조 수단이지 전제가 아니다)."""
    out = {}
    try:
        with open(_QUARANTINE_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                nodeid, _, reason = line.partition("#")
                nodeid = nodeid.strip()
                if nodeid:
                    out[nodeid] = reason.strip() or "QUARANTINE.txt 참고"
    except OSError:
        pass
    return out


def pytest_collection_modifyitems(config, items):
    quarantined = _load_quarantine()
    if not quarantined:
        return
    seen = set()
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        reason = quarantined.get(nodeid)
        if reason is not None:
            seen.add(nodeid)
            item.add_marker(_pytest.mark.xfail(reason=f"[격리] {reason}", strict=False))

    # 목록에 있는데 **실제로 없는** 테스트(이름이 바뀌었거나 지워진 것)를 일러 준다.
    #   안 그러면 죽은 줄이 목록에 조용히 남아, 격리가 실제보다 많아 보인다.
    #   전체 실행일 때만 본다 — 파일 하나만 돌리면 나머지가 다 '없음'으로 잡히니까.
    targets = config.getoption("file_or_dir", default=[]) or []
    if not targets or targets in (["tests"], ["tests/"]):
        dead = sorted(set(quarantined) - seen)
        if dead:
            print("\n[격리] 목록에 있으나 존재하지 않는 테스트 — QUARANTINE.txt 에서 지우세요:")
            for d in dead:
                print("   ", d)

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

_ALL_MODEL_MODULES = [
    "lemouton.sourcing.models",
    "lemouton.sourcing.models_pricing",
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
    "lemouton.markets.models_shopmine",
]

for _mod in _ALL_MODEL_MODULES:
    try:
        __import__(_mod)
    except ImportError:
        pass  # 모델 파일 없는 환경(정상)

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
    "webapp.auth.models",
    "webapp.icon_store_model",
    "webapp.server_ip_model",
]

for _mod in _ALL_MODEL_MODULES:
    try:
        __import__(_mod)
    except ImportError:
        pass  # 모델 파일 없는 환경(정상)

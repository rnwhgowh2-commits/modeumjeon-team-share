"""모델·옵션 마스터 CRUD 헬퍼."""
import openpyxl
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import Model, Option


def upsert_model(session: Session, *, model_code: str, **kwargs) -> Model:
    existing = session.get(Model, model_code)
    if existing is None:
        m = Model(model_code=model_code, **kwargs)
        session.add(m)
        return m
    for k, v in kwargs.items():
        if v is not None:
            setattr(existing, k, v)
    return existing


def get_model(session: Session, model_code: str) -> Model | None:
    return session.get(Model, model_code)


def list_models(session: Session, *, brand: str | None = None) -> list[Model]:
    stmt = select(Model)
    if brand is not None:
        stmt = stmt.where(Model.brand == brand)
    return list(session.scalars(stmt).all())


def upsert_option(session: Session, *, canonical_sku: str, **kwargs) -> Option:
    existing = session.get(Option, canonical_sku)
    if existing is None:
        o = Option(canonical_sku=canonical_sku, **kwargs)
        session.add(o)
        return o
    for k, v in kwargs.items():
        if v is not None:
            setattr(existing, k, v)
    return existing


def get_option_by_canonical(session: Session, canonical_sku: str) -> Option | None:
    return session.get(Option, canonical_sku)


def list_options_by_model(session: Session, model_code: str) -> list[Option]:
    stmt = select(Option).where(Option.model_code == model_code)
    return list(session.scalars(stmt).all())


def find_option_by_boxhero_sku(session: Session, boxhero_sku: str) -> Option | None:
    stmt = select(Option).where(Option.boxhero_sku == boxhero_sku)
    return session.scalars(stmt).first()


# ─────────────────────────────────────────────────────────────────────────────
# V7 부트스트랩 — 소싱처_URL_르무통_updated.xlsx 임포트
# ─────────────────────────────────────────────────────────────────────────────
#
# V7 xlsx 실제 포맷 (1행 = 1 (소싱처, 상품명) 조합):
#   소싱처             | 상품명           | URL                         | 쿠팡A | 쿠팡B
#   ──────────────────────────────────────────────────────────────────────────
#   무신사             | 메이트 블랙       | https://www.musinsa.com/... | ID    | ID
#   SSF               | 메이트 블랙       | https://www.ssfshop.com/... | ID    | ID
#   르무통(공홈)       | 메이트 블랙       | https://lemouton.co.kr/...  | ID    | ID
#   …
#   무신사(모음전)     | 메이트           | https://www.musinsa.com/... | -     | -
#   르무통(모음전)     | 메이트           | https://m.lemouton.co.kr/...| -     | -
#
# 모델 마스터(=모음전 행) vs 옵션(=색상 행) 구분 규칙:
#   - 르무통(모음전)·무신사(모음전) → 모델 단위 URL  (T3에서 처리)
#   - 무신사·SSF·르무통(공홈)        → 색상 단위 URL  (T4 옵션 부트스트랩에서 처리)
#
# T3 본 함수는 르무통(모음전) 행을 기준으로 Model을 생성하고, 무신사(모음전)
# 의 URL을 상품명 매칭으로 보강한다. 색상-level 행은 의도적으로 무시한다.

# 소싱처 라벨 → Model 필드 매핑 (모음전 = 모델 단위 URL)
SOURCE_TO_MODEL_FIELD = {
    "르무통(모음전)": "url_lemouton",
    "무신사(모음전)": "url_musinsa",
}

# (참고) 색상-level URL 매핑 — T4에서 사용할 예정. 본 함수는 미사용.
SOURCE_TO_OPTION_FIELD = {
    "무신사": "option_id_musinsa",
    "SSF": "option_id_ssf",
    "르무통(공홈)": "option_id_lemouton",
}

# 호환성 alias — 플랜에서 언급된 COL_MAP 이름 유지.
# 실제 V7 파일은 헤더가 아닌 행 단위 소싱처 라벨로 분류되므로
# 이 매핑은 "소싱처 라벨 → 모델 필드" 의미로 정의한다.
COL_MAP = SOURCE_TO_MODEL_FIELD


def bootstrap_from_xlsx(session: Session, xlsx_path: str) -> int:
    """V7 부트스트랩 엑셀에서 Model 마스터를 일괄 등록한다.

    V7 실제 포맷:
        헤더: [소싱처, 상품명, URL, 쿠팡A, 쿠팡B]
        모델 단위 URL은 `르무통(모음전)`·`무신사(모음전)` 행에서 추출.

    Args:
        session: SQLAlchemy 세션
        xlsx_path: V7 부트스트랩 xlsx 경로

    Returns:
        생성/업데이트된 모델 수.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return 0

    # 첫 행은 헤더 (col 1=소싱처, col 2=상품명, col 3=URL).
    # V7 실제 파일에서 헤더 col 3 값은 example URL 이라 헤더 스키마 검증은
    # 첫 두 컬럼만 확인.
    header = rows[0]
    if (header[0] or "").strip() != "소싱처" or (header[1] or "").strip() != "상품명":
        raise ValueError(
            f"V7 부트스트랩 xlsx 헤더 형식이 예상과 다름. "
            f"expected col1='소싱처', col2='상품명', got={header[:2]!r}"
        )

    # Pass 1: 르무통(모음전) → Model 생성/업데이트 (모델명, url_lemouton)
    # Pass 2: 무신사(모음전) → 매칭되는 Model에 url_musinsa 설정
    #
    # 두 패스로 나누는 이유: 무신사(모음전) 행이 르무통(모음전) 보다
    # 위에 오기 때문 (V7 실제 파일에서 무신사 모음전이 134행, 르무통
    # 모음전이 137행부터 시작). Model 생성을 먼저 보장한 뒤 보강한다.

    lemouton_collection_rows: list[tuple[str, str]] = []  # (상품명, URL)
    musinsa_collection_rows: list[tuple[str, str]] = []   # (상품명, URL)

    for row in rows[1:]:
        if not row or row[0] is None:
            continue
        source = str(row[0]).strip()
        name = str(row[1] or "").strip()
        url = str(row[2] or "").strip() if row[2] is not None else ""
        if not name or not url:
            continue
        if source == "르무통(모음전)":
            lemouton_collection_rows.append((name, url))
        elif source == "무신사(모음전)":
            musinsa_collection_rows.append((name, url))
        # 그 외 (무신사·SSF·르무통(공홈)) 는 색상-level → T4에서 처리

    count = 0
    created_or_updated: dict[str, Model] = {}
    for name, url in lemouton_collection_rows:
        # 모델 코드는 상품명을 그대로 사용 (한글 코드 허용 — String(64))
        m = upsert_model(
            session,
            model_code=name,
            model_name_raw=name,
            brand="르무통",
            url_lemouton=url,
        )
        created_or_updated[name] = m
        count += 1

    # Pass 1에서 add() 만 호출되어 아직 flush 전이므로 session.get() 으로
    # 신규 객체를 조회할 수 없다. Pass 1 에서 추적한 dict로 보강한다.
    for name, url in musinsa_collection_rows:
        target = created_or_updated.get(name) or session.get(Model, name)
        if target is None:
            # 무신사 모음전에만 있고 르무통 모음전에 없는 모델은
            # 데이터 무결성 차원에서 새 Model 생성하지 않는다
            # (사용자가 르무통(모음전) URL을 추가하기 전엔 등록 보류).
            continue
        target.url_musinsa = url

    return count

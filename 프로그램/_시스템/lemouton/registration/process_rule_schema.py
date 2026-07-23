# -*- coding: utf-8 -*-
"""가공 규칙 13항목 — 항목마다 **무엇을 담는지** 선언한다.

정본: `docs/superpowers/specs/2026-07-17-신규상품등록-가공템플릿-design.md` §7
사장님 확정 2026-07-19 — 13개 한 번에(1-1 나), 마켓마다 다르게(1-2 나),
항목 내용은 **§7 이 정본**(1-3: "문서를 정확히 찾아봐라. 이미 논의했다").

━━ 왜 스키마를 따로 두나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · 폼 13개를 손으로 짜면 화면과 저장이 어긋난다. 스키마 하나에서 둘 다 나오게 한다.
  · 저장할 때 **모양을 검사**한다. 오타로 만든 설정이 조용히 저장되면
    「왜 안 먹지」로 한참 헤맨다 (item_key 오타를 막은 것과 같은 이유).
  · 기본값이 한곳에 모인다 — 화면·컴파일러·문서가 같은 값을 본다.

━━ 담지 않는 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  §7-12(세트 묶기)·13(등록 마무리)·14(까대기)는 **항목 규칙이 아니다.**
  세트 묶기는 정책의 소싱처·마켓 연결이 이미 담당하고, 나머지 둘은 별도 기능이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lemouton.registration.process_policy import ITEM_KEYS, ITEM_LABELS


@dataclass(frozen=True)
class Field:
    """설정 칸 하나."""

    key: str
    label: str
    type: str          # 'bool' | 'int' | 'text' | 'choice' | 'list'
    default: object = None
    choices: tuple = ()
    hint: str = ""
    unit: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "type": self.type,
                "default": self.default, "choices": list(self.choices),
                "hint": self.hint, "unit": self.unit}


@dataclass(frozen=True)
class ItemSchema:
    """항목 하나의 설정 모양."""

    key: str
    label: str
    spec_ref: str                       # 설계서 몇 번인지 (근거 추적용)
    fields: tuple = field(default_factory=tuple)
    note: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "spec_ref": self.spec_ref,
                "note": self.note, "fields": [f.to_dict() for f in self.fields]}


def _F(*a, **kw):
    return Field(*a, **kw)


# ── 13항목 (설계서 §7) ──────────────────────────────────────────
SCHEMAS: dict = {
    "name": ItemSchema(
        "name", ITEM_LABELS["name"], "§7-1 상품명 조합",
        note="브랜드 + 원본 상품명 순서로 조립. 치환표와 금지어가 여기 붙습니다.",
        fields=(
            # ★ [2026-07-23 리뷰 S2] 기본 순서에서 'model_no'(품번)를 뺐다 —
            #   ProductDraft 에 품번 칸이 아직 없어서(models.py:23~ 전수 확인) 기본값에
            #   넣어 두면 **모든 마켓 행에 「품번 칸이 없습니다」 경고가 상시** 뜬다.
            #   늘 뜨는 경고는 안 읽힌다. 품번 칸이 생기면 설계서 §7-1 대로 되돌린다.
            #   (사장님이 직접 'model_no' 를 넣으면 그때는 진짜 경고로 뜬다.)
            #   ※ [2026-07-24] main(PR#423) 이 같은 줄의 **hint 문구**를 손봤다.
            #     충돌이 나면 **default 는 이 브랜치 것**(model_no 제외)을,
            #     hint 는 main 것을 쓴다 — main 의 default 를 그대로 받으면
            #     위에 적은 상시 경고가 그대로 되살아난다.
            _F("token_order", "조립 순서", "list",
               default=["brand", "origin_name"],
               hint="한 줄에 하나씩 · 위에서 아래 순서로 이어 붙입니다 "
                    "· brand(브랜드) / origin_name(원본 상품명) "
                    "· 사이에 임의 텍스트도 한 줄로 넣을 수 있습니다 "
                    "· 품번(model_no)은 담을 칸이 아직 없습니다"),
            _F("brand_case", "브랜드 영문 표기", "choice", default="upper",
               choices=("upper", "as_is"), hint="upper = 대문자"),
            _F("separator", "구분자", "text", default=" "),
            _F("max_len", "최대 글자수", "int", default=100, unit="자",
               hint="넘으면 뒤에서 자름"),
            _F("dedupe_words", "중복 단어 자동 제거", "bool", default=True),
            _F("replacements", "치환표", "list", default=[],
               hint="예: 재킷 → 자켓 재킷 · 엑셀 업로드/다운로드"),
        )),
    "price": ItemSchema(
        "price", ITEM_LABELS["price"], "§7-2 판매가·마진 (§5 전체 적용)",
        note="★ 기준은 최종매입가입니다(사장님 확정). 마켓마다 다르게 걸 수 있습니다.",
        fields=(
            _F("mode", "방식", "choice", default="margin_rate",
               choices=("margin_rate", "fixed_amount")),
            _F("margin_rate", "마진율", "int", default=25, unit="%",
               hint="최종매입가 기준"),
            _F("fixed_amount", "고정 금액", "int", default=0, unit="원"),
        )),
    "images": ItemSchema(
        "images", ITEM_LABELS["images"], "§7-3 대표이미지",
        note="마켓마다 허용 장수가 다릅니다 — 초과분은 자동 제외합니다.",
        fields=(
            _F("mode", "무엇을 올릴지", "choice", default="rep_only",
               choices=("rep_only", "rep_plus_extra", "range")),
            _F("extra_count", "추가 이미지 장수", "int", default=0, unit="장"),
            _F("range_from", "N번째부터", "int", default=1),
            _F("range_to", "M번째까지", "int", default=1),
            _F("square_crop", "정사각 자르기", "bool", default=True),
            _F("excluded_brands", "이미지 제외 브랜드", "list", default=[],
               hint="모델(사람) 노출 지재권 위험 브랜드"),
        )),
    "detail": ItemSchema(
        "detail", ITEM_LABELS["detail"], "§7-4 상세페이지",
        note="브랜드마다 후크 이미지를 다르게 걸 수 있습니다.",
        fields=(
            _F("mode", "만드는 방식", "choice", default="recombine",
               choices=("recombine", "original", "frame"),
               hint="이미지 재조합 / 원본 통째 / 프레임 템플릿"),
            _F("top_images", "상단 삽입 이미지", "list", default=[]),
            _F("bottom_images", "하단 삽입 이미지", "list", default=[]),
            _F("common_notice", "하단 공통안내 자동", "bool", default=True),
            _F("hide_source_logo", "소싱처 로고 가리기", "bool", default=True),
        )),
    "notice": ItemSchema(
        "notice", ITEM_LABELS["notice"], "§7-5 상품고시정보",
        note="의류·신발·가방잡화·액세서리 4종. 크롤로 채우고 빈 칸은 기본값 · 누락 시 알림.",
        fields=(
            _F("auto_from_crawl", "크롤 값 우선", "bool", default=True),
            _F("warn_on_missing", "누락 시 알림", "bool", default=True),
        )),
    "origin": ItemSchema(
        "origin", ITEM_LABELS["origin"], "§7-6 판매방식·통관",
        fields=(
            _F("mode", "원산지", "choice", default="auto",
               choices=("auto", "fixed"), hint="auto = 크롤/브랜드 기준"),
            _F("fixed_value", "고정값", "text", default=""),
        )),
    "kc": ItemSchema(
        "kc", ITEM_LABELS["kc"], "§7-7 인증·표시정보",
        note="소싱처에서 KC 인증번호를 가져올 수 있으면 반드시 수집·저장합니다.",
        fields=(
            _F("safety_target", "안전기준준수 대상", "bool", default=False),
            _F("collect_kc_no", "KC 인증번호 수집", "bool", default=True),
        )),
    "category": ItemSchema(
        "category", ITEM_LABELS["category"], "§7-8 카테고리",
        note="실패하면 등록하지 않고 보류합니다 — 엉뚱한 카테고리로 올리면 노출이 죽습니다.",
        fields=(
            _F("auto_map", "자동 매핑", "bool", default=True),
            _F("on_fail", "실패했을 때", "choice", default="hold",
               choices=("hold", "default_category")),
        )),
    "options": ItemSchema(
        "options", ITEM_LABELS["options"], "§7-9 옵션(색상·사이즈)",
        fields=(
            _F("combine", "색상 × 사이즈 조합형", "bool", default=True),
            _F("size_order", "사이즈 정렬", "choice", default="small_to_big",
               choices=("small_to_big", "as_is")),
            _F("exclude_soldout", "품절 옵션 제외", "bool", default=True),
            _F("color_image_link", "색상별 대표 이미지 연결", "bool", default=True),
        )),
    "shipping": ItemSchema(
        "shipping", ITEM_LABELS["shipping"], "§7-10 배송·반품·AS",
        note="출고 소요일은 영업일로 셉니다 — 주말·공휴일은 빼고요.",
        fields=(
            _F("fee_mode", "배송비", "choice", default="free",
               choices=("free", "paid", "free_over")),
            _F("fee_amount", "배송비", "int", default=0, unit="원"),
            _F("free_over", "이 금액 이상 무료", "int", default=0, unit="원"),
            _F("return_fee", "반품 배송비", "int", default=5000, unit="원"),
            _F("jeju_extra", "제주 추가", "int", default=3000, unit="원"),
            _F("island_extra", "도서산간 추가", "int", default=5000, unit="원"),
            _F("bundle", "묶음배송", "bool", default=False),
            _F("ship_days", "출고 소요일", "int", default=3, unit="영업일"),
        )),
    "tags": ItemSchema(
        "tags", ITEM_LABELS["tags"], "§7-11 검색태그·키워드",
        note="1차는 스마트스토어 「추천 태그 조회」 API 를 씁니다.",
        fields=(
            _F("auto_generate", "자동 생성", "bool", default=True),
            _F("max_count", "최대 개수", "int", default=10, unit="개",
               hint="마켓 한도까지 채움 (스스 10개)"),
            _F("fixed_tags", "고정 태그", "list", default=[]),
        )),
    "brand": ItemSchema(
        "brand", ITEM_LABELS["brand"], "§7-1 브랜드 표기",
        note="표기를 고르지 않으면 저장된 브랜드를 그대로 씁니다 — 프로그램이 번역해 "
             "지어내지 않습니다.",
        fields=(
            # ★ [2026-07-23 리뷰 C2] 기본값은 **'as_is'(지정 안 함)** 다.
            #   전에는 'korean' 이었다. 그러면 브랜드 규칙을 **기본값 그대로 저장만 해도**
            #   brand='NIKE' 인 상품이 「국문 브랜드명을 넣어 주세요」로 6마켓 전부 막혔다
            #   — 사장님은 국문을 고른 적이 없다. 모르는 것을 「국문 요구」로 단정한
            #   것이라 폴백 금지의 반대 방향 위반이다.
            #   2차 피해가 더 나쁘다: 안내대로 brand 칸을 '나이키' 로 고치면 그 값이
            #   11번가 brand payload(compile_more.py:132-140)와 지재권 제한표 판정으로
            #   그대로 흘러가 실데이터가 오염된다.
            _F("mode", "브랜드 표기", "choice", default="as_is",
               choices=("as_is", "korean", "english", "both"),
               hint="지정 안 함 = 저장된 브랜드를 그대로 씁니다"),
            # ★ [2026-07-24 2차 리뷰 C-new] `position` 에도 **mode 와 똑같은 결함**이
            #   남아 있었다. 기본값이 'front' 라, 브랜드 항목을 **기본값 그대로 저장만
            #   해도** 사장님이 「상품명」에서 직접 정한 조립 순서
            #   ['origin_name','brand'](= 에어포스 1 NIKE)가 **고른 적 없는 'front'** 에
            #   져서 「NIKE 에어포스 1」로 뒤집혔다. 그 정책에 붙은 모든 상품에 번진다.
            #   기본값을 'as_is'(지정 안 함)로 바꿔 **조립 순서를 그대로 따르게** 한다.
            _F("position", "위치", "choice", default="as_is",
               choices=("as_is", "front", "back", "none"),
               hint="지정 안 함 = 「상품명」의 조립 순서를 그대로 따릅니다"),
        )),
    "banned_words": ItemSchema(
        "banned_words", ITEM_LABELS["banned_words"], "§7-1 금지어 2분류",
        note="「수집 금지」는 어느 마켓에도 안 올리고, 「업로드 금지」는 그 마켓만 뺍니다.",
        fields=(
            _F("collect_banned", "수집 금지어", "list", default=[],
               hint="이 단어가 있으면 아예 안 가져옵니다"),
            _F("upload_banned", "업로드 금지어", "list", default=[],
               hint="이 마켓에만 안 올립니다"),
        )),
}

_TYPE_PY = {"bool": bool, "int": int, "text": str, "list": list}


def schema_for(item_key: str) -> ItemSchema:
    """항목 스키마. 모르는 키는 거부한다."""
    key = (item_key or "").strip()
    if key not in SCHEMAS:
        raise ValueError(
            f"모르는 항목입니다: {item_key!r} — 쓸 수 있는 항목: {', '.join(ITEM_KEYS)}")
    return SCHEMAS[key]


def default_config(item_key: str) -> dict:
    """그 항목의 기본값 한 벌."""
    return {f.key: f.default for f in schema_for(item_key).fields}


def validate_config(item_key: str, config: dict) -> dict:
    """설정을 검사하고 **기본값을 채운** 한 벌로 돌려준다.

    ★ 모르는 칸·틀린 형·범위 밖 값은 거부한다. 조용히 저장되면 「왜 안 먹지」가 된다.
    """
    sc = schema_for(item_key)
    known = {f.key: f for f in sc.fields}
    cfg = dict(config or {})

    unknown = sorted(set(cfg) - set(known))
    if unknown:
        raise ValueError(
            f"「{sc.label}」에 모르는 칸이 있습니다: {', '.join(unknown)} — "
            f"쓸 수 있는 칸: {', '.join(known)}")

    out = {}
    for k, f in known.items():
        if k not in cfg or cfg[k] is None:
            out[k] = f.default
            continue
        v = cfg[k]
        if f.type == "choice":
            if v not in f.choices:
                raise ValueError(
                    f"「{sc.label} · {f.label}」 값이 잘못됐습니다: {v!r} — "
                    f"고를 수 있는 값: {', '.join(f.choices)}")
            out[k] = v
            continue
        py = _TYPE_PY[f.type]
        if f.type == "int":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"「{sc.label} · {f.label}」 는 숫자여야 합니다: {v!r}")
            iv = int(v)
            if iv < 0:
                raise ValueError(f"「{sc.label} · {f.label}」 는 음수일 수 없습니다: {v!r}")
            out[k] = iv
            continue
        if not isinstance(v, py):
            raise ValueError(
                f"「{sc.label} · {f.label}」 형이 맞지 않습니다: {type(v).__name__} "
                f"(필요: {f.type})")
        out[k] = v
    return out


def all_schemas() -> list:
    """화면이 폼을 그릴 수 있게 13항목 전부."""
    return [SCHEMAS[k].to_dict() for k in ITEM_KEYS]

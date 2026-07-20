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
        note="브랜드 + 원본 상품명 + 품번 순서로 조립. 치환표와 금지어가 여기 붙습니다.",
        fields=(
            _F("token_order", "조립 순서", "list",
               default=["brand", "origin_name", "model_no"],
               hint="드래그로 순서 변경 · 사이에 임의 텍스트 삽입"),
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
        fields=(
            _F("mode", "브랜드 표기", "choice", default="korean",
               choices=("korean", "english", "both")),
            _F("position", "위치", "choice", default="front",
               choices=("front", "back", "none")),
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

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
    # ── 목록형(type='list') 전용 ──
    #   'text' = 한 줄에 하나씩 적는 1열 목록 (금지어·태그·이미지 주소…)
    #   'pair' = 두 칸짜리 표 (치환표: 찾을 말 → 바꿀 말)
    #   비워두면 'text' 로 본다 — 화면이 어떤 편집칸을 그릴지 이 값으로 정한다.
    item_shape: str = ""
    columns: tuple = ()      # item_shape='pair' 일 때 두 칸의 이름

    def __post_init__(self):
        if self.type != "list":
            return
        if not self.item_shape:
            object.__setattr__(self, "item_shape", "text")
        # ★ 모르는 모양을 조용히 1열로 떨어뜨리면, 오타 난 칸이 엉뚱한 편집기로
        #   그려지고도 아무도 모른다. 스키마를 짤 때 바로 터뜨린다.
        if self.item_shape not in ("text", "pair"):
            raise ValueError(
                f"「{self.label}」 목록 모양이 잘못됐습니다: {self.item_shape!r} "
                f"— 쓸 수 있는 값: text(1열) · pair(2열)")

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "type": self.type,
                "default": self.default, "choices": list(self.choices),
                # 🔴 [2026-08-13] 라벨을 스키마에 실어 보낸다 — 화면이 두 곳이라
                #   각자 목록을 들고 있으면 한쪽만 갱신돼 영어가 샌다(실제로 샜다).
                "choice_labels": {c: CHOICE_LABELS.get(c, c) for c in self.choices},
                "hint": self.hint, "unit": self.unit,
                "item_shape": self.item_shape, "columns": list(self.columns)}


#: 선택지를 사장님 화면에 우리말로 보여 주는 표. **단일 원천.**
#:
#: 🔴 [2026-08-13] 왜 여기 있나 — 3갈래 옵션 축을 열고 보니 정작 사장님 화면엔
#:    `one`·`two`·`three` 가 **영어 그대로** 나왔다. 전수로 세니 13개가 그랬다.
#:    라벨 목록이 화면 파일 안(`bulk/policy_detail.html` 의 JS)에만 있었고,
#:    또 다른 화면(`policy/detail.html`)은 `{{ c }}` 로 **생짜로 찍고** 있었다.
#:    → 표를 스키마 옆으로 옮겨 두 화면이 같은 것을 보게 한다.
#: ★ 뜻은 각 `_F(...)` 의 `hint` 원문 그대로 옮긴다 — 지어내지 않는다.
#: ★ 값 자체가 한글인 선택지(「과세」·「새상품」 등)는 여기 없어도 그대로 보인다.
CHOICE_LABELS = {
    # 글자 다듬기
    "upper": "대문자", "as_is": "원본 그대로",
    "korean": "국문", "english": "영문", "both": "국문+영문",
    "front": "맨 앞", "back": "맨 뒤", "none": "안 붙임",
    # 가격
    "margin_rate": "마진율(%)", "margin_amount": "마진금액 (매입가 + 금액)",
    "fixed_amount": "고정 금액", "fixed_price": "지정가 (이 값으로 못 박음)",
    "cheapest": "가장 싼 곳", "priciest": "가장 비싼 곳", "average": "평균",
    "max": "가장 비싼 값으로", "min": "가장 싼 값으로",
    "WON": "정액 (원)", "PERCENT": "정률 (%)",
    # 옵션 축 — 마켓에 나가는 그룹 이름과 **같은 글자**로 둔다
    #   (`options.py` 의 _ONE_GROUP·_MODEL_GROUP·_COLOR_GROUP·_SIZE_GROUP)
    "one": "한 갈래 (메이트 블랙 260)", "two": "색상 · 사이즈",
    "three": "모델명 · 색상 · 사이즈",
    "into_price": "판매가에 합침",
    # 이미지
    "rep_only": "대표만", "rep_plus_extra": "대표 + 추가", "range": "N~M번째",
    "recombine": "이미지 재조합", "original": "원본 통째", "frame": "프레임 템플릿",
    # 그 밖
    "auto": "자동(크롤·브랜드)", "fixed": "고정값", "hold": "보류 (안 올림)",
    "default_category": "기본 카테고리로", "small_to_big": "작은 → 큰",
    "free": "무료", "paid": "유료(1개당)", "free_over": "N원 이상 무료",
}


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
            #   [머지 2026-07-24] default 는 이 브랜치(model_no 제외), hint 는 main 문구를
            #   따르되 「품번 칸이 아직 없다」는 정직한 한 줄을 유지한다(3차 리뷰 확인).
            _F("token_order", "조립 순서", "list",
               default=["brand", "origin_name"],
               hint="한 줄에 하나씩 · 위에서 아래 순서로 이어 붙입니다 "
                    "· brand(브랜드) / origin_name(원본 상품명) "
                    "· 사이에 임의 텍스트도 한 줄로 넣을 수 있습니다 "
                    "· 품번(model_no)은 담을 칸이 아직 없습니다"),
            _F("brand_case", "브랜드 영문 표기", "choice", default="upper",
               choices=("upper", "as_is"),
               hint="upper = 대문자 · 브랜드 「위치/표기」를 지정 안 하면 "
                    "대소문자도 원본 그대로 둡니다"),
            _F("separator", "구분자", "text", default=" "),
            _F("max_len", "최대 글자수", "int", default=100, unit="자",
               hint="넘으면 뒤에서 자름"),
            _F("dedupe_words", "중복 단어 자동 제거", "bool", default=True),
            _F("replacements", "치환표", "list", default=[],
               item_shape="pair", columns=("찾을 말", "바꿀 말"),
               hint="예: 재킷 → 자켓 · 바꿀 말을 비우면 그 말을 지웁니다 "
                    "· 엑셀에서 두 열을 복사해 붙여넣어도 됩니다"),
        )),
    "price": ItemSchema(
        "price", ITEM_LABELS["price"], "§7-2 판매가·마진 (§5 전체 적용)",
        note="★ 기준은 최종매입가입니다(사장님 확정). 소싱품과 사입품은 매입 구조가 "
             "달라 따로 정합니다 — 한 값으로 묶으면 사입품 마진이 틀어집니다.",
        fields=(
            # [2026-08-01] 가격 템플릿(115칸)이 가진 것을 정책이 다 담게 넓혔다.
            #   사장님 확정 — 「우리 정책이 가격 템플릿보다 큰 범위여야 한다」.
            #   옛 칸(mode/margin_rate/fixed_amount)으로 저장된 값은
            #   lemouton/policy/price_cfg.py 가 새 칸으로 번역해 읽는다.
            # ── 소싱품 (소싱처에서 사서 바로 보내는 상품) ──
            _F("sourcing_mode", "소싱품 정하는 법", "choice", default="margin_rate",
               choices=("margin_rate", "margin_amount", "fixed_price"),
               hint="마진율 = 매입가 × (1+율) · 마진금액 = 매입가 + 금액 · "
                    "지정가 = 이 값으로 못 박음"),
            # [2026-08-02] 사장님 확정 — 「마진율도 정책별로 다르게 내가 넣는다」.
            #   기본값을 지어내지 않는다. 다만 **비워두면 무슨 값이 쓰이는지는 밝힌다** —
            #   빈칸을 보는 동안 속으로 다른 숫자가 쓰이면 화면이 거짓말하는 것이다.
            _F("sourcing_rate", "소싱품 마진율", "int", default=None, unit="%",
               hint="최종매입가 기준 · 비워두면 마켓 기본(스스 9.45 · 나머지 12.42)으로 "
                    "계산됩니다 — 정책마다 직접 넣어 주세요"),
            _F("sourcing_amount", "소싱품 마진금액", "int", default=None, unit="원"),
            _F("sourcing_fixed", "소싱품 지정가", "int", default=None, unit="원"),
            # ── 사입품 (우리가 미리 사둔 재고) ──
            _F("purchase_mode", "사입품 정하는 법", "choice", default="margin_rate",
               choices=("margin_rate", "margin_amount", "fixed_price")),
            _F("purchase_rate", "사입품 마진율", "int", default=None, unit="%",
               hint="비워두면 마켓 기본(스스 9.45 · 나머지 12.42)으로 계산됩니다"),
            _F("purchase_amount", "사입품 마진금액", "int", default=None, unit="원"),
            _F("purchase_fixed", "사입품 지정가", "int", default=None, unit="원"),
            # [2026-07-31] 노션 「(3) 마켓별 가격 정책 — 마켓별수수료」.
            #   넣을 칸이 아예 없어서, 사장님이 수수료율을 주셔도 저장할 곳이 없었다.
            # [2026-08-02] 사장님이 마켓별 실제 요율을 확정했다:
            #   스스 6 · 쿠팡 11.55 · 롯데온 18(제휴 2 포함) · 11번가 8 ·
            #   옥션 15(제휴 2 포함) · G마켓 15(제휴 2 포함)
            #   🔴 **여기에 숫자를 적지 않는다.** 항목표는 마켓을 모른다 — 한 숫자를 적으면
            #     어느 마켓에서든 그 값이 뜨고, 사장님이 보는 값과 계산에 쓰는 값이
            #     어긋난다(2026-08-02 실제로 났던 사고).
            #     표는 `lemouton/pricing/fee_defaults.py`(화면에서 고침) 한 곳뿐이고,
            #     화면은 `default_fee_pct(마켓)` 으로 그 마켓 값을 받아 채운다.
            _F("fee_rate", "수수료율", "int", default=None, unit="%",
               hint="카테고리·제휴이벤트에 따라 달라지니 실제 요율로 고쳐 주세요"),
            # ── 가격 안전장치 (확정 J3 — 접지 않고 항상 보인다) ──
            #   🔴 배송비·반품비·교환비는 여기 두지 않는다. 「배송」 항목에 이미 있어
            #     중복이 된다 — 가격 계산은 「배송」 항목의 값을 읽는다.
            _F("floor_price", "안 내려갈 값", "int", default=None, unit="원",
               hint="이 밑으로는 안 나갑니다"),
            _F("cap_price", "안 올라갈 값", "int", default=None, unit="원"),
            _F("rounding_unit", "끝자리 맞춤", "int", default=100, unit="원",
               hint="이 단위로 버립니다 (100 = 100원 단위)"),
            _F("normal_price", "정상가", "int", default=None, unit="원",
               hint="할인 전 표시가. 안 정하면 마켓에 보내지 않습니다"),
            _F("source_pick", "여러 소싱처일 때", "choice", default="cheapest",
               choices=("cheapest", "priciest", "average"),
               hint="한 옵션에 소싱처가 여럿일 때 어느 매입가로 계산할지"),
            # [2026-08-01] 확정 K3 — 스스 전용 항목이던 「사이즈별 가격 통일」을
            #   판매가 안으로 들였다. 가격을 정하는 규칙이 판매가와 떨어져 있으면
            #   판매가만 채우고 지나친다. 가격 템플릿은 6마켓 모두 이 규칙을 갖고 있었다.
            _F("size_unify", "사이즈별 가격 통일", "choice", default="",
               choices=("", "max", "min"),
               hint="사이즈마다 매입가가 다를 때 — 비우면 통일 안 함 · "
                    "max = 가장 비싼 값으로 · min = 가장 싼 값으로"),
            # [2026-08-06] 사장님 확정 — 「즉시할인은 판매가 안에. 굳이 구분할 필요 없다」
            #   (K3 와 같은 이유로 판매가 항목 안에 둔다).
            #   🔴 위 `normal_price`(정상가)와 **다른 것**이다:
            #     정상가 = 마켓에 「원래 이 값이었다」고 보여주는 **표시용 숫자**
            #     즉시할인 = 실제로 깎여서 **고객이 내는 돈이 줄어드는** 값
            #     같은 뜻으로 두 칸을 두면 어느 쪽이 진짜인지 모르게 된다 — 구분을 못 박는다.
            #   마켓별 나가는 자리(지도 실측):
            #     스스   = customerBenefit.immediateDiscountPolicy.discountMethod
            #     쿠팡   = 즉시할인쿠폰을 만들어 옵션(vendorItemId)에 붙임
            #              ⏰ 쿠팡은 **다음날 0시부터** 적용(문서 명시) — 화면이 알린다
            #     나머지 = 아직 실측 안 됨 → 보내지 않는다(날조 금지)
            _F("discount_unit", "즉시할인 방식", "choice", default="WON",
               choices=("WON", "PERCENT"),
               hint="WON = 정액(원) · PERCENT = 정률(%)"),
            _F("discount_value", "즉시할인 깎을 값", "int", default=None,
               hint="비우면 할인 없음. 판매가는 그대로 두고 고객가만 깎습니다"),
        )),
    "images": ItemSchema(
        "images", ITEM_LABELS["images"], "§7-3 대표이미지",
        note="마켓마다 허용 장수가 다릅니다 — 초과분은 자동 제외합니다.",
        fields=(
            # 🔴 [2026-08-13 사장님 확정] 기본값 `rep_only`(대표 1장만)는 **사장님 뜻과 다르다.**
            #   사장님 확정 = 「사진 전량 그대로」. 지금은 이 규칙이 모음전 전송에
            #   안 먹어서(초안이 옵션 사진을 다시 모아 씀) 눈에 안 띌 뿐이다.
            #   ★ 이 규칙을 실제로 이을 때 **기본값을 「전부 올리기」로 바꿔야 한다** —
            #     안 바꾸고 이으면 사진 전량이 나가던 스마트스토어가 1장으로 줄어든다.
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
            # 노션 「(3) 마켓별 가격 정책 — 옵션별 추가금」.
            #   값 자체는 옵션에 이미 있다(extra_price). 정책이 정하는 것은
            #   **그 값을 마켓에 어떻게 보낼지**다.
            _F("extra_price_mode", "옵션별 추가금", "choice", default="as_is",
               choices=("as_is", "into_price"),
               hint="as_is = 옵션 추가금 그대로 전달 · into_price = 판매가에 합치고 "
                    "추가금 0 (옵션마다 값이 갈리는 마켓용)"),
            # 노션 「(1) 마켓별 옵션 1/2/3축 구성 정책」 + ①「기본적으로 1축 구성
            #   옵션번호지만 마켓별 업로드 시 2/3축으로 쪼갤 수 있음」.
            #   우리 옵션번호는 언제나 하나다 — 바뀌는 건 **구매자에게 보이는 갈래 수**뿐.
            _F("axis", "옵션 축 구성", "choice", default="two",
               choices=("one", "two", "three"),
               hint="one = 한 갈래(「메이트 블랙 260」) · two = 색상·사이즈 두 갈래(기본) · "
                    "three = 모델명·색상·사이즈 세 갈래 (스마트스토어만 — "
                    "다른 마켓은 두 갈래로 나갑니다)"),
        )),
    "shipping": ItemSchema(
        "shipping", ITEM_LABELS["shipping"], "§7-10 배송·반품·AS",
        note="출고 소요일은 영업일로 셉니다 — 주말·공휴일은 빼고요.",
        fields=(
            _F("fee_mode", "배송비", "choice", default="free",
               choices=("free", "paid", "free_over")),
            # [2026-08-02] 사장님 확정 — 「배송비도 정책별로 다르게 내가 넣는다」.
            #   이 값은 판매가 계산에 그대로 더해진다(unified: raw = base + shipping_fee).
            _F("fee_amount", "배송비", "int", default=0, unit="원",
               hint="판매가에 더해집니다 · 정책마다 다르면 정책을 따로 만들어 주세요"),
            _F("free_over", "이 금액 이상 무료", "int", default=0, unit="원"),
            _F("return_fee", "반품 배송비", "int", default=5000, unit="원"),
            _F("jeju_extra", "제주 추가", "int", default=3000, unit="원"),
            _F("island_extra", "도서산간 추가", "int", default=5000, unit="원"),
            _F("bundle", "묶음배송", "bool", default=False),
            _F("ship_days", "출고 소요일", "int", default=3, unit="영업일"),
            # [2026-07-31] 노션 「(2) 마켓별 기본 정책」에 있는데 칸이 없던 것들 —
            #   배송(기간, **출하지**) / 반품교환(**택배사, 회송지**).
            #   🔴 주소·택배사는 지어낼 수 없는 값이라 기본값을 두지 않는다. 비어 있으면
            #     「안 정함」이고, 그 상태로는 마켓에 보내지 않는다(가짜 주소 금지).
            _F("ship_from", "출하지 주소", "text", default="",
               hint="상품이 나가는 곳. 비워두면 마켓 계정에 등록된 출고지를 씁니다"),
            _F("return_to", "반품 회송지 주소", "text", default="",
               hint="반품이 돌아오는 곳. 비워두면 출하지와 같다고 보지 않습니다 — "
                    "마켓 계정 설정을 씁니다"),
            _F("courier", "반품·교환 택배사", "text", default="",
               hint="예: CJ대한통운 · 비워두면 마켓 기본 택배사"),
            _F("exchange_fee", "교환 배송비", "int", default=None, unit="원",
               hint="비워두면 반품 배송비의 2배로 봅니다(지금 동작)"),
            # 노션 「AS안내메세지(스스:A/S번호포함)」 — 이 항목 제목이 「배송·반품·AS」다.
            #   🔴 전화번호에 폴백을 두지 않는다. 실제 판매 상품에 가짜 번호를 게시하는
            #     일이 되기 때문이다(compile_smartstore 가 같은 이유로 막고 있다).
            _F("as_phone", "A/S 전화번호", "text", default="",
               hint="스마트스토어는 필수입니다. 지어내지 않으니 꼭 실제 번호를 넣어 주세요"),
            _F("as_guide", "A/S 안내 문구", "text", default="",
               hint="반품·교환 안내문. 마켓마다 길이 제한이 다릅니다"),
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
    # ══ [2026-08-12] 사장님 엑셀 「마켓별 상품등록 정보」 대조로 추가 ══════════
    #   근거 = 각 마켓 **상품등록 API 원문**(webapp/data/marketplace_api_map.json).
    #   필수 판정과 그 근거는 `lemouton/policy/required.py` 가 따로 들고 있다.
    #   🔴 기본값은 사장님이 엑셀에 적어 두신 값 그대로다 — 지어내지 않았다.
    "listing": ItemSchema(
        "listing", ITEM_LABELS["listing"], "§7-6 판매방식·통관 (엑셀 O·N·R·Q열)",
        note="상품마다 거의 안 바뀌는 값들입니다 — 한 번 정해 두면 손 갈 일이 없습니다.",
        fields=(
            # 쿠팡 items.taxType[필수] · 옥션/G마켓 isVatFree[필수] · 11번가 suplDtyfrPrdClfCd[필수]
            # 🔴 [2026-08-13 사장님 확정] 「영세」를 뺐다.
            #   영세율은 수출·외화획득 거래에 쓰는 것이라 국내 마켓 소매엔 해당이 없고,
            #   무엇보다 **쿠팡·옥션·G마켓엔 영세를 보낼 칸 자체가 없다**
            #   (쿠팡 TAX/FREE 둘 · ESM isVatFree 는 참/거짓). 선택지에 남겨 두면
            #   고른 값과 나가는 값이 갈려 「고쳤는데 왜 안 먹지」가 된다.
            _F("tax_type", "과세구분", "choice", default="과세",
               choices=("과세", "면세"),
               hint="기본은 과세입니다. 면세는 도서·농수산물 같은 부가세 면세 품목에만 쓰세요"),
            # 🔴 [2026-08-13 사장님 확정] 「상품상태」·「판매기간」을 여기서 뺐다.
            #   · 상품상태 = 무조건 새상품 · 판매기간 = 마켓마다 가장 긴 것으로 자동.
            #   고를 것이 하나뿐인 칸을 남기면 사장님이 바꿀 수 있다고 오해한다.
            #   대신 무엇이 나가는지는 `policy/fixed_sends.py`(「정해져 나가는 값」)가
            #   화면에 그대로 보여준다 — 빼기만 하고 안 보여주면 「어디 갔지」가 된다.
            # 스스 minorPurchasable[필수] · 쿠팡 adultOnly[필수] · 11번가 minorSelCnYn[필수]
            _F("minor_purchase", "미성년자 구매", "choice", default="전연령 구매 가능",
               choices=("전연령 구매 가능", "19세 이상만"),
               hint="성인 카테고리 상품은 마켓이 강제로 19세 이상으로 돌립니다"),
            # 쿠팡 manufacture — 「정확한 제조사를 못 적으면 brand 와 동일하게 입력 가능」
            _F("manufacturer_mode", "제조사", "choice", default="브랜드와 동일",
               choices=("브랜드와 동일", "직접 입력"),
               hint="쿠팡 문서가 「제조사를 모르면 브랜드와 동일하게」라고 안내합니다"),
            _F("manufacturer_fixed", "제조사 직접 입력", "text", default="",
               hint="위에서 「직접 입력」을 고른 경우에만 씁니다"),
        )),
    "price_compare": ItemSchema(
        "price_compare", ITEM_LABELS["price_compare"], "§7-6 판매방식·통관 (엑셀 M열)",
        note="가격비교에 걸면 노출이 늘지만 수수료가 더 붙습니다.",
        fields=(
            # 스스 naverShoppingRegistration[필수] · 11번가 prcCmpExpYn(선택) · ESM pcs>isUse
            #   🔴 쿠팡 등록 API 에는 이 개념 자체가 없다 — 사장님 엑셀도 X 로 적혀 있다.
            _F("expose", "가격비교 노출", "bool", default=True,
               hint="사장님 확정 = 노출 · 스스(필수)·11번가·옥션·G마켓에 나갑니다 "
                    "· 쿠팡은 등록 API 에 이 칸이 없어 아무 일도 안 합니다 "
                    "· 롯데ON 은 등록 필드를 아직 확인 못 해 안 보냅니다"),
            # [2026-08-24 지도 전문 실측] 11번가 prcDscCmpExpYn · 옥션 isUseIacPcsCoupon.
            #   🔴 G마켓 쿠폰 칸(isUseGmkPcsCoupon)은 지도에 「사용불가」 — 마켓이
            #     설정을 막아 뒀다. 노출 여부만 가능하다.
            _F("coupon", "가격비교 쿠폰 적용", "bool", default=None,
               hint="가격비교 사이트에서 쿠폰 할인을 적용할지 · 11번가·옥션만 정할 수 "
                    "있습니다(G마켓은 마켓이 설정을 막아 뒀습니다) "
                    "· 안 정하면 그 칸을 아예 안 보냅니다"),
            _F("fee_add_pct", "가격비교 수수료 가산", "int", default=2, unit="%",
               hint="사장님 엑셀 = 롯데온·11번가 2%. 🔴 지금은 적어 두기만 하고 "
                    "판매가 계산에는 아직 안 들어갑니다"),
        )),
    "ids": ItemSchema(
        "ids", ITEM_LABELS["ids"], "§7-11 식별번호 (엑셀 V·W열)",
        note="상품마다 값이 달라 정책은 「빈칸일 때 어떻게 할지」만 정합니다.",
        fields=(
            # 11번가 modelNm — 「모델명이 없을 시 "없음"으로 입력합니다」
            _F("model_mode", "모델번호", "choice", default="없으면 「없음」",
               choices=("없으면 「없음」", "없으면 비워 둠"),
               hint="11번가는 빈칸을 받지 않아 「없음」이라고 적어야 합니다"),
            # 쿠팡 emptyBarcode(없으면 true) + emptyBarcodeReason
            _F("barcode_mode", "바코드", "choice", default="없다고 밝힘",
               choices=("없다고 밝힘", "없으면 비워 둠"),
               hint="쿠팡은 바코드가 없으면 「없음」이라고 밝히는 칸이 따로 있습니다"),
            _F("barcode_empty_reason", "바코드 없는 사유", "text", default="자체 제작 상품",
               hint="쿠팡 전용 · 100자 제한"),
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


def _dup_notice(where: str, values: list, notices: list) -> None:
    """같은 말이 여러 번 있으면 **막지 않고 알린다** — 사장님 의도일 수 있다."""
    seen = {}
    for v in values:
        seen[v] = seen.get(v, 0) + 1
    dups = [v for v in dict.fromkeys(values) if seen[v] > 1]
    for v in dups:
        notices.append(f"{where} 「{v}」 가 {seen[v]}번 있습니다 — 그대로 저장했습니다.")


def _reject_tab(where: str, line_no: int, text: str, what: str = "") -> None:
    """🔴 줄 **안쪽** 탭은 거부한다.

    엑셀에서 두 열을 복사해 1열 목록에 붙이면 `짝퉁\\t가품` 이 한 덩어리로 들어온다.
    화면에선 탭이 넓은 공백처럼 보여 「두 단어」로 읽히는데, 저장은 한 개다.
    조용히 들어가면 나중에 가공 엔진이 이 금지어로 **영원히 못 걸러낸다.**
    """
    if "\t" not in text:
        return
    raise ValueError(
        f"{where} {line_no}번째 줄{what}에 탭(칸 나눔)이 들어 있습니다 — "
        f"두 열을 붙여넣으신 것 같습니다. 한 줄에 하나씩 적어주세요.")


def _clean_text_list(where: str, value: list, notices: list) -> list:
    """1열 목록. 앞뒤 공백·빈 줄만 지우고 **순서는 건드리지 않는다**."""
    out, trimmed, dropped = [], 0, 0
    for i, v in enumerate(value):
        if not isinstance(v, str):
            raise ValueError(
                f"{where} {i + 1}번째 줄은 글자여야 합니다: {v!r}")
        _reject_tab(where, i + 1, v)
        s = v.strip()
        if s != v:
            trimmed += 1
        if not s:
            dropped += 1
            continue
        out.append(s)
    if trimmed:
        notices.append(f"{where} {trimmed}줄의 앞뒤 공백을 지웠습니다.")
    if dropped:
        notices.append(f"{where} 빈 줄 {dropped}개를 뺐습니다.")
    _dup_notice(where, out, notices)
    return out


def _clean_pair_list(where: str, cols: tuple, value: list, notices: list) -> list:
    """2열 표(치환표). 아무것도 안 적은 줄만 빼고, 나머지는 적은 그대로 둔다."""
    left = cols[0] if cols else "왼쪽 칸"
    out, trimmed, dropped = [], 0, 0
    for i, row in enumerate(value):
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError(
                f"{where} {i + 1}번째 줄은 두 칸(「{left}」·「{cols[1] if cols else '오른쪽 칸'}」)"
                f"이어야 합니다: {row!r}")
        a, b = row
        if not isinstance(a, str) or not isinstance(b, str):
            raise ValueError(f"{where} {i + 1}번째 줄은 글자여야 합니다: {row!r}")
        _reject_tab(where, i + 1, a, f" 「{left}」")
        _reject_tab(where, i + 1, b, f" 「{cols[1] if cols else '오른쪽 칸'}」")
        sa, sb = a.strip(), b.strip()
        if sa != a or sb != b:
            trimmed += 1
        if not sa and not sb:
            dropped += 1
            continue
        if not sa:
            raise ValueError(
                f"{where} {i + 1}번째 줄 — 「{left}」이(가) 비었습니다. "
                f"무엇을 바꿀지 적어주세요.")
        out.append([sa, sb])
    if trimmed:
        notices.append(f"{where} {trimmed}줄의 앞뒤 공백을 지웠습니다.")
    if dropped:
        notices.append(f"{where} 아무것도 안 적은 빈 줄 {dropped}개를 뺐습니다.")
    _dup_notice(where, [r[0] for r in out], notices)
    return out


def validate_config(item_key: str, config: dict, *, notices: list = None) -> dict:
    """설정을 검사하고 **기본값을 채운** 한 벌로 돌려준다.

    ★ 모르는 칸·틀린 형·범위 밖 값은 거부한다. 조용히 저장되면 「왜 안 먹지」가 된다.

    Args:
        notices: 리스트를 주면 **프로그램이 손댄 내용**을 여기에 적어 준다
            (빈 줄 제거·앞뒤 공백 제거·같은 말 중복). 화면이 그대로 띄운다 —
            사장님이 넣은 값을 몰래 고치면 안 되므로, 고쳤으면 반드시 알린다.

    ★ 목록 검사 규칙은 **여기 한 벌뿐이다.** 화면은 검사하지 않고 이 결과만 보여준다.
    """
    if notices is None:
        notices = []
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
            # ★ 목록 기본값은 **복사해서** 넘긴다. 그대로 넘기면 스키마에 박힌
            #   그 리스트를 호출한 쪽이 고칠 수 있어, 온 프로그램의 기본값이 오염된다.
            out[k] = list(f.default) if isinstance(f.default, list) else f.default
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
        if f.type == "list":
            where = f"「{sc.label} · {f.label}」"
            out[k] = (_clean_pair_list(where, f.columns, v, notices)
                      if f.item_shape == "pair"
                      else _clean_text_list(where, v, notices))
            continue
        out[k] = v
    return out


def all_schemas() -> list:
    """화면이 폼을 그릴 수 있게 전 항목(ITEM_KEYS 순서 그대로)."""
    return [SCHEMAS[k].to_dict() for k in ITEM_KEYS]

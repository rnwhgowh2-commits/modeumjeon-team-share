"""미확정 상품명에서 브랜드 후보를 추출·순위화한다.
'매장정품/국내매장판/정품 + 브랜드후보' 패턴으로 후보 토큰을 뽑고, 일반 단어(성별·의류종류)는 제외."""
import re
import collections

# 브랜드 표준 한글명 — 영문→한글, 하위라인→상위 브랜드. 분산(같은 브랜드가 여러 줄) 방지.
BRAND_ALIAS = {
    # 영문 → 한글
    "CHAMPION": "챔피언", "LULULEMON": "룰루레몬", "DICKIES": "디키즈", "DAKS": "닥스",
    "SALOMON": "살로몬", "LACOSTE": "라코스테", "COVERNAT": "커버낫", "ARENA": "아레나",
    "NIKE": "나이키", "ADIDAS": "아디다스", "PUMA": "푸마", "LEE": "리", "EIDER": "에이더",
    "KODAK": "코닥", "JANSPORT": "잔스포츠", "TOPTEN": "탑텐", "TRILLION": "트릴리온",
    "ASICS": "아식스", "CONVERSE": "컨버스", "GUESS": "게스",
    "KEEN": "킨", "LEMOUTON": "르무통", "PATAGONIA": "파타고니아", "JEEP": "지프", "JEEPKIDS": "지프키즈",
    # 나이키 하위 라인 → 나이키
    "NSW": "나이키", "조던": "나이키", "에어포스": "나이키", "에어맥스": "나이키",
    "덩크": "나이키", "코르테즈": "나이키", "P-6000": "나이키", "드라이핏": "나이키", "드라이 핏": "나이키",
    # 아디다스 하위 → 아디다스
    "아디컬러": "아디다스", "삼바": "아디다스",
}


def normalize_brand(keyword: str) -> str:
    """키워드를 표준 한글 브랜드명으로. 매핑 없으면 키워드 그대로(한글 브랜드는 이미 정상)."""
    if keyword is None:
        return ""
    k = str(keyword).strip()
    return BRAND_ALIAS.get(k) or BRAND_ALIAS.get(k.upper()) or k


# 브랜드가 아닌 일반 단어 (후보에서 제외)
STOPWORDS = {
    "남성","여성","남녀","공용","아동","키즈","주니어","남아","여아","성인","우먼","우먼스","맨즈","우먼즈",
    "반팔","긴팔","반바지","긴바지","기모","집업","후드","맨투맨","니트","패딩","자켓","점퍼","코트","팬츠",
    "티셔츠","셔츠","원피스","스커트","드라이","베이직","오버핏","릴렉스핏","슬림핏","레귤러핏","미니","라운드",
}

_PREFIX = re.compile(r'(?:매장정품|국내매장판|정품)\s*[>]?\s*([가-힣A-Za-z]{2,12})')
_GENDER = re.compile(r'(?:남성|여성|남녀|공용|아동|키즈|주니어)\s+([가-힣A-Za-z]{2,12})')


def _candidate(name: str):
    """상품명에서 브랜드 후보 토큰 1개 추출 (없으면 None)."""
    m = _PREFIX.search(name)
    if not m:
        return None
    w = m.group(1)
    if w in STOPWORDS:
        m2 = _GENDER.search(name)
        if m2 and m2.group(1) not in STOPWORDS:
            return m2.group(1)
        return None
    return w


def suggest_from_names(names, extract_fn, top: int = 30):
    """미확정으로 분류되는 상품명들에서 브랜드 후보를 빈도순으로 반환.

    names: iterable[str] (더망고 마켓상품명)
    extract_fn: callable(name)->str, '미확정' 이면 미분류
    returns: {"suggestions":[{"keyword":str,"count":int}], "unresolvable":int, "total_unclassified":int,
              "unresolved_products":[{"name":str,"count":int}]}
    """
    cand = collections.Counter()
    unresolved_counter = collections.Counter()
    unresolvable = 0
    total = 0
    for n in names:
        if extract_fn(n) != "미확정":
            continue
        total += 1
        c = _candidate(str(n))
        if c:
            cand[c] += 1
        else:
            unresolvable += 1
            unresolved_counter[str(n)] += 1
    sugg = [{"keyword": k, "count": v, "brand": normalize_brand(k)} for k, v in cand.most_common(top)]
    unresolved_products = [{"name": k, "count": v} for k, v in unresolved_counter.most_common(50)]
    return {
        "suggestions": sugg,
        "unresolvable": unresolvable,
        "total_unclassified": total,
        "unresolved_products": unresolved_products,
    }

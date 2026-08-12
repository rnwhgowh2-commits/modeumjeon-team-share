# -*- coding: utf-8 -*-
"""개발 체크리스트 — 셀 판정 (순수 함수, Flask 의존 없음).

🔴 여기 WIRED 는 화면 6상태 중 하나이고, required.WIRED 는 배선 2상태 중 하나다.
  문자열이 우연히 같을 뿐 다른 개념이다 — 비교는 반드시 심볼로 한다.
"""
from __future__ import annotations

import json
import os

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                     "webapp", "data")


def load_columns(name: str = "dev_checklist_columns.json") -> list[dict]:
    """열 정의 한 벌. 열 번호가 겹치면 **터뜨린다.**

    🔴 `cells` 는 `<마켓>:<열번호>` 로 키를 잡는다 — 번호가 겹치면 뒤 열이 앞 열을
      조용히 덮어써서 칸이 사라지는데, `counts` 는 두 열을 다 세므로 개수만 보면
      아무도 못 알아챈다. 손으로 쓰는 판(소싱처 등)이 늘어날수록 위험하다.
    """
    with open(os.path.join(_DATA, name), encoding="utf-8") as f:
        cols = json.load(f)["columns"]
    nums = [c["col"] for c in cols]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    if dup:
        raise ValueError(f"{name} 에 열 번호가 겹칩니다: {dup}")
    return cols


from lemouton.policy import required as _req

#: 칸 상태 — 화면 표시와 뜻
NA = "na"                  # ➖ 해당없음    : 엑셀이 비었거나 「-」
IMPOSSIBLE = "impossible"  # ⚫ 불가        : 엑셀이 「X」 (마켓에 기능 자체가 없음)
TODO = "todo"              # ⬜ 미착수      : 우리 칸이 없거나 마켓 근거를 못 찾음
STORED = "stored"          # 🟡 저장만 됨   : 칸은 있는데 보내는 코드가 없음
WIRED = "wired"            # 🟢 나감(미검증) : 보내지만 실계정 확인 전
DONE = "done"              # 🟢 검증완료    : 보내고 실계정으로 확인함

_BLANK = ("", "-")

#: 배선 3번째 값 — 프로그램에 담을 칸조차 없다. `required.WIRED`/`STORED_ONLY` 와 같은 축.
#:
#: 🔴 여기를 빈 문자열로 내보내면 안 된다. 화면이 `wiring != 'wired'` 로 「저장만 됨」을
#:   그리기 때문에, **칸이 아예 없는 것**이 「저장은 된다」는 거짓말로 뜬다.
WIRING_NONE = "none"
WIRING_NONE_NOTE = "프로그램에 담을 칸이 아직 없습니다"


def _spec(market: str, col: dict) -> str:
    """그 마켓의 엑셀 메모. 모르는 마켓 이름이면 **터뜨린다.**

    🔴 조용히 빈 문자열로 떨어뜨리면 「모른다」가 「해당없음」으로 둔갑한다.
      오타 난 마켓 키가 화면에 ➖ 로 뜨면 아무도 못 알아챈다.
    """
    specs = col.get("specs") or {}
    if market not in specs:
        raise KeyError(
            f"「{col.get('name', '?')}」 열에 마켓 {market!r} 가 없습니다 — "
            f"있는 마켓: {', '.join(sorted(specs)) or '(없음)'}")
    return (specs[market] or "").strip()


def cell_state(market: str, col: dict, marks: dict | None = None) -> str:
    """그 칸의 상태 하나. 판정 순서를 바꾸지 말 것 — 앞 조건이 뒤를 가린다."""
    spec = _spec(market, col)
    if spec in _BLANK:
        return NA
    if spec.upper() == "X":
        return IMPOSSIBLE
    item = col.get("item")
    if not item:
        return TODO                       # 프로그램에 담을 칸이 아직 없다
    status, _evidence, _note = _req.status_of(market, item)
    if status == _req.UNKNOWN:
        return TODO                       # 「없다」가 아니라 「모른다」 — 지어내지 않는다
    if _req.wiring_of(item)[0] != _req.WIRED:
        return STORED                     # 채워도 안 나간다
    key = f"{market}:{col['col']}"
    if ((marks or {}).get(key) or {}).get("verified"):
        return DONE
    return WIRED


def conflict_of(market: str, col: dict) -> str:
    """우리 기준과 마켓 문서가 어긋나는가. 기계 판정만 — 추측하지 않는다.

    CONDITIONAL(「~인 경우 필수」)은 **일부러 안 잡는다** — 조건이 맞는지는 기계가 못 정한다.
    """
    item = col.get("item")
    if not item:
        return ""
    spec = _spec(market, col)
    status, _e, _n = _req.status_of(market, item)
    if spec in _BLANK or spec.upper() == "X":
        if status == _req.REQUIRED:
            return "마켓 문서는 [필수]라는데 우리는 안 쓰기로 돼 있습니다"
    return ""


MARKETS = [("coupang", "쿠팡"), ("smartstore", "스마트스토어"), ("lotteon", "롯데온"),
           ("eleven11", "11번가"), ("auction", "옥션"), ("gmarket", "G마켓")]


def load_marks(name: str = "dev_checklist_marks.json") -> tuple[dict, str]:
    """(손보정, 못 읽은 이유). 파일이 없으면 ``({}, "")`` — 아직 아무도 안 달았다는 뜻.

    🔴 오타 한 칸이 표 전체를 가리면 안 된다. 못 읽으면 표는 그대로 그리되
      **왜 못 읽었는지를 배너로 올린다**(조용히 빈 것으로 치지 않는다).
      이 파일은 사람이 손으로 고치는 파일이라(`_설명` 참조) 오타가 정상 상황이다.
    """
    path = os.path.join(_DATA, name)
    if not os.path.exists(path):
        return {}, ""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return {}, (f"손보정 파일({name})을 읽지 못했습니다 — {e}. "
                    f"고칠 때까지 손보정은 반영되지 않습니다")
    if not isinstance(raw, dict) or "marks" not in raw:
        return {}, (f"손보정 파일({name})에 marks 가 없습니다 — "
                    f"「비어 있음」이 아니라 잘못 고쳐진 것입니다")
    marks = raw["marks"]
    if not isinstance(marks, dict):
        return {}, (f"손보정 파일({name})의 marks 가 표가 아닙니다 — "
                    f"「\"<마켓>:<열번호>\": {{…}}」 묶음이어야 합니다. "
                    f"고칠 때까지 손보정은 반영되지 않습니다")
    bad = sorted(k for k, v in marks.items() if not isinstance(v, dict))
    if bad:
        return {}, (f"손보정 파일({name})의 값이 묶음이 아닌 칸이 있습니다: "
                    f"{', '.join(bad)} — 「{{\"verified\": \"YYYY-MM-DD\"}}」 처럼 "
                    f"적어야 합니다. 고칠 때까지 손보정은 반영되지 않습니다")
    return marks, ""


#: 열 정의에 그 마켓 칸이 아예 없을 때 셀에 적는 말.
#: 🔴 「해당없음(➖)」으로 지어내지 않는다 — 빠진 것과 없는 것은 다른 사실이다.
_MISSING_SPEC_NOTE = "열 정의에 이 마켓이 빠져 있습니다 — 열 정의를 고쳐 주세요"


def _missing_specs(cols: list, markets: list) -> list[str]:
    """열 정의에 빠진 (마켓 × 열) 을 한 번에 모은다.

    🔴 한 칸 때문에 표 전체를 못 보게 하지 않는다. 다만 「해당없음」으로 지어내지도 않는다 —
      그 칸은 미착수로 두고, 무엇이 빠졌는지 배너로 말한다.
      (손보정 파일은 오타가 나도 배너로 살려 두는데 열 정의만 500 이면 비대칭이다.
       판매처 열 정의는 스크립트 생성물이지만 소싱처 열 정의는 사람이 손으로 쓴다.)
    """
    out = []
    for col in cols:
        specs = col.get("specs") or {}
        gone = [m for m, _ in markets if m not in specs]
        if gone:
            out.append(f"「{col['name']}」 열에 {', '.join(gone)} 가 빠져 있습니다")
    return out


def build(columns_file: str = "dev_checklist_columns.json",
          markets: list | None = None,
          marks_file: str = "dev_checklist_marks.json") -> dict:
    """화면이 그대로 그릴 수 있는 한 벌.

    🔴 「판」을 이루는 셋(열 정의·마켓 목록·손보정 파일)은 **반드시 같이** 바뀐다.
      하나라도 모듈에 박아 두면 소싱처판이 판매처 마켓 목록으로 판정하다 터지고,
      판매처 손보정이 소싱처 표에 거짓 경보로 전건 뜬다.
    """
    cols = load_columns(columns_file)
    # 🔴 `markets or MARKETS` 로 쓰면 **「마켓 없음」이 「전부」로 뒤집힌다** —
    #   빈 설정이 조용히 판매처 6마켓 표를 그린다. 안 준 것과 비운 것은 다른 뜻이다.
    board = list(MARKETS if markets is None else markets)
    marks, unreadable = load_marks(marks_file)
    missing = _missing_specs(cols, board)
    cells, rows = {}, []
    for market, label in board:
        counts = {k: 0 for k in (NA, IMPOSSIBLE, TODO, STORED, WIRED, DONE)}
        for col in cols:
            item = col.get("item")
            # 배선은 마켓과 무관하다(항목 하나당 하나) — 빠진 칸에서도 참말을 할 수 있다.
            wiring = _req.wiring_of(item) if item else (WIRING_NONE, WIRING_NONE_NOTE)
            if market not in (col.get("specs") or {}):
                # 열 정의에 그 마켓이 없다 → 미착수로 두고 왜인지 적는다 (표는 그린다)
                state, spec_text, conflict = TODO, "", ""
                status, evidence, note = _req.UNKNOWN, "", _MISSING_SPEC_NOTE
            else:
                state = cell_state(market, col, marks)
                spec_text, conflict = _spec(market, col), conflict_of(market, col)
                status, evidence, note = (_req.status_of(market, item) if item
                                          else (_req.UNKNOWN, "", WIRING_NONE_NOTE))
            counts[state] += 1
            key = f"{market}:{col['col']}"
            cells[key] = {
                "state": state,
                "spec": spec_text,
                "required": status,
                "evidence": evidence,
                "note": note,
                "wiring": wiring[0],
                "wiring_note": wiring[1],
                "api": _req.SOURCE_API.get(market, ""),
                "conflict": conflict,
                # 🔴 검증완료가 아닌 칸에는 검증일을 싣지 않는다.
                #   노란 칸에 날짜가 찍히면 「반쯤 검증됨」으로 읽힌다 —
                #   왜 안 됐는지는 배너가 말한다(➖·⚫ 뿐 아니라 🟡·⬜ 도 마찬가지다).
                "verified": (((marks.get(key) or {}).get("verified") or "")
                             if state == DONE else ""),
            }
        # 🔴 분모 = **채울 수 있는 칸**. ➖해당없음뿐 아니라 ⚫불가도 뺀다 —
        #   불가 칸은 `cell_state` 가 손보정을 보기도 전에 끊으므로 done 이 될 길이 없다.
        #   안 빼면 쿠팡은 21/22 = 95.5% 에서 멈춰 100%가 영영 안 찬다.
        counts["total"] = len(cols) - counts[NA] - counts[IMPOSSIBLE]
        rows.append({"market": market, "label": label, "counts": counts})
    # 배너 차례 — ① 손보정을 아예 못 읽은 사유 ② 열 정의에 빠진 칸 ③ 손보정 어긋남.
    #   ①이 있으면 `load_marks` 가 marks 를 늘 {} 로 돌려주므로 ③은 반드시 비어 있다
    #   (예전 `[unreadable] + problems` 의 뒷항은 항상 `+ []` 인 죽은 줄이었다).
    #   그래도 ②는 살아 있으니 셋을 차례대로 잇는다.
    banners = ([unreadable] if unreadable else []) + missing \
        + drift(marks, columns_file, board)
    return {"columns": cols, "rows": rows, "cells": cells, "drift": banners}


# ══════════════════════════════════════════════════════════════════════════
#  소싱처판 — 근거표(required.py)가 없다. 자동으로 아는 것은 「크롤러가 있나」 하나뿐.
# ══════════════════════════════════════════════════════════════════════════

#: 소싱처 8곳. 이름은 `source_registry.SOURCES`(빌트인 6) + 크롤 가이드(현대H몰·롯데아이몰).
#:
#: 🔴 `lotteon` 을 「롯데홈쇼핑」이라 적으면 안 된다. `accounts.py` 의 소싱처 씨앗 목록만
#:   그렇게 적혀 있는데, 같은 파일의 `SOURCING_SITES` 는 `lotteon`=롯데온(lotteon.com) ·
#:   `lotteimall`=롯데홈쇼핑(lottehomeshopping.com) 으로 가른다.
#:   `_detect_site_from_url` 도 `lotteon.com`→lotteon / `lotteimall.com`→lotteimall 이다.
#:   여기서 「롯데홈쇼핑」을 쓰면 바로 아래 `lotteimall` 줄과 이름이 겹쳐 어느 줄인지 못 가린다.
SOURCES = [("lemouton", "르무통 공홈"), ("ss_lemouton", "스마트스토어 르무통"),
           ("musinsa", "무신사"), ("ssf", "SSF샵"), ("lotteon", "롯데온"),
           ("ssg", "SSG"), ("hmall", "현대H몰"), ("lotteimall", "롯데아이몰")]

_SOURCING_COLUMNS = "dev_checklist_sourcing.json"
_SOURCING_MARKS = "dev_checklist_sourcing_marks.json"

#: 소싱처엔 「마켓 문서가 요구하는가」에 해당하는 근거표가 없다 — 그 사실을 그대로 적는다.
#: 🔴 「해당없음」으로 지어내지 않는다. 화면은 required=='unknown' 일 때만
#:   「없다는 뜻이 아니라 모른다는 뜻입니다」를 띄운다.
_SOURCING_NO_EVIDENCE = ("소싱처엔 마켓 등록 근거표(required.py) 같은 것이 없습니다 — "
                         "이 판은 손보정으로 채웁니다")
_HAS_CRAWLER_NOTE = "크롤러가 등록돼 있습니다 — 값을 읽어 오는 데까지는 됩니다"
_NO_CRAWLER_NOTE = "이 소싱처의 크롤러가 아직 없습니다"


def _crawler_registered(source_key: str) -> bool:
    """그 소싱처의 크롤러가 실제로 등록돼 있나. 없으면 아무것도 시작 안 된 것.

    🔴 못 알아보면 False 가 아니라 **모른다**로 다뤄야 하지만, 지금은 등록 여부만 본다.
      그래서 import·호출 실패를 **삼키지 않는다**. 삼켜서 False 로 떨어뜨리면 8소싱처
      184칸이 전부 ⬜미착수로 뒤집히는데 화면엔 아무 이유도 안 뜬다 —
      「크롤러가 없다」와 「확인을 못 했다」는 다른 사실이다.
      터뜨려서 호출자(`build_sourcing`)가 배너로 말하게 한다.
    """
    from lemouton.sourcing.crawlers import build_crawlers
    return source_key in (build_crawlers() or {})


def _sourcing_drift(marks: dict, cols: list, known: dict) -> list[str]:
    """소싱처 손보정이 표와 어긋나면 사람 말로 돌려준다.

    판매처 `drift` 처럼 `cell_state` 에 판정을 맡길 수 없다(근거표가 없어 판정 축이 다르다).
    그래도 **키가 표를 못 가리키는 경우**는 같은 급으로 잡는다 — 그 손보정은 화면에
    영영 안 뜨는데 파일에는 남아 있어 「달아 뒀다」고 착각하게 만든다.
    """
    by_col = {str(c["col"]) for c in cols}
    out = []
    for key, mark in (marks or {}).items():
        if not isinstance(mark, dict) or not (mark.get("verified") or mark.get("impossible")):
            continue
        source, sep, raw = key.partition(":")
        if source not in known:
            out.append(f"손보정에 모르는 소싱처 이름이 있습니다: {key} — "
                       f"쓸 수 있는 이름: {', '.join(known)}")
            continue
        # 🔴 글자로 견준다. `int()` 로 견주면 `musinsa:03` 이 통과해 버리는데
        #   화면 키는 `musinsa:3` 이라 그 손보정은 영영 안 읽힌다.
        if not sep or raw not in by_col:
            out.append(f"손보정의 열 번호를 표에서 찾지 못했습니다: {key} — "
                       f"「<소싱처>:<열번호>」 로, 열번호는 앞에 0 을 붙이지 말고 적습니다")
    return out


def build_sourcing() -> dict:
    """소싱처판. `build()` 와 **같은 모양**을 돌려준다 — 화면 조각이 한 벌이기 때문이다.

    자동으로 아는 것은 「크롤러가 등록돼 있나」 하나뿐이고 나머지는 손보정이다.
    🔴 손보정 파일은 판매처 것과 반드시 갈라 쓴다(`_SOURCING_MARKS`).
    """
    cols = load_columns(_SOURCING_COLUMNS)
    marks, unreadable = load_marks(_SOURCING_MARKS)
    banners = [unreadable] if unreadable else []
    banners += _missing_specs(cols, SOURCES)

    try:
        registered = {k: _crawler_registered(k) for k, _ in SOURCES}
    except Exception as e:                       # noqa: BLE001 — 삼키는 게 아니라 배너로 옮긴다
        registered = {k: False for k, _ in SOURCES}
        banners.append(f"크롤러 등록 여부를 확인하지 못했습니다 — {e}. "
                       f"아래 표의 「크롤러 있음」 판정은 믿지 마십시오")

    cells, rows = {}, []
    for key, label in SOURCES:
        has_crawler = registered.get(key, False)
        counts = {k: 0 for k in (NA, IMPOSSIBLE, TODO, STORED, WIRED, DONE)}
        for col in cols:
            mark = marks.get(f"{key}:{col['col']}") or {}
            if mark.get("impossible"):
                state = IMPOSSIBLE           # ⚫ 원래 안 되는 것 — 영원한 빨간불로 두지 않는다
            elif mark.get("verified"):
                state = DONE
            elif has_crawler:
                state = STORED
            else:
                state = TODO
            counts[state] += 1
            cells[f"{key}:{col['col']}"] = {
                "state": state,
                "spec": ((col.get("specs") or {}).get(key) or "").strip(),
                # 근거표가 없다 = 「요구 안 한다」가 아니라 「모른다」
                "required": _req.UNKNOWN,
                "evidence": "",
                "note": mark.get("note") or _SOURCING_NO_EVIDENCE,
                # 🔴 빈 문자열로 내보내지 않는다 — 화면이 `!= 'wired'` 로 뭉뚱그리면
                #   크롤러조차 없는 칸이 「저장은 된다」는 거짓말로 뜬다.
                "wiring": STORED if has_crawler else WIRING_NONE,
                "wiring_note": _HAS_CRAWLER_NOTE if has_crawler else _NO_CRAWLER_NOTE,
                "api": "",
                "conflict": "",
                # 검증완료가 아닌 칸에는 검증일을 싣지 않는다(판매처와 같은 규칙)
                "verified": (mark.get("verified") or "") if state == DONE else "",
            }
        # 분모 = 채울 수 있는 칸. ⚫불가는 done 이 될 길이 없으니 뺀다(안 빼면 100%가 안 찬다).
        counts["total"] = len(cols) - counts[NA] - counts[IMPOSSIBLE]
        rows.append({"market": key, "label": label, "counts": counts})

    banners += _sourcing_drift(marks, cols, dict(SOURCES))
    return {"columns": cols, "rows": rows, "cells": cells, "drift": banners}


#: 검증완료를 달았는데 그 칸이 done 이 아닌 이유 — 사장님이 무엇을 고쳐야 할지 바로 알게 한다
_WHY_NOT_DONE = {
    NA: "그 마켓엔 해당 없는 항목입니다",
    IMPOSSIBLE: "그 마켓에는 이 기능 자체가 없습니다",
    TODO: "프로그램에 담을 칸이 없거나 마켓 근거를 아직 못 찾았습니다",
    STORED: "저장만 되고 마켓으로 나가지 않습니다",
    # 배선도 멀쩡한데 done 이 아니면 남는 이유는 하나뿐 — 키 글자가 표와 다르다
    # (예: `smartstore:05`). 화면은 그 값을 영영 못 읽으므로 조용히 넘기면 안 된다.
    WIRED: ("손보정 키가 표의 형식과 달라 화면이 그 값을 못 읽습니다 — "
            "「<마켓>:<열번호>」 로, 열번호는 앞에 0 을 붙이지 말고 적습니다"),
}


def drift(marks: dict, columns_file: str = "dev_checklist_columns.json",
          markets: list | None = None) -> list[str]:
    """손보정이 코드와 어긋나면 사람 말로 돌려준다. 없으면 빈 목록.

    🔴 판정은 `cell_state` 에 맡긴다. 여기서 따로 판정하면 화면과 배너가 서로 다른 말을
      한다 — 같은 오타가 열 번호에 따라 침묵/오보로 갈리고, ➖ 칸에 검증일이 붙는다.
    """
    known = dict(MARKETS if markets is None else markets)
    by_col = {c["col"]: c for c in load_columns(columns_file)}
    out = []
    for key, mark in (marks or {}).items():
        if not (mark or {}).get("verified"):
            continue
        market, _, raw = key.partition(":")
        if market not in known:
            out.append(f"손보정에 모르는 마켓 이름이 있습니다: {key} — "
                       f"쓸 수 있는 이름: {', '.join(known)}")
            continue
        try:
            col = by_col[int(raw)]
        except (ValueError, KeyError):
            out.append(f"손보정의 열 번호를 표에서 찾지 못했습니다: {key}")
            continue
        if market not in (col.get("specs") or {}):
            # 열 정의에 그 마켓이 빠져 있다 — build 가 이미 따로 말하므로 여기선 죽지만 않으면 된다
            out.append(f"「{col['name']}」 열에 {market} 가 빠져 있어 "
                       f"검증완료를 판정할 수 없습니다")
            continue
        state = cell_state(market, col, {key: mark})
        if state == DONE:
            continue                      # 제대로 달린 검증완료 — 조용하다
        out.append(f"「{col['name']}」({known[market]}) 에 검증완료가 달려 있는데 "
                   f"{_WHY_NOT_DONE[state]}")
    return out

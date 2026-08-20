# -*- coding: utf-8 -*-
"""노션 「투두리스트 (영빈)」 일일 요약·변경사항 보고.

**흐름**
    ① 노션 API 로 페이지의 체크박스를 전부 읽는다
    ② 오늘 요일 블록만 골라낸다
    ③ 어제 저장본과 대조해 신규/완료/해제/삭제/문구수정을 뽑는다
    ④ 카카오톡 200자 요약으로 만들어 「나에게 보내기」로 쏜다
    ⑤ 오늘 것을 내일 비교용으로 저장한다

**왜 블록 ID 로 대조하나**
    문구로 대조하면 오타 하나만 고쳐도 「삭제 1 + 신규 1」로 잡힌다.
    노션 블록 ID 는 문구를 고쳐도 유지되므로, ID 를 신원으로 쓰고 문구 변화는
    따로 `edited` 로 분류한다.

**요일 블록을 고르는 규칙 (중요)**
    이 페이지는 주차가 지나도 지난 주 요일 블록을 지우지 않고 아래에 쌓아둔다.
    그래서 「월요일」 같은 라벨이 문서에 6번 넘게 나온다. 문서에 **처음 등장하는**
    해당 요일 블록을 이번 주로 본다(맨 위가 최신). 이 가정이 깨지면 보고 내용이
    통째로 지난 주 것이 되므로, 미리보기 화면과 보고 payload 에 **몇 번째 블록을
    골랐는지·그 블록의 첫 항목이 무엇인지** 항상 같이 실어 눈으로 검증 가능하게 한다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import requests

logger = logging.getLogger(__name__)

_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

# 「투두리스트 (영빈)」 페이지. 환경변수로 덮어쓸 수 있게 둔다(페이지를 새로 팠을 때).
_DEFAULT_PAGE_ID = "316cf482-7373-806e-882b-f86e9df1cbf2"

# 테스트에서만 덮어쓴다. 평소엔 None → state_store 가 정하는 영속 경로.
#   라이브(AWS)는 배포마다 컨테이너를 새로 만들어 앱 안 data/ 는 날아간다.
#   여기 두면 배포한 날마다 "첫 실행"으로 오인돼 그날 보고가 통째로 빠진다.
_SNAPSHOT_PATH: Optional[str] = None


def _snapshot_path() -> str:
    if _SNAPSHOT_PATH:
        return _SNAPSHOT_PATH
    from shared.state_store import state_path

    return state_path("notion_todo_snapshot.json")

_WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
_WEEKDAY_RE = re.compile(r"^(월|화|수|목|금|토|일)요일$")

# 재귀 깊이 상한 — 이 페이지는 토글>컬럼>콜아웃>토글로 4~6단이지만,
#   순환이나 예상 밖 깊이에서 무한 재귀가 나지 않게 막아둔다.
_MAX_DEPTH = 12

# 429/5xx 재시도 횟수. 노션 속도 제한은 통합당 평균 초당 3회.
_RETRY_MAX = 5


def _seoul_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:  # noqa: BLE001 — tzdata 없는 환경 폴백
        return datetime.now(timezone(timedelta(hours=9)))


# ──────────────────────────────────────────────────────────────
# 어느 노션 문서를 읽나 — 화면에서 갈아탈 수 있다
# ──────────────────────────────────────────────────────────────
#   🔴 **환경변수에 저장하면 안 된다.** UI 로 저장하면 그 요청을 받은 워커의
#      os.environ 만 바뀌고 나머지 워커·스케줄러는 옛 문서를 계속 읽는다
#      (같은 함정을 키 저장에서 겪었다). 파일 하나에 두면 전원이 같은 것을 본다.
#   환경변수는 **운영자 강제 지정**용으로만 남겨 둔다(있으면 그게 이긴다).
_PAGE_FILE = "notion_todo_page.json"
_PAGE_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_PAGE_ID_RAW_RE = re.compile(r"[0-9a-f]{32}", re.I)


def _page_file() -> str:
    if _SNAPSHOT_PATH:   # 테스트: 스냅샷과 같은 폴더에 둔다
        return os.path.join(os.path.dirname(_SNAPSHOT_PATH), _PAGE_FILE)
    from shared.state_store import state_path

    return state_path(_PAGE_FILE)


def _load_page_choice() -> dict:
    try:
        with open(_page_file(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("id"):
            return data
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — 손상 파일이 보고를 막지 않게
        logger.exception("%s 읽기 실패 — 기본 문서로", _PAGE_FILE)
    return {}


def dashify(raw: str) -> str:
    """32자리 노션 번호에 하이픈을 넣어 정식 모양으로."""
    s = (raw or "").replace("-", "")
    if len(s) != 32:
        return raw
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"


def extract_page_id(raw: str) -> Optional[str]:
    """노션 주소(또는 번호)에서 문서 번호를 뽑는다.

    사장님이 붙여넣는 것은 대개 이런 모양이다:
        https://www.notion.so/제목-316cf4827373806e882bf86e9df1cbf2?pvs=4
        https://www.notion.so/workspace/316cf482-7373-806e-882b-f86e9df1cbf2
    `?v=...` 같은 꼬리표에 또 다른 32자리가 붙어 있을 수 있어 **물음표 앞까지만** 본다
    (그 뒤는 보기(view) 번호라 그걸 잡으면 없는 문서를 읽는다).
    """
    s = (raw or "").strip()
    if not s:
        return None
    s = s.split("?")[0].split("#")[0]
    m = _PAGE_ID_RE.search(s)
    if m:
        return m.group(0).lower()
    m = _PAGE_ID_RAW_RE.search(s.replace("-", ""))
    if m:
        return dashify(m.group(0).lower())
    return None


def page_id() -> str:
    """지금 읽는 문서 번호. 환경변수 > 저장된 선택 > 기본값."""
    env = (os.environ.get("NOTION_TODO_PAGE_ID") or "").strip()
    if env:
        return env
    return (_load_page_choice().get("id") or _DEFAULT_PAGE_ID).strip()


def page_title() -> str:
    """화면에 보여줄 문서 이름. 고른 적 없으면 기본 문서 이름."""
    if (os.environ.get("NOTION_TODO_PAGE_ID") or "").strip():
        return os.environ.get("NOTION_TODO_PAGE_TITLE") or "(운영자 지정 문서)"
    return _load_page_choice().get("title") or "투두리스트 (영빈)"


def is_default_page() -> bool:
    return page_id().replace("-", "") == _DEFAULT_PAGE_ID.replace("-", "")


def clear_baseline() -> None:
    """어제 저장본과 마지막 보고를 지운다.

    🔴 **문서를 갈아탈 때 반드시 같이 해야 한다.** 남의 문서에서 만든 기준선을
    그대로 두면 다음 회차가 「어제 것 전부 삭제 + 오늘 것 전부 신규」로 잡혀
    수백 건짜리 거짓 보고가 나간다. 비워두면 첫 회차는 기준선만 저장하고
    발송하지 않으므로(run_slot_report 의 first_run) 안전하다.
    """
    for path in (_snapshot_path(), _last_report_path()):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("기준선 삭제 실패 — %s", path)


def set_page(page_id_raw: str, *, title: str = "") -> dict:
    """읽을 문서를 바꾼다. **기준선도 같이 비운다.**

    Returns:
        {ok, id, title, error}
    """
    pid = extract_page_id(page_id_raw)
    if not pid:
        return {"ok": False, "error": "노션 주소에서 문서 번호를 찾지 못했습니다. "
                                      "주소를 통째로 붙여넣어 주세요."}
    payload = {"id": pid, "title": (title or "").strip(),
               "at": _seoul_now().isoformat()}
    path = _page_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)
    clear_baseline()
    return {"ok": True, "id": pid, "title": payload["title"]}


def list_pages(*, limit: int = 50) -> dict:
    """노션이 우리에게 열어준 문서 목록.

    노션 API 는 **연결(통합)에 공유된 문서만** 돌려준다 — 목록에 없다는 것은
    그 문서의 `⋯ > 연결`에 우리 연결이 없다는 뜻이고, 그때는 주소를 붙여넣어도
    읽지 못한다. 그래서 화면에 그 사실을 같이 적는다.

    Returns:
        {ok, pages: [{id, title, url, is_current}], error}
    """
    tok = _token()
    if not tok:
        return {"ok": False, "pages": [], "error": "노션 시크릿이 아직 없습니다."}
    try:
        resp = requests.post(
            f"{_NOTION_API}/search",
            headers={"Authorization": f"Bearer {tok}",
                     "Notion-Version": _NOTION_VERSION,
                     "Content-Type": "application/json"},
            json={"filter": {"value": "page", "property": "object"},
                  "page_size": min(limit, 100)},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("노션 문서 목록 조회 실패")
        return {"ok": False, "pages": [], "error": str(e)}
    if resp.status_code != 200:
        return {"ok": False, "pages": [],
                "error": f"노션 {resp.status_code}: {resp.text[:200]}"}

    cur = page_id().replace("-", "")
    pages = []
    for row in (resp.json().get("results") or []):
        pid = row.get("id") or ""
        pages.append({
            "id": pid,
            "title": _page_title_of(row) or "(제목 없음)",
            "url": row.get("url") or "",
            "is_current": pid.replace("-", "") == cur,
        })
    return {"ok": True, "pages": pages, "error": None}


def _page_title_of(row: dict) -> str:
    """검색 결과 한 줄에서 제목을 뽑는다.

    문서 제목은 `properties` 안 **type 이 title 인 칸**에 들어 있는데, 칸 이름은
    문서마다 다르다(`title`·`이름`·`Name`…). 이름으로 찾으면 한글 워크스페이스에서
    제목이 통째로 비어 보인다 — type 으로 찾는다.
    """
    props = row.get("properties") or {}
    for value in props.values():
        if not isinstance(value, dict) or value.get("type") != "title":
            continue
        parts = value.get("title") or []
        text = "".join(p.get("plain_text", "") for p in parts
                       if isinstance(p, dict)).strip()
        if text:
            return text
    return ""


def page_url() -> str:
    return f"https://www.notion.so/{page_id().replace('-', '')}"


def public_base() -> str:
    return (os.environ.get("MOUM_PUBLIC_BASE") or "https://mou-m.com").rstrip("/")


def link_url() -> str:
    """카톡 말풍선·버튼이 열 주소.

    카카오는 **앱에 등록된 웹 도메인**([앱] > [제품 링크 관리] > [웹 도메인])의 링크만
    살려둔다. 등록 안 된 도메인이면 링크가 아예 안 먹거나 버튼이 사라진다
    (2026-08-02 실측: 카톡은 왔는데 눌러도 아무 반응 없음).

    노션 주소를 직접 쓰면 남의 도메인(notion.so)을 등록해야 한다. 대신 **우리 도메인**
    으로 한 번 받아 노션으로 넘긴다 — 사장님이 소유한 도메인 하나만 등록하면 된다.
    """
    return f"{public_base()}/reports/notion-todo/open"


def shot_url() -> str:
    """카톡에서 「캡처 크게 보기」로 열 원본 사진 주소.

    말풍선의 작은 사진은 잘려 보인다 — 눌렀을 때 **원본 캡처**가 떠야 쓸모가 있다.
    (2026-08-02 사장님: 「노션에서 보기가 아니라 캡처본으로」)
    """
    return f"{public_base()}/reports/notion-todo/shot/latest"


def history_url() -> str:
    """변경 이력 화면 주소(카톡 「변경 이력 전체」 버튼)."""
    return f"{public_base()}/reports/notion-todo/history"


def _token() -> str:
    tok = (os.environ.get("NOTION_TOKEN") or "").strip()
    if not tok:
        # UI 로 저장한 키는 공유 .env 에만 있고 이 프로세스 환경엔 없을 수 있다.
        try:
            from lemouton.auth.secrets import refresh_env

            refresh_env()
            tok = (os.environ.get("NOTION_TOKEN") or "").strip()
        except Exception:   # noqa: BLE001
            logger.debug("shared .env 재로드 실패(무시)", exc_info=True)
    return tok


# ──────────────────────────────────────────────────────────────
# ① 노션 읽기
# ──────────────────────────────────────────────────────────────
def _plain_text(block: dict) -> str:
    """블록의 표시 문구. 서식(굵게·색)은 버리고 글자만 이어붙인다."""
    body = block.get(block.get("type") or "", {})
    if not isinstance(body, dict):
        return ""
    parts = body.get("rich_text") or body.get("text") or []
    if not isinstance(parts, list):
        return ""
    return "".join(p.get("plain_text", "") for p in parts if isinstance(p, dict)).strip()


def _get_with_retry(session: requests.Session, url: str,
                    params: dict) -> requests.Response:
    """429(속도 제한)와 5xx 를 지수 백오프로 재시도.

    노션은 통합당 **평균 초당 3회**가 상한이다. 이 페이지는 토글·컬럼·콜아웃이
    깊게 중첩돼 블록마다 자식 조회가 필요하므로 수백 번 호출이 나가고, 재시도가
    없으면 중간에 429 한 번으로 그날 보고가 통째로 실패한다.
    """
    delay = 1.0
    last: Optional[requests.Response] = None
    for attempt in range(_RETRY_MAX):
        resp = session.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            return resp
        last = resp
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After") or delay)
            logger.info("노션 429 — %.1f초 대기 후 재시도 (%d/%d)",
                        wait, attempt + 1, _RETRY_MAX)
            time.sleep(min(wait, 30.0))
            delay = min(delay * 2, 30.0)
            continue
        if 500 <= resp.status_code < 600:
            logger.info("노션 %d — %.1f초 후 재시도 (%d/%d)",
                        resp.status_code, delay, attempt + 1, _RETRY_MAX)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
            continue
        break   # 4xx(권한·미연결 등)는 재시도해도 같다
    raise RuntimeError(
        f"노션 블록 조회 실패 {last.status_code if last else '?'}: "
        f"{last.text[:200] if last else ''}"
    )


def _fetch_children(block_id: str, session: requests.Session) -> list[dict]:
    """자식 블록 전부(페이지네이션 포함)."""
    out: list[dict] = []
    cursor: Optional[str] = None
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = _get_with_retry(
            session, f"{_NOTION_API}/blocks/{block_id}/children", params
        )
        payload = resp.json()
        out.extend(payload.get("results") or [])
        if not payload.get("has_more"):
            break
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return out


def fetch_todos(*, session: Optional[requests.Session] = None) -> list[dict]:
    """페이지 전체를 훑어 체크박스를 문서 순서대로 뽑는다.

    Returns:
        [{id, text, checked, weekday, weekday_seq, order}] — order 는 문서 등장 순서.

    Raises:
        RuntimeError — 토큰 미설정 / 노션 API 실패(권한·페이지 미연결 포함)
    """
    if not _token():
        raise RuntimeError("NOTION_TOKEN 환경변수가 비어 있음")

    own = session is None
    session = session or requests.Session()
    if own:
        session.headers.update(
            {
                "Authorization": f"Bearer {_token()}",
                "Notion-Version": _NOTION_VERSION,
            }
        )

    todos: list[dict] = []
    # 요일 라벨이 문서에 몇 번째로 나온 것인지 세는 카운터(같은 요일이 여러 주 쌓여 있다).
    weekday_seen: dict[str, int] = {}

    def walk(block_id: str, weekday: Optional[str], weekday_seq: Optional[int],
             depth: int) -> None:
        if depth > _MAX_DEPTH:
            logger.warning("노션 재귀 깊이 상한 도달 — block=%s", block_id)
            return
        cur_weekday, cur_seq = weekday, weekday_seq
        for child in _fetch_children(block_id, session):
            ctype = child.get("type")
            text = _plain_text(child)

            # 요일 라벨을 만나면 그 시점 이후 형제·자손은 그 요일 소속으로 본다.
            if text and _WEEKDAY_RE.match(text):
                cur_weekday = text
                weekday_seen[text] = weekday_seen.get(text, -1) + 1
                cur_seq = weekday_seen[text]

            if ctype == "to_do":
                todos.append(
                    {
                        "id": child.get("id"),
                        "text": text,
                        "checked": bool(
                            (child.get("to_do") or {}).get("checked")
                        ),
                        "weekday": cur_weekday,
                        "weekday_seq": cur_seq,
                        "order": len(todos),
                        # 노션이 블록마다 알려주는 값 — 「언제 누가 고쳤나」의 원천.
                        #   우리가 추측할 필요 없이 노션이 사실을 갖고 있다.
                        "last_edited": child.get("last_edited_time"),
                        "last_editor": ((child.get("last_edited_by") or {})
                                        .get("id")),
                    }
                )

            if child.get("has_children"):
                walk(child["id"], cur_weekday, cur_seq, depth + 1)

    walk(page_id(), None, None, 0)
    return todos


# ──────────────────────────────────────────────────────────────
# ② 오늘 요일 골라내기
# ──────────────────────────────────────────────────────────────
def weekday_label(when: Optional[date] = None) -> str:
    """오늘(또는 지정일)의 한글 요일 라벨."""
    when = when or _seoul_now().date()
    return _WEEKDAYS[when.weekday()]


def todays_todos(todos: Iterable[dict], *, when: Optional[date] = None) -> list[dict]:
    """오늘 요일 블록의 항목만. 같은 요일이 여러 주 쌓여 있으면 **처음 것**(최신 주)."""
    label = weekday_label(when)
    return [t for t in todos if t.get("weekday") == label and t.get("weekday_seq") == 0]


# ──────────────────────────────────────────────────────────────
# ③ 어제와 대조
# ──────────────────────────────────────────────────────────────
def diff_todos(prev: Iterable[dict], curr: Iterable[dict]) -> dict:
    """어제 저장본과 오늘을 대조.

    Returns:
        {added, completed, reopened, removed, edited} — 각각 항목 dict 의 리스트.
        completed = 어제 미완료 → 오늘 완료. reopened = 그 반대(체크 해제).
        edited    = 같은 블록의 문구만 바뀐 것 ({id, before, after}).
    """
    prev_by_id = {t["id"]: t for t in prev if t.get("id")}
    curr_by_id = {t["id"]: t for t in curr if t.get("id")}

    added = [t for tid, t in curr_by_id.items() if tid not in prev_by_id]
    removed = [t for tid, t in prev_by_id.items() if tid not in curr_by_id]

    completed, reopened, edited = [], [], []
    for tid, cur in curr_by_id.items():
        old = prev_by_id.get(tid)
        if not old:
            continue
        if not old.get("checked") and cur.get("checked"):
            completed.append(cur)
        elif old.get("checked") and not cur.get("checked"):
            reopened.append(cur)
        if (old.get("text") or "") != (cur.get("text") or ""):
            edited.append({
                "id": tid,
                "before": old.get("text", ""),
                "after": cur.get("text", ""),
                # 노션이 알려주는 실제 수정 시각 — 회차 사이에 바뀐 것이라
                #   우리가 관측한 시각으로는 「언제」를 알 수 없다.
                "last_edited": cur.get("last_edited"),
                # 요일 칸으로 걸러내려면 여기에도 실어야 한다.
                "weekday": cur.get("weekday"),
                "weekday_seq": cur.get("weekday_seq"),
            })

    return {
        "added": added,
        "completed": completed,
        "reopened": reopened,
        "removed": removed,
        "edited": edited,
    }


# ──────────────────────────────────────────────────────────────
# 스냅샷 저장소
# ──────────────────────────────────────────────────────────────
def load_snapshot() -> dict:
    """어제 저장본. 없으면 빈 스냅샷(=첫 실행)."""
    try:
        with open(_snapshot_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — 손상 파일이 보고를 영구 차단하지 않게
        logger.exception("notion_todo_snapshot.json 읽기 실패 — 빈 스냅샷으로 시작")
    return {"at": None, "todos": [], "sent_date": None}


def save_snapshot(todos: list[dict], *, sent_date: Optional[str] = None) -> None:
    """오늘 것을 내일 비교용으로 저장(원자적 교체)."""
    payload = {
        "at": _seoul_now().isoformat(),
        "todos": todos,
        "sent_date": sent_date,
    }
    path = _snapshot_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


# ──────────────────────────────────────────────────────────────
# ④ 카톡 200자 요약
# ──────────────────────────────────────────────────────────────
def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# 표식 — 사장님 확정(시안 1 「그림 표식」, 2026-08-02).
#   글자를 덜 먹어 같은 200자에 항목이 더 들어간다(6건 기준 한글표식 166자 vs 149자).
_MARK = {
    "completed": "✅",   # 완료
    "added": "🆕",       # 추가
    "edited": "✏️",      # 수정
    "removed": "🗑",     # 삭제
    "reopened": "↩️",    # 체크 해제(완료였다가 다시 열림)
}
# 카톡에 적을 순서 — 「끝난 것」부터 본다.
_ORDER = ["completed", "added", "edited", "removed", "reopened"]


def _hhmm(raw: Optional[str], *, today: Optional[date] = None) -> str:
    """노션이 준 UTC 시각 → 서울 시각. 없으면 빈 문자열.

    **오늘 고친 것만 'HH:MM'**, 다른 날이면 'M/D'. 시:분만 찍으면 며칠 전에 고친
    항목이 오늘 그 시각에 한 것처럼 보인다(2026-08-02 실측 — 오후 6시인데 20:31·
    22:13 이 찍혀 미래처럼 읽혔다).
    """
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        try:
            from zoneinfo import ZoneInfo

            dt = dt.astimezone(ZoneInfo("Asia/Seoul"))
        except Exception:  # noqa: BLE001
            dt = dt.astimezone(timezone(timedelta(hours=9)))
        today = today or _seoul_now().date()
        if dt.date() == today:
            return dt.strftime("%H:%M")
        return f"{dt.month}/{dt.day}"
    except Exception:  # noqa: BLE001
        return ""


def _head(when: date, slot: str = "") -> str:
    label = weekday_label(when)[0]
    base = f"{when.month}/{when.day}({label})"
    return f"{base} {slot}" if slot else base


def build_photo_message(today: list[dict], *, when: Optional[date] = None,
                        slot: str = "", changed: int = 0) -> str:
    """사진 통 — 첫 줄이 제목, 나머지가 설명(카카오 feed 규격)."""
    when = when or _seoul_now().date()
    label = weekday_label(when)[0]
    title = f"영빈 투두 {_head(when, slot)}"
    if today:
        body = f"오늘({label}) 남은 일 {sum(1 for t in today if not t.get('checked'))}건"
    else:
        # 0건이라고 말하면 「다 끝냈다」로 읽힌다 — 못 찾은 것과 구별해야 한다.
        body = f"오늘({label}) 요일 칸을 못 찾았습니다"
    if not changed:
        body += "\n바뀐 것 없음"
    return f"{title}\n{body}"


def build_change_message(changes: dict, *, when: Optional[date] = None,
                         slot: str = "", limit: int = 200) -> str:
    """변경 통 — 시각을 앞에, 표식으로 종류를 나타낸다.

    자리가 모자라면 뒤에서부터 줄이고 「외 N건」으로 정직하게 남긴다 —
    말없이 잘라내면 몇 건이 빠졌는지 알 길이 없다.
    """
    when = when or _seoul_now().date()
    rows: list[tuple[str, str]] = []
    for kind in _ORDER:
        for item in (changes.get(kind) or []):
            if kind == "edited":
                text = f"{item.get('before') or ''} → {item.get('after') or ''}"
                edited_at = item.get("last_edited")
            else:
                text = item.get("text") or ""
                edited_at = item.get("last_edited")
            if not text.strip() or text.strip() == "→":
                continue          # 노션의 빈 체크박스
            rows.append((_hhmm(edited_at, today=when),
                         f"{_MARK[kind]} {_shorten(text, 34)}"))

    total = sum(len(changes.get(k) or []) for k in _ORDER)
    title = f"{_head(when, slot)} · 변경 {total}건"

    lines: list[str] = []
    used = len(title) + 1
    for i, (hhmm, body) in enumerate(rows):
        line = f"{hhmm} {body}".strip()
        rest = len(rows) - i
        tail = f"\n외 {rest}건" if rest > 1 else ""
        if used + len(line) + 1 + len(tail) > limit:
            if rest:
                lines.append(f"외 {rest}건")
            break
        lines.append(line)
        used += len(line) + 1
    return title + "\n" + "\n".join(lines)


def filter_changes_to_weekday(changes: dict, weekday: str) -> dict:
    """변경분을 **오늘 요일 칸(이번 주)** 것만 남긴다.

    보고의 주인공은 오늘 요일 칸이고 사진도 그 칸이다. 그런데 대조는 페이지 전체를
    보므로, 거르지 않으면 다른 요일·지난 주 칸의 변경까지 섞여 나간다
    (2026-08-02 실측: 오늘 칸은 37건인데 변경이 719건으로 잡혔다).

    삭제(removed)는 어제 저장본에서 오므로 그때 기록된 요일을 쓴다 —
    오늘 읽은 목록엔 없는 항목이라 지금 요일을 알 방법이 그것뿐이다.
    """
    def _keep(item: dict) -> bool:
        return (item.get("weekday") == weekday
                and item.get("weekday_seq") == 0)

    return {k: [i for i in (changes.get(k) or []) if _keep(i)] for k in _ORDER}


def has_changes(changes: dict) -> bool:
    return any(changes.get(k) for k in _ORDER)


# ──────────────────────────────────────────────────────────────
# ⑤ 오케스트레이션
# ──────────────────────────────────────────────────────────────
def build_report(*, when: Optional[date] = None) -> dict:
    """노션을 읽어 오늘 보고 내용을 만든다. **발송·저장은 하지 않는다**(미리보기 겸용).

    Returns:
        {ok, message, changes, today, weekday, picked, page_url, error}
        picked = 요일 블록을 어떻게 골랐는지 근거(첫 항목·개수) — 눈으로 검증하라고 싣는다.
    """
    when = when or _seoul_now().date()
    try:
        todos = fetch_todos()
    except Exception as e:  # noqa: BLE001 — 화면·로그에 사유를 그대로 보여준다
        logger.exception("노션 읽기 실패")
        return {"ok": False, "error": str(e), "page_url": page_url()}

    snapshot = load_snapshot()
    changes = diff_todos(snapshot.get("todos") or [], todos)
    today = todays_todos(todos, when=when)
    label = weekday_label(when)

    picked = {
        "weekday": label,
        "count": len(today),
        "first_item": (today[0].get("text") if today else None),
        "total_blocks_for_weekday": len(
            {t.get("weekday_seq") for t in todos if t.get("weekday") == label}
        ),
    }
    # 사진과 같은 기준으로 — 오늘 요일 칸 것만 보고한다.
    changes_all = changes
    changes = filter_changes_to_weekday(changes_all, label)
    changed = sum(len(changes.get(k) or []) for k in _ORDER)
    changed_all = sum(len(changes_all.get(k) or []) for k in _ORDER)
    return {
        "ok": True,
        "changed_all": changed_all,
        "photo_message": build_photo_message(today, when=when, changed=changed),
        "change_message": (build_change_message(changes, when=when)
                           if changed else ""),
        "changed_count": changed,
        "changes": changes,
        "today": today,
        "weekday": label,
        "picked": picked,
        "todos": todos,
        "first_run": not (snapshot.get("todos")),
        "page_url": page_url(),
    }


# ──────────────────────────────────────────────────────────────
# 화면용 — 수집을 뒤로 돌리고 마지막 결과를 보여준다
# ──────────────────────────────────────────────────────────────
#   노션 한 바퀴는 블록마다 자식 조회라 수백 번 호출이고, 속도 제한(초당 3회)까지
#   걸려 **몇 분**이 걸린다. 이걸 요청 안에서 그대로 하면 Cloudflare 100초 상한에
#   걸려 화면이 죽는다(524). 그래서 화면은 저장된 마지막 결과만 즉시 보여주고,
#   새로 읽는 일은 백그라운드 스레드로 돌린다.
_LAST_REPORT_FILE = "notion_todo_last_report.json"

# 문구 형식 판 번호. **문구·범위·표식을 바꿀 때마다 올린다.**
#   저장본에 찍어두고 다를 때 「없는 셈」 치면, 코드를 고친 뒤 화면이 스스로
#   「다시 읽어야 한다」고 말한다. 이게 없으면 배포는 됐는데 화면·카톡은 옛 것이
#   그대로 나가고, 사람이 매번 「다시 읽기」를 기억해야 한다(2026-08-02 반복 발생).
REPORT_FORMAT_VERSION = 3
_refresh_lock = threading.Lock()
_refreshing = False


def _last_report_path() -> str:
    if _SNAPSHOT_PATH:   # 테스트: 스냅샷과 같은 폴더에 둔다
        return os.path.join(os.path.dirname(_SNAPSHOT_PATH), _LAST_REPORT_FILE)
    from shared.state_store import state_path

    return state_path(_LAST_REPORT_FILE)


def load_last_report() -> Optional[dict]:
    """마지막으로 수집한 보고 내용. 없거나 형식이 옛 것이면 None.

    ★문구 형식을 바꾼 뒤에도 **바꾸기 전에 저장된 보고서**가 남아 있다. 그걸 그대로
    쓰면 새 코드가 없는 칸을 찾다 터지거나(KeyError), 더 나쁘게는 **옛 형식 그대로
    카톡이 나간다**(2026-08-02 실측 — 시안대로 안 오고 옛 한 통이 왔다).
    없는 셈 치고 「노션 다시 읽기」를 유도하는 편이 정직하다.
    """
    try:
        with open(_last_report_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        logger.exception("last_report 읽기 실패")
        return None
    if not isinstance(data, dict):
        return None
    if data.get("ok"):
        if "photo_message" not in data:
            logger.info("last_report 가 옛 형식(칸 이름) — 다시 읽어야 함")
            return None
        if data.get("format") != REPORT_FORMAT_VERSION:
            logger.info("last_report 판 번호 불일치(%s ≠ %s) — 다시 읽어야 함",
                        data.get("format"), REPORT_FORMAT_VERSION)
            return None
    return data


def _save_last_report(report: dict) -> None:
    slim = {k: v for k, v in report.items() if k != "todos"}
    slim["collected_at"] = _seoul_now().isoformat()
    slim["format"] = REPORT_FORMAT_VERSION
    path = _last_report_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False)
    os.replace(tmp, path)


def is_refreshing() -> bool:
    return _refreshing


def start_refresh() -> bool:
    """백그라운드로 노션을 다시 읽는다. 이미 도는 중이면 False."""
    global _refreshing
    with _refresh_lock:
        if _refreshing:
            return False
        _refreshing = True

    def _work() -> None:
        global _refreshing
        try:
            report = build_report()
            _save_last_report(report)
        except Exception:  # noqa: BLE001 — 스레드가 조용히 죽지 않게 남긴다
            logger.exception("notion_todo 백그라운드 수집 실패")
            try:
                _save_last_report({"ok": False, "error": "수집 중 예외 — 서버 로그 확인"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            _refreshing = False

    threading.Thread(target=_work, name="notion-todo-refresh", daemon=True).start()
    return True


def run_slot_report(slot: str, *, dry_run: bool = False,
                    when: Optional[date] = None) -> dict:
    """등록된 시각 하나에 대한 발송. 하루 여러 번 도는 진입점.

    `run_daily_report` 와 달리 **시각별로** 중복 발송을 막는다 — 하나의 발송일만
    쓰면 그날 첫 회차 뒤 나머지 시각이 전부 막힌다.

    사진(노션 요일 칸 캡처)이 신선하면 붙이고, 없으면 **글만** 보낸다.
    사장님 PC 가 꺼져 있다고 보고 자체가 빠지면 안 된다.
    """
    from lemouton.reports import report_history, report_schedule, shot_store

    when = when or _seoul_now().date()
    day = when.isoformat()

    if not dry_run and report_schedule.already_sent(slot, day):
        logger.info("notion_todo: %s %s 는 이미 발송함 — 건너뜀", day, slot)
        return {"ok": True, "skipped": "already_sent", "slot": slot, "date": day}

    report = build_report(when=when)
    if not report.get("ok"):
        return report
    _save_last_report(report)

    if report.get("first_run"):
        save_snapshot(report["todos"], sent_date=day)
        logger.info("notion_todo: 첫 실행 — 기준선 %d건 저장, 발송 생략",
                    len(report["todos"]))
        return {"ok": True, "skipped": "baseline_saved", "slot": slot,
                "count": len(report["todos"]), "date": day}

    if dry_run:
        report["dry_run"] = True
        return report

    from shared.notifier import send_kakao_memo_detailed

    image_url = shot_store.public_url() or ""

    # ① 사진 통 — 오늘 요일 칸 사진 + 남은 일. 사진이 없으면 글만 나간다.
    # 사진이 있으면 말풍선 탭·첫 버튼 모두 **캡처 원본**으로 — 작은 사진은 잘려 보인다.
    #   사진이 없는 회차(PC 꺼짐)엔 열어봐야 없으니 노션으로 보낸다.
    if image_url:
        photo_link = shot_url()
        photo_buttons = [("캡처 크게 보기", shot_url()),
                         ("노션에서 보기", link_url())]
    else:
        photo_link = link_url()
        photo_buttons = [("노션에서 보기", link_url())]
    first = send_kakao_memo_detailed(
        report["photo_message"], link_url=photo_link,
        buttons=photo_buttons, image_url=image_url)

    # ② 변경 통 — 바뀐 게 있을 때만. 없는데 보내면 알림만 늘고 읽을 게 없다.
    second = None
    if report.get("change_message"):
        second = send_kakao_memo_detailed(
            report["change_message"], link_url=history_url(),
            button_title="변경 이력 전체")

    ok = first["ok"] and (second is None or second["ok"])
    res = {"ok": ok, "photo": first, "change": second,
           "error": (first.get("error") or (second or {}).get("error"))}

    # 이력은 발송 성공 여부와 무관하게 남긴다 — 보낸 것만 기록하면 실패한 날의
    #   변경분이 영영 사라진다.
    report_history.append(slot=slot, changes=report["changes"], sent=ok)

    if ok:
        save_snapshot(report["todos"], sent_date=day)
        report_schedule.mark_sent(slot, day)
    else:
        logger.error("notion_todo: %s 카톡 발송 실패 — %s", slot, res.get("error"))

    report["sent"] = res["ok"]
    report["send_detail"] = {k: v for k, v in res.items() if k != "error"}
    report["had_image"] = bool(image_url)
    return report


def run_daily_report(*, dry_run: bool = False,
                     when: Optional[date] = None) -> dict:
    """옛 진입점 — 시각표의 첫 회차로 위임한다.

    발송 경로가 둘이면 표식·두 통 구성이 한쪽에만 반영돼 조용히 어긋난다.
    실제 로직은 run_slot_report 한 곳에만 둔다.
    """
    from lemouton.reports import report_schedule

    slots = report_schedule.times()
    return run_slot_report(slots[0] if slots else "09:30",
                           dry_run=dry_run, when=when)

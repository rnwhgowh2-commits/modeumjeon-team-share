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
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import requests

logger = logging.getLogger(__name__)

_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

# 「투두리스트 (영빈)」 페이지. 환경변수로 덮어쓸 수 있게 둔다(페이지를 새로 팠을 때).
_DEFAULT_PAGE_ID = "316cf482-7373-806e-882b-f86e9df1cbf2"

_SNAPSHOT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "notion_todo_snapshot.json"
)

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


def page_id() -> str:
    return (os.environ.get("NOTION_TODO_PAGE_ID") or _DEFAULT_PAGE_ID).strip()


def page_url() -> str:
    return f"https://www.notion.so/{page_id().replace('-', '')}"


def _token() -> str:
    return (os.environ.get("NOTION_TOKEN") or "").strip()


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
            edited.append(
                {"id": tid, "before": old.get("text", ""), "after": cur.get("text", "")}
            )

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
        with open(_SNAPSHOT_PATH, encoding="utf-8") as f:
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
    os.makedirs(os.path.dirname(_SNAPSHOT_PATH), exist_ok=True)
    tmp = _SNAPSHOT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, _SNAPSHOT_PATH)


# ──────────────────────────────────────────────────────────────
# ④ 카톡 200자 요약
# ──────────────────────────────────────────────────────────────
def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_message(changes: dict, today: list[dict], *,
                  when: Optional[date] = None, limit: int = 200) -> str:
    """카톡 본문. 상한을 넘지 않게 항목을 줄여가며 채운다.

    머리말(날짜·집계)과 오늘 진행률은 **항상 남기고**, 개별 항목만 잘라낸다.
    항목이 하나도 안 들어가면 집계 숫자만으로도 「뭔가 바뀌었다」는 신호가 된다.
    """
    when = when or _seoul_now().date()
    label = weekday_label(when)[0]

    n_add = len(changes.get("added") or [])
    n_done = len(changes.get("completed") or [])
    n_reopen = len(changes.get("reopened") or [])
    n_removed = len(changes.get("removed") or [])
    n_edited = len(changes.get("edited") or [])

    head = f"[영빈 투두 {when.month}/{when.day}({label})]"
    counts = []
    if n_add:
        counts.append(f"신규 {n_add}")
    if n_done:
        counts.append(f"완료 {n_done}")
    if n_reopen:
        counts.append(f"해제 {n_reopen}")
    if n_removed:
        counts.append(f"삭제 {n_removed}")
    if n_edited:
        counts.append(f"수정 {n_edited}")
    summary = " · ".join(counts) if counts else "변경 없음"

    open_cnt = sum(1 for t in today if not t.get("checked"))
    tail = f"오늘({label}) 남은 일 {open_cnt}건" if today else "오늘 요일 블록 못 찾음"

    lines = [head, summary]
    # 완료를 먼저 — 「무엇이 끝났나」가 사장님이 제일 먼저 볼 정보.
    candidates = (
        [("✅", t.get("text", "")) for t in (changes.get("completed") or [])]
        + [("🆕", t.get("text", "")) for t in (changes.get("added") or [])]
        + [("↩️", t.get("text", "")) for t in (changes.get("reopened") or [])]
    )
    base_len = len("\n".join(lines + [tail]))
    for icon, text in candidates:
        item = f"{icon} {_shorten(text, 30)}"
        if base_len + len(item) + 1 > limit:
            break
        lines.append(item)
        base_len += len(item) + 1
    lines.append(tail)
    return "\n".join(lines)


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
    return {
        "ok": True,
        "message": build_message(changes, today, when=when),
        "changes": changes,
        "today": today,
        "weekday": label,
        "picked": picked,
        "todos": todos,
        "first_run": not (snapshot.get("todos")),
        "page_url": page_url(),
    }


def run_daily_report(*, dry_run: bool = False,
                     when: Optional[date] = None) -> dict:
    """스케줄러가 부르는 진입점. 하루 1건만 나가도록 스냅샷에 발송일을 기록한다.

    Args:
        dry_run — True 면 카톡을 보내지 않고 내용만 돌려준다(스냅샷도 안 건드림).
    """
    when = when or _seoul_now().date()
    today_key = when.isoformat()

    snapshot = load_snapshot()
    if not dry_run and snapshot.get("sent_date") == today_key:
        # 배포로 프로세스가 재기동되면 misfire 보정으로 잡이 한 번 더 뛸 수 있다.
        logger.info("notion_todo: %s 은 이미 발송함 — 건너뜀", today_key)
        return {"ok": True, "skipped": "already_sent", "date": today_key}

    report = build_report(when=when)
    if not report.get("ok"):
        return report
    if dry_run:
        report["dry_run"] = True
        return report

    if report.get("first_run"):
        # 첫 실행은 어제가 없어 전 항목이 「신규」로 잡힌다 — 카톡에 700건이 쏟아지는
        #   대신 기준선만 저장하고 조용히 끝낸다. 다음 날부터 진짜 변경만 나간다.
        save_snapshot(report["todos"], sent_date=today_key)
        logger.info("notion_todo: 첫 실행 — 기준선 %d건 저장, 발송 생략",
                    len(report["todos"]))
        return {"ok": True, "skipped": "baseline_saved",
                "count": len(report["todos"]), "date": today_key}

    from shared.notifier import send_kakao_memo

    sent = send_kakao_memo(
        report["message"], link_url=page_url(), button_title="노션에서 보기"
    )
    # 발송 성공했을 때만 발송일을 찍는다 — 실패했는데 찍으면 그날은 영영 못 보낸다.
    save_snapshot(report["todos"], sent_date=today_key if sent else
                  snapshot.get("sent_date"))
    report["sent"] = sent
    if not sent:
        logger.error("notion_todo: 카톡 발송 실패 — 다음 틱에서 재시도")
    return report

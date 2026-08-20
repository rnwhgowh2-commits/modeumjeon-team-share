# -*- coding: utf-8 -*-
"""전송 작업 기록 — 만들기 · 한 건 적기 · 마무리 · 되짚기.

🔴 이 모듈의 규율은 하나다 — **마켓이 한 말과 우리가 한 말을 섞지 않는다.**
   `record()` 는 마켓 원문을 받는 칸(`market_code`·`market_message`)과 우리 안내
   칸(`our_note`)을 따로 받는다. 한 칸에 합쳐 넣는 길을 아예 열어두지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from lemouton.send.models import (
    FAILURE_KINDS, KIND_LABEL, KIND_MARKET_REJECTED, KIND_NETWORK,
    KIND_NO_REASON_GIVEN, KIND_OK, SendJob, SendJobRow,
)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SendError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패 사유."""


def start_job(session, *, mode: str = 'send', filters: dict | None = None,
              started_by: str = '') -> SendJob:
    """전송 작업을 연다. 호출자가 commit."""
    if mode not in ('send', 'harvest', 'both'):
        raise SendError(f'모르는 작업 방식입니다: {mode}')
    job = SendJob(mode=mode, started_by=(started_by or '').strip() or None,
                  filters_json=json.dumps(filters or {}, ensure_ascii=False))
    session.add(job)
    session.flush()
    return job


def record(session, *, job: SendJob, market: str, kind: str,
           set_id: int | None = None, model_code: str = '',
           account_key: str = 'default', action: str = 'update',
           market_product_id: str = '', market_code: str = '',
           market_message: str = '', our_note: str = '',
           http_status: int | None = None) -> SendJobRow:
    """한 건의 결과를 적는다.

    Args:
        kind: 부류 — **우리가** 붙인다. `models.KIND_*` 중 하나.
        market_code / market_message: **마켓이 준 원문 그대로.**
            🔴 우리가 만든 문장을 여기 넣지 않는다. 넣는 순간 사장님은
              「마켓이 그랬다」고 읽는다.
        our_note: 우리가 덧붙일 말. 마켓 칸과 섞이지 않는다.

    실패인데 마켓이 아무 말도 안 했으면 부류를 :data:`KIND_NO_REASON_GIVEN` 으로
    **바꿔서** 적는다 — 「거부당했다」고만 하고 사유가 비면 화면이 거짓말처럼 보인다.
    """
    if kind not in KIND_LABEL:
        raise SendError(f'모르는 실패 부류입니다: {kind} — '
                        f'쓸 수 있는 것: {", ".join(sorted(KIND_LABEL))}')
    mc = (market_code or '').strip()
    mm = (market_message or '').strip()
    if kind == KIND_MARKET_REJECTED and not (mc or mm):
        kind = KIND_NO_REASON_GIVEN

    row = SendJobRow(job_id=job.id, set_id=set_id,
                     model_code=(model_code or '').strip() or None,
                     market=market, account_key=account_key or 'default',
                     action=action, kind=kind,
                     market_product_id=(market_product_id or '').strip() or None,
                     market_code=mc or None, market_message=mm or None,
                     our_note=(our_note or '').strip() or None,
                     http_status=http_status)
    session.add(row)
    job.total = (job.total or 0) + 1
    if kind in FAILURE_KINDS:
        job.fail_count = (job.fail_count or 0) + 1
    elif kind == KIND_OK:
        job.ok_count = (job.ok_count or 0) + 1
    session.flush()
    return row


def finish_job(session, *, job: SendJob, stopped: bool = False) -> SendJob:
    job.status = 'stopped' if stopped else 'done'
    job.finished_at = _utcnow()
    session.flush()
    return job


# ── 어댑터 결과 → 우리 칸으로 ────────────────────────────────────────────
#
# 어댑터는 마켓 원문을 한 문자열에 담아 준다:
#   adapters/smartstore.py  error=f"{r.error_code}: {r.error_message}"
#   adapters/coupang.py     error=price_result.error_message or "price update failed"
# 그 한 덩어리를 코드/메시지로 **갈라서** 담는다. 못 가르면 통째로 메시지에 넣는다 —
# 억지로 쪼개면 없는 코드를 만들어내게 된다.

#: `CODE: 메시지` 모양만 가른다. 코드는 영문 대문자·숫자·밑줄·점·하이픈만.
_CODE_HEAD = re.compile(r'^([A-Z][A-Z0-9_.\-]{1,39}):\s*(.*)$', re.S)

#: 어댑터가 예외를 문자열로 만든 것 — 마켓 말이 아니라 **우리 쪽 사정**이다.
_OURS = re.compile(r'^(?:[A-Za-z_]*(?:Error|Exception|Timeout)):')


def split_market_error(raw) -> tuple[str, str, bool]:
    """어댑터 `UploadResult.error` → (코드, 메시지, 마켓이_말했나).

    Returns:
        (market_code, market_message, from_market)
        `from_market=False` 면 마켓 말이 아니다 — 우리 쪽 예외거나 빈 값이다.
        호출자는 그걸 `our_note` 에 넣고 마켓 칸은 비워 둬야 한다.
    """
    s = (raw or '').strip() if isinstance(raw, str) else ''
    if not s:
        return ('', '', False)
    if _OURS.match(s):
        return ('', '', False)          # ConnectionError: ... 같은 것 — 우리 쪽 사정
    m = _CODE_HEAD.match(s)
    if m:
        code, msg = m.group(1).strip(), m.group(2).strip()
        # 「코드만 있고 메시지 없음」도 마켓이 말한 것이다.
        return (code, msg, True)
    return ('', s, True)                # 코드를 못 가름 — 통째로 메시지


def record_upload_result(session, *, job: SendJob, result, set_id=None,
                         model_code: str = '', account_key: str = 'default',
                         action: str = 'update', market_product_id: str = ''):
    """어댑터 결과(`UploadResult`)를 그대로 한 줄로 적는다.

    성공이면 OK. 실패면 마켓 말인지 우리 쪽 사정인지 갈라 담는다 —
    갈라 담아야 사장님이 「마켓이 거부했다」와 「연결이 안 됐다」를 구분한다.
    """
    if getattr(result, 'success', False):
        return record(session, job=job, market=result.market, kind=KIND_OK,
                      set_id=set_id, model_code=model_code, account_key=account_key,
                      action=action, market_product_id=market_product_id,
                      http_status=getattr(result, 'http_status', None))

    code, msg, from_market = split_market_error(getattr(result, 'error', None))
    if from_market:
        kind, note = KIND_MARKET_REJECTED, ''
    else:
        # 마켓이 말한 게 아니다 — 원문은 우리 안내 칸에 넣고 마켓 칸은 비운다.
        kind = KIND_NETWORK if getattr(result, 'http_status', None) is None else \
            KIND_NO_REASON_GIVEN
        note = (getattr(result, 'error', '') or '').strip()
        code = msg = ''
    return record(session, job=job, market=result.market, kind=kind,
                  set_id=set_id, model_code=model_code, account_key=account_key,
                  action=action, market_product_id=market_product_id,
                  market_code=code, market_message=msg, our_note=note,
                  http_status=getattr(result, 'http_status', None))


# ── 되짚기 ──────────────────────────────────────────────────────────────

def job_summary(session, job_id: int) -> dict:
    """작업 하나 요약 — 부류별 몇 건인지.

    화면이 「무엇부터 손볼까」를 정하는 데 쓴다. 많은 부류가 위로 온다.
    """
    from sqlalchemy import func
    job = session.get(SendJob, job_id)
    if job is None:
        raise SendError('그런 전송 작업이 없습니다.')
    rows = (session.query(SendJobRow.kind, func.count(SendJobRow.id))
            .filter(SendJobRow.job_id == job_id)
            .group_by(SendJobRow.kind).all())
    by_kind = [{'kind': k, 'label': KIND_LABEL.get(k, (k, ''))[0],
                'how_to_fix': KIND_LABEL.get(k, ('', ''))[1],
                'count': n, 'failed': k in FAILURE_KINDS}
               for k, n in rows]
    by_kind.sort(key=lambda r: (not r['failed'], -r['count']))
    return {'id': job.id, 'mode': job.mode, 'status': job.status,
            'total': job.total, 'ok': job.ok_count, 'fail': job.fail_count,
            'started_at': job.started_at, 'finished_at': job.finished_at,
            'by_kind': by_kind}


def failures(session, job_id: int, *, kind: str = '', limit: int = 200) -> list[dict]:
    """실패한 건들 — 마켓 원문 그대로 실어 준다."""
    q = (session.query(SendJobRow)
         .filter(SendJobRow.job_id == job_id,
                 SendJobRow.kind.in_(list(FAILURE_KINDS))))
    if kind:
        q = q.filter(SendJobRow.kind == kind)
    out = []
    for r in q.order_by(SendJobRow.id).limit(limit).all():
        out.append({
            'set_id': r.set_id, 'model_code': r.model_code,
            'market': r.market, 'account_key': r.account_key,
            'action': r.action, 'market_product_id': r.market_product_id,
            'kind': r.kind, 'kind_label': KIND_LABEL.get(r.kind, (r.kind, ''))[0],
            'how_to_fix': KIND_LABEL.get(r.kind, ('', ''))[1],
            # 🔴 마켓 말과 우리 말을 화면에도 따로 준다.
            'market_code': r.market_code, 'market_message': r.market_message,
            'our_note': r.our_note,
            'reason': r.reason_text,
            'http_status': r.http_status, 'at': r.created_at,
        })
    return out


def recent_jobs(session, limit: int = 20) -> list[dict]:
    rows = (session.query(SendJob).order_by(SendJob.id.desc()).limit(limit).all())
    return [{'id': j.id, 'mode': j.mode, 'status': j.status, 'total': j.total,
             'ok': j.ok_count, 'fail': j.fail_count,
             'started_at': j.started_at, 'finished_at': j.finished_at,
             'started_by': j.started_by} for j in rows]


def last_sent_at(session, *, set_ids: list[int]) -> dict:
    """구성별·마켓별 **마지막으로 보낸 때** — 목록의 「마켓 전송」 칸에 쓴다.

    Returns: `{set_id: {market: datetime}}` (성공한 것만)
    """
    from sqlalchemy import func
    if not set_ids:
        return {}
    rows = (session.query(SendJobRow.set_id, SendJobRow.market,
                          func.max(SendJobRow.created_at))
            .filter(SendJobRow.set_id.in_(set_ids), SendJobRow.kind == KIND_OK)
            .group_by(SendJobRow.set_id, SendJobRow.market).all())
    out: dict = {}
    for sid, mk, at in rows:
        out.setdefault(sid, {})[mk] = at
    return out
